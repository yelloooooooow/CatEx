"""Resolve explicit VASP 5.4.4 scientific protocols without writing files."""

from __future__ import annotations

import hashlib
import json
import math
import re
from contextlib import suppress
from dataclasses import replace
from pathlib import Path
from typing import Any

from pymatgen.io.vasp import Poscar

from catex.models import ArtifactRecord, Diagnostic, Severity
from catex.structures import inspect_structure
from catex.vasp.incar import parse_incar_text, validate_incar
from catex.vasp.kpoints import parse_kpoints_text, validate_kpoints
from catex.vasp.models import ValidationMode
from catex.vasp.potcar import parse_potcar_metadata, validate_potcar_metadata
from catex.vasp.registry import is_energy_family_relevant
from catex.workflow.models import (
    KpointsSpecification,
    ProtocolResolutionReport,
    ProtocolReview,
    ResolvedProtocol,
    ReviewState,
    ScientificProtocol,
)

_IDENTIFIER = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$")
_INCAR_TAG = re.compile(r"^[A-Za-z][A-Za-z0-9_]*$")
_UTC_TIMESTAMP = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$")
_TARGET_VASP_VERSION = "5.4.4"


def _canonical_json(data: Any) -> bytes:
    return json.dumps(
        data,
        allow_nan=False,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")


def _digest(data: Any) -> str:
    return hashlib.sha256(_canonical_json(data)).hexdigest()


def _read_utf8(
    path: Path,
) -> tuple[str | None, ArtifactRecord | None, tuple[Diagnostic, ...]]:
    try:
        data = path.read_bytes()
        text = data.decode("utf-8-sig")
        artifact = ArtifactRecord(
            path=str(path),
            sha256=hashlib.sha256(data).hexdigest(),
            size_bytes=len(data),
        )
        return text, artifact, ()
    except FileNotFoundError:
        return (
            None,
            None,
            (
                Diagnostic(
                    "PROTOCOL_SOURCE_NOT_FOUND",
                    Severity.ERROR,
                    "A required protocol source file does not exist.",
                    {"path": str(path)},
                ),
            ),
        )
    except UnicodeDecodeError as exc:
        return (
            None,
            None,
            (
                Diagnostic(
                    "PROTOCOL_SOURCE_ENCODING_INVALID",
                    Severity.ERROR,
                    "Protocol inputs must be UTF-8/ASCII compatible.",
                    {"path": str(path), "byte_offset": exc.start},
                ),
            ),
        )
    except OSError as exc:
        return (
            None,
            None,
            (
                Diagnostic(
                    "PROTOCOL_SOURCE_READ_FAILED",
                    Severity.ERROR,
                    "A protocol source file could not be read.",
                    {"path": str(path), "exception_type": type(exc).__name__},
                ),
            ),
        )


def _three_values(
    value: Any, *, integers: bool
) -> tuple[int, int, int] | tuple[float, float, float]:
    if not isinstance(value, list) or len(value) != 3:
        raise ValueError("must be a JSON array with exactly three values")
    if integers:
        if any(isinstance(item, bool) or not isinstance(item, int) for item in value):
            raise ValueError("subdivisions must contain three integers")
        parsed_ints = tuple(value)
        if any(item <= 0 for item in parsed_ints):
            raise ValueError("subdivisions must be positive")
        return parsed_ints  # type: ignore[return-value]
    if any(isinstance(item, bool) or not isinstance(item, (int, float)) for item in value):
        raise ValueError("shift must contain three finite numbers")
    parsed_floats = tuple(float(item) for item in value)
    if not all(math.isfinite(item) for item in parsed_floats):
        raise ValueError("shift must contain three finite numbers")
    return parsed_floats  # type: ignore[return-value]


def parse_scientific_protocol(text: str) -> ScientificProtocol:
    """Parse the strict JSON boundary for a scientific protocol."""

    try:
        raw = json.loads(text)
    except json.JSONDecodeError as exc:
        raise ValueError(f"scientific protocol JSON is invalid at line {exc.lineno}") from exc
    if not isinstance(raw, dict):
        raise ValueError("scientific protocol root must be a JSON object")
    expected_keys = {"schema_version", "protocol_id", "target_vasp_version", "incar", "kpoints"}
    unknown = sorted(set(raw) - expected_keys)
    if unknown:
        raise ValueError(f"unsupported scientific protocol fields: {', '.join(unknown)}")
    if raw.get("schema_version") != "catex.scientific-protocol.v1":
        raise ValueError("scientific protocol schema must be catex.scientific-protocol.v1")
    protocol_id = raw.get("protocol_id")
    if not isinstance(protocol_id, str) or not _IDENTIFIER.fullmatch(protocol_id):
        raise ValueError("protocol_id must be a safe 1-64 character identifier")
    target = raw.get("target_vasp_version")
    if target != _TARGET_VASP_VERSION:
        raise ValueError("this registry supports target_vasp_version 5.4.4 only")
    raw_incar = raw.get("incar")
    if not isinstance(raw_incar, dict) or not raw_incar:
        raise ValueError("incar must be a non-empty JSON object")
    incar: dict[str, str] = {}
    for raw_tag, raw_value in raw_incar.items():
        if not isinstance(raw_tag, str) or not _INCAR_TAG.fullmatch(raw_tag):
            raise ValueError(f"invalid INCAR tag: {raw_tag!r}")
        tag = raw_tag.upper()
        if tag in incar:
            raise ValueError(f"duplicate normalized INCAR tag: {tag}")
        if not isinstance(raw_value, str) or not raw_value.strip():
            raise ValueError(f"INCAR {tag} must be a non-empty string")
        value = raw_value.strip()
        if any(character in value for character in "\r\n;#!") or any(
            ord(character) < 32 for character in value
        ):
            raise ValueError(f"INCAR {tag} contains a forbidden control/comment separator")
        incar[tag] = value

    raw_kpoints = raw.get("kpoints")
    if not isinstance(raw_kpoints, dict):
        raise ValueError("kpoints must be a JSON object")
    unknown_kpoints = sorted(
        set(raw_kpoints) - {"comment", "generation_mode", "subdivisions", "shift"}
    )
    if unknown_kpoints:
        raise ValueError(f"unsupported kpoints fields: {', '.join(unknown_kpoints)}")
    mode = raw_kpoints.get("generation_mode")
    if mode not in {"gamma", "monkhorst-pack"}:
        raise ValueError("generation_mode must be gamma or monkhorst-pack")
    subdivisions = _three_values(raw_kpoints.get("subdivisions"), integers=True)
    shift = _three_values(raw_kpoints.get("shift", [0, 0, 0]), integers=False)
    comment = raw_kpoints.get("comment", "CatEx resolved mesh")
    if (
        not isinstance(comment, str)
        or not comment.strip()
        or len(comment) > 100
        or any(character in comment for character in "\r\n")
    ):
        raise ValueError("kpoints comment must be one non-empty line of at most 100 characters")
    return ScientificProtocol(
        protocol_id=protocol_id,
        target_vasp_version=target,
        incar=incar,
        kpoints=KpointsSpecification(
            generation_mode=mode,
            subdivisions=subdivisions,  # type: ignore[arg-type]
            shift=shift,  # type: ignore[arg-type]
            comment=comment.strip(),
        ),
    )


def render_incar(protocol: ScientificProtocol) -> str:
    """Render stable, one-assignment-per-line INCAR text."""

    return "".join(f"{tag} = {value}\n" for tag, value in sorted(protocol.incar.items()))


def render_kpoints(specification: KpointsSpecification) -> str:
    """Render the supported regular-mesh KPOINTS subset deterministically."""

    mode = "Gamma" if specification.generation_mode == "gamma" else "Monkhorst-Pack"
    subdivisions = " ".join(str(value) for value in specification.subdivisions)
    shift = " ".join(format(value, ".12g") for value in specification.shift)
    return f"{specification.comment}\n0\n{mode}\n{subdivisions}\n{shift}\n"


def energy_family_payload(
    protocol: ScientificProtocol,
    *,
    potcar_metadata,
) -> dict[str, Any]:
    """Return the documented scientific-only compatibility payload."""

    included_incar = {
        tag: value
        for tag, value in sorted(protocol.incar.items())
        if is_energy_family_relevant(tag)
    }
    return {
        "schema": "catex.energy-family.v1",
        "target_vasp_version": protocol.target_vasp_version,
        "incar": included_incar,
        "kpoints": {
            "generation_mode": protocol.kpoints.generation_mode,
            "subdivisions": list(protocol.kpoints.subdivisions),
            "shift": list(protocol.kpoints.shift),
        },
        "potcar": {
            "potential_family": potcar_metadata.potential_family,
            "datasets": [
                {
                    "element": item.element,
                    "potential_label": item.potential_label,
                    "titel": item.titel,
                    "lexch": item.lexch,
                    "zval": item.zval,
                    "enmax_eV": item.enmax_ev,
                    "sha256": item.sha256,
                }
                for item in potcar_metadata.datasets
            ],
        },
    }


def resolve_protocol(
    protocol_path: str | Path,
    *,
    poscar_path: str | Path,
    potcar_metadata_path: str | Path,
) -> ProtocolResolutionReport:
    """Resolve and validate one protocol against exact POSCAR/POTCAR metadata artifacts."""

    paths = tuple(Path(item) for item in (protocol_path, poscar_path, potcar_metadata_path))
    texts: list[str | None] = []
    source_artifacts: list[ArtifactRecord | None] = []
    diagnostics: list[Diagnostic] = []
    for path in paths:
        text, artifact, findings = _read_utf8(path)
        texts.append(text)
        source_artifacts.append(artifact)
        diagnostics.extend(findings)
    if any(text is None for text in texts):
        return ProtocolResolutionReport(None, None, tuple(diagnostics))

    try:
        protocol = parse_scientific_protocol(texts[0] or "")
    except ValueError as exc:
        return ProtocolResolutionReport(
            None,
            None,
            (
                Diagnostic(
                    "SCIENTIFIC_PROTOCOL_INVALID",
                    Severity.ERROR,
                    str(exc),
                    {"path": str(paths[0])},
                ),
            ),
        )

    artifacts = tuple(item for item in source_artifacts if item is not None)
    if len(artifacts) != 3:
        return ProtocolResolutionReport(protocol, None, tuple(diagnostics))
    try:
        poscar = Poscar.from_str(texts[1] or "")
    except Exception as exc:
        diagnostics.append(
            Diagnostic(
                "PROTOCOL_POSCAR_PARSE_FAILED",
                Severity.ERROR,
                "The protocol source POSCAR could not be parsed.",
                {"exception_type": type(exc).__name__},
            )
        )
        return ProtocolResolutionReport(protocol, None, tuple(diagnostics))
    inspected = inspect_structure(
        poscar.structure,
        source_format="vasp-poscar",
        artifact=artifacts[1],
    )
    diagnostics.extend(inspected.diagnostics)

    metadata, metadata_diagnostics = parse_potcar_metadata(texts[2] or "", artifact=artifacts[2])
    diagnostics.extend(metadata_diagnostics)
    incar_text = render_incar(protocol)
    incar_summary, incar_parse_diagnostics = parse_incar_text(incar_text)
    diagnostics.extend(incar_parse_diagnostics)
    diagnostics.extend(
        validate_incar(
            incar_summary,
            num_sites=len(poscar.structure),
            num_species=len(poscar.site_symbols),
            mode=ValidationMode.STRICT,
        )
    )
    kpoints_text = render_kpoints(protocol.kpoints)
    kpoints_summary, kpoints_parse_diagnostics = parse_kpoints_text(kpoints_text)
    diagnostics.extend(kpoints_parse_diagnostics)
    if kpoints_summary is not None:
        diagnostics.extend(
            validate_kpoints(kpoints_summary, poscar.structure, mode=ValidationMode.STRICT)
        )
    if metadata is not None:
        encut = None
        with suppress(KeyError, ValueError):
            encut = float(protocol.incar["ENCUT"].replace("D", "E").replace("d", "e"))
        diagnostics.extend(
            validate_potcar_metadata(
                metadata,
                poscar_species_order=tuple(poscar.site_symbols),
                encut_ev=encut,
                mode=ValidationMode.STRICT,
            )
        )
    if metadata is None or any(item.severity is Severity.ERROR for item in diagnostics):
        return ProtocolResolutionReport(protocol, None, tuple(diagnostics))

    family_payload = energy_family_payload(protocol, potcar_metadata=metadata)
    energy_family_id = f"sha256:{_digest(family_payload)}"
    resolved_payload = {
        "schema": "catex.resolved-protocol-digest.v1",
        "protocol": protocol.to_dict(),
        "incar_text": incar_text,
        "kpoints_text": kpoints_text,
        "potcar": family_payload["potcar"],
        "source_sha256": [item.sha256 for item in artifacts],
        "energy_family_id": energy_family_id,
    }
    resolved = ResolvedProtocol(
        protocol_id=protocol.protocol_id,
        target_vasp_version=protocol.target_vasp_version,
        incar_values=protocol.incar,
        incar_text=incar_text,
        kpoints=protocol.kpoints,
        kpoints_text=kpoints_text,
        potcar_metadata=metadata,
        energy_family_id=energy_family_id,
        resolved_protocol_sha256=_digest(resolved_payload),
        source_artifacts=artifacts,
    )
    diagnostics.append(
        Diagnostic(
            "PROTOCOL_MANUAL_REVIEW_REQUIRED",
            Severity.WARNING,
            "The resolved scientific protocol requires an explicit human review before writing.",
            {"resolved_protocol_sha256": resolved.resolved_protocol_sha256},
        )
    )
    return ProtocolResolutionReport(protocol, resolved, tuple(diagnostics))


def record_protocol_review(
    resolved: ResolvedProtocol,
    *,
    approved: bool,
    reviewer: str,
    reviewed_at_utc: str,
    note: str,
) -> ResolvedProtocol:
    """Return a reviewed copy; this function performs no I/O."""

    if not reviewer.strip() or len(reviewer) > 100 or any(c in reviewer for c in "\r\n"):
        raise ValueError("reviewer must be one non-empty line of at most 100 characters")
    if not _UTC_TIMESTAMP.fullmatch(reviewed_at_utc):
        raise ValueError("reviewed_at_utc must use YYYY-MM-DDTHH:MM:SSZ")
    if len(note) > 500 or any(c in note for c in "\r\n"):
        raise ValueError("review note must be one line of at most 500 characters")
    review = ProtocolReview(
        state=ReviewState.APPROVED if approved else ReviewState.REJECTED,
        reviewer=reviewer.strip(),
        reviewed_at_utc=reviewed_at_utc,
        note=note,
    )
    return replace(resolved, review=review)
