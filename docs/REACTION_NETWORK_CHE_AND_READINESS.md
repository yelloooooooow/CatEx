# Reaction networks, CHE, and production-readiness gates

PR-017 closes the code-side Paper 4 integration baseline with three independent pieces: a
generic reaction-network identity, an explicitly reviewed computational hydrogen electrode
(CHE) correction, and a non-authorizing scientific-case readiness report.

## Reaction network

`create_reaction_network` accepts only intact, element- and charge-balanced
`ReactionDefinition` objects. It canonicalizes reaction/state order, rejects duplicate reaction
IDs and conflicting state identities, constructs directed reactant-to-product connectivity, and
can require named terminal states to be reachable from named starts. Connectedness and
reachability are validation rules, not automatic mechanism selection.

The resulting `catex.reaction-network.v1` still requires one explicit hash-bound human review.
`assess_reaction_network_readiness` enables pathway planning only after exactly one valid
approval. It always keeps `execution_authorized=false`; network review is not permission to run
or submit calculations.

## Computational hydrogen electrode

`ComputationalHydrogenElectrodeProtocol` explicitly records:

- SHE or RHE potential scale;
- electrode potential in volts;
- pH;
- temperature in kelvin;
- method/source description and source artifact SHA256 values.

The protocol is an immutable reaction-domain definition and must be reviewed separately. The
application accepts an exact integer/rational signed number of proton-electron pairs. Positive
means the written reduction step consumes `H+ + e-`; negative means it produces pairs. In eV,
the implemented convention is:

```text
ΔG(U,pH) = ΔG(0,0) + n·U + n·kB·T·ln(10)·pH    [SHE]
ΔG(U_RHE) = ΔG(0,0) + n·U_RHE                  [RHE]
```

Thus a negative potential lowers the free energy of a step with positive consumed-pair count.
For RHE, the pH contribution is already absorbed into the potential scale and the separately
reported pH correction is exactly zero. The function refuses a zero pair count, non-exact float
stoichiometry, incomplete base thermochemistry, missing CHE review, or missing/non-finite
temperature. It does not propagate uncertainty or infer a rate-limiting step.

## Scientific-case readiness

Each `ScientificCaseRequirement` records a category, required/optional flag, explicit
`satisfied`/`blocked`/`not_applicable` status, evidence hashes, human assessor, UTC timestamp,
and note. A satisfied item must contain evidence; required items cannot be marked not applicable.
The combined report is hash-bound and ready only when every required item is satisfied.

Even a fully ready report keeps `execution_authorized=false`. Submission authority, destination,
resource scope, and retention/cleanup permission remain separate operational decisions.

## Paper 4 state

The Paper 4 project now contains executable/readable planning artifacts:

- `production-readiness.json`: 3 evidence-backed satisfied requirements and 10 explicit blockers;
- `reaction-network-draft.json`: conceptual CO and HCOOH branches with null scientific identities;
- `che-protocol-draft.json`: SHE, U=0 V and pH=0 are recorded, while the missing temperature is null;
- `thermochemistry-requirements.json`: every unknown state correction is null, never a fake zero.

Tests reconstruct the readiness report, validate every evidence digest and rehash each reviewed
artifact available in the checkout. Reviewed Git text uses `canonical_text_evidence_sha256`, which
normalizes CRLF/CR to LF before UTF-8 hashing so Windows and Linux audit the same logical content.
Binary artifacts and scientifically byte-significant sources must still use raw byte SHA256.
Copyright/data-policy-excluded local sources are not required to exist in CI. Tests also confirm
both reaction branches remain identity-blocked, reject the incomplete CHE protocol, and ensure all
missing thermochemical values stay null.

The code-side workflow is complete, but the actual Paper 4 production science remains blocked by
author-equivalent coordinates/constraints, a production storage policy, reviewed per-variant
protocols, the nitrogen chemical-potential reference, per-state thermochemistry and temperature,
the Table S2 interpretation conflict, and accepted production runs. No HPC connection, input
materialization, submission, modification, or deletion is performed by PR-017.
