"""Conservative extraction of common characterization summaries.

The extractor intentionally handles only transparent text/CSV conventions and
explicit statements supplied by the researcher.  It never assigns an XPS
oxidation state from an unfitted spectrum or measures a lattice fringe from a
TEM image.
"""

from __future__ import annotations

import csv
import io
import math
import re
from collections.abc import Mapping
from itertools import pairwise
from pathlib import Path
from typing import Any

from pymatgen.core import Composition, Element

_TEXT_SUFFIXES = {".csv", ".dat", ".txt", ".tsv", ".xy"}
_ELEMENT = re.compile(r"^[A-Z][a-z]?$")
_FLOAT = re.compile(r"[-+]?(?:\d+(?:\.\d*)?|\.\d+)(?:[Ee][-+]?\d+)?")
_D_SPACING = re.compile(
    r"(?i)(?:\bd(?:[-_ ]?spacing)?|(?:晶格|晶面)间距\s*d?)\s*(?:=|:|为)?\s*"
    r"(\d+(?:\.\d+)?)\s*"
    r"(?:±|\+/-)?\s*(\d+(?:\.\d+)?)?\s*(Å|Å|angstroms?|a\b|nm\b)"
)
_PHASE_FORMULA = re.compile(
    r"(?i)(?:indexed|assigned|identified|matched)\s+(?:entirely\s+)?(?:to|as)\s+"
    r"(?:the\s+)?([A-Z][A-Za-z0-9.()·+-]{1,39})(?:\s+phase)?"
)
_PHASE_FORMULA_ZH = re.compile(
    r"(?:归属(?:于|为)?|对应(?:于)?|鉴定为|匹配为|物相为)\s*"
    r"([A-Z][A-Za-z0-9.()·+-]{1,39})"
)
_RADIATION = re.compile(r"(?i)\b(?:cu|copper)\s*k\s*(?:\u03b1|alpha|a)(?:1)?\b")
_XPS_SOURCE = re.compile(r"(?i)\b(al|mg)\s*k\s*(?:\u03b1|alpha|a)\b")
_VOLTAGE = re.compile(r"(?i)\b(\d+(?:\.\d+)?)\s*kV\b")
_INCIDENCE = re.compile(
    r"(?i)\b(?:incidence|incident|\u5165\u5c04)(?:\s+angle|\u89d2)?\s*(?:=|:)?\s*"
    r"(\d+(?:\.\d+)?)\s*(?:deg(?:ree)?s?|\u00b0)"
)
_OXIDIZED = re.compile(
    r"(?i)\b([A-Z][a-z]?)\s*(?:[-\u2013\u2014]\s*O|oxide|oxidized|"
    r"\([2345678]\+\)|[2345678]\+)"
)


def _normalized_header(value: str) -> str:
    return re.sub(r"[^a-z0-9%]+", "_", value.strip().lower()).strip("_")


def _finite(value: str | None) -> float | None:
    if value is None:
        return None
    match = _FLOAT.search(value.replace("%", ""))
    if match is None:
        return None
    result = float(match.group())
    return result if math.isfinite(result) else None


def _read_text(path: Path) -> tuple[str | None, list[str]]:
    if path.suffix.lower() not in _TEXT_SUFFIXES:
        return None, [
            "The uploaded file is retained, but automatic extraction supports "
            "text and CSV files only."
        ]
    try:
        return path.read_text(encoding="utf-8-sig", errors="strict"), []
    except UnicodeDecodeError:
        return None, [
            "The uploaded text file could not be decoded as UTF-8; enter a short "
            "conclusion manually."
        ]


def _table(text: str) -> list[dict[str, str]]:
    lines = [
        line for line in text.splitlines() if line.strip() and not line.lstrip().startswith("#")
    ]
    if len(lines) < 2:
        return []
    sample = "\n".join(lines[:20])
    try:
        dialect = csv.Sniffer().sniff(sample, delimiters=",;\t")
    except csv.Error:
        dialect = csv.excel
        if all("," not in line and ";" not in line and "\t" not in line for line in lines[:2]):
            return []
    reader = csv.DictReader(io.StringIO("\n".join(lines)), dialect=dialect)
    if not reader.fieldnames:
        return []
    field_map = {field: _normalized_header(field) for field in reader.fieldnames if field}
    return [
        {field_map[key]: (value or "").strip() for key, value in row.items() if key in field_map}
        for row in reader
    ]


def _first(row: Mapping[str, str], names: tuple[str, ...]) -> str | None:
    for name in names:
        if name in row and row[name].strip():
            return row[name]
    return None


def _element(value: str | None) -> str | None:
    if value is None:
        return None
    raw = value.strip()
    match = re.match(r"^([A-Z][a-z]?)", raw)
    if match is None or _ELEMENT.fullmatch(match.group(1)) is None:
        return None
    try:
        return Element(match.group(1)).symbol
    except ValueError:
        return None


def _reported_phase_formulas(text: str) -> list[str]:
    """Return only explicitly assigned phase formulas from prose."""

    formulas: list[str] = []
    for match in (*_PHASE_FORMULA.finditer(text), *_PHASE_FORMULA_ZH.finditer(text)):
        candidate = match.group(1).rstrip(".,;:")
        try:
            composition = Composition(candidate)
        except (TypeError, ValueError):
            continue
        if not composition.elements:
            continue
        formula = composition.reduced_formula
        if formula not in formulas:
            formulas.append(formula)
    return formulas


def _fraction_interval(
    value: float,
    uncertainty: float | None,
    *,
    percent: bool,
) -> tuple[float, float]:
    scale = 100.0 if percent else 1.0
    center = value / scale
    spread = (uncertainty / scale) if uncertainty is not None else max(0.005, 0.05 * center)
    return max(0.0, center - spread), min(1.0, center + spread)


def _composition_rows(
    rows: list[dict[str, str]],
    *,
    kind: str,
    evidence_id: str,
) -> list[dict[str, Any]]:
    constraints: list[dict[str, Any]] = []
    for row in rows:
        element = _element(_first(row, ("element", "symbol", "species")))
        if element is None:
            continue
        atomic_percent = _first(
            row,
            (
                "atomic_percent",
                "atomic",
                "at_percent",
                "at",
                "atom_percent",
                "metal_atomic_percent",
                "metal_at_percent",
            ),
        )
        atomic_fraction = _first(
            row,
            (
                "atomic_fraction",
                "atom_fraction",
                "at_fraction",
                "metal_atomic_fraction",
                "metal_fraction",
            ),
        )
        weight = _first(row, ("weight_percent", "wt_percent", "wt", "mass_percent"))
        generic = _first(row, ("value", "fraction", "composition", "percent"))
        raw_value = atomic_percent or atomic_fraction or weight or generic
        value = _finite(raw_value)
        if value is None:
            continue
        unit_text = " ".join(row.values()).lower()
        if weight is not None or "wt" in unit_text or "weight" in unit_text:
            basis = "weight_fraction"
        elif "metal" in unit_text or any(key.startswith("metal_") for key in row):
            basis = "metal_normalized_atomic_fraction"
        else:
            basis = "total_atomic_fraction"
        percent = (
            atomic_percent is not None
            or weight is not None
            or "%" in (raw_value or "")
            or value > 1
            or any(token in unit_text for token in ("percent", "at.%", "wt.%"))
        )
        uncertainty = _finite(_first(row, ("uncertainty", "error", "std", "sigma", "plus_minus")))
        lower, upper = _fraction_interval(value, uncertainty, percent=percent)
        scope = "bulk" if kind == "icp" else "surface" if kind == "xps" else "local"
        constraints.append(
            {
                "element": element,
                "minimum_atomic_fraction": lower,
                "maximum_atomic_fraction": upper,
                "scope": scope,
                "basis": basis,
                "evidence_ids": [evidence_id],
            }
        )
    return constraints


def _xps_environment_rows(
    rows: list[dict[str, str]],
    *,
    evidence_id: str,
) -> list[dict[str, Any]]:
    groups: dict[str, list[tuple[bool, float]]] = {}
    for row in rows:
        element = _element(_first(row, ("element", "symbol", "species", "core_level")))
        assignment = _first(row, ("state", "assignment", "chemical_state", "component", "species"))
        fraction = _finite(
            _first(
                row,
                ("area_fraction", "fraction", "relative_area", "percent", "area_percent"),
            )
        )
        if element is None or assignment is None or fraction is None:
            continue
        text = assignment.lower()
        oxidized = any(token in text for token in ("-o", "oxide", "oxid", "oh", "+"))
        groups.setdefault(element, []).append((oxidized, fraction))
    constraints: list[dict[str, Any]] = []
    for element, values in sorted(groups.items()):
        total = sum(value for _, value in values)
        if total <= 0 or not any(oxidized for oxidized, _ in values):
            continue
        oxidized_fraction = sum(value for oxidized, value in values if oxidized) / total
        lower, upper = _fraction_interval(oxidized_fraction, None, percent=False)
        constraints.append(
            {
                "element": element,
                "neighbor_element": "O",
                "minimum_site_fraction": lower,
                "maximum_site_fraction": upper,
                "cutoff_angstrom": 2.6,
                "scope": "surface",
                "evidence_ids": [evidence_id],
            }
        )
    return constraints


def _spacing_rows(rows: list[dict[str, str]], *, evidence_id: str) -> list[dict[str, Any]]:
    constraints: list[dict[str, Any]] = []
    for row in rows:
        spacing = _finite(_first(row, ("d_spacing_angstrom", "d_spacing", "spacing_angstrom", "d")))
        if spacing is None or spacing <= 0:
            continue
        tolerance = _finite(
            _first(row, ("tolerance_angstrom", "uncertainty_angstrom", "uncertainty", "error"))
        )
        constraints.append(
            {
                "d_spacing_angstrom": spacing,
                "tolerance_angstrom": tolerance or max(0.03, spacing * 0.02),
                "evidence_ids": [evidence_id],
            }
        )
    return constraints


def extract_characterization_summary(
    path: str | Path | None,
    *,
    kind: str,
    evidence_id: str,
    conclusion: str = "",
    instrument_info: str = "",
) -> dict[str, Any]:
    """Extract bounded suggestions from one uploaded artifact and short note."""

    source = Path(path) if path is not None else None
    if source is None:
        text, notices = None, []
    else:
        text, notices = _read_text(source)
    rows = _table(text) if text is not None else []
    combined = "\n".join(item for item in (conclusion, instrument_info, text or "") if item)
    metadata: dict[str, Any] = {
        "automatic_extraction": {
            "source_filename": source.name if source is not None else None,
            "text_table_detected": bool(rows),
            "method": "transparent-rule-parser-v1",
        }
    }
    if conclusion.strip():
        metadata["brief_conclusion"] = conclusion.strip()
    if instrument_info.strip():
        metadata["instrument_info"] = instrument_info.strip()
    if kind in {"xrd", "gixrd"} and text is not None:
        numeric_pairs = []
        for line in text.splitlines():
            values = _FLOAT.findall(line.replace(",", " "))
            if len(values) >= 2:
                numeric_pairs.append((float(values[0]), float(values[1])))
        if len(numeric_pairs) >= 5:
            angles = sorted({item[0] for item in numeric_pairs})
            metadata["xrd_scan"] = {
                "point_count": len(numeric_pairs),
                "two_theta_min_degrees": angles[0],
                "two_theta_max_degrees": angles[-1],
                "median_step_degrees": sorted(b - a for a, b in pairwise(angles) if b > a)[
                    max(0, (len(angles) - 2) // 2)
                ]
                if len(angles) > 1
                else None,
            }
    if _RADIATION.search(combined):
        metadata["radiation"] = "CuKa"
    if match := _XPS_SOURCE.search(combined):
        metadata["xps_source"] = f"{match.group(1).title()}Ka"
    if match := _VOLTAGE.search(combined):
        metadata["accelerating_voltage_kv"] = float(match.group(1))
    if match := _INCIDENCE.search(combined):
        metadata["incidence_angle_degrees"] = float(match.group(1))
    if kind == "gixrd" or re.search(r"(?i)\bGI[- ]?XRD\b|grazing", combined):
        metadata["geometry"] = "grazing_incidence"

    reported_phases = _reported_phase_formulas(conclusion) if kind in {"xrd", "gixrd"} else []
    if reported_phases:
        metadata["reported_phase_formulas"] = reported_phases

    composition = _composition_rows(rows, kind=kind, evidence_id=evidence_id)
    local_environments = (
        _xps_environment_rows(rows, evidence_id=evidence_id) if kind == "xps" else []
    )
    spacings = _spacing_rows(rows, evidence_id=evidence_id) if kind == "tem" else []

    if kind == "xps" and not local_environments:
        oxidized_elements = sorted(
            {
                element
                for match in _OXIDIZED.finditer(conclusion)
                if (element := _element(match.group(1))) is not None
            }
        )
        for element in oxidized_elements:
            local_environments.append(
                {
                    "element": element,
                    "neighbor_element": "O",
                    "minimum_site_fraction": 0.01,
                    "maximum_site_fraction": 1.0,
                    "cutoff_angstrom": 2.6,
                    "scope": "surface",
                    "evidence_ids": [evidence_id],
                }
            )
        if oxidized_elements:
            notices.append(
                "An oxygen-coordination presence constraint was inferred from the brief "
                "conclusion; confirm the range before treating it as mandatory."
            )
    if kind == "tem" and not spacings:
        for match in _D_SPACING.finditer(conclusion):
            scale = 10.0 if match.group(3).lower() == "nm" else 1.0
            spacing = float(match.group(1)) * scale
            tolerance = (
                float(match.group(2)) * scale if match.group(2) else max(0.03, spacing * 0.02)
            )
            spacings.append(
                {
                    "d_spacing_angstrom": spacing,
                    "tolerance_angstrom": tolerance,
                    "evidence_ids": [evidence_id],
                }
            )
    if kind == "xps" and text is not None and not rows:
        notices.append(
            "No fitted XPS peak table was recognized; the raw spectrum was retained "
            "without automatic oxidation-state assignment."
        )
    if (
        kind == "tem"
        and source is not None
        and source.suffix.lower() not in _TEXT_SUFFIXES
        and not spacings
    ):
        notices.append(
            "A TEM image alone is not converted into a lattice spacing; add a measured "
            "d-spacing or a table."
        )
    if kind in {"icp", "eds"} and not composition:
        notices.append(
            "No composition table was recognized; add element ranges manually or use "
            "element/value/unit columns."
        )

    suggested_elements = {
        item["element"] for item in composition if isinstance(item.get("element"), str)
    }
    for formula in reported_phases:
        suggested_elements.update(element.symbol for element in Composition(formula).elements)

    return {
        "schema_version": "catex.evidence-extraction.v1",
        "metadata": metadata,
        "composition_constraints": composition,
        "local_environment_constraints": local_environments,
        "lattice_spacing_constraints": spacings,
        "suggested_elements": sorted(suggested_elements),
        "notices": list(dict.fromkeys(notices)),
        "automatic": True,
        "review_required": True,
    }
