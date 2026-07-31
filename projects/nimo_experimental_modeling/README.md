# Ni-Mo experiment-informed modeling example

This is a **synthetic software acceptance case**, not a scientific
identification of an electrodeposited Ni-Mo catalyst.

The example demonstrates:

- separate as-prepared and activated sample states;
- bulk Ni/Mo composition intervals;
- a local structure catalog containing ideal Ni, Mo, and hypothetical B2-NiMo;
- an as-prepared synthetic diffraction trace;
- activated-state XPS metadata that triggers an unresolved oxygenated-surface
  hypothesis rather than fabricated O coordinates;
- rule-based generation of bulk references and low-index slabs;
- explicit warnings when the target state and XRD state differ.

Run from the repository root:

```powershell
.\.venvs\catex-core-py312\Scripts\python.exe -m catex `
  infer-experimental-models `
  projects\nimo_experimental_modeling\experiment.json `
  --catalog projects\nimo_experimental_modeling\catalog.json `
  --format json
```

To write representatives, select a destination that does not yet exist:

```powershell
.\.venvs\catex-core-py312\Scripts\python.exe -m catex `
  materialize-experimental-models `
  projects\nimo_experimental_modeling\experiment.json `
  --catalog projects\nimo_experimental_modeling\catalog.json `
  --destination output\nimo-representatives `
  --format json
```

Replace the synthetic pattern and hypothetical structures with raw local data
and exact CIF/SI provenance before scientific use.
