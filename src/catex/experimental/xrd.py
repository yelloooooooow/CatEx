"""Transparent powder-XRD parsing, forward simulation, and hypothesis ranking."""

from __future__ import annotations

import itertools
import math
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np
from pymatgen.analysis.diffraction.xrd import XRDCalculator
from pymatgen.core import Structure

from catex.experimental.providers import ProviderRegistry
from catex.models import Diagnostic, Severity


@dataclass(frozen=True, slots=True)
class XRDPattern:
    """Finite, sorted two-theta/intensity pattern retained in memory."""

    two_theta_degrees: tuple[float, ...]
    intensity: tuple[float, ...]
    source_name: str = "in-memory"
    skipped_lines: int = 0
    schema_version: str = "catex.xrd-pattern.v1"

    def __post_init__(self) -> None:
        x = np.asarray(self.two_theta_degrees, dtype=float)
        y = np.asarray(self.intensity, dtype=float)
        if x.ndim != 1 or y.ndim != 1 or len(x) != len(y) or len(x) < 5:
            raise ValueError("XRD pattern must contain at least five paired points")
        if not np.isfinite(x).all() or not np.isfinite(y).all():
            raise ValueError("XRD pattern values must be finite")
        if np.any(np.diff(x) <= 0):
            raise ValueError("XRD two-theta values must be strictly increasing")
        if np.max(y) <= 0:
            raise ValueError("XRD pattern must contain positive intensity")
        if self.skipped_lines < 0:
            raise ValueError("skipped_lines must be non-negative")

    def arrays(self) -> tuple[np.ndarray, np.ndarray]:
        return (
            np.asarray(self.two_theta_degrees, dtype=float),
            np.asarray(self.intensity, dtype=float),
        )

    def to_dict(self, *, include_points: bool = False) -> dict[str, Any]:
        x, y = self.arrays()
        result: dict[str, Any] = {
            "schema_version": self.schema_version,
            "source_name": self.source_name,
            "num_points": len(x),
            "two_theta_range_degrees": [float(x[0]), float(x[-1])],
            "intensity_range": [float(np.min(y)), float(np.max(y))],
            "skipped_lines": self.skipped_lines,
        }
        if include_points:
            result["two_theta_degrees"] = list(self.two_theta_degrees)
            result["intensity"] = list(self.intensity)
        return result


@dataclass(frozen=True, slots=True)
class XRDSearchSettings:
    """Explicit nuisance grid and ranking limits for the transparent baseline."""

    wavelength: str = "CuKa"
    shift_values_degrees: tuple[float, ...] = (-0.2, -0.1, 0.0, 0.1, 0.2)
    fwhm_values_degrees: tuple[float, ...] = (0.1, 0.2, 0.4)
    baseline_window_points: int = 0
    peak_relative_threshold: float = 0.05
    peak_tolerance_degrees: float = 0.25
    single_phase_pool: int = 8
    maximum_phases: int = 3
    complexity_penalty: float = 0.02
    minimum_supported_score: float = 0.55
    ambiguity_margin: float = 0.03

    def __post_init__(self) -> None:
        if not self.wavelength.strip():
            raise ValueError("wavelength must be non-empty")
        for name, values in (
            ("shift_values_degrees", self.shift_values_degrees),
            ("fwhm_values_degrees", self.fwhm_values_degrees),
        ):
            if not values or not all(math.isfinite(float(item)) for item in values):
                raise ValueError(f"{name} must contain finite values")
        if any(value <= 0 for value in self.fwhm_values_degrees):
            raise ValueError("FWHM values must be positive")
        if self.baseline_window_points < 0:
            raise ValueError("baseline_window_points must be non-negative")
        if not 0 < self.peak_relative_threshold < 1:
            raise ValueError("peak_relative_threshold must be between zero and one")
        if self.peak_tolerance_degrees <= 0:
            raise ValueError("peak_tolerance_degrees must be positive")
        if not 1 <= self.single_phase_pool <= 50:
            raise ValueError("single_phase_pool must be between 1 and 50")
        if not 1 <= self.maximum_phases <= 3:
            raise ValueError("maximum_phases must be between 1 and 3")
        if not 0 <= self.complexity_penalty < 1:
            raise ValueError("complexity_penalty must be in [0, 1)")
        if not 0 <= self.minimum_supported_score <= 1:
            raise ValueError("minimum_supported_score must be in [0, 1]")
        if not 0 <= self.ambiguity_margin <= 1:
            raise ValueError("ambiguity_margin must be in [0, 1]")

    def to_dict(self) -> dict[str, Any]:
        return {
            "wavelength": self.wavelength,
            "shift_values_degrees": list(self.shift_values_degrees),
            "fwhm_values_degrees": list(self.fwhm_values_degrees),
            "baseline_window_points": self.baseline_window_points,
            "peak_relative_threshold": self.peak_relative_threshold,
            "peak_tolerance_degrees": self.peak_tolerance_degrees,
            "single_phase_pool": self.single_phase_pool,
            "maximum_phases": self.maximum_phases,
            "complexity_penalty": self.complexity_penalty,
            "minimum_supported_score": self.minimum_supported_score,
            "ambiguity_margin": self.ambiguity_margin,
        }


@dataclass(frozen=True, slots=True)
class PeakMatchEvidence:
    """One-to-one peak support and counter-evidence for a single phase."""

    matched_pairs_degrees: tuple[tuple[float, float], ...]
    unexplained_observed_degrees: tuple[float, ...]
    missing_predicted_degrees: tuple[float, ...]

    def to_dict(self) -> dict[str, Any]:
        return {
            "matched_pairs_degrees": [list(item) for item in self.matched_pairs_degrees],
            "unexplained_observed_degrees": list(self.unexplained_observed_degrees),
            "missing_predicted_degrees": list(self.missing_predicted_degrees),
        }


@dataclass(frozen=True, slots=True)
class SinglePhaseMatch:
    """Best nuisance-grid fit for one database structure."""

    reference_key: str
    formula: str
    evidence_score: float
    cosine_similarity: float
    explained_intensity_fraction: float
    normalized_absolute_residual: float
    shift_degrees: float
    fwhm_degrees: float
    peak_evidence: PeakMatchEvidence

    def to_dict(self) -> dict[str, Any]:
        return {
            "reference_key": self.reference_key,
            "formula": self.formula,
            "evidence_score": self.evidence_score,
            "cosine_similarity": self.cosine_similarity,
            "explained_intensity_fraction": self.explained_intensity_fraction,
            "normalized_absolute_residual": self.normalized_absolute_residual,
            "shift_degrees": self.shift_degrees,
            "fwhm_degrees": self.fwhm_degrees,
            "peak_evidence": self.peak_evidence.to_dict(),
        }


@dataclass(frozen=True, slots=True)
class PhaseCombinationMatch:
    """Shared-nuisance non-negative fit of a bounded phase combination."""

    reference_keys: tuple[str, ...]
    formulas: tuple[str, ...]
    diffraction_contributions: tuple[float, ...]
    evidence_score: float
    cosine_similarity: float
    explained_intensity_fraction: float
    normalized_absolute_residual: float
    shift_degrees: float
    fwhm_degrees: float
    covered_required_elements: tuple[str, ...]
    missing_required_elements: tuple[str, ...]

    def to_dict(self) -> dict[str, Any]:
        return {
            "reference_keys": list(self.reference_keys),
            "formulas": list(self.formulas),
            "diffraction_contributions": list(self.diffraction_contributions),
            "contribution_interpretation": (
                "non-negative profile contributions; not mass or volume fractions"
            ),
            "evidence_score": self.evidence_score,
            "cosine_similarity": self.cosine_similarity,
            "explained_intensity_fraction": self.explained_intensity_fraction,
            "normalized_absolute_residual": self.normalized_absolute_residual,
            "shift_degrees": self.shift_degrees,
            "fwhm_degrees": self.fwhm_degrees,
            "covered_required_elements": list(self.covered_required_elements),
            "missing_required_elements": list(self.missing_required_elements),
        }


@dataclass(frozen=True, slots=True)
class PhaseSearchReport:
    """Ranked XRD hypotheses without an uncalibrated probability claim."""

    pattern: XRDPattern
    settings: XRDSearchSettings
    considered_reference_keys: tuple[str, ...]
    single_phase_matches: tuple[SinglePhaseMatch, ...]
    combination_matches: tuple[PhaseCombinationMatch, ...]
    diagnostics: tuple[Diagnostic, ...]
    schema_version: str = "catex.phase-search.v1"

    @property
    def has_errors(self) -> bool:
        return any(item.severity is Severity.ERROR for item in self.diagnostics)

    @property
    def best_score(self) -> float | None:
        values = [
            *(item.evidence_score for item in self.single_phase_matches),
            *(item.evidence_score for item in self.combination_matches),
        ]
        return max(values) if values else None

    @property
    def status(self) -> str:
        if self.has_errors:
            return "error"
        if self.best_score is None:
            return "no_candidates"
        if self.best_score < self.settings.minimum_supported_score:
            return "insufficient_support"
        return "hypotheses_found"

    def ranked_reference_support(self) -> dict[str, float]:
        """Return each parent phase's strongest single or combination support."""

        support = {item.reference_key: item.evidence_score for item in self.single_phase_matches}
        for combination in self.combination_matches:
            for key, contribution in zip(
                combination.reference_keys,
                combination.diffraction_contributions,
                strict=True,
            ):
                inherited = combination.evidence_score * contribution
                support[key] = max(support.get(key, 0.0), inherited)
        return support

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "status": self.status,
            "pattern": self.pattern.to_dict(),
            "settings": self.settings.to_dict(),
            "considered_reference_keys": list(self.considered_reference_keys),
            "best_score": self.best_score,
            "score_interpretation": (
                "ranking evidence only; not a calibrated posterior probability"
            ),
            "single_phase_matches": [item.to_dict() for item in self.single_phase_matches],
            "combination_matches": [item.to_dict() for item in self.combination_matches],
            "diagnostics": [item.to_dict() for item in self.diagnostics],
        }


def parse_xrd_path(path: str | Path) -> XRDPattern:
    """Parse a text XRD file using the first two finite numeric columns."""

    source = Path(path)
    if not source.is_file():
        raise ValueError("XRD path must be an existing regular file")
    x_values: list[float] = []
    y_values: list[float] = []
    skipped = 0
    for raw_line in source.read_text(encoding="utf-8-sig", errors="strict").splitlines():
        line = raw_line.strip()
        if not line or line.startswith(("#", ";", "//")):
            skipped += 1
            continue
        fields = line.replace(",", " ").replace("\t", " ").split()
        if len(fields) < 2:
            skipped += 1
            continue
        try:
            x_value = float(fields[0])
            y_value = float(fields[1])
        except ValueError:
            skipped += 1
            continue
        if not math.isfinite(x_value) or not math.isfinite(y_value):
            raise ValueError("XRD file contains a non-finite numeric point")
        x_values.append(x_value)
        y_values.append(max(0.0, y_value))
    if len(x_values) < 5:
        raise ValueError("XRD file contains fewer than five numeric points")
    order = np.argsort(np.asarray(x_values), kind="stable")
    x = np.asarray(x_values, dtype=float)[order]
    y = np.asarray(y_values, dtype=float)[order]
    unique, inverse = np.unique(x, return_inverse=True)
    if len(unique) != len(x):
        accumulated = np.zeros(len(unique), dtype=float)
        counts = np.zeros(len(unique), dtype=float)
        np.add.at(accumulated, inverse, y)
        np.add.at(counts, inverse, 1.0)
        x = unique
        y = accumulated / counts
    return XRDPattern(
        tuple(float(item) for item in x),
        tuple(float(item) for item in y),
        source_name=source.name,
        skipped_lines=skipped,
    )


def _rolling_baseline(values: np.ndarray, window: int) -> np.ndarray:
    if window <= 1:
        return np.zeros_like(values)
    window = min(window, len(values))
    half = window // 2
    baseline = np.empty_like(values)
    for index in range(len(values)):
        start = max(0, index - half)
        stop = min(len(values), index + half + 1)
        baseline[index] = float(np.percentile(values[start:stop], 10))
    return baseline


def preprocess_pattern(pattern: XRDPattern, *, baseline_window_points: int = 0) -> XRDPattern:
    """Clip, optionally subtract a transparent rolling baseline, and normalize."""

    x, raw = pattern.arrays()
    baseline = _rolling_baseline(raw, baseline_window_points)
    intensity = np.clip(raw - baseline, 0.0, None)
    maximum = float(np.max(intensity))
    if maximum <= 0:
        raise ValueError("XRD preprocessing removed all positive intensity")
    intensity /= maximum
    return XRDPattern(
        tuple(float(item) for item in x),
        tuple(float(item) for item in intensity),
        source_name=pattern.source_name,
        skipped_lines=pattern.skipped_lines,
    )


def simulate_xrd_on_grid(
    structure: Structure,
    two_theta_degrees: np.ndarray,
    *,
    wavelength: str,
    shift_degrees: float,
    fwhm_degrees: float,
) -> np.ndarray:
    """Calculate and Gaussian-broaden a powder pattern on an explicit grid."""

    if fwhm_degrees <= 0:
        raise ValueError("fwhm_degrees must be positive")
    calculator = XRDCalculator(wavelength=wavelength, symprec=0)
    lower = float(np.min(two_theta_degrees) - abs(shift_degrees) - 1.0)
    upper = float(np.max(two_theta_degrees) + abs(shift_degrees) + 1.0)
    calculated = calculator.get_pattern(
        structure,
        scaled=True,
        two_theta_range=(max(0.0, lower), min(180.0, upper)),
    )
    profile = np.zeros_like(two_theta_degrees, dtype=float)
    sigma = fwhm_degrees / (2.0 * math.sqrt(2.0 * math.log(2.0)))
    for position, intensity in zip(calculated.x, calculated.y, strict=True):
        center = float(position) + shift_degrees
        profile += float(intensity) * np.exp(-0.5 * ((two_theta_degrees - center) / sigma) ** 2)
    maximum = float(np.max(profile))
    if maximum > 0:
        profile /= maximum
    return profile


def _profile_metrics(observed: np.ndarray, predicted: np.ndarray) -> tuple[float, float, float]:
    denominator = float(np.dot(predicted, predicted))
    scale = max(0.0, float(np.dot(observed, predicted)) / denominator) if denominator else 0.0
    fitted = predicted * scale
    observed_norm = float(np.linalg.norm(observed))
    fitted_norm = float(np.linalg.norm(fitted))
    cosine = (
        float(np.dot(observed, fitted)) / (observed_norm * fitted_norm)
        if observed_norm and fitted_norm
        else 0.0
    )
    absolute_residual = float(np.sum(np.abs(observed - fitted)))
    observed_sum = float(np.sum(np.abs(observed)))
    normalized_residual = absolute_residual / observed_sum if observed_sum else 1.0
    explained = max(0.0, min(1.0, 1.0 - normalized_residual))
    return max(0.0, min(1.0, cosine)), explained, normalized_residual


def _detect_peaks(
    x: np.ndarray,
    y: np.ndarray,
    *,
    relative_threshold: float,
    minimum_separation_degrees: float,
) -> tuple[tuple[float, float], ...]:
    candidates = [
        index
        for index in range(1, len(y) - 1)
        if y[index] >= y[index - 1]
        and y[index] > y[index + 1]
        and y[index] >= relative_threshold * float(np.max(y))
    ]
    selected: list[int] = []
    for index in sorted(candidates, key=lambda item: float(y[item]), reverse=True):
        if all(abs(float(x[index] - x[other])) >= minimum_separation_degrees for other in selected):
            selected.append(index)
    return tuple(
        (float(x[index]), float(y[index])) for index in sorted(selected, key=lambda item: x[item])
    )


def _peak_evidence(
    x: np.ndarray,
    observed: np.ndarray,
    predicted: np.ndarray,
    settings: XRDSearchSettings,
) -> PeakMatchEvidence:
    observed_peaks = _detect_peaks(
        x,
        observed,
        relative_threshold=settings.peak_relative_threshold,
        minimum_separation_degrees=settings.peak_tolerance_degrees,
    )
    predicted_peaks = _detect_peaks(
        x,
        predicted,
        relative_threshold=settings.peak_relative_threshold,
        minimum_separation_degrees=settings.peak_tolerance_degrees,
    )
    unused = set(range(len(predicted_peaks)))
    matched: list[tuple[float, float]] = []
    unexplained: list[float] = []
    for observed_position, _observed_intensity in sorted(
        observed_peaks,
        key=lambda item: item[1],
        reverse=True,
    ):
        eligible = [
            index
            for index in unused
            if abs(observed_position - predicted_peaks[index][0]) <= settings.peak_tolerance_degrees
        ]
        if not eligible:
            unexplained.append(observed_position)
            continue
        chosen = min(
            eligible,
            key=lambda index: abs(observed_position - predicted_peaks[index][0]),
        )
        unused.remove(chosen)
        matched.append((observed_position, predicted_peaks[chosen][0]))
    missing = [predicted_peaks[index][0] for index in sorted(unused)]
    return PeakMatchEvidence(
        tuple(sorted(matched)),
        tuple(sorted(unexplained)),
        tuple(sorted(missing)),
    )


def _single_match(
    reference_key: str,
    formula: str,
    structure: Structure,
    pattern: XRDPattern,
    settings: XRDSearchSettings,
    cache: dict[tuple[str, float, float], np.ndarray],
) -> SinglePhaseMatch:
    x, observed = pattern.arrays()
    best: tuple[float, float, float, float, float, float, np.ndarray] | None = None
    best_key: tuple[float, ...] | None = None
    for shift in settings.shift_values_degrees:
        for fwhm in settings.fwhm_values_degrees:
            predicted = simulate_xrd_on_grid(
                structure,
                x,
                wavelength=settings.wavelength,
                shift_degrees=shift,
                fwhm_degrees=fwhm,
            )
            cache[(reference_key, shift, fwhm)] = predicted
            cosine, explained, residual = _profile_metrics(observed, predicted)
            score = 0.7 * cosine + 0.3 * explained
            key = (score, cosine, explained, -residual, -abs(shift), -fwhm)
            if best_key is None or key > best_key:
                best_key = key
                best = (score, cosine, explained, residual, shift, fwhm, predicted)
    if best is None:  # pragma: no cover - settings validation guarantees a grid
        raise ValueError("empty XRD nuisance grid")
    score, cosine, explained, residual, shift, fwhm, predicted = best
    return SinglePhaseMatch(
        reference_key=reference_key,
        formula=formula,
        evidence_score=score,
        cosine_similarity=cosine,
        explained_intensity_fraction=explained,
        normalized_absolute_residual=residual,
        shift_degrees=shift,
        fwhm_degrees=fwhm,
        peak_evidence=_peak_evidence(x, observed, predicted, settings),
    )


def _nonnegative_least_squares(matrix: np.ndarray, target: np.ndarray) -> np.ndarray:
    """Solve tiny NNLS problems exactly by enumerating active phase subsets."""

    columns = matrix.shape[1]
    best_weights = np.zeros(columns, dtype=float)
    best_residual = float(np.dot(target, target))
    for mask in range(1, 1 << columns):
        active = [index for index in range(columns) if mask & (1 << index)]
        candidate, *_ = np.linalg.lstsq(matrix[:, active], target, rcond=None)
        if np.any(candidate < -1e-10):
            continue
        weights = np.zeros(columns, dtype=float)
        weights[active] = np.clip(candidate, 0.0, None)
        residual = float(np.sum((target - matrix @ weights) ** 2))
        if residual < best_residual:
            best_residual = residual
            best_weights = weights
    return best_weights


def _combination_match(
    reference_keys: tuple[str, ...],
    registry: ProviderRegistry,
    pattern: XRDPattern,
    settings: XRDSearchSettings,
    cache: dict[tuple[str, float, float], np.ndarray],
    required_elements: set[str],
) -> PhaseCombinationMatch:
    _, observed = pattern.arrays()
    best: tuple[float, float, float, float, float, float, np.ndarray] | None = None
    best_key: tuple[float, ...] | None = None
    for shift in settings.shift_values_degrees:
        for fwhm in settings.fwhm_values_degrees:
            matrix = np.column_stack([cache[(key, shift, fwhm)] for key in reference_keys])
            weights = _nonnegative_least_squares(matrix, observed)
            fitted = matrix @ weights
            cosine, explained, residual = _profile_metrics(observed, fitted)
            score = (
                0.7 * cosine
                + 0.3 * explained
                - settings.complexity_penalty * (len(reference_keys) - 1)
            )
            key = (score, cosine, explained, -residual, -abs(shift), -fwhm)
            if best_key is None or key > best_key:
                best_key = key
                best = (score, cosine, explained, residual, shift, fwhm, weights)
    if best is None:  # pragma: no cover
        raise ValueError("empty XRD nuisance grid")
    score, cosine, explained, residual, shift, fwhm, raw_weights = best
    total = float(np.sum(raw_weights))
    contributions = raw_weights / total if total > 0 else raw_weights
    covered = set().union(*(set(registry.get_reference(key).elements) for key in reference_keys))
    missing = required_elements - covered
    if missing:
        score = max(0.0, score - 0.15)
    return PhaseCombinationMatch(
        reference_keys=reference_keys,
        formulas=tuple(registry.get_reference(key).formula for key in reference_keys),
        diffraction_contributions=tuple(float(item) for item in contributions),
        evidence_score=score,
        cosine_similarity=cosine,
        explained_intensity_fraction=explained,
        normalized_absolute_residual=residual,
        shift_degrees=shift,
        fwhm_degrees=fwhm,
        covered_required_elements=tuple(sorted(required_elements & covered)),
        missing_required_elements=tuple(sorted(missing)),
    )


def search_xrd_phases(
    raw_pattern: XRDPattern,
    registry: ProviderRegistry,
    *,
    allowed_elements: tuple[str, ...] = (),
    excluded_elements: tuple[str, ...] = (),
    required_elements: tuple[str, ...] = (),
    settings: XRDSearchSettings | None = None,
) -> PhaseSearchReport:
    """Rank single and bounded multiphase hypotheses from a local structure registry."""

    active = settings or XRDSearchSettings()
    pattern = preprocess_pattern(
        raw_pattern,
        baseline_window_points=active.baseline_window_points,
    )
    references = registry.search(
        allowed_elements=allowed_elements,
        excluded_elements=excluded_elements,
    )
    diagnostics: list[Diagnostic] = []
    if raw_pattern.skipped_lines:
        diagnostics.append(
            Diagnostic(
                "XRD_NONDATA_LINES_SKIPPED",
                Severity.INFO,
                "Non-numeric, blank, or comment lines were skipped while parsing XRD.",
                {"count": raw_pattern.skipped_lines},
            )
        )
    if not references:
        diagnostics.append(
            Diagnostic(
                "XRD_NO_COMPATIBLE_REFERENCE_STRUCTURES",
                Severity.ERROR,
                "No catalog structures satisfy the declared elemental constraints.",
            )
        )
        return PhaseSearchReport(
            pattern,
            active,
            (),
            (),
            (),
            tuple(diagnostics),
        )

    cache: dict[tuple[str, float, float], np.ndarray] = {}
    single_matches = [
        _single_match(
            reference.key,
            reference.formula,
            registry.get_structure(reference.key),
            pattern,
            active,
            cache,
        )
        for reference in references
    ]
    single_matches.sort(key=lambda item: (-item.evidence_score, item.reference_key))
    pool = tuple(item.reference_key for item in single_matches[: active.single_phase_pool])
    combinations: list[PhaseCombinationMatch] = []
    required = set(required_elements)
    for size in range(2, active.maximum_phases + 1):
        for keys in itertools.combinations(pool, size):
            combinations.append(
                _combination_match(
                    keys,
                    registry,
                    pattern,
                    active,
                    cache,
                    required,
                )
            )
    combinations.sort(key=lambda item: (-item.evidence_score, item.reference_keys))
    if single_matches and single_matches[0].evidence_score < active.minimum_supported_score:
        diagnostics.append(
            Diagnostic(
                "XRD_REFERENCE_LIBRARY_INSUFFICIENT",
                Severity.WARNING,
                "No single reference reached the provisional support threshold.",
                {
                    "best_score": single_matches[0].evidence_score,
                    "threshold": active.minimum_supported_score,
                },
            )
        )
    if single_matches and single_matches[0].peak_evidence.unexplained_observed_degrees:
        diagnostics.append(
            Diagnostic(
                "XRD_UNEXPLAINED_PEAKS_REMAIN",
                Severity.WARNING,
                "The best single-phase fit leaves observed peaks unexplained.",
                {
                    "two_theta_degrees": list(
                        single_matches[0].peak_evidence.unexplained_observed_degrees
                    )
                },
            )
        )
    return PhaseSearchReport(
        pattern=pattern,
        settings=active,
        considered_reference_keys=tuple(item.key for item in references),
        single_phase_matches=tuple(single_matches),
        combination_matches=tuple(combinations),
        diagnostics=tuple(diagnostics),
    )
