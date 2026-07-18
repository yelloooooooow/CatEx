"""Pure numerical analysis of caller-parsed electronic-structure data."""

from __future__ import annotations

import hashlib
import json
import math
import re
from collections.abc import Sequence
from dataclasses import replace
from itertools import pairwise
from typing import Any

import numpy as np

from catex.catalysis import (
    AdsorptionConfiguration,
    ConfigurationReadinessReport,
    is_intact_catalysis_identity,
)
from catex.electronic_structure.models import (
    ChargeAnalysisReport,
    ChargePartitionInput,
    ChargePartitionMethod,
    DbandMoment,
    DensityOfStatesAnalysisReport,
    DensityOfStatesInput,
    ElectronicStructureSummary,
    MagneticMomentInput,
    MagnetismAnalysisReport,
    OrbitalFamily,
    ProjectedDosSeries,
    SpinChannel,
)

_IDENTIFIER = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,99}")
_SHA256 = re.compile(r"[0-9a-f]{64}")


def _digest(payload: dict[str, Any]) -> str:
    encoded = json.dumps(
        payload,
        allow_nan=False,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _report_content(report: object, hash_field: str) -> dict[str, Any]:
    payload = report.to_dict()  # type: ignore[attr-defined]
    payload.pop(hash_field)
    return payload


def _identifier(value: str, *, field: str) -> str:
    if not isinstance(value, str) or _IDENTIFIER.fullmatch(value) is None:
        raise ValueError(f"{field} must be a safe identifier of at most 100 characters")
    return value


def _one_line(value: str, *, field: str, maximum: int) -> str:
    if not isinstance(value, str) or any(character in value for character in "\r\n"):
        raise ValueError(f"{field} must be one line")
    normalized = value.strip()
    if not normalized or len(normalized) > maximum:
        raise ValueError(f"{field} must be non-empty and at most {maximum} characters")
    return normalized


def _configuration_hash(value: str) -> str:
    if not isinstance(value, str) or _SHA256.fullmatch(value) is None:
        raise ValueError("configuration_identity_sha256 must be a lowercase SHA256")
    return value


def _source_hashes(values: Sequence[str]) -> tuple[str, ...]:
    result = tuple(values)
    if (
        not result
        or len(set(result)) != len(result)
        or any(not isinstance(item, str) or _SHA256.fullmatch(item) is None for item in result)
    ):
        raise ValueError("source_sha256s must contain unique lowercase SHA256 values")
    return tuple(sorted(result))


def _finite_vector(
    values: Sequence[float],
    *,
    field: str,
    nonnegative: bool = False,
) -> tuple[float, ...]:
    result = tuple(values)
    if not result:
        raise ValueError(f"{field} must not be empty")
    normalized: list[float] = []
    for value in result:
        if (
            not isinstance(value, int | float)
            or isinstance(value, bool)
            or not math.isfinite(value)
            or (nonnegative and value < 0)
        ):
            qualifier = " finite non-negative" if nonnegative else " finite"
            raise ValueError(f"{field} must contain{qualifier} numbers")
        normalized.append(float(value))
    return tuple(normalized)


def _indices(values: Sequence[int], *, size: int, field: str) -> tuple[int, ...]:
    result = tuple(values)
    if (
        not result
        or len(set(result)) != len(result)
        or any(
            not isinstance(item, int) or isinstance(item, bool) or item < 0 or item >= size
            for item in result
        )
    ):
        raise ValueError(f"{field} must contain unique valid 0-based indices")
    return tuple(sorted(result))


def _interpolate(energies: np.ndarray, values: np.ndarray, energy: float) -> float:
    return float(np.interp(energy, energies, values))


def _windowed_arrays(
    energies_relative: np.ndarray,
    densities: np.ndarray,
    lower: float,
    upper: float,
) -> tuple[np.ndarray, np.ndarray]:
    interior = (energies_relative > lower) & (energies_relative < upper)
    window_energies = np.concatenate(
        (np.array([lower]), energies_relative[interior], np.array([upper]))
    )
    window_densities = np.concatenate(
        (
            np.array([_interpolate(energies_relative, densities, lower)]),
            densities[interior],
            np.array([_interpolate(energies_relative, densities, upper)]),
        )
    )
    return window_energies, window_densities


def _d_band_moment(
    series: ProjectedDosSeries,
    energies_relative: np.ndarray,
    densities: np.ndarray,
    window: tuple[float, float],
) -> DbandMoment:
    energy, density = _windowed_arrays(energies_relative, densities, *window)
    weight = float(np.trapezoid(density, energy))
    if not math.isfinite(weight) or weight <= 0:
        raise ValueError(f"d projected series {series.label!r} has zero weight in the window")
    center = float(np.trapezoid(energy * density, energy) / weight)
    variance = float(np.trapezoid(((energy - center) ** 2) * density, energy) / weight)
    width = math.sqrt(max(variance, 0.0))
    return DbandMoment(
        series_label=series.label,
        site_indices_0based=tuple(sorted(series.site_indices_0based)),
        spin_channel=series.spin_channel,
        energy_window_relative_to_fermi_ev=window,
        integrated_weight_states=weight,
        center_relative_to_fermi_ev=center,
        width_ev=width,
    )


def analyze_density_of_states(
    data: DensityOfStatesInput,
    *,
    d_band_window_relative_to_fermi_ev: tuple[float, float] = (-10.0, 2.0),
) -> DensityOfStatesAnalysisReport:
    """Calculate DOS(Ef), spin polarization, and explicit projected d-band moments."""

    if not isinstance(data, DensityOfStatesInput):
        raise ValueError("data must be a DensityOfStatesInput")
    dos_id = _identifier(data.dos_id, field="dos_id")
    configuration_hash = _configuration_hash(data.configuration_identity_sha256)
    parser_name = _one_line(data.parser_name, field="parser_name", maximum=100)
    sources = _source_hashes(data.source_sha256s)
    if (
        not isinstance(data.number_of_sites, int)
        or isinstance(data.number_of_sites, bool)
        or data.number_of_sites <= 0
    ):
        raise ValueError("number_of_sites must be a positive integer")
    energies = _finite_vector(data.energies_ev, field="energies_ev")
    if len(energies) < 2 or any(right <= left for left, right in pairwise(energies)):
        raise ValueError("energies_ev must contain at least two strictly increasing values")
    total = _finite_vector(
        data.total_density_states_per_ev,
        field="total_density_states_per_ev",
        nonnegative=True,
    )
    if len(total) != len(energies):
        raise ValueError("total DOS must have one value per energy")
    if (
        not isinstance(data.fermi_energy_ev, int | float)
        or isinstance(data.fermi_energy_ev, bool)
        or not math.isfinite(data.fermi_energy_ev)
    ):
        raise ValueError("fermi_energy_ev must be finite")
    fermi = float(data.fermi_energy_ev)
    if not energies[0] <= fermi <= energies[-1]:
        raise ValueError("fermi_energy_ev must lie inside the energy grid")

    spin_up = data.spin_up_density_states_per_ev
    spin_down = data.spin_down_density_states_per_ev
    if (spin_up is None) != (spin_down is None):
        raise ValueError("spin-up and spin-down DOS must be supplied together")
    normalized_up: tuple[float, ...] | None = None
    normalized_down: tuple[float, ...] | None = None
    if spin_up is not None and spin_down is not None:
        normalized_up = _finite_vector(
            spin_up,
            field="spin_up_density_states_per_ev",
            nonnegative=True,
        )
        normalized_down = _finite_vector(
            spin_down,
            field="spin_down_density_states_per_ev",
            nonnegative=True,
        )
        if len(normalized_up) != len(energies) or len(normalized_down) != len(energies):
            raise ValueError("spin-resolved DOS must have one value per energy")

    lower, upper = d_band_window_relative_to_fermi_ev
    if (
        any(
            not isinstance(value, int | float)
            or isinstance(value, bool)
            or not math.isfinite(value)
            for value in (lower, upper)
        )
        or lower >= upper
    ):
        raise ValueError("d-band window must contain two increasing finite values")
    relative_min = energies[0] - fermi
    relative_max = energies[-1] - fermi
    if lower < relative_min or upper > relative_max:
        raise ValueError("d-band window must be fully covered by the supplied energy grid")
    window = (float(lower), float(upper))

    projected: list[tuple[ProjectedDosSeries, tuple[float, ...]]] = []
    labels: set[str] = set()
    for series in data.projected_series:
        if not isinstance(series, ProjectedDosSeries):
            raise ValueError("projected_series must contain ProjectedDosSeries records")
        label = _identifier(series.label, field="projected DOS label")
        if label in labels:
            raise ValueError("projected DOS labels must be unique")
        labels.add(label)
        if not isinstance(series.orbital_family, OrbitalFamily) or not isinstance(
            series.spin_channel, SpinChannel
        ):
            raise ValueError("projected DOS orbital and spin labels must use declared enums")
        indices = _indices(
            series.site_indices_0based,
            size=data.number_of_sites,
            field="projected DOS site_indices_0based",
        )
        densities = _finite_vector(
            series.densities_states_per_ev,
            field=f"projected DOS {label}",
            nonnegative=True,
        )
        if len(densities) != len(energies):
            raise ValueError("each projected DOS must have one value per energy")
        projected.append(
            (
                ProjectedDosSeries(
                    label=label,
                    orbital_family=series.orbital_family,
                    site_indices_0based=indices,
                    spin_channel=series.spin_channel,
                    densities_states_per_ev=densities,
                ),
                densities,
            )
        )

    energy_array = np.asarray(energies, dtype=float)
    relative_array = energy_array - fermi
    total_at_fermi = _interpolate(energy_array, np.asarray(total, dtype=float), fermi)
    spin_polarization: float | None = None
    if normalized_up is not None and normalized_down is not None:
        up_at_fermi = _interpolate(energy_array, np.asarray(normalized_up), fermi)
        down_at_fermi = _interpolate(energy_array, np.asarray(normalized_down), fermi)
        denominator = up_at_fermi + down_at_fermi
        spin_polarization = (up_at_fermi - down_at_fermi) / denominator if denominator > 0 else None
    moments = tuple(
        _d_band_moment(series, relative_array, np.asarray(densities), window)
        for series, densities in sorted(projected, key=lambda item: item[0].label)
        if series.orbital_family is OrbitalFamily.D
    )
    provisional = DensityOfStatesAnalysisReport(
        dos_id=dos_id,
        configuration_identity_sha256=configuration_hash,
        source_sha256s=sources,
        parser_name=parser_name,
        number_of_sites=data.number_of_sites,
        fermi_energy_ev=fermi,
        total_density_at_fermi_states_per_ev=total_at_fermi,
        spin_polarization_at_fermi=spin_polarization,
        d_band_moments=moments,
        analysis_sha256="0" * 64,
    )
    result = replace(
        provisional,
        analysis_sha256=_digest(_report_content(provisional, "analysis_sha256")),
    )
    return result


def analyze_magnetism(data: MagneticMomentInput) -> MagnetismAnalysisReport:
    """Summarize explicit per-site collinear moments without assigning a spin state."""

    if not isinstance(data, MagneticMomentInput):
        raise ValueError("data must be a MagneticMomentInput")
    moment_id = _identifier(data.moment_id, field="moment_id")
    configuration_hash = _configuration_hash(data.configuration_identity_sha256)
    sources = _source_hashes(data.source_sha256s)
    parser_name = _one_line(data.parser_name, field="parser_name", maximum=100)
    moments = _finite_vector(data.per_site_moments_mu_b, field="per_site_moments_mu_b")
    active = _indices(
        data.active_site_indices_0based,
        size=len(moments),
        field="active_site_indices_0based",
    )
    provisional = MagnetismAnalysisReport(
        moment_id=moment_id,
        configuration_identity_sha256=configuration_hash,
        source_sha256s=sources,
        parser_name=parser_name,
        number_of_sites=len(moments),
        active_site_indices_0based=active,
        total_moment_mu_b=math.fsum(moments),
        absolute_moment_sum_mu_b=math.fsum(abs(item) for item in moments),
        active_site_total_moment_mu_b=math.fsum(moments[index] for index in active),
        active_site_absolute_moment_sum_mu_b=math.fsum(abs(moments[index]) for index in active),
        analysis_sha256="0" * 64,
    )
    return replace(
        provisional,
        analysis_sha256=_digest(_report_content(provisional, "analysis_sha256")),
    )


def analyze_charge_partition(data: ChargePartitionInput) -> ChargeAnalysisReport:
    """Compute reference minus population, where a positive value means electron loss."""

    if not isinstance(data, ChargePartitionInput):
        raise ValueError("data must be a ChargePartitionInput")
    charge_id = _identifier(data.charge_id, field="charge_id")
    configuration_hash = _configuration_hash(data.configuration_identity_sha256)
    if not isinstance(data.method, ChargePartitionMethod):
        raise ValueError("method must be a ChargePartitionMethod")
    method_label = data.method_label.strip()
    if data.method is ChargePartitionMethod.OTHER or method_label:
        method_label = _one_line(method_label, field="method_label", maximum=100)
    parser_name = _one_line(data.parser_name, field="parser_name", maximum=100)
    sources = _source_hashes(data.source_sha256s)
    populations = _finite_vector(
        data.electron_populations,
        field="electron_populations",
        nonnegative=True,
    )
    references = _finite_vector(
        data.reference_valence_electrons,
        field="reference_valence_electrons",
        nonnegative=True,
    )
    if len(populations) != len(references):
        raise ValueError("electron populations and references must have the same length")
    active = _indices(
        data.active_site_indices_0based,
        size=len(populations),
        field="active_site_indices_0based",
    )
    deficits = tuple(
        reference - population
        for reference, population in zip(references, populations, strict=True)
    )
    provisional = ChargeAnalysisReport(
        charge_id=charge_id,
        configuration_identity_sha256=configuration_hash,
        method=data.method,
        method_label=method_label,
        source_sha256s=sources,
        parser_name=parser_name,
        number_of_sites=len(populations),
        active_site_indices_0based=active,
        electron_deficit_by_site_e=deficits,
        total_electron_deficit_e=math.fsum(deficits),
        active_site_electron_deficit_e=math.fsum(deficits[index] for index in active),
        analysis_sha256="0" * 64,
    )
    return replace(
        provisional,
        analysis_sha256=_digest(_report_content(provisional, "analysis_sha256")),
    )


def _intact_analysis(report: object, expected_schema: str) -> bool:
    try:
        return (
            report.schema_version == expected_schema  # type: ignore[attr-defined]
            and _SHA256.fullmatch(report.analysis_sha256) is not None  # type: ignore[attr-defined]
            and report.analysis_sha256  # type: ignore[attr-defined]
            == _digest(_report_content(report, "analysis_sha256"))
            and report.manual_interpretation_required  # type: ignore[attr-defined]
            and not report.writes_performed  # type: ignore[attr-defined]
            and not report.commands_executed  # type: ignore[attr-defined]
        )
    except (AttributeError, TypeError, ValueError):
        return False


def summarize_electronic_structure(
    configuration: AdsorptionConfiguration,
    readiness: ConfigurationReadinessReport,
    dos: DensityOfStatesAnalysisReport,
    magnetism: MagnetismAnalysisReport,
    charge: ChargeAnalysisReport,
) -> ElectronicStructureSummary:
    """Bind three intact analyses to one four-identity-approved configuration."""

    if not is_intact_catalysis_identity(configuration):
        raise ValueError("configuration must be an intact adsorption identity")
    if (
        not isinstance(readiness, ConfigurationReadinessReport)
        or not readiness.ready_for_calculation_planning
        or readiness.configuration_id != configuration.configuration_id
        or readiness.configuration_identity_sha256 != configuration.identity_sha256
        or len(readiness.accepted_review_sha256s) != 4
        or any(_SHA256.fullmatch(item) is None for item in readiness.accepted_review_sha256s)
    ):
        raise ValueError("configuration must pass the four-identity review gate")
    reports = (
        (dos, "catex.density-of-states-analysis.v1"),
        (magnetism, "catex.magnetism-analysis.v1"),
        (charge, "catex.charge-analysis.v1"),
    )
    if any(not _intact_analysis(report, schema) for report, schema in reports):
        raise ValueError("electronic-structure reports must be intact and interpretation-gated")
    if any(
        report.configuration_identity_sha256 != configuration.identity_sha256
        for report, _ in reports
    ):
        raise ValueError("all analyses must be bound to the reviewed configuration")
    expected_sites = len(configuration.substrate_indices_0based) + len(
        configuration.adsorbate_indices_0based
    )
    if (
        dos.number_of_sites != expected_sites
        or magnetism.number_of_sites != expected_sites
        or charge.number_of_sites != expected_sites
    ):
        raise ValueError("all analyses must cover exactly the reviewed configuration sites")
    source_hashes = tuple(
        sorted({source for report, _ in reports for source in report.source_sha256s})
    )
    provisional = ElectronicStructureSummary(
        configuration_id=configuration.configuration_id,
        configuration_identity_sha256=configuration.identity_sha256,
        configuration_review_sha256s=readiness.accepted_review_sha256s,
        dos_analysis_sha256=dos.analysis_sha256,
        magnetism_analysis_sha256=magnetism.analysis_sha256,
        charge_analysis_sha256=charge.analysis_sha256,
        source_sha256s=source_hashes,
        summary_sha256="0" * 64,
    )
    return replace(
        provisional,
        summary_sha256=_digest(_report_content(provisional, "summary_sha256")),
    )
