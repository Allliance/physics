"""Shared HLE judging and per-question aggregation across independent rounds."""

from __future__ import annotations

import concurrent.futures
import hashlib
import json
import os
import sys
import tempfile
from pathlib import Path

from .prompts import JUDGE_PROMPT, JUDGE_SCHEMA, JUDGE_SYSTEM_PROMPT
from .backends import make_fable_client, parse_fable_response, resolve_fable_model

FABLE_JUDGE_MAX_TOKENS = 8192


def judge_backend_config(args) -> dict:
    if args.judge_model == "gpt-5.6-sol":
        return {}
    if args.judge_model != "claude-fable-5":
        raise ValueError(f"Unsupported judge model: {args.judge_model}")
    return {"judge_api_model": resolve_fable_model(args.fable_model),
            "judge_base_url": os.environ.get("ANTHROPIC_BASE_URL", "https://api.anthropic.com"),
            "judge_max_output_tokens": FABLE_JUDGE_MAX_TOKENS}


def validate_judgment(content: dict) -> None:
    if not isinstance(content, dict) or set(content) != set(JUDGE_SCHEMA["required"]):
        raise ValueError("Judge returned an invalid JSON object.")
    if content["correct"] not in {"yes", "no"} or content["strict"] is not True:
        raise ValueError("Judge returned an invalid correctness label or strict flag.")
    if type(content["confidence"]) is not int or not 0 <= content["confidence"] <= 100:
        raise ValueError("Judge returned an invalid confidence.")
    if not all(isinstance(content[key], str) for key in ["extracted_final_answer", "reasoning"]):
        raise ValueError("Judge returned invalid answer/reasoning text.")


def fingerprint(value) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True).encode()).hexdigest()


def load_answers(dataset_name: str, question_ids: list[str]) -> dict[str, str]:
    from datasets import load_dataset

    dataset = load_dataset(dataset_name, split="test").select_columns(["id", "answer"])
    wanted = set(question_ids)
    answers = {q["id"]: q["answer"] for q in dataset if q["id"] in wanted}
    if set(answers) != wanted:
        raise ValueError("Missing reference answers for selected questions.")
    return answers


def make_judge(args):
    config = judge_backend_config(args)
    if args.judge_model == "claude-fable-5":
        client = make_fable_client(args.timeout)
    else:
        sys.path.insert(0, str(args.codex_cli_path.resolve()))
        from codex_cli import CodexLLM

        client = CodexLLM(
            model=args.judge_model, model_reasoning_effort=args.judge_reasoning_effort,
            timeout=args.timeout, system_prompt=JUDGE_SYSTEM_PROMPT, strict_no_tools=True,
            web_search="disabled", sandbox_mode="read-only", env_inherit="none",
        )

    def judge(question: dict, prediction: dict, answer: str) -> dict:
        # Refusals are failures, never a successful match to a missing answer.
        if prediction.get("refused"):
            return {"correct_answer": answer, "model_answer": "None", "correct": "no",
                    "confidence": 0, "reasoning": "The evaluated model refused the question."}
        prompt = JUDGE_PROMPT.format(question=question["question"],
                                     correct_answer=answer, response=prediction["response"])
        actual_model = args.judge_model
        if args.judge_model == "claude-fable-5":
            with client.messages.stream(
                model=config["judge_api_model"], max_tokens=FABLE_JUDGE_MAX_TOKENS,
                system=JUDGE_SYSTEM_PROMPT,
                messages=[{"role": "user", "content": prompt + "\n\nOutput JSON schema:\n" + json.dumps(JUDGE_SCHEMA)}],
                thinking={"type": "adaptive"}, output_config={"effort": args.judge_reasoning_effort},
            ) as stream:
                message = stream.get_final_message().model_dump(mode="json")
            result = parse_fable_response(message, config["judge_api_model"])
            if result["refused"]:
                raise ValueError("Fable judge refused; judgment remains pending.")
            content = json.loads(result["response"])
            actual_model = result["actual_model"]
        else:
            with tempfile.TemporaryDirectory(prefix="hle-judge-") as tmp:
                schema = Path(tmp) / "schema.json"
                schema.write_text(json.dumps(JUDGE_SCHEMA))
                result = client.complete(prompt, output_schema=schema)
            content = json.loads(result.text)
        validate_judgment(content)
        return {"correct_answer": answer, "model_answer": content["extracted_final_answer"],
                "reasoning": content["reasoning"], "correct": content["correct"],
                "confidence": content["confidence"], "actual_model": actual_model}
    return judge


def judge_round(args, questions: list[dict], answers: dict, predictions: dict,
                output: Path, write_json) -> dict:
    manifest = {
        "version": 1, "judge_model": args.judge_model,
        "judge_reasoning_effort": args.judge_reasoning_effort,
        "questions_and_answers_sha256": fingerprint([questions, answers]),
        "judge_prompt_sha256": fingerprint([JUDGE_PROMPT, JUDGE_SCHEMA, JUDGE_SYSTEM_PROMPT]),
    }
    manifest.update(judge_backend_config(args))
    metadata = output.with_suffix(output.suffix + ".meta.json")
    if metadata.exists():
        if json.loads(metadata.read_text()) != manifest:
            raise ValueError("Judge configuration changed; choose a new --output file.")
    elif output.exists():
        raise ValueError("Existing judged output has no manifest; choose a new --output file.")
    else:
        write_json(metadata, manifest)
    judged = json.loads(output.read_text()) if output.exists() else {}
    if not isinstance(judged, dict) or set(judged) - set(predictions):
        raise ValueError("Judged checkpoint has unexpected question IDs.")
    for qid, item in judged.items():
        if (item.get("prediction_sha256") != fingerprint(predictions[qid]) or
                item.get("judge_response", {}).get("correct") not in {"yes", "no"}):
            raise ValueError("Judged checkpoint does not match saved predictions.")
    pending = [q for q in questions if q["id"] in predictions and q["id"] not in judged]
    if not pending:
        return judged
    judge = make_judge(args)

    def attempt(q):
        qid = q["id"]
        result = judge(q, predictions[qid], answers[qid])
        if result.get("correct") not in {"yes", "no"}:
            raise ValueError("Invalid judge result.")
        return qid, {**predictions[qid], "judge_response": result,
                     "judge_model": args.judge_model,
                     "judge_reasoning_effort": args.judge_reasoning_effort,
                     "prediction_sha256": fingerprint(predictions[qid])}

    with concurrent.futures.ThreadPoolExecutor(max_workers=args.num_workers) as pool:
        futures = {pool.submit(attempt, q): q["id"] for q in pending}
        for future in concurrent.futures.as_completed(futures):
            try:
                qid, result = future.result()
            except Exception as exc:
                print(f"Error judging {futures[future]}: {exc}", file=sys.stderr, flush=True)
                continue
            judged[qid] = result
            write_json(output, judged)
            print(f"Judged {qid} ({len(judged)}/{len(questions)})", flush=True)
    return judged


def aggregate_scores(question_ids: list[str], rounds: list[dict], aggregation: str) -> dict:
    if not question_ids or not rounds or aggregation not in {"mean", "max"}:
        raise ValueError("Scores require questions, rounds, and mean/max aggregation.")
    per_question = {}
    for qid in question_ids:
        scores = []
        for judged in rounds:
            label = judged.get(qid, {}).get("judge_response", {}).get("correct")
            if label is not None and label not in {"yes", "no"}:
                raise ValueError(f"Invalid correctness label for {qid}: {label!r}")
            scores.append(None if label is None else int(label == "yes"))
        complete = all(score is not None for score in scores)
        per_question[qid] = {
            "round_scores": scores,
            "mean": sum(scores) / len(scores) if complete else None,
            "max": max(scores) if complete else None,
        }
    complete = all(item["mean"] is not None for item in per_question.values())
    totals = {mode: sum(q[mode] for q in per_question.values()) / len(question_ids)
              if complete else None for mode in ["mean", "max"]}
    round_scores = []
    for index in range(len(rounds)):
        values = [q["round_scores"][index] for q in per_question.values()]
        round_scores.append(sum(values) / len(values) if None not in values else None)
    return {
        "complete": complete, "questions": len(question_ids), "rounds": len(rounds),
        "aggregation": aggregation, "final_score": totals[aggregation],
        "final_score_percent": 100 * totals[aggregation] if complete else None,
        "mean_score": totals["mean"], "max_score": totals["max"],
        "round_scores": round_scores, "per_question": per_question,
        "missing_judgments": sum(score is None for q in per_question.values() for score in q["round_scores"]),
    }
