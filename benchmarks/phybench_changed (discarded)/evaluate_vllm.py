#!/usr/bin/env python3
"""Evaluate an OpenAI-compatible vLLM server on answer-bearing PHYBench rows."""

from __future__ import annotations

import argparse
import json
import re
import threading
import time
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


BENCHMARK_ROOT = Path(__file__).resolve().parent
DATASET_REVISION = "0da5232022d6036ec3ff63e031e3afd9f998f5a1"
DATASET_SHA256 = "a01955ffb2ff86d7833770d3d9f308e3bc1b0e2fea92c5092c4e68a619048a6b"
DATASET_PATH = BENCHMARK_ROOT / "data" / "PHYBench-fullques_v1.json"

import sys

sys.path.insert(0, str(BENCHMARK_ROOT / "EED"))
from EED import EED  # noqa: E402


FINAL_ONLY_SYSTEM_PROMPT = """Solve the supplied physics problem yourself without tools, files, web search, or external context.
Return only the final symbolic answer requested by the problem. Do not include a derivation, explanation,
units unless the problem requests them, a box, or surrounding prose. Use LaTeX notation."""
THINKING_SYSTEM_PROMPT = """Solve the supplied physics problem yourself without tools, files, web search, or external context.
Think carefully in the model's reasoning section. After reasoning, return only the final symbolic answer
using the required response schema. Do not repeat the derivation outside the reasoning section."""
ANSWER_SCHEMA = {
    "type": "object",
    "properties": {"final_answer": {"type": "string"}},
    "required": ["final_answer"],
    "additionalProperties": False,
}


@dataclass(frozen=True)
class Config:
    model: str
    base_url: str
    samples: int
    max_workers: int
    timeout: float
    max_tokens: int
    temperature: float
    top_p: float
    top_k: int
    min_p: float
    presence_penalty: float
    repetition_penalty: float
    enable_thinking: bool = False
    thinking_token_budget: int | None = None
    use_response_schema: bool = True


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()
            if line.strip()]


def append_jsonl(path: Path, item: dict[str, Any], lock: threading.Lock) -> None:
    with lock, path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(item, ensure_ascii=False) + "\n")
        handle.flush()


def load_rows(limit: int | None = None) -> list[dict[str, Any]]:
    rows = json.loads(DATASET_PATH.read_text(encoding="utf-8"))
    rows = [row for row in rows if row.get("content") and row.get("answer")]
    return rows if limit is None else rows[:limit]


def endpoint(base_url: str) -> str:
    base_url = base_url.rstrip("/")
    return (f"{base_url}/chat/completions" if base_url.endswith("/v1")
            else f"{base_url}/v1/chat/completions")


def parse_final_answer(content: str) -> str:
    content = content.strip()
    try:
        parsed = json.loads(content)
        if isinstance(parsed, dict) and isinstance(parsed.get("final_answer"), str):
            return parsed["final_answer"].strip()
    except json.JSONDecodeError:
        pass
    match = re.search(r'"final_answer"\s*:\s*"((?:\\.|[^"\\])*)"', content, re.DOTALL)
    if match:
        try:
            return json.loads(f'"{match.group(1)}"').strip()
        except json.JSONDecodeError:
            pass
    content = re.sub(r"^```(?:json|latex|tex)?\s*", "", content, flags=re.IGNORECASE)
    return re.sub(r"\s*```$", "", content).strip()


def extract_last_box(content: str) -> str:
    boxes = []
    start = 0
    marker = "\\boxed{"
    while True:
        index = content.find(marker, start)
        if index < 0:
            break
        depth = 1
        cursor = index + len(marker)
        escaped = False
        while cursor < len(content):
            character = content[cursor]
            if escaped:
                escaped = False
            elif character == "\\":
                escaped = True
            elif character == "{":
                depth += 1
            elif character == "}":
                depth -= 1
                if depth == 0:
                    boxes.append(content[index + len(marker):cursor].strip())
                    start = cursor + 1
                    break
            cursor += 1
        else:
            break
    return boxes[-1] if boxes else ""


def request_generation(row: dict[str, Any], sample: int, config: Config,
                       attempts: int = 5) -> dict[str, Any]:
    payload = {
        "model": config.model,
        "messages": [
            {"role": "system", "content": (THINKING_SYSTEM_PROMPT if config.enable_thinking
                                             else FINAL_ONLY_SYSTEM_PROMPT)},
            {"role": "user", "content": row["content"]},
        ],
        "max_tokens": config.max_tokens,
        "temperature": config.temperature,
        "top_p": config.top_p,
        "top_k": config.top_k,
        "min_p": config.min_p,
        "presence_penalty": config.presence_penalty,
        "repetition_penalty": config.repetition_penalty,
        "chat_template_kwargs": {"enable_thinking": config.enable_thinking},
    }
    if config.use_response_schema:
        payload["response_format"] = {
            "type": "json_schema",
            "json_schema": {
                "name": "phybench_answer",
                "strict": True,
                "schema": ANSWER_SCHEMA,
            },
        }
    if config.enable_thinking and config.thinking_token_budget is not None:
        payload["thinking_token_budget"] = config.thinking_token_budget
    body = json.dumps(payload).encode()
    last_error = ""
    for request_attempt in range(1, attempts + 1):
        request = urllib.request.Request(
            endpoint(config.base_url), data=body, method="POST",
            headers={"Authorization": "Bearer EMPTY", "Content-Type": "application/json"},
        )
        try:
            with urllib.request.urlopen(request, timeout=config.timeout) as response:
                raw = json.load(response)
            message = raw["choices"][0]["message"]
            content = message.get("content") or ""
            final_answer = parse_final_answer(content)
            if not config.use_response_schema:
                final_answer = extract_last_box(content) or final_answer
            format_error = None
            if not final_answer:
                raise ValueError("empty final answer")
            return {
                "id": str(row["id"]),
                "sample": sample,
                "tag": row["tag"],
                "final_answer": final_answer,
                "content": content,
                "reasoning": message.get("reasoning") or message.get("reasoning_content"),
                "format_error": format_error,
                "finish_reason": raw["choices"][0].get("finish_reason"),
                "usage": raw.get("usage") or {},
                "request_attempts": request_attempt,
                "created_at": utc_now(),
            }
        except urllib.error.HTTPError as exc:
            last_error = f"HTTP {exc.code}: {exc.read().decode(errors='replace')}"
        except (urllib.error.URLError, TimeoutError, json.JSONDecodeError,
                KeyError, IndexError, ValueError) as exc:
            last_error = repr(exc)
        if request_attempt < attempts:
            time.sleep(min(2 ** (request_attempt - 1), 8))
    raise RuntimeError(f"row {row['id']} sample {sample} failed: {last_error}")


def normalize_latex(value: str) -> str:
    value = value.strip()
    for opening, closing in (("\\[", "\\]"), ("$$", "$$"), ("$", "$")):
        if value.startswith(opening) and value.endswith(closing):
            value = value[len(opening):-len(closing)].strip()
            break
    if value.startswith("\\boxed{") and value.endswith("}"):
        value = value[len("\\boxed{"):-1].strip()
    return value.replace("\\left", "").replace("\\right", "").strip()


def score_generation(row: dict[str, Any], generation: dict[str, Any]) -> dict[str, Any]:
    normalized = normalize_latex(generation["final_answer"])
    try:
        eed_score, relative_distance, tree_size, distance = EED(row["answer"], normalized)
        score_error = None
    except Exception as exc:  # The released parser rejects some malformed model LaTeX.
        eed_score, relative_distance, tree_size, distance = 0.0, 1.0, 0.0, 0.0
        score_error = repr(exc)
    return {
        "id": str(row["id"]),
        "sample": generation["sample"],
        "tag": row["tag"],
        "reference_answer": row["answer"],
        "final_answer": generation["final_answer"],
        "normalized_final_answer": normalized,
        "eed_score": float(eed_score),
        "relative_distance": float(relative_distance),
        "tree_size": float(tree_size),
        "distance": float(distance),
        "success": bool(eed_score == 100),
        "score_error": score_error,
        "created_at": utc_now(),
    }


def summarize(rows: list[dict[str, Any]], generations: list[dict[str, Any]],
              scores: list[dict[str, Any]], config: Config) -> dict[str, Any]:
    by_problem: dict[str, list[dict[str, Any]]] = {str(row["id"]): [] for row in rows}
    for item in scores:
        if item["id"] in by_problem:
            by_problem[item["id"]].append(item)
    solved = {item_id for item_id, values in by_problem.items()
              if any(item["success"] for item in values)}
    sample_metrics = {}
    for sample in range(1, config.samples + 1):
        values = [item for item in scores if item["sample"] == sample]
        sample_metrics[str(sample)] = {
            "completed": len(values),
            "exact": sum(item["success"] for item in values),
            "accuracy": (sum(item["success"] for item in values) / len(values)
                         if values else None),
            "mean_eed": (sum(item["eed_score"] for item in values) / len(values)
                         if values else None),
        }
    by_tag = {}
    for tag in sorted({row["tag"] for row in rows}):
        ids = {str(row["id"]) for row in rows if row["tag"] == tag}
        values = [item for item in scores if item["id"] in ids]
        best = [max((item["eed_score"] for item in by_problem[item_id]), default=0.0)
                for item_id in ids]
        by_tag[tag] = {
            "total": len(ids),
            f"pass_at_{config.samples}": len(ids & solved) / len(ids),
            "mean_best_eed": sum(best) / len(best),
        }
    best_scores = [max((item["eed_score"] for item in values), default=0.0)
                   for values in by_problem.values()]
    usage_fields = ("prompt_tokens", "completion_tokens", "total_tokens")
    usage = {field: sum(int(item.get("usage", {}).get(field) or 0)
                        for item in generations) for field in usage_fields}
    return {
        "benchmark": "Eureka-Lab/PHYBench text-only answer-bearing split",
        "dataset_revision": DATASET_REVISION,
        "dataset_sha256": DATASET_SHA256,
        "config": asdict(config),
        "evaluation": "Authors' EED implementation; exact success iff EED score == 100.",
        "sampling_policy": f"{config.samples} independent samples per problem, launched concurrently.",
        "total_problems": len(rows),
        "expected_requests": len(rows) * config.samples,
        "completed_requests": len(scores),
        "solved": len(solved),
        f"pass_at_{config.samples}": len(solved) / len(rows),
        "mean_best_eed": sum(best_scores) / len(best_scores),
        "per_sample": sample_metrics,
        "by_tag": by_tag,
        "score_error_count": sum(item["score_error"] is not None for item in scores),
        "format_error_count": sum(bool(item.get("format_error")) for item in generations),
        "length_capped_count": sum(item.get("finish_reason") == "length" for item in generations),
        "usage": usage,
        "unsolved_ids": sorted(set(by_problem) - solved, key=int),
        "updated_at": utc_now(),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-url", default="http://127.0.0.1:8000/v1")
    parser.add_argument("--model", default="Qwen/Qwen3.5-9B")
    parser.add_argument("--samples", type=int, default=1)
    parser.add_argument("--max-workers", type=int, default=1024)
    parser.add_argument("--timeout", type=float, default=1800)
    parser.add_argument("--max-tokens", type=int, default=8192)
    parser.add_argument("--temperature", type=float, default=1.0)
    parser.add_argument("--top-p", type=float, default=0.95)
    parser.add_argument("--top-k", type=int, default=20)
    parser.add_argument("--min-p", type=float, default=0.0)
    parser.add_argument("--presence-penalty", type=float, default=1.5)
    parser.add_argument("--repetition-penalty", type=float, default=1.0)
    parser.add_argument("--enable-thinking", action="store_true")
    parser.add_argument("--thinking-token-budget", type=int)
    parser.add_argument(
        "--no-response-schema",
        action="store_true",
        help="Request plain text and parse it locally instead of using guided JSON decoding.",
    )
    parser.add_argument(
        "--exclude-ids",
        default="",
        help="Comma-separated problem IDs to exclude before generation and scoring.",
    )
    parser.add_argument("--limit", type=int)
    parser.add_argument("--output-root", type=Path,
                        default=BENCHMARK_ROOT / "artifacts" / "qwen3.5-9b-nonthinking-single")
    args = parser.parse_args()
    if args.samples < 1 or args.max_workers < 1:
        parser.error("--samples and --max-workers must be at least 1")
    config = Config(
        model=args.model,
        base_url=args.base_url,
        samples=args.samples,
        max_workers=args.max_workers,
        timeout=args.timeout,
        max_tokens=args.max_tokens,
        temperature=args.temperature,
        top_p=args.top_p,
        top_k=args.top_k,
        min_p=args.min_p,
        presence_penalty=args.presence_penalty,
        repetition_penalty=args.repetition_penalty,
        enable_thinking=args.enable_thinking,
        thinking_token_budget=args.thinking_token_budget,
        use_response_schema=not args.no_response_schema,
    )
    source_rows = load_rows()
    excluded_ids = {value.strip() for value in args.exclude_ids.split(",") if value.strip()}
    source_ids = {str(row["id"]) for row in source_rows}
    unknown_exclusions = excluded_ids - source_ids
    if unknown_exclusions:
        parser.error(f"unknown --exclude-ids: {sorted(unknown_exclusions)}")
    rows = [row for row in source_rows if str(row["id"]) not in excluded_ids]
    if args.limit is not None:
        rows = rows[:args.limit]
    row_by_id = {str(row["id"]): row for row in rows}
    args.output_root.mkdir(parents=True, exist_ok=True)
    (args.output_root / "manifest.json").write_text(
        json.dumps({
            "config": asdict(config),
            "audit_source_rows": len(source_rows),
            "excluded_benchmark_failure_count": len(excluded_ids),
            "excluded_benchmark_failure_ids": sorted(excluded_ids, key=int),
            "evaluated_ids": [str(row["id"]) for row in rows],
        }, indent=2) + "\n",
        encoding="utf-8",
    )
    generation_path = args.output_root / "generations.jsonl"
    failure_path = args.output_root / "failures.jsonl"
    score_path = args.output_root / "scores.jsonl"
    existing = {(item["id"], item["sample"]): item for item in read_jsonl(generation_path)}
    lock = threading.Lock()
    tasks = [(row, sample) for row in rows for sample in range(1, args.samples + 1)
             if (str(row["id"]), sample) not in existing]
    print(f"launching {len(tasks)} missing requests with max_workers={args.max_workers}", flush=True)
    failures = []
    with ThreadPoolExecutor(max_workers=args.max_workers) as pool:
        futures = {pool.submit(request_generation, row, sample, config):
                   (str(row["id"]), sample) for row, sample in tasks}
        for completed, future in enumerate(as_completed(futures), start=1):
            key = futures[future]
            try:
                item = future.result()
                existing[key] = item
                append_jsonl(generation_path, item, lock)
            except Exception as exc:
                failure = {"id": key[0], "sample": key[1], "error": repr(exc),
                           "created_at": utc_now()}
                failures.append(failure)
                append_jsonl(failure_path, failure, lock)
            if completed % 25 == 0 or completed == len(futures):
                print(f"completed {completed}/{len(futures)} requests; failures={len(failures)}",
                      flush=True)

    scores = []
    for key in sorted(existing, key=lambda value: (int(value[0]), value[1])):
        if key[0] not in row_by_id:
            continue
        scores.append(score_generation(row_by_id[key[0]], existing[key]))
    score_path.write_text("".join(json.dumps(item, ensure_ascii=False) + "\n" for item in scores),
                          encoding="utf-8")
    summary = summarize(rows, list(existing.values()), scores, config)
    (args.output_root / "summary.json").write_text(
        json.dumps(summary, indent=2) + "\n", encoding="utf-8"
    )
    print(json.dumps(summary, indent=2), flush=True)
    if failures:
        raise RuntimeError(f"{len(failures)} requests failed after retries; rerun to resume")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
