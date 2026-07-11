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
    temperature: float = 0.0
    max_tokens: int | None = None

    def complete(self, prompt: str, *, system_prompt: str, schema: dict[str, Any] | None = None) -> Completion:
        body: dict[str, Any] = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": prompt},
            ],
            "temperature": self.temperature,
        }
        if self.max_tokens is not None:
            body["max_tokens"] = self.max_tokens
        if schema is not None:
            body["response_format"] = {
                "type": "json_schema",
                "json_schema": {"name": "evaluation", "strict": True, "schema": schema},
            }
        request = urllib.request.Request(
            f"{self.base_url.rstrip('/')}/v1/chat/completions",
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
            text=raw["choices"][0]["message"]["content"],
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
             reasoning_effort: str | None = None) -> LLM:
    if backend == "codex":
        return CodexCLICompatibleLLM(model=model, reasoning_effort=reasoning_effort, timeout=timeout)
    if backend == "openai":
        if not url:
            raise ValueError("--url is required for the openai backend")
        return OpenAICompatibleLLM(model=model, base_url=url, api_key=api_key, timeout=timeout)
    raise ValueError(f"Unknown backend: {backend}")

