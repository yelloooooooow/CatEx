"""Project-scoped persistence and orchestration for experimental modeling."""

from __future__ import annotations

import hashlib
import importlib.util
import json
import os
import re
from collections.abc import Mapping, Sequence
from datetime import UTC, datetime
from pathlib import Path
from types import MappingProxyType
from typing import Any
from uuid import uuid4

import numpy as np
from pymatgen.core import Structure
from pymatgen.io.vasp import Poscar

from catex.experimental import (
    GPTCandidatePlanner,
    OpenAIResponsesTransport,
    ProviderRegistry,
    RuleCandidatePlanner,
    XRDSearchSettings,
    extract_characterization_summary,
    fetch_optimade_structures,
    infer_experimental_models,
    load_local_structure_catalog,
    materialize_provider_catalog,
    parse_experiment_spec,
    parse_xrd_path,
    simulate_xrd_on_grid,
)
from catex.experimental.materials_project import (
    MPAPISummaryClient,
    fetch_materials_project_structures,
)
from catex.experimental.models import StructureReference, StructureSourceKind
from catex.experimental.providers import CatalogEntry, StructureProvider
from catex.hashing import structure_hash
from catex_app.projects import ProjectStore
from catex_app.secure_store import (
    CredentialProvider,
    CredentialStore,
    CredentialStoreError,
    SystemCredentialStore,
    environment_variable,
    resolve_credential,
)
from catex_app.services import _viewer_payload

MAX_EVIDENCE_UPLOAD_BYTES = 20 * 1024 * 1024
MAX_EXPERIMENT_JSON_BYTES = 4 * 1024 * 1024
_SAFE_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}$")
_EVIDENCE_ID = re.compile(r"^evidence-[0-9a-f]{20}$")
_SPEC_ID = re.compile(r"^spec-[0-9a-f]{20}$")
_CATALOG_ID = re.compile(r"^catalog-[0-9a-f]{16}$")
_RUN_ID = re.compile(r"^model-run-[0-9a-f]{16}$")
_REVIEW_ID = re.compile(r"^model-review-[0-9a-f]{16}$")
_BLOCKED_UPLOAD_SUFFIXES = {
    ".bat",
    ".cmd",
    ".com",
    ".dll",
    ".exe",
    ".js",
    ".msi",
    ".ps1",
    ".py",
    ".scr",
    ".vbs",
}


class ExperimentalModelingError(ValueError):
    """Raised when a project modeling operation violates a bounded contract."""


def _utc_now() -> str:
    return datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _json_bytes(payload: object) -> bytes:
    return (
        json.dumps(
            payload,
            allow_nan=False,
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
        )
        + "\n"
    ).encode("utf-8")


def _write_json(path: Path, payload: Mapping[str, Any], *, exclusive: bool = False) -> None:
    content = _json_bytes(dict(payload))
    if len(content) > MAX_EXPERIMENT_JSON_BYTES:
        raise ExperimentalModelingError("experimental-modeling JSON exceeds the safety limit")
    with path.open("xb" if exclusive else "wb") as stream:
        stream.write(content)


def _read_json(path: Path) -> dict[str, Any]:
    content = path.read_bytes()
    if len(content) > MAX_EXPERIMENT_JSON_BYTES:
        raise ExperimentalModelingError("stored experimental-modeling JSON is too large")
    try:
        payload = json.loads(content.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ExperimentalModelingError("stored experimental-modeling JSON is invalid") from exc
    if not isinstance(payload, dict):
        raise ExperimentalModelingError("stored experimental-modeling JSON must be an object")
    return payload


def _safe_identifier(value: str, *, field: str) -> str:
    if _SAFE_ID.fullmatch(value) is None:
        raise ExperimentalModelingError(f"{field} has an invalid identifier format")
    return value


def _safe_filename(filename: str) -> str:
    if (
        not filename
        or filename in {".", ".."}
        or "/" in filename
        or "\\" in filename
        or any(ord(character) < 32 for character in filename)
    ):
        raise ExperimentalModelingError("evidence filename must be one safe basename")
    if len(filename) > 255:
        raise ExperimentalModelingError("evidence filename exceeds 255 characters")
    if Path(filename).suffix.lower() in _BLOCKED_UPLOAD_SUFFIXES:
        raise ExperimentalModelingError("executable or script evidence uploads are not accepted")
    return filename


def _one_line(value: str, *, field: str, maximum: int, allow_empty: bool = False) -> str:
    normalized = value.strip()
    if "\n" in value or "\r" in value or len(normalized) > maximum:
        raise ExperimentalModelingError(f"{field} must be one line of at most {maximum} characters")
    if not allow_empty and not normalized:
        raise ExperimentalModelingError(f"{field} must not be empty")
    return normalized


def _bounded_text(value: str, *, field: str, maximum: int) -> str:
    normalized = value.strip()
    if not normalized or len(normalized) > maximum:
        raise ExperimentalModelingError(f"{field} must contain between 1 and {maximum} characters")
    if any(ord(character) < 32 and character not in {"\n", "\r", "\t"} for character in value):
        raise ExperimentalModelingError(f"{field} contains an unsupported control character")
    return normalized


def _file_token(value: str) -> str:
    normalized = re.sub(r"[^A-Za-z0-9._-]", "-", value).strip(".-")
    return normalized[:80] or "candidate"


class _ProjectStructureProvider:
    def __init__(self, entries: Mapping[str, CatalogEntry]) -> None:
        if not entries:
            raise ExperimentalModelingError("project provider requires at least one structure")
        self._entries = MappingProxyType(dict(sorted(entries.items())))

    @property
    def provider_id(self) -> str:
        return "project"

    def references(self) -> tuple[StructureReference, ...]:
        return tuple(item.reference for item in self._entries.values())

    def get(self, reference_key: str) -> Structure:
        try:
            return self._entries[reference_key].structure.copy()
        except KeyError as exc:
            raise ExperimentalModelingError(
                f"unknown project structure reference: {reference_key}"
            ) from exc


class ExperimentalModelingService:
    """Append-oriented application service used by the local Web workbench."""

    def __init__(
        self,
        store: ProjectStore,
        credential_store: CredentialStore | None = None,
    ) -> None:
        self.store = store
        self.credential_store = credential_store or SystemCredentialStore()

    def _credential_status(self, provider: CredentialProvider) -> dict[str, Any]:
        environment_configured = bool(os.environ.get(environment_variable(provider), "").strip())
        saved_to_system = False
        store_readable = False
        store_status = self.credential_store.status()
        if store_status.available:
            try:
                saved_to_system = bool(self.credential_store.get(provider))
                store_readable = True
            except CredentialStoreError:
                store_readable = False
        source = (
            "environment"
            if environment_configured
            else "system_keyring"
            if saved_to_system
            else None
        )
        return {
            "configured": source is not None,
            "source": source,
            "environment_configured": environment_configured,
            "saved_to_system": saved_to_system,
            "system_store_readable": store_readable,
        }

    def capabilities(self) -> dict[str, Any]:
        mp_client_installed = importlib.util.find_spec("mp_api") is not None
        store_status = self.credential_store.status()
        mp_credential = self._credential_status("materials_project")
        openai_credential = self._credential_status("openai")
        return {
            "schema_version": "catex.experimental-modeling-capabilities.v2",
            "enabled": True,
            "max_evidence_upload_bytes": MAX_EVIDENCE_UPLOAD_BYTES,
            "rule_planner": {"available": True, "external_api": False},
            "providers": {
                "project": {"available": True, "requires_key": False},
                "optimade": {"available": True, "requires_key": False},
                "materials_project": {
                    "available": mp_client_installed and mp_credential["configured"],
                    "client_installed": mp_client_installed,
                    "key_configured": mp_credential["configured"],
                    "credential_source": mp_credential["source"],
                    "saved_to_system": mp_credential["saved_to_system"],
                    "requires_key": True,
                    "api_key_environment_variable": "MP_API_KEY",
                },
            },
            "gpt_planner": {
                "available": openai_credential["configured"],
                "key_configured": openai_credential["configured"],
                "credential_source": openai_credential["source"],
                "saved_to_system": openai_credential["saved_to_system"],
                "api_key_environment_variable": "OPENAI_API_KEY",
                "model": os.environ.get("CATEX_OPENAI_MODEL", "gpt-5.6-sol"),
                "responses_api": True,
                "stores_responses": False,
            },
            "credential_store": store_status.to_dict(),
            "credentials_persisted": store_status.available and store_status.persistent,
        }

    @staticmethod
    def _validated_secret(secret: str) -> str:
        value = secret.strip()
        if not 8 <= len(value) <= 4096:
            raise ExperimentalModelingError("credential must contain between 8 and 4096 characters")
        if any(ord(character) < 33 or ord(character) == 127 for character in value):
            raise ExperimentalModelingError(
                "credential must not contain whitespace or control characters"
            )
        return value

    def save_credential(
        self,
        provider: CredentialProvider,
        secret: str,
    ) -> dict[str, Any]:
        """Verify and persist one credential in the operating-system keyring."""

        value = self._validated_secret(secret)
        status = self.credential_store.status()
        if not status.available or not status.persistent:
            raise ExperimentalModelingError(
                "a supported operating-system credential store is not available"
            )
        verification: dict[str, Any]
        try:
            if provider == "materials_project":
                if importlib.util.find_spec("mp_api") is None:
                    raise ExperimentalModelingError(
                        "Materials Project support requires the optional mp-api dependency"
                    )
                verification = {
                    "database_version": MPAPISummaryClient(api_key=value).verify_connection()
                }
            elif provider == "openai":
                verification = {
                    "visible_model_count": OpenAIResponsesTransport(
                        model=os.environ.get("CATEX_OPENAI_MODEL", "gpt-5.6-sol"),
                        api_key=value,
                    ).verify_api_key()
                }
            else:
                raise ExperimentalModelingError("unsupported credential provider")
        except ValueError as exc:
            raise ExperimentalModelingError(str(exc)) from exc
        try:
            self.credential_store.set(provider, value)
        except CredentialStoreError as exc:
            raise ExperimentalModelingError(str(exc)) from exc
        return {
            "schema_version": "catex.credential-save.v1",
            "provider": provider,
            "saved_to_system": True,
            "verified": True,
            "verification": verification,
            "capabilities": self.capabilities(),
        }

    def delete_credential(self, provider: CredentialProvider) -> dict[str, Any]:
        """Delete one CatEx credential from the operating-system keyring."""

        try:
            deleted = self.credential_store.delete(provider)
        except CredentialStoreError as exc:
            raise ExperimentalModelingError(str(exc)) from exc
        return {
            "schema_version": "catex.credential-delete.v1",
            "provider": provider,
            "deleted_from_system": deleted,
            "capabilities": self.capabilities(),
        }

    def _root(self, project_id: str) -> Path:
        project = self.store.project_directory(project_id)
        root = project / "experimental-modeling"
        root.mkdir(exist_ok=True)
        for name in (
            "evidence",
            "specs",
            "catalogs",
            "runs",
            "reviews",
            "materializations",
        ):
            (root / name).mkdir(exist_ok=True)
        (root / "evidence" / "files").mkdir(exist_ok=True)
        return root

    def add_evidence(self, project_id: str, filename: str, content: bytes) -> dict[str, Any]:
        safe_name = _safe_filename(filename)
        if not content:
            raise ExperimentalModelingError("evidence upload must not be empty")
        if len(content) > MAX_EVIDENCE_UPLOAD_BYTES:
            raise ExperimentalModelingError("evidence upload exceeds the 20 MiB limit")
        root = self._root(project_id)
        digest = hashlib.sha256(content).hexdigest()
        evidence_id = f"evidence-{digest[:20]}"
        metadata_path = root / "evidence" / f"{evidence_id}.json"
        if metadata_path.is_file():
            record = _read_json(metadata_path)
            stored = root / "evidence" / "files" / str(record["stored_filename"])
            if stored.is_file() and hashlib.sha256(stored.read_bytes()).hexdigest() == digest:
                return record
            raise ExperimentalModelingError("stored evidence no longer matches its record")
        suffix = Path(safe_name).suffix.lower()
        stored_filename = f"{digest}{suffix}"
        stored_path = root / "evidence" / "files" / stored_filename
        with stored_path.open("xb") as stream:
            stream.write(content)
        record = {
            "schema_version": "catex.web-experimental-evidence-artifact.v1",
            "evidence_artifact_id": evidence_id,
            "project_id": project_id,
            "original_filename": safe_name,
            "stored_filename": stored_filename,
            "sha256": digest,
            "size_bytes": len(content),
            "created_at_utc": _utc_now(),
            "retained": True,
        }
        _write_json(metadata_path, record, exclusive=True)
        self.store.append_event(
            project_id,
            "experimental.evidence_added",
            {
                "evidence_artifact_id": evidence_id,
                "sha256": digest,
                "size_bytes": len(content),
            },
        )
        return record

    def list_evidence(self, project_id: str) -> list[dict[str, Any]]:
        root = self._root(project_id) / "evidence"
        return [_read_json(path) for path in sorted(root.glob("evidence-*.json"))]

    def extract_evidence(
        self,
        project_id: str,
        *,
        evidence_artifact_id: str | None,
        evidence_id: str,
        kind: str,
        conclusion: str,
        instrument_info: str,
    ) -> dict[str, Any]:
        """Return reviewable suggestions from a stored characterization file."""

        _safe_identifier(evidence_id, field="evidence_id")
        stored = None
        if evidence_artifact_id is not None:
            record = self._evidence_record(project_id, evidence_artifact_id)
            stored = self._root(project_id) / "evidence" / "files" / str(record["stored_filename"])
        try:
            return extract_characterization_summary(
                stored,
                kind=kind,
                evidence_id=evidence_id,
                conclusion=_one_line(
                    conclusion,
                    field="conclusion",
                    maximum=1000,
                    allow_empty=True,
                ),
                instrument_info=_one_line(
                    instrument_info,
                    field="instrument_info",
                    maximum=1000,
                    allow_empty=True,
                ),
            )
        except (TypeError, ValueError) as exc:
            raise ExperimentalModelingError(str(exc)) from exc

    def _evidence_record(self, project_id: str, evidence_artifact_id: str) -> dict[str, Any]:
        if _EVIDENCE_ID.fullmatch(evidence_artifact_id) is None:
            raise ExperimentalModelingError("evidence_artifact_id has an invalid format")
        path = self._root(project_id) / "evidence" / f"{evidence_artifact_id}.json"
        if not path.is_file():
            raise ExperimentalModelingError("evidence artifact does not exist")
        record = _read_json(path)
        stored = self._root(project_id) / "evidence" / "files" / str(record["stored_filename"])
        if stored.parent != self._root(project_id) / "evidence" / "files" or not stored.is_file():
            raise ExperimentalModelingError("stored evidence artifact is unavailable")
        content = stored.read_bytes()
        if (
            len(content) != record["size_bytes"]
            or hashlib.sha256(content).hexdigest() != record["sha256"]
        ):
            raise ExperimentalModelingError("stored evidence no longer matches its record")
        return record

    def _core_spec_payload(self, project_id: str, payload: Mapping[str, Any]) -> dict[str, Any]:
        core = json.loads(json.dumps(payload, allow_nan=False))
        evidence = core.get("evidence", [])
        if not isinstance(evidence, list):
            raise ExperimentalModelingError("spec evidence must be an array")
        for item in evidence:
            if not isinstance(item, dict):
                raise ExperimentalModelingError("every evidence item must be an object")
            artifact_id = item.pop("evidence_artifact_id", None)
            if artifact_id:
                record = self._evidence_record(project_id, str(artifact_id))
                item["artifact"] = f"evidence/files/{record['stored_filename']}"
        return core

    def save_spec(self, project_id: str, payload: Mapping[str, Any]) -> dict[str, Any]:
        root = self._root(project_id)
        core = self._core_spec_payload(project_id, payload)
        try:
            parsed = parse_experiment_spec(core, artifact_root=root)
        except (TypeError, ValueError, KeyError) as exc:
            raise ExperimentalModelingError(str(exc)) from exc
        normalized_payload = parsed.spec.to_dict()
        digest = hashlib.sha256(_json_bytes(normalized_payload)).hexdigest()
        spec_revision_id = f"spec-{digest[:20]}"
        revision = {
            "schema_version": "catex.web-experimental-spec-revision.v1",
            "spec_revision_id": spec_revision_id,
            "project_id": project_id,
            "created_at_utc": _utc_now(),
            "identity_sha256": digest,
            "spec": json.loads(json.dumps(payload, allow_nan=False)),
            "normalized_spec": normalized_payload,
        }
        revision_path = root / "specs" / f"{spec_revision_id}.json"
        if not revision_path.exists():
            _write_json(revision_path, revision, exclusive=True)
        else:
            revision = _read_json(revision_path)
        _write_json(
            root / "specs" / "current.json",
            {
                "schema_version": "catex.web-experimental-spec-pointer.v1",
                "spec_revision_id": spec_revision_id,
            },
        )
        self.store.append_event(
            project_id,
            "experimental.spec_saved",
            {"spec_revision_id": spec_revision_id, "identity_sha256": digest},
        )
        return revision

    def current_spec(self, project_id: str) -> dict[str, Any] | None:
        root = self._root(project_id)
        pointer = root / "specs" / "current.json"
        if not pointer.is_file():
            return None
        spec_revision_id = str(_read_json(pointer).get("spec_revision_id", ""))
        if _SPEC_ID.fullmatch(spec_revision_id) is None:
            raise ExperimentalModelingError("current spec pointer is invalid")
        path = root / "specs" / f"{spec_revision_id}.json"
        if not path.is_file():
            raise ExperimentalModelingError("current spec revision is unavailable")
        return _read_json(path)

    def _experiment_input(self, project_id: str) -> tuple[dict[str, Any], Any]:
        revision = self.current_spec(project_id)
        if revision is None:
            raise ExperimentalModelingError("save an experimental specification first")
        core = self._core_spec_payload(project_id, revision["spec"])
        try:
            parsed = parse_experiment_spec(core, artifact_root=self._root(project_id))
        except (TypeError, ValueError, KeyError) as exc:
            raise ExperimentalModelingError(str(exc)) from exc
        return revision, parsed

    def _catalog_snapshot(self, project_id: str, catalog_id: str) -> dict[str, Any]:
        if _CATALOG_ID.fullmatch(catalog_id) is None:
            raise ExperimentalModelingError("catalog_id has an invalid format")
        path = self._root(project_id) / "catalogs" / catalog_id / "snapshot.json"
        if not path.is_file():
            raise ExperimentalModelingError("structure catalog does not exist")
        return _read_json(path)

    def list_catalogs(self, project_id: str) -> list[dict[str, Any]]:
        root = self._root(project_id) / "catalogs"
        return [
            _read_json(path)
            for path in sorted(root.glob("catalog-*/snapshot.json"))
            if path.is_file()
        ]

    def _materialize_catalog(
        self,
        project_id: str,
        provider: StructureProvider,
        *,
        provider_kind: str,
        display_provider_id: str,
        query: Mapping[str, Any],
        fetch_report: Mapping[str, Any],
    ) -> dict[str, Any]:
        root = self._root(project_id)
        catalog_id = f"catalog-{uuid4().hex[:16]}"
        destination = root / "catalogs" / catalog_id
        materialization = materialize_provider_catalog(provider, destination)
        snapshot = {
            "schema_version": "catex.web-structure-catalog-snapshot.v1",
            "catalog_id": catalog_id,
            "project_id": project_id,
            "provider_kind": provider_kind,
            "provider_id": provider.provider_id,
            "display_provider_id": display_provider_id,
            "created_at_utc": _utc_now(),
            "query": dict(query),
            "reference_count": len(provider.references()),
            "references": [item.to_dict() for item in provider.references()],
            "fetch_report": dict(fetch_report),
            "materialization": materialization.to_dict(),
        }
        _write_json(destination / "snapshot.json", snapshot, exclusive=True)
        self.store.append_event(
            project_id,
            "experimental.catalog_fetched",
            {
                "catalog_id": catalog_id,
                "provider_kind": provider_kind,
                "reference_count": len(provider.references()),
            },
        )
        return snapshot

    def fetch_optimade(
        self,
        project_id: str,
        *,
        base_url: str,
        provider_id: str,
        required_elements: Sequence[str],
        maximum_results: int,
        maximum_pages: int,
        license: str = "",
        citation: str = "",
        transport: Any = None,
    ) -> dict[str, Any]:
        display_id = _safe_identifier(provider_id, field="provider_id")
        internal_id = f"{display_id}-{uuid4().hex[:8]}"
        try:
            result = fetch_optimade_structures(
                base_url=base_url,
                provider_id=internal_id,
                required_elements=required_elements,
                maximum_results=maximum_results,
                maximum_pages=maximum_pages,
                license=license,
                citation=citation,
                transport=transport,
            )
        except (TypeError, ValueError) as exc:
            raise ExperimentalModelingError(str(exc)) from exc
        return self._materialize_catalog(
            project_id,
            result.provider,
            provider_kind="optimade",
            display_provider_id=display_id,
            query={
                "base_url": base_url,
                "required_elements": list(required_elements),
                "maximum_results": maximum_results,
                "maximum_pages": maximum_pages,
            },
            fetch_report=result.report.to_dict(),
        )

    def fetch_materials_project(
        self,
        project_id: str,
        *,
        required_elements: Sequence[str],
        maximum_results: int,
        client: Any = None,
    ) -> dict[str, Any]:
        provider_id = f"materials-project-{uuid4().hex[:8]}"
        if client is None:
            credential = resolve_credential(
                self.credential_store,
                "materials_project",
            )
            if credential is None:
                raise ExperimentalModelingError(
                    "save a Materials Project credential or configure MP_API_KEY first"
                )
            client = MPAPISummaryClient(api_key=credential.value)
        try:
            result = fetch_materials_project_structures(
                provider_id=provider_id,
                required_elements=required_elements,
                maximum_results=maximum_results,
                client=client,
            )
        except (TypeError, ValueError) as exc:
            raise ExperimentalModelingError(str(exc)) from exc
        return self._materialize_catalog(
            project_id,
            result.provider,
            provider_kind="materials_project",
            display_provider_id="Materials Project",
            query={
                "required_elements": list(required_elements),
                "maximum_results": maximum_results,
            },
            fetch_report=result.report.to_dict(),
        )

    def _project_provider(self, project_id: str) -> StructureProvider | None:
        entries: dict[str, CatalogEntry] = {}
        for artifact in self.store.list_artifacts(project_id):
            if artifact.get("artifact_type") != "structure":
                continue
            try:
                structure = Structure.from_file(
                    self.store.artifact_path(project_id, str(artifact["artifact_id"]))
                )
            except Exception as exc:
                raise ExperimentalModelingError(
                    f"project structure {artifact['artifact_id']} could not be parsed"
                ) from exc
            reference = StructureReference(
                provider="project",
                record_id=str(artifact["artifact_id"]),
                formula=structure.composition.reduced_formula,
                elements=tuple(sorted(item.symbol for item in structure.composition.elements)),
                source_kind=StructureSourceKind.USER_SUPPLIED,
                source_locator=f"project:{project_id}/artifacts/{artifact['artifact_id']}",
                structure_sha256=structure_hash(structure),
                artifact_sha256=str(artifact["sha256"]),
            )
            entries[reference.key] = CatalogEntry(reference, structure)
        return _ProjectStructureProvider(entries) if entries else None

    def _provider_registry(
        self,
        project_id: str,
        catalog_ids: Sequence[str],
    ) -> tuple[ProviderRegistry, tuple[str, ...]]:
        providers: list[StructureProvider] = []
        project_provider = self._project_provider(project_id)
        if project_provider is not None:
            providers.append(project_provider)
        selected = list(catalog_ids)
        if not selected:
            selected = [item["catalog_id"] for item in self.list_catalogs(project_id)]
        for catalog_id in selected:
            snapshot = self._catalog_snapshot(project_id, catalog_id)
            catalog_path = (
                self._root(project_id) / "catalogs" / str(snapshot["catalog_id"]) / "catalog.json"
            )
            try:
                providers.append(load_local_structure_catalog(catalog_path))
            except ValueError as exc:
                raise ExperimentalModelingError(str(exc)) from exc
        if not providers:
            raise ExperimentalModelingError(
                "add a project structure or fetch a structure catalog before inference"
            )
        try:
            registry = ProviderRegistry(providers)
        except ValueError as exc:
            raise ExperimentalModelingError(str(exc)) from exc
        return registry, tuple(selected)

    @staticmethod
    def _xrd_plot_data(
        experiment: Any,
        registry: ProviderRegistry,
        report: Any,
    ) -> dict[str, Any] | None:
        phase_search = report.phase_search
        if phase_search is None:
            return None
        xrd_records = [
            item
            for item in experiment.spec.evidence
            if item.evidence_id in experiment.artifact_paths and item.kind.value in {"xrd", "gixrd"}
        ]
        if not xrd_records:
            return None
        selected = sorted(xrd_records, key=lambda item: item.evidence_id)[0]
        pattern = parse_xrd_path(experiment.artifact_paths[selected.evidence_id])
        x, observed = pattern.arrays()
        observed = observed / max(float(np.max(observed)), 1e-12)

        best_single = (
            phase_search.single_phase_matches[0] if phase_search.single_phase_matches else None
        )
        best_combination = (
            phase_search.combination_matches[0] if phase_search.combination_matches else None
        )
        if best_combination is not None and (
            best_single is None or best_combination.evidence_score > best_single.evidence_score
        ):
            predicted = np.zeros_like(x)
            for key, contribution in zip(
                best_combination.reference_keys,
                best_combination.diffraction_contributions,
                strict=True,
            ):
                predicted += contribution * simulate_xrd_on_grid(
                    registry.get_structure(key),
                    x,
                    wavelength=phase_search.settings.wavelength,
                    shift_degrees=best_combination.shift_degrees,
                    fwhm_degrees=best_combination.fwhm_degrees,
                )
            label = " + ".join(best_combination.formulas)
        elif best_single is not None:
            predicted = simulate_xrd_on_grid(
                registry.get_structure(best_single.reference_key),
                x,
                wavelength=phase_search.settings.wavelength,
                shift_degrees=best_single.shift_degrees,
                fwhm_degrees=best_single.fwhm_degrees,
            )
            label = best_single.formula
        else:
            return None
        predicted = predicted / max(float(np.max(predicted)), 1e-12)
        residual = observed - predicted
        if len(x) > 500:
            indices = np.linspace(0, len(x) - 1, 500, dtype=int)
            x = x[indices]
            observed = observed[indices]
            predicted = predicted[indices]
            residual = residual[indices]
        return {
            "schema_version": "catex.web-xrd-plot.v1",
            "label": label,
            "two_theta_degrees": [float(item) for item in x],
            "observed_normalized": [float(item) for item in observed],
            "fitted_normalized": [float(item) for item in predicted],
            "residual": [float(item) for item in residual],
        }

    def infer(
        self,
        project_id: str,
        *,
        planner_kind: str,
        catalog_ids: Sequence[str],
        maximum_representatives: int,
        xrd_settings: Mapping[str, Any] | None,
    ) -> dict[str, Any]:
        revision, experiment = self._experiment_input(project_id)
        registry, resolved_catalog_ids = self._provider_registry(project_id, catalog_ids)
        if planner_kind == "rule":
            planner = RuleCandidatePlanner()
        elif planner_kind == "gpt":
            credential = resolve_credential(self.credential_store, "openai")
            if credential is None:
                raise ExperimentalModelingError(
                    "save an OpenAI credential or configure OPENAI_API_KEY first"
                )
            planner = GPTCandidatePlanner(
                OpenAIResponsesTransport(
                    model=os.environ.get("CATEX_OPENAI_MODEL", "gpt-5.6-sol"),
                    api_key=credential.value,
                )
            )
        else:
            raise ExperimentalModelingError("planner_kind must be rule or gpt")
        try:
            settings = XRDSearchSettings(**dict(xrd_settings or {}))
            run = infer_experimental_models(
                experiment,
                registry,
                planner,
                xrd_settings=settings,
                maximum_representatives=maximum_representatives,
            )
        except (TypeError, ValueError) as exc:
            raise ExperimentalModelingError(str(exc)) from exc

        run_id = f"model-run-{uuid4().hex[:16]}"
        run_root = self._root(project_id) / "runs" / run_id
        run_root.mkdir(exist_ok=False)
        candidates_root = run_root / "candidates"
        candidates_root.mkdir()
        assessments = {
            item.candidate_id: item.to_dict() for item in run.report.candidate_assessments
        }
        candidate_records: list[dict[str, Any]] = []
        for index, candidate in enumerate(run.candidates, start=1):
            filename = f"{index:04d}-{_file_token(candidate.candidate_id)}.cif"
            path = candidates_root / filename
            candidate.structure.to(filename=path, fmt="cif")
            content = path.read_bytes()
            candidate_records.append(
                {
                    "candidate_id": candidate.candidate_id,
                    "relative_path": f"candidates/{filename}",
                    "cif_sha256": hashlib.sha256(content).hexdigest(),
                    "size_bytes": len(content),
                    "assessment": assessments[candidate.candidate_id],
                    "viewer": _viewer_payload(candidate.structure),
                }
            )
        record = {
            "schema_version": "catex.web-experimental-modeling-run.v1",
            "run_id": run_id,
            "project_id": project_id,
            "created_at_utc": _utc_now(),
            "spec_revision_id": revision["spec_revision_id"],
            "planner_kind": planner_kind,
            "catalog_ids": list(resolved_catalog_ids),
            "report": run.report.to_dict(),
            "xrd_plot": self._xrd_plot_data(experiment, registry, run.report),
            "candidates": candidate_records,
            "review_required": True,
            "materialized": False,
        }
        _write_json(run_root / "run.json", record, exclusive=True)
        self.store.append_event(
            project_id,
            "experimental.inference_completed",
            {
                "run_id": run_id,
                "report_sha256": run.report.identity_sha256,
                "planner_kind": planner_kind,
                "candidate_count": len(candidate_records),
            },
        )
        return record

    def _run_record(self, project_id: str, run_id: str) -> dict[str, Any]:
        if _RUN_ID.fullmatch(run_id) is None:
            raise ExperimentalModelingError("run_id has an invalid format")
        path = self._root(project_id) / "runs" / run_id / "run.json"
        if not path.is_file():
            raise ExperimentalModelingError("experimental-modeling run does not exist")
        record = _read_json(path)
        record["materialized"] = self._run_materialized(project_id, run_id)
        return record

    def _run_materialized(self, project_id: str, run_id: str) -> bool:
        for path in (self._root(project_id) / "materializations").glob("*.json"):
            if _read_json(path).get("run_id") == run_id:
                return True
        return False

    def list_runs(self, project_id: str) -> list[dict[str, Any]]:
        records = []
        for path in sorted(
            (self._root(project_id) / "runs").glob("model-run-*/run.json"),
            reverse=True,
        ):
            record = _read_json(path)
            records.append(
                {
                    "schema_version": record["schema_version"],
                    "run_id": record["run_id"],
                    "created_at_utc": record["created_at_utc"],
                    "spec_revision_id": record["spec_revision_id"],
                    "planner_kind": record["planner_kind"],
                    "status": record["report"]["status"],
                    "claim_ceiling": record["report"]["claim_ceiling"],
                    "report_sha256": record["report"]["identity_sha256"],
                    "candidate_count": len(record["candidates"]),
                    "representative_count": len(record["report"]["representative_candidate_ids"]),
                    "materialized": self._run_materialized(project_id, str(record["run_id"])),
                }
            )
        return records

    def get_run(self, project_id: str, run_id: str) -> dict[str, Any]:
        return self._run_record(project_id, run_id)

    def record_review(
        self,
        project_id: str,
        run_id: str,
        *,
        approved_candidate_ids: Sequence[str],
        reviewer: str,
        note: str,
    ) -> dict[str, Any]:
        run = self._run_record(project_id, run_id)
        reviewer = _one_line(reviewer, field="reviewer", maximum=100)
        note = _bounded_text(note, field="note", maximum=1000)
        selected = tuple(dict.fromkeys(approved_candidate_ids))
        if not selected:
            raise ExperimentalModelingError("approve at least one representative candidate")
        representatives = set(run["report"]["representative_candidate_ids"])
        unknown = sorted(set(selected) - representatives)
        if unknown:
            raise ExperimentalModelingError(
                "only representative candidates from this run may be approved"
            )
        review_id = f"model-review-{uuid4().hex[:16]}"
        record = {
            "schema_version": "catex.web-experimental-model-review.v1",
            "review_id": review_id,
            "project_id": project_id,
            "run_id": run_id,
            "report_sha256": run["report"]["identity_sha256"],
            "approved_candidate_ids": list(selected),
            "reviewer": reviewer,
            "note": note,
            "reviewed_at_utc": _utc_now(),
            "unique_structure_claimed": False,
        }
        _write_json(
            self._root(project_id) / "reviews" / f"{review_id}.json",
            record,
            exclusive=True,
        )
        self.store.append_event(
            project_id,
            "experimental.candidates_reviewed",
            {
                "review_id": review_id,
                "run_id": run_id,
                "approved_candidate_ids": list(selected),
            },
        )
        return record

    def list_reviews(self, project_id: str, run_id: str) -> list[dict[str, Any]]:
        self._run_record(project_id, run_id)
        return [
            record
            for path in sorted((self._root(project_id) / "reviews").glob("*.json"))
            if (record := _read_json(path)).get("run_id") == run_id
        ]

    def materialize(
        self,
        project_id: str,
        run_id: str,
        *,
        candidate_ids: Sequence[str],
        confirm_report_sha256: str,
        approved_write: bool,
    ) -> dict[str, Any]:
        if not approved_write:
            raise ExperimentalModelingError("approved_write must be true")
        run = self._run_record(project_id, run_id)
        if confirm_report_sha256 != run["report"]["identity_sha256"]:
            raise ExperimentalModelingError(
                "confirm_report_sha256 does not match the immutable inference report"
            )
        selected = tuple(dict.fromkeys(candidate_ids))
        if not selected:
            raise ExperimentalModelingError("select at least one candidate to materialize")
        reviews = self.list_reviews(project_id, run_id)
        approved = {
            candidate_id for review in reviews for candidate_id in review["approved_candidate_ids"]
        }
        if not set(selected) <= approved:
            raise ExperimentalModelingError(
                "every materialized candidate must first be explicitly approved"
            )
        candidate_map = {item["candidate_id"]: item for item in run["candidates"]}
        if not set(selected) <= set(candidate_map):
            raise ExperimentalModelingError("candidate does not belong to this run")
        prepared: list[tuple[str, bytes, str]] = []
        for candidate_id in selected:
            relative = Path(str(candidate_map[candidate_id]["relative_path"]))
            path = (self._root(project_id) / "runs" / run_id / relative).resolve()
            run_root = (self._root(project_id) / "runs" / run_id).resolve()
            if not path.is_relative_to(run_root) or not path.is_file():
                raise ExperimentalModelingError("stored candidate structure is unavailable")
            cif_content = path.read_bytes()
            cif_sha256 = hashlib.sha256(cif_content).hexdigest()
            if cif_sha256 != candidate_map[candidate_id].get("cif_sha256") or len(
                cif_content
            ) != candidate_map[candidate_id].get("size_bytes"):
                raise ExperimentalModelingError(
                    "stored candidate structure no longer matches the immutable run"
                )
            try:
                structure = Structure.from_file(path)
            except Exception as exc:
                raise ExperimentalModelingError(
                    "stored candidate structure could not be parsed"
                ) from exc
            content = Poscar(structure).get_str().encode("utf-8")
            prepared.append((candidate_id, content, cif_sha256))
        artifacts = []
        for candidate_id, content, cif_sha256 in prepared:
            artifacts.append(
                {
                    "candidate_id": candidate_id,
                    "source_candidate_cif_sha256": cif_sha256,
                    "artifact": self.store.add_structure(
                        project_id,
                        f"{_file_token(candidate_id)}.vasp",
                        content,
                    ),
                }
            )
        materialization_id = f"materialization-{uuid4().hex[:16]}"
        record = {
            "schema_version": "catex.web-experimental-materialization.v1",
            "materialization_id": materialization_id,
            "project_id": project_id,
            "run_id": run_id,
            "report_sha256": confirm_report_sha256,
            "candidate_ids": list(selected),
            "artifacts": artifacts,
            "materialized_at_utc": _utc_now(),
            "approved_write": True,
        }
        _write_json(
            self._root(project_id) / "materializations" / f"{materialization_id}.json",
            record,
            exclusive=True,
        )
        self.store.append_event(
            project_id,
            "experimental.candidates_materialized",
            {
                "materialization_id": materialization_id,
                "run_id": run_id,
                "artifact_ids": [item["artifact"]["artifact_id"] for item in artifacts],
            },
        )
        return record
