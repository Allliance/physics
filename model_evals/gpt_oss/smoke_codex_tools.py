#!/usr/bin/env python3
"""Verify that Codex executes a local GPT-OSS tool call through vLLM."""

import json
import os
from pathlib import Path
import sys


ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from utils.codex_cli import CodexLLM, validate_codex_result


base_url = os.environ["OPENAI_COMPAT_BASE_URL"]
model = os.environ.get("OPENAI_COMPAT_MODEL", "openai/gpt-oss-120b")
client = CodexLLM(
    model=model, model_reasoning_effort="high", timeout=600,
    system_prompt="Use the shell tool when explicitly requested, then give a concise final answer.",
    strict_no_tools=False, web_search="live", sandbox_mode="workspace-write",
    env_inherit="none", env_set={"PATH": "/usr/local/bin:/usr/bin:/bin"},
    max_exec_retries=0, config_overrides=[
        'features.unified_exec=false',
        'model_provider="vllm"',
        'model_providers.vllm.name="gpt-oss"',
        f'model_providers.vllm.base_url="{base_url}"',
        'model_providers.vllm.wire_api="responses"',
        'model_providers.vllm.requires_openai_auth=false',
    ],
)
result = client.complete("Use the shell to run `python3 -c 'print(6*7)'`. Report its output.")
validate_codex_result(result)
tool_events = [event.get("item", {}).get("type") for event in result.events
               if event.get("item", {}).get("type") in
               {"command_execution", "file_change", "mcp_tool_call", "web_search"}]
if "command_execution" not in tool_events:
    raise RuntimeError(f"Codex/GPT-OSS completed without the required shell call: {tool_events}")
print(json.dumps({"response": result.text, "tool_events": tool_events,
                  "usage": result.usage}, indent=2))
