#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import os
import sys
import glob
import json
import argparse
import traceback
import multiprocessing as mp
from typing import Any, Dict, List, Tuple

from tqdm import tqdm

# ---- Shared utilities ----
from Analyze_Label.utils import (
    load_jsonl_objects,
    save_json_object,
    load_json_object,
    to_json_safe,
)
from Analyze_Label.Analysis.sol_error.phrase import parse_error_analysis_output
from Analyze_Label.Analysis.sol_error.prompt import build_error_analysis_prompt
from utils.llm_utils import call_model_api
from utils.prompt_utils import get_problem_context


def _is_jsonl(path: str) -> bool:
    print(path)
    return path.lower().endswith(".jsonl")


def _iter_json_files(path_or_glob: str) -> List[str]:
    """Return concrete file list from a file/dir/glob."""
    if any(ch in path_or_glob for ch in ["*", "?", "["]):
        files = sorted(glob.glob(path_or_glob))
        return [p for p in files if os.path.isfile(p)]

    if os.path.isdir(path_or_glob):
        files = []
        for fname in sorted(os.listdir(path_or_glob)):
            fp = os.path.join(path_or_glob, fname)
            if os.path.isfile(fp) and (fname.lower().endswith(".json") or fname.lower().endswith(".jsonl")):
                files.append(fp)
        return files

    if os.path.isfile(path_or_glob):
        return [path_or_glob]

    raise FileNotFoundError(f"No such file/dir/glob: {path_or_glob}")


def _load_grade_records_from_file(path: str) -> List[Dict[str, Any]]:
    """Load grade dict(s) from JSON/JSONL; normalize to list of records."""
    if _is_jsonl(path):
        records = load_jsonl_objects(path)
        if not isinstance(records, list):
            raise ValueError(f"{path} (jsonl) did not yield a list")
        return records

    obj = load_json_object(path)
    if isinstance(obj, list):
        return obj
    if isinstance(obj, dict):
        return [obj]
    raise ValueError(f"Unsupported JSON structure in {path}; expected list or dict")


def load_all_grade_records(grades_path: str) -> List[Dict[str, Any]]:
    all_records: List[Dict[str, Any]] = []
    for f in _iter_json_files(grades_path):
        try:
            all_records.extend(_load_grade_records_from_file(f))
        except Exception as e:
            print(f"[WARN] Skipping {f}: {e}", file=sys.stderr)
    return all_records


def load_problems_index(raw_problems_path: str) -> Dict[Any, Dict[str, Any]]:
    """Build id->problem index from JSON/JSONL (list of problems, or dict with 'problems'/'items'/'data')."""
    problems: List[Dict[str, Any]] = []
    if _is_jsonl(raw_problems_path):
        problems = load_jsonl_objects(raw_problems_path)
    else:
        obj = load_json_object(raw_problems_path)
        if isinstance(obj, list):
            problems = obj
        elif isinstance(obj, dict):
            for k in ("problems", "items", "data"):
                if k in obj and isinstance(obj[k], list):
                    problems = obj[k]
                    break
            if not problems:
                if isinstance(obj, dict) and "id" in obj:
                    problems = [obj]
                else:
                    raise ValueError("Unrecognized problems JSON structure.")
        else:
            raise ValueError("Unrecognized problems file.")

    idx: Dict[Any, Dict[str, Any]] = {}
    for p in problems:
        if "id" in p:
            idx[str(p["id"])] = p
    return idx


def build_prompt(problem_context: str,
                 student_answer: str,
                 matches: list,
                 score: float) -> str:
    """
    Use your taxonomy prompt (imported as error_analysis_prompt),
    and pass matches JSON string into it.
    """
    matches_str = json.dumps(matches or [], ensure_ascii=False, indent=2)
    return build_error_analysis_prompt(problem_context, student_answer, matches_str, score)


def _append_uncertain_id(uncertain_path: str, pid: Any) -> None:
    """
    Append a problem id to uncertain.json (as a unique list of ids).
    """
    os.makedirs(os.path.dirname(uncertain_path), exist_ok=True)
    data: List[Any] = []
    if os.path.exists(uncertain_path):
        try:
            obj = load_json_object(uncertain_path)
            if isinstance(obj, list):
                data = obj
        except Exception:
            # If file corrupted, we will overwrite with a new list that includes pid
            data = []

    if pid not in data:
        data.append(pid)

    # Save as a compact list
    with open(uncertain_path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def _call_and_parse(model_name: str, prompt: str) -> Dict[str, Any]:
    """
    Call the model and parse with parse_error_analysis_output.
    Return dict (parsed) or {"ok": False, ...} on failure.
    """
    try:
        res = call_model_api(model_name=model_name, context=prompt)
    except Exception as e:
        return {
            "ok": False,
            "summary": f"LLM call failed: {e}",
            "primary_error": "Uncertain",
            "secondary_errors": [],
            "incorrect_expressions": [],
            "related_correct_expressions": [],
            "unit_dimension_status": "unknown",
            "assumption_mismatch": "unknown",
            "rationale": "Model call failed; no analysis produced.",
            "confidence": 0.0,
        }

    try:
        parsed = parse_error_analysis_output(res)
        if isinstance(parsed, dict):
            return to_json_safe(parsed)  # expected to contain "ok", "primary_error", etc.
        else:
            return {
                "ok": False,
                "summary": "Parser returned non-dict.",
                "raw_text": res,
                "primary_error": "Uncertain",
                "secondary_errors": [],
            }
    except Exception as e:
        return {
            "ok": False,
            "summary": f"Parse failed: {e}",
            "raw_text": res,
            "primary_error": "Uncertain",
            "secondary_errors": [],
        }


def analyze_one(record: Dict[str, Any],
                problems_by_id: Dict[Any, Dict[str, Any]],
                outdir: str,
                model_name: str,
                overwrite: bool,
                max_retries: int,
                uncertain_path: str) -> Tuple[Any, str]:
    """
    Process a single grade record.
    Writes: {outdir}/diff_<problem_id>.json
    If final primary_error == "Uncertain" after retries, appends id to uncertain.json.
    """
    pid_raw = record.get("problem_id")
    if pid_raw is None:
        return (pid_raw, "skip:no-problem_id")

    out_path = os.path.join(outdir, f"diff_{pid_raw}.json")
    if (not overwrite) and os.path.exists(out_path):
        try:
            load_json_object(out_path)
            return (pid_raw, "skip:exists")
        except Exception:
            pass  # corrupted file; proceed
    pid = str(pid_raw).strip()
    problem = problems_by_id.get(pid)
    if problem is None:
        stub = {
            "ok": False,
            "summary": f"Problem id {pid} not found in raw problems.",
            "primary_error": "Uncertain",
            "secondary_errors": [],
            "incorrect_expressions": [],
            "related_correct_expressions": [],
            "unit_dimension_status": "unknown",
            "assumption_mismatch": "unknown",
            "rationale": "Problem not found; cannot analyze.",
            "confidence": 0.0,
        }
        save_json_object(out_path, to_json_safe(stub))
        _append_uncertain_id(uncertain_path, pid)
        return (pid, "error:problem-not-found")

    try:
        problem_context = get_problem_context(problem)
    except Exception as e:
        stub = {
            "ok": False,
            "summary": f"get_problem_context failed: {e}",
            "primary_error": "Uncertain",
            "secondary_errors": [],
            "incorrect_expressions": [],
            "related_correct_expressions": [],
            "unit_dimension_status": "unknown",
            "assumption_mismatch": "unknown",
            "rationale": "Problem context construction failed.",
            "confidence": 0.0,
        }
        save_json_object(out_path, to_json_safe(stub))
        _append_uncertain_id(uncertain_path, pid)
        return (pid, "error:context-failed")

    student_answer = record.get("answer", "") or ""
    matches = record.get("matches", []) or []
    score = float(record.get("score", 0.0))
    if score == 1.0:
        # 满分题直接跳过
        return pid, "ok"

    prompt = build_prompt(problem_context, student_answer, matches, score)

    # Retry loop for Uncertain
    attempt = 0
    final_clean: Dict[str, Any] = {}
    status = "ok"

    while attempt < max_retries:
        attempt += 1
        clean = _call_and_parse(model_name, prompt)

        # Persist each attempt? — 保留最后一次的（成功或失败）
        final_clean = clean

        primary = (clean or {}).get("primary_error")
        ok_flag = bool((clean or {}).get("ok", True))  # 如果解析器没加 ok，就默认 True

        if primary and primary != "Uncertain" and ok_flag:
            status = f"ok@{attempt}"
            break

        # 若解析失败但返回里没有 primary_error，也继续重试
        status = f"uncertain@{attempt}"

    # 保存最终结果
    save_json_object(out_path, to_json_safe(final_clean))

    # 若仍为不确定，记入 uncertain.json
    if (final_clean or {}).get("primary_error") == "Uncertain":
        _append_uncertain_id(uncertain_path, pid)
        return (pid, f"uncertain_final_after_{attempt}")

    return (pid, status)


def worker(rank: int,
           shard: List[Dict[str, Any]],
           problems_by_id: Dict[Any, Dict[str, Any]],
           outdir: str,
           model_name: str,
           overwrite: bool,
           max_retries: int,
           uncertain_path: str):
    os.makedirs(outdir, exist_ok=True)
    tbar = tqdm(shard, desc=f"worker-{rank}", position=rank)
    for rec in tbar:
        try:
            pid, status = analyze_one(
                rec, problems_by_id, outdir, model_name, overwrite, max_retries, uncertain_path
            )
            tbar.set_postfix_str(f"{pid}:{status}")
        except Exception:
            traceback.print_exc()


def main():
    parser = argparse.ArgumentParser(description="Analyze student solution errors (taxonomy prompt) with retries for Uncertain.")
    parser.add_argument("--grades", required=True,
                        help="Path/dir/glob to grade files (.json/.jsonl or a directory).")
    parser.add_argument("--problems", required=True,
                        help="Raw problems file (JSON/JSONL) containing items with 'id'.")
    parser.add_argument("--outdir", default="Analyze_Label/Analysis/sol_error/results",
                        help="Output directory for per-problem JSON results.")
    parser.add_argument("--model", default="gpt-4o", help="Model name passed to call_model_api.")
    parser.add_argument("--processes", type=int, default=1, help="Number of worker processes.")
    parser.add_argument("--overwrite", action="store_true", help="Overwrite existing outputs.")
    parser.add_argument("--slice", type=int, nargs=2, default=[-1, -1],
                        metavar=("START", "END"),
                        help="Slice [START, END) into loaded grade records (default: all).")
    parser.add_argument("--max-retries", type=int, default=5,
                        help="Max retries when primary_error == 'Uncertain'. Default 5.")
    parser.add_argument("--uncertain-file", type=str, default=None,
                        help="Path to store final-uncertain ids. Default: <outdir>/uncertain.json")

    args = parser.parse_args()
    print(args.problems)
    problems_by_id = load_problems_index(args.problems)
    grade_records = load_all_grade_records(args.grades)

    # Optional slice
    s0, s1 = args.slice
    if s0 >= 0 or s1 >= 0:
        s = s0 if s0 >= 0 else 0
        e = s1 if s1 >= 0 else len(grade_records)
        grade_records = grade_records[s:e]

    if not grade_records:
        print("[ERROR] No grade records to process after loading/slicing.", file=sys.stderr)
        sys.exit(2)

    outdir = args.outdir
    os.makedirs(outdir, exist_ok=True)
    uncertain_path = args.uncertain_file or os.path.join(outdir, "uncertain.json")

    procs = max(1, int(args.processes))
    shards = [grade_records[i::procs] for i in range(procs)]

    if procs == 1:
        worker(0, shards[0], problems_by_id, outdir, args.model, args.overwrite, args.max_retries, uncertain_path)
    else:
        ps: List[mp.Process] = []
        for r in range(procs):
            p = mp.Process(target=worker, args=(
                r, shards[r], problems_by_id, outdir, args.model, args.overwrite, args.max_retries, uncertain_path
            ))
            p.start()
            ps.append(p)
        for p in ps:
            p.join()


if __name__ == "__main__":
    main()