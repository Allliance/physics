import unittest

from eval.__main__ import resolve_dataset_path
from eval.parsing import detect_part_ids, extract_boxes, map_separated_boxes, parse_json_object
from eval.pipeline import resolve_ground_truth


class ParsingTests(unittest.TestCase):
    def test_dataset_selection(self):
        self.assertEqual(resolve_dataset_path("FrontierPhysics", "test").name, "test.parquet")
        self.assertEqual(resolve_dataset_path("Physics", "validation").name, "validation.parquet")
        with self.assertRaisesRegex(ValueError, "no validation split"):
            resolve_dataset_path("FrontierPhysics", "validation")

    def test_parts_are_ground_truth_keys_in_order(self):
        self.assertEqual(detect_part_ids({"b": "one", "d": "two", "f": "three"}), ["b", "d", "f"])

    def test_parts_require_nonempty_ground_truths(self):
        with self.assertRaisesRegex(ValueError, "at least one part"):
            detect_part_ids({})

    def test_balanced_boxes(self):
        text = r"work \boxed{(a) \frac{x}{y}} then \boxed{(b) z}"
        self.assertEqual(extract_boxes(text), [r"(a) \frac{x}{y}", "(b) z"])

    def test_empty_and_whitespace_boxes(self):
        self.assertEqual(extract_boxes(r"\boxed{} \boxed   { (b) answer }"), ["", "(b) answer"])

    def test_escaped_braces_do_not_affect_balance(self):
        self.assertEqual(extract_boxes(r"\boxed{(a) \{x\} and \text{set {A}}}"),
                         [r"(a) \{x\} and \text{set {A}}"])

    def test_deeply_nested_box_content(self):
        text = r"\boxed{(a) \frac{1}{1+\frac{x}{1+\frac{y}{z}}}}"
        self.assertEqual(extract_boxes(text), [r"(a) \frac{1}{1+\frac{x}{1+\frac{y}{z}}}"])

    def test_no_box_returns_empty_list(self):
        self.assertEqual(extract_boxes("There is no final answer box."), [])

    def test_unclosed_box_is_ignored(self):
        self.assertEqual(extract_boxes(r"reasoning \boxed{(a) unfinished"), [])

    def test_map_boxes(self):
        mapped, errors = map_separated_boxes(["(a) 1", "(b): 2"], ["a", "b"])
        self.assertEqual(mapped, {"a": "1", "b": "2"})
        self.assertEqual(errors, [])

    def test_json_fenced(self):
        self.assertEqual(parse_json_object('```json\n{"correct": ["a"]}\n```')["correct"], ["a"])

    def test_ground_truths(self):
        value, source = resolve_ground_truth({"ground_truths": '{"a":"final"}'}, ["a"])
        self.assertEqual((value, source), ({"a": "final"}, "ground_truths"))

    def test_ground_truths_is_required(self):
        with self.assertRaisesRegex(ValueError, "no ground_truths"):
            resolve_ground_truth({"id": "missing"}, ["a"])
        with self.assertRaisesRegex(ValueError, "missing parts"):
            resolve_ground_truth({"id": "partial", "ground_truths": '{"a":"x"}'}, ["a", "b"])


if __name__ == "__main__":
    unittest.main()
