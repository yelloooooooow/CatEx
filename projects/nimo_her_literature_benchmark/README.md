# Ni–Mo HER literature benchmark

This is a traceable software/scientific sanity check for the experiment-informed
modeling workflow. It is based on Y. Chen *et al.*, “Macroporous NiMo alloy
self-supporting electrodes for efficient hydrogen evolution at ultrahigh current
densities,” *Materials Advances* **4** (2023) 2868–2873,
DOI [10.1039/D3MA00151B](https://doi.org/10.1039/D3MA00151B).

## Inputs reproduced from the paper

- XRD: all reported diffraction peaks were indexed to Ni4Mo (JCPDS 65-5480).
- EDX: Ni:Mo atomic ratio 4:1.
- XPS: surface Mo:Ni molar ratio 1:4; metallic Mo and Ni components were
  reported, while O was present but not quantitatively assigned here.
- HRTEM: 0.208 nm fringe assigned to the MoNi4 (121) plane.

The two CSV files are deliberately simple exports resembling what a user can
drop into the CatEx page. `tests/test_nimo_literature_benchmark.py` runs the same
transparent extraction functions used by the web UI, so the researcher does not
write metadata JSON. `experiment.json` is the resulting auditable snapshot.

The numerical intervals around the published 4:1 ratios are CatEx's default
review tolerances when no uncertainty is supplied; they are not presented as
experimental error bars. Likewise, the raw XRD figure was not digitized, so this
benchmark supports a representative candidate claim rather than an independent
powder-pattern phase-identification claim.

The positive parent is the NIST JARVIS Ni4Mo structure JVASP-16581. Its reported
conventional cell is I4/m with a=b=5.729 Å and c=3.563 Å; these parameters give
d(121)=2.080 Å. The catalog also contains an explicit fcc-Ni negative control.

Run the saved audit snapshot:

```powershell
.\.venvs\catex-core-py312\Scripts\python.exe -m catex `
  infer-experimental-models `
  projects\nimo_her_literature_benchmark\experiment.json `
  --catalog projects\nimo_her_literature_benchmark\catalog.json `
  --format json
```

Expected outcome: `ready_for_review`, `candidate_only`, and all retained
representatives descend from the Ni4Mo parent. This does **not** establish the
unique real surface or the operando active structure.
