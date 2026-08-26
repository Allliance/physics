from __future__ import annotations
from typing import Callable, Dict, Optional
from together import Together
import anthropic
from openai import OpenAI
import os

import httpx
import json
# with open("api_keys.json", "r") as f:
#     API_KEYS = json.load(f)
# --- Together model mapping ---------------------------------------------------
TOGETHER_ALIASES: Dict[str, str] = {
    # "DeepSeek-R1-Distill-Llama-70B": "deepseek-ai/DeepSeek-R1-Distill-Llama-70B",
    "Qwen3-235B-A22B-Instruct-2507-tput": "Qwen/Qwen3-235B-A22B-Instruct-2507-tput",
    # "Qwen2.5-VL-72B-Instruct": "Qwen/Qwen2.5-VL-72B-Instruct",
    # "QwQ-32B": "Qwen/QwQ-32B",
    "Llama-4-Scout-17B-16E-Instruct": "meta-llama/Llama-4-Scout-17B-16E-Instruct",
    "Llama-3.1-8B-Instruct-Turbo": "meta-llama/Meta-Llama-3.1-8B-Instruct-Turbo",
    "gpt-oss-120b": "openai/gpt-oss-120b",  # via Together
    "gpt-oss-20b": "openai/gpt-oss-20b", 
    "Llama-3.3-70B-Instruct-Turbo": "meta-llama/Llama-3.3-70B-Instruct-Turbo",
    "Llama-3.3-70B-Instruct-Turbo-Free":"meta-llama/Llama-3.3-70B-Instruct-Turbo-Free",
    "Qwen2.5-72B-Instruct-Turbo":"Qwen/Qwen2.5-72B-Instruct-Turbo",
    "Deepseek-R1": "deepseek-ai/DeepSeek-R1",
}

# --- OpenAI model sets --------------------------------------------------------
OPENAI_SIMPLE = {
    "gpt-4o",
    "gpt-4.1",
    "gpt-4o-mini",
    "gpt-4.1-mini",
    "o3",
    "o4-mini",
    "o3-pro",  # 80$/1M tokens
}
# OPENAI_REASONING = {"gpt-5", "gpt-5-mini"}

OPENAI_REASONING_ALIASES: Dict[str, str] = {
    "gpt-5": "gpt-5",
    "gpt-5-low": "gpt-5",
    "gpt-5-mini-low": "gpt-5-mini",
}

CLAUDE_MODELS = {
    "claude-sonnet-4-20250514",
}

# --- Gemini (OpenAI-compatible Chat Completions) ------------------------------
GEMINI_MODELS = {
    "gemini-2.5-pro",
    "gemini-2.5-flash",
    # "gemini-2.5-flash-lite",
    # "gemini-2.0-flash",  
    # "gemini-2.0-pro",
}
DEEPSEEK_MODELS={
    "deepseek-chat",
    "deepseek-reasoner"
    
}
DEEPSEEK_BASE_URL = "https://api.deepseek.com"
GEMINI_OPENAI_BASE_URL = "https://generativelanguage.googleapis.com/v1beta/openai/"


# --- Grok (xAI, OpenAI-compatible Chat Completions) ---------------------------
GROK_MODELS = {
    "grok-4"
    }

GROK_BASE_URL = "https://api.x.ai/v1"

# --- Utilities ---------------------------------------------------------------
def _with_retries(fn: Callable[[], str], max_retries: int) -> str:
    """Execute `fn` up to `max_retries` times; re-raise the last exception if all attempts fail."""
    last_err: Exception | None = None
    for attempt in range(max_retries):
        try:
            return fn()
        except Exception as e:
            last_err = e
            if attempt >= max_retries - 1:
                raise
    raise last_err

def _match_together_model(name: str) -> str:
    """Return the canonical Together model ID if an alias is found; otherwise, return the original name."""
    return TOGETHER_ALIASES.get(name, name)

def _match_oai_reason_model(name: str) -> str:
    return OPENAI_REASONING_ALIASES.get(name,name)



# --- Single-call helpers -----------------------------------------------------
def call_claude_once(client: anthropic.Anthropic, model: str, context: str, system_prompt: Optional[str] = None) -> str:
    """Call Claude via anthropic API and return plain text."""
    msgs = []
    if system_prompt:
        msgs.append({"role": "system", "content": [{"type": "text", "text": system_prompt}]})
    msgs.append({"role": "user", "content": [{"type": "text", "text": context}]})

    resp = client.messages.create(
        model=model,
        max_tokens=8096,
        messages=msgs,
    )
    return resp.content[0].text

def call_grok_chat_once(
    client: OpenAI,
    model: str,
    user_content: str,
    system_prompt: Optional[str] = None,
) -> str:
    """Call Grok via xAI OpenAI-compatible Chat Completions API."""
    messages = []
    if system_prompt:
        messages.append({"role": "system", "content": system_prompt})
    messages.append({"role": "user", "content": user_content})

    resp = client.chat.completions.create(model=model, messages=messages)
    msg = resp.choices[0].message
    return getattr(msg, "content", str(msg))

def call_together_once(client: Together, model: str, context: str) -> str:
    resp = client.chat.completions.create(
        model=model,
        messages=[{"role": "user", "content": context}],
    )
    return resp.choices[0].message.content

def call_openai_simple_once(create: Callable[..., any], model: str, context: str) -> str:
    resp = create(model=model, input=context)
    return resp.output_text

def call_openai_reasoning_once(
    create: Callable[..., any],
    model: str,
    context: str,
    verbosity: str,
    reasoning_effort: str,
) -> str:
    resp = create(
        model=model,
        input=context,
        text={"verbosity": verbosity},
        reasoning={"effort": reasoning_effort},
    )
    return resp.output[1].content[0].text

def call_gemini_chat_once(
    client: OpenAI,
    model: str,
    user_content: str,
    system_prompt: Optional[str] = None,
) -> str:
    """Call Gemini via OpenAI-compatible Chat Completions API using messages=[...]."""
    messages = []
    if system_prompt:
        messages.append({"role": "system", "content": system_prompt})
    messages.append({"role": "user", "content": user_content})

    resp = client.chat.completions.create(model=model, messages=messages)
    msg = resp.choices[0].message
    return getattr(msg, "content", str(msg))



def call_deepseek_chat_once(
    client: OpenAI,
    model: str,
    user_content: str,
    system_prompt: Optional[str] = None,
) -> str:
    """Call deepseek via OpenAI-compatible Chat Completions API using messages=[...]."""
    messages = []
    if system_prompt:
        messages.append({"role": "system", "content": system_prompt})
    messages.append({"role": "user", "content": user_content})
    resp = client.chat.completions.create(model=model, messages=messages)
    msg = resp.choices[0].message
    return getattr(msg, "content", str(msg))

# --- Public API --------------------------------------------------------------
def call_model_api(
    model_name: str,
    context: str,
    max_retries: int = 5,
    reasoning_effort: str = "low",
    verbosity: str = "low",
    system_prompt: Optional[str] = None,
) -> str:
    """
    Unified entry point for Together, OpenAI Responses API, and Gemini (OpenAI-compatible Chat Completions).

    Behavior:
      - Together models -> together.chat.completions
      - OpenAI simple models -> openai.responses.create(...).output_text
      - OpenAI reasoning models -> openai.responses.create(...).output[1].content[0].text
      - Gemini models -> OpenAI(base_url=Gemini).chat.completions.create(messages=[...]).choices[0].message.content

    Raises:
        ValueError: If `model_name` is not recognized in any model list.
    """
    if (
        model_name not in TOGETHER_ALIASES
        and model_name not in OPENAI_SIMPLE
        # and model_name not in OPENAI_REASONING
        and model_name not in GEMINI_MODELS
        and model_name not in GROK_MODELS
        and model_name not in CLAUDE_MODELS
        and model_name not in DEEPSEEK_MODELS
        and model_name not in OPENAI_REASONING_ALIASES
    ):
        raise ValueError(f"Unknown model name: {model_name}")
    print("[text]")
    # Together
    if model_name in TOGETHER_ALIASES:
        t_client = Together()
        tgt_model = _match_together_model(model_name)
        return _with_retries(
            lambda: call_together_once(t_client, tgt_model, context),
            max_retries=max_retries,
        )
    if model_name in OPENAI_REASONING_ALIASES:
        o_client = OpenAI()
        create = o_client.responses.create
        o_model = _match_oai_reason_model(model_name)
        # print(o_model)
        return _with_retries(
            lambda: call_openai_reasoning_once(
                create, o_model, context, verbosity, reasoning_effort
            ),
            max_retries=max_retries,
            )
    # OpenAI
    if model_name in OPENAI_SIMPLE :
        o_client = OpenAI()
        create = o_client.responses.create
        if model_name in OPENAI_SIMPLE:
            return _with_retries(
                lambda: call_openai_simple_once(create, model_name, context),
                max_retries=max_retries,
            )
        return _with_retries(
            lambda: call_openai_reasoning_once(
                create, model_name, context, verbosity, reasoning_effort
            ),
            max_retries=max_retries,
        )

    # Gemini via OpenAI-compatible Chat Completions
    if model_name in GEMINI_MODELS:
        GEMINI_API_KEY=os.getenv("GEMINI_API_KEY")
        g_client = OpenAI(
            api_key=GEMINI_API_KEY,
            base_url=GEMINI_OPENAI_BASE_URL,
        )
        return _with_retries(
            lambda: call_gemini_chat_once(
                g_client, model_name, context, system_prompt
            ),
            max_retries=max_retries,
        )
    if model_name in GROK_MODELS:
        XAI_API_KEY = os.getenv("XAI_API_KEY")
        g_client = OpenAI(
            api_key=XAI_API_KEY,
            base_url=GROK_BASE_URL,
            timeout=httpx.Timeout(3600.0),  # long timeout for reasoning
        )
        return _with_retries(
            lambda: call_grok_chat_once(
                g_client, model_name, context, system_prompt
            ),
            max_retries=max_retries,
        )
    if model_name in CLAUDE_MODELS:
        A_API_KEY = os.getenv("ANTHROPIC_API_KEY")
        a_client = anthropic.Anthropic(api_key=A_API_KEY)
        return _with_retries(
            lambda: call_claude_once(a_client, model_name, context, system_prompt),
            max_retries=max_retries,
        )
        
    if model_name in DEEPSEEK_MODELS:
        DEEPSEEK_API_KEY = os.getenv("DEEPSEEK_API_KEY")
        d_client = OpenAI(
            api_key=DEEPSEEK_API_KEY,
            base_url=DEEPSEEK_BASE_URL,
        )
        return _with_retries(
            lambda: call_grok_chat_once(
                d_client, model_name, context, system_prompt
            ),
            max_retries=max_retries,
        ) 


if __name__ == "__main__":
    PROMPT = "Tell me the capital of France."
    # result = call_model_api("grok-4", PROMPT)
    # result = call_model_api("claude-sonnet-4-20250514", PROMPT)
    result=call_model_api("gpt-5-low", PROMPT)
    # result=call_model_api("o4-mini", PROMPT)
    # result = call_model_api("gpt-5-mini", PROMPT, reasoning_effort="low", verbosity="low")
    print("\n[RESPONSE]")
    print(result)
