import sympy as sp

q = sp.symbols('q')

def answer(q):
    r"""
    Return the expression of the generating function in SymPy format.

    Inputs
    ----------
    q: sympy.Symbol, Fugacity for the U(1) charge, $q$

    Outputs
    ----------
    generating_func: sympy.Expr, the generating function of the index of trace relations to up charge 15 in a free $U(2)$ gauge theory
    """

    # ------------------ FILL IN YOUR RESULTS BELOW ------------------
    generating_func = -q**7 + 2*q**9 - q**10 + 3*q**12 - 3*q**13 - 2*q**14 + 5*q**15
    # ---------------------------------------------------------------

    return generating_func
