# Physics RLVR with verl

This workflow trains `Qwen/Qwen3-4B` with GRPO on PRISM. All eligible PRISM
rows are training data; validation is an exact deterministic sample of 200
eligible UGPhysics rows. This makes training and validation disjoint at the
benchmark level.

`verl/` is vendored at commit `4eff9ae30a23b59554758fa0ca93940605ae5cdf`.
Its upstream Git metadata has been removed; see `verl/UPSTREAM_COMMIT`.

PRISM can alternatively use the external generative judge in
`llm_judge_reward.py`. It returns the expected value of a calibrated five-level
physics-correctness rubric for training. Validation instead uses the binary
`default` prompt from `llm_judge/prompts.py`, where `score` and `acc` are the
literal 0-or-1 correctness grade. Both paths use constrained JSON output. The
training rubric disables judge reasoning for throughput, while binary
validation uses the validated thinking-enabled judge configuration.

## Data

Prepare both datasets from the repository root:

```bash
uv run --with pyarrow --with chardet python -m rlvr.prepare_data all
```

Generated files live under `rlvr/data/{prism,ugphysics}/`. Rows already marked
`benchmark_failure` in `audit/all-responses/` and PRISM multimodal rows are
excluded by default. The UGPhysics population is collected directly from
`audit/all-responses/ugphysics/responses.jsonl`; it is not sampled from the
larger upstream corpus. `prism/train.parquet` contains every eligible PRISM
row, and `ugphysics/validation.parquet` contains exactly 200 audited rows
selected by a seeded SHA-256 ordering (`--seed` and `--validation-size` control
the selection). No PRISM validation or UGPhysics training parquet is produced.

## Tests

```bash
python3 -m unittest discover -s rlvr/tests -p 'test_*.py'
uv run --with 'numpy<2' --with sympy==1.14.0 \
  --with antlr4-python3-runtime==4.11 --with regex --with chardet \
  --with openai --with httpx python -m rlvr.smoke_reward
```

## Training

Run the one-step W&B-tracked smoke test:

```bash
mkdir -p rlvr/runs/slurm
sbatch --time=01:00:00 --job-name=qwen3-4b-rlvr-smoke --gres=gpu:1 \
  --cpus-per-task=32 --mem=500000M \
  --export=ALL,RLVR_MODE=smoke,RLVR_NGPUS=1,MAX_RESPONSE_LENGTH=1024 \
  rlvr/jobs/qwen3_4b.sbatch
```

Start the PRISM experiment:

```bash
sbatch --gres=gpu:4 --cpus-per-task=128 --mem=1400000M \
  --export=ALL,RLVR_MODE=train,RLVR_NGPUS=4,TRAIN_DATASET=prism,VALIDATION_DATASET=ugphysics \
  rlvr/jobs/qwen3_4b.sbatch
```

Run the one-step LLM-judge smoke test (eight GPUs total: four Qwen3.5-27B judge
replicas with DP=4/TP=1 and four Qwen3-4B trainer GPUs):

```bash
sbatch rlvr/jobs/qwen3_4b_llm_judge.sbatch
```

Start the full five-epoch PRISM LLM-judge run:

```bash
sbatch --job-name=qwen3-4b-prism-llm-judge-train \
  --export=ALL,RLVR_MODE=train rlvr/jobs/qwen3_4b_llm_judge.sbatch
```

The judge model and topology are explicit controls: `JUDGE_MODEL`,
`JUDGE_DP_SIZE`, and `JUDGE_TP_SIZE`. This smoke launcher validates the requested
four-GPU DP=4/TP=1 topology. The reward client uses `LLM_JUDGE_BASE_URL`,
`LLM_JUDGE_MODEL`, `LLM_JUDGE_MAX_TOKENS`, and `LLM_JUDGE_RETRIES`, so the same
reward function also works with a separately managed OpenAI-compatible vLLM
endpoint.

The launcher defaults to PRISM training and UGPhysics validation. Override
either dataset independently when needed:

```bash
sbatch --export=ALL,RLVR_MODE=train,TRAIN_DATASET=prism,VALIDATION_DATASET=ugphysics \
  rlvr/jobs/qwen3_4b.sbatch
```

The job installs the small native-grader dependency set from
`reward-requirements.txt` into an isolated directory (the grader and verl need
different ANTLR versions), maps `WANDB_TOKEN` from `~/.bashrc` to W&B's standard
`WANDB_API_KEY` without writing the token to an artifact, and keeps checkpoints,
validation generations, container logs, and Slurm logs under `rlvr/runs/`.

Useful controls are environment variables: `TRAIN_BATCH_SIZE`,
`PPO_MINI_BATCH_SIZE`, `ROLLOUT_N`, `MAX_PROMPT_LENGTH`,
`MAX_RESPONSE_LENGTH`, `TOTAL_EPOCHS`, `ACTOR_LR`, `REWARD_TIMEOUT_SECONDS`,
`RLVR_PRISM_MAX_ANSWER_EQUATIONS`, `RLVR_PRISM_MAX_MEMORY_GB`, and
`EXPERIMENT_NAME`. PRISM scores run in disposable subprocesses with an 8 GiB
address-space limit by default, preventing pathological SymPy expressions from
exhausting a training node. Set `RLVR_PRISM_ISOLATE=0` only for debugging.
