#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
Bucket problems by a precomputed PCSC (Performance-Calibrated Structural Complexity)
and report avg accuracy/score per bucket.

We LOAD 'PCSC' from the depth JSON (field: "PCSC").
If missing, we fallback to: PCSC ≈ λ * entropy_complexity + (1-λ) * (1 - EAS),
and if EAS also missing, fallback to entropy_complexity (weak proxy).

Manual thresholds on PCSC:
  - Easy:   C <= T1
  - Medium: T1 < C <= T2
  - Hard:   C > T2
"""

import os
import json
from glob import glob

# ---- Fixed paths ----
GRADES_DIR = "/home/users/wanjiazh/AI4S_Bench/main_exp/results_03_dag/text/gpt-4.1/grades/dag"
DEPTH_PATH  = "/home/users/wanjiazh/AI4S_Bench/main_exp/03_dag_depth.json"

# ---- Manual thresholds on PCSC ----
T1 = 1.25  # Easy/Medium cutoff
T2 = 2.5   # Medium/Hard cutoff
LAMBDA = 0.40  # only used for fallback PCSC reconstruction


def _is_num(x):
    return isinstance(x, (int, float)) and not isinstance(x, bool)


def load_depth_and_pcsc(path):
    """
    Load [{id, depth, PCSC, entropy_complexity, EAS, ...}, ...] and return:
      stats[id_str] = {"depth": int, "pcsc": float}

    PCSC preferred; if missing, reconstruct from entropy/EAS if available.
    """
    with open(path, "r", encoding="utf-8") as f:
        data = json.load(f)

    stats = {}
    for item in data:
        if "id" not in item:
            continue
        pid = str(item["id"])
        depth = int(item.get("depth", 0) or 0)

        if _is_num(item.get("PCSC")):
            pcsc = float(item["PCSC"])
        else:
            # Fallbacks
            ent = item.get("entropy_complexity", None)
            eas = item.get("EAS", None)
            if _is_num(ent) and _is_num(eas):
                pcsc = LAMBDA * float(ent) + (1.0 - LAMBDA) * (1.0 - float(eas))
            elif _is_num(ent):
                pcsc = float(ent)  # weakest fallback
            else:
                pcsc = None

        stats[pid] = {"depth": depth, "pcsc": pcsc}
    return stats


def bucket_by_pcsc(C, t1, t2):
    if C <= t1:
        return "Easy"
    if C <= t2:
        return "Medium"
    return "Hard"


def summarize():
    stats = load_depth_and_pcsc(DEPTH_PATH)
    files = sorted(glob(os.path.join(GRADES_DIR, "*grade.json")))

    buckets = {
        "Easy":   {"n": 0, "acc_sum": 0.0, "score_sum": 0.0, "depth_sum": 0.0, "comp_sum": 0.0},
        "Medium": {"n": 0, "acc_sum": 0.0, "score_sum": 0.0, "depth_sum": 0.0, "comp_sum": 0.0},
        "Hard":   {"n": 0, "acc_sum": 0.0, "score_sum": 0.0, "depth_sum": 0.0, "comp_sum": 0.0},
    }
    overall = {"n": 0, "acc_sum": 0.0, "score_sum": 0.0, "depth_sum": 0.0, "comp_sum": 0.0}

    skipped_missing_pcsc = 0
    for fp in files:
        with open(fp, "r", encoding="utf-8") as f:
            rec = json.load(f)

        pid = str(rec["problem_id"])
        st = stats.get(pid)
        if st is None:
            # no DAG stats entry for this problem id
            continue

        C = st.get("pcsc")
        if not _is_num(C):
            # PCSC not available; skip this record
            skipped_missing_pcsc += 1
            continue

        depth = st["depth"]
        bucket = bucket_by_pcsc(C, T1, T2)

        acc_val = 1.0 if rec.get("is_correct") else 0.0
        score_val = float(rec.get("score", 0.0))

        b = buckets[bucket]
        b["n"] += 1
        b["acc_sum"] += acc_val
        b["score_sum"] += score_val
        b["depth_sum"] += depth
        b["comp_sum"] += C

        overall["n"] += 1
        overall["acc_sum"] += acc_val
        overall["score_sum"] += score_val
        overall["depth_sum"] += depth
        overall["comp_sum"] += C

    result = {}
    for name, agg in buckets.items():
        n = agg["n"]
        result[name] = {
            "n": n,
            "avg_acc":       (agg["acc_sum"]   / n) if n else 0.0,
            "avg_score":     (agg["score_sum"] / n) if n else 0.0,
            "avg_depth":     (agg["depth_sum"] / n) if n else 0.0,
            "avg_pcsc":      (agg["comp_sum"]  / n) if n else 0.0,
        }

    n_all = overall["n"]
    result["Overall"] = {
        "n": n_all,
        "avg_acc":       (overall["acc_sum"]   / n_all) if n_all else 0.0,
        "avg_score":     (overall["score_sum"] / n_all) if n_all else 0.0,
        "avg_depth":     (overall["depth_sum"] / n_all) if n_all else 0.0,
        "avg_pcsc":      (overall["comp_sum"]  / n_all) if n_all else 0.0,
    }

    result["_thresholds"] = {"T1_easy_max": T1, "T2_medium_max": T2}
    result["_skipped_missing_pcsc"] = skipped_missing_pcsc

    print(json.dumps(result, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    summarize()
