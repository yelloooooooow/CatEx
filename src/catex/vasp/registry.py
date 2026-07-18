"""Explicit CatEx support registry for INCAR tags used with VASP 5.4.4."""

from __future__ import annotations

import re
from dataclasses import dataclass
from enum import StrEnum
from types import MappingProxyType
from typing import Any

from catex.models import Diagnostic, Severity
from catex.vasp.models import IncarSummary, ValidationMode

_REAL = re.compile(r"^[+-]?(?:\d+(?:\.\d*)?|\.\d+)(?:[EeDd][+-]?\d+)?$")
_REPEATED_REAL = re.compile(
    r"^(?:(?P<count>\d+)\*)?(?P<value>[+-]?(?:\d+(?:\.\d*)?|\.\d+)(?:[EeDd][+-]?\d+)?)$"
)
_KEYWORD = re.compile(r"^[A-Za-z][A-Za-z0-9_.+-]*$")


class IncarValueKind(StrEnum):
    """Syntax kind accepted at the protocol boundary."""

    INTEGER = "integer"
    KEYWORD = "keyword"
    LOGICAL = "logical"
    LOGICAL_OR_KEYWORD = "logical_or_keyword"
    REAL = "real"
    REAL_ARRAY = "real_array"
    TEXT = "text"


@dataclass(frozen=True, slots=True)
class IncarTagRule:
    """One deliberately supported tag, not a claim about every VASP feature."""

    tag: str
    value_kind: IncarValueKind
    energy_family_relevant: bool = True
    provider: str = "vasp-5.4.4"
    fixed_array_length: int | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "tag": self.tag,
            "value_kind": self.value_kind.value,
            "energy_family_relevant": self.energy_family_relevant,
            "provider": self.provider,
            "fixed_array_length": self.fixed_array_length,
        }


@dataclass(frozen=True, slots=True)
class Vasp544IncarRegistry:
    """Serializable snapshot of the supported-tag boundary."""

    rules: tuple[IncarTagRule, ...]
    target_vasp_version: str = "5.4.4"
    schema_version: str = "catex.vasp544-incar-registry.v1"

    @property
    def diagnostics(self) -> tuple[Diagnostic, ...]:
        return ()

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "target_vasp_version": self.target_vasp_version,
            "scope": "catex-supported-tags-not-exhaustive-vasp-manual",
            "rules": [item.to_dict() for item in self.rules],
        }


def _rule(
    tag: str,
    value_kind: IncarValueKind,
    *,
    energy: bool = True,
    provider: str = "vasp-5.4.4",
    fixed_array_length: int | None = None,
) -> IncarTagRule:
    return IncarTagRule(tag, value_kind, energy, provider, fixed_array_length)


_RULE_LIST = (
    _rule("ADDGRID", IncarValueKind.LOGICAL),
    _rule("ALGO", IncarValueKind.KEYWORD),
    _rule("AMIX", IncarValueKind.REAL),
    _rule("AMIX_MAG", IncarValueKind.REAL),
    _rule("BMIX", IncarValueKind.REAL),
    _rule("BMIX_MAG", IncarValueKind.REAL),
    _rule("CSHIFT", IncarValueKind.REAL),
    _rule("DIPOL", IncarValueKind.REAL_ARRAY, fixed_array_length=3),
    _rule("EB_K", IncarValueKind.REAL, provider="vaspsol-1.0"),
    _rule("EDIFF", IncarValueKind.REAL),
    _rule("EDIFFG", IncarValueKind.REAL),
    _rule("EMAX", IncarValueKind.REAL),
    _rule("EMIN", IncarValueKind.REAL),
    _rule("ENAUG", IncarValueKind.REAL),
    _rule("ENCUT", IncarValueKind.REAL),
    _rule("FERDO", IncarValueKind.REAL_ARRAY),
    _rule("FERWE", IncarValueKind.REAL_ARRAY),
    _rule("GGA", IncarValueKind.KEYWORD),
    _rule("GGA_COMPAT", IncarValueKind.LOGICAL),
    _rule("IBRION", IncarValueKind.INTEGER),
    _rule("ICHARG", IncarValueKind.INTEGER),
    _rule("IDIPOL", IncarValueKind.INTEGER),
    _rule("ISIF", IncarValueKind.INTEGER),
    _rule("ISMEAR", IncarValueKind.INTEGER),
    _rule("ISPIN", IncarValueKind.INTEGER),
    _rule("ISTART", IncarValueKind.INTEGER),
    _rule("ISYM", IncarValueKind.INTEGER),
    _rule("IVDW", IncarValueKind.INTEGER),
    _rule("KPAR", IncarValueKind.INTEGER, energy=False),
    _rule("LAECHG", IncarValueKind.LOGICAL),
    _rule("LAMBDA_D_K", IncarValueKind.REAL, provider="vaspsol-1.0"),
    _rule("LASPH", IncarValueKind.LOGICAL),
    _rule("LCALCEPS", IncarValueKind.LOGICAL),
    _rule("LCALCPOL", IncarValueKind.LOGICAL),
    _rule("LCHARG", IncarValueKind.LOGICAL, energy=False),
    _rule("LDAU", IncarValueKind.LOGICAL),
    _rule("LDAUJ", IncarValueKind.REAL_ARRAY),
    _rule("LDAUL", IncarValueKind.REAL_ARRAY),
    _rule("LDAUPRINT", IncarValueKind.INTEGER),
    _rule("LDAUTYPE", IncarValueKind.INTEGER),
    _rule("LDAUU", IncarValueKind.REAL_ARRAY),
    _rule("LDIPOL", IncarValueKind.LOGICAL),
    _rule("LELF", IncarValueKind.LOGICAL),
    _rule("LEPSILON", IncarValueKind.LOGICAL),
    _rule("LMAXMIX", IncarValueKind.INTEGER),
    _rule("LMAXPAW", IncarValueKind.INTEGER),
    _rule("LNONCOLLINEAR", IncarValueKind.LOGICAL),
    _rule("LOPTICS", IncarValueKind.LOGICAL),
    _rule("LORBIT", IncarValueKind.INTEGER),
    _rule("LPLANE", IncarValueKind.LOGICAL, energy=False),
    _rule("LREAL", IncarValueKind.LOGICAL_OR_KEYWORD),
    _rule("LSORBIT", IncarValueKind.LOGICAL),
    _rule("LSOL", IncarValueKind.LOGICAL, provider="vaspsol-1.0"),
    _rule("LVHAR", IncarValueKind.LOGICAL),
    _rule("LVTOT", IncarValueKind.LOGICAL),
    _rule("LWAVE", IncarValueKind.LOGICAL, energy=False),
    _rule("MAGMOM", IncarValueKind.REAL_ARRAY),
    _rule("MDALGO", IncarValueKind.INTEGER),
    _rule("METAGGA", IncarValueKind.KEYWORD),
    _rule("NBANDS", IncarValueKind.INTEGER),
    _rule("NC_K", IncarValueKind.REAL, provider="vaspsol-1.0"),
    _rule("NCORE", IncarValueKind.INTEGER, energy=False),
    _rule("NEDOS", IncarValueKind.INTEGER),
    _rule("NELECT", IncarValueKind.REAL),
    _rule("NELM", IncarValueKind.INTEGER),
    _rule("NELMDL", IncarValueKind.INTEGER),
    _rule("NELMIN", IncarValueKind.INTEGER),
    _rule("NPAR", IncarValueKind.INTEGER, energy=False),
    _rule("NSIM", IncarValueKind.INTEGER, energy=False),
    _rule("NSW", IncarValueKind.INTEGER),
    _rule("NUPDOWN", IncarValueKind.REAL),
    _rule("NWRITE", IncarValueKind.INTEGER, energy=False),
    _rule("POTIM", IncarValueKind.REAL),
    _rule("PREC", IncarValueKind.KEYWORD),
    _rule("PSTRESS", IncarValueKind.REAL),
    _rule("ROPT", IncarValueKind.REAL_ARRAY),
    _rule("RWIGS", IncarValueKind.REAL_ARRAY),
    _rule("SAXIS", IncarValueKind.REAL_ARRAY, fixed_array_length=3),
    _rule("SIGMA", IncarValueKind.REAL),
    _rule("SMASS", IncarValueKind.REAL),
    _rule("SYSTEM", IncarValueKind.TEXT, energy=False),
    _rule("TAU", IncarValueKind.REAL, provider="vaspsol-1.0"),
    _rule("TEBEG", IncarValueKind.REAL),
    _rule("TEEND", IncarValueKind.REAL),
    _rule("VOSKOWN", IncarValueKind.LOGICAL),
)

INCAR_TAG_RULES = MappingProxyType({item.tag: item for item in _RULE_LIST})


def vasp544_incar_registry() -> Vasp544IncarRegistry:
    """Return the stable, sorted registry snapshot."""

    return Vasp544IncarRegistry(tuple(sorted(_RULE_LIST, key=lambda item: item.tag)))


def is_energy_family_relevant(tag: str) -> bool:
    """Return the registered compatibility policy for a normalized tag."""

    rule = INCAR_TAG_RULES.get(tag.upper())
    if rule is None:
        raise KeyError(f"INCAR tag is not registered: {tag}")
    return rule.energy_family_relevant


def _parse_logical(value: str) -> None:
    normalized = value.strip().strip('"').upper().strip(".")
    if normalized not in {"T", "TRUE", "F", "FALSE"}:
        raise ValueError("expected a VASP logical value")


def _parse_real(value: str) -> None:
    if _REAL.fullmatch(value.strip().strip('"')) is None:
        raise ValueError("expected a real value")


def _parse_integer(value: str) -> None:
    normalized = value.strip().strip('"')
    if _REAL.fullmatch(normalized) is None:
        raise ValueError("expected an integer value")
    if not float(normalized.replace("D", "E").replace("d", "e")).is_integer():
        raise ValueError("expected an integer value")


def _parse_array(value: str) -> int:
    count = 0
    for token in value.strip().strip('"').split():
        match = _REPEATED_REAL.fullmatch(token)
        if match is None:
            raise ValueError("expected a whitespace-separated real array")
        repetitions = int(match.group("count") or 1)
        if repetitions <= 0:
            raise ValueError("array repetition counts must be positive")
        count += repetitions
    if count == 0:
        raise ValueError("real array must not be empty")
    return count


def _validate_value(rule: IncarTagRule, value: str) -> None:
    if rule.value_kind is IncarValueKind.LOGICAL:
        _parse_logical(value)
    elif rule.value_kind is IncarValueKind.INTEGER:
        _parse_integer(value)
    elif rule.value_kind is IncarValueKind.REAL:
        _parse_real(value)
    elif rule.value_kind is IncarValueKind.REAL_ARRAY:
        count = _parse_array(value)
        if rule.fixed_array_length is not None and count != rule.fixed_array_length:
            raise ValueError(f"expected exactly {rule.fixed_array_length} array values")
    elif rule.value_kind is IncarValueKind.KEYWORD:
        if _KEYWORD.fullmatch(value.strip().strip('"')) is None:
            raise ValueError("expected one keyword token")
    elif rule.value_kind is IncarValueKind.LOGICAL_OR_KEYWORD:
        try:
            _parse_logical(value)
        except ValueError:
            if _KEYWORD.fullmatch(value.strip().strip('"')) is None:
                raise ValueError("expected a logical value or one keyword token") from None
    elif not value.strip():
        raise ValueError("text must not be empty")


def validate_incar_registry(
    summary: IncarSummary,
    *,
    mode: ValidationMode,
) -> tuple[Diagnostic, ...]:
    """Reject unsupported protocol tags in strict mode and validate registered syntax."""

    diagnostics: list[Diagnostic] = []
    for assignment in summary.assignments:
        rule = INCAR_TAG_RULES.get(assignment.tag)
        if rule is None:
            severity = Severity.ERROR if mode is ValidationMode.STRICT else Severity.WARNING
            diagnostics.append(
                Diagnostic(
                    "INCAR_TAG_NOT_IN_VASP544_REGISTRY",
                    severity,
                    "The tag is outside the current CatEx VASP 5.4.4 support registry.",
                    {"tag": assignment.tag, "line": assignment.line_start},
                )
            )
            continue
        try:
            _validate_value(rule, assignment.raw_value)
        except ValueError as exc:
            diagnostics.append(
                Diagnostic(
                    "INCAR_REGISTERED_VALUE_INVALID",
                    Severity.ERROR,
                    str(exc),
                    {
                        "tag": assignment.tag,
                        "line": assignment.line_start,
                        "value_kind": rule.value_kind.value,
                    },
                )
            )
    return tuple(diagnostics)
