import os
import json
import time
import argparse
import logging
from typing import Callable, Dict, List, Tuple, Optional, Set
from functools import partial
from contextlib import contextmanager
from logging.handlers import RotatingFileHandler

from utils.prompt_utils import get_eval_prompt
from utils.llm_utils import call_model_api
from utils.llm_multimodal_utils import call_multimodal_model_api
from utils.data_utils import filter_and_convert
from tqdm import tqdm

import multiprocessing
DATA_BATCH_SIZE = 1
# --------------------------
# Logging utilities
# --------------------------


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        payload = {
            "ts": self.formatTime(record, datefmt="%Y-%m-%dT%H:%M:%S%z"),
            "level": record.levelname,
            "name": record.name,
            "msg": record.getMessage(),
        }
        # include known extras
        for key in ("model", "problem_id", "method", "path", "phase"):
            if hasattr(record, key):
                payload[key] = getattr(record, key)

        # include ALL other non-standard extras automatically
        std = set(vars(logging.LogRecord('',0,'',0,'',(),None)))
        for k, v in record.__dict__.items():
            if k not in payload and k not in std and not k.startswith('_'):
                payload[k] = v

        if record.exc_info:
            payload["exc_info"] = self.formatException(record.exc_info)
        return json.dumps(payload, ensure_ascii=False)

def get_id(item):
    if item.get("id"):
        return item["id"]
    elif item.get("problem_id"):
        return item["problem_id"]
    else:
        return None

def merge_json_files(input_dir, output_file, overwrite=False):
    if os.path.exists(output_file) and not overwrite:
        try:
            merged_data = json.load(open(output_file, "r"))
            ids = [get_id(item) for item in merged_data]
            ids = [id for id in ids if id is not None]
        except:
            merged_data, ids = [], []
    else:
        merged_data, ids = [], []

    for filename in os.listdir(input_dir):
        if filename.endswith("response.json"):
            file_path = os.path.join(input_dir, filename)
            with open(file_path, "r", encoding="utf-8") as f:
                try:
                    data = json.load(f)
                    if isinstance(data, list):
                        for item in data:
                            cur_id = get_id(item)
                            if cur_id is None or cur_id in ids:
                                pass
                            else:
                                merged_data.append(item)
                                ids.append(cur_id)
                    else:
                        cur_id = get_id(data)
                        if cur_id is None or cur_id in ids:
                            pass
                        else:
                            merged_data.append(data)
                            ids.append(cur_id)
                            
                except json.JSONDecodeError:
                    print(f"Warning: Could not parse {file_path}, skipped.")

    with open(output_file, "w", encoding="utf-8") as out_f:
        json.dump(merged_data, out_f, ensure_ascii=False, indent=2)

    print(f"Merged {len(merged_data)} records into {output_file}")


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
        if log_dir:
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

def _is_valid_response_item(item):
    if isinstance(item, str):
        try:
            item = json.loads(item)
        except:
            return False
    if not isinstance(item, dict):
        return False
    if not item.get("response") or len(item["response"]) <= 1:
        return False
    if not item.get("problem_id"):
        return False
    return True

def _load_existing_problem_ids_from_final(resp_path: str, logger: logging.Logger) -> Set[str]:
    """Read existing final file and return set of problem_ids; robust to format issues."""
    existing: Set[str] = set()
    if not os.path.exists(resp_path):
        return existing
    try:
        with open(resp_path, "r", encoding="utf-8") as f:
            data = json.load(f)
        if isinstance(data, list):
            for item in data:
                # Accept either dicts with 'problem_id' or plain ids if someone changed format
                if _is_valid_response_item(item):
                    existing.add(str(item["problem_id"]))
        else:
            if _is_valid_response_item(data):
                existing.add(str(data["problem_id"]))
    except Exception as e:
        logger.warning("Could not parse existing final responses; will not skip by final file",
                       extra={"phase": "prep", "path": resp_path})
    return existing



def generate_for_model(
    rank: int,
    file_path: Optional[str],
    mapping_json: Optional[str],
    model_name: str,
    batched_input_problems: List[Dict],
    call_fn: Callable[..., str],
    responses_dir: str,
    overwrite: bool = False,
    logger: Optional[logging.Logger] = None,
    skip_ids: Optional[Set[str]] = None,
) -> None:
    """Generate & save responses for one model, unless file exists and overwrite=False.
    Also skips problems whose IDs are already present in the final merged file (skip_ids).
    """
    extra = {"model": model_name, "path": responses_dir, "phase": "generate"}
    skip_ids = skip_ids or set()

    for problem in tqdm(batched_input_problems, desc=str(rank), position=rank):
        problem = problem[0]
        pid = str(problem["id"])  # normalize to str for set membership
        out_path = os.path.join(responses_dir, f"{pid}_response.json")

        # New: skip if final already has this problem and not overwriting
        if (pid in skip_ids) and (not overwrite):
            if logger:
                logger.info("Skip: already present in final file",
                            extra={**extra, "problem_id": pid})
            continue

        # Existing per-problem skip
        if os.path.exists(out_path) and not overwrite:
            with open(out_path, "r") as f:
                res_item = json.load(f)
                if _is_valid_response_item(res_item):
                    if logger:
                        logger.info("Skip: per-problem response exists",
                                    extra={**extra, "problem_id": pid})
                    continue
                else:
                    if logger:
                        logger.info("per-problem response is invalid, not skipping", extra={**extra, "problem_id": pid})

        os.makedirs(os.path.dirname(out_path), exist_ok=True)
        pextra = {**extra, "problem_id": pid}

        try:
            _t_total0 = time.perf_counter()

            with timed(logger, "build_prompt", **pextra):
                prompt = get_eval_prompt(problem)
            logger.debug(f"Prompt built (len={len(prompt)})", extra=pextra)

            _t_model0 = time.perf_counter()
            with timed(logger, "model_call", **pextra):
                if mapping_json is None:
                    resp = call_fn(model_name, prompt)
                else:
                    images = problem.get("images", None)
                    logger.debug(f"Calling api with image: {images}")
                    resp = call_fn(file_path, model_name, images, mapping_json, prompt)
                    if len(resp) == 0:
                        logger.exception("Empty response", extra=pextra)
                        continue
            _model_ms = (time.perf_counter() - _t_model0) * 1000.0
            logger.info(f"model_call latency_ms={_model_ms:.1f}", extra=pextra)

            _total_ms = (time.perf_counter() - _t_total0) * 1000.0
            logger.info(f"problem total_ms={_total_ms:.1f}", extra=pextra)

            item = {
                "problem_id": pid,
                "response": resp,
                "model_call_ms": round(_model_ms, 1),
                "total_ms": round(_total_ms, 1),
                "raw_problem": problem,
            }
        except Exception:
            logger.exception("Generation failed; continuing", extra=pextra)
            # On failure, do not write a broken file for this pid
            continue

        with timed(logger, "write_responses_file", **extra):
            with open(out_path, "w", encoding="utf-8") as f:
                json.dump([item], f, ensure_ascii=False, indent=2)

    logger.info("Generate: done", extra=extra)


def load_and_filter(problems_file: str, logger: Optional[logging.Logger] = None) -> List[Dict]:
    logger = logger or logging.getLogger("evaluator")
    extra = {"phase": "load", "path": problems_file}
    with timed(logger, "read_problems_file", **extra):
        with open(problems_file, encoding="utf-8") as f:
            raw = json.load(f)
    logger.debug("Raw problems loaded", extra={**extra, "count": len(raw)})
    with timed(logger, "filter_and_convert", **extra):
        filtered = [filter_and_convert(p) for p in raw if filter_and_convert(p)]
    logger.info("Problems ready", extra={**extra, "count": len(filtered)})
    return filtered


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--multiprocessing", type=int, default=8,
                        help="Number of parallel processes for generation")
    parser.add_argument("--mode", type=str, default='text',
                        help="Evaluation mode, 'text' or 'multimodal'")
    parser.add_argument("--problems_file", default="01-1.json")
    parser.add_argument("--mapping_json", type=str, default="/home/users/wanjiazh/AI4S_Bench/jpg_file_ids.json",
                        help="Path to image file id mapping JSON (for multimodal mode)")
    parser.add_argument("--file_path", type=str, default="/home/users/wanjiazh/data/PHYBE/",
                        help="Base path for image locations (for multimodal mode)")
    parser.add_argument("--slice", type=int, nargs=2, default=[-1, -1],
                        metavar=("START","END"))
    parser.add_argument("--results_dir", default="results")
    parser.add_argument("--log_path", type=str, default=None)
    parser.add_argument("--threshold", type=float, default=0.8)
    parser.add_argument("--overwrite", action="store_true",
                        help="If set, re-generate all responses even if files exist")
    parser.add_argument("--method", type=str, default="tree",
                        choices=["tree", "dag", "seephys"])
    parser.add_argument('--models', nargs='+', required=True, help='List of model names to process')
    # New logging controls
    parser.add_argument("--log_level", type=str, default="INFO",
                        help="Logging level: DEBUG, INFO, WARNING, ERROR")
    parser.add_argument("--json_logs", action="store_true",
                        help="Emit logs in JSON format")
    args = parser.parse_args()

    logger = setup_logging(args.log_path, level=args.log_level, json_logs=args.json_logs)
    logger.info(f"models: {str(args.models)}")
    logger.info("Run started", extra={"phase": "start"})

    all_problems = load_and_filter(args.problems_file, logger=logger)
    logger.info("All problems loaded", extra={"count": len(all_problems), "phase": "prep"})

    if args.slice != [-1, -1]:
        start, end = args.slice
        problems = all_problems[start:end]
        logger.info(
            "Applying slice",
            extra={"phase": "prep", "slice_start": start, "slice_end": end, "count": len(problems)}
        )
    else:
        problems = all_problems
        logger.info("Using full problem set", extra={"phase": "prep", "count": len(problems)})

    logger.info(
        "Evaluation setup",
        extra={
            "phase": "prep",
            "models": ",".join(args.models),
            "method": args.method,
            "threshold": args.threshold,
            "overwrite": args.overwrite
        }
    )

    # choose text vs. multimodal API
    if args.mode == "multimodal":
        call_api = call_multimodal_model_api
        mapping_json = args.mapping_json
        file_path = args.file_path
    elif args.mode == "text":
        call_api = call_model_api
        mapping_json = None
        file_path = None
    else:
        logger.error("Invalid mode specified", extra={"mode": args.mode, "phase": "prep"})
        raise ValueError(f"Invalid mode: {args.mode}. Choose 'text' or 'multimodal'.")

    batched_problems = [problems[i: i + DATA_BATCH_SIZE] for i in range(0, len(problems), DATA_BATCH_SIZE)]

    for model in args.models:
        logger.info("Model: start evaluation", extra={"model": model, "phase": "loop"})
        result_mode_dir = os.path.join(args.results_dir, args.mode)
        result_dir = os.path.join(result_mode_dir, model.replace("/", "_"))
        os.makedirs(result_dir, exist_ok=True)
        responses_dir = os.path.join(result_dir, "responses")
        os.makedirs(responses_dir, exist_ok=True)

        # paths
        resp_path = os.path.join(responses_dir, f"{model}_final_responses.json")

        # New: compute skip set from existing final file if not overwriting
        skip_ids = set()
        if not args.overwrite:
            skip_ids = _load_existing_problem_ids_from_final(resp_path, logger)
            if skip_ids:
                logger.info("Loaded existing problem_ids from final file",
                            extra={"phase": "prep", "count": len(skip_ids), "path": resp_path, "model": model})

        # 1) generate (if needed)
        num_processes = args.multiprocessing
        processes = []
        for i in range(num_processes):
            p = multiprocessing.Process(
                target=generate_for_model,
                args=(
                    i, file_path, mapping_json, model,
                    batched_problems[i::num_processes],
                    call_api, responses_dir, args.overwrite, logger, skip_ids
                )
            )
            p.start()
            processes.append(p)
        for p in processes:
            p.join()

        # 2) merge per-problem files into the final file for this model
        merge_json_files(responses_dir, resp_path, overwrite=args.overwrite)


if __name__ == "__main__":
    main()
