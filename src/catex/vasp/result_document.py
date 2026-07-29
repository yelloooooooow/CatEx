"""Unified, bounded metadata document for common VASP result artifacts."""

from __future__ import annotations

import hashlib
import re
import xml.etree.ElementTree as ET
from contextlib import suppress
from pathlib import Path
from typing import Any

from pymatgen.io.vasp.inputs import Poscar

from catex.vasp.output import parse_vasp_output

SUPPORTED_RESULT_FILES = {
    "OUTCAR",
    "OSZICAR",
    "CONTCAR",
    "vasprun.xml",
    "XDATCAR",
    "CHGCAR",
    "LOCPOT",
    "ELFCAR",
}
_MAX_METADATA_SOURCE_BYTES = 512 * 1024 * 1024
_MAX_STRUCTURE_BYTES = 5 * 1024 * 1024
_GRID = re.compile(r"^\s*(\d+)\s+(\d+)\s+(\d+)\s*$")


class VaspResultDocumentError(ValueError):
    """Raised when a VASP result collection violates the bounded contract."""


def _artifact(path: Path) -> dict[str, Any]:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        while chunk := stream.read(1024 * 1024):
            digest.update(chunk)
    return {
        "filename": path.name,
        "size_bytes": path.stat().st_size,
        "sha256": digest.hexdigest(),
    }


def _vasprun_summary(path: Path) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    values: dict[str, float] = {}
    ionic_steps = 0
    diagnostics: list[dict[str, Any]] = []
    try:
        with path.open("rb") as stream:
            prefix = stream.read(4096).upper()
        if b"<!DOCTYPE" in prefix or b"<!ENTITY" in prefix:
            raise VaspResultDocumentError("vasprun.xml DTD and entities are not accepted")
        for _, element in ET.iterparse(path, events=("end",)):
            if element.tag == "calculation":
                ionic_steps += 1
            if element.tag == "i":
                name = element.attrib.get("name", "")
                if name in {"e_fr_energy", "e_0_energy", "efermi"} and element.text:
                    with suppress(ValueError):
                        values[name] = float(element.text.strip())
            element.clear()
    except (ET.ParseError, OSError, VaspResultDocumentError) as error:
        diagnostics.append(
            {
                "code": "VASPRUN_XML_PARSE_FAILED",
                "severity": "warning",
                "message": f"vasprun.xml metadata could not be parsed ({type(error).__name__}).",
            }
        )
    return (
        {
            "filename": path.name,
            "ionic_step_count": ionic_steps,
            "free_energy_eV": values.get("e_fr_energy"),
            "sigma_zero_energy_eV": values.get("e_0_energy"),
            "fermi_energy_eV": values.get("efermi"),
            "full_xml_retained_in_document": False,
        },
        diagnostics,
    )


def _xdatcar_summary(path: Path) -> dict[str, Any]:
    frame_count = 0
    first_marker: str | None = None
    with path.open("r", encoding="utf-8", errors="replace") as stream:
        for line in stream:
            normalized = line.strip()
            if normalized.lower().startswith(("direct configuration", "cartesian configuration")):
                frame_count += 1
                first_marker = first_marker or normalized
    return {
        "filename": path.name,
        "frame_count": frame_count,
        "coordinate_marker": first_marker,
        "coordinates_included_in_document": False,
    }


def _grid_summary(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8", errors="replace") as stream:
        header = stream.read(2 * 1024 * 1024)
    lines = header.splitlines()
    dimensions: tuple[int, int, int] | None = None
    for line in lines[8:]:
        match = _GRID.fullmatch(line)
        if match is None:
            continue
        candidate = tuple(int(match.group(index)) for index in range(1, 4))
        if all(value > 1 for value in candidate):
            dimensions = candidate
            break
    return {
        "filename": path.name,
        "kind": path.name.upper(),
        "grid_dimensions": list(dimensions) if dimensions else None,
        "grid_point_count": (dimensions[0] * dimensions[1] * dimensions[2] if dimensions else None),
        "values_included_in_document": False,
    }


def _structure_summary(path: Path) -> dict[str, Any]:
    structure = Poscar.from_file(path, check_for_potcar=False).structure
    species_counts: dict[str, int] = {}
    for site in structure:
        symbol = site.specie.symbol
        species_counts[symbol] = species_counts.get(symbol, 0) + 1
    return {
        "source": path.name,
        "record": {
            "canonical_hash": hashlib.sha256(path.read_bytes()).hexdigest(),
            "formula": structure.composition.formula,
            "reduced_formula": structure.composition.reduced_formula,
            "num_sites": len(structure),
            "species_counts": list(species_counts.items()),
            "lattice_lengths": list(structure.lattice.abc),
            "lattice_angles": list(structure.lattice.angles),
            "volume_angstrom3": structure.volume,
        },
        "viewer": {
            "schema_version": "catex.structure-viewer.v1",
            "lattice": structure.lattice.matrix.tolist(),
            "species": [site.specie.symbol for site in structure],
            "fractional_coordinates": structure.frac_coords.tolist(),
            "cartesian_coordinates": structure.cart_coords.tolist(),
            "periodic": [True, True, True],
        },
    }


def build_vasp_result_document(directory: str | Path) -> dict[str, Any]:
    """Build one portable result summary without retaining large raw arrays."""

    root = Path(directory)
    if not root.is_dir():
        raise VaspResultDocumentError("VASP result directory does not exist")
    paths = {
        path.name: path
        for path in root.iterdir()
        if path.is_file() and path.name in SUPPORTED_RESULT_FILES
    }
    if not paths:
        raise VaspResultDocumentError("no supported VASP result artifact was found")
    total_size = sum(path.stat().st_size for path in paths.values())
    if total_size > _MAX_METADATA_SOURCE_BYTES:
        raise VaspResultDocumentError("VASP result collection exceeds the 512 MiB limit")

    diagnostics: list[dict[str, Any]] = []
    output = None
    if "OUTCAR" in paths or "OSZICAR" in paths:
        output = parse_vasp_output(root).to_dict()

    final_structure = None
    contcar = paths.get("CONTCAR")
    if contcar is not None:
        if contcar.stat().st_size <= _MAX_STRUCTURE_BYTES:
            try:
                final_structure = _structure_summary(contcar)
            except (OSError, ValueError) as error:
                diagnostics.append(
                    {
                        "code": "CONTCAR_PARSE_FAILED",
                        "severity": "warning",
                        "message": (
                            f"CONTCAR structure could not be parsed ({type(error).__name__})."
                        ),
                    }
                )
        else:
            diagnostics.append(
                {
                    "code": "CONTCAR_TOO_LARGE",
                    "severity": "warning",
                    "message": "CONTCAR exceeds the bounded structure inspection limit.",
                }
            )

    vasprun = None
    if "vasprun.xml" in paths:
        vasprun, xml_diagnostics = _vasprun_summary(paths["vasprun.xml"])
        diagnostics.extend(xml_diagnostics)

    trajectory = _xdatcar_summary(paths["XDATCAR"]) if "XDATCAR" in paths else None
    volumetric = [
        _grid_summary(paths[name]) for name in ("CHGCAR", "LOCPOT", "ELFCAR") if name in paths
    ]
    energy = output.get("energy") if output else None
    if energy is None and vasprun is not None:
        energy = {
            "free_energy_eV": vasprun["free_energy_eV"],
            "sigma_zero_energy_eV": vasprun["sigma_zero_energy_eV"],
            "source": "vasprun.xml",
        }

    return {
        "schema_version": "catex.vasp-result-document.v1",
        "directory": root.name,
        "artifact_inventory": [_artifact(paths[name]) for name in sorted(paths)],
        "energy": energy,
        "vasp_output": output,
        "vasprun": vasprun,
        "final_structure": final_structure,
        "trajectory": trajectory,
        "volumetric": volumetric,
        "diagnostics": diagnostics,
        "raw_volumetric_values_included": False,
        "raw_trajectory_coordinates_included": False,
    }
