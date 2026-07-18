from __future__ import annotations

import pytest

from catex.models import Severity
from catex.vasp.incar import (
    expand_repeated_reals,
    parse_bool,
    parse_float,
    parse_incar_text,
    parse_int,
    validate_incar,
)
from catex.vasp.models import ValidationMode


def _codes(diagnostics) -> set[str]:
    return {item.code for item in diagnostics}


def _summary(text: str):
    summary, diagnostics = parse_incar_text(text)
    assert not any(item.severity is Severity.ERROR for item in diagnostics)
    return summary


def test_raw_parser_preserves_semicolon_assignments_and_ignores_comments() -> None:
    summary, diagnostics = parse_incar_text(
        'header without syntax\nISMEAR = 0; SIGMA = 0.05 ! comment\nSYSTEM = "A#B"\n'
    )

    assert diagnostics == ()
    assert summary.value("ismear") == "0"
    assert summary.value("SIGMA") == "0.05"
    assert summary.value("SYSTEM") == '"A#B"'


def test_raw_parser_joins_backslash_continuation() -> None:
    summary, diagnostics = parse_incar_text("MAGMOM = 2*1 \\\n  2*0\n")

    assert diagnostics == ()
    assert expand_repeated_reals(summary.value("MAGMOM") or "") == (1.0, 1.0, 0.0, 0.0)


def test_raw_parser_reports_duplicate_case_insensitively() -> None:
    summary, diagnostics = parse_incar_text("ENCUT=400\nencut=500\n")

    assert summary.duplicate_tags == ("ENCUT",)
    duplicate = next(item for item in diagnostics if item.code == "INCAR_DUPLICATE_TAG")
    assert duplicate.severity is Severity.ERROR
    assert duplicate.context["lines"] == [1, 2]


@pytest.mark.parametrize(
    ("text", "expected_code"),
    [
        ('SYSTEM = "unterminated\n', "INCAR_UNTERMINATED_QUOTE"),
        ("MAGMOM = 2*1 \\", "INCAR_DANGLING_CONTINUATION"),
        ("ENCUT =\n", "INCAR_VALUE_EMPTY"),
        ("PLUGINS { STRUCTURE = T }\n", "INCAR_STATEMENT_INVALID"),
    ],
)
def test_raw_parser_reports_unsafe_syntax(text, expected_code) -> None:
    _, diagnostics = parse_incar_text(text)

    assert expected_code in _codes(diagnostics)


def test_continuation_trailing_whitespace_is_visible() -> None:
    _, diagnostics = parse_incar_text("MAGMOM = 1*1 \\   \n1*0\n")

    assert "INCAR_CONTINUATION_TRAILING_WHITESPACE" in _codes(diagnostics)


@pytest.mark.parametrize(
    ("value", "expected"),
    [(".TRUE.", True), ("F", False), ('"true"', True)],
)
def test_parse_bool(value, expected) -> None:
    assert parse_bool(value) is expected


@pytest.mark.parametrize("value", ["maybe", "1"])
def test_parse_bool_rejects_invalid(value) -> None:
    with pytest.raises(ValueError):
        parse_bool(value)


def test_numeric_parsers_accept_fortran_exponents() -> None:
    assert parse_float("1D-5") == pytest.approx(1e-5)
    assert parse_int("2.0") == 2
    assert expand_repeated_reals("2*1.5 1D-1") == (1.5, 1.5, 0.1)


@pytest.mark.parametrize("value", ["2.5", "word"])
def test_parse_int_rejects_non_integer(value) -> None:
    with pytest.raises(ValueError):
        parse_int(value)


@pytest.mark.parametrize("value", ["0*1", "2*", ""])
def test_repeated_array_rejects_invalid_tokens(value) -> None:
    with pytest.raises(ValueError):
        expand_repeated_reals(value)


def test_collinear_magmom_expansion_matches_nions() -> None:
    summary = _summary("ENCUT=500\nISPIN=2\nMAGMOM=1*2 3*0\nNSW=0\n")

    diagnostics = validate_incar(summary, num_sites=4, num_species=2, mode=ValidationMode.STRICT)

    assert "MAGMOM_LENGTH_MISMATCH" not in _codes(diagnostics)
    assert not any(item.severity is Severity.ERROR for item in diagnostics)


def test_magmom_length_mismatch_is_always_error() -> None:
    summary = _summary("ENCUT=500\nISPIN=2\nMAGMOM=2*1\n")

    diagnostics = validate_incar(
        summary, num_sites=4, num_species=1, mode=ValidationMode.EXPLORATION
    )

    finding = next(item for item in diagnostics if item.code == "MAGMOM_LENGTH_MISMATCH")
    assert finding.severity is Severity.ERROR


def test_noncollinear_mode_requires_three_values_per_site() -> None:
    summary = _summary("ENCUT=500\nISPIN=2\nLNONCOLLINEAR=T\nLSORBIT=T\nMAGMOM=0 0 2 0 0 -2\n")

    diagnostics = validate_incar(summary, num_sites=2, num_species=1, mode=ValidationMode.STRICT)

    assert "MAGMOM_LENGTH_MISMATCH" not in _codes(diagnostics)
    assert "ISPIN_IGNORED_NONCOLLINEAR" in _codes(diagnostics)
    assert "VASP_NCL_EXECUTABLE_REQUIRED" in _codes(diagnostics)


def test_policy_findings_change_severity_but_syntax_does_not() -> None:
    summary = _summary("ISPIN=2\n")

    strict = validate_incar(summary, num_sites=1, num_species=1, mode=ValidationMode.STRICT)
    exploratory = validate_incar(
        summary, num_sites=1, num_species=1, mode=ValidationMode.EXPLORATION
    )

    assert (
        next(item for item in strict if item.code == "ENCUT_NOT_EXPLICIT").severity
        is Severity.ERROR
    )
    assert (
        next(item for item in exploratory if item.code == "ENCUT_NOT_EXPLICIT").severity
        is Severity.WARNING
    )
    assert (
        next(item for item in strict if item.code == "MAGMOM_NOT_EXPLICIT").severity
        is Severity.ERROR
    )


def test_ionic_and_scalar_relationships_are_checked() -> None:
    summary = _summary(
        "ENCUT=-1\nEDIFF=0\nSIGMA=-0.1\nNELM=0\nNSW=2\nEDIFFG=-0.02\nISPIN=1\nMAGMOM=1\n"
    )

    diagnostics = validate_incar(summary, num_sites=1, num_species=1, mode=ValidationMode.STRICT)
    codes = _codes(diagnostics)

    assert {
        "ENCUT_NONPOSITIVE",
        "EDIFF_NONPOSITIVE",
        "SIGMA_NONPOSITIVE",
        "NELM_NONPOSITIVE",
        "IONIC_STEPS_WITHOUT_MOTION_ALGORITHM",
        "MAGMOM_WITH_NONMAGNETIC_MODE",
    } <= codes


def test_ldau_arrays_follow_poscar_species_count() -> None:
    summary = _summary("ENCUT=500\nLDAU=T\nLDAUL=2 -1\nLDAUU=4.0\nLDAUJ=2*0\nLASPH=F\n")

    diagnostics = validate_incar(summary, num_sites=2, num_species=2, mode=ValidationMode.STRICT)
    codes = _codes(diagnostics)

    assert "LDAUU_SPECIES_COUNT_MISMATCH" in codes
    assert "LASPH_RECOMMENDED_FOR_LDAU" in codes


def test_vaspsol_request_is_never_silently_accepted() -> None:
    summary = _summary("ENCUT=500\nLSOL=.TRUE.\n")

    diagnostics = validate_incar(summary, num_sites=1, num_species=1, mode=ValidationMode.STRICT)

    assert "VASPSOL_CAPABILITY_REQUIRES_RUNTIME_CHECK" in _codes(diagnostics)


def test_post_vasp5_tag_family_is_rejected() -> None:
    summary = _summary("ENCUT=500\nML_MODE=run\n")

    diagnostics = validate_incar(
        summary, num_sites=1, num_species=1, mode=ValidationMode.EXPLORATION
    )

    finding = next(
        item for item in diagnostics if item.code == "INCAR_TAG_INCOMPATIBLE_WITH_VASP_5_4_4"
    )
    assert finding.severity is Severity.ERROR
