#!/usr/bin/env python3
"""Compute Cosmic Explorer scalar-dark-matter sensitivity for Challenge 56."""

from __future__ import annotations

import math
import runpy
from pathlib import Path


def sensitivities() -> tuple[float, float]:
    cm_in_inverse_gev = 5.06773071616e13
    density = 178.0 * 0.4 / cm_in_inverse_gev**3
    mass = 4.135667696e-24 * 200.0
    field_amplitude = math.sqrt(2.0 * density) / mass
    strain_per_coupling = 3.5 * 0.06 / 4.0e4 * field_amplitude

    coherence_time = 1.0 / (200.0 * (230.0 / 299792.458) ** 2)
    noise_asd = 2.0e-25
    short_time = 1000.0
    long_time = 0.7 * 365.25 * 86400.0
    short_threshold = noise_asd / math.sqrt(short_time)
    long_threshold = noise_asd / (long_time * coherence_time) ** 0.25
    return short_threshold / strain_per_coupling, long_threshold / strain_per_coupling


def main() -> None:
    values = sensitivities()
    print(f"1000 s: {values[0]:.12e} GeV^-1")
    print(f"0.7 yr: {values[1]:.12e} GeV^-1")
    expected = runpy.run_path(Path(__file__).with_name("answer.py"))["answer"]()
    if any(not math.isclose(value, target, rel_tol=5.0e-6) for value, target in zip(values, expected)):
        raise AssertionError((values, expected))


if __name__ == "__main__":
    main()
