#!/usr/bin/env python3
"""Compute the idealized coherent LIGO dark-vector reach in Challenge 57."""

from __future__ import annotations

import math
import runpy
from pathlib import Path


def sensitivities() -> list[float]:
    cm_in_inverse_gev = 5.06773071616e13
    meter_in_inverse_gev = 5.06773071616e15
    density = 0.4 / cm_in_inverse_gev**3
    mass = 4.135667696e-24 * 250.0
    neutron_mass = 0.93956542194
    alpha = 7.2973525643e-3
    electric_charge = math.sqrt(4.0 * math.pi * alpha)
    arm_length = 4000.0 * meter_in_inverse_gev
    strain_coefficient = (
        electric_charge * math.sqrt(2.0 * density) / (neutron_mass * mass**2 * arm_length)
    )

    observation_time = 13.0 * 365.25 * 86400.0
    strain_threshold = 3.0e-24 / math.sqrt(observation_time)
    return [strain_threshold / (strain_coefficient * delta_q) for delta_q in (0.074, 0.006, 0.0005)]


def main() -> None:
    values = sensitivities()
    for delta_q, value in zip((0.074, 0.006, 0.0005), values):
        print(f"delta_q={delta_q:g}: epsilon={value:.12e}")
    expected = runpy.run_path(Path(__file__).with_name("answer.py"))["answer"]()
    if any(not math.isclose(value, target, rel_tol=5.0e-7) for value, target in zip(values, expected)):
        raise AssertionError((values, expected))


if __name__ == "__main__":
    main()
