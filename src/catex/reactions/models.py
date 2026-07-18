"""Versioned models for balanced reactions and reviewed thermochemistry."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from fractions import Fraction
from typing import Any

from catex.energetics import LinearEnergyDerivationReport, ReviewedEnergyRecord, VaspEnergyKind
from catex.models import Diagnostic, Severity


class ChemicalPhase(StrEnum):
    """Explicit phase or reservoir role for a chemical state."""

    ADSORBED = "adsorbed"
    ELECTRON = "electron"
    GAS = "gas"
    LIQUID = "liquid"
    SOLID = "solid"
    SOLVATED = "solvated"
    SURFACE = "surface"


class ChemicalStateSubjectKind(StrEnum):
    """Provenance class behind one reaction state."""

    ADSORBATE = "adsorbate"
    ADSORPTION_CONFIGURATION = "adsorption_configuration"
    CATALYST = "catalyst"
    EXTERNAL_REFERENCE = "external_reference"


class ReactionPurpose(StrEnum):
    """Scientific interpretation applied to one shared balanced-reaction core."""

    ADSORPTION = "adsorption"
    ELEMENTARY_STEP = "elementary_step"
    FORMATION = "formation"
    GENERIC = "generic"


class DefinitionSubjectKind(StrEnum):
    """Reaction-domain identities that require explicit scientific review."""

    CHEMICAL_STATE = "chemical_state"
    COMPUTATIONAL_HYDROGEN_ELECTRODE_PROTOCOL = "computational_hydrogen_electrode_protocol"
    REACTION = "reaction"
    REFERENCE_STATE_SET = "reference_state_set"
    STATE_ENERGY_BINDING = "state_energy_binding"
    THERMOCHEMICAL_CORRECTION = "thermochemical_correction"
    THERMOCHEMISTRY_PROTOCOL = "thermochemistry_protocol"


class DefinitionReviewDecision(StrEnum):
    """Explicit decision for a reaction-domain scientific definition."""

    APPROVED = "approved"
    REJECTED = "rejected"


class StandardState(StrEnum):
    """Thermochemical standard-state convention for one chemical state."""

    ELECTRON_RESERVOIR = "electron_reservoir"
    GAS_1_BAR = "gas_1_bar"
    PURE_LIQUID = "pure_liquid"
    PURE_SOLID = "pure_solid"
    SOLUTION_1_M = "solution_1_m"
    SURFACE_SITE = "surface_site"


class LowFrequencyTreatment(StrEnum):
    """Declared handling of low-frequency modes."""

    EXPLICIT = "explicit"
    HARMONIC = "harmonic"
    QUASI_RRHO = "quasi_rrho"


class ImaginaryModePolicy(StrEnum):
    """Declared handling of imaginary frequencies."""

    MANUAL_REVIEW = "manual_review"
    REJECT = "reject"
    TRANSITION_STATE_ONE_MODE = "transition_state_one_mode"


class CorrectionSourceKind(StrEnum):
    """Origin of numerical thermochemical components."""

    EXPLICIT_ASSUMPTION = "explicit_assumption"
    FREQUENCY_ANALYSIS = "frequency_analysis"
    MIXED = "mixed"
    TABULATED = "tabulated"


class ReferenceElectrode(StrEnum):
    """Potential scale used by a computational hydrogen electrode protocol."""

    RHE = "RHE"
    SHE = "SHE"


@dataclass(frozen=True, slots=True)
class RationalValue:
    """Canonical exact rational used for stoichiometry and composition."""

    numerator: int
    denominator: int

    @property
    def fraction(self) -> Fraction:
        return Fraction(self.numerator, self.denominator)

    def to_dict(self) -> dict[str, int]:
        return {"numerator": self.numerator, "denominator": self.denominator}


@dataclass(frozen=True, slots=True)
class ElementAmount:
    """One elemental amount in a chemical state."""

    element: str
    amount: RationalValue

    def to_dict(self) -> dict[str, Any]:
        return {"element": self.element, "amount": self.amount.to_dict()}


@dataclass(frozen=True, slots=True)
class ChemicalState:
    """Composition-, charge-, phase-, and provenance-bound reaction state."""

    state_id: str
    phase: ChemicalPhase
    formula: str
    composition: tuple[ElementAmount, ...]
    charge_e: RationalValue
    subject_kind: ChemicalStateSubjectKind
    subject_id: str
    subject_identity_sha256: str
    identity_sha256: str
    manual_review_required: bool = True
    writes_performed: bool = False
    commands_executed: bool = False
    schema_version: str = "catex.chemical-state.v1"

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "state_id": self.state_id,
            "phase": self.phase.value,
            "formula": self.formula,
            "composition": [item.to_dict() for item in self.composition],
            "charge_e": self.charge_e.to_dict(),
            "subject_kind": self.subject_kind.value,
            "subject_id": self.subject_id,
            "subject_identity_sha256": self.subject_identity_sha256,
            "identity_sha256": self.identity_sha256,
            "manual_review_required": self.manual_review_required,
            "writes_performed": self.writes_performed,
            "commands_executed": self.commands_executed,
        }


@dataclass(frozen=True, slots=True)
class ReferenceStateEntry:
    """One state identity included in an explicit reference-state set."""

    state_id: str
    state_identity_sha256: str

    def to_dict(self) -> dict[str, str]:
        return {
            "state_id": self.state_id,
            "state_identity_sha256": self.state_identity_sha256,
        }


@dataclass(frozen=True, slots=True)
class ReferenceStateSet:
    """Reviewed collection of explicit states used as energetic references."""

    reference_set_id: str
    entries: tuple[ReferenceStateEntry, ...]
    identity_sha256: str
    manual_review_required: bool = True
    writes_performed: bool = False
    commands_executed: bool = False
    schema_version: str = "catex.reference-state-set.v1"

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "reference_set_id": self.reference_set_id,
            "entries": [item.to_dict() for item in self.entries],
            "identity_sha256": self.identity_sha256,
            "manual_review_required": self.manual_review_required,
            "writes_performed": self.writes_performed,
            "commands_executed": self.commands_executed,
        }


@dataclass(frozen=True, slots=True)
class StateStoichiometry:
    """Input pair used to define a reaction; negative is reactant, positive is product."""

    state: ChemicalState
    coefficient: int | str | Fraction


@dataclass(frozen=True, slots=True)
class ReactionTerm:
    """Normalized signed coefficient bound to one immutable chemical state."""

    state_id: str
    state_identity_sha256: str
    coefficient: RationalValue

    def to_dict(self) -> dict[str, Any]:
        return {
            "state_id": self.state_id,
            "state_identity_sha256": self.state_identity_sha256,
            "coefficient": self.coefficient.to_dict(),
        }


@dataclass(frozen=True, slots=True)
class ReactionDefinition:
    """Element- and charge-balanced reaction shared by all property kinds."""

    reaction_id: str
    purpose: ReactionPurpose
    terms: tuple[ReactionTerm, ...]
    reference_set_id: str | None
    reference_set_identity_sha256: str | None
    identity_sha256: str
    element_and_charge_balanced: bool = True
    manual_review_required: bool = True
    writes_performed: bool = False
    commands_executed: bool = False
    schema_version: str = "catex.reaction-definition.v1"

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "reaction_id": self.reaction_id,
            "purpose": self.purpose.value,
            "terms": [item.to_dict() for item in self.terms],
            "reference_set_id": self.reference_set_id,
            "reference_set_identity_sha256": self.reference_set_identity_sha256,
            "identity_sha256": self.identity_sha256,
            "element_and_charge_balanced": self.element_and_charge_balanced,
            "manual_review_required": self.manual_review_required,
            "writes_performed": self.writes_performed,
            "commands_executed": self.commands_executed,
        }


@dataclass(frozen=True, slots=True)
class ReactionDefinitionReport:
    """Validation report that never emits an unbalanced ReactionDefinition."""

    reaction_id: str
    reaction: ReactionDefinition | None
    diagnostics: tuple[Diagnostic, ...]
    writes_performed: bool = False
    commands_executed: bool = False
    schema_version: str = "catex.reaction-definition-report.v1"

    @property
    def has_errors(self) -> bool:
        return any(item.severity is Severity.ERROR for item in self.diagnostics)

    @property
    def status(self) -> str:
        return "validated" if self.reaction is not None and not self.has_errors else "error"

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "status": self.status,
            "reaction_id": self.reaction_id,
            "reaction": self.reaction.to_dict() if self.reaction else None,
            "writes_performed": self.writes_performed,
            "commands_executed": self.commands_executed,
            "diagnostics": [item.to_dict() for item in self.diagnostics],
        }


@dataclass(frozen=True, slots=True)
class StateEnergyBinding:
    """Reviewed VASP energy assigned to one immutable chemical state."""

    binding_id: str
    state_id: str
    state_identity_sha256: str
    reviewed_energy: ReviewedEnergyRecord
    identity_sha256: str
    manual_review_required: bool = True
    writes_performed: bool = False
    commands_executed: bool = False
    schema_version: str = "catex.state-energy-binding.v1"

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "binding_id": self.binding_id,
            "state_id": self.state_id,
            "state_identity_sha256": self.state_identity_sha256,
            "reviewed_energy": {
                "energy_id": self.reviewed_energy.energy_id,
                "record_sha256": self.reviewed_energy.record_sha256,
                "value_eV": self.reviewed_energy.value_ev,
                "energy_family_id": self.reviewed_energy.energy_family_id,
                "kind": self.reviewed_energy.kind.value,
            },
            "identity_sha256": self.identity_sha256,
            "manual_review_required": self.manual_review_required,
            "writes_performed": self.writes_performed,
            "commands_executed": self.commands_executed,
        }


@dataclass(frozen=True, slots=True)
class ScientificDefinitionReview:
    """Explicit review bound to one immutable reaction-domain definition."""

    decision: DefinitionReviewDecision
    subject_kind: DefinitionSubjectKind
    subject_id: str
    subject_identity_sha256: str
    reviewer: str
    reviewed_at_utc: str
    note: str
    review_sha256: str
    human_review_recorded: bool = True
    automatic_approval_performed: bool = False
    writes_performed: bool = False
    commands_executed: bool = False
    schema_version: str = "catex.scientific-definition-review.v1"

    @property
    def approved(self) -> bool:
        return self.decision is DefinitionReviewDecision.APPROVED

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "decision": self.decision.value,
            "approved": self.approved,
            "subject_kind": self.subject_kind.value,
            "subject_id": self.subject_id,
            "subject_identity_sha256": self.subject_identity_sha256,
            "reviewer": self.reviewer,
            "reviewed_at_utc": self.reviewed_at_utc,
            "note": self.note,
            "review_sha256": self.review_sha256,
            "human_review_recorded": self.human_review_recorded,
            "automatic_approval_performed": self.automatic_approval_performed,
            "writes_performed": self.writes_performed,
            "commands_executed": self.commands_executed,
        }


@dataclass(frozen=True, slots=True)
class ReactionElectronicEnergyReport:
    """Reviewed stoichiometric interpretation of a same-family linear energy derivation."""

    reaction_id: str
    reaction_identity_sha256: str
    purpose: ReactionPurpose
    value_ev: float | None
    energy_family_id: str | None
    kind: VaspEnergyKind | None
    linear_derivation: LinearEnergyDerivationReport
    state_energy_binding_sha256s: tuple[str, ...]
    accepted_review_sha256s: tuple[str, ...]
    derivation_sha256: str | None
    diagnostics: tuple[Diagnostic, ...]
    stoichiometry_reviewed: bool
    reference_states_reviewed: bool
    thermochemical_corrections_included: bool = False
    electrochemical_correction_included: bool = False
    writes_performed: bool = False
    commands_executed: bool = False
    schema_version: str = "catex.reaction-electronic-energy.v1"

    @property
    def has_errors(self) -> bool:
        return any(item.severity is Severity.ERROR for item in self.diagnostics)

    @property
    def status(self) -> str:
        return "derived" if self.value_ev is not None and not self.has_errors else "not_derived"

    @property
    def property_kind(self) -> str:
        return f"{self.purpose.value}_electronic_energy"

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "status": self.status,
            "property_kind": self.property_kind,
            "reaction_id": self.reaction_id,
            "reaction_identity_sha256": self.reaction_identity_sha256,
            "purpose": self.purpose.value,
            "value_eV": self.value_ev,
            "energy_family_id": self.energy_family_id,
            "kind": self.kind.value if self.kind else None,
            "linear_derivation": self.linear_derivation.to_dict(),
            "state_energy_binding_sha256s": list(self.state_energy_binding_sha256s),
            "accepted_review_sha256s": list(self.accepted_review_sha256s),
            "derivation_sha256": self.derivation_sha256,
            "stoichiometry_reviewed": self.stoichiometry_reviewed,
            "reference_states_reviewed": self.reference_states_reviewed,
            "thermochemical_corrections_included": (self.thermochemical_corrections_included),
            "electrochemical_correction_included": (self.electrochemical_correction_included),
            "writes_performed": self.writes_performed,
            "commands_executed": self.commands_executed,
            "diagnostics": [item.to_dict() for item in self.diagnostics],
        }


@dataclass(frozen=True, slots=True)
class ThermochemistryProtocol:
    """Shared conventions required before state corrections may be combined."""

    protocol_id: str
    temperature_kelvin: float
    gas_standard_pressure_pa: float
    solution_standard_concentration_mol_l: float
    low_frequency_treatment: LowFrequencyTreatment
    imaginary_mode_policy: ImaginaryModePolicy
    identity_sha256: str
    manual_review_required: bool = True
    writes_performed: bool = False
    commands_executed: bool = False
    schema_version: str = "catex.thermochemistry-protocol.v1"

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "protocol_id": self.protocol_id,
            "temperature_kelvin": self.temperature_kelvin,
            "gas_standard_pressure_pa": self.gas_standard_pressure_pa,
            "solution_standard_concentration_mol_l": (self.solution_standard_concentration_mol_l),
            "low_frequency_treatment": self.low_frequency_treatment.value,
            "imaginary_mode_policy": self.imaginary_mode_policy.value,
            "energy_unit": "eV",
            "entropy_unit": "eV/K",
            "identity_sha256": self.identity_sha256,
            "manual_review_required": self.manual_review_required,
            "writes_performed": self.writes_performed,
            "commands_executed": self.commands_executed,
        }


@dataclass(frozen=True, slots=True)
class ThermochemicalCorrection:
    """Explicit state correction under one reviewed thermochemistry protocol."""

    correction_id: str
    state_id: str
    state_identity_sha256: str
    protocol_id: str
    protocol_identity_sha256: str
    standard_state: StandardState
    source_kind: CorrectionSourceKind
    source_reference: str
    source_sha256s: tuple[str, ...]
    zero_point_energy_ev: float
    thermal_enthalpy_ev: float
    entropy_ev_per_kelvin: float
    solvation_free_energy_ev: float
    other_free_energy_ev: float
    uncertainty_ev: float | None
    identity_sha256: str
    manual_review_required: bool = True
    writes_performed: bool = False
    commands_executed: bool = False
    schema_version: str = "catex.thermochemical-correction.v1"

    def total_correction_ev(self, protocol: ThermochemistryProtocol) -> float:
        if (
            protocol.protocol_id != self.protocol_id
            or protocol.identity_sha256 != self.protocol_identity_sha256
        ):
            raise ValueError("correction and thermochemistry protocol identities do not match")
        return (
            self.zero_point_energy_ev
            + self.thermal_enthalpy_ev
            - protocol.temperature_kelvin * self.entropy_ev_per_kelvin
            + self.solvation_free_energy_ev
            + self.other_free_energy_ev
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "correction_id": self.correction_id,
            "state_id": self.state_id,
            "state_identity_sha256": self.state_identity_sha256,
            "protocol_id": self.protocol_id,
            "protocol_identity_sha256": self.protocol_identity_sha256,
            "standard_state": self.standard_state.value,
            "source_kind": self.source_kind.value,
            "source_reference": self.source_reference,
            "source_sha256s": list(self.source_sha256s),
            "zero_point_energy_eV": self.zero_point_energy_ev,
            "thermal_enthalpy_eV": self.thermal_enthalpy_ev,
            "entropy_eV_per_kelvin": self.entropy_ev_per_kelvin,
            "solvation_free_energy_eV": self.solvation_free_energy_ev,
            "other_free_energy_eV": self.other_free_energy_ev,
            "uncertainty_eV": self.uncertainty_ev,
            "identity_sha256": self.identity_sha256,
            "manual_review_required": self.manual_review_required,
            "writes_performed": self.writes_performed,
            "commands_executed": self.commands_executed,
        }


@dataclass(frozen=True, slots=True)
class ReactionFreeEnergyReport:
    """Reviewed reaction free energy with a complete component audit trail."""

    reaction_id: str
    reaction_identity_sha256: str
    purpose: ReactionPurpose
    thermochemistry_protocol_id: str
    thermochemistry_protocol_identity_sha256: str
    temperature_kelvin: float
    electronic_derivation_sha256: str | None
    energy_family_id: str | None
    electronic_energy_kind: VaspEnergyKind | None
    electronic_energy_ev: float | None
    delta_zero_point_energy_ev: float | None
    delta_thermal_enthalpy_ev: float | None
    negative_t_delta_entropy_ev: float | None
    delta_solvation_free_energy_ev: float | None
    delta_other_free_energy_ev: float | None
    value_ev: float | None
    correction_identity_sha256s: tuple[str, ...]
    accepted_review_sha256s: tuple[str, ...]
    derivation_sha256: str | None
    diagnostics: tuple[Diagnostic, ...]
    standard_states_explicit: bool
    thermochemical_corrections_included: bool
    electrochemical_correction_included: bool = False
    computational_hydrogen_electrode_applied: bool = False
    electrode_potential_v: float | None = None
    ph: float | None = None
    uncertainty_model_applied: bool = False
    writes_performed: bool = False
    commands_executed: bool = False
    schema_version: str = "catex.reaction-free-energy.v1"

    @property
    def has_errors(self) -> bool:
        return any(item.severity is Severity.ERROR for item in self.diagnostics)

    @property
    def status(self) -> str:
        return "derived" if self.value_ev is not None and not self.has_errors else "not_derived"

    @property
    def property_kind(self) -> str:
        return f"{self.purpose.value}_free_energy"

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "status": self.status,
            "property_kind": self.property_kind,
            "reaction_id": self.reaction_id,
            "reaction_identity_sha256": self.reaction_identity_sha256,
            "purpose": self.purpose.value,
            "thermochemistry_protocol_id": self.thermochemistry_protocol_id,
            "thermochemistry_protocol_identity_sha256": (
                self.thermochemistry_protocol_identity_sha256
            ),
            "temperature_kelvin": self.temperature_kelvin,
            "electronic_derivation_sha256": self.electronic_derivation_sha256,
            "energy_family_id": self.energy_family_id,
            "electronic_energy_kind": (
                self.electronic_energy_kind.value if self.electronic_energy_kind else None
            ),
            "components_eV": {
                "electronic_energy": self.electronic_energy_ev,
                "delta_zero_point_energy": self.delta_zero_point_energy_ev,
                "delta_thermal_enthalpy": self.delta_thermal_enthalpy_ev,
                "negative_t_delta_entropy": self.negative_t_delta_entropy_ev,
                "delta_solvation_free_energy": self.delta_solvation_free_energy_ev,
                "delta_other_free_energy": self.delta_other_free_energy_ev,
            },
            "value_eV": self.value_ev,
            "correction_identity_sha256s": list(self.correction_identity_sha256s),
            "accepted_review_sha256s": list(self.accepted_review_sha256s),
            "derivation_sha256": self.derivation_sha256,
            "standard_states_explicit": self.standard_states_explicit,
            "thermochemical_corrections_included": (self.thermochemical_corrections_included),
            "electrochemical_correction_included": (self.electrochemical_correction_included),
            "computational_hydrogen_electrode_applied": (
                self.computational_hydrogen_electrode_applied
            ),
            "electrode_potential_v": self.electrode_potential_v,
            "pH": self.ph,
            "uncertainty_model_applied": self.uncertainty_model_applied,
            "writes_performed": self.writes_performed,
            "commands_executed": self.commands_executed,
            "diagnostics": [item.to_dict() for item in self.diagnostics],
        }


@dataclass(frozen=True, slots=True)
class ComputationalHydrogenElectrodeProtocol:
    """Reviewed potential/pH convention for exact proton-electron pair corrections."""

    protocol_id: str
    reference_electrode: ReferenceElectrode
    electrode_potential_v: float
    ph: float
    temperature_kelvin: float
    source_reference: str
    source_sha256s: tuple[str, ...]
    identity_sha256: str
    manual_review_required: bool = True
    writes_performed: bool = False
    commands_executed: bool = False
    schema_version: str = "catex.computational-hydrogen-electrode-protocol.v1"

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "protocol_id": self.protocol_id,
            "reference_electrode": self.reference_electrode.value,
            "electrode_potential_v": self.electrode_potential_v,
            "pH": self.ph,
            "temperature_kelvin": self.temperature_kelvin,
            "source_reference": self.source_reference,
            "source_sha256s": list(self.source_sha256s),
            "identity_sha256": self.identity_sha256,
            "manual_review_required": self.manual_review_required,
            "writes_performed": self.writes_performed,
            "commands_executed": self.commands_executed,
        }


@dataclass(frozen=True, slots=True)
class ComputationalHydrogenElectrodeReport:
    """Potential/pH correction applied to one intact thermochemical free energy."""

    reaction_id: str
    reaction_identity_sha256: str
    base_free_energy_derivation_sha256: str
    protocol_id: str
    protocol_identity_sha256: str
    reference_electrode: ReferenceElectrode
    electrode_potential_v: float
    ph: float
    temperature_kelvin: float
    proton_electron_pairs_consumed: RationalValue
    potential_correction_ev: float | None
    ph_correction_ev: float | None
    electrochemical_correction_ev: float | None
    base_free_energy_ev: float | None
    value_ev: float | None
    protocol_review_sha256: str | None
    source_sha256s: tuple[str, ...]
    derivation_sha256: str | None
    diagnostics: tuple[Diagnostic, ...]
    positive_pairs_consumed_negative_potential_lowers_free_energy: bool = True
    electrochemical_correction_included: bool = False
    computational_hydrogen_electrode_applied: bool = False
    uncertainty_model_applied: bool = False
    manual_interpretation_required: bool = True
    writes_performed: bool = False
    commands_executed: bool = False
    schema_version: str = "catex.computational-hydrogen-electrode-report.v1"

    @property
    def has_errors(self) -> bool:
        return any(item.severity is Severity.ERROR for item in self.diagnostics)

    @property
    def status(self) -> str:
        return "derived" if self.value_ev is not None and not self.has_errors else "not_derived"

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "status": self.status,
            "reaction_id": self.reaction_id,
            "reaction_identity_sha256": self.reaction_identity_sha256,
            "base_free_energy_derivation_sha256": self.base_free_energy_derivation_sha256,
            "protocol_id": self.protocol_id,
            "protocol_identity_sha256": self.protocol_identity_sha256,
            "reference_electrode": self.reference_electrode.value,
            "electrode_potential_v": self.electrode_potential_v,
            "pH": self.ph,
            "temperature_kelvin": self.temperature_kelvin,
            "proton_electron_pairs_consumed": self.proton_electron_pairs_consumed.to_dict(),
            "potential_correction_eV": self.potential_correction_ev,
            "pH_correction_eV": self.ph_correction_ev,
            "electrochemical_correction_eV": self.electrochemical_correction_ev,
            "base_free_energy_eV": self.base_free_energy_ev,
            "value_eV": self.value_ev,
            "protocol_review_sha256": self.protocol_review_sha256,
            "source_sha256s": list(self.source_sha256s),
            "derivation_sha256": self.derivation_sha256,
            "positive_pairs_consumed_negative_potential_lowers_free_energy": (
                self.positive_pairs_consumed_negative_potential_lowers_free_energy
            ),
            "electrochemical_correction_included": self.electrochemical_correction_included,
            "computational_hydrogen_electrode_applied": (
                self.computational_hydrogen_electrode_applied
            ),
            "uncertainty_model_applied": self.uncertainty_model_applied,
            "manual_interpretation_required": self.manual_interpretation_required,
            "writes_performed": self.writes_performed,
            "commands_executed": self.commands_executed,
            "diagnostics": [item.to_dict() for item in self.diagnostics],
        }
