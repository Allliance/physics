# Kimi K3 Max: agentic replacement results

Every incorrect attempt in the selected saved evaluation runs was
replaced by an independent Kimi K3 Max retry using the Codex harness, local
tools, and the OpenRouter `agentic-web` preset. Existing correct attempts were
preserved. Replacement answers were judged by GPT-5.6-Sol High.

| Dataset | Retries | Retry correct | Original mean@4 | Final mean@4 | Original pass@4 | Final pass@4 |
|---|---:|---:|---:|---:|---:|---:|
| phybench | 65 | 0 | 81.53% | pending | 92.05% | pending |
| prism | 27 | 0 | 90.88% | pending | 97.30% | pending |
| ugphysics | 36 | 0 | 88.46% | pending | 96.15% | pending |

Overall replacement success: 0/128 (0.00%).
