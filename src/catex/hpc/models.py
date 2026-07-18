"""Records emitted by HPC-boundary metadata inspection."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from catex.models import Diagnostic, Severity
from catex.vasp.models import PotcarDatasetMetadata


@dataclass(frozen=True, slots=True)
class PotcarMetadataExtractionReport:
    """Copyright-safe result that never contains POTCAR tabulated data or its full path."""

    source_name: str
    potential_family: str
    source_sha256: str | None
    source_size_bytes: int | None
    datasets: tuple[PotcarDatasetMetadata, ...]
    diagnostics: tuple[Diagnostic, ...]
    authorized_hpc_read: bool
    raw_content_included: bool = False
    writes_performed: bool = False
    schema_version: str = "catex.hpc-potcar-metadata-extraction.v1"

    @property
    def has_errors(self) -> bool:
        return any(item.severity is Severity.ERROR for item in self.diagnostics)

    @property
    def status(self) -> str:
        return "error" if self.has_errors else "metadata_ready"

    @property
    def metadata_document(self) -> dict[str, Any] | None:
        if self.has_errors or not self.datasets:
            return None
        return {
            "schema_version": "catex.potcar-metadata.v1",
            "potential_family": self.potential_family,
            "datasets": [item.to_dict() for item in self.datasets],
        }

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "status": self.status,
            "source_name": self.source_name,
            "source_sha256": self.source_sha256,
            "source_size_bytes": self.source_size_bytes,
            "potential_family": self.potential_family,
            "datasets": [item.to_dict() for item in self.datasets],
            "metadata_document": self.metadata_document,
            "authorized_hpc_read": self.authorized_hpc_read,
            "raw_content_included": self.raw_content_included,
            "writes_performed": self.writes_performed,
            "diagnostics": [item.to_dict() for item in self.diagnostics],
        }
