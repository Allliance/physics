# Kimi K3 Max: agentic replacement results

Every incorrect attempt in the selected saved evaluation runs was
replaced by an independent Kimi K3 Max retry using the Codex harness, local
tools, and the OpenRouter `agentic-web` preset. Existing correct attempts were
preserved. Replacement answers were judged by GPT-5.6-Sol High.

| Dataset | Retries | Retry correct | Original mean@4 | Final mean@4 | Original pass@4 | Final pass@4 |
|---|---:|---:|---:|---:|---:|---:|
| hle-physics | 510 | 82 | 36.88% | 47.03% | 47.03% | 55.45% |
| cmt | 133 | 56 | 33.50% | 61.50% | 48.00% | 80.00% |
| critpt | 118 | 24 | 46.36% | 57.27% | 61.82% | 72.73% |

Overall replacement success: 162/761 (21.29%).
