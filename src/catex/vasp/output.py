"""Streaming, read-only parsing of VASP 5.4.4 OUTCAR and OSZICAR artifacts."""

from __future__ import annotations

import hashlib
import math
import re
from dataclasses import dataclass, field
from pathlib import Path

from catex.models import ArtifactRecord, Diagnostic, Severity
from catex.vasp.output_models import (
    ConvergenceState,
    ConvergenceSummary,
    EnergySummary,
    ForceSummary,
    MagnetizationComponent,
    MagnetizationSummary,
    ParseConfidence,
    ParseEvidence,
    TerminationSummary,
    VaspOutputParseReport,
    VaspRunOutcome,
    VibrationalMode,
    VibrationalSummary,
)

_FLOAT_TOKEN = r"[+-]?(?:\d+(?:\.\d*)?|\.\d+)(?:[EeDd][+-]?\d+)?"
_FLOAT_PATTERN = re.compile(_FLOAT_TOKEN)
_VERSION_PATTERN = re.compile(r"\bvasp\.([0-9]+(?:\.[0-9]+){1,2})", re.IGNORECASE)
_ITERATION_PATTERN = re.compile(r"\bIteration\s+(\d+)\s*\(\s*(\d+)\s*\)")
_TOTEN_PATTERN = re.compile(rf"free\s+energy\s+TOTEN\s*=\s*({_FLOAT_TOKEN})\s+eV", re.IGNORECASE)
_ENTROPY_PATTERN = re.compile(
    rf"energy\s+without\s+entropy\s*=\s*({_FLOAT_TOKEN})"
    rf"\s+energy\(sigma->0\)\s*=\s*({_FLOAT_TOKEN})",
    re.IGNORECASE,
)
_MAGNETIZATION_PATTERN = re.compile(r"^\s*magnetization\s*\(([xyz])\)", re.IGNORECASE)
_OSZICAR_ION_PATTERN = re.compile(r"^\s*(\d+)\b.*\bF=\s*(" + _FLOAT_TOKEN + r")")
_OSZICAR_E0_PATTERN = re.compile(r"\bE0=\s*(" + _FLOAT_TOKEN + r")")
_OSZICAR_MAG_PATTERN = re.compile(r"\bmag=\s*(.+)$", re.IGNORECASE)
_OSZICAR_ELECTRONIC_PATTERN = re.compile(
    r"^\s*(?:DAV|RMM|CG|DMP|DIIS|EDDIAG|IALGO)\s*:\s*(\d+)\b", re.IGNORECASE
)
_VIBRATION_PATTERN = re.compile(
    rf"^\s*(?P<index>\d+)\s+f(?P<imaginary>\s*/\s*i)?\s*=\s*"
    rf"(?P<thz>{_FLOAT_TOKEN})\s+THz.*?"
    rf"(?P<wavenumber>{_FLOAT_TOKEN})\s+cm-1.*?"
    rf"(?P<energy>{_FLOAT_TOKEN})\s+meV",
    re.IGNORECASE,
)

_FATAL_MARKERS = (
    ("very bad news", "VASP_INTERNAL_ERROR"),
    ("brmix: very serious problems", "BRMIX_FAILURE"),
    ("zbrent: fatal error", "ZBRENT_FAILURE"),
    ("error fexcp", "FEXCP_FAILURE"),
    ("internal error in subroutine", "VASP_INTERNAL_ERROR"),
    ("segmentation fault", "SEGMENTATION_FAULT"),
    ("sigsegv", "SEGMENTATION_FAULT"),
    ("mpi_abort", "MPI_ABORT"),
    ("forrtl: severe", "FORTRAN_RUNTIME_FAILURE"),
)


def _float(token: str) -> float | None:
    try:
        value = float(token.replace("D", "E").replace("d", "e"))
    except ValueError:
        return None
    return value if math.isfinite(value) else None


def _evidence(
    path: Path,
    line_start: int,
    line_end: int,
    parser_rule: str,
    confidence: ParseConfidence = ParseConfidence.HIGH,
) -> ParseEvidence:
    return ParseEvidence(str(path), line_start, line_end, parser_rule, confidence)


@dataclass(slots=True)
class _EnergyRecord:
    free_energy_ev: float
    energy_without_entropy_ev: float | None
    sigma_zero_energy_ev: float | None
    ionic_step: int | None
    line_start: int
    line_end: int


@dataclass(slots=True)
class _ForceRecord:
    vectors: tuple[tuple[float, float, float], ...]
    ionic_step: int | None
    line_start: int
    line_end: int


@dataclass(slots=True)
class _MagnetizationRecord:
    component: str
    site_totals: tuple[float, ...]
    projected_sum: float
    ionic_step: int | None
    line_start: int
    line_end: int


@dataclass(slots=True)
class _OszicarEnergyRecord:
    free_energy_ev: float
    sigma_zero_energy_ev: float | None
    ionic_step: int
    cell_moment_mub: tuple[float, ...] | None
    line_number: int


@dataclass(slots=True)
class _VibrationalRecord:
    mode_index: int
    imaginary: bool
    frequency_thz: float
    wavenumber_cm1: float
    energy_mev: float
    line_number: int


@dataclass(slots=True)
class _OutcarScanner:
    path: Path
    version: str | None = None
    nions: int | None = None
    nelm: int | None = None
    nsw: int | None = None
    ibrion: int | None = None
    ediff: float | None = None
    ediffg: float | None = None
    current_ionic_step: int | None = None
    current_electronic_step: int | None = None
    highest_ionic_step: int = 0
    energy_count: int = 0
    last_energy: _EnergyRecord | None = None
    last_force: _ForceRecord | None = None
    magnetization_records: dict[tuple[int, str], _MagnetizationRecord] = field(default_factory=dict)
    electronic_converged_steps: set[int] = field(default_factory=set)
    electronic_convergence_evidence: ParseEvidence | None = None
    ionic_converged: bool = False
    ionic_convergence_evidence: ParseEvidence | None = None
    normal_footer_evidence: ParseEvidence | None = None
    fatal_errors: dict[str, ParseEvidence] = field(default_factory=dict)
    incomplete_force_blocks: int = 0
    incomplete_magnetization_blocks: int = 0
    vibration_records: dict[int, _VibrationalRecord] = field(default_factory=dict)
    last_line_number: int = 0
    saw_content: bool = False
    _force_start: int | None = None
    _force_rows: list[tuple[float, float, float]] = field(default_factory=list)
    _mag_start: int | None = None
    _mag_component: str | None = None
    _mag_rows: list[float] = field(default_factory=list)

    def _parameter(self, line: str, name: str) -> int | None:
        match = re.search(rf"\b{name}\s*=\s*(-?\d+)", line, re.IGNORECASE)
        return int(match.group(1)) if match else None

    def _float_parameter(self, line: str, name: str) -> float | None:
        match = re.search(rf"\b{name}\s*=\s*({_FLOAT_TOKEN})", line, re.IGNORECASE)
        return _float(match.group(1)) if match else None

    def _finish_force(self, line_number: int) -> None:
        if not self._force_rows:
            return
        if self.nions is not None and len(self._force_rows) != self.nions:
            self.incomplete_force_blocks += 1
        else:
            self.last_force = _ForceRecord(
                tuple(self._force_rows),
                self.current_ionic_step,
                self._force_start or line_number,
                line_number,
            )
        self._force_start = None
        self._force_rows = []

    def _accept_force_line(self, line_number: int, line: str) -> bool:
        if self._force_start is None:
            return False
        stripped = line.strip()
        if not stripped or set(stripped) == {"-"}:
            if self._force_rows and set(stripped) == {"-"}:
                self._finish_force(line_number)
            return True
        if stripped.lower().startswith("total drift"):
            self._finish_force(line_number)
            return True
        tokens = stripped.split()
        if len(tokens) >= 6:
            values = [_float(token) for token in tokens[:6]]
            if all(value is not None for value in values):
                self._force_rows.append((float(values[3]), float(values[4]), float(values[5])))
                return True
        if self._force_rows:
            self.incomplete_force_blocks += 1
            self._force_start = None
            self._force_rows = []
        return False

    def _finish_magnetization(self, line_number: int, projected_sum: float) -> None:
        if not self._mag_rows or self._mag_component is None:
            return
        if self.nions is not None and len(self._mag_rows) != self.nions:
            self.incomplete_magnetization_blocks += 1
        else:
            step = self.current_ionic_step or 0
            self.magnetization_records[(step, self._mag_component)] = _MagnetizationRecord(
                self._mag_component,
                tuple(self._mag_rows),
                projected_sum,
                self.current_ionic_step,
                self._mag_start or line_number,
                line_number,
            )
        self._mag_start = None
        self._mag_component = None
        self._mag_rows = []

    def _accept_magnetization_line(self, line_number: int, line: str) -> bool:
        if self._mag_start is None:
            return False
        stripped = line.strip()
        if stripped.lower().startswith("tot"):
            values = [_float(token) for token in _FLOAT_PATTERN.findall(stripped[3:])]
            finite = [value for value in values if value is not None]
            if finite:
                self._finish_magnetization(line_number, float(finite[-1]))
            return True
        row_match = re.match(r"^\s*(\d+)\s+(.+)$", line)
        if row_match:
            values = [_float(token) for token in _FLOAT_PATTERN.findall(row_match.group(2))]
            finite = [value for value in values if value is not None]
            if finite:
                self._mag_rows.append(float(finite[-1]))
                return True
        return not self._mag_rows or not stripped or set(stripped) == {"-"} or "# of ion" in line

    def accept(self, line_number: int, line: str) -> None:
        self.last_line_number = line_number
        if line.strip():
            self.saw_content = True

        force_consumed = self._accept_force_line(line_number, line)
        magnetization_consumed = self._accept_magnetization_line(line_number, line)
        if force_consumed or magnetization_consumed:
            return

        version_match = _VERSION_PATTERN.search(line)
        if version_match and self.version is None:
            self.version = version_match.group(1)

        for name, attribute in (
            ("NIONS", "nions"),
            ("NELM", "nelm"),
            ("NSW", "nsw"),
            ("IBRION", "ibrion"),
        ):
            value = self._parameter(line, name)
            if value is not None:
                setattr(self, attribute, value)
        for name, attribute in (("EDIFF", "ediff"), ("EDIFFG", "ediffg")):
            value = self._float_parameter(line, name)
            if value is not None:
                setattr(self, attribute, value)

        iteration_match = _ITERATION_PATTERN.search(line)
        if iteration_match:
            self.current_ionic_step = int(iteration_match.group(1))
            self.current_electronic_step = int(iteration_match.group(2))
            self.highest_ionic_step = max(self.highest_ionic_step, self.current_ionic_step)

        lower = line.lower()
        if "aborting loop because ediff is reached" in lower:
            if self.current_ionic_step is not None:
                self.electronic_converged_steps.add(self.current_ionic_step)
            self.electronic_convergence_evidence = _evidence(
                self.path, line_number, line_number, "outcar.electronic_convergence_marker"
            )
        if "reached required accuracy - stopping structural energy minimisation" in lower:
            self.ionic_converged = True
            self.ionic_convergence_evidence = _evidence(
                self.path, line_number, line_number, "outcar.ionic_convergence_marker"
            )
        if "general timing and accounting informations for this job" in lower:
            self.normal_footer_evidence = _evidence(
                self.path, line_number, line_number, "outcar.normal_termination_footer"
            )
        for marker, code in _FATAL_MARKERS:
            if marker in lower and code not in self.fatal_errors:
                self.fatal_errors[code] = _evidence(
                    self.path, line_number, line_number, f"outcar.fatal_marker.{code.lower()}"
                )

        energy_match = _TOTEN_PATTERN.search(line)
        if energy_match:
            value = _float(energy_match.group(1))
            if value is not None:
                self.energy_count += 1
                ionic_step = self.current_ionic_step or self.energy_count
                self.highest_ionic_step = max(self.highest_ionic_step, ionic_step)
                self.last_energy = _EnergyRecord(
                    value, None, None, ionic_step, line_number, line_number
                )
        entropy_match = _ENTROPY_PATTERN.search(line)
        if entropy_match and self.last_energy is not None:
            without_entropy = _float(entropy_match.group(1))
            sigma_zero = _float(entropy_match.group(2))
            self.last_energy.energy_without_entropy_ev = without_entropy
            self.last_energy.sigma_zero_energy_ev = sigma_zero
            self.last_energy.line_end = line_number

        if "POSITION" in line and "TOTAL-FORCE" in line and "eV/Angst" in line:
            if self._force_start is not None:
                self.incomplete_force_blocks += 1
            self._force_start = line_number
            self._force_rows = []

        magnetization_match = _MAGNETIZATION_PATTERN.match(line)
        if magnetization_match:
            if self._mag_start is not None:
                self.incomplete_magnetization_blocks += 1
            self._mag_start = line_number
            self._mag_component = magnetization_match.group(1).lower()
            self._mag_rows = []

        vibration_match = _VIBRATION_PATTERN.match(line)
        if vibration_match:
            values = (
                _float(vibration_match.group("thz")),
                _float(vibration_match.group("wavenumber")),
                _float(vibration_match.group("energy")),
            )
            if all(value is not None for value in values):
                index = int(vibration_match.group("index"))
                self.vibration_records[index] = _VibrationalRecord(
                    mode_index=index,
                    imaginary=vibration_match.group("imaginary") is not None,
                    frequency_thz=float(values[0]),
                    wavenumber_cm1=float(values[1]),
                    energy_mev=float(values[2]),
                    line_number=line_number,
                )

    def finish(self) -> None:
        if self._force_start is not None:
            self.incomplete_force_blocks += 1
            self._force_start = None
            self._force_rows = []
        if self._mag_start is not None:
            self.incomplete_magnetization_blocks += 1
            self._mag_start = None
            self._mag_component = None
            self._mag_rows = []


@dataclass(slots=True)
class _OszicarScanner:
    path: Path
    last_energy: _OszicarEnergyRecord | None = None
    current_electronic_step: int | None = None
    last_line_number: int = 0
    saw_content: bool = False

    def accept(self, line_number: int, line: str) -> None:
        self.last_line_number = line_number
        if line.strip():
            self.saw_content = True
        electronic_match = _OSZICAR_ELECTRONIC_PATTERN.match(line)
        if electronic_match:
            self.current_electronic_step = int(electronic_match.group(1))
        ionic_match = _OSZICAR_ION_PATTERN.match(line)
        if not ionic_match:
            return
        free_energy = _float(ionic_match.group(2))
        if free_energy is None:
            return
        e0_match = _OSZICAR_E0_PATTERN.search(line)
        sigma_zero = _float(e0_match.group(1)) if e0_match else None
        mag_match = _OSZICAR_MAG_PATTERN.search(line)
        cell_moment: tuple[float, ...] | None = None
        if mag_match:
            moments = [_float(token) for token in _FLOAT_PATTERN.findall(mag_match.group(1))]
            finite = tuple(float(value) for value in moments[:3] if value is not None)
            cell_moment = finite or None
        self.last_energy = _OszicarEnergyRecord(
            free_energy,
            sigma_zero,
            int(ionic_match.group(1)),
            cell_moment,
            line_number,
        )

    def finish(self) -> None:
        return


def _scan_file(
    path: Path,
    scanner: _OutcarScanner | _OszicarScanner,
) -> tuple[ArtifactRecord | None, tuple[Diagnostic, ...]]:
    diagnostics: list[Diagnostic] = []
    digest = hashlib.sha256()
    bytes_read = 0
    decoding_replaced = False
    try:
        before = path.stat()
        with path.open("rb") as stream:
            for line_number, raw_line in enumerate(stream, start=1):
                digest.update(raw_line)
                bytes_read += len(raw_line)
                try:
                    line = raw_line.decode("utf-8")
                except UnicodeDecodeError:
                    line = raw_line.decode("utf-8", errors="replace")
                    decoding_replaced = True
                scanner.accept(line_number, line.rstrip("\r\n"))
        scanner.finish()
        after = path.stat()
    except OSError as exc:
        return (
            None,
            (
                Diagnostic(
                    "VASP_OUTPUT_READ_FAILED",
                    Severity.ERROR,
                    "A VASP output artifact could not be read.",
                    {"path": str(path), "exception_type": type(exc).__name__},
                ),
            ),
        )

    artifact = ArtifactRecord(str(path), digest.hexdigest(), bytes_read)
    if decoding_replaced:
        diagnostics.append(
            Diagnostic(
                "VASP_OUTPUT_DECODING_REPLACED",
                Severity.WARNING,
                "Non-UTF-8 bytes were replaced while parsing the text output.",
                {"path": str(path)},
            )
        )
    if before.st_size != after.st_size or before.st_mtime_ns != after.st_mtime_ns:
        diagnostics.append(
            Diagnostic(
                "VASP_OUTPUT_CHANGED_DURING_PARSE",
                Severity.ERROR,
                "The output changed during parsing; results are not a stable snapshot.",
                {"path": str(path)},
            )
        )
    return artifact, tuple(diagnostics)


def _missing_report(directory: Path, diagnostic: Diagnostic) -> VaspOutputParseReport:
    return VaspOutputParseReport(
        directory=str(directory),
        artifacts=(),
        detected_vasp_version=None,
        termination=TerminationSummary(VaspRunOutcome.UNKNOWN, False, (), ParseConfidence.LOW, ()),
        convergence=ConvergenceSummary(
            ConvergenceState.UNKNOWN, ConvergenceState.UNKNOWN, 0, None, ()
        ),
        energy=None,
        forces=None,
        magnetization=None,
        diagnostics=(diagnostic,),
    )


def _convergence(
    outcar: _OutcarScanner | None,
    oszicar: _OszicarScanner | None,
) -> ConvergenceSummary:
    if outcar is None:
        steps = oszicar.last_energy.ionic_step if oszicar and oszicar.last_energy else 0
        final_electronic = oszicar.current_electronic_step if oszicar else None
        return ConvergenceSummary(
            ConvergenceState.UNKNOWN,
            ConvergenceState.UNKNOWN,
            steps,
            final_electronic,
            (),
        )

    if outcar.ibrion in {5, 6, 7, 8}:
        calculation_type = "vibration"
    elif outcar.ibrion == 0 and (outcar.nsw or 0) > 0:
        calculation_type = "molecular_dynamics"
    elif outcar.ibrion in {1, 2, 3} and (outcar.nsw or 0) > 0:
        calculation_type = "relaxation"
    elif outcar.nsw == 0 or outcar.ibrion == -1:
        calculation_type = "static"
    else:
        calculation_type = "unknown"

    final_ionic = max(
        outcar.highest_ionic_step,
        oszicar.last_energy.ionic_step if oszicar and oszicar.last_energy else 0,
    )
    final_electronic = outcar.current_electronic_step
    if final_electronic is None and oszicar is not None:
        final_electronic = oszicar.current_electronic_step

    evidence: list[ParseEvidence] = []
    converged_step = final_ionic in outcar.electronic_converged_steps
    if not outcar.electronic_converged_steps and outcar.electronic_convergence_evidence:
        converged_step = True
    if converged_step:
        electronic = ConvergenceState.CONVERGED
        if outcar.electronic_convergence_evidence:
            evidence.append(outcar.electronic_convergence_evidence)
    elif (
        final_electronic is not None and outcar.nelm is not None and final_electronic >= outcar.nelm
    ):
        electronic = ConvergenceState.NOT_CONVERGED
        evidence.append(
            _evidence(
                outcar.path,
                outcar.last_line_number,
                outcar.last_line_number,
                "outcar.final_electronic_step_reached_nelm",
                ParseConfidence.MEDIUM,
            )
        )
    else:
        electronic = ConvergenceState.UNKNOWN

    if outcar.nsw == 0 or outcar.ibrion in {-1, 0, 5, 6, 7, 8}:
        ionic = ConvergenceState.NOT_APPLICABLE
    elif outcar.nsw is not None and outcar.nsw > 0 and outcar.ibrion in {1, 2, 3}:
        if outcar.ionic_converged:
            ionic = ConvergenceState.CONVERGED
            if outcar.ionic_convergence_evidence:
                evidence.append(outcar.ionic_convergence_evidence)
        elif outcar.normal_footer_evidence and final_ionic >= outcar.nsw:
            ionic = ConvergenceState.NOT_CONVERGED
            evidence.append(
                _evidence(
                    outcar.path,
                    outcar.last_line_number,
                    outcar.last_line_number,
                    "outcar.ionic_steps_reached_nsw_without_ediffg_marker",
                    ParseConfidence.MEDIUM,
                )
            )
        else:
            ionic = ConvergenceState.UNKNOWN
    else:
        ionic = ConvergenceState.UNKNOWN

    return ConvergenceSummary(
        electronic,
        ionic,
        final_ionic,
        final_electronic,
        tuple(evidence),
        calculation_type,
        outcar.ediff,
        outcar.ediffg,
        outcar.nelm,
        outcar.nsw,
        outcar.ibrion,
    )


def _vibrational_summary(outcar: _OutcarScanner | None) -> VibrationalSummary | None:
    if outcar is None or not outcar.vibration_records:
        return None
    modes = tuple(
        VibrationalMode(
            mode_index=record.mode_index,
            imaginary=record.imaginary,
            frequency_thz=record.frequency_thz,
            wavenumber_cm1=record.wavenumber_cm1,
            energy_mev=record.energy_mev,
            evidence=_evidence(
                outcar.path,
                record.line_number,
                record.line_number,
                "outcar.vibrational_mode",
            ),
        )
        for record in sorted(outcar.vibration_records.values(), key=lambda item: item.mode_index)
    )
    return VibrationalSummary(modes)


def _termination(
    outcar: _OutcarScanner | None,
    oszicar: _OszicarScanner | None,
    convergence: ConvergenceSummary,
) -> TerminationSummary:
    evidence: list[ParseEvidence] = []
    fatal_codes: tuple[str, ...] = ()
    if outcar and outcar.fatal_errors:
        fatal_codes = tuple(sorted(outcar.fatal_errors))
        evidence.extend(outcar.fatal_errors[code] for code in fatal_codes)
        return TerminationSummary(
            VaspRunOutcome.FAILED, False, fatal_codes, ParseConfidence.HIGH, tuple(evidence)
        )
    if outcar and outcar.normal_footer_evidence:
        evidence.append(outcar.normal_footer_evidence)
        unconverged = (
            convergence.electronic is ConvergenceState.NOT_CONVERGED
            or convergence.ionic is ConvergenceState.NOT_CONVERGED
        )
        return TerminationSummary(
            VaspRunOutcome.UNCONVERGED if unconverged else VaspRunOutcome.NORMAL,
            True,
            (),
            ParseConfidence.HIGH,
            tuple(evidence),
        )
    if outcar and outcar.saw_content:
        evidence.append(
            _evidence(
                outcar.path,
                max(1, outcar.last_line_number),
                max(1, outcar.last_line_number),
                "outcar.eof_without_normal_footer",
                ParseConfidence.MEDIUM,
            )
        )
        return TerminationSummary(
            VaspRunOutcome.TRUNCATED, False, (), ParseConfidence.MEDIUM, tuple(evidence)
        )
    if oszicar and oszicar.saw_content:
        evidence.append(
            _evidence(
                oszicar.path,
                max(1, oszicar.last_line_number),
                max(1, oszicar.last_line_number),
                "oszicar.present_without_outcar_footer",
                ParseConfidence.LOW,
            )
        )
        return TerminationSummary(
            VaspRunOutcome.TRUNCATED, False, (), ParseConfidence.LOW, tuple(evidence)
        )
    return TerminationSummary(VaspRunOutcome.UNKNOWN, False, (), ParseConfidence.LOW, ())


def _energy_summary(
    outcar: _OutcarScanner | None,
    oszicar: _OszicarScanner | None,
    termination: TerminationSummary,
    diagnostics: list[Diagnostic],
) -> EnergySummary | None:
    out_record = outcar.last_energy if outcar else None
    osz_record = oszicar.last_energy if oszicar else None
    if out_record is None and osz_record is None:
        return None

    evidence: list[ParseEvidence] = []
    if out_record is not None and outcar is not None:
        evidence.append(
            _evidence(
                outcar.path,
                out_record.line_start,
                out_record.line_end,
                "outcar.final_free_energy_block",
            )
        )
        free_energy = out_record.free_energy_ev
        without_entropy = out_record.energy_without_entropy_ev
        sigma_zero = out_record.sigma_zero_energy_ev
        ionic_step = out_record.ionic_step
        confidence = (
            ParseConfidence.HIGH if termination.normal_footer_found else ParseConfidence.MEDIUM
        )
    else:
        assert osz_record is not None and oszicar is not None
        free_energy = osz_record.free_energy_ev
        without_entropy = None
        sigma_zero = osz_record.sigma_zero_energy_ev
        ionic_step = osz_record.ionic_step
        confidence = ParseConfidence.MEDIUM

    if osz_record is not None and oszicar is not None:
        osz_evidence = _evidence(
            oszicar.path,
            osz_record.line_number,
            osz_record.line_number,
            "oszicar.final_ionic_summary",
        )
        evidence.append(osz_evidence)
        if out_record is not None:
            disagreement = abs(out_record.free_energy_ev - osz_record.free_energy_ev)
            if disagreement > 5e-4:
                confidence = ParseConfidence.LOW
                diagnostics.append(
                    Diagnostic(
                        "ENERGY_SOURCE_DISAGREEMENT",
                        Severity.WARNING,
                        "OUTCAR and OSZICAR final free energies disagree beyond text precision.",
                        {"absolute_difference_eV": disagreement},
                    )
                )
            elif termination.normal_footer_found:
                confidence = ParseConfidence.HIGH

    return EnergySummary(
        free_energy,
        without_entropy,
        sigma_zero,
        ionic_step,
        confidence,
        tuple(evidence),
    )


def _force_summary(
    outcar: _OutcarScanner | None,
    termination: TerminationSummary,
) -> ForceSummary | None:
    if outcar is None or outcar.last_force is None or not outcar.last_force.vectors:
        return None
    record = outcar.last_force
    norms = [
        math.sqrt(sum(component * component for component in vector)) for vector in record.vectors
    ]
    index, maximum = max(enumerate(norms, start=1), key=lambda item: item[1])
    confidence = ParseConfidence.HIGH if termination.normal_footer_found else ParseConfidence.MEDIUM
    return ForceSummary(
        record.vectors,
        maximum,
        index,
        record.ionic_step,
        confidence,
        _evidence(
            outcar.path,
            record.line_start,
            record.line_end,
            "outcar.last_complete_total_force_block",
        ),
    )


def _magnetization_summary(
    outcar: _OutcarScanner | None,
    oszicar: _OszicarScanner | None,
) -> MagnetizationSummary | None:
    components: list[MagnetizationComponent] = []
    if outcar and outcar.magnetization_records:
        final_step = max(step for step, _ in outcar.magnetization_records)
        for component in ("x", "y", "z"):
            record = outcar.magnetization_records.get((final_step, component))
            if record is None:
                continue
            components.append(
                MagnetizationComponent(
                    component,
                    record.site_totals,
                    record.projected_sum,
                    record.ionic_step,
                    _evidence(
                        outcar.path,
                        record.line_start,
                        record.line_end,
                        f"outcar.site_projected_magnetization_{component}",
                    ),
                )
            )

    cell_moment = None
    cell_evidence = None
    if oszicar and oszicar.last_energy and oszicar.last_energy.cell_moment_mub:
        cell_moment = oszicar.last_energy.cell_moment_mub
        cell_evidence = _evidence(
            oszicar.path,
            oszicar.last_energy.line_number,
            oszicar.last_energy.line_number,
            "oszicar.cell_magnetic_moment",
        )
    if not components and cell_moment is None:
        return None
    confidence = ParseConfidence.HIGH if components and cell_moment else ParseConfidence.MEDIUM
    return MagnetizationSummary(tuple(components), cell_moment, cell_evidence, confidence)


def parse_vasp_output(directory: str | Path) -> VaspOutputParseReport:
    """Parse OUTCAR and OSZICAR without modifying or materializing output files."""

    root = Path(directory)
    if not root.is_dir():
        return _missing_report(
            root,
            Diagnostic(
                "VASP_OUTPUT_DIRECTORY_NOT_FOUND",
                Severity.ERROR,
                "The VASP output directory does not exist or is not a directory.",
                {"path": str(root)},
            ),
        )

    outcar_path = root / "OUTCAR"
    oszicar_path = root / "OSZICAR"
    outcar = _OutcarScanner(outcar_path) if outcar_path.is_file() else None
    oszicar = _OszicarScanner(oszicar_path) if oszicar_path.is_file() else None
    artifacts: list[ArtifactRecord] = []
    diagnostics: list[Diagnostic] = []

    if outcar is not None:
        artifact, findings = _scan_file(outcar_path, outcar)
        if artifact:
            artifacts.append(artifact)
        diagnostics.extend(findings)
    if oszicar is not None:
        artifact, findings = _scan_file(oszicar_path, oszicar)
        if artifact:
            artifacts.append(artifact)
        diagnostics.extend(findings)

    if outcar is None and oszicar is None:
        return _missing_report(
            root,
            Diagnostic(
                "VASP_OUTPUT_FILES_MISSING",
                Severity.ERROR,
                "Neither OUTCAR nor OSZICAR is present.",
                {"directory": str(root)},
            ),
        )
    if outcar is None:
        diagnostics.append(
            Diagnostic(
                "OUTCAR_MISSING",
                Severity.WARNING,
                "OUTCAR is missing; OSZICAR-only observations have reduced confidence.",
                {"directory": str(root)},
            )
        )

    convergence = _convergence(outcar, oszicar)
    termination = _termination(outcar, oszicar, convergence)

    if outcar and outcar.version and not outcar.version.startswith("5.4.4"):
        diagnostics.append(
            Diagnostic(
                "VASP_VERSION_OUTSIDE_TARGET",
                Severity.WARNING,
                "The output was not produced by the target VASP 5.4.4 line.",
                {"detected_version": outcar.version, "target_version": "5.4.4"},
            )
        )
    elif outcar and outcar.version is None:
        diagnostics.append(
            Diagnostic(
                "VASP_VERSION_NOT_DETECTED",
                Severity.INFO,
                "No VASP version banner was found in OUTCAR.",
                {},
            )
        )

    if termination.outcome is VaspRunOutcome.FAILED:
        diagnostics.append(
            Diagnostic(
                "VASP_RUN_FAILED",
                Severity.ERROR,
                "A known fatal VASP or runtime marker was found.",
                {"fatal_error_codes": list(termination.fatal_error_codes)},
            )
        )
    elif termination.outcome is VaspRunOutcome.TRUNCATED:
        diagnostics.append(
            Diagnostic(
                "VASP_OUTPUT_TRUNCATED_OR_RUNNING",
                Severity.WARNING,
                "No normal termination footer was found; the artifact is truncated "
                "or still running.",
                {},
            )
        )
    elif termination.outcome is VaspRunOutcome.UNCONVERGED:
        diagnostics.append(
            Diagnostic(
                "VASP_RUN_UNCONVERGED",
                Severity.ERROR,
                "VASP terminated normally but an explicit convergence criterion was not met.",
                {
                    "electronic": convergence.electronic.value,
                    "ionic": convergence.ionic.value,
                },
            )
        )
    elif termination.outcome is VaspRunOutcome.UNKNOWN:
        diagnostics.append(
            Diagnostic(
                "VASP_RUN_OUTCOME_UNKNOWN",
                Severity.ERROR,
                "There is insufficient output evidence to classify the run.",
                {},
            )
        )

    if termination.normal_footer_found and (
        convergence.electronic is ConvergenceState.UNKNOWN
        or convergence.ionic is ConvergenceState.UNKNOWN
    ):
        diagnostics.append(
            Diagnostic(
                "VASP_CONVERGENCE_UNKNOWN",
                Severity.WARNING,
                "The process ended normally, but scientific convergence could not be proven.",
                {
                    "electronic": convergence.electronic.value,
                    "ionic": convergence.ionic.value,
                },
            )
        )

    if outcar and outcar.incomplete_force_blocks:
        diagnostics.append(
            Diagnostic(
                "OUTCAR_FORCE_BLOCK_INCOMPLETE",
                Severity.WARNING,
                "One or more TOTAL-FORCE blocks were incomplete and ignored.",
                {"count": outcar.incomplete_force_blocks},
            )
        )
    if outcar and outcar.incomplete_magnetization_blocks:
        diagnostics.append(
            Diagnostic(
                "OUTCAR_MAGNETIZATION_BLOCK_INCOMPLETE",
                Severity.WARNING,
                "One or more magnetization blocks were incomplete and ignored.",
                {"count": outcar.incomplete_magnetization_blocks},
            )
        )

    energy = _energy_summary(outcar, oszicar, termination, diagnostics)
    forces = _force_summary(outcar, termination)
    magnetization = _magnetization_summary(outcar, oszicar)
    vibrations = _vibrational_summary(outcar)
    if energy is None:
        diagnostics.append(
            Diagnostic(
                "VASP_FINAL_ENERGY_MISSING",
                Severity.WARNING,
                "No complete final energy record was found.",
                {},
            )
        )

    return VaspOutputParseReport(
        directory=str(root),
        artifacts=tuple(artifacts),
        detected_vasp_version=outcar.version if outcar else None,
        termination=termination,
        convergence=convergence,
        energy=energy,
        forces=forces,
        magnetization=magnetization,
        vibrations=vibrations,
        diagnostics=tuple(diagnostics),
    )
