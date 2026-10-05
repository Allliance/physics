# Kimi K3 Max: agentic replacement results

Every incorrect attempt in the saved corrected HLE, CritPt, and CMT runs was
replaced by an independent Kimi K3 Max retry using the Codex harness, local
tools, and the OpenRouter `agentic-web` preset. Existing correct attempts were
preserved. Replacement answers were judged by GPT-5.6-Sol High.

| Dataset | Retries | Retry correct | Original mean@4 | Final mean@4 | Original pass@4 | Final pass@4 |
|---|---:|---:|---:|---:|---:|---:|
| hle | 182 | 60 | 60.43% | 73.48% | 75.65% | 83.48% |
| critpt | 100 | 28 | 53.70% | 66.67% | 66.67% | 81.48% |
| cmt | 60 | 29 | 69.39% | 84.18% | 87.76% | 93.88% |

Overall replacement success: 117/342 (34.21%).
