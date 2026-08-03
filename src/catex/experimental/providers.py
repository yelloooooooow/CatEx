"""Traceable local structure providers and provider registry."""

from __future__ import annotations

import hashlib
import json
import urllib.error
import urllib.parse
import urllib.request
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from pathlib import Path
from types import MappingProxyType
from typing import Any, Protocol

from pymatgen.core import Structure

from catex.experimental.models import StructureReference, StructureSourceKind
from catex.hashing import artifact_record, structure_hash
from catex.models import ArtifactRecord, Diagnostic, Severity

_CATALOG_KEYS = {"schema_version", "provider", "entries"}
_ENTRY_KEYS = {
    "record_id",
    "path",
    "source_kind",
    "source_locator",
    "license",
    "citation",
}


class StructureProvider(Protocol):
    """Minimal provider interface consumed by the inference core."""

    @property
    def provider_id(self) -> str: ...

    def references(self) -> tuple[StructureReference, ...]: ...

    def get(self, reference_key: str) -> Structure: ...


class JSONHTTPTransport(Protocol):
    """Read-only JSON transport used by remote structure providers."""

    def get_json(self, url: str) -> Mapping[str, Any]: ...


@dataclass(frozen=True, slots=True)
class CatalogEntry:
    """Runtime pair of an immutable reference and parsed structure."""

    reference: StructureReference
    structure: Structure


class InMemoryStructureProvider:
    """Deterministic provider useful for tests and programmatic integrations."""

    def __init__(
        self,
        provider_id: str,
        entries: Iterable[tuple[str, Structure, StructureSourceKind]],
    ) -> None:
        normalized: dict[str, CatalogEntry] = {}
        for record_id, source, source_kind in entries:
            structure = source.copy()
            elements = tuple(sorted(item.symbol for item in structure.composition.elements))
            reference = StructureReference(
                provider=provider_id,
                record_id=record_id,
                formula=structure.composition.reduced_formula,
                elements=elements,
                source_kind=source_kind,
                source_locator=f"memory:{record_id}",
                structure_sha256=structure_hash(structure),
            )
            normalized[reference.key] = CatalogEntry(reference, structure)
        if not normalized:
            raise ValueError("structure provider must contain at least one entry")
        self._provider_id = provider_id
        self._entries = MappingProxyType(dict(sorted(normalized.items())))

    @property
    def provider_id(self) -> str:
        return self._provider_id

    def references(self) -> tuple[StructureReference, ...]:
        return tuple(item.reference for item in self._entries.values())

    def get(self, reference_key: str) -> Structure:
        try:
            entry = self._entries[reference_key]
        except KeyError as exc:
            raise ValueError(f"unknown structure reference: {reference_key}") from exc
        return entry.structure.copy()


class LocalStructureCatalog:
    """Read-only catalog whose structure paths are confined to one local root."""

    def __init__(
        self,
        provider_id: str,
        entries: Mapping[str, CatalogEntry],
        *,
        catalog_path: Path,
    ) -> None:
        if not entries:
            raise ValueError("local structure catalog must contain at least one valid entry")
        self._provider_id = provider_id
        self._entries = MappingProxyType(dict(sorted(entries.items())))
        self.catalog_path = catalog_path

    @property
    def provider_id(self) -> str:
        return self._provider_id

    def references(self) -> tuple[StructureReference, ...]:
        return tuple(item.reference for item in self._entries.values())

    def get(self, reference_key: str) -> Structure:
        try:
            entry = self._entries[reference_key]
        except KeyError as exc:
            raise ValueError(f"unknown structure reference: {reference_key}") from exc
        return entry.structure.copy()


class _URLJSONTransport:
    """Small HTTPS-only transport with bounded response size."""

    def __init__(self, *, timeout_seconds: float = 30.0, maximum_bytes: int = 20_000_000):
        if not 1 <= timeout_seconds <= 120:
            raise ValueError("timeout_seconds must be between 1 and 120")
        if not 1_000 <= maximum_bytes <= 100_000_000:
            raise ValueError("maximum_bytes must be between 1000 and 100000000")
        self.timeout_seconds = timeout_seconds
        self.maximum_bytes = maximum_bytes

    def get_json(self, url: str) -> Mapping[str, Any]:
        parsed = urllib.parse.urlparse(url)
        if parsed.scheme != "https" or not parsed.netloc:
            raise ValueError("remote structure URL must use HTTPS")
        request = urllib.request.Request(
            url,
            headers={"Accept": "application/vnd.api+json, application/json"},
            method="GET",
        )
        try:
            with urllib.request.urlopen(request, timeout=self.timeout_seconds) as response:
                final_url = urllib.parse.urlparse(response.geturl())
                if final_url.scheme != "https" or final_url.netloc != parsed.netloc:
                    raise ValueError(
                        "remote structure provider redirect cannot leave the configured HTTPS host"
                    )
                raw = response.read(self.maximum_bytes + 1)
        except urllib.error.HTTPError as exc:
            raise ValueError(f"remote structure provider returned HTTP {exc.code}") from exc
        except urllib.error.URLError as exc:
            raise ValueError("remote structure provider request failed") from exc
        if len(raw) > self.maximum_bytes:
            raise ValueError("remote structure provider response exceeded the size limit")
        try:
            payload = json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise ValueError("remote structure provider returned invalid JSON") from exc
        if not isinstance(payload, Mapping):
            raise ValueError("remote structure provider response must be a JSON object")
        return payload


class OptimadeStructureProvider:
    """In-memory structures retrieved from an explicit OPTIMADE endpoint."""

    def __init__(self, provider_id: str, entries: Mapping[str, CatalogEntry]) -> None:
        if not entries:
            raise ValueError("OPTIMADE provider returned no accepted ordered structures")
        self._provider_id = provider_id
        self._entries = MappingProxyType(dict(sorted(entries.items())))

    @property
    def provider_id(self) -> str:
        return self._provider_id

    def references(self) -> tuple[StructureReference, ...]:
        return tuple(item.reference for item in self._entries.values())

    def get(self, reference_key: str) -> Structure:
        try:
            return self._entries[reference_key].structure.copy()
        except KeyError as exc:
            raise ValueError(f"unknown structure reference: {reference_key}") from exc


@dataclass(frozen=True, slots=True)
class OptimadeFetchReport:
    """Auditable summary of an explicit read-only OPTIMADE request."""

    provider_id: str
    base_url: str
    required_elements: tuple[str, ...]
    received_records: int
    accepted_records: int
    diagnostics: tuple[Diagnostic, ...]
    network_read_performed: bool = True
    writes_performed: bool = False
    schema_version: str = "catex.optimade-fetch.v1"

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "provider_id": self.provider_id,
            "base_url": self.base_url,
            "required_elements": list(self.required_elements),
            "received_records": self.received_records,
            "accepted_records": self.accepted_records,
            "network_read_performed": self.network_read_performed,
            "writes_performed": self.writes_performed,
            "diagnostics": [item.to_dict() for item in self.diagnostics],
        }


@dataclass(frozen=True, slots=True)
class OptimadeFetchResult:
    """Runtime provider paired with its serializable retrieval report."""

    provider: OptimadeStructureProvider
    report: OptimadeFetchReport


@dataclass(frozen=True, slots=True)
class ProviderCatalogMaterializationReport:
    """New-directory cache of one provider using the local catalog contract."""

    provider_id: str
    destination: str
    catalog: ArtifactRecord
    structures: tuple[ArtifactRecord, ...]
    writes_performed: bool = True
    schema_version: str = "catex.provider-catalog-materialization.v1"

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "provider_id": self.provider_id,
            "destination": self.destination,
            "catalog": self.catalog.to_dict(),
            "structures": [item.to_dict() for item in self.structures],
            "writes_performed": self.writes_performed,
        }


@dataclass(frozen=True, slots=True)
class OptimadeCatalogFetchReport:
    """Combined retrieval and local-cache report for the explicit CLI operation."""

    fetch: OptimadeFetchReport
    materialization: ProviderCatalogMaterializationReport
    schema_version: str = "catex.optimade-catalog-fetch.v1"

    @property
    def diagnostics(self) -> tuple[Diagnostic, ...]:
        return self.fetch.diagnostics

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "status": "materialized",
            "fetch": self.fetch.to_dict(),
            "materialization": self.materialization.to_dict(),
        }


def _optimade_structure(attributes: Mapping[str, Any]) -> Structure:
    dimension_types = attributes.get("dimension_types")
    if dimension_types not in ([1, 1, 1], (1, 1, 1)):
        raise ValueError("only three-dimensional periodic OPTIMADE structures are supported")
    structure_features = attributes.get("structure_features", [])
    if structure_features not in ([], ()):
        raise ValueError("OPTIMADE structures with special structure features are unsupported")
    lattice = attributes.get("lattice_vectors")
    positions = attributes.get("cartesian_site_positions")
    species_at_sites = attributes.get("species_at_sites")
    species_definitions = attributes.get("species")
    if not isinstance(lattice, list) or len(lattice) != 3:
        raise ValueError("OPTIMADE lattice_vectors are missing or invalid")
    if not isinstance(positions, list) or not isinstance(species_at_sites, list):
        raise ValueError("OPTIMADE site positions or species_at_sites are missing")
    if len(positions) != len(species_at_sites) or not positions:
        raise ValueError("OPTIMADE site arrays must be non-empty and aligned")
    if not isinstance(species_definitions, list):
        raise ValueError("OPTIMADE species definitions are missing")
    definitions: dict[str, str] = {}
    for raw in species_definitions:
        if not isinstance(raw, Mapping):
            raise ValueError("OPTIMADE species definition must be an object")
        name = raw.get("name")
        symbols = raw.get("chemical_symbols")
        concentrations = raw.get("concentration")
        if (
            not isinstance(name, str)
            or not isinstance(symbols, list)
            or len(symbols) != 1
            or not isinstance(concentrations, list)
            or len(concentrations) != 1
            or float(concentrations[0]) != 1.0
        ):
            raise ValueError("disordered or vacancy OPTIMADE species are not supported in v1")
        definitions[name] = str(symbols[0])
    try:
        site_symbols = [definitions[str(name)] for name in species_at_sites]
    except KeyError as exc:
        raise ValueError("OPTIMADE species_at_sites references an unknown species") from exc
    try:
        return Structure(
            lattice,
            site_symbols,
            positions,
            coords_are_cartesian=True,
        )
    except Exception as exc:
        raise ValueError("OPTIMADE structure could not be constructed") from exc


def _next_optimade_url(
    payload: Mapping[str, Any],
    *,
    current_url: str,
    base_netloc: str,
) -> str | None:
    links = payload.get("links")
    if not isinstance(links, Mapping):
        return None
    raw_next = links.get("next")
    if isinstance(raw_next, Mapping):
        raw_next = raw_next.get("href")
    if raw_next is None:
        return None
    if not isinstance(raw_next, str) or not raw_next.strip():
        raise ValueError("OPTIMADE next link must be a non-empty URL")
    next_url = urllib.parse.urljoin(current_url, raw_next)
    parsed = urllib.parse.urlparse(next_url)
    if parsed.scheme != "https" or parsed.netloc != base_netloc:
        raise ValueError("OPTIMADE pagination cannot leave the configured HTTPS host")
    return next_url


def fetch_optimade_structures(
    *,
    base_url: str,
    provider_id: str,
    required_elements: Iterable[str],
    maximum_results: int = 100,
    maximum_pages: int = 5,
    license: str = "",
    citation: str = "",
    transport: JSONHTTPTransport | None = None,
) -> OptimadeFetchResult:
    """Fetch ordered 3D structures from one explicitly configured OPTIMADE API."""

    from pymatgen.core import Element

    parsed_base = urllib.parse.urlparse(base_url)
    if parsed_base.scheme != "https" or not parsed_base.netloc:
        raise ValueError("OPTIMADE base_url must use HTTPS")
    if parsed_base.query or parsed_base.fragment or parsed_base.username is not None:
        raise ValueError("OPTIMADE base_url must not contain credentials, a query, or a fragment")
    if not 1 <= maximum_results <= 1000:
        raise ValueError("maximum_results must be between 1 and 1000")
    if not 1 <= maximum_pages <= 20:
        raise ValueError("maximum_pages must be between 1 and 20")
    elements = tuple(sorted({Element(item).symbol for item in required_elements}))
    if not elements:
        raise ValueError("required_elements must not be empty")
    filter_expression = "elements HAS ALL " + ", ".join(json.dumps(item) for item in elements)
    query = urllib.parse.urlencode(
        {
            "filter": filter_expression,
            "page_limit": min(maximum_results, 100),
            "response_fields": (
                "chemical_formula_reduced,elements,lattice_vectors,"
                "cartesian_site_positions,species_at_sites,species,dimension_types,"
                "structure_features"
            ),
        }
    )
    configured_root = base_url.rstrip("/")
    api_root = configured_root if configured_root.endswith("/v1") else configured_root + "/v1"
    endpoint = api_root + "/structures?" + query
    active_transport = transport or _URLJSONTransport()
    entries: dict[str, CatalogEntry] = {}
    diagnostics: list[Diagnostic] = []
    received = 0
    current_url: str | None = endpoint
    for _page in range(maximum_pages):
        if current_url is None or len(entries) >= maximum_results:
            break
        payload = active_transport.get_json(current_url)
        data = payload.get("data")
        if not isinstance(data, list):
            raise ValueError("OPTIMADE response data must be an array")
        for raw_record in data:
            if len(entries) >= maximum_results:
                break
            received += 1
            if not isinstance(raw_record, Mapping):
                diagnostics.append(
                    Diagnostic(
                        "OPTIMADE_RECORD_SKIPPED",
                        Severity.WARNING,
                        "A non-object OPTIMADE record was skipped.",
                        {"record_index": received - 1},
                    )
                )
                continue
            external_id = str(raw_record.get("id", ""))
            attributes = raw_record.get("attributes")
            if not external_id or not isinstance(attributes, Mapping):
                diagnostics.append(
                    Diagnostic(
                        "OPTIMADE_RECORD_SKIPPED",
                        Severity.WARNING,
                        "An OPTIMADE record without ID or attributes was skipped.",
                        {"record_index": received - 1},
                    )
                )
                continue
            try:
                structure = _optimade_structure(attributes)
            except ValueError as exc:
                diagnostics.append(
                    Diagnostic(
                        "OPTIMADE_STRUCTURE_UNSUPPORTED",
                        Severity.WARNING,
                        "An OPTIMADE structure was skipped by the v1 ordered-3D contract.",
                        {"external_id": external_id, "reason": str(exc)},
                    )
                )
                continue
            returned_elements = {item.symbol for item in structure.composition.elements}
            if not set(elements) <= returned_elements:
                diagnostics.append(
                    Diagnostic(
                        "OPTIMADE_CHEMISTRY_FILTER_MISMATCH",
                        Severity.WARNING,
                        "An OPTIMADE record that omitted required elements was skipped.",
                        {
                            "external_id": external_id,
                            "required_elements": list(elements),
                            "returned_elements": sorted(returned_elements),
                        },
                    )
                )
                continue
            digest = structure_hash(structure)
            if any(item.reference.structure_sha256 == digest for item in entries.values()):
                continue
            record_id = "opt-" + hashlib.sha256(external_id.encode("utf-8")).hexdigest()[:16]
            reference = StructureReference(
                provider=provider_id,
                record_id=record_id,
                formula=structure.composition.reduced_formula,
                elements=tuple(sorted(item.symbol for item in structure.composition.elements)),
                source_kind=StructureSourceKind.DATABASE,
                source_locator=(
                    f"{api_root}/structures/{urllib.parse.quote(external_id, safe='')}"
                ),
                structure_sha256=digest,
                license=license,
                citation=citation,
            )
            entries[reference.key] = CatalogEntry(reference, structure)
        current_url = _next_optimade_url(
            payload,
            current_url=current_url,
            base_netloc=parsed_base.netloc,
        )
    provider = OptimadeStructureProvider(provider_id, entries)
    report = OptimadeFetchReport(
        provider_id=provider_id,
        base_url=configured_root,
        required_elements=elements,
        received_records=received,
        accepted_records=len(entries),
        diagnostics=tuple(diagnostics),
    )
    return OptimadeFetchResult(provider, report)


def materialize_provider_catalog(
    provider: StructureProvider,
    destination: str | Path,
) -> ProviderCatalogMaterializationReport:
    """Cache a provider as CIF files and a loadable catalog in one new directory."""

    target = Path(destination).resolve()
    if target.exists():
        raise ValueError("provider catalog destination must not already exist")
    if not target.parent.is_dir():
        raise ValueError("provider catalog destination parent must exist")
    target.mkdir()
    structures_directory = target / "structures"
    structures_directory.mkdir()
    artifacts: list[ArtifactRecord] = []
    entries: list[dict[str, Any]] = []
    for index, reference in enumerate(provider.references(), start=1):
        filename = f"{index:04d}-{reference.record_id}.cif"
        path = structures_directory / filename
        provider.get(reference.key).to(filename=path, fmt="cif")
        artifacts.append(artifact_record(path))
        entries.append(
            {
                "record_id": reference.record_id,
                "path": f"structures/{filename}",
                "source_kind": reference.source_kind.value,
                "source_locator": reference.source_locator,
                "license": reference.license,
                "citation": reference.citation,
            }
        )
    catalog_path = target / "catalog.json"
    catalog_path.write_text(
        json.dumps(
            {
                "schema_version": "catex.structure-catalog.v1",
                "provider": provider.provider_id,
                "entries": entries,
            },
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )
    return ProviderCatalogMaterializationReport(
        provider_id=provider.provider_id,
        destination=str(target),
        catalog=artifact_record(catalog_path),
        structures=tuple(artifacts),
    )


def load_local_structure_catalog(path: str | Path) -> LocalStructureCatalog:
    """Load a strict path-confined JSON catalog and parse all structures."""

    source = Path(path).resolve()
    if not source.is_file():
        raise ValueError("catalog path must be an existing regular file")
    try:
        payload = json.loads(source.read_text(encoding="utf-8-sig"))
    except json.JSONDecodeError as exc:
        raise ValueError("structure catalog is not valid JSON") from exc
    if not isinstance(payload, Mapping):
        raise ValueError("structure catalog must be a JSON object")
    unknown = sorted(set(payload) - _CATALOG_KEYS)
    if unknown:
        raise ValueError(f"structure catalog contains unknown fields: {', '.join(unknown)}")
    if payload.get("schema_version", "catex.structure-catalog.v1") != (
        "catex.structure-catalog.v1"
    ):
        raise ValueError("unsupported structure catalog schema_version")
    provider_id = str(payload.get("provider", "local"))
    raw_entries = payload.get("entries")
    if not isinstance(raw_entries, list):
        raise ValueError("catalog entries must be a JSON array")
    root = source.parent
    entries: dict[str, CatalogEntry] = {}
    for index, raw_item in enumerate(raw_entries):
        if not isinstance(raw_item, Mapping):
            raise ValueError(f"catalog entry {index} must be a JSON object")
        unknown = sorted(set(raw_item) - _ENTRY_KEYS)
        if unknown:
            raise ValueError(f"catalog entry {index} contains unknown fields: {', '.join(unknown)}")
        structure_path = (root / str(raw_item["path"])).resolve()
        if not structure_path.is_relative_to(root):
            raise ValueError("catalog structure path must remain inside the catalog root")
        if not structure_path.is_file():
            raise ValueError(f"catalog structure does not exist: {structure_path.name}")
        try:
            structure = Structure.from_file(structure_path)
        except Exception as exc:
            raise ValueError(
                f"catalog structure could not be parsed: {structure_path.name}"
            ) from exc
        artifact = artifact_record(structure_path)
        reference = StructureReference(
            provider=provider_id,
            record_id=str(raw_item["record_id"]),
            formula=structure.composition.reduced_formula,
            elements=tuple(sorted(item.symbol for item in structure.composition.elements)),
            source_kind=StructureSourceKind(str(raw_item.get("source_kind", "user_supplied"))),
            source_locator=str(raw_item.get("source_locator", f"catalog:{structure_path.name}")),
            structure_sha256=structure_hash(structure),
            artifact_sha256=artifact.sha256,
            license=str(raw_item.get("license", "")),
            citation=str(raw_item.get("citation", "")),
        )
        if reference.key in entries:
            raise ValueError(f"duplicate structure reference: {reference.key}")
        entries[reference.key] = CatalogEntry(reference, structure)
    return LocalStructureCatalog(provider_id, entries, catalog_path=source)


class ProviderRegistry:
    """Read-only union of independently versioned structure providers."""

    def __init__(self, providers: Iterable[StructureProvider]) -> None:
        normalized: dict[str, StructureProvider] = {}
        keys: set[str] = set()
        for provider in providers:
            if provider.provider_id in normalized:
                raise ValueError(f"duplicate provider ID: {provider.provider_id}")
            references = provider.references()
            overlap = keys & {item.key for item in references}
            if overlap:
                raise ValueError(f"duplicate structure reference: {sorted(overlap)[0]}")
            keys.update(item.key for item in references)
            normalized[provider.provider_id] = provider
        if not normalized:
            raise ValueError("provider registry must contain at least one provider")
        self._providers = MappingProxyType(dict(sorted(normalized.items())))
        self._references = MappingProxyType(
            {
                item.key: item
                for provider in self._providers.values()
                for item in provider.references()
            }
        )

    def references(self) -> tuple[StructureReference, ...]:
        return tuple(self._references[key] for key in sorted(self._references))

    def get_reference(self, reference_key: str) -> StructureReference:
        try:
            return self._references[reference_key]
        except KeyError as exc:
            raise ValueError(f"unknown structure reference: {reference_key}") from exc

    def get_structure(self, reference_key: str) -> Structure:
        reference = self.get_reference(reference_key)
        return self._providers[reference.provider].get(reference_key)

    def search(
        self,
        *,
        allowed_elements: Iterable[str] = (),
        excluded_elements: Iterable[str] = (),
    ) -> tuple[StructureReference, ...]:
        """Return references compatible with explicit elemental presence constraints."""

        allowed = set(allowed_elements)
        excluded = set(excluded_elements)
        matches = []
        for reference in self.references():
            elements = set(reference.elements)
            if excluded & elements:
                continue
            if allowed and not elements <= allowed:
                continue
            matches.append(reference)
        return tuple(matches)
