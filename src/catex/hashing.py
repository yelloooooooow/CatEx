"""Deterministic content hashing for artifacts and parsed structures."""

from __future__ import annotations

import hashlib
import json
import math
from pathlib import Path
from typing import Any

import numpy as np
from pymatgen.core import Structure

from catex.models import ArtifactRecord


def artifact_record(path: str | Path) -> ArtifactRecord:
    """Hash a file without loading the entire artifact into memory."""

    source = Path(path)
    digest = hashlib.sha256()
    with source.open("rb") as stream:
        while chunk := stream.read(1024 * 1024):
            digest.update(chunk)
    return ArtifactRecord(
        path=str(source),
        sha256=digest.hexdigest(),
        size_bytes=source.stat().st_size,
    )


def _rounded(value: float, decimals: int) -> float:
    result = round(float(value), decimals)
    return 0.0 if result == 0 else result


def _site_species(site: Any, decimals: int) -> list[list[str | float]]:
    species = [
        [str(specie), _rounded(occupancy, decimals)] for specie, occupancy in site.species.items()
    ]
    return sorted(species, key=lambda item: str(item[0]))


def canonical_structure_payload(structure: Structure, *, decimals: int = 8) -> dict[str, Any]:
    """Return an order-independent, cell-wrapped structure representation.

    The payload is intentionally not invariant to a global origin shift or a
    crystallographic cell change. Scientific equivalence is evaluated by the
    periodic matcher in :mod:`catex.structures`, not by comparing this digest.
    """

    lattice = np.asarray(structure.lattice.matrix, dtype=float)
    fractional = np.asarray(structure.frac_coords, dtype=float)
    if not np.isfinite(lattice).all() or not np.isfinite(fractional).all():
        raise ValueError("structure contains non-finite lattice or fractional coordinates")

    sites: list[dict[str, Any]] = []
    for site, coords in zip(structure, fractional, strict=True):
        wrapped = np.mod(coords, 1.0)
        wrapped[np.isclose(wrapped, 1.0, atol=10 ** (-(decimals + 1)))] = 0.0
        sites.append(
            {
                "species": _site_species(site, decimals),
                "fractional_coordinates": [_rounded(value, decimals) for value in wrapped],
            }
        )

    sites.sort(
        key=lambda item: (
            json.dumps(item["species"], sort_keys=True, separators=(",", ":")),
            tuple(item["fractional_coordinates"]),
        )
    )
    payload = {
        "schema": "catex.canonical-structure.v1",
        "lattice_matrix_angstrom": [
            [_rounded(value, decimals) for value in row] for row in lattice
        ],
        "sites": sites,
    }
    return payload


def structure_hash(structure: Structure, *, decimals: int = 8) -> str:
    """Compute a deterministic SHA256 digest of the canonical payload."""

    if decimals < 0 or not math.isfinite(decimals):
        raise ValueError("decimals must be a non-negative integer")
    payload = canonical_structure_payload(structure, decimals=decimals)
    encoded = json.dumps(
        payload,
        ensure_ascii=False,
        allow_nan=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()
