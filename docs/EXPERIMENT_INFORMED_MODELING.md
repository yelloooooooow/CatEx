# Experiment-informed representative atomistic modeling

## Status and scientific contract

CatEx `v0.33` provides a local-first vertical slice from inexpensive
characterization evidence to reviewable, DFT-ready representative structures.
It does **not** claim to reconstruct the unique real atomic structure of a
heterogeneous material.

The implemented contract is:

```text
workbench inputs (internally normalized to JSON) + evidence artifacts + structure catalog
    -> automatically extracted, reviewable evidence constraints
    -> composition-filtered parent structures
    -> transparent single/multiphase XRD hypotheses
    -> bounded candidate recipes
    -> deterministic structure generation and validation
    -> representative model set, ambiguity, and next-experiment advice
```

The default workflow performs no network calls and no writes. Structure files
are written only by the explicit `materialize-experimental-models` command, and
only into a destination that does not already exist.

## What is implemented

- Evidence kinds: XRD/GIXRD, ICP, EDS, XPS, Raman, SEM, TEM, synthesis,
  electrochemistry, literature, and other.
- Evidence roles: hard, soft, and contextual.
- Independent optional XRD, ICP, EDS, XPS, and TEM inputs; no modality is
  required just to generate candidates.
- Automatic extraction from common text/CSV tables, instrument notes, and
  English or Chinese short conclusions, including explicit phase formulas and
  Å/nm lattice-spacing conversion.
  The workbench creates the structured metadata and constraints; users do not
  write JSON.
- Total-atomic, metal-normalized, and weight composition bases with bulk,
  surface, and local scopes.
- XPS-derived local coordination ranges and TEM/SAED d-spacing ranges as
  transparent compatibility checks.
- Path-free evidence identities using SHA-256, artifact basename, and size.
- Path-confined local structure catalogs with source kind, locator, license,
  citation, artifact hash, and structure hash.
- A bounded candidate-recipe DSL:
  - identity
  - diagonal supercell
  - explicit site substitution
  - explicit site vacancy
  - bounded isotropic strain (at most 10 percent)
  - low-index slab generation with all retained terminations
  - orthogonal c-axis vacuum reset
  - deterministic composition matching
  - bounded surface coordination motifs
- Powder-XRD forward simulation using pymatgen.
- Explicit nuisance grids for global two-theta shift and Gaussian FWHM.
- One-to-one matched peaks, missing predicted peaks, and unexplained observed
  peaks.
- Single-phase ranking and up-to-three-phase shared-nuisance non-negative
  fitting.
- Rule planner and optional schema-constrained GPT planner.
- Geometry and chemistry diagnostics, fail-closed recipe execution, candidate
  deduplication, representative selection, and unresolved-hypothesis retention.
- POSCAR/CIF materialization with a content-bound manifest.
- Read-only 3D candidate inspection with atom selection, element/index and
  coordinate details, composition counts, cell lengths, and optional index
  labels.

Measurement conditions stay attached to each evidence record. If measurements
came from materially different specimens or treatments, record that fact in
the short conclusion or instrument/condition field. CatEx keeps those notes
with the evidence and does not pretend that a generic lifecycle label can
reconcile incompatible measurements.

## Deliberate limitations

- XRD evidence scores are ranking quantities, not calibrated posterior
  probabilities.
- Multiphase non-negative weights are diffraction-profile contributions, not
  mass or volume fractions.
- The transparent XRD baseline is not a Rietveld replacement. DARA, GSAS-II,
  CrystalShift, and other refinement engines should be integrated behind a
  future backend interface after licensing and reproducibility evaluation.
- Ordinary XPS, Raman, SEM, or TEM summaries are categorical or interval
  constraints. They do not uniquely generate atomic coordinates.
- A slab inherits support for its parent bulk phase. Powder XRD does not
  directly validate a particular surface termination.
- The v1 planner does not invent oxide, hydroxide, interface, or amorphous
  coordinates when no traceable parent structure is available. Such hypotheses
  remain unresolved and are reported.
- There is no universal acceptable Rwp, evidence score, or DFT-property
  tolerance. Thresholds are explicit provisional gates that must be calibrated
  for a fixed benchmark and decision.

## Experiment specification

The JSON document uses `catex.experiment-spec.v1`:

```json
{
  "schema_version": "catex.experiment-spec.v1",
  "sample_id": "tu-nimo-01",
  "material_pack": "alloy-electrocatalyst",
  "allowed_elements": ["Ni", "Mo", "O"],
  "excluded_elements": [],
  "composition_constraints": [
    {
      "element": "Ni",
      "minimum_atomic_fraction": 0.60,
      "maximum_atomic_fraction": 0.80,
      "scope": "bulk",
      "basis": "total_atomic_fraction",
      "evidence_ids": ["icp-composition"]
    }
  ],
  "evidence": [
    {
      "evidence_id": "xrd-pattern",
      "kind": "xrd",
      "role": "hard",
      "artifact": "xrd.xy",
      "metadata": {
        "radiation": "CuKa",
        "substrate": "Ni foam"
      }
    }
  ]
}
```

Unknown fields, duplicate evidence IDs, invalid element symbols, infeasible
composition intervals, missing artifacts, and artifact path traversal are
rejected. Artifact paths are resolved relative to the experiment JSON and are
not serialized into the scientific report.

The JSON form above is primarily an API/CLI contract. In the Web workbench the
researcher chooses a method, optionally uploads a file, and enters a short
conclusion and instrument/condition text. CatEx generates this structure,
displays extracted ranges for correction, and keeps raw spectra or images
without inventing numerical interpretations it cannot justify.

## Local structure catalog

The catalog uses `catex.structure-catalog.v1`:

```json
{
  "schema_version": "catex.structure-catalog.v1",
  "provider": "local-nimo",
  "entries": [
    {
      "record_id": "nimo-parent-01",
      "path": "structures/nimo.cif",
      "source_kind": "literature",
      "source_locator": "doi-or-SI-identifier",
      "license": "verify-before-redistribution",
      "citation": "Exact source of the supplied CIF"
    }
  ]
}
```

All structure paths must remain inside the directory containing the catalog.
Use actual CIF/SI coordinates. A structure inferred only from a paper figure
must be labeled `hypothetical`, not `literature`.

### Optional OPTIMADE import

Remote discovery is deliberately separated from inference. The following
explicit command performs a bounded HTTPS read from one configured OPTIMADE
provider and writes an ordinary, reusable local catalog:

```powershell
catex fetch-optimade-catalog https://example-provider.org `
  --provider-id example-provider `
  --element Ni `
  --element Mo `
  --maximum-results 100 `
  --maximum-pages 5 `
  --license "verify provider terms" `
  --citation "record the provider/version here" `
  --destination downloaded-nimo-catalog `
  --format json
```

Only ordered, fully occupied, three-dimensionally periodic structures are
accepted in v1. Pagination cannot leave the configured HTTPS host, result/page
counts are bounded, opaque remote IDs are converted to safe local IDs, and the
report records accepted/skipped counts and diagnostics. The resulting
`downloaded-nimo-catalog/catalog.json` is then passed to the normal offline
inference command. CatEx does not silently contact every database, and it
cannot infer a provider's license or the correct literature citation for the
user.

### Optional Materials Project import

The Web workbench can explicitly query Materials Project through the official
`mp-api` client. Enter the key in the Materials Project credential card and
select **Verify and save securely**. CatEx verifies the key before replacing
any existing value, then stores it in the operating-system credential manager.
On Windows this is Windows Credential Manager rather than a CatEx file.

Environment variables remain an automation fallback and take precedence over
the system credential:

```powershell
$env:MP_API_KEY = "<your rotated Materials Project key>"
pnpm web:poc
```

Do not put a real key in a project field, exported bundle, Git file, or support
log. The dedicated password field holds the value only long enough to send it
to the loopback backend and clears immediately on submission. It is never
written to browser storage. Capability and mutation responses report only
status/source metadata. A search records the database version and result
provenance in an immutable local catalog snapshot; it never records the key.
Rotate any key that has previously been pasted into chat or another persistent
message.

## Web workbench

Open a project and select **Experimental Models / 实验建模**. The page follows
five explicit stages:

1. identify the sample and target lifecycle state;
2. upload bounded evidence artifacts and describe their role/scope;
3. select project structures or explicitly fetch an OPTIMADE/Materials Project
   snapshot;
4. run the deterministic rule planner, or the optional GPT planner;
5. inspect competing phases and candidates, record a human review, then
   explicitly materialize approved structures into the project.

Specs, catalogs, runs, reviews, and materializations are append-oriented
records under the project `experimental-modeling/` directory. Uploaded evidence
is content addressed. A run is bound to exact spec and catalog revisions.
Materialization requires all of:

- a representative candidate from the bound run;
- an explicit positive review containing that candidate;
- the exact report SHA-256 copied from the run;
- `approved_write=true`.

The Web page provides separate password inputs for Materials Project and
OpenAI. Each key is verified before it is stored in the system credential
manager. A user can remove either stored key from the same page. Provider and
GPT capability responses show only readiness, source (`environment` or
`system_keyring`), and whether a system entry exists; they never return a
credential value. The rule planner and project-local structures remain usable
without any API or agent.

## CLI

Read-only inference:

```powershell
catex infer-experimental-models experiment.json `
  --catalog catalog.json `
  --format json
```

Explicitly write selected candidates into a new directory:

```powershell
catex materialize-experimental-models experiment.json `
  --catalog catalog.json `
  --destination output-models `
  --format json
```

The command refuses an existing destination. Each selected candidate receives
`POSCAR`, `structure.cif`, and a top-level content-bound manifest.

For the staged validation plan using ordinary XRD, ICP, XPS, and TEM evidence,
see the [Ni–Mo experiment-informed modeling benchmark](NIMO_EXPERIMENTAL_MODELING_BENCHMARK.md).

Optional GPT planning:

```powershell
$env:OPENAI_API_KEY = "set outside CatEx"
catex infer-experimental-models experiment.json `
  --catalog catalog.json `
  --planner gpt `
  --model YOUR_EXPLICIT_MODEL_ID `
  --format json
```

For CLI use, the API key is read from the environment at request time. Web
users may instead save it in the operating-system credential manager. The GPT
output is a strict plan containing only known evidence IDs, known
parent-reference keys, and allowlisted operations. Local validators remain
authoritative, and arbitrary generated Python is never executed.

## Interpretation of status

| Status | Meaning |
| --- | --- |
| `ready_for_review` | At least one valid representative exists and the XRD library reaches the configured support gate. Human scientific review is still required. |
| `insufficient_evidence` | Candidates exist, but the evidence supports only candidate-level claims. |
| `no_valid_candidates` | No recipe produced a valid representative. |
| `error` | A report-level invariant failed. |

Claim ceilings are independent of status:

- `no_atomic_claim`
- `candidate_only`
- `phase_family_supported`
- `structural_variant_supported`

The v1 workflow intentionally stops at `phase_family_supported`; it does not
promote a low-cost characterization set to unique surface-structure support.

## Recommended validation ladder

1. Synthetic single phases, binary/ternary mixtures, noise, shift, broadening,
   substrate peaks, and missing-library cases.
2. DARA commercial precursor mixtures.
3. A fixed, leakage-controlled labeled subset of opXRD.
4. Literature structures with exact CIF/SI provenance.
5. MoNi4 and NiMo/NiMoOx reconstructions.
6. User electrodeposited Ni-Mo, separated into as-prepared, activated, and
   post-mortem states.

Primary metrics should include candidate recall at K, unexplained peak evidence,
invalid-candidate rejection, duplicate rate, calibration error where genuine
probabilities are emitted, abstention behavior, provenance completeness,
robustness to nuisance choices, and downstream DFT conclusion stability.

## Backend extension boundary

Future providers and refinement engines must preserve the current evidence
contract. A backend must report:

- exact input artifact hashes and instrument metadata;
- database/provider version and structure provenance;
- fitted nuisance and physical parameters;
- supporting and contradictory evidence;
- score semantics and whether calibration has been performed;
- phase-fraction semantics;
- failure and abstention states;
- third-party license and redistribution requirements.

The initial transparent baseline remains useful even after adding a mature
backend because it provides an inspectable regression oracle.
