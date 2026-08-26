#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import os
import json
from collections import Counter

VALID_LABELS = {"DAE", "PTAE", "MPUE", "CAE", "VRE", "DCE", "UDE"}

# claude-sonnet-4-20250514
base_dir = "/home/users/wanjiazh/AI4S_Bench/Analyze_Label/Analysis/sol_error"
def extract_record(obj):
    """提取 JSON 文件中的 primary_error 和 secondary_errors（兼容 {..} 与 {"data":{..}}）"""
    if isinstance(obj, dict) and "data" in obj and isinstance(obj["data"], dict):
        obj = obj["data"]
    if not isinstance(obj, dict):
        return None, []
    primary = obj.get("primary_error")
    secondary = obj.get("secondary_errors", [])
    if not isinstance(primary, str):
        primary = None
    if not isinstance(secondary, list):
        secondary = []
    return primary, [s for s in secondary if isinstance(s, str)]

def iter_json_files(path):
    if os.path.isdir(path):
        for root, _, files in os.walk(path):
            for fn in files:
                if fn.lower().endswith(".json"):
                    yield os.path.join(root, fn)

def analyze_dirs(base_dir, output_json):
    all_results = {}

    # overall 汇总累加器
    overall_primary = Counter()
    overall_secondary = Counter()
    overall_files_scanned = 0
    overall_files_parsed = 0
    overall_records_found = 0

    for i in range(1, 8):  # 01 到 07
        dir_path = os.path.join(base_dir, f"{MODEL}", f"results_{i:02d}_dag" )
        if not os.path.exists(dir_path):
            # 也记录个空壳，方便查看哪些目录缺失
            all_results[f"results_{i:02d}_dag"] = {
                "files_scanned": 0,
                "files_parsed": 0,
                "records_found": 0,
                "primary_counts": {},
                "secondary_counts": {},
                "dir_exists": False,
                "dir_path": dir_path,
            }
            continue

        primary_counter = Counter()
        secondary_counter = Counter()
        files_seen = 0
        files_ok = 0
        records_found = 0

        for fp in iter_json_files(dir_path):
            files_seen += 1
            try:
                with open(fp, "r", encoding="utf-8") as f:
                    data = json.load(f)
            except Exception:
                continue  # 跳过坏文件

            files_ok += 1
            primary, secondary = extract_record(data)
            if  primary is None and secondary==[]:
                os.remove(fp)
                print(f"delete {fp}")
            if primary is not None or secondary:
                records_found += 1

            if primary:
                if primary in VALID_LABELS:
                    primary_counter[primary] += 1
                else:
                    primary_counter[f"UNKNOWN:{primary}"] += 1

            for s in secondary:
                if s in VALID_LABELS:
                    secondary_counter[s] += 1
                else:
                    secondary_counter[f"UNKNOWN:{s}"] += 1

        # 保存单目录结果
        all_results[f"results_{i:02d}_dag"] = {
            "files_scanned": files_seen,
            "files_parsed": files_ok,
            "records_found": records_found,
            "primary_counts": dict(primary_counter),
            "secondary_counts": dict(secondary_counter),
            "dir_exists": True,
            "dir_path": dir_path,
        }

        # 汇总到 overall
        overall_primary.update(primary_counter)
        overall_secondary.update(secondary_counter)
        overall_files_scanned += files_seen
        overall_files_parsed += files_ok
        overall_records_found += records_found

    # 组织 overall 结果
    all_results["overall"] = {
        "files_scanned": overall_files_scanned,
        "files_parsed": overall_files_parsed,
        "records_found": overall_records_found,
        "primary_counts": dict(overall_primary),
        "secondary_counts": dict(overall_secondary),
    }

    # 写入 JSON
    with open(output_json, "w", encoding="utf-8") as f:
        json.dump(all_results, f, indent=2, ensure_ascii=False)

if __name__ == "__main__":
    for MODEL in ["gpt-5-high"]:
        output_json = os.path.join(base_dir, f"{MODEL}","summary_results.json")
        analyze_dirs(base_dir, output_json)
        print(f"统计结果已保存到: {output_json}")