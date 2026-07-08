"""Small wrapper that uses `codex exec` like a text-generation API."""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any


DEFAULT_SYSTEM_PROMPT = (
    "Answer using only the supplied prompt. Do not use tools, shell commands, "
    "files, web search, or external context."
)

TOOL_ITEM_TYPES = {
    "command_execution",
    "file_change",
    "mcp_tool_call",
    "web_search",
}


class CodexExecError(RuntimeError):
    """Raised when `codex exec` fails."""


class CodexToolUseError(RuntimeError):
    """Raised when Codex emits a tool event despite the no-tools wrapper."""


class CodexToolRetryError(CodexToolUseError):
    """Raised after Codex keeps using tools across all retry attempts."""


@dataclass
class CodexLLMResult:
    text: str
    events: list[dict[str, Any]]
    usage: dict[str, Any] | None = None
    attempts: int = 1


@dataclass
class CodexLLM:
    """Minimal `codex exec` client.

    This does not expose a server. It gives Python code a simple function-call
    interface around Codex CLI's non-interactive mode.
    """

    model: str | None = None
    model_reasoning_effort: str | None = None
    codex_bin: str = "codex"
    timeout: float | None = None
    system_prompt: str = DEFAULT_SYSTEM_PROMPT
    strict_no_tools: bool = True
    max_tool_retries: int = 3

    def complete(
        self,
        prompt: str,
        *,
        system_prompt: str | None = None,
        output_schema: Path | None = None,
        api_key: str | None = None,
    ) -> CodexLLMResult:
        last_error: CodexToolUseError | None = None
        max_attempts = 1 if not self.strict_no_tools else self.max_tool_retries + 1
        for attempt in range(1, max_attempts + 1):
            try:
                result = self._complete_once(
                    prompt,
                    system_prompt=system_prompt,
                    output_schema=output_schema,
                    api_key=api_key,
                )
                result.attempts = attempt
                return result
            except CodexToolUseError as exc:
                last_error = exc
                if attempt == max_attempts:
                    break

        raise CodexToolRetryError(
            f"Codex used tools after {max_attempts} attempt(s). Last error: {last_error}"
        )

    def _complete_once(
        self,
        prompt: str,
        *,
        system_prompt: str | None,
        output_schema: Path | None,
        api_key: str | None,
    ) -> CodexLLMResult:
        with tempfile.TemporaryDirectory(prefix="codex-llm-") as tmpdir:
            cmd = self._build_command(Path(tmpdir), output_schema)
            env = os.environ.copy()
            if api_key:
                env["CODEX_API_KEY"] = api_key

            completed = subprocess.run(
                cmd,
                input=self._compose_prompt(system_prompt, prompt),
                text=True,
                capture_output=True,
                timeout=self.timeout,
                env=env,
                check=False,
            )

        if completed.returncode != 0:
            raise CodexExecError(
                f"codex exec failed with exit code {completed.returncode}\n"
                f"stderr:\n{completed.stderr.strip()}"
            )

        return self._parse_jsonl(completed.stdout)

    def _build_command(self, cwd: Path, output_schema: Path | None) -> list[str]:
        cmd = [
            self.codex_bin,
            "--ask-for-approval",
            "never",
            "exec",
            "--json",
            "--ephemeral",
            "--ignore-user-config",
            "--ignore-rules",
            "--skip-git-repo-check",
            "--sandbox",
            "read-only",
            "--cd",
            str(cwd),
            "-c",
            'web_search="disabled"',
            "-c",
            "features.multi_agent=false",
            "-c",
            "project_doc_max_bytes=0",
            "-c",
            "project_root_markers=[]",
            "-c",
            'shell_environment_policy.inherit="none"',
            "-c",
            "allow_login_shell=false",
        ]
        if self.model:
            cmd.extend(["--model", self.model])
        if self.model_reasoning_effort:
            cmd.extend(["-c", f'model_reasoning_effort="{self.model_reasoning_effort}"'])
        if output_schema:
            cmd.extend(["--output-schema", str(output_schema)])
        cmd.append("-")
        return cmd

    def _compose_prompt(self, system_prompt: str | None, prompt: str) -> str:
        system = self.system_prompt if system_prompt is None else system_prompt
        if not system:
            return prompt
        return f"{system.strip()}\n\nUser prompt:\n{prompt}"

    def _parse_jsonl(self, stdout: str) -> CodexLLMResult:
        events: list[dict[str, Any]] = []
        tool_events: list[str] = []
        final_text = ""
        usage: dict[str, Any] | None = None

        for line in stdout.splitlines():
            if not line.strip():
                continue
            event = json.loads(line)
            events.append(event)

            item = event.get("item") or {}
            item_type = item.get("type")
            if self.strict_no_tools and item_type in TOOL_ITEM_TYPES:
                tool_events.append(item_type)
            if item_type == "agent_message" and "text" in item:
                final_text = item["text"]
            if event.get("type") == "turn.completed":
                usage = event.get("usage")

        if tool_events:
            seen = ", ".join(sorted(set(tool_events)))
            raise CodexToolUseError(f"Codex used disallowed tool event(s): {seen}")
        if not final_text:
            raise CodexExecError("codex exec completed without an agent message.")
        return CodexLLMResult(text=final_text, events=events, usage=usage)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Call Codex CLI like a simple LLM API.")
    parser.add_argument("prompt", nargs="?", help="Prompt text. Reads stdin when omitted.")
    parser.add_argument("--system", default=DEFAULT_SYSTEM_PROMPT)
    parser.add_argument("--model", default=os.getenv("CODEX_LLM_MODEL"))
    parser.add_argument("--model-reasoning-effort", default=os.getenv("CODEX_LLM_REASONING_EFFORT"))
    parser.add_argument("--codex-bin", default=os.getenv("CODEX_BIN", "codex"))
    parser.add_argument("--timeout", type=float, default=120.0)
    parser.add_argument(
        "--max-tool-retries",
        type=int,
        default=3,
        help="Retry this many times if Codex emits tool events.",
    )
    parser.add_argument("--output-schema", type=Path)
    parser.add_argument("--api-key", default=os.getenv("CODEX_API_KEY"))
    parser.add_argument(
        "--allow-tools",
        action="store_true",
        help="Do not fail if Codex emits tool events.",
    )
    parser.add_argument(
        "--show-usage",
        action="store_true",
        help="Print token usage JSON to stderr after the response.",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    prompt = args.prompt
    if prompt is None:
        import sys

        prompt = sys.stdin.read()

    client = CodexLLM(
        model=args.model,
        model_reasoning_effort=args.model_reasoning_effort,
        codex_bin=args.codex_bin,
        timeout=args.timeout,
        system_prompt=args.system,
        strict_no_tools=not args.allow_tools,
        max_tool_retries=args.max_tool_retries,
    )
    result = client.complete(
        prompt,
        output_schema=args.output_schema,
        api_key=args.api_key,
    )
    print(result.text)
    if args.show_usage and result.usage is not None:
        import sys

        print(json.dumps(result.usage), file=sys.stderr)
    return 0
