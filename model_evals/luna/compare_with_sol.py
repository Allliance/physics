#!/usr/bin/env python3
"""Compare Luna's corrected benchmark answers with saved Sol solver runs."""

import csv
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "analysis/CMT-Benchmark"))
sys.path.insert(0, str(ROOT / "analysis/CritPt/scripts"))

from cmt_eval.dataset import load_dataset as load_cmt
from critpt_eval.dataset import load_dataset as load_critpt

TAG = "luna-high-corrected-20260914"
LUNA = ROOT / f"model_evals/luna/runs/{TAG}"
GEMINI = ROOT / "model_evals/gemini/runs/gemini31-20260908"
REPEATED = GEMINI / "repeated"


def read(path):
    return json.loads(Path(path).read_text())


def suffix(round_number):
    return "" if round_number == 1 else f".round{round_number}"


def answer_grade(judgment):
    if not judgment:
        return None
    grade = judgment.get("judgment", judgment.get("judge_response", {}))
    value = grade.get("correct")
    return value == "yes" if value in {"yes", "no"} else None


def collect_pair(rows, answers, luna_prefix, sol_prefix, rounds, sol_configuration,
                 sol_audit=None):
    records = []
    for number in range(1, rounds + 1):
        ext = suffix(number)
        luna_answers = read(luna_prefix.with_name(luna_prefix.name + ext + ".json"))
        luna_judgments = read(luna_prefix.with_name(luna_prefix.name + ext + ".judged.json"))
        sol_answers = read(sol_prefix.with_name(sol_prefix.name + ext + ".json"))
        sol_judgment_path = sol_prefix.with_name(sol_prefix.name + ext + ".judged.json")
        sol_judgments = read(sol_judgment_path) if sol_judgment_path.exists() else {}
        for row in rows:
            qid = row["id"]
            records.append({
                "benchmark": row["benchmark"], "round": number, "id": qid,
                "question": row["question"], "reference_answer": answers[qid],
                "luna_answer": luna_answers[qid]["response"],
                "luna_fable_correct": answer_grade(luna_judgments.get(qid)),
                "sol_answer": sol_answers[qid]["response"],
                "sol_fable_correct": answer_grade(sol_judgments.get(qid)),
                "sol_audit_credit_correct": (sol_audit.get(qid) if sol_audit else None),
                "luna_configuration": "GPT-5.6-Luna High; no tools",
                "sol_configuration": sol_configuration,
            })
    return records


def collect():
    completed = set(read(LUNA / "summary.json").get("completed_benchmarks", []))
    records = []
    audit_results = read(ROOT / "eval/sol-high-audit-credit-results.json")["results"]
    for benchmark in ("phybench", "prism", "ugphysics"):
        if benchmark not in completed:
            continue
        luna_dir = LUNA / benchmark / "frozen-gemini-corrected"
        rows = read(luna_dir / "dataset.json")
        for row in rows:
            row["benchmark"] = benchmark
        answers = {row["id"]: row["reference_answer"] for row in rows}
        luna_predictions = read(luna_dir / "predictions.json")
        luna_judgments = read(luna_dir / "judgments.json")
        sol_dir = ROOT / f"eval/artifacts/sol-high-fable-judge/{benchmark}"
        sol_predictions = read(sol_dir / "predictions.json")
        sol_judgments = read(sol_dir / "judgments.json")
        audit = {row["id"]: bool(row["correct"])
                 for row in audit_results[benchmark]["per_question"]}
        for row in rows:
            qid = row["id"]
            records.append({
                "benchmark": benchmark, "round": 1, "id": qid,
                "question": row["question"], "reference_answer": answers[qid],
                "luna_answer": luna_predictions[qid]["response"],
                "luna_fable_correct": answer_grade(luna_judgments.get(qid)),
                "sol_answer": sol_predictions[qid]["response"],
                "sol_fable_correct": answer_grade(sol_judgments.get(qid)),
                "sol_audit_credit_correct": audit[qid],
                "luna_configuration": "GPT-5.6-Luna High; no tools",
                "sol_configuration": "GPT-5.6-Sol High; no tools",
            })

    if "hle" in completed:
        source = read(REPEATED / "hle-corrected.json")
        rows = [{"id": row["id"], "question": row["question"], "benchmark": "hle"}
                for row in source]
        answers = {row["id"]: row["answer"] for row in source}
        records += collect_pair(
            rows, answers,
            ROOT / f"benchmarks/hle/artifacts/{TAG}/hle-corrected-no-tools",
            ROOT / "benchmarks/hle/artifacts/gpt56sol-high-initial-20260906/no_tools",
            4, "GPT-5.6-Sol High; no tools")

    if "cmt" in completed:
        questions, answers = load_cmt(ROOT / "analysis/CMT-Benchmark/data/cmt_data_clean.json")
        ids = set(read(REPEATED / "cmt-corrected-ids.json"))
        rows = [{**row, "benchmark": "cmt"} for row in questions if row["id"] in ids]
        records += collect_pair(
            rows, answers,
            ROOT / f"analysis/CMT-Benchmark/artifacts/{TAG}/cmt-corrected-no-tools",
            ROOT / "analysis/CMT-Benchmark/artifacts/clean-refresh-20260906/clean_no_tools",
            4, "GPT-5.6-Sol High; no tools")

    if "critpt" in completed:
        sol = ROOT / "analysis/CritPt/artifacts/sol-max-tools-four-rounds-20260907/gpt-5.6-sol-corrected"
        manifest = read(sol.with_suffix(".run.json"))
        questions, answers = load_critpt(Path(manifest["dataset"]))
        ids = set(manifest["question_ids"])
        rows = [{**row, "benchmark": "critpt"} for row in questions if row["id"] in ids]
        records += collect_pair(
            rows, answers,
            ROOT / f"analysis/CritPt/artifacts/{TAG}/critpt-corrected-no-tools",
            sol, 4, "GPT-5.6-Sol Max; tools and live web")
    return records


def score(records, field):
    available = [row[field] for row in records if row[field] is not None]
    yes = sum(available)
    missing = len(records) - len(available)
    return {
        "mean": yes / len(available) if available else None,
        "judged": len(available),
        "correct": yes,
        "full_denominator_bounds": [yes / len(records), (yes + missing) / len(records)],
    }


def summarize(records):
    results = {}
    order = ("phybench", "prism", "ugphysics", "hle", "cmt", "critpt")
    for benchmark in order:
        items = [row for row in records if row["benchmark"] == benchmark]
        if not items:
            continue
        questions = len({row["id"] for row in items})
        repeated = len(items) > questions
        row = {"questions": questions, "attempts": len(items), "repeated": repeated}
        for model, field in (("luna", "luna_fable_correct"),
                             ("sol", "sol_fable_correct"),
                             ("sol_audit_credit", "sol_audit_credit_correct")):
            result = score(items, field)
            if result["judged"]:
                row[model] = result
                if repeated and result["judged"] == len(items):
                    row[model]["pass"] = sum(any(x[field] for x in items if x["id"] == qid)
                                             for qid in {x["id"] for x in items}) / questions
        results[benchmark] = row
    return {"results": results, "rows": len(records)}


def write_report(output, value):
    lines = ["# GPT-5.6-Luna High versus saved GPT-5.6-Sol runs", "",
             "Both models use Fable 5 High judgments. PHYBench through CMT use High reasoning and no tools for both models. The saved CritPt Sol run used Max reasoning with tools and live web, so that row is contextual rather than a controlled comparison.", "",
             "| Benchmark | Metric | Luna | Sol | Luna − Sol |",
             "|---|---|---:|---:|---:|"]
    for benchmark, row in value["results"].items():
        if "luna" not in row or "sol" not in row:
            continue
        metrics = (("mean", "mean@4"), ("pass", "pass@4")) if row["repeated"] else (("mean", "pass@1"),)
        for metric, label in metrics:
            if metric not in row["luna"] or metric not in row["sol"]:
                continue
            luna = row["luna"][metric]
            if metric == "mean" and row["sol"]["judged"] < row["attempts"]:
                low, high = row["sol"]["full_denominator_bounds"]
                lines.append(f"| {benchmark} | {label} | {100*luna:.2f}% | {100*low:.2f}–{100*high:.2f}% | {100*(luna-high):+.2f} to {100*(luna-low):+.2f} pp |")
            else:
                sol = row["sol"][metric]
                lines.append(f"| {benchmark} | {label} | {100*luna:.2f}% | {100*sol:.2f}% | {100*(luna-sol):+.2f} pp |")
    lines += ["", "For the first three benchmarks, the CSV also includes the later expert audit-credit verdict for each saved Sol answer. Direct Fable scores remain the controlled comparison because Luna has not received that extra credit pass.", "",
              "See `luna_vs_sol_answers.csv` for the complete side-by-side answer text and per-attempt verdicts.", ""]
    (output / "MODEL_COMPARISON.md").write_text("\n".join(lines))


def main():
    records = collect()
    output = LUNA
    fields = ["benchmark", "round", "id", "question", "reference_answer", "luna_answer",
              "luna_fable_correct", "sol_answer", "sol_fable_correct",
              "sol_audit_credit_correct", "luna_configuration", "sol_configuration"]
    with (output / "luna_vs_sol_answers.csv").open("w", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=fields)
        writer.writeheader()
        writer.writerows(records)
    value = summarize(records)
    (output / "model_comparison.json").write_text(json.dumps(value, indent=2) + "\n")
    write_report(output, value)
    print(json.dumps(value, indent=2))


if __name__ == "__main__":
    main()
