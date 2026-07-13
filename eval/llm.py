"""Common completion interface for OpenAI-compatible servers and Codex CLI."""

from __future__ import annotations

import json
import urllib.error
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol

from utils.codex_cli import CodexLLM


@dataclass
class Completion:
    text: str
    usage: dict[str, Any] | None = None
    raw: Any = None


class LLM(Protocol):
    def complete(self, prompt: str, *, system_prompt: str, schema: dict[str, Any] | None = None) -> Completion: ...


@dataclass
class OpenAICompatibleLLM:
    """Minimal /v1/chat/completions client (works with OpenAI and vLLM)."""

    model: str
    base_url: str
    api_key: str = "EMPTY"
    timeout: float = 300.0
    temperature: float | None = 0.0
    top_p: float | None = None
    top_k: int | None = None
    min_p: float | None = None
    presence_penalty: float | None = None
    repetition_penalty: float | None = None
    extra_body: dict[str, Any] | None = None
    max_tokens: int | None = None
    reasoning_effort: str | None = None

    def complete(self, prompt: str, *, system_prompt: str, schema: dict[str, Any] | None = None) -> Completion:
        body: dict[str, Any] = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": prompt},
            ],
        }
        if self.temperature is not None:
            body["temperature"] = self.temperature
        for name in ("top_p", "top_k", "min_p", "presence_penalty", "repetition_penalty"):
            value = getattr(self, name)
            if value is not None:
                body[name] = value
        if self.max_tokens is not None:
            token_limit_parameter = ("max_completion_tokens"
                                     if self.model.startswith(("gpt-5", "o1", "o3", "o4"))
                                     else "max_tokens")
            body[token_limit_parameter] = self.max_tokens
        if self.reasoning_effort is not None:
            body["reasoning_effort"] = self.reasoning_effort
        if self.extra_body:
            body.update(self.extra_body)
        if schema is not None:
            body["response_format"] = {
                "type": "json_schema",
                "json_schema": {"name": "evaluation", "strict": True, "schema": schema},
            }
        base_url = self.base_url.rstrip("/")
        endpoint = (f"{base_url}/chat/completions"
                    if base_url.endswith(("/v1", "/openai"))
                    else f"{base_url}/v1/chat/completions")
        request = urllib.request.Request(
            endpoint,
            data=json.dumps(body).encode(),
            headers={"Authorization": f"Bearer {self.api_key}", "Content-Type": "application/json"},
            method="POST",
        )
        try:
            with urllib.request.urlopen(request, timeout=self.timeout) as response:
                raw = json.load(response)
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode(errors="replace")
            raise RuntimeError(f"LLM HTTP {exc.code}: {detail}") from exc
        return Completion(
            # Reasoning models can exhaust their token budget before emitting a
            # final channel, in which case OpenAI-compatible servers return null.
            text=raw["choices"][0]["message"].get("content") or "",
            usage=raw.get("usage"),
            raw=raw,
        )


@dataclass
class CodexCLICompatibleLLM:
    model: str = "gpt-5.5"
    reasoning_effort: str | None = None
    timeout: float = 300.0

    def complete(self, prompt: str, *, system_prompt: str, schema: dict[str, Any] | None = None) -> Completion:
        client = CodexLLM(
            model=self.model,
            model_reasoning_effort=self.reasoning_effort,
            timeout=self.timeout,
        )
        schema_path = None
        if schema is not None:
            import tempfile

            handle = tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False)
            try:
                json.dump(schema, handle)
                handle.close()
                schema_path = Path(handle.name)
                result = client.complete(prompt, system_prompt=system_prompt, output_schema=schema_path)
            finally:
                Path(handle.name).unlink(missing_ok=True)
        else:
            result = client.complete(prompt, system_prompt=system_prompt)
        return Completion(text=result.text, usage=result.usage, raw={"attempts": result.attempts})


def make_llm(*, backend: str, model: str, url: str | None, api_key: str, timeout: float,
             reasoning_effort: str | None = None, max_tokens: int | None = None,
             temperature: float | None = 0.0, top_p: float | None = None,
             top_k: int | None = None, min_p: float | None = None,
             presence_penalty: float | None = None,
             repetition_penalty: float | None = None,
             extra_body: dict[str, Any] | None = None) -> LLM:
    if backend == "codex":
        return CodexCLICompatibleLLM(model=model, reasoning_effort=reasoning_effort, timeout=timeout)
    if backend == "openai":
        if not url:
            raise ValueError("--url is required for the openai backend")
        return OpenAICompatibleLLM(model=model, base_url=url, api_key=api_key, timeout=timeout,
                                   max_tokens=max_tokens, reasoning_effort=reasoning_effort,
                                   temperature=temperature, top_p=top_p, top_k=top_k,
                                   min_p=min_p, presence_penalty=presence_penalty,
                                   repetition_penalty=repetition_penalty,
                                   extra_body=extra_body)
    raise ValueError(f"Unknown backend: {backend}")
