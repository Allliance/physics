#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import os
import json
from glob import glob
from collections import defaultdict

MODELS = [
    # "o4-mini",
    # "claude-sonnet-4-20250514",
    # # "deepseek-v3",
    # "deepseek-reasoner",
    # "deepseek-chat",
    # "gemini-2.5-flash", 
    # "gemini-2.5-pro", 
    # "gpt-4.1",
    # "gpt-4o-mini",
    # "gpt-5-high",
    # "gpt-5-mini-high",
    # "gpt-5-medium",
    # "gpt-5-mini-medium",
    # "gpt-5-low",
    # "gpt-5-mini-low",
    # "gpt-oss-20b",
    # "gpt-oss-120b",
    "grok-4",
    # "Llama-4-Scout-17B-16E-Instruct",
    # "Llama-3.3-70B-Instruct-Turbo",
    # "Qwen2.5-72B-Instruct-Turbo",
    # "Qwen3-235B-A22B-Instruct-2507-tput",
]
BASE = "/scratch/users/wanjiazh/AI4S_Bench"
MODE = "text"

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


# === 新增：读取响应时间（ms） ===
def load_times(response_dir):
    """
    读取 {response_dir} 下的 *_response.json，兼容以下情况：
    - 顶层是 dict 或 list
    - problem_id / model_call_ms 可能在嵌套字段里
    - 如果解析不到 problem_id，则从文件名如 '1001_response.json' 推断

    返回: dict[str, float]  {pid: avg_model_call_ms}
    """
    def find_key_recursive(obj, key):
        # 在任意嵌套结构中递归查找第一个 key
        if isinstance(obj, dict):
            if key in obj:
                return obj[key]
            for v in obj.values():
                r = find_key_recursive(v, key)
                if r is not None:
                    return r
        elif isinstance(obj, list):
            for it in obj:
                r = find_key_recursive(it, key)
                if r is not None:
                    return r
        return None

    def infer_pid_from_filename(fp):
        base = os.path.basename(fp)
        if "_response" in base:
            return base.split("_response")[0]
        return None

    # 汇总：同 pid 多条取平均
    ms_accumulator = defaultdict(lambda: {"sum": 0.0, "n": 0})

    pattern = os.path.join(response_dir, "*_response.json")
    for fp in glob(pattern):
        try:
            with open(fp, "r", encoding="utf-8") as f:
                rec = json.load(f)
        except Exception:
            continue

        # 尝试解析 problem_id 与 model_call_ms（递归找）
        pid = find_key_recursive(rec, "problem_id")
        if pid is None:
            pid = infer_pid_from_filename(fp)
        if pid is None:
            continue
        pid = str(pid)

        ms_val = find_key_recursive(rec, "model_call_ms")
        if ms_val is None:
            # 有些日志可能用 seconds；可选再尝试 'model_call_s' / 'latency_ms'
            ms_val = find_key_recursive(rec, "latency_ms")
            if ms_val is None:
                model_call_s = find_key_recursive(rec, "model_call_s")
                if model_call_s is not None:
                    try:
                        ms_val = float(model_call_s) * 1000.0
                    except Exception:
                        ms_val = None

        if ms_val is None:
            continue

        try:
            ms = float(ms_val)
        except Exception:
            continue

        ms_accumulator[pid]["sum"] += ms
        ms_accumulator[pid]["n"] += 1

    # 产出平均
    times = {}
    for pid, agg in ms_accumulator.items():
        if agg["n"] > 0:
            times[pid] = agg["sum"] / agg["n"]
    return times
def aggregate(labels, grades, depths, key, transform=None, times=None):
    """
    聚合各桶的 n / avg_acc / avg_score，并新增 avg_ms（平均响应时间毫秒）和 ms_n（计数）。
    times: dict {pid: ms}
    """
    buckets = defaultdict(lambda: {
        "n": 0, "acc_sum": 0.0, "score_sum": 0.0,
        "ms_sum": 0.0, "ms_n": 0
    })
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
        if times is not None and pid in times:
            b["ms_sum"] += times[pid]
            b["ms_n"] += 1

    result = {}
    for k, agg in buckets.items():
        n = agg["n"]
        ms_n = agg["ms_n"]
        result[k] = {
            "n": n,
            "avg_acc": agg["acc_sum"] / n if n else 0.0,
            "avg_score": agg["score_sum"] / n if n else 0.0,
            "avg_ms": agg["ms_sum"] / ms_n if ms_n else None,
            "ms_n": ms_n,
        }
    return result


def load_standard_counts(standard_file):
    """
    支持格式：
    1) {"E": 69, "M": 115, "H": 135}
    2) {"E": [...], "M": [...], "H": [...]}
    3) {"C1+C2+entropy": {"E": {"n": ...}, "M": {"n": ...}, "H": {"n": ...}}}
    """
    if not os.path.exists(standard_file):
        return None

    with open(standard_file, "r", encoding="utf-8") as f:
        data = json.load(f)

    # 格式 1：直接给计数
    if all(k in data for k in ("E", "M", "H")) and all(isinstance(data[k], int) for k in ("E", "M", "H")):
        return {"E": data["E"], "M": data["M"], "H": data["H"]}

    # 格式 2：给题目列表
    if all(k in data for k in ("E", "M", "H")) and all(isinstance(data[k], list) for k in ("E", "M", "H")):
        return {"E": len(data["E"]), "M": len(data["M"]), "H": len(data["H"])}

    # 格式 3：嵌套结构
    if "C1+C2+entropy" in data and isinstance(data["C1+C2+entropy"], dict):
        sub = data["C1+C2+entropy"]
        out = {}
        for k in ("E", "M", "H"):
            v = sub.get(k, {})
            if isinstance(v, dict) and "n" in v:
                out[k] = int(v["n"])
        if len(out) == 3:
            return out

    # 其它未知格式 -> 返回 None
    return None


def compare_counts(actual_counts, expected_counts):
    """
    actual_counts: {"E": n1, "M": n2, "H": n3}
    expected_counts: 同结构
    """
    diff = {}
    ok = True
    for k in ("E", "M", "H"):
        a = int(actual_counts.get(k, 0))
        e = int(expected_counts.get(k, 0))
        d = a - e
        diff[k] = {"actual": a, "expected": e, "delta": d}
        if d != 0:
            ok = False
    return ok, diff


if __name__ == "__main__":
    for num in range(1, 8):  # 01–07
        print(f"\n=== Processing num={num} ===")
        standard_file = f"/scratch/users/wanjiazh/AI4S_Bench/main_exp_v2/results_0{num}_cleaned_dag/text/diff_results_0{num}_gpt-4.1_dag.json"
        std_counts = load_standard_counts(standard_file)

        if std_counts is None:
            print(f"[WARN] No standard file or unrecognized format: {standard_file}")

        for model in MODELS:
            print(f"\n=== model={model} ===")

            label_dir = f"{BASE}/Analyze_Label/diff_level_label/results/0{num}"
            grade_dir = f"{BASE}/main_exp_v2/results_0{num}_cleaned_dag/{MODE}/{model}/grades/dag"
            depth_file = f"{BASE}/main_exp_v2/0{num}_dag_depth.json"
            output_file = f"{BASE}/main_exp_v2/results_0{num}_cleaned_dag/{MODE}/diff_results_0{num}_{model}_dag.json"
            response_dir = f"{BASE}/main_exp_v2/results_0{num}_cleaned_dag/{MODE}/{model}/responses"

            labels = load_labels(label_dir)
            grades = load_grades(grade_dir)
            depths = load_depths(depth_file)
            times = load_times(response_dir)  # 新增：加载响应时间
            print(grade_dir)
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

            results_dict["C1+C2"] = aggregate(labels, grades, depths, "C1C2", transform=bucket_c1_c2, times=times)

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

            results_dict["entropy_complexity"] = aggregate(labels, grades, depths, "entropy_complexity", transform=bucket_entropy, times=times)

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

                # 注意：这里的线性组合与阈值是你现有逻辑，保持不变
                val = s + ent_bucket * 0.5

                if 2.5 <= val <= 5.5:
                    return "E"
                elif 5.5 < val <= 6.5:
                    return "M"
                elif 6.5 < val <= 7.5:
                    return "H"
                else:
                    return "other"

            c1c2ent = aggregate(labels, grades, depths, "C1C2Entropy", transform=bucket_c1c2_entropy, times=times)
            results_dict["C1+C2+entropy"] = c1c2ent

            # === 与标准计数进行一致性校验（仅针对 E/M/H 桶） ===
            actual_counts = {
                "E": c1c2ent.get("E", {}).get("n", 0),
                "M": c1c2ent.get("M", {}).get("n", 0),
                "H": c1c2ent.get("H", {}).get("n", 0),
            }

            consistency = {
                "standard_file": standard_file,
                "actual_counts": actual_counts,
                "expected_counts": std_counts if std_counts is not None else {},
                "ok": True,
                "diff": {},
                "note": "",
            }

            if std_counts is None:
                consistency["ok"] = False
                consistency["note"] = "No standard counts available; skipped strict check."
                print(f"[SKIP] num=0{num}, model={model}: no standard counts")
            else:
                ok, diff = compare_counts(actual_counts, std_counts)
                consistency["ok"] = ok
                consistency["diff"] = diff
                if ok:
                    print(f"[PASS] num=0{num}, model={model}: E/M/H counts match the standard.")
                else:
                    print(f"[FAIL] num=0{num}, model={model}: E/M/H counts mismatch!")
                    for k, v in diff.items():
                        if v["delta"] != 0:
                            print(f"  - {k}: actual={v['actual']}, expected={v['expected']}, delta={v['delta']}")
                    consistency["note"] = "Counts mismatch. 说明题目生成可能有遗漏或分桶逻辑不一致。"

            # 保存结果（不写入 consistency，以保持与你原始输出结构兼容；如需写入可解除下面注释）
            # results_dict["consistency_check"] = consistency

            os.makedirs(os.path.dirname(output_file), exist_ok=True)
            with open(output_file, "w", encoding="utf-8") as f:
                json.dump(results_dict, f, indent=2, ensure_ascii=False)

            print(f"Saved results to {output_file}")