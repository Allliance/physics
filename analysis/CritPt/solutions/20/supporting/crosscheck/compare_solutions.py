"""
Cross-check of the two independent solution sets for Challenges 20 and 39.

    "ours"   -> challenges/20/answer.py , challenges/39/answer.py
    "theirs" -> solutions/20/answer.py  , solutions/39/answer.py
                (codex-cli/gpt-5.6-sol, per solutions/*/metadata.json,
                 review_status "generated-unreviewed")

Summary of what this script establishes
---------------------------------------
CHALLENGE 39 -- the two answers are the SAME EXPRESSION.  SymPy simplifies
their difference to exactly 0, and they agree numerically to ~5e-17 over
10x10 blocks of (n, n') for four parameter sets including complex alpha.  The
apparent discrepancy is two algebraic rewritings applied at once:

    2 |a|^2 a^{n'} (a*)^n            = 2 a^{n'+1} (a*)^{n+1}
    2 / [ (g^2/2 gam^2) D^2 + S ]    = 4 gam^2 / [ g^2 D^2 + 2 gam^2 S ]

with D = n - n', S = n + n' + 2; the product of the two rewritings turns
2|a|^2 into 4 gam^2 a a* and shifts both exponents by one.

CHALLENGE 20 -- the g FORMULAE ARE IDENTICAL to ours in the cycle-averaged
(C = 1/2) convention, which is the default of our answer.py.  The one
substantive difference is that their omega_t retains the optical-binding
correction to the torsional stiffness,

    k_tor -> k_tor [ 1 + (V chi_par / pi R^3)(cos kR + kR sin kR) ] ,

which we derived with exactly the same coefficient (challenge20.pdf Sec. 5,
"Binding-induced frequency shift") but dropped, following the source paper
arXiv:2504.08194.  This script verifies

    omega_t^theirs / [ omega_t^ours * sqrt(1 + delta) ]        = 1
    g^theirs / g^ours(C=1/2) * sqrt(1 + delta)                 = 1

to 12 digits at six (P_0, R) combinations, with
delta = 4 alpha_par (cos kR + kR sin kR) / (4 pi eps0 R^3).

Run:  py compare_solutions.py
"""

from __future__ import annotations

import importlib.util
import math
import os

import numpy as np
import sympy as sp

_HERE = os.path.dirname(os.path.abspath(__file__))
_ROOT = os.path.dirname(_HERE)


def _load(name: str, relpath: str):
    spec = importlib.util.spec_from_file_location(
        name, os.path.join(_ROOT, relpath))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


ours20 = _load("ours20", "challenges/20/answer.py")
theirs20 = _load("theirs20", "solutions/20/answer.py")
ours39 = _load("ours39", "challenges/39/answer.py")
theirs39 = _load("theirs39", "solutions/39/answer.py")


# ============================================================================
# Challenge 20
# ============================================================================
PAR20 = dict(a=300e-9, b=180e-9, rho=3500.0, eps_r=5.7, w0=500e-9)
LAM20 = 1064e-9


def binding_correction(R: float, k: float) -> float:
    """delta = 4 alpha_par [cos kR + kR sin kR] / (4 pi eps0 R^3).

    The relative shift of the torsional stiffness caused by the neighbour's
    scattered field.  Equivalently (V chi_par / pi R^3)(cos kR + kR sin kR).
    """
    a_par, _ = ours20.polarizabilities(PAR20["a"], PAR20["b"], PAR20["eps_r"])
    return (4.0 * a_par * (math.cos(k * R) + k * R * math.sin(k * R))
            / (4.0 * math.pi * ours20.EPS0 * R ** 3))


def compare20(cases=((0.6, 1.06e-6), (0.6, 0.95 * LAM20), (0.6, 2.0 * LAM20),
                     (1.0, 1.06e-6), (1.0, 0.95 * LAM20), (1.0, 2.0 * LAM20))):
    k = 2.0 * math.pi / LAM20
    a, b, rho = PAR20["a"], PAR20["b"], PAR20["rho"]
    eps_r, w0 = PAR20["eps_r"], PAR20["w0"]
    rows = []
    for P0, R in cases:
        wt_t, g_t = theirs20.answer(a * 1e9, b * 1e9, rho, k, eps_r,
                                    P0 * 1e3, w0 * 1e9, R * 1e9)
        wt_o = ours20.omega_t(a, b, eps_r, rho, P0, w0)
        g_half = ours20.coupling_g(a, b, eps_r, rho, P0, w0, R, k,
                                   "time_averaged")
        g_one = ours20.coupling_g(a, b, eps_r, rho, P0, w0, R, k, "paper")
        delta = binding_correction(R, k)
        rows.append(dict(
            P0=P0, R=R, R_lam=R / LAM20, delta=delta,
            wt_theirs=wt_t, wt_ours=wt_o, wt_ours_corr=wt_o * math.sqrt(1 + delta),
            g_theirs=g_t, g_ours_half=g_half, g_ours_one=g_one,
            ratio_w=wt_t / (wt_o * math.sqrt(1 + delta)),
            ratio_g=g_t / g_half * math.sqrt(1 + delta)))
    return rows


# ============================================================================
# Challenge 39
# ============================================================================
def symbolic39():
    """Return sympy.simplify(theirs - ours); should be exactly 0.

    SymPy does not automatically identify |alpha|^2 with alpha*conj(alpha) for
    a symbol of unknown sign, so that one substitution is made by hand before
    simplifying.  The check is repeated with a real positive alpha, where no
    substitution is needed.
    """
    n, npr = sp.symbols("n n_prime", integer=True, nonnegative=True)
    g, gam = sp.symbols("g gamma", positive=True)

    def build(al):
        theirs = theirs39.answer(n, npr, g, gam, al)
        ours = (sp.exp(-sp.Abs(al) ** 2) * sp.KroneckerDelta(npr, 0)
                * sp.KroneckerDelta(n, 0)
                + sp.exp(-sp.Abs(al) ** 2) * 2 * sp.Abs(al) ** 2
                * al ** npr * sp.conjugate(al) ** n
                / (sp.sqrt(sp.factorial(n) * sp.factorial(npr))
                   * (g ** 2 / (2 * gam ** 2) * (n - npr) ** 2 + n + npr + 2)))
        return theirs, ours

    al = sp.symbols("alpha")                       # general complex
    theirs, ours = build(al)
    sub = {sp.Abs(al) ** 2: al * sp.conjugate(al)}
    diff = sp.simplify(sp.expand((theirs - ours).subs(sub)))

    alr = sp.symbols("alpha", positive=True)       # real positive
    th_r, ou_r = build(alr)
    diff_real = sp.simplify(sp.expand(th_r - ou_r))

    return diff, diff_real, theirs, ours


def numeric39(cases=((1.0, 1.0, 1.0), (10.0, 1.0, 0.8 + 0.6j),
                     (0.2, 3.0, 1.5), (2.0, 0.7, -0.9 + 0.2j)), N: int = 10):
    """max |theirs - ours| over an N x N block of (n', n)."""
    rows = []
    for g, gam, alpha in cases:
        A = ours39.coherent_closed_form(alpha, g, gam, N)
        worst = 0.0
        for i in range(N):
            for j in range(N):
                t = complex(theirs39.answer(sp.Integer(j), sp.Integer(i),
                                            sp.Float(g), sp.Float(gam),
                                            sp.nsimplify(alpha)).evalf())
                worst = max(worst, abs(t - A[i, j]))
        rows.append(dict(g=g, gamma=gam, alpha=alpha, N=N, worst=worst))
    return rows


# ============================================================================
if __name__ == "__main__":
    print("=" * 78)
    print("CHALLENGE 39  --  are the two expressions the same?")
    print("=" * 78)
    diff, diff_real, theirs_expr, ours_expr = symbolic39()
    print("  theirs :", theirs_expr)
    print()
    print("  ours   :", ours_expr)
    print()
    print("  sympy.simplify(theirs - ours), complex alpha  = %s" % diff)
    print("  sympy.simplify(theirs - ours), alpha > 0      = %s" % diff_real)
    print("  -> %s" % ("IDENTICAL expressions" if (diff == 0 and diff_real == 0)
                       else "DIFFERENT, investigate"))
    print()
    print("      g   gamma        alpha    N   max|theirs-ours| over the block")
    rows39 = numeric39()
    for r in rows39:
        print("  %5.1f   %5.1f  %11s  %3d               %9.2e"
              % (r["g"], r["gamma"], str(r["alpha"]), r["N"], r["worst"]))
    print()

    print("=" * 78)
    print("CHALLENGE 20  --  where do the two answers differ?")
    print("=" * 78)
    rows20 = compare20()
    print("   P0[W] R/lam    delta      omega_t/2pi [MHz]"
          "                       ratio")
    print("                          theirs      ours      ours*sqrt(1+d)"
          "     t/(o*sqrt)")
    for r in rows20:
        print("   %4.1f  %5.3f  %+8.5f   %9.6f %9.6f      %9.6f   %.12f"
              % (r["P0"], r["R_lam"], r["delta"],
                 r["wt_theirs"] / 2 / math.pi / 1e6,
                 r["wt_ours"] / 2 / math.pi / 1e6,
                 r["wt_ours_corr"] / 2 / math.pi / 1e6, r["ratio_w"]))
    print()
    print("   P0[W] R/lam            g/2pi [kHz]                        ratio")
    print("                       theirs   ours(C=1/2)  ours(C=1)"
          "    (t/o)*sqrt(1+d)")
    for r in rows20:
        print("   %4.1f  %5.3f    %+10.4f  %+10.4f  %+10.4f      %.12f"
              % (r["P0"], r["R_lam"], r["g_theirs"] / 2 / math.pi / 1e3,
                 r["g_ours_half"] / 2 / math.pi / 1e3,
                 r["g_ours_one"] / 2 / math.pi / 1e3, r["ratio_g"]))
    print()
    print("  -> both ratios are 1 to 12 digits: the two g formulae are the")
    print("     same, and the whole difference is the optical-binding factor")
    print("     sqrt(1+delta) that they keep in omega_t and we dropped.")
    print()

    # assertions
    assert diff == 0 and diff_real == 0, "challenge 39 expressions differ"
    assert max(r["worst"] for r in rows39) < 1e-15
    assert max(abs(r["ratio_w"] - 1.0) for r in rows20) < 1e-11
    assert max(abs(r["ratio_g"] - 1.0) for r in rows20) < 1e-11
    print("ALL CONSISTENCY ASSERTIONS PASSED.")
