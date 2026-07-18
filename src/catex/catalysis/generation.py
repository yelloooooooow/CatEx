"""Rigid adsorption placement, geometry deduplication, and collinear spin planning."""

from __future__ import annotations

import hashlib
import json
import math
import re
from collections.abc import Sequence
from dataclasses import replace
from typing import Any

import numpy as np
from pymatgen.core import Molecule, Structure
from pymatgen.util.coord import pbc_diff

from catex.catalysis.generation_models import (
    AdsorptionGenerationRecord,
    BindingAlignmentMode,
    BindingAnchorPair,
    ConfigurationDeduplicationGroup,
    ConfigurationDeduplicationReport,
    GeneratedAdsorptionConfiguration,
    MultiSpinCalculationPlan,
    SpinInitialization,
    SpinProtocolVariant,
)
from catex.catalysis.identity import (
    create_adsorbate,
    create_adsorption_configuration,
    is_intact_catalysis_identity,
    ordered_structure_hash,
)
from catex.catalysis.models import (
    Adsorbate,
    AdsorptionConfiguration,
    AdsorptionPlacementKind,
    CatalystSystem,
    ConfigurationReadinessReport,
    SiteDefinition,
)
from catex.hashing import structure_hash
from catex.workflow import ScientificProtocol

_IDENTIFIER = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,99}$")
_SHA256 = re.compile(r"^[0-9a-f]{64}$")


def _digest(payload: dict[str, Any]) -> str:
    encoded = json.dumps(
        payload,
        allow_nan=False,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _identifier(value: str, *, field: str, maximum: int = 100) -> str:
    if not isinstance(value, str) or _IDENTIFIER.fullmatch(value) is None or len(value) > maximum:
        raise ValueError(f"{field} must be a safe identifier of at most {maximum} characters")
    return value


def _finite_positive(value: float, *, field: str) -> float:
    if (
        not isinstance(value, int | float)
        or isinstance(value, bool)
        or not math.isfinite(value)
        or value <= 0
    ):
        raise ValueError(f"{field} must be a finite positive number")
    return float(value)


def _rotation_from_vectors(source: np.ndarray, target: np.ndarray) -> np.ndarray:
    source_unit = source / np.linalg.norm(source)
    target_unit = target / np.linalg.norm(target)
    cross = np.cross(source_unit, target_unit)
    sine = float(np.linalg.norm(cross))
    cosine = float(np.clip(np.dot(source_unit, target_unit), -1.0, 1.0))
    if sine < 1e-12:
        if cosine > 0:
            return np.eye(3)
        basis = np.array([1.0, 0.0, 0.0])
        if abs(float(np.dot(source_unit, basis))) > 0.9:
            basis = np.array([0.0, 1.0, 0.0])
        axis = np.cross(source_unit, basis)
        axis /= np.linalg.norm(axis)
        return 2.0 * np.outer(axis, axis) - np.eye(3)
    axis = cross / sine
    skew = np.array([[0.0, -axis[2], axis[1]], [axis[2], 0.0, -axis[0]], [-axis[1], axis[0], 0.0]])
    return np.eye(3) + skew * sine + (skew @ skew) * (1.0 - cosine)


def _alignment(source: np.ndarray, target: np.ndarray) -> tuple[np.ndarray, BindingAlignmentMode]:
    count = len(source)
    if count == 1:
        return np.eye(3), BindingAlignmentMode.TRANSLATION_ONLY
    if count == 2:
        source_vector = source[1] - source[0]
        target_vector = target[1] - target[0]
        if np.linalg.norm(source_vector) < 1e-10 or np.linalg.norm(target_vector) < 1e-10:
            raise ValueError("two-point alignment requires distinct source and target points")
        return (
            _rotation_from_vectors(source_vector, target_vector),
            BindingAlignmentMode.TWO_POINT_RIGID,
        )
    covariance = source.T @ target
    left, _, right_transpose = np.linalg.svd(covariance)
    rotation = right_transpose.T @ left.T
    if np.linalg.det(rotation) < 0:
        right_transpose[-1, :] *= -1
        rotation = right_transpose.T @ left.T
    return rotation, BindingAlignmentMode.KABSCH


def _generation_payload(record: AdsorptionGenerationRecord) -> dict[str, Any]:
    return {
        "schema": "catex.adsorption-generation-content.v1",
        "generation_id": record.generation_id,
        "configuration_id": record.configuration_id,
        "configuration_identity_sha256": record.configuration_identity_sha256,
        "binding_anchor_pairs": [item.to_dict() for item in record.binding_anchor_pairs],
        "height_angstrom": record.height_angstrom,
        "alignment_mode": record.alignment_mode.value,
        "binding_alignment_rmsd_angstrom": record.binding_alignment_rmsd_angstrom,
        "minimum_substrate_distance_angstrom": (record.minimum_substrate_distance_angstrom),
        "alignment_tolerance_angstrom": record.alignment_tolerance_angstrom,
        "minimum_allowed_distance_angstrom": record.minimum_allowed_distance_angstrom,
        "molecule_distorted": record.molecule_distorted,
    }


def generate_adsorption_configuration(
    catalyst: CatalystSystem,
    catalyst_structure: Structure,
    site: SiteDefinition,
    adsorbate: Adsorbate,
    molecule: Molecule,
    *,
    generation_id: str,
    configuration_id: str,
    binding_anchor_pairs: Sequence[tuple[int, int]],
    height_angstrom: float,
    alignment_tolerance_angstrom: float = 0.25,
    minimum_allowed_distance_angstrom: float = 0.6,
) -> GeneratedAdsorptionConfiguration:
    """Rigidly place one reviewed molecular identity over explicit site anchors."""

    generation_id_value = _identifier(generation_id, field="generation_id")
    height = _finite_positive(height_angstrom, field="height_angstrom")
    alignment_tolerance = _finite_positive(
        alignment_tolerance_angstrom,
        field="alignment_tolerance_angstrom",
    )
    minimum_distance = _finite_positive(
        minimum_allowed_distance_angstrom,
        field="minimum_allowed_distance_angstrom",
    )
    if not isinstance(molecule, Molecule):
        raise ValueError("molecule must be a pymatgen Molecule")
    recreated = create_adsorbate(
        molecule,
        adsorbate_id=adsorbate.adsorbate_id,
        binding_atom_indices_0based=adsorbate.binding_atom_indices_0based,
        stereochemistry_label=adsorbate.stereochemistry_label,
    )
    if recreated.identity_sha256 != adsorbate.identity_sha256:
        raise ValueError("live molecule does not match the adsorbate identity")
    if not is_intact_catalysis_identity(site) or not is_intact_catalysis_identity(catalyst):
        raise ValueError("catalyst and site identities must be intact")

    raw_pairs = tuple(binding_anchor_pairs)
    if not raw_pairs or len(set(raw_pairs)) != len(raw_pairs):
        raise ValueError("binding_anchor_pairs must be non-empty and unique")
    declared_binding = set(adsorbate.binding_atom_indices_0based)
    pairs = []
    for binding_index, anchor_position in raw_pairs:
        if (
            not isinstance(binding_index, int)
            or isinstance(binding_index, bool)
            or binding_index not in declared_binding
            or not isinstance(anchor_position, int)
            or isinstance(anchor_position, bool)
            or anchor_position < 0
            or anchor_position >= len(site.anchor_indices_0based)
        ):
            raise ValueError(
                "binding-anchor pairs must reference declared binding atoms and anchors"
            )
        pairs.append(BindingAnchorPair(binding_index, anchor_position))
    if {item.binding_atom_index_0based for item in pairs} != declared_binding:
        raise ValueError("every declared adsorbate binding atom must be assigned")
    pairs_tuple = tuple(
        sorted(
            pairs,
            key=lambda item: (
                item.binding_atom_index_0based,
                item.site_anchor_position_0based,
            ),
        )
    )

    lattice = catalyst_structure.lattice
    a_vector, b_vector, c_vector = np.asarray(lattice.matrix, dtype=float)
    normal = np.cross(a_vector, b_vector)
    normal /= np.linalg.norm(normal)
    if float(np.dot(normal, c_vector)) < 0:
        normal *= -1
    anchor_fractional = np.asarray(
        [catalyst_structure[index].frac_coords for index in site.anchor_indices_0based],
        dtype=float,
    )
    base = anchor_fractional[0]
    unwrapped = np.asarray([base + pbc_diff(item, base) for item in anchor_fractional])
    anchor_cartesian = np.asarray(lattice.get_cartesian_coords(unwrapped), dtype=float)

    binding_indices = tuple(sorted(declared_binding))
    target_points = []
    for binding_index in binding_indices:
        anchor_positions = tuple(
            item.site_anchor_position_0based
            for item in pairs_tuple
            if item.binding_atom_index_0based == binding_index
        )
        target_points.append(
            np.mean(anchor_cartesian[list(anchor_positions)], axis=0) + height * normal
        )
    targets = np.asarray(target_points, dtype=float)
    molecule_cartesian = np.asarray(molecule.cart_coords, dtype=float)
    source_binding = molecule_cartesian[list(binding_indices)]
    source_center = np.mean(source_binding, axis=0)
    target_center = np.mean(targets, axis=0)
    centered_source = source_binding - source_center
    centered_target = targets - target_center
    rotation, alignment_mode = _alignment(centered_source, centered_target)
    transformed = (molecule_cartesian - source_center) @ rotation.T + target_center
    transformed_binding = transformed[list(binding_indices)]
    alignment_rmsd = float(np.sqrt(np.mean(np.sum((transformed_binding - targets) ** 2, axis=1))))
    if alignment_rmsd > alignment_tolerance:
        raise ValueError("rigid binding alignment exceeds alignment_tolerance_angstrom")

    combined = catalyst_structure.copy()
    for site_record, coordinates in zip(molecule, transformed, strict=True):
        combined.append(site_record.species, coordinates, coords_are_cartesian=True)
    substrate_indices = tuple(range(len(catalyst_structure)))
    adsorbate_indices = tuple(range(len(catalyst_structure), len(combined)))
    interfacial_distances = tuple(
        combined.get_distance(substrate_index, adsorbate_index)
        for substrate_index in substrate_indices
        for adsorbate_index in adsorbate_indices
    )
    closest = min(interfacial_distances)
    if closest < minimum_distance:
        raise ValueError("generated adsorption structure contains a substrate-adsorbate clash")

    configuration = create_adsorption_configuration(
        catalyst,
        catalyst_structure,
        site,
        adsorbate,
        combined,
        configuration_id=configuration_id,
        placement_kind=AdsorptionPlacementKind.RULE_BASED,
        substrate_indices_0based=substrate_indices,
        adsorbate_indices_0based=adsorbate_indices,
    )
    provisional = AdsorptionGenerationRecord(
        generation_id=generation_id_value,
        configuration_id=configuration.configuration_id,
        configuration_identity_sha256=configuration.identity_sha256,
        binding_anchor_pairs=pairs_tuple,
        height_angstrom=height,
        alignment_mode=alignment_mode,
        binding_alignment_rmsd_angstrom=alignment_rmsd,
        minimum_substrate_distance_angstrom=closest,
        alignment_tolerance_angstrom=alignment_tolerance,
        minimum_allowed_distance_angstrom=minimum_distance,
        identity_sha256="0" * 64,
    )
    generation = replace(
        provisional,
        identity_sha256=_digest(_generation_payload(provisional)),
    )
    return GeneratedAdsorptionConfiguration(combined, configuration, generation)


def _valid_generated(item: object) -> bool:
    try:
        return (
            isinstance(item, GeneratedAdsorptionConfiguration)
            and isinstance(item.structure, Structure)
            and isinstance(item.configuration, AdsorptionConfiguration)
            and is_intact_catalysis_identity(item.configuration)
            and item.generation.schema_version == "catex.adsorption-generation.v1"
            and item.generation.configuration_id == item.configuration.configuration_id
            and item.generation.configuration_identity_sha256 == item.configuration.identity_sha256
            and _SHA256.fullmatch(item.generation.identity_sha256) is not None
            and item.generation.identity_sha256 == _digest(_generation_payload(item.generation))
            and structure_hash(item.structure)
            == item.configuration.combined_structure_canonical_sha256
            and ordered_structure_hash(item.structure)
            == item.configuration.combined_structure_ordered_sha256
            and not item.generation.molecule_distorted
            and item.generation.manual_configuration_review_required
            and not item.generation.writes_performed
            and not item.generation.commands_executed
        )
    except (AttributeError, TypeError, ValueError):
        return False


def _same_geometry(
    first: GeneratedAdsorptionConfiguration,
    second: GeneratedAdsorptionConfiguration,
    tolerance: float,
) -> bool:
    first_configuration = first.configuration
    second_configuration = second.configuration
    if (
        first_configuration.catalyst_identity_sha256
        != second_configuration.catalyst_identity_sha256
        or first_configuration.site_identity_sha256 != second_configuration.site_identity_sha256
        or first_configuration.adsorbate_identity_sha256
        != second_configuration.adsorbate_identity_sha256
        or len(first_configuration.adsorbate_indices_0based)
        != len(second_configuration.adsorbate_indices_0based)
        or not np.allclose(
            first.structure.lattice.matrix,
            second.structure.lattice.matrix,
            atol=1e-10,
            rtol=0,
        )
    ):
        return False
    for first_index, second_index in zip(
        first_configuration.adsorbate_indices_0based,
        second_configuration.adsorbate_indices_0based,
        strict=True,
    ):
        fractional_difference = pbc_diff(
            second.structure[second_index].frac_coords,
            first.structure[first_index].frac_coords,
        )
        displacement = first.structure.lattice.get_cartesian_coords(fractional_difference)
        if float(np.linalg.norm(displacement)) > tolerance:
            return False
    return True


def deduplicate_adsorption_configurations(
    configurations: Sequence[GeneratedAdsorptionConfiguration],
    *,
    tolerance_angstrom: float = 0.05,
) -> ConfigurationDeduplicationReport:
    """Group same-domain candidates by ordered adsorbate geometry under PBC."""

    tolerance = _finite_positive(tolerance_angstrom, field="tolerance_angstrom")
    items = tuple(configurations)
    if not items or any(not _valid_generated(item) for item in items):
        raise ValueError("configurations must be non-empty intact generated candidates")
    if len({item.configuration.configuration_id for item in items}) != len(items):
        raise ValueError("configuration IDs must be unique")
    ordered = tuple(sorted(items, key=lambda item: item.configuration.identity_sha256))
    unassigned = list(ordered)
    groups: list[ConfigurationDeduplicationGroup] = []
    while unassigned:
        representative = unassigned.pop(0)
        members = [representative]
        remaining = []
        for candidate in unassigned:
            if _same_geometry(representative, candidate, tolerance):
                members.append(candidate)
            else:
                remaining.append(candidate)
        unassigned = remaining
        groups.append(
            ConfigurationDeduplicationGroup(
                representative_configuration_id=(representative.configuration.configuration_id),
                representative_configuration_identity_sha256=(
                    representative.configuration.identity_sha256
                ),
                member_configuration_ids=tuple(
                    item.configuration.configuration_id for item in members
                ),
                member_configuration_identity_sha256s=tuple(
                    item.configuration.identity_sha256 for item in members
                ),
            )
        )
    groups_tuple = tuple(groups)
    identity = {
        "schema": "catex.configuration-deduplication-content.v1",
        "tolerance_angstrom": tolerance,
        "groups": [item.to_dict() for item in groups_tuple],
    }
    return ConfigurationDeduplicationReport(
        tolerance_angstrom=tolerance,
        groups=groups_tuple,
        deduplication_sha256=_digest(identity),
    )


def _spin_variant_payload(variant: SpinProtocolVariant) -> dict[str, Any]:
    return {
        "schema": "catex.spin-protocol-variant-content.v1",
        "spin_initialization": variant.spin_initialization.to_dict(),
        "protocol": variant.protocol.to_dict(),
    }


def plan_multi_spin_calculations(
    configuration: AdsorptionConfiguration,
    readiness: ConfigurationReadinessReport,
    base_protocol: ScientificProtocol,
    initializations: Sequence[SpinInitialization],
) -> MultiSpinCalculationPlan:
    """Create distinct collinear protocol variants without writing or submitting jobs."""

    if not is_intact_catalysis_identity(configuration):
        raise ValueError("configuration must be an intact adsorption identity")
    if (
        not isinstance(readiness, ConfigurationReadinessReport)
        or not readiness.ready_for_calculation_planning
        or readiness.configuration_id != configuration.configuration_id
        or readiness.configuration_identity_sha256 != configuration.identity_sha256
        or len(readiness.accepted_review_sha256s) != 4
        or any(_SHA256.fullmatch(item) is None for item in readiness.accepted_review_sha256s)
    ):
        raise ValueError("configuration must pass the four-identity review gate")
    if (
        not isinstance(base_protocol, ScientificProtocol)
        or base_protocol.schema_version != "catex.scientific-protocol.v1"
        or base_protocol.target_vasp_version != "5.4.4"
    ):
        raise ValueError("base_protocol must be a VASP 5.4.4 ScientificProtocol")
    noncollinear = base_protocol.incar.get("LNONCOLLINEAR", "FALSE").strip().upper()
    if noncollinear in {"T", "TRUE", ".TRUE."}:
        raise ValueError("collinear multi-spin planning cannot override LNONCOLLINEAR")
    candidates = tuple(initializations)
    if len(candidates) < 2:
        raise ValueError("multi-spin planning requires at least two initializations")
    expected_sites = len(configuration.substrate_indices_0based) + len(
        configuration.adsorbate_indices_0based
    )
    normalized: list[SpinInitialization] = []
    seen_labels: set[str] = set()
    seen_states: set[tuple[tuple[float, ...], float | None]] = set()
    for item in candidates:
        if not isinstance(item, SpinInitialization):
            raise ValueError("initializations must contain SpinInitialization records")
        label = _identifier(item.label, field="spin label", maximum=32)
        raw_moments = tuple(item.magnetic_moments_mu_b)
        if len(raw_moments) != expected_sites or any(
            not isinstance(value, int | float)
            or isinstance(value, bool)
            or not math.isfinite(value)
            for value in raw_moments
        ):
            raise ValueError("each MAGMOM vector must contain one finite value per site")
        moments = tuple(float(value) for value in raw_moments)
        nupdown = item.nupdown
        if nupdown is not None and (
            not isinstance(nupdown, int | float)
            or isinstance(nupdown, bool)
            or not math.isfinite(nupdown)
        ):
            raise ValueError("nupdown must be finite when supplied")
        state_key = (moments, float(nupdown) if nupdown is not None else None)
        if label in seen_labels or state_key in seen_states:
            raise ValueError("spin labels and numerical initial states must be unique")
        seen_labels.add(label)
        seen_states.add(state_key)
        normalized.append(SpinInitialization(label, moments, state_key[1]))

    variants: list[SpinProtocolVariant] = []
    for item in sorted(normalized, key=lambda value: value.label):
        protocol_id = f"{base_protocol.protocol_id}-{item.label}"
        _identifier(protocol_id, field="spin protocol_id", maximum=64)
        incar = dict(base_protocol.incar)
        incar["ISPIN"] = "2"
        incar["MAGMOM"] = " ".join(format(value, ".12g") for value in item.magnetic_moments_mu_b)
        if item.nupdown is None:
            incar.pop("NUPDOWN", None)
        else:
            incar["NUPDOWN"] = format(item.nupdown, ".12g")
        protocol = ScientificProtocol(
            protocol_id=protocol_id,
            target_vasp_version=base_protocol.target_vasp_version,
            incar=incar,
            kpoints=base_protocol.kpoints,
        )
        provisional = SpinProtocolVariant(
            spin_initialization=item,
            protocol=protocol,
            protocol_variant_sha256="0" * 64,
        )
        variants.append(
            replace(
                provisional,
                protocol_variant_sha256=_digest(_spin_variant_payload(provisional)),
            )
        )
    variants_tuple = tuple(variants)
    plan_payload = {
        "schema": "catex.multi-spin-calculation-plan-content.v1",
        "configuration_id": configuration.configuration_id,
        "configuration_identity_sha256": configuration.identity_sha256,
        "configuration_review_sha256s": list(readiness.accepted_review_sha256s),
        "base_protocol": base_protocol.to_dict(),
        "variant_sha256s": [item.protocol_variant_sha256 for item in variants_tuple],
    }
    return MultiSpinCalculationPlan(
        configuration_id=configuration.configuration_id,
        configuration_identity_sha256=configuration.identity_sha256,
        configuration_review_sha256s=readiness.accepted_review_sha256s,
        base_protocol_id=base_protocol.protocol_id,
        variants=variants_tuple,
        plan_sha256=_digest(plan_payload),
    )
