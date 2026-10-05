#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import os
import json
import math

# ==== 配置 ====
base = "/home/users/wanjiazh/AI4S_Bench/main_exp"

# 复杂度阈值（基于 PCSC：Performance-Calibrated Structural Complexity）
# Easy:   C ≤ T1
# Medium: T1 < C ≤ T2
# Hard:   C > T2
T1 = 1.25
T2 = 2.5

# 与生成 PCSC 时保持一致（若文件里已给出 PCSC，则不会用到这个）
LAMBDA = 0.40  # PCSC = λ * entropy + (1-λ) * (1 - EAS)

def _is_num(x):
    return isinstance(x, (int, float)) and not isinstance(x, bool)

def bucket_by_pcsc(C: float) -> str:
    if C <= T1:
        return "Easy"
    elif C <= T2:
        return "Medium"
    else:
        return "Hard"

def safe_entropy(entry: dict) -> float:
    """优先读取 'entropy_complexity'；缺失则用结构近似回算。"""
    if _is_num(entry.get("entropy_complexity")):
        return float(entry["entropy_complexity"])
    depth = float(entry.get("depth", 0.0) or 0.0)
    num_nodes = int(entry.get("num_nodes", 0) or 0)
    num_edges = int(entry.get("num_edges", 0) or 0)
    num_roots = int(entry.get("num_roots", 0) or 0)
    denom = max(1, (num_nodes - num_roots))
    branching = num_edges / denom
    return depth * math.log1p(branching)

def safe_pcsc(entry: dict) -> float:
    """
    读取/回退得到 PCSC：
      1) 若有 'PCSC' 则直接用；
      2) 若无但有 'entropy_complexity' 与 'EAS'，则用同样的 λ 组合；
      3) 否则退回到基于 entropy 的近似（弱替代）。
    """
    if _is_num(entry.get("PCSC")):
        return float(entry["PCSC"])
    ent = safe_entropy(entry)
    eas = entry.get("EAS", None)
    if _is_num(eas):
        return LAMBDA * ent + (1.0 - LAMBDA) * (1.0 - float(eas))
    return ent

# ===== 合并 01–07（按 PCSC 统计）=====
perfile_stats = {}   # 每个文件的 E/M/H + 平均度量
total_probs = 0
sum_pcsc = 0.0
sum_entropy = 0.0
sum_eas = 0.0
sum_depth = 0.0

easy_all = 0
medium_all = 0
hard_all = 0

# 全局按桶累计（用于计算每个难度档内部的平均 PCSC/Entropy/EAS/Depth）
bucket_aggs = {
    "Easy":   {"n": 0, "pcsc_sum": 0.0, "ent_sum": 0.0, "eas_sum": 0.0, "depth_sum": 0.0},
    "Medium": {"n": 0, "pcsc_sum": 0.0, "ent_sum": 0.0, "eas_sum": 0.0, "depth_sum": 0.0},
    "Hard":   {"n": 0, "pcsc_sum": 0.0, "ent_sum": 0.0, "eas_sum": 0.0, "depth_sum": 0.0},
}

for i in range(1, 8):  # 01-07
    json_path = os.path.join(base, f"{i:02d}_dag_depth.json")
    if not os.path.exists(json_path):
        continue

    with open(json_path, "r", encoding="utf-8") as f:
        data = json.load(f)

    e = m = h = 0
    file_sum_pcsc = 0.0
    file_sum_entropy = 0.0
    file_sum_eas = 0.0
    file_sum_depth = 0.0
    file_total = 0

    for entry in data:
        C_pcsc = safe_pcsc(entry)
        C_ent = safe_entropy(entry)
        E_eas = float(entry.get("EAS", 0.0) or 0.0)
        D = float(entry.get("depth", 0.0) or 0.0)

        file_sum_pcsc += C_pcsc
        file_sum_entropy += C_ent
        file_sum_eas += E_eas
        file_sum_depth += D
        file_total += 1

        label = bucket_by_pcsc(C_pcsc)
        if label == "Easy":
            e += 1
        elif label == "Medium":
            m += 1
        else:
            h += 1

        # --- 全局按桶累计 ---
        b = bucket_aggs[label]
        b["n"] += 1
        b["pcsc_sum"]  += C_pcsc
        b["ent_sum"]   += C_ent
        b["eas_sum"]   += E_eas
        b["depth_sum"] += D

    perfile_stats[f"{i:02d}"] = {
        "Easy": e,
        "Medium": m,
        "Hard": h,
        "Total": file_total,
        "AvgPCSC": (file_sum_pcsc / file_total) if file_total else 0.0,
        "AvgEntropy": (file_sum_entropy / file_total) if file_total else 0.0,
        "AvgEAS": (file_sum_eas / file_total) if file_total else 0.0,
        "AvgDepth": (file_sum_depth / file_total) if file_total else 0.0,
    }

    total_probs += file_total
    sum_pcsc += file_sum_pcsc
    sum_entropy += file_sum_entropy
    sum_eas += file_sum_eas
    sum_depth += file_sum_depth
    easy_all += e
    medium_all += m
    hard_all += h

# 全局统计
avg_pcsc = (sum_pcsc / total_probs) if total_probs > 0 else 0.0
avg_entropy = (sum_entropy / total_probs) if total_probs > 0 else 0.0
avg_eas = (sum_eas / total_probs) if total_probs > 0 else 0.0
avg_depth = (sum_depth / total_probs) if total_probs > 0 else 0.0

# 每个难度档内部的平均
bucket_means = {}
for name, agg in bucket_aggs.items():
    n = agg["n"]
    bucket_means[name] = {
        "n": n,
        "avg_pcsc":  (agg["pcsc_sum"]  / n) if n else 0.0,
        "avg_entropy": (agg["ent_sum"]   / n) if n else 0.0,
        "avg_eas":    (agg["eas_sum"]   / n) if n else 0.0,
        "avg_depth":  (agg["depth_sum"] / n) if n else 0.0,
    }

# 输出到文件（PCSC 命名）
out_file = os.path.join(base, "all_dag_pcsc_stats.txt")
with open(out_file, "w", encoding="utf-8") as f:
    f.write(f"# PCSC-based bucketing (T1={T1}, T2={T2})\n")
    f.write(f"Average PCSC (overall): {avg_pcsc:.4f}\n")
    f.write(f"Average entropy (overall): {avg_entropy:.4f}\n")
    f.write(f"Average EAS (overall): {avg_eas:.4f}\n")
    f.write(f"Average depth (overall): {avg_depth:.4f}\n")
    f.write(f"Total problems: {total_probs}\n")
    f.write(f"Easy (≤{T1}): {easy_all}\n")
    f.write(f"Medium ({T1}–{T2}]: {medium_all}\n")
    f.write(f"Hard (>{T2}): {hard_all}\n\n")

    f.write("# Per-file E/M/H breakdown by PCSC\n")
    f.write(f"Easy: C ≤ {T1};  Medium: {T1} < C ≤ {T2};  Hard: C > {T2}\n")
    for k in sorted(perfile_stats.keys()):
        row = perfile_stats[k]
        if row["Total"] > 0:
            e_pct = row["Easy"] / row["Total"] * 100
            m_pct = row["Medium"] / row["Total"] * 100
            h_pct = row["Hard"] / row["Total"] * 100
        else:
            e_pct = m_pct = h_pct = 0.0
        f.write(
            f"{k}: Easy={row['Easy']}({e_pct:.2f}%), "
            f"Medium={row['Medium']}({m_pct:.2f}%), "
            f"Hard={row['Hard']}({h_pct:.2f}%), "
            f"Total={row['Total']}, "
            f"AvgPCSC={row['AvgPCSC']:.4f}, "
            f"AvgEntropy={row['AvgEntropy']:.4f}, "
            f"AvgEAS={row['AvgEAS']:.4f}, "
            f"AvgDepth={row['AvgDepth']:.4f}\n"
        )

    f.write("\n# Bucket-level averages (across ALL files)\n")
    for name in ["Easy", "Medium", "Hard"]:
        bm = bucket_means[name]
        f.write(
            f"{name}: n={bm['n']}, "
            f"avg_pcsc={bm['avg_pcsc']:.4f}, "
            f"avg_entropy={bm['avg_entropy']:.4f}, "
            f"avg_eas={bm['avg_eas']:.4f}, "
            f"avg_depth={bm['avg_depth']:.4f}\n"
        )

    # 总计行
    if total_probs > 0:
        eP = easy_all / total_probs * 100
        mP = medium_all / total_probs * 100
        hP = hard_all / total_probs * 100
    else:
        eP = mP = hP = 0.0
    f.write(
        f"\nTOTAL: Easy={easy_all}({eP:.2f}%), "
        f"Medium={medium_all}({mP:.2f}%), "
        f"Hard={hard_all}({hP:.2f}%), "
        f"Total={total_probs}, "
        f"AvgPCSC={avg_pcsc:.4f}, AvgEntropy={avg_entropy:.4f}, "
        f"AvgEAS={avg_eas:.4f}, AvgDepth={avg_depth:.4f}\n"
    )

# 控制台输出
print(f"PCSC thresholds: Easy ≤ {T1}, Medium ({T1}, {T2}], Hard > {T2}")
for k in sorted(perfile_stats.keys()):
    row = perfile_stats[k]
    if row["Total"] > 0:
        e_pct = row["Easy"] / row["Total"] * 100
        m_pct = row["Medium"] / row["Total"] * 100
        h_pct = row["Hard"] / row["Total"] * 100
    else:
        e_pct = m_pct = h_pct = 0.0
    print(
        f"{k}: Easy={row['Easy']}({e_pct:.2f}%), "
        f"Medium={row['Medium']}({m_pct:.2f}%), "
        f"Hard={row['Hard']}({h_pct:.2f}%), "
        f"Total={row['Total']}, "
        f"AvgPCSC={row['AvgPCSC']:.4f}, "
        f"AvgEntropy={row['AvgEntropy']:.4f}, "
        f"AvgEAS={row['AvgEAS']:.4f}, "
        f"AvgDepth={row['AvgDepth']:.4f}"
    )

print("\n# Bucket-level averages (across ALL files)")
for name in ["Easy", "Medium", "Hard"]:
    bm = bucket_aggs[name]
    n = bm["n"]
    print(
        f"{name}: n={n}, "
        f"avg_pcsc={(bm['pcsc_sum']/n if n else 0.0):.4f}, "
        f"avg_entropy={(bm['ent_sum']/n if n else 0.0):.4f}, "
        f"avg_eas={(bm['eas_sum']/n if n else 0.0):.4f}, "
        f"avg_depth={(bm['depth_sum']/n if n else 0.0):.4f}"
    )

print(
    f"\nTOTAL: Easy={easy_all}({(easy_all/total_probs*100 if total_probs else 0.0):.2f}%), "
    f"Medium={medium_all}({(medium_all/total_probs*100 if total_probs else 0.0):.2f}%), "
    f"Hard={hard_all}({(hard_all/total_probs*100 if total_probs else 0.0):.2f}%), "
    f"Total={total_probs}, "
    f"AvgPCSC={avg_pcsc:.4f}, AvgEntropy={avg_entropy:.4f}, AvgEAS={avg_eas:.4f}, AvgDepth={avg_depth:.4f}"
)
print(f"合并完成，结果保存到 {out_file}")
