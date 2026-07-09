# Messy Partition Examples Review

This file aggregates the initial 5-row smoke test and the additional 15-row sample test for the messy multi-part partitioning prompt.

## Initial 5-Row Smoke Test

## FrontierPhysics/test.parquet row=3 id=thermo-early-universe/9.2

Verification passed: `True`
Metrics: jaccard=0.9, content_jaccard=1.0, missing=0.0357, added=0.069, length_ratio=0.988, doubled_latex=[]

Original:

```text
Determine the average energy per particle and average entropy per particle for the photons, electrons, positrons and neutrinos during the first second of the universe.
```

Partitioned:

```text
Determine for the photons, electrons, positrons and neutrinos during the first second of the universe:
(a) the average energy per particle.
(b) average entropy per particle.
```

## Physics-TTT/test.parquet row=67 id=quantum/4007

Verification passed: `True`
Metrics: jaccard=0.9474, content_jaccard=1.0, missing=0.0137, added=0.04, length_ratio=0.9967, doubled_latex=[]

Original:

```text
Determine the energy levels, their degeneracy and the corresponding eigenfunctions of an electron contained in a cube of essentially infinite volume $L^3$. The electron is in an electromagnetic field characterized by the vector potential $$ \mathbf{A} = H_0x\hat{e}_y \quad (\lvert \hat{e}_y \rvert = 1). $$
```

Partitioned:

```text
Determine, of an electron contained in a cube of essentially infinite volume $L^3$:
(a) the energy levels.
(b) their degeneracy.
(c) the corresponding eigenfunctions.
The electron is in an electromagnetic field characterized by the vector potential $$ \mathbf{A} = H_0x\hat{e}_y \quad (\lvert \hat{e}_y \rvert = 1). $$
```

## Physics-TTT/train.parquet row=45 id=statistics/2-126

Verification passed: `True`
Metrics: jaccard=0.9315, content_jaccard=1.0, missing=0.0286, added=0.0423, length_ratio=0.9942, doubled_latex=[]

Original:

```text
Find the pressure, entropy, and specific heat at constant volume of an ideal Boltzmann gas of indistinguishable particles in the extreme relativistic limit, in which the energy of a particle is related to its momentum by $ \varepsilon = cp $. Express your answer as functions of the volume $ V $, temperature $ T $, and number of particles $ N $.
```

Partitioned:

```text
Find, of an ideal Boltzmann gas of indistinguishable particles in the extreme relativistic limit, in which the energy of a particle is related to its momentum by $ \varepsilon = cp $. Express your answer as functions of the volume $ V $, temperature $ T $, and number of particles $ N $:
(a) the pressure.
(b) entropy.
(c) specific heat at constant volume.
```

## Physics-TTT/train.parquet row=94 id=optics/3-25

Verification passed: `True`
Metrics: jaccard=0.9692, content_jaccard=1.0, missing=0.0156, added=0.0156, length_ratio=1.0, doubled_latex=[]

Original:

```text
﻿Solar energy at the rate 800 W/m$^2$ strikes a flat solar panel for water heating. If the panel has absorptance = 0.96 for all wavelengths and the sides are perfect insulators, calculate the maximum temperature of the water. If the absorptance dropped by 1/2, how would this affect the final temperature?
```

Partitioned:

```text
Solar energy at the rate 800 W/m$^2$ strikes a flat solar panel for water heating. If the panel has absorptance = 0.96 for all wavelengths and the sides are perfect insulators:
(a) calculate the maximum temperature of the water.
(b) If the absorptance dropped by 1/2, how would this affect the final temperature?
```

## Physics-TTT/train.parquet row=305 id=electro/1_15

Verification passed: `True`
Metrics: jaccard=0.9385, content_jaccard=1.0, missing=0.0317, added=0.0317, length_ratio=0.9896, doubled_latex=[]

Original:

```text
In the equilibrium configuration, a spherical conducting shell of inner radius $a$ and outer radius $b$ has a charge $q$ fixed at the center and a charge density $\sigma$ uniformly distributed on the outer surface. Find the electric field for all $r$, and the charge on the inner surface.
```

Partitioned:

```text
In the equilibrium configuration, a spherical conducting shell of inner radius $a$ and outer radius $b$ has a charge $q$ fixed at the center and a charge density $\sigma$ uniformly distributed on the outer surface. Find:
(a) the electric field for all $r$.
(b) the charge on the inner surface.
```

## Additional 15-Row Sample Test

## FrontierPhysics/test.parquet row=58 id=textbook/7.3

Verification passed: `True`
Metrics: jaccard=0.9691, content_jaccard=0.9753, missing=0.0309, added=0.0, length_ratio=0.9817, doubled_latex=[]

Original:

```text
**Exercise 7.3.** Assume the probability that an electron experiences a collision between time *t* and $t + dt$ is $dt/\tau$. (i) Give the probability distribution function for $t_c$, $p(t_c) = (1/\tau)e^{-t_c/\tau}$. (ii) Calculate $\langle t_c \rangle$ and $\langle t_c^2 \rangle$. (iii) Let *n* be the number of collisions experienced by the electron in a time interval of length *t* (say, between *t'* and $t' + t$). The probability distribution for *n* is the Poisson distribution $P(n) = e^{-\overline{n}} \overline{n}^n / n!$, where $\overline{n}$ is its average. Find the value of $\overline{n}$.
```

Partitioned:

```text
**Exercise 7.3.** Assume the probability that an electron experiences a collision between time *t* and $t + dt$ is $dt/\tau$.
(a) Give the probability distribution function for $t_c$, $p(t_c) = (1/\tau)e^{-t_c/\tau}$.
(b) Calculate $\langle t_c \rangle$ and $\langle t_c^2 \rangle$.
(c) Let *n* be the number of collisions experienced by the electron in a time interval of length *t* (say, between *t'* and $t' + t$). The probability distribution for *n* is the Poisson distribution $P(n) = e^{-\overline{n}} \overline{n}^n / n!$, where $\overline{n}$ is its average. Find the value of $\overline{n}$.
```

## FrontierPhysics/test.parquet row=71 id=interacting-electron-gas/6.6

Verification passed: `True`
Metrics: jaccard=1.0, content_jaccard=1.0, missing=0.0, added=0.0, length_ratio=1.0, doubled_latex=[]

Original:

```text
PROBLEM 6.6. A two-dimensional electron gas in a compensating background of positive charge exhibits a net magnetization, that is, a difference in the population between the up and down spins. The electrons interact via a $1/r$ interaction. Define the relative magnetization in the electron gas as (119) $$ \xi = \frac{n_{\uparrow} - n_{\downarrow}}{n_{\uparrow} + n_{\downarrow}}. $$ The Fermi momentum for up and down spins can be written as (120) $$ p_{F\uparrow} = p_F \sqrt{1+\xi}, \qquad p_{F\downarrow} = p_F \sqrt{1-\xi}. $$ Calculate the ground state energy, at the level of Hartree-Fock of the electron gas as a function of $\xi$. For what values of $\xi$ is the ground state stable? Estimate the value of $r_s$ at which the ground state energy of the fully polarized (ferromagnetic) electron gas is lower in energy than the completely unpolarized ($\xi = 0$) gas.
```

Partitioned:

```text
PROBLEM 6.6. A two-dimensional electron gas in a compensating background of positive charge exhibits a net magnetization, that is, a difference in the population between the up and down spins. The electrons interact via a $1/r$ interaction. Define the relative magnetization in the electron gas as (119) $$ \xi = \frac{n_{\uparrow} - n_{\downarrow}}{n_{\uparrow} + n_{\downarrow}}. $$ The Fermi momentum for up and down spins can be written as (120) $$ p_{F\uparrow} = p_F \sqrt{1+\xi}, \qquad p_{F\downarrow} = p_F \sqrt{1-\xi}. $$
(a) Calculate the ground state energy, at the level of Hartree-Fock of the electron gas as a function of $\xi$.
(b) For what values of $\xi$ is the ground state stable?
(c) Estimate the value of $r_s$ at which the ground state energy of the fully polarized (ferromagnetic) electron gas is lower in energy than the completely unpolarized ($\xi = 0$) gas.
```

## FrontierPhysics/test.parquet row=102 id=pathria/7.13

Verification passed: `True`
Metrics: jaccard=0.9831, content_jaccard=1.0, missing=0.0114, added=0.0057, length_ratio=0.9935, doubled_latex=[]

Original:

```text
Consider an ideal Bose gas confined to a region of area A in two dimensions. Express the number of particles in the excited states, $N_e$, and the number of particles in the ground state, $N_0$, in terms of $z$, $T$, and $A$, and determine whether the system exhibits Bose-Einstein condensation unless $T \rightarrow 0$ K. If the area A and the total number of particles N are held fixed and we require both $N_e$ and $N_0$ to be of order $N$, give the condensation temperature scaling $$ T \sim \frac{h^{2}}{m k l^{2}} \frac{1}{\ln N}, $$ where $l \sim \sqrt{A/N}$ is the mean interparticle distance in the system.
```

Partitioned:

```text
Consider an ideal Bose gas confined to a region of area A in two dimensions.
(a) Express the number of particles in the excited states, $N_e$, and the number of particles in the ground state, $N_0$, in terms of $z$, $T$, and $A$.
(b) determine whether the system exhibits Bose-Einstein condensation unless $T \rightarrow 0$ K.
(c) If the area A and the total number of particles N are held fixed and we require both $N_e$ and $N_0$ to be of order $N$, give the condensation temperature scaling $$ T \sim \frac{h^{2}}{m k l^{2}} \frac{1}{\ln N}, $$ where $l \sim \sqrt{A/N}$ is the mean interparticle distance in the system.
```

## FrontierPhysics/train.parquet row=11 id=pathria/7.24

Verification passed: `False`
Metrics: jaccard=0.7826, content_jaccard=1.0, missing=0.1, added=0.1429, length_ratio=0.9826, doubled_latex=[]

Original:

```text
Calculate the photon number density, entropy density, and energy density of the 2.725K cosmic microwave background.
```

Partitioned:

```text
Calculate, of the 2.725K cosmic microwave background:
(a) the photon number density.
(b) entropy density.
(c) energy density.
```

## FrontierPhysics/train.parquet row=51 id=textbook/3.15

Verification passed: `True`
Metrics: jaccard=0.9448, content_jaccard=0.9571, missing=0.0552, added=0.0, length_ratio=0.9671, doubled_latex=[]

Original:

```text
Exercise 3.15. Consider a variable $x$ with range $(-\infty, +\infty)$ and a Gaussian distribution function $p(x) = \frac{1}{\sqrt{2\pi}\sigma} e^{-x^2/(2\sigma^2)}$. (i) Calculate $\int_{-\infty}^{+\infty} p(x)\,dx$. (ii) Calculate $\langle\langle x^{2n} \rangle\rangle$ for all positive integer $n$'s. (iii) Calculate $\langle\langle e^{-i\alpha x} \rangle\rangle$. (iv) Expand $e^{-i\alpha x}$ as a Taylor series in $x$, calculate the average for every single term, and resum the series.
```

Partitioned:

```text
Exercise 3.15. Consider a variable $x$ with range $(-\infty, +\infty)$ and a Gaussian distribution function $p(x) = \frac{1}{\sqrt{2\pi}\sigma} e^{-x^2/(2\sigma^2)}$.
(a) Calculate $\int_{-\infty}^{+\infty} p(x)\,dx$.
(b) Calculate $\langle\langle x^{2n} \rangle\rangle$ for all positive integer $n$'s.
(c) Calculate $\langle\langle e^{-i\alpha x} \rangle\rangle$.
(d) Expand $e^{-i\alpha x}$ as a Taylor series in $x$, calculate the average for every single term, and resum the series.
```

## FrontierPhysics/train.parquet row=106 id=textbook/12.2

Verification passed: `True`
Metrics: jaccard=0.9716, content_jaccard=1.0, missing=0.0214, added=0.0072, length_ratio=0.9861, doubled_latex=[]

Original:

```text
Assuming the Dietriche equation of state, $$P = \rho^2 \left( \frac{\partial e}{\partial \rho} \right)_s,\qquad P(v - b) = kT \exp\!\left(-\frac{a}{kTv}\right),$$ evaluate the critical constants $P_c$, $v_c$, and $T_c$ of the given system in terms of the parameters $a$ and $b$, and give the quantity $\frac{k T_c}{P_c v_c}$. - Further give the expression for the second virial coefficient $B_2$ for the Dietrici equation of state.
```

Partitioned:

```text
Assuming the Dietriche equation of state, $$P = \rho^2 \left( \frac{\partial e}{\partial \rho} \right)_s,\qquad P(v - b) = kT \exp\!\left(-\frac{a}{kTv}\right),$$
(a) evaluate the critical constants $P_c$, $v_c$, and $T_c$ of the given system in terms of the parameters $a$ and $b$.
(b) give the quantity $\frac{k T_c}{P_c v_c}$.
(c) Further give the expression for the second virial coefficient $B_2$ for the Dietrici equation of state.
```

## Physics-TTT/test.parquet row=12 id=mechanics/1_30

Verification passed: `True`
Metrics: jaccard=0.9605, content_jaccard=1.0, missing=0.0135, added=0.0267, length_ratio=0.9945, doubled_latex=[]

Original:

```text
Paris and London are connected by a straight subway tunnel (see Fig. 1.19). A train travels between the two cities powered only by the gravitational force of the earth. Calculate the maximum speed of the train and the time taken to travel from London to Paris. The distance between the two cities is 300 km and the radius of the earth is 6400 km. Neglect friction.
```

Partitioned:

```text
Paris and London are connected by a straight subway tunnel (see Fig. 1.19). A train travels between the two cities powered only by the gravitational force of the earth. The distance between the two cities is 300 km and the radius of the earth is 6400 km. Neglect friction.
Calculate:
(a) the maximum speed of the train.
(b) the time taken to travel from London to Paris.
```

## Physics-TTT/test.parquet row=30 id=electro/1_17

Verification passed: `True`
Metrics: jaccard=1.0, content_jaccard=1.0, missing=0.0, added=0.0, length_ratio=1.0, doubled_latex=[]

Original:

```text
The inside of a grounded spherical metal shell (inner radius $R_1$ and outer radius $R_2$) is filled with space charge of uniform charge density $\rho$. Find the electrostatic energy of the system. Find the potential at the center.
```

Partitioned:

```text
The inside of a grounded spherical metal shell (inner radius $R_1$ and outer radius $R_2$) is filled with space charge of uniform charge density $\rho$.
(a) Find the electrostatic energy of the system.
(b) Find the potential at the center.
```

## Physics-TTT/test.parquet row=103 id=quantum/5077

Verification passed: `True`
Metrics: jaccard=1.0, content_jaccard=1.0, missing=0.0, added=0.0, length_ratio=1.0, doubled_latex=[]

Original:

```text
A particle which moves only in the $x$ direction is confined between vertical walls at $x = 0$ and $x = a$. If the particle is in the ground state, what is the energy? Suppose the walls are suddenly separated to infinity; what is the probability that the particle has momentum of magnitude between $p$ and $p + dp$ ? What is the energy of such a particle?
```

Partitioned:

```text
A particle which moves only in the $x$ direction is confined between vertical walls at $x = 0$ and $x = a$.
(a) If the particle is in the ground state, what is the energy?
(b) Suppose the walls are suddenly separated to infinity; what is the probability that the particle has momentum of magnitude between $p$ and $p + dp$ ?
(c) What is the energy of such a particle?
```

## Physics-TTT/train.parquet row=70 id=Classical Mechanics/2-5

Verification passed: `True`
Metrics: jaccard=1.0, content_jaccard=1.0, missing=0.0, added=0.0, length_ratio=1.0, doubled_latex=[]

Original:

```text
Three identical masses are interconnected via three identical springs and the system is constrained to move along a hoop. Find the normal modes. Suppose you displace the top mass a bit and the masses are initially at rest, determine the subsequent motion of the system after letting go of the top mass.
```

Partitioned:

```text
Three identical masses are interconnected via three identical springs and the system is constrained to move along a hoop.
(a) Find the normal modes.
(b) Suppose you displace the top mass a bit and the masses are initially at rest, determine the subsequent motion of the system after letting go of the top mass.
```

## Physics-TTT/train.parquet row=284 id=atomic/4-46

Verification passed: `False`
Metrics: jaccard=0.9636, content_jaccard=0.9231, missing=0.0, added=0.0364, length_ratio=1.0116, doubled_latex=['\\\\text', '\\\\text', '\\\\pi', '\\\\pi']

Original:

```text
A $K_0^L$ meson $(Mc^2 = 498 \text{ MeV})$ decays into $\pi^+\pi^-$ $(mc^2 = 140 \text{ MeV})$ in flight. The ratio of the momentum of the $K_0^L$ to $Mc$ is $p/Mc = 1$. Find the maximum transverse component of momentum that any decay pion can have in the laboratory. Find the maximum longitudinal momentum that a pion can have in the laboratory.
```

Partitioned:

```text
A $K_0^L$ meson $(Mc^2 = 498 \\text{ MeV})$ decays into $\\pi^+\\pi^-$ $(mc^2 = 140 \\text{ MeV})$ in flight. The ratio of the momentum of the $K_0^L$ to $Mc$ is $p/Mc = 1$.
(a) Find the maximum transverse component of momentum that any decay pion can have in the laboratory.
(b) Find the maximum longitudinal momentum that a pion can have in the laboratory.
```

## Physics-TTT/train.parquet row=310 id=quantum/7010

Verification passed: `True`
Metrics: jaccard=0.9852, content_jaccard=1.0, missing=0.0075, added=0.0075, length_ratio=0.995, doubled_latex=[]

Original:

```text
Two identical nonrelativistic fermions of mass $m$, spin $1/2$ are in a one-dimensional square well of length $L$, with $V$ infinitely large and repulsive outside the well. The fermions are subject to a repulsive inter-particle potential $V(x_1 - x_2)$, which may be treated as a perturbation. Classify the three lowest-energy states in terms of the states of the individual particles and state the spin of each. Calculate (in first-order perturbation theory) the energies of second- and third-lowest states; leave your result in the form of an integral. Neglect spin-dependent forces throughout.
```

Partitioned:

```text
Two identical nonrelativistic fermions of mass $m$, spin $1/2$ are in a one-dimensional square well of length $L$, with $V$ infinitely large and repulsive outside the well. The fermions are subject to a repulsive inter-particle potential $V(x_1 - x_2)$, which may be treated as a perturbation. Neglect spin-dependent forces throughout.
(a) Classify the three lowest-energy states in terms of the states of the individual particles.
(b) state the spin of each.
(c) Calculate (in first-order perturbation theory) the energies of second- and third-lowest states; leave your result in the form of an integral.
```

## Physics-TTT/train.parquet row=669 id=atomic/3-11

Verification passed: `True`
Metrics: jaccard=1.0, content_jaccard=1.0, missing=0.0, added=0.0, length_ratio=1.0, doubled_latex=[]

Original:

```text
List all of the known leptons. How does $\mu^+$ decay?
```

Partitioned:

```text
(a) List all of the known leptons.
(b) How does $\mu^+$ decay?
```

## Physics-TTT/validation.parquet row=14 id=optics/2-53

Verification passed: `True`
Metrics: jaccard=0.9348, content_jaccard=1.0, missing=0.0444, added=0.0227, length_ratio=0.9826, doubled_latex=[]

Original:

```text
﻿ A transmission type diffraction grating having 250 lines/mm is illuminated with visible light at normal incidence to the plane of the grooves. What wavelengths appear at a diffraction angle of $30^\circ$, and what colors are they?
```

Partitioned:

```text
A transmission type diffraction grating having 250 lines/mm is illuminated with visible light at normal incidence to the plane of the grooves.
(a) What wavelengths appear at a diffraction angle of $30^\circ$?
(b) what colors are they?
```

## Physics-TTT/validation.parquet row=18 id=optics/2-35

Verification passed: `True`
Metrics: jaccard=0.964, content_jaccard=1.0, missing=0.0183, added=0.0183, length_ratio=0.9942, doubled_latex=[]

Original:

```text
﻿Light from a monochromatic point source of wavelength $\lambda$ is focused to a point image by a Fresnel half-period zone plate having 100 open odd half-period zones (1, 3, 5, \ldots, 199) with all even zones opaque. Compare the image dot intensity with that at the same point for the zone plate removed, and for a lens of the same focal length and diameter corresponding to 200 half-period zones of the zone plate. Assume the diameter of the opening is small compared to the distance from the source and the image.
```

Partitioned:

```text
﻿Light from a monochromatic point source of wavelength $\lambda$ is focused to a point image by a Fresnel half-period zone plate having 100 open odd half-period zones (1, 3, 5, \ldots, 199) with all even zones opaque. Assume the diameter of the opening is small compared to the distance from the source and the image. Compare the image dot intensity with that at the same point:
(a) for the zone plate removed.
(b) for a lens of the same focal length and diameter corresponding to 200 half-period zones of the zone plate.
```
