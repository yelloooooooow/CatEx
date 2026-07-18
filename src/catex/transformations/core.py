"""Deterministic in-memory structure transformations with explicit provenance."""

from __future__ import annotations

import hashlib
import json
import math
import re
from collections.abc import Mapping, Sequence
from dataclasses import replace
from datetime import datetime
from typing import Any

import numpy as np
from pymatgen.core import Element, Lattice, Structure
from pymatgen.core.surface import SlabGenerator

from catex.catalysis import (
    CatalystModelKind,
    CatalystSystem,
    StructureOrigin,
    create_catalyst_system,
    ordered_structure_hash,
)
from catex.hashing import structure_hash
from catex.models import Diagnostic, Severity
from catex.structures import inspect_structure
from catex.transformations.models import (
    AtomMappingKind,
    ParentAtomLineage,
    StructureTransformationOperation,
    StructureTransformationRecord,
    TransformationProduct,
    TransformationReadinessReport,
    TransformationReview,
    TransformationReviewDecision,
)

_IDENTIFIER = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,99}$")
_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_UTC_TIMESTAMP = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$")
_UTC_FORMAT = "%Y-%m-%dT%H:%M:%SZ"


def _digest(payload: dict[str, Any]) -> str:
    encoded = json.dumps(
        payload,
        allow_nan=False,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _identifier(value: str, *, field: str) -> str:
    if not isinstance(value, str) or _IDENTIFIER.fullmatch(value) is None:
        raise ValueError(f"{field} must be a safe identifier of at most 100 characters")
    return value


def _one_line(value: str, *, field: str, maximum: int) -> str:
    if not isinstance(value, str) or any(item in value for item in "\r\n"):
        raise ValueError(f"{field} must be one line")
    normalized = value.strip()
    if not normalized or len(normalized) > maximum:
        raise ValueError(f"{field} must be non-empty and at most {maximum} characters")
    return normalized


def _timestamp(value: str) -> None:
    if not isinstance(value, str) or _UTC_TIMESTAMP.fullmatch(value) is None:
        raise ValueError("reviewed_at_utc must use YYYY-MM-DDTHH:MM:SSZ")
    try:
        datetime.strptime(value, _UTC_FORMAT)
    except ValueError as exc:
        raise ValueError("reviewed_at_utc must be a valid UTC timestamp") from exc


def _finite_positive(value: float, *, field: str) -> float:
    if (
        not isinstance(value, int | float)
        or isinstance(value, bool)
        or not math.isfinite(value)
        or value <= 0
    ):
        raise ValueError(f"{field} must be a finite positive number")
    return float(value)


def _record_payload(record: StructureTransformationRecord) -> dict[str, Any]:
    return {
        "schema": "catex.structure-transformation-content.v1",
        "transformation_id": record.transformation_id,
        "operation": record.operation.value,
        "input_canonical_sha256": record.input_canonical_sha256,
        "input_ordered_sha256": record.input_ordered_sha256,
        "output_canonical_sha256": record.output_canonical_sha256,
        "output_ordered_sha256": record.output_ordered_sha256,
        "parameters": dict(record.parameters),
        "mapping_kind": record.mapping_kind.value,
        "parent_atom_lineage": [item.to_dict() for item in record.parent_atom_lineage],
        "removed_parent_indices_0based": list(record.removed_parent_indices_0based),
        "created_child_indices_0based": list(record.created_child_indices_0based),
        "exact_atom_mapping_complete": record.exact_atom_mapping_complete,
    }


def _product(
    parent: Structure,
    child: Structure,
    *,
    transformation_id: str,
    operation: StructureTransformationOperation,
    parameters: Mapping[str, Any],
    mapping_kind: AtomMappingKind,
    lineage: Sequence[ParentAtomLineage],
    removed: Sequence[int] = (),
    created: Sequence[int] = (),
    exact_complete: bool,
    diagnostics: Sequence[Diagnostic] = (),
) -> TransformationProduct:
    if not isinstance(parent, Structure) or not isinstance(child, Structure):
        raise ValueError("parent and child must be pymatgen Structure objects")
    provisional = StructureTransformationRecord(
        transformation_id=_identifier(transformation_id, field="transformation_id"),
        operation=operation,
        input_canonical_sha256=structure_hash(parent),
        input_ordered_sha256=ordered_structure_hash(parent),
        output_canonical_sha256=structure_hash(child),
        output_ordered_sha256=ordered_structure_hash(child),
        parameters=parameters,
        mapping_kind=mapping_kind,
        parent_atom_lineage=tuple(lineage),
        removed_parent_indices_0based=tuple(removed),
        created_child_indices_0based=tuple(created),
        exact_atom_mapping_complete=exact_complete,
        identity_sha256="0" * 64,
    )
    record = replace(provisional, identity_sha256=_digest(_record_payload(provisional)))
    return TransformationProduct(
        structure=child,
        record=record,
        diagnostics=tuple(diagnostics),
    )


def _indices(values: Sequence[int], *, size: int, field: str) -> tuple[int, ...]:
    result = tuple(values)
    if (
        not result
        or any(not isinstance(item, int) or isinstance(item, bool) for item in result)
        or len(set(result)) != len(result)
        or any(item < 0 or item >= size for item in result)
    ):
        raise ValueError(f"{field} must contain unique valid 0-based indices")
    return tuple(sorted(result))


def create_vacancies(
    structure: Structure,
    vacancy_indices_0based: Sequence[int],
    *,
    transformation_id: str,
) -> TransformationProduct:
    """Remove explicit sites and retain an exact parent-to-child atom mapping."""

    indices = _indices(
        vacancy_indices_0based,
        size=len(structure),
        field="vacancy_indices_0based",
    )
    if len(indices) >= len(structure):
        raise ValueError("vacancy transformation cannot remove every site")
    child = structure.copy()
    child.remove_sites(indices)
    removed_set = set(indices)
    lineage: list[ParentAtomLineage] = []
    child_index = 0
    for parent_index in range(len(structure)):
        children = () if parent_index in removed_set else (child_index,)
        lineage.append(ParentAtomLineage(parent_index, children))
        child_index += len(children)
    return _product(
        structure,
        child,
        transformation_id=transformation_id,
        operation=StructureTransformationOperation.VACANCY,
        parameters={"vacancy_indices_0based": list(indices)},
        mapping_kind=AtomMappingKind.EXACT_INDEX,
        lineage=lineage,
        removed=indices,
        exact_complete=True,
    )


def _replace_sites(
    structure: Structure,
    replacements: Mapping[int, str],
    *,
    transformation_id: str,
    operation: StructureTransformationOperation,
) -> TransformationProduct:
    if not isinstance(replacements, Mapping) or not replacements:
        raise ValueError("replacements must be a non-empty index-to-element mapping")
    indices = _indices(tuple(replacements), size=len(structure), field="replacement indices")
    normalized: dict[int, str] = {}
    for index in indices:
        raw = replacements[index]
        if not isinstance(raw, str):
            raise ValueError("replacement species must be element symbols")
        try:
            element = Element(raw)
        except ValueError as exc:
            raise ValueError(f"invalid replacement element: {raw!r}") from exc
        if str(structure[index].specie) == element.symbol:
            raise ValueError("replacement must change the element at every selected site")
        normalized[index] = element.symbol

    child = structure.copy()
    for index, element in normalized.items():
        child.replace(index, element)
    lineage = tuple(ParentAtomLineage(index, (index,)) for index in range(len(structure)))
    return _product(
        structure,
        child,
        transformation_id=transformation_id,
        operation=operation,
        parameters={
            "replacements": [
                {
                    "index_0based": index,
                    "from": str(structure[index].specie),
                    "to": normalized[index],
                }
                for index in indices
            ]
        },
        mapping_kind=AtomMappingKind.EXACT_INDEX,
        lineage=lineage,
        exact_complete=True,
    )


def substitute_sites(
    structure: Structure,
    replacements: Mapping[int, str],
    *,
    transformation_id: str,
) -> TransformationProduct:
    """Apply explicit compositional substitutions without guessing sites."""

    return _replace_sites(
        structure,
        replacements,
        transformation_id=transformation_id,
        operation=StructureTransformationOperation.SUBSTITUTION,
    )


def dope_sites(
    structure: Structure,
    replacements: Mapping[int, str],
    *,
    transformation_id: str,
) -> TransformationProduct:
    """Apply explicit dopant substitutions with distinct scientific provenance."""

    return _replace_sites(
        structure,
        replacements,
        transformation_id=transformation_id,
        operation=StructureTransformationOperation.DOPING,
    )


def set_orthogonal_c_vacuum(
    structure: Structure,
    vacuum_angstrom: float,
    *,
    transformation_id: str,
    orthogonality_tolerance: float = 1e-8,
) -> TransformationProduct:
    """Set vacuum along a c axis that is perpendicular to the in-plane lattice."""

    vacuum = _finite_positive(vacuum_angstrom, field="vacuum_angstrom")
    tolerance = _finite_positive(
        orthogonality_tolerance,
        field="orthogonality_tolerance",
    )
    if len(structure) == 0:
        raise ValueError("vacuum transformation requires a non-empty structure")
    matrix = np.asarray(structure.lattice.matrix, dtype=float)
    a_vector, b_vector, c_vector = matrix
    c_length = float(np.linalg.norm(c_vector))
    c_hat = c_vector / c_length
    if (
        abs(float(np.dot(a_vector, c_hat))) > tolerance
        or abs(float(np.dot(b_vector, c_hat))) > tolerance
    ):
        raise ValueError("c must be perpendicular to both in-plane lattice vectors")

    wrapped = np.mod(np.asarray(structure.frac_coords, dtype=float)[:, 2], 1.0)
    order = np.argsort(wrapped)
    sorted_z = wrapped[order]
    gaps = np.diff(np.concatenate((sorted_z, [sorted_z[0] + 1.0])))
    gap_index = int(np.argmax(gaps))
    start = sorted_z[(gap_index + 1) % len(sorted_z)]
    unwrapped = np.mod(wrapped - start, 1.0)
    unwrapped[np.isclose(unwrapped, 1.0, atol=1e-10)] = 0.0
    distances = unwrapped * c_length
    distances -= float(np.min(distances))
    occupied_span = float(np.max(distances))
    new_c_length = occupied_span + vacuum
    new_projections = distances + vacuum / 2.0

    cartesian = np.asarray(structure.cart_coords, dtype=float)
    in_plane = cartesian - np.outer(cartesian @ c_hat, c_hat)
    new_cartesian = in_plane + np.outer(new_projections, c_hat)
    lattice = Lattice([a_vector, b_vector, c_hat * new_c_length])
    child = Structure(
        lattice,
        [site.species for site in structure],
        new_cartesian,
        coords_are_cartesian=True,
        site_properties=structure.site_properties,
        charge=structure.charge,
    )
    lineage = tuple(ParentAtomLineage(index, (index,)) for index in range(len(structure)))
    return _product(
        structure,
        child,
        transformation_id=transformation_id,
        operation=StructureTransformationOperation.SET_VACUUM,
        parameters={
            "vacuum_angstrom": vacuum,
            "occupied_span_angstrom": occupied_span,
            "axis": "c",
            "orthogonality_tolerance": tolerance,
        },
        mapping_kind=AtomMappingKind.EXACT_INDEX,
        lineage=lineage,
        exact_complete=True,
    )


def generate_slab_candidates(
    bulk: Structure,
    *,
    transformation_id_prefix: str,
    miller_index: Sequence[int],
    minimum_slab_angstrom: float,
    minimum_vacuum_angstrom: float,
    primitive: bool = False,
    lll_reduce: bool = False,
    maximum_candidates: int = 32,
) -> tuple[TransformationProduct, ...]:
    """Generate deterministic slab candidates without selecting a termination."""

    prefix = _identifier(transformation_id_prefix, field="transformation_id_prefix")
    miller = tuple(miller_index)
    if (
        len(miller) != 3
        or any(not isinstance(item, int) or isinstance(item, bool) for item in miller)
        or miller == (0, 0, 0)
    ):
        raise ValueError("miller_index must contain three integers and cannot be (0, 0, 0)")
    slab_size = _finite_positive(minimum_slab_angstrom, field="minimum_slab_angstrom")
    vacuum_size = _finite_positive(
        minimum_vacuum_angstrom,
        field="minimum_vacuum_angstrom",
    )
    if not isinstance(primitive, bool) or not isinstance(lll_reduce, bool):
        raise ValueError("primitive and lll_reduce must be booleans")
    if (
        not isinstance(maximum_candidates, int)
        or isinstance(maximum_candidates, bool)
        or maximum_candidates < 1
        or maximum_candidates > 256
    ):
        raise ValueError("maximum_candidates must be an integer from 1 to 256")

    generator = SlabGenerator(
        bulk,
        miller,
        slab_size,
        vacuum_size,
        lll_reduce=lll_reduce,
        center_slab=True,
        primitive=primitive,
        reorient_lattice=True,
    )
    slabs = generator.get_slabs(
        symmetrize=False,
        repair=False,
        filter_out_sym_slabs=True,
    )
    if not slabs:
        raise ValueError("pymatgen did not generate any slab candidates")
    if len(slabs) > maximum_candidates:
        raise ValueError("slab candidate count exceeds the explicit safety limit")
    ordered_slabs = tuple(
        sorted(
            slabs,
            key=lambda item: (structure_hash(item), ordered_structure_hash(item)),
        )
    )
    products: list[TransformationProduct] = []
    for candidate_index, slab in enumerate(ordered_slabs):
        classes: dict[int, list[int]] = {}
        mapping_available = True
        for child_index, site in enumerate(slab):
            raw = site.properties.get("bulk_equivalent")
            if not isinstance(raw, int) or raw < 0:
                mapping_available = False
                break
            classes.setdefault(raw, []).append(child_index)
        if not mapping_available:
            raise ValueError("slab candidate lacks pymatgen bulk-equivalence lineage")
        lineage = tuple(
            ParentAtomLineage(parent, tuple(children))
            for parent, children in sorted(classes.items())
        )
        products.append(
            _product(
                bulk,
                slab,
                transformation_id=f"{prefix}-{candidate_index:03d}",
                operation=StructureTransformationOperation.SLAB_GENERATION,
                parameters={
                    "candidate_index_0based": candidate_index,
                    "miller_index": list(miller),
                    "minimum_slab_angstrom": slab_size,
                    "minimum_vacuum_angstrom": vacuum_size,
                    "primitive": primitive,
                    "lll_reduce": lll_reduce,
                    "center_slab": True,
                    "symmetrize": False,
                    "repair": False,
                    "filter_out_sym_slabs": True,
                },
                mapping_kind=AtomMappingKind.BULK_EQUIVALENCE,
                lineage=lineage,
                exact_complete=False,
                diagnostics=(
                    Diagnostic(
                        "SLAB_TERMINATION_REVIEW_REQUIRED",
                        Severity.WARNING,
                        "Generated slab termination and bulk-equivalence mapping require review.",
                        {"candidate_index_0based": candidate_index},
                    ),
                ),
            )
        )
    return tuple(products)


def _valid_record(record: object) -> bool:
    try:
        return (
            isinstance(record, StructureTransformationRecord)
            and record.schema_version == "catex.structure-transformation.v1"
            and _IDENTIFIER.fullmatch(record.transformation_id) is not None
            and isinstance(record.operation, StructureTransformationOperation)
            and isinstance(record.mapping_kind, AtomMappingKind)
            and all(
                _SHA256.fullmatch(item) is not None
                for item in (
                    record.input_canonical_sha256,
                    record.input_ordered_sha256,
                    record.output_canonical_sha256,
                    record.output_ordered_sha256,
                    record.identity_sha256,
                )
            )
            and record.identity_sha256 == _digest(_record_payload(record))
            and record.manual_review_required
            and not record.writes_performed
            and not record.commands_executed
        )
    except (AttributeError, TypeError, ValueError):
        return False


def _review_payload(review: TransformationReview) -> dict[str, Any]:
    return {
        "schema": "catex.transformation-review-content.v1",
        "decision": review.decision.value,
        "transformation_id": review.transformation_id,
        "transformation_identity_sha256": review.transformation_identity_sha256,
        "reviewer": review.reviewer,
        "reviewed_at_utc": review.reviewed_at_utc,
        "note": review.note,
    }


def record_transformation_review(
    record: StructureTransformationRecord,
    *,
    accepted: bool,
    reviewer: str,
    reviewed_at_utc: str,
    note: str,
) -> TransformationReview:
    """Record a human transformation decision without changing the product."""

    if not _valid_record(record):
        raise ValueError("record must be an intact structure transformation")
    if not isinstance(accepted, bool):
        raise ValueError("accepted must be a boolean")
    reviewer_value = _one_line(reviewer, field="reviewer", maximum=100)
    note_value = _one_line(note, field="note", maximum=500)
    _timestamp(reviewed_at_utc)
    provisional = TransformationReview(
        decision=(
            TransformationReviewDecision.APPROVED
            if accepted
            else TransformationReviewDecision.REJECTED
        ),
        transformation_id=record.transformation_id,
        transformation_identity_sha256=record.identity_sha256,
        reviewer=reviewer_value,
        reviewed_at_utc=reviewed_at_utc,
        note=note_value,
        review_sha256="0" * 64,
    )
    return replace(provisional, review_sha256=_digest(_review_payload(provisional)))


def _valid_review(review: object, record: StructureTransformationRecord) -> bool:
    try:
        return (
            isinstance(review, TransformationReview)
            and review.schema_version == "catex.transformation-review.v1"
            and isinstance(review.decision, TransformationReviewDecision)
            and review.transformation_id == record.transformation_id
            and review.transformation_identity_sha256 == record.identity_sha256
            and _SHA256.fullmatch(review.review_sha256) is not None
            and review.review_sha256 == _digest(_review_payload(review))
            and review.human_review_recorded
            and not review.automatic_approval_performed
            and not review.writes_performed
            and not review.commands_executed
        )
    except (AttributeError, TypeError, ValueError):
        return False


def assess_transformation_readiness(
    product: TransformationProduct,
    reviews: Sequence[TransformationReview],
) -> TransformationReadinessReport:
    """Require an intact live output and exactly one approval before registration."""

    diagnostics: list[Diagnostic] = []
    intact = (
        isinstance(product, TransformationProduct)
        and _valid_record(product.record)
        and isinstance(product.structure, Structure)
        and structure_hash(product.structure) == product.record.output_canonical_sha256
        and ordered_structure_hash(product.structure) == product.record.output_ordered_sha256
        and not product.has_errors
    )
    if not intact:
        diagnostics.append(
            Diagnostic(
                "TRANSFORMATION_PRODUCT_INVALID",
                Severity.ERROR,
                "Live structure and transformation provenance must remain intact.",
            )
        )
    bound = tuple(item for item in reviews if _valid_review(item, product.record))
    approved = tuple(
        item for item in bound if item.decision is TransformationReviewDecision.APPROVED
    )
    if len(bound) != 1 or len(approved) != 1:
        diagnostics.append(
            Diagnostic(
                "TRANSFORMATION_APPROVAL_MISSING_OR_AMBIGUOUS",
                Severity.ERROR,
                "Exactly one valid transformation approval is required.",
                {
                    "bound_review_count": len(bound),
                    "valid_approval_count": len(approved),
                },
            )
        )
    ready = intact and not diagnostics
    return TransformationReadinessReport(
        transformation_id=product.record.transformation_id,
        transformation_identity_sha256=product.record.identity_sha256,
        ready_for_catalyst_registration=ready,
        accepted_review_sha256=approved[0].review_sha256 if ready else None,
        diagnostics=tuple(diagnostics),
    )


def register_transformed_catalyst(
    product: TransformationProduct,
    readiness: TransformationReadinessReport,
    *,
    catalyst_id: str,
    model_kind: CatalystModelKind,
) -> CatalystSystem:
    """Register a reviewed transformation product as a catalyst identity."""

    if (
        not isinstance(readiness, TransformationReadinessReport)
        or not readiness.ready_for_catalyst_registration
        or readiness.transformation_id != product.record.transformation_id
        or readiness.transformation_identity_sha256 != product.record.identity_sha256
        or readiness.accepted_review_sha256 is None
    ):
        raise ValueError("transformation product must pass its explicit review gate")
    inspected = inspect_structure(product.structure)
    if inspected.record is None or inspected.has_errors:
        raise ValueError("transformed structure must pass structure inspection")
    return create_catalyst_system(
        inspected.record,
        product.structure,
        catalyst_id=catalyst_id,
        model_kind=model_kind,
        structure_origin=StructureOrigin.TRANSFORMED,
        transformation_sha256s=(product.record.identity_sha256,),
    )
