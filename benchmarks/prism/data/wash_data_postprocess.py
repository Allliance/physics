import json
import argparse
from utils.convert_answer_format_utils import str_to_dict

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Convert standard answer format to JSON format.")
    parser.add_argument("--input_file", type=str, default="rewritten/01-1_rewritten_0-5_v3.stage3.json", help="Path to the input file containing standard answer format.")
    parser.add_argument("--output_file", type=str, default="rewritten/01-1_rewritten_0-5_v3.stage4.json", help="Path to the output JSON file.")
    
    args = parser.parse_args()
    
    problem_list = json.load(open(args.input_file, "r", encoding="utf-8"))
    
    newlist = list()
    for i, problem_item in enumerate(problem_list):
        if problem_item.get("id") is None:
            print("Missing id.")
            problem_item["id"] = str(10000+i)
        problem_id = problem_item["id"]
        problem_grading_standard = problem_item["grading_standard"]
        try:
            tree_structure = str_to_dict(problem_grading_standard,total_score_for_current_problem=1.0)
        except:
            continue
        current_dict = problem_item
        
        final_answer_form = current_dict.get("final_answer_form", "algebraic")

        if final_answer_form == "algebraic":
            epsilon_for_equal = 1e-5
        else:
            significant_figures = current_dict.get("significant_figures", 2)
            assert significant_figures >= 1, current_dict
            if significant_figures == 1:
                epsilon_for_equal = 0.2
            elif significant_figures == 2:
                epsilon_for_equal = 0.2
            elif significant_figures >= 3:
                epsilon_for_equal = 5*10^{1-significant_figures}
        
        tree_structure["epsilon_for_equal"] = epsilon_for_equal
        
        problem_item["grading_standard_tree"] = tree_structure
        newlist.append(problem_item)
    print(f"altogether {len(newlist)} valid items")
    with open(args.output_file, "w", encoding="utf-8") as f:
        json.dump(newlist, f, ensure_ascii=False, indent=2)
    
    print(f"Converted data saved to {args.output_file}")
