"""Web adapter for provenance-bound energy ledgers and generic linear derivations."""

from __future__ import annotations

import json
from typing import Any

from catex.energetics import (
    EnergyTerm,
    ReviewedEnergyEvidence,
    ReviewedEnergyRecord,
    VaspEnergyKind,
    derive_linear_energy,
)
from catex.vasp.output_models import ParseConfidence
from catex_app.projects import ProjectStore


def _hydrate(payload: dict[str, Any]) -> ReviewedEnergyRecord:
    return ReviewedEnergyRecord(
        energy_id=payload["energy_id"],
        kind=VaspEnergyKind(payload["kind"]),
        value_ev=payload["value_eV"],
        ionic_step=payload["ionic_step"],
        parse_confidence=ParseConfidence(payload["parse_confidence"]),
        energy_family_id=payload["energy_family_id"],
        review_sha256=payload["review_sha256"],
        binding_identity_sha256=payload["binding_identity_sha256"],
        record_sha256=payload["record_sha256"],
        output_directory_name=payload["output_directory_name"],
        vasp_artifact_names_and_sha256=tuple(
            (item["name"], item["sha256"]) for item in payload["vasp_artifacts"]
        ),
        evidence=tuple(
            ReviewedEnergyEvidence(
                artifact_name=item["artifact_name"],
                line_start=item["line_start"],
                line_end=item["line_end"],
                parser_rule=item["parser_rule"],
                confidence=ParseConfidence(item["confidence"]),
            )
            for item in payload["evidence"]
        ),
        scientific_result_accepted=payload["scientific_result_accepted"],
        submission_scientific_result_eligible=payload["submission_scientific_result_eligible"],
        eligible_for_same_energy_family_derivation=payload[
            "eligible_for_same_energy_family_derivation"
        ],
        human_review_recorded=payload["human_review_recorded"],
        automatic_acceptance_performed=payload["automatic_acceptance_performed"],
        writes_performed=payload["writes_performed"],
        commands_executed=payload["commands_executed"],
        additional_submission_performed=payload["additional_submission_performed"],
    )


class EnergyAnalysisService:
    def __init__(self, projects: ProjectStore):
        self.projects = projects

    def energy_payloads(self, project_id: str) -> list[dict[str, Any]]:
        project = self.projects.project_directory(project_id)
        paths = sorted(project.glob("runs/*/results/pull-*/*/reviewed-energy.json"))
        return [self.projects._read_json(path) for path in paths]

    def derive(
        self,
        project_id: str,
        *,
        derivation_id: str,
        coefficients: dict[str, float],
        approved_write: bool,
    ) -> dict[str, Any]:
        if not approved_write:
            raise PermissionError("approved_write=true is required to save a derivation")
        hydrated = tuple(_hydrate(item) for item in self.energy_payloads(project_id))
        records = {item.energy_id: item for item in hydrated}
        unknown = sorted(set(coefficients) - set(records))
        if unknown:
            raise ValueError(f"unknown reviewed energy ids: {', '.join(unknown)}")
        terms = tuple(EnergyTerm(value, records[key]) for key, value in coefficients.items())
        report = derive_linear_energy(terms, derivation_id=derivation_id)
        if report.value_ev is None or report.has_errors:
            return report.to_dict()
        directory = self.projects.project_directory(project_id) / "analysis"
        directory.mkdir(exist_ok=True)
        path = directory / f"{derivation_id}.json"
        if path.exists():
            raise ValueError("derivation_id already exists; overwrite is forbidden")
        with path.open("x", encoding="utf-8", newline="\n") as stream:
            json.dump(report.to_dict(), stream, ensure_ascii=False, indent=2, sort_keys=True)
            stream.write("\n")
        self.projects.append_event(
            project_id,
            "energy.linear_derivation_saved",
            {
                "derivation_id": derivation_id,
                "derivation_sha256": report.derivation_sha256,
            },
        )
        return report.to_dict()


__all__ = ["EnergyAnalysisService"]
