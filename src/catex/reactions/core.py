"""Balanced reaction construction and fail-closed energetic derivations."""

from __future__ import annotations

import hashlib
import json
import math
import re
from collections.abc import Sequence
from dataclasses import replace
from datetime import datetime
from fractions import Fraction
from typing import Any

from pymatgen.core import Composition

from catex.catalysis import (
    Adsorbate,
    AdsorptionConfiguration,
    CatalystSystem,
    is_intact_catalysis_identity,
)
from catex.energetics import (
    EnergyTerm,
    LinearEnergyDerivationReport,
    ReviewedEnergyRecord,
    assess_energy_compatibility,
    derive_linear_energy,
)
from catex.models import Diagnostic, Severity
from catex.reactions.models import (
    ChemicalPhase,
    ChemicalState,
    ChemicalStateSubjectKind,
    ComputationalHydrogenElectrodeProtocol,
    ComputationalHydrogenElectrodeReport,
    CorrectionSourceKind,
    DefinitionReviewDecision,
    DefinitionSubjectKind,
    ElementAmount,
    ImaginaryModePolicy,
    LowFrequencyTreatment,
    RationalValue,
    ReactionDefinition,
    ReactionDefinitionReport,
    ReactionElectronicEnergyReport,
    ReactionFreeEnergyReport,
    ReactionPurpose,
    ReactionTerm,
    ReferenceElectrode,
    ReferenceStateEntry,
    ReferenceStateSet,
    ScientificDefinitionReview,
    StandardState,
    StateEnergyBinding,
    StateStoichiometry,
    ThermochemicalCorrection,
    ThermochemistryProtocol,
)

_IDENTIFIER = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,99}$")
_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_UTC_TIMESTAMP = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$")
_UTC_FORMAT = "%Y-%m-%dT%H:%M:%SZ"

_DefinitionSubject = (
    ChemicalState
    | ReferenceStateSet
    | ReactionDefinition
    | StateEnergyBinding
    | ThermochemistryProtocol
    | ThermochemicalCorrection
    | ComputationalHydrogenElectrodeProtocol
)


def _digest(payload: dict[str, Any]) -> str:
    encoded = json.dumps(
        payload,
        allow_nan=False,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _matches(pattern: re.Pattern[str], value: object) -> bool:
    return isinstance(value, str) and pattern.fullmatch(value) is not None


def _identifier(value: str, *, field: str) -> str:
    if not _matches(_IDENTIFIER, value):
        raise ValueError(f"{field} must be a safe identifier of at most 100 characters")
    return value


def _one_line(value: str, *, field: str, maximum: int) -> str:
    if not isinstance(value, str) or any(item in value for item in "\r\n"):
        raise ValueError(f"{field} must be one line")
    normalized = value.strip()
    if not normalized or len(normalized) > maximum:
        raise ValueError(f"{field} must be non-empty and at most {maximum} characters")
    return normalized


def _timestamp(value: str) -> None:
    if not isinstance(value, str) or _UTC_TIMESTAMP.fullmatch(value) is None:
        raise ValueError("reviewed_at_utc must use YYYY-MM-DDTHH:MM:SSZ")
    try:
        datetime.strptime(value, _UTC_FORMAT)
    except ValueError as exc:
        raise ValueError("reviewed_at_utc must be a valid UTC timestamp") from exc


def _fraction(value: int | str | Fraction, *, field: str) -> Fraction:
    if isinstance(value, bool) or not isinstance(value, int | str | Fraction):
        raise ValueError(f"{field} must be an integer, rational string, or Fraction")
    try:
        result = Fraction(value)
    except (ValueError, ZeroDivisionError) as exc:
        raise ValueError(f"{field} must be a valid finite rational") from exc
    return result


def _rational(value: Fraction) -> RationalValue:
    return RationalValue(value.numerator, value.denominator)


def _composition(formula: str) -> tuple[ElementAmount, ...]:
    if not formula:
        return ()
    try:
        composition = Composition(formula)
    except (TypeError, ValueError) as exc:
        raise ValueError("formula must be a valid chemical composition") from exc
    return tuple(
        ElementAmount(
            element=str(element),
            amount=_rational(Fraction(str(float(amount))).limit_denominator(1_000_000)),
        )
        for element, amount in sorted(composition.items(), key=lambda item: str(item[0]))
    )


def _sum_compositions(*formulas: str) -> str:
    combined = Composition({})
    for formula in formulas:
        combined += Composition(formula)
    return combined.formula


def _state_identity(state: ChemicalState) -> dict[str, Any]:
    return {
        "schema": "catex.chemical-state-content.v1",
        "state_id": state.state_id,
        "phase": state.phase.value,
        "formula": state.formula,
        "composition": [item.to_dict() for item in state.composition],
        "charge_e": state.charge_e.to_dict(),
        "subject_kind": state.subject_kind.value,
        "subject_id": state.subject_id,
        "subject_identity_sha256": state.subject_identity_sha256,
    }


def _build_state(
    *,
    state_id: str,
    phase: ChemicalPhase,
    formula: str,
    charge: Fraction,
    subject_kind: ChemicalStateSubjectKind,
    subject_id: str,
    subject_identity_sha256: str,
) -> ChemicalState:
    state_id_value = _identifier(state_id, field="state_id")
    if not isinstance(phase, ChemicalPhase):
        raise ValueError("phase must be a ChemicalPhase")
    if not _matches(_SHA256, subject_identity_sha256):
        raise ValueError("subject_identity_sha256 must be a SHA256")
    provisional = ChemicalState(
        state_id=state_id_value,
        phase=phase,
        formula=formula,
        composition=_composition(formula),
        charge_e=_rational(charge),
        subject_kind=subject_kind,
        subject_id=_identifier(subject_id, field="subject_id"),
        subject_identity_sha256=subject_identity_sha256,
        identity_sha256="0" * 64,
    )
    return replace(provisional, identity_sha256=_digest(_state_identity(provisional)))


def create_catalyst_state(
    catalyst: CatalystSystem,
    *,
    state_id: str,
    phase: ChemicalPhase = ChemicalPhase.SURFACE,
) -> ChemicalState:
    """Bind a catalyst identity to a surface or solid chemical state."""

    if not is_intact_catalysis_identity(catalyst):
        raise ValueError("catalyst identity is invalid")
    if phase not in {ChemicalPhase.SURFACE, ChemicalPhase.SOLID}:
        raise ValueError("catalyst state phase must be surface or solid")
    return _build_state(
        state_id=state_id,
        phase=phase,
        formula=catalyst.formula,
        charge=Fraction(str(catalyst.charge_e)),
        subject_kind=ChemicalStateSubjectKind.CATALYST,
        subject_id=catalyst.catalyst_id,
        subject_identity_sha256=catalyst.identity_sha256,
    )


def create_adsorbate_state(
    adsorbate: Adsorbate,
    *,
    state_id: str,
    phase: ChemicalPhase,
) -> ChemicalState:
    """Bind a molecular identity to an explicit gas, liquid, or solvated state."""

    if not is_intact_catalysis_identity(adsorbate):
        raise ValueError("adsorbate identity is invalid")
    if phase not in {ChemicalPhase.GAS, ChemicalPhase.LIQUID, ChemicalPhase.SOLVATED}:
        raise ValueError("molecular reference phase must be gas, liquid, or solvated")
    return _build_state(
        state_id=state_id,
        phase=phase,
        formula=adsorbate.formula,
        charge=Fraction(adsorbate.charge_e),
        subject_kind=ChemicalStateSubjectKind.ADSORBATE,
        subject_id=adsorbate.adsorbate_id,
        subject_identity_sha256=adsorbate.identity_sha256,
    )


def create_adsorption_state(
    catalyst: CatalystSystem,
    adsorbate: Adsorbate,
    configuration: AdsorptionConfiguration,
    *,
    state_id: str,
) -> ChemicalState:
    """Bind a linked single-adsorbate configuration to its combined composition."""

    if not all(is_intact_catalysis_identity(item) for item in (catalyst, adsorbate, configuration)):
        raise ValueError("adsorption state requires intact catalysis identities")
    if (
        configuration.catalyst_identity_sha256 != catalyst.identity_sha256
        or configuration.adsorbate_identity_sha256 != adsorbate.identity_sha256
    ):
        raise ValueError("configuration does not link the supplied catalyst and adsorbate")
    return _build_state(
        state_id=state_id,
        phase=ChemicalPhase.ADSORBED,
        formula=_sum_compositions(catalyst.formula, adsorbate.formula),
        charge=Fraction(str(catalyst.charge_e)) + Fraction(adsorbate.charge_e),
        subject_kind=ChemicalStateSubjectKind.ADSORPTION_CONFIGURATION,
        subject_id=configuration.configuration_id,
        subject_identity_sha256=configuration.identity_sha256,
    )


def create_external_reference_state(
    *,
    state_id: str,
    reference_id: str,
    provenance_sha256: str,
    formula: str,
    formal_charge_e: int | str | Fraction,
    phase: ChemicalPhase,
) -> ChemicalState:
    """Create an explicit external reference, including an electron reservoir when requested."""

    charge = _fraction(formal_charge_e, field="formal_charge_e")
    if phase not in {
        ChemicalPhase.ELECTRON,
        ChemicalPhase.GAS,
        ChemicalPhase.LIQUID,
        ChemicalPhase.SOLID,
        ChemicalPhase.SOLVATED,
    }:
        raise ValueError(
            "external references must be electron, gas, liquid, solid, or solvated states"
        )
    if phase is ChemicalPhase.ELECTRON:
        if formula or charge != -1:
            raise ValueError("electron state requires empty formula and formal charge -1")
    elif not formula:
        raise ValueError("non-electron reference states require a formula")
    return _build_state(
        state_id=state_id,
        phase=phase,
        formula=formula,
        charge=charge,
        subject_kind=ChemicalStateSubjectKind.EXTERNAL_REFERENCE,
        subject_id=reference_id,
        subject_identity_sha256=provenance_sha256,
    )


def _valid_state(state: object) -> bool:
    try:
        return (
            isinstance(state, ChemicalState)
            and state.schema_version == "catex.chemical-state.v1"
            and _matches(_IDENTIFIER, state.state_id)
            and isinstance(state.phase, ChemicalPhase)
            and isinstance(state.subject_kind, ChemicalStateSubjectKind)
            and _matches(_IDENTIFIER, state.subject_id)
            and _matches(_SHA256, state.subject_identity_sha256)
            and _matches(_SHA256, state.identity_sha256)
            and state.composition == _composition(state.formula)
            and state.charge_e.denominator != 0
            and (
                (
                    state.phase is ChemicalPhase.ELECTRON
                    and not state.formula
                    and state.charge_e.fraction == -1
                    and state.subject_kind is ChemicalStateSubjectKind.EXTERNAL_REFERENCE
                )
                or (state.phase is not ChemicalPhase.ELECTRON and bool(state.formula))
            )
            and state.identity_sha256 == _digest(_state_identity(state))
            and state.manual_review_required
            and not state.writes_performed
            and not state.commands_executed
        )
    except (AttributeError, TypeError, ValueError, ZeroDivisionError):
        return False


def _reference_set_identity(reference_set: ReferenceStateSet) -> dict[str, Any]:
    return {
        "schema": "catex.reference-state-set-content.v1",
        "reference_set_id": reference_set.reference_set_id,
        "entries": [item.to_dict() for item in reference_set.entries],
    }


def create_reference_state_set(
    states: Sequence[ChemicalState],
    *,
    reference_set_id: str,
) -> ReferenceStateSet:
    """Create a deterministic set of explicit reference-state identities."""

    reference_set_id_value = _identifier(reference_set_id, field="reference_set_id")
    if not states or any(not _valid_state(item) for item in states):
        raise ValueError("reference states must be non-empty intact ChemicalState records")
    entries = tuple(
        sorted(
            (ReferenceStateEntry(item.state_id, item.identity_sha256) for item in states),
            key=lambda item: item.state_id,
        )
    )
    if len({item.state_id for item in entries}) != len(entries):
        raise ValueError("reference state IDs must be unique")
    provisional = ReferenceStateSet(
        reference_set_id=reference_set_id_value,
        entries=entries,
        identity_sha256="0" * 64,
    )
    return replace(
        provisional,
        identity_sha256=_digest(_reference_set_identity(provisional)),
    )


def _valid_reference_set(reference_set: object) -> bool:
    try:
        return (
            isinstance(reference_set, ReferenceStateSet)
            and reference_set.schema_version == "catex.reference-state-set.v1"
            and _matches(_IDENTIFIER, reference_set.reference_set_id)
            and _matches(_SHA256, reference_set.identity_sha256)
            and reference_set.identity_sha256 == _digest(_reference_set_identity(reference_set))
            and bool(reference_set.entries)
            and len({item.state_id for item in reference_set.entries}) == len(reference_set.entries)
            and all(
                isinstance(item, ReferenceStateEntry)
                and _matches(_IDENTIFIER, item.state_id)
                and _matches(_SHA256, item.state_identity_sha256)
                for item in reference_set.entries
            )
            and tuple(item.state_id for item in reference_set.entries)
            == tuple(sorted(item.state_id for item in reference_set.entries))
            and reference_set.manual_review_required
            and not reference_set.writes_performed
            and not reference_set.commands_executed
        )
    except (AttributeError, TypeError, ValueError):
        return False


def _reaction_identity(reaction: ReactionDefinition) -> dict[str, Any]:
    return {
        "schema": "catex.reaction-definition-content.v1",
        "reaction_id": reaction.reaction_id,
        "purpose": reaction.purpose.value,
        "terms": [item.to_dict() for item in reaction.terms],
        "reference_set_id": reaction.reference_set_id,
        "reference_set_identity_sha256": reaction.reference_set_identity_sha256,
    }


def define_reaction(
    stoichiometry: Sequence[StateStoichiometry],
    *,
    reaction_id: str,
    purpose: ReactionPurpose,
    reference_set: ReferenceStateSet | None = None,
) -> ReactionDefinitionReport:
    """Validate exact element and charge balance before creating a reaction identity."""

    reaction_id_value = _identifier(reaction_id, field="reaction_id")
    if not isinstance(purpose, ReactionPurpose):
        raise ValueError("purpose must be a ReactionPurpose")
    diagnostics: list[Diagnostic] = []
    normalized: list[tuple[ChemicalState, Fraction]] = []
    for index, item in enumerate(stoichiometry):
        if not isinstance(item, StateStoichiometry) or not _valid_state(item.state):
            diagnostics.append(
                Diagnostic(
                    "REACTION_STATE_INVALID",
                    Severity.ERROR,
                    "Every reaction term must reference an intact ChemicalState.",
                    {"position_0based": index},
                )
            )
            continue
        try:
            coefficient = _fraction(item.coefficient, field="reaction coefficient")
        except ValueError:
            diagnostics.append(
                Diagnostic(
                    "REACTION_COEFFICIENT_INVALID",
                    Severity.ERROR,
                    "Reaction coefficients must be non-zero exact rational values.",
                    {"position_0based": index},
                )
            )
            continue
        if coefficient == 0:
            diagnostics.append(
                Diagnostic(
                    "REACTION_COEFFICIENT_INVALID",
                    Severity.ERROR,
                    "Reaction coefficients must be non-zero exact rational values.",
                    {"position_0based": index},
                )
            )
            continue
        normalized.append((item.state, coefficient))

    state_ids = tuple(item.state_id for item, _ in normalized)
    if not normalized or len(set(state_ids)) != len(state_ids):
        diagnostics.append(
            Diagnostic(
                "REACTION_STATES_EMPTY_OR_DUPLICATED",
                Severity.ERROR,
                "A reaction requires unique chemical state IDs.",
            )
        )
    if normalized and (
        not any(coefficient < 0 for _, coefficient in normalized)
        or not any(coefficient > 0 for _, coefficient in normalized)
    ):
        diagnostics.append(
            Diagnostic(
                "REACTION_SIDES_INVALID",
                Severity.ERROR,
                "A reaction requires at least one reactant and one product.",
            )
        )

    normalized.sort(key=lambda item: item[0].state_id)
    element_balance: dict[str, Fraction] = {}
    charge_balance = Fraction(0)
    for state, coefficient in normalized:
        for item in state.composition:
            element_balance[item.element] = (
                element_balance.get(item.element, Fraction(0)) + coefficient * item.amount.fraction
            )
        charge_balance += coefficient * state.charge_e.fraction
    nonzero_elements = {
        element: str(amount) for element, amount in element_balance.items() if amount != 0
    }
    if nonzero_elements:
        diagnostics.append(
            Diagnostic(
                "REACTION_ELEMENT_UNBALANCED",
                Severity.ERROR,
                "Reaction element counts are not balanced.",
                {"nonzero_element_balances": tuple(sorted(nonzero_elements.items()))},
            )
        )
    if charge_balance != 0:
        diagnostics.append(
            Diagnostic(
                "REACTION_CHARGE_UNBALANCED",
                Severity.ERROR,
                "Reaction formal charge is not balanced.",
                {"charge_balance_e": str(charge_balance)},
            )
        )

    requires_references = purpose in {ReactionPurpose.ADSORPTION, ReactionPurpose.FORMATION}
    if reference_set is not None and not _valid_reference_set(reference_set):
        diagnostics.append(
            Diagnostic(
                "REFERENCE_STATE_SET_INVALID",
                Severity.ERROR,
                "The supplied reference-state set is not intact.",
            )
        )
    if requires_references and reference_set is None:
        diagnostics.append(
            Diagnostic(
                "REFERENCE_STATE_SET_REQUIRED",
                Severity.ERROR,
                "Adsorption and formation reactions require an explicit reference-state set.",
            )
        )
    if reference_set is not None and _valid_reference_set(reference_set):
        reactant_identities = {
            (state.state_id, state.identity_sha256)
            for state, coefficient in normalized
            if coefficient < 0
        }
        missing = tuple(
            item.state_id
            for item in reference_set.entries
            if (item.state_id, item.state_identity_sha256) not in reactant_identities
        )
        if missing:
            diagnostics.append(
                Diagnostic(
                    "REFERENCE_STATE_NOT_A_REACTANT",
                    Severity.ERROR,
                    "Every declared reference state must appear as the same reaction reactant.",
                    {"state_ids": missing},
                )
            )
        if requires_references:
            declared_references = {
                (item.state_id, item.state_identity_sha256) for item in reference_set.entries
            }
            omitted = tuple(
                state_id
                for state_id, state_sha256 in sorted(reactant_identities)
                if (state_id, state_sha256) not in declared_references
            )
            if omitted:
                diagnostics.append(
                    Diagnostic(
                        "REFERENCE_STATE_COVERAGE_INCOMPLETE",
                        Severity.ERROR,
                        (
                            "Adsorption and formation reference sets must explicitly cover "
                            "every reactant state."
                        ),
                        {"state_ids": omitted},
                    )
                )

    if diagnostics:
        return ReactionDefinitionReport(
            reaction_id=reaction_id_value,
            reaction=None,
            diagnostics=tuple(diagnostics),
        )
    terms = tuple(
        ReactionTerm(state.state_id, state.identity_sha256, _rational(coefficient))
        for state, coefficient in normalized
    )
    provisional = ReactionDefinition(
        reaction_id=reaction_id_value,
        purpose=purpose,
        terms=terms,
        reference_set_id=reference_set.reference_set_id if reference_set else None,
        reference_set_identity_sha256=(reference_set.identity_sha256 if reference_set else None),
        identity_sha256="0" * 64,
    )
    reaction = replace(provisional, identity_sha256=_digest(_reaction_identity(provisional)))
    return ReactionDefinitionReport(
        reaction_id=reaction_id_value,
        reaction=reaction,
        diagnostics=(),
    )


def _valid_reaction(reaction: object) -> bool:
    try:
        coefficients = tuple(item.coefficient.fraction for item in reaction.terms)
        return (
            isinstance(reaction, ReactionDefinition)
            and reaction.schema_version == "catex.reaction-definition.v1"
            and _matches(_IDENTIFIER, reaction.reaction_id)
            and _matches(_SHA256, reaction.identity_sha256)
            and reaction.identity_sha256 == _digest(_reaction_identity(reaction))
            and reaction.element_and_charge_balanced
            and bool(reaction.terms)
            and all(
                isinstance(item, ReactionTerm)
                and _matches(_IDENTIFIER, item.state_id)
                and _matches(_SHA256, item.state_identity_sha256)
                and item.coefficient.denominator != 0
                and item.coefficient.fraction != 0
                for item in reaction.terms
            )
            and tuple(item.state_id for item in reaction.terms)
            == tuple(sorted(item.state_id for item in reaction.terms))
            and len({item.state_id for item in reaction.terms}) == len(reaction.terms)
            and any(item < 0 for item in coefficients)
            and any(item > 0 for item in coefficients)
            and (
                (
                    reaction.reference_set_id is None
                    and reaction.reference_set_identity_sha256 is None
                    and reaction.purpose
                    not in {ReactionPurpose.ADSORPTION, ReactionPurpose.FORMATION}
                )
                or (
                    _matches(_IDENTIFIER, reaction.reference_set_id)
                    and _matches(_SHA256, reaction.reference_set_identity_sha256)
                )
            )
            and reaction.manual_review_required
            and not reaction.writes_performed
            and not reaction.commands_executed
        )
    except (AttributeError, TypeError, ValueError, ZeroDivisionError):
        return False


def _state_energy_identity(binding: StateEnergyBinding) -> dict[str, Any]:
    return {
        "schema": "catex.state-energy-binding-content.v1",
        "binding_id": binding.binding_id,
        "state_id": binding.state_id,
        "state_identity_sha256": binding.state_identity_sha256,
        "energy_id": binding.reviewed_energy.energy_id,
        "reviewed_energy_record_sha256": binding.reviewed_energy.record_sha256,
        "value_eV": binding.reviewed_energy.value_ev,
        "energy_family_id": binding.reviewed_energy.energy_family_id,
        "kind": binding.reviewed_energy.kind.value,
    }


def bind_state_energy(
    state: ChemicalState,
    reviewed_energy: ReviewedEnergyRecord,
    *,
    binding_id: str,
) -> StateEnergyBinding:
    """Assign one intact reviewed VASP energy to one immutable chemical state."""

    if not _valid_state(state):
        raise ValueError("state must be an intact ChemicalState")
    if not assess_energy_compatibility((reviewed_energy,)).compatible:
        raise ValueError("reviewed_energy must be an intact accepted VASP energy")
    provisional = StateEnergyBinding(
        binding_id=_identifier(binding_id, field="binding_id"),
        state_id=state.state_id,
        state_identity_sha256=state.identity_sha256,
        reviewed_energy=reviewed_energy,
        identity_sha256="0" * 64,
    )
    return replace(provisional, identity_sha256=_digest(_state_energy_identity(provisional)))


def _valid_state_energy(binding: object) -> bool:
    try:
        return (
            isinstance(binding, StateEnergyBinding)
            and binding.schema_version == "catex.state-energy-binding.v1"
            and _matches(_IDENTIFIER, binding.binding_id)
            and _matches(_SHA256, binding.identity_sha256)
            and assess_energy_compatibility((binding.reviewed_energy,)).compatible
            and binding.identity_sha256 == _digest(_state_energy_identity(binding))
            and binding.manual_review_required
            and not binding.writes_performed
            and not binding.commands_executed
        )
    except (AttributeError, TypeError, ValueError):
        return False


def _protocol_identity(protocol: ThermochemistryProtocol) -> dict[str, Any]:
    return {
        "schema": "catex.thermochemistry-protocol-content.v1",
        "protocol_id": protocol.protocol_id,
        "temperature_kelvin": protocol.temperature_kelvin,
        "gas_standard_pressure_pa": protocol.gas_standard_pressure_pa,
        "solution_standard_concentration_mol_l": (protocol.solution_standard_concentration_mol_l),
        "low_frequency_treatment": protocol.low_frequency_treatment.value,
        "imaginary_mode_policy": protocol.imaginary_mode_policy.value,
    }


def create_thermochemistry_protocol(
    *,
    protocol_id: str,
    temperature_kelvin: float,
    gas_standard_pressure_pa: float = 100_000.0,
    solution_standard_concentration_mol_l: float = 1.0,
    low_frequency_treatment: LowFrequencyTreatment,
    imaginary_mode_policy: ImaginaryModePolicy,
) -> ThermochemistryProtocol:
    """Create explicit shared temperature and standard-state conventions."""

    numerical = (
        temperature_kelvin,
        gas_standard_pressure_pa,
        solution_standard_concentration_mol_l,
    )
    if any(
        not isinstance(item, int | float)
        or isinstance(item, bool)
        or not math.isfinite(item)
        or item <= 0
        for item in numerical
    ):
        raise ValueError("temperature, pressure, and concentration must be finite and positive")
    if not isinstance(low_frequency_treatment, LowFrequencyTreatment) or not isinstance(
        imaginary_mode_policy, ImaginaryModePolicy
    ):
        raise ValueError("frequency and imaginary-mode policies must use explicit enums")
    provisional = ThermochemistryProtocol(
        protocol_id=_identifier(protocol_id, field="protocol_id"),
        temperature_kelvin=float(temperature_kelvin),
        gas_standard_pressure_pa=float(gas_standard_pressure_pa),
        solution_standard_concentration_mol_l=float(solution_standard_concentration_mol_l),
        low_frequency_treatment=low_frequency_treatment,
        imaginary_mode_policy=imaginary_mode_policy,
        identity_sha256="0" * 64,
    )
    return replace(provisional, identity_sha256=_digest(_protocol_identity(provisional)))


def _valid_protocol(protocol: object) -> bool:
    try:
        numerical = (
            protocol.temperature_kelvin,
            protocol.gas_standard_pressure_pa,
            protocol.solution_standard_concentration_mol_l,
        )
        return (
            isinstance(protocol, ThermochemistryProtocol)
            and protocol.schema_version == "catex.thermochemistry-protocol.v1"
            and _matches(_IDENTIFIER, protocol.protocol_id)
            and _matches(_SHA256, protocol.identity_sha256)
            and all(
                isinstance(item, int | float)
                and not isinstance(item, bool)
                and math.isfinite(item)
                and item > 0
                for item in numerical
            )
            and isinstance(protocol.low_frequency_treatment, LowFrequencyTreatment)
            and isinstance(protocol.imaginary_mode_policy, ImaginaryModePolicy)
            and protocol.identity_sha256 == _digest(_protocol_identity(protocol))
            and protocol.manual_review_required
            and not protocol.writes_performed
            and not protocol.commands_executed
        )
    except (AttributeError, TypeError, ValueError):
        return False


def _che_protocol_identity(protocol: ComputationalHydrogenElectrodeProtocol) -> dict[str, Any]:
    return {
        "schema": "catex.computational-hydrogen-electrode-protocol-content.v1",
        "protocol_id": protocol.protocol_id,
        "reference_electrode": protocol.reference_electrode.value,
        "electrode_potential_v": protocol.electrode_potential_v,
        "pH": protocol.ph,
        "temperature_kelvin": protocol.temperature_kelvin,
        "source_reference": protocol.source_reference,
        "source_sha256s": list(protocol.source_sha256s),
    }


def create_computational_hydrogen_electrode_protocol(
    *,
    protocol_id: str,
    reference_electrode: ReferenceElectrode,
    electrode_potential_v: float,
    ph: float,
    temperature_kelvin: float,
    source_reference: str,
    source_sha256s: Sequence[str],
) -> ComputationalHydrogenElectrodeProtocol:
    """Create an explicit CHE potential, pH, scale, temperature, and source convention."""

    if not isinstance(reference_electrode, ReferenceElectrode):
        raise ValueError("reference_electrode must be SHE or RHE")
    numerical = (electrode_potential_v, ph, temperature_kelvin)
    if any(
        not isinstance(item, int | float) or isinstance(item, bool) or not math.isfinite(item)
        for item in numerical
    ):
        raise ValueError("CHE potential, pH, and temperature must be finite")
    if ph < 0 or temperature_kelvin <= 0:
        raise ValueError("CHE pH must be non-negative and temperature must be positive")
    hashes = tuple(sorted(source_sha256s))
    if (
        not hashes
        or len(set(hashes)) != len(hashes)
        or any(not _matches(_SHA256, item) for item in hashes)
    ):
        raise ValueError("source_sha256s must contain unique lowercase SHA256 values")
    provisional = ComputationalHydrogenElectrodeProtocol(
        protocol_id=_identifier(protocol_id, field="protocol_id"),
        reference_electrode=reference_electrode,
        electrode_potential_v=float(electrode_potential_v),
        ph=float(ph),
        temperature_kelvin=float(temperature_kelvin),
        source_reference=_one_line(source_reference, field="source_reference", maximum=500),
        source_sha256s=hashes,
        identity_sha256="0" * 64,
    )
    return replace(
        provisional,
        identity_sha256=_digest(_che_protocol_identity(provisional)),
    )


def _valid_che_protocol(protocol: object) -> bool:
    try:
        return (
            isinstance(protocol, ComputationalHydrogenElectrodeProtocol)
            and protocol.schema_version == "catex.computational-hydrogen-electrode-protocol.v1"
            and _matches(_IDENTIFIER, protocol.protocol_id)
            and isinstance(protocol.reference_electrode, ReferenceElectrode)
            and all(
                isinstance(item, int | float) and not isinstance(item, bool) and math.isfinite(item)
                for item in (
                    protocol.electrode_potential_v,
                    protocol.ph,
                    protocol.temperature_kelvin,
                )
            )
            and protocol.ph >= 0
            and protocol.temperature_kelvin > 0
            and _one_line(protocol.source_reference, field="source_reference", maximum=500)
            == protocol.source_reference
            and bool(protocol.source_sha256s)
            and len(set(protocol.source_sha256s)) == len(protocol.source_sha256s)
            and tuple(sorted(protocol.source_sha256s)) == protocol.source_sha256s
            and all(_matches(_SHA256, item) for item in protocol.source_sha256s)
            and _matches(_SHA256, protocol.identity_sha256)
            and protocol.identity_sha256 == _digest(_che_protocol_identity(protocol))
            and protocol.manual_review_required
            and not protocol.writes_performed
            and not protocol.commands_executed
        )
    except (AttributeError, TypeError, ValueError):
        return False


_PHASE_STANDARD_STATE = {
    ChemicalPhase.ADSORBED: StandardState.SURFACE_SITE,
    ChemicalPhase.ELECTRON: StandardState.ELECTRON_RESERVOIR,
    ChemicalPhase.GAS: StandardState.GAS_1_BAR,
    ChemicalPhase.LIQUID: StandardState.PURE_LIQUID,
    ChemicalPhase.SOLID: StandardState.PURE_SOLID,
    ChemicalPhase.SOLVATED: StandardState.SOLUTION_1_M,
    ChemicalPhase.SURFACE: StandardState.SURFACE_SITE,
}


def _correction_identity(correction: ThermochemicalCorrection) -> dict[str, Any]:
    return {
        "schema": "catex.thermochemical-correction-content.v1",
        "correction_id": correction.correction_id,
        "state_id": correction.state_id,
        "state_identity_sha256": correction.state_identity_sha256,
        "protocol_id": correction.protocol_id,
        "protocol_identity_sha256": correction.protocol_identity_sha256,
        "standard_state": correction.standard_state.value,
        "source_kind": correction.source_kind.value,
        "source_reference": correction.source_reference,
        "source_sha256s": list(correction.source_sha256s),
        "zero_point_energy_eV": correction.zero_point_energy_ev,
        "thermal_enthalpy_eV": correction.thermal_enthalpy_ev,
        "entropy_eV_per_kelvin": correction.entropy_ev_per_kelvin,
        "solvation_free_energy_eV": correction.solvation_free_energy_ev,
        "other_free_energy_eV": correction.other_free_energy_ev,
        "uncertainty_eV": correction.uncertainty_ev,
    }


def create_thermochemical_correction(
    state: ChemicalState,
    protocol: ThermochemistryProtocol,
    *,
    correction_id: str,
    standard_state: StandardState,
    source_kind: CorrectionSourceKind,
    source_reference: str,
    source_sha256s: Sequence[str],
    zero_point_energy_ev: float,
    thermal_enthalpy_ev: float,
    entropy_ev_per_kelvin: float,
    solvation_free_energy_ev: float = 0.0,
    other_free_energy_ev: float = 0.0,
    uncertainty_ev: float | None = None,
) -> ThermochemicalCorrection:
    """Create a source-bound state correction with explicit units and standard state."""

    if not _valid_state(state) or not _valid_protocol(protocol):
        raise ValueError("state and thermochemistry protocol must be intact")
    if standard_state is not _PHASE_STANDARD_STATE[state.phase]:
        raise ValueError("standard_state is incompatible with the chemical phase")
    if not isinstance(source_kind, CorrectionSourceKind):
        raise ValueError("source_kind must be a CorrectionSourceKind")
    source_reference_value = _one_line(
        source_reference,
        field="source_reference",
        maximum=300,
    )
    source_hashes = tuple(source_sha256s)
    if (
        not source_hashes
        or len(set(source_hashes)) != len(source_hashes)
        or any(not _matches(_SHA256, item) for item in source_hashes)
    ):
        raise ValueError("source_sha256s must contain unique provenance hashes")
    components = (
        zero_point_energy_ev,
        thermal_enthalpy_ev,
        entropy_ev_per_kelvin,
        solvation_free_energy_ev,
        other_free_energy_ev,
    )
    if any(
        not isinstance(item, int | float) or isinstance(item, bool) or not math.isfinite(item)
        for item in components
    ):
        raise ValueError("thermochemical components must be finite numbers")
    if entropy_ev_per_kelvin < 0:
        raise ValueError("absolute state entropy cannot be negative")
    if uncertainty_ev is not None and (
        not isinstance(uncertainty_ev, int | float)
        or isinstance(uncertainty_ev, bool)
        or not math.isfinite(uncertainty_ev)
        or uncertainty_ev < 0
    ):
        raise ValueError("uncertainty_ev must be finite and non-negative")
    provisional = ThermochemicalCorrection(
        correction_id=_identifier(correction_id, field="correction_id"),
        state_id=state.state_id,
        state_identity_sha256=state.identity_sha256,
        protocol_id=protocol.protocol_id,
        protocol_identity_sha256=protocol.identity_sha256,
        standard_state=standard_state,
        source_kind=source_kind,
        source_reference=source_reference_value,
        source_sha256s=source_hashes,
        zero_point_energy_ev=float(zero_point_energy_ev),
        thermal_enthalpy_ev=float(thermal_enthalpy_ev),
        entropy_ev_per_kelvin=float(entropy_ev_per_kelvin),
        solvation_free_energy_ev=float(solvation_free_energy_ev),
        other_free_energy_ev=float(other_free_energy_ev),
        uncertainty_ev=float(uncertainty_ev) if uncertainty_ev is not None else None,
        identity_sha256="0" * 64,
    )
    return replace(provisional, identity_sha256=_digest(_correction_identity(provisional)))


def _valid_correction(correction: object) -> bool:
    try:
        components = (
            correction.zero_point_energy_ev,
            correction.thermal_enthalpy_ev,
            correction.entropy_ev_per_kelvin,
            correction.solvation_free_energy_ev,
            correction.other_free_energy_ev,
        )
        return (
            isinstance(correction, ThermochemicalCorrection)
            and correction.schema_version == "catex.thermochemical-correction.v1"
            and _matches(_IDENTIFIER, correction.correction_id)
            and _matches(_SHA256, correction.identity_sha256)
            and _matches(_IDENTIFIER, correction.state_id)
            and _matches(_SHA256, correction.state_identity_sha256)
            and _matches(_IDENTIFIER, correction.protocol_id)
            and _matches(_SHA256, correction.protocol_identity_sha256)
            and isinstance(correction.standard_state, StandardState)
            and isinstance(correction.source_kind, CorrectionSourceKind)
            and bool(correction.source_reference)
            and bool(correction.source_sha256s)
            and len(set(correction.source_sha256s)) == len(correction.source_sha256s)
            and all(_matches(_SHA256, item) for item in correction.source_sha256s)
            and all(
                isinstance(item, int | float) and not isinstance(item, bool) and math.isfinite(item)
                for item in components
            )
            and correction.entropy_ev_per_kelvin >= 0
            and (
                correction.uncertainty_ev is None
                or (
                    isinstance(correction.uncertainty_ev, int | float)
                    and not isinstance(correction.uncertainty_ev, bool)
                    and math.isfinite(correction.uncertainty_ev)
                    and correction.uncertainty_ev >= 0
                )
            )
            and correction.identity_sha256 == _digest(_correction_identity(correction))
            and correction.manual_review_required
            and not correction.writes_performed
            and not correction.commands_executed
        )
    except (AttributeError, TypeError, ValueError):
        return False


def _definition_subject(
    subject: _DefinitionSubject,
) -> tuple[DefinitionSubjectKind, str, str]:
    if _valid_state(subject):
        return DefinitionSubjectKind.CHEMICAL_STATE, subject.state_id, subject.identity_sha256
    if _valid_reference_set(subject):
        return (
            DefinitionSubjectKind.REFERENCE_STATE_SET,
            subject.reference_set_id,
            subject.identity_sha256,
        )
    if _valid_reaction(subject):
        return DefinitionSubjectKind.REACTION, subject.reaction_id, subject.identity_sha256
    if _valid_state_energy(subject):
        return (
            DefinitionSubjectKind.STATE_ENERGY_BINDING,
            subject.binding_id,
            subject.identity_sha256,
        )
    if _valid_protocol(subject):
        return (
            DefinitionSubjectKind.THERMOCHEMISTRY_PROTOCOL,
            subject.protocol_id,
            subject.identity_sha256,
        )
    if _valid_che_protocol(subject):
        return (
            DefinitionSubjectKind.COMPUTATIONAL_HYDROGEN_ELECTRODE_PROTOCOL,
            subject.protocol_id,
            subject.identity_sha256,
        )
    if _valid_correction(subject):
        return (
            DefinitionSubjectKind.THERMOCHEMICAL_CORRECTION,
            subject.correction_id,
            subject.identity_sha256,
        )
    raise ValueError("subject must be an intact reaction-domain definition")


def _review_content(review: ScientificDefinitionReview) -> dict[str, Any]:
    return {
        "schema": "catex.scientific-definition-review-content.v1",
        "decision": review.decision.value,
        "subject_kind": review.subject_kind.value,
        "subject_id": review.subject_id,
        "subject_identity_sha256": review.subject_identity_sha256,
        "reviewer": review.reviewer,
        "reviewed_at_utc": review.reviewed_at_utc,
        "note": review.note,
    }


def record_definition_review(
    subject: _DefinitionSubject,
    *,
    accepted: bool,
    reviewer: str,
    reviewed_at_utc: str,
    note: str,
) -> ScientificDefinitionReview:
    """Record a hash-bound definition review without mutating or executing anything."""

    if not isinstance(accepted, bool):
        raise ValueError("accepted must be a boolean")
    kind, subject_id, identity_sha256 = _definition_subject(subject)
    reviewer_value = _one_line(reviewer, field="reviewer", maximum=100)
    note_value = _one_line(note, field="note", maximum=500)
    _timestamp(reviewed_at_utc)
    provisional = ScientificDefinitionReview(
        decision=(
            DefinitionReviewDecision.APPROVED if accepted else DefinitionReviewDecision.REJECTED
        ),
        subject_kind=kind,
        subject_id=subject_id,
        subject_identity_sha256=identity_sha256,
        reviewer=reviewer_value,
        reviewed_at_utc=reviewed_at_utc,
        note=note_value,
        review_sha256="0" * 64,
    )
    return replace(provisional, review_sha256=_digest(_review_content(provisional)))


def _valid_bound_review(
    review: object,
    *,
    kind: DefinitionSubjectKind,
    subject_id: str,
    subject_sha256: str,
) -> bool:
    try:
        return (
            isinstance(review, ScientificDefinitionReview)
            and review.schema_version == "catex.scientific-definition-review.v1"
            and isinstance(review.decision, DefinitionReviewDecision)
            and review.subject_kind is kind
            and review.subject_id == subject_id
            and review.subject_identity_sha256 == subject_sha256
            and _matches(_SHA256, review.review_sha256)
            and review.review_sha256 == _digest(_review_content(review))
            and review.human_review_recorded
            and not review.automatic_approval_performed
            and not review.writes_performed
            and not review.commands_executed
        )
    except (AttributeError, TypeError, ValueError):
        return False


def _approval(
    reviews: Sequence[ScientificDefinitionReview],
    *,
    kind: DefinitionSubjectKind,
    subject_id: str,
    subject_sha256: str,
) -> tuple[str | None, Diagnostic | None]:
    bound = tuple(
        review
        for review in reviews
        if _valid_bound_review(
            review,
            kind=kind,
            subject_id=subject_id,
            subject_sha256=subject_sha256,
        )
    )
    approved = tuple(
        review for review in bound if review.decision is DefinitionReviewDecision.APPROVED
    )
    if len(bound) == 1 and len(approved) == 1:
        return approved[0].review_sha256, None
    return None, Diagnostic(
        "SCIENTIFIC_DEFINITION_APPROVAL_MISSING_OR_AMBIGUOUS",
        Severity.ERROR,
        "Exactly one valid approval is required for each scientific definition.",
        {
            "subject_kind": kind.value,
            "subject_id": subject_id,
            "bound_review_count": len(bound),
            "valid_approval_count": len(approved),
        },
    )


def _electronic_identity(report: ReactionElectronicEnergyReport) -> dict[str, Any]:
    return {
        "schema": "catex.reaction-electronic-energy-content.v1",
        "reaction_id": report.reaction_id,
        "reaction_identity_sha256": report.reaction_identity_sha256,
        "purpose": report.purpose.value,
        "value_eV": report.value_ev,
        "energy_family_id": report.energy_family_id,
        "kind": report.kind.value if report.kind else None,
        "linear_derivation_sha256": report.linear_derivation.derivation_sha256,
        "state_energy_binding_sha256s": list(report.state_energy_binding_sha256s),
        "accepted_review_sha256s": list(report.accepted_review_sha256s),
    }


def _valid_linear_derivation(report: object) -> bool:
    try:
        identity = {
            "schema": "catex.linear-energy-derivation-content.v1",
            "derivation_id": report.derivation_id,
            "operation": "linear_combination",
            "terms": [item.to_dict() for item in report.terms],
            "energy_family_id": report.energy_family_id,
            "kind": report.kind.value if report.kind else None,
        }
        candidate = math.fsum(item.contribution_ev for item in report.terms)
        compatibility = report.compatibility
        return (
            isinstance(report, LinearEnergyDerivationReport)
            and report.schema_version == "catex.linear-energy-derivation.v1"
            and report.status == "derived"
            and _matches(_IDENTIFIER, report.derivation_id)
            and bool(report.terms)
            and all(
                math.isfinite(item.coefficient)
                and item.coefficient != 0
                and math.isfinite(item.value_ev)
                and math.isfinite(item.contribution_ev)
                and item.contribution_ev == item.coefficient * item.value_ev
                for item in report.terms
            )
            and math.isfinite(candidate)
            and report.value_ev == candidate
            and _matches(_SHA256, report.derivation_sha256)
            and report.derivation_sha256 == _digest(identity)
            and compatibility.schema_version == "catex.energy-compatibility.v1"
            and compatibility.compatible
            and not compatibility.has_errors
            and compatibility.common_energy_family_id == report.energy_family_id
            and compatibility.common_kind is report.kind
            and compatibility.energy_ids == tuple(item.energy_id for item in report.terms)
            and compatibility.record_sha256s == tuple(item.record_sha256 for item in report.terms)
            and not report.has_errors
            and not report.scientific_interpretation_approved
            and not report.reference_state_reviewed
            and not report.thermochemical_corrections_included
            and not report.writes_performed
            and not report.commands_executed
            and not report.additional_submission_performed
            and not compatibility.writes_performed
            and not compatibility.commands_executed
            and not compatibility.additional_submission_performed
        )
    except (AttributeError, TypeError, ValueError, OverflowError):
        return False


def derive_reaction_electronic_energy(
    reaction: ReactionDefinition,
    bindings: Sequence[StateEnergyBinding],
    reviews: Sequence[ScientificDefinitionReview],
) -> ReactionElectronicEnergyReport:
    """Apply reviewed balanced stoichiometry to compatible reviewed VASP energies."""

    diagnostics: list[Diagnostic] = []
    if not _valid_reaction(reaction):
        raise ValueError("reaction must be an intact balanced ReactionDefinition")
    binding_by_state = {item.state_id: item for item in bindings if _valid_state_energy(item)}
    if len(binding_by_state) != len(bindings) or set(binding_by_state) != {
        item.state_id for item in reaction.terms
    }:
        diagnostics.append(
            Diagnostic(
                "REACTION_STATE_ENERGY_BINDINGS_INCOMPLETE",
                Severity.ERROR,
                "Exactly one intact state-energy binding is required for every reaction state.",
            )
        )
    else:
        for term in reaction.terms:
            if binding_by_state[term.state_id].state_identity_sha256 != term.state_identity_sha256:
                diagnostics.append(
                    Diagnostic(
                        "REACTION_STATE_ENERGY_IDENTITY_MISMATCH",
                        Severity.ERROR,
                        "A state-energy binding references a different chemical-state identity.",
                        {"state_id": term.state_id},
                    )
                )

    approvals: list[str] = []
    subjects: list[tuple[DefinitionSubjectKind, str, str]] = [
        (DefinitionSubjectKind.REACTION, reaction.reaction_id, reaction.identity_sha256)
    ]
    if reaction.reference_set_id and reaction.reference_set_identity_sha256:
        subjects.append(
            (
                DefinitionSubjectKind.REFERENCE_STATE_SET,
                reaction.reference_set_id,
                reaction.reference_set_identity_sha256,
            )
        )
    subjects.extend(
        (
            DefinitionSubjectKind.CHEMICAL_STATE,
            term.state_id,
            term.state_identity_sha256,
        )
        for term in reaction.terms
    )
    ordered_bindings = tuple(
        binding_by_state[state_id]
        for state_id in sorted(binding_by_state)
        if state_id in binding_by_state
    )
    subjects.extend(
        (
            DefinitionSubjectKind.STATE_ENERGY_BINDING,
            binding.binding_id,
            binding.identity_sha256,
        )
        for binding in ordered_bindings
    )
    for kind, subject_id, subject_sha256 in subjects:
        review_sha256, diagnostic = _approval(
            reviews,
            kind=kind,
            subject_id=subject_id,
            subject_sha256=subject_sha256,
        )
        if diagnostic:
            diagnostics.append(diagnostic)
        elif review_sha256:
            approvals.append(review_sha256)

    derivation_id = f"{reaction.reaction_id}-electronic"
    if diagnostics:
        linear = derive_linear_energy((), derivation_id=derivation_id)
    else:
        linear = derive_linear_energy(
            tuple(
                EnergyTerm(
                    float(term.coefficient.fraction),
                    binding_by_state[term.state_id].reviewed_energy,
                )
                for term in reaction.terms
            ),
            derivation_id=derivation_id,
        )
        diagnostics.extend(linear.diagnostics)
    value = linear.value_ev if not diagnostics else None
    provisional = ReactionElectronicEnergyReport(
        reaction_id=reaction.reaction_id,
        reaction_identity_sha256=reaction.identity_sha256,
        purpose=reaction.purpose,
        value_ev=value,
        energy_family_id=linear.energy_family_id if value is not None else None,
        kind=linear.kind if value is not None else None,
        linear_derivation=linear,
        state_energy_binding_sha256s=(
            tuple(binding_by_state[item.state_id].identity_sha256 for item in reaction.terms)
            if value is not None
            else ()
        ),
        accepted_review_sha256s=tuple(approvals) if value is not None else (),
        derivation_sha256=None,
        diagnostics=tuple(diagnostics),
        stoichiometry_reviewed=value is not None,
        reference_states_reviewed=(
            value is not None
            and (
                reaction.reference_set_identity_sha256 is not None
                or reaction.purpose not in {ReactionPurpose.ADSORPTION, ReactionPurpose.FORMATION}
            )
        ),
    )
    return replace(
        provisional,
        derivation_sha256=(
            _digest(_electronic_identity(provisional)) if value is not None else None
        ),
    )


def _valid_electronic_report(
    report: object,
    reaction: ReactionDefinition,
) -> bool:
    try:
        state_count = len(reaction.terms)
        expected_review_count = (
            1 + (2 * state_count) + (1 if reaction.reference_set_identity_sha256 is not None else 0)
        )
        return (
            isinstance(report, ReactionElectronicEnergyReport)
            and report.schema_version == "catex.reaction-electronic-energy.v1"
            and report.status == "derived"
            and report.reaction_id == reaction.reaction_id
            and report.reaction_identity_sha256 == reaction.identity_sha256
            and report.purpose is reaction.purpose
            and report.value_ev is not None
            and math.isfinite(report.value_ev)
            and _valid_linear_derivation(report.linear_derivation)
            and report.linear_derivation.value_ev == report.value_ev
            and report.linear_derivation.energy_family_id == report.energy_family_id
            and report.linear_derivation.kind is report.kind
            and len(report.linear_derivation.terms) == state_count
            and len(report.state_energy_binding_sha256s) == state_count
            and len(set(report.state_energy_binding_sha256s)) == state_count
            and all(_matches(_SHA256, item) for item in report.state_energy_binding_sha256s)
            and len(report.accepted_review_sha256s) == expected_review_count
            and len(set(report.accepted_review_sha256s)) == expected_review_count
            and all(_matches(_SHA256, item) for item in report.accepted_review_sha256s)
            and _matches(_SHA256, report.derivation_sha256)
            and report.derivation_sha256 == _digest(_electronic_identity(report))
            and report.stoichiometry_reviewed
            and report.reference_states_reviewed
            and not report.thermochemical_corrections_included
            and not report.electrochemical_correction_included
        )
    except (AttributeError, TypeError, ValueError):
        return False


def _free_energy_identity(report: ReactionFreeEnergyReport) -> dict[str, Any]:
    return {
        "schema": "catex.reaction-free-energy-content.v1",
        "reaction_id": report.reaction_id,
        "reaction_identity_sha256": report.reaction_identity_sha256,
        "purpose": report.purpose.value,
        "thermochemistry_protocol_id": report.thermochemistry_protocol_id,
        "thermochemistry_protocol_identity_sha256": (
            report.thermochemistry_protocol_identity_sha256
        ),
        "temperature_kelvin": report.temperature_kelvin,
        "electronic_derivation_sha256": report.electronic_derivation_sha256,
        "energy_family_id": report.energy_family_id,
        "electronic_energy_kind": (
            report.electronic_energy_kind.value if report.electronic_energy_kind else None
        ),
        "components_eV": {
            "electronic": report.electronic_energy_ev,
            "delta_zpe": report.delta_zero_point_energy_ev,
            "delta_thermal_enthalpy": report.delta_thermal_enthalpy_ev,
            "negative_t_delta_entropy": report.negative_t_delta_entropy_ev,
            "delta_solvation": report.delta_solvation_free_energy_ev,
            "delta_other": report.delta_other_free_energy_ev,
        },
        "value_eV": report.value_ev,
        "correction_identity_sha256s": list(report.correction_identity_sha256s),
        "accepted_review_sha256s": list(report.accepted_review_sha256s),
        "electrochemical_correction_included": report.electrochemical_correction_included,
        "computational_hydrogen_electrode_applied": (
            report.computational_hydrogen_electrode_applied
        ),
    }


def derive_reaction_free_energy(
    reaction: ReactionDefinition,
    electronic: ReactionElectronicEnergyReport,
    protocol: ThermochemistryProtocol,
    corrections: Sequence[ThermochemicalCorrection],
    reviews: Sequence[ScientificDefinitionReview],
) -> ReactionFreeEnergyReport:
    """Combine reviewed state corrections without silently applying CHE, potential, or pH."""

    if not _valid_reaction(reaction):
        raise ValueError("reaction must be an intact balanced ReactionDefinition")
    diagnostics: list[Diagnostic] = []
    if not _valid_electronic_report(electronic, reaction):
        diagnostics.append(
            Diagnostic(
                "REACTION_ELECTRONIC_ENERGY_INVALID",
                Severity.ERROR,
                "A complete reviewed electronic reaction-energy report is required.",
            )
        )
    if not _valid_protocol(protocol):
        raise ValueError("protocol must be an intact ThermochemistryProtocol")

    correction_by_state = {item.state_id: item for item in corrections if _valid_correction(item)}
    if len(correction_by_state) != len(corrections) or set(correction_by_state) != {
        item.state_id for item in reaction.terms
    }:
        diagnostics.append(
            Diagnostic(
                "THERMOCHEMICAL_CORRECTIONS_INCOMPLETE",
                Severity.ERROR,
                "Exactly one intact thermochemical correction is required for every state.",
            )
        )
    else:
        for term in reaction.terms:
            correction = correction_by_state[term.state_id]
            if (
                correction.state_identity_sha256 != term.state_identity_sha256
                or correction.protocol_id != protocol.protocol_id
                or correction.protocol_identity_sha256 != protocol.identity_sha256
            ):
                diagnostics.append(
                    Diagnostic(
                        "THERMOCHEMICAL_CORRECTION_IDENTITY_MISMATCH",
                        Severity.ERROR,
                        "A correction uses another state or thermochemistry protocol.",
                        {"state_id": term.state_id},
                    )
                )

    approval_hashes: list[str] = []
    subjects = [
        (
            DefinitionSubjectKind.THERMOCHEMISTRY_PROTOCOL,
            protocol.protocol_id,
            protocol.identity_sha256,
        )
    ]
    ordered_corrections = tuple(
        correction_by_state[state_id] for state_id in sorted(correction_by_state)
    )
    subjects.extend(
        (
            DefinitionSubjectKind.THERMOCHEMICAL_CORRECTION,
            item.correction_id,
            item.identity_sha256,
        )
        for item in ordered_corrections
    )
    for kind, subject_id, subject_sha256 in subjects:
        review_sha256, diagnostic = _approval(
            reviews,
            kind=kind,
            subject_id=subject_id,
            subject_sha256=subject_sha256,
        )
        if diagnostic:
            diagnostics.append(diagnostic)
        elif review_sha256:
            approval_hashes.append(review_sha256)

    components: tuple[float | None, ...] = (None, None, None, None, None)
    value: float | None = None
    if not diagnostics and electronic.value_ev is not None:
        zpe = math.fsum(
            float(term.coefficient.fraction)
            * correction_by_state[term.state_id].zero_point_energy_ev
            for term in reaction.terms
        )
        enthalpy = math.fsum(
            float(term.coefficient.fraction)
            * correction_by_state[term.state_id].thermal_enthalpy_ev
            for term in reaction.terms
        )
        negative_t_entropy = math.fsum(
            -protocol.temperature_kelvin
            * float(term.coefficient.fraction)
            * correction_by_state[term.state_id].entropy_ev_per_kelvin
            for term in reaction.terms
        )
        solvation = math.fsum(
            float(term.coefficient.fraction)
            * correction_by_state[term.state_id].solvation_free_energy_ev
            for term in reaction.terms
        )
        other = math.fsum(
            float(term.coefficient.fraction)
            * correction_by_state[term.state_id].other_free_energy_ev
            for term in reaction.terms
        )
        components = (zpe, enthalpy, negative_t_entropy, solvation, other)
        candidate = math.fsum((electronic.value_ev, *components))
        if not math.isfinite(candidate) or not all(
            item is not None and math.isfinite(item) for item in components
        ):
            diagnostics.append(
                Diagnostic(
                    "REACTION_FREE_ENERGY_NONFINITE",
                    Severity.ERROR,
                    "Thermochemical combination produced a non-finite value.",
                )
            )
        else:
            value = candidate

    zpe, enthalpy, negative_t_entropy, solvation, other = components
    provisional = ReactionFreeEnergyReport(
        reaction_id=reaction.reaction_id,
        reaction_identity_sha256=reaction.identity_sha256,
        purpose=reaction.purpose,
        thermochemistry_protocol_id=protocol.protocol_id,
        thermochemistry_protocol_identity_sha256=protocol.identity_sha256,
        temperature_kelvin=protocol.temperature_kelvin,
        electronic_derivation_sha256=(electronic.derivation_sha256 if value is not None else None),
        energy_family_id=electronic.energy_family_id if value is not None else None,
        electronic_energy_kind=electronic.kind if value is not None else None,
        electronic_energy_ev=electronic.value_ev if value is not None else None,
        delta_zero_point_energy_ev=zpe if value is not None else None,
        delta_thermal_enthalpy_ev=enthalpy if value is not None else None,
        negative_t_delta_entropy_ev=negative_t_entropy if value is not None else None,
        delta_solvation_free_energy_ev=solvation if value is not None else None,
        delta_other_free_energy_ev=other if value is not None else None,
        value_ev=value,
        correction_identity_sha256s=(
            tuple(correction_by_state[item.state_id].identity_sha256 for item in reaction.terms)
            if value is not None
            else ()
        ),
        accepted_review_sha256s=tuple(approval_hashes) if value is not None else (),
        derivation_sha256=None,
        diagnostics=tuple(diagnostics),
        standard_states_explicit=value is not None,
        thermochemical_corrections_included=value is not None,
    )
    return replace(
        provisional,
        derivation_sha256=(
            _digest(_free_energy_identity(provisional)) if value is not None else None
        ),
    )


def is_intact_reaction_definition(reaction: object) -> bool:
    """Return whether a reaction is balanced and its immutable content hash is intact."""

    return _valid_reaction(reaction)


def is_intact_reaction_free_energy(report: object) -> bool:
    """Return whether a pre-electrochemical free-energy report is complete and intact."""

    try:
        components = (
            report.electronic_energy_ev,
            report.delta_zero_point_energy_ev,
            report.delta_thermal_enthalpy_ev,
            report.negative_t_delta_entropy_ev,
            report.delta_solvation_free_energy_ev,
            report.delta_other_free_energy_ev,
        )
        expected = math.fsum(components)
        correction_count = len(report.correction_identity_sha256s)
        return (
            isinstance(report, ReactionFreeEnergyReport)
            and report.schema_version == "catex.reaction-free-energy.v1"
            and report.status == "derived"
            and _matches(_IDENTIFIER, report.reaction_id)
            and _matches(_SHA256, report.reaction_identity_sha256)
            and isinstance(report.purpose, ReactionPurpose)
            and _matches(_IDENTIFIER, report.thermochemistry_protocol_id)
            and _matches(_SHA256, report.thermochemistry_protocol_identity_sha256)
            and isinstance(report.temperature_kelvin, int | float)
            and not isinstance(report.temperature_kelvin, bool)
            and math.isfinite(report.temperature_kelvin)
            and report.temperature_kelvin > 0
            and _matches(_SHA256, report.electronic_derivation_sha256)
            and isinstance(report.energy_family_id, str)
            and report.energy_family_id.startswith("sha256:")
            and _matches(_SHA256, report.energy_family_id.removeprefix("sha256:"))
            and report.electronic_energy_kind is not None
            and all(
                isinstance(item, int | float) and not isinstance(item, bool) and math.isfinite(item)
                for item in components
            )
            and isinstance(report.value_ev, int | float)
            and not isinstance(report.value_ev, bool)
            and math.isfinite(report.value_ev)
            and report.value_ev == expected
            and correction_count > 0
            and len(set(report.correction_identity_sha256s)) == correction_count
            and all(_matches(_SHA256, item) for item in report.correction_identity_sha256s)
            and len(report.accepted_review_sha256s) == correction_count + 1
            and len(set(report.accepted_review_sha256s)) == correction_count + 1
            and all(_matches(_SHA256, item) for item in report.accepted_review_sha256s)
            and _matches(_SHA256, report.derivation_sha256)
            and report.derivation_sha256 == _digest(_free_energy_identity(report))
            and report.standard_states_explicit
            and report.thermochemical_corrections_included
            and not report.electrochemical_correction_included
            and not report.computational_hydrogen_electrode_applied
            and report.electrode_potential_v is None
            and report.ph is None
            and not report.uncertainty_model_applied
            and not report.writes_performed
            and not report.commands_executed
            and not report.has_errors
        )
    except (AttributeError, TypeError, ValueError):
        return False


def _che_report_identity(report: ComputationalHydrogenElectrodeReport) -> dict[str, Any]:
    return {
        "schema": "catex.computational-hydrogen-electrode-report-content.v1",
        "reaction_id": report.reaction_id,
        "reaction_identity_sha256": report.reaction_identity_sha256,
        "base_free_energy_derivation_sha256": report.base_free_energy_derivation_sha256,
        "protocol_id": report.protocol_id,
        "protocol_identity_sha256": report.protocol_identity_sha256,
        "reference_electrode": report.reference_electrode.value,
        "electrode_potential_v": report.electrode_potential_v,
        "pH": report.ph,
        "temperature_kelvin": report.temperature_kelvin,
        "proton_electron_pairs_consumed": report.proton_electron_pairs_consumed.to_dict(),
        "potential_correction_eV": report.potential_correction_ev,
        "pH_correction_eV": report.ph_correction_ev,
        "electrochemical_correction_eV": report.electrochemical_correction_ev,
        "base_free_energy_eV": report.base_free_energy_ev,
        "value_eV": report.value_ev,
        "protocol_review_sha256": report.protocol_review_sha256,
        "source_sha256s": list(report.source_sha256s),
        "sign_convention": (report.positive_pairs_consumed_negative_potential_lowers_free_energy),
    }


def apply_computational_hydrogen_electrode(
    base_free_energy: ReactionFreeEnergyReport,
    protocol: ComputationalHydrogenElectrodeProtocol,
    *,
    proton_electron_pairs_consumed: int | str | Fraction,
    reviews: Sequence[ScientificDefinitionReview],
) -> ComputationalHydrogenElectrodeReport:
    """Apply explicit SHE/RHE potential and pH corrections to reviewed thermochemistry."""

    if not is_intact_reaction_free_energy(base_free_energy):
        raise ValueError("base_free_energy must be an intact pre-electrochemical report")
    if not _valid_che_protocol(protocol):
        raise ValueError("protocol must be an intact CHE protocol")
    pairs = _fraction(
        proton_electron_pairs_consumed,
        field="proton_electron_pairs_consumed",
    )
    if pairs == 0:
        raise ValueError("proton_electron_pairs_consumed must be non-zero")
    review_sha256, diagnostic = _approval(
        reviews,
        kind=DefinitionSubjectKind.COMPUTATIONAL_HYDROGEN_ELECTRODE_PROTOCOL,
        subject_id=protocol.protocol_id,
        subject_sha256=protocol.identity_sha256,
    )
    diagnostics = (diagnostic,) if diagnostic else ()
    potential_correction: float | None = None
    ph_correction: float | None = None
    electrochemical_correction: float | None = None
    value: float | None = None
    if not diagnostics and review_sha256 is not None:
        pair_count = float(pairs)
        potential_correction = pair_count * protocol.electrode_potential_v
        ph_correction = (
            0.0
            if protocol.reference_electrode is ReferenceElectrode.RHE
            else pair_count
            * 8.617333262145e-5
            * protocol.temperature_kelvin
            * math.log(10.0)
            * protocol.ph
        )
        electrochemical_correction = math.fsum((potential_correction, ph_correction))
        value = math.fsum((base_free_energy.value_ev, electrochemical_correction))
        if not all(
            math.isfinite(item)
            for item in (potential_correction, ph_correction, electrochemical_correction, value)
        ):
            diagnostics = (
                Diagnostic(
                    "CHE_CORRECTION_NONFINITE",
                    Severity.ERROR,
                    "The CHE correction produced a non-finite value.",
                ),
            )
            potential_correction = None
            ph_correction = None
            electrochemical_correction = None
            value = None
    provisional = ComputationalHydrogenElectrodeReport(
        reaction_id=base_free_energy.reaction_id,
        reaction_identity_sha256=base_free_energy.reaction_identity_sha256,
        base_free_energy_derivation_sha256=base_free_energy.derivation_sha256,
        protocol_id=protocol.protocol_id,
        protocol_identity_sha256=protocol.identity_sha256,
        reference_electrode=protocol.reference_electrode,
        electrode_potential_v=protocol.electrode_potential_v,
        ph=protocol.ph,
        temperature_kelvin=protocol.temperature_kelvin,
        proton_electron_pairs_consumed=_rational(pairs),
        potential_correction_ev=potential_correction,
        ph_correction_ev=ph_correction,
        electrochemical_correction_ev=electrochemical_correction,
        base_free_energy_ev=base_free_energy.value_ev if value is not None else None,
        value_ev=value,
        protocol_review_sha256=review_sha256 if value is not None else None,
        source_sha256s=protocol.source_sha256s,
        derivation_sha256=None,
        diagnostics=diagnostics,
        electrochemical_correction_included=value is not None,
        computational_hydrogen_electrode_applied=value is not None,
    )
    return replace(
        provisional,
        derivation_sha256=(
            _digest(_che_report_identity(provisional)) if value is not None else None
        ),
    )


def is_intact_computational_hydrogen_electrode_report(report: object) -> bool:
    """Return whether a derived CHE report is numerically and hash consistent."""

    try:
        pairs = report.proton_electron_pairs_consumed.fraction
        return (
            isinstance(report, ComputationalHydrogenElectrodeReport)
            and report.schema_version == "catex.computational-hydrogen-electrode-report.v1"
            and report.status == "derived"
            and _matches(_IDENTIFIER, report.reaction_id)
            and _matches(_SHA256, report.reaction_identity_sha256)
            and _matches(_SHA256, report.base_free_energy_derivation_sha256)
            and _matches(_IDENTIFIER, report.protocol_id)
            and _matches(_SHA256, report.protocol_identity_sha256)
            and isinstance(report.reference_electrode, ReferenceElectrode)
            and pairs != 0
            and all(
                isinstance(item, int | float) and not isinstance(item, bool) and math.isfinite(item)
                for item in (
                    report.electrode_potential_v,
                    report.ph,
                    report.temperature_kelvin,
                    report.potential_correction_ev,
                    report.ph_correction_ev,
                    report.electrochemical_correction_ev,
                    report.base_free_energy_ev,
                    report.value_ev,
                )
            )
            and report.ph >= 0
            and report.temperature_kelvin > 0
            and report.electrochemical_correction_ev
            == math.fsum((report.potential_correction_ev, report.ph_correction_ev))
            and report.value_ev
            == math.fsum((report.base_free_energy_ev, report.electrochemical_correction_ev))
            and (
                report.reference_electrode is not ReferenceElectrode.RHE
                or report.ph_correction_ev == 0.0
            )
            and _matches(_SHA256, report.protocol_review_sha256)
            and bool(report.source_sha256s)
            and tuple(sorted(set(report.source_sha256s))) == report.source_sha256s
            and all(_matches(_SHA256, item) for item in report.source_sha256s)
            and _matches(_SHA256, report.derivation_sha256)
            and report.derivation_sha256 == _digest(_che_report_identity(report))
            and report.positive_pairs_consumed_negative_potential_lowers_free_energy
            and report.electrochemical_correction_included
            and report.computational_hydrogen_electrode_applied
            and not report.uncertainty_model_applied
            and report.manual_interpretation_required
            and not report.writes_performed
            and not report.commands_executed
            and not report.has_errors
        )
    except (AttributeError, TypeError, ValueError):
        return False
