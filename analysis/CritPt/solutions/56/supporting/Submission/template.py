def answer():
    r"""
    Return the values of the smallest $\Lambda_\gamma^{-1}$.

    Inputs
    ----------
    None

    Outputs
    ----------
    lambda_inv: list[float]
        Smallest coupling strength $\Lambda_\gamma^{-1}$ the Cosmic Explorer can probe at 200 Hz
        with an observation time of $\{1000\,\text{s}, 0.7\,\text{yrs}\}$ and a signal-to-noise of 1.
    """

    # ------------------ FILL IN YOUR RESULTS BELOW ------------------
    # Units: GeV^-1.  Computed by Claude_Notes/challenge56.py (exact beamsplitter
    # geometry with Snell refraction, silicon index response, finite light-travel
    # time of the 40 km arms, finite-coherence detection statistics).
    # The sharp two-regime idealization would give [2.97e-23, 1.43e-24].
    lambda_inv = [3.05e-23, 1.85e-24]
    # ---------------------------------------------------------------

    return lambda_inv
