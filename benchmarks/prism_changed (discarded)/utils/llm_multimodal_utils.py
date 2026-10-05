from __future__ import annotations
import anthropic
import base64
import os
from typing import Callable, Optional, List, Dict, Tuple
from openai import OpenAI

# Local utilities for uploading/reusing OpenAI Files and converting images to data URLs
from utils.load_image_to_openai import get_or_upload_file_id, _to_data_url,  _to_data_b64
# Text-only fallback API
from utils.llm_utils import call_model_api
import logging
logger = logging.getLogger("evaluator")

def _extract_output_text(resp) -> str:
    texts = []
    try:
        if getattr(resp, "output", None):
            for item in resp.output or []:
                for c in getattr(item, "content", []) or []:
                    if getattr(c, "type", None) == "output_text" and getattr(c, "text", None):
                        texts.append(c.text)
        # SDK 有时会聚合到 output_text
        if not texts and getattr(resp, "output_text", None):
            texts.append(resp.output_text)
    except Exception:
        pass

    if texts:
        return "\n".join(texts)

    # 打点：finish_reason / usage / 原始结构
    fr = getattr(resp, "finish_reason", None)
    usage = getattr(resp, "usage", None)
    logger.warning(f"No output_text. finish_reason={fr}, usage={usage}, raw={resp}")
    raise RuntimeError("Model returned no text. See logs for details.")



def safe_join(base_path: str, sub_path: str) -> str:
    """
    Join base_path and sub_path safely.
    - Removes leading/trailing whitespace
    - Removes leading slash from sub_path to avoid os.path.join override
    """
    sub_path_clean = sub_path.strip().lstrip(os.sep)
    return os.path.join(base_path, sub_path_clean)

# =============================================================================
# Model sets
# =============================================================================
# OpenAI multimodal models (Responses API: simple image+text)
OPENAI_MM_SIMPLE = {
    "gpt-4o",
    "gpt-4o-mini",
    "gpt-4.1",
    "gpt-4.1-mini",
    "o4-mini"
}

# OpenAI multimodal models (Responses API: reasoning mode)
OPENAI_MM_REASONING_ALIASES: Dict[str, str] = {"gpt-5-medium":"gpt-5", 
                        "gpt-5-mini-medium":"gpt-5-mini"}


# Gemini multimodal models (OpenAI-compatible Chat Completions)
GEMINI_MM_MODELS = {
    "gemini-2.0-flash",
    "gemini-2.0-pro",
    "gemini-2.5-flash",
    "gemini-2.5-flash-lite",
    "gemini-2.5-pro",
}

# Base URL for Gemini's OpenAI-compatible API
GEMINI_OPENAI_BASE_URL = "https://generativelanguage.googleapis.com/v1beta/openai/"

CLAUDE_MM_MODELS = {
    "claude-sonnet-4-20250514",
}



# =============================================================================
# Grok multimodal models
# =============================================================================
GROK_MM_MODELS = {
    "grok-4"
}


GROK_OPENAI_BASE_URL = "https://api.x.ai/v1"




# =============================================================================
# Utilities
# =============================================================================
def _match_oai_reason_model(name: str) -> str:
    return OPENAI_MM_REASONING_ALIASES.get(name,name)

def _with_retries(fn: Callable[[], str], max_retries: int) -> str:
    """
    Retry helper for calling APIs.
    - Retries up to `max_retries` times.
    - Returns the result on success, raises last error on failure.
    """
    last_err: Exception | None = None
    for attempt in range(max_retries):
        try:
            return fn()
        except Exception as e:
            last_err = e
            if attempt >= max_retries - 1:
                raise
    assert last_err is not None
    raise last_err

# =============================================================================
# Payload builders (with captions)
# =============================================================================
def _user_mm_input_for_openai_responses_with_captions(
    context: str,
    labeled_file_ids: List[Tuple[str, str]],  # [(caption, file_id), ...]
):
    """
    Build the input payload for OpenAI Responses API with multiple images and captions.
    - `context`: the main text instruction for the model
    - Each image is introduced with a short text "[Image X] caption"
    - Followed by the actual image
    """
    content = [{"type": "input_text", "text": context}]
    for idx, (cap, fid) in enumerate(labeled_file_ids):
        tag = chr(ord("A") + idx)  # A, B, C, ...
        content.append({"type": "input_text", "text": f"[Image {tag}] {cap}"})
        content.append({"type": "input_image", "file_id": fid})
    return [{"role": "user", "content": content}]

def _user_mm_messages_for_gemini_with_captions(
    context: str,
    labeled_data_urls: List[Tuple[str, str]],  # [(caption, data_url), ...]
    system_prompt: Optional[str],
):
    """
    Build the input messages for Gemini (OpenAI-compatible Chat Completions) with multiple images and captions.
    - `context`: the main text instruction for the model
    - Each image is introduced with a short text "[Image X] caption"
    - Followed by the actual image_url
    """
    messages = []
    if system_prompt:
        messages.append({"role": "system", "content": system_prompt})

    mixed = [{"type": "text", "text": context}]
    for idx, (cap, url) in enumerate(labeled_data_urls):
        tag = chr(ord("A") + idx)
        mixed.append({"type": "text", "text": f"[Image {tag}] {cap}"})
        mixed.append({"type": "image_url", "image_url": {"url": url}})

    messages.append({"role": "user", "content": mixed})
    return messages

# =============================================================================
# Single-call helpers
# =============================================================================
def _openai_mm_simple_once(
    create,
    model: str,
    labeled_file_ids: List[Tuple[str, str]],
    context: str,
    max_output_tokens: int,
) -> str:
    """Call OpenAI simple multimodal model (image+text)."""
   
    resp = create(
        model=model,
        input=_user_mm_input_for_openai_responses_with_captions(context, labeled_file_ids),
        max_output_tokens=max_output_tokens,
    )
    return resp.output_text
def _grok_mm_once(
    client: OpenAI,
    model: str,
    context: str,
    labeled_data_urls: List[Tuple[str, str]],
) -> str:
    """
    Call Grok multimodal model (OpenAI-compatible Chat Completions).
    - `labeled_data_urls`: [(caption, data_url), ...]
    """
    messages = []
    mixed = [{"type": "text", "text": context}]
    for idx, (cap, url) in enumerate(labeled_data_urls):
        tag = chr(ord("A") + idx)
        mixed.append({"type": "text", "text": f"[Image {tag}] {cap}"})
        mixed.append({
            "type": "image_url",
            "image_url": {"url": url, "detail": "high"}
        })
    messages.append({"role": "user", "content": mixed})

    resp = client.chat.completions.create(model=model, messages=messages)
    return resp.choices[0].message.content

def _claude_mm_once(
    client: anthropic.Anthropic,
    model: str,
    context: str,
    labeled_data_b64: List[Tuple[str, str]],
) -> str:
    """
    Call Anthropic multimodal model.
    - labeled_data_b64: [(caption, base64_data), ...]
    """
    # 构造 content 列表
    mixed = [{"type": "text", "text": context}]
    for idx, (cap, url) in enumerate(labeled_data_b64):
        tag = chr(ord("A") + idx)
        # 如果要在文字里显示标签，取消注释
        # mixed.append({"type": "text", "text": f"[Image {tag}] {cap}"})
        mixed.append({
            "type": "image",
            "source": {
                "type": "base64",
                "media_type": "image/jpeg",
                "data": url,
            }
        })

    # 最终消息必须是一个列表，每个元素包含 role 和 content
    messages = [{"role": "user", "content": mixed}]
    # print("DEBUG messages:", messages)

    # 调用 Anthropic API
    resp = client.messages.create(
        model=model,
        max_tokens=8192,
        messages=messages,
    )

    return resp.content[0].text if resp.content else ""

def _openai_mm_reasoning_once(
    create,
    model: str,
    labeled_file_ids: List[Tuple[str, str]],
    context: str,
    max_output_tokens: int,
    verbosity: str,
    reasoning_effort: str,
) -> str:
    """Call OpenAI reasoning multimodal model (image+text + reasoning metadata)."""
    o_model = _match_oai_reason_model(model)
    resp = create(
        model=o_model,
        input=_user_mm_input_for_openai_responses_with_captions(context, labeled_file_ids),
        text={"verbosity": verbosity},
        reasoning={"effort": reasoning_effort},
        max_output_tokens=max_output_tokens,
    )
    return resp.output_text

def _gemini_mm_once(
    client: OpenAI,
    model: str,
    context: str,
    labeled_data_urls: List[Tuple[str, str]],
    system_prompt: Optional[str],
) -> str:
    """Call Gemini multimodal model (OpenAI-compatible Chat Completions)."""
    messages = _user_mm_messages_for_gemini_with_captions(context, labeled_data_urls, system_prompt)
    resp = client.chat.completions.create(model=model, messages=messages)
    return resp.choices[0].message.content

# =============================================================================
# Public API
# =============================================================================
def call_multimodal_model_api(
    file_path: str,
    model_name: str,
    images: List[Dict[str, str]],  # Must be [{"caption": str, "location": str}, ...]
    mapping_json: str,
    context: str,
    max_tokens: int = 8192,
    max_retries: int = 5,
    reasoning_effort: str = "medium",
    verbosity: str = "medium",
    gemini_system_prompt: Optional[str] = None,
) -> str:
    """
    Unified API for calling multimodal models with multiple images and captions.
    - If `images` is empty: falls back to text-only call_model_api
    - For OpenAI Responses API:
        * Upload or reuse file_ids (via get_or_upload_file_id)
        * Send text + "[Image X] caption" + image for each image
    - For Gemini Chat Completions:
        * Convert images to data URLs
        * Send text + "[Image X] caption" + image_url for each image
    """
    invalid_loc = False
    if images:
        for img in images:
            cap = img["caption"]
            loc = img["location"]
            full_loc = safe_join(file_path, loc)
            if not os.path.exists(full_loc):
                invalid_loc = True
                break
            
    if not images or invalid_loc:
        # Fallback to text-only mode
        print("No or invalid images provided")
        logger.info("No or invalid images provided, falling back to text-only model API call.")
        return call_model_api(
            model_name,
            context,
            max_retries,
            reasoning_effort,
            verbosity,
          
        )
    # OpenAI Responses API path
    if model_name in OPENAI_MM_SIMPLE or model_name in OPENAI_MM_REASONING_ALIASES:
        labeled_file_ids: List[Tuple[str, str]] = []
        for img in images:
            cap = img["caption"]
            loc = img["location"]
            full_loc = safe_join(file_path, loc)
            fid = get_or_upload_file_id(full_loc, mapping_json)
            labeled_file_ids.append((cap, fid))

        client = OpenAI(api_key=os.environ.get("OPENAI_API_KEY"))
        create = client.responses.create

        if model_name in OPENAI_MM_SIMPLE:
            return _with_retries(
                lambda: _openai_mm_simple_once(create, model_name, labeled_file_ids, context, max_tokens),
                max_retries=max_retries,
            )
        else:
            return _with_retries(
                lambda: _openai_mm_reasoning_once(create, model_name, labeled_file_ids, context, max_tokens, verbosity, reasoning_effort),
                max_retries=max_retries,
            )

    # Gemini Chat Completions path
    if model_name in GEMINI_MM_MODELS:
        labeled_data_urls: List[Tuple[str, str]] = []
        for img in images:
            cap = img["caption"]
            loc = img["location"]
            full_loc = safe_join(file_path, loc)
            labeled_data_urls.append((cap, _to_data_url(full_loc)))

        g_client = OpenAI(api_key=os.getenv("GEMINI_API_KEY"), base_url=GEMINI_OPENAI_BASE_URL)
        return _with_retries(
            lambda: _gemini_mm_once(g_client, model_name, context, labeled_data_urls, gemini_system_prompt),
            max_retries=max_retries,
        )
        # Grok Chat Completions path
    if model_name in GROK_MM_MODELS:
        labeled_data_urls: List[Tuple[str, str]] = []
        for img in images:
            cap = img["caption"]
            loc = img["location"]
            full_loc = safe_join(file_path, loc)
            
            labeled_data_urls.append((cap, _to_data_url(full_loc)))
        

        g_client = OpenAI(api_key=os.getenv("XAI_API_KEY"), base_url=GROK_OPENAI_BASE_URL)
        return _with_retries(
            lambda: _grok_mm_once(g_client, model_name, context, labeled_data_urls),
            max_retries=max_retries,
        )
    if model_name in CLAUDE_MM_MODELS:
        labeled_data_urls: List[Tuple[str, str]] = []
        for img in images:
            cap = img["caption"]
            loc = img["location"]
            full_loc = safe_join(file_path, loc)
            
            labeled_data_urls.append((cap, _to_data_b64(full_loc)))
        

        c_client = anthropic.Anthropic(api_key=os.getenv("ANTHROPIC_API_KEY"))
        return _with_retries(
            lambda: _claude_mm_once(c_client, model_name, context, labeled_data_urls),
            max_retries=max_retries,
        )
# =============================================================================
# Example
# =============================================================================
if __name__ == "__main__":
    # Example normalized input: captions + file locations
    IMAGES = [
      {
        "caption": "Fig. 1.6",
        "location": "/01-1/images/e58fb4f182f54cf9a6f273b191da20c7eeb428115b81868135ad3681c55f90c3.jpg"
      }
    ]
    # IMAGES=None

    PROMPT = (
        "What is in this image"
    )

    MAPPING_JSON = "jpg_file_ids.json"  # Used for file_id reuse in OpenAI path

    # Choose a model (OpenAI or Gemini)
    # model = "gpt-4o-mini"
    # model = "gemini-2.5-flash"
    # model = "grok-4"
    # model = "gpt-5-mini-medium"
    # model = "gpt-5-medium"
    model= "claude-sonnet-4-20250514"
    # model = "gemini-2.5-flash"

    out = call_multimodal_model_api(
        file_path="/home/users/wanjiazh/data/PHYBE/",  # Base path for image locations
        model_name=model,
        images=IMAGES,
        mapping_json=MAPPING_JSON,
        context=PROMPT,
        max_tokens=8192,
        gemini_system_prompt="You are a helpful assistant.",
    )

    print("\n[RESPONSE]")
    print(out)
