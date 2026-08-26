"""Shared Codex CLI tool-environment settings for CritPt runs.

The Codex sandbox starts with `shell_environment_policy.inherit="none"`, which
leaves PATH pointing only at Codex's own shim directory — no interpreter at all.
These settings hand the sandbox a purpose-built scientific Python environment
while keeping the CritPt repo itself hidden (the `codex_isolated` wrapper
bind-mounts an empty directory over it, so answers/results stay unreachable).

Rebuild the environment with:
    uv venv --python /usr/bin/python3 /shared/data/home/aa3242/codex_tools_env
    VIRTUAL_ENV=/shared/data/home/aa3242/codex_tools_env \
        uv pip install numpy scipy sympy mpmath pandas matplotlib qutip
"""

from __future__ import annotations

from pathlib import Path


TOOLS_ENV = Path("/shared/data/home/aa3242/codex_tools_env")

#: Sandbox mode: `workspace-write` lets the agent write scratch scripts into its
#: per-call temp cwd (and /tmp) while still blocking network access from the shell.
SANDBOX_MODE = "workspace-write"

#: Inherit nothing from the parent process, then set exactly what is needed.
ENV_INHERIT = "none"

ENV_SET = {
    "PATH": f"{TOOLS_ENV}/bin:/usr/local/bin:/usr/bin:/bin",
    "HOME": "/tmp",
    "TMPDIR": "/tmp",
    "MPLBACKEND": "Agg",
    "PYTHONNOUSERSITE": "1",
    "PYTHONDONTWRITEBYTECODE": "1",
    "OMP_NUM_THREADS": "4",
    "OPENBLAS_NUM_THREADS": "4",
    "MKL_NUM_THREADS": "4",
    "LC_ALL": "C.UTF-8",
}

#: Appended to the system prompt so the agent knows the interpreter exists and
#: which libraries are importable. Without this it wastes turns probing for
#: `python`, `julia`, `bc`, and friends.
TOOLS_PROMPT_SUFFIX = (
    "\n\n**Computational environment**\n"
    "You have a working shell with Python 3.10 on PATH as `python3`. "
    "Available libraries: numpy 2.2, scipy 1.15, sympy 1.14, mpmath 1.3, "
    "pandas 2.3, matplotlib 3.10, qutip 5.2. "
    "You may write scratch scripts into the current working directory and run them. "
    "There is no network access from the shell (package installation will fail), "
    "but the web_search tool is available separately. "
    "Use `python3` for every non-trivial numerical or symbolic step — "
    "verify algebra with sympy and numbers with numpy/scipy/mpmath instead of "
    "evaluating them mentally, and state in the derivation which results were "
    "computed this way."
)


#: Emit `reasoning` items in the event stream. Note: these are short
#: reasoning-summary headers, not raw chain-of-thought -- the API does not
#: expose raw CoT over this channel (`show_raw_agent_reasoning` adds nothing).
REASONING_SUMMARY = "detailed"


def codex_tool_kwargs() -> dict[str, object]:
    """Keyword arguments for `CodexLLM` that enable a usable toolchain."""
    return {
        "sandbox_mode": SANDBOX_MODE,
        "env_inherit": ENV_INHERIT,
        "env_set": dict(ENV_SET),
        "reasoning_summary": REASONING_SUMMARY,
        "capture_workspace": True,
    }
