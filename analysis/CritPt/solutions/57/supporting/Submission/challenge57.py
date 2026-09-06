#!/usr/bin/env python
"""
challenge57.py -- Challenge 57: LIGO with modified (doped) mirrors for ultralight vector dark matter
======================================================================================================

Question.  A vector field A^mu couples to the B-L current, L contains -eps e J^mu_{B-L} A_mu, and is all the
dark matter.  LIGO: strain ASD 3e-24 Hz^-1/2 at 250 Hz.  Inner mirrors (ITMs) have Q_D/M = 0.5/m_n;
the doped outer mirrors (ETMs) gain delta(Q_D/M) = delta q/m_n, delta q = {0.074, 6e-3, 5e-4}.
With T = 13 yr and SNR = 1, what is the smallest eps_{B-L} at 250 Hz for each delta q?

Physics chain (equation numbers refer to solution.tex)
    Step 1  field: omega -> m_A; dark electric field amplitude sqrt(2 rho/eps0) (SI)
    Step 2  force on a mirror: a = eps e (Q/M) sqrt(2 rho/eps0) (e_hat . polarization); free-mass displacement dx = a/omega^2
    Step 3  exact round trip of one arm with different ITM/ETM charge-to-mass ratios (Morisaki+21 Eq. 11, Michimura+20 Eq. 9):
            dL(t) = [4 sin^2(omega L/2c) + 2 delta q/q0] n.dx(t-L/c)  [in phase]  + 2 L (n.k)(n.dx)  [quadrature]
            = undoped finite-light-travel-time term + doping term + k.dr term
    Step 4  Michelson output h = -(dL_n - dL_m)/(2L); RMS over random polarization and propagation direction
            (<(n.e)^2> = 1/3, n.m = 0):  <h^2> = (dx0^2 / 4L^2) [Gamma^2/3 + (2 k L)^2/9]
            (reduces to Morisaki+21 Eqs. 23-24 for delta q = 0: checked under --verbose)
    Step 5  detection statistics: power threshold <h^2> = S_h / T_eff, T_eff = sqrt(tau T), tau = 2 pi/(m_A v^2)
            (Pierce+18 Eq. 9, Morisaki+21 Eqs. 20-21: the convention of the problem's source literature);
            alternative: amplitude matched-filter threshold with the Derevianko R(T) as in Challenge 56
    Step 6  eps_min = sqrt(S_h/(T_eff <h^2>_1)),  <h^2>_1 = <h^2> per unit eps^2

Reproducibility: PROBLEM (verbatim inputs) / MODEL (non-given inputs with sources) / CONV; astropy CODATA 2018;
--verbose prints intermediate quantities and checks; results.json and figs/ written in the working directory.
Run:  conda run -n pyjax python challenge57.py [--verbose] [--no-fig]
"""
import sys, argparse, json
import numpy as np
import astropy
import astropy.units as u
import astropy.constants as const
from scipy.integrate import quad

# ==========================================================================
# INPUTS
# ==========================================================================
PROBLEM = dict(                                        # verbatim from problem.tex
    f_DM     = 250.0 * u.Hz,
    sqrt_Sh  = 3.0e-24 / u.Hz**0.5,                    # LIGO strain ASD at 250 Hz (one-sided)
    q0       = 0.5,                                    # inner mirrors: Q_D/M = q0/m_n
    delta_q  = [0.074, 6e-3, 5e-4],                    # outer mirrors gain delta q/m_n
    T_obs    = 13.0 * u.yr,                            # Julian years (astropy)
    SNR      = 1.0,
)
MODEL = dict(                                          # NOT given by the problem
    rho_DM   = 0.4 * u.GeV / u.cm**3,   # Pierce+18, Morisaki+21, LVK 2022 (Read 2014); carried over from Challenge 56
    v_DM     = 230.0 * u.km / u.s,      # carried over from Challenge 56; Pierce+18 / Morisaki+21 / Michimura+20 (RAVE, Smith+07)
    L_arm    = 3994.5 * u.m,            # Advanced LIGO arm length (Aasi+15, CQG 32, 074001, Table 1); "4 km" variant below
    n_dot_m  = 0.0,                     # perpendicular arms
    rho_alt  = 0.3 * u.GeV / u.cm**3,   # direct-detection convention (Lewin & Smith; Baxter+21) -> variant
    L_alt    = 4000.0 * u.m,            # nominal "4 km" -> variant
)
CONV = dict(
    threshold = "power: <h^2> = S_h/T_eff, T_eff = sqrt(tau T), tau = 2 pi/(m_A v^2) (Pierce+18 Eq. 9; Morisaki+21 Eqs. 20-21)",
    averaging = "RMS over random polarization and propagation direction (all source papers); forced by 13-yr sidereal averaging",
    alt_stat  = "amplitude matched filter h0 sqrt(T/S_h) = 1 with Derevianko R(T), xi c = v, eta = 1 (as in Challenge 56)",
)

hbar, c, eps0, e_ch, m_n = const.hbar, const.c, const.eps0, const.e.si, const.m_n


def banner(s): print("\n" + "=" * 78 + "\n" + s + "\n" + "=" * 78)


# ==========================================================================
def step1_field(P, M, verbose):
    omega = (2 * np.pi * P["f_DM"]).to(1 / u.s)
    mA = (hbar * omega).to(u.eV)                                   # m_A c^2
    rho = M["rho_DM"].to(u.J / u.m**3)                               # GeV/cm^3 -> J/m^3 (energy density)
    E_D = np.sqrt(2 * rho / eps0).to(u.V / u.m)                     # dark electric field amplitude
    beta = (M["v_DM"] / c).decompose().value
    k = (omega / c * beta).to(1 / u.m)                              # m_A v / hbar
    if verbose:
        banner("Step 1: field")
        print(f"omega = {omega:.5e}; m_A c^2 = {mA:.5e}; rho = {rho:.5e}; E_D = sqrt(2 rho/eps0) = {E_D:.5e}")
        print(f"beta = {beta:.5e}; k = {k:.4e}; k L = {(k*M['L_arm']).decompose():.4e}")
    return dict(omega=omega, mA=mA, rho=rho, E_D=E_D, beta=beta, k=k)


# ==========================================================================
def step2_displacement(P, M, F, verbose):
    """Displacement amplitude of an inner mirror per unit eps: dx0 = e (q0/m_n) E_D / omega^2."""
    a0 = (e_ch * P["q0"] / m_n * F["E_D"]).to(u.m / u.s**2)          # per unit eps
    dx0 = (a0 / F["omega"]**2).to(u.m)
    if verbose:
        banner("Step 2: force and displacement per unit eps")
        print(f"e q0/m_n = {(e_ch*P['q0']/m_n).to(u.C/u.kg):.5e}; a0 = {a0:.5e}; dx0 = {dx0:.5e}")
    return dict(a0=a0, dx0=dx0)


# ==========================================================================
def step34_signal(P, M, F, D, verbose, L=None, include_ltt=True, include_k=True):
    """<h^2> per unit eps^2 for each delta q.  Exact round trip, RMS over polarization and direction."""
    L = M["L_arm"] if L is None else L
    x = (F["omega"] * L / c).decompose().value                       # omega L / c
    ltt = 4 * np.sin(x / 2)**2 if include_ltt else 0.0               # undoped finite-light-travel-time coefficient
    kL = (F["k"] * L).decompose().value
    dx0 = D["dx0"].to(u.m).value; Lm = L.to(u.m).value
    out = {}
    for dq in P["delta_q"]:
        Gam = ltt + 2 * dq / P["q0"]                                 # in-phase coefficient Gamma (round trip)
        quad_term = (2 * kL)**2 / 9 if include_k else 0.0
        h2 = dx0**2 / (4 * Lm**2) * (Gam**2 / 3 + quad_term)           # <h^2> per eps^2 (time + orientation average)
        out[dq] = dict(Gamma=Gam, h2=h2, ltt=ltt, dop=2 * dq / P["q0"], kL=kL)
    if verbose:
        banner("Steps 3-4: arm signal and Michelson output per unit eps")
        print(f"omega L/c = {x:.5e}; 4 sin^2(omega L/2c) = {ltt:.4e}; 2 k L = {2*kL:.4e}")
        for dq, r in out.items():
            print(f"delta q = {dq:.3g}: doping coeff 2dq/q0 = {r['dop']:.4e}, Gamma = {r['Gamma']:.4e}, "
                  f"undoped/doping = {r['ltt']/r['dop']:.4f}, <h^2>^(1/2) per eps = {np.sqrt(r['h2']):.4e}")
        # check against Morisaki Eqs. (23)-(24) in the undoped limit.  Their eps^2 e^2 rho (Q/M)^2 (natural units)
        # is a0^2/2 in SI (a0 = e (Q/M) sqrt(2 rho/eps0)), and their m_A -> omega, k = m_A v -> k here.
        a0 = D["a0"].value; om = F["omega"].value
        mor23 = 8 * (a0**2 / 2) * np.sin(x / 2)**4 / (3 * om**4 * Lm**2) * (1 - M["n_dot_m"])
        mor24 = 2 * (a0**2 / 2) * (F["beta"] / (om * c.value))**2 / 9 * (1 - M["n_dot_m"]**2)   # 2 eps^2 e^2 v^2 rho (Q/M)^2/(9 m^2), SI: /c^2
        mine23 = dx0**2 / (4 * Lm**2) * (ltt**2 / 3); mine24 = dx0**2 / (4 * Lm**2) * (2 * kL)**2 / 9
        print(f"check vs Morisaki Eq.(23): mine {mine23:.6e} vs {mor23:.6e} (ratio {mine23/mor23:.6f}); "
              f"Eq.(24): mine {mine24:.6e} vs {mor24:.6e} (ratio {mine24/mor24:.6f})")
    return out


# ==========================================================================
def A2(tau, tau_c, eta):
    x2 = (tau / tau_c)**2
    return np.exp(-eta**2 * x2 / (1 + x2)) / (1 + x2)**1.5


def R_of_T(T, tau_c, eta=1.0):
    I, _ = quad(lambda tt: (1 - tt / T)**2 * A2(tt, tau_c, eta), 0, T, limit=500,
                points=[tau_c, 3 * tau_c, 10 * tau_c] if T > 10 * tau_c else None)
    return ((T / 3) / I)**0.25


def step56_threshold(P, M, F, verbose):
    Sh = (P["sqrt_Sh"]**2).to(1 / u.Hz).value
    T = P["T_obs"].to(u.s).value
    tau = 1 / (P["f_DM"].value * F["beta"]**2)                        # 2 pi/(m v^2)
    tau_c = tau / (2 * np.pi)                                          # 1/(xi^2 omega)
    Teff = np.sqrt(tau * T)
    h2_thr = Sh / Teff                                                 # power threshold on <h^2>
    R = R_of_T(T, tau_c, 1.0)
    h0_thr_alt = np.sqrt(Sh / T) * R                                   # amplitude threshold (56-style)
    if verbose:
        banner("Steps 5-6: thresholds")
        print(f"T = {T:.4e} s; tau = 2pi/(m v^2) = {tau:.1f} s; tau_c = {tau_c:.1f} s; T/tau = {T/tau:.3e}; T_eff = {Teff:.4e} s")
        print(f"power threshold <h^2> = S/T_eff = {h2_thr:.4e} (sqrt = {np.sqrt(h2_thr):.4e})")
        print(f"amplitude alternative: R(T) = {R:.4f}; h0 = sqrt(S/T) R = {h0_thr_alt:.4e}  (<h^2> = h0^2/2 = {h0_thr_alt**2/2:.4e})")
    return dict(Sh=Sh, T=T, tau=tau, tau_c=tau_c, Teff=Teff, h2_thr=h2_thr, R=R, h0_thr_alt=h0_thr_alt)


# ==========================================================================
def main():
    ap = argparse.ArgumentParser(); ap.add_argument("--verbose", action="store_true"); ap.add_argument("--no-fig", action="store_true")
    a = ap.parse_args(); V = a.verbose
    if V:
        banner("Environment"); print(f"astropy {astropy.__version__} ({const.hbar.reference})")
        print("PROBLEM:", {k: str(v) for k, v in PROBLEM.items()}); print("MODEL:", {k: str(v) for k, v in MODEL.items()}); print("CONV:", CONV)
    F = step1_field(PROBLEM, MODEL, V)
    D = step2_displacement(PROBLEM, MODEL, F, V)
    S = step34_signal(PROBLEM, MODEL, F, D, V)
    Th = step56_threshold(PROBLEM, MODEL, F, V)

    # variants of the signal model
    S_dop = step34_signal(PROBLEM, MODEL, F, D, False, include_ltt=False, include_k=False)   # doping only (intended)
    S_nok = step34_signal(PROBLEM, MODEL, F, D, False, include_k=False)
    S_L4 = step34_signal(PROBLEM, MODEL, F, D, False, L=MODEL["L_alt"])
    rho_ratio = (MODEL["rho_alt"] / MODEL["rho_DM"]).decompose().value

    banner("RESULT: smallest eps_{B-L} at SNR = 1, f = 250 Hz, T = 13 yr")
    rows = []
    hdr = f"{'signal model':46s} {'statistic':30s} " + " ".join(f"{'dq='+str(dq):>12s}" for dq in PROBLEM["delta_q"])
    print(hdr); print("-" * len(hdr))
    def eps_power(Sig, h2thr=Th["h2_thr"]): return [np.sqrt(h2thr / Sig[dq]["h2"]) for dq in PROBLEM["delta_q"]]
    def eps_amp(Sig): return [Th["h0_thr_alt"] / np.sqrt(2 * Sig[dq]["h2"]) for dq in PROBLEM["delta_q"]]
    table = [
        ("exact (ltt + doping + k.dr), L = 3994.5 m", "power, T_eff = sqrt(tau T)", eps_power(S)),
        ("exact", "amplitude MF + Derevianko R(T)", eps_amp(S)),
        ("doping only (as the problem implies)", "power, T_eff = sqrt(tau T)", eps_power(S_dop)),
        ("exact, no k.dr term", "power", eps_power(S_nok)),
        ("exact, L = 4000 m", "power", eps_power(S_L4)),
        ("exact, rho = 0.3 GeV/cm^3", "power", [x / np.sqrt(rho_ratio) for x in eps_power(S)]),
    ]
    for sn, st, vals in table:
        rows.append(dict(signal=sn, statistic=st, eps=vals))
        print(f"{sn:46s} {st:30s} " + " ".join(f"{v:12.4e}" for v in vals))
    json.dump(dict(rows=rows, thresholds={k: float(v) for k, v in Th.items()},
                   signal={str(dq): {k: float(v) for k, v in r.items()} for dq, r in S.items()},
                   dx0=D["dx0"].value, mA_eV=F["mA"].value, kL=float((F["k"]*MODEL["L_arm"]).decompose().value)),
              open("results.json", "w"), indent=1)
    print("wrote results.json")

    if not a.no_fig:
        import matplotlib; matplotlib.use("Agg"); import matplotlib.pyplot as plt, os
        os.makedirs("figs", exist_ok=True)
        dqs = np.logspace(-4, -0.5, 200)
        x = (F["omega"] * MODEL["L_arm"] / c).decompose().value; ltt = 4 * np.sin(x / 2)**2
        fig, ax = plt.subplots(figsize=(6, 3.6))
        ax.loglog(dqs, ltt / (2 * dqs / PROBLEM["q0"]), label=r"undoped light-travel-time term / doping term")
        for dq in PROBLEM["delta_q"]:
            ax.axvline(dq, color="grey", lw=0.8)
        ax.axhline(1, color="k", ls="--", lw=0.8)
        ax.set_xlabel(r"$\delta q$"); ax.set_ylabel("amplitude ratio"); ax.legend(fontsize=8)
        ax.tick_params(which="major", length=5.25); ax.tick_params(which="minor", length=3)
        fig.tight_layout(); fig.savefig("figs/ltt_vs_doping.png", dpi=160); print("figure: figs/ltt_vs_doping.png")


if __name__ == "__main__":
    main()
