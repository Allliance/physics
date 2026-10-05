"""Run four independent Gemini attempts with the saved Sol benchmark protocols."""

import argparse
import concurrent.futures
import fcntl
import hashlib
import json
import copy
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "benchmarks/hle"))
sys.path.insert(0, str(ROOT / "analysis/CritPt/scripts"))

from eval.datasets import load_dataset as corrected_dataset
from hle_eval.scoring import aggregate_scores, fingerprint
from critpt_eval.dataset import DATASETS, load_dataset, verify_audit_snapshot


def read_json(path, default=None):
    return json.loads(path.read_text()) if path.exists() else default


def write_json(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(value, indent=2) + "\n")
    temporary.replace(path)


def semantic_plan(plan):
    """Worker counts change scheduling, never the attempts or scoring protocol."""
    value = copy.deepcopy(plan)
    for job in value['jobs'].values():
        command = job['command']
        if '--num-workers' in command:
            command[command.index('--num-workers') + 1] = '<runtime-workers>'
    return value


def enabled_plan(directory, plan):
    value = copy.deepcopy(plan)
    disabled = set(read_json(directory / 'disabled-jobs.json', {}).get('jobs', []))
    value['jobs'] = {name: job for name, job in value['jobs'].items() if name not in disabled}
    value['prediction_calls'] = sum(len(job['question_ids']) * 4 for job in value['jobs'].values())
    return value


def retain_judge_budgets(plan, previous):
    """Resume explicit judge budgets saved in a suite's job commands."""
    for name, job in plan['jobs'].items():
        saved = previous['jobs'].get(name, {}).get('command', [])
        flag = '--judge-max-output-tokens'
        if flag in saved:
            budget = int(saved[saved.index(flag) + 1])
            if budget < 1:
                raise ValueError('Saved judge token budget must be positive')
            job['command'] += [flag, str(budget)]


def hle_rows():
    """Use the exact cached HLE snapshot behind Sol's 202-question run."""
    import pyarrow as pa

    manifest = read_json(ROOT / "benchmarks/hle/artifacts/gpt56sol-high-initial-20260906/no_tools.run.json")
    cache = Path.home() / ".cache/huggingface/datasets/cais___hle"
    for path in sorted(cache.rglob("hle-test.arrow")):
        with pa.memory_map(str(path)) as source:
            rows = pa.ipc.open_stream(source).read_all().select(
                ["id", "question", "image", "category", "answer"]).to_pylist()
        rows = [row for row in rows if row["category"].casefold() == "physics" and not row["image"]]
        questions = [{key: row[key] for key in ("id", "question", "image", "category")} for row in rows]
        if ([row["id"] for row in rows] == manifest["question_ids"]
                and fingerprint(questions) == manifest["questions_sha256"]):
            return rows
    raise ValueError("No cached HLE snapshot matches the saved Sol question IDs and text")


def prepare(args):
    directory = args.output_dir.resolve()
    rows = hle_rows()
    corrected, selection = corrected_dataset("hle")
    by_id = {row["id"]: row for row in rows}
    for row in corrected:
        original = by_id.get(row["id"])
        if original is None or original["question"].strip() != row["question"].strip():
            raise ValueError(f"Cannot reuse HLE original prediction for {row['id']}")
    cmt = ROOT / "analysis/CMT-Benchmark"
    clean = cmt / "data/cmt_data_clean.json"
    snapshot = cmt / "artifacts/clean-refresh-20260906/inputs/cmt_data_clean.json"
    if clean.read_bytes() != snapshot.read_bytes():
        raise ValueError("Current CMT corrected data differ from Sol's refreshed corrected snapshot")
    comparison = read_json(cmt / "artifacts/clean-refresh-20260906/comparison.json")
    cmt_ids = list(comparison["results"]["clean_no_tools"]["per_question"])
    if set(cmt_ids) != set(comparison["results"]["clean_tools"]["per_question"]):
        raise ValueError("Sol CMT corrected tool conditions use different IDs")
    critpt_ids = {}
    for split, path in DATASETS.items():
        verify_audit_snapshot(path)
        questions, _, _ = load_dataset(path)
        critpt_ids[split] = [row["id"] for row in questions]
    tag = "gemini-" + hashlib.sha256(str(directory).encode()).hexdigest()[:12]
    jobs = {}
    if args.tools != 'none':
        raise ValueError('Gemini tool-enabled experiments were discarded; use --tools none')
    modes = [False]
    for benchmark in ("hle", "cmt", "critpt"):
        base = ROOT / {"hle": "benchmarks/hle", "cmt": "analysis/CMT-Benchmark",
                       "critpt": "analysis/CritPt"}[benchmark]
        for split in (["original"] if benchmark == "hle" else ["original", "corrected"]):
            for use_tools in modes:
                name = f"{benchmark}-{split}-{'tools' if use_tools else 'no-tools'}"
                output = base / "artifacts" / tag / f"{name}.json"
                script = base / ("scripts/evaluate.py" if benchmark == "critpt" else "evaluate.py")
                command = [sys.executable, "-u", str(script), "--model", "gemini",
                           "--judge-model", "fable", "--judge-reasoning-effort", "high",
                           "--reasoning-effort", "max" if benchmark == "critpt" else "high",
                           "--rounds", "4", "--aggregation", "mean", "--num-workers", str(args.workers),
                           "--timeout", "3600" if benchmark == "critpt" else "1800",
                           "--max-output-tokens", "65536", "--output", str(output),
                           "--use-tools" if use_tools else "--no-use-tools",
                           "--web-search", "live" if use_tools else "disabled"]
                if benchmark == "hle":
                    command += ["--dataset", str(directory / "hle-original.json"), "--no-include-images",
                                "--round-workers", "4", "--limit-policy", "incorrect"]
                    ids = [row["id"] for row in rows]
                elif benchmark == "cmt":
                    command += ["--dataset", str(cmt / "data" / (
                        "cmt_data_original.jsonl" if split == "original" else "cmt_data_clean.json"))]
                    ids = [str(i) for i in range(50)] if split == "original" else cmt_ids
                    if split == "corrected":
                        command += ["--ids-file", str(directory / "cmt-corrected-ids.json")]
                else:
                    command += ["--dataset", split, "--round-workers", "2", "--limit-policy", "incorrect"]
                    ids = critpt_ids[split]
                jobs[name] = {"benchmark": benchmark, "split": split, "use_tools": use_tools,
                              "question_ids": ids, "output": str(output), "command": command}
    plan = {"jobs": jobs, "hle_corrected_ids": selection["retained_ids"],
            "inputs_sha256": {"hle_original": fingerprint(rows), "hle_corrected": fingerprint(corrected),
                              "cmt_original": hashlib.sha256((cmt / "data/cmt_data_original.jsonl").read_bytes()).hexdigest(),
                              "cmt_corrected": hashlib.sha256(clean.read_bytes()).hexdigest(),
                              **{f"critpt_{split}": hashlib.sha256(path.read_bytes()).hexdigest()
                                 for split, path in DATASETS.items()}},
            "prediction_calls": sum(len(job["question_ids"]) * 4 for job in jobs.values()),
            "protocol": {"model": "gemini-3.1-pro-preview", "judge": "claude-fable-5 high",
                         "tools": "Disabled for every Gemini prediction and judgment",
                         "critpt_effort": "requested max; effective high (Gemini's highest level)",
                         "hle_corrected": "Reuse original responses after question identity validation; rejudge against full audit references instead of original short answers",
                         "cmt_corrected": "Same 49 IDs and corrected source as Sol clean-refresh-20260906"}}
    plan = enabled_plan(directory, plan)
    previous = read_json(directory / "jobs.json")
    if previous:
        previous = enabled_plan(directory, previous)
        retain_judge_budgets(plan, previous)
    if previous and semantic_plan(previous) != semantic_plan(plan):
        raise ValueError("Suite settings or inputs changed; choose a new --output-dir")
    write_json(directory / "hle-original.json", rows)
    write_json(directory / "hle-corrected.json", [
        {"id": row["id"], "question": row["question"], "answer": row["reference_answer"],
         "category": "Physics", "image": ""} for row in corrected])
    write_json(directory / "cmt-corrected-ids.json", cmt_ids)
    write_json(directory / "jobs.json", plan)
    return plan


def summarize(directory, plan):
    plan = enabled_plan(directory, plan)
    results = {}
    for name, job in plan["jobs"].items():
        output = Path(job["output"])
        if job["benchmark"] == "critpt":
            row = read_json(output.with_suffix(".summary.json"), {})
        else:
            rounds = []
            for number in range(1, 5):
                suffix = "" if number == 1 else f".round{number}"
                path = output.with_name(f"{output.stem}{suffix}.judged.json")
                rounds.append(read_json(path, {}))
            row = aggregate_scores(job["question_ids"], rounds, "mean")
            if job["benchmark"] == "hle":
                corrected_rounds = []
                for number in range(1, 5):
                    suffix = "" if number == 1 else f".round{number}"
                    corrected_path = output.with_name(output.stem.replace("original", "corrected") + suffix + ".judged.json")
                    corrected_rounds.append(read_json(corrected_path, {}))
                corrected = aggregate_scores(plan["hle_corrected_ids"], corrected_rounds, "mean")
                results[name.replace("original", "corrected")] = metrics(corrected)
        results[name] = metrics(row, len(job["question_ids"]))
    summary = {"complete": all(row["complete"] for row in results.values()), "results": results,
               "planned_prediction_calls": plan["prediction_calls"],
               "planned_judgment_calls": plan["prediction_calls"] + 4 * len(plan["hle_corrected_ids"]) * sum(job["benchmark"] == "hle" for job in plan["jobs"].values()),
               "protocol": plan["protocol"]}
    write_json(directory / "suite-summary.json", summary)
    return summary


def judge_hle_corrected(directory, job):
    """Rejudge the same independent attempts with the corrected full references."""
    from hle_eval import runner
    from hle_eval.scoring import judge_round

    rows = read_json(directory / "hle-corrected.json")
    ids = {row["id"] for row in rows}
    questions = [{key: row[key] for key in ("id", "question", "category", "image")} for row in rows]
    answers = {row["id"]: row["answer"] for row in rows}
    args = runner.parse_args(job["command"][3:])
    # Native round workers share the configured total worker budget.
    args.num_workers = max(1, args.num_workers // 4)
    output = Path(job["output"])

    def judge(number):
        suffix = "" if number == 1 else f".round{number}"
        predictions = read_json(output.with_name(output.stem + suffix + ".json"), {})
        predictions = {qid: prediction for qid, prediction in predictions.items() if qid in ids}
        path = output.with_name(output.stem.replace("original", "corrected") + suffix + ".judged.json")
        return judge_round(args, questions, answers, predictions, path, write_json)

    with concurrent.futures.ThreadPoolExecutor(max_workers=4) as pool:
        list(pool.map(judge, range(1, 5)))


def metrics(row, questions=None):
    complete = bool(row.get("complete"))
    return {"complete": complete, "questions": row.get("questions", questions), "rounds": 4,
            "mean@4": row.get("mean_score") if complete else None,
            "pass@4": row.get("max_score") if complete else None,
            "missing_judgments": row.get("missing_judgments", questions * 4 if questions else None)}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--tools", choices=["none"], default="none")
    parser.add_argument("--workers", type=int, default=8, help="Per-benchmark concurrency; jobs run in parallel")
    parser.add_argument("--stage", choices=["prepare", "all", "summary"], default="all")
    args = parser.parse_args(argv)
    if args.workers < 1:
        parser.error("--workers must be positive")
    directory = args.output_dir.resolve()
    directory.mkdir(parents=True, exist_ok=True)
    lock = (directory / '.repeated.lock').open('w')
    fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
    plan = read_json(directory / "jobs.json") if args.stage == "summary" else prepare(args)
    if not plan:
        raise ValueError("Prepare the suite before summarizing")
    if args.stage == "all":
        def run(item):
            name, job = item
            if name not in enabled_plan(directory, plan)['jobs']:
                return name, 'stopped by user'
            with (directory / f"{name}.log").open("a") as log:
                result = subprocess.run(job["command"], cwd=ROOT, stdout=log, stderr=subprocess.STDOUT)
            if job["benchmark"] == "hle" and name in enabled_plan(directory, plan)['jobs']:
                judge_hle_corrected(directory, job)
            write_json(directory / f"{name}.exit.json", {"returncode": result.returncode})
            return name, result.returncode
        with concurrent.futures.ThreadPoolExecutor(max_workers=len(plan["jobs"])) as pool:
            for future in concurrent.futures.as_completed([pool.submit(run, item) for item in plan["jobs"].items()]):
                print(future.result(), flush=True)
                summarize(directory, plan)
    result = summarize(directory, plan)
    print(json.dumps(result, indent=2), flush=True)
    return 0 if args.stage == "prepare" or result["complete"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
