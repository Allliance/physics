"""Generation, durable caching, judging, and result aggregation."""

from __future__ import annotations

import hashlib
import json
import re
import tempfile
import threading
from base64 import b64decode
from binascii import Error as Base64Error
from concurrent.futures import ThreadPoolExecutor
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .llm import Completion, LLM
from .parsing import (
    detect_part_ids, extract_boxes, map_separated_boxes, parse_json_object, strip_part_label,
)
from .prompts import (
    MERGED_GENERATION_SYSTEM, MERGED_JUDGE_SYSTEM, SEPARATED_GENERATION_SYSTEM,
    SEPARATED_JUDGE_SYSTEM, generation_prompt, merged_judge_prompt, separated_judge_prompt,
)

MERGED_SCHEMA = {
    "type": "object",
    "properties": {
        "parts": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "part": {"type": "string"},
                    "score": {"type": ["integer", "null"], "enum": [0, 1, None]},
                    "reason": {"type": "string"},
                },
                "required": ["part", "score", "reason"],
                "additionalProperties": False,
            },
        },
    },
    "required": ["parts"],
    "additionalProperties": False,
}
SEPARATED_SCHEMA = {
    "type": "object",
    "properties": {"correct": {"type": "boolean"}, "reason": {"type": "string"}},
    "required": ["correct", "reason"],
    "additionalProperties": False,
}


def read_rows(path: Path) -> list[dict[str, Any]]:
    try:
        import pyarrow.parquet as pq
    except ImportError as exc:
        raise RuntimeError("Parquet support requires pyarrow: uv run --with pyarrow python -m eval ...") from exc
    return [normalize_row(row) for row in pq.read_table(path).to_pylist()]


def _json_value(value: Any) -> Any:
    if isinstance(value, str):
        try:
            return json.loads(value)
        except json.JSONDecodeError:
            return value
    return value


_DATA_URL_RE = re.compile(r"^data:(?P<mime>[^;,]+)(?:;[^,]*)*;base64,(?P<data>.*)$", re.S)
_IMAGE_SUFFIXES = {
    "image/gif": ".gif",
    "image/jpeg": ".jpg",
    "image/jpg": ".jpg",
    "image/png": ".png",
    "image/webp": ".webp",
}


def _media_references(value: Any) -> list[str]:
    raw = _json_value(value)
    if raw in (None, "", []):
        return []
    if isinstance(raw, str):
        return [raw]
    if isinstance(raw, dict):
        raw = [raw]
    if not isinstance(raw, list):
        return []

    references: list[str] = []
    for item in raw:
        if isinstance(item, str):
            references.append(item)
            continue
        if not isinstance(item, dict):
            continue
        image_url = item.get("image_url")
        if isinstance(image_url, dict) and isinstance(image_url.get("url"), str):
            references.append(image_url["url"])
        elif isinstance(image_url, str):
            references.append(image_url)
        elif isinstance(item.get("url"), str):
            references.append(item["url"])
        elif isinstance(item.get("path"), str):
            references.append(item["path"])
    return references


def _local_media_candidates(reference: str, dataset: Path) -> list[Path]:
    path = Path(reference).expanduser()
    if path.is_absolute():
        return [path]
    return [
        dataset.parent / path,
        dataset.parent / "images" / path,
        dataset.parent / "figures" / path,
        dataset.parent.parent / "images" / path,
        dataset.parent.parent / "figures" / path,
        Path.cwd() / path,
    ]


def materialize_row_media(row: dict[str, Any], dataset: Path, directory: Path) -> tuple[list[Path], list[str]]:
    """Write row media to image files usable by `codex exec --image`."""
    paths: list[Path] = []
    missing: list[str] = []
    for column in ("graphs", "images"):
        for index, reference in enumerate(_media_references(row.get(column))):
            match = _DATA_URL_RE.match(reference)
            if match:
                mime = match.group("mime").lower()
                suffix = _IMAGE_SUFFIXES.get(mime, ".img")
                path = directory / f"{column}_{index + 1}{suffix}"
                try:
                    path.write_bytes(b64decode(match.group("data"), validate=False))
                except (Base64Error, ValueError) as exc:
                    missing.append(f"{column}[{index}]: invalid data URL ({exc})")
                    continue
                paths.append(path)
                continue

            if reference.startswith(("http://", "https://")):
                missing.append(f"{column}[{index}]: URL media is not supported by codex --image")
                continue

            source = next((candidate for candidate in _local_media_candidates(reference, dataset)
                           if candidate.is_file()), None)
            if source is None:
                missing.append(f"{column}[{index}]: missing local image {reference!r}")
                continue
            paths.append(source)
    return paths, missing


def _media_prompt(prompt: str, image_count: int) -> str:
    if image_count == 0:
        return prompt
    noun = "image" if image_count == 1 else "images"
    return (
        f"{prompt}\n\nAttached media: {image_count} {noun} from the problem's "
        "`graphs`/`images` columns. Use the attached media as part of the problem statement."
    )


def _complete_with_row_media(llm: LLM, prompt: str, *, system_prompt: str,
                             dataset: Path, row: dict[str, Any], include_media: bool,
                             schema: dict[str, Any] | None = None) -> tuple[Completion, int, list[str]]:
    if not include_media:
        return llm.complete(prompt, system_prompt=system_prompt, schema=schema), 0, []
    with tempfile.TemporaryDirectory(prefix="eval-row-media-") as tmpdir:
        image_paths, missing_media = materialize_row_media(row, dataset, Path(tmpdir))
        completion = llm.complete(
            _media_prompt(prompt, len(image_paths)),
            system_prompt=system_prompt,
            schema=schema,
            image_paths=image_paths or None,
        )
    return completion, len(image_paths), missing_media


def normalize_row(row: dict[str, Any]) -> dict[str, Any]:
    """Accept older prepared parquet rows alongside finalized eval rows."""
    normalized = dict(row)
    if "question" not in normalized and "questions" in normalized:
        normalized["question"] = normalized.get("questions")
    if "solution" not in normalized and "solutions" in normalized:
        normalized["solution"] = normalized.get("solutions")
    if "ground_truths" not in normalized and "final_answers" in normalized:
        answers = _json_value(normalized.get("final_answers"))
        if isinstance(answers, list):
            normalized["ground_truths"] = {
                chr(ord("a") + index): answer
                for index, answer in enumerate(answers)
            }
            normalized.setdefault("is_multi_part", len(answers) > 1)
        elif isinstance(answers, dict):
            normalized["ground_truths"] = answers
            normalized.setdefault("is_multi_part", len(answers) > 1)
    return normalized


def load_ground_truths(row: dict[str, Any]) -> dict[str, str]:
    if "ground_truths" not in row or row["ground_truths"] is None:
        raise ValueError(f"Row {row.get('id')!r} has no ground_truths value")
    supplied = _json_value(row["ground_truths"])
    if not isinstance(supplied, dict):
        raise ValueError(f"Row {row.get('id')!r} ground_truths must be a JSON object")
    return {str(part): str(answer) for part, answer in supplied.items() if answer is not None}


def resolve_ground_truth(row: dict[str, Any], parts: list[str]) -> tuple[dict[str, str], str]:
    supplied = load_ground_truths(row)
    missing = [part for part in parts if part not in supplied]
    if missing:
        raise ValueError(f"Row {row.get('id')!r} ground_truths is missing parts: {missing}")
    return {part: str(supplied[part]) for part in parts}, "ground_truths"


def candidate_answers(row: dict[str, Any], response: dict[str, Any],
                      parts: list[str]) -> dict[str, str]:
    """Canonicalize a preserved single sub-question to the dataset's part ``a``."""
    supplied = response.get("extracted_answers", {})
    if not isinstance(supplied, dict):
        return {}
    if row.get("is_multi_part") is False and parts == ["a"] and len(supplied) == 1:
        return {"a": strip_part_label(str(next(iter(supplied.values()))))}
    return {str(part): str(answer) for part, answer in supplied.items()}


def _merged_extracted_answer(response: dict[str, Any]) -> str:
    boxes = response.get("boxes")
    if isinstance(boxes, list):
        return str(boxes[-1]) if boxes else ""
    return str(response.get("extracted_answer") or "")


def _merged_format_errors(response: dict[str, Any]) -> list[str]:
    boxes = response.get("boxes")
    if isinstance(boxes, list):
        return [] if boxes else ["expected at least 1 box, found 0"]
    errors = response.get("format_errors")
    return errors if isinstance(errors, list) else []


def _key(dataset: Path, row: dict[str, Any]) -> str:
    identity = f"{dataset.resolve()}\0{row.get('id')}\0{row.get('question')}"
    return hashlib.sha256(identity.encode()).hexdigest()[:20]


def _attempt_key(row_key: str, attempt: int) -> str:
    if attempt < 1:
        raise ValueError("attempt must be at least 1")
    return row_key if attempt == 1 else f"{row_key}:attempt:{attempt}"


def _load_jsonl(path: Path, key: str = "key") -> dict[str, dict[str, Any]]:
    if not path.exists():
        return {}
    result = {}
    for line in path.read_text().splitlines():
        if line.strip():
            item = json.loads(line)
            result[item[key]] = item
    return result


def _append(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a") as handle:
        handle.write(json.dumps(value, ensure_ascii=False) + "\n")
        handle.flush()


def _valid_merged_score(value: Any) -> bool:
    return value is None or (type(value) is int and value in {0, 1})


def _usage_token_count(item: dict[str, Any], *names: str) -> int:
    usage = item.get("usage") or {}
    for name in names:
        value = usage.get(name)
        if value is not None:
            return int(value or 0)
    return 0


def _judgment_has_reasons(judgment: dict[str, Any], mode: str, parts: list[str]) -> bool:
    per_part = judgment.get("parts")
    if mode == "merged":
        return (
            isinstance(per_part, dict)
            and bool(per_part)
            and all(isinstance(value, dict)
                    and "score" in value
                    and _valid_merged_score(value["score"])
                    and isinstance(value.get("reason"), str)
                    and value["reason"].strip()
                    for value in per_part.values())
        )
    return (
        isinstance(per_part, dict)
        and all(isinstance(per_part.get(part), dict)
                and isinstance(per_part[part].get("reason"), str)
                and per_part[part]["reason"].strip()
                for part in parts)
    )


def _merged_part_results(parsed: dict[str, Any], row: dict[str, Any]) -> dict[str, dict[str, Any]]:
    """Normalize merged judge output."""
    parsed_parts = parsed.get("parts")
    results: dict[str, dict[str, Any]] = {}
    if isinstance(parsed_parts, list):
        for index, item in enumerate(parsed_parts):
            if not isinstance(item, dict):
                continue
            part = str(item.get("part") or "").strip()
            if not part:
                part = "a" if len(parsed_parts) == 1 else str(index + 1)
            if "score" in item and _valid_merged_score(item["score"]):
                score = item["score"]
            else:
                score = 1 if item.get("correct") is True else 0
            if part not in results:
                results[part] = {
                    "score": score,
                    "reason": str(item.get("reason", "")),
                }

    # Tolerate legacy/non-strict JSON if a backend ignores the schema.
    if not results and isinstance(parsed.get("correct"), list):
        returned_correct = [str(part) for part in parsed.get("correct", [])]
        for part in returned_correct:
            results[part] = {
                "score": 1,
                "reason": str(parsed.get("reason", "")),
            }

    if row.get("is_multi_part") is False and results:
        any_result = next(iter(results.values()))
        results = {"a": any_result}
    if not results:
        results = {"a": {"score": None, "reason": "Judge did not return any part judgments."}}
    return results


@dataclass
class GenerationConfig:
    """Model-agnostic generation settings recorded with every evaluation."""

    model: str
    reasoning_effort: str | None = None
    max_tokens: int | None = None
    temperature: float | None = None
    top_p: float | None = None
    top_k: int | None = None
    min_p: float | None = None
    presence_penalty: float | None = None
    repetition_penalty: float | None = None
    extra_body: dict[str, Any] | None = None
    include_media: bool = False

    def cache_tag(self) -> str:
        payload = json.dumps(asdict(self), sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(payload.encode()).hexdigest()[:10]


@dataclass
class RunConfig:
    mode: str
    generation: GenerationConfig
    judge_name: str
    limit: int | None = None
    overwrite: bool = False
    max_workers: int = 32
    judge_reasoning_effort: str | None = None
    judge_max_tokens: int | None = None
    repeat: int = 1


def model_artifact_dir(root: Path, dataset: Path, config: RunConfig) -> Path:
    model = re.sub(r"[^A-Za-z0-9_.-]+", "_", config.generation.model)
    return (root / dataset.parent.name / dataset.stem / config.mode
            / f"model_{model}_gen_{config.generation.cache_tag()}")


def artifact_dir(root: Path, dataset: Path, config: RunConfig) -> Path:
    judge = re.sub(r"[^A-Za-z0-9_.-]+", "_", config.judge_name)
    return model_artifact_dir(root, dataset, config) / f"judge_{judge}"


def run(dataset: Path, output_root: Path, config: RunConfig, generator: LLM, judge: LLM) -> Path:
    if config.mode == "separated":
        raise ValueError("separated mode is deprecated; use merged mode")
    if config.mode != "merged":
        raise ValueError("mode must be merged")
    if config.repeat < 1:
        raise ValueError("repeat must be at least 1")
    all_rows = read_rows(dataset)
    if config.mode == "merged":
        rows = [row for row in all_rows if str(row.get("solution") or "").strip()]
        skipped_no_ground_truth_parts = 0
        skipped_no_reference_solution = len(all_rows) - len(rows)
    else:
        rows = [row for row in all_rows if load_ground_truths(row)]
        skipped_no_ground_truth_parts = len(all_rows) - len(rows)
        skipped_no_reference_solution = 0
    if config.limit is not None:
        rows = rows[:config.limit]
    model_out = model_artifact_dir(output_root, dataset, config)
    out = artifact_dir(output_root, dataset, config)
    model_out.mkdir(parents=True, exist_ok=True)
    out.mkdir(parents=True, exist_ok=True)
    responses_path = model_out / "responses.jsonl"
    judgments_path, failures_path = out / "judgments.jsonl", out / "failures.jsonl"
    if config.overwrite:
        responses_path.unlink(missing_ok=True)
        judgments_path.unlink(missing_ok=True)
        failures_path.unlink(missing_ok=True)
    responses, judgments = _load_jsonl(responses_path), _load_jsonl(judgments_path)
    failures = _load_jsonl(failures_path, key="failure_key")
    gen_system = MERGED_GENERATION_SYSTEM if config.mode == "merged" else SEPARATED_GENERATION_SYSTEM

    write_lock = threading.Lock()

    def process_attempt(task: tuple[dict[str, Any], int]) -> None:
        row, attempt = task
        row_key = _key(dataset, row)
        key = _attempt_key(row_key, attempt)
        if config.mode == "merged":
            parts = []
        else:
            truths = load_ground_truths(row)
            parts = detect_part_ids(truths)
        if key not in responses:
            completion, media_count, missing_media = _complete_with_row_media(
                generator, generation_prompt(row["question"]),
                system_prompt=gen_system, dataset=dataset, row=row,
                include_media=config.generation.include_media,
            )
            boxes = extract_boxes(completion.text)
            record = {
                "key": key, "dataset": str(dataset), "id": row.get("id"), "part_ids": parts,
                "row_key": row_key, "attempt": attempt,
                "response": completion.text, "boxes": boxes, "usage": completion.usage,
                "created_at": datetime.now(timezone.utc).isoformat(),
                "media_count": media_count,
                "missing_media": missing_media,
            }
            if config.mode == "merged":
                record["extracted_answer"] = _merged_extracted_answer(record)
                record["format_errors"] = _merged_format_errors(record)
            else:
                record["extracted_answers"], record["format_errors"] = map_separated_boxes(boxes, parts)
            with write_lock:
                _append(responses_path, record)
                responses[key] = record

        response = responses[key]
        cached_judgment = judgments.get(key)
        if cached_judgment is not None:
            if config.mode == "merged" and _judgment_has_reasons(cached_judgment, config.mode, parts):
                return
            cached_parts = cached_judgment.get("part_ids", [])
            if (config.mode != "merged" and cached_parts == parts
                    and _judgment_has_reasons(cached_judgment, config.mode, parts)):
                return
            if (config.mode != "merged"
                    and set(parts).issubset(cached_parts)
                    and _judgment_has_reasons(cached_judgment, config.mode, parts)):
                filtered = dict(cached_judgment)
                filtered["part_ids"] = parts
                filtered["correct"] = [part for part in cached_judgment.get("correct", []) if part in parts]
                filtered["score"] = len(filtered["correct"]) / len(parts)
                if "parts" in cached_judgment:
                    filtered["parts"] = {part: cached_judgment["parts"][part] for part in parts}
                filtered["row_key"] = row_key
                filtered["attempt"] = attempt
                filtered["created_at"] = datetime.now(timezone.utc).isoformat()
                with write_lock:
                    _append(judgments_path, filtered)
                    judgments[key] = filtered
                return
        if config.mode == "merged":
            failure_key = f"{key}:merged:v2"
            if failure_key in failures:
                return
            try:
                completion, media_count, missing_media = _complete_with_row_media(
                    judge,
                    merged_judge_prompt(row["question"], str(row.get("solution") or ""),
                                        _merged_extracted_answer(response)),
                    system_prompt=MERGED_JUDGE_SYSTEM, schema=MERGED_SCHEMA,
                    dataset=dataset, row=row,
                    include_media=config.generation.include_media,
                )
                parsed = parse_json_object(completion.text)
            except Exception as exc:
                failure = {"failure_key": failure_key, "key": key, "id": row.get("id"),
                           "row_key": row_key, "attempt": attempt, "part": None,
                           "error": f"{type(exc).__name__}: {exc}",
                           "created_at": datetime.now(timezone.utc).isoformat()}
                with write_lock:
                    _append(failures_path, failure)
                    failures[failure_key] = failure
                return
            part_results = _merged_part_results(parsed, row)
            parts = list(part_results)
            scored_parts = [part for part in parts if part_results[part]["score"] is not None]
            correct = [part for part in scored_parts if part_results[part]["score"] == 1]
            score = (sum(part_results[part]["score"] for part in scored_parts) / len(scored_parts)
                     if scored_parts else None)
            per_part = {
                part: {
                    "score": part_results[part]["score"],
                    "reason": str(part_results[part].get("reason", "")),
                    "judge_response": completion.text,
                    "usage": completion.usage,
                }
                for part in parts
            }
            judgment = {"key": key, "id": row.get("id"), "part_ids": parts,
                        "row_key": row_key, "attempt": attempt, "correct": correct,
                        "score": score, "num_scored_parts": len(scored_parts),
                        "num_unscored_parts": len(parts) - len(scored_parts),
                        "judge_response": completion.text, "usage": completion.usage,
                        "parts": per_part, "media_count": media_count,
                        "missing_media": missing_media}
        else:
            truths, provenance = resolve_ground_truth(row, parts)
            answers = candidate_answers(row, response, parts)
            per_part, correct = {}, []
            for part in parts:
                failure_key = f"{key}:{part}"
                try:
                    completion = judge.complete(
                        separated_judge_prompt(row["question"], part, truths[part],
                                               answers.get(part, "")),
                        system_prompt=SEPARATED_JUDGE_SYSTEM, schema=SEPARATED_SCHEMA,
                    )
                    parsed = parse_json_object(completion.text)
                except Exception as exc:
                    failure = {"failure_key": failure_key, "key": key, "id": row.get("id"),
                               "row_key": row_key, "attempt": attempt, "part": part,
                               "error": f"{type(exc).__name__}: {exc}",
                               "created_at": datetime.now(timezone.utc).isoformat()}
                    with write_lock:
                        _append(failures_path, failure)
                        failures[failure_key] = failure
                    return
                is_correct = parsed.get("correct") is True
                if is_correct:
                    correct.append(part)
                per_part[part] = {"correct": is_correct, "reason": str(parsed.get("reason", "")),
                                  "judge_response": completion.text, "usage": completion.usage,
                                  "ground_truth": truths[part]}
                with write_lock:
                    failures.pop(failure_key, None)
            judgment = {"key": key, "id": row.get("id"), "part_ids": parts,
                        "row_key": row_key, "attempt": attempt, "correct": correct,
                        "score": len(correct) / len(parts), "ground_truth_source": provenance,
                        "parts": per_part}
        judgment["judge_reasoning_effort"] = config.judge_reasoning_effort
        judgment["judge_max_tokens"] = config.judge_max_tokens
        judgment["created_at"] = datetime.now(timezone.utc).isoformat()
        with write_lock:
            _append(judgments_path, judgment)
            judgments[key] = judgment

    with ThreadPoolExecutor(max_workers=config.max_workers) as executor:
        tasks = [(row, attempt) for row in rows for attempt in range(1, config.repeat + 1)]
        list(executor.map(process_attempt, tasks))

    selected = [judgments[_key(dataset, row)] for row in rows if _key(dataset, row) in judgments]
    scored_selected = [item for item in selected if item.get("score") is not None]
    selected_attempts = [
        judgments[_attempt_key(_key(dataset, row), attempt)]
        for row in rows for attempt in range(1, config.repeat + 1)
        if _attempt_key(_key(dataset, row), attempt) in judgments
    ]
    selected_responses = [
        responses[_attempt_key(_key(dataset, row), attempt)]
        for row in rows for attempt in range(1, config.repeat + 1)
        if _attempt_key(_key(dataset, row), attempt) in responses
    ]
    first_attempt_responses = [responses[_key(dataset, row)] for row in rows
                               if _key(dataset, row) in responses]
    failed = [failure for failure in failures.values()
              if failure.get("key") in {
                  _attempt_key(_key(dataset, row), attempt)
                  for row in rows for attempt in range(1, config.repeat + 1)
              }]
    prompt_tokens = sum(_usage_token_count(item, "prompt_tokens", "input_tokens")
                        for item in selected_responses)
    completion_tokens = sum(_usage_token_count(item, "completion_tokens", "output_tokens")
                            for item in selected_responses)
    token_cap = config.generation.max_tokens
    summary = {
        "dataset": str(dataset), "mode": config.mode, "generator": config.generation.model,
        "judge": config.judge_name, "repeat": config.repeat,
        "num_rows": len(selected), "num_attempts": len(selected_attempts),
        "num_skipped_no_ground_truth_parts": skipped_no_ground_truth_parts,
        "num_skipped_no_reference_solution": skipped_no_reference_solution,
        "num_failed_judgments": len(failed),
        "mean_score": (sum(x["score"] for x in scored_selected) / len(scored_selected)
                       if scored_selected else None),
        "num_unscored_rows": len(selected) - len(scored_selected),
        "format_error_rows": sum(bool(_merged_format_errors(item) if config.mode == "merged"
                                      else item.get("format_errors"))
                                 for item in first_attempt_responses),
        "format_error_attempts": sum(bool(_merged_format_errors(item) if config.mode == "merged"
                                          else item.get("format_errors"))
                                     for item in selected_responses),
        "empty_final_rows": sum(not item.get("response") for item in first_attempt_responses),
        "empty_final_attempts": sum(not item.get("response") for item in selected_responses),
        "media_rows": sum((item.get("media_count") or 0) > 0 for item in first_attempt_responses),
        "media_attempts": sum((item.get("media_count") or 0) > 0 for item in selected_responses),
        "missing_media_rows": sum(bool(item.get("missing_media")) for item in first_attempt_responses),
        "missing_media_attempts": sum(bool(item.get("missing_media")) for item in selected_responses),
        "rows_at_token_cap": (sum(
            ((item.get("usage") or {}).get("completion_tokens", 0) or 0) >= token_cap
            for item in first_attempt_responses) if token_cap is not None else None),
        "attempts_at_token_cap": (sum(
            ((item.get("usage") or {}).get("completion_tokens", 0) or 0) >= token_cap
            for item in selected_responses) if token_cap is not None else None),
        "generator_prompt_tokens": prompt_tokens,
        "generator_completion_tokens": completion_tokens,
        "generator_total_tokens": prompt_tokens + completion_tokens,
        "created_at": datetime.now(timezone.utc).isoformat(),
    }
    if config.repeat > 1:
        per_row_mean_scores, per_row_best_scores = [], []
        for row in rows:
            scores = []
            for attempt in range(1, config.repeat + 1):
                judgment = judgments.get(_attempt_key(_key(dataset, row), attempt))
                if judgment is None or judgment.get("score") is None:
                    break
                scores.append(judgment["score"])
            if len(scores) == config.repeat:
                per_row_mean_scores.append(sum(scores) / len(scores))
                per_row_best_scores.append(max(scores))
        mean_at_k = (sum(per_row_mean_scores) / len(per_row_mean_scores)
                     if per_row_mean_scores else None)
        best_at_k = (sum(per_row_best_scores) / len(per_row_best_scores)
                     if per_row_best_scores else None)
        summary[f"mean@{config.repeat}"] = mean_at_k
        summary[f"best@{config.repeat}"] = best_at_k
        summary[f"mean_at_{config.repeat}"] = mean_at_k
        summary[f"best_at_{config.repeat}"] = best_at_k
        summary[f"num_rows_with_all_{config.repeat}_attempts_scored"] = len(per_row_mean_scores)
        summary[f"num_rows_missing_{config.repeat}_attempt_scores"] = len(rows) - len(per_row_mean_scores)
    (out / "summary.json").write_text(json.dumps(summary, indent=2) + "\n")
    (out / "run_config.json").write_text(json.dumps(asdict(config), indent=2) + "\n")
    return out
