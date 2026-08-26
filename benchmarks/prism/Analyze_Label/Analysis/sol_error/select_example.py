#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import os
import json

base_dir = "/home/users/wanjiazh/AI4S_Bench/Analyze_Label/Analysis/sol_error/Qwen3-235B-A22B-Instruct-2507-tput"

# 要遍历的子目录 results_01_dag ~ results_07_dag
for i in range(1, 8):
    results_dir = os.path.join(base_dir, f"results_0{i}_dag")
    if not os.path.exists(results_dir):
        continue

    for root, _, files in os.walk(results_dir):
        for f in files:
            if f.endswith(".json"):
                file_path = os.path.join(root, f)
                try:
                    with open(file_path, "r") as fp:
                        content = json.load(fp)
                    
                    data = content.get("data", {})
                    if (
                        data.get("primary_error") == "VRE"
                        and data.get("secondary_errors") == []
                    ):
                        print(json.dumps({
                            "path": file_path,
                            "confidence": data.get("confidence")
                        }, ensure_ascii=False))
                except Exception as e:
                    print(f"Error reading {file_path}: {e}")