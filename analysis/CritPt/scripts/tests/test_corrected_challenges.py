import hashlib
import json
from pathlib import Path
import tempfile
import unittest

from build_corrected_challenges import (
    build_corrected_challenges, prepare_ground_truth, prepare_problem, text_body,
)


class CorrectedChallengesTests(unittest.TestCase):
    def fixture(self, base):
        decisions = {
            "03": {"verdict": {"problem": "clean", "model": "incorrect"}, "reason": "Expert corrected answer."},
            "04": {"verdict": {"problem": "repairable", "model": "correct"}, "reason": "Expert clarified assumptions."},
            "11": {"reason": "Unclear", "question_for_expert": "Which interpretation?"},
            "38": {"verdict": {"problem": "clean", "model": "incorrect"}, "reason": "No replacement answer."},
            "41": {"verdict": {"problem": "unrepairable", "model": "none"}, "reason": "No unique repair."},
        }
        originals = [{"challenge_id": f"Challenge_{int(k)}", "problem_description": f"Original {k}",
                      "code_template": "def answer(): return ..."} for k in ("00", *decisions)]
        (base / "original_challenges.jsonl").write_text("\n".join(json.dumps(r) for r in originals))
        (base / "annotations.csv").write_text("Challenge ID\n" + "\n".join(decisions))
        for k in ("03", "04", "11", "41"):
            folder = base / "solutions" / k
            folder.mkdir(parents=True)
            (folder / "final_answer.tex").write_text("Audited answer " + k)
        (base / "solutions/04/problem.tex").write_text("Corrected problem 04")
        sources = {p.relative_to(base).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest()
                   for p in base.rglob("*") if p.is_file()}
        (base / "verdict_review.json").write_text(json.dumps({"source_sha256": sources, "challenges": decisions}))
        verdicts = {k: v["verdict"] for k, v in decisions.items() if "verdict" in v}
        (base / "verdicts.json").write_text(json.dumps(verdicts))

    def test_exports_only_supported_pairs_with_exact_schema(self):
        with tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary)
            self.fixture(base)
            rows, ids, excluded = build_corrected_challenges(base)
            self.assertEqual(ids, ["03", "04"])
            self.assertEqual(rows, [
                {"challenge_id": "03", "problem": "Original 03", "ground_truth": "Audited answer 03"},
                {"challenge_id": "04", "problem": "Corrected problem 04", "ground_truth": "Audited answer 04"},
            ])
            self.assertEqual(excluded, {"00": "unaudited", "11": "unresolved audit",
                                       "38": "missing audited final answer", "41": "unrepairable problem"})
            self.assertFalse((base / "corrected_challenge.jsonl").exists())

    def test_changed_answer_requires_readjudication(self):
        with tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary)
            self.fixture(base)
            (base / "solutions/03/final_answer.tex").write_text("Unreviewed answer")
            with self.assertRaisesRegex(ValueError, "Reviewed source changed"):
                build_corrected_challenges(base)

    def test_rejects_stale_verdict_export(self):
        with tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary)
            self.fixture(base)
            (base / "verdicts.json").write_text("{}")
            with self.assertRaisesRegex(ValueError, "stale"):
                build_corrected_challenges(base)

    def test_reads_slim_original_schema_without_using_its_reference_answer(self):
        with tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary)
            self.fixture(base)
            path = base / "original_challenges.jsonl"
            records = [json.loads(line) for line in path.read_text().splitlines()]
            slim = [{"challenge_id": f"{int(r['challenge_id'].split('_')[-1]):02d}",
                     "problem": r["problem_description"], "ground_truth": "Ignored stale reference"}
                    for r in records]
            path.write_text("\n".join(json.dumps(r) for r in slim))
            review_path = base / "verdict_review.json"
            review = json.loads(review_path.read_text())
            review["source_sha256"][path.name] = hashlib.sha256(path.read_bytes()).hexdigest()
            review_path.write_text(json.dumps(review))
            rows, ids, _ = build_corrected_challenges(base)
            self.assertEqual(ids, ["03", "04"])
            self.assertEqual(rows[0]["problem"], "Original 03")
            self.assertEqual(rows[0]["ground_truth"], "Audited answer 03")

    def test_tex_macros_and_corrections_survive_without_layout_or_metadata(self):
        raw = r"""\documentclass{article}
\newcommand{\kb}{k_{\mathrm B}}
\newcommand{\ketbra}[2]{\lvert #1\rangle\langle #2\rvert}
\begin{document}\maketitle
\textbf{Problem ID:} hidden\\
\textbf{Python implementation:} answer.py
\paragraph*{Problem setup}
{\color{blue}Keep $\kb$ and $\ketbra{b}{\alpha}$; retain 5\%.}
% hidden solution comment
\[\adjustbox{max width=\linewidth}{$\frac{1}{2}$}\]
\end{document}"""
        actual = text_body(raw)
        for unwanted in ("hidden", "answer.py", "color", "documentclass", "linewidth", "adjustbox", r"\kb"):
            self.assertNotIn(unwanted, actual)
        self.assertIn(r"k_{\mathrm B}", actual)
        self.assertIn(r"\lvert b\rangle\langle \alpha\rvert", actual)
        self.assertIn(r"5\%", actual)
        self.assertIn(r"\[\frac{1}{2}\]", actual)

    def test_review_appendix_is_removed_but_action_conventions_remain(self):
        raw = (r"\section*{Problem setup}Compute the observable."
               r"\section*{\chg{Issues found in the statement and how they are handled}}"
               "The answer is 3.1675.")
        actual = prepare_problem("08", raw)
        self.assertNotIn("3.1675", actual)
        self.assertIn(r"\mathcal S_{EH}", actual)
        self.assertIn(r"\epsilon_{0123}=1", actual)

    def test_special_extraction_fails_if_reviewed_marker_changes(self):
        with self.assertRaisesRegex(ValueError, "marker changed"):
            prepare_problem("07", "Unexpected new format")

    def test_converts_template_only_answer_notation(self):
        with tempfile.TemporaryDirectory() as temporary:
            folder = Path(temporary)
            (folder / "solution.tex").write_text(
                "Neither changes the asymptotic population growth rate to first order.")
            raw = r"(\mathrm{answer}_{\beta},\mathrm{answer}_{\sigma^2})=(\mathrm{C},\mathrm{C})"
            answer = prepare_ground_truth("02", raw, folder)
            self.assertIn("population growth rate", answer)
            self.assertNotIn(r"\mathrm{C}", answer)
            answer = prepare_ground_truth("62", r"k_{\mathrm{value}}=1", folder)
            self.assertEqual(answer, "k=1")


if __name__ == "__main__":
    unittest.main()
