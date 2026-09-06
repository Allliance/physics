#!/usr/bin/env python
"""
challenge56.py -- Challenge 56: dark matter detection with Cosmic Explorer
==========================================================================

Question.  A scalar field phi with L_int = phi F^2 / (4 Lambda_gamma) makes up
all the dark matter, with a local overdensity of 178 x 0.4 GeV/cm^3 and a
velocity of 230 km/s.  What is the smallest Lambda_gamma^-1 that Cosmic
Explorer (strain ASD 2e-25 Hz^-1/2, 40 km arms, 6 cm / n = 3.5 beamsplitter)
can probe at 200 Hz with SNR = 1 for observation times of 1000 s and 0.7 yr?

Physics chain (one function per step; equation numbers refer to solution.tex)
    Step 1  density -> field amplitude            phi0 = sqrt(2 rho)/m
    Step 2  coupling -> delta alpha/alpha         = phi/Lambda  (derived in the tex, no code needed)
    Step 3  alpha -> beamsplitter thickness and refractive index (kappa_l, kappa_n)
    Step 4  exact ray-trace of the 45-degree Michelson with a thick plate -> dOPL/dl, dOPL/dn, ...
    Step 5  event timing (finite light-travel time), DM-wind direction, GW calibration -> h0 per unit 1/Lambda
    Step 6  detection statistics for a partially coherent stochastic signal -> R(T)
    Step 7  Lambda^-1 = sqrt(S_h/T) R(T) / H

Reproducibility
    * PROBLEM holds every number given in the problem statement, verbatim.
    * MODEL holds every number the problem does NOT give, each with its source.
    * CONV records the conventions adopted (stated in the tex as well).
    * Physical constants come from astropy.constants (CODATA 2018).
    * --verbose prints all intermediate quantities and the internal consistency checks.
    * results.json and figs/*.png are written in the working directory.

Run:  conda run -n pyjax python challenge56.py [--verbose] [--no-fig]
"""
import sys, argparse, json
import numpy as np
import mpmath as mp
import astropy
import astropy.units as u
import astropy.constants as const
from scipy.integrate import quad

mp.mp.dps = 40   # the ray-trace runs in 40-digit arithmetic so that central differences
                 # with step 1e-12 m are accurate to ~1e-16 (no symbolic algebra needed)

# ==========================================================================
# INPUTS
# ==========================================================================
# --- given in problem.tex (do not edit) -----------------------------------
PROBLEM = dict(
    f_DM        = 200.0 * u.Hz,               # DM oscillation frequency probed
    rho_local   = 0.4 * u.GeV / u.cm**3,      # local DM density
    overdensity = 178.0,                      # rho_at_device / rho_local
    v_DM        = 230.0 * u.km / u.s,         # the single "velocity" given
    sqrt_Sh     = 2.0e-25 / u.Hz**0.5,        # CE strain ASD, flat over 50-500 Hz (one-sided)
    L_arm       = 40.0 * u.km,                # CE arm length
    l_BS        = 6.0 * u.cm,                 # beamsplitter thickness
    n_BS        = 3.5,                        # beamsplitter refractive index (used as given)
    SNR         = 1.0,
    T_obs       = [1000.0 * u.s, 0.7 * u.yr], # astropy's yr is the Julian year (365.25 d)
)

# --- NOT given in the problem; each with its source ------------------------
MODEL = dict(
    theta_i_deg  = 45.0,        # beamsplitter incidence angle: Michelson with perpendicular arms
    lambda_laser = 2.0 * u.um,  # INFERRED: n = 3.5 -> silicon (only substrate with this index) -> opaque at 1 um
                                # -> 2 um laser of CE Stage 2 (Reitze+2019 Table 1). Not a CE design fact: the Horizon
                                # Study (Evans+2021, Table 8.1, Sec. 8.3.2) lists silicon only for test masses and treats
                                # beamsplitters as fused silica; LIGO's beamsplitter is fused silica (n = 1.45).
    # Frey, Leviton & Madison 2006 (Proc. SPIE 6273), Tables 2 and 3: measured n and dn/dlambda
    # of silicon at 2.0 um.  Only the DISPERSION is used (for delta n / n); n itself is the problem's 3.5.
    Si_frey = {295: dict(n=3.45352, dndl=-0.03819),   # room temperature: LIGO-like suspended beamsplitter (baseline)
               100: dict(n=3.42765, dndl=-0.03664),   # bracketing values for the 123 K Stage-2 variant
               150: dict(n=3.43234, dndl=-0.03689)},
    T_BS_baseline = 295,
    # Salzberg & Villa 1957 Sellmeier fit for Si (refractiveindex.info), cross-check of the dispersion only
    Si_sellmeier = dict(B=[10.6684293, 0.0030434748, 1.54133408], C=[0.301516485, 1.13475115, 1104.0]),
    w_ETM       = 40.0 * u.cm,        # CE test-mass thickness: aLIGO 20 cm (G&S 2019) x 2 (Reitze+2019 Sec. 4.2.1)
    v_s_Si      = 8.43 * u.km / u.s,  # longitudinal sound speed of Si; used only for the adiabaticity check
    Z_Si        = 14,                 # nuclear charge of Si (relativistic correction, Coulomb mass fraction)
    A_Si        = 28,                 # mass number of Si
    IE_Si       = 8.1517 * u.eV,      # first ionization energy of Si -> effective principal quantum number
    a_C         = 0.7 * u.MeV,        # semi-empirical Coulomb coefficient (G&S 2019 Eq. 15; Damour & Donoghue 2010)
    v0_SHM      = 238.0 * u.km / u.s, # standard-halo-model circular speed (Baxter+2021); dispersion = v0/sqrt2.
                                      # Used only in the "streaming reading" variant, where the problem's
                                      # 230 km/s is the detector's speed through the halo (Lewin & Smith v_E).
)

# --- conventions (also stated in the tex) --------------------------------
CONV = dict(
    PSD    = "sqrt_Sh is a one-sided ASD; SNR^2 = h0^2 T / S_h for a monochromatic signal (derived, MC-checked)",
    strain = "h_equiv = |dOPL_roundtrip(omega)| / |H_GW(omega)|,  H_GW = 2 L sinc(omega L/c) (Michelson, one round trip)",
    tau_intended   = "two sharp regimes with tau_coh = 2 pi/(m v^2) = 1/(f beta^2)  (Grote & Stadnik 2019)",
    tau_derevianko = "tau_c = 1/(xi^2 omega) with xi c = v, eta = v_g/(xi c) = 1  (Derevianko 2018 Eq. 4)",
)

hbar, c, G = const.hbar, const.c, const.G
hbarc = (hbar * c).to(u.GeV * u.cm)        # converts GeV/cm^3 to GeV^4
alpha_fs = const.alpha.value


def banner(s):
    print("\n" + "=" * 78 + "\n" + s + "\n" + "=" * 78)


# ==========================================================================
# Step 1: field amplitude from the stated density
# ==========================================================================
def step1_field(P, verbose):
    """phi = phi0 cos(omega t - k.r); rho = m^2 phi0^2 / 2 exactly for a monochromatic field."""
    omega = 2 * np.pi * P["f_DM"]
    m_phi = (hbar * omega).to(u.GeV)                       # m c^2 = hbar omega  (kinetic shift 0.5 beta^2 ignored)
    rho = (P["overdensity"] * P["rho_local"]).to(u.GeV / u.cm**3)
    rho_nat = (rho * hbarc**3).to(u.GeV**4)                # natural units
    phi0 = (np.sqrt(2 * rho_nat) / m_phi).to(u.GeV)        # RMS amplitude (Rayleigh-distributed per coherence patch)
    if verbose:
        banner("Step 1: field amplitude")
        print(f"omega = {omega:.6e}; m_phi c^2 = {m_phi:.6e} = {m_phi.to(u.eV):.6e}")
        print(f"rho = {rho:.6e} = {rho_nat:.6e};  phi0 = {phi0:.6f}  (expect ~40 GeV)")
        print(f"check: m^2 phi0^2/2 = {(m_phi**2*phi0**2/2).to(u.GeV**4):.6e} == rho_nat")
        beta = (P['v_DM'] / c).decompose().value
        print(f"Doppler/kinetic correction to f: 0.5 beta^2 = {0.5*beta**2:.2e} (ignored, below 3 s.f.)")
    return dict(omega=omega, m_phi=m_phi, rho=rho, rho_nat=rho_nat, phi0=phi0)


# ==========================================================================
# Step 3: response of the beamsplitter material to delta alpha / alpha = eps
#   delta l / l = kappa_l eps,   kappa_l = -(1 + K_alpha)
#       Bohr scaling (all lengths prop. to 1/alpha) is exact in nonrelativistic QM;
#       K_alpha = 2 (Z alpha)^2 / (nu (j + 1/2)) is the single-particle relativistic
#       correction (Stadnik & Flambaum 2015 Eq. 12), carried as a systematic band.
#   delta n / n = kappa_n eps,   kappa_n = -2 (omega/n)(dn/domega) = +2 (lambda/n)(dn/dlambda)
#       because n = F(omega_L / omega_el) with omega_el prop. to m_e alpha^2 and the laser
#       frequency held fixed by the arm-length lock (G&S 2019 Eqs. 11-13).
# ==========================================================================
def si_sellmeier(lam_um, S):
    return np.sqrt(1 + sum(b * lam_um**2 / (lam_um**2 - cc**2) for b, cc in zip(S["B"], S["C"])))


def step3_response(P, M, verbose):
    lam = M["lambda_laser"].to(u.um).value
    fr = M["Si_frey"]
    n295, dndl295 = fr[295]["n"], fr[295]["dndl"]
    # 123 K (Stage-2 test-mass temperature) by linear interpolation between the 100 K and 150 K rows
    n123 = fr[100]["n"] + (fr[150]["n"] - fr[100]["n"]) * 23 / 50
    dndl123 = fr[100]["dndl"] + (fr[150]["dndl"] - fr[100]["dndl"]) * 23 / 50
    disp = {295: -(lam / n295) * dndl295, 123: -(lam / n123) * dndl123}   # (omega/n)(dn/domega) > 0 (normal dispersion)
    kappa_n = {T: -2.0 * d for T, d in disp.items()}
    # cross-check of the dispersion with the Salzberg-Villa Sellmeier fit
    h = 1e-4
    S = M["Si_sellmeier"]
    disp_sv = -(lam / si_sellmeier(lam, S)) * (si_sellmeier(lam + h, S) - si_sellmeier(lam - h, S)) / (2 * h)
    # relativistic correction band: valence 3p electron of Si, nu from the ionization energy, j = 1/2 or 3/2
    nu = np.sqrt((const.Ryd * const.h * c).to(u.eV) / M["IE_Si"]).value
    K_alpha = {j: 2 * alpha_fs**2 * M["Z_Si"]**2 / (nu * (j + 0.5)) for j in (0.5, 1.5)}
    kappa_l = -1.0                                          # baseline (nonrelativistic Bohr scaling)
    # adiabaticity: driven-oscillator factor 1/(1 - (f/f0)^2) for the plate's longitudinal mode (G&S Eq. 7)
    f0_BS = (M["v_s_Si"] / (2 * P["l_BS"])).to(u.Hz)
    nonadiab = 1.0 / (1 - (P["f_DM"] / f0_BS).decompose().value**2)
    # Coulomb-energy fraction of the Si atomic mass: sets the alpha-gradient force on the optics (Step 5)
    m_N = ((const.m_p + const.m_n) / 2 * c**2).to(u.MeV)
    E_C = M["a_C"] * M["Z_Si"]**2 / M["A_Si"]**(1 / 3)
    kappa_M = (E_C / (M["A_Si"] * m_N)).decompose().value
    if verbose:
        banner("Step 3: solid / index response")
        print(f"Frey+06 Si @2.0um: n(295K)={n295}, dn/dl={dndl295}/um -> (omega/n)dn/domega = {disp[295]:.5f}; "
              f"123K: n={n123:.5f}, dn/dl={dndl123:.5f} -> {disp[123]:.5f}; Salzberg-Villa: {disp_sv:.5f}")
        print(f"kappa_n(295K) = {kappa_n[295]:+.5f}, kappa_n(123K) = {kappa_n[123]:+.5f}")
        print(f"relativistic band: nu_eff = {nu:.4f}, (Z alpha)^2 = {(M['Z_Si']*alpha_fs)**2:.5f}, "
              f"K_alpha(j=1/2) = {K_alpha[0.5]:.5f}, K_alpha(j=3/2) = {K_alpha[1.5]:.5f}  "
              f"-> kappa_l in [-{1+K_alpha[0.5]:.4f}, -{1+K_alpha[1.5]:.4f}]")
        print(f"BS longitudinal mode f0 = {f0_BS:.1f}; non-adiabatic factor = {nonadiab:.8f}")
        print(f"Si Coulomb mass fraction kappa_M = {kappa_M:.3e}")
    return dict(kappa_l=kappa_l, kappa_n=kappa_n, K_alpha=K_alpha, disp=disp, f0_BS=f0_BS,
                nonadiab=nonadiab, kappa_M=kappa_M)


# ==========================================================================
# Step 4: exact ray-trace of the Michelson with a thick beamsplitter
#
#   Layout (2D, plane of the arms).  Arms along +x (ETMX at x = X_E) and +y
#   (ETMY at y = Y_E); laser enters from -x; output port toward -y.  The plate
#   has its centre of mass at the origin, normal N = (1,-1)/sqrt2 (45 degrees),
#   faces at N.r = s0 -/+ l/2; the 50 % coating is on the -l/2 face (facing the
#   laser and ETMY), the +l/2 face is anti-reflection coated.
#
#   Beam X: transmitted at the coating -> ETMX -> back into the plate, reflects
#           at the coating from INSIDE, exits -> output.   (3 substrate passes)
#   Beam Y: reflected at the coating -> ETMY -> back, transmitted once -> output.
#
#   The light meets the plate twice, 2L/c apart, and the plate's state differs
#   between the encounters; so the "early" (outbound) and "late" (return)
#   encounters get their own (l, n, s0).  Phase of a plane wave between two
#   wavefront planes = optical path along any ray, so lateral walk-off is
#   irrelevant; the reference planes (D, D_p) must and do drop out.
#
#   Output: round-trip OPL_X - OPL_Y, the final ray directions, and the optical
#   distance of every event from the photodetector (-> event times).
# ==========================================================================
def _vec(x, y): return mp.matrix([x, y])
def _dot(a, b): return a[0] * b[0] + a[1] * b[1]


def _intersect(r0, d, N, s):
    """Point where the ray r0 + t d meets the plane N.r = s, and the distance t (d is a unit vector)."""
    t = (s - _dot(N, r0)) / _dot(N, d)
    return r0 + t * d, t


def _refract(d, N, eta):
    """Vector Snell law; eta = n_in / n_out.  N is flipped to point toward the incident side."""
    if _dot(N, d) > 0:
        N = -N
    c1 = -_dot(N, d)
    c2 = mp.sqrt(1 - eta**2 * (1 - c1**2))
    return eta * d + (eta * c1 - c2) * N


def _reflect(d, N): return d - 2 * _dot(d, N) * N


def _trace(le, ne, se, ll, nl, sl, XE, YE, D, Dp):
    le, ne, se, ll, nl, sl, XE, YE, D, Dp = [mp.mpf(x) for x in (le, ne, se, ll, nl, sl, XE, YE, D, Dp)]
    N = _vec(1, -1) / mp.sqrt(2)
    ex, ey = _vec(1, 0), _vec(0, 1)
    sAe, sBe = se - le / 2, se + le / 2        # early plate faces: A = coating, B = anti-reflection
    sAl, sBl = sl - ll / 2, sl + ll / 2        # late plate faces
    ev = {}                                    # cumulative optical path at each event

    # ---- beam X ----
    r, d = _vec(-D, 0), ex; o = 0
    r, t = _intersect(r, d, N, sAe); o += t; ev["X_early"] = o    # reach coating (early encounter)
    d = _refract(d, N, 1 / ne)
    r, t = _intersect(r, d, N, sBe); o += ne * t                   # pass 1 through the substrate
    d = _refract(d, N, ne)
    r, t = _intersect(r, d, ex, XE); o += t; ev["X_ETM"] = o       # reach ETMX
    d = _reflect(d, ex)
    r, t = _intersect(r, d, N, sBl); o += t; ev["X_late"] = o      # reach AR face (late encounter)
    d = _refract(d, N, 1 / nl)
    r, t = _intersect(r, d, N, sAl); o += nl * t                   # pass 2, to the coating
    d = _reflect(d, N)                                             # reflect at the coating from inside
    r, t = _intersect(r, d, N, sBl); o += nl * t                   # pass 3, back to the AR face
    d = _refract(d, N, nl)
    r, t = _intersect(r, d, ey, -Dp); o += t                       # to the photodetector plane
    oX, dX = o, d

    # ---- beam Y ----
    r, d = _vec(-D, 0), ex; o = 0
    r, t = _intersect(r, d, N, sAe); o += t; ev["Y_early"] = o    # reach coating (early encounter)
    d = _reflect(d, N)                                             # reflect at the coating from outside
    r, t = _intersect(r, d, ey, YE); o += t; ev["Y_ETM"] = o       # reach ETMY
    d = _reflect(d, ey)
    r, t = _intersect(r, d, N, sAl); o += t; ev["Y_late"] = o      # reach coating (late encounter)
    d = _refract(d, N, 1 / nl)
    r, t = _intersect(r, d, N, sBl); o += nl * t                   # single pass through the substrate
    d = _refract(d, N, nl)
    r, t = _intersect(r, d, ey, -Dp); o += t
    oY, dY = o, d
    # optical distance of each event from the photodetector (negative = before arrival)
    times = {k: float(v - (oX if k[0] == "X" else oY)) for k, v in ev.items()}
    return oX - oY, dX, dY, times


def step4_geometry(P, M, verbose):
    th = np.deg2rad(M["theta_i_deg"])
    assert abs(th - np.pi / 4) < 1e-12, "ray-trace is written for the 45 deg Michelson layout"
    names = ["l_e", "n_e", "s_e", "l_l", "n_l", "s_l", "X_E", "Y_E", "D", "D_p"]
    l0, n0, L0 = P["l_BS"].to(u.m).value, P["n_BS"], P["L_arm"].to(u.m).value
    nom = [l0, n0, 0.0, l0, n0, 0.0, L0, L0, 100.0, 100.0]
    f = lambda a: _trace(*a)[0]
    hstep = mp.mpf("1e-12")

    def deriv(i):                      # central difference of dOPL w.r.t. parameter i
        ap, am = list(nom), list(nom)
        ap[i] = mp.mpf(nom[i]) + hstep; am[i] = mp.mpf(nom[i]) - hstep
        return float((f(ap) - f(am)) / (2 * hstep))

    S = {names[i]: deriv(i) for i in range(8)}          # sensitivities (m of round-trip OPL per m)
    dD, dDp = deriv(8), deriv(9)                          # must vanish
    dOPL_nom, dX, dY, times = _trace(*nom)
    theta_r = np.arcsin(np.sin(th) / n0)
    per_pass = n0 * np.cos(theta_r) - np.cos(th)                             # textbook plate-insertion path per pass
    dnc_dn = np.cos(theta_r) + np.sin(th)**2 / (n0**2 * np.cos(theta_r))    # d(n cos theta_r)/dn
    cvac = c.to(u.m / u.s).value
    t_ev = {k: v / cvac for k, v in times.items()}                          # seconds before PD arrival
    if verbose:
        banner("Step 4: exact ray-trace sensitivities (round trip, m per m)")
        print("early: dl %.6f dn %.6f ds0 %.6f | late: dl %.6f dn %.6f ds0 %.6f | dXE %.6f dYE %.6f"
              % (S["l_e"], S["n_e"], S["s_e"], S["l_l"], S["n_l"], S["s_l"], S["X_E"], S["Y_E"]))
        print(f"totals: dl {S['l_e']+S['l_l']:.6f}, dn {S['n_e']+S['n_l']:.6f}, ds0 {S['s_e']+S['s_l']:.6f}")
        print(f"final ray directions X,Y (expect 0,-1,0,-1): {[round(float(x),12) for x in (dX[0],dX[1],dY[0],dY[1])]}")
        print(f"check: independent of reference planes D, Dp: {dD:.1e}, {dDp:.1e}")
        print(f"check: closed form  dOPL/dl = 2 n cos(theta_r) = {2*n0*np.cos(theta_r):.6f}; "
              f"dOPL/dn = 2 l d(n cos theta_r)/dn = {2*l0*dnc_dn:.6f}")
        print(f"check: early = late = n cos(theta_r) = {n0*np.cos(theta_r):.6f} "
              f"(per-pass transmission {per_pass:.6f} + coating-face motion cos(theta_i) {np.cos(th):.6f})")
        print(f"check: no-Snell limit sqrt2 (n - 1/2) = {np.sqrt(2)*(n0-0.5):.6f} per encounter (Vermeulen+21 Eq. 5); "
              f"G&S Eq.(17) sqrt2 n = {np.sqrt(2)*n0:.6f}")
        print(f"check: GW calibration dXE - dYE = {S['X_E']-S['Y_E']:.6f} (expect 4); static uniform translation: "
              f"{S['s_e']+S['s_l'] + (S['X_E']-S['Y_E'])/np.sqrt(2):.1e} (expect 0)")
        print("event times before PD arrival [s]: " + ", ".join(f"{k} {v:.4e}" for k, v in t_ev.items()))
    return dict(S=S, theta_r=theta_r, per_pass=per_pass, t_ev=t_ev)


# ==========================================================================
# Step 5: complex signal amplitude per unit (1/Lambda)
#
#   eps(t, r) = eps0 cos(omega t - k.r) with eps0 = phi0/Lambda.  Each optic
#   is perturbed at its own event time t_j and position r_j; the response is
#   the sum of (sensitivity x perturbation) with phase factor exp(-i(omega t_j + k.r_j)).
#     * beamsplitter thickness/index (early and late encounters)          [in phase, cos]
#     * end-mirror faces move by (w/2) eps toward the BS (mirror breathes about its CoM)
#     * centre-of-mass displacements from the alpha-gradient force
#       delta x = kappa_M (v/omega) eps0 sin(...) along v-hat                [quadrature, sin -> factor -i]
#   The strain-equivalent amplitude divides by the Michelson GW transfer
#   function H_GW = 2 L sinc(omega L/c) (round-trip OPL per unit strain).
# ==========================================================================
def step5_amplitude(P, M, F, R, Gm, verbose, kappa_l=None, kappa_n=None, timing=True,
                    gw_sinc=True, nth=91, nph=181):
    kappa_l = R["kappa_l"] if kappa_l is None else kappa_l
    kappa_n = R["kappa_n"][M["T_BS_baseline"]] if kappa_n is None else kappa_n
    omega = F["omega"].to(1 / u.s).value; phi0 = F["phi0"].value
    L = P["L_arm"].to(u.m).value; l = P["l_BS"].to(u.m).value; n = P["n_BS"]
    w = M["w_ETM"].to(u.m).value
    v = P["v_DM"].to(u.m / u.s).value
    cvac = c.to(u.m / u.s).value
    k = (F["m_phi"] / (hbar * c) * (P["v_DM"] / c)).to(1 / u.m).value      # |k| = m v / hbar
    S, t = Gm["S"], Gm["t_ev"]
    dx0 = R["kappa_M"] * v / omega                                          # displacement amplitude per unit eps0
    if not timing:
        t = {key: 0.0 for key in t}

    # grid of DM-velocity directions: v-hat = (sin th cos ph, sin th sin ph, cos th), z vertical
    th = np.linspace(0, np.pi, nth); ph = np.linspace(0, 2 * np.pi, nph)
    TH, PH = np.meshgrid(th, ph, indexing="ij")
    vx, vy = np.sin(TH) * np.cos(PH), np.sin(TH) * np.sin(PH)
    phX, phY = k * L * vx, k * L * vy                         # k.r at ETMX and ETMY (BS at the origin)
    E = lambda tt, kr=0.0: np.exp(-1j * (omega * tt + kr))     # phase of eps at (t_event, r_event)

    A_BS = (kappa_l * l * S["l_e"] + kappa_n * n * S["n_e"]) * E(t["X_early"]) \
         + (kappa_l * l * S["l_l"] + kappa_n * n * S["n_l"]) * E(t["X_late"])
    A_ETM = (-kappa_l) * (w / 2) * (S["X_E"] * E(t["X_ETM"], phX) + S["Y_E"] * E(t["Y_ETM"], phY))   # face moves by -(delta w)/2 = -kappa_l (w/2) eps toward the BS
    A_disp = (-1j) * dx0 * (S["X_E"] * vx * E(t["X_ETM"], phX) + S["Y_E"] * vy * E(t["Y_ETM"], phY)
                            + (S["s_e"] * E(t["X_early"]) + S["s_l"] * E(t["X_late"])) * (vx - vy) / np.sqrt(2))
    A_tot = A_BS + A_ETM + A_disp                                # m of round-trip OPL per unit eps0
    x = omega * L / cvac
    H_GW = 2 * L * (np.sinc(x / np.pi) if gw_sinc else 1.0)      # numpy sinc(x) = sin(pi x)/(pi x)
    h_unit = np.abs(A_tot) / H_GW * phi0                         # strain per unit (1/Lambda) [GeV]
    out = dict(h_unit=h_unit, TH=TH, PH=PH, kL=k * L, x=x, H_GW=H_GW,
               h_BS_only=abs(A_BS) / H_GW * phi0,
               A_BS_abs=abs(A_BS), A_ETM_max=np.abs(A_ETM).max(), A_disp_max=np.abs(A_disp).max(), dx0=dx0)
    if verbose:
        banner("Step 5: signal amplitude per unit 1/Lambda_gamma [GeV^-1]")
        print(f"k L = {k*L:.4e} (reduced de Broglie wavelength {1/k:.3e} m); omega L/c = {x:.5f}; "
              f"sinc = {np.sinc(x/np.pi):.6f}; cos(omega L/c) [early/late] = {np.cos(x):.6f}")
        print(f"|A_BS| = {abs(A_BS):.6f} m/eps0 (no timing would be "
              f"{abs(kappa_l*l*(S['l_e']+S['l_l'])+kappa_n*n*(S['n_e']+S['n_l'])):.6f})")
        print(f"ETM-size term max {np.abs(A_ETM).max():.3e}, displacement term max {np.abs(A_disp).max():.3e} m/eps0")
        print(f"h per unit 1/Lambda: min {h_unit.min():.6e}, max {h_unit.max():.6e}, "
              f"direction range {(h_unit.max()-h_unit.min())/h_unit.mean():.2e}")
    return out


# ==========================================================================
# Steps 6 and 7: detection statistics and the threshold coupling
#
#   Monochromatic: SNR = h0 sqrt(T/S_h)  (one-sided PSD; Monte-Carlo checked below).
#   Stochastic field (Derevianko 2018 Eqs. 3-4):
#       <phi(t) phi(t+tau)> = (phi0^2/2) A(tau) cos(omega' tau + psi),
#       A(tau) = exp(-eta^2 x^2 / (2(1+x^2))) (1+x^2)^(-3/4),  x = tau/tau_c,  tau_c = 1/(xi^2 omega).
#   Optimal quadratic estimator (Derevianko Eq. 15): sigma prop. to [sum_p (<|phi_p|^2>/rho_p)^2]^(-1/4).
#   The expected power spectrum of a record of duration T is the Fourier transform of
#   (1-|tau|/T) x correlation; by Parseval the sum is prop. to int_0^T (1-tau/T)^2 A^2 dtau
#   and the phase psi drops out.  Normalized to the monochromatic threshold:
#       h_min(T) = sqrt(S_h/T) R(T),   R(T) = [ (T/3) / int_0^T (1-tau/T)^2 A(tau)^2 dtau ]^(1/4)
#   R -> 1 for T << tau_c and R -> (T/(3 I tau_c))^(1/4), I = int A^2 dx, for T >> tau_c.
# ==========================================================================
def A2(tau, tau_c, eta):
    x2 = (tau / tau_c)**2
    return np.exp(-eta**2 * x2 / (1 + x2)) / (1 + x2)**1.5


def R_of_T(T, tau_c, eta=1.0):
    I, _ = quad(lambda tt: (1 - tt / T)**2 * A2(tt, tau_c, eta), 0, T, limit=500,
                points=[tau_c, 3 * tau_c, 10 * tau_c] if T > 10 * tau_c else None)
    return ((T / 3) / I)**0.25


def step67_limits(P, M, F, h_unit_mean, verbose):
    beta = (P["v_DM"] / c).decompose().value
    omega = F["omega"].to(1 / u.s).value
    Sh = (P["sqrt_Sh"]**2).to(1 / u.Hz).value
    tau_GS = 1 / (P["f_DM"].value * beta**2)                 # 2 pi/(m v^2): Grote & Stadnik convention
    tau_D = 1 / (beta**2 * omega)                            # 1/(xi^2 omega) with xi c = v: Derevianko (primary)
    # "streaming reading": the problem's 230 km/s is the detector's speed through the halo (v_g);
    # the dispersion is then the SHM value v0/sqrt2 and eta = v_g/(xi c)
    xi_str = (M["v0_SHM"] / np.sqrt(2) / c).decompose().value
    tau_D_v0 = 1 / (xi_str**2 * omega)
    eta_str = beta / xi_str
    res = {}
    for T in P["T_obs"]:
        Ts = T.to(u.s).value
        # two-regime idealization (sharp switch at tau)
        h_int = P["SNR"] * np.sqrt(Sh / (Ts if Ts < tau_GS else np.sqrt(Ts * tau_GS)))
        h_int_D = P["SNR"] * np.sqrt(Sh / (Ts if Ts < tau_D else np.sqrt(Ts * tau_D)))
        # exact finite-coherence statistics, for the two readings of the given velocity
        R1 = R_of_T(Ts, tau_D, 1.0); R2 = R_of_T(Ts, tau_D_v0, eta_str)
        h_ex = P["SNR"] * np.sqrt(Sh / Ts) * R1
        h_ex_v0 = P["SNR"] * np.sqrt(Sh / Ts) * R2
        res[str(T)] = dict(T_s=Ts, h_intended=h_int, h_intended_tauD=h_int_D, R_D=R1, R_D_v0=R2,
                           h_exact=h_ex, h_exact_v0=h_ex_v0)
        if verbose:
            banner(f"Step 6/7: T = {T} = {Ts:.4e} s")
            print(f"tau_GS = {tau_GS:.1f} s (T/tau = {Ts/tau_GS:.3e}); tau_D = {tau_D:.1f} s (T/tau = {Ts/tau_D:.3e}); "
                  f"tau_c(streaming reading, xi c = {xi_str*c.to(u.km/u.s).value:.1f} km/s, eta = {eta_str:.3f}) = {tau_D_v0:.1f} s")
            print(f"h_min intended (two-regime, tau_GS) = {h_int:.4e}; same with tau_D = {h_int_D:.4e}")
            print(f"R(T) Derevianko: xi c = v: {R1:.5f}; streaming reading: {R2:.5f}")
            print(f"h_min exact = {h_ex:.4e}; (streaming reading) {h_ex_v0:.4e}")
    if verbose:
        print(f"asymptotic check: R(T>>tau_c) -> (T/(3 I tau_c))^(1/4), I(eta=1) = "
              f"{quad(lambda x: A2(x,1.0,1.0), 0, np.inf)[0]:.4f}")
    return dict(tau_GS=tau_GS, tau_D=tau_D, tau_D_v0=tau_D_v0, per_T=res)


# ==========================================================================
# Independent checks (printed under --verbose)
# ==========================================================================
def checks(P, F, verbose):
    if not verbose:
        return
    banner("Independent checks")
    # (a) gravity of the overdensity is irrelevant
    rho_si = (F["rho"] / c**2).to(u.kg / u.m**3)
    omega = F["omega"].to(1 / u.s).value
    print(f"rho = {rho_si:.3e}; oscillating-metric strain ~ G rho/omega^2 = "
          f"{(G*rho_si/(omega/u.s)**2).decompose().value:.2e}")
    # (b) SNR convention: matched filter on white noise with a known ONE-SIDED PSD S_h = 2 sigma^2 / f_s
    rng = np.random.default_rng(1)
    fs, T = 2000.0, 200.0
    N = int(fs * T); t = np.arange(N) / fs
    Sh = 1.0; sigma = np.sqrt(Sh * fs / 2); h0 = 0.05
    tmpl = np.cos(2 * np.pi * 200.0 * t)
    snr = [np.sum((h0 * tmpl + rng.normal(0, sigma, N)) * tmpl) / (sigma * np.sqrt(np.sum(tmpl**2)))
           for _ in range(3000)]
    print(f"MC matched-filter SNR = {np.mean(snr):.3f} +- {np.std(snr)/np.sqrt(len(snr)):.3f}; "
          f"h0 sqrt(T/S_h) = {h0*np.sqrt(T/Sh):.3f}; a spurious 1/sqrt2 would give {h0*np.sqrt(T/(2*Sh)):.3f}")
    # (c) Michelson GW transfer function: dOPL_X - dOPL_Y = c int_{t-2L/c}^{t} h dt' for h = cos(omega t)
    L = P["L_arm"].to(u.m).value; cv = c.to(u.m / u.s).value
    tau = 2 * L / cv
    amp = max(abs(cv * quad(lambda x: np.cos(omega * x), t0 - tau, t0)[0])
              for t0 in np.linspace(0, 2 * np.pi / omega, 400))
    print(f"GW response: numeric amplitude / (2L) = {amp/(2*L):.6f}; sinc(omega L/c) = {np.sinc(omega*L/cv/np.pi):.6f}")


# ==========================================================================
def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--verbose", action="store_true")
    ap.add_argument("--no-fig", action="store_true")
    a = ap.parse_args(); V = a.verbose
    if V:
        banner("Environment")
        print(f"python {sys.version.split()[0]}, numpy {np.__version__}, mpmath {mp.__version__}, "
              f"astropy {astropy.__version__} ({const.hbar.reference})")
        print("PROBLEM:", {k: (str(v) if not isinstance(v, list) else [str(x) for x in v]) for k, v in PROBLEM.items()})
        print("MODEL  :", {k: str(v) for k, v in MODEL.items()})
        print("CONV   :", CONV)

    F = step1_field(PROBLEM, V)
    R = step3_response(PROBLEM, MODEL, V)
    Gm = step4_geometry(PROBLEM, MODEL, V)
    A = step5_amplitude(PROBLEM, MODEL, F, R, Gm, V)
    TD = step67_limits(PROBLEM, MODEL, F, A["h_unit"].mean(), V)
    checks(PROBLEM, F, V)

    # ---- variants of the signal amplitude H (strain per unit 1/Lambda) ----
    l = PROBLEM["l_BS"].to(u.m).value; n = PROBLEM["n_BS"]; L = PROBLEM["L_arm"].to(u.m).value
    phi0 = F["phi0"].value
    run = lambda **kw: step5_amplitude(PROBLEM, MODEL, F, R, Gm, False, **kw)["h_unit"].mean()
    hv = {
        "exact (baseline: Frey 295K, kappa_l=-1, timing, sinc)": A["h_unit"].mean(),
        "  direction min / max": (A["h_unit"].min(), A["h_unit"].max()),
        "  no timing, no sinc": run(timing=False, gw_sinc=False),
        "  timing only (no sinc)": run(gw_sinc=False),
        "  delta n dropped": run(kappa_n=0.0),
        "  BS at 123 K": run(kappa_n=R["kappa_n"][123]),
        "  relativistic kappa_l (j=1/2)": run(kappa_l=-(1 + R["K_alpha"][0.5])),
        "  relativistic kappa_l (j=3/2)": run(kappa_l=-(1 + R["K_alpha"][1.5])),
        "G&S Eq.(18): sqrt2 n l / L, no dn": np.sqrt(2) * n * l / L * phi0,
        "Vermeulen Eq.(5) no Snell: sqrt2 (n-1/2) l / L": np.sqrt(2) * (n - 0.5) * l / L * phi0,
        "closed form n cos(theta_r) l / L, no dn, no timing": n * np.cos(Gm["theta_r"]) * l / L * phi0,
    }
    banner("Signal amplitude h per unit Lambda^-1 [GeV^-1]: variants")
    for k, v in hv.items():
        print(f"{k:60s} " + ("%.6e / %.6e" % v if isinstance(v, tuple) else f"{v:.6e}"))

    # ---- result table: signal model x time-domain model ----
    banner("RESULT: smallest Lambda_gamma^-1 [GeV^-1] at SNR = 1, f = 200 Hz")
    hdr = f"{'signal model':42s} {'time model':34s} {'1000 s':>12s} {'0.7 yr':>12s}"
    print(hdr); print("-" * len(hdr))
    rows = []
    sig_models = [("exact ray-trace (baseline)", A["h_unit"].mean()),
                  ("G&S Eq.(18) (likely intended)", hv["G&S Eq.(18): sqrt2 n l / L, no dn"]),
                  ("Vermeulen Eq.(5), no Snell", hv["Vermeulen Eq.(5) no Snell: sqrt2 (n-1/2) l / L"])]
    time_models = [("two-regime, tau=2pi/(m v^2)", "h_intended"), ("two-regime, tau=1/(m v^2)", "h_intended_tauD"),
                   ("Derevianko exact, xi c = v", "h_exact"), ("Derevianko exact, streaming + SHM", "h_exact_v0")]
    keys = list(TD["per_T"].keys())
    for sn, hu in sig_models:
        for tn, tk in time_models:
            vals = [TD["per_T"][kk][tk] / hu for kk in keys]
            rows.append(dict(signal=sn, time=tn, lam_1000s=vals[0], lam_07yr=vals[1]))
            print(f"{sn:42s} {tn:34s} {vals[0]:12.4e} {vals[1]:12.4e}")
    print(f"\ndirection range (baseline signal, Derevianko exact): 1000 s "
          f"{TD['per_T'][keys[0]]['h_exact']/A['h_unit'].max():.4e} .. {TD['per_T'][keys[0]]['h_exact']/A['h_unit'].min():.4e}")
    print(f"tau_GS = {TD['tau_GS']:.1f} s, tau_D = {TD['tau_D']:.1f} s; R(1000 s) = {TD['per_T'][keys[0]]['R_D']:.4f}, "
          f"R(0.7 yr) = {TD['per_T'][keys[1]]['R_D']:.4f}")

    json.dump(dict(h_unit=hv, limits=rows, tau=dict(GS=TD["tau_GS"], D=TD["tau_D"], D_v0=TD["tau_D_v0"]),
                   R={k: (TD["per_T"][k]["R_D"], TD["per_T"][k]["R_D_v0"]) for k in keys},
                   K_alpha=R["K_alpha"], kappa_n=R["kappa_n"], sens=Gm["S"], t_ev=Gm["t_ev"]),
              open("results.json", "w"), indent=1, default=lambda o: float(o) if np.isscalar(o) else str(o))
    print("wrote results.json")

    if not a.no_fig:
        import matplotlib; matplotlib.use("Agg")
        import matplotlib.pyplot as plt, os
        os.makedirs("figs", exist_ok=True)
        # (1) direction dependence of the signal amplitude
        rel = (A["h_unit"] / A["h_unit"].mean() - 1) * 1e4
        fig, ax = plt.subplots(figsize=(7, 3.6))
        im = ax.pcolormesh(np.rad2deg(A["PH"]), np.rad2deg(A["TH"]), rel, shading="auto", cmap="RdBu_r")
        ax.set_xlabel("DM wind azimuth from X arm [deg]"); ax.set_ylabel("polar angle from vertical [deg]")
        fig.colorbar(im, ax=ax).set_label(r"$(h_0/\langle h_0\rangle - 1)\times 10^{4}$")
        fig.tight_layout(); fig.savefig("figs/direction_dependence.png", dpi=160)
        # (2) threshold factor R(T) versus the two-regime idealization
        Ts = np.logspace(1, 8, 300)
        fig, ax = plt.subplots(figsize=(6, 3.6))
        xi_str_kms = MODEL["v0_SHM"].to(u.km / u.s).value / np.sqrt(2)
        for tau, eta, lab in [(TD["tau_D"], 1.0, r"$\xi c = v = 230$ km/s, $\eta=1$ (primary)"),
                              (TD["tau_D_v0"], PROBLEM["v_DM"].to(u.km / u.s).value / xi_str_kms,
                               r"$v_g = 230$ km/s, $\xi c = %.0f$ km/s (SHM), $\eta=%.2f$" % (xi_str_kms, 230 / xi_str_kms))]:
            ax.loglog(Ts, [R_of_T(T, tau, eta) for T in Ts], label=lab)
        ax.loglog(Ts, np.where(Ts < TD["tau_GS"], 1, (Ts / TD["tau_GS"])**0.25), "k--",
                  label=r"two-regime, $\tau=2\pi/(mv^2)$")
        for T in PROBLEM["T_obs"]:
            ax.axvline(T.to(u.s).value, color="grey", lw=0.8)
        ax.set_xlabel("observation time T [s]"); ax.set_ylabel(r"$R(T) = h_{\min}(T)\,/\,\sqrt{S_h/T}$")
        ax.tick_params(which="major", length=3.5 * 1.5)   # 1.5 x matplotlib defaults (3.5 / 2.0 pt)
        ax.tick_params(which="minor", length=2.0 * 1.5)
        ax.legend(fontsize=8)
        fig.tight_layout(); fig.savefig("figs/R_of_T.png", dpi=160)
        print("figures: figs/direction_dependence.png, figs/R_of_T.png")


if __name__ == "__main__":
    main()
