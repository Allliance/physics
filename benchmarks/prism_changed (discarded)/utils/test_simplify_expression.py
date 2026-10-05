import unittest

from utils.simplify_expression import simplify_latex_expr


class PresentationMacroTests(unittest.TestCase):
    def test_unwraps_boxed_formula_with_nested_braces(self):
        actual = simplify_latex_expr(r"\boxed{v=\frac{2GM}{R}}")
        self.assertEqual(actual, simplify_latex_expr(r"v=\frac{2GM}{R}"))

    def test_unwraps_fbox_formula(self):
        actual = simplify_latex_expr(r"\fbox{x=a+b}")
        self.assertEqual(actual, simplify_latex_expr(r"x=a+b"))

    def test_unwraps_multiple_wrappers(self):
        actual = simplify_latex_expr(r"\boxed{x=a}+\fbox{y=b}")
        self.assertEqual(actual, simplify_latex_expr(r"x=a+y=b"))

    def test_preserves_unbalanced_macro(self):
        self.assertIn(r"\boxed", simplify_latex_expr(r"\boxed{x=a"))


if __name__ == "__main__":
    unittest.main()
