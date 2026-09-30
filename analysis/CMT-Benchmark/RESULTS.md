# CMT evaluation results

GPT-5.6-Sol High was evaluated on September 6, 2026, and Fable 5 High on
September 9. Each model was judged by the other at high effort, without judge
tools, against the corresponding dataset's reference solutions.

| Model | Tools | Metric | Original (50 problems) | Corrected (49 problems) |
| --- | --- | --- | ---: | ---: |
| GPT-5.6-Sol High | No | Mean@4 | 47.50% (95/200) | 83.16% (163/196) |
| GPT-5.6-Sol High | Yes | Mean@4 | 61.00% (122/200) | 87.24% (171/196) |
| GPT-5.6-Sol High | Yes | Pass@4 | 72.00% (36/50) | 97.96% (48/49) |
| Fable 5 High | Yes | Mean@4 | 53.50% (107/200) | 85.20% (167/196) |
| Fable 5 High | Yes | Pass@4 | 60.00% (30/50) | 93.88% (46/49) |

Mean@4 averages correctness across four attempts; pass@4 counts
problems solved in any of those attempts. Tools include computation and web access.

The corrected set contains 20 unchanged and 29 repaired problems; unrepairable
index 14 is excluded.

Fable used fresh independent sessions, each limited to 100 tool turns and one
hour. Exhausted generation budgets and refusals count as unsuccessful attempts;
API and judge failures were retried.

Artifacts (gitignored): [Sol original comparison](artifacts/mean-pass-at4-20260906/comparison.json),
[Sol corrected results](artifacts/clean-refresh-20260906/comparison.json),
and [Fable results and provenance](artifacts/fable-high-tools-four-rounds-sol-high-20260909/comparison.json).
