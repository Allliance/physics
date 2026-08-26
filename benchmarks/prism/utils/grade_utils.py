import re, json, os, copy, ast, time, logging
import multiprocessing as mp
from typing import List, Tuple, Union, Optional
from contextlib import contextmanager

from utils.formula_comparison_utils import (
    whether_rel_latex_correct,
    whether_rel_latex_correct_with_units,
    whether_rel_latex_correct_with_units_with_only_one_dict_parameter
)
from utils.simplify_expression import simplify_latex_expr
from utils.numerical_utils import analyze_formula

# --------------------------
# Logging helpers (aligned with evaluator)
# --------------------------

logger = logging.getLogger("evaluator")

@contextmanager
def timed(msg: str, **extra):
    start = time.time()
    logger.debug(f"[START] {msg}", extra=extra)
    try:
        yield
    finally:
        dur_ms = (time.time() - start) * 1000.0
        logger.debug(f"[END] {msg} ({dur_ms:.1f} ms)", extra=extra)

# --------------------------
# Matching utilities
# --------------------------

def get_match_info(std_eq, ans_eq, std_id, ans_id, reason=None):
    info = {
        "std_equation": std_eq,
        "answer_equation": ans_eq,
        "index_std": std_id,
        "index_answer": ans_id
    }
    if reason:
        info["reason"] = reason
    return info

def match_equations(std_eqs, ans_eqs):  # remember to put the standard solution in the first
    extra = {"phase": "match", "mode": "sequential"}
    scores = [0] * len(std_eqs)
    match_info = []
    logger.debug("Sequential match start", extra={**extra, "std_count": len(std_eqs), "ans_count": len(ans_eqs)})
    for i in range(len(std_eqs)):
        for j in range(len(ans_eqs)):
            try:
                epsilon_std = analyze_formula(std_eqs[i])
                epsilon_ans = analyze_formula(ans_eqs[j])
                epsilon = max(epsilon_std, epsilon_ans, 1e-5)
                correctness, reason = whether_rel_latex_correct_with_units(
                    std_eqs[i], ans_eqs[j], epsilon_for_equal=epsilon
                )
            except Exception:
                logger.debug("Comparison error; continuing", extra={**extra, "i": i, "j": j})
                continue
            if correctness:
                scores[i] = 1
                info = get_match_info(std_eqs[i], ans_eqs[j], i, j, reason)
                match_info.append(info)
                logger.debug("Match found", extra={**extra, "i": i, "j": j})
                break
    logger.debug("Sequential match done", extra={**extra, "matched": sum(scores)})
    return scores, match_info

def _worker_match(args):
    """
    Worker function: given (i, std_eq, ans_eqs), returns
    (i, score, match_info_or_None).
    """
    i, std_eq, ans_eqs = args
    # Local logger in subprocess (inherits root config)
    _log = logging.getLogger("evaluator")
    extra = {"phase": "match", "mode": "parallel", "i": i}
    for j, ans_eq in enumerate(ans_eqs):
        try:
            # Use same epsilon logic as sequential path
            eps_std = analyze_formula(std_eq)
            eps_ans = analyze_formula(ans_eq)
            epsilon = max(eps_std, eps_ans, 1e-5)
            correctness, reason = whether_rel_latex_correct_with_units(std_eq, ans_eq, epsilon_for_equal=epsilon)
        except Exception:
            # Keep subprocess logging minimal to avoid noise
            continue
        if correctness:
            info = get_match_info(std_eq, ans_eq, i, j, reason)
            _log.debug("Worker match", extra={**extra, "j": j})
            return i, 1, info
    return i, 0, None

def match_equations_parallel(std_eqs, ans_eqs):
    """
    Parallel version of match_equations. Returns (scores, match_info).
    """
    extra = {"phase": "match", "mode": "parallel", "std_count": len(std_eqs), "ans_count": len(ans_eqs)}
    logger.debug("Parallel match start", extra=extra)
    tasks = [(i, std_eq, ans_eqs) for i, std_eq in enumerate(std_eqs)]

    with timed("pool_map_match", **extra):
        with mp.Pool(mp.cpu_count()) as pool:
            results = pool.map(_worker_match, tasks)

    results.sort(key=lambda x: x[0])
    scores = [score for (_, score, _) in results]
    match_info = [info for (_, _, info) in results if info is not None]

    logger.debug("Parallel match done", extra={**extra, "matched": sum(scores)})
    return scores, match_info

# --------------------------
# Equation extraction & grading helpers
# --------------------------

def extract_equations(solution):
    extra = {"phase": "extract"}
    solution=str(solution)
    logger.debug(f"solution: {solution}", extra=extra)
    with timed("extract_equations_regex", **extra):
        equations_ori = re.findall(r'\$\$(.*?)\$\$', solution, re.DOTALL)
    equations = [simplify_latex_expr(eq.strip()) for eq in equations_ori]
    # Keep relations only
    relations = ['=', '<', '>', '\\leq', '\\geq', '\\ll', '\\gg', '\\approx']
    equations = [eq for eq in equations if any(tok in eq for tok in relations)]
    logger.debug("Equations extracted",
                 extra={**extra, "raw_count": len(equations_ori), "filtered_count": len(equations)})
    return equations

def replace_formulas(s: str, replacements: List[int], default_non_rel: int = 0) -> str:
    """
    Replace only the $$...$$ blocks that represent relations with bits from `replacements`.
    Non-relational $$...$$ blocks are replaced by `default_non_rel` to keep the grade
    structure parseable. This keeps counts aligned and avoids StopIteration.
    """
    extra = {"phase": "replace"}
    logger.debug("Replace formulas start", extra={**extra})

    relations = ['=', '<', '>', '\\leq', '\\geq', '\\ll', '\\gg', '\\approx']
    repl_iter = iter(replacements)

    def _is_rel(eq: str) -> bool:
        return any(tok in eq for tok in relations)

    def _sub(m: re.Match) -> str:
        block = m.group(0)             # $$ ... $$
        inner = m.group(1).strip()     # content without $$ via the capturing group
        eq = simplify_latex_expr(inner)
        if _is_rel(eq):
            try:
                return str(next(repl_iter))
            except StopIteration:
                raise ValueError("Not enough replacements for relational formulas")
        else:
            # keep grade string valid; don’t leave $$...$$ in place
            return str(default_non_rel)

    # Use a capturing group for inner so we can simplify/inspect it quickly
    result = re.sub(r'\$\$(.*?)\$\$', _sub, s, flags=re.DOTALL)

    # Optional: warn if caller computed too many bits
    try:
        _ = next(repl_iter)
    except StopIteration:
        pass
    else:
        logger.warning("Extra bits in replacements were not used", extra=extra)

    logger.debug("Replace formulas done", extra=extra)
    return result


def set_grade(s: str) -> List[int]:
    """
    Convert an input string s like "[1,0,(0,1),[0,1]]" into the flattened list of 0/1.
    """
    extra = {"phase": "set_grade"}
    try:
        structure = ast.literal_eval(s)
    except Exception as e:
        logger.error("Invalid grade structure", extra={**extra, "err": str(e)})
        raise ValueError(f"Invalid input: {e}")

    Node = Union[int, list, tuple]

    def process(node: Node) -> Tuple[List[int], bool]:
        if isinstance(node, int):
            return [node], bool(node)

        children = []
        for child in node:
            bits, succ = process(child)
            children.append((bits, succ))

        if isinstance(node, tuple):
            flat = []
            for bits, _ in children:
                flat.extend(bits)
            succ = all(s for _, s in children)
            return flat, succ

        # list wrapper with backward propagation
        succ_indices = [i for i, (_, s) in enumerate(children) if s]
        if succ_indices:
            max_i = max(succ_indices)
            for i in range(max_i + 1):
                bits, _ = children[i]
                children[i] = ([1] * len(bits), True)

        flat = []
        for bits, _ in children:
            flat.extend(bits)
        succ = children[-1][1]
        return flat, succ

    with timed("set_grade_process", **extra):
        flat, _ = process(structure)
    logger.debug("Grade flattened", extra={**extra, "length": len(flat)})
    return flat

def log_debug_info(pid, std_equations, answer_equations, matches, log_path):
    extra = {"phase": "debug_log", "problem_id": pid, "path": log_path}
    if log_path is None:
        logger.debug("Debug log skipped (no path)", extra=extra)
        return
    else:
        log_path = '.'.join(log_path.split('.')[:-1])+"_grading.log"

    try:
        os.makedirs(os.path.dirname(log_path), exist_ok=True)
    except Exception:
        # If path has no directory component, ignore
        pass

    try:
        if os.path.exists(log_path):
            with open(log_path, "r", encoding="utf-8") as f:
                content = f.read().strip()
                try:
                    debug_info = json.loads(content) if content else []
                except ValueError:
                    debug_info = []
        else:
            debug_info = []

        debug_info.append({
            'id': pid,
            'std_equations': std_equations,
            'answer_equations': answer_equations,
            'matches': matches
        })
        with open(log_path, 'w', encoding="utf-8") as f:
            json.dump(debug_info, f, indent=2, ensure_ascii=False)
        logger.debug("Debug info appended", extra=extra)
    except Exception:
        logger.exception("Failed to write debug info", extra=extra)

def sanitize(s: str) -> str:
    """
    Remove any bare identifiers so that things like foo[1,2] become [1,2].
    Leaves only digits, commas, brackets, parentheses and whitespace.
    """
    extra = {"phase": "sanitize"}
    with timed("sanitize_transform", **extra):
        s = re.sub(r'[A-Za-z_]\w*', '', s)
        s = s.replace(' ', '')
        s = re.sub(r'(?<=[\]\)])(?=[\[\(])', ',', s)
    logger.debug("Sanitized grade string", extra=extra)
    return s

# --------------------------
# Public grading APIs
# --------------------------

def grade_problem(problem: dict, answer: str, log_path: Optional[str] = None):
    extra = {"phase": "grade_tree", "problem_id": problem.get("id")}
    logger.debug("grade_problem start", extra=extra)

    with timed("extract_standard_equations", **extra):
        std_eqs = extract_equations(problem["grading_standard"])
    with timed("extract_answer_equations", **extra):
        ans_eqs = extract_equations(answer)

    with timed("match_equations_parallel", **extra):
        eq_matches, match_info = match_equations_parallel(std_eqs, ans_eqs)

    with timed("replace_and_sanitize", **extra):
        raw_grade = replace_formulas(problem["grading_standard"], eq_matches)
        raw_grade = sanitize(raw_grade)
    logger.debug("Raw grade string ready", extra={**extra, "len": len(raw_grade)})

    try:
        with timed("set_grade_parse", **extra):
            grades = set_grade(raw_grade)
    except Exception:
        logger.warning("Fallback to simple eq_matches due to parsing error", extra=extra)
        grades = set_grade(str(eq_matches))

    log_debug_info(problem.get("id"), std_eqs, ans_eqs, match_info, log_path)
    score = (sum(grades) / len(grades)) if grades else 0.0
    logger.info("grade_problem done", extra={**extra, "score": round(score, 4)})
    return score, match_info

def grade_problem_dag(problem: dict, answer: str, log_path: Optional[str] = None):
    extra = {"phase": "grade_dag", "problem_id": problem.get("id")}
    logger.debug("grade_problem_dag start", extra=extra)

    grading_standard = copy.deepcopy(problem['grading_standard'])
    if isinstance(grading_standard, str):
        try:
            with timed("parse_grading_standard_json", **extra):
                grading_standard = json.loads(
                    grading_standard.replace('\\', '\\\\').replace(r'\\n', r'\n')
                )
        except Exception as e:
            logger.error("Error loading grading standard JSON",
                         extra={**extra, "err": str(e), "length": len(grading_standard)})
            raise

    std_formulas = [item['formula'] for item in grading_standard]
    std_formulas = [formula.replace('$','') for formula in std_formulas]
    with timed("extract_answer_equations", **extra):
        ans_eqs = extract_equations(answer)

    with timed("match_equations_parallel", **extra):
        eq_matches, match_info = match_equations_parallel(std_formulas, ans_eqs)

    idx_to_std = {item['index']: item for item in grading_standard}
    idx_list = [item['index'] for item in grading_standard]
    matched = {idx: bool(eq_matches[i]) for i, idx in enumerate(idx_list)}

    final_marked = set()
    def mark(idx):
        if idx in final_marked:
            return
        final_marked.add(idx)
        for dep in idx_to_std[idx]['dependency']:
            mark(dep)

    with timed("propagate_dependencies", **extra):
        for idx in idx_list:
            if matched[idx]:
                mark(idx)

    grades = [1 if idx in final_marked else 0 for idx in idx_list]

    if log_path:
        log_debug_info(problem.get("id"), std_formulas, ans_eqs, match_info, log_path)

    score = (sum(grades) / len(grades)) if grades else 0.0
    logger.info("grade_problem_dag done", extra={**extra, "score": round(score, 4)})
    return score, match_info

def grade_problem_treebased(problem: dict, answer: str, log_path: Optional[str] = None):
    extra = {"phase": "grade_tree_external", "problem_id": problem.get("id")}
    logger.debug("grade_problem_treebased start", extra=extra)
    with timed("extract_answer_equations", **extra):
        ans_eqs = extract_equations(answer)

    with timed("import_gradePhyX", **extra):
        from gradePhyX import (
            build_problem_formulas_for_multiProblems,
            build_Student_AnswersAndScores_for_MultiProblem_from_dict,
            multiStudent_compare_multiProblem
        )

    problemFormulas = dict(
        dummy_problemID_formulas=problem['grading_standard_tree']  # dict
    )
    studentsAnswers = dict(
        dummy_studentID_formulas=dict(
            dummy_problemID_formulas=ans_eqs  # list
        )
    )

    with timed("build_problem_structs", **extra):
        problemsList = build_problem_formulas_for_multiProblems(problemFormulas)
        studentsAnswersAndScores = build_Student_AnswersAndScores_for_MultiProblem_from_dict(
            problemsList, studentsAnswers
        )

    with timed("compare_multiProblem", **extra):
        multiStudent_compare_multiProblem(
            problemsList,
            studentsAnswersAndScores,
            mp.cpu_count() // 3 * 2,
            return_detailed_score=True,
            compare_function=whether_rel_latex_correct_with_units_with_only_one_dict_parameter
        )

    score = studentsAnswersAndScores['dummy_studentID_formulas']['dummy_problemID_formulas'].points
    match_info = studentsAnswersAndScores['dummy_studentID_formulas']['dummy_problemID_formulas'] \
        .detailed_score.checkScores()

    if log_path:
        # For consistency, log key bits
        log_debug_info(problem.get("id"), [], ans_eqs, match_info, log_path)

    logger.info("grade_problem_treebased done", extra={**extra, "score": round(score, 4)})
    return score, match_info
