import sympy as sp

x, p_z, epsilon_UV, epsilon_IR, mu = sp.symbols('x p_z epsilon_UV epsilon_IR mu')

def answer(x, p_z, epsilon_UV, epsilon_IR, mu):
    r"""
    Return the expressions of $\tilde q_{\rm sail}(x,p^z,\epsilon,\mu)$ in Sympy format.

    Inputs
    ----------
    x: sympy.Symbol, longitudinal momentum fraction $x$
    p_z: sympy.Symbol, longitudinal momentum $p^z$
    epsilon_UV: sympy.Symbol, dimensional–regularization parameter for UV divergences, $\epsilon_{\rm UV}$
    epsilon_IR: sympy.Symbol, dimensional–regularization parameter for IR divergences, $\epsilon_{\rm IR}$
    mu: sympy.Symbol, renormalization scale $\mu$

    Outputs
    ----------
    expr_lt0:  sympy.Expr,  $\tilde q_{\rm sail}(x,p^z,\epsilon,\mu)$ for $x < 0$, to $O(\epsilon^0)$
    expr_mid:  sympy.Expr,  $\tilde q_{\rm sail}(x,p^z,\epsilon,\mu)$ for $0<x<1$, to $O(\epsilon^0)$
    expr_gt1:  sympy.Expr,  $\tilde q_{\rm sail}(x,p^z,\epsilon,\mu)$ for $x > 1$, to $O(\epsilon^0)$
    """

    # ------------------ FILL IN YOUR RESULTS BELOW ------------------
    prefactor = sp.I / (16 * sp.pi**2 * p_z)

    expr_lt0 = prefactor * (
        1 + 2*x*sp.log((1 - x)/(-x))
    ) / (1 - x)

    expr_mid = prefactor * (
        -2*x/epsilon_IR
        + 2*x*sp.log(4*x*(1 - x)*p_z**2/mu**2)
        + 1 - 2*x
    ) / (1 - x)

    expr_gt1 = prefactor * (
        2*x*sp.log(x/(x - 1)) - 1
    ) / (1 - x)
    # ---------------------------------------------------------------

    return expr_lt0, expr_mid, expr_gt1
