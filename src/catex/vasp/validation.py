"""Directory-level orchestration for read-only VASP 5.4.4 input validation."""

from __future__ import annotations

import hashlib
from contextlib import suppress
from pathlib import Path

from pymatgen.io.vasp import Kpoints, Poscar

from catex.models import ArtifactRecord, Diagnostic, Severity
from catex.structures import inspect_structure
from catex.vasp.incar import (
    parse_bool,
    parse_float,
    parse_incar_text,
    parse_int,
    validate_incar,
)
from catex.vasp.kpoints import parse_kpoints_text, validate_kpoints
from catex.vasp.models import ValidationMode, VaspInputValidationReport
from catex.vasp.potcar import parse_potcar_metadata, validate_potcar_metadata


def _policy(mode: ValidationMode) -> Severity:
    return Severity.ERROR if mode is ValidationMode.STRICT else Severity.WARNING


def _with_file(diagnostic: Diagnostic, filename: str) -> Diagnostic:
    return Diagnostic(
        diagnostic.code,
        diagnostic.severity,
        diagnostic.message,
        {**diagnostic.context, "input_file": filename},
    )


def _read_text_artifact(
    path: Path,
    *,
    missing_code: str,
) -> tuple[str | None, ArtifactRecord | None, tuple[Diagnostic, ...]]:
    """Read one file once and bind the exact bytes to an artifact digest."""

    if not path.is_file():
        return (
            None,
            None,
            (
                Diagnostic(
                    missing_code,
                    Severity.ERROR,
                    "A required VASP input file is missing.",
                    {"path": str(path)},
                ),
            ),
        )
    try:
        data = path.read_bytes()
    except OSError as exc:
        return (
            None,
            None,
            (
                Diagnostic(
                    "VASP_INPUT_READ_FAILED",
                    Severity.ERROR,
                    "A VASP input artifact could not be read.",
                    {"path": str(path), "exception_type": type(exc).__name__},
                ),
            ),
        )
    artifact = ArtifactRecord(
        path=str(path),
        sha256=hashlib.sha256(data).hexdigest(),
        size_bytes=len(data),
    )
    try:
        text = data.decode("utf-8-sig")
    except UnicodeDecodeError as exc:
        return (
            None,
            artifact,
            (
                Diagnostic(
                    "VASP_INPUT_ENCODING_INVALID",
                    Severity.ERROR,
                    "VASP text inputs must be UTF-8/ASCII compatible.",
                    {"path": str(path), "byte_offset": exc.start},
                ),
            ),
        )
    return text, artifact, ()


def _dipole_diagnostics(
    *,
    incar,
    estimated_vacuum: tuple[float, float, float] | None,
    mode: ValidationMode,
) -> tuple[Diagnostic, ...]:
    diagnostics: list[Diagnostic] = []
    raw_ldipol = incar.value("LDIPOL")
    if raw_ldipol is None:
        return ()
    try:
        enabled = parse_bool(raw_ldipol)
    except ValueError as exc:
        return (
            Diagnostic(
                "INCAR_VALUE_INVALID",
                Severity.ERROR,
                "LDIPOL is not a VASP logical value.",
                {"tag": "LDIPOL", "raw_value": raw_ldipol, "reason": str(exc)},
            ),
        )
    if not enabled:
        return ()
    raw_idipol = incar.value("IDIPOL")
    idipol = None
    if raw_idipol is not None:
        try:
            idipol = parse_int(raw_idipol)
        except ValueError as exc:
            diagnostics.append(
                Diagnostic(
                    "INCAR_VALUE_INVALID",
                    Severity.ERROR,
                    "IDIPOL is not an integer.",
                    {"tag": "IDIPOL", "raw_value": raw_idipol, "reason": str(exc)},
                )
            )
    if idipol is not None and idipol not in {1, 2, 3, 4}:
        diagnostics.append(
            Diagnostic(
                "IDIPOL_INVALID",
                Severity.ERROR,
                "IDIPOL must be 1, 2, 3, or 4.",
                {"idipol": idipol},
            )
        )
    vacuum_axes = (
        tuple(index for index, value in enumerate(estimated_vacuum) if value >= 8.0)
        if estimated_vacuum is not None
        else ()
    )
    if len(vacuum_axes) == 1:
        expected = vacuum_axes[0] + 1
        if idipol is None:
            diagnostics.append(
                Diagnostic(
                    "IDIPOL_MISSING_FOR_SLAB",
                    _policy(mode),
                    "LDIPOL is enabled for a slab-like cell, but IDIPOL is not explicit.",
                    {"expected_idipol": expected},
                )
            )
        elif idipol != expected:
            diagnostics.append(
                Diagnostic(
                    "IDIPOL_VACUUM_AXIS_MISMATCH",
                    _policy(mode),
                    "IDIPOL does not match the detected slab vacuum axis.",
                    {"actual_idipol": idipol, "expected_idipol": expected},
                )
            )
    elif not vacuum_axes:
        diagnostics.append(
            Diagnostic(
                "LDIPOL_WITHOUT_DETECTED_VACUUM",
                Severity.WARNING,
                "LDIPOL is enabled, but no cell axis has at least 8 Å estimated vacuum.",
            )
        )
    else:
        diagnostics.append(
            Diagnostic(
                "LDIPOL_VACUUM_AXIS_AMBIGUOUS",
                Severity.WARNING,
                "More than one vacuum axis was detected; review IDIPOL manually.",
                {"vacuum_axes": list(vacuum_axes)},
            )
        )
    return tuple(diagnostics)


def validate_vasp_input(
    directory: str | Path,
    *,
    mode: ValidationMode | str = ValidationMode.STRICT,
    potcar_metadata_path: str | Path | None = None,
) -> VaspInputValidationReport:
    """Validate a VASP input directory without modifying or generating any file."""

    active_mode = ValidationMode(mode)
    root = Path(directory)
    diagnostics: list[Diagnostic] = []
    artifacts: list[ArtifactRecord] = []
    structure_record = None
    structure = None
    species_order: tuple[str, ...] = ()
    estimated_vacuum = None
    incar_summary = None
    kpoints_summary = None
    metadata = None

    if not root.is_dir():
        return VaspInputValidationReport(
            directory=str(root),
            mode=active_mode,
            artifacts=(),
            structure=None,
            poscar_species_order=(),
            incar=None,
            kpoints=None,
            potcar_metadata=None,
            diagnostics=(
                Diagnostic(
                    "VASP_INPUT_DIRECTORY_NOT_FOUND",
                    Severity.ERROR,
                    "The requested VASP input directory does not exist.",
                    {"path": str(root)},
                ),
            ),
        )

    poscar_text, poscar_artifact, poscar_read_diagnostics = _read_text_artifact(
        root / "POSCAR", missing_code="POSCAR_FILE_NOT_FOUND"
    )
    diagnostics.extend(poscar_read_diagnostics)
    if poscar_artifact is not None:
        artifacts.append(poscar_artifact)
    if poscar_text is not None:
        try:
            poscar = Poscar.from_str(poscar_text)
        except Exception as exc:
            diagnostics.append(
                Diagnostic(
                    "POSCAR_PARSE_FAILED",
                    Severity.ERROR,
                    "pymatgen could not parse POSCAR.",
                    {"exception_type": type(exc).__name__},
                )
            )
        else:
            structure = poscar.structure
            species_order = tuple(poscar.site_symbols)
            if not poscar.true_names:
                diagnostics.append(
                    Diagnostic(
                        "POSCAR_SPECIES_NAMES_UNVERIFIED",
                        _policy(active_mode),
                        "POSCAR does not provide an explicit VASP 5 species-name line.",
                    )
                )
            inspected = inspect_structure(
                structure,
                source_format="vasp-poscar",
                artifact=poscar_artifact,
            )
            structure_record = inspected.record
            diagnostics.extend(_with_file(item, "POSCAR") for item in inspected.diagnostics)
            if inspected.metrics is not None:
                estimated_vacuum = inspected.metrics.estimated_vacuum_angstrom

    incar_text, incar_artifact, incar_read_diagnostics = _read_text_artifact(
        root / "INCAR", missing_code="INCAR_FILE_NOT_FOUND"
    )
    diagnostics.extend(incar_read_diagnostics)
    if incar_artifact is not None:
        artifacts.append(incar_artifact)
    if incar_text is not None:
        incar_summary, parse_diagnostics = parse_incar_text(incar_text)
        diagnostics.extend(_with_file(item, "INCAR") for item in parse_diagnostics)
        if structure is not None:
            diagnostics.extend(
                _with_file(item, "INCAR")
                for item in validate_incar(
                    incar_summary,
                    num_sites=len(structure),
                    num_species=len(species_order),
                    mode=active_mode,
                )
            )
            diagnostics.extend(
                _with_file(item, "INCAR")
                for item in _dipole_diagnostics(
                    incar=incar_summary,
                    estimated_vacuum=estimated_vacuum,
                    mode=active_mode,
                )
            )

    kpoints_text, kpoints_artifact, kpoints_read_diagnostics = _read_text_artifact(
        root / "KPOINTS", missing_code="KPOINTS_FILE_NOT_FOUND"
    )
    diagnostics.extend(kpoints_read_diagnostics)
    if kpoints_artifact is not None:
        artifacts.append(kpoints_artifact)
    if kpoints_text is not None:
        try:
            Kpoints.from_str(kpoints_text)
        except Exception as exc:
            diagnostics.append(
                Diagnostic(
                    "KPOINTS_PARSE_FAILED",
                    Severity.ERROR,
                    "pymatgen could not parse KPOINTS.",
                    {"exception_type": type(exc).__name__},
                )
            )
        kpoints_summary, parse_diagnostics = parse_kpoints_text(kpoints_text)
        diagnostics.extend(_with_file(item, "KPOINTS") for item in parse_diagnostics)
        if kpoints_summary is not None and structure is not None:
            diagnostics.extend(
                _with_file(item, "KPOINTS")
                for item in validate_kpoints(kpoints_summary, structure, mode=active_mode)
            )

    if potcar_metadata_path is None:
        metadata_path = root / "catex-potcar-metadata.json"
    else:
        metadata_path = Path(potcar_metadata_path)
        if not metadata_path.is_absolute():
            metadata_path = root / metadata_path
    if metadata_path.is_file():
        metadata_text, metadata_artifact, metadata_read_diagnostics = _read_text_artifact(
            metadata_path, missing_code="POTCAR_METADATA_FILE_NOT_FOUND"
        )
        diagnostics.extend(metadata_read_diagnostics)
        if metadata_artifact is not None:
            artifacts.append(metadata_artifact)
        if metadata_text is not None and metadata_artifact is not None:
            metadata, metadata_diagnostics = parse_potcar_metadata(
                metadata_text, artifact=metadata_artifact
            )
            diagnostics.extend(
                _with_file(item, metadata_path.name) for item in metadata_diagnostics
            )
    else:
        diagnostics.append(
            Diagnostic(
                "POTCAR_METADATA_MISSING",
                _policy(active_mode),
                "A copyright-safe POTCAR metadata record is required for full validation.",
                {"expected_filename": metadata_path.name},
            )
        )

    if (root / "POTCAR").is_file():
        diagnostics.append(
            Diagnostic(
                "RAW_POTCAR_PRESENT_NOT_READ",
                Severity.INFO,
                "A raw POTCAR exists, but CatEx deliberately did not open or hash it.",
            )
        )

    if metadata is not None and species_order:
        encut = None
        if incar_summary is not None and incar_summary.value("ENCUT") is not None:
            with suppress(ValueError):
                encut = parse_float(incar_summary.value("ENCUT") or "")
        diagnostics.extend(
            _with_file(item, metadata_path.name)
            for item in validate_potcar_metadata(
                metadata,
                poscar_species_order=species_order,
                encut_ev=encut,
                mode=active_mode,
            )
        )

    return VaspInputValidationReport(
        directory=str(root),
        mode=active_mode,
        artifacts=tuple(artifacts),
        structure=structure_record,
        poscar_species_order=species_order,
        incar=incar_summary,
        kpoints=kpoints_summary,
        potcar_metadata=metadata,
        diagnostics=tuple(diagnostics),
    )
