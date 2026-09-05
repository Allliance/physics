"""Resource-capped one-shot worker for the UGPhysics symbolic grader."""

from __future__ import annotations

import json
import math
import os
import resource
import sys


RESULT_PREFIX = "RLVR_UGPHYSICS_RESULT="


def _apply_resource_limits() -> None:
    memory_gb = max(1.0, float(os.environ.get("RLVR_UGPHYSICS_MAX_MEMORY_GB", "8")))
    memory_bytes = int(memory_gb * 1024**3)
    resource.setrlimit(resource.RLIMIT_AS, (memory_bytes, memory_bytes))
    timeout = max(1.0, float(os.environ.get("RLVR_UGPHYSICS_CHILD_TIMEOUT_SECONDS", "60")))
    soft_cpu_limit = max(1, math.ceil(timeout))
    resource.setrlimit(resource.RLIMIT_CPU, (soft_cpu_limit, soft_cpu_limit + 1))


def _emit(payload: dict[str, object]) -> None:
    print(f"{RESULT_PREFIX}{json.dumps(payload, separators=(',', ':'))}", flush=True)


def main() -> int:
    _apply_resource_limits()
    request = json.load(sys.stdin)
    from rlvr.reward import _timeout, score_ugphysics

    timeout = float(os.environ.get("RLVR_UGPHYSICS_CHILD_TIMEOUT_SECONDS", "60"))
    try:
        with _timeout(timeout):
            result = score_ugphysics(str(request["solution"]), request["truth"])
    except TimeoutError:
        _emit({"error": "timeout"})
    except MemoryError:
        _emit({"error": "memory"})
    except Exception as exc:
        _emit({"error": f"{type(exc).__name__}: {exc}"})
    else:
        _emit({"result": result})
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
