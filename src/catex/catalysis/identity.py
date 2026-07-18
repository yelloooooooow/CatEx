"""Pure construction, hashing, and review gates for catalysis-domain identities."""

from __future__ import annotations

import hashlib
import json
import math
import re
from collections.abc import Sequence
from dataclasses import replace
from datetime import datetime
from typing import Any

import numpy as np
from pymatgen.core import Molecule, Structure
from pymatgen.util.coord import pbc_diff

from catex.catalysis.models import (
    Adsorbate,
    AdsorptionConfiguration,
    AdsorptionPlacementKind,
    CatalystModelKind,
    CatalystSystem,
    ConfigurationReadinessReport,
    IdentityReviewDecision,
    IdentitySubjectKind,
    ScientificIdentityReview,
    SiteDefinition,
    SiteKind,
    StructureOrigin,
)
from catex.hashing import structure_hash
from catex.models import Diagnostic, Severity, StructureRecord

_IDENTIFIER = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,99}$")
_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_UTC_TIMESTAMP = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$")
_UTC_FORMAT = "%Y-%m-%dT%H:%M:%SZ"
_DECIMALS = 8

_IdentitySubject = CatalystSystem | SiteDefinition | Adsorbate | AdsorptionConfiguration


def _digest(payload: dict[str, Any]) -> str:
    encoded = json.dumps(
        payload,
        allow_nan=False,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _matches(pattern: re.Pattern[str], value: object) -> bool:
    return isinstance(value, str) and pattern.fullmatch(value) is not None


def _identifier(value: str, *, field: str) -> str:
    if not _matches(_IDENTIFIER, value):
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


def _rounded(value: float) -> float:
    result = round(float(value), _DECIMALS)
    return 0.0 if result == 0 else result


def _site_species(site: Any) -> tuple[tuple[str, float], ...]:
    return tuple(sorted((str(key), _rounded(value)) for key, value in site.species.items()))


def _ordered_periodic_payload(structure: Structure) -> dict[str, Any]:
    lattice = np.asarray(structure.lattice.matrix, dtype=float)
    fractional = np.asarray(structure.frac_coords, dtype=float)
    if not np.isfinite(lattice).all() or not np.isfinite(fractional).all():
        raise ValueError("structure contains non-finite lattice or coordinates")
    sites = []
    for site, coords in zip(structure, fractional, strict=True):
        wrapped = np.mod(coords, 1.0)
        wrapped[np.isclose(wrapped, 1.0, atol=10 ** (-(_DECIMALS + 1)))] = 0.0
        sites.append(
            {
                "species": [list(item) for item in _site_species(site)],
                "fractional_coordinates": [_rounded(item) for item in wrapped],
            }
        )
    return {
        "schema": "catex.ordered-periodic-structure.v1",
        "lattice_matrix_angstrom": [[_rounded(item) for item in row] for row in lattice],
        "sites_in_order": sites,
    }


def ordered_structure_hash(structure: Structure) -> str:
    """Hash a periodic structure while preserving site order for index-based mappings."""

    return _digest(_ordered_periodic_payload(structure))


def _catalyst_identity(catalyst: CatalystSystem) -> dict[str, Any]:
    return {
        "schema": "catex.catalyst-system-content.v1",
        "catalyst_id": catalyst.catalyst_id,
        "model_kind": catalyst.model_kind.value,
        "structure_origin": catalyst.structure_origin.value,
        "formula": catalyst.formula,
        "num_sites": catalyst.num_sites,
        "charge_e": catalyst.charge_e,
        "canonical_structure_sha256": catalyst.canonical_structure_sha256,
        "ordered_structure_sha256": catalyst.ordered_structure_sha256,
        "source_artifact_sha256": catalyst.source_artifact_sha256,
        "transformation_sha256s": list(catalyst.transformation_sha256s),
    }


def create_catalyst_system(
    record: StructureRecord,
    structure: Structure,
    *,
    catalyst_id: str,
    model_kind: CatalystModelKind,
    structure_origin: StructureOrigin,
    transformation_sha256s: Sequence[str] = (),
) -> CatalystSystem:
    """Create a catalyst identity only when the live structure matches its inspected record."""

    catalyst_id_value = _identifier(catalyst_id, field="catalyst_id")
    if not isinstance(record, StructureRecord) or record.schema_version != "catex.structure.v1":
        raise ValueError("record must be a catex.structure.v1 StructureRecord")
    if not isinstance(structure, Structure) or not isinstance(model_kind, CatalystModelKind):
        raise ValueError("structure and model_kind must use CatEx domain types")
    if not isinstance(structure_origin, StructureOrigin):
        raise ValueError("structure_origin must be a StructureOrigin")
    if not structure.is_ordered or not record.is_ordered:
        raise ValueError("catalyst identity requires a fully ordered structure")
    canonical = structure_hash(structure)
    if (
        record.canonical_hash != canonical
        or record.num_sites != len(structure)
        or record.formula != structure.composition.formula
        or record.reduced_formula != structure.composition.reduced_formula
        or not math.isclose(record.charge, float(structure.charge), abs_tol=1e-8)
    ):
        raise ValueError("live structure does not match the inspected StructureRecord")
    transformations = tuple(transformation_sha256s)
    if len(set(transformations)) != len(transformations) or any(
        not _matches(_SHA256, item) for item in transformations
    ):
        raise ValueError("transformation_sha256s must be unique SHA256 values")
    source_sha256 = record.artifact.sha256 if record.artifact else None
    if source_sha256 is not None and not _matches(_SHA256, source_sha256):
        raise ValueError("source artifact SHA256 is invalid")
    if structure_origin is StructureOrigin.EXTERNAL_IMPORT and source_sha256 is None:
        raise ValueError("external_import requires a source artifact SHA256")
    if structure_origin is StructureOrigin.TRANSFORMED and not transformations:
        raise ValueError("transformed catalyst identity requires transformation provenance")

    provisional = CatalystSystem(
        catalyst_id=catalyst_id_value,
        model_kind=model_kind,
        structure_origin=structure_origin,
        formula=record.formula,
        num_sites=record.num_sites,
        charge_e=record.charge,
        canonical_structure_sha256=canonical,
        ordered_structure_sha256=ordered_structure_hash(structure),
        source_artifact_sha256=source_sha256,
        transformation_sha256s=transformations,
        identity_sha256="0" * 64,
    )
    return replace(provisional, identity_sha256=_digest(_catalyst_identity(provisional)))


def _structure_matches_catalyst(catalyst: CatalystSystem, structure: Structure) -> bool:
    return (
        _valid_catalyst(catalyst)
        and isinstance(structure, Structure)
        and len(structure) == catalyst.num_sites
        and structure_hash(structure) == catalyst.canonical_structure_sha256
        and ordered_structure_hash(structure) == catalyst.ordered_structure_sha256
    )


def _site_identity(site: SiteDefinition) -> dict[str, Any]:
    return {
        "schema": "catex.site-definition-content.v1",
        "site_id": site.site_id,
        "catalyst_id": site.catalyst_id,
        "catalyst_identity_sha256": site.catalyst_identity_sha256,
        "ordered_structure_sha256": site.ordered_structure_sha256,
        "kind": site.kind.value,
        "anchor_indices_0based": list(site.anchor_indices_0based),
        "anchor_species": list(site.anchor_species),
        "anchor_fractional_coordinates_wrapped": [
            list(item) for item in site.anchor_fractional_coordinates_wrapped
        ],
        "fractional_centroid_wrapped": list(site.fractional_centroid_wrapped),
    }


def define_site(
    catalyst: CatalystSystem,
    structure: Structure,
    *,
    site_id: str,
    kind: SiteKind,
    anchor_indices_0based: Sequence[int],
) -> SiteDefinition:
    """Define a PBC-aware active site without modifying the catalyst structure."""

    site_id_value = _identifier(site_id, field="site_id")
    if not isinstance(kind, SiteKind):
        raise ValueError("kind must be a SiteKind")
    if not _structure_matches_catalyst(catalyst, structure):
        raise ValueError("site structure does not match the catalyst ordered identity")
    indices = tuple(anchor_indices_0based)
    if (
        not indices
        or any(not isinstance(item, int) or isinstance(item, bool) for item in indices)
        or len(set(indices)) != len(indices)
        or any(item < 0 or item >= len(structure) for item in indices)
    ):
        raise ValueError("anchor indices must be unique valid 0-based integers")
    if kind is SiteKind.ATOP and len(indices) != 1:
        raise ValueError("an atop site requires exactly one anchor")
    if kind is SiteKind.BRIDGE and len(indices) != 2:
        raise ValueError("a bridge site requires exactly two anchors")
    if kind is SiteKind.HOLLOW and len(indices) < 3:
        raise ValueError("a hollow site requires at least three anchors")

    fractional = np.mod(np.asarray([structure[item].frac_coords for item in indices]), 1.0)
    base = fractional[0]
    unwrapped = np.asarray([base + pbc_diff(item, base) for item in fractional])
    centroid = np.mod(np.mean(unwrapped, axis=0), 1.0)
    coordinates = tuple(tuple(_rounded(value) for value in row) for row in fractional)
    centroid_tuple = tuple(_rounded(value) for value in centroid)
    provisional = SiteDefinition(
        site_id=site_id_value,
        catalyst_id=catalyst.catalyst_id,
        catalyst_identity_sha256=catalyst.identity_sha256,
        ordered_structure_sha256=catalyst.ordered_structure_sha256,
        kind=kind,
        anchor_indices_0based=indices,
        anchor_species=tuple(str(structure[item].specie) for item in indices),
        anchor_fractional_coordinates_wrapped=coordinates,  # type: ignore[arg-type]
        fractional_centroid_wrapped=centroid_tuple,  # type: ignore[arg-type]
        identity_sha256="0" * 64,
    )
    return replace(provisional, identity_sha256=_digest(_site_identity(provisional)))


def _molecule_geometry_payload(molecule: Molecule) -> dict[str, Any]:
    distances = np.asarray(molecule.distance_matrix, dtype=float)
    if not np.isfinite(distances).all():
        raise ValueError("adsorbate geometry contains non-finite distances")
    return {
        "schema": "catex.ordered-molecular-geometry.v1",
        "species_in_order": [str(site.specie) for site in molecule],
        "distance_matrix_angstrom": [[_rounded(value) for value in row] for row in distances],
    }


def _adsorbate_identity(adsorbate: Adsorbate) -> dict[str, Any]:
    return {
        "schema": "catex.adsorbate-content.v1",
        "adsorbate_id": adsorbate.adsorbate_id,
        "formula": adsorbate.formula,
        "species_in_order": list(adsorbate.species_in_order),
        "charge_e": adsorbate.charge_e,
        "spin_multiplicity": adsorbate.spin_multiplicity,
        "binding_atom_indices_0based": list(adsorbate.binding_atom_indices_0based),
        "stereochemistry_label": adsorbate.stereochemistry_label,
        "geometry_sha256": adsorbate.geometry_sha256,
    }


def create_adsorbate(
    molecule: Molecule,
    *,
    adsorbate_id: str,
    binding_atom_indices_0based: Sequence[int],
    stereochemistry_label: str = "unspecified",
) -> Adsorbate:
    """Create a molecular identity without changing coordinates or guessing binding atoms."""

    adsorbate_id_value = _identifier(adsorbate_id, field="adsorbate_id")
    stereochemistry = _one_line(
        stereochemistry_label,
        field="stereochemistry_label",
        maximum=100,
    )
    if not isinstance(molecule, Molecule) or len(molecule) == 0:
        raise ValueError("molecule must be a non-empty pymatgen Molecule")
    if not molecule.is_ordered:
        raise ValueError("adsorbate identity requires ordered molecular sites")
    indices = tuple(binding_atom_indices_0based)
    if (
        not indices
        or any(not isinstance(item, int) or isinstance(item, bool) for item in indices)
        or len(set(indices)) != len(indices)
        or any(item < 0 or item >= len(molecule) for item in indices)
    ):
        raise ValueError("binding atom indices must be unique valid 0-based integers")
    charge = float(molecule.charge)
    if not math.isfinite(charge) or not math.isclose(charge, round(charge), abs_tol=1e-8):
        raise ValueError("adsorbate charge must be a finite integer")
    multiplicity = molecule.spin_multiplicity
    if not isinstance(multiplicity, int) or multiplicity < 1:
        raise ValueError("adsorbate spin multiplicity must be a positive integer")
    geometry_sha256 = _digest(_molecule_geometry_payload(molecule))
    provisional = Adsorbate(
        adsorbate_id=adsorbate_id_value,
        formula=molecule.composition.formula,
        species_in_order=tuple(str(site.specie) for site in molecule),
        charge_e=round(charge),
        spin_multiplicity=multiplicity,
        binding_atom_indices_0based=indices,
        stereochemistry_label=stereochemistry,
        geometry_sha256=geometry_sha256,
        identity_sha256="0" * 64,
    )
    return replace(provisional, identity_sha256=_digest(_adsorbate_identity(provisional)))


def _configuration_identity(configuration: AdsorptionConfiguration) -> dict[str, Any]:
    return {
        "schema": "catex.adsorption-configuration-content.v1",
        "configuration_id": configuration.configuration_id,
        "catalyst_id": configuration.catalyst_id,
        "catalyst_identity_sha256": configuration.catalyst_identity_sha256,
        "site_id": configuration.site_id,
        "site_identity_sha256": configuration.site_identity_sha256,
        "adsorbate_id": configuration.adsorbate_id,
        "adsorbate_identity_sha256": configuration.adsorbate_identity_sha256,
        "placement_kind": configuration.placement_kind.value,
        "combined_structure_canonical_sha256": (configuration.combined_structure_canonical_sha256),
        "combined_structure_ordered_sha256": (configuration.combined_structure_ordered_sha256),
        "substrate_indices_0based": list(configuration.substrate_indices_0based),
        "adsorbate_indices_0based": list(configuration.adsorbate_indices_0based),
        "binding_distances_angstrom": [
            list(item) for item in configuration.binding_distances_angstrom
        ],
        "minimum_binding_distance_angstrom": (configuration.minimum_binding_distance_angstrom),
        "maximum_binding_distance_angstrom": (configuration.maximum_binding_distance_angstrom),
        "single_adsorbate_only": configuration.single_adsorbate_only,
    }


def create_adsorption_configuration(
    catalyst: CatalystSystem,
    catalyst_structure: Structure,
    site: SiteDefinition,
    adsorbate: Adsorbate,
    combined_structure: Structure,
    *,
    configuration_id: str,
    placement_kind: AdsorptionPlacementKind,
    substrate_indices_0based: Sequence[int],
    adsorbate_indices_0based: Sequence[int],
) -> AdsorptionConfiguration:
    """Register one supplied initial geometry after exhaustive atom-mapping checks."""

    configuration_id_value = _identifier(configuration_id, field="configuration_id")
    if not isinstance(placement_kind, AdsorptionPlacementKind):
        raise ValueError("placement_kind must be an AdsorptionPlacementKind")
    if not _structure_matches_catalyst(catalyst, catalyst_structure):
        raise ValueError("catalyst structure does not match its ordered identity")
    if not _valid_site(site) or (
        site.catalyst_id != catalyst.catalyst_id
        or site.catalyst_identity_sha256 != catalyst.identity_sha256
    ):
        raise ValueError("site identity is invalid or belongs to another catalyst")
    if not _valid_adsorbate(adsorbate):
        raise ValueError("adsorbate identity is invalid")
    if not isinstance(combined_structure, Structure) or not combined_structure.is_ordered:
        raise ValueError("combined_structure must be a fully ordered pymatgen Structure")

    substrate_indices = tuple(substrate_indices_0based)
    adsorbate_indices = tuple(adsorbate_indices_0based)
    expected = set(range(len(combined_structure)))
    if (
        len(substrate_indices) != catalyst.num_sites
        or len(adsorbate_indices) != len(adsorbate.species_in_order)
        or len(set(substrate_indices)) != len(substrate_indices)
        or len(set(adsorbate_indices)) != len(adsorbate_indices)
        or set(substrate_indices).intersection(adsorbate_indices)
        or set(substrate_indices).union(adsorbate_indices) != expected
    ):
        raise ValueError("substrate and adsorbate mappings must be disjoint and exhaustive")
    if any(
        not isinstance(item, int) or isinstance(item, bool) or item < 0
        for item in (*substrate_indices, *adsorbate_indices)
    ):
        raise ValueError("configuration mappings must contain non-negative integers")

    extracted = Structure(
        combined_structure.lattice,
        [combined_structure[item].species for item in substrate_indices],
        [combined_structure[item].frac_coords for item in substrate_indices],
    )
    if ordered_structure_hash(extracted) != catalyst.ordered_structure_sha256:
        raise ValueError("mapped substrate atoms do not reproduce the catalyst ordered identity")
    mapped_adsorbate_species = tuple(
        str(combined_structure[item].specie) for item in adsorbate_indices
    )
    if mapped_adsorbate_species != adsorbate.species_in_order:
        raise ValueError("mapped adsorbate species do not match the adsorbate atom order")

    mapped_anchors = tuple(substrate_indices[item] for item in site.anchor_indices_0based)
    mapped_binding_atoms = tuple(
        adsorbate_indices[item] for item in adsorbate.binding_atom_indices_0based
    )
    distances = tuple(
        tuple(
            _rounded(combined_structure.get_distance(anchor, binding))
            for binding in mapped_binding_atoms
        )
        for anchor in mapped_anchors
    )
    flat_distances = tuple(item for row in distances for item in row)
    if not flat_distances or not all(math.isfinite(item) and item > 0 for item in flat_distances):
        raise ValueError("binding distances must be finite and positive")

    provisional = AdsorptionConfiguration(
        configuration_id=configuration_id_value,
        catalyst_id=catalyst.catalyst_id,
        catalyst_identity_sha256=catalyst.identity_sha256,
        site_id=site.site_id,
        site_identity_sha256=site.identity_sha256,
        adsorbate_id=adsorbate.adsorbate_id,
        adsorbate_identity_sha256=adsorbate.identity_sha256,
        placement_kind=placement_kind,
        combined_structure_canonical_sha256=structure_hash(combined_structure),
        combined_structure_ordered_sha256=ordered_structure_hash(combined_structure),
        substrate_indices_0based=substrate_indices,
        adsorbate_indices_0based=adsorbate_indices,
        binding_distances_angstrom=distances,
        minimum_binding_distance_angstrom=min(flat_distances),
        maximum_binding_distance_angstrom=max(flat_distances),
        identity_sha256="0" * 64,
    )
    return replace(
        provisional,
        identity_sha256=_digest(_configuration_identity(provisional)),
    )


def _valid_catalyst(catalyst: object) -> bool:
    try:
        return (
            isinstance(catalyst, CatalystSystem)
            and catalyst.schema_version == "catex.catalyst-system.v1"
            and _matches(_IDENTIFIER, catalyst.catalyst_id)
            and _matches(_SHA256, catalyst.canonical_structure_sha256)
            and _matches(_SHA256, catalyst.ordered_structure_sha256)
            and _matches(_SHA256, catalyst.identity_sha256)
            and catalyst.identity_sha256 == _digest(_catalyst_identity(catalyst))
            and catalyst.manual_review_required
            and not catalyst.writes_performed
            and not catalyst.commands_executed
        )
    except (AttributeError, TypeError, ValueError):
        return False


def _valid_site(site: object) -> bool:
    try:
        return (
            isinstance(site, SiteDefinition)
            and site.schema_version == "catex.site-definition.v1"
            and _matches(_IDENTIFIER, site.site_id)
            and _matches(_SHA256, site.identity_sha256)
            and site.identity_sha256 == _digest(_site_identity(site))
            and site.manual_review_required
            and not site.writes_performed
            and not site.commands_executed
        )
    except (AttributeError, TypeError, ValueError):
        return False


def _valid_adsorbate(adsorbate: object) -> bool:
    try:
        return (
            isinstance(adsorbate, Adsorbate)
            and adsorbate.schema_version == "catex.adsorbate.v1"
            and _matches(_IDENTIFIER, adsorbate.adsorbate_id)
            and _matches(_SHA256, adsorbate.geometry_sha256)
            and _matches(_SHA256, adsorbate.identity_sha256)
            and adsorbate.identity_sha256 == _digest(_adsorbate_identity(adsorbate))
            and adsorbate.manual_review_required
            and not adsorbate.writes_performed
            and not adsorbate.commands_executed
        )
    except (AttributeError, TypeError, ValueError):
        return False


def _valid_configuration(configuration: object) -> bool:
    try:
        return (
            isinstance(configuration, AdsorptionConfiguration)
            and configuration.schema_version == "catex.adsorption-configuration.v1"
            and _matches(_IDENTIFIER, configuration.configuration_id)
            and _matches(_SHA256, configuration.identity_sha256)
            and configuration.identity_sha256 == _digest(_configuration_identity(configuration))
            and configuration.single_adsorbate_only
            and configuration.manual_review_required
            and not configuration.scientific_identity_approved
            and not configuration.writes_performed
            and not configuration.commands_executed
        )
    except (AttributeError, TypeError, ValueError):
        return False


def is_intact_catalysis_identity(subject: object) -> bool:
    """Return whether a catalyst-domain record still matches its deterministic identity."""

    return (
        _valid_catalyst(subject)
        or _valid_site(subject)
        or _valid_adsorbate(subject)
        or _valid_configuration(subject)
    )


def _subject_identity(subject: _IdentitySubject) -> tuple[IdentitySubjectKind, str, str]:
    if _valid_catalyst(subject):
        return IdentitySubjectKind.CATALYST, subject.catalyst_id, subject.identity_sha256
    if _valid_site(subject):
        return IdentitySubjectKind.SITE, subject.site_id, subject.identity_sha256
    if _valid_adsorbate(subject):
        return IdentitySubjectKind.ADSORBATE, subject.adsorbate_id, subject.identity_sha256
    if _valid_configuration(subject):
        return (
            IdentitySubjectKind.ADSORPTION_CONFIGURATION,
            subject.configuration_id,
            subject.identity_sha256,
        )
    raise ValueError("subject must be an intact CatEx catalysis identity")


def _review_content(review: ScientificIdentityReview) -> dict[str, Any]:
    return {
        "schema": "catex.scientific-identity-review-content.v1",
        "decision": review.decision.value,
        "subject_kind": review.subject_kind.value,
        "subject_id": review.subject_id,
        "subject_identity_sha256": review.subject_identity_sha256,
        "reviewer": review.reviewer,
        "reviewed_at_utc": review.reviewed_at_utc,
        "note": review.note,
    }


def record_identity_review(
    subject: _IdentitySubject,
    *,
    accepted: bool,
    reviewer: str,
    reviewed_at_utc: str,
    note: str,
) -> ScientificIdentityReview:
    """Record an explicit human decision without modifying the reviewed identity."""

    if not isinstance(accepted, bool):
        raise ValueError("accepted must be a boolean")
    kind, subject_id, identity_sha256 = _subject_identity(subject)
    reviewer_value = _one_line(reviewer, field="reviewer", maximum=100)
    note_value = _one_line(note, field="note", maximum=500)
    _timestamp(reviewed_at_utc)
    provisional = ScientificIdentityReview(
        decision=(IdentityReviewDecision.APPROVED if accepted else IdentityReviewDecision.REJECTED),
        subject_kind=kind,
        subject_id=subject_id,
        subject_identity_sha256=identity_sha256,
        reviewer=reviewer_value,
        reviewed_at_utc=reviewed_at_utc,
        note=note_value,
        review_sha256="0" * 64,
    )
    return replace(provisional, review_sha256=_digest(_review_content(provisional)))


def _valid_bound_review(
    review: object,
    *,
    expected_kind: IdentitySubjectKind,
    expected_id: str,
    expected_sha256: str,
) -> bool:
    try:
        return (
            isinstance(review, ScientificIdentityReview)
            and review.schema_version == "catex.scientific-identity-review.v1"
            and isinstance(review.decision, IdentityReviewDecision)
            and review.subject_kind is expected_kind
            and review.subject_id == expected_id
            and review.subject_identity_sha256 == expected_sha256
            and _matches(_SHA256, review.review_sha256)
            and review.review_sha256 == _digest(_review_content(review))
            and review.human_review_recorded
            and not review.automatic_approval_performed
            and not review.writes_performed
            and not review.commands_executed
        )
    except (AttributeError, TypeError, ValueError):
        return False


def assess_configuration_readiness(
    catalyst: CatalystSystem,
    site: SiteDefinition,
    adsorbate: Adsorbate,
    configuration: AdsorptionConfiguration,
    reviews: Sequence[ScientificIdentityReview],
) -> ConfigurationReadinessReport:
    """Require intact linked identities and four explicit approvals before calculation planning."""

    required = (
        IdentitySubjectKind.CATALYST,
        IdentitySubjectKind.SITE,
        IdentitySubjectKind.ADSORBATE,
        IdentitySubjectKind.ADSORPTION_CONFIGURATION,
    )
    diagnostics: list[Diagnostic] = []
    linked = (
        _valid_catalyst(catalyst)
        and _valid_site(site)
        and _valid_adsorbate(adsorbate)
        and _valid_configuration(configuration)
        and site.catalyst_id == catalyst.catalyst_id
        and site.catalyst_identity_sha256 == catalyst.identity_sha256
        and configuration.catalyst_identity_sha256 == catalyst.identity_sha256
        and configuration.site_identity_sha256 == site.identity_sha256
        and configuration.adsorbate_identity_sha256 == adsorbate.identity_sha256
    )
    if not linked:
        diagnostics.append(
            Diagnostic(
                "CATALYSIS_IDENTITY_LINK_INVALID",
                Severity.ERROR,
                (
                    "Catalyst, site, adsorbate, and configuration identities must be "
                    "intact and linked."
                ),
            )
        )

    subjects = {
        IdentitySubjectKind.CATALYST: (catalyst.catalyst_id, catalyst.identity_sha256),
        IdentitySubjectKind.SITE: (site.site_id, site.identity_sha256),
        IdentitySubjectKind.ADSORBATE: (adsorbate.adsorbate_id, adsorbate.identity_sha256),
        IdentitySubjectKind.ADSORPTION_CONFIGURATION: (
            configuration.configuration_id,
            configuration.identity_sha256,
        ),
    }
    accepted_hashes: list[str] = []
    for kind in required:
        subject_id, subject_hash = subjects[kind]
        bound_reviews = tuple(
            review
            for review in reviews
            if _valid_bound_review(
                review,
                expected_kind=kind,
                expected_id=subject_id,
                expected_sha256=subject_hash,
            )
        )
        approved_reviews = tuple(
            review for review in bound_reviews if review.decision is IdentityReviewDecision.APPROVED
        )
        if len(bound_reviews) != 1 or len(approved_reviews) != 1:
            diagnostics.append(
                Diagnostic(
                    "CATALYSIS_IDENTITY_APPROVAL_MISSING_OR_AMBIGUOUS",
                    Severity.ERROR,
                    "Exactly one valid approval is required for each scientific identity.",
                    {
                        "subject_kind": kind.value,
                        "bound_review_count": len(bound_reviews),
                        "valid_approval_count": len(approved_reviews),
                    },
                )
            )
        else:
            accepted_hashes.append(approved_reviews[0].review_sha256)

    ready = linked and not diagnostics
    return ConfigurationReadinessReport(
        configuration_id=configuration.configuration_id,
        configuration_identity_sha256=configuration.identity_sha256,
        ready_for_calculation_planning=ready,
        required_subject_kinds=required,
        accepted_review_sha256s=tuple(accepted_hashes) if ready else (),
        diagnostics=tuple(diagnostics),
    )
