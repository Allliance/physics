"""Small resumable-eval client for an OpenAI-compatible chat endpoint."""

from __future__ import annotations

import http.client
import json
import os
from pathlib import Path
import signal
import shutil
import subprocess
import tempfile
import time
import urllib.error
import urllib.request


RUN_COMMAND_TOOL = {
    "type": "function",
    "function": {
        "name": "run_command",
        "description": (
            "Run a shell command in an isolated writable scratch directory with no network. "
            "Use Python, SymPy, or other installed command-line tools for calculations."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "command": {"type": "string", "description": "Shell command to execute."},
            },
            "required": ["command"],
            "additionalProperties": False,
        },
    },
}


class ToolLoopError(RuntimeError):
    """A native tool loop failed after receiving billable model responses."""

    def __init__(self, message: str, partial_result: dict):
        super().__init__(message)
        self.partial_result = partial_result


class OutputTruncatedError(ToolLoopError):
    """The model exhausted its output budget before returning an answer."""


def sandbox_config(codex_bin: str) -> str:
    executable = shutil.which(codex_bin)
    if not executable:
        raise FileNotFoundError(f"Codex executable not found: {codex_bin}")
    executable = str(Path(executable).resolve())
    return f'''default_permissions = "eval-tool"

[permissions.eval-tool]
extends = ":workspace"

[permissions.eval-tool.filesystem]
":root" = "deny"
":minimal" = "read"
"{executable}" = "read"

[permissions.eval-tool.filesystem.":workspace_roots"]
"." = "write"

[permissions.eval-tool.network]
enabled = false
'''


def backend_metadata() -> dict:
    """Return stable provenance metadata recorded in evaluation manifests.

    The optional manifest overrides are useful when a resumable run changes
    transport/provider without changing the evaluated model or decoding.  The
    actual connection always comes from OPENAI_COMPAT_BASE_URL/MODEL.
    """
    return {
        "base_url": os.environ.get(
            "OPENAI_COMPAT_MANIFEST_BASE_URL",
            os.environ.get("OPENAI_COMPAT_BASE_URL", "http://127.0.0.1:8000/v1"),
        ),
        "served_model": os.environ.get(
            "OPENAI_COMPAT_MANIFEST_MODEL",
            os.environ.get("OPENAI_COMPAT_MODEL", "openai/gpt-oss-120b"),
        ),
        "wire_api": "chat_completions",
    }


def connection_config() -> dict:
    return {
        "base_url": os.environ.get("OPENAI_COMPAT_BASE_URL", "http://127.0.0.1:8000/v1"),
        "served_model": os.environ.get("OPENAI_COMPAT_MODEL", "openai/gpt-oss-120b"),
    }


def _openrouter_headers() -> dict[str, str]:
    api_key = os.environ.get("OPENAI_COMPAT_API_KEY") or os.environ.get("OPENROUTER_API_KEY")
    if not api_key:
        raise RuntimeError("OPENROUTER_API_KEY is required for an OpenRouter endpoint")
    return {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
        "HTTP-Referer": os.environ.get(
            "OPENROUTER_HTTP_REFERER", "https://github.com/physics-evaluation"
        ),
        "X-Title": os.environ.get("OPENROUTER_APP_TITLE", "Physics LLM Evaluation"),
    }


def _openrouter_chat(payload: dict, *, timeout: float, attempts: int = 5) -> dict:
    config = connection_config()
    request = urllib.request.Request(
        f'{config["base_url"].rstrip("/")}/chat/completions',
        data=json.dumps(payload).encode(), method="POST", headers=_openrouter_headers(),
    )
    last_error = None
    for attempt in range(1, attempts + 1):
        try:
            with urllib.request.urlopen(request, timeout=timeout) as response:
                return json.load(response)
        except urllib.error.HTTPError as exc:
            last_error = RuntimeError(f"HTTP {exc.code}: {exc.read().decode(errors='replace')}")
        except (urllib.error.URLError, TimeoutError, http.client.IncompleteRead,
                json.JSONDecodeError,
                KeyError, IndexError, ValueError) as exc:
            last_error = exc
        if attempt < attempts:
            time.sleep(min(2 ** (attempt - 1), 8))
    raise RuntimeError(f"OpenRouter chat request failed after {attempts} attempts: {last_error}")


def _sandboxed_command(command: str, *, workspace: Path, codex_home: Path,
                       codex_bin: str, timeout: float) -> dict:
    """Execute one model-requested command through the Codex local sandbox."""
    environment = {
        "PATH": "/usr/local/bin:/usr/bin:/bin",
        "HOME": str(codex_home),
        "CODEX_HOME": str(codex_home),
        "TMPDIR": str(workspace),
        "TMP": str(workspace),
        "TEMP": str(workspace),
        "LANG": "C.UTF-8",
        "PYTHONNOUSERSITE": "1",
    }
    executable = shutil.which(codex_bin)
    if not executable:
        raise FileNotFoundError(f"Codex executable not found: {codex_bin}")
    argv = [
        executable, "sandbox", "-P", "eval-tool", "-C", str(workspace),
        "--sandbox-state-disable-network", "--", "/bin/bash", "-c", command,
    ]
    process = subprocess.Popen(
        argv, text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
        env=environment, start_new_session=True,
    )
    try:
        stdout, stderr = process.communicate(timeout=timeout)
        result = {
            "exit_code": process.returncode,
            "stdout": stdout[-20000:],
            "stderr": stderr[-5000:],
        }
    except subprocess.TimeoutExpired as exc:
        # Killing only the Codex launcher can orphan a resource-intensive
        # command inside its sandbox.  Each invocation owns a fresh session,
        # so terminating the process group reliably reaps every descendant.
        os.killpg(process.pid, signal.SIGKILL)
        stdout, stderr = process.communicate()
        result = {
            "exit_code": None,
            "stdout": (stdout or "")[-20000:],
            "stderr": (stderr or "")[-5000:],
            "error": f"Command exceeded {timeout:g} seconds",
        }
    return result


def _aggregate_usage(values: list[dict]) -> dict:
    keys = ("prompt_tokens", "completion_tokens", "total_tokens", "cost")
    result = {key: sum(value.get(key, 0) or 0 for value in values) for key in keys}
    web_searches = sum(
        (
            (value.get("server_tool_use") or {}).get("web_search_requests", 0)
            or (value.get("server_tool_use_details") or {}).get(
                "web_search_requests", 0
            )
            or 0
        )
        for value in values
    )
    if web_searches:
        result["server_tool_use"] = {"web_search_requests": web_searches}
    return result


def _partial_tool_result(config: dict, usage_by_turn: list[dict], trace: list[dict],
                         actual_model: str | None) -> dict:
    return {
        "usage": _aggregate_usage(usage_by_turn),
        "usage_by_turn": usage_by_turn,
        "actual_model": actual_model,
        "requested_model": config["served_model"],
        "tool_events": [item["name"] for item in trace],
        "tool_trace": trace,
        "completed_turns": len(usage_by_turn),
    }


def generate_with_tools(prompt: str, *, system_prompt: str, reasoning_effort: str,
                        max_output_tokens: int, timeout: float, max_tool_turns: int = 20,
                        command_timeout: float = 120, web_search: bool = True,
                        web_search_engine: str = "auto",
                        web_search_max_total_results: int = 10,
                        prior_reasoning: str | None = None,
                        codex_bin: str = "codex") -> dict:
    """Run a native OpenRouter tool loop with commands isolated by Codex.

    OpenRouter executes its hosted web-search tool. Local commands run with the
    Codex ``eval-tool`` permission profile: only the temporary workspace is
    writable, non-minimal filesystem reads are denied, and network is disabled.
    """
    config = connection_config()
    if "openrouter.ai" not in config["base_url"]:
        raise ValueError("Native tool generation requires an OpenRouter endpoint")
    if min(max_output_tokens, timeout, max_tool_turns, command_timeout) <= 0:
        raise ValueError("Token, timeout, and tool-turn limits must be positive")
    supported_search_engines = {
        "auto", "native", "exa", "firecrawl", "parallel", "perplexity",
    }
    if web_search_engine not in supported_search_engines:
        raise ValueError(f"Unsupported web-search engine: {web_search_engine!r}")
    if web_search_max_total_results <= 0:
        raise ValueError("Web-search result limit must be positive")
    messages = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": prompt},
    ]
    if prior_reasoning:
        messages.extend([
            {
                "role": "assistant",
                "content": "Prior working notes from this same attempt:\n\n" + prior_reasoning,
            },
            {
                "role": "user",
                "content": (
                    "Continue from these working notes. Verify or complete the solution "
                    "with the available local execution tool if useful, then return the "
                    "requested self-contained final answer. Do not request web search."
                ),
            },
        ])
    tools = [RUN_COMMAND_TOOL]
    if web_search:
        tools.append({
            "type": "openrouter:web_search",
            "parameters": {
                "engine": web_search_engine,
                "max_results": 5,
                "max_total_results": web_search_max_total_results,
            },
        })
    usage_by_turn = []
    trace = []
    actual_model = None
    force_answer = False
    with (tempfile.TemporaryDirectory(prefix="openrouter-tools-") as directory,
          tempfile.TemporaryDirectory(prefix="codex-sandbox-home-") as home):
        workspace = Path(directory)
        codex_home = Path(home)
        (codex_home / "config.toml").write_text(sandbox_config(codex_bin))
        # Permit at most ``max_tool_turns`` command rounds, followed by one
        # answer-only turn so the last command result can be synthesized.
        for turn in range(1, max_tool_turns + 2):
            answer_only = turn > max_tool_turns
            payload = {
                "model": config["served_model"],
                "messages": messages,
                "tools": tools,
                "tool_choice": "none" if answer_only or force_answer else "auto",
                "parallel_tool_calls": False,
                "reasoning": {"effort": reasoning_effort},
                "max_tokens": max_output_tokens,
            }
            provider_sort = os.environ.get("OPENROUTER_PROVIDER_SORT")
            if provider_sort:
                payload["provider"] = {"sort": provider_sort}
            # Evaluation retries happen at the checkpoint layer. Retrying an
            # indeterminate timed-out request here could duplicate a paid turn.
            try:
                raw = _openrouter_chat(payload, timeout=timeout, attempts=1)
            except Exception as exc:
                if usage_by_turn:
                    raise ToolLoopError(
                        f"OpenRouter tool loop failed on turn {turn}: {exc}",
                        _partial_tool_result(
                            config, usage_by_turn, trace, actual_model
                        ),
                    ) from exc
                raise
            usage_by_turn.append(raw.get("usage") or {})
            actual_model = raw.get("model") or actual_model
            choice = raw["choices"][0]
            message = choice["message"]
            calls = message.get("tool_calls") or []
            if not calls:
                text = (message.get("content") or "").strip()
                if not text:
                    finish = choice.get("finish_reason")
                    hosted_searches = (
                        (raw.get("usage") or {}).get("server_tool_use_details") or {}
                    ).get("web_search_requests", 0) or 0
                    if finish == "tool_calls" and hosted_searches and not force_answer:
                        # A hosted search can consume the configured cumulative
                        # result budget just as the model asks for another search.
                        # OpenRouter then returns an empty tool_calls finish with
                        # no client-side call to execute. Preserve the assistant
                        # message (including reasoning details) and give the model
                        # one answer-only continuation instead of discarding the
                        # completed research and reasoning.
                        messages.append(message)
                        messages.append({
                            "role": "user",
                            "content": (
                                "The hosted-search round has ended. Using the research "
                                "and reasoning already completed, return the requested "
                                "self-contained final answer now. Do not request another "
                                "tool."
                            ),
                        })
                        force_answer = True
                        continue
                    if finish == "length":
                        partial = _partial_tool_result(
                            config, usage_by_turn, trace, actual_model
                        )
                        partial.update({
                            "finish_reason": finish,
                            "reasoning_content": (
                                message.get("reasoning_content") or message.get("reasoning")
                            ),
                        })
                        raise OutputTruncatedError(
                            "OpenRouter exhausted the output-token limit before an answer",
                            partial,
                        )
                    partial = _partial_tool_result(
                        config, usage_by_turn, trace, actual_model
                    )
                    partial.update({
                        "finish_reason": finish,
                        "native_finish_reason": choice.get("native_finish_reason"),
                        "reasoning_content": (
                            message.get("reasoning_content") or message.get("reasoning")
                        ),
                        "provider_error": choice.get("error") or raw.get("error"),
                    })
                    raise ToolLoopError(
                        f"OpenRouter returned neither tool calls nor an answer "
                        f"(finish={finish!r})",
                        partial,
                    )
                hosted = sum(
                    (usage.get("server_tool_use") or {}).get("web_search_requests", 0) or 0
                    for usage in usage_by_turn
                )
                annotations = message.get("annotations") or []
                cited_web = any(
                    annotation.get("type") == "url_citation"
                    for annotation in annotations
                    if isinstance(annotation, dict)
                )
                tool_events = [item["name"] for item in trace]
                tool_events.extend(
                    ["openrouter:web_search"] * (hosted or int(cited_web))
                )
                return {
                    "response": text,
                    "reasoning_content": message.get("reasoning_content") or message.get("reasoning"),
                    "usage": _aggregate_usage(usage_by_turn),
                    "usage_by_turn": usage_by_turn,
                    "actual_model": raw.get("model"),
                    "requested_model": config["served_model"],
                    "finish_reason": choice.get("finish_reason"),
                    "attempts": 1,
                    "tool_events": tool_events,
                    "tool_trace": trace,
                    "web_annotations": annotations,
                    "web_search_engine": web_search_engine,
                    "web_search_max_total_results": web_search_max_total_results,
                    "refused": False,
                }
            messages.append(message)
            for call in calls:
                if answer_only:
                    partial = _partial_tool_result(
                        config, usage_by_turn, trace, actual_model
                    )
                    partial.update({
                        "finish_reason": choice.get("finish_reason"),
                        "terminal_failure": "tool_turn_limit",
                    })
                    raise ToolLoopError(
                        f"OpenRouter model requested another tool after "
                        f"{max_tool_turns} tool turns",
                        partial,
                    )
                name = call.get("function", {}).get("name")
                if not isinstance(name, str) or name.lower() != "run_command":
                    raise ValueError(f"Unexpected client-side tool call: {name!r}")
                name = "run_command"
                arguments = json.loads(call["function"]["arguments"])
                command = arguments.get("command")
                if not isinstance(command, str) or not command.strip():
                    raise ValueError("run_command requires a nonempty command")
                result = _sandboxed_command(
                    command, workspace=workspace, codex_home=codex_home,
                    codex_bin=codex_bin, timeout=command_timeout,
                )
                trace.append({
                    "turn": turn, "name": name, "arguments": arguments, "result": result,
                })
                messages.append({
                    "role": "tool", "tool_call_id": call["id"],
                    "content": json.dumps(result),
                })
    raise AssertionError("unreachable")


def generate(prompt: str, *, system_prompt: str, reasoning_effort: str,
             max_output_tokens: int, timeout: float, attempts: int = 5,
             temperature: float | None = None, top_p: float | None = None,
             output_schema: dict | None = None) -> dict:
    config = connection_config()
    timeout = float(os.environ.get("OPENAI_COMPAT_TIMEOUT_OVERRIDE", timeout))
    is_openrouter = "openrouter.ai" in config["base_url"]
    payload = {
        "model": config["served_model"],
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": prompt},
        ],
        "max_tokens": max_output_tokens,
    }
    if is_openrouter:
        payload["reasoning"] = {"effort": reasoning_effort}
        provider_sort = os.environ.get("OPENROUTER_PROVIDER_SORT")
        if provider_sort:
            payload["provider"] = {"sort": provider_sort}
    else:
        payload["reasoning_effort"] = reasoning_effort
    if temperature is not None:
        payload["temperature"] = temperature
    if top_p is not None:
        payload["top_p"] = top_p
    if output_schema is not None:
        payload["response_format"] = {
            "type": "json_schema",
            "json_schema": {"name": "response", "strict": True, "schema": output_schema},
        }
    api_key = os.environ.get("OPENAI_COMPAT_API_KEY")
    if is_openrouter:
        api_key = api_key or os.environ.get("OPENROUTER_API_KEY")
        if not api_key:
            raise RuntimeError("OPENROUTER_API_KEY is required for an OpenRouter endpoint")
    headers = {
        "Authorization": f"Bearer {api_key or 'EMPTY'}",
        "Content-Type": "application/json",
    }
    if is_openrouter:
        headers["HTTP-Referer"] = os.environ.get(
            "OPENROUTER_HTTP_REFERER", "https://github.com/physics-evaluation"
        )
        headers["X-Title"] = os.environ.get("OPENROUTER_APP_TITLE", "Physics LLM Evaluation")
    request = urllib.request.Request(
        f'{config["base_url"].rstrip("/")}/chat/completions',
        data=json.dumps(payload).encode(), method="POST",
        headers=headers,
    )
    last_error = None
    for attempt in range(1, attempts + 1):
        try:
            with urllib.request.urlopen(request, timeout=timeout) as response:
                raw = json.load(response)
            choice = raw["choices"][0]
            message = choice["message"]
            text = (message.get("content") or "").strip()
            if choice.get("finish_reason") == "error":
                raise ValueError("OpenAI-compatible endpoint returned finish_reason=error")
            if not text and choice.get("finish_reason") == "length":
                return {
                    "response": "[No completed answer: configured generation limit exhausted.]",
                    "response_is_placeholder": True,
                    "limit_exhausted": True,
                    "usage": raw.get("usage") or {},
                    "actual_model": raw.get("model"),
                    "finish_reason": "length",
                    "attempts": attempt,
                    "tool_events": [],
                }
            if not text:
                raise ValueError("OpenAI-compatible endpoint returned no final-channel answer")
            return {
                "response": text,
                "reasoning_content": message.get("reasoning_content") or message.get("reasoning"),
                "usage": raw.get("usage") or {},
                "actual_model": raw.get("model"),
                "finish_reason": choice.get("finish_reason"),
                "attempts": attempt,
                "tool_events": [],
            }
        except urllib.error.HTTPError as exc:
            last_error = RuntimeError(f"HTTP {exc.code}: {exc.read().decode(errors='replace')}")
        except (urllib.error.URLError, TimeoutError, http.client.IncompleteRead,
                json.JSONDecodeError,
                KeyError, IndexError, ValueError) as exc:
            last_error = exc
        if attempt < attempts:
            time.sleep(min(2 ** (attempt - 1), 8))
    raise RuntimeError(f"OpenAI-compatible generation failed after {attempts} attempts: {last_error}")
