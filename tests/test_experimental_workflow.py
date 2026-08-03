from __future__ import annotations

import json

import numpy as np
import pytest
from pymatgen.core import Lattice, Structure

from catex.cli import main
from catex.experimental import (
    CandidateOperation,
    CandidateOperationKind,
    CandidatePlan,
    CandidateRecipe,
    ClaimLevel,
    CompositionScope,
    ElementConstraint,
    EvidenceKind,
    EvidenceRecord,
    EvidenceRole,
    ExperimentInput,
    ExperimentSpec,
    InferenceStatus,
    InMemoryStructureProvider,
    LatticeSpacingConstraint,
    ProviderRegistry,
    RuleCandidatePlanner,
    RulePlannerSettings,
    StructuralHypothesis,
    StructureSourceKind,
    XRDSearchSettings,
    infer_experimental_models,
    load_experiment_spec,
    materialize_representative_models,
    simulate_xrd_on_grid,
)


def _nickel() -> Structure:
    return Structure.from_spacegroup(
        "Fm-3m",
        Lattice.cubic(3.52),
        ["Ni"],
        [[0, 0, 0]],
    )


def _prepare_case(tmp_path):
    structure = _nickel()
    structure_path = tmp_path / "ni.cif"
    structure.to(filename=structure_path, fmt="cif")
    x = np.linspace(20.0, 100.0, 1601)
    y = simulate_xrd_on_grid(
        structure,
        x,
        wavelength="CuKa",
        shift_degrees=0.0,
        fwhm_degrees=0.2,
    )
    xrd_path = tmp_path / "ni.xy"
    xrd_path.write_text(
        "\n".join(f"{angle:.6f} {intensity:.12f}" for angle, intensity in zip(x, y, strict=True)),
        encoding="utf-8",
    )
    spec_path = tmp_path / "experiment.json"
    spec_path.write_text(
        json.dumps(
            {
                "schema_version": "catex.experiment-spec.v1",
                "sample_id": "synthetic-ni",
                "target_state": "as_prepared",
                "material_pack": "generic",
                "allowed_elements": ["Ni"],
                "excluded_elements": [],
                "composition_constraints": [
                    {
                        "element": "Ni",
                        "minimum_atomic_fraction": 0.99,
                        "maximum_atomic_fraction": 1.0,
                        "scope": "bulk",
                        "evidence_ids": ["composition"],
                    }
                ],
                "evidence": [
                    {
                        "evidence_id": "composition",
                        "kind": "icp",
                        "sample_state": "as_prepared",
                        "role": "hard",
                    },
                    {
                        "evidence_id": "xrd",
                        "kind": "xrd",
                        "sample_state": "as_prepared",
                        "role": "hard",
                        "artifact": "ni.xy",
                        "metadata": {"radiation": "CuKa"},
                    },
                ],
            }
        ),
        encoding="utf-8",
    )
    catalog_path = tmp_path / "catalog.json"
    catalog_path.write_text(
        json.dumps(
            {
                "schema_version": "catex.structure-catalog.v1",
                "provider": "synthetic",
                "entries": [
                    {
                        "record_id": "ni",
                        "path": "ni.cif",
                        "source_kind": "hypothetical",
                        "source_locator": "synthetic:test",
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    return spec_path, catalog_path, structure


def test_reported_xrd_formula_prioritizes_and_scores_the_matching_parent() -> None:
    nickel = _nickel()
    nickel_molybdenum = Structure(
        Lattice.cubic(3.2),
        ["Ni", "Mo"],
        [[0, 0, 0], [0.5, 0.5, 0.5]],
    )
    registry = ProviderRegistry(
        (
            InMemoryStructureProvider(
                "reported-phase",
                (
                    ("a-nickel", nickel, StructureSourceKind.HYPOTHETICAL),
                    ("z-nickel-molybdenum", nickel_molybdenum, StructureSourceKind.HYPOTHETICAL),
                ),
            ),
        )
    )
    evidence = EvidenceRecord(
        evidence_id="xrd-conclusion",
        kind=EvidenceKind.XRD,
        role=EvidenceRole.SOFT,
        metadata={"reported_phase_formulas": ["NiMo"]},
        note="所有衍射峰均归属于NiMo物相。",
    )
    spec = ExperimentSpec(
        sample_id="reported-phase",
        evidence=(evidence,),
        allowed_elements=("Ni", "Mo"),
        material_pack="generic",
    )

    run = infer_experimental_models(
        ExperimentInput(spec, {}),
        registry,
        RuleCandidatePlanner(
            RulePlannerSettings(
                maximum_parent_phases=1,
                include_bulk_models=True,
                maximum_recipes=1,
            )
        ),
    )

    assessment = run.report.candidate_assessments[0]
    assert assessment.parent_reference_key.endswith(":z-nickel-molybdenum")
    assert assessment.parent_support == pytest.approx(1.0)
    assert run.report.status is InferenceStatus.READY_FOR_REVIEW
    assert run.report.claim_ceiling is ClaimLevel.PHASE_FAMILY_SUPPORTED
    assert any(
        item.code == "RULE_PLANNER_REPORTED_PHASE_PRIORITIZATION" for item in run.report.diagnostics
    )


def test_legacy_phase_parser_results_are_ignored_until_reinterpreted() -> None:
    registry = ProviderRegistry(
        (
            InMemoryStructureProvider(
                "legacy-phase",
                (
                    ("a-nickel", _nickel(), StructureSourceKind.HYPOTHETICAL),
                    (
                        "z-nickel-molybdenum",
                        Structure(
                            Lattice.cubic(3.2),
                            ["Ni", "Mo"],
                            [[0, 0, 0], [0.5, 0.5, 0.5]],
                        ),
                        StructureSourceKind.HYPOTHETICAL,
                    ),
                ),
            ),
        )
    )
    evidence = EvidenceRecord(
        evidence_id="legacy-xrd",
        kind=EvidenceKind.XRD,
        role=EvidenceRole.SOFT,
        metadata={
            "automatic_extraction": {"method": "transparent-rule-parser-v1"},
            "reported_phase_formulas": ["NiMo"],
        },
    )
    spec = ExperimentSpec(
        sample_id="legacy-phase",
        evidence=(evidence,),
        allowed_elements=("Ni", "Mo"),
    )

    run = infer_experimental_models(
        ExperimentInput(spec, {}),
        registry,
        RuleCandidatePlanner(
            RulePlannerSettings(
                maximum_parent_phases=1,
                include_bulk_models=True,
                maximum_recipes=1,
            )
        ),
    )

    assessment = run.report.candidate_assessments[0]
    assert assessment.parent_reference_key.endswith(":a-nickel")
    assert assessment.parent_support is None
    assert not any(check.kind == "xrd" for check in assessment.evidence_checks)


def test_end_to_end_inference_and_new_directory_materialization(tmp_path) -> None:
    spec_path, _, structure = _prepare_case(tmp_path)
    experiment = load_experiment_spec(spec_path)
    registry = ProviderRegistry(
        (
            InMemoryStructureProvider(
                "synthetic",
                (("ni", structure, StructureSourceKind.HYPOTHETICAL),),
            ),
        )
    )
    run = infer_experimental_models(
        experiment,
        registry,
        RuleCandidatePlanner(),
        xrd_settings=XRDSearchSettings(
            shift_values_degrees=(0.0,),
            fwhm_values_degrees=(0.2,),
            maximum_phases=1,
            minimum_supported_score=0.9,
        ),
    )

    assert run.report.status is InferenceStatus.READY_FOR_REVIEW
    assert run.report.claim_ceiling is ClaimLevel.PHASE_FAMILY_SUPPORTED
    assert run.report.external_api_called is False
    assert run.report.writes_performed is False
    assert run.report.representative_candidate_ids == ("bulk-1.c0",)
    assert run.report.identity_sha256 == run.report.identity_sha256

    destination = tmp_path / "representatives"
    materialized = materialize_representative_models(run, destination)

    assert materialized.writes_performed is True
    assert (destination / "manifest.json").is_file()
    assert (destination / "01-bulk-1.c0" / "POSCAR").is_file()
    assert materialized.inference_sha256 == run.report.identity_sha256
    with pytest.raises(ValueError, match="must not already exist"):
        materialize_representative_models(run, destination)


def test_cli_inference_and_materialization(tmp_path, capsys) -> None:
    spec_path, catalog_path, _ = _prepare_case(tmp_path)

    exit_code = main(
        [
            "infer-experimental-models",
            str(spec_path),
            "--catalog",
            str(catalog_path),
            "--format",
            "json",
        ]
    )
    payload = json.loads(capsys.readouterr().out)

    assert exit_code == 0
    assert payload["status"] == "ready_for_review"
    assert payload["external_api_called"] is False
    assert payload["writes_performed"] is False

    destination = tmp_path / "cli-representatives"
    materialize_exit = main(
        [
            "materialize-experimental-models",
            str(spec_path),
            "--catalog",
            str(catalog_path),
            "--destination",
            str(destination),
            "--format",
            "json",
        ]
    )
    materialized = json.loads(capsys.readouterr().out)

    assert materialize_exit == 0
    assert materialized["writes_performed"] is True
    assert destination.is_dir()


def test_inference_without_xrd_abstains_and_recommends_low_cost_evidence(tmp_path) -> None:
    spec = ExperimentSpec(
        sample_id="no-xrd",
        evidence=(),
        allowed_elements=("Ni",),
    )
    registry = ProviderRegistry(
        (
            InMemoryStructureProvider(
                "synthetic",
                (("ni", _nickel(), StructureSourceKind.HYPOTHETICAL),),
            ),
        )
    )

    run = infer_experimental_models(
        ExperimentInput(spec, {}),
        registry,
        RuleCandidatePlanner(),
        maximum_representatives=1,
    )

    assert run.report.status is InferenceStatus.INSUFFICIENT_EVIDENCE
    assert run.report.claim_ceiling is ClaimLevel.CANDIDATE_ONLY
    assert run.report.phase_search is None
    assessment = run.report.candidate_assessments[0]
    assert assessment.modality_support == ()
    assert assessment.parent_support is None
    assert assessment.surface_support is None
    assert assessment.local_support is None
    assert run.report.has_errors is False
    assert any("XRD/GIXRD" in item for item in run.report.recommended_next_experiments)
    assert any(
        item.code == "EXPERIMENTAL_MODELING_NO_XRD_ARTIFACT" for item in run.report.diagnostics
    )
    with pytest.raises(ValueError, match="between 1 and 50"):
        infer_experimental_models(
            ExperimentInput(spec, {}),
            registry,
            RuleCandidatePlanner(),
            maximum_representatives=0,
        )


def test_inference_can_review_candidates_from_composition_without_xrd() -> None:
    evidence = EvidenceRecord(
        evidence_id="icp-1",
        kind=EvidenceKind.ICP,
        role=EvidenceRole.SOFT,
    )
    spec = ExperimentSpec(
        sample_id="composition-only",
        evidence=(evidence,),
        composition_constraints=(
            ElementConstraint(
                "Ni",
                0.95,
                1.0,
                CompositionScope.BULK,
                ("icp-1",),
            ),
        ),
        allowed_elements=("Ni",),
    )
    registry = ProviderRegistry(
        (
            InMemoryStructureProvider(
                "synthetic",
                (("ni", _nickel(), StructureSourceKind.HYPOTHETICAL),),
            ),
        )
    )

    run = infer_experimental_models(
        ExperimentInput(spec, {}),
        registry,
        RuleCandidatePlanner(),
        maximum_representatives=1,
    )

    assert run.report.status is InferenceStatus.READY_FOR_REVIEW
    assert run.report.claim_ceiling is ClaimLevel.CANDIDATE_ONLY
    assert run.report.phase_search is None
    checks = run.report.candidate_assessments[0].evidence_checks
    assert any(item.kind == "composition" and item.status == "within_range" for item in checks)
    assert run.report.candidate_assessments[0].parent_support == pytest.approx(1.0)


def test_inference_can_review_candidates_from_tem_spacing_without_xrd() -> None:
    evidence = EvidenceRecord(
        evidence_id="tem-1",
        kind=EvidenceKind.TEM,
        role=EvidenceRole.SOFT,
    )
    spec = ExperimentSpec(
        sample_id="tem-only",
        evidence=(evidence,),
        lattice_spacing_constraints=(LatticeSpacingConstraint(2.032, 0.05, ("tem-1",)),),
        allowed_elements=("Ni",),
    )
    registry = ProviderRegistry(
        (
            InMemoryStructureProvider(
                "synthetic",
                (("ni", _nickel(), StructureSourceKind.HYPOTHETICAL),),
            ),
        )
    )

    run = infer_experimental_models(
        ExperimentInput(spec, {}),
        registry,
        RuleCandidatePlanner(),
        maximum_representatives=1,
    )

    assert run.report.status is InferenceStatus.READY_FOR_REVIEW
    assert run.report.claim_ceiling is ClaimLevel.CANDIDATE_ONLY
    assert any(
        item.kind == "tem" and item.status == "within_range"
        for item in run.report.candidate_assessments[0].evidence_checks
    )
    assert run.report.candidate_assessments[0].local_support is not None


class _InvalidRecipePlanner:
    planner_id = "test-invalid"

    def plan(self, spec, registry, phase_search):
        reference = registry.references()[0]
        hypothesis = StructuralHypothesis(
            hypothesis_id="invalid",
            summary="A recipe that must fail local bounds.",
            evidence_ids=(),
            parent_reference_keys=(reference.key,),
            generated_atomistic_candidate=True,
        )
        recipe = CandidateRecipe(
            recipe_id="invalid-strain",
            parent_reference_key=reference.key,
            hypothesis_id=hypothesis.hypothesis_id,
            operations=(
                CandidateOperation(
                    CandidateOperationKind.ISOTROPIC_STRAIN,
                    {"strain": 0.5},
                ),
            ),
            evidence_ids=(),
            rationale="Exercise fail-closed workflow handling.",
        )
        return CandidatePlan((hypothesis,), (recipe,), (), self.planner_id)


def test_inference_catches_invalid_recipe_and_refuses_empty_materialization(tmp_path) -> None:
    spec = ExperimentSpec(
        sample_id="invalid-recipe",
        evidence=(),
        allowed_elements=("Ni",),
    )
    registry = ProviderRegistry(
        (
            InMemoryStructureProvider(
                "synthetic",
                (("ni", _nickel(), StructureSourceKind.HYPOTHETICAL),),
            ),
        )
    )

    run = infer_experimental_models(ExperimentInput(spec, {}), registry, _InvalidRecipePlanner())

    assert run.report.status is InferenceStatus.NO_VALID_CANDIDATES
    assert run.report.claim_ceiling is ClaimLevel.NO_ATOMIC_CLAIM
    assert run.report.has_errors is True
    assert run.report.diagnostics[-1].code == "CANDIDATE_RECIPE_EXECUTION_FAILED"
    with pytest.raises(ValueError, match="no representative"):
        materialize_representative_models(run, tmp_path / "must-not-exist")
