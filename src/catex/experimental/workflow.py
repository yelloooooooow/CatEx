"""End-to-end experiment-informed candidate inference and controlled materialization."""

from __future__ import annotations

import json
import math
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from pymatgen.analysis.diffraction.xrd import XRDCalculator
from pymatgen.core import Composition, Element, Structure

from catex.experimental.models import (
    CandidateAssessment,
    ClaimLevel,
    CompositionBasis,
    CompositionScope,
    EvidenceCheck,
    EvidenceKind,
    EvidenceRole,
    ExperimentSpec,
    InferenceStatus,
    ModalitySupport,
    ModelKind,
    StructuralHypothesis,
    SupportDomain,
    content_digest,
)
from catex.experimental.planning import CandidatePlan, CandidatePlanner
from catex.experimental.providers import ProviderRegistry
from catex.experimental.recipes import CandidateExecution, execute_candidate_recipe
from catex.experimental.spec import ExperimentInput
from catex.experimental.xrd import (
    PhaseSearchReport,
    XRDSearchSettings,
    parse_xrd_path,
    search_xrd_phases,
)
from catex.hashing import artifact_record, structure_hash
from catex.models import ArtifactRecord, Diagnostic, Severity


@dataclass(frozen=True, slots=True)
class ExperimentalModelingReport:
    """Serializable scientific result; runtime structures remain out of the record."""

    experiment: ExperimentSpec
    status: InferenceStatus
    claim_ceiling: ClaimLevel
    phase_search: PhaseSearchReport | None
    candidate_plan: CandidatePlan
    candidate_assessments: tuple[CandidateAssessment, ...]
    representative_candidate_ids: tuple[str, ...]
    unresolved_hypothesis_ids: tuple[str, ...]
    ambiguity_reasons: tuple[str, ...]
    recommended_next_experiments: tuple[str, ...]
    diagnostics: tuple[Diagnostic, ...]
    external_api_called: bool
    writes_performed: bool = False
    schema_version: str = "catex.experimental-modeling-report.v2"

    @property
    def has_errors(self) -> bool:
        return any(item.severity is Severity.ERROR for item in self.diagnostics)

    @property
    def identity_sha256(self) -> str:
        return content_digest(self.to_dict(include_identity=False))

    def to_dict(self, *, include_identity: bool = True) -> dict[str, Any]:
        result = {
            "schema_version": self.schema_version,
            "status": self.status.value,
            "claim_ceiling": self.claim_ceiling.value,
            "claim_interpretation": (
                "The report ranks representative hypotheses; it does not reconstruct "
                "a unique real atomic structure."
            ),
            "experiment": self.experiment.to_dict(),
            "phase_search": self.phase_search.to_dict() if self.phase_search else None,
            "candidate_plan": self.candidate_plan.to_dict(),
            "candidate_assessments": [item.to_dict() for item in self.candidate_assessments],
            "representative_candidate_ids": list(self.representative_candidate_ids),
            "unresolved_hypothesis_ids": list(self.unresolved_hypothesis_ids),
            "ambiguity_reasons": list(self.ambiguity_reasons),
            "recommended_next_experiments": list(self.recommended_next_experiments),
            "threshold_interpretation": (
                "Hard evidence is used only for exclusion. Soft checks are aggregated "
                "within modality and support domain using geometric means; context evidence "
                "does not score. Representatives are non-dominated on parent, surface, and "
                "local support, with missing domains treated as incomparable rather than zero."
            ),
            "external_api_called": self.external_api_called,
            "writes_performed": self.writes_performed,
            "diagnostics": [item.to_dict() for item in self.diagnostics],
        }
        if include_identity:
            result["identity_sha256"] = self.identity_sha256
        return result


@dataclass(frozen=True, slots=True)
class ExperimentalModelingRun:
    """Serializable report paired with in-memory candidate structures."""

    report: ExperimentalModelingReport
    candidates: tuple[CandidateExecution, ...]

    def representative_structures(self) -> tuple[tuple[str, Structure], ...]:
        selected = set(self.report.representative_candidate_ids)
        return tuple(
            (item.candidate_id, item.structure.copy())
            for item in self.candidates
            if item.candidate_id in selected
        )


@dataclass(frozen=True, slots=True)
class MaterializedCandidate:
    """One newly written DFT-ready structure artifact."""

    candidate_id: str
    poscar: ArtifactRecord
    cif: ArtifactRecord

    def to_dict(self) -> dict[str, Any]:
        return {
            "candidate_id": self.candidate_id,
            "poscar": self.poscar.to_dict(),
            "cif": self.cif.to_dict(),
        }


@dataclass(frozen=True, slots=True)
class CandidateMaterializationReport:
    """Manifest for an explicit new-directory write."""

    inference_sha256: str
    destination: str
    candidates: tuple[MaterializedCandidate, ...]
    manifest: ArtifactRecord
    writes_performed: bool = True
    schema_version: str = "catex.candidate-materialization.v1"

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "inference_sha256": self.inference_sha256,
            "destination": self.destination,
            "candidates": [item.to_dict() for item in self.candidates],
            "manifest": self.manifest.to_dict(),
            "writes_performed": self.writes_performed,
        }


def _select_xrd_evidence(
    experiment: ExperimentInput,
) -> tuple[Path | None, tuple[Diagnostic, ...]]:
    candidates = [
        item
        for item in experiment.spec.evidence
        if item.kind in {EvidenceKind.XRD, EvidenceKind.GIXRD}
        and item.evidence_id in experiment.artifact_paths
    ]
    if not candidates:
        return (
            None,
            (
                Diagnostic(
                    "EXPERIMENTAL_MODELING_NO_XRD_ARTIFACT",
                    Severity.WARNING,
                    "No local XRD/GIXRD artifact is available for phase-family inference.",
                ),
            ),
        )
    selected = sorted(candidates, key=lambda item: item.evidence_id)[0]
    diagnostics = []
    if len(candidates) > 1:
        diagnostics.append(
            Diagnostic(
                "EXPERIMENTAL_MODELING_MULTIPLE_XRD_ARTIFACTS",
                Severity.WARNING,
                "Only one XRD artifact is used by the v1 vertical slice.",
                {
                    "selected_evidence_id": selected.evidence_id,
                    "available_evidence_ids": sorted(item.evidence_id for item in candidates),
                },
            )
        )
    return experiment.artifact_paths[selected.evidence_id], tuple(diagnostics)


def _ranked_phase_scores(
    phase_search: PhaseSearchReport | None,
) -> tuple[tuple[tuple[str, ...], float], ...]:
    if phase_search is None:
        return ()
    values = [
        ((item.reference_key,), item.evidence_score) for item in phase_search.single_phase_matches
    ]
    values.extend(
        (item.reference_keys, item.evidence_score) for item in phase_search.combination_matches
    )
    return tuple(sorted(values, key=lambda item: (-item[1], item[0])))


def _ambiguity_reasons(
    phase_search: PhaseSearchReport | None,
    hypotheses: tuple[StructuralHypothesis, ...],
) -> tuple[str, ...]:
    reasons: list[str] = []
    ranked = _ranked_phase_scores(phase_search)
    if (
        len(ranked) >= 2
        and phase_search is not None
        and ranked[0][1] - ranked[1][1] <= phase_search.settings.ambiguity_margin
    ):
        reasons.append(
            "Multiple phase combinations lie within the configured XRD ambiguity margin."
        )
    if phase_search is not None and phase_search.status == "insufficient_support":
        reasons.append(
            "The local reference library does not explain the diffraction pattern strongly enough."
        )
    if any(not item.generated_atomistic_candidate for item in hypotheses):
        reasons.append(
            "At least one evidence-supported hypothesis lacks a defensible atomic realization."
        )
    return tuple(reasons)


def _next_experiments(
    spec: ExperimentSpec,
    phase_search: PhaseSearchReport | None,
    hypotheses: tuple[StructuralHypothesis, ...],
) -> tuple[str, ...]:
    kinds = {item.kind for item in spec.evidence}
    recommendations: list[str] = []
    if not ({EvidenceKind.ICP, EvidenceKind.EDS} & kinds):
        recommendations.append(
            "Add ICP-OES or quantified EDS with uncertainty to constrain bulk composition."
        )
    if not ({EvidenceKind.XRD, EvidenceKind.GIXRD} & kinds):
        recommendations.append(
            "Add laboratory XRD/GIXRD with wavelength, scan range, substrate, "
            "and geometry metadata."
        )
    elif phase_search is not None and phase_search.status != "hypotheses_found":
        recommendations.append(
            "Acquire a longer-count or geometry-adjusted XRD/GIXRD scan before "
            "adding a costly method."
        )
    if EvidenceKind.XPS not in kinds:
        recommendations.append(
            "Add fitted XPS composition or chemical-state results to constrain surface models."
        )
    if EvidenceKind.TEM not in kinds:
        recommendations.append(
            "Add targeted TEM/SAED lattice-spacing and crystallite-size evidence "
            "for leading phases."
        )
    if any(item.hypothesis_id == "surface-oxygen-unresolved" for item in hypotheses):
        recommendations.append(
            "Add a quantified XPS peak table, and compare with Raman if oxide families "
            "remain ambiguous."
        )
    if any(item.hypothesis_id == "disordered-motif-ensemble-unresolved" for item in hypotheses):
        recommendations.append(
            "Treat disorder as a motif ensemble; use total scattering/PDF only if "
            "candidate-dependent DFT conclusions remain different."
        )
    return tuple(dict.fromkeys(recommendations))


def _constraint_role(spec: ExperimentSpec, evidence_ids: tuple[str, ...]) -> EvidenceRole:
    roles = {item.role for item in spec.evidence if item.evidence_id in set(evidence_ids)}
    if EvidenceRole.HARD in roles:
        return EvidenceRole.HARD
    if EvidenceRole.SOFT in roles:
        return EvidenceRole.SOFT
    return EvidenceRole.CONTEXT


def _interval_score(value: float, lower: float, upper: float) -> tuple[str, float]:
    if lower <= value <= upper:
        return "within_range", 1.0
    width = max(upper - lower, 0.02)
    distance = lower - value if value < lower else value - upper
    return "outside_range", max(0.0, 1.0 - distance / width)


_MODALITY_DOMAIN = {
    EvidenceKind.XRD: SupportDomain.PARENT,
    EvidenceKind.ICP: SupportDomain.PARENT,
    EvidenceKind.XPS: SupportDomain.SURFACE,
    EvidenceKind.EDS: SupportDomain.LOCAL,
    EvidenceKind.TEM: SupportDomain.LOCAL,
}


def _normalized_modality(kind: EvidenceKind) -> EvidenceKind:
    return EvidenceKind.XRD if kind is EvidenceKind.GIXRD else kind


def _geometric_mean(values: tuple[float, ...]) -> float:
    if not values:
        raise ValueError("geometric mean requires at least one value")
    if any(value == 0 for value in values):
        return 0.0
    return math.exp(sum(math.log(value) for value in values) / len(values))


def _soft_modality_support(
    checks: tuple[EvidenceCheck, ...],
    spec: ExperimentSpec,
) -> tuple[ModalitySupport, ...]:
    evidence_by_id = {item.evidence_id: item for item in spec.evidence}
    grouped: dict[EvidenceKind, dict[str, float]] = {}
    for check in checks:
        if check.score is None or check.kind == "geometry":
            continue
        for evidence_id in check.evidence_ids:
            evidence = evidence_by_id.get(evidence_id)
            if evidence is None or evidence.role is not EvidenceRole.SOFT:
                continue
            modality = _normalized_modality(evidence.kind)
            if modality not in _MODALITY_DOMAIN:
                continue
            grouped.setdefault(modality, {})[check.check_id] = check.score
    return tuple(
        ModalitySupport(
            modality=modality,
            domain=_MODALITY_DOMAIN[modality],
            score=_geometric_mean(tuple(check_scores.values())),
            check_ids=tuple(sorted(check_scores)),
        )
        for modality, check_scores in sorted(grouped.items(), key=lambda item: item[0].value)
    )


def _domain_support(
    modality_support: tuple[ModalitySupport, ...],
    domain: SupportDomain,
) -> float | None:
    scores = tuple(item.score for item in modality_support if item.domain is domain)
    return _geometric_mean(scores) if scores else None


def _top_region_indices(structure: Structure, *, depth_angstrom: float = 3.0) -> tuple[int, ...]:
    import numpy as np

    c_vector = np.asarray(structure.lattice.matrix[2], dtype=float)
    c_hat = c_vector / np.linalg.norm(c_vector)
    projected = np.asarray(structure.cart_coords, dtype=float) @ c_hat
    top = float(np.max(projected))
    return tuple(index for index, value in enumerate(projected) if top - value <= depth_angstrom)


def _composition_value(
    structure: Structure,
    *,
    element: str,
    scope: CompositionScope,
    basis: CompositionBasis,
    model_kind: ModelKind,
) -> float | None:
    if scope is CompositionScope.BULK and model_kind is ModelKind.SURFACE:
        return None
    if scope is CompositionScope.SURFACE:
        if model_kind is not ModelKind.SURFACE:
            return None
        indices = _top_region_indices(structure)
    else:
        indices = tuple(range(len(structure)))
    if not indices:
        return None
    if basis is CompositionBasis.WEIGHT_FRACTION:
        masses = [float(Element(str(structure[index].specie)).atomic_mass) for index in indices]
        denominator = sum(masses)
        numerator = sum(
            mass
            for index, mass in zip(indices, masses, strict=True)
            if str(structure[index].specie) == element
        )
    else:
        eligible = list(indices)
        if basis is CompositionBasis.METAL_NORMALIZED_ATOMIC_FRACTION:
            eligible = [
                index for index in indices if Element(str(structure[index].specie)).is_metal
            ]
        denominator = float(len(eligible))
        numerator = float(sum(str(structure[index].specie) == element for index in eligible))
    return numerator / denominator if denominator else None


def _environment_value(
    structure: Structure,
    *,
    element: str,
    neighbor_element: str,
    cutoff_angstrom: float,
    scope: CompositionScope,
    model_kind: ModelKind,
) -> float | None:
    if scope is CompositionScope.SURFACE:
        if model_kind is not ModelKind.SURFACE:
            return None
        indices = _top_region_indices(structure)
    else:
        indices = tuple(range(len(structure)))
    centers = [index for index in indices if str(structure[index].specie) == element]
    if not centers:
        return 0.0
    coordinated = sum(
        any(
            str(neighbor.specie) == neighbor_element
            for neighbor in structure.get_neighbors(structure[index], cutoff_angstrom)
        )
        for index in centers
    )
    return coordinated / len(centers)


def _parent_d_spacings(structure: Structure) -> tuple[float, ...]:
    pattern = XRDCalculator(wavelength="CuKa", symprec=0).get_pattern(
        structure,
        scaled=False,
        two_theta_range=(5.0, 175.0),
    )
    return tuple(sorted({float(item) for item in pattern.d_hkls}, reverse=True))


def _reported_phase_formulas(metadata: Mapping[str, Any]) -> tuple[str, ...]:
    extraction = metadata.get("automatic_extraction")
    if isinstance(extraction, Mapping) and extraction.get("method") == "transparent-rule-parser-v1":
        return ()
    raw = metadata.get("reported_phase_formulas")
    values = raw if isinstance(raw, list | tuple) else ()
    formulas = []
    for value in values:
        if not isinstance(value, str):
            continue
        try:
            formula = Composition(value).reduced_formula
        except (TypeError, ValueError):
            continue
        if formula not in formulas:
            formulas.append(formula)
    return tuple(formulas)


def _evidence_checks(
    execution: CandidateExecution,
    spec: ExperimentSpec,
    registry: ProviderRegistry,
    phase_support: dict[str, float],
    phase_search: PhaseSearchReport | None,
) -> tuple[EvidenceCheck, ...]:
    checks: list[EvidenceCheck] = []
    inherited = phase_support.get(execution.recipe.parent_reference_key)
    if phase_search is not None:
        xrd_ids = tuple(
            item.evidence_id
            for item in spec.evidence
            if item.kind in {EvidenceKind.XRD, EvidenceKind.GIXRD}
        )
        threshold = phase_search.settings.minimum_supported_score
        value = inherited or 0.0
        checks.append(
            EvidenceCheck(
                check_id="xrd-parent-phase",
                kind="xrd",
                label="Parent-phase XRD support",
                role=_constraint_role(spec, xrd_ids),
                status="within_range" if value >= threshold else "outside_range",
                score=max(0.0, min(1.0, value)),
                predicted_value=value,
                experimental_minimum=threshold,
                experimental_maximum=1.0,
                unit="score",
                evidence_ids=xrd_ids,
                message=(
                    "XRD evaluates the parent crystalline phase; it does not identify "
                    "this surface termination."
                    if execution.model_kind is ModelKind.SURFACE
                    else "The simulated parent phase is compared with the measured powder pattern."
                ),
            )
        )
    else:
        parent_formula = Composition(
            registry.get_reference(execution.recipe.parent_reference_key).formula
        ).reduced_formula
        for index, evidence in enumerate(
            (
                item
                for item in spec.evidence
                if item.kind in {EvidenceKind.XRD, EvidenceKind.GIXRD}
                and _reported_phase_formulas(item.metadata)
            ),
            start=1,
        ):
            formulas = _reported_phase_formulas(evidence.metadata)
            matched = parent_formula in formulas
            checks.append(
                EvidenceCheck(
                    check_id=f"xrd-reported-phase-{index}",
                    kind="xrd",
                    label=f"Reported phase formula {' / '.join(formulas)}",
                    role=evidence.role,
                    status="within_range" if matched else "outside_range",
                    score=1.0 if matched else 0.0,
                    predicted_value=1.0 if matched else 0.0,
                    experimental_minimum=1.0,
                    experimental_maximum=1.0,
                    unit="formula match",
                    evidence_ids=(evidence.evidence_id,),
                    message=(
                        "The parent reduced formula matches the researcher-entered XRD phase "
                        "assignment; this does not distinguish polymorphs or surface terminations."
                    ),
                )
            )
    for index, constraint in enumerate(spec.composition_constraints, start=1):
        value = _composition_value(
            execution.structure,
            element=constraint.element,
            scope=constraint.scope,
            basis=constraint.basis,
            model_kind=execution.model_kind,
        )
        role = _constraint_role(spec, constraint.evidence_ids)
        if value is None:
            status, score = "not_applicable", None
        else:
            status, score = _interval_score(
                value,
                constraint.minimum_atomic_fraction,
                constraint.maximum_atomic_fraction,
            )
        checks.append(
            EvidenceCheck(
                check_id=f"composition-{index}",
                kind="composition",
                label=f"{constraint.element} · {constraint.scope.value} · {constraint.basis.value}",
                role=role,
                status=status,
                score=score,
                predicted_value=value,
                experimental_minimum=constraint.minimum_atomic_fraction,
                experimental_maximum=constraint.maximum_atomic_fraction,
                unit="fraction",
                evidence_ids=constraint.evidence_ids,
                message=(
                    "This model type does not represent the requested spatial composition scope."
                    if value is None
                    else "Candidate composition is compared with the entered interval."
                ),
            )
        )
    for index, constraint in enumerate(spec.local_environment_constraints, start=1):
        value = _environment_value(
            execution.structure,
            element=constraint.element,
            neighbor_element=constraint.neighbor_element,
            cutoff_angstrom=constraint.cutoff_angstrom,
            scope=constraint.scope,
            model_kind=execution.model_kind,
        )
        if value is None:
            status, score = "not_applicable", None
        else:
            status, score = _interval_score(
                value,
                constraint.minimum_site_fraction,
                constraint.maximum_site_fraction,
            )
        checks.append(
            EvidenceCheck(
                check_id=f"xps-environment-{index}",
                kind="xps",
                label=f"{constraint.element} coordinated to {constraint.neighbor_element}",
                role=_constraint_role(spec, constraint.evidence_ids),
                status=status,
                score=score,
                predicted_value=value,
                experimental_minimum=constraint.minimum_site_fraction,
                experimental_maximum=constraint.maximum_site_fraction,
                unit="site fraction",
                evidence_ids=constraint.evidence_ids,
                message=(
                    "This is a geometric compatibility proxy, not a simulated XPS spectrum."
                    if value is not None
                    else "A bulk model is not used to evaluate a surface XPS constraint."
                ),
            )
        )
    if spec.lattice_spacing_constraints:
        parent = registry.get_structure(execution.recipe.parent_reference_key)
        spacings = _parent_d_spacings(parent)
        for index, constraint in enumerate(spec.lattice_spacing_constraints, start=1):
            nearest = min(spacings, key=lambda item: abs(item - constraint.d_spacing_angstrom))
            difference = abs(nearest - constraint.d_spacing_angstrom)
            lower = constraint.d_spacing_angstrom - constraint.tolerance_angstrom
            upper = constraint.d_spacing_angstrom + constraint.tolerance_angstrom
            checks.append(
                EvidenceCheck(
                    check_id=f"tem-spacing-{index}",
                    kind="tem",
                    label=f"TEM/SAED d = {constraint.d_spacing_angstrom:.3f} Å",
                    role=_constraint_role(spec, constraint.evidence_ids),
                    status=(
                        "within_range"
                        if difference <= constraint.tolerance_angstrom
                        else "outside_range"
                    ),
                    score=max(0.0, 1.0 - difference / constraint.tolerance_angstrom),
                    predicted_value=nearest,
                    experimental_minimum=lower,
                    experimental_maximum=upper,
                    unit="Å",
                    evidence_ids=constraint.evidence_ids,
                    message=(
                        "Nearest parent-phase diffraction spacing; a local TEM observation "
                        "is not a bulk phase fraction."
                    ),
                )
            )
    checks.append(
        EvidenceCheck(
            check_id="geometry",
            kind="geometry",
            label="Geometry validation",
            role=EvidenceRole.HARD,
            status="within_range" if execution.valid else "outside_range",
            score=1.0 if execution.valid else 0.0,
            message="Local geometry and periodic-distance diagnostics.",
        )
    )
    return tuple(checks)


def _candidate_assessment(
    execution: CandidateExecution,
    phase_support: dict[str, float],
    spec: ExperimentSpec,
    registry: ProviderRegistry,
    phase_search: PhaseSearchReport | None,
) -> CandidateAssessment:
    checks = _evidence_checks(execution, spec, registry, phase_support, phase_search)
    modality_support = _soft_modality_support(checks, spec)
    hard_failure = any(
        item.role is EvidenceRole.HARD and item.status == "outside_range" for item in checks
    )
    xrd_direct = (
        execution.model_kind is ModelKind.BULK
        and len(execution.recipe.operations) == 1
        and execution.recipe.operations[0].kind.value == "identity"
    )
    return CandidateAssessment(
        candidate_id=execution.candidate_id,
        recipe_id=execution.recipe.recipe_id,
        hypothesis_id=execution.recipe.hypothesis_id,
        parent_reference_key=execution.recipe.parent_reference_key,
        model_kind=execution.model_kind,
        structure_sha256=structure_hash(execution.structure),
        formula=execution.structure.composition.reduced_formula,
        num_sites=len(execution.structure),
        valid=execution.valid and not hard_failure,
        modality_support=modality_support,
        parent_support=_domain_support(modality_support, SupportDomain.PARENT),
        surface_support=_domain_support(modality_support, SupportDomain.SURFACE),
        local_support=_domain_support(modality_support, SupportDomain.LOCAL),
        xrd_directly_applicable=xrd_direct,
        evidence_checks=checks,
        transformation_sha256s=execution.transformation_sha256s,
        diagnostics=execution.diagnostics,
    )


_SUPPORT_FIELDS = ("parent_support", "surface_support", "local_support")


def _support_vector(assessment: CandidateAssessment) -> tuple[float | None, ...]:
    return tuple(getattr(assessment, name) for name in _SUPPORT_FIELDS)


def _dominates(left: CandidateAssessment, right: CandidateAssessment) -> bool:
    left_values = _support_vector(left)
    right_values = _support_vector(right)
    left_mask = tuple(value is not None for value in left_values)
    right_mask = tuple(value is not None for value in right_values)
    if left_mask != right_mask or not any(left_mask):
        return False
    comparable = tuple(
        (left_value, right_value)
        for left_value, right_value in zip(left_values, right_values, strict=True)
        if left_value is not None and right_value is not None
    )
    return all(left_value >= right_value for left_value, right_value in comparable) and any(
        left_value > right_value for left_value, right_value in comparable
    )


def _pareto_frontier(
    assessments: tuple[CandidateAssessment, ...],
) -> tuple[CandidateAssessment, ...]:
    return tuple(
        candidate
        for candidate in assessments
        if not any(
            other.candidate_id != candidate.candidate_id and _dominates(other, candidate)
            for other in assessments
        )
    )


def _crowding_distances(
    frontier: tuple[CandidateAssessment, ...],
) -> dict[str, float]:
    distances = {item.candidate_id: 0.0 for item in frontier}
    for field_name in _SUPPORT_FIELDS:
        available = sorted(
            (
                (float(getattr(item, field_name)), item)
                for item in frontier
                if getattr(item, field_name) is not None
            ),
            key=lambda record: (record[0], record[1].candidate_id),
        )
        if len(available) < 2 or available[0][0] == available[-1][0]:
            continue
        distances[available[0][1].candidate_id] = math.inf
        distances[available[-1][1].candidate_id] = math.inf
        span = available[-1][0] - available[0][0]
        for index in range(1, len(available) - 1):
            candidate_id = available[index][1].candidate_id
            if math.isinf(distances[candidate_id]):
                continue
            distances[candidate_id] += (available[index + 1][0] - available[index - 1][0]) / span
    return distances


def _representatives(
    assessments: tuple[CandidateAssessment, ...],
    *,
    maximum_representatives: int,
) -> tuple[str, ...]:
    valid = sorted(
        (item for item in assessments if item.valid),
        key=lambda item: item.candidate_id,
    )
    unique: list[CandidateAssessment] = []
    seen_hashes: set[str] = set()
    for item in valid:
        if item.structure_sha256 in seen_hashes:
            continue
        unique.append(item)
        seen_hashes.add(item.structure_sha256)
    frontier = _pareto_frontier(tuple(unique))
    if len(frontier) <= maximum_representatives:
        return tuple(item.candidate_id for item in frontier)
    crowding = _crowding_distances(frontier)
    selected = sorted(
        frontier,
        key=lambda item: (-crowding[item.candidate_id], item.candidate_id),
    )[:maximum_representatives]
    return tuple(item.candidate_id for item in selected)


def infer_experimental_models(
    experiment: ExperimentInput,
    registry: ProviderRegistry,
    planner: CandidatePlanner,
    *,
    xrd_settings: XRDSearchSettings | None = None,
    maximum_representatives: int = 10,
) -> ExperimentalModelingRun:
    """Run the local evidence-to-representative-model vertical slice."""

    if not 1 <= maximum_representatives <= 50:
        raise ValueError("maximum_representatives must be between 1 and 50")
    diagnostics: list[Diagnostic] = []
    xrd_path, xrd_diagnostics = _select_xrd_evidence(experiment)
    diagnostics.extend(xrd_diagnostics)
    phase_search = None
    if xrd_path is not None:
        pattern = parse_xrd_path(xrd_path)
        phase_search = search_xrd_phases(
            pattern,
            registry,
            allowed_elements=experiment.spec.model_elements,
            excluded_elements=experiment.spec.excluded_elements,
            required_elements=experiment.spec.required_bulk_elements,
            settings=xrd_settings,
        )
        diagnostics.extend(phase_search.diagnostics)

    plan = planner.plan(experiment.spec, registry, phase_search)
    diagnostics.extend(plan.diagnostics)
    executions: list[CandidateExecution] = []
    for recipe in plan.recipes:
        try:
            executions.extend(execute_candidate_recipe(recipe, registry, experiment.spec))
        except ValueError as exc:
            diagnostics.append(
                Diagnostic(
                    "CANDIDATE_RECIPE_EXECUTION_FAILED",
                    Severity.ERROR,
                    "A candidate recipe failed local deterministic validation.",
                    {
                        "recipe_id": recipe.recipe_id,
                        "exception_type": type(exc).__name__,
                        "reason": str(exc),
                    },
                )
            )

    phase_support = phase_search.ranked_reference_support() if phase_search is not None else {}
    assessments = tuple(
        _candidate_assessment(
            item,
            phase_support,
            experiment.spec,
            registry,
            phase_search,
        )
        for item in executions
    )
    representative_ids = _representatives(
        assessments,
        maximum_representatives=maximum_representatives,
    )
    unresolved = tuple(
        item.hypothesis_id for item in plan.hypotheses if not item.generated_atomistic_candidate
    )
    ambiguity = _ambiguity_reasons(phase_search, plan.hypotheses)
    if not representative_ids:
        status = InferenceStatus.NO_VALID_CANDIDATES
        claim = ClaimLevel.NO_ATOMIC_CLAIM
    elif (phase_search is not None and phase_search.status == "hypotheses_found") or any(
        check.kind == "xrd" and check.role is EvidenceRole.SOFT and check.status == "within_range"
        for assessment in assessments
        for check in assessment.evidence_checks
    ):
        status = InferenceStatus.READY_FOR_REVIEW
        claim = ClaimLevel.PHASE_FAMILY_SUPPORTED
    elif any(
        check.kind in {"composition", "xps", "tem"} and check.status != "not_applicable"
        for assessment in assessments
        for check in assessment.evidence_checks
    ):
        # Non-XRD evidence can support representative candidates without
        # supporting a crystallographic phase-family claim.
        status = InferenceStatus.READY_FOR_REVIEW
        claim = ClaimLevel.CANDIDATE_ONLY
    else:
        status = InferenceStatus.INSUFFICIENT_EVIDENCE
        claim = ClaimLevel.CANDIDATE_ONLY
    report = ExperimentalModelingReport(
        experiment=experiment.spec,
        status=status,
        claim_ceiling=claim,
        phase_search=phase_search,
        candidate_plan=plan,
        candidate_assessments=assessments,
        representative_candidate_ids=representative_ids,
        unresolved_hypothesis_ids=unresolved,
        ambiguity_reasons=ambiguity,
        recommended_next_experiments=_next_experiments(
            experiment.spec,
            phase_search,
            plan.hypotheses,
        ),
        diagnostics=tuple(diagnostics),
        external_api_called=plan.external_api_called,
    )
    return ExperimentalModelingRun(report=report, candidates=tuple(executions))


def materialize_representative_models(
    run: ExperimentalModelingRun,
    destination: str | Path,
) -> CandidateMaterializationReport:
    """Write only selected candidates into one entirely new directory."""

    target = Path(destination).resolve()
    if target.exists():
        raise ValueError("candidate destination must not already exist")
    if not target.parent.is_dir():
        raise ValueError("candidate destination parent must exist")
    representatives = run.representative_structures()
    if not representatives:
        raise ValueError("inference run has no representative structures to materialize")
    target.mkdir()
    records: list[MaterializedCandidate] = []
    manifest_candidates: list[dict[str, Any]] = []
    for index, (candidate_id, structure) in enumerate(representatives, start=1):
        candidate_directory = target / f"{index:02d}-{candidate_id}"
        candidate_directory.mkdir()
        poscar = candidate_directory / "POSCAR"
        cif = candidate_directory / "structure.cif"
        structure.to(filename=poscar, fmt="poscar")
        structure.to(filename=cif, fmt="cif")
        poscar_record = artifact_record(poscar)
        cif_record = artifact_record(cif)
        records.append(
            MaterializedCandidate(
                candidate_id=candidate_id,
                poscar=poscar_record,
                cif=cif_record,
            )
        )
        manifest_candidates.append(
            {
                "candidate_id": candidate_id,
                "structure_sha256": structure_hash(structure),
                "poscar_sha256": poscar_record.sha256,
                "cif_sha256": cif_record.sha256,
            }
        )
    manifest_path = target / "manifest.json"
    manifest_payload = {
        "schema_version": "catex.candidate-materialization-manifest.v1",
        "inference_sha256": run.report.identity_sha256,
        "claim_ceiling": run.report.claim_ceiling.value,
        "scientific_review_required": True,
        "candidates": manifest_candidates,
    }
    manifest_path.write_text(
        json.dumps(
            manifest_payload,
            allow_nan=False,
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )
    return CandidateMaterializationReport(
        inference_sha256=run.report.identity_sha256,
        destination=str(target),
        candidates=tuple(records),
        manifest=artifact_record(manifest_path),
    )
