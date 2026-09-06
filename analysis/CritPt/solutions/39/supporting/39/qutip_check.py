"""
Standalone QuTiP cross-check for Challenge 39.

This script is deliberately SELF-CONTAINED and independent of `answer.py`: the
analytic steady state is re-implemented here from scratch, element by element,
so that the agreement between the two columns of every table below is not an
artefact of shared code.

Model (hbar = 1), three-level atom |b>, |e>, |d> in a lossless cavity:

    H       = (g/2) ( |b><e| a^dag + |e><b| a )
    J       = sqrt(gamma) |d><e|
    rho_dot = -i[H, rho] + J rho J^dag - (1/2){J^dag J, rho}
    rho_0   = |b><b| (x) |psi_c><psi_c|

Analytic steady state of the cavity, derived in challenge39.pdf, valid for an
arbitrary initial cavity state:

    <n'|rho_ss|n> = rho0_{00} d_{n0} d_{n'0}
                  + rho0_{n'+1,n+1} * 2 sqrt((n+1)(n'+1))
                    / [ (g^2 / 2 gamma^2) (n - n')^2 + n + n' + 2 ]

Sections
--------
    0.  why qutip.steadystate() must not be used here
    1.  coherent input        |alpha>
    2.  squeezed vacuum       S(r e^{i theta}) |0>          [bonus]
    3.  squeezed coherent     D(alpha) S(r) |0>             [bonus]
    4.  convergence of the propagation in T
    5.  an explicit small matrix, printed element by element

Usage:  py qutip_check.py
"""

from __future__ import annotations

import math
import warnings

import numpy as np
import qutip as qt

# atomic level ordering used throughout: 0 = |b>, 1 = |e>, 2 = |d>
B, E, D = 0, 1, 2


# ============================================================================
# model
# ============================================================================
def build_model(g: float, gamma: float, N: int):
    """Return (H, c_ops) on the 3 (x) N Hilbert space."""
    b, e, d = (qt.basis(3, i) for i in (B, E, D))
    idN = qt.qeye(N)
    a = qt.tensor(qt.qeye(3), qt.destroy(N))
    H = (g / 2.0) * (qt.tensor(b * e.dag(), idN) * a.dag()
                     + qt.tensor(e * b.dag(), idN) * a)
    c_ops = [math.sqrt(gamma) * qt.tensor(d * e.dag(), idN)]
    return H, c_ops


def propagate(psi_c, g: float, gamma: float, N: int, T: float | None = None,
              atol: float = 1e-12, rtol: float = 1e-10):
    """rho_c(T) for the atom starting in |b> and the cavity in psi_c.

    A Fock cutoff at N is EXACT for this model rather than an approximation:
    H only converts |b,n> into |e,n-1>, so the photon number never increases
    and span{|n> : n < N} is an invariant subspace.

    T defaults to 60 / (slowest relaxation rate of the n = 1 manifold), which
    is gamma/4 in the strong-coupling regime and the Purcell rate g^2/gamma in
    the weak-coupling one.
    """
    H, c_ops = build_model(g, gamma, N)
    dm = qt.ket2dm(psi_c) if psi_c.type == "ket" else psi_c
    rho0 = qt.tensor(qt.ket2dm(qt.basis(3, B)), dm)
    if T is None:
        T = 60.0 / min(gamma / 4.0, g ** 2 / gamma)
    opts = {"atol": atol, "rtol": rtol, "nsteps": 200000}
    res = qt.mesolve(H, rho0, [0.0, T], c_ops=c_ops, e_ops=[], options=opts)
    return res.states[-1].ptrace(1).full()


# ============================================================================
# analytic result, re-implemented independently of answer.py
# ============================================================================
def analytic(rho0_c, g: float, gamma: float) -> np.ndarray:
    """<n'|rho_ss|n>, coded as a literal transcription of the formula."""
    r0 = np.asarray(rho0_c, dtype=complex)
    N = r0.shape[0]
    out = np.zeros((N, N), dtype=complex)
    for npr in range(N):
        for n in range(N):
            if npr + 1 < N and n + 1 < N:
                den = ((g ** 2 / (2.0 * gamma ** 2)) * (n - npr) ** 2
                       + n + npr + 2.0)
                out[npr, n] = (r0[npr + 1, n + 1]
                               * 2.0 * math.sqrt((n + 1) * (npr + 1)) / den)
    out[0, 0] += r0[0, 0]
    return out


def ket_from_amplitudes(c) -> qt.Qobj:
    v = np.asarray(c, dtype=complex).reshape(-1, 1)
    return qt.Qobj(v).unit()


def coherent_ket(alpha: complex, N: int) -> qt.Qobj:
    """c_n = e^{-|alpha|^2/2} alpha^n / sqrt(n!), truncated and renormalised.

    Built from the analytic amplitudes rather than with qt.coherent(), whose
    default 'operator' method applies a truncated displacement operator and so
    differs from the analytic state at the 1e-6 level for small N.
    """
    n = np.arange(N)
    logfac = np.array([math.lgamma(k + 1) for k in n])
    if alpha == 0:
        c = np.zeros(N, complex)
        c[0] = 1.0
    else:
        c = np.exp(-0.5 * abs(alpha) ** 2 + n * np.log(complex(alpha))
                   - 0.5 * logfac)
    return ket_from_amplitudes(c)


def squeezed_vacuum_ket(r: float, theta: float, N: int) -> qt.Qobj:
    """<2m|S(r e^{i theta})|0> = (-e^{i theta} tanh r)^m sqrt((2m)!)
                                 / (2^m m! sqrt(cosh r)).

    Same convention as qt.squeeze(N, z) = exp[(z* a^2 - z a^dag^2)/2].
    """
    c = np.zeros(N, complex)
    for m in range(N // 2 + 1):
        if 2 * m >= N:
            break
        logmag = (0.5 * math.lgamma(2 * m + 1) - m * math.log(2.0)
                  - math.lgamma(m + 1))
        c[2 * m] = (math.exp(logmag) / math.sqrt(math.cosh(r))
                    * (-np.exp(1j * theta) * math.tanh(r)) ** m)
    return ket_from_amplitudes(c)


def squeezed_coherent_ket(alpha: complex, r: float, N: int) -> qt.Qobj:
    return (qt.displace(N, alpha) * qt.squeeze(N, r) * qt.basis(N, 0)).unit()


def compare(psi_c: qt.Qobj, g: float, gamma: float, N: int, **kw):
    """max |rho_analytic - rho_qutip| for one parameter set."""
    rho0 = qt.ket2dm(psi_c).full()
    A = analytic(rho0, g, gamma)
    Bm = propagate(psi_c, g, gamma, N, **kw)
    return np.abs(A - Bm).max(), A, Bm


# ============================================================================
# 0.  why steadystate() must not be used
# ============================================================================
def section0(N: int = 6, g: float = 1.0, gamma: float = 1.0):
    print("=" * 78)
    print("0.  The Liouvillian kernel is degenerate: steadystate() is invalid")
    print("=" * 78)
    H, c_ops = build_model(g, gamma, N)
    L = qt.liouvillian(H, c_ops).full()
    nzero = int(np.sum(np.abs(np.linalg.eigvals(L)) < 1e-10))
    expected = N * N + 1 + 2 * N          # |d><d| block, |b,0><b,0|, and the
    print("  N = %d:  dim(Liouvillian) = %d x %d" % (N, L.shape[0], L.shape[1]))
    print("  zero eigenvalues of L : %d   [predicted N^2 + 1 + 2N = %d]"
          % (nzero, expected))
    print("     N^2 from |d><d| (x) any cavity state, 1 from |b,0><b,0|,")
    print("     and 2N frozen |b,0><d,m| coherences")
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            qt.steadystate(H, c_ops)
        print("  qutip.steadystate() returned a state -- but it is an")
        print("  ARBITRARY kernel element, not the physical steady state.")
    except Exception as exc:
        print("  qutip.steadystate() raises %s:" % type(exc).__name__)
        print("     %s" % str(exc).split("\n")[0][:70])
    print("  => the physical steady state depends on rho(0); this script")
    print("     obtains it by propagating to long times instead.")
    print()


# ============================================================================
# 1-3.  parameter sweeps
# ============================================================================
def section1(cases=((1.0, 1.0, 1.0, 20),
                    (10.0, 1.0, 1.0, 20),
                    (0.2, 1.0, 1.2, 22),
                    (3.0, 2.0, 1.5, 24),
                    (2.0, 0.7, 0.8 + 0.6j, 22))):
    print("=" * 78)
    print("1.  COHERENT input  |alpha>")
    print("=" * 78)
    print("      g   gamma        alpha    N     max|analytic - qutip|")
    worst = 0.0
    for g, gamma, alpha, N in cases:
        d, _, _ = compare(coherent_ket(alpha, N), g, gamma, N)
        worst = max(worst, d)
        print("   %5.1f   %5.1f  %11s  %3d              %9.2e"
              % (g, gamma, str(alpha), N, d))
    print()
    return worst


def section2(cases=((1.0, 1.0, 0.6, 0.0, 24),
                    (5.0, 1.0, 0.8, 0.0, 28),
                    (0.3, 1.0, 0.5, 0.0, 24),
                    (2.0, 1.5, 0.7, 0.9, 26))):
    print("=" * 78)
    print("2.  BONUS -- SQUEEZED VACUUM input  S(r e^{i theta})|0>")
    print("=" * 78)
    print("      g   gamma      r  theta    N   max|analytic - qutip|"
          "   P(odd)+P(0)")
    worst = 0.0
    for g, gamma, r, theta, N in cases:
        psi = squeezed_vacuum_ket(r, theta, N)
        d, A, _ = compare(psi, g, gamma, N)
        worst = max(worst, d)
        p = A[0, 0].real + sum(A[n, n].real for n in range(1, N, 2))
        print("   %5.1f   %5.1f  %5.2f  %5.2f  %3d            %9.2e"
              "     %.10f" % (g, gamma, r, theta, N, d, p))
    print("   (the squeezed vacuum has only even n and exactly one photon is")
    print("    always lost, so the steady state lives on odd n plus |0>)")
    print()
    return worst


def section3(cases=((1.5, 1.0, 0.7, 0.4, 24),
                    (3.0, 1.0, 0.5 + 0.3j, 0.6, 26))):
    print("=" * 78)
    print("3.  BONUS -- SQUEEZED COHERENT input  D(alpha) S(r)|0>")
    print("=" * 78)
    print("      g   gamma        alpha      r    N     max|analytic - qutip|")
    worst = 0.0
    for g, gamma, alpha, r, N in cases:
        d, _, _ = compare(squeezed_coherent_ket(alpha, r, N), g, gamma, N)
        worst = max(worst, d)
        print("   %5.1f   %5.1f  %11s  %5.2f  %3d              %9.2e"
              % (g, gamma, str(alpha), r, N, d))
    print()
    return worst


# ============================================================================
# 4.  convergence in the propagation time
# ============================================================================
def section4(g: float = 1.0, gamma: float = 1.0, alpha: float = 1.0,
             N: int = 20):
    print("=" * 78)
    print("4.  Convergence in the propagation time (g=%.1f, gamma=%.1f, "
          "alpha=%.1f)" % (g, gamma, alpha))
    print("=" * 78)
    psi = coherent_ket(alpha, N)
    A = analytic(qt.ket2dm(psi).full(), g, gamma)
    rate = min(gamma / 4.0, g ** 2 / gamma)
    print("     T*rate    max|analytic - qutip|")
    for f in (1, 3, 10, 30, 60):
        rho = propagate(psi, g, gamma, N, T=f / rate)
        print("     %6d              %9.2e" % (f, np.abs(A - rho).max()))
    print("   (exponential convergence: the transient decays at `rate`)")
    print()


# ============================================================================
# 5.  an explicit small matrix
# ============================================================================
def section5(g: float = 2.0, gamma: float = 1.0, alpha: float = 1.0,
             N: int = 12, show: int = 5):
    print("=" * 78)
    print("5.  Explicit matrix elements, g=%.1f gamma=%.1f alpha=%.1f "
          "(top-left %dx%d)" % (g, gamma, alpha, show, show))
    print("=" * 78)
    psi = coherent_ket(alpha, N)
    d, A, Bm = compare(psi, g, gamma, N)
    np.set_printoptions(precision=6, suppress=True, linewidth=150)
    def block(m):
        lines = np.array2string(m[:show, :show].real).splitlines()
        return "\n".join("   " + ln for ln in lines)
    print("  analytic  <n'|rho_ss|n>:")
    print(block(A))
    print("  qutip:")
    print(block(Bm))
    print("  max abs difference over the full %dx%d matrix: %.3e" % (N, N, d))
    print("  trace: analytic %.12f, qutip %.12f"
          % (np.trace(A).real, np.trace(Bm).real))
    print()


# ============================================================================
if __name__ == "__main__":
    section0()
    w = max(section1(), section2(), section3())
    section4()
    section5()
    print("=" * 78)
    print("WORST DISAGREEMENT OVER ALL PARAMETER SETS: %.2e" % w)
    print("=" * 78)
    assert w < 1e-9, "analytic result disagrees with QuTiP"
