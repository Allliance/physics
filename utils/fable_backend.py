"""Shared no-tool Fable transport, image formatting, and response validation."""

import base64
import json
import os
from pathlib import Path


class GenerationLimitError(ValueError):
    """The evaluated attempt exhausted its generation budget."""


def image_block(path: Path) -> dict:
    data = path.read_bytes()
    if data.startswith(b"\x89PNG\r\n\x1a\n"):
        mime = "image/png"
    elif data.startswith(b"\xff\xd8\xff"):
        mime = "image/jpeg"
    elif data.startswith((b"GIF87a", b"GIF89a")):
        mime = "image/gif"
    elif data.startswith(b"RIFF") and data[8:12] == b"WEBP":
        mime = "image/webp"
    else:
        raise ValueError("Image must be PNG, JPEG, GIF, or WebP.")
    return {"type": "image", "source": {"type": "base64", "media_type": mime,
                                        "data": base64.b64encode(data).decode("ascii")}}


def resolve_fable_model(explicit: str | None) -> str:
    if explicit:
        return explicit
    if os.environ.get("ANTHROPIC_DEFAULT_FABLE_MODEL"):
        return os.environ["ANTHROPIC_DEFAULT_FABLE_MODEL"]
    config = Path(os.environ.get("CLAUDE_CONFIG_DIR", str(Path.home() / ".claude"))) / "settings.json"
    if config.exists():
        settings = json.loads(config.read_text())
        mapped = settings.get("modelOverrides", {}).get("claude-fable-5")
        if mapped:
            return mapped
        mapped = settings.get("env", {}).get("ANTHROPIC_DEFAULT_FABLE_MODEL")
        if mapped:
            return mapped
    return "claude-fable-5"


def parse_fable_response(response: dict, api_model: str) -> dict:
    actual = response.get("model")
    if actual not in {api_model, "claude-fable-5"}:
        raise ValueError(f"Expected Fable 5 ({api_model}); API returned model {actual!r}.")
    blocks = response.get("content", [])
    if any(b.get("type") in {"tool_use", "server_tool_use"} for b in blocks):
        raise ValueError("Unexpected tool use in no-tool Fable response.")
    stop = response.get("stop_reason")
    text = "\n".join(b["text"] for b in blocks if b.get("type") == "text").strip()
    if stop == "max_tokens":
        raise GenerationLimitError("Fable exhausted --max-output-tokens (stop_reason='max_tokens').")
    if stop not in {"end_turn", "refusal"}:
        raise ValueError(f"Incomplete Fable response (stop_reason={stop!r}); rerun to retry.")
    if not text and stop == "refusal":
        text = "Explanation: The model refused this request.\nAnswer: None\nConfidence: 0%"
    if not text:
        raise ValueError("Fable returned no answer text.")
    return {"response": text, "usage": response.get("usage"), "actual_model": actual,
            "stop_reason": stop, "refused": stop == "refusal", "attempts": 1, "tool_events": []}


def make_fable_client(timeout: float):
    import anthropic

    token = os.environ.get("ANTHROPIC_AUTH_TOKEN")
    key = os.environ.get("ANTHROPIC_API_KEY") or os.environ.get("CLAUDE_API_KEY")
    if not token and not key:
        raise ValueError("Set ANTHROPIC_AUTH_TOKEN or ANTHROPIC_API_KEY for Fable.")
    return anthropic.Anthropic(
        api_key=None if token else key, auth_token=token,
        base_url=os.environ.get("ANTHROPIC_BASE_URL", "https://api.anthropic.com"),
        timeout=timeout, max_retries=2,
    )
