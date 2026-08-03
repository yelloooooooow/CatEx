# ADR 0007: Project-scoped experimental-modeling workbench

- Status: accepted
- Date: 2026-07-31
- Supersedes: none
- Extends: ADR 0006
- Credential handling superseded by: ADR 0008

## Context

ADR 0006 defines the scientific core for converting experimental
evidence and traceable parent structures into a finite representative model
set. A CLI alone makes the workflow too cumbersome for routine use and hides
important decisions such as measurement compatibility, provider provenance,
competing phase hypotheses, and the boundary between inference and writing.

The application must work across material systems. It cannot encode Ni-Mo as
the product architecture, require an LLM for routine structure operations, or
present a ranked candidate as the uniquely reconstructed real material.

## Decision

CatEx adds a project-scoped Experimental Models workspace and matching
versioned FastAPI routes.

The application is split into four layers:

1. strict evidence/spec schemas and deterministic scientific inference;
2. replaceable structure providers that materialize immutable local snapshots;
3. an optional schema-constrained GPT planning adapter;
4. a human review and content-bound materialization gate.

Project structures and the rule planner are always available. OPTIMADE access
is an explicit bounded network action. Materials Project access uses the
official `mp-api` client and requires `MP_API_KEY` in the server process.
Optional GPT planning uses the Responses API and requires `OPENAI_API_KEY`.
Credentials are never accepted by a project route, persisted, or returned.

Every inference run binds exact spec and catalog revisions. Reviews may approve
only representative candidates from the bound report. Write-back requires an
approved candidate, an exact report SHA-256 confirmation, and an explicit
write flag. The created POSCAR enters the existing project structure service,
so downstream DFT preparation does not need a second structure abstraction.

The workflow registry adds typed ports for evidence sets, structure catalogs,
candidate model sets, and reviewed model sets. The `experiment-to-dft`
template connects the review gate to the existing VASP path.

## Consequences

- Ordinary local use and new material systems do not depend on GPT.
- Provider APIs improve discovery but do not decide which model is true.
- Measurement conflicts, ambiguity, assumptions, and suggested next experiments remain
  visible in the primary interface.
- Database structure access is reproducible at the local snapshot level.
- The original environment-only credential decision is superseded by ADR 0008.
- The first XRD fitter is transparent and useful for ranking/regression, but is
  not a Rietveld engine and does not establish universal error tolerances.
- The Web service stores more immutable artifacts, trading disk space for
  auditability.
