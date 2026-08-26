import re
from typing import List, Dict, Any, Union

def str_to_dict(input_str: str, total_score_for_current_problem: float) -> Dict[str, Any]:
    """
    Convert a string representation of formulas into a dictionary format.
    
    Args:
        input_str: String representation like "[A,B,[C,D]],[(E,F),G]]"
        total_score_for_current_problem: Total points for this problem
    
    Returns:
        Dictionary with the required structure
    """
    # Remove outer brackets if present
    input_str = input_str.strip()
    if input_str.startswith('[') and input_str.endswith(']'):
        input_str = input_str[1:-1]
    
    # Parse the main structure
    parsed_structure = parse_formula_structure(input_str)
    
    # Count total formulas to calculate points
    total_formulas = count_formulas(parsed_structure)
    
    # Build the dictionary structure
    result = {
        'points': total_score_for_current_problem
    }
    
    # Add prevsumnode structure
    build_prevsumnode_structure(result, parsed_structure, total_score_for_current_problem, total_formulas)
    
    return result

def parse_formula_structure(s: str) -> List[Union[str, List, tuple]]:
    """
    Parse the formula string into a nested structure.
    Returns a list where each element can be:
    - str: a formula
    - list: a prevsumnode (bracket group)
    - tuple: a part group (parenthesis group)
    """
    result = []
    i = 0
    current_formula = ""
    in_latex = False
    
    while i < len(s):
        char = s[i]
        
        # Handle LaTeX delimiters
        if char == '$' and i + 1 < len(s) and s[i + 1] == '$':
            in_latex = not in_latex
            current_formula += '$$'
            i += 2
            continue
        
        if in_latex:
            current_formula += char
            i += 1
            continue
        
        if char == '[':
            # Save current formula if any
            if current_formula.strip():
                result.append(current_formula.strip())
                current_formula = ""
            
            # Find matching closing bracket
            bracket_count = 1
            j = i + 1
            temp_in_latex = False
            while j < len(s) and bracket_count > 0:
                if s[j] == '$' and j + 1 < len(s) and s[j + 1] == '$':
                    temp_in_latex = not temp_in_latex
                    j += 2
                    continue
                if not temp_in_latex:
                    if s[j] == '[':
                        bracket_count += 1
                    elif s[j] == ']':
                        bracket_count -= 1
                j += 1
            
            # Recursively parse the content inside brackets
            inner_content = s[i+1:j-1]
            result.append(parse_formula_structure(inner_content))
            i = j
            
        elif char == '(':
            # Save current formula if any
            if current_formula.strip():
                result.append(current_formula.strip())
                current_formula = ""
            
            # Find matching closing parenthesis
            paren_count = 1
            j = i + 1
            temp_in_latex = False
            while j < len(s) and paren_count > 0:
                if s[j] == '$' and j + 1 < len(s) and s[j + 1] == '$':
                    temp_in_latex = not temp_in_latex
                    j += 2
                    continue
                if not temp_in_latex:
                    if s[j] == '(':
                        paren_count += 1
                    elif s[j] == ')':
                        paren_count -= 1
                j += 1
            
            # Parse content inside parentheses as a tuple (part group)
            inner_content = s[i+1:j-1]
            result.append(tuple(parse_formula_structure(inner_content)))
            i = j
            
        elif char == ',':
            # End of current formula (only if not in LaTeX)
            if current_formula.strip():
                result.append(current_formula.strip())
                current_formula = ""
            i += 1
            
        else:
            current_formula += char
            i += 1
    
    # Add the last formula if any
    if current_formula.strip():
        result.append(current_formula.strip())
    
    return result

def count_formulas(structure: List[Union[str, List, tuple]]) -> int:
    """Count the total number of individual formulas in the structure."""
    count = 0
    for item in structure:
        if isinstance(item, str):
            count += 1
        elif isinstance(item, (list, tuple)):
            count += count_formulas(list(item))
    return count

def build_prevsumnode_structure(parent_dict: Dict[str, Any], structure: List[Union[str, List, tuple]], 
                               total_points: float, total_formulas: int) -> None:
    """
    Build the prevsumnode structure in the parent dictionary.
    """
    prevsumnode_index = 1
    
    for item in structure:
        node_formulas_count = count_formulas([item]) # Count formulas in the current node
        
        node_dict = {
            'points': node_formulas_count / total_formulas * total_points
        }
        
        if isinstance(item, str):
            # Single formula
            node_dict['formula_1'] = {
                'points': node_formulas_count / total_formulas * total_points,
                'answer_latex': item
            }
        elif isinstance(item, list):
            # Nested prevsumnode structure
            build_prevsumnode_structure(node_dict, item, total_points, total_formulas)
        elif isinstance(item, tuple):
            # Part structure (parentheses group)
            build_part_structure(node_dict, list(item), total_points, total_formulas)
        
        parent_dict[f'prevsumnode_{prevsumnode_index}'] = node_dict
        prevsumnode_index += 1

def build_part_structure(parent_dict: Dict[str, Any], structure: List[Union[str, List, tuple]], 
                        total_points: float, total_formulas: int) -> None:
    """
    Build the part structure in the parent dictionary.
    """
    part_index = 1
    
    for item in structure:
        node_formulas_count = count_formulas([item]) # Count formulas in the current node
        
        part_dict = {
            'points': node_formulas_count / total_formulas * total_points
        }
        
        if isinstance(item, str):
            # Single formula in a part
            part_dict['formula_1'] = {
                'points': node_formulas_count / total_formulas * total_points,
                'answer_latex': item
            }
        elif isinstance(item, list):
            # Nested prevsumnode in part
            build_prevsumnode_structure(part_dict, item, total_points, total_formulas)
        elif isinstance(item, tuple):
            # Nested part in part
            build_part_structure(part_dict, list(item), total_points, total_formulas)
        
        parent_dict[f'part_{part_index}'] = part_dict
        part_index += 1

# Test function
def test_parser():
    """Test the parser with some examples."""
    
    # Test case 1: Simple example from the problem description
    test1 = "A,B,[C,D],[(E,F),G]"
    result1 = str_to_dict(test1, 7.0)  # Using 7 as total points for easy fraction verification
    
    print("Test 1 Result:")
    print_dict_structure(result1)
    print()
    
    # Test case 2: One of the provided examples (simplified)
    test2 = "$$m(\\ddot{r}-r\\dot{\\theta}^2)=f(r)-\\lambda\\dot{r}$$,$$m(2\\dot{r}\\dot{\\theta}+r\\ddot{\\theta})=-\\lambdar\\dot{\\theta}$$,$$\\frac{1}{r}\\frac{d}{dt}(mr^2\\dot{\\theta})=-\\lambdar\\dot{\\theta}$$"
    result2 = str_to_dict(f"[{test2}]", 10.0)
    
    print("Test 2 Result:")
    print_dict_structure(result2)
    print()

def print_dict_structure(d: Dict[str, Any], indent: int = 0) -> None:
    """Helper function to print dictionary structure nicely."""
    for key, value in d.items():
        print("  " * indent + f"{key}:")
        if isinstance(value, dict):
            print_dict_structure(value, indent + 1)
        else:
            print("  " * (indent + 1) + str(value))

if __name__ == "__main__":
    test_parser()



    # Test case 3: Example with multiple prevsumnodes and parts
    test3 = "[$$mR\\omega^2\\leq\\frac{GmM}{R^2}$$,$$\\frac{M}{R^3}\\geq\\frac{\\omega^2}{G}$$,$$\\rho=\\frac{M}{\\frac{4}{3}\\piR^3}\\geq\\frac{3\\omega^2}{4\\piG}$$,$$\\rho_{\\min}=\\frac{3(2\\pi\\times30)^2}{4\\pi\\times6.7\\times10^{-11}}\\sim1.3\\times10^{14}\\\\mathrm{kg/m^3}$$],[$$\\frac{3M}{4\\piR^3}\\geq\\rho_{\\min}$$,$$R\\leq\\left(\\frac{3M}{4\\pi\\rho_{\\min}}\\right)^{1/3}$$,$$R_{\\max}=\\left(\\frac{6\\times10^{30}}{4\\pi\\times1.3\\times10^{14}}\\right)^{1/3}=1.5\\times10^5\\,\\mathrm{m}=150\\,\\mathrm{km}$$],[$$\\rho_{\\mathrm{nuclear}}\\approx\\frac{m_p}{4\\piR_0^3/3}$$,$$m_p\\approxm_H=\\frac{2\\times10^{-3}}{2\\times6.02\\times10^{23}}=1.7\\times10^{-27}\\\\mathrm{kg}$$,$$R_0\\approx1.5\\times10^{-15}\\\\mathrm{m}$$,$$\\rho_{\\mathrm{nuclear}}\\approx1.2\\times10^{17}\\\\mathrm{kg/m^3}$$,$$R=\\left(\\frac{6\\times10^{30}}{4\\pi\\times1.2\\times10^{17}}\\right)^{1/3}\\approx17\\,\\mathrm{km}$$]"
    result3 = str_to_dict(test3, 100.0)
    print("Test 3 Result:")
    print_dict_structure(result3)
    print()

    # Test case 4: Another example
    test4 = "[$$v=\\sqrt{2gl}$$,$$\\frac{mv_1^2}{l-d}=mg$$,$$v_1^2=(l-d)g$$,$$\\frac{mv^2}{2}=\\frac{mv_1^2}{2}+2mg(l-d)$$,$$2gl=(l-d)g+4(l-d)g$$,$$d=\\frac{3l}{5}$$]"
    result4 = str_to_dict(test4, 50.0)
    print("Test 4 Result:")
    print_dict_structure(result4)
    print()

    import json
    # Test with examples
    examples = [
        "(    [        $$F = w + \\frac{w}{g} a$$,        $$F = w \\left( 1 + \\frac{a}{g} \\right)$$    ],    [        $$P = F v_t$$,        $$v_t = V + v$$,        $$F = w \\left( 1 + \\frac{a}{g} \\right)$$,        $$P = w \\left( 1 + \\frac{a}{g} \\right) (V + v)$$    ])",
        "[$$m(\\ddot{r}-r\\dot{\\theta}^2)=f(r)-\\lambda\\dot{r}$$,$$m(2\\dot{r}\\dot{\\theta}+r\\ddot{\\theta})=-\\lambda r\\dot{\\theta}$$,$$\\frac{1}{r}\\frac{d}{dt}(mr^2\\dot{\\theta})=-\\lambda r\\dot{\\theta}$$,$$\\frac{dJ}{dt}=-\\frac{\\lambda}{m}J$$,$$J=J_0e^{-\\frac{\\lambda}{m}t}$$]",
        "[$$mR\\omega^2\\leq\\frac{GmM}{R^2}$$,$$\\frac{M}{R^3}\\geq\\frac{\\omega^2}{G}$$,$$\\rho=\\frac{M}{\\frac{4}{3}\\piR^3}\\geq\\frac{3\\omega^2}{4\\piG}$$,$$\\rho_{\\min}=\\frac{3(2\\pi\\times30)^2}{4\\pi\\times6.7\\times10^{-11}}\\sim1.3\\times10^{14}\\mathrm{kg/m^3}$$]",
        "[$$v=\\sqrt{2gl}$$,$$\\frac{mv_1^2}{l-d}=mg$$,$$v_1^2=(l-d)g$$,([$$\\frac{mv^2}{2}=\\frac{mv_1^2}{2}+2mg(l-d)$$,$$2gl=(l-d)g+4(l-d)g$$],$$d=\\frac{3l}{5}$$)]"
    ]

    for i, example in enumerate(examples, 1):
        result = str_to_dict(example, total_score_for_current_problem=1.0)
        print(f"\nExample {i} Result:\n{json.dumps(result, ensure_ascii=False)}")
        # with open(f"example_{i}_result.json", "w", encoding="utf-8") as f:
        #     json.dump(result, f, ensure_ascii=False, indent=2)
