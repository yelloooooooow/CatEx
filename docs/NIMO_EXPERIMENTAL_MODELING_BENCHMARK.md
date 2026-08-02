# Ni–Mo experiment-informed modeling benchmark

## Purpose

This benchmark tests whether CatEx can turn ordinary characterization of an
electrodeposited Ni–Mo HER catalyst into a small, traceable **ensemble of
representative atomistic models**. It does not test recovery of a unique real
structure, because XRD, ICP, XPS, and TEM do not contain enough information to
make that claim for a heterogeneous, nanocrystalline, or reconstructed
electrode.

The primary scientific question is:

> Can CatEx retain the structurally different models that remain compatible
> with the measurements, reject models that conflict with them, and expose the
> unresolved choices that could change the DFT conclusion?

## Minimum practical evidence bundle

Synchrotron data are not a prerequisite. The first benchmark should accept the
following routine measurements, including partial bundles:

| Evidence | Required structured fields | What it can constrain | What it cannot establish alone |
| --- | --- | --- | --- |
| XRD/GIXRD | two-theta/intensity file, wavelength, scan range, substrate, geometry | crystalline phase families, lattice changes, approximate domain size, multiphase alternatives | a unique surface termination, amorphous local order, or catalytic active site |
| ICP-OES/MS | element, value, at.% or wt.%, uncertainty/replicates, sample stage | bulk elemental composition | surface enrichment or oxidation state |
| XPS | element/core level, assigned component, binding energy, fraction/range, fitting note, sample stage | surface composition and oxidation/hydroxylation hypotheses | atomic coordinates or an unambiguous bulk phase |
| TEM/HRTEM/SAED/EDS | d-spacing and tolerance, indexed plane if known, domain size, morphology/interface flags, local composition | local phases, lattice spacings, interfaces, crystallinity and size ranges | a statistically unique whole-electrode model from one field of view |

The sample stage (`as prepared`, `activated`, `working-state approximation`,
`post-reaction`, or `uncertain`) is optional metadata, not another experiment.
It prevents evidence from physically different states from being merged
silently. This is important for Ni–Mo because activation and operation may
remove Mo or change the oxygen coverage.

## Candidate families for the benchmark

The benchmark should deliberately contain competing model classes rather than
one favored structure:

1. ordered intermetallic Ni3Mo bulk and several low-index/stepped surfaces;
2. dilute substitutional Mo in fcc Ni, using enumerated cells and SQS models
   over the ICP composition interval;
3. Ni-rich/Mo-deficient variants representing activation or leaching;
4. Ni–Mo alloy surfaces with O/OH coverage appropriate to the electrochemical
   condition;
5. metal/oxide or hydroxide interfaces only when XPS/TEM support them;
6. Mo/NiMo and related metal/alloy interfaces when a distinct Mo phase is
   supported;
7. an unresolved disordered or amorphous motif ensemble when no crystalline
   parent explains the data.

These families are grounded in published modeling choices, but publication is
not treated as validation:

- Wijten et al. used the SEM-EDX Ni:Mo ratio to choose Ni3Mo, considered
  multiple BFDH facets and a stepped surface, and then showed experimentally
  that Mo leaching changes the catalyst during operation
  ([ChemSusChem 2019](https://doi.org/10.1002/cssc.201900617)).
- Pham et al. compared Ni3Mo (001), (020), (100), and (101) for alkaline HER
  rather than assuming one universal surface
  ([Applied Surface Science 2021](https://doi.org/10.1016/j.apsusc.2020.147894)).
- Zhao et al. modeled bimetallic NiMo centers in an electrodeposited and
  activated NiMo@Ni(OH)2MoOx composite
  ([Renewable Energy 2022](https://doi.org/10.1016/j.renene.2022.04.025)).
- Ma et al. compared an alloy with a Mo/NiMo heterojunction
  ([Journal of Alloys and Compounds 2023](https://doi.org/10.1016/j.jallcom.2022.167855)).
- Sousa et al. used a dilute Ni96Mo4 surface for a low-Mo electrodeposit,
  illustrating composition-matched substitutional modeling
  ([International Journal of Hydrogen Energy 2025](https://doi.org/10.1016/j.ijhydene.2025.05.272)).
- Zhang et al. combined DFT, surface Pourbaix analysis, and microkinetics and
  identified an O-covered Ni3Mo(111) working surface, illustrating why the
  operating state can matter more than the pristine slab
  ([Advanced Science 2026](https://doi.org/10.1002/advs.202518742)).

## Validation contract

There is no universal error tolerance that proves a model is real. Each gate
must be linked to the measurement uncertainty and to the decision being made.
The following values are starting points for the benchmark, not general laws:

- bulk composition: inside the reported ICP confidence interval; when no
  uncertainty is supplied, use a visible provisional gate of plus/minus
  2 at.% and mark it uncalibrated;
- XRD peak position: after an explicit global zero-shift fit, start with a
  0.25 degree peak-matching tolerance; rank by whole-pattern and peak-level
  evidence, not one best peak;
- TEM/SAED d-spacing: start with a 3 percent relative interval unless the
  experiment reports a different uncertainty;
- XPS component fractions: use the experimenter's fitted interval; if only a
  qualitative assignment exists, treat it as a soft categorical constraint,
  not a numerical target;
- relaxed bulk lattice parameters: a 1–3 percent discrepancy can be a useful
  DFT sanity check, but it is not evidence that a surface model is correct;
- HER activity: do not equate one experimental overpotential with one
  calculated hydrogen adsorption free energy. In alkaline HER, compare at
  least hydrogen binding, water dissociation, surface stability/coverage, and
  then a kinetic or ranking observable.

A candidate passes only the observables that are physically applicable to it.
For example, powder XRD can support the parent bulk phase but cannot directly
select a slab termination. The output is a Pareto-ranked ensemble with a table
of passed, failed, and unavailable observables.

## Software implementation plan

### P0 — current v0.32.2 baseline

- local and database-backed parent structures;
- bounded substitutions, vacancies, strain, supercells, and slabs;
- transparent XRD simulation/ranking and multiphase combinations;
- state-aware evidence records, scoped composition intervals, provenance,
  human confirmation, and explicit project write;
- read-only 3D candidate inspection with atom identity and coordinates.

This baseline is a candidate-management and XRD-ranking system. ICP/EDS
composition intervals affect candidate checks, but raw ICP, XPS, and TEM data
are not yet parsed into complete forward-model scores.

### P1 — structured routine-characterization input

- add table editors and CSV templates for ICP, XPS components, and TEM/SAED
  spacings;
- parse common two-column XRD exports and store units, instrument settings,
  substrate, uncertainty, and sample stage;
- keep raw files immutable and derive reviewable normalized records;
- allow bulk, surface, and local composition ranges for the same element;
- show missing metadata as a warning with a usable fallback, not a hard block
  unless the numerical comparison would be invalid.

Potential reusable components include
[GSAS-II](https://github.com/AdvancedPhotonSource/GSAS-II) or
[XERUS](https://github.com/pedrobcst/Xerus) for diffraction refinement,
[lmfitxps](https://github.com/Julian-Hochhaus/lmfitxps) for XPS line-shape
building blocks, and [HyperSpy](https://hyperspy.org/) / [pyxem](https://pyxem.org/)
for microscopy and diffraction data. They should be optional adapters behind a
stable CatEx evidence schema, not mandatory heavyweight dependencies.

### P2 — broader candidate generation

- integrate SQS generation for substitutionally disordered alloys, for
  example with [icet](https://icet.materialsmodeling.org/advanced_topics/sqs_generation.html);
- enumerate composition-compatible substitutions and vacancies with symmetry
  reduction and deterministic seeds;
- add traceable builders for alloy/oxide, alloy/hydroxide, and metal/alloy
  interfaces;
- add state-conditioned O/OH/H coverages and retain all low-energy plausible
  terminations;
- represent poorly crystalline samples as motif ensembles rather than a fake
  periodic "amorphous crystal".

### P3 — calibrated evidence fusion

- add diffraction refinement adapters and nuisance-parameter calibration;
- forward-calculate d-spacings and surface/bulk composition observables;
- score hard failures separately from soft ranking evidence;
- add Pareto and approximate-Bayesian ranking with uncertainty propagation;
- calibrate gates on synthetic patterns, published open datasets, and held-out
  in-house measurements.

Related designs worth borrowing are
[XERUS](https://doi.org/10.1002/adts.202100588) for database-to-XRD automation,
[XMatcher](https://arxiv.org/abs/2607.17162) for interpretable peak-level and
multiphase evidence, and
[DiffPy structure-mining](https://doi.org/10.1107/S1600576719014684) for
database candidate screening against total-scattering PDF. CatEx's distinct
role is to combine several inexpensive measurements and carry the accepted
models into a traceable DFT workflow.

### P4 — Ni–Mo HER calculation benchmark

For each retained family, use a converged and consistent protocol to calculate:

1. bulk/interface stability and segregation or vacancy tendencies;
2. surface free-energy/coverage ordering over the relevant potential-pH range;
3. hydrogen adsorption across representative sites and coverages;
4. alkaline Volmer water-dissociation barriers for the leading surfaces;
5. selected microkinetic trends only after the thermodynamic model is stable.

The first target is reproduction of **qualitative decisions** in the papers:
which phase family, interface, or working-surface model remains plausible and
how activity rankings change. Numerical agreement with a published DFT value
is a unit benchmark for the protocol, not proof that the experimental sample
has that structure.

## Acceptance sequence

1. Run the existing synthetic Ni–Mo case to test deterministic software
   behavior.
2. Rebuild the model choices from the 2019 electrodeposited Ni–Mo study using
   only its reported ordinary characterization, then check whether CatEx keeps
   Ni3Mo and the relevant surface variants without claiming uniqueness.
3. Test a dilute alloy case against the 2025 Ni96Mo4 modeling choice.
4. Test interface generation against the 2022 composite and 2023 Mo/NiMo
   studies.
5. Test state-conditioned coverage and mechanism ranking against the 2026
   O-covered Ni3Mo study.
6. Freeze thresholds, then process one in-house electrodeposited Ni–Mo sample
   without tuning the rules to its expected answer.

The benchmark succeeds when CatEx produces a compact candidate ensemble,
explains every rejection and retained ambiguity, preserves source and
transformation provenance, and shows whether the scientific conclusion is
stable across the remaining models.

## Role of an optional language-model API

An API is useful for literature retrieval, translating free-text experimental
notes into a proposed schema, and suggesting bounded candidate operations. It
is not required for chemical-system generality and must not decide whether a
model passes. Database queries, structure transformations, forward simulation,
constraint checks, deduplication, and scoring remain deterministic local code.
All AI proposals must compile to the allowlisted recipe schema and pass the
same validators as a manually created recipe.
