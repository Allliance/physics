import os
import json
import time
import argparse
import signal

import glob

import logging
from typing import Callable, Dict, List, Tuple, Optional
from functools import partial
from contextlib import contextmanager
from logging.handlers import RotatingFileHandler

from utils.grade_utils import grade_problem, grade_problem_dag
from utils.prompt_utils import get_eval_prompt
from utils.llm_utils import call_model_api
from utils.data_utils import filter_and_convert
from utils.seephys import grade_problem_seephys

from tqdm import tqdm

import multiprocessing
DATA_BATCH_SIZE = 1
# --------------------------
# Logging utilities
# --------------------------


class JsonFormatter(logging.Formatter):
    """Minimal JSON log formatter."""
    def format(self, record: logging.LogRecord) -> str:
        payload = {
            "ts": self.formatTime(record, datefmt="%Y-%m-%dT%H:%M:%S%z"),
            "level": record.levelname,
            "name": record.name,
            "msg": record.getMessage(),
        }
        # Common extras if present
        for key in ("model", "problem_id", "method", "path", "phase"):
            if hasattr(record, key):
                payload[key] = getattr(record, key)
        if record.exc_info:
            payload["exc_info"] = self.formatException(record.exc_info)
        return json.dumps(payload, ensure_ascii=False)

def setup_logging(
    log_path: Optional[str],
    level: str = "INFO",
    json_logs: bool = False,
    logger_name: str = "evaluator"
) -> logging.Logger:
    logger = logging.getLogger(logger_name)
    logger.setLevel(getattr(logging, level.upper(), logging.INFO))
    logger.handlers.clear()
    logger.propagate = False

    if json_logs:
        formatter = JsonFormatter()
    else:
        formatter = logging.Formatter(
            fmt="%(asctime)s | %(levelname)-8s | %(name)s | %(message)s",
            datefmt="%Y-%m-%d %H:%M:%S",
        )

    # Console handler
    ch = logging.StreamHandler()
    ch.setFormatter(formatter)
    logger.addHandler(ch)

    # Optional rotating file handler
    if log_path:
        log_dir = os.path.dirname(log_path)
        if log_dir:  # Only try to create directory if there's actually a directory path
            os.makedirs(log_dir, exist_ok=True)
        fh = RotatingFileHandler(log_path, maxBytes=10 * 1024 * 1024, backupCount=3)
        fh.setFormatter(formatter)
        logger.addHandler(fh)

    logger.debug("Logging configured", extra={"path": log_path})
    return logger


@contextmanager
def timed(logger: logging.Logger, msg: str, **extra):
    start = time.time()
    logger.debug(f"[START] {msg}", extra=extra)
    try:
        yield
    finally:
        dur = (time.time() - start) * 1000.0
        logger.debug(f"[END] {msg} ({dur:.1f} ms)", extra=extra)
        
# --- after your existing `timed` context manager, add: ---
@contextmanager
def time_limit(seconds: float):
    """Raise TimeoutError if the block runs longer than `seconds` (POSIX only)."""
    if not seconds or seconds <= 0:
        # No-op when disabled
        yield
        return

    def _handler(signum, frame):
        raise TimeoutError("grading_timeout")

    old_handler = signal.signal(signal.SIGALRM, _handler)
    # Use setitimer so we can supply fractional seconds
    signal.setitimer(signal.ITIMER_REAL, seconds)
    try:
        yield
    finally:
        # Clear timer and restore handler
        signal.setitimer(signal.ITIMER_REAL, 0.0)
        signal.signal(signal.SIGALRM, old_handler)


def aggregate_from_files(grades_dir: str, threshold: float) -> tuple[float, int, int]:
    total = 0.0
    correct = 0
    n_eval = 0
    for path in glob.glob(os.path.join(grades_dir, "*_grade.json")):
        try:
            with open(path, encoding="utf-8") as f:
                g = json.load(f)
            if not isinstance(g, dict): 
                continue
            if "score" not in g:
                continue  # error stub or diagnostic
            score = float(g.get("score") or 0.0)
            ok = bool(g.get("is_correct", score >= threshold))
            total += score
            correct += int(ok)
            n_eval += 1
        except Exception:
            # ignore corrupt/partial files
            continue
    return total, correct, n_eval

def grade_for_model(
    rank: int,
    model_name: str,
    batched_input_problems: List[Dict],
    compare_fn: Callable[[Dict, str], Tuple[float, List]],
    threshold: float,
    out_dir: str,
    correct_count: dict,
    total_count: dict,
    eval_count: dict,
    logger: Optional[logging.Logger] = None,
    overwrite: bool = False,
    per_problem_timeout: float = 0.0,
) -> None:
    """Grade a shard of problems for one model and write per-problem files."""
    total, correct, n_eval = 0.0, 0, 0
    extra = {"model": model_name, "phase": "grade"}
    logger = logger or logging.getLogger("evaluator")

    # Helper to get the solution string robustly
    def _get_solution(d: Dict) -> Optional[str]:
        return (
            d.get("response")
            or d.get("final_response")
            or d.get("answer")
            or d.get("solution")
        )

    for batch in tqdm(batched_input_problems, desc=str(rank), position=rank):
        item = batch[0]
        pid = item.get("problem_id") or item.get("id")
        pextra = {**extra, "problem_id": pid}
        if pid is None:
            logger.warning("Skip: missing problem_id", extra=pextra)
            continue

        out_path = os.path.join(out_dir, f"{pid}_grade.json")
        if os.path.exists(out_path) and (not overwrite):
            # Load existing file and decide whether to skip
            should_skip = True
            try:
                with open(out_path, encoding="utf-8") as f:
                    existing = json.load(f)
                # Re-grade if prior run error'd or incomplete (no score)
                if isinstance(existing, dict) and ("error" in existing or "score" not in existing):
                    should_skip = False
                    tqdm.write(f"[rank {rank}] Regrading {pid}: prior error/incomplete result")
                else:
                    tqdm.write(f"[rank {rank}] Skip: grade already exists for problem {pid}")
            except Exception:
                # Corrupt file → re-grade
                should_skip = False
                tqdm.write(f"[rank {rank}] Regrading {pid}: existing file unreadable/corrupt")

            if should_skip:
                continue

        os.makedirs(os.path.dirname(out_path), exist_ok=True)

        try:
            sol = _get_solution(item)
            if not sol:
                # Write a diagnostic file so you can trace why it was skipped
                diag = {
                    "problem_id": pid,
                    "error": "missing_solution_text",
                    "available_keys": list(item.keys()),
                }
                with open(out_path, "w", encoding="utf-8") as f:
                    json.dump(diag, f, indent=2, ensure_ascii=False)
                logger.warning("Missing solution text; wrote diagnostic", extra=pextra)
                continue

            raw_problem = item.get("raw_problem", item.get("problem") or item)
            _t0 = time.perf_counter()
            try:
                with time_limit(per_problem_timeout):
                    score, matches = compare_fn(raw_problem, sol)
            except TimeoutError:
                # Write a stub and continue; aggregator will skip (no "score")
                timeout_stub = {
                    "problem_id": pid,
                    "error": "grading_timeout",
                    "timeout_seconds": per_problem_timeout,
                }
                with open(out_path, "w", encoding="utf-8") as f:
                    json.dump(timeout_stub, f, indent=2, ensure_ascii=False)
                logger.warning(
                    f"Grading timed out after {per_problem_timeout}s",
                    extra=pextra
                )
                continue
            ms = (time.perf_counter() - _t0) * 1000.0

            ok = score >= threshold
            total += score
            correct += int(ok)
            n_eval += 1

            logger.info(
                f"Problem graded: score={score:.2f} {'✓' if ok else '✗'}",
                extra=pextra,
            )

            grade_info = {
                "problem_id": pid,
                "score": score,
                "is_correct": ok,
                "answer": sol,
                "matches": matches or None,
                "grade_time_ms": round(ms, 1),
            }
            # Write ONLY this problem's grade to its file
            with open(out_path, "w", encoding="utf-8") as f:
                json.dump(grade_info, f, indent=2, ensure_ascii=False)

        except Exception:
            logger.exception("Grading failed; wrote error stub", extra=pextra)
            err_stub = {
                "problem_id": pid,
                "error": "grading_exception",
            }
            with open(out_path, "w", encoding="utf-8") as f:
                json.dump(err_stub, f, indent=2, ensure_ascii=False)

    # Report back to parent via shared dicts
    correct_count[rank] = correct
    total_count[rank] = total
    eval_count[rank] = n_eval

def collect_all_model_summaries(result_mode_dir: str, method: str) -> Dict[str, Dict]:
    """
    Scan results/{mode}/*/grades/{method}/*_grades_{method}.json
    and merge into {model_name: summary_dict}.
    """
    merged: Dict[str, Dict] = {}
    pattern = os.path.join(
        result_mode_dir, "*", "grades", method, f"*_grades_{method}.json"
    )
    for path in glob.glob(pattern):
        try:
            with open(path, encoding="utf-8") as f:
                data = json.load(f)
            if not isinstance(data, dict):
                continue
            model_key = data.get("model")
            if not model_key:
                # Fallback: infer from directory name
                # .../{mode}/{model_sanitized}/grades/{method}/file.json
                p3 = os.path.dirname(os.path.dirname(os.path.dirname(path)))  # -> .../{mode}/{model_sanitized}
                model_key = os.path.basename(p3)
            merged[model_key] = data
        except Exception:
            # Ignore unreadable files
            continue
    return merged

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--multiprocessing", type=int, default=1,
                        help="Number of parallel processes for generation")
    parser.add_argument("--mode", type=str, default='text',
                        help="Evaluation mode, 'text' or 'multimodal'")
    parser.add_argument("--problems_file", default="01-1.json")
    parser.add_argument("--mapping_json", type=str, default="/Users/zwj/AI4S_Bench/jpg_file_ids.json",
                        help="Path to image file id mapping JSON (for multimodal mode)")
    parser.add_argument("--file_path", type=str, default="/Users/zwj/Downloads/PHYBE/",
                        help="Base path for image locations (for multimodal mode)")
    parser.add_argument("--slice", type=int, nargs=2, default=[0, 10],
                        metavar=("START","END"))
    parser.add_argument("--results_dir", default="results")
    parser.add_argument("--log_path", type=str, default=None)
    parser.add_argument("--threshold", type=float, default=0.8)
    parser.add_argument("--overwrite", action="store_true",
                        help="If set, re-generate all responses even if files exist")
    parser.add_argument("--method", type=str, default="tree",
                        choices=["tree", "dag", "seephys"])
    # New logging controls
    parser.add_argument("--log_level", type=str, default="INFO",
                        help="Logging level: DEBUG, INFO, WARNING, ERROR")
    parser.add_argument("--json_logs", action="store_true",
                        help="Emit logs in JSON format")
    parser.add_argument('--models', nargs='+', required=True, help='List of model names to grade for')
    parser.add_argument(
        "--per_problem_timeout", type=float, default=120.0,
        help="Seconds allowed per problem (0 = disabled). POSIX only."
    )
    args = parser.parse_args()
    logger = setup_logging(args.log_path, level=args.log_level, json_logs=args.json_logs)
    logger.debug(f"problems file is: {args.problems_file}")


    # final_results: Dict[str, Dict] = {}
    for model in args.models:
        logger.info("Model: start evaluation", extra={"model": model, "phase": "loop", "problems_file": args.problems_file})
        result_mode_dir = os.path.join(args.results_dir, args.mode)
        result_dir = os.path.join(result_mode_dir, model.replace("/", "_"))
        os.makedirs(result_dir, exist_ok=True)
        responses_dir = os.path.join(result_dir, "responses")
        grades_init_dir = os.path.join(result_dir, "grades")
        grades_dir= os.path.join(grades_init_dir, args.method)
        grade_path = os.path.join(grades_dir, f"{model}_grades_{args.method}.json")
        grade_final_path = os.path.join(result_mode_dir, f"final_grades_{args.method}.json") 

        os.makedirs(grades_dir, exist_ok=True)
        # paths
        resp_path = os.path.join(responses_dir, f"{model}_final_responses.json")
        

        # 2) grade
        method = args.method
        logger.info("Evaluation method", extra={"model": model, "method": method, "phase": "grade"})

        if method == "tree":
            compare_fn=partial(grade_problem, log_path=args.log_path)
            
        elif method == "dag":
           compare_fn=partial(grade_problem_dag, log_path=args.log_path)
        elif method == "seephys":
            def generate_func(context):
                return call_model_api(model_name="gpt-5-mini", context=context)
            compare_fn=partial(grade_problem_seephys, generate_func=generate_func)
        else:
            logger.error("Undefined evaluation method", extra={"method": method, "phase": "grade"})
            raise ValueError(f"Evaluation Method {method} Undefined.")
        


        num_processes = args.multiprocessing 
        print(f"Using {num_processes} processes for grading.")
        processes = []
        logger = logger or logging.getLogger("evaluator")
        extra = {"model": model, "phase": "grade"}

        logger.info("Grade: loading responses", extra={**extra, "path": resp_path})
        with timed(logger, "read_responses_file", **extra):
            with open(resp_path, encoding="utf-8") as f:
                saved = json.load(f)
        logger.info(f"Loaded {len(saved)} responses from {resp_path}",extra={**extra})
        get_id = lambda x: x["problem_id"] if x.get("problem_id") else x.get("id", None)
        ids = [get_id(s) for s in saved]
        logger.info(f"ids loaded: {str(ids)}", extra={**extra})

        batched_saved = [saved[i : i + DATA_BATCH_SIZE] for i in range(0, len(saved), DATA_BATCH_SIZE)]
        manager = multiprocessing.Manager()
        correct_count = manager.dict()  # 

        total_count = manager.dict()    #
        eval_count = manager.dict()
             #
        for i in range(num_processes):
            p = multiprocessing.Process(
                target=grade_for_model,
                args=(
                    i,
                    model,
                    batched_saved[i :: num_processes],
                    compare_fn,
                    args.threshold,
                    grades_dir,
                    correct_count,
                    total_count,
                    eval_count,
                    logger,
                    args.overwrite,
                    args.per_problem_timeout,   # <-- NEW
                )
            )
            p.start()
            processes.append(p)
        for p in processes:
            p.join()
        overall_total, overall_correct, overall_eval = aggregate_from_files(grades_dir, args.threshold)
        avg = (overall_total / overall_eval) if overall_eval else 0.0
        acc = (overall_correct / overall_eval) if overall_eval else 0.0
        logger.info(
            "Grade: summary",
            extra={**extra, "avg": round(avg, 3), "acc": round(acc, 4), "evaluated": overall_eval}
        )
        res = {"model": model, "grade_method": args.method, "overall_score": avg, "accuracy": acc, "evaluated": overall_eval}
        
        with open(grade_path, "w", encoding="utf-8") as f:
            json.dump(res, f, indent=2, ensure_ascii=False)

        # final_results[model] = res
        # with open(grade_final_path, "w", encoding="utf-8") as f:
        #     json.dump(final_results, f, indent=2, ensure_ascii=False)
            
        logger.info(
            "Model: done",
            extra={"model": model, "phase": "loop", "avg": res["overall_score"], "acc": res["accuracy"]}
        )
    
    # After evaluating requested models, gather ALL model summaries on disk
    result_mode_dir = os.path.join(args.results_dir, args.mode)
    merged_final = collect_all_model_summaries(result_mode_dir, args.method)
    grade_final_path = os.path.join(result_mode_dir, f"final_grades_{args.method}.json")
    with open(grade_final_path, "w", encoding="utf-8") as f:
        json.dump(merged_final, f, indent=2, ensure_ascii=False)

    logger.info("All models summary written", extra={"phase": "final", "path": grade_final_path, "count": len(merged_final)})

if __name__ == "__main__":
    main()
