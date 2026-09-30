"""Prediction backends for Sol, Fable Messages API, and Fable with tools."""

from __future__ import annotations

import argparse
import base64
import json
import os
import sys
from pathlib import Path

from .prompts import SYSTEM_PROMPT, TOOLS_SYSTEM_PROMPT

TOOL_PATH = "/usr/local/bin:/usr/bin:/bin"


def validate_codex_result(result) -> None:
    terminal = [(index, event.get("type")) for index, event in enumerate(result.events)
                if event.get("type") in {"turn.completed", "turn.failed"}]
    if not terminal or terminal[-1][1] != "turn.completed":
        raise ValueError("Codex stream did not complete successfully")
    completed_at = terminal[-1][0]
    if any(event.get("type") == "error" for event in result.events[completed_at + 1:]):
        raise ValueError("Codex stream errored after completion")
    if not isinstance(result.text, str) or not result.text.strip():
        raise ValueError("Codex stream completed without answer text")


def image_block(path: Path) -> dict:
    data = path.read_bytes()
    # Dataset URLs and local paths need not have file extensions.
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
    # Reuse Claude Code's mapping without executing helpers or reading credentials.
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
        from .errors import GenerationLimitError

        raise GenerationLimitError("Fable exhausted --max-output-tokens (stop_reason='max_tokens').")
    if stop not in {"end_turn", "refusal"}:
        raise ValueError(f"Incomplete Fable response (stop_reason={stop!r}); rerun to retry.")
    # A refusal is an evaluated outcome, never silently replaced by Opus.
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



def make_predictor(args: argparse.Namespace, api_model: str | None):
    if args.model == "gemini-3.1-pro-preview":
        sys.path.insert(0, str(Path(__file__).resolve().parents[3]))
        from utils.gemini_backend import generate, GeminiLimitError

        def predict(question: dict, image: Path | None) -> dict:
            try:
                return generate(
                    question["question"], image, effort=args.reasoning_effort,
                    max_output_tokens=args.max_output_tokens, timeout=args.timeout,
                    system_prompt=TOOLS_SYSTEM_PROMPT if args.use_tools else SYSTEM_PROMPT,
                    use_tools=args.use_tools, web_search=args.web_search == "live",
                )
            except GeminiLimitError as exc:
                from .errors import GenerationLimitError
                raise GenerationLimitError(str(exc)) from exc
        return predict

    if args.model in {"gpt-oss-120b", "kimi-k3", "glm-5.3", "deepseek-v4-pro"}:
        repository = Path(__file__).resolve().parents[3]
        sys.path[:0] = [str(repository / "utils"), str(repository)]
        if args.use_tools:
            from codex_cli import CodexLLM
            from utils.openai_compatible import backend_metadata

            local = backend_metadata()
            client = CodexLLM(
                model=local["served_model"], model_reasoning_effort=args.reasoning_effort,
                timeout=args.timeout, system_prompt=TOOLS_SYSTEM_PROMPT, strict_no_tools=False,
                web_search=args.web_search, sandbox_mode="workspace-write", env_inherit="none",
                env_set={"PATH": TOOL_PATH}, config_overrides=[
                    'model_provider="vllm"',
                    'model_providers.vllm.name="gpt-oss"',
                    f'model_providers.vllm.base_url="{local["base_url"]}"',
                    'model_providers.vllm.wire_api="responses"',
                    'model_providers.vllm.requires_openai_auth=false',
                ],
            )

            def predict(question: dict, image: Path | None) -> dict:
                if image:
                    raise ValueError("gpt-oss-120b is text-only")
                result = client.complete(question["question"])
                validate_codex_result(result)
                trace = [event for event in result.events if event.get("item", {}).get("type") in
                         {"command_execution", "file_change", "mcp_tool_call", "web_search"}]
                return {"response": result.text, "usage": result.usage, "attempts": result.attempts,
                        "tool_events": [event["item"]["type"] for event in trace], "tool_trace": trace}
            return predict
        from utils.openai_compatible import generate

        def predict(question: dict, image: Path | None) -> dict:
            if image:
                raise ValueError(f"{args.model} image input is not enabled in this evaluation")
            return generate(question["question"], system_prompt=SYSTEM_PROMPT,
                            reasoning_effort=args.reasoning_effort,
                            max_output_tokens=args.max_output_tokens, timeout=args.timeout,
                            temperature=1.0 if args.model != "gpt-oss-120b" else None,
                            top_p=(1.0 if args.model == "deepseek-v4-pro" else 0.95)
                            if args.model != "gpt-oss-120b" else None)
        return predict

    if args.model in {"gpt-5.6-sol", "gpt-5.6-luna", "gpt-6-astra"}:
        sys.path.insert(0, str(args.codex_cli_path.resolve()))
        from codex_cli import CodexLLM

        client = CodexLLM(
            model=args.model, model_reasoning_effort=args.reasoning_effort, timeout=args.timeout,
            system_prompt=TOOLS_SYSTEM_PROMPT if args.use_tools else SYSTEM_PROMPT,
            strict_no_tools=not args.use_tools, web_search=args.web_search,
            sandbox_mode="workspace-write" if args.use_tools else "read-only", env_inherit="none",
            env_set={"PATH": TOOL_PATH} if args.use_tools else None,
        )

        def predict(question: dict, image: Path | None) -> dict:
            result = client.complete(question["question"], image_paths=[image] if image else None)
            validate_codex_result(result)
            trace = [event for event in result.events if event.get("item", {}).get("type") in
                     {"command_execution", "file_change", "mcp_tool_call", "web_search"}]
            return {"response": result.text, "usage": result.usage, "attempts": result.attempts,
                    "tool_events": [event["item"]["type"] for event in trace], "tool_trace": trace}
        return predict

    if args.use_tools:
        from .claude import make_predictor as make_claude_predictor

        return make_claude_predictor(args, api_model, TOOLS_SYSTEM_PROMPT, image_block)

    client = make_fable_client(args.timeout)

    def predict(question: dict, image: Path | None) -> dict:
        content = ([image_block(image)] if image else []) + [{"type": "text", "text": question["question"]}]
        with client.messages.stream(
            model=api_model, max_tokens=args.max_output_tokens, system=SYSTEM_PROMPT,
            messages=[{"role": "user", "content": content}],
            thinking={"type": "adaptive"}, output_config={"effort": args.reasoning_effort},
        ) as stream:
            response = stream.get_final_message()
        return parse_fable_response(response.model_dump(mode="json"), api_model)
    return predict
