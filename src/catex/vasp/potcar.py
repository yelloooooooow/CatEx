"""Validation of copyright-safe POTCAR metadata, never raw POTCAR contents."""

from __future__ import annotations

import json
import re
from typing import Any

from pymatgen.core import Element

from catex.models import ArtifactRecord, Diagnostic, Severity
from catex.vasp.models import (
    PotcarDatasetMetadata,
    PotcarMetadata,
    ValidationMode,
)

_SHA256 = re.compile(r"^[0-9a-fA-F]{64}$")


def _policy(mode: ValidationMode) -> Severity:
    return Severity.ERROR if mode is ValidationMode.STRICT else Severity.WARNING


def _required_string(data: dict[str, Any], key: str) -> str:
    value = data.get(key)
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{key} must be a non-empty string")
    return value.strip()


def _required_positive_float(data: dict[str, Any], key: str) -> float:
    value = data.get(key)
    if isinstance(value, bool):
        raise ValueError(f"{key} must be numeric")
    try:
        parsed = float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{key} must be numeric") from exc
    if parsed <= 0:
        raise ValueError(f"{key} must be positive")
    return parsed


def parse_potcar_metadata(
    text: str,
    *,
    artifact: ArtifactRecord,
) -> tuple[PotcarMetadata | None, tuple[Diagnostic, ...]]:
    """Parse a small metadata JSON without accepting or reading POTCAR content."""

    try:
        raw = json.loads(text)
    except json.JSONDecodeError as exc:
        return None, (
            Diagnostic(
                "POTCAR_METADATA_JSON_INVALID",
                Severity.ERROR,
                "The POTCAR metadata file is not valid JSON.",
                {"line": exc.lineno, "column": exc.colno},
            ),
        )
    if not isinstance(raw, dict):
        return None, (
            Diagnostic(
                "POTCAR_METADATA_ROOT_INVALID",
                Severity.ERROR,
                "The POTCAR metadata root must be a JSON object.",
            ),
        )
    if raw.get("schema_version") != "catex.potcar-metadata.v1":
        return None, (
            Diagnostic(
                "POTCAR_METADATA_SCHEMA_UNSUPPORTED",
                Severity.ERROR,
                "The metadata schema must be catex.potcar-metadata.v1.",
                {"schema_version": raw.get("schema_version")},
            ),
        )
    try:
        family = _required_string(raw, "potential_family")
    except ValueError as exc:
        return None, (Diagnostic("POTCAR_METADATA_FIELD_INVALID", Severity.ERROR, str(exc)),)
    raw_datasets = raw.get("datasets")
    if not isinstance(raw_datasets, list) or not raw_datasets:
        return None, (
            Diagnostic(
                "POTCAR_METADATA_DATASETS_INVALID",
                Severity.ERROR,
                "datasets must be a non-empty JSON array.",
            ),
        )

    diagnostics: list[Diagnostic] = []
    datasets: list[PotcarDatasetMetadata] = []
    for index, data in enumerate(raw_datasets):
        if not isinstance(data, dict):
            diagnostics.append(
                Diagnostic(
                    "POTCAR_METADATA_DATASET_INVALID",
                    Severity.ERROR,
                    "Each dataset must be a JSON object.",
                    {"dataset_index": index},
                )
            )
            continue
        try:
            element = _required_string(data, "element")
            Element(element)
            potential_label = _required_string(data, "potential_label")
            titel = _required_string(data, "titel")
            lexch = _required_string(data, "lexch")
            zval = _required_positive_float(data, "zval")
            enmax = _required_positive_float(data, "enmax_eV")
            digest = _required_string(data, "sha256")
            if not _SHA256.match(digest):
                raise ValueError("sha256 must contain exactly 64 hexadecimal characters")
        except (ValueError, KeyError) as exc:
            diagnostics.append(
                Diagnostic(
                    "POTCAR_METADATA_DATASET_INVALID",
                    Severity.ERROR,
                    str(exc),
                    {"dataset_index": index},
                )
            )
            continue
        datasets.append(
            PotcarDatasetMetadata(
                element=element,
                potential_label=potential_label,
                titel=titel,
                lexch=lexch,
                zval=zval,
                enmax_ev=enmax,
                sha256=digest.lower(),
            )
        )

    if any(item.severity is Severity.ERROR for item in diagnostics):
        return None, tuple(diagnostics)
    return PotcarMetadata(family, tuple(datasets), artifact), tuple(diagnostics)


def validate_potcar_metadata(
    metadata: PotcarMetadata,
    *,
    poscar_species_order: tuple[str, ...],
    encut_ev: float | None,
    mode: ValidationMode,
) -> tuple[Diagnostic, ...]:
    """Check dataset order, PBE header consistency, and ENCUT/ENMAX."""

    diagnostics: list[Diagnostic] = []
    metadata_order = tuple(item.element for item in metadata.datasets)
    if metadata_order != poscar_species_order:
        diagnostics.append(
            Diagnostic(
                "POTCAR_ORDER_MISMATCH",
                Severity.ERROR,
                "POTCAR dataset elements must follow the POSCAR species order exactly.",
                {
                    "poscar_species_order": list(poscar_species_order),
                    "metadata_species_order": list(metadata_order),
                },
            )
        )
    for index, dataset in enumerate(metadata.datasets):
        if dataset.potential_label not in dataset.titel:
            diagnostics.append(
                Diagnostic(
                    "POTCAR_TITEL_LABEL_MISMATCH",
                    Severity.WARNING,
                    "The potential label is not visible in the recorded TITEL.",
                    {"dataset_index": index, "potential_label": dataset.potential_label},
                )
            )
        if "PBE" in metadata.potential_family.upper() and dataset.lexch.upper() != "PE":
            diagnostics.append(
                Diagnostic(
                    "POTCAR_LEXCH_FAMILY_MISMATCH",
                    Severity.ERROR,
                    "A PBE potential family should record LEXCH = PE.",
                    {"dataset_index": index, "lexch": dataset.lexch},
                )
            )
    maximum = metadata.maximum_enmax_ev
    if encut_ev is not None and maximum is not None and encut_ev < maximum:
        diagnostics.append(
            Diagnostic(
                "ENCUT_BELOW_POTCAR_ENMAX",
                _policy(mode),
                "ENCUT is below the largest recommended ENMAX in the metadata.",
                {"encut_eV": encut_ev, "maximum_enmax_eV": maximum},
            )
        )
    return tuple(diagnostics)
