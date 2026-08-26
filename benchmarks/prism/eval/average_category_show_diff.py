#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import os
import json
from glob import glob
from collections import defaultdict

BASE = "/scratch/users/wanjiazh/AI4S_Bench/main_exp_v2"
MODE = "text"
MODELS = [
    "deepseek-chat",
    "Qwen2.5-72B-Instruct-Turbo",
    "Llama-3.3-70B-Instruct-Turbo",
    "Llama-4-Scout-17B-16E-Instruct",
    
    "deepseek-reasoner",
    "gpt-oss-20b",
    "gpt-oss-120b",
    "Qwen3-235B-A22B-Instruct-2507-tput",
    
    "claude-sonnet-4-20250514",
    "gpt-4o-mini",
    "gpt-4.1",
    
    
    "gemini-2.5-flash", 
    "gemini-2.5-pro", 
    
    "gpt-5-high",
    "gpt-5-medium",
    "gpt-5-low",
    "gpt-5-mini-high",
    "gpt-5-mini-medium",
    "gpt-5-mini-low",
    "grok-4",
    "o4-mini", 
]

def weighted_average(files):
    """
    对每个 section/bucket 做加权聚合：
      - acc / score：按 n 加权
      - ms（响应时间）：按 ms_n 加权
    并生成 "C1+C2+entropy" 的整体加权结果（E/M/H 合并）。
    """
    merged = {}

    for fp in files:
        with open(fp, "r", encoding="utf-8") as f:
            data = json.load(f)

        for section, secdata in data.items():
            if section not in merged:
                merged[section] = defaultdict(lambda: {
                    "n_sum": 0,
                    "acc_weighted_sum": 0.0,
                    "score_weighted_sum": 0.0,
                    "ms_n_sum": 0,
                    "ms_weighted_sum": 0.0,
                    "count_files": 0
                })

            for bucket, vals in secdata.items():
                # 兼容缺失字段
                n = int(vals.get("n", 0))
                avg_acc = float(vals.get("avg_acc", 0.0))
                avg_score = float(vals.get("avg_score", 0.0))

                # 响应时间字段（来自上游脚本的聚合）
                ms_n = int(vals.get("ms_n", 0)) if isinstance(vals.get("ms_n", 0), (int, float)) else 0
                avg_ms = vals.get("avg_ms", None)
                try:
                    avg_ms = float(avg_ms) if avg_ms is not None else None
                except Exception:
                    avg_ms = None

                agg = merged[section][bucket]
                agg["n_sum"] += n
                agg["acc_weighted_sum"] += avg_acc * n
                agg["score_weighted_sum"] += avg_score * n
                agg["count_files"] += 1

                if avg_ms is not None and ms_n > 0:
                    # 注意 avg_ms 是对该文件的桶内按 ms_n 平均后的结果
                    # 合并层面要再按 ms_n 做一次加权
                    agg["ms_n_sum"] += ms_n
                    agg["ms_weighted_sum"] += avg_ms * ms_n

    # 归一化：得到每个 section/bucket 的加权结果
    final = {}
    for section, secdata in merged.items():
        final[section] = {}
        for bucket, acc in secdata.items():
            n_sum = acc["n_sum"]
            ms_n_sum = acc["ms_n_sum"]

            if n_sum > 0:
                avg_acc = round(acc["acc_weighted_sum"] / n_sum * 100, 2)
                avg_score = round(acc["score_weighted_sum"] / n_sum * 100, 2)
            else:
                avg_acc = 0.0
                avg_score = 0.0

            if ms_n_sum > 0:
                avg_ms = round(acc["ms_weighted_sum"] / ms_n_sum, 2)
            else:
                avg_ms = None

            final[section][bucket] = {
                "n_total": n_sum,
                "avg_acc": avg_acc,       # %
                "avg_score": avg_score,   # %
                "avg_ms": avg_ms,         # 毫秒（按 ms_n 加权）
                "ms_n_total": ms_n_sum,   # 计入时间样本数
                "count_files": acc["count_files"]
            }

    # === 追加：对 "C1+C2+entropy" 做整体加权平均（E/M/H 合并）===
    sec = "C1+C2+entropy"
    if sec in final:
        buckets = final[sec]
        need = ["E", "M", "H"]
        n_total = sum(buckets[b]["n_total"] for b in need if b in buckets)
        ms_n_total = sum(buckets[b]["ms_n_total"] for b in need if b in buckets)

        if n_total > 0:
            acc_num = sum(buckets[b]["avg_acc"] * buckets[b]["n_total"] for b in need if b in buckets)
            score_num = sum(buckets[b]["avg_score"] * buckets[b]["n_total"] for b in need if b in buckets)
            overall_acc = round(acc_num / n_total, 2)
            overall_score = round(score_num / n_total, 2)
        else:
            overall_acc = 0.0
            overall_score = 0.0

        if ms_n_total > 0:
            ms_num = sum(
                (buckets[b]["avg_ms"] * buckets[b]["ms_n_total"])
                for b in need if b in buckets and buckets[b]["avg_ms"] is not None
            )
            overall_ms = round(ms_num / ms_n_total, 2)
        else:
            overall_ms = None

        overall = {
            "n_total": int(n_total),
            "avg_acc": overall_acc,
            "avg_score": overall_score,
            "avg_ms": overall_ms,
            "ms_n_total": int(ms_n_total)
        }
        final["_overall_C1+C2+entropy"] = overall

    return final


if __name__ == "__main__":
    for model in MODELS:
        pattern = os.path.join(BASE, "results_0*_dag", MODE, f"diff_results_*_{model}_dag.json")
        # print(pattern)
        out_dir = os.path.join(BASE, "all_category", MODE)
        os.makedirs(out_dir, exist_ok=True)
        output_file = os.path.join(out_dir, f"all_category_results_weighted_{model}.json")

        files = sorted(glob(pattern))
        print("========================")
        print(f"[{model}] Found {len(files)} files")
        results = weighted_average(files)

        with open(output_file, "w", encoding="utf-8") as f:
            json.dump(results, f, indent=2, ensure_ascii=False)

        # # 只打印整体加权平均的小结
        # if "C1+C2+entropy" in results:
        #     print("E: ", json.dumps(results["C1+C2+entropy"].get("E", {}), ensure_ascii=False))
        #     print("M: ", json.dumps(results["C1+C2+entropy"].get("M", {}), ensure_ascii=False))
        #     print("H: ", json.dumps(results["C1+C2+entropy"].get("H", {}), ensure_ascii=False))

        # if "_overall_C1+C2+entropy" in results:
        #     print(f"[{model}] Overall (C1+C2+entropy):",
        #           json.dumps(results["_overall_C1+C2+entropy"], ensure_ascii=False))
        # else:
        #     print(f"[{model}] No overall (C1+C2+entropy) computed.")

        # LaTeX 行（注意引号）
        try:
            e = results["C1+C2+entropy"]["E"]
            m = results["C1+C2+entropy"]["M"]
            h = results["C1+C2+entropy"]["H"]
            ov = results["_overall_C1+C2+entropy"]
            print(
                f"&{e['avg_acc']}&{e['avg_score']}&{(e.get('avg_ms')/1000):.2f}  "
                f"&{m['avg_acc']}&{m['avg_score']}&{m.get('avg_ms')/1000:.2f}  "
                f"&{h['avg_acc']}&{h['avg_score']}&{h.get('avg_ms')/1000:.2f}  "
                f"&{ov['avg_acc']}&{ov['avg_score']}&{ov.get('avg_ms')/1000:.2f}\\\\"
                # f"  % avg_ms: E={e.get('avg_ms')}, M={m.get('avg_ms')}, H={h.get('avg_ms')}, Overall={ov.get('avg_ms')}"
            )
        except KeyError:
            pass