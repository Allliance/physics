import os
import json
import requests
import base64
import mimetypes
import logging
from contextlib import contextmanager

logger = logging.getLogger("evaluator")

# -------- blocking lock (same for readers & writers) --------
@contextmanager
def blocking_lock(path: str):
    """Blocking exclusive advisory lock on a sidecar .lock file."""
    lock_path = f"{path}.lock"
    os.makedirs(os.path.dirname(os.path.abspath(path)) or ".", exist_ok=True)
    f = open(lock_path, "a+")
    try:
        try:
            import fcntl  # *nix
            fcntl.flock(f.fileno(), fcntl.LOCK_EX)  # blocks until free
        except ImportError:
            import msvcrt  # Windows (no shared locks; exclusive is fine)
            # Lock 1 byte; will block until free
            msvcrt.locking(f.fileno(), msvcrt.LK_LOCK, 1)
        yield
    finally:
        try:
            try:
                import fcntl
                fcntl.flock(f.fileno(), fcntl.LOCK_UN)
            except ImportError:
                import msvcrt
                msvcrt.locking(f.fileno(), msvcrt.LK_UNLCK, 1)
        finally:
            f.close()

def _atomic_write_json(path: str, obj: dict) -> None:
    tmp = f"{path}.tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(obj, f, ensure_ascii=False, indent=2)
        f.flush()
        os.fsync(f.fileno())
    os.replace(tmp, path)

# -------- public API: no retries, readers just wait --------
def save_mapping(mapping: dict, mapping_json: str) -> None:
    with blocking_lock(mapping_json):
        _atomic_write_json(mapping_json, mapping)

def load_mapping(mapping_json: str) -> dict:
    if not os.path.exists(mapping_json):
        return {}
    with blocking_lock(mapping_json):          # waits if a writer is committing
        with open(mapping_json, "r", encoding="utf-8") as f:
            text = f.read()
    return json.loads(text) if text.strip() else {}

def _to_data_url(image_path: str) -> str:
    """Encode local image to data URL (for Gemini Chat Completions)."""
    mime, _ = mimetypes.guess_type(image_path)
    if not mime:
        mime = "image/jpeg"
    with open(image_path, "rb") as f:
        b64 = base64.b64encode(f.read()).decode("utf-8")
    print("[Encoding image]")
    return f"data:{mime};base64,{b64}"

def _to_data_b64(image_path: str) -> str:
    """Encode local image to data URL (for Gemini Chat Completions)."""
    mime, _ = mimetypes.guess_type(image_path)
    if not mime:
        mime = "image/jpeg"
    with open(image_path, "rb") as f:
        
        b64 = base64.standard_b64encode(f.read()).decode("utf-8")
    print("[Encoding image]")
    return b64


def check_file_id_valid(file_id: str) -> bool:
    """
    check file_id is valid and purpose is vision
    """
    api_key = os.environ.get("OPENAI_API_KEY")
    url = f"https://api.openai.com/v1/files/{file_id}"
    headers = {"Authorization": f"Bearer {api_key}"}

    resp = requests.get(url, headers=headers)
    if resp.status_code != 200:
        print(f"[ERROR] File ID {file_id} not found or inaccessible.")
        return False

    file_info = resp.json()
    if file_info.get("purpose") != "vision":
        print(f"[ERROR] File ID {file_id} purpose is '{file_info.get('purpose')}', not 'vision'.")
        return False

    print(f"[OK] File ID {file_id} is valid for vision.")
    return True

def get_or_upload_file_id(image_path: str, mapping_json: str) -> str:
    """
    get file_id from JSON, if not exist or invalid, upload the image and save the mapping to JSON
    """
    mapping = load_mapping(mapping_json)
    abs_path = os.path.abspath(image_path)

    file_id = mapping.get(abs_path)
    if file_id and check_file_id_valid(file_id):
        logger.debug(f"Found file id for image path {image_path} with abs path {abs_path}: {file_id}")
        return file_id

    logger.debug(f"Did not find file id for image path {image_path} with abs path {abs_path}")
    # upload the image
    file_id = upload_image_to_openai(abs_path)
    mapping[abs_path] = file_id
    save_mapping(mapping, mapping_json)
    return file_id


            
def upload_image_to_openai(file_path: str) -> str:
    """
    upload a JPG image to OpenAI, return file_id
    """
    api_key = os.environ.get("OPENAI_API_KEY")
    if not api_key:
        raise EnvironmentError("please set OPENAI_API_KEY")

    url = "https://api.openai.com/v1/files"
    headers = {
        "Authorization": f"Bearer {api_key}",
        "OpenAI-Beta": "vision"
    }
    with open(file_path, "rb") as f:
        files = {"file": f}
        data = {"purpose": "vision"}
        resp = requests.post(url, headers=headers, files=files, data=data, timeout=120)
    resp.raise_for_status()
    file_id = resp.json()["id"]
    print(f"[OK] {file_path} -> {file_id}")
    return file_id


def upload_folder_jpgs(folder: str, mapping_json: str = "jpg_file_ids.json"):
    """
    upload all .jpg files in a folder, and save the {path: file_id} mapping to JSON
    """
    folder = os.path.abspath(folder)
    mapping = {}

    for name in os.listdir(folder):
        if name.lower().endswith(".jpg"):
            path = os.path.join(folder, name)
            file_id = upload_image_to_openai(path)
            mapping[path] = file_id

    save_mapping(mapping, mapping_json)

    print(f"\nAll done. Saved mapping to: {os.path.abspath(mapping_json)}")


if __name__ == "__main__":
    folder_path = "/Users/zwj/Downloads/PHYBE/01-1/"
    mapping_json = os.path.join(folder_path, "jpg_file_ids.json")
    upload_folder_jpgs(folder_path, mapping_json)
