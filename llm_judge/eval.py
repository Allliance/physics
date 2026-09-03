"""Run an LLM judge over the physics meta-evaluation dataset.

Maintenance: after changing this module, run ``./llm_judge/static_test.sh``.
When a Qwen judge server is available, also run ``static_test.sh --live``; that
100-row accuracy check is a soft regression signal because generation is
nondeterministic.

Examples:
    python3 -m llm_judge.eval --backend codex --model gpt-5.5 --limit 5
    python3 -m llm_judge.eval --backend anthropic --model "Claude Opus 5" --limit 5
    python3 -m llm_judge.eval --backend openai --model my-model \
        --base-url http://localhost:8000/v1 --max-workers 32
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import random
import re
import sys
import tempfile
import time
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Protocol


REPOSITORY_ROOT = Path(__file__).resolve().parent.parent
if str(REPOSITORY_ROOT) not in sys.path:
    sys.path.insert(0, str(REPOSITORY_ROOT))

from llm_judge.prompts import PROMPTS, JudgePrompt, get_prompt  # noqa: E402
from utils.codex_cli import CodexLLM  # noqa: E402


DEFAULT_DATASET = Path(__file__).resolve().parent / "meta_evaluation_dataset.jsonl"
DEFAULT_OUTPUT_DIR = Path(__file__).resolve().parent / "judgements"
JUDGMENT_SCHEMA = {
    "type": "object",
    "properties": {
        "grade": {"type": "integer", "enum": [0, 1]},
        "reason": {"type": "string", "minLength": 1, "maxLength": 1000},
    },
    "required": ["grade", "reason"],
    "additionalProperties": False,
}
JUDGMENT_SCHEMA_FINGERPRINT = hashlib.sha256(
    json.dumps(JUDGMENT_SCHEMA, sort_keys=True, separators=(",", ":")).encode("utf-8")
).hexdigest()[:12]


@dataclass(frozen=True)
class Completion:
    text: str
    usage: dict[str, Any] | None = None


class JudgeClient(Protocol):
    def complete(self, system_prompt: str, user_prompt: str) -> Completion: ...


@dataclass(frozen=True)
class RunConfig:
    backend: str
    model: str
    prompt_name: str
    prompt_fingerprint: str
    response_format: str
    reasoning_effort: str | None = None
    max_tokens: int | None = None
    temperature: float | None = None
    top_p: float | None = None
    extra_body: dict[str, Any] | None = None
    base_url: str | None = None
    schema_fingerprint: str = JUDGMENT_SCHEMA_FINGERPRINT

    @property
    def run_id(self) -> str:
        payload = json.dumps(asdict(self), sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:12]


@dataclass
class OpenAICompatibleJudge:
    model: str
    base_url: str
    api_key: str
    timeout: float
    response_format: str
    reasoning_effort: str | None = None
    max_tokens: int | None = None
    temperature: float | None = None
    top_p: float | None = None
    extra_body: dict[str, Any] | None = None

    def complete(self, system_prompt: str, user_prompt: str) -> Completion:
        body: dict[str, Any] = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
        }
        if self.reasoning_effort is not None:
            body["reasoning_effort"] = self.reasoning_effort
        if self.max_tokens is not None:
            parameter = (
                "max_completion_tokens"
                if self.model.startswith(("gpt-5", "o1", "o3", "o4"))
                else "max_tokens"
            )
            body[parameter] = self.max_tokens
        if self.temperature is not None:
            body["temperature"] = self.temperature
        if self.top_p is not None:
            body["top_p"] = self.top_p
        if self.response_format == "json-schema":
            body["response_format"] = {
                "type": "json_schema",
                "json_schema": {
                    "name": "physics_judgment",
                    "strict": True,
                    "schema": JUDGMENT_SCHEMA,
                },
            }
        elif self.response_format == "json-object":
            body["response_format"] = {"type": "json_object"}
        if self.extra_body:
            body.update(self.extra_body)

        request = urllib.request.Request(
            _chat_completions_url(self.base_url),
            data=json.dumps(body).encode("utf-8"),
            headers={
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json",
            },
            method="POST",
        )
        try:
            with urllib.request.urlopen(request, timeout=self.timeout) as response:
                raw = json.load(response)
        except urllib.error.HTTPError as error:
            detail = error.read().decode("utf-8", errors="replace")
            raise RuntimeError(f"LLM HTTP {error.code}: {detail}") from error

        content = raw["choices"][0]["message"].get("content")
        if isinstance(content, list):
            content = "".join(
                str(part.get("text", "")) for part in content if isinstance(part, dict)
            )
        if not isinstance(content, str) or not content.strip():
            raise ValueError("LLM response did not contain text")
        return Completion(text=content, usage=raw.get("usage"))


@dataclass(frozen=True)
class AnthropicJudge:
    model: str
    base_url: str
    api_key: str
    timeout: float
    response_format: str
    max_tokens: int
    temperature: float | None = None
    top_p: float | None = None
    extra_body: dict[str, Any] | None = None
    api_version: str = "2023-06-01"

    def request_body(self, system_prompt: str, user_prompt: str) -> dict[str, Any]:
        body: dict[str, Any] = {
            "model": self.model,
            "max_tokens": self.max_tokens,
            "system": system_prompt,
            "messages": [{"role": "user", "content": user_prompt}],
        }
        if self.temperature is not None:
            body["temperature"] = self.temperature
        if self.top_p is not None:
            body["top_p"] = self.top_p
        if self.response_format == "json-schema":
            body["output_config"] = {
                "format": {"type": "json_schema", "schema": JUDGMENT_SCHEMA}
            }
        if self.extra_body:
            body.update(self.extra_body)
        return body

    def complete(self, system_prompt: str, user_prompt: str) -> Completion:
        request = urllib.request.Request(
            _anthropic_messages_url(self.base_url),
            data=json.dumps(self.request_body(system_prompt, user_prompt)).encode("utf-8"),
            headers={
                "x-api-key": self.api_key,
                "anthropic-version": self.api_version,
                "Content-Type": "application/json",
                # Some Anthropic-compatible gateways reject urllib's default UA.
                "User-Agent": "llm-judge/1.0",
            },
            method="POST",
        )
        try:
            with urllib.request.urlopen(request, timeout=self.timeout) as response:
                raw = json.load(response)
        except urllib.error.HTTPError as error:
            detail = error.read().decode("utf-8", errors="replace")
            raise RuntimeError(f"Anthropic HTTP {error.code}: {detail}") from error

        content = raw.get("content")
        if not isinstance(content, list):
            raise ValueError("Anthropic response did not contain content blocks")
        text = "".join(
            block.get("text", "")
            for block in content
            if isinstance(block, dict) and block.get("type") == "text"
        )
        if not text.strip():
            usage = raw.get("usage") or {}
            raise ValueError(
                "Anthropic response did not contain text "
                f"(stop_reason={raw.get('stop_reason')!r}, "
                f"output_tokens={usage.get('output_tokens')!r})"
            )
        return Completion(text=text, usage=raw.get("usage"))


@dataclass
class CodexJudge:
    model: str
    timeout: float
    response_format: str
    reasoning_effort: str | None = None

    def complete(self, system_prompt: str, user_prompt: str) -> Completion:
        client = CodexLLM(
            model=self.model,
            model_reasoning_effort=self.reasoning_effort,
            timeout=self.timeout,
        )
        schema_path: Path | None = None
        if self.response_format != "none":
            with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as handle:
                json.dump(JUDGMENT_SCHEMA, handle)
                schema_path = Path(handle.name)
        try:
            result = client.complete(
                user_prompt,
                system_prompt=system_prompt,
                output_schema=schema_path,
            )
        finally:
            if schema_path is not None:
                schema_path.unlink(missing_ok=True)
        return Completion(text=result.text, usage=result.usage)


def _chat_completions_url(base_url: str) -> str:
    base_url = base_url.rstrip("/")
    if base_url.endswith("/chat/completions"):
        return base_url
    if base_url.endswith(("/v1", "/openai")):
        return f"{base_url}/chat/completions"
    return f"{base_url}/v1/chat/completions"


def _anthropic_messages_url(base_url: str) -> str:
    base_url = base_url.rstrip("/")
    if base_url.endswith("/v1/messages"):
        return base_url
    if base_url.endswith("/v1"):
        return f"{base_url}/messages"
    return f"{base_url}/v1/messages"


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.is_file():
        raise ValueError(f"dataset does not exist: {path}")
    rows = []
    with path.open(encoding="utf-8") as handle:
        for line_number, line in enumerate(handle, start=1):
            if not line.strip():
                continue
            try:
                row = json.loads(line)
            except json.JSONDecodeError as error:
                raise ValueError(f"invalid JSON at {path}:{line_number}") from error
            if not isinstance(row, dict):
                raise ValueError(f"expected a JSON object at {path}:{line_number}")
            rows.append(row)
    return rows


def validate_row(row: dict[str, Any]) -> None:
    required_strings = (
        "meta_eval_id",
        "dataset",
        "problem_id",
        "problem_statement",
        "reference_solution",
        "model_response",
    )
    missing = [field for field in required_strings if not isinstance(row.get(field), str)]
    if missing:
        raise ValueError(
            f"row {row.get('meta_eval_id')!r} is missing string field(s): {', '.join(missing)}"
        )
    if type(row.get("final_grade")) is not int or row["final_grade"] not in (0, 1):
        raise ValueError(f"row {row['meta_eval_id']!r} has invalid final_grade")


def select_rows(
    rows: list[dict[str, Any]],
    datasets: set[str] | None,
    limit: int | None,
    sample_size: int | None = None,
    sample_seed: int = 0,
) -> list[dict[str, Any]]:
    for row in rows:
        validate_row(row)
    row_ids = [row["meta_eval_id"] for row in rows]
    if len(set(row_ids)) != len(row_ids):
        raise ValueError("dataset contains duplicate meta_eval_id values")
    selected = [row for row in rows if datasets is None or row["dataset"] in datasets]
    if datasets is not None:
        available = {row["dataset"] for row in rows}
        unknown = datasets - available
        if unknown:
            raise ValueError(f"unknown dataset(s): {', '.join(sorted(unknown))}")
    if limit is not None and sample_size is not None:
        raise ValueError("limit and sample_size are mutually exclusive")
    if limit is not None:
        if limit < 1:
            raise ValueError("limit must be at least 1")
        selected = selected[:limit]
    if sample_size is not None:
        if sample_size < 1:
            raise ValueError("sample_size must be at least 1")
        if sample_size > len(selected):
            raise ValueError(
                f"sample_size {sample_size} exceeds {len(selected)} available rows"
            )
        sampled_indices = sorted(
            random.Random(sample_seed).sample(range(len(selected)), sample_size)
        )
        selected = [selected[index] for index in sampled_indices]
    if not selected:
        raise ValueError("no rows selected")
    return selected


def parse_judgment(text: str) -> tuple[int, str]:
    candidate = text.strip()
    fenced = re.fullmatch(r"```(?:json)?\s*(.*?)\s*```", candidate, flags=re.DOTALL)
    if fenced:
        candidate = fenced.group(1)
    try:
        parsed = json.loads(candidate)
    except json.JSONDecodeError:
        parsed = None
        decoder = json.JSONDecoder()
        for match in re.finditer(r"\{", candidate):
            try:
                parsed, _ = decoder.raw_decode(candidate[match.start() :])
                break
            except json.JSONDecodeError:
                continue
        if parsed is None:
            raise ValueError("judge did not return a JSON object")
    if not isinstance(parsed, dict):
        raise ValueError("judge output must be a JSON object")
    grade = parsed.get("grade")
    reason = parsed.get("reason")
    if type(grade) is not int or grade not in (0, 1):
        raise ValueError("judge grade must be integer 0 or 1")
    if not isinstance(reason, str) or not reason.strip():
        raise ValueError("judge reason must be a non-empty string")
    return grade, reason.strip()


def _load_latest_records(path: Path, run_id: str) -> dict[str, dict[str, Any]]:
    if not path.exists():
        return {}
    records: dict[str, dict[str, Any]] = {}
    with path.open(encoding="utf-8") as handle:
        for line_number, line in enumerate(handle, start=1):
            if not line.strip():
                continue
            try:
                record = json.loads(line)
            except json.JSONDecodeError as error:
                raise ValueError(f"invalid cached JSON at {path}:{line_number}") from error
            if record.get("run_id") != run_id:
                raise ValueError(
                    f"{path} contains a different run configuration; choose another --output"
                )
            judgment_id = record.get("judgment_id")
            if not isinstance(judgment_id, str):
                raise ValueError(f"cached record at {path}:{line_number} has no judgment_id")
            records[judgment_id] = record
    return records


def _successful(record: dict[str, Any] | None) -> bool:
    return bool(
        record
        and record.get("status") == "completed"
        and type(record.get("predicted_grade")) is int
        and record["predicted_grade"] in (0, 1)
    )


def judge_row(
    row: dict[str, Any], client: JudgeClient, prompt: JudgePrompt, config: RunConfig
) -> dict[str, Any]:
    started = time.monotonic()
    base_record = {
        "judgment_id": row["meta_eval_id"],
        "meta_eval_id": row["meta_eval_id"],
        "dataset": row["dataset"],
        "source_index": row.get("source_index"),
        "problem_id": row["problem_id"],
        "final_grade": row["final_grade"],
        "run_id": config.run_id,
        "backend": config.backend,
        "model": config.model,
        "prompt_name": config.prompt_name,
        "prompt_fingerprint": config.prompt_fingerprint,
        "created_at": datetime.now(timezone.utc).isoformat(),
    }
    try:
        system_prompt, user_prompt = prompt.render(row)
        completion = client.complete(system_prompt, user_prompt)
        predicted_grade, reason = parse_judgment(completion.text)
        return {
            **base_record,
            "status": "completed",
            "predicted_grade": predicted_grade,
            "matches_final_grade": predicted_grade == row["final_grade"],
            "reason": reason,
            "judge_response": completion.text,
            "usage": completion.usage,
            "latency_seconds": round(time.monotonic() - started, 3),
        }
    except Exception as error:
        return {
            **base_record,
            "status": "error",
            "error": f"{type(error).__name__}: {error}",
            "latency_seconds": round(time.monotonic() - started, 3),
        }


def classification_metrics(records: list[dict[str, Any]]) -> dict[str, Any]:
    completed = [record for record in records if _successful(record)]
    tp = sum(r["final_grade"] == 1 and r["predicted_grade"] == 1 for r in completed)
    tn = sum(r["final_grade"] == 0 and r["predicted_grade"] == 0 for r in completed)
    fp = sum(r["final_grade"] == 0 and r["predicted_grade"] == 1 for r in completed)
    fn = sum(r["final_grade"] == 1 and r["predicted_grade"] == 0 for r in completed)
    solved_total = tp + fn
    unsolved_total = tn + fp
    accuracy = (tp + tn) / len(completed) if completed else None
    solved_recall = tp / solved_total if solved_total else None
    unsolved_recall = tn / unsolved_total if unsolved_total else None
    balanced_accuracy = (
        (solved_recall + unsolved_recall) / 2
        if solved_recall is not None and unsolved_recall is not None
        else None
    )
    return {
        "num_scored": len(completed),
        "accuracy": accuracy,
        "balanced_accuracy": balanced_accuracy,
        "solved_recall": solved_recall,
        "unsolved_recall": unsolved_recall,
        "confusion_matrix": {
            "true_solved_predicted_solved": tp,
            "true_solved_predicted_unsolved": fn,
            "true_unsolved_predicted_solved": fp,
            "true_unsolved_predicted_unsolved": tn,
        },
    }


def build_summary(
    rows: list[dict[str, Any]],
    records: dict[str, dict[str, Any]],
    config: RunConfig,
    selection: dict[str, Any] | None = None,
) -> dict[str, Any]:
    selected_records = [
        records[row["meta_eval_id"]]
        for row in rows
        if row["meta_eval_id"] in records
    ]
    completed = [record for record in selected_records if _successful(record)]
    by_dataset = {}
    for dataset in sorted({row["dataset"] for row in rows}):
        dataset_records = [record for record in completed if record["dataset"] == dataset]
        by_dataset[dataset] = classification_metrics(dataset_records)
    return {
        "run_id": config.run_id,
        "config": asdict(config),
        "num_selected": len(rows),
        "num_completed": len(completed),
        "num_errors": sum(record.get("status") == "error" for record in selected_records),
        "num_missing": len(rows) - len(selected_records),
        "expected_grade_counts": {
            str(grade): sum(row["final_grade"] == grade for row in rows) for grade in (0, 1)
        },
        "selection": selection,
        "metrics": classification_metrics(completed),
        "metrics_by_dataset": by_dataset,
        "updated_at": datetime.now(timezone.utc).isoformat(),
    }


def default_output_path(config: RunConfig) -> Path:
    model = re.sub(r"[^A-Za-z0-9_.-]+", "_", config.model).strip("_") or "model"
    prompt = re.sub(r"[^A-Za-z0-9_.-]+", "_", config.prompt_name)
    return DEFAULT_OUTPUT_DIR / f"{model}__{prompt}__{config.run_id}.jsonl"


def run_evaluation(
    rows: list[dict[str, Any]],
    client: JudgeClient,
    prompt: JudgePrompt,
    config: RunConfig,
    output_path: Path,
    max_workers: int,
    overwrite: bool = False,
    selection: dict[str, Any] | None = None,
) -> dict[str, Any]:
    if max_workers < 1:
        raise ValueError("max_workers must be at least 1")
    output_path.parent.mkdir(parents=True, exist_ok=True)
    if overwrite:
        output_path.unlink(missing_ok=True)
    records = _load_latest_records(output_path, config.run_id)
    pending = [row for row in rows if not _successful(records.get(row["meta_eval_id"]))]

    if pending:
        with output_path.open("a", encoding="utf-8") as output_handle:
            with ThreadPoolExecutor(max_workers=max_workers) as executor:
                results = executor.map(
                    lambda row: judge_row(row, client, prompt, config), pending
                )
                for index, record in enumerate(results, start=1):
                    output_handle.write(json.dumps(record, ensure_ascii=False) + "\n")
                    output_handle.flush()
                    records[record["judgment_id"]] = record
                    state = "ok" if record["status"] == "completed" else "error"
                    print(
                        f"[{index}/{len(pending)}] {record['judgment_id']}: {state}",
                        file=sys.stderr,
                    )

    summary = build_summary(rows, records, config, selection=selection)
    summary_path = output_path.with_suffix(".summary.json")
    summary_path.write_text(json.dumps(summary, indent=2, ensure_ascii=False) + "\n")
    summary["output_path"] = str(output_path)
    summary["summary_path"] = str(summary_path)
    summary["num_cached"] = len(rows) - len(pending)
    return summary


def _make_client(args: argparse.Namespace) -> JudgeClient:
    if args.backend == "codex":
        unsupported = [
            name
            for name in ("max_tokens", "temperature", "top_p", "extra_body")
            if getattr(args, name) is not None
        ]
        if unsupported:
            options = ", ".join(f"--{name.replace('_', '-')}" for name in unsupported)
            raise ValueError(f"codex backend does not support: {options}")
        return CodexJudge(
            model=args.model,
            timeout=args.timeout,
            response_format=args.response_format,
            reasoning_effort=args.reasoning_effort,
        )
    if args.backend == "anthropic":
        if args.reasoning_effort is not None:
            raise ValueError("anthropic backend does not support --reasoning-effort")
        return AnthropicJudge(
            model=args.model,
            base_url=args.base_url,
            api_key=args.api_key,
            timeout=args.timeout,
            response_format=args.response_format,
            max_tokens=args.max_tokens,
            temperature=args.temperature,
            top_p=args.top_p,
            extra_body=args.extra_body,
        )
    return OpenAICompatibleJudge(
        model=args.model,
        base_url=args.base_url,
        api_key=args.api_key,
        timeout=args.timeout,
        response_format=args.response_format,
        reasoning_effort=args.reasoning_effort,
        max_tokens=args.max_tokens,
        temperature=args.temperature,
        top_p=args.top_p,
        extra_body=args.extra_body,
    )


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dataset-path", type=Path, default=DEFAULT_DATASET)
    parser.add_argument(
        "--dataset",
        dest="datasets",
        action="append",
        help="only judge this source dataset; repeat to select multiple datasets",
    )
    selection_group = parser.add_mutually_exclusive_group()
    selection_group.add_argument(
        "--limit", type=int, help="judge only the first N selected rows"
    )
    selection_group.add_argument(
        "--sample-size", type=int, help="judge a seeded random sample of N rows"
    )
    parser.add_argument(
        "--sample-seed", type=int, default=0, help="random seed for --sample-size"
    )
    parser.add_argument(
        "--backend", choices=("anthropic", "codex", "openai"), default="codex"
    )
    parser.add_argument(
        "--model",
        default=os.getenv("OPENAI_MODEL") or os.getenv("CODEX_LLM_MODEL") or "gpt-5.5",
    )
    parser.add_argument("--prompt", choices=sorted(PROMPTS), default="default")
    parser.add_argument(
        "--base-url",
        help=(
            "provider API base URL; defaults to ANTHROPIC_BASE_URL for anthropic "
            "or OPENAI_BASE_URL for openai"
        ),
    )
    parser.add_argument(
        "--api-key",
        help=(
            "provider API key; defaults to CLAUDE_API_KEY/ANTHROPIC_API_KEY for "
            "anthropic or OPENAI_API_KEY for openai"
        ),
    )
    parser.add_argument("--timeout", type=float, default=300.0)
    parser.add_argument("--max-workers", type=int, default=8)
    parser.add_argument("--reasoning-effort")
    parser.add_argument("--max-tokens", type=int)
    parser.add_argument("--temperature", type=float)
    parser.add_argument("--top-p", type=float)
    parser.add_argument("--extra-body", type=json.loads)
    parser.add_argument(
        "--response-format",
        choices=("json-schema", "json-object", "none"),
        default="json-schema",
    )
    parser.add_argument(
        "--output",
        type=Path,
        help="output JSONL; defaults to judgements/<run>.jsonl",
    )
    parser.add_argument("--overwrite", action="store_true")
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="print the first rendered prompt and configuration without calling a model",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    try:
        if args.backend == "anthropic":
            args.base_url = args.base_url or os.getenv(
                "ANTHROPIC_BASE_URL", "https://api.anthropic.com"
            )
            args.api_key = args.api_key or os.getenv("CLAUDE_API_KEY") or os.getenv(
                "ANTHROPIC_API_KEY"
            )
            args.max_tokens = args.max_tokens or 8192
            if not args.api_key:
                raise ValueError(
                    "anthropic backend requires --api-key, CLAUDE_API_KEY, or "
                    "ANTHROPIC_API_KEY"
                )
        elif args.backend == "openai":
            args.base_url = args.base_url or os.getenv(
                "OPENAI_BASE_URL", "https://api.openai.com/v1"
            )
            args.api_key = args.api_key or os.getenv("OPENAI_API_KEY", "EMPTY")
        prompt = get_prompt(args.prompt)
        rows = select_rows(
            read_jsonl(args.dataset_path.expanduser()),
            set(args.datasets) if args.datasets else None,
            args.limit,
            sample_size=args.sample_size,
            sample_seed=args.sample_seed,
        )
        selection = {
            "method": (
                "random" if args.sample_size is not None else "head" if args.limit else "all"
            ),
            "datasets": sorted(args.datasets) if args.datasets else None,
            "limit": args.limit,
            "sample_size": args.sample_size,
            "sample_seed": args.sample_seed if args.sample_size is not None else None,
            "selected_ids_sha256": hashlib.sha256(
                "\n".join(row["meta_eval_id"] for row in rows).encode("utf-8")
            ).hexdigest(),
        }
        config = RunConfig(
            backend=args.backend,
            model=args.model,
            prompt_name=prompt.name,
            prompt_fingerprint=prompt.fingerprint,
            response_format=args.response_format,
            reasoning_effort=args.reasoning_effort,
            max_tokens=args.max_tokens,
            temperature=args.temperature,
            top_p=args.top_p,
            extra_body=args.extra_body,
            base_url=(
                args.base_url.rstrip("/")
                if args.backend in ("anthropic", "openai")
                else None
            ),
        )
        output_path = args.output.expanduser() if args.output else default_output_path(config)
        if args.output is None and args.sample_size is not None:
            output_path = output_path.with_name(
                f"{output_path.stem}__sample{args.sample_size}-seed{args.sample_seed}.jsonl"
            )
        if args.dry_run:
            system_prompt, user_prompt = prompt.render(rows[0])
            preview = {
                "run_id": config.run_id,
                "config": asdict(config),
                "num_selected": len(rows),
                "selection": selection,
                "output_path": str(output_path),
                "first_meta_eval_id": rows[0]["meta_eval_id"],
                "system_prompt": system_prompt,
                "user_prompt": user_prompt,
            }
            print(json.dumps(preview, indent=2, ensure_ascii=False))
            return 0
        client = _make_client(args)
        summary = run_evaluation(
            rows=rows,
            client=client,
            prompt=prompt,
            config=config,
            output_path=output_path,
            max_workers=args.max_workers,
            overwrite=args.overwrite,
            selection=selection,
        )
    except ValueError as error:
        print(f"error: {error}", file=sys.stderr)
        return 2
    print(json.dumps(summary, indent=2, ensure_ascii=False))
    return 1 if summary["num_errors"] or summary["num_missing"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
