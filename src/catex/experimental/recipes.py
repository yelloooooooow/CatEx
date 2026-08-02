"""Validated execution of the bounded candidate-recipe DSL."""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any

import numpy as np
from pymatgen.core import Lattice, Structure

from catex.experimental.models import (
    CandidateOperation,
    CandidateOperationKind,
    CandidateRecipe,
    CompositionBasis,
    CompositionScope,
    ExperimentSpec,
    ModelKind,
    content_digest,
)
from catex.experimental.providers import ProviderRegistry
from catex.hashing import structure_hash
from catex.models import Diagnostic, Severity
from catex.structures import inspect_structure
from catex.transformations import (
    create_vacancies,
    generate_slab_candidates,
    set_orthogonal_c_vacuum,
    substitute_sites,
)


@dataclass(frozen=True, slots=True)
class CandidateExecution:
    """Runtime structure plus complete deterministic recipe provenance."""

    candidate_id: str
    recipe: CandidateRecipe
    structure: Structure
    model_kind: ModelKind
    transformation_sha256s: tuple[str, ...]
    diagnostics: tuple[Diagnostic, ...]

    @property
    def valid(self) -> bool:
        return not any(item.severity is Severity.ERROR for item in self.diagnostics)


@dataclass(frozen=True, slots=True)
class _Branch:
    structure: Structure
    model_kind: ModelKind
    transformation_sha256s: tuple[str, ...]
    label: str


def _integer(value: Any, *, field_name: str, minimum: int = 0, maximum: int = 10_000) -> int:
    if not isinstance(value, int) or isinstance(value, bool) or value < minimum or value > maximum:
        raise ValueError(f"{field_name} must be an integer from {minimum} to {maximum}")
    return value


def _finite_float(
    value: Any,
    *,
    field_name: str,
    minimum: float,
    maximum: float,
) -> float:
    if not isinstance(value, int | float) or isinstance(value, bool):
        raise ValueError(f"{field_name} must be a number")
    normalized = float(value)
    if not math.isfinite(normalized) or not minimum <= normalized <= maximum:
        raise ValueError(f"{field_name} must be finite and in [{minimum}, {maximum}]")
    return normalized


def _operation_digest(
    *,
    kind: CandidateOperationKind,
    parameters: dict[str, Any],
    input_sha256: str,
    output_sha256: str,
) -> str:
    return content_digest(
        {
            "schema": "catex.experimental-operation-execution.v1",
            "kind": kind.value,
            "parameters": parameters,
            "input_sha256": input_sha256,
            "output_sha256": output_sha256,
        }
    )


def _supercell(branch: _Branch, operation: CandidateOperation) -> _Branch:
    raw = operation.parameters.get("scale")
    if not isinstance(raw, list) or len(raw) != 3:
        raise ValueError("supercell scale must be a three-integer JSON array")
    scale = tuple(
        _integer(value, field_name="supercell scale", minimum=1, maximum=12) for value in raw
    )
    if math.prod(scale) > 512:
        raise ValueError("supercell scale would create more than 512 unit-cell copies")
    parent_sha = structure_hash(branch.structure)
    child = branch.structure.copy()
    child.make_supercell(scale)
    child_sha = structure_hash(child)
    digest = _operation_digest(
        kind=operation.kind,
        parameters={"scale": list(scale)},
        input_sha256=parent_sha,
        output_sha256=child_sha,
    )
    return _Branch(
        child,
        branch.model_kind,
        (*branch.transformation_sha256s, digest),
        branch.label,
    )


def _substitute(branch: _Branch, operation: CandidateOperation, *, identity: str) -> _Branch:
    raw = operation.parameters.get("replacements")
    if not isinstance(raw, dict) or not raw:
        raise ValueError("substitute replacements must be a non-empty index-to-element object")
    replacements: dict[int, str] = {}
    for key, value in raw.items():
        try:
            index = int(key)
        except (TypeError, ValueError) as exc:
            raise ValueError("substitute replacement keys must be 0-based indices") from exc
        if str(index) != str(key) and key != index:
            raise ValueError("substitute replacement keys must be canonical integer strings")
        replacements[index] = str(value)
    product = substitute_sites(
        branch.structure,
        replacements,
        transformation_id=identity,
    )
    return _Branch(
        product.structure,
        branch.model_kind,
        (*branch.transformation_sha256s, product.record.identity_sha256),
        branch.label,
    )


def _vacancy(branch: _Branch, operation: CandidateOperation, *, identity: str) -> _Branch:
    raw = operation.parameters.get("indices_0based")
    if not isinstance(raw, list):
        raise ValueError("vacancy indices_0based must be a JSON array")
    indices = tuple(
        _integer(value, field_name="vacancy index", maximum=len(branch.structure) - 1)
        for value in raw
    )
    product = create_vacancies(
        branch.structure,
        indices,
        transformation_id=identity,
    )
    return _Branch(
        product.structure,
        branch.model_kind,
        (*branch.transformation_sha256s, product.record.identity_sha256),
        branch.label,
    )


def _isotropic_strain(branch: _Branch, operation: CandidateOperation) -> _Branch:
    strain = _finite_float(
        operation.parameters.get("strain"),
        field_name="strain",
        minimum=-0.1,
        maximum=0.1,
    )
    parent_sha = structure_hash(branch.structure)
    matrix = np.asarray(branch.structure.lattice.matrix, dtype=float) * (1.0 + strain)
    child = Structure(
        Lattice(matrix),
        [site.species for site in branch.structure],
        branch.structure.frac_coords,
        site_properties=branch.structure.site_properties,
        charge=branch.structure.charge,
    )
    child_sha = structure_hash(child)
    digest = _operation_digest(
        kind=operation.kind,
        parameters={"strain": strain},
        input_sha256=parent_sha,
        output_sha256=child_sha,
    )
    return _Branch(
        child,
        branch.model_kind,
        (*branch.transformation_sha256s, digest),
        branch.label,
    )


def _slabs(
    branch: _Branch,
    operation: CandidateOperation,
    *,
    identity_prefix: str,
) -> tuple[_Branch, ...]:
    raw_miller = operation.parameters.get("miller_index")
    if not isinstance(raw_miller, list) or len(raw_miller) != 3:
        raise ValueError("slab miller_index must be a three-integer JSON array")
    miller = tuple(
        _integer(value, field_name="miller index", minimum=-9, maximum=9) for value in raw_miller
    )
    if miller == (0, 0, 0):
        raise ValueError("slab miller_index cannot be (0, 0, 0)")
    minimum_slab = _finite_float(
        operation.parameters.get("minimum_slab_angstrom", 8.0),
        field_name="minimum_slab_angstrom",
        minimum=1.0,
        maximum=100.0,
    )
    minimum_vacuum = _finite_float(
        operation.parameters.get("minimum_vacuum_angstrom", 12.0),
        field_name="minimum_vacuum_angstrom",
        minimum=1.0,
        maximum=100.0,
    )
    maximum_candidates = _integer(
        operation.parameters.get("maximum_candidates", 8),
        field_name="maximum_candidates",
        minimum=1,
        maximum=32,
    )
    products = generate_slab_candidates(
        branch.structure,
        transformation_id_prefix=identity_prefix,
        miller_index=miller,
        minimum_slab_angstrom=minimum_slab,
        minimum_vacuum_angstrom=minimum_vacuum,
        maximum_candidates=maximum_candidates,
    )
    selected_raw = operation.parameters.get("termination_indices")
    if selected_raw is None:
        selected = tuple(range(len(products)))
    else:
        if not isinstance(selected_raw, list) or not selected_raw:
            raise ValueError("termination_indices must be a non-empty JSON array")
        selected = tuple(
            _integer(
                value,
                field_name="termination index",
                maximum=max(0, len(products) - 1),
            )
            for value in selected_raw
        )
        if len(selected) != len(set(selected)):
            raise ValueError("termination_indices must not contain duplicates")
    return tuple(
        _Branch(
            products[index].structure,
            ModelKind.SURFACE,
            (*branch.transformation_sha256s, products[index].record.identity_sha256),
            f"{branch.label}.t{index}",
        )
        for index in selected
    )


def _set_vacuum(branch: _Branch, operation: CandidateOperation, *, identity: str) -> _Branch:
    amount = _finite_float(
        operation.parameters.get("vacuum_angstrom"),
        field_name="vacuum_angstrom",
        minimum=1.0,
        maximum=100.0,
    )
    product = set_orthogonal_c_vacuum(
        branch.structure,
        amount,
        transformation_id=identity,
    )
    return _Branch(
        product.structure,
        ModelKind.SURFACE,
        (*branch.transformation_sha256s, product.record.identity_sha256),
        branch.label,
    )


def _top_region_indices(structure: Structure, *, depth_angstrom: float) -> tuple[int, ...]:
    matrix = np.asarray(structure.lattice.matrix, dtype=float)
    c_hat = matrix[2] / np.linalg.norm(matrix[2])
    projected = np.asarray(structure.cart_coords, dtype=float) @ c_hat
    top = float(np.max(projected))
    return tuple(
        index for index, value in enumerate(projected) if top - float(value) <= depth_angstrom
    )


def _rounded_counts(fractions: dict[str, float], total: int) -> dict[str, int]:
    raw = {element: fraction * total for element, fraction in fractions.items()}
    counts = {element: math.floor(value) for element, value in raw.items()}
    remaining = total - sum(counts.values())
    for element in sorted(raw, key=lambda item: (-(raw[item] - counts[item]), item))[:remaining]:
        counts[element] += 1
    return counts


def _match_composition(
    branch: _Branch,
    operation: CandidateOperation,
    *,
    identity: str,
) -> _Branch:
    raw = operation.parameters.get("target_fractions")
    if not isinstance(raw, dict) or not raw:
        raise ValueError("match_composition target_fractions must be a non-empty object")
    from pymatgen.core import Element

    fractions: dict[str, float] = {}
    for key, value in raw.items():
        try:
            symbol = Element(str(key)).symbol
        except ValueError as exc:
            raise ValueError("match_composition target element is invalid") from exc
        fractions[symbol] = _finite_float(
            value,
            field_name=f"target fraction for {symbol}",
            minimum=0.0,
            maximum=1.0,
        )
    total_fraction = sum(fractions.values())
    if not math.isclose(total_fraction, 1.0, abs_tol=1e-6):
        raise ValueError("match_composition target fractions must sum to one")
    scope = str(operation.parameters.get("scope", "bulk"))
    if scope not in {"bulk", "surface"}:
        raise ValueError("match_composition scope must be bulk or surface")
    basis = CompositionBasis(str(operation.parameters.get("basis", "total_atomic_fraction")))
    if basis is CompositionBasis.WEIGHT_FRACTION:
        raise ValueError("match_composition does not convert weight fractions into site counts")
    depth = _finite_float(
        operation.parameters.get("surface_depth_angstrom", 3.0),
        field_name="surface_depth_angstrom",
        minimum=0.5,
        maximum=20.0,
    )
    if scope == "surface":
        if branch.model_kind is not ModelKind.SURFACE:
            raise ValueError("surface composition matching requires a slab candidate")
        region = _top_region_indices(branch.structure, depth_angstrom=depth)
    else:
        region = tuple(range(len(branch.structure)))
    if basis is CompositionBasis.METAL_NORMALIZED_ATOMIC_FRACTION:
        region = tuple(
            index for index in region if Element(str(branch.structure[index].specie)).is_metal
        )
    eligible = tuple(index for index in region if str(branch.structure[index].specie) in fractions)
    # Include existing sites as replaceable hosts even when one requested element is absent.
    if len(eligible) < len(region):
        eligible = tuple(
            index
            for index in region
            if basis is CompositionBasis.TOTAL_ATOMIC_FRACTION
            or Element(str(branch.structure[index].specie)).is_metal
        )
    if not eligible:
        raise ValueError("match_composition found no eligible sites")
    desired = _rounded_counts(fractions, len(eligible))
    remaining_by_species = dict(desired)
    replacements: dict[int, str] = {}
    surplus: list[int] = []
    for index in sorted(
        eligible,
        key=lambda item: (*np.asarray(branch.structure[item].frac_coords, dtype=float), item),
    ):
        current = str(branch.structure[index].specie)
        if remaining_by_species.get(current, 0) > 0:
            remaining_by_species[current] -= 1
        else:
            surplus.append(index)
    deficits = [
        element
        for element in sorted(remaining_by_species)
        for _ in range(remaining_by_species[element])
    ]
    if len(surplus) != len(deficits):
        raise ValueError("match_composition could not balance target site counts")
    replacements.update(zip(surplus, deficits, strict=True))
    if replacements:
        product = substitute_sites(
            branch.structure,
            replacements,
            transformation_id=identity,
        )
        child = product.structure
        digest = product.record.identity_sha256
    else:
        child = branch.structure.copy()
        digest = _operation_digest(
            kind=operation.kind,
            parameters={
                "target_fractions": fractions,
                "scope": scope,
                "basis": basis.value,
                "surface_depth_angstrom": depth,
            },
            input_sha256=structure_hash(branch.structure),
            output_sha256=structure_hash(child),
        )
    return _Branch(
        child,
        branch.model_kind,
        (*branch.transformation_sha256s, digest),
        branch.label,
    )


def _add_surface_coordination(
    branch: _Branch,
    operation: CandidateOperation,
) -> _Branch:
    if branch.model_kind is not ModelKind.SURFACE:
        raise ValueError("surface coordination requires a slab candidate")
    from pymatgen.core import Element

    try:
        center = Element(str(operation.parameters.get("element"))).symbol
        neighbor = Element(str(operation.parameters.get("neighbor_element"))).symbol
    except ValueError as exc:
        raise ValueError("surface coordination elements are invalid") from exc
    fraction = _finite_float(
        operation.parameters.get("target_site_fraction"),
        field_name="target_site_fraction",
        minimum=0.0,
        maximum=1.0,
    )
    cutoff = _finite_float(
        operation.parameters.get("cutoff_angstrom", 2.6),
        field_name="cutoff_angstrom",
        minimum=0.5,
        maximum=6.0,
    )
    height = _finite_float(
        operation.parameters.get("height_angstrom", min(2.0, cutoff * 0.75)),
        field_name="height_angstrom",
        minimum=0.6,
        maximum=4.0,
    )
    depth = _finite_float(
        operation.parameters.get("surface_depth_angstrom", 3.0),
        field_name="surface_depth_angstrom",
        minimum=0.5,
        maximum=20.0,
    )
    top_region = _top_region_indices(branch.structure, depth_angstrom=depth)
    centers = [index for index in top_region if str(branch.structure[index].specie) == center]
    if not centers:
        raise ValueError(f"surface coordination found no top-surface {center} sites")
    already_coordinated = {
        index
        for index in centers
        if any(
            str(site.specie) == neighbor
            for site in branch.structure.get_neighbors(branch.structure[index], cutoff)
        )
    }
    target_count = min(len(centers), math.ceil(fraction * len(centers)))
    to_add = max(0, target_count - len(already_coordinated))
    available = [index for index in centers if index not in already_coordinated]
    selected = available[:to_add]
    child = branch.structure.copy()
    c_vector = np.asarray(child.lattice.matrix[2], dtype=float)
    c_hat = c_vector / np.linalg.norm(c_vector)
    for index in selected:
        coordinate = np.asarray(branch.structure[index].coords, dtype=float) + c_hat * height
        child.append(neighbor, coordinate, coords_are_cartesian=True, validate_proximity=True)
    digest = _operation_digest(
        kind=operation.kind,
        parameters={
            "element": center,
            "neighbor_element": neighbor,
            "target_site_fraction": fraction,
            "cutoff_angstrom": cutoff,
            "height_angstrom": height,
            "surface_depth_angstrom": depth,
            "added_count": len(selected),
        },
        input_sha256=structure_hash(branch.structure),
        output_sha256=structure_hash(child),
    )
    return _Branch(
        child,
        ModelKind.SURFACE,
        (*branch.transformation_sha256s, digest),
        branch.label,
    )


def _composition_diagnostics(
    structure: Structure,
    spec: ExperimentSpec,
    *,
    model_kind: ModelKind,
) -> tuple[Diagnostic, ...]:
    elements = {item.symbol for item in structure.composition.elements}
    diagnostics: list[Diagnostic] = []
    excluded = set(spec.excluded_elements) & elements
    if excluded:
        diagnostics.append(
            Diagnostic(
                "CANDIDATE_EXCLUDED_ELEMENT",
                Severity.ERROR,
                "The candidate contains an explicitly excluded element.",
                {"elements": sorted(excluded)},
            )
        )
    if spec.model_elements and not elements <= set(spec.model_elements):
        diagnostics.append(
            Diagnostic(
                "CANDIDATE_OUTSIDE_ALLOWED_CHEMISTRY",
                Severity.ERROR,
                "The candidate contains elements outside the declared chemical system.",
                {"elements": sorted(elements - set(spec.model_elements))},
            )
        )
    required = set(spec.required_bulk_elements)
    missing = required - elements
    if model_kind is ModelKind.BULK and missing:
        diagnostics.append(
            Diagnostic(
                "CANDIDATE_MISSING_REQUIRED_BULK_ELEMENT",
                Severity.WARNING,
                "A single phase need not contain every bulk element; mixture coverage is required.",
                {"elements": sorted(missing)},
            )
        )

    total = float(structure.composition.num_atoms)
    for constraint in spec.composition_constraints:
        if constraint.scope is not CompositionScope.BULK:
            continue
        fraction = float(structure.composition.get(constraint.element, 0.0)) / total
        if model_kind is ModelKind.SURFACE:
            diagnostics.append(
                Diagnostic(
                    "SURFACE_STOICHIOMETRY_NOT_BULK_COMPOSITION",
                    Severity.INFO,
                    "A slab termination is not expected to reproduce bulk composition exactly.",
                    {"element": constraint.element, "slab_atomic_fraction": fraction},
                )
            )
        elif not (
            constraint.minimum_atomic_fraction <= fraction <= constraint.maximum_atomic_fraction
        ):
            diagnostics.append(
                Diagnostic(
                    "SINGLE_PHASE_COMPOSITION_INTERVAL_MISMATCH",
                    Severity.INFO,
                    "The phase alone falls outside a bulk composition interval; a mixture may fit.",
                    {
                        "element": constraint.element,
                        "candidate_atomic_fraction": fraction,
                        "minimum": constraint.minimum_atomic_fraction,
                        "maximum": constraint.maximum_atomic_fraction,
                    },
                )
            )
    return tuple(diagnostics)


def execute_candidate_recipe(
    recipe: CandidateRecipe,
    registry: ProviderRegistry,
    spec: ExperimentSpec,
) -> tuple[CandidateExecution, ...]:
    """Execute one bounded recipe and return every explicit slab termination branch."""

    parent = registry.get_structure(recipe.parent_reference_key)
    reference = registry.get_reference(recipe.parent_reference_key)
    if structure_hash(parent) != reference.structure_sha256:
        raise ValueError("provider returned a structure that does not match its reference hash")
    branches = (_Branch(parent, ModelKind.BULK, (), "b0"),)
    for operation_index, operation in enumerate(recipe.operations):
        next_branches: list[_Branch] = []
        for branch_index, branch in enumerate(branches):
            identity = f"{recipe.recipe_id}.o{operation_index}.b{branch_index}"
            if operation.kind is CandidateOperationKind.IDENTITY:
                next_branches.append(branch)
            elif operation.kind is CandidateOperationKind.SUPERCELL:
                next_branches.append(_supercell(branch, operation))
            elif operation.kind is CandidateOperationKind.SUBSTITUTE:
                next_branches.append(_substitute(branch, operation, identity=identity))
            elif operation.kind is CandidateOperationKind.VACANCY:
                next_branches.append(_vacancy(branch, operation, identity=identity))
            elif operation.kind is CandidateOperationKind.ISOTROPIC_STRAIN:
                next_branches.append(_isotropic_strain(branch, operation))
            elif operation.kind is CandidateOperationKind.SLAB:
                next_branches.extend(_slabs(branch, operation, identity_prefix=identity))
            elif operation.kind is CandidateOperationKind.SET_VACUUM:
                next_branches.append(_set_vacuum(branch, operation, identity=identity))
            elif operation.kind is CandidateOperationKind.MATCH_COMPOSITION:
                next_branches.append(_match_composition(branch, operation, identity=identity))
            elif operation.kind is CandidateOperationKind.ADD_SURFACE_COORDINATION:
                next_branches.append(_add_surface_coordination(branch, operation))
            else:  # pragma: no cover - exhaustive enum guard
                raise ValueError(f"unsupported candidate operation: {operation.kind.value}")
        branches = tuple(next_branches)
        if not branches:
            raise ValueError("candidate recipe produced no structure branches")

    executions: list[CandidateExecution] = []
    for index, branch in enumerate(branches):
        inspection = inspect_structure(branch.structure)
        diagnostics = (
            *inspection.diagnostics,
            *_composition_diagnostics(branch.structure, spec, model_kind=branch.model_kind),
        )
        executions.append(
            CandidateExecution(
                candidate_id=f"{recipe.recipe_id}.c{index}",
                recipe=recipe,
                structure=branch.structure,
                model_kind=branch.model_kind,
                transformation_sha256s=branch.transformation_sha256s,
                diagnostics=diagnostics,
            )
        )
    return tuple(executions)
