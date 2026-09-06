"""
Generalised Challenge 20: two *arbitrarily shaped* rigid dielectric particles in
two linearly polarised Gaussian tweezers, reduced to the two-ellipsoid answer.

Physical content
----------------
1.  DIPOLE ORDER IS SHAPE-BLIND.  For any particle small compared with the
    wavelength, the leading optical response is a single symmetric rank-2
    polarisability tensor alpha (three principal values alpha_1 >= alpha_2 >=
    alpha_3).  Every quantity in the two-particle librational problem -- trap
    stiffnesses, tilt-induced transverse dipoles, the dipole-dipole coupling --
    depends on the shape *only* through alpha and through the inertia tensor.
    Hence at dipole order an arbitrary particle is exactly equivalent to a
    unique ellipsoid, computed here by `equivalent_ellipsoid`.  The optical
    equivalence is exact; the *mechanical* part is not, because the equivalent
    ellipsoid generally has the wrong inertia tensor -- one must keep the true
    one.

2.  A GENERAL PARTICLE HAS TWO LIBRATIONAL MODES, NOT ONE.  With alpha_1 the
    largest principal polarisability, equilibrium puts body axis 1 along the
    polarisation.  Expanding U = -(1/4) E0^2 e.alpha(Omega).e to second order in
    the rotation vector phi about equilibrium gives

        U = const + (1/4) E0^2 [ (alpha_1-alpha_2) phi_3^2
                               + (alpha_1-alpha_3) phi_2^2 ]

    so k_2 = (1/2) E0^2 (alpha_1-alpha_3),  k_3 = (1/2) E0^2 (alpha_1-alpha_2),
    and phi_1 -- the spin about the polarisation axis -- is an EXACT zero mode
    of a uniform, strictly linearly polarised field, for any shape.  Two
    librations per particle, four modes in total.

3.  THE COUPLING IS A MATRIX, AND IT SEES G_par AS WELL AS G_perp.  The
    tilt-induced transverse dipole is

        dp/dphi_3 = (alpha_1-alpha_2) E0 u_2,
        dp/dphi_2 = -(alpha_1-alpha_3) E0 u_3,

    with u_i the lab images of the body axes, and the coupling block is

        kappa_{mu nu} = -C Re[ (dp_1/dphi^mu) . G(R) . (dp_2/dphi^nu) ].

    Only when both transverse directions are perpendicular to R (i.e. the
    polarisation is parallel to R, as in the challenge) is the block diagonal
    and proportional to Re G_perp.  In the geometry of arXiv:2504.08194
    (polarisation perpendicular to R) one mode couples through the LONGITUDINAL
    G_par ~ 1/R^2 and the other through the transverse G_perp ~ 1/R: two
    different couplings with different ranges.

4.  MULTIPOLES.  Beyond dipole order the response is the full multipole
    hierarchy (equivalently the T-matrix): p = alpha.E + (1/3) A:grad E + ...,
    Q = A.E + C:grad E + ...  For a CENTROSYMMETRIC shape (ellipsoid included)
    A vanishes by parity and corrections to g start at O((a/R)^2); an arbitrary
    shape has A != 0 and therefore an O(a/R) correction that no ellipsoid can
    reproduce.  That, and the inertia tensor, are the only ways an arbitrary
    particle escapes the equivalent-ellipsoid description.  The centrosymmetric
    O((a/R)^2) coefficients of Ref. [Zhang2025] App. A are implemented in
    `multipole_coefficients` for comparison.

Reduction chain (verified numerically in `demo_reduction`):
    arbitrary shape -> equivalent ellipsoid (alpha tensor)
        -> axially symmetric (alpha_2 = alpha_3, I_2 = I_3): two degenerate
           librations
        -> polarisation along R: coupling block diagonal, both entries equal
        -> one libration plane: H = hbar w_t (a1'a1 + a2'a2)
                                  + hbar g (a1'a2 + a1 a2')   [= answer.py]

Run `py generalized.py` for the full report.
"""

from __future__ import annotations

import importlib.util
import math
import os

import numpy as np
from scipy.integrate import quad
from scipy.linalg import eigh
from scipy.optimize import brentq, fsolve

# ---------------------------------------------------------------- constants --
EPS0 = 8.8541878128e-12
C_LIGHT = 299792458.0
HBAR = 1.054571817e-34

# import the two-ellipsoid reference implementation (../answer.py)
_HERE = os.path.dirname(os.path.abspath(__file__))
_spec = importlib.util.spec_from_file_location(
    "challenge20_answer", os.path.join(_HERE, os.pardir, "answer.py"))
answer = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(answer)


# ============================================================================
# 1.  Shape -> polarisability tensor, and its inverse
# ============================================================================
def depolarization_general(a: float, b: float, c: float) -> np.ndarray:
    """Depolarisation factors (L1, L2, L3) of a general ellipsoid.

        L_i = (abc/2) int_0^inf ds / [ (s + a_i^2) sqrt((s+a^2)(s+b^2)(s+c^2)) ]

    Osborn, Phys. Rev. 67, 351 (1945); Landau & Lifshitz, ECM Sec. 4.
    Sum_i L_i = 1 identically.
    """
    ax = np.array([a, b, c], float)
    scale = ax.max()
    u = ax / scale                      # integrate in units of the largest axis

    def integrand(t, i):
        # substitution s = u_max^2 t/(1-t) maps [0,inf) -> [0,1)
        s = t / (1.0 - t)
        jac = 1.0 / (1.0 - t) ** 2
        rad = math.sqrt((s + u[0] ** 2) * (s + u[1] ** 2) * (s + u[2] ** 2))
        return jac / ((s + u[i] ** 2) * rad)

    L = np.array([0.5 * np.prod(u) * quad(integrand, 0.0, 1.0, args=(i,),
                                          limit=200)[0] for i in range(3)])
    return L / L.sum()                  # enforce the exact sum rule


def alpha_ellipsoid(a: float, b: float, c: float, eps_r: float) -> np.ndarray:
    """Principal quasi-static polarisabilities of a general ellipsoid [SI]."""
    V = 4.0 / 3.0 * math.pi * a * b * c
    L = depolarization_general(a, b, c)
    return EPS0 * V * (eps_r - 1.0) / (1.0 + L * (eps_r - 1.0))


def equivalent_ellipsoid(alphas, eps_r: float):
    """Semi-axes (a, b, c) of the unique ellipsoid with the given alpha tensor.

    Inverting alpha_i = eps0 V (eps_r-1)/(1 + L_i (eps_r-1)) together with the
    sum rule Sum L_i = 1 fixes the volume in closed form,

        V = (eps_r + 2) / [ eps0 (eps_r - 1) Sum_i 1/alpha_i ],

    after which each L_i is known and the two independent axis ratios follow
    from a 2-d root find.  This is the exact statement that, at dipole order,
    an arbitrary sub-wavelength particle is optically indistinguishable from
    one specific ellipsoid.
    """
    al = np.asarray(alphas, float)
    V = (eps_r + 2.0) / (EPS0 * (eps_r - 1.0) * np.sum(1.0 / al))
    L = (EPS0 * V * (eps_r - 1.0) / al - 1.0) / (eps_r - 1.0)
    if np.any(L <= 0) or np.any(L >= 1):
        raise ValueError("no ellipsoid reproduces this alpha tensor: L = %s" % L)

    abc = 3.0 * V / (4.0 * math.pi)     # product of the semi-axes

    def residual(p):
        # p = (ln(a/c), ln(b/c)); axes are then fixed by abc
        r1, r2 = math.exp(p[0]), math.exp(p[1])
        c_ = (abc / (r1 * r2)) ** (1.0 / 3.0)
        Lc = depolarization_general(r1 * c_, r2 * c_, c_)
        return [Lc[0] - L[0], Lc[1] - L[1]]

    # initial guess from the sphere
    sol = fsolve(residual, [0.3, 0.1], full_output=True)
    p = sol[0]
    if sol[2] != 1:
        raise RuntimeError("equivalent-ellipsoid root find failed: %s" % sol[3])
    r1, r2 = math.exp(p[0]), math.exp(p[1])
    c_ = (abc / (r1 * r2)) ** (1.0 / 3.0)
    return r1 * c_, r2 * c_, c_


def inertia_ellipsoid(a: float, b: float, c: float, rho: float) -> np.ndarray:
    """Principal moments (I_1, I_2, I_3) about the body axes 1, 2, 3."""
    m = rho * 4.0 / 3.0 * math.pi * a * b * c
    return m / 5.0 * np.array([b ** 2 + c ** 2, a ** 2 + c ** 2, a ** 2 + b ** 2])


# ============================================================================
# 2.  Electrodynamics: the dyadic Green function
# ============================================================================
def green_dyadic(Rvec, k: float) -> np.ndarray:
    """Free-space dyadic Green function G with E_scattered = G . p  [SI, 3x3].

        G(R) = e^{ikR}/(4 pi eps0 R) [ (1 - RR) k^2 + (3 RR - 1)(1/R^2 - ik/R) ]

    Its eigenvalues are G_par (along R) and G_perp (twice, transverse):
        G_par  = 2 e^{ikR} (1 - ikR) / (4 pi eps0 R^3)      ~ 1/R^2 far field
        G_perp =   e^{ikR} (k^2R^2 + ikR - 1)/(4 pi eps0 R^3) ~ 1/R far field
    """
    Rvec = np.asarray(Rvec, float)
    R = np.linalg.norm(Rvec)
    n = Rvec / R
    nn = np.outer(n, n)
    pref = np.exp(1j * k * R) / (4.0 * math.pi * EPS0 * R)
    return pref * ((np.eye(3) - nn) * k ** 2
                   + (3.0 * nn - np.eye(3)) * (1.0 / R ** 2 - 1j * k / R))


def G_par(R: float, k: float) -> complex:
    """Longitudinal eigenvalue of G (dipoles along R)."""
    return 2.0 * np.exp(1j * k * R) * (1.0 - 1j * k * R) / (
        4.0 * math.pi * EPS0 * R ** 3)


def G_perp(R: float, k: float) -> complex:
    """Transverse eigenvalue of G (dipoles perpendicular to R)."""
    return np.exp(1j * k * R) * ((k * R) ** 2 + 1j * k * R - 1.0) / (
        4.0 * math.pi * EPS0 * R ** 3)


# ============================================================================
# 3.  The generalised librational problem
# ============================================================================
class Particle:
    """A rigid sub-wavelength dielectric particle.

    alphas   : (alpha_1, alpha_2, alpha_3), principal polarisabilities, sorted
               descending (body axis 1 is the most polarisable one).
    inertia  : (I_1, I_2, I_3), principal moments about the *same* body axes.
               If the optical and mechanical principal axes do not coincide,
               pass `inertia_matrix` instead (3x3 in the alpha eigenbasis).
    axes     : 3x3 rotation matrix whose columns u_1, u_2, u_3 are the lab
               images of the body axes at equilibrium.
    """

    def __init__(self, alphas, inertia=None, axes=None, inertia_matrix=None):
        self.alphas = np.asarray(alphas, float)
        if self.alphas[0] < max(self.alphas[1:]):
            raise ValueError("body axis 1 must be the most polarisable axis")
        if inertia_matrix is not None:
            self.inertia_matrix = np.asarray(inertia_matrix, float)
        else:
            self.inertia_matrix = np.diag(np.asarray(inertia, float))
        self.axes = np.eye(3) if axes is None else np.asarray(axes, float)

    # -- single-particle trap ------------------------------------------------
    def trap_stiffness(self, E0: float) -> np.ndarray:
        """(k_2, k_3) for rotations about body axes 2 and 3.

        phi_1, the spin about the polarisation direction, is an exact zero mode
        of a uniform linearly polarised field and is omitted.
        """
        a1, a2, a3 = self.alphas
        return 0.5 * E0 ** 2 * np.array([a1 - a3, a1 - a2])

    def dipole_derivatives(self, E0: float) -> np.ndarray:
        """Rows dp/dphi_2 and dp/dphi_3 of the tilt-induced dipole, in the lab."""
        a1, a2, a3 = self.alphas
        u1, u2, u3 = self.axes[:, 0], self.axes[:, 1], self.axes[:, 2]
        return np.vstack([-(a1 - a3) * E0 * u3,       # d p / d phi_2
                          +(a1 - a2) * E0 * u2])      # d p / d phi_3

    def reduced_inertia(self) -> np.ndarray:
        """2x2 inertia block for (phi_2, phi_3)."""
        return self.inertia_matrix[1:, 1:]

    def librational_frequencies(self, E0: float) -> np.ndarray:
        k = self.trap_stiffness(E0)
        return np.sqrt(k / np.diag(self.reduced_inertia()))


def coupling_block(p1: Particle, p2: Particle, Rvec, k: float, E0: float,
                   C: float = 0.5) -> np.ndarray:
    """2x2 potential-energy coupling kappa_{mu nu} between the two particles.

        kappa_{mu nu} = -C Re[ (dp_1/dphi^mu) . G(R) . (dp_2/dphi^nu) ]

    C = 1/2 is the cycle-averaged (physical) value; C = 1 reproduces the
    convention of arXiv:2504.08194.  See the FACTOR OF TWO note in answer.py.
    """
    G = green_dyadic(Rvec, k)
    D1 = p1.dipole_derivatives(E0)
    D2 = p2.dipole_derivatives(E0)
    return -C * np.real(D1 @ G @ D2.T)


def assemble(p1: Particle, p2: Particle, Rvec, k: float, E0: float,
             C: float = 0.5):
    """Full 4x4 stiffness and inertia matrices in the basis
    (phi_2^{(1)}, phi_3^{(1)}, phi_2^{(2)}, phi_3^{(2)})."""
    K = np.zeros((4, 4))
    K[:2, :2] = np.diag(p1.trap_stiffness(E0))
    K[2:, 2:] = np.diag(p2.trap_stiffness(E0))
    kap = coupling_block(p1, p2, Rvec, k, E0, C)
    K[:2, 2:] = kap
    K[2:, :2] = kap.T
    M = np.zeros((4, 4))
    M[:2, :2] = p1.reduced_inertia()
    M[2:, 2:] = p2.reduced_inertia()
    return K, M


def normal_modes(p1: Particle, p2: Particle, Rvec, k: float, E0: float,
                 C: float = 0.5):
    """Exact normal-mode frequencies (rad/s) of the coupled four-mode problem."""
    K, M = assemble(p1, p2, Rvec, k, E0, C)
    w2, vecs = eigh(K, M)
    return np.sqrt(np.abs(w2)), vecs


def second_quantized(p1: Particle, p2: Particle, Rvec, k: float, E0: float,
                     C: float = 0.5):
    """Local-mode frequencies and the beam-splitter coupling matrix.

        H = sum_{i,mu} hbar w_{i mu} b'b + sum_{mu nu} hbar g_{mu nu}
            (b_{1 mu}' b_{2 nu} + h.c.)

        g_{mu nu} = kappa_{mu nu} / (2 sqrt(I_{1 mu} I_{2 nu} w_{1 mu} w_{2 nu}))

    which reduces to g = kappa/(2 I w_t) for identical particles.
    """
    w1 = p1.librational_frequencies(E0)
    w2 = p2.librational_frequencies(E0)
    I1 = np.diag(p1.reduced_inertia())
    I2 = np.diag(p2.reduced_inertia())
    kap = coupling_block(p1, p2, Rvec, k, E0, C)
    denom = 2.0 * np.sqrt(np.outer(I1 * w1, I2 * w2))
    return w1, w2, kap / denom


# ============================================================================
# 4.  Multipole corrections (centrosymmetric particles)
# ============================================================================
def multipole_coefficients(a: float, b: float, eps_r: float, R: float):
    """C1, C2 of Appendix A of arXiv:2504.08194 for a prolate spheroid,

        C1 = (3/5)  (eps_r-1)  (a^2-b^2)  / [ (1+L(eps_r-1))^2 R^2 ]
        C2 = (9/25) (eps_r-1)^2 (a^2-b^2)^2 / [ (1+L(eps_r-1))^4 R^4 ]

    Both are O((a/R)^2) and O((a/R)^4): for a centrosymmetric particle the
    dipole-quadrupole term vanishes by parity, so the series in a/R is even.
    """
    L_par, _ = answer.depolarization_factors(a, b)
    d = 1.0 + L_par * (eps_r - 1.0)
    C1 = 0.6 * (eps_r - 1.0) * (a ** 2 - b ** 2) / (d ** 2 * R ** 2)
    C2 = 0.36 * (eps_r - 1.0) ** 2 * (a ** 2 - b ** 2) ** 2 / (d ** 4 * R ** 4)
    return C1, C2


# ============================================================================
# 5.  Demonstrations
# ============================================================================
PAR = dict(answer.PAPER_PARAMS)           # a, b, eps_r, rho, w0
LAM = answer.PAPER_LAMBDA
KVEC = 2.0 * math.pi / LAM


def _spheroid_particle(axes, P0=1.0):
    """The challenge's prolate spheroid, as a general `Particle`."""
    a, b, eps_r, rho = PAR["a"], PAR["b"], PAR["eps_r"], PAR["rho"]
    al = alpha_ellipsoid(a, b, b, eps_r)                  # (alpha_par, perp, perp)
    In = inertia_ellipsoid(a, b, b, rho)
    return Particle(alphas=al, inertia=In, axes=axes)


def demo_reduction(P0: float = 1.0, R: float = 1.06e-6, C: float = 1.0):
    """General framework -> the two-ellipsoid answer, to machine precision."""
    E0 = math.sqrt(answer.field_amplitude_squared(P0, PAR["w0"]))
    axes = np.eye(3)                       # body axis 1 -> x = polarisation = R
    p1 = _spheroid_particle(axes)
    p2 = _spheroid_particle(axes)
    Rvec = np.array([R, 0.0, 0.0])

    w1, w2, g = second_quantized(p1, p2, Rvec, KVEC, E0, C)
    w_ref, g_ref = answer.solve(P0=P0, R=R, k=KVEC,
                                convention="paper" if C == 1.0 else
                                "time_averaged", **PAR)

    print("  general framework : w_t/2pi = %.9f MHz (both modes: %.9f)"
          % (w1[0] / 2 / math.pi / 1e6, w1[1] / 2 / math.pi / 1e6))
    print("  answer.py         : w_t/2pi = %.9f MHz" % (w_ref / 2 / math.pi / 1e6))
    print("  general framework : g/2pi   = %+.9f kHz, %+.9f kHz (diagonal)"
          % (g[0, 0] / 2 / math.pi / 1e3, g[1, 1] / 2 / math.pi / 1e3))
    print("  answer.py         : g/2pi   = %+.9f kHz" % (g_ref / 2 / math.pi / 1e3))
    print("  off-diagonal coupling g_23  = %.3e  (zero by symmetry)"
          % abs(g[0, 1]))
    err_w = abs(w1[0] - w_ref) / w_ref
    err_g = max(abs(g[0, 0] - g_ref), abs(g[1, 1] - g_ref)) / abs(g_ref)
    print("  relative error: dw = %.2e, dg = %.2e" % (err_w, err_g))

    w_nm, _ = normal_modes(p1, p2, Rvec, KVEC, E0, C)
    exact = np.array([w_ref * math.sqrt(1.0 + s * 2.0 * g_ref / w_ref)
                      for s in (+1, -1)])
    print("  exact normal modes /2pi (MHz): "
          + ", ".join("%.6f" % (x / 2 / math.pi / 1e6) for x in w_nm)
          + "   (each doubly degenerate)")
    print("  vs w_t sqrt(1 +/- 2g/w_t)    : %.6f, %.6f   [max dev %.1e]"
          % (min(exact) / 2 / math.pi / 1e6, max(exact) / 2 / math.pi / 1e6,
             max(abs(np.sort(w_nm)[::2] - np.sort(exact)))))
    print("  vs the RWA result w_t +/- g  : %.6f, %.6f   [RWA error %.2f kHz,"
          " = g^2/2w_t]"
          % ((w_ref - abs(g_ref)) / 2 / math.pi / 1e6,
             (w_ref + abs(g_ref)) / 2 / math.pi / 1e6,
             g_ref ** 2 / (2 * w_ref) / 2 / math.pi / 1e3))
    return err_w, err_g


def demo_paper_geometry(P0: float = 1.0, R: float = 1.06e-6, C: float = 1.0):
    """Polarisation perpendicular to R: the two librations decouple but acquire
    *different* couplings, one longitudinal (G_par) and one transverse (G_perp)."""
    E0 = math.sqrt(answer.field_amplitude_squared(P0, PAR["w0"]))
    # body axis 1 -> y (polarisation); u_2 -> z, u_3 -> x, right handed
    axes = np.array([[0.0, 0.0, 1.0],
                     [1.0, 0.0, 0.0],
                     [0.0, 1.0, 0.0]])
    p1 = _spheroid_particle(axes)
    p2 = _spheroid_particle(axes)
    Rvec = np.array([R, 0.0, 0.0])
    w1, w2, g = second_quantized(p1, p2, Rvec, KVEC, E0, C)
    d_alpha = answer.polarizability_anisotropy(PAR["a"], PAR["b"], PAR["eps_r"])
    I = answer.moment_of_inertia(PAR["a"], PAR["b"], PAR["rho"])
    print("  tilt in the R-polarisation plane (longitudinal, G_par):"
          "  g/2pi = %+9.3f kHz" % (g[0, 0] / 2 / math.pi / 1e3))
    print("  tilt out of that plane          (transverse,  G_perp): "
          " g/2pi = %+9.3f kHz" % (g[1, 1] / 2 / math.pi / 1e3))
    print("  analytic check: -C d_alpha^2 E0^2 Re G_par /(2 I w) = %+9.3f kHz"
          % (-C * d_alpha ** 2 * E0 ** 2 * G_par(R, KVEC).real
             / (2 * I * w1[0]) / 2 / math.pi / 1e3))
    print("  ratio g_par/g_perp = %.4f = Re G_par / Re G_perp = %.4f"
          % (g[0, 0] / g[1, 1], G_par(R, KVEC).real / G_perp(R, KVEC).real))
    print("  far-field scaling: G_par ~ 1/R^2 (short ranged), G_perp ~ 1/R")


def demo_equivalent_ellipsoid():
    """Arbitrary alpha tensor -> the unique ellipsoid that reproduces it."""
    eps_r = PAR["eps_r"]
    a, b, c = 300e-9, 220e-9, 150e-9                    # a triaxial test shape
    al = alpha_ellipsoid(a, b, c, eps_r)
    a2, b2, c2 = equivalent_ellipsoid(al, eps_r)
    print("  input  semi-axes (nm): %.3f, %.3f, %.3f" % (a * 1e9, b * 1e9, c * 1e9))
    print("  alpha tensor (1e-31) : %.6f, %.6f, %.6f" % tuple(al * 1e31))
    print("  recovered axes  (nm) : %.3f, %.3f, %.3f" % (a2 * 1e9, b2 * 1e9, c2 * 1e9))
    print("  round-trip error     : %.2e"
          % (max(abs(a2 - a), abs(b2 - b), abs(c2 - c)) / a))
    # a genuinely non-ellipsoidal alpha, e.g. from a measured / simulated shape
    al_arb = np.array([9.0e-31, 6.4e-31, 5.0e-31])
    ea, eb, ec = equivalent_ellipsoid(al_arb, eps_r)
    print("  arbitrary alpha (1e-31) %.2f, %.2f, %.2f -> ellipsoid (nm) "
          "%.1f, %.1f, %.1f" % (*(al_arb * 1e31), ea * 1e9, eb * 1e9, ec * 1e9))
    print("  check: alpha of that ellipsoid (1e-31) = %.4f, %.4f, %.4f"
          % tuple(alpha_ellipsoid(ea, eb, ec, eps_r) * 1e31))


def demo_triaxial(P0: float = 1.0, R: float = 1.06e-6, C: float = 1.0):
    """A fully anisotropic particle: two non-degenerate librations per particle."""
    eps_r, rho = PAR["eps_r"], PAR["rho"]
    a, b, c = 300e-9, 220e-9, 150e-9
    al = alpha_ellipsoid(a, b, c, eps_r)
    In = inertia_ellipsoid(a, b, c, rho)
    E0 = math.sqrt(answer.field_amplitude_squared(P0, PAR["w0"]))
    p1 = Particle(alphas=al, inertia=In)
    p2 = Particle(alphas=al, inertia=In)
    Rvec = np.array([R, 0.0, 0.0])
    w1, w2, g = second_quantized(p1, p2, Rvec, KVEC, E0, C)
    print("  alpha (1e-31)          : %.4f, %.4f, %.4f" % tuple(al * 1e31))
    print("  inertia (1e-30 kg m^2) : %.4f, %.4f, %.4f" % tuple(In * 1e30))
    print("  librational freqs /2pi : %.4f MHz (phi_2), %.4f MHz (phi_3)"
          % (w1[0] / 2 / math.pi / 1e6, w1[1] / 2 / math.pi / 1e6))
    print("  couplings /2pi         : g_22 = %+8.3f kHz, g_33 = %+8.3f kHz, "
          "g_23 = %.1e" % (g[0, 0] / 2 / math.pi / 1e3,
                           g[1, 1] / 2 / math.pi / 1e3, g[0, 1]))
    print("  (the two modes are non-degenerate, so the pair of beam-splitter")
    print("   couplings is resolved in frequency; g_23 vanishes because both")
    print("   transverse directions are perpendicular to R)")


def demo_multipole():
    """Size of the leading multipole corrections for the benchmark particle."""
    a, b, eps_r = PAR["a"], PAR["b"], PAR["eps_r"]
    print("  R/lambda   C1 (this work)   C2 (this work)")
    for Rl in (0.95, 1.0, 1.5, 2.0):
        C1, C2 = multipole_coefficients(a, b, eps_r, Rl * LAM)
        print("  %6.2f     %12.5f    %12.6f" % (Rl, C1, C2))
    C1, C2 = multipole_coefficients(a, b, eps_r, LAM)
    print("  at R = lambda: this work C1 = %.4f, C2 = %.5f;  "
          "Ref. App. A quotes 0.0252 / 0.0006;  their Zenodo header says "
          "0.033 / 0.012" % (C1, C2))
    print("  -> the published multipole coefficients are mutually inconsistent;")
    print("     all three are nonetheless <= a few percent, i.e. far too small")
    print("     to explain the constant factor 1.334977 found in answer.py.")


if __name__ == "__main__":
    np.set_printoptions(precision=6, suppress=False)
    print(__doc__.split("Run `py")[0].strip()[:0] or "", end="")

    print("=" * 78)
    print("1.  REDUCTION TEST: general framework  ->  challenges/20/answer.py")
    print("=" * 78)
    ew, eg = demo_reduction()
    print()

    print("=" * 78)
    print("2.  SAME PARTICLES, POLARISATION PERPENDICULAR TO R (arXiv:2504.08194)")
    print("=" * 78)
    demo_paper_geometry()
    print()

    print("=" * 78)
    print("3.  EQUIVALENT ELLIPSOID: arbitrary alpha tensor -> unique ellipsoid")
    print("=" * 78)
    demo_equivalent_ellipsoid()
    print()

    print("=" * 78)
    print("4.  FULLY ANISOTROPIC PARTICLES: two librations per particle")
    print("=" * 78)
    demo_triaxial()
    print()

    print("=" * 78)
    print("5.  MULTIPOLE CORRECTIONS (centrosymmetric: even powers of a/R)")
    print("=" * 78)
    demo_multipole()
    print()

    assert ew < 1e-12 and eg < 1e-12, "reduction to answer.py failed"
    print("REDUCTION VERIFIED: the general treatment reproduces answer.py to "
          "%.0e relative." % max(ew, eg))
