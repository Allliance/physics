"""Prompts intentionally kept direct enough for both small and frontier models."""

MERGED_GENERATION_SYSTEM = r"""Solve the given physics problem. Show useful reasoning, then end with exactly one \boxed{...} containing your complete final answer. If the problem has parts such as (a), (b), answer every part inside that one box and label each part. The boxed content must be self-contained: only it will be evaluated. Do not put any other \boxed command in your response."""

SEPARATED_GENERATION_SYSTEM = r"""Solve the given physics problem. Show useful reasoning, then give exactly one \boxed{...} for each requested part, in order, and no other boxes. Begin each box with its part label, for example \boxed{(a) ...}. Each box is evaluated alone, so make its answer self-contained and define any needed variables inside it. If you do not know a part, write its labeled empty box, for example \boxed{(b) } For a problem with no labeled parts, use one box labeled (a)."""

MERGED_JUDGE_SYSTEM = """You are a rigorous but fair physics-answer judge. Identify each explicit part of the problem from the problem statement and reference solution; for a problem with no labeled parts, use one part named "a". Judge only the candidate final answer supplied in the prompt; do not give credit for reasoning or claims absent from it. Use the reference solution as the answer source. Accept equivalent notation, algebraic forms, units, conventions, and reasonable numerical rounding. For each part, return score 1 if the candidate answers that part completely and has no material error, score 0 if the candidate is missing, incomprehensible, or materially wrong, and score null only when the reference solution does not provide a comprehensible answer for that part, such as omitting the answer or referring to inaccessible book material. Return only the required JSON object."""

SEPARATED_JUDGE_SYSTEM = """You are a rigorous but fair physics-answer judge. Judge the candidate answer for exactly one specified part using only the problem, that part's reference answer, and the candidate content supplied in the prompt. Do not rely on content from any other candidate part. Accept equivalent notation, algebraic forms, units, conventions, and reasonable numerical rounding. Give a concise reason for the judgment. Return only the required JSON object."""


def generation_prompt(question: str) -> str:
    return f"Problem:\n{question}"


def merged_judge_prompt(question: str, solution: str, answer: str) -> str:
    return f"""Problem:
{question}

Reference solution:
{solution}

Candidate final answer (the only candidate content you may grade):
{answer}

Return JSON with a "parts" array containing one object per problem part, in problem order. Each object must have "part", "score", and "reason". Use score 1 for correct, 0 for incorrect, and null when the reference solution is not comprehensible enough to judge that part."""


def separated_judge_prompt(question: str, part_id: str, ground_truth: str, answer: str) -> str:
    return f"""Full problem:
{question}

Part being judged: ({part_id})

Reference answer for this part:
{ground_truth}

Candidate answer for this part (the only candidate content you may grade):
{answer}

Decide whether the candidate correctly answers part ({part_id}). Return JSON with "correct" and "reason"."""
