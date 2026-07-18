"""Bounded application services for uploads and synthetic demonstrations."""

from __future__ import annotations

import hashlib
import tempfile
from pathlib import Path
from typing import Any

from pymatgen.core import Structure
from pymatgen.io.vasp.inputs import Poscar

from catex.structures import inspect_path
from catex.vasp.output import parse_vasp_output

MAX_STRUCTURE_UPLOAD_BYTES = 5 * 1024 * 1024
_ALLOWED_STRUCTURE_SUFFIXES = {".cif", ".poscar", ".vasp"}
_ALLOWED_STRUCTURE_NAMES = {"POSCAR", "CONTCAR"}


class UploadRejected(ValueError):
    """Raised when an upload violates the POC boundary."""


def _validate_upload(filename: str, content: bytes) -> str:
    if not filename or filename in {".", ".."}:
        raise UploadRejected("A non-empty filename is required.")
    if "/" in filename or "\\" in filename or any(ord(char) < 32 for char in filename):
        raise UploadRejected("The filename must not contain paths or control characters.")
    if not content:
        raise UploadRejected("The uploaded structure is empty.")
    if len(content) > MAX_STRUCTURE_UPLOAD_BYTES:
        raise UploadRejected("The uploaded structure exceeds the 5 MiB POC limit.")
    if filename.upper() not in _ALLOWED_STRUCTURE_NAMES:
        suffix = Path(filename).suffix.lower()
        if suffix not in _ALLOWED_STRUCTURE_SUFFIXES:
            raise UploadRejected("Only POSCAR, CONTCAR, .poscar, .vasp, and .cif are accepted.")
    return filename


def _viewer_payload(structure: Structure) -> dict[str, Any]:
    return {
        "schema_version": "catex.structure-viewer.v1",
        "lattice": [[float(value) for value in row] for row in structure.lattice.matrix],
        "species": [site.species_string for site in structure],
        "fractional_coordinates": [
            [float(value) for value in site.frac_coords] for site in structure
        ],
        "cartesian_coordinates": [[float(value) for value in site.coords] for site in structure],
        "periodic": [True, True, True],
    }


def inspect_structure_upload(filename: str, content: bytes) -> dict[str, Any]:
    """Inspect one bounded upload in an ephemeral directory without retaining it."""

    safe_name = _validate_upload(filename, content)
    digest = hashlib.sha256(content).hexdigest()
    with tempfile.TemporaryDirectory(prefix="catex-web-upload-") as temporary:
        path = Path(temporary) / safe_name
        with path.open("xb") as stream:
            stream.write(content)
        report = inspect_path(path)
        viewer: dict[str, Any] | None = None
        if report.record is not None:
            viewer = _viewer_payload(Structure.from_file(path))
    return {
        "schema_version": "catex.structure-upload-inspection.v1",
        "retained": False,
        "source": {"filename": safe_name, "size_bytes": len(content), "sha256": digest},
        "inspection": report.to_dict(),
        "viewer": viewer,
    }


def convert_cif_upload_to_poscar(filename: str, content: bytes) -> dict[str, Any]:
    """Convert one bounded CIF upload to a deterministic VASP 5 POSCAR in memory."""

    safe_name = _validate_upload(filename, content)
    if Path(safe_name).suffix.lower() != ".cif":
        raise UploadRejected("Only .cif files can be converted by this endpoint.")
    try:
        text = content.decode("utf-8-sig")
        structure = Structure.from_str(text, fmt="cif")
    except (UnicodeDecodeError, ValueError, OSError) as exc:
        raise UploadRejected("The CIF could not be parsed into a periodic structure.") from exc
    poscar_text = Poscar(structure, comment=Path(safe_name).stem).get_str()
    inspection = inspect_structure_upload("POSCAR", poscar_text.encode("utf-8"))
    return {
        "schema_version": "catex.cif-to-poscar.v1",
        "source_filename": safe_name,
        "output_filename": "POSCAR",
        "poscar_text": poscar_text,
        "inspection": inspection,
        "writes_performed": False,
    }


def constrain_poscar(
    content: bytes,
    *,
    strategy: str,
    mobile_indices_1based: tuple[int, ...] = (),
    bottom_layer_count: int = 0,
    layer_tolerance_angstrom: float = 0.5,
) -> dict[str, Any]:
    """Add VASP selective-dynamics flags without running VASPKIT or mutating a file."""

    _validate_upload("POSCAR", content)
    try:
        poscar = Poscar.from_str(content.decode("utf-8-sig"))
    except (UnicodeDecodeError, ValueError, OSError) as exc:
        raise UploadRejected("The POSCAR could not be parsed.") from exc
    site_count = len(poscar.structure)
    if strategy not in {"none", "adsorbate_indices", "bottom_layers"}:
        raise UploadRejected("Unsupported selective-dynamics strategy.")
    if not 0.01 <= layer_tolerance_angstrom <= 5.0:
        raise UploadRejected("Layer tolerance must be between 0.01 and 5.0 angstrom.")

    fixed: set[int] = set()
    if strategy == "adsorbate_indices":
        mobile = set(mobile_indices_1based)
        if not mobile or min(mobile) < 1 or max(mobile) > site_count:
            raise UploadRejected("Mobile atom indices must be within the POSCAR site range.")
        fixed = set(range(1, site_count + 1)) - mobile
    elif strategy == "bottom_layers":
        if bottom_layer_count < 1:
            raise UploadRejected("At least one bottom layer must be fixed.")
        sites = enumerate(poscar.structure, start=1)
        indexed_z = sorted(
            ((index, float(site.coords[2])) for index, site in sites),
            key=lambda item: item[1],
        )
        layers: list[list[int]] = []
        layer_reference: float | None = None
        for index, z_value in indexed_z:
            if layer_reference is None or z_value - layer_reference > layer_tolerance_angstrom:
                layers.append([index])
                layer_reference = z_value
            else:
                layers[-1].append(index)
        if bottom_layer_count >= len(layers):
            raise UploadRejected("The fixed-layer count must leave at least one mobile layer.")
        fixed = {index for layer in layers[:bottom_layer_count] for index in layer}

    flags = [[index not in fixed] * 3 for index in range(1, site_count + 1)]
    constrained = Poscar(
        poscar.structure,
        comment=poscar.comment,
        selective_dynamics=flags,
    ).get_str()
    mobile = tuple(index for index in range(1, site_count + 1) if index not in fixed)
    return {
        "schema_version": "catex.selective-dynamics.v1",
        "strategy": strategy,
        "poscar_text": constrained,
        "site_count": site_count,
        "fixed_indices_1based": sorted(fixed),
        "mobile_indices_1based": list(mobile),
        "fixed_count": len(fixed),
        "mobile_count": len(mobile),
        "writes_performed": False,
    }


_DEMO_OUTCAR = "\n".join(
    (
        " vasp.5.4.4.18Apr17-6-g9f103f2a35",
        " NIONS =      2",
        " NELM   =     60",
        " NSW    =     10",
        " IBRION =      2",
        " --------------------------------------- Iteration    1(   1) "
        " ---------------------------------------",
        " aborting loop because EDIFF is reached",
        "  free  energy   TOTEN  =       -10.00000000 eV",
        "  energy  without entropy=      -9.99500000  energy(sigma->0) =      -9.99750000",
        " --------------------------------------- Iteration    2(   1) "
        " ---------------------------------------",
        " aborting loop because EDIFF is reached",
        "  free  energy   TOTEN  =       -10.25000000 eV",
        "  energy  without entropy=     -10.24000000  energy(sigma->0) =     -10.24500000",
        " POSITION                                       TOTAL-FORCE (eV/Angst)",
        " -----------------------------------------------------------------------------------",
        "  0.010000  0.000000  0.000000   0.020000  0.030000  0.000000",
        "  0.990000  1.000000  1.000000  -0.020000 -0.030000  0.000000",
        " -----------------------------------------------------------------------------------",
        " reached required accuracy - stopping structural energy minimisation",
        " General timing and accounting informations for this job:",
        "",
    )
)

_DEMO_OSZICAR = """ DAV:   1    -0.100000000000E+02   -0.10000E+02   -0.10000E+00   16   0.100E+00
   1 F= -.10000000E+02 E0= -.99975000E+01  d E =-.100000E+02  mag= 2.1000
 DAV:   1    -0.102500000000E+02   -0.25000E+00   -0.10000E-02   16   0.100E-04
   2 F= -.10250000E+02 E0= -.10245000E+02  d E =-.250000E+00  mag= 2.0000
"""


def parse_demo_vasp_output() -> dict[str, Any]:
    """Parse a packaged synthetic VASP result; never run VASP or contact a scheduler."""

    with tempfile.TemporaryDirectory(prefix="catex-web-demo-") as temporary:
        directory = Path(temporary)
        (directory / "OUTCAR").write_text(_DEMO_OUTCAR, encoding="utf-8", newline="\n")
        (directory / "OSZICAR").write_text(_DEMO_OSZICAR, encoding="utf-8", newline="\n")
        payload = parse_vasp_output(directory).to_dict()
    payload["directory"] = "synthetic-demo"
    for artifact in payload["artifacts"]:
        artifact["path"] = Path(artifact["path"]).name
    payload["demo"] = {
        "synthetic": True,
        "scientific_result_eligible": False,
        "commands_executed": False,
        "hpc_contacted": False,
    }
    return payload
