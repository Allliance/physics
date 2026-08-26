import json
import os
from tqdm import tqdm
from typing import Any, Dict, List, Optional
import math

def load_json_object(input_path: str, permit_errors=False) -> str:
    try:
        with open(input_path, 'r', encoding='utf-8') as fr:
            return json.load(fr)
    except Exception as e:
        if permit_errors:
            return []
        else:
            raise e


import json

def save_json_object(saved_path: str, obj, **kwargs) -> str:
    with open(saved_path, "w", encoding="utf-8") as out_f:
        ensure_ascii = kwargs.pop('ensure_ascii', False)
        json.dump(obj, out_f, ensure_ascii=ensure_ascii, indent=2, **kwargs)
    return saved_path


def load_jsonl_objects(input_path: str, permit_errors=False, print_tbar=False, read_amount=-1) -> str:
    objects = []
    tbar = tqdm() if print_tbar else None
    with open(input_path, 'r', encoding='utf-8') as fr:
        for line in fr:
            try:
                objects.append(json.loads(line))
                if print_tbar:
                    tbar.update(1)
                if read_amount != -1 and len(objects) >= read_amount:
                    return objects
            except Exception as e:
                if not permit_errors:
                    raise e
    return objects

def save_jsonl_objects(saved_path: str, objs, print_tbar=False, **kwargs):
    with open(saved_path, 'w', encoding='utf-8') as fw:
        for obj in (tqdm(objs) if print_tbar else objs):
            ensure_ascii = kwargs.pop('ensure_ascii', False)
            fw.write(json.dumps(obj, ensure_ascii=ensure_ascii, **kwargs) + '\n')




def to_json_safe(obj: Any):
    """Recursively convert common non-JSON types to JSON-friendly ones."""
    if obj is None or isinstance(obj, (str, bool, int)):
        return obj
    if isinstance(obj, float):
        return obj if math.isfinite(obj) else str(obj)
    if isinstance(obj, dict):
        return {str(k): to_json_safe(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple, set)):
        return [to_json_safe(v) for v in obj]
    return str(obj)