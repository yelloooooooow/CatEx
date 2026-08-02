from __future__ import annotations

from pathlib import Path

from catex.experimental import (
    ClaimLevel,
    InferenceStatus,
    ProviderRegistry,
    RuleCandidatePlanner,
    extract_characterization_summary,
    infer_experimental_models,
    load_local_structure_catalog,
    parse_experiment_spec,
)

ROOT = Path(__file__).resolve().parents[1] / "projects" / "nimo_her_literature_benchmark"


def test_published_nimo_measurements_select_the_ni4mo_parent() -> None:
    inputs = (
        (
            "xrd-phase",
            "xrd",
            None,
            "All diffraction peaks were indexed to the Ni4Mo phase (JCPDS 65-5480).",
            "",
            "context",
        ),
        (
            "eds-ratio",
            "eds",
            ROOT / "eds_composition.csv",
            "EDX reports an atomic Ni:Mo ratio of 4:1.",
            "STEM-EDX elemental analysis",
            "hard",
        ),
        (
            "xps-ratio",
            "xps",
            ROOT / "xps_metal_ratio.csv",
            "XPS reports Mo:Ni = 1:4; metallic Mo and Ni are present; O is unquantified.",
            "XPS peak fitting",
            "soft",
        ),
        (
            "tem-spacing",
            "tem",
            None,
            "HRTEM d-spacing = 0.208 nm for the MoNi4 (121) plane.",
            "HRTEM and SAED",
            "hard",
        ),
    )
    evidence = []
    compositions = []
    environments = []
    spacings = []
    suggested_elements: set[str] = set()
    for evidence_id, kind, path, conclusion, instrument, role in inputs:
        extraction = extract_characterization_summary(
            path,
            kind=kind,
            evidence_id=evidence_id,
            conclusion=conclusion,
            instrument_info=instrument,
        )
        evidence.append(
            {
                "evidence_id": evidence_id,
                "kind": kind,
                "role": role,
                "metadata": extraction["metadata"],
                "note": conclusion,
            }
        )
        compositions.extend(extraction["composition_constraints"])
        environments.extend(extraction["local_environment_constraints"])
        spacings.extend(extraction["lattice_spacing_constraints"])
        suggested_elements.update(extraction["suggested_elements"])

    experiment = parse_experiment_spec(
        {
            "schema_version": "catex.experiment-spec.v1",
            "sample_id": "chen-2023-nimo-pa-at-nf",
            "material_pack": "alloy-electrocatalyst",
            "allowed_elements": sorted(suggested_elements),
            "excluded_elements": [],
            "composition_constraints": compositions,
            "local_environment_constraints": environments,
            "lattice_spacing_constraints": spacings,
            "evidence": evidence,
        }
    )
    registry = ProviderRegistry((load_local_structure_catalog(ROOT / "catalog.json"),))

    run = infer_experimental_models(
        experiment,
        registry,
        RuleCandidatePlanner(),
        maximum_representatives=10,
    )

    assert suggested_elements == {"Ni", "Mo"}
    assert run.report.status is InferenceStatus.READY_FOR_REVIEW
    assert run.report.claim_ceiling is ClaimLevel.CANDIDATE_ONLY
    assert run.report.external_api_called is False
    assessments = {item.candidate_id: item for item in run.report.candidate_assessments}
    retained = [assessments[item] for item in run.report.representative_candidate_ids]
    assert retained
    assert all("nist-jarvis-jvasp-16581-ni4mo" in item.parent_reference_key for item in retained)
    assert all(
        not item.valid
        for item in assessments.values()
        if "fcc-ni-negative-control" in item.parent_reference_key
    )
    bulk = next(item for item in retained if item.model_kind.value == "bulk")
    assert bulk.formula == "Ni4Mo"
    assert any(
        check.kind == "tem"
        and check.status == "within_range"
        and abs((check.predicted_value or 0.0) - 2.08) < 0.01
        for check in bulk.evidence_checks
    )
