"""Reproducible, resumable Codex evaluation for the ScalePhysics benchmark."""

from __future__ import annotations

import argparse
import hashlib
import json
import random
import re
import shutil
import sys
import tempfile
import threading
from concurrent.futures import ThreadPoolExecutor
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
if str(REPOSITORY_ROOT) not in sys.path:
    sys.path.insert(0, str(REPOSITORY_ROOT))

from utils.codex_cli import CodexLLM


ROOT = Path(__file__).resolve().parent
DEFAULT_DATASET = ROOT / "data/test.parquet"
DEFAULT_OUTPUT = ROOT / "results"
GENERATOR_SYSTEM = r"""Solve the physics problem without using tools or external sources. Show concise useful reasoning and finish with exactly one \boxed{...} containing every requested final answer. For multipart questions, label all parts inside the single box."""
JUDGE_SYSTEM = """You are a rigorous physics benchmark judge. Decide whether the candidate answer correctly and completely answers every part of the problem. Use the official answer and worked solution as the gold standard. Accept algebraically equivalent forms, equivalent units, and reasonable numerical rounding. Ignore minor presentation issues. A problem is correct only if every requested part is correct. Return only the requested JSON."""
JUDGE_SCHEMA = {
    "type": "object",
    "properties": {"correct": {"type": "boolean"}, "reason": {"type": "string"}},
    "required": ["correct", "reason"],
    "additionalProperties": False,
}


def read_rows(path: Path) -> list[dict[str, Any]]:
    try:
        import pyarrow.parquet as pq
    except ImportError as exc:
        raise RuntimeError("pyarrow is required; run with `uv run --with pyarrow`") from exc
    return pq.read_table(path).to_pylist()


def select_rows(rows: list[dict[str, Any]], sample_size: int, seed: int) -> list[dict[str, Any]]:
    if sample_size < 1:
        raise ValueError("sample size must be positive")
    if sample_size > len(rows):
        raise ValueError(f"sample size {sample_size} exceeds dataset size {len(rows)}")
    return sorted(random.Random(seed).sample(rows, sample_size), key=lambda row: str(row["id"]))


def parse_json_object(text: str) -> dict[str, Any]:
    stripped = text.strip()
    fenced = re.fullmatch(r"```(?:json)?\s*(.*?)\s*```", stripped, re.S)
    if fenced:
        stripped = fenced.group(1)
    value = json.loads(stripped)
    if not isinstance(value, dict):
        raise ValueError("judge response is not a JSON object")
    return value


def row_key(row: dict[str, Any]) -> str:
    return hashlib.sha256(f"{row.get('id')}\0{row.get('question')}".encode()).hexdigest()[:20]


def load_jsonl(path: Path) -> dict[str, dict[str, Any]]:
    if not path.exists():
        return {}
    records = {}
    for line in path.read_text().splitlines():
        if line.strip():
            record = json.loads(line)
            records[record["key"]] = record
    return records


def append_jsonl(path: Path, record: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(record, ensure_ascii=False) + "\n")
        handle.flush()


def judge_prompt(row: dict[str, Any], candidate: str) -> str:
    official = json.dumps(row.get("answer"), ensure_ascii=False)
    return f"""Problem:
{row['question']}

Official final answer(s):
{official}

Official worked solution:
{row['solution']}

Candidate response:
{candidate}

Return JSON with boolean `correct` and a concise `reason`."""


def codex_binary() -> str:
    found = shutil.which("codex")
    local = Path.home() / ".local/bin/codex"
    if found:
        return found
    if local.is_file():
        return str(local)
    raise RuntimeError("codex CLI was not found on PATH or at ~/.local/bin/codex")


@dataclass(frozen=True)
class Config:
    model: str = "gpt-5.6-sol"
    judge_model: str = "gpt-5.6-sol"
    reasoning_effort: str = "high"
    judge_reasoning_effort: str = "high"
    sample_size: int = 100
    seed: int = 5600
    max_workers: int = 16
    timeout: float = 600.0

    @property
    def run_name(self) -> str:
        model = re.sub(r"[^A-Za-z0-9_.-]+", "_", self.model)
        return f"{model}_{self.reasoning_effort}_n{self.sample_size}_seed{self.seed}"


def run(dataset: Path, output_root: Path, config: Config) -> Path:
    all_rows = read_rows(dataset)
    rows = select_rows(all_rows, config.sample_size, config.seed)
    run_dir = output_root / config.run_name
    run_dir.mkdir(parents=True, exist_ok=True)
    manifest = [{"key": row_key(row), "id": row["id"], "dataset_index": index}
                for index, row in enumerate(rows)]
    manifest_path = run_dir / "sample.jsonl"
    content = "".join(json.dumps(item) + "\n" for item in manifest)
    if manifest_path.exists() and manifest_path.read_text() != content:
        raise RuntimeError(f"sample manifest mismatch in {run_dir}")
    if not manifest_path.exists():
        manifest_path.write_text(content)

    responses_path = run_dir / "responses.jsonl"
    judgments_path = run_dir / "judgments.jsonl"
    failures_path = run_dir / "failures.jsonl"
    responses, judgments = load_jsonl(responses_path), load_jsonl(judgments_path)
    lock = threading.Lock()
    binary = codex_binary()

    def make_client(model: str, effort: str) -> CodexLLM:
        return CodexLLM(model=model, model_reasoning_effort=effort,
                        codex_bin=binary, timeout=config.timeout)

    def process(row: dict[str, Any]) -> None:
        key = row_key(row)
        try:
            if key not in responses:
                result = make_client(config.model, config.reasoning_effort).complete(
                    f"Problem:\n{row['question']}", system_prompt=GENERATOR_SYSTEM)
                record = {"key": key, "id": row["id"], "response": result.text,
                          "usage": result.usage,
                          "created_at": datetime.now(timezone.utc).isoformat()}
                with lock:
                    append_jsonl(responses_path, record)
                    responses[key] = record
            if key in judgments:
                return
            with tempfile.NamedTemporaryFile(mode="w", suffix=".json") as schema:
                json.dump(JUDGE_SCHEMA, schema)
                schema.flush()
                result = make_client(config.judge_model, config.judge_reasoning_effort).complete(
                    judge_prompt(row, responses[key]["response"]), system_prompt=JUDGE_SYSTEM,
                    output_schema=Path(schema.name))
            parsed = parse_json_object(result.text)
            record = {"key": key, "id": row["id"], "correct": parsed.get("correct") is True,
                      "reason": str(parsed.get("reason", "")), "judge_response": result.text,
                      "usage": result.usage,
                      "created_at": datetime.now(timezone.utc).isoformat()}
            with lock:
                append_jsonl(judgments_path, record)
                judgments[key] = record
        except Exception as exc:
            with lock:
                append_jsonl(failures_path, {"key": key, "id": row.get("id"),
                    "error": f"{type(exc).__name__}: {exc}",
                    "created_at": datetime.now(timezone.utc).isoformat()})

    with ThreadPoolExecutor(max_workers=config.max_workers) as executor:
        list(executor.map(process, rows))

    selected = [judgments[row_key(row)] for row in rows if row_key(row) in judgments]
    correct = sum(item["correct"] for item in selected)
    summary = {"dataset": str(dataset), "dataset_rows": len(all_rows),
               "sample_size": config.sample_size, "seed": config.seed,
               "model": config.model, "reasoning_effort": config.reasoning_effort,
               "judge_model": config.judge_model,
               "judge_reasoning_effort": config.judge_reasoning_effort,
               "num_responses": sum(row_key(row) in responses for row in rows),
               "num_judged": len(selected), "num_correct": correct,
               "num_incorrect": len(selected) - correct,
               "accuracy": correct / len(selected) if selected else None,
               "created_at": datetime.now(timezone.utc).isoformat()}
    (run_dir / "summary.json").write_text(json.dumps(summary, indent=2) + "\n")
    (run_dir / "run_config.json").write_text(json.dumps(asdict(config), indent=2) + "\n")
    return run_dir


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dataset", type=Path, default=DEFAULT_DATASET)
    parser.add_argument("--output-root", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--model", default="gpt-5.6-sol")
    parser.add_argument("--judge-model", default="gpt-5.6-sol")
    parser.add_argument("--reasoning-effort", default="high")
    parser.add_argument("--judge-reasoning-effort", default="high")
    parser.add_argument("--sample-size", type=int, default=100)
    parser.add_argument("--seed", type=int, default=5600)
    parser.add_argument("--max-workers", type=int, default=16)
    parser.add_argument("--timeout", type=float, default=600.0)
    args = parser.parse_args()
    print(run(args.dataset, args.output_root, Config(
        model=args.model, judge_model=args.judge_model,
        reasoning_effort=args.reasoning_effort,
        judge_reasoning_effort=args.judge_reasoning_effort,
        sample_size=args.sample_size, seed=args.seed,
        max_workers=args.max_workers, timeout=args.timeout)))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
