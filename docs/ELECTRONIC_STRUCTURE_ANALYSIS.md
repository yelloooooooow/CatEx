# Electronic-structure analysis and generic integration acceptance

PR-016 adds a pure numerical layer for caller-parsed DOS/PDOS, collinear magnetic moments,
and charge-partition populations. The layer has no file parser, path, SSH, scheduler, write, or
job-submission capability. An adapter must parse external artifacts and supply their lowercase
SHA256 values before these functions can run. All three inputs declare the total site count, which
is rechecked against the reviewed adsorption configuration before reports can be combined.

## DOS and PDOS

`DensityOfStatesInput` contains a strictly increasing absolute energy grid, an explicit Fermi
energy, non-negative total DOS, optional paired spin-up/spin-down arrays, and typed projected
series. Each projected series declares its site indices, `s/p/d/f` orbital family, and spin
channel. Array lengths, finite values, source hashes, unique labels, and energy-window coverage
are checked fail closed.

`analyze_density_of_states` reports:

- linearly interpolated total DOS at the Fermi level;
- `(DOS_up - DOS_down) / (DOS_up + DOS_down)` when both spin arrays are supplied;
- for every explicit d-projected series, its integrated weight, first moment relative to the
  Fermi level, and square-root second central moment in a caller-selected, fully covered window.

The API does not sum unspecified orbitals, infer an active site, decide metallicity, assign a
bonding mechanism, or turn a d-band center into an activity conclusion.

## Magnetism and charge

`analyze_magnetism` receives one finite collinear moment per site plus explicit active-site
indices. It reports signed and absolute sums for the full system and active subset. It does not
assign oxidation state, ferro-/antiferromagnetic order, or a ground-state multiplicity.

`analyze_charge_partition` receives electron populations, matching neutral-reference valence
populations, a declared Bader/DDEC/other method, and active-site indices. The per-site convention
is:

```text
electron deficit = reference valence population - partitioned electron population
```

A positive deficit therefore means electron loss under that declared partition scheme. It is not
an automatically assigned formal oxidation state.

## Provenance and review gate

Every analysis is bound to one adsorption-configuration identity and one or more source artifact
hashes. Parser names are retained, source hashes are canonicalized, and each report has a
deterministic content hash. `summarize_electronic_structure` rechecks those hashes and requires
the upstream catalyst/site/adsorbate/configuration four-identity approval gate.

The resulting summary always states that manual interpretation is required and that no automatic
scientific conclusion was performed. SHA256 provides integrity and provenance, not user identity
authentication or a digital signature.

## Non-Paper-4 integration benchmark

`projects/reference_pt_co_adsorption/` documents the synthetic Pt/CO acceptance case implemented
by `tests/test_nonpaper4_end_to_end.py`. It executes the generic chain from a reviewed vacuum
transformation through adsorption placement, multi-spin planning, a balanced/reviewed synthetic
adsorption free energy, and electronic summaries. It uses pytest temporary files only for the
existing synthetic VASP-output fixtures and does not contact an HPC system.

This benchmark proves that the core is not selected by `project_purpose` and does not require
Paper-4-specific DAC, metal-pair, or CO2RR constants. Its numerical values are test data, not
research results.
