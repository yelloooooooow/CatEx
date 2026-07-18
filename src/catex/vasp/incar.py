"""Raw-text INCAR parsing and VASP 5.4.4 validation rules."""

from __future__ import annotations

import re
from dataclasses import dataclass

from catex.models import Diagnostic, Severity
from catex.vasp.models import IncarAssignment, IncarSummary, ValidationMode
from catex.vasp.registry import validate_incar_registry

_ASSIGNMENT = re.compile(r"^([A-Za-z][A-Za-z0-9_]*)\s*=\s*(.*)$", re.DOTALL)
_REAL = re.compile(r"^[+-]?(?:\d+(?:\.\d*)?|\.\d+)(?:[EeDd][+-]?\d+)?$")
_REPEATED_REAL = re.compile(
    r"^(?:(?P<count>\d+)\*)?(?P<value>[+-]?(?:\d+(?:\.\d*)?|\.\d+)(?:[EeDd][+-]?\d+)?)$"
)
_POST_VASP5_PREFIXES = ("ELPH_", "KERNEL_", "ML_", "PLUGINS_")


@dataclass(frozen=True, slots=True)
class _LogicalLine:
    text: str
    line_start: int
    line_end: int


def _policy(mode: ValidationMode) -> Severity:
    return Severity.ERROR if mode is ValidationMode.STRICT else Severity.WARNING


def _strip_comment(line: str, in_quote: bool) -> tuple[str, bool]:
    output: list[str] = []
    quoted = in_quote
    for character in line:
        if character == '"':
            quoted = not quoted
            output.append(character)
        elif character in "#!" and not quoted:
            break
        else:
            output.append(character)
    return "".join(output), quoted


def _logical_lines(text: str) -> tuple[tuple[_LogicalLine, ...], tuple[Diagnostic, ...]]:
    logical: list[_LogicalLine] = []
    diagnostics: list[Diagnostic] = []
    buffer: list[str] = []
    start: int | None = None
    in_quote = False
    continued = False

    for line_number, physical in enumerate(text.splitlines(), start=1):
        content, in_quote = _strip_comment(physical, in_quote)
        trimmed = content.rstrip()
        has_continuation = not in_quote and trimmed.endswith("\\")
        if has_continuation:
            if not content.endswith("\\"):
                diagnostics.append(
                    Diagnostic(
                        "INCAR_CONTINUATION_TRAILING_WHITESPACE",
                        Severity.WARNING,
                        "Whitespace follows a continuation backslash; VASP 5.4.4 parsing may vary.",
                        {"line": line_number},
                    )
                )
            trimmed = trimmed[:-1]

        if start is None and trimmed.strip():
            start = line_number
        if start is not None:
            buffer.append(trimmed)

        continued = has_continuation
        if start is not None and not in_quote and not has_continuation:
            logical.append(_LogicalLine(" ".join(buffer), start, line_number))
            buffer = []
            start = None

    if in_quote:
        diagnostics.append(
            Diagnostic(
                "INCAR_UNTERMINATED_QUOTE",
                Severity.ERROR,
                "A quoted INCAR value was not terminated.",
                {"line_start": start},
            )
        )
    if buffer:
        diagnostics.append(
            Diagnostic(
                "INCAR_DANGLING_CONTINUATION",
                Severity.ERROR,
                "The INCAR ends during a continued statement.",
                {"line_start": start, "continued": continued},
            )
        )
        logical.append(_LogicalLine(" ".join(buffer), start or 1, len(text.splitlines())))
    return tuple(logical), tuple(diagnostics)


def _split_semicolons(text: str) -> tuple[str, ...]:
    segments: list[str] = []
    current: list[str] = []
    in_quote = False
    for character in text:
        if character == '"':
            in_quote = not in_quote
            current.append(character)
        elif character == ";" and not in_quote:
            segments.append("".join(current))
            current = []
        else:
            current.append(character)
    segments.append("".join(current))
    return tuple(segments)


def parse_incar_text(text: str) -> tuple[IncarSummary, tuple[Diagnostic, ...]]:
    """Parse assignments without allowing pymatgen to hide duplicate raw tags."""

    logical, line_diagnostics = _logical_lines(text)
    assignments: list[IncarAssignment] = []
    diagnostics = list(line_diagnostics)
    for line in logical:
        for segment in _split_semicolons(line.text):
            statement = segment.strip()
            if not statement:
                continue
            match = _ASSIGNMENT.match(statement)
            if match is None:
                if "=" in statement or any(char in statement for char in '{}"'):
                    diagnostics.append(
                        Diagnostic(
                            "INCAR_STATEMENT_INVALID",
                            Severity.ERROR,
                            "The statement does not use VASP 5.4.4 TAG = VALUE syntax.",
                            {
                                "line_start": line.line_start,
                                "line_end": line.line_end,
                                "statement": statement,
                            },
                        )
                    )
                continue
            tag = match.group(1).upper()
            value = match.group(2).strip()
            if not value:
                diagnostics.append(
                    Diagnostic(
                        "INCAR_VALUE_EMPTY",
                        Severity.ERROR,
                        "An INCAR assignment has no value.",
                        {"tag": tag, "line": line.line_start},
                    )
                )
            assignments.append(IncarAssignment(tag, value, line.line_start, line.line_end))

    summary = IncarSummary(tuple(assignments))
    for tag in summary.duplicate_tags:
        lines = [item.line_start for item in assignments if item.tag == tag]
        diagnostics.append(
            Diagnostic(
                "INCAR_DUPLICATE_TAG",
                Severity.ERROR,
                "A tag occurs more than once; the intended effective value is ambiguous.",
                {"tag": tag, "lines": lines},
            )
        )
    return summary, tuple(diagnostics)


def parse_bool(value: str) -> bool:
    normalized = value.strip().strip('"').strip().upper().strip(".")
    if normalized in {"T", "TRUE"}:
        return True
    if normalized in {"F", "FALSE"}:
        return False
    raise ValueError(f"not a VASP logical value: {value}")


def parse_float(value: str) -> float:
    normalized = value.strip().strip('"').strip()
    if not _REAL.match(normalized):
        raise ValueError(f"not a VASP real value: {value}")
    return float(normalized.replace("D", "E").replace("d", "e"))


def parse_int(value: str) -> int:
    parsed = parse_float(value)
    if not parsed.is_integer():
        raise ValueError(f"not a VASP integer value: {value}")
    return int(parsed)


def expand_repeated_reals(value: str) -> tuple[float, ...]:
    """Expand VASP forms such as ``2*5.0 4*0``."""

    expanded: list[float] = []
    for token in value.strip().strip('"').split():
        match = _REPEATED_REAL.match(token)
        if match is None:
            raise ValueError(f"invalid repeated real token: {token}")
        count = int(match.group("count") or 1)
        if count <= 0:
            raise ValueError(f"repetition count must be positive: {token}")
        number = float(match.group("value").replace("D", "E").replace("d", "e"))
        expanded.extend([number] * count)
    if not expanded:
        raise ValueError("real array is empty")
    return tuple(expanded)


def _typed_value(
    summary: IncarSummary,
    tag: str,
    parser,
    diagnostics: list[Diagnostic],
):
    raw = summary.value(tag)
    if raw is None:
        return None
    try:
        return parser(raw)
    except (ValueError, OverflowError) as exc:
        diagnostics.append(
            Diagnostic(
                "INCAR_VALUE_INVALID",
                Severity.ERROR,
                "An INCAR value has the wrong scalar or array syntax.",
                {"tag": tag, "raw_value": raw, "reason": str(exc)},
            )
        )
        return None


def validate_incar(
    summary: IncarSummary,
    *,
    num_sites: int,
    num_species: int,
    mode: ValidationMode,
) -> tuple[Diagnostic, ...]:
    """Validate high-risk INCAR relationships for VASP 5.4.4."""

    diagnostics = list(validate_incar_registry(summary, mode=mode))
    for tag in sorted({item.tag for item in summary.assignments}):
        if tag.startswith(_POST_VASP5_PREFIXES):
            diagnostics.append(
                Diagnostic(
                    "INCAR_TAG_INCOMPATIBLE_WITH_VASP_5_4_4",
                    Severity.ERROR,
                    "This tag family belongs to post-VASP-5 functionality.",
                    {"tag": tag, "target_vasp_version": "5.4.4"},
                )
            )
    encut = _typed_value(summary, "ENCUT", parse_float, diagnostics)
    if encut is None and summary.value("ENCUT") is None:
        diagnostics.append(
            Diagnostic(
                "ENCUT_NOT_EXPLICIT",
                _policy(mode),
                "ENCUT should be explicit so energies remain comparable across POTCAR sets.",
            )
        )
    elif encut is not None and encut <= 0:
        diagnostics.append(
            Diagnostic("ENCUT_NONPOSITIVE", Severity.ERROR, "ENCUT must be positive.")
        )

    for tag in ("EDIFF", "SIGMA", "POTIM"):
        parsed = _typed_value(summary, tag, parse_float, diagnostics)
        if parsed is not None and parsed <= 0:
            diagnostics.append(
                Diagnostic(
                    f"{tag}_NONPOSITIVE",
                    Severity.ERROR,
                    f"{tag} must be positive when explicitly set.",
                )
            )
    for tag in ("NELM", "NELMIN", "KPAR", "NCORE"):
        parsed = _typed_value(summary, tag, parse_int, diagnostics)
        if parsed is not None and parsed <= 0:
            diagnostics.append(
                Diagnostic(
                    f"{tag}_NONPOSITIVE",
                    Severity.ERROR,
                    f"{tag} must be a positive integer.",
                )
            )

    ispin = _typed_value(summary, "ISPIN", parse_int, diagnostics)
    ispin = 1 if ispin is None and summary.value("ISPIN") is None else ispin
    if ispin is not None and ispin not in {1, 2}:
        diagnostics.append(
            Diagnostic("ISPIN_INVALID", Severity.ERROR, "ISPIN must be either 1 or 2.")
        )
    lnoncollinear = _typed_value(summary, "LNONCOLLINEAR", parse_bool, diagnostics)
    lsorbit = _typed_value(summary, "LSORBIT", parse_bool, diagnostics)
    noncollinear = bool(lnoncollinear or lsorbit)
    magmom_raw = summary.value("MAGMOM")
    magmom = None
    if magmom_raw is not None:
        magmom = _typed_value(summary, "MAGMOM", expand_repeated_reals, diagnostics)
    magnetic = ispin == 2 or noncollinear
    if magnetic and magmom is None and magmom_raw is None:
        diagnostics.append(
            Diagnostic(
                "MAGMOM_NOT_EXPLICIT",
                _policy(mode),
                "Magnetic calculations should explicitly define initial moments.",
            )
        )
    if magmom is not None:
        expected = 3 * num_sites if noncollinear else num_sites
        if len(magmom) != expected:
            diagnostics.append(
                Diagnostic(
                    "MAGMOM_LENGTH_MISMATCH",
                    Severity.ERROR,
                    "Expanded MAGMOM length does not match the magnetic mode and NIONS.",
                    {
                        "actual_values": len(magmom),
                        "expected_values": expected,
                        "num_sites": num_sites,
                        "noncollinear": noncollinear,
                    },
                )
            )
        if not magnetic:
            diagnostics.append(
                Diagnostic(
                    "MAGMOM_WITH_NONMAGNETIC_MODE",
                    Severity.WARNING,
                    "MAGMOM is present while ISPIN defaults to or equals 1.",
                )
            )
    if noncollinear and ispin == 2:
        diagnostics.append(
            Diagnostic(
                "ISPIN_IGNORED_NONCOLLINEAR",
                Severity.WARNING,
                "In noncollinear mode ISPIN is not the controlling magnetic switch.",
            )
        )
    if lsorbit:
        diagnostics.append(
            Diagnostic(
                "VASP_NCL_EXECUTABLE_REQUIRED",
                Severity.INFO,
                "LSORBIT requires the noncollinear VASP executable and PAW potentials.",
            )
        )

    nsw = _typed_value(summary, "NSW", parse_int, diagnostics)
    nsw = 0 if nsw is None and summary.value("NSW") is None else nsw
    ibrion = _typed_value(summary, "IBRION", parse_int, diagnostics)
    ibrion = -1 if ibrion is None and summary.value("IBRION") is None else ibrion
    if nsw is not None and nsw < 0:
        diagnostics.append(Diagnostic("NSW_NEGATIVE", Severity.ERROR, "NSW cannot be negative."))
    if nsw and nsw > 0 and ibrion == -1:
        diagnostics.append(
            Diagnostic(
                "IONIC_STEPS_WITHOUT_MOTION_ALGORITHM",
                _policy(mode),
                "NSW is positive while IBRION is absent or -1.",
            )
        )
    if summary.value("EDIFFG") is not None and (nsw is None or nsw <= 0):
        diagnostics.append(
            Diagnostic(
                "EDIFFG_WITHOUT_IONIC_STEPS",
                Severity.WARNING,
                "EDIFFG has no ionic convergence role when NSW is zero.",
            )
        )

    ldau = _typed_value(summary, "LDAU", parse_bool, diagnostics)
    if ldau:
        for tag, parser in (
            ("LDAUL", expand_repeated_reals),
            ("LDAUU", expand_repeated_reals),
            ("LDAUJ", expand_repeated_reals),
        ):
            values = _typed_value(summary, tag, parser, diagnostics)
            if values is None and summary.value(tag) is None:
                diagnostics.append(
                    Diagnostic(
                        f"{tag}_MISSING",
                        _policy(mode),
                        f"{tag} should be explicit when LDAU is enabled.",
                    )
                )
            elif values is not None and len(values) != num_species:
                diagnostics.append(
                    Diagnostic(
                        f"{tag}_SPECIES_COUNT_MISMATCH",
                        Severity.ERROR,
                        f"{tag} must contain one value per POSCAR species.",
                        {"actual_values": len(values), "expected_values": num_species},
                    )
                )
        lasph = _typed_value(summary, "LASPH", parse_bool, diagnostics)
        if not lasph:
            diagnostics.append(
                Diagnostic(
                    "LASPH_RECOMMENDED_FOR_LDAU",
                    Severity.WARNING,
                    "Review LASPH for DFT+U calculations instead of relying on its default.",
                )
            )

    lsol = _typed_value(summary, "LSOL", parse_bool, diagnostics)
    if lsol:
        diagnostics.append(
            Diagnostic(
                "VASPSOL_CAPABILITY_REQUIRES_RUNTIME_CHECK",
                Severity.WARNING,
                "LSOL is requested; the selected HPC executable must be VASPsol-enabled.",
            )
        )
    return tuple(diagnostics)
