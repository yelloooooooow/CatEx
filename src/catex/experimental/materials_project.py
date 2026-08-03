"""Optional Materials Project structure provider.

The adapter keeps the API key at the process boundary, records the database
version, and converts remote documents into the same immutable provider
contract used by local and OPTIMADE catalogs.
"""

from __future__ import annotations

import hashlib
import os
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any, Protocol

from pymatgen.core import Element, Structure

from catex.experimental.models import StructureReference, StructureSourceKind
from catex.experimental.providers import (
    CatalogEntry,
    OptimadeStructureProvider,
    StructureProvider,
)
from catex.hashing import structure_hash
from catex.models import Diagnostic, Severity


class MaterialsProjectClient(Protocol):
    """Narrow injectable client used by the provider and its tests."""

    def fetch_summaries(
        self,
        *,
        required_elements: tuple[str, ...],
        maximum_results: int,
    ) -> tuple[str, Sequence[object]]: ...


class MPAPISummaryClient:
    """Runtime bridge to the official optional ``mp-api`` package."""

    def __init__(
        self,
        *,
        api_key: str | None = None,
        api_key_environment_variable: str = "MP_API_KEY",
    ) -> None:
        self.api_key = api_key
        self.api_key_environment_variable = api_key_environment_variable

    def _resolved_api_key(self) -> str:
        api_key = self.api_key or os.environ.get(self.api_key_environment_variable)
        if not api_key:
            raise ValueError(
                f"{self.api_key_environment_variable} or a system credential is required at runtime"
            )
        return api_key

    @staticmethod
    def _mpr_class() -> type:
        try:
            from mp_api.client import MPRester
        except ImportError as exc:
            raise ValueError(
                "Materials Project support requires the optional mp-api dependency"
            ) from exc
        return MPRester

    def verify_connection(self) -> str:
        """Validate one key without persisting it and return the database version."""

        api_key = self._resolved_api_key()
        mpr_class = self._mpr_class()
        try:
            with mpr_class(api_key) as rester:
                return str(rester.get_database_version())
        except Exception as exc:
            raise ValueError("Materials Project credential verification failed") from exc

    def fetch_summaries(
        self,
        *,
        required_elements: tuple[str, ...],
        maximum_results: int,
    ) -> tuple[str, Sequence[object]]:
        fields = [
            "material_id",
            "formula_pretty",
            "structure",
            "energy_above_hull",
            "is_stable",
            "deprecated",
        ]
        api_key = self._resolved_api_key()
        mpr_class = self._mpr_class()
        try:
            with mpr_class(api_key) as rester:
                database_version = str(rester.get_database_version())
                documents = rester.materials.summary.search(
                    elements=list(required_elements),
                    fields=fields,
                    num_chunks=1,
                    chunk_size=maximum_results,
                )
        except Exception as exc:
            raise ValueError("Materials Project API request failed") from exc
        return database_version, documents


@dataclass(frozen=True, slots=True)
class MaterialsProjectFetchReport:
    """Auditable metadata for one explicit Materials Project read."""

    provider_id: str
    required_elements: tuple[str, ...]
    database_version: str
    received_records: int
    accepted_records: int
    records: tuple[Mapping[str, Any], ...]
    diagnostics: tuple[Diagnostic, ...]
    network_read_performed: bool = True
    writes_performed: bool = False
    schema_version: str = "catex.materials-project-fetch.v1"

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "provider_id": self.provider_id,
            "required_elements": list(self.required_elements),
            "database_version": self.database_version,
            "received_records": self.received_records,
            "accepted_records": self.accepted_records,
            "records": [dict(item) for item in self.records],
            "network_read_performed": self.network_read_performed,
            "writes_performed": self.writes_performed,
            "diagnostics": [item.to_dict() for item in self.diagnostics],
        }


@dataclass(frozen=True, slots=True)
class MaterialsProjectFetchResult:
    """Runtime provider paired with its serializable retrieval report."""

    provider: StructureProvider
    report: MaterialsProjectFetchReport


def _document_value(document: object, key: str, default: object = None) -> object:
    if isinstance(document, Mapping):
        return document.get(key, default)
    return getattr(document, key, default)


def _document_structure(document: object) -> Structure:
    value = _document_value(document, "structure")
    if isinstance(value, Structure):
        return value.copy()
    if isinstance(value, Mapping):
        try:
            return Structure.from_dict(dict(value))
        except Exception as exc:
            raise ValueError("Materials Project structure dictionary is invalid") from exc
    raise ValueError("Materials Project summary did not contain a structure")


def fetch_materials_project_structures(
    *,
    provider_id: str,
    required_elements: Sequence[str],
    maximum_results: int = 100,
    client: MaterialsProjectClient | None = None,
) -> MaterialsProjectFetchResult:
    """Fetch a bounded, ordered structure set through the official API client."""

    if not 1 <= maximum_results <= 1000:
        raise ValueError("maximum_results must be between 1 and 1000")
    elements = tuple(sorted({Element(item).symbol for item in required_elements}))
    if not elements:
        raise ValueError("required_elements must not be empty")

    database_version, documents = (client or MPAPISummaryClient()).fetch_summaries(
        required_elements=elements,
        maximum_results=maximum_results,
    )
    entries: dict[str, CatalogEntry] = {}
    records: list[Mapping[str, Any]] = []
    diagnostics: list[Diagnostic] = []
    seen_structures: set[str] = set()
    received = 0
    for document in documents[:maximum_results]:
        received += 1
        external_id = str(_document_value(document, "material_id", "")).strip()
        if not external_id:
            diagnostics.append(
                Diagnostic(
                    "MATERIALS_PROJECT_RECORD_SKIPPED",
                    Severity.WARNING,
                    "A Materials Project record without a material ID was skipped.",
                    {"record_index": received - 1},
                )
            )
            continue
        if bool(_document_value(document, "deprecated", False)):
            diagnostics.append(
                Diagnostic(
                    "MATERIALS_PROJECT_DEPRECATED_SKIPPED",
                    Severity.INFO,
                    "A deprecated Materials Project record was skipped.",
                    {"material_id": external_id},
                )
            )
            continue
        try:
            structure = _document_structure(document)
        except ValueError as exc:
            diagnostics.append(
                Diagnostic(
                    "MATERIALS_PROJECT_STRUCTURE_SKIPPED",
                    Severity.WARNING,
                    "A Materials Project structure could not be normalized.",
                    {"material_id": external_id, "reason": str(exc)},
                )
            )
            continue
        returned_elements = {item.symbol for item in structure.composition.elements}
        if not set(elements) <= returned_elements:
            diagnostics.append(
                Diagnostic(
                    "MATERIALS_PROJECT_CHEMISTRY_FILTER_MISMATCH",
                    Severity.WARNING,
                    "A returned structure omitted at least one required element.",
                    {
                        "material_id": external_id,
                        "required_elements": list(elements),
                        "returned_elements": sorted(returned_elements),
                    },
                )
            )
            continue
        digest = structure_hash(structure)
        if digest in seen_structures:
            continue
        seen_structures.add(digest)
        record_id = "mp-" + hashlib.sha256(external_id.encode("utf-8")).hexdigest()[:16]
        formula = str(
            _document_value(
                document,
                "formula_pretty",
                structure.composition.reduced_formula,
            )
        )
        reference = StructureReference(
            provider=provider_id,
            record_id=record_id,
            formula=formula,
            elements=tuple(sorted(returned_elements)),
            source_kind=StructureSourceKind.DATABASE,
            source_locator=f"https://materialsproject.org/materials/{external_id}",
            structure_sha256=digest,
            citation="Materials Project; cite the database and primary calculation methods.",
        )
        entries[reference.key] = CatalogEntry(reference, structure)
        energy_above_hull = _document_value(document, "energy_above_hull")
        records.append(
            {
                "record_id": record_id,
                "material_id": external_id,
                "formula": formula,
                "structure_sha256": digest,
                "energy_above_hull_eV_per_atom": (
                    float(energy_above_hull) if energy_above_hull is not None else None
                ),
                "is_stable": (
                    bool(_document_value(document, "is_stable"))
                    if _document_value(document, "is_stable") is not None
                    else None
                ),
            }
        )
    if not entries:
        raise ValueError("Materials Project returned no accepted ordered structures")
    provider = OptimadeStructureProvider(provider_id, entries)
    return MaterialsProjectFetchResult(
        provider=provider,
        report=MaterialsProjectFetchReport(
            provider_id=provider_id,
            required_elements=elements,
            database_version=database_version,
            received_records=received,
            accepted_records=len(entries),
            records=tuple(records),
            diagnostics=tuple(diagnostics),
        ),
    )
