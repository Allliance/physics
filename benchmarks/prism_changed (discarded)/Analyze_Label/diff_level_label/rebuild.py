from typing import Dict, List, Tuple, Optional
import string

def _clean(s: Optional[str]) -> str:
    if not s:
        return ""
    # Preserve LaTeX while normalizing spaces/newlines
    return " ".join(str(s).strip().split())

def rebuild_problem_and_solution(item: Dict) -> Tuple[int, str, str]:
    """
    Merge a single record's context + (optional) subproblems into one 'problem' string,
    and merge all available solutions into one 'solution' string.
    Returns:
        (id, problem_text, solution_text)
    """
    qid = item.get("id")
    context = _clean(item.get("context", ""))

    # Build problem text
    problem_lines: List[str] = []
    if context:
        problem_lines.append(context)

    subqs = item.get("subquestions") or []

    if subqs:
        # sort by provided letter if present; otherwise by index
        def _key(i_pair):
            i, sq = i_pair
            letter = (sq.get("letter") or "").strip().lower()
            if letter and letter in string.ascii_lowercase:
                return (0, string.ascii_lowercase.index(letter))
            return (1, i)
        ordered = [sq for _, sq in sorted(list(enumerate(subqs)), key=_key)]

        # assign fallback letters for missing ones
        fallback_letters = iter(string.ascii_lowercase)
        for sq in ordered:
            letter = (sq.get("letter") or "").strip()
            if not letter:
                letter = next(fallback_letters)
                sq["letter"] = letter

        # append each subproblem
        for sq in ordered:
            letter = (sq.get("letter") or "").strip()
            subp = _clean(sq.get("subproblem", ""))
            if subp:
                problem_lines.append(f"({letter}) {subp}")
            else:
                problem_lines.append(f"({letter}) [No subproblem text provided]")

    problem_text = "\n".join(problem_lines).strip()

    # Build solution text
    solution_lines: List[str] = []
    if subqs:
        def _key2(i_pair):
            i, sq = i_pair
            letter = (sq.get("letter") or "").strip().lower()
            if letter and letter in string.ascii_lowercase:
                return (0, string.ascii_lowercase.index(letter))
            return (1, i)
        ordered = [sq for _, sq in sorted(list(enumerate(subqs)), key=_key2)]

        for sq in ordered:
            letter = (sq.get("letter") or "").strip() or "?"
            sol = _clean(sq.get("solution", ""))
            if sol:
                solution_lines.append(f"({letter}) {sol}")
            else:
                solution_lines.append(f"({letter}) [No solution provided]")
    else:
        top_sol = _clean(item.get("solution", ""))
        if top_sol:
            solution_lines.append(top_sol)

    solution_text = "\n".join(solution_lines).strip()

    return qid, problem_text, solution_text


def batch_build_problems_and_solutions(items: List[Dict]) -> List[Dict]:
    """
    Process a list of records into a list of {"id", "problem", "solution"} dicts.
    """
    output = []
    for it in items:
        qid, problem, solution = rebuild_problem_and_solution(it)
        output.append({
            "id": qid,
            "problem": problem,
            "solution": solution
        })
    return output


# -----------------------------
# Example
if __name__ == "__main__":
    example = {
        "id": 1001,
        "context": "A man of weight $\\pmb { w }$ is in an elevator of weight $\\pmb { w }$. "
                   "The elevator accelerates vertically up at a rate $\\pmb { a }$ and at a certain instant has a speed $\\boldsymbol { V }$",
        "source": "Wisconsin",
        "subquestions": [
            {
                "letter": "a",
                "subproblem": "What is the apparent weight of the man?",
                "solution": "The apparent weight is $$F = w \\left( 1 + \\frac{a}{g} \\right)$$."
            },
            {
                "letter": "b",
                "subproblem": "The man climbs a vertical ladder within the elevator at a speed $\\boldsymbol{v}$ relative to the elevator. What is the man's power output?",
                "solution": "Power is $$P = w \\left(1 + \\frac{a}{g}\\right)(V+v).$$"
            }
        ]
    }
    qid, p, s = rebuild_problem_and_solution(example)
    print(f"ID: {qid}")
    print("=== PROBLEM ===")
    print(p)
    print("\n=== SOLUTION ===")
    print(s)
