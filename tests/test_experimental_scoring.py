from __future__ import annotations

import math

import pytest
from pymatgen.core import Lattice, Structure

from catex.experimental import (
    CandidateAssessment,
    CandidateExecution,
    CandidateOperation,
    CandidateOperationKind,
    CandidateRecipe,
    CompositionBasis,
    CompositionScope,
    ElementConstraint,
    EvidenceCheck,
    EvidenceKind,
    EvidenceRecord,
    EvidenceRole,
    ExperimentSpec,
    InMemoryStructureProvider,
    LatticeSpacingConstraint,
    LocalEnvironmentConstraint,
    ModalitySupport,
    ModelKind,
    ProviderRegistry,
    StructureSourceKind,
    SupportDomain,
)
from catex.experimental.workflow import (
    _candidate_assessment,
    _composition_value,
    _crowding_distances,
    _domain_support,
    _environment_value,
    _geometric_mean,
    _representatives,
    _soft_modality_support,
)


def _check(
    check_id: str,
    evidence_id: str,
    score: float,
    *,
    role: EvidenceRole,
) -> EvidenceCheck:
    return EvidenceCheck(
        check_id=check_id,
        kind="composition",
        label=check_id,
        role=role,
        status="within_range",
        score=score,
        evidence_ids=(evidence_id,),
    )


def test_only_soft_evidence_contributes_and_scores_are_grouped_by_modality() -> None:
    evidence = (
        EvidenceRecord("icp-hard", EvidenceKind.ICP, EvidenceRole.HARD),
        EvidenceRecord("xrd-context", EvidenceKind.XRD, EvidenceRole.CONTEXT),
        EvidenceRecord("icp-a", EvidenceKind.ICP, EvidenceRole.SOFT),
        EvidenceRecord("icp-b", EvidenceKind.ICP, EvidenceRole.SOFT),
        EvidenceRecord("xrd-soft", EvidenceKind.XRD, EvidenceRole.SOFT),
        EvidenceRecord("xps-soft", EvidenceKind.XPS, EvidenceRole.SOFT),
        EvidenceRecord("tem-soft", EvidenceKind.TEM, EvidenceRole.SOFT),
        EvidenceRecord("eds-soft", EvidenceKind.EDS, EvidenceRole.SOFT),
    )
    checks = (
        _check("hard", "icp-hard", 1.0, role=EvidenceRole.HARD),
        _check("context", "xrd-context", 1.0, role=EvidenceRole.CONTEXT),
        _check("icp-a", "icp-a", 1.0, role=EvidenceRole.SOFT),
        _check("icp-b", "icp-b", 0.25, role=EvidenceRole.SOFT),
        _check("xrd", "xrd-soft", 0.81, role=EvidenceRole.SOFT),
        _check("xps", "xps-soft", 0.64, role=EvidenceRole.SOFT),
        _check("tem", "tem-soft", 0.49, role=EvidenceRole.SOFT),
        _check("eds", "eds-soft", 0.36, role=EvidenceRole.SOFT),
    )

    support = _soft_modality_support(checks, ExperimentSpec("score-test", evidence=evidence))
    by_modality = {item.modality: item for item in support}

    assert set(by_modality) == {
        EvidenceKind.ICP,
        EvidenceKind.XRD,
        EvidenceKind.XPS,
        EvidenceKind.TEM,
        EvidenceKind.EDS,
    }
    assert by_modality[EvidenceKind.ICP].score == pytest.approx(0.5)
    assert by_modality[EvidenceKind.ICP].check_ids == ("icp-a", "icp-b")
    assert _domain_support(support, SupportDomain.PARENT) == pytest.approx(math.sqrt(0.5 * 0.81))
    assert _domain_support(support, SupportDomain.SURFACE) == pytest.approx(0.64)
    assert _domain_support(support, SupportDomain.LOCAL) == pytest.approx(math.sqrt(0.49 * 0.36))


def _assessment(
    candidate_id: str,
    digest_character: str,
    *,
    parent: float | None,
    surface: float | None,
    local: float | None,
) -> CandidateAssessment:
    return CandidateAssessment(
        candidate_id=candidate_id,
        recipe_id=f"recipe-{candidate_id}",
        hypothesis_id=f"hypothesis-{candidate_id}",
        parent_reference_key="provider:parent",
        model_kind=ModelKind.SURFACE if surface is not None else ModelKind.BULK,
        structure_sha256=digest_character * 64,
        formula="NiMo",
        num_sites=2,
        valid=True,
        modality_support=(),
        parent_support=parent,
        surface_support=surface,
        local_support=local,
        xrd_directly_applicable=False,
        evidence_checks=(),
        transformation_sha256s=(),
        diagnostics=(),
    )


def test_representatives_are_the_true_non_dominated_frontier() -> None:
    assessments = (
        _assessment("candidate-a", "a", parent=0.9, surface=0.3, local=0.4),
        _assessment("candidate-b", "b", parent=0.8, surface=0.6, local=0.4),
        _assessment("candidate-c", "c", parent=0.7, surface=0.2, local=0.3),
        _assessment("candidate-d", "d", parent=0.95, surface=None, local=None),
    )

    representatives = _representatives(assessments, maximum_representatives=10)

    assert set(representatives) == {"candidate-a", "candidate-b", "candidate-d"}
    assert "candidate-c" not in representatives


def test_missing_support_domains_are_incomparable_not_zero() -> None:
    assessments = (
        _assessment("bulk", "e", parent=0.7, surface=None, local=None),
        _assessment("surface", "f", parent=0.8, surface=0.9, local=None),
    )

    assert set(_representatives(assessments, maximum_representatives=10)) == {
        "bulk",
        "surface",
    }


def test_pareto_limit_uses_crowding_distance_to_preserve_frontier_extremes() -> None:
    frontier = (
        _assessment("low-parent", "1", parent=0.1, surface=0.9, local=0.5),
        _assessment("middle-a", "2", parent=0.4, surface=0.6, local=0.5),
        _assessment("middle-b", "3", parent=0.7, surface=0.3, local=0.5),
        _assessment("high-parent", "4", parent=0.9, surface=0.1, local=0.5),
    )

    distances = _crowding_distances(frontier)

    assert math.isinf(distances["low-parent"])
    assert math.isinf(distances["high-parent"])
    assert distances["middle-a"] > 0
    assert distances["middle-b"] > 0
    assert set(_representatives(frontier, maximum_representatives=2)) == {
        "low-parent",
        "high-parent",
    }


def test_surface_checks_apply_hard_exclusion_without_polluting_soft_support() -> None:
    structure = Structure(
        Lattice.cubic(3.0),
        ["Ni", "O"],
        [[0.0, 0.0, 0.0], [0.5, 0.5, 0.5]],
    )
    provider = InMemoryStructureProvider(
        "scoring",
        (("parent", structure, StructureSourceKind.HYPOTHETICAL),),
    )
    registry = ProviderRegistry((provider,))
    parent_key = registry.references()[0].key
    recipe = CandidateRecipe(
        recipe_id="surface-hard-check",
        parent_reference_key=parent_key,
        hypothesis_id="surface-hypothesis",
        operations=(CandidateOperation(CandidateOperationKind.IDENTITY),),
        evidence_ids=("eds-hard", "xps-soft"),
        rationale="Exercise hard exclusion and surface support independently.",
    )
    execution = CandidateExecution(
        candidate_id="surface-hard-check.c0",
        recipe=recipe,
        structure=structure,
        model_kind=ModelKind.SURFACE,
        transformation_sha256s=(),
        diagnostics=(),
    )
    spec = ExperimentSpec(
        sample_id="surface-hard-check",
        evidence=(
            EvidenceRecord("eds-hard", EvidenceKind.EDS, EvidenceRole.HARD),
            EvidenceRecord("xps-soft", EvidenceKind.XPS, EvidenceRole.SOFT),
        ),
        composition_constraints=(
            ElementConstraint(
                "Ni",
                0.9,
                1.0,
                scope=CompositionScope.SURFACE,
                evidence_ids=("eds-hard",),
            ),
        ),
        local_environment_constraints=(
            LocalEnvironmentConstraint(
                "Ni",
                "O",
                0.5,
                1.0,
                cutoff_angstrom=4.0,
                scope=CompositionScope.SURFACE,
                evidence_ids=("xps-soft",),
            ),
        ),
    )

    assessment = _candidate_assessment(execution, {}, spec, registry, None)

    assert assessment.valid is False
    assert assessment.parent_support is None
    assert assessment.surface_support == pytest.approx(1.0)
    assert assessment.local_support is None
    assert [item.modality for item in assessment.modality_support] == [EvidenceKind.XPS]
    assert next(
        item for item in assessment.evidence_checks if item.kind == "composition"
    ).status == ("outside_range")

    assert _composition_value(
        structure,
        element="Ni",
        scope=CompositionScope.LOCAL,
        basis=CompositionBasis.WEIGHT_FRACTION,
        model_kind=ModelKind.BULK,
    ) == pytest.approx(58.6934 / (58.6934 + 15.9994), rel=1e-4)
    assert (
        _environment_value(
            structure,
            element="Mo",
            neighbor_element="O",
            cutoff_angstrom=4.0,
            scope=CompositionScope.LOCAL,
            model_kind=ModelKind.BULK,
        )
        == 0.0
    )
    assert (
        _environment_value(
            structure,
            element="Ni",
            neighbor_element="O",
            cutoff_angstrom=4.0,
            scope=CompositionScope.SURFACE,
            model_kind=ModelKind.BULK,
        )
        is None
    )


def test_support_contract_rejects_invalid_values_and_ignores_unscored_modalities() -> None:
    with pytest.raises(ValueError, match="at least one value"):
        _geometric_mean(())
    with pytest.raises(ValueError, match="score must be in"):
        ModalitySupport(EvidenceKind.XRD, SupportDomain.PARENT, 1.1, ("check",))
    with pytest.raises(ValueError, match="unsupported modality aggregation"):
        ModalitySupport(
            EvidenceKind.XRD,
            SupportDomain.PARENT,
            0.5,
            ("check",),
            aggregation="arithmetic_mean",
        )
    with pytest.raises(ValueError, match="status is invalid"):
        EvidenceCheck("bad-status", "xrd", "Bad", EvidenceRole.SOFT, "unknown", 0.5)
    with pytest.raises(ValueError, match="score must be in"):
        EvidenceCheck("bad-score", "xrd", "Bad", EvidenceRole.SOFT, "within_range", -0.1)
    with pytest.raises(ValueError, match="predicted_value must be finite"):
        EvidenceCheck(
            "bad-value",
            "xrd",
            "Bad",
            EvidenceRole.SOFT,
            "within_range",
            0.5,
            predicted_value=math.nan,
        )

    sem_evidence = EvidenceRecord("sem-soft", EvidenceKind.SEM, EvidenceRole.SOFT)
    sem_check = _check("sem", "sem-soft", 0.8, role=EvidenceRole.SOFT)
    assert (
        _soft_modality_support(
            (sem_check,),
            ExperimentSpec("unsupported-modality", evidence=(sem_evidence,)),
        )
        == ()
    )


def test_experimental_scoring_schema_rejects_ambiguous_or_invalid_inputs() -> None:
    with pytest.raises(ValueError, match="invalid element symbol"):
        ElementConstraint("NotAnElement", 0.0, 1.0)
    with pytest.raises(ValueError, match="must be finite"):
        ElementConstraint("Ni", math.nan, 1.0)
    with pytest.raises(ValueError, match="0 <= minimum"):
        ElementConstraint("Ni", 0.8, 0.2)

    with pytest.raises(ValueError, match="must be valid symbols"):
        LocalEnvironmentConstraint("Ni", "NotAnElement", 0.0, 1.0)
    with pytest.raises(ValueError, match="must be finite"):
        LocalEnvironmentConstraint("Ni", "O", 0.0, math.inf)
    with pytest.raises(ValueError, match="0 <= minimum"):
        LocalEnvironmentConstraint("Ni", "O", 0.8, 0.2)
    with pytest.raises(ValueError, match=r"between 0\.5 and 6\.0"):
        LocalEnvironmentConstraint("Ni", "O", 0.0, 1.0, cutoff_angstrom=0.2)
    with pytest.raises(ValueError, match="scope must be surface or local"):
        LocalEnvironmentConstraint(
            "Ni",
            "O",
            0.0,
            1.0,
            scope=CompositionScope.BULK,
        )

    with pytest.raises(ValueError, match="finite and positive"):
        LatticeSpacingConstraint(0.0, 0.1)
    with pytest.raises(ValueError, match="no larger than d-spacing"):
        LatticeSpacingConstraint(1.0, 1.1)

    evidence = EvidenceRecord("known", EvidenceKind.ICP, EvidenceRole.SOFT)
    with pytest.raises(ValueError, match="evidence IDs must be unique"):
        ExperimentSpec("duplicate-evidence", evidence=(evidence, evidence))
    with pytest.raises(ValueError, match="must not overlap"):
        ExperimentSpec(
            "overlapping-elements",
            evidence=(),
            allowed_elements=("Ni",),
            excluded_elements=("Ni",),
        )
    duplicate = ElementConstraint("Ni", 0.1, 0.9)
    with pytest.raises(ValueError, match="at most one interval"):
        ExperimentSpec(
            "duplicate-constraint",
            evidence=(),
            composition_constraints=(duplicate, duplicate),
        )
    with pytest.raises(ValueError, match="unknown evidence IDs"):
        ExperimentSpec(
            "unknown-composition-evidence",
            evidence=(),
            composition_constraints=(ElementConstraint("Ni", 0.1, 0.9, evidence_ids=("missing",)),),
        )
    with pytest.raises(ValueError, match="cannot sum to more than one"):
        ExperimentSpec(
            "impossible-composition",
            evidence=(),
            composition_constraints=(
                ElementConstraint("Ni", 0.6, 0.8),
                ElementConstraint("Mo", 0.6, 0.8),
            ),
        )

    with pytest.raises(ValueError, match="at least one operation"):
        CandidateRecipe("empty", "provider:parent", "hypothesis", (), (), "No operation")
    with pytest.raises(ValueError, match="random_seed must be an integer"):
        CandidateRecipe(
            "bad-seed",
            "provider:parent",
            "hypothesis",
            (CandidateOperation(CandidateOperationKind.IDENTITY),),
            (),
            "Invalid seed",
            random_seed=True,
        )
