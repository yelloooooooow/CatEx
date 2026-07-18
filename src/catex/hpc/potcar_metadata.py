"""Stream raw POTCAR only inside an explicitly authorized HPC boundary."""

from __future__ import annotations

import hashlib
import re
from pathlib import Path
from typing import Any

from pymatgen.core import Element

from catex.hpc.models import PotcarMetadataExtractionReport
from catex.models import Diagnostic, Severity
from catex.vasp.models import PotcarDatasetMetadata

_TITEL = re.compile(r"\bTITEL\s*=\s*([^;\r\n]+)")
_LEXCH = re.compile(r"\bLEXCH\s*=\s*([A-Za-z0-9_.+-]+)")
_ZVAL = re.compile(r"\bZVAL\s*=\s*([+-]?(?:\d+(?:\.\d*)?|\.\d+)(?:[EeDd][+-]?\d+)?)")
_ENMAX = re.compile(r"\bENMAX\s*=\s*([+-]?(?:\d+(?:\.\d*)?|\.\d+)(?:[EeDd][+-]?\d+)?)")
_POTENTIAL_LABEL = re.compile(r"^(?P<element>[A-Z][a-z]?)(?:_[A-Za-z0-9]+)*$")
_FAMILY = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._+-]{0,99}$")


def _number(value: str, *, field: str) -> float:
    parsed = float(value.replace("D", "E").replace("d", "e"))
    if parsed <= 0:
        raise ValueError(f"{field} must be positive")
    return parsed


def _title_identity(titel: str) -> tuple[str, str]:
    for token in titel.split():
        match = _POTENTIAL_LABEL.fullmatch(token)
        if match is None:
            continue
        element = match.group("element")
        try:
            Element(element)
        except ValueError:
            continue
        return element, token
    raise ValueError("TITEL does not contain a recognizable element potential label")


def _capture(
    state: dict[str, str],
    *,
    field: str,
    value: str,
    dataset_index: int,
    diagnostics: list[Diagnostic],
) -> None:
    normalized = value.strip()
    previous = state.get(field)
    if previous is not None and previous != normalized:
        diagnostics.append(
            Diagnostic(
                "POTCAR_HEADER_FIELD_CONFLICT",
                Severity.ERROR,
                "A dataset repeats a metadata field with conflicting values.",
                {"dataset_index": dataset_index, "field": field},
            )
        )
    else:
        state[field] = normalized


def _finalize_dataset(
    state: dict[str, str],
    *,
    dataset_index: int,
    digest: str,
    diagnostics: list[Diagnostic],
) -> PotcarDatasetMetadata | None:
    missing = sorted({"titel", "lexch", "zval", "enmax_eV"} - set(state))
    if missing:
        diagnostics.append(
            Diagnostic(
                "POTCAR_HEADER_FIELD_MISSING",
                Severity.ERROR,
                "A POTCAR dataset is missing required copyright-safe header metadata.",
                {"dataset_index": dataset_index, "fields": missing},
            )
        )
        return None
    try:
        element, label = _title_identity(state["titel"])
        zval = _number(state["zval"], field="ZVAL")
        enmax = _number(state["enmax_eV"], field="ENMAX")
    except ValueError as exc:
        diagnostics.append(
            Diagnostic(
                "POTCAR_HEADER_VALUE_INVALID",
                Severity.ERROR,
                str(exc),
                {"dataset_index": dataset_index},
            )
        )
        return None
    return PotcarDatasetMetadata(
        element=element,
        potential_label=label,
        titel=state["titel"],
        lexch=state["lexch"],
        zval=zval,
        enmax_ev=enmax,
        sha256=digest,
    )


def extract_potcar_metadata(
    path: str | Path,
    *,
    potential_family: str,
    authorized_hpc_read: bool = False,
) -> PotcarMetadataExtractionReport:
    """Read a POTCAR stream once and retain only safe headers and exact dataset hashes."""

    source = Path(path)
    source_name = source.name or "POTCAR"
    if not _FAMILY.fullmatch(potential_family):
        raise ValueError("potential_family must be a safe 1-100 character identifier")
    if not authorized_hpc_read:
        return PotcarMetadataExtractionReport(
            source_name=source_name,
            potential_family=potential_family,
            source_sha256=None,
            source_size_bytes=None,
            datasets=(),
            diagnostics=(
                Diagnostic(
                    "POTCAR_HPC_AUTHORIZATION_REQUIRED",
                    Severity.ERROR,
                    "Raw POTCAR may be read only inside an explicitly authorized HPC boundary.",
                ),
            ),
            authorized_hpc_read=False,
        )

    total_hasher = hashlib.sha256()
    dataset_hasher = hashlib.sha256()
    total_size = 0
    dataset_size = 0
    dataset_has_nonempty_bytes = False
    dataset_index = 0
    state: dict[str, str] = {}
    datasets: list[PotcarDatasetMetadata] = []
    diagnostics: list[Diagnostic] = []
    try:
        stream = source.open("rb")
    except OSError as exc:
        return PotcarMetadataExtractionReport(
            source_name=source_name,
            potential_family=potential_family,
            source_sha256=None,
            source_size_bytes=None,
            datasets=(),
            diagnostics=(
                Diagnostic(
                    "POTCAR_READ_FAILED",
                    Severity.ERROR,
                    "The authorized POTCAR stream could not be opened.",
                    {"exception_type": type(exc).__name__},
                ),
            ),
            authorized_hpc_read=True,
        )

    with stream:
        for raw_line in stream:
            total_hasher.update(raw_line)
            dataset_hasher.update(raw_line)
            total_size += len(raw_line)
            dataset_size += len(raw_line)
            if raw_line.strip():
                dataset_has_nonempty_bytes = True
            line = raw_line.decode("ascii", errors="ignore")
            for field, pattern in (
                ("titel", _TITEL),
                ("lexch", _LEXCH),
                ("zval", _ZVAL),
                ("enmax_eV", _ENMAX),
            ):
                match = pattern.search(line)
                if match is not None:
                    _capture(
                        state,
                        field=field,
                        value=match.group(1),
                        dataset_index=dataset_index,
                        diagnostics=diagnostics,
                    )
            if raw_line.strip() == b"End of Dataset":
                dataset = _finalize_dataset(
                    state,
                    dataset_index=dataset_index,
                    digest=dataset_hasher.hexdigest(),
                    diagnostics=diagnostics,
                )
                if dataset is not None:
                    datasets.append(dataset)
                dataset_index += 1
                dataset_hasher = hashlib.sha256()
                dataset_size = 0
                dataset_has_nonempty_bytes = False
                state = {}

    if total_size == 0:
        diagnostics.append(
            Diagnostic("POTCAR_EMPTY", Severity.ERROR, "The authorized POTCAR stream is empty.")
        )
    elif dataset_size and dataset_has_nonempty_bytes:
        diagnostics.append(
            Diagnostic(
                "POTCAR_DATASET_TERMINATOR_MISSING",
                Severity.ERROR,
                "The final dataset does not end with the required End of Dataset marker.",
                {"dataset_index": dataset_index},
            )
        )
    if dataset_index == 0:
        diagnostics.append(
            Diagnostic(
                "POTCAR_DATASET_NOT_FOUND",
                Severity.ERROR,
                "No complete POTCAR dataset was found.",
            )
        )
    if any(item.severity is Severity.ERROR for item in diagnostics):
        datasets = []
    return PotcarMetadataExtractionReport(
        source_name=source_name,
        potential_family=potential_family,
        source_sha256=total_hasher.hexdigest(),
        source_size_bytes=total_size,
        datasets=tuple(datasets),
        diagnostics=tuple(diagnostics),
        authorized_hpc_read=True,
    )


def metadata_document(report: PotcarMetadataExtractionReport) -> dict[str, Any]:
    """Return downstream metadata or fail rather than emitting partial data."""

    document = report.metadata_document
    if document is None:
        raise ValueError("POTCAR metadata extraction did not produce a complete document")
    return document
