"""Versioned records for experiment-informed atomistic model inference.

The records in this module deliberately separate observations, hypotheses,
recipes, and accepted runtime structures.  A good fit is evidence for a model;
it is not promoted to proof that the model is the unique real structure.
"""

from __future__ import annotations

import hashlib
import json
import math
import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from enum import StrEnum
from types import MappingProxyType
from typing import Any

from catex.models import Diagnostic

_IDENTIFIER = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}$")
_SHA256 = re.compile(r"^[0-9a-f]{64}$")


def content_digest(payload: Mapping[str, Any]) -> str:
    """Return a deterministic digest for one JSON-compatible payload."""

    encoded = json.dumps(
        payload,
        allow_nan=False,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _identifier(value: str, *, field_name: str) -> str:
    if not isinstance(value, str) or _IDENTIFIER.fullmatch(value) is None:
        raise ValueError(f"{field_name} must be a safe identifier of at most 128 characters")
    return value


def _one_line(value: str, *, field_name: str, maximum: int, allow_empty: bool = False) -> str:
    if not isinstance(value, str) or "\n" in value or "\r" in value:
        raise ValueError(f"{field_name} must be one line")
    normalized = value.strip()
    if (not normalized and not allow_empty) or len(normalized) > maximum:
        qualifier = "possibly empty and " if allow_empty else ""
        raise ValueError(f"{field_name} must be {qualifier}at most {maximum} characters")
    return normalized


def _json_mapping(value: Mapping[str, Any], *, field_name: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise ValueError(f"{field_name} must be a mapping")
    normalized = dict(sorted(value.items()))
    try:
        json.dumps(normalized, allow_nan=False, ensure_ascii=False, sort_keys=True)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{field_name} must contain finite JSON-compatible values") from exc
    return MappingProxyType(normalized)


def _identifiers(values: Sequence[str], *, field_name: str) -> tuple[str, ...]:
    result = tuple(_identifier(item, field_name=field_name) for item in values)
    if len(result) != len(set(result)):
        raise ValueError(f"{field_name} must not contain duplicates")
    return result


class EvidenceKind(StrEnum):
    """Experimental or documentary evidence types supported by the v1 contract."""

    XRD = "xrd"
    GIXRD = "gixrd"
    ICP = "icp"
    EDS = "eds"
    XPS = "xps"
    RAMAN = "raman"
    SEM = "sem"
    TEM = "tem"
    SYNTHESIS = "synthesis"
    ELECTROCHEMISTRY = "electrochemistry"
    LITERATURE = "literature"
    OTHER = "other"


class EvidenceRole(StrEnum):
    """How strongly a record constrains candidate construction."""

    HARD = "hard"
    SOFT = "soft"
    CONTEXT = "context"


class CompositionScope(StrEnum):
    """Spatial scope represented by one composition constraint."""

    BULK = "bulk"
    SURFACE = "surface"
    LOCAL = "local"
    UNSPECIFIED = "unspecified"


class CompositionBasis(StrEnum):
    """Denominator used by one reported composition interval."""

    TOTAL_ATOMIC_FRACTION = "total_atomic_fraction"
    METAL_NORMALIZED_ATOMIC_FRACTION = "metal_normalized_atomic_fraction"
    WEIGHT_FRACTION = "weight_fraction"


class StructureSourceKind(StrEnum):
    """Provenance class for a parent periodic structure."""

    EXPERIMENTAL = "experimental"
    DFT_RELAXED = "dft_relaxed"
    DATABASE = "database"
    LITERATURE = "literature"
    USER_SUPPLIED = "user_supplied"
    HYPOTHETICAL = "hypothetical"


class CandidateOperationKind(StrEnum):
    """Allowlisted operations in the candidate recipe DSL."""

    IDENTITY = "identity"
    SUPERCELL = "supercell"
    SUBSTITUTE = "substitute"
    VACANCY = "vacancy"
    ISOTROPIC_STRAIN = "isotropic_strain"
    SLAB = "slab"
    SET_VACUUM = "set_vacuum"
    MATCH_COMPOSITION = "match_composition"
    ADD_SURFACE_COORDINATION = "add_surface_coordination"


class ModelKind(StrEnum):
    """Coarse physical role of a generated atomistic model."""

    BULK = "bulk"
    SURFACE = "surface"


class ClaimLevel(StrEnum):
    """Maximum defensible interpretation of the current evidence."""

    NO_ATOMIC_CLAIM = "no_atomic_claim"
    CANDIDATE_ONLY = "candidate_only"
    PHASE_FAMILY_SUPPORTED = "phase_family_supported"
    STRUCTURAL_VARIANT_SUPPORTED = "structural_variant_supported"


class InferenceStatus(StrEnum):
    """Fail-closed state of an experiment-informed inference run."""

    READY_FOR_REVIEW = "ready_for_review"
    INSUFFICIENT_EVIDENCE = "insufficient_evidence"
    NO_VALID_CANDIDATES = "no_valid_candidates"
    ERROR = "error"


@dataclass(frozen=True, slots=True)
class EvidenceArtifact:
    """Path-free identity of a local evidence artifact."""

    name: str
    sha256: str
    size_bytes: int

    def __post_init__(self) -> None:
        object.__setattr__(self, "name", _one_line(self.name, field_name="name", maximum=255))
        if _SHA256.fullmatch(self.sha256) is None:
            raise ValueError("sha256 must be a lowercase SHA256 digest")
        if not isinstance(self.size_bytes, int) or isinstance(self.size_bytes, bool):
            raise ValueError("size_bytes must be an integer")
        if self.size_bytes < 0:
            raise ValueError("size_bytes must be non-negative")

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "sha256": self.sha256,
            "size_bytes": self.size_bytes,
        }


@dataclass(frozen=True, slots=True)
class EvidenceRecord:
    """One observation with an explicit epistemic role."""

    evidence_id: str
    kind: EvidenceKind
    role: EvidenceRole
    metadata: Mapping[str, Any] = field(default_factory=dict)
    artifact: EvidenceArtifact | None = None
    note: str = ""
    schema_version: str = "catex.experimental-evidence.v1"

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "evidence_id",
            _identifier(self.evidence_id, field_name="evidence_id"),
        )
        object.__setattr__(
            self,
            "metadata",
            _json_mapping(self.metadata, field_name="metadata"),
        )
        object.__setattr__(
            self,
            "note",
            _one_line(self.note, field_name="note", maximum=1000, allow_empty=True),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "evidence_id": self.evidence_id,
            "kind": self.kind.value,
            "role": self.role.value,
            "metadata": dict(self.metadata),
            "artifact": self.artifact.to_dict() if self.artifact else None,
            "note": self.note,
        }


@dataclass(frozen=True, slots=True)
class ElementConstraint:
    """Atomic-fraction interval from bulk, surface, or local composition evidence."""

    element: str
    minimum_atomic_fraction: float
    maximum_atomic_fraction: float
    scope: CompositionScope = CompositionScope.BULK
    evidence_ids: tuple[str, ...] = ()
    basis: CompositionBasis = CompositionBasis.TOTAL_ATOMIC_FRACTION

    def __post_init__(self) -> None:
        from pymatgen.core import Element

        try:
            symbol = Element(self.element).symbol
        except (TypeError, ValueError) as exc:
            raise ValueError(f"invalid element symbol: {self.element!r}") from exc
        lower = float(self.minimum_atomic_fraction)
        upper = float(self.maximum_atomic_fraction)
        if not math.isfinite(lower) or not math.isfinite(upper):
            raise ValueError("atomic-fraction bounds must be finite")
        if not 0 <= lower <= upper <= 1:
            raise ValueError("atomic-fraction bounds must satisfy 0 <= minimum <= maximum <= 1")
        object.__setattr__(self, "element", symbol)
        object.__setattr__(self, "minimum_atomic_fraction", lower)
        object.__setattr__(self, "maximum_atomic_fraction", upper)
        object.__setattr__(
            self,
            "evidence_ids",
            _identifiers(self.evidence_ids, field_name="evidence_ids"),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "element": self.element,
            "minimum_atomic_fraction": self.minimum_atomic_fraction,
            "maximum_atomic_fraction": self.maximum_atomic_fraction,
            "scope": self.scope.value,
            "basis": self.basis.value,
            "evidence_ids": list(self.evidence_ids),
        }


@dataclass(frozen=True, slots=True)
class LocalEnvironmentConstraint:
    """Fraction of target sites coordinated to one neighboring element.

    This is a deliberately modest XPS/EDS compatibility proxy.  It does not
    claim to predict a core-level spectrum or oxidation state.
    """

    element: str
    neighbor_element: str
    minimum_site_fraction: float
    maximum_site_fraction: float
    cutoff_angstrom: float = 2.6
    scope: CompositionScope = CompositionScope.SURFACE
    evidence_ids: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        from pymatgen.core import Element

        try:
            element = Element(self.element).symbol
            neighbor = Element(self.neighbor_element).symbol
        except (TypeError, ValueError) as exc:
            raise ValueError("local environment elements must be valid symbols") from exc
        lower = float(self.minimum_site_fraction)
        upper = float(self.maximum_site_fraction)
        cutoff = float(self.cutoff_angstrom)
        if not all(math.isfinite(item) for item in (lower, upper, cutoff)):
            raise ValueError("local environment values must be finite")
        if not 0 <= lower <= upper <= 1:
            raise ValueError("site-fraction bounds must satisfy 0 <= minimum <= maximum <= 1")
        if not 0.5 <= cutoff <= 6.0:
            raise ValueError("local environment cutoff must be between 0.5 and 6.0 angstrom")
        if self.scope not in {CompositionScope.SURFACE, CompositionScope.LOCAL}:
            raise ValueError("local environment scope must be surface or local")
        object.__setattr__(self, "element", element)
        object.__setattr__(self, "neighbor_element", neighbor)
        object.__setattr__(self, "minimum_site_fraction", lower)
        object.__setattr__(self, "maximum_site_fraction", upper)
        object.__setattr__(self, "cutoff_angstrom", cutoff)
        object.__setattr__(
            self,
            "evidence_ids",
            _identifiers(self.evidence_ids, field_name="evidence_ids"),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "element": self.element,
            "neighbor_element": self.neighbor_element,
            "minimum_site_fraction": self.minimum_site_fraction,
            "maximum_site_fraction": self.maximum_site_fraction,
            "cutoff_angstrom": self.cutoff_angstrom,
            "scope": self.scope.value,
            "evidence_ids": list(self.evidence_ids),
        }


@dataclass(frozen=True, slots=True)
class LatticeSpacingConstraint:
    """One local lattice-spacing observation from TEM or SAED."""

    d_spacing_angstrom: float
    tolerance_angstrom: float
    evidence_ids: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        spacing = float(self.d_spacing_angstrom)
        tolerance = float(self.tolerance_angstrom)
        if not math.isfinite(spacing) or spacing <= 0:
            raise ValueError("d_spacing_angstrom must be finite and positive")
        if not math.isfinite(tolerance) or not 0 < tolerance <= spacing:
            raise ValueError("tolerance_angstrom must be positive and no larger than d-spacing")
        object.__setattr__(self, "d_spacing_angstrom", spacing)
        object.__setattr__(self, "tolerance_angstrom", tolerance)
        object.__setattr__(
            self,
            "evidence_ids",
            _identifiers(self.evidence_ids, field_name="evidence_ids"),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "d_spacing_angstrom": self.d_spacing_angstrom,
            "tolerance_angstrom": self.tolerance_angstrom,
            "evidence_ids": list(self.evidence_ids),
        }


@dataclass(frozen=True, slots=True)
class ExperimentSpec:
    """Normalized evidence and constraints for one representative model set."""

    sample_id: str
    evidence: tuple[EvidenceRecord, ...]
    composition_constraints: tuple[ElementConstraint, ...] = ()
    local_environment_constraints: tuple[LocalEnvironmentConstraint, ...] = ()
    lattice_spacing_constraints: tuple[LatticeSpacingConstraint, ...] = ()
    allowed_elements: tuple[str, ...] = ()
    excluded_elements: tuple[str, ...] = ()
    material_pack: str = "generic"
    schema_version: str = "catex.experiment-spec.v1"

    def __post_init__(self) -> None:
        from pymatgen.core import Element

        object.__setattr__(self, "sample_id", _identifier(self.sample_id, field_name="sample_id"))
        evidence_ids = [item.evidence_id for item in self.evidence]
        if len(evidence_ids) != len(set(evidence_ids)):
            raise ValueError("evidence IDs must be unique")
        allowed = tuple(sorted({Element(item).symbol for item in self.allowed_elements}))
        excluded = tuple(sorted({Element(item).symbol for item in self.excluded_elements}))
        if set(allowed) & set(excluded):
            raise ValueError("allowed_elements and excluded_elements must not overlap")
        constraint_keys = [
            (item.element, item.scope, item.basis) for item in self.composition_constraints
        ]
        if len(constraint_keys) != len(set(constraint_keys)):
            raise ValueError(
                "composition constraints must contain at most one interval per element, "
                "scope, and basis"
            )
        known_evidence = set(evidence_ids)
        if any(
            evidence_id not in known_evidence
            for constraint in self.composition_constraints
            for evidence_id in constraint.evidence_ids
        ):
            raise ValueError("composition constraints reference unknown evidence IDs")
        if any(
            evidence_id not in known_evidence
            for constraint in self.local_environment_constraints
            for evidence_id in constraint.evidence_ids
        ):
            raise ValueError("local environment constraints reference unknown evidence IDs")
        if any(
            evidence_id not in known_evidence
            for constraint in self.lattice_spacing_constraints
            for evidence_id in constraint.evidence_ids
        ):
            raise ValueError("lattice-spacing constraints reference unknown evidence IDs")
        grouped_minimums: dict[tuple[CompositionScope, CompositionBasis], float] = {}
        for item in self.composition_constraints:
            key = (item.scope, item.basis)
            grouped_minimums[key] = grouped_minimums.get(key, 0.0) + item.minimum_atomic_fraction
        if any(value > 1 + 1e-12 for value in grouped_minimums.values()):
            raise ValueError(
                "minimum composition fractions cannot sum to more than one per scope and basis"
            )
        object.__setattr__(self, "allowed_elements", allowed)
        object.__setattr__(self, "excluded_elements", excluded)
        object.__setattr__(
            self,
            "material_pack",
            _identifier(self.material_pack, field_name="material_pack"),
        )

    @property
    def required_bulk_elements(self) -> tuple[str, ...]:
        return tuple(
            sorted(
                item.element
                for item in self.composition_constraints
                if item.scope is CompositionScope.BULK and item.minimum_atomic_fraction > 0
            )
        )

    @property
    def model_elements(self) -> tuple[str, ...]:
        """Elements allowed in parent and generated environment-aware candidates."""

        return tuple(
            sorted(
                {
                    *self.allowed_elements,
                    *(item.element for item in self.composition_constraints),
                    *(item.element for item in self.local_environment_constraints),
                    *(item.neighbor_element for item in self.local_environment_constraints),
                }
            )
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "sample_id": self.sample_id,
            "material_pack": self.material_pack,
            "allowed_elements": list(self.allowed_elements),
            "excluded_elements": list(self.excluded_elements),
            "composition_constraints": [item.to_dict() for item in self.composition_constraints],
            "local_environment_constraints": [
                item.to_dict() for item in self.local_environment_constraints
            ],
            "lattice_spacing_constraints": [
                item.to_dict() for item in self.lattice_spacing_constraints
            ],
            "evidence": [item.to_dict() for item in self.evidence],
        }


@dataclass(frozen=True, slots=True)
class StructureReference:
    """Traceable parent structure from a pluggable provider."""

    provider: str
    record_id: str
    formula: str
    elements: tuple[str, ...]
    source_kind: StructureSourceKind
    source_locator: str
    structure_sha256: str
    artifact_sha256: str | None = None
    license: str = ""
    citation: str = ""
    schema_version: str = "catex.structure-reference.v1"

    def __post_init__(self) -> None:
        from pymatgen.core import Element

        object.__setattr__(self, "provider", _identifier(self.provider, field_name="provider"))
        object.__setattr__(self, "record_id", _identifier(self.record_id, field_name="record_id"))
        object.__setattr__(
            self,
            "formula",
            _one_line(self.formula, field_name="formula", maximum=255),
        )
        object.__setattr__(
            self,
            "elements",
            tuple(sorted({Element(item).symbol for item in self.elements})),
        )
        object.__setattr__(
            self,
            "source_locator",
            _one_line(self.source_locator, field_name="source_locator", maximum=1000),
        )
        if _SHA256.fullmatch(self.structure_sha256) is None:
            raise ValueError("structure_sha256 must be a lowercase SHA256 digest")
        if self.artifact_sha256 is not None and _SHA256.fullmatch(self.artifact_sha256) is None:
            raise ValueError("artifact_sha256 must be a lowercase SHA256 digest")
        object.__setattr__(
            self,
            "license",
            _one_line(self.license, field_name="license", maximum=255, allow_empty=True),
        )
        object.__setattr__(
            self,
            "citation",
            _one_line(self.citation, field_name="citation", maximum=1000, allow_empty=True),
        )

    @property
    def key(self) -> str:
        return f"{self.provider}:{self.record_id}"

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "provider": self.provider,
            "record_id": self.record_id,
            "key": self.key,
            "formula": self.formula,
            "elements": list(self.elements),
            "source_kind": self.source_kind.value,
            "source_locator": self.source_locator,
            "structure_sha256": self.structure_sha256,
            "artifact_sha256": self.artifact_sha256,
            "license": self.license,
            "citation": self.citation,
        }


@dataclass(frozen=True, slots=True)
class CandidateOperation:
    """One allowlisted and JSON-serializable structure operation."""

    kind: CandidateOperationKind
    parameters: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "parameters",
            _json_mapping(self.parameters, field_name="parameters"),
        )

    def to_dict(self) -> dict[str, Any]:
        return {"kind": self.kind.value, "parameters": dict(self.parameters)}


@dataclass(frozen=True, slots=True)
class CandidateRecipe:
    """Auditable recipe from a parent structure to one or more candidate models."""

    recipe_id: str
    parent_reference_key: str
    hypothesis_id: str
    operations: tuple[CandidateOperation, ...]
    evidence_ids: tuple[str, ...]
    rationale: str
    assumptions: tuple[str, ...] = ()
    random_seed: int = 0
    planner: str = "rule"
    schema_version: str = "catex.candidate-recipe.v1"

    def __post_init__(self) -> None:
        object.__setattr__(self, "recipe_id", _identifier(self.recipe_id, field_name="recipe_id"))
        object.__setattr__(
            self,
            "parent_reference_key",
            _identifier(self.parent_reference_key, field_name="parent_reference_key"),
        )
        object.__setattr__(
            self,
            "hypothesis_id",
            _identifier(self.hypothesis_id, field_name="hypothesis_id"),
        )
        if not self.operations:
            raise ValueError("candidate recipe must contain at least one operation")
        object.__setattr__(
            self,
            "evidence_ids",
            _identifiers(self.evidence_ids, field_name="evidence_ids"),
        )
        object.__setattr__(
            self,
            "rationale",
            _one_line(self.rationale, field_name="rationale", maximum=1000),
        )
        assumptions = tuple(
            _one_line(item, field_name="assumption", maximum=1000) for item in self.assumptions
        )
        object.__setattr__(self, "assumptions", assumptions)
        if not isinstance(self.random_seed, int) or isinstance(self.random_seed, bool):
            raise ValueError("random_seed must be an integer")
        object.__setattr__(self, "planner", _identifier(self.planner, field_name="planner"))

    @property
    def identity_sha256(self) -> str:
        return content_digest(self.to_dict(include_identity=False))

    def to_dict(self, *, include_identity: bool = True) -> dict[str, Any]:
        result = {
            "schema_version": self.schema_version,
            "recipe_id": self.recipe_id,
            "parent_reference_key": self.parent_reference_key,
            "hypothesis_id": self.hypothesis_id,
            "operations": [item.to_dict() for item in self.operations],
            "evidence_ids": list(self.evidence_ids),
            "rationale": self.rationale,
            "assumptions": list(self.assumptions),
            "random_seed": self.random_seed,
            "planner": self.planner,
        }
        if include_identity:
            result["identity_sha256"] = self.identity_sha256
        return result


@dataclass(frozen=True, slots=True)
class StructuralHypothesis:
    """Evidence-linked scientific hypothesis without a truth claim."""

    hypothesis_id: str
    summary: str
    evidence_ids: tuple[str, ...]
    parent_reference_keys: tuple[str, ...] = ()
    assumptions: tuple[str, ...] = ()
    generated_atomistic_candidate: bool = False
    schema_version: str = "catex.structural-hypothesis.v1"

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "hypothesis_id",
            _identifier(self.hypothesis_id, field_name="hypothesis_id"),
        )
        object.__setattr__(
            self,
            "summary",
            _one_line(self.summary, field_name="summary", maximum=1000),
        )
        object.__setattr__(
            self,
            "evidence_ids",
            _identifiers(self.evidence_ids, field_name="evidence_ids"),
        )
        object.__setattr__(
            self,
            "parent_reference_keys",
            _identifiers(
                self.parent_reference_keys,
                field_name="parent_reference_keys",
            ),
        )
        object.__setattr__(
            self,
            "assumptions",
            tuple(
                _one_line(item, field_name="assumption", maximum=1000) for item in self.assumptions
            ),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "hypothesis_id": self.hypothesis_id,
            "summary": self.summary,
            "evidence_ids": list(self.evidence_ids),
            "parent_reference_keys": list(self.parent_reference_keys),
            "assumptions": list(self.assumptions),
            "generated_atomistic_candidate": self.generated_atomistic_candidate,
        }


@dataclass(frozen=True, slots=True)
class CandidateAssessment:
    """Serializable assessment of one generated runtime structure."""

    candidate_id: str
    recipe_id: str
    hypothesis_id: str
    parent_reference_key: str
    model_kind: ModelKind
    structure_sha256: str
    formula: str
    num_sites: int
    valid: bool
    evidence_score: float
    phase_support_score: float | None
    xrd_directly_applicable: bool
    evidence_checks: tuple[EvidenceCheck, ...]
    transformation_sha256s: tuple[str, ...]
    diagnostics: tuple[Diagnostic, ...]
    schema_version: str = "catex.candidate-assessment.v1"

    def __post_init__(self) -> None:
        for name in (
            "candidate_id",
            "recipe_id",
            "hypothesis_id",
            "parent_reference_key",
        ):
            object.__setattr__(self, name, _identifier(getattr(self, name), field_name=name))
        if _SHA256.fullmatch(self.structure_sha256) is None:
            raise ValueError("structure_sha256 must be a lowercase SHA256 digest")
        if not math.isfinite(self.evidence_score):
            raise ValueError("evidence_score must be finite")
        if self.phase_support_score is not None and not math.isfinite(self.phase_support_score):
            raise ValueError("phase_support_score must be finite when present")
        if self.num_sites <= 0:
            raise ValueError("num_sites must be positive")

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "candidate_id": self.candidate_id,
            "recipe_id": self.recipe_id,
            "hypothesis_id": self.hypothesis_id,
            "parent_reference_key": self.parent_reference_key,
            "model_kind": self.model_kind.value,
            "structure_sha256": self.structure_sha256,
            "formula": self.formula,
            "num_sites": self.num_sites,
            "valid": self.valid,
            "evidence_score": self.evidence_score,
            "phase_support_score": self.phase_support_score,
            "xrd_directly_applicable": self.xrd_directly_applicable,
            "evidence_checks": [item.to_dict() for item in self.evidence_checks],
            "transformation_sha256s": list(self.transformation_sha256s),
            "diagnostics": [item.to_dict() for item in self.diagnostics],
        }


@dataclass(frozen=True, slots=True)
class EvidenceCheck:
    """Transparent candidate-versus-observation comparison."""

    check_id: str
    kind: str
    label: str
    role: EvidenceRole
    status: str
    score: float | None
    predicted_value: float | None = None
    experimental_minimum: float | None = None
    experimental_maximum: float | None = None
    unit: str = ""
    evidence_ids: tuple[str, ...] = ()
    message: str = ""

    def __post_init__(self) -> None:
        object.__setattr__(self, "check_id", _identifier(self.check_id, field_name="check_id"))
        if self.status not in {"within_range", "outside_range", "not_applicable"}:
            raise ValueError("evidence check status is invalid")
        if self.score is not None and (not math.isfinite(self.score) or not 0 <= self.score <= 1):
            raise ValueError("evidence check score must be in [0, 1]")
        for name in ("predicted_value", "experimental_minimum", "experimental_maximum"):
            value = getattr(self, name)
            if value is not None and not math.isfinite(value):
                raise ValueError(f"{name} must be finite when present")
        object.__setattr__(
            self,
            "label",
            _one_line(self.label, field_name="label", maximum=255),
        )
        object.__setattr__(
            self,
            "unit",
            _one_line(self.unit, field_name="unit", maximum=32, allow_empty=True),
        )
        object.__setattr__(
            self,
            "message",
            _one_line(self.message, field_name="message", maximum=1000, allow_empty=True),
        )
        object.__setattr__(
            self,
            "evidence_ids",
            _identifiers(self.evidence_ids, field_name="evidence_ids"),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "check_id": self.check_id,
            "kind": self.kind,
            "label": self.label,
            "role": self.role.value,
            "status": self.status,
            "score": self.score,
            "predicted_value": self.predicted_value,
            "experimental_minimum": self.experimental_minimum,
            "experimental_maximum": self.experimental_maximum,
            "unit": self.unit,
            "evidence_ids": list(self.evidence_ids),
            "message": self.message,
        }
