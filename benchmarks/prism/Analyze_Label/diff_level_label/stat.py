#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import os
import json
from glob import glob
from collections import defaultdict

# 你要跑的模型列表
MODELS = [ "Qwen2.5-72B-Instruct-Turbo"]  
BASE = "/home/users/wanjiazh/AI4S_Bench"


def load_labels(label_dir):
    labels = {}
    for fp in glob(os.path.join(label_dir, "*.json")):
        try:
            with open(fp, "r", encoding="utf-8") as f:
                rec = json.load(f)
        except Exception:
            continue
        pid = os.path.basename(fp).split(".")[0].split("_")[-1]
        data = rec.get("data", {})
        scores = data.get("scores", {})
        labels[pid] = {
            "difficulty": data.get("difficulty"),
            "C1": scores.get("C1"),
            "C2": scores.get("C2"),
        }
    return labels


def load_grades(grade_dir):
    grades = {}
    for fp in glob(os.path.join(grade_dir, "*_grade.json")):
        try:
            with open(fp, "r", encoding="utf-8") as f:
                rec = json.load(f)
        except Exception:
            continue
        pid = str(rec.get("problem_id"))
        acc_val = 1.0 if float(rec.get("score", 0.0)) == 1.0 else 0.0
        score_val = float(rec.get("score", 0.0))
        grades[pid] = {"acc": acc_val, "score": score_val}
    return grades


def load_depths(depth_file):
    depths = {}
    with open(depth_file, "r", encoding="utf-8") as f:
        data = json.load(f)
    for rec in data:
        pid = str(rec["id"])
        depths[pid] = rec
    return depths


def aggregate(labels, grades, depths, key, transform=None):
    buckets = defaultdict(lambda: {"n": 0, "acc_sum": 0.0, "score_sum": 0.0})
    for pid, info in labels.items():
        if pid not in grades:
            continue
        value = info.get(key)
        if transform:
            value = transform(info, depths.get(pid, {}))
        if value is None:
            continue
        g = grades[pid]
        b = buckets[value]
        b["n"] += 1
        b["acc_sum"] += g["acc"]
        b["score_sum"] += g["score"]
    result = {}
    for k, agg in buckets.items():
        n = agg["n"]
        result[k] = {
            "n": n,
            "avg_acc": agg["acc_sum"] / n if n else 0.0,
            "avg_score": agg["score_sum"] / n if n else 0.0,
        }
    return result


if __name__ == "__main__":
    mode="text"
    for num in range(1, 8):  # 01–07
        for model in MODELS:
            print(f"\n=== Processing num={num}, model={model} ===")

            label_dir = f"{BASE}/Analyze_Label/diff_level_label/results/0{num}"
            grade_dir = f"{BASE}/main_exp/results_0{num}_dag/{mode}/{model}/grades/dag"
            depth_file = f"{BASE}/main_exp/0{num}_dag_depth.json"
            output_file = f"{BASE}/main_exp/results_0{num}_dag/{mode}/diff_results_0{num}_{model}_dag.json"

            labels = load_labels(label_dir)
            grades = load_grades(grade_dir)
            depths = load_depths(depth_file)

            results_dict = {}

            # === (C1+C2) 分桶 ===
            def bucket_c1_c2(info, depth_info):
                c1, c2 = info.get("C1"), info.get("C2")
                if c1 is None or c2 is None:
                    return None
                s = c1 + c2
                if s in [2, 3, 4]:
                    return "2-3-4"
                elif s == 5:
                    return "5"
                elif s == 6:
                    return "6"
                else:
                    return "other"

            results_dict["C1+C2"] = aggregate(labels, grades, depths, "C1C2", transform=bucket_c1_c2)

            # === entropy_complexity 分桶 ===
            def bucket_entropy(info, depth_info):
                val = depth_info.get("entropy_complexity")
                if val is None:
                    return None
                if val <= 3:
                    return "1"
                elif val > 7:
                    return "3"
                else:
                    return "2"

            results_dict["entropy_complexity"] = aggregate(labels, grades, depths, "entropy_complexity", transform=bucket_entropy)

            # === (C1+C2+entropy) 分桶 ===
            def bucket_c1c2_entropy(info, depth_info):
                c1, c2 = info.get("C1"), info.get("C2")
                if c1 is None or c2 is None:
                    return None
                s = c1 + c2

                ent = depth_info.get("entropy_complexity")
                if ent is None:
                    return None

                if ent < 3:
                    ent_bucket = 1
                elif ent > 7:
                    ent_bucket = 3
                else:
                    ent_bucket = 2

                val = s + ent_bucket * 0.5

                if 2.5 <= val <= 5.5:
                    return "E"
                elif 5.5 < val <= 6.5:
                    return "M"
                elif 6.5 < val <= 7.5:
                    return "H"
                else:
                    return "other"

            results_dict["C1+C2+entropy"] = aggregate(labels, grades, depths, "C1C2Entropy", transform=bucket_c1c2_entropy)

            # 保存结果
            os.makedirs(os.path.dirname(output_file), exist_ok=True)
            with open(output_file, "w", encoding="utf-8") as f:
                json.dump(results_dict, f, indent=2, ensure_ascii=False)

            print(f"Saved results to {output_file}")
