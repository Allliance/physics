#!/usr/bin/env python3
import os
import json
import argparse

def delete_if_any_null_response(file_path) -> bool:
    """返回是否已删除"""
    try:
        with open(file_path, "r") as fp:
            data = json.load(fp)
        if isinstance(data, list):
            return any(item.get("response") is None for item in data)
    except Exception as e:
        print(f"⚠️ Error reading {file_path}: {e}")
    return False

def delete_if_missing_solution_error(file_path) -> bool:
    """返回是否已删除"""
    try:
        with open(file_path, "r") as fp:
            data = json.load(fp)
        if isinstance(data, dict):
            return data.get("error") == "missing_solution_text"
        if isinstance(data, list):
            return any(isinstance(item, dict) and item.get("error") == "missing_solution_text" for item in data)
    except Exception as e:
        print(f"⚠️ Error reading {file_path}: {e}")
    return False

def sweep_responses(responses_dir, dry_run=False):
    checked = deleted = 0
    for root, _, files in os.walk(responses_dir):
        for f in files:
            if f.endswith("_response.json"):
                file_path = os.path.join(root, f)
                checked += 1
                should_delete = delete_if_any_null_response(file_path)
                if should_delete:
                    if dry_run:
                        print(f"[DRY-RUN] 🗑️ Would delete (null response found): {file_path}")
                    else:
                        os.remove(file_path)
                        print(f"🗑️ Deleted (null response found): {file_path}")
                    deleted += 1
    print(f"Responses → checked: {checked}, deleted: {deleted}")
    return checked, deleted

def sweep_grades(grades_dir, dry_run=False):
    checked = deleted = 0
    for root, _, files in os.walk(grades_dir):
        for f in files:
            if f.endswith("_grade.json"):
                file_path = os.path.join(root, f)
                checked += 1
                should_delete = delete_if_missing_solution_error(file_path)
                if should_delete:
                    if dry_run:
                        print(f"[DRY-RUN] 🗑️ Would delete (missing_solution_text): {file_path}")
                    else:
                        os.remove(file_path)
                        print(f"🗑️ Deleted (missing_solution_text): {file_path}")
                    deleted += 1
    print(f"Grades    → checked: {checked}, deleted: {deleted}")
    return checked, deleted

def main():
    parser = argparse.ArgumentParser(description="Clean response/grade JSONs by deletion rules.")
    parser.add_argument("--dry-run", action="store_true", help="Preview deletions without removing files.")
    args = parser.parse_args()
    for i in range(1,8):
        root= f"/home/users/wanjiazh/AI4S_Bench/main_exp_v2/results_0{i}_cleaned_dag/text/gpt-4o-mini"

        responses_dir = os.path.join(root, "responses")
        grades_dir = os.path.join(root, "grades", "dag")

        print(f"Root: {root}")
        if not os.path.isdir(responses_dir):
            print(f"⚠️ Responses dir not found: {responses_dir}")
        if not os.path.isdir(grades_dir):
            print(f"⚠️ Grades dir not found: {grades_dir}")

        total_checked = total_deleted = 0
        if os.path.isdir(responses_dir):
            c, d = sweep_responses(responses_dir, dry_run=args.dry_run)
            total_checked += c; total_deleted += d
        if os.path.isdir(grades_dir):
            c, d = sweep_grades(grades_dir, dry_run=args.dry_run)
            total_checked += c; total_deleted += d

        print(f"\n✅ Completed. Total checked: {total_checked}, total deleted: {total_deleted}. "
            f"{'(dry-run)' if args.dry_run else ''}")

if __name__ == "__main__":
    main()