"""Typed, source-bound records for electronic-structure analysis."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import Any


class SpinChannel(StrEnum):
    """Spin channel represented by a density-of-states series."""

    DOWN = "down"
    TOTAL = "total"
    UP = "up"


class OrbitalFamily(StrEnum):
    """Coarse angular-momentum family for projected DOS."""

    D = "d"
    F = "f"
    P = "p"
    S = "s"


class ChargePartitionMethod(StrEnum):
    """Declared population-analysis method; values are never inferred."""

    BADER = "bader"
    DDEC = "ddec"
    OTHER = "other"


@dataclass(frozen=True, slots=True)
class ProjectedDosSeries:
    """One caller-parsed projected-DOS series."""

    label: str
    orbital_family: OrbitalFamily
    site_indices_0based: tuple[int, ...]
    spin_channel: SpinChannel
    densities_states_per_ev: tuple[float, ...]

    def to_dict(self) -> dict[str, Any]:
        return {
            "label": self.label,
            "orbital_family": self.orbital_family.value,
            "site_indices_0based": list(self.site_indices_0based),
            "spin_channel": self.spin_channel.value,
            "densities_states_per_ev": list(self.densities_states_per_ev),
        }


@dataclass(frozen=True, slots=True)
class DensityOfStatesInput:
    """Caller-parsed DOS arrays bound to an adsorption configuration and source hashes."""

    dos_id: str
    configuration_identity_sha256: str
    fermi_energy_ev: float
    number_of_sites: int
    energies_ev: tuple[float, ...]
    total_density_states_per_ev: tuple[float, ...]
    projected_series: tuple[ProjectedDosSeries, ...]
    source_sha256s: tuple[str, ...]
    spin_up_density_states_per_ev: tuple[float, ...] | None = None
    spin_down_density_states_per_ev: tuple[float, ...] | None = None
    parser_name: str = "caller_supplied"
    schema_version: str = "catex.density-of-states-input.v1"

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "dos_id": self.dos_id,
            "configuration_identity_sha256": self.configuration_identity_sha256,
            "fermi_energy_ev": self.fermi_energy_ev,
            "number_of_sites": self.number_of_sites,
            "energies_ev": list(self.energies_ev),
            "total_density_states_per_ev": list(self.total_density_states_per_ev),
            "spin_up_density_states_per_ev": (
                list(self.spin_up_density_states_per_ev)
                if self.spin_up_density_states_per_ev is not None
                else None
            ),
            "spin_down_density_states_per_ev": (
                list(self.spin_down_density_states_per_ev)
                if self.spin_down_density_states_per_ev is not None
                else None
            ),
            "projected_series": [item.to_dict() for item in self.projected_series],
            "source_sha256s": list(self.source_sha256s),
            "parser_name": self.parser_name,
        }


@dataclass(frozen=True, slots=True)
class DbandMoment:
    """Numerical d-band moment for one explicit projected-DOS series."""

    series_label: str
    site_indices_0based: tuple[int, ...]
    spin_channel: SpinChannel
    energy_window_relative_to_fermi_ev: tuple[float, float]
    integrated_weight_states: float
    center_relative_to_fermi_ev: float
    width_ev: float

    def to_dict(self) -> dict[str, Any]:
        return {
            "series_label": self.series_label,
            "site_indices_0based": list(self.site_indices_0based),
            "spin_channel": self.spin_channel.value,
            "energy_window_relative_to_fermi_ev": list(self.energy_window_relative_to_fermi_ev),
            "integrated_weight_states": self.integrated_weight_states,
            "center_relative_to_fermi_ev": self.center_relative_to_fermi_ev,
            "width_ev": self.width_ev,
        }


@dataclass(frozen=True, slots=True)
class DensityOfStatesAnalysisReport:
    """Deterministic numerical DOS summary without scientific interpretation."""

    dos_id: str
    configuration_identity_sha256: str
    source_sha256s: tuple[str, ...]
    parser_name: str
    number_of_sites: int
    fermi_energy_ev: float
    total_density_at_fermi_states_per_ev: float
    spin_polarization_at_fermi: float | None
    d_band_moments: tuple[DbandMoment, ...]
    analysis_sha256: str
    manual_interpretation_required: bool = True
    automatic_scientific_conclusion_performed: bool = False
    writes_performed: bool = False
    commands_executed: bool = False
    schema_version: str = "catex.density-of-states-analysis.v1"

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "dos_id": self.dos_id,
            "configuration_identity_sha256": self.configuration_identity_sha256,
            "source_sha256s": list(self.source_sha256s),
            "parser_name": self.parser_name,
            "number_of_sites": self.number_of_sites,
            "fermi_energy_ev": self.fermi_energy_ev,
            "total_density_at_fermi_states_per_ev": (self.total_density_at_fermi_states_per_ev),
            "spin_polarization_at_fermi": self.spin_polarization_at_fermi,
            "d_band_moments": [item.to_dict() for item in self.d_band_moments],
            "analysis_sha256": self.analysis_sha256,
            "manual_interpretation_required": self.manual_interpretation_required,
            "automatic_scientific_conclusion_performed": (
                self.automatic_scientific_conclusion_performed
            ),
            "writes_performed": self.writes_performed,
            "commands_executed": self.commands_executed,
        }


@dataclass(frozen=True, slots=True)
class MagneticMomentInput:
    """Caller-parsed collinear per-site moments with explicit active-site indices."""

    moment_id: str
    configuration_identity_sha256: str
    per_site_moments_mu_b: tuple[float, ...]
    active_site_indices_0based: tuple[int, ...]
    source_sha256s: tuple[str, ...]
    parser_name: str = "caller_supplied"
    schema_version: str = "catex.magnetic-moment-input.v1"

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "moment_id": self.moment_id,
            "configuration_identity_sha256": self.configuration_identity_sha256,
            "per_site_moments_mu_b": list(self.per_site_moments_mu_b),
            "active_site_indices_0based": list(self.active_site_indices_0based),
            "source_sha256s": list(self.source_sha256s),
            "parser_name": self.parser_name,
        }


@dataclass(frozen=True, slots=True)
class MagnetismAnalysisReport:
    """Arithmetic summary of explicit collinear magnetic moments."""

    moment_id: str
    configuration_identity_sha256: str
    source_sha256s: tuple[str, ...]
    parser_name: str
    number_of_sites: int
    active_site_indices_0based: tuple[int, ...]
    total_moment_mu_b: float
    absolute_moment_sum_mu_b: float
    active_site_total_moment_mu_b: float
    active_site_absolute_moment_sum_mu_b: float
    analysis_sha256: str
    manual_interpretation_required: bool = True
    automatic_magnetic_state_assignment_performed: bool = False
    writes_performed: bool = False
    commands_executed: bool = False
    schema_version: str = "catex.magnetism-analysis.v1"

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "moment_id": self.moment_id,
            "configuration_identity_sha256": self.configuration_identity_sha256,
            "source_sha256s": list(self.source_sha256s),
            "parser_name": self.parser_name,
            "number_of_sites": self.number_of_sites,
            "active_site_indices_0based": list(self.active_site_indices_0based),
            "total_moment_mu_b": self.total_moment_mu_b,
            "absolute_moment_sum_mu_b": self.absolute_moment_sum_mu_b,
            "active_site_total_moment_mu_b": self.active_site_total_moment_mu_b,
            "active_site_absolute_moment_sum_mu_b": (self.active_site_absolute_moment_sum_mu_b),
            "analysis_sha256": self.analysis_sha256,
            "manual_interpretation_required": self.manual_interpretation_required,
            "automatic_magnetic_state_assignment_performed": (
                self.automatic_magnetic_state_assignment_performed
            ),
            "writes_performed": self.writes_performed,
            "commands_executed": self.commands_executed,
        }


@dataclass(frozen=True, slots=True)
class ChargePartitionInput:
    """Population analysis and explicit neutral-atom reference populations."""

    charge_id: str
    configuration_identity_sha256: str
    method: ChargePartitionMethod
    electron_populations: tuple[float, ...]
    reference_valence_electrons: tuple[float, ...]
    active_site_indices_0based: tuple[int, ...]
    source_sha256s: tuple[str, ...]
    method_label: str = ""
    parser_name: str = "caller_supplied"
    schema_version: str = "catex.charge-partition-input.v1"

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "charge_id": self.charge_id,
            "configuration_identity_sha256": self.configuration_identity_sha256,
            "method": self.method.value,
            "method_label": self.method_label,
            "electron_populations": list(self.electron_populations),
            "reference_valence_electrons": list(self.reference_valence_electrons),
            "active_site_indices_0based": list(self.active_site_indices_0based),
            "source_sha256s": list(self.source_sha256s),
            "parser_name": self.parser_name,
        }


@dataclass(frozen=True, slots=True)
class ChargeAnalysisReport:
    """Per-site electron deficit summary using an explicit sign convention."""

    charge_id: str
    configuration_identity_sha256: str
    method: ChargePartitionMethod
    method_label: str
    source_sha256s: tuple[str, ...]
    parser_name: str
    number_of_sites: int
    active_site_indices_0based: tuple[int, ...]
    electron_deficit_by_site_e: tuple[float, ...]
    total_electron_deficit_e: float
    active_site_electron_deficit_e: float
    analysis_sha256: str
    positive_deficit_means_electron_loss: bool = True
    manual_interpretation_required: bool = True
    automatic_oxidation_state_assignment_performed: bool = False
    writes_performed: bool = False
    commands_executed: bool = False
    schema_version: str = "catex.charge-analysis.v1"

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "charge_id": self.charge_id,
            "configuration_identity_sha256": self.configuration_identity_sha256,
            "method": self.method.value,
            "method_label": self.method_label,
            "source_sha256s": list(self.source_sha256s),
            "parser_name": self.parser_name,
            "number_of_sites": self.number_of_sites,
            "active_site_indices_0based": list(self.active_site_indices_0based),
            "electron_deficit_by_site_e": list(self.electron_deficit_by_site_e),
            "total_electron_deficit_e": self.total_electron_deficit_e,
            "active_site_electron_deficit_e": self.active_site_electron_deficit_e,
            "analysis_sha256": self.analysis_sha256,
            "positive_deficit_means_electron_loss": (self.positive_deficit_means_electron_loss),
            "manual_interpretation_required": self.manual_interpretation_required,
            "automatic_oxidation_state_assignment_performed": (
                self.automatic_oxidation_state_assignment_performed
            ),
            "writes_performed": self.writes_performed,
            "commands_executed": self.commands_executed,
        }


@dataclass(frozen=True, slots=True)
class ElectronicStructureSummary:
    """Review-gated binding of DOS, magnetism, and charge reports to one configuration."""

    configuration_id: str
    configuration_identity_sha256: str
    configuration_review_sha256s: tuple[str, ...]
    dos_analysis_sha256: str
    magnetism_analysis_sha256: str
    charge_analysis_sha256: str
    source_sha256s: tuple[str, ...]
    summary_sha256: str
    manual_interpretation_required: bool = True
    automatic_scientific_conclusion_performed: bool = False
    writes_performed: bool = False
    commands_executed: bool = False
    schema_version: str = "catex.electronic-structure-summary.v1"

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "configuration_id": self.configuration_id,
            "configuration_identity_sha256": self.configuration_identity_sha256,
            "configuration_review_sha256s": list(self.configuration_review_sha256s),
            "dos_analysis_sha256": self.dos_analysis_sha256,
            "magnetism_analysis_sha256": self.magnetism_analysis_sha256,
            "charge_analysis_sha256": self.charge_analysis_sha256,
            "source_sha256s": list(self.source_sha256s),
            "summary_sha256": self.summary_sha256,
            "manual_interpretation_required": self.manual_interpretation_required,
            "automatic_scientific_conclusion_performed": (
                self.automatic_scientific_conclusion_performed
            ),
            "writes_performed": self.writes_performed,
            "commands_executed": self.commands_executed,
        }
