#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import os
import json

TARGET_DIR = "/home/users/wanjiazh/AI4S_Bench/Analyze_Label/Analysis/sol_error/claude-sonnet-4-20250514"

def is_uncertain_json(path: str) -> bool:
    """Check if a JSON file contains primary_error == 'Uncertain'."""
    try:
        with open(path, "r", encoding="utf-8") as f:
            obj = json.load(f)
        # 兼容结构 { "primary_error": ... } 或 { "data": { "primary_error": ... } }
        if isinstance(obj, dict):
            if "primary_error" in obj and obj["primary_error"] == "DAE":
                return True
            if "data" in obj and isinstance(obj["data"], dict) and obj["data"].get("primary_error") == "DAE":
                return True
    except Exception:
        pass
    return False

def main():
    deleted = 0
    scanned = 0
    for root, _, files in os.walk(TARGET_DIR):
        for fn in files:
            if fn.lower().endswith(".json"):
                path = os.path.join(root, fn)
                scanned += 1
                if is_uncertain_json(path):
                    # print(f"[DELETE] {path}")                    
                    print(f"[DAW] {path}")
                    try:
                        # os.remove(path)
                        deleted += 1
                    except Exception as e:
                        print(f"  [ERROR] Failed to delete {path}: {e}")
    print(f"Scanned {scanned} JSON files, deleted {deleted} uncertain ones.")

if __name__ == "__main__":
    main()