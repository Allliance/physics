"""
Challenge 39 -- Alteration of cavity field coherences due to atom-cavity
interaction.

A three-level atom (ground states |b>, |d>, excited |e>) sits in a lossless
cavity prepared in a coherent state |alpha>.  With hbar = 1,

    H  = (g/2) ( |b><e| a^dag + |e><b| a ),
    J  = sqrt(gamma) |d><e|,
    rho_dot = -i[H, rho] + J rho J^dag - (1/2){J^dag J, rho},
    rho_0 = |b><b| (x) |alpha><alpha| .

Result
------
For ANY initial cavity state rho_c(0) (pure or mixed), the exact steady state
of the cavity is

    rho_c,ss = <0|rho_c(0)|0> |0><0|  +  F o ( a rho_c(0) a^dag ),          (*)

where "o" is the elementwise (Hadamard) product in the Fock basis and

    F_{n'n} = 2 / [ (g^2 / 2 gamma^2) (n - n')^2 + n + n' + 2 ].

Elementwise,

    <n'|rho_c,ss|n> = rho^0_{00} d_{n0} d_{n'0}
                    + rho^0_{n'+1,n+1} * 2 sqrt((n+1)(n'+1))
                      / [ (g^2/2gamma^2)(n-n')^2 + n + n' + 2 ] .

For the coherent state of the problem, rho^0_{n'n} = e^{-|a|^2}
a^{n'} (a*)^n / sqrt(n'! n!), so

    <n'|rho_c,ss|n> = e^{-|a|^2} [ d_{n0} d_{n'0}
                      + 2 |a|^2 a^{n'} (a*)^n
                        / ( sqrt(n! n'!) [ (g^2/2gamma^2)(n-n')^2 + n+n'+2 ] ) ].

Checks built into this module:
  * Tr rho_c,ss = 1 analytically and numerically.
  * The DIAGONAL is <n|rho_ss|n> = |c_{n+1}|^2 + |c_0|^2 d_{n0}, independent of
    g and gamma: one photon is removed with certainty unless the cavity was
    already empty.
  * The normalised coherence is reduced by exactly
        D_{n'n} = 2 sqrt((n+1)(n'+1)) / [ (g^2/2gamma^2)(n-n')^2 + n+n'+2 ] <= 1,
    equal to 1 only for n = n'.  D -> 0 as g/gamma -> infinity (the emission
    time resolves the Rabi frequency sqrt(n) g/2, i.e. maximal which-path
    information); D -> 2 sqrt((n+1)(n'+1))/(n+n'+2) as g/gamma -> 0, the
    residual decoherence from the n-dependent Purcell rate g^2 n / gamma.

WARNING about qutip's steadystate(): the Liouvillian here has a hugely
degenerate kernel (every |d><d| (x) rho_c is stationary, and so is
|b,0><b,0|), so the steady state is NOT determined by L rho = 0 alone -- it
depends on the initial condition.  `steadystate()` returns an arbitrary kernel
element.  The cross-check below therefore integrates the master equation to
long times instead.

Bonus: the derivation never used the coherent-state amplitudes, so (*) holds
verbatim for a squeezed input.  For squeezed vacuum only even n are populated
initially, hence the steady state is supported on ODD n plus the vacuum.

Run `py answer.py` for the derivation summary and the QuTiP cross-checks.
"""

from __future__ import annotations

import math

import numpy as np


# ---------------------------------------------------------------- analytics --
def coherence_kernel(N: int, g: float, gamma: float) -> np.ndarray:
    """F_{n'n} = 2 / [ (g^2/2gamma^2)(n-n')^2 + n + n' + 2 ]  (N x N)."""
    n = np.arange(N)
    dn2 = (n[None, :] - n[:, None]) ** 2          # (n - n')^2 with rows = n'
    s = n[None, :] + n[:, None] + 2.0
    return 2.0 / ((g ** 2 / (2.0 * gamma ** 2)) * dn2 + s)


def coherence_reduction(N: int, g: float, gamma: float) -> np.ndarray:
    """D_{n'n} = F_{n'n} sqrt((n+1)(n'+1)): the factor by which the normalised
    coherence between Fock states n and n' is reduced.  D <= 1, D_{nn} = 1."""
    n = np.arange(N)
    return coherence_kernel(N, g, gamma) * np.sqrt(
        np.outer(n + 1.0, n + 1.0))


def steady_state_from_rho0(rho0_c, g: float, gamma: float) -> np.ndarray:
    """Exact cavity steady state for an arbitrary initial cavity state.

        rho_ss = rho0_{00} |0><0| + F o (a rho0 a^dag)
    """
    r0 = np.asarray(rho0_c, dtype=complex)
    N = r0.shape[0]
    n = np.arange(N)
    a = np.diag(np.sqrt(n[1:]), 1)                 # annihilation operator
    out = coherence_kernel(N, g, gamma) * (a @ r0 @ a.conj().T)
    out[0, 0] += r0[0, 0]
    return out


def steady_state_from_amplitudes(c, g: float, gamma: float) -> np.ndarray:
    """Same, for a pure initial cavity state |psi> = sum_n c_n |n>."""
    c = np.asarray(c, dtype=complex)
    return steady_state_from_rho0(np.outer(c, c.conj()), g, gamma)


def coherent_amplitudes(alpha: complex, N: int) -> np.ndarray:
    """c_n = e^{-|alpha|^2/2} alpha^n / sqrt(n!)."""
    n = np.arange(N)
    logc = (-0.5 * abs(alpha) ** 2 + n * np.log(alpha if alpha != 0 else 1.0)
            - 0.5 * np.array([math.lgamma(k + 1) for k in n]))
    c = np.exp(logc)
    if alpha == 0:
        c = np.zeros(N, complex)
        c[0] = 1.0
    return c


def squeezed_vacuum_amplitudes(r: float, theta: float, N: int) -> np.ndarray:
    """<2m|S(r e^{i theta})|0> = (-e^{i theta} tanh r)^m sqrt((2m)!)
                                 / (2^m m! sqrt(cosh r)),  odd terms zero.

    Matches qutip's squeeze(N, z) = exp[(z* a^2 - z a^dag^2)/2].
    """
    c = np.zeros(N, complex)
    pref = 1.0 / math.sqrt(math.cosh(r))
    for m in range(N // 2 + 1):
        if 2 * m >= N:
            break
        logmag = (0.5 * math.lgamma(2 * m + 1) - m * math.log(2.0)
                  - math.lgamma(m + 1))
        c[2 * m] = (pref * math.exp(logmag)
                    * (-np.exp(1j * theta) * math.tanh(r)) ** m)
    return c


def coherent_closed_form(alpha: complex, g: float, gamma: float,
                         N: int) -> np.ndarray:
    """The explicit closed form quoted in the docstring, coded directly.

        <n'|rho_ss|n> = e^{-|a|^2} [ d_{n0}d_{n'0} + 2 |a|^2 a^{n'} (a*)^n
                        / ( sqrt(n! n'!) ((g^2/2g^2)(n-n')^2 + n+n'+2) ) ]
    """
    out = np.zeros((N, N), complex)
    e = math.exp(-abs(alpha) ** 2)
    fact = np.array([math.factorial(k) for k in range(N)], dtype=float)
    for npr in range(N):
        for n in range(N):
            den = (g ** 2 / (2.0 * gamma ** 2)) * (n - npr) ** 2 + n + npr + 2.0
            num = 2.0 * abs(alpha) ** 2 * (alpha ** npr) * (np.conj(alpha) ** n)
            out[npr, n] = e * num / (math.sqrt(fact[n] * fact[npr]) * den)
    out[0, 0] += e
    return out


def squeezed_vacuum_closed_form(r: float, theta: float, g: float, gamma: float,
                                N: int) -> np.ndarray:
    """Closed form for an initial squeezed vacuum, coded directly from
    s_{2m} and the kernel (bonus part of the problem)."""
    s = squeezed_vacuum_amplitudes(r, theta, N)
    out = np.zeros((N, N), complex)
    for npr in range(N - 1):
        for n in range(N - 1):
            den = (g ** 2 / (2.0 * gamma ** 2)) * (n - npr) ** 2 + n + npr + 2.0
            out[npr, n] = (s[npr + 1] * np.conj(s[n + 1])
                           * 2.0 * math.sqrt((n + 1) * (npr + 1)) / den)
    out[0, 0] += abs(s[0]) ** 2
    return out


# ------------------------------------------------------------------- QuTiP ---
def qutip_steady_state(psi_c, g: float, gamma: float, N: int,
                       T: float | None = None, atol: float = 1e-12,
                       rtol: float = 1e-10):
    """Integrate the master equation to long times and trace out the atom.

    `steadystate()` is unusable here (degenerate Liouvillian kernel), so the
    physical steady state is obtained as lim_{t->inf} rho(t).

    Note that a Fock cutoff at N is EXACT for this model, not an
    approximation: H only converts |b,n> into |e,n-1>, so the photon number
    never increases and span{|n> : n < N} is an invariant subspace.
    """
    import qutip as qt

    b, e, d = (qt.basis(3, i) for i in range(3))
    a = qt.tensor(qt.qeye(3), qt.destroy(N))
    H = (g / 2.0) * (qt.tensor(b * e.dag(), qt.qeye(N)) * a.dag()
                     + qt.tensor(e * b.dag(), qt.qeye(N)) * a)
    c_ops = [math.sqrt(gamma) * qt.tensor(d * e.dag(), qt.qeye(N))]
    dm = qt.ket2dm(psi_c) if psi_c.type == "ket" else psi_c
    rho0 = qt.tensor(qt.ket2dm(b), dm)
    if T is None:
        # slowest relaxation rate of the n = 1 manifold: gamma/4 (strong
        # coupling) or the Purcell rate g^2/gamma (weak coupling)
        T = 60.0 / min(gamma / 4.0, g ** 2 / gamma)
    opts = {"atol": atol, "rtol": rtol, "nsteps": 200000}
    res = qt.mesolve(H, rho0, [0.0, T], c_ops=c_ops, e_ops=[], options=opts)
    return res.states[-1].ptrace(1).full()


def _ket(c):
    """Normalised QuTiP ket from an amplitude vector."""
    import qutip as qt
    v = np.asarray(c, dtype=complex)
    return qt.Qobj(v.reshape(-1, 1)).unit()


# -------------------------------------------------------------- validation ---
def _fmt(x):
    return "%.3e" % x


def crosscheck_coherent(cases=((1.0, 1.0, 1.0, 20),
                               (10.0, 1.0, 1.0, 20),
                               (0.2, 1.0, 1.2, 22),
                               (3.0, 2.0, 1.5, 24),
                               (2.0, 0.7, 0.8 + 0.6j, 22))):
    """|rho_analytic - rho_qutip| for the coherent-state problem.

    The initial state is the analytic amplitude vector truncated at N and
    renormalised, so that the SAME state enters both sides; the truncation is
    then exact (see `qutip_steady_state`) and any residual difference is pure
    integrator error.  `tail` reports the discarded weight, i.e. how far the
    truncated state is from a true coherent state, and `d_closed` compares the
    infinite-dimensional closed form against the same run.
    """
    rows = []
    for g, gamma, alpha, N in cases:
        c = coherent_amplitudes(alpha, N)
        tail = abs(1.0 - float(np.vdot(c, c).real))
        cn = c / np.linalg.norm(c)
        A = steady_state_from_amplitudes(cn, g, gamma)
        Acl = coherent_closed_form(alpha, g, gamma, N)
        B = qutip_steady_state(_ket(cn), g, gamma, N)
        rows.append(dict(g=g, gamma=gamma, alpha=alpha, N=N, tail=tail,
                         d=np.abs(A - B).max(),
                         d_closed=np.abs(Acl - B).max(),
                         d_trunc=np.abs(Acl - A).max(),
                         tr=np.trace(Acl).real))
    return rows


def crosscheck_squeezed(cases=((1.0, 1.0, 0.6, 0.0, 24),
                               (5.0, 1.0, 0.8, 0.0, 28),
                               (0.3, 1.0, 0.5, 0.0, 24),
                               (2.0, 1.5, 0.7, 0.9, 26))):
    """Bonus: same, for an initial squeezed vacuum S(r e^{i theta})|0>."""
    import qutip as qt
    rows = []
    for g, gamma, r, theta, N in cases:
        s = squeezed_vacuum_amplitudes(r, theta, N)
        tail = abs(1.0 - float(np.vdot(s, s).real))
        # convention check against qutip's squeeze() (itself truncated, so the
        # agreement is limited by the same tail)
        conv = np.abs((qt.squeeze(N, r * np.exp(1j * theta))
                       * qt.basis(N, 0)).full().ravel() - s).max()
        sn = s / np.linalg.norm(s)
        A = steady_state_from_amplitudes(sn, g, gamma)
        B = qutip_steady_state(_ket(sn), g, gamma, N)
        odd = sum(A[n, n].real for n in range(1, N, 2))
        rows.append(dict(g=g, gamma=gamma, r=r, theta=theta, N=N, tail=tail,
                         conv=conv, d=np.abs(A - B).max(),
                         tr=np.trace(A).real, p_odd=odd, p_vac=A[0, 0].real))
    return rows


def crosscheck_squeezed_coherent(cases=((1.5, 1.0, 0.7, 0.4, 24),
                                        (3.0, 1.0, 0.5 + 0.3j, 0.6, 26))):
    """Squeezed *coherent* input D(alpha) S(r)|0>, via the general formula."""
    import qutip as qt
    rows = []
    for g, gamma, alpha, r, N in cases:
        psi = (qt.displace(N, alpha) * qt.squeeze(N, r) * qt.basis(N, 0)).unit()
        A = steady_state_from_rho0(qt.ket2dm(psi).full(), g, gamma)
        B = qutip_steady_state(psi, g, gamma, N)
        rows.append(dict(g=g, gamma=gamma, alpha=alpha, r=r, N=N,
                         d=np.abs(A - B).max()))
    return rows


def _tex(x):
    """1.23e-13 -> 1.23\\times10^{-13}"""
    m, e = ("%.2e" % x).split("e")
    return "%s\\times10^{%d}" % (m, int(e))


def latex_rows_coherent(rows):
    return "\n".join(
        "$%.1f$ & $%.1f$ & $%s$ & $%d$ & $%s$ & $%s$ & $%s$ \\\\"
        % (r["g"], r["gamma"],
           ("%.1f" % np.real(r["alpha"])) if np.imag(r["alpha"]) == 0
           else ("%.1f%+.1f\\mathrm{i}"
                 % (np.real(r["alpha"]), np.imag(r["alpha"]))),
           r["N"], _tex(r["d"]), _tex(r["d_closed"]), _tex(r["d_trunc"]))
        for r in rows)


def latex_rows_squeezed(rows):
    return "\n".join(
        "$%.1f$ & $%.1f$ & $%.1f$ & $%.1f$ & $%d$ & $%s$ & $%.12f$ & $%.10f$ \\\\"
        % (r["g"], r["gamma"], r["r"], r["theta"], r["N"], _tex(r["d"]),
           r["tr"], r["p_odd"] + r["p_vac"])
        for r in rows)


def latex_rows_squeezed_coherent(rows):
    return "\n".join(
        "$%.1f$ & $%.1f$ & $%s$ & $%.1f$ & $%d$ & $%s$ \\\\"
        % (r["g"], r["gamma"],
           ("%.1f" % np.real(r["alpha"])) if np.imag(r["alpha"]) == 0
           else ("%.1f%+.1f\\mathrm{i}"
                 % (np.real(r["alpha"]), np.imag(r["alpha"]))),
           r["r"], r["N"], _tex(r["d"]))
        for r in rows)


# -------------------------------------------------------------------- main ---
if __name__ == "__main__":
    print("=" * 78)
    print("CHALLENGE 39 -- steady-state cavity coherences")
    print("=" * 78)
    print("  <n'|rho_ss|n> = rho0_{00} d_n0 d_n'0")
    print("                + rho0_{n'+1,n+1} 2 sqrt((n+1)(n'+1))")
    print("                  / [ (g^2/2gamma^2)(n-n')^2 + n + n' + 2 ]")
    print()
    print("  coherent input: = e^{-|a|^2}[ d_n0 d_n'0 + 2|a|^2 a^{n'}(a*)^n /")
    print("                    ( sqrt(n! n'!) ((g^2/2gamma^2)(n-n')^2+n+n'+2) )]")
    print()

    # structural checks -------------------------------------------------------
    g, gamma, alpha, N = 2.0, 1.0, 1.1, 24
    A = coherent_closed_form(alpha, g, gamma, N)
    c = coherent_amplitudes(alpha, N)
    print("Structural checks (g=%.1f, gamma=%.1f, alpha=%.1f, N=%d):"
          % (g, gamma, alpha, N))
    print("  trace                       = %.14f" % np.trace(A).real)
    print("  hermiticity  max|A-A^dag|   = %s" % _fmt(np.abs(A - A.conj().T).max()))
    diag_pred = np.array([abs(c[n + 1]) ** 2 for n in range(N - 1)])
    diag_pred = np.append(diag_pred, 0.0)
    diag_pred[0] += abs(c[0]) ** 2
    print("  diagonal vs |c_{n+1}|^2     = %s   (g, gamma independent)"
          % _fmt(np.abs(np.diag(A).real - diag_pred).max()))
    D = coherence_reduction(N, g, gamma)
    print("  coherence reduction D: max = %.12f (should be 1, at n=n'),"
          " min = %.3e" % (D.max(), D.min()))
    print("  D for (n,n')=(0,1): %.6f  (g/gamma=0.1 -> %.6f, "
          "g/gamma=10 -> %.6f)"
          % (D[0, 1], coherence_reduction(2, 0.1, 1.0)[0, 1],
             coherence_reduction(2, 10.0, 1.0)[0, 1]))
    print()

    # QuTiP cross-checks ------------------------------------------------------
    print("=" * 78)
    print("QuTiP cross-check -- COHERENT input  |max(rho_analytic-rho_qutip)|")
    print("=" * 78)
    print("     g   gamma        alpha    N     formula(*)    closed form"
          "    truncation")
    rows_c = crosscheck_coherent()
    for r in rows_c:
        print("  %4.1f   %5.1f  %11s  %3d      %9s      %9s     %9s"
              % (r["g"], r["gamma"], str(r["alpha"]), r["N"], _fmt(r["d"]),
                 _fmt(r["d_closed"]), _fmt(r["d_trunc"])))
    print("  (formula(*) uses the same truncated state as QuTiP, so it is an")
    print("   exact test; the closed form is the N->infinity limit and differs")
    print("   by the Fock-space truncation, last column)")
    print()

    print("=" * 78)
    print("BONUS -- SQUEEZED VACUUM input  S(r e^{i theta})|0>")
    print("=" * 78)
    print("     g   gamma      r  theta    N     maxdiff   Fock tail"
          "        trace   P(odd)+P(0)")
    rows_s = crosscheck_squeezed()
    for r in rows_s:
        print("  %4.1f   %5.1f  %5.2f  %5.2f  %3d   %9s   %9s   %.12f   %.10f"
              % (r["g"], r["gamma"], r["r"], r["theta"], r["N"], _fmt(r["d"]),
                 _fmt(r["tail"]), r["tr"], r["p_odd"] + r["p_vac"]))
    print("  (all population sits on ODD n plus the vacuum, as it must: the")
    print("   squeezed vacuum has only even n, and exactly one photon is lost)")
    print()

    print("=" * 78)
    print("BONUS -- SQUEEZED COHERENT input  D(alpha) S(r)|0>")
    print("=" * 78)
    print("     g   gamma        alpha      r    N        maxdiff")
    rows_sc = crosscheck_squeezed_coherent()
    for r in rows_sc:
        print("  %4.1f   %5.1f  %11s  %5.2f  %3d      %9s"
              % (r["g"], r["gamma"], str(r["alpha"]), r["r"], r["N"],
                 _fmt(r["d"])))
    print()

    worst = max([r["d"] for r in rows_c] + [r["d"] for r in rows_s]
                + [r["d"] for r in rows_sc])
    print("WORST DISAGREEMENT OVER ALL %d CASES: %s"
          % (len(rows_c) + len(rows_s) + len(rows_sc), _fmt(worst)))
    assert worst < 1e-9, "analytic result disagrees with QuTiP"
    print()
    print("LaTeX rows (coherent):")
    print(latex_rows_coherent(rows_c))
    print()
    print("LaTeX rows (squeezed vacuum):")
    print(latex_rows_squeezed(rows_s))
    print()
    print("LaTeX rows (squeezed coherent):")
    print(latex_rows_squeezed_coherent(rows_sc))
