import json
from utils.helper_utils import safe_json_loads
import os
import re
import copy
import argparse
from utils.llm_utils import call_model_api
from utils.prompt_utils import (
    get_wash_prompt_stage1,
    get_wash_prompt_stage2,
    get_wash_prompt_stage3,
    get_review_prompt_stage1,
    get_review_prompt_stage2,
    get_review_prompt_stage3
)
from tqdm import tqdm
from concurrent.futures import ProcessPoolExecutor, ThreadPoolExecutor, as_completed

import logging
import time
import traceback
from logging.handlers import RotatingFileHandler
from contextlib import contextmanager
import ast

# -------- Logging helpers --------

def setup_logging(log_file: str | None, level: str = "INFO", json_logs: bool = False) -> logging.Logger:
    logger = logging.getLogger("washer")
    logger.setLevel(getattr(logging, level.upper(), logging.INFO))
    logger.handlers.clear()

    if json_logs:
        fmt = '{"ts":"%(asctime)s","level":"%(levelname)s","msg":"%(message)s"}'
        datefmt = "%Y-%m-%dT%H:%M:%S"
    else:
        fmt = "%(asctime)s | %(levelname)-8s | %(message)s"
        datefmt = "%H:%M:%S"

    stream_h = logging.StreamHandler()
    stream_h.setFormatter(logging.Formatter(fmt=fmt, datefmt=datefmt))
    logger.addHandler(stream_h)

    if log_file:
        file_h = RotatingFileHandler(log_file, maxBytes=10_000_000, backupCount=3)
        file_h.setFormatter(logging.Formatter(fmt=fmt, datefmt=datefmt))
        logger.addHandler(file_h)

    return logger

def _trunc(s: str | None, n: int = 300) -> str:
    if not s:
        return ""
    s = s.replace("\n", "\\n")
    return s if len(s) <= n else s[:n] + "...(trunc)"

@contextmanager
def timed(logger: logging.Logger, label: str, ctx: str = ""):
    t0 = time.perf_counter()
    try:
        yield
    finally:
        dt = (time.perf_counter() - t0) * 1000.0
        logger.debug(f"{ctx} {label} done in {dt:.1f} ms")

def ctx_str(idx=None, stage=None, attempt=None, retry=None, item=None):
    parts = []
    if idx is not None: parts.append(f"idx={idx}")
    if item and isinstance(item, dict) and item.get('id'): parts.append(f"id={item.get('id')}")
    if stage is not None: parts.append(f"stage={stage}")
    if attempt is not None: parts.append(f"attempt={attempt}")
    if retry is not None: parts.append(f"retry={retry}")
    return "[" + " ".join(parts) + "]"



_CODE_FENCE_RE = re.compile(
    r"""```[ \t]*           # opening backticks with optional spaces
        (?:[A-Za-z0-9_+\-]+[ \t]*)?  # optional language tag (json, jsonc, python, etc.)
        \n                   # newline after the opening fence
        (.*?)                # non-greedy capture of the payload
        \n?```               # optional newline then closing backticks
    """,
    re.DOTALL | re.VERBOSE,
)

def extract_code_block(text: str) -> str:
    logger = logging.getLogger("washer")
    m = _CODE_FENCE_RE.search(text)
    if m:
        payload = m.group(1)
        logger.debug("extract_code_block: fenced payload len=%d", len(payload))
        return payload

    stripped = text.strip()
    if stripped.startswith("{") or stripped.startswith("["):
        logger.debug("extract_code_block: raw JSON detected len=%d", len(stripped))
        return stripped

    logger.warning("extract_code_block: no fenced/JSON block found")
    raise ValueError("No code block found; expected a fenced block or raw JSON.")




_STAGE_FIELDS = {
    1: ["context", "solution", "subquestions", "images"],
    2: ["final_answer_form", "final_answer_instructions", "subquestions"],
    3: ["grading_standard"],
}


def _collect_stage_deltas(before: dict, after: dict, fields: list[str]) -> dict:
    """Return per-field before/after snapshots for the requested fields."""
    deltas: dict[str, dict[str, object]] = {}
    for field in fields:
        before_val = before.get(field)
        after_val = after.get(field)
        if before_val != after_val:
            deltas[field] = {
                "before": copy.deepcopy(before_val),
                "after": copy.deepcopy(after_val),
            }
    return deltas



def check_valid(item: dict, stage: int, method: str = None) -> bool:
    logger = logging.getLogger("washer")
    c = ctx_str(item=item, stage=stage)
    try:
        logger.debug("%s check_valid: stage=%s method=%s keys=%s",
                     c, stage, method, sorted(list(item.keys())))

        # --- Common required fields ---
        if not item.get("id"):
            logger.debug("%s invalid: missing 'id'", c)
            return False
        if not item.get("context"):
            logger.debug("%s invalid: missing 'context'", c)
            return False

        # --- Stage 1 checks ---
        if stage == 1:
            has_solution = bool(item.get("solution"))
            subs = item.get("subquestions")

            if not has_solution:
                if not subs:
                    logger.debug("%s stage1 invalid: no 'solution' and no 'subquestions'", c)
                    return False
                if not isinstance(subs, list):
                    logger.debug("%s stage1 invalid: 'subquestions' is not a list (got %s)",
                                 c, type(subs).__name__)
                    return False
                bad_idx = [i for i, q in enumerate(subs)
                           if not isinstance(q, dict) or "solution" not in q]
                if bad_idx:
                    logger.debug("%s stage1 invalid: subquestions missing 'solution' at idx=%s",
                                 c, bad_idx[:10])
                    return False

            logger.debug("%s stage1 valid", c)
            return True

        # --- Stage 2 checks ---
        if stage == 2:
            faf_ok = "final_answer_form" in item
            fai_ok = "final_answer_instructions" in item
            if not (faf_ok and fai_ok):
                subs = item.get("subquestions")
                if not subs:
                    logger.debug("%s stage2 invalid: missing final_* and no 'subquestions'", c)
                    return False
                if not isinstance(subs, list):
                    logger.debug("%s stage2 invalid: 'subquestions' is not a list (got %s)",
                                 c, type(subs).__name__)
                    return False
                bad_idx = [i for i, q in enumerate(subs)
                           if not isinstance(q, dict)
                           or "final_answer_form" not in q
                           or "final_answer_instructions" not in q]
                if bad_idx:
                    logger.debug("%s stage2 invalid: subquestions missing final_* at idx=%s",
                                 c, bad_idx[:10])
                    return False

            logger.debug("%s stage2 valid", c)
            return True

        # --- Stage 3 checks ---
        if stage == 3:
            if method == "seephys":
                return True
            if "grading_standard" not in item:
                logger.debug("%s stage3 invalid: missing 'grading_standard'", c)
                return False

            gs = item.get("grading_standard")
            gs_type = type(gs).__name__
            gs_preview = _trunc(json.dumps(gs) if isinstance(gs, (dict, list)) else str(gs), 200)
            logger.debug("%s stage3: method=%s gs_type=%s preview=%s",
                         c, method, gs_type, gs_preview)

            if method == "dag":
                try:
                    if isinstance(gs, (dict, list)):
                        pass
                    else:
                        _ = safe_json_loads(gs)
                except Exception as e:
                    logger.debug("%s stage3 invalid (dag): grading_standard not JSON-parsable: %s",
                                 c, e)
                    return False

            if method == "tree":
                try:
                    if isinstance(gs, str):
                        s = gs
                    else:
                        # keep original behavior (expects str), but make it robust for logging
                        s = json.dumps(gs)
                    s = re.sub(r'(\$\$.*?\$\$)', '1', s, flags=re.DOTALL)
                    _ = ast.literal_eval(s)
                except Exception as e:
                    logger.debug("%s stage3 invalid (tree): literal_eval failed: %s", c, e)
                    return False

            logger.debug("%s stage3 valid", c)
            return True

        logger.warning("%s check_valid called with unsupported stage=%s", c, stage)
        return False

    except Exception as e:
        logger.exception("%s check_valid raised exception: %s", c, e)
        return False

def _get_id(obj) -> str | None:
    if isinstance(obj, dict):
        if obj.get("id") is not None:
            return obj.get("id")
        else:
            return obj.get("problem_id", None)
    return None

def _load_json_safe(path: str):
    if not os.path.exists(path):
        return None
    with open(path, "r") as f:
        return json.load(f)

def _upgrade_ckpt_to_id_keys(ckpt_raw, items_by_index) -> dict[str, dict] :
    """
    Accepts a ckpt that might be:
      - dict keyed by problem_id
      - dict keyed by index (strings or ints)
      - list of results (old style)
    Returns: dict[problem_id] -> result
    """
    out: dict[str, dict] = {}

    # dict case
    if isinstance(ckpt_raw, dict):
        for k, v in ckpt_raw.items():
            # If value itself has an id, prefer that
            vid = _get_id(v)
            if vid:
                out[str(vid)] = v
                continue
            # Else, if key is an index and we can map index->id, do it
            try:
                idx = int(k)
                base = items_by_index.get(idx)
                bid = _get_id(base)
                if bid:
                    out[str(bid)] = v
            except Exception:
                # Might already be keyed by a non-numeric id string
                if isinstance(k, str) and k:
                    out[k] = v
        return out

    # list case (old style)
    if isinstance(ckpt_raw, list):
        for v in ckpt_raw:
            vid = _get_id(v)
            if vid:
                out[str(vid)] = v
        return out

    return out



def review_washed(item, model_name: str, stage:int, method=None, original_item=None):
    logger = logging.getLogger("washer")
    c = ctx_str(item=item, stage=stage)
    with timed(logger, "review_washed", c):
        try:
            if stage == 1:
                review_prompt = get_review_prompt_stage1(item, original_sample=original_item)
            elif stage == 2:
                review_prompt = get_review_prompt_stage2(item)
            elif stage == 3:
                review_prompt = get_review_prompt_stage3(item, method=method)
            else:
                logger.error("%s invalid stage for review: %s", c, stage)
                return False, "Invalid stage"

            llm_result = call_model_api(model_name, review_prompt)
            logger.debug("%s reviewer raw: %s", c, _trunc(llm_result, 500))

            valid_str = re.search(r'<judge>(.*?)</judge>', llm_result, re.DOTALL)
            reason_str = re.search(r'<reason>(.*?)</reason>', llm_result, re.DOTALL)

            if valid_str is None or reason_str is None:
                logger.warning("%s reviewer missing <judge> or <reason>", c)
                return False, "Failed when calling reviewer LLM."

            v = valid_str.group(1).strip().lower()
            reason = reason_str.group(1).strip()
            if v == "valid":
                logger.info("%s review: VALID | reason=%s", c, _trunc(reason))
                return True, reason
            elif v == "invalid":
                logger.info("%s review: INVALID | reason=%s", c, _trunc(reason))
                return False, reason
            else:
                logger.warning("%s reviewer <judge> unexpected: %s", c, v)
                return False, "Failed when calling reviewer LLM. The result is not valid or invalid."
        except Exception as e:
            logger.error("%s review exception: %s\n%s", c, e, traceback.format_exc())
            return False, "Reviewer exception"


def get_wash_prompt_stage_with_history(item, history, stage: int, method=None, max_chars: int = -1):
    """
    Build a wash prompt for a retry that includes the full chronological
    history of all previous answers and reviewer feedback.

    history: list of dicts like:
      {"answer": <raw_model_output_str>,
       "feedback": <reviewer_reason_str>,
       "judge": "valid" | "invalid"}
    """
    logger = logging.getLogger("washer")

    if stage == 1:
        prompt = get_wash_prompt_stage1(item)
    elif stage == 2:
        prompt = get_wash_prompt_stage2(item)
    elif stage == 3:
        prompt = get_wash_prompt_stage3(item, use_dag=True if method == "dag" else False)
    else:
        raise ValueError(f"Unsupported stage: {stage}")

    def truncate(text: str) -> str:
        if text is None:
            return ""
        return text if max_chars == -1 or len(text) <= max_chars else text[:max_chars] + "\n...[TRUNCATED]..."

    if history:
        prompt += (
            "\n\n---\n"
            "This is a RETRY.\n"
            "Below is the full chronological log of your previous attempts and the reviewer's feedback.\n"
            "Learn from these mistakes and strictly follow the stage instructions above.\n"
            "---\n"
        )
        for i, h in enumerate(history, 1):
            prompt += (
                f"[Attempt {i} — Your Answer]\n{truncate(h.get('answer', ''))}\n"
            )
            j = h.get("judge", "")
            if j:
                prompt += f"[Attempt {i} — Reviewer Decision]\n{j.upper()}\n"
            fb = h.get("feedback", "")
            if fb:
                prompt += f"[Attempt {i} — Reviewer Feedback]\n{truncate(fb)}\n"
            prompt += "---\n"
        prompt += "Now provide a corrected answer according to the required schema and criteria."

    logger.debug("%s history build: attempts=%d",
                 ctx_str(item=item, stage=stage), len(history))
    return prompt


def process_stage1(item: dict, model_name: str, max_attempts: int, original_item: dict) -> dict:
    logger = logging.getLogger("washer")
    c = ctx_str(item=item, stage=1)
    base_prompt = get_wash_prompt_stage1(item)
    logger.debug("%s stage1 prompt_len=%d", c, len(base_prompt))

    history = []  # <-- accumulate across attempts & reviewer loops

    for attempt in range(1, max_attempts+1):
        cA = ctx_str(item=item, stage=1, attempt=attempt)
        try:
            prompt = get_wash_prompt_stage_with_history(item, history, 1)
            if not history:  # first shot uses base prompt (no history section)
                prompt = base_prompt

            with timed(logger, "stage1_call_model", cA):
                raw = call_model_api(model_name, prompt)
            logger.debug("%s raw_len=%d raw_snippet=%s", cA, len(raw or ""), _trunc(raw))

            extracted = extract_code_block(raw)
            parsed = safe_json_loads(extracted)
            ok = check_valid(parsed, stage=1)
            logger.info("%s parsed_ok=%s", cA, ok)
            if not ok:
                # structural problem; try next attempt
                continue

            is_good, reason = review_washed(parsed, model_name, stage=1, original_item=original_item)

            # reviewer loop (keep full history)
            maxloop = 5
            loopcount = 0
            while (not is_good) and (loopcount < maxloop):
                loopcount += 1
                cL = ctx_str(item=item, stage=1, attempt=attempt)
                logger.debug("%s reviewer_loop=%d reason=%s", cL, loopcount, _trunc(reason))

                # record the last attempt + feedback
                history.append({"answer": raw or "", "feedback": reason or "", "judge": "invalid"})

                newprompt = get_wash_prompt_stage_with_history(item, history, 1)
                try:
                    raw = call_model_api(model_name, newprompt)
                    extracted = extract_code_block(raw)
                    parsed = safe_json_loads(extracted)
                    if not check_valid(parsed, stage=1):
                        logger.debug("%s re-parse invalid after reviewer loop", cL)
                        # still record attempt, but no new feedback yet
                        continue
                    is_good, reason = review_washed(parsed, model_name, stage=1, original_item=original_item)
                except Exception as e:
                    logger.warning("%s reviewer_loop exception: %s", cL, e)
                    continue

            # If we exit loop because it's now good, optionally record the success for completeness
            if is_good:
                history.append({"answer": raw or "", "feedback": reason or "", "judge": "valid"})

            logger.info("%s done reviewer_good=%s loops=%d", cA, is_good, loopcount)
            return parsed

        except Exception as e:
            logger.error("%s attempt failed: %s\n%s", cA, e, traceback.format_exc())

    logger.warning("%s stage1 exhausted attempts", c)
    return None



def process_stage2(item: dict, model_name: str, max_attempts: int) -> dict:
    logger = logging.getLogger("washer")
    c = ctx_str(item=item, stage=2)
    base_prompt = get_wash_prompt_stage2(item)
    logger.debug("%s stage2 prompt_len=%d", c, len(base_prompt))

    history = []

    for attempt in range(1, max_attempts + 1):
        cA = ctx_str(item=item, stage=2, attempt=attempt)
        try:
            prompt = get_wash_prompt_stage_with_history(item, history, 2)
            if not history:
                prompt = base_prompt

            with timed(logger, "stage2_call_model", cA):
                raw = call_model_api(model_name, prompt)
            logger.debug("%s raw_len=%d raw_snippet=%s", cA, len(raw or ""), _trunc(raw))

            with timed(logger, "stage2_extract", cA):
                extracted = extract_code_block(raw)

            with timed(logger, "stage2_parse", cA):
                parsed = safe_json_loads(extracted)

            ok = check_valid(parsed, stage=2)
            logger.info("%s parsed_ok=%s", cA, ok)
            if not ok:
                continue

            is_good, reason = review_washed(parsed, model_name, stage=2)

            maxloop = 5
            loopcount = 0
            while (not is_good) and (loopcount < maxloop):
                loopcount += 1
                cL = ctx_str(item=item, stage=2, attempt=attempt)
                logger.debug("%s reviewer_loop=%d reason=%s", cL, loopcount, _trunc(reason))

                history.append({"answer": raw or "", "feedback": reason or "", "judge": "invalid"})

                newprompt = get_wash_prompt_stage_with_history(item, history, 2)
                try:
                    raw = call_model_api(model_name, newprompt)
                    extracted = extract_code_block(raw)
                    parsed = safe_json_loads(extracted)
                    if not check_valid(parsed, stage=2):
                        logger.debug("%s re-parse invalid after reviewer loop", cL)
                        continue
                    is_good, reason = review_washed(parsed, model_name, stage=2)
                except Exception as e:
                    logger.warning("%s reviewer_loop exception: %s", cL, e)
                    continue

            if is_good:
                history.append({"answer": raw or "", "feedback": reason or "", "judge": "valid"})

            logger.info("%s done reviewer_good=%s loops=%d", cA, is_good, loopcount)
            return parsed

        except Exception as e:
            logger.error("%s attempt failed: %s\n%s", cA, e, traceback.format_exc())

    logger.warning("%s stage2 exhausted attempts", c)
    return None




def process_stage3(item: dict, model_name: str, max_attempts: int, method: str) -> dict:
    if method=="seephys":
        return item
    logger = logging.getLogger("washer")
    c = ctx_str(item=item, stage=3)
    base_prompt = get_wash_prompt_stage3(item, use_dag=True if method == "dag" else False)
    org_item = copy.deepcopy(item)
    logger.debug("%s stage3 prompt_len=%d method=%s", c, len(base_prompt), method)

    history = []

    for attempt in range(1, max_attempts + 1):
        cA = ctx_str(item=item, stage=3, attempt=attempt)
        try:
            prompt = get_wash_prompt_stage_with_history(org_item, history, 3, method=method)
            if not history:
                prompt = base_prompt

            with timed(logger, "stage3_call_model", cA):
                raw = call_model_api(model_name, prompt)
            logger.debug("%s raw_len=%d raw_snippet=%s", cA, len(raw or ""), _trunc(raw))

            with timed(logger, "stage3_extract", cA):
                extracted = extract_code_block(raw)

            # Prefer JSON grading_standard; fall back to raw block
            try:
                with timed(logger, "stage3_parse_gs", cA):
                    parsed_gs = safe_json_loads(extracted)
            except Exception:
                logger.debug("%s grading_standard not JSON; storing raw block", cA)
                parsed_gs = extracted

            item["grading_standard"] = parsed_gs
            ok = check_valid(item, stage=3, method=method)
            logger.info("%s parsed_ok=%s", cA, ok)
            if not ok:
                continue

            isgood, reason = review_washed(item, model_name, stage=3, method=method)
            loopcount = 0
            maxcount = 5
            while (not isgood) and (loopcount < maxcount):
                loopcount += 1
                cL = ctx_str(item=item, stage=3, attempt=attempt)
                logger.debug("%s reviewer_loop=%d reason=%s", cL, loopcount, _trunc(reason))

                history.append({"answer": raw or "", "feedback": reason or "", "judge": "invalid"})

                newprompt = get_wash_prompt_stage_with_history(org_item, history, 3, method=method)
                try:
                    raw = call_model_api(model_name, newprompt)
                    extracted = extract_code_block(raw)
                    try:
                        parsed_gs = safe_json_loads(extracted)
                    except Exception:
                        parsed_gs = extracted
                    item["grading_standard"] = parsed_gs
                    if not check_valid(item, 3, method=method):
                        logger.debug("%s re-parse invalid after reviewer loop", cL)
                        continue
                    isgood, reason = review_washed(item, model_name, stage=3, method=method)
                except Exception as e:
                    logger.warning("%s reviewer_loop exception: %s", cL, e)
                    continue

            if isgood:
                history.append({"answer": raw or "", "feedback": reason or "", "judge": "valid"})

            logger.info("%s done reviewer_good=%s loops=%d", cA, isgood, loopcount)
            return item

        except Exception as e:
            logger.error("%s attempt failed: %s\n%s", cA, e, traceback.format_exc())

    logger.warning("%s stage3 exhausted attempts", c)
    return None



def process_item(idx: int, orig_item: dict, stages: list, model: str, max_attempts: int, method: str):
    logger = logging.getLogger("washer")
    item = copy.deepcopy(orig_item)
    retry_count = 0
    logger.info("%s start stages=%s", ctx_str(idx=idx, item=item), stages)

    while retry_count < 3:
        result = None
        stage_deltas: dict[str, dict] = {}
        try:
            failed = False
            for stage in stages:
                logger.info("%s entering stage=%d retry=%d", ctx_str(idx=idx, item=item, stage=stage, retry=retry_count), stage, retry_count)
                before_snapshot = copy.deepcopy(item)

                if stage == 1:
                    result = process_stage1(item, model, max_attempts, orig_item)
                elif stage == 2:
                    result = process_stage2(item, model, max_attempts)
                elif stage == 3:
                    result = process_stage3(item, model, max_attempts, method)
                else:
                    raise ValueError(f"Unsupported stage: {stage}")

                if result is None:
                    logger.warning("%s stage %d returned None; resetting and retrying", ctx_str(idx=idx, item=item, stage=stage), stage)
                    item = copy.deepcopy(orig_item)
                    retry_count += 1
                    failed = True
                    stage_deltas = {}
                    break

                item = copy.deepcopy(result)
                fields = _STAGE_FIELDS.get(stage, [])
                stage_key = f"stage_{stage}"
                deltas = _collect_stage_deltas(before_snapshot, item, fields) if fields else {}
                stage_deltas[stage_key] = deltas

            if failed:
                continue
            if result is not None:
                stage_change_log = {k: v for k, v in stage_deltas.items()}
                extra_fields: dict[str, object] = {}
                for stage_key, changes in stage_change_log.items():
                    if not changes:
                        continue
                    stage_num = stage_key.split("_")[-1]
                    for field, delta in changes.items():
                        after_key = f"{field}_after_stage_{stage_num}"
                        extra_fields[after_key] = copy.deepcopy(delta["after"])

                if stage_change_log:
                    item["stage_change_log"] = stage_change_log
                for key, value in extra_fields.items():
                    item[key] = value

                logger.info("%s finished all stages retry=%d", ctx_str(idx=idx, item=item), retry_count)
                return item
        except Exception as e:
            logger.error("%s exception: %s\n%s", ctx_str(idx=idx, item=item), e, traceback.format_exc())
            item = copy.deepcopy(orig_item)
            retry_count += 1

    logger.error("%s failed after retries", ctx_str(idx=idx, item=orig_item))
    return None


def main():
    parser = argparse.ArgumentParser(
        description="Multi-stage JSON cleaning with optional parallelism and verification"
    )
    parser.add_argument("--raw", required=True)
    parser.add_argument("--out", required=True)
    parser.add_argument("--model", default="gpt-5")
    parser.add_argument("--start", type=int, default=0)
    parser.add_argument("--end", type=int)
    parser.add_argument("--max-attempts", type=int, default=5)
    parser.add_argument("--num-stages", nargs="+", type=int, default=[1,2,3],
                        help="Stages to run: choose from 1,2,3")
    parser.add_argument("--overwrite", action="store_true")
    parser.add_argument("--workers", type=int, default=1)
    parser.add_argument("--method", type=str, default="dag")
    parser.add_argument("--log-file", default=None, help="Write logs here (also keeps console logs)")
    parser.add_argument("--log-level", default="INFO", choices=["DEBUG","INFO","WARNING","ERROR","CRITICAL"])
    parser.add_argument("--json-logs", action="store_true")

    args = parser.parse_args()
    logger = setup_logging(args.log_file, args.log_level, args.json_logs)
    with timed(logger, "all", "[startup]"):
        logger.info("Run config raw=%s out=%s model=%s stages=%s start=%s end=%s workers=%s method=%s",
                    args.raw, args.out, args.model, args.num_stages, args.start, args.end, args.workers, args.method)

    bad = [s for s in args.num_stages if s not in (1,2,3)]
    if bad:
        raise ValueError(f"Unsupported stages: {bad}. Use any of 1,2,3.")

    with open(args.raw) as f:
        all_data = json.load(f)
    start = max(args.start, 0)
    end = min(args.end, len(all_data)) if args.end and args.end > 0 else len(all_data)
    items = all_data[start:end]

    final = f"{args.out}.json" if not args.out.endswith(".json") else args.out
    
    # 1) Load previously finalized results (resume by skipping their ids)
    existing_by_id: dict[str, dict] = {}
    if not args.overwrite:
        existing_final = _load_json_safe(final)
        if isinstance(existing_final, list):
            for it in existing_final:
                iid = _get_id(it)
                if iid:
                    existing_by_id[str(iid)] = it

    # 2) Prepare an index->item view for upgrading old ckpts
    items_by_index = {i: it for i, it in enumerate(items)}

    # 3) Prepare checkpoint storage (always id-keyed going forward)
    ckpt = f"{args.out}.tmp"
    if args.overwrite and os.path.exists(ckpt):
        os.remove(ckpt)
        ckpt_data_by_id = {}
    else:
        ckpt_data_by_id = {}
        if os.path.exists(ckpt):
            raw_ckpt = _load_json_safe(ckpt)
            ckpt_data_by_id = _upgrade_ckpt_to_id_keys(raw_ckpt, items_by_index)


    # 4) Build the list of remaining items (skip those already in final OR ckpt)
    remaining: list[tuple[int, dict]] = []
    for i, it in enumerate(items):
        iid = _get_id(it)
        if not iid:
            # If an item lacks id, we process it anyway (cannot dedupe).
            remaining.append((i, it))
            continue
        sid = str(iid)
        if sid in existing_by_id:
            continue
        if sid in ckpt_data_by_id and ckpt_data_by_id[sid] is not None:
            continue
        remaining.append((i, it))

    logger.info(
        "Loaded %d items, processing slice [%d:%d]. %d already in final, %d already in ckpt, %d remaining.",
        len(all_data), start, end, len(existing_by_id), len(ckpt_data_by_id), len(remaining)
    )


    if args.workers > 1 and remaining:
        with ThreadPoolExecutor(max_workers=args.workers) as pool:
            idx_to_item = {idx: item for idx, item in remaining}
            futures = {
                pool.submit(process_item, idx, item, args.num_stages, args.model, args.max_attempts, args.method): idx
                for idx, item in remaining
            }

            for fut in tqdm(as_completed(futures), total=len(futures), desc="Processing"):
                idx = futures[fut]
                try:
                    result = fut.result()
                except Exception as e:
                    logger.warning("[parallel] idx=%s produced None; storing None", idx)
                    result = None
                item = idx_to_item[idx]
                iid = _get_id(item)
                key = str(iid) if iid else str(idx)
                ckpt_data_by_id[key] = result
                tmp_path = ckpt + ".write"
                with open(tmp_path, "w") as f:
                    json.dump(ckpt_data_by_id, f, indent=2)
                os.replace(tmp_path, ckpt)


    else:
        logger.info("Using single worker")
        for idx, item in tqdm(remaining, desc="Processing", unit="item"):
            result = process_item(idx, item, args.num_stages, args.model, args.max_attempts, args.method)
            logger.info("result is: %s", result)
            iid = _get_id(item)
            key = str(iid) if iid else str(idx)  # fallback to index if no id
            ckpt_data_by_id[key] = result
            tmp_path = ckpt + ".write"
            with open(tmp_path, "w") as f:
                json.dump(ckpt_data_by_id, f, indent=2)
            os.replace(tmp_path, ckpt)
            
    # Merge: existing final + new ckpt, prefer newly produced results for any duplicate ids
    merged_by_id = dict(existing_by_id)
    for k, v in ckpt_data_by_id.items():
        if v is not None:
            merged_by_id[str(k)] = v

    # Build an ordered list:
    # 1) follow the input slice order for any item present in merged_by_id
    # 2) then append any extra items that were in the existing final but not in this slice
    ordered: list[dict] = []
    seen: set[str] = set()

    for it in items:
        iid = _get_id(it)
        if not iid:
            continue
        sid = str(iid)
        if sid in merged_by_id and sid not in seen:
            ordered.append(merged_by_id[sid])
            seen.add(sid)

    for sid, val in merged_by_id.items():
        if sid not in seen:
            ordered.append(val)
            seen.add(sid)

    with open(final, "w") as f:
        json.dump(ordered, f, indent=2)

    succ = sum(1 for v in ordered if v is not None)
    total_attempted = len(existing_by_id) + len([1 for v in ckpt_data_by_id.values() if v is not None])
    logger.info("Summary: written=%d, carried_from_existing=%d, newly_added=%d",
                len(ordered), len(existing_by_id), max(0, succ - len(existing_by_id)))

    # Cleanup
    if os.path.exists(ckpt):
        os.remove(ckpt)

    print(f"Done → {final}")

if __name__ == "__main__":
    main()
