"""Tool-enabled Fable evaluation through a fresh Claude Code CLI session."""

from __future__ import annotations

import json
import os
import signal
import subprocess
import tempfile


def parse_events(stdout: str, api_model: str) -> dict:
    events = [json.loads(line) for line in stdout.splitlines() if line.strip()]
    results = [e for e in events if e.get("type") == "result"]
    if not results:
        raise ValueError("Claude CLI returned no completion result.")
    result = results[-1]
    if result.get("is_error") or result.get("subtype") != "success":
        raise ValueError(f"Claude CLI failed: {result.get('result', result.get('subtype'))}")
    assistants = [e["message"] for e in events if e.get("type") == "assistant"]
    models = {m.get("model") for m in assistants}
    if not models or not models <= {api_model, "claude-fable-5"}:
        raise ValueError(f"Expected Fable 5; Claude CLI used {sorted(str(m) for m in models)}.")
    if any(m.get("stop_reason") == "max_tokens" for m in assistants):
        raise ValueError("Claude CLI returned a truncated response.")
    text = result.get("result", "").strip()
    if not text:
        raise ValueError("Claude CLI returned no answer text.")
    calls = [b for m in assistants for b in m.get("content", []) if b.get("type") == "tool_use"]
    tool_results = [b for e in events if e.get("type") == "user"
                    for b in e.get("message", {}).get("content", [])
                    if isinstance(b, dict) and b.get("type") == "tool_result"]
    return {"response": text, "usage": result.get("usage"), "actual_model": "claude-fable-5",
            "attempts": 1, "stop_reason": result.get("stop_reason"),
            "refused": any(m.get("stop_reason") == "refusal" for m in assistants),
            "tool_events": [b["name"] for b in calls], "tool_calls": calls,
            "tool_results": tool_results, "num_turns": result.get("num_turns")}


def make_predictor(args, api_model: str, system_prompt: str, image_block):
    def predict(question, image):
        env = os.environ.copy()
        # --bare uses explicit API credentials and skips user hooks/memory/plugins.
        key = env.get("ANTHROPIC_AUTH_TOKEN") or env.get("ANTHROPIC_API_KEY") or env.get("CLAUDE_API_KEY")
        if not key:
            raise ValueError("Fable tools require Anthropic API/gateway credentials.")
        env["ANTHROPIC_API_KEY"] = key
        env["CLAUDE_CODE_MAX_OUTPUT_TOKENS"] = str(args.max_output_tokens)
        env.pop("CLAUDECODE", None)
        tools = ["Bash", "Read", "Write", "Edit"]
        if args.web_search == "live":
            tools += ["WebSearch", "WebFetch"]
        content = ([image_block(image)] if image else []) + [{"type": "text", "text": question["question"]}]
        message = {"type": "user", "message": {"role": "user", "content": content}}
        settings = {"modelOverrides": {"claude-fable-5": api_model},
                    "env": {"ANTHROPIC_DEFAULT_FABLE_MODEL": api_model}}
        command = [
            args.claude_bin, "--bare", "-p", "--model", api_model,
            "--effort", args.reasoning_effort, "--max-turns", str(args.max_tool_turns),
            "--system-prompt", system_prompt, "--input-format", "stream-json",
            "--output-format", "stream-json", "--verbose", "--no-session-persistence",
            "--disable-slash-commands", "--setting-sources", "", "--settings", json.dumps(settings),
            "--strict-mcp-config", "--mcp-config", '{"mcpServers":{}}',
            "--permission-mode", "dontAsk", "--tools", ",".join(tools),
            "--allowedTools", ",".join(tools),
        ]
        with tempfile.TemporaryDirectory(prefix="cmt-fable-tools-") as tmp:
            process = subprocess.Popen(command, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                       stderr=subprocess.PIPE, text=True, cwd=tmp, env=env,
                                       start_new_session=True)
            try:
                stdout, stderr = process.communicate(json.dumps(message) + "\n", timeout=args.timeout)
            except subprocess.TimeoutExpired:
                os.killpg(process.pid, signal.SIGKILL)
                process.communicate()
                raise TimeoutError("Fable tool session exceeded --timeout.") from None
        if process.returncode:
            # Parse the structured error first; stderr alone can omit API errors.
            if stdout.strip():
                parse_events(stdout, api_model)
            raise ValueError(f"Claude CLI exited {process.returncode}: {stderr[-2000:]}")
        return parse_events(stdout, api_model)
    return predict
