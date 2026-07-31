# ADR-0006: Experiment-informed representative modeling

## Status

Accepted for CatEx `v0.31`.

## Context

The dominant uncertainty in applying DFT to synthesized heterogeneous
catalysts is often the mapping from a real, evolving sample to a tractable
atomistic model. Low-cost characterization does not uniquely determine atomic
coordinates. Existing projects solve phase search, refinement, structure
generation, or agent orchestration separately, but CatEx needs a traceable
boundary between experimental evidence and its existing DFT workflow.

## Decision

Add `catex.experimental` as a scientific-core module with the following
separation:

1. Evidence records are state-aware, immutable, and path-free.
2. Parent structures come from pluggable providers with explicit provenance.
3. Planners emit a bounded recipe DSL, never executable source code.
4. Deterministic local code executes and validates every recipe.
5. XRD search retains multiple hypotheses and exposes counter-evidence.
6. Surface models inherit support only for their parent bulk phase.
7. Reports contain a claim ceiling, ambiguity, unresolved hypotheses, and
   affordable next-experiment recommendations.
8. The default planner is deterministic and offline.
9. GPT is an optional, replaceable planning adapter using structured output.
10. Structure materialization is a separate explicit command that creates only
    a new destination.

## Consequences

- The system can be useful without an API key.
- A new chemistry is supported through structure providers and material packs,
  not by hard-coding Ni-Mo.
- GPT failures cannot bypass local validation.
- The workflow can honestly return several candidates or no atomic claim.
- DARA/BGMN, GSAS-II, CrystalShift, XMatcher, and generative PXRD models remain
  replaceable backends rather than architectural dependencies.
- The v1 baseline cannot make quantitative Rietveld or unique amorphous,
  interface, or operando claims.

## Rejected alternatives

- **One unconstrained LLM that writes and executes pymatgen Python.** Rejected
  because it is difficult to validate, secure, reproduce, and audit.
- **A unique Top-1 structure output.** Rejected because low-cost multimodal
  characterization is underdetermined.
- **Direct coordinate optimization against XRD similarity.** Rejected because
  similar profiles need not imply structurally correct coordinates.
- **Mandatory cloud database and GPT access.** Rejected because CatEx is
  local-first and experimental data may be unpublished.
- **Bundling a Rietveld backend immediately.** Rejected pending benchmark,
  runtime, and license evaluation.
