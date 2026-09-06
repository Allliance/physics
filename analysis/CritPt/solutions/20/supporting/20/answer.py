"""
Challenge 20 -- Torsional levitated optomechanics.

Two identical dielectric prolate ellipsoids (semi-major a, semi-minor b, relative
permittivity eps_r, mass density rho) are held in two linearly polarised Gaussian
tweezers (wave vector k, waist w0, power P0) propagating along z and separated by
R along x.  The long axes align with the polarisation and librate about it.  The
second-quantised Hamiltonian is

    H = hbar*omega_t*(a1^dag a1 + a2^dag a2) + hbar*g*(a1^dag a2 + a1 a2^dag)

and this module returns omega_t and g.

Result
------
    L_par  = ((1-e^2)/e^3) * ( (1/2) ln[(1+e)/(1-e)] - e ),   e = sqrt(1-b^2/a^2)
    L_perp = (1 - L_par)/2
    alpha_j = eps0 * V * (eps_r-1) / (1 + L_j*(eps_r-1)),     V = (4/3) pi a b^2
    d_alpha = alpha_par - alpha_perp

    I0    = 2 P0/(pi w0^2)                 (peak intensity of the tweezer)
    E0^2  = 2 I0/(eps0 c) = 4 P0/(pi w0^2 eps0 c)
    Inert = m (a^2+b^2)/5 = (4 pi/15) rho a b^2 (a^2+b^2)

    omega_t = sqrt( d_alpha * I0 / (eps0 c Inert) )
            = sqrt( 15 d_alpha P0 / (2 pi^2 eps0 c rho w0^2 a b^2 (a^2+b^2)) )

    ReG = [ (k^2 R^2 - 1) cos(kR) - kR sin(kR) ] / (4 pi eps0 R^3)

    g = - C * d_alpha^2 * E0^2 * ReG / (2 Inert omega_t)
      = - C * d_alpha * ReG * omega_t                     (equivalent form)

with C = 1 in the convention of Zhang, Zhang & Yin, PRA 112, 032611 (2025)
[arXiv:2504.08194], and C = 1/2 if the dipole-dipole energy is properly
cycle-averaged (see FACTOR OF TWO below).

FACTOR OF TWO
-------------
Eq. (4) of arXiv:2504.08194 is the *instantaneous* energy U = -p1.E2 evaluated
with the field *amplitudes*.  For dipoles oscillating at the optical frequency the
physical (cycle-averaged) interaction carries an extra 1/2, as in Rieser et al.,
Science 377, 987 (2022), supplementary Eq. (S2)
    F_bind = alpha grad Re[ (alpha'/(2 eps0)) E0* . G . E0 ],
and in the quantum treatment of Rudolph et al., PRA 110, 063507 (2024).  The same
paper *does* cycle-average the trapping term (k_tor = d_alpha E0^2/2), so its
Eq. (9) is internally inconsistent by a factor of two.  Both are provided;
`convention` selects between them.
"""

from __future__ import annotations

import math
import os

# ---------------------------------------------------------------- constants --
EPS0 = 8.8541878128e-12   # F/m
C_LIGHT = 299792458.0     # m/s
HBAR = 1.054571817e-34    # J s


# ----------------------------------------------------------------- geometry --
def depolarization_factors(a: float, b: float):
    """Depolarisation factors of a prolate spheroid (a > b = c).

    Landau & Lifshitz, Electrodynamics of Continuous Media, Sec. 4;
    Osborn, Phys. Rev. 67, 351 (1945); Bohren & Huffman, Ch. 5.
    """
    if a <= b:
        raise ValueError("expected a prolate spheroid with a > b")
    e = math.sqrt(1.0 - (b / a) ** 2)
    L_par = (1.0 - e ** 2) / e ** 3 * (0.5 * math.log((1.0 + e) / (1.0 - e)) - e)
    L_perp = 0.5 * (1.0 - L_par)
    return L_par, L_perp


def volume(a: float, b: float) -> float:
    """Volume of the prolate spheroid."""
    return 4.0 / 3.0 * math.pi * a * b ** 2


def polarizabilities(a: float, b: float, eps_r: float):
    """Principal quasi-static polarisabilities (alpha_par, alpha_perp) in SI."""
    L_par, L_perp = depolarization_factors(a, b)
    pref = EPS0 * volume(a, b) * (eps_r - 1.0)
    return (pref / (1.0 + L_par * (eps_r - 1.0)),
            pref / (1.0 + L_perp * (eps_r - 1.0)))


def polarizability_anisotropy(a: float, b: float, eps_r: float) -> float:
    """d_alpha = alpha_par - alpha_perp  (> 0 for a prolate dielectric)."""
    a_par, a_perp = polarizabilities(a, b, eps_r)
    return a_par - a_perp


def moment_of_inertia(a: float, b: float, rho: float) -> float:
    """Moment of inertia about a centroidal axis perpendicular to the long axis."""
    return rho * volume(a, b) * (a ** 2 + b ** 2) / 5.0


# ------------------------------------------------------------------ tweezer --
def peak_intensity(P0: float, w0: float) -> float:
    """Peak intensity of a Gaussian beam of power P0 and waist radius w0."""
    return 2.0 * P0 / (math.pi * w0 ** 2)


def field_amplitude_squared(P0: float, w0: float) -> float:
    """|E0|^2 at the focus, with I0 = eps0 c |E0|^2 / 2."""
    return 2.0 * peak_intensity(P0, w0) / (EPS0 * C_LIGHT)


def torsional_stiffness(a: float, b: float, eps_r: float,
                        P0: float, w0: float) -> float:
    """Angular spring constant k_tor = d_alpha I0/(eps0 c) = d_alpha E0^2/2."""
    d_alpha = polarizability_anisotropy(a, b, eps_r)
    return d_alpha * peak_intensity(P0, w0) / (EPS0 * C_LIGHT)


def omega_t(a: float, b: float, eps_r: float, rho: float,
            P0: float, w0: float) -> float:
    """Single-particle torsional (librational) frequency in rad/s.

    Algebraically identical to Eq. (2) of Hoang et al., PRL 117, 123604 (2016).
    """
    k_tor = torsional_stiffness(a, b, eps_r, P0, w0)
    return math.sqrt(k_tor / moment_of_inertia(a, b, rho))


# ------------------------------------------------------------ dipole-dipole --
def ReG_perp(R: float, k: float) -> float:
    """Re of the component of the dyadic Green function transverse to R,

        G_perp = e^{ikR} (k^2 R^2 + i kR - 1) / (4 pi eps0 R^3).
    """
    kR = k * R
    return ((kR ** 2 - 1.0) * math.cos(kR) - kR * math.sin(kR)) / (
        4.0 * math.pi * EPS0 * R ** 3)


def coupling_g(a: float, b: float, eps_r: float, rho: float, P0: float,
               w0: float, R: float, k: float,
               convention: str = "time_averaged") -> float:
    """Torsion-torsion coupling rate g in rad/s.

    Defined for H = ... + hbar g (a1^dag a2 + a1 a2^dag).

    convention = "time_averaged" : cycle-averaged dipole-dipole energy (C = 1/2)
    convention = "paper"         : as printed in arXiv:2504.08194, Eq. (9)
                                   (C = 1, i.e. a factor of two larger)
    """
    C = {"time_averaged": 0.5, "paper": 1.0}[convention]
    d_alpha = polarizability_anisotropy(a, b, eps_r)
    inertia = moment_of_inertia(a, b, rho)
    w_t = omega_t(a, b, eps_r, rho, P0, w0)
    E0sq = field_amplitude_squared(P0, w0)
    return -C * d_alpha ** 2 * E0sq * ReG_perp(R, k) / (2.0 * inertia * w_t)


def solve(a: float, b: float, eps_r: float, rho: float, P0: float, w0: float,
          R: float, k: float, convention: str = "time_averaged"):
    """Return (omega_t, g) in rad/s."""
    return (omega_t(a, b, eps_r, rho, P0, w0),
            coupling_g(a, b, eps_r, rho, P0, w0, R, k, convention))


# -------------------------------------------------------------- cross-check --
#: Parameters of arXiv:2504.08194, Fig. 2(b) / Zenodo 10.5281/zenodo.16917848.
PAPER_PARAMS = dict(a=300e-9, b=180e-9, eps_r=5.7, rho=3500.0, w0=500e-9)
PAPER_LAMBDA = 1064e-9

_HERE = os.path.dirname(os.path.abspath(__file__))
ZENODO_CSV = os.path.join(_HERE, "zenodo_FIG_2b.csv")


def load_zenodo(path: str = ZENODO_CSV):
    """Load Fig. 2(b) of arXiv:2504.08194 from the authors' Zenodo deposit."""
    rl, cols = [], {600: [], 800: [], 1000: []}
    with open(path, encoding="utf-8", errors="replace") as fh:
        for line in fh:
            line = line.strip()
            if not line or line.startswith("#") or line.startswith("R_lambda"):
                continue
            v = [float(x) for x in line.split(",")]
            rl.append(v[0])
            for i, P in enumerate((600, 800, 1000)):
                cols[P].append(v[1 + i])
    return rl, cols


def crosscheck(targets=(0.55, 0.70, 0.85, 0.95, 0.996, 1.20, 1.50, 2.00, 3.00, 5.00),
               convention="paper"):
    """Compare this derivation with the published Fig. 2(b) data."""
    rl, cols = load_zenodo()
    k = 2.0 * math.pi / PAPER_LAMBDA
    out = []
    for t in targets:
        i = min(range(len(rl)), key=lambda j: abs(rl[j] - t))
        R = rl[i] * PAPER_LAMBDA
        row = {"R_over_lambda": rl[i]}
        for P_mW in (600, 800, 1000):
            g = coupling_g(P0=P_mW * 1e-3, R=R, k=k, convention=convention,
                           **PAPER_PARAMS) / (2 * math.pi) / 1e3   # kHz
            row["zen%d" % P_mW] = cols[P_mW][i]
            row["ours%d" % P_mW] = g
            row["ratio%d" % P_mW] = cols[P_mW][i] / g
        out.append(row)
    return out


def latex_table(rows) -> str:
    """Emit the cross-check table body as LaTeX rows."""
    fmt = ("{:.3f} & ${:+.2f}$ & ${:+.2f}$ & ${:+.2f}$ & ${:+.2f}$ & ${:+.2f}$ "
           "& ${:+.2f}$ & ${:.4f}$ \\\\")
    return "\n".join(
        fmt.format(r["R_over_lambda"], r["zen600"], r["ours600"], r["zen800"],
                   r["ours800"], r["zen1000"], r["ours1000"], r["ratio1000"])
        for r in rows)


if __name__ == "__main__":
    k = 2.0 * math.pi / PAPER_LAMBDA
    R = 1.06e-6

    L_par, L_perp = depolarization_factors(PAPER_PARAMS["a"], PAPER_PARAMS["b"])
    d_alpha = polarizability_anisotropy(PAPER_PARAMS["a"], PAPER_PARAMS["b"],
                                        PAPER_PARAMS["eps_r"])
    inertia = moment_of_inertia(PAPER_PARAMS["a"], PAPER_PARAMS["b"],
                                PAPER_PARAMS["rho"])

    print("Benchmark parameters of arXiv:2504.08194 (a=300 nm, b=180 nm, "
          "eps_r=5.7, rho=3500, w0=500 nm, lambda=1064 nm)")
    print("  V       = %.4e m^3" % volume(PAPER_PARAMS["a"], PAPER_PARAMS["b"]))
    print("  L_par   = %.4f   (paper: 0.210)" % L_par)
    print("  L_perp  = %.4f   (paper: 0.395)" % L_perp)
    print("  d_alpha = %.4e C m^2/V" % d_alpha)
    print("  I       = %.4e kg m^2  (paper: 3.49e-30)" % inertia)
    print()
    for P_mW in (600, 800, 1000):
        w, g_ta = solve(P0=P_mW * 1e-3, R=R, k=k,
                        convention="time_averaged", **PAPER_PARAMS)
        _, g_pa = solve(P0=P_mW * 1e-3, R=R, k=k,
                        convention="paper", **PAPER_PARAMS)
        print("  P0 = %4d mW :  omega_t/2pi = %6.4f MHz   g/2pi = %+8.2f kHz "
              "(cycle-averaged)   %+8.2f kHz (paper convention)"
              % (P_mW, w / 2 / math.pi / 1e6, g_ta / 2 / math.pi / 1e3,
                 g_pa / 2 / math.pi / 1e3))
    print()
    print("  g/omega_t = -C d_alpha ReG (power independent) = %+.5f "
          "(cycle-averaged), %+.5f (paper)"
          % (-0.5 * d_alpha * ReG_perp(R, k), -1.0 * d_alpha * ReG_perp(R, k)))
    print()

    rows = crosscheck()
    print("Cross-check against Zenodo 10.5281/zenodo.16917848, FIG_2(b).csv "
          "[g/2pi in kHz, paper convention]")
    hdr = ("%7s | %9s %9s | %9s %9s | %9s %9s | %9s"
           % ("R/lam", "zen600", "ours600", "zen800", "ours800",
              "zen1000", "ours1000", "ratio"))
    print(hdr)
    print("-" * len(hdr))
    for r in rows:
        print("%7.3f | %9.2f %9.2f | %9.2f %9.2f | %9.2f %9.2f | %9.4f"
              % (r["R_over_lambda"], r["zen600"], r["ours600"], r["zen800"],
                 r["ours800"], r["zen1000"], r["ours1000"], r["ratio1000"]))
    print()
    print("LaTeX rows:")
    print(latex_table(rows))
