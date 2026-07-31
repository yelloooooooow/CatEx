"""Strict parsing of local experiment specifications and evidence artifacts."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from types import MappingProxyType
from typing import Any

from catex.experimental.models import (
    CompositionScope,
    ElementConstraint,
    EvidenceArtifact,
    EvidenceKind,
    EvidenceRecord,
    EvidenceRole,
    ExperimentSpec,
    SampleState,
)

_TOP_LEVEL_KEYS = {
    "schema_version",
    "sample_id",
    "target_state",
    "material_pack",
    "allowed_elements",
    "excluded_elements",
    "composition_constraints",
    "evidence",
}
_EVIDENCE_KEYS = {
    "evidence_id",
    "kind",
    "sample_state",
    "role",
    "metadata",
    "artifact",
    "note",
}
_CONSTRAINT_KEYS = {
    "element",
    "minimum_atomic_fraction",
    "maximum_atomic_fraction",
    "scope",
    "evidence_ids",
}


def _reject_unknown(payload: Mapping[str, Any], allowed: set[str], *, context: str) -> None:
    unknown = sorted(set(payload) - allowed)
    if unknown:
        raise ValueError(f"{context} contains unknown fields: {', '.join(unknown)}")


def _mapping(value: Any, *, field_name: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise ValueError(f"{field_name} must be a JSON object")
    return value


def _sequence(value: Any, *, field_name: str) -> list[Any]:
    if not isinstance(value, list):
        raise ValueError(f"{field_name} must be a JSON array")
    return value


def _artifact_identity(path: Path) -> EvidenceArtifact:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        while chunk := stream.read(1024 * 1024):
            digest.update(chunk)
    return EvidenceArtifact(
        name=path.name,
        sha256=digest.hexdigest(),
        size_bytes=path.stat().st_size,
    )


@dataclass(frozen=True, slots=True)
class ExperimentInput:
    """Normalized spec plus runtime-only paths for local evidence artifacts."""

    spec: ExperimentSpec
    artifact_paths: Mapping[str, Path]
    source_path: Path | None = None

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "artifact_paths",
            MappingProxyType(dict(sorted(self.artifact_paths.items()))),
        )


def parse_experiment_spec(
    payload: Mapping[str, Any],
    *,
    artifact_root: str | Path | None = None,
    source_path: str | Path | None = None,
) -> ExperimentInput:
    """Parse one strict JSON-compatible experiment specification."""

    _reject_unknown(payload, _TOP_LEVEL_KEYS, context="experiment spec")
    schema = payload.get("schema_version", "catex.experiment-spec.v1")
    if schema != "catex.experiment-spec.v1":
        raise ValueError("unsupported experiment spec schema_version")
    root = Path(artifact_root or ".").resolve()
    runtime_paths: dict[str, Path] = {}
    evidence: list[EvidenceRecord] = []
    for index, raw_item in enumerate(_sequence(payload.get("evidence", []), field_name="evidence")):
        item = _mapping(raw_item, field_name=f"evidence[{index}]")
        _reject_unknown(item, _EVIDENCE_KEYS, context=f"evidence[{index}]")
        evidence_id = str(item["evidence_id"])
        artifact = None
        raw_artifact = item.get("artifact")
        if raw_artifact is not None:
            if not isinstance(raw_artifact, str) or not raw_artifact.strip():
                raise ValueError(f"evidence[{index}].artifact must be a non-empty path")
            candidate = (root / raw_artifact).resolve()
            if not candidate.is_relative_to(root):
                raise ValueError("evidence artifact must remain inside artifact_root")
            if not candidate.is_file():
                raise ValueError(f"evidence artifact does not exist: {candidate.name}")
            artifact = _artifact_identity(candidate)
            runtime_paths[evidence_id] = candidate
        evidence.append(
            EvidenceRecord(
                evidence_id=evidence_id,
                kind=EvidenceKind(str(item["kind"])),
                sample_state=SampleState(str(item.get("sample_state", "unspecified"))),
                role=EvidenceRole(str(item.get("role", "context"))),
                metadata=_mapping(item.get("metadata", {}), field_name="metadata"),
                artifact=artifact,
                note=str(item.get("note", "")),
            )
        )

    constraints: list[ElementConstraint] = []
    for index, raw_item in enumerate(
        _sequence(
            payload.get("composition_constraints", []),
            field_name="composition_constraints",
        )
    ):
        item = _mapping(raw_item, field_name=f"composition_constraints[{index}]")
        _reject_unknown(
            item,
            _CONSTRAINT_KEYS,
            context=f"composition_constraints[{index}]",
        )
        constraints.append(
            ElementConstraint(
                element=str(item["element"]),
                minimum_atomic_fraction=float(item["minimum_atomic_fraction"]),
                maximum_atomic_fraction=float(item["maximum_atomic_fraction"]),
                scope=CompositionScope(str(item.get("scope", "bulk"))),
                evidence_ids=tuple(
                    str(value)
                    for value in _sequence(
                        item.get("evidence_ids", []),
                        field_name="evidence_ids",
                    )
                ),
            )
        )

    spec = ExperimentSpec(
        sample_id=str(payload["sample_id"]),
        target_state=SampleState(str(payload.get("target_state", "unspecified"))),
        evidence=tuple(evidence),
        composition_constraints=tuple(constraints),
        allowed_elements=tuple(
            str(value)
            for value in _sequence(
                payload.get("allowed_elements", []),
                field_name="allowed_elements",
            )
        ),
        excluded_elements=tuple(
            str(value)
            for value in _sequence(
                payload.get("excluded_elements", []),
                field_name="excluded_elements",
            )
        ),
        material_pack=str(payload.get("material_pack", "generic")),
    )
    return ExperimentInput(
        spec=spec,
        artifact_paths=runtime_paths,
        source_path=Path(source_path).resolve() if source_path is not None else None,
    )


def load_experiment_spec(path: str | Path) -> ExperimentInput:
    """Load and parse an experiment specification with path traversal protection."""

    source = Path(path).resolve()
    if not source.is_file():
        raise ValueError("experiment spec path must be an existing regular file")
    try:
        payload = json.loads(source.read_text(encoding="utf-8-sig"))
    except json.JSONDecodeError as exc:
        raise ValueError("experiment spec is not valid JSON") from exc
    return parse_experiment_spec(
        _mapping(payload, field_name="experiment spec"),
        artifact_root=source.parent,
        source_path=source,
    )
