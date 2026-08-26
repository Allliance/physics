from __future__ import annotations
import os
import base64
import mimetypes
from typing import Callable, Optional
from openai import OpenAI
from load_image_to_openai import get_or_upload_file_id, _to_data_url
from llm_utils import call_model_api

# --- OpenAI multimodal model sets --------------------------------------------
OPENAI_MM_SIMPLE = {
    "gpt-4o",
    "gpt-4o-mini",
    "gpt-4.1",
    "gpt-4.1-mini",
}
OPENAI_MM_REASONING = {
    "gpt-5",
    "gpt-5-mini",
}
# --- Gemini multimodal models (OpenAI-compatible Chat Completions) -----------
GEMINI_MM_MODELS = {
    "gemini-2.0-flash",  
    "gemini-2.0-pro",
    "gemini-2.5-flash",
    "gemini-2.5-flash-lite",
    "gemini-2.5-pro",
}
GEMINI_OPENAI_BASE_URL = "https://generativelanguage.googleapis.com/v1beta/openai/"


# --- Utilities ----------------------------------------------------------------
def _with_retries(fn: Callable[[], str], max_retries: int) -> str:
    """Retry helper."""
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

def _user_mm_input_for_openai_responses(context: str, file_id: str):
    """OpenAI Responses: one image + one text."""
    return [
        {
            "role": "user",
            "content": [
                {"type": "input_text", "text": context},
                {"type": "input_image", "file_id": file_id},
            ],
        }
    ]


def _user_mm_messages_for_gemini(context: str, data_url: str, system_prompt: Optional[str]):
    """
    Gemini (OpenAI-compatible Chat Completions) message format, matching your example:
    content: [{"type": "text", ...}, {"type": "image_url", "image_url": {"url": "..."}}, ...]
    """
    messages = []
    if system_prompt:
        messages.append({"role": "system", "content": system_prompt})
    messages.append(
        {
            "role": "user",
            "content": [
                {"type": "text", "text": context},
                {"type": "image_url", "image_url": {"url": data_url}},
            ],
        }
    )
    return messages


# --- Single-call helpers ------------------------------------------------------
def call_openai_mm_simple_once(
    create, model: str, file_id: str, context: str, max_output_tokens: int
) -> str:
    resp = create(
        model=model,
        input=_user_mm_input_for_openai_responses(context, file_id),
        max_output_tokens=max_output_tokens,
    )
    return resp.output_text


def call_openai_mm_reasoning_once(
    create,
    model: str,
    file_id: str,
    context: str,
    max_output_tokens: int,
    verbosity: str,
    reasoning_effort: str,
) -> str:
    resp = create(
        model=model,
        input=_user_mm_input_for_openai_responses(context, file_id),
        text={"verbosity": verbosity},
        reasoning={"effort": reasoning_effort},
        max_output_tokens=max_output_tokens,
    )
    return resp.output_text


def call_gemini_mm_once(
    client: OpenAI,
    model: str,
    context: str,
    data_url: str,
    system_prompt: Optional[str],
) -> str:
    """Gemini via OpenAI-compatible Chat Completions with (text + image_url)."""
    messages = _user_mm_messages_for_gemini(context, data_url, system_prompt)
    resp = client.chat.completions.create(model=model, messages=messages)
    # 直接返回 message.content（Gemini 兼容端点此处为字符串）
    return resp.choices[0].message.content


# --- Public API ---------------------------------------------------------------
def call_multimodal_model_api(
    model_name: str,
    image_path: str,
    mapping_json: str,
    context: str,
    max_tokens: int = 1024,
    max_retries: int = 5,
    reasoning_effort: str = "medium",
    verbosity: str = "medium",
    gemini_system_prompt: Optional[str] = None,
) -> str:
    """
    Call multimodal models (OpenAI Responses OR Gemini Chat Completions) with an image and text.

    Routing:
      - OpenAI (Responses API):
          * Simple:    input=[input_text, input_image(file_id)] → output_text
          * Reasoning: + text/verbosity + reasoning/effort      → output_text
          * Uses OpenAI Files; mapping_json is used.
      - Gemini (OpenAI-compatible Chat Completions):
          * messages=[{"type":"text"}, {"type":"image_url": {"url": dataURL}}] → choices[0].message.content
          * Does NOT use OpenAI Files; mapping_json is ignored.
    """
    if (
        model_name not in OPENAI_MM_SIMPLE
        and model_name not in OPENAI_MM_REASONING
        and model_name not in GEMINI_MM_MODELS
    ):
        raise ValueError(f"Unknown or non-multimodal model name: {model_name}")
    # --- Text-only fallback (no image) ---
    if image_path is None:
        print("No iamge for this problem")
        return call_model_api(model_name, context, max_retries, reasoning_effort, verbosity, gemini_system_prompt)
    # --- Multimodal path (with image) ---
    else:
        # --- OpenAI path ---
        if model_name in OPENAI_MM_SIMPLE or model_name in OPENAI_MM_REASONING:
            file_id = get_or_upload_file_id(image_path, mapping_json)
            client = OpenAI(api_key=os.environ.get("OPENAI_API_KEY"))
            create = client.responses.create

            if model_name in OPENAI_MM_SIMPLE:
                return _with_retries(
                    lambda: call_openai_mm_simple_once(create, model_name, file_id, context, max_tokens),
                    max_retries=max_retries,
                )
            else:
                return _with_retries(
                    lambda: call_openai_mm_reasoning_once(
                        create, model_name, file_id, context, max_tokens, verbosity, reasoning_effort
                    ),
                    max_retries=max_retries,
                )

        # --- Gemini path (Chat Completions) ---
        data_url = _to_data_url(image_path)
        g_client = OpenAI(
            api_key=os.getenv("GEMINI_API_KEY"),
            base_url=GEMINI_OPENAI_BASE_URL,
        )
        return _with_retries(
            lambda: call_gemini_mm_once(
                g_client, model_name, context, data_url, gemini_system_prompt
            ),
            max_retries=max_retries,
        )


# --- Example ------------------------------------------------------------------
if __name__ == "__main__":
    IMAGE_PATH = None
    PROMPT = "What is in this image?"
    mapping_json = "jpg_file_ids.json"

    out = call_multimodal_model_api(
        model_name="gemini-2.0-flash",
        image_path=IMAGE_PATH,
        mapping_json=mapping_json,  # ignored for Gemini
        context=PROMPT,
        max_tokens=1024,
        gemini_system_prompt="You are a helpful assistant.",
    )

    # out = call_multimodal_model_api(
    #     model_name="gpt-5-mini",
    #     image_path=IMAGE_PATH,
    #     mapping_json=mapping_json,
    #     context=PROMPT,
    #     max_tokens=1024,
    # )
    print("\n[RESPONSE]")
    print(out)
