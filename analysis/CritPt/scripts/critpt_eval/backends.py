"""CritPt prompts over the same Codex/Anthropic transports used by HLE."""

import importlib
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile

from .prompts import PREDICTION, PREDICTION_TOOLS, JUDGE_SYSTEM, JUDGE, JUDGE_SCHEMA
from .storage import fingerprint

REPOSITORY = Path(__file__).resolve().parents[4]
for directory in (REPOSITORY, REPOSITORY / "utils"):
    if str(directory) not in sys.path:
        sys.path.insert(0, str(directory))

from utils.fable_backend import (
    GenerationLimitError, make_fable_client, parse_fable_response, resolve_fable_model,
)

TOOL_PATH = "/usr/local/bin:/usr/bin:/bin"


def make_claude_predictor(args, api_model, system_prompt, image_block):
    """Load the historical tool harness only for standalone tool evaluations."""
    archive = REPOSITORY / "benchmarks/hle_changed (discarded)"
    if str(archive) not in sys.path:
        sys.path.insert(0, str(archive))
    legacy = importlib.import_module("hle_eval.claude")
    predict = legacy.make_predictor(args, api_model, system_prompt, image_block)

    def complete(question, image):
        try:
            return predict(question, image)
        except legacy.GenerationLimitError as error:
            raise GenerationLimitError(str(error)) from error

    return complete


def backend_config(args):
    config = {
        "api_model": resolve_fable_model(args.fable_model),
        "anthropic_route_sha256": fingerprint(os.environ.get("ANTHROPIC_BASE_URL", "https://api.anthropic.com")),
        "codex_bin": args.codex_bin,
        "claude_bin": args.claude_bin,
        "claude_launch_mode": "safe-mode" if args.model == "claude-fable-5" and args.use_tools else None,
    }
    if args.model == "gemini-3.1-pro-preview":
        from gemini_backend import backend_metadata
        config["gemini"] = backend_metadata(args.reasoning_effort)
    if args.model in {"gpt-oss-120b", "kimi-k3", "glm-5.3", "deepseek-v4-pro"}:
        from openai_compatible import backend_metadata
        config["openai_compatible"] = backend_metadata()
        if args.use_tools:
            config["codex_harness"] = {"wire_api": "responses", "harness": "codex exec",
                                       "tool_environment": {"PATH": TOOL_PATH}}
    return config


def codex_client(args, *, judge=False):
    from codex_cli import CodexLLM

    tools = args.use_tools and not judge
    return CodexLLM(
        model=args.judge_model if judge else args.model,
        model_reasoning_effort=args.judge_reasoning_effort if judge else args.reasoning_effort,
        codex_bin=args.codex_bin, timeout=args.timeout,
        system_prompt=JUDGE_SYSTEM if judge else PREDICTION_TOOLS if tools else PREDICTION,
        strict_no_tools=not tools, web_search=args.web_search if tools else "disabled",
        sandbox_mode="workspace-write" if tools else "read-only", env_inherit="none",
        env_set={"PATH": TOOL_PATH} if tools else None,
        max_exec_retries=0 if judge else 6, max_tool_retries=0,
    )


def validate_codex_result(result):
    # The wrapper can extract text from a failed stream. Require an actual
    # completed turn, so a truncated or failed answer never becomes a prediction.
    terminal = [(index, event.get("type")) for index, event in enumerate(result.events)
                if event.get("type") in {"turn.completed", "turn.failed"}]
    if not terminal or terminal[-1][1] != "turn.completed":
        raise ValueError("Codex stream did not complete successfully")
    completed_at = terminal[-1][0]
    if any(event.get("type") == "error" for event in result.events[completed_at + 1:]):
        raise ValueError("Codex stream errored after completion")
    if not isinstance(result.text, str) or not result.text.strip():
        raise ValueError("Codex stream completed without answer text")


def make_predictor(args, config):
    if args.model == "gemini-3.1-pro-preview":
        from gemini_backend import generate, GeminiLimitError

        def predict(question):
            try:
                return generate(
                    question["question"], effort=args.reasoning_effort,
                    max_output_tokens=args.max_output_tokens, timeout=args.timeout,
                    system_prompt=PREDICTION_TOOLS if args.use_tools else PREDICTION,
                    use_tools=args.use_tools, web_search=args.web_search == "live",
                )
            except GeminiLimitError as exc:
                raise GenerationLimitError(str(exc)) from exc
        return predict
    if args.model in {"gpt-oss-120b", "kimi-k3", "glm-5.3", "deepseek-v4-pro"}:
        if args.use_tools:
            from codex_cli import CodexExecError, CodexLLM
            from openai_compatible import backend_metadata

            local = backend_metadata()
            client = CodexLLM(
                model=local["served_model"], model_reasoning_effort=args.reasoning_effort,
                codex_bin=args.codex_bin, timeout=args.timeout,
                system_prompt=PREDICTION_TOOLS, strict_no_tools=False,
                web_search=args.web_search, sandbox_mode="workspace-write", env_inherit="none",
                env_set={"PATH": TOOL_PATH}, max_exec_retries=6, max_tool_retries=0,
                config_overrides=[
                    'model_provider="vllm"',
                    'model_providers.vllm.name="gpt-oss"',
                    f'model_providers.vllm.base_url="{local["base_url"]}"',
                    'model_providers.vllm.wire_api="responses"',
                    'model_providers.vllm.requires_openai_auth=false',
                ],
            )

            def predict(question):
                try:
                    result = client.complete(question["question"])
                except subprocess.TimeoutExpired:
                    raise GenerationLimitError("Codex session exhausted its timeout budget") from None
                except CodexExecError as exc:
                    if "completed without an agent message" in str(exc):
                        raise GenerationLimitError(
                            "Codex session completed without an answer"
                        ) from None
                    raise
                validate_codex_result(result)
                trace = [event for event in result.events if event.get("item", {}).get("type") in
                         {"command_execution", "file_change", "mcp_tool_call", "web_search"}]
                return {"response": result.text, "usage": result.usage, "attempts": result.attempts,
                        "tool_trace": trace, "tool_events": [e["item"]["type"] for e in trace]}
            return predict
        from openai_compatible import generate

        def predict(question):
            return generate(question["question"], system_prompt=PREDICTION,
                            reasoning_effort=args.reasoning_effort,
                            max_output_tokens=args.max_output_tokens, timeout=args.timeout,
                            temperature=1.0 if args.model != "gpt-oss-120b" else None,
                            top_p=(1.0 if args.model == "deepseek-v4-pro" else 0.95)
                            if args.model != "gpt-oss-120b" else None)
        return predict
    if args.model in {"gpt-5.6-sol", "gpt-5.6-luna", "gpt-6-astra"}:
        client = codex_client(args)

        def predict(question):
            try:
                result = client.complete(question["question"])
            except subprocess.TimeoutExpired:
                raise GenerationLimitError("Codex session exhausted its timeout budget") from None
            validate_codex_result(result)
            trace = [event for event in result.events if event.get("item", {}).get("type") in
                     {"command_execution", "file_change", "mcp_tool_call", "web_search"}]
            return {"response": result.text, "usage": result.usage, "attempts": result.attempts,
                    "tool_trace": trace, "tool_events": [e["item"]["type"] for e in trace]}
        return predict
    if args.use_tools:
        cli = make_claude_predictor(args, config["api_model"], PREDICTION_TOOLS, None)
        return lambda question: cli({"question": question["question"]}, None)
    client = make_fable_client(args.timeout)

    def predict(question):
        with client.messages.stream(
            model=config["api_model"], max_tokens=args.max_output_tokens, system=PREDICTION,
            messages=[{"role": "user", "content": question["question"]}],
            thinking={"type": "adaptive"}, output_config={"effort": args.reasoning_effort},
        ) as stream:
            message = stream.get_final_message().model_dump(mode="json")
        return parse_fable_response(message, config["api_model"])
    return predict


def validate_judgment(content):
    if not isinstance(content, dict) or set(content) != set(JUDGE_SCHEMA["required"]):
        raise ValueError("Judge response must match the JSON schema")
    if content["correct"] not in {"yes", "no"}:
        raise ValueError("Judge correctness must be yes or no")
    if type(content["confidence"]) is not int or not 0 <= content["confidence"] <= 100:
        raise ValueError("Judge confidence must be an integer from 0 to 100")
    for field in ("reasoning", "extracted_final_answer"):
        if not isinstance(content[field], str) or not content[field].strip():
            raise ValueError(f"Judge returned empty {field}")


def make_judge(args, config):
    client = make_fable_client(args.timeout) if args.judge_model == "claude-fable-5" else codex_client(args, judge=True)

    def judge(question, prediction, answer):
        payload = {"problem": question["question"], "ground_truth": answer,
                   "model_solution": prediction["response"]}
        prompt = JUDGE + "\n" + json.dumps(payload, ensure_ascii=False)
        if args.judge_model == "claude-fable-5":
            with client.messages.stream(
                model=config["api_model"], max_tokens=args.judge_max_output_tokens,
                system=JUDGE_SYSTEM,
                messages=[{"role": "user", "content": prompt + "\nOutput schema:\n" + json.dumps(JUDGE_SCHEMA)}],
                thinking={"type": "adaptive"}, output_config={"effort": args.judge_reasoning_effort},
            ) as stream:
                message = stream.get_final_message().model_dump(mode="json")
            response = parse_fable_response(message, config["api_model"])
            if response["refused"]:
                raise ValueError("Judge refused; judgment remains pending")
            raw, usage = response["response"], response["usage"]
            actual_model = response["actual_model"]
        else:
            with tempfile.TemporaryDirectory(prefix="critpt-judge-") as directory:
                schema = Path(directory) / "schema.json"
                schema.write_text(json.dumps(JUDGE_SCHEMA))
                response = client.complete(prompt, output_schema=schema)
            validate_codex_result(response)
            raw, usage = response.text, response.usage
            actual_model = None  # The Codex wrapper does not report an observed model ID.
        content = json.loads(raw)
        validate_judgment(content)
        return {"judgment": content, "usage": usage, "raw_response": raw, "actual_model": actual_model}
    return judge
