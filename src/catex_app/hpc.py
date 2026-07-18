"""Project-bound HPC orchestration with explicit stage, submit, observe, and pull gates."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from uuid import uuid4

from catex.energetics import VaspEnergyKind, bind_reviewed_vasp_energy
from catex.hpc import parse_slurm_snapshot, validate_run_binding
from catex.results import record_scientific_result_review
from catex.vasp import parse_vasp_output
from catex_app.hpc_gateway import HpcConnectionProfile, HpcGateway, HpcGatewayError
from catex_app.projects import ProjectStore
from catex_app.services import MAX_STRUCTURE_UPLOAD_BYTES, UploadRejected, inspect_structure_upload

_SUBMISSION_TEMPLATE = (
    "sbatch --chdir=<authorized-job-directory> --parsable <authorized-job-directory>/slurm.sh"
)


def _utc_now() -> str:
    return datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _write_json_exclusive(path: Path, payload: dict[str, Any]) -> None:
    with path.open("x", encoding="utf-8", newline="\n") as stream:
        json.dump(payload, stream, ensure_ascii=False, indent=2, sort_keys=True)
        stream.write("\n")


class HpcWorkspaceService:
    """Keep connection secrets ephemeral while persisting sanitized run evidence."""

    def __init__(self, projects: ProjectStore, gateway: HpcGateway):
        self.projects = projects
        self.gateway = gateway

    @staticmethod
    def _structure_snapshot(path: Path) -> dict[str, Any] | None:
        if not path.is_file() or path.stat().st_size > MAX_STRUCTURE_UPLOAD_BYTES:
            return None
        try:
            payload = inspect_structure_upload(path.name, path.read_bytes())
        except (OSError, UploadRejected, ValueError):
            return None
        return {
            "filename": path.name,
            "inspection": payload["inspection"],
            "viewer": payload["viewer"],
        }

    def _enrich_result(
        self, project_id: str, run_id: str, directory: Path, result: dict[str, Any]
    ) -> dict[str, Any]:
        run = self.projects.run_directory(project_id, run_id)
        enriched = dict(result)
        enriched.setdefault("initial_structure", self._structure_snapshot(run / "POSCAR"))
        enriched.setdefault("final_structure", self._structure_snapshot(directory / "CONTCAR"))
        vasp = enriched.get("vasp") if isinstance(enriched.get("vasp"), dict) else {}
        binding = enriched.get("binding") if isinstance(enriched.get("binding"), dict) else {}
        enriched["analysis_eligible"] = bool(
            vasp.get("scientifically_complete") and binding.get("binding_valid")
        )
        enriched["human_review_required"] = False
        return enriched

    def probe(self, profile: HpcConnectionProfile) -> dict[str, Any]:
        return self.gateway.probe(profile)

    def inspect_potcar_metadata(
        self, profile: HpcConnectionProfile, labels: tuple[str, ...]
    ) -> dict[str, Any]:
        return self.gateway.inspect_potcar_metadata(profile, labels)

    def stage(
        self,
        project_id: str,
        run_id: str,
        profile: HpcConnectionProfile,
        *,
        confirm_plan_sha256: str,
        approved_remote_write: bool,
    ) -> dict[str, Any]:
        if not approved_remote_write:
            raise PermissionError("approved_remote_write=true is required")
        run = self.projects.run_directory(project_id, run_id)
        manifest = self.projects._read_json(run / "catex-manifest.json")
        if manifest.get("plan_sha256") != confirm_plan_sha256:
            raise HpcGatewayError("plan confirmation digest does not match the local run")
        record_path = run / "catex-remote-stage.json"
        if record_path.exists():
            raise HpcGatewayError("this run already has a remote stage record")
        outcome = self.gateway.stage(profile, run, run_id)
        record = {
            **outcome,
            "schema_version": "catex.remote-stage-record.v1",
            "staged_at_utc": _utc_now(),
            "plan_sha256": confirm_plan_sha256,
            "credentials_retained": False,
            "remote_root_retained": False,
        }
        _write_json_exclusive(record_path, record)
        self.projects.append_event(
            project_id,
            "run.remote_staged",
            {"run_id": run_id, "plan_sha256": confirm_plan_sha256},
        )
        return record

    def copy_potcar(
        self,
        project_id: str,
        run_id: str,
        profile: HpcConnectionProfile,
        *,
        approved_local_write: bool,
    ) -> dict[str, Any]:
        if not approved_local_write:
            raise PermissionError("approved_local_write=true is required")
        run = self.projects.run_directory(project_id, run_id)
        stage = self.projects._read_json(run / "catex-remote-stage.json")
        if stage.get("potcar_materialized_on_hpc") is not True:
            raise HpcGatewayError("the remote stage has no confirmed POTCAR")
        payload = self.gateway.download_potcar(profile, run_id)
        if payload.get("sha256") != stage.get("potcar_sha256"):
            raise HpcGatewayError("copied POTCAR hash does not match the remote build receipt")
        return payload

    def submit(
        self,
        project_id: str,
        run_id: str,
        profile: HpcConnectionProfile,
        *,
        confirm_plan_sha256: str,
        approved_submit: bool,
    ) -> dict[str, Any]:
        if not approved_submit:
            raise PermissionError("approved_submit=true is required")
        run = self.projects.run_directory(project_id, run_id)
        stage = self.projects._read_json(run / "catex-remote-stage.json")
        if stage.get("plan_sha256") != confirm_plan_sha256:
            raise HpcGatewayError("staged plan does not match the submission confirmation")
        receipt_path = run / "catex-submission-receipt.json"
        if receipt_path.exists():
            raise HpcGatewayError("this run has already been submitted")
        submission = self.gateway.submit(profile, run_id, confirm_plan_sha256)
        config = self.projects._read_json(
            self.projects.project_directory(project_id) / "config" / "potcar-metadata.json"
        )
        synthetic = str(config.get("potential_family", "")).upper().startswith("SYNTHETIC")
        receipt = {
            "schema_version": "catex.submission-receipt.v1",
            "submitted_at_utc": _utc_now(),
            "job_id": submission["job_id"],
            "job_directory_name": run_id,
            "job_name": run_id,
            "plan_sha256": confirm_plan_sha256,
            "slurm_script_sha256": self.projects._read_json(run / "catex-manifest.json")[
                "slurm_script_sha256"
            ],
            "submission_command_template": _SUBMISSION_TEMPLATE,
            "raw_submission_output_sha256": submission["raw_submission_output_sha256"],
            "submission_performed": True,
            "approved_scope": f"project-{project_id[-12:]}-run-{run_id}"[:128],
            "scientific_result_eligible": not synthetic,
            "overwrite_performed": False,
            "deletion_performed": False,
        }
        _write_json_exclusive(receipt_path, receipt)
        self.projects.mark_remote_submission(
            project_id,
            run_id=run_id,
            job_id=str(submission["job_id"]),
            plan_sha256=confirm_plan_sha256,
        )
        return receipt

    def observe(
        self,
        project_id: str,
        run_id: str,
        profile: HpcConnectionProfile,
    ) -> dict[str, Any]:
        run = self.projects.run_directory(project_id, run_id)
        receipt = self.projects._read_json(run / "catex-submission-receipt.json")
        observed_at = _utc_now()
        raw = self.gateway.observe(profile, run_id, str(receipt["job_id"]))
        report = parse_slurm_snapshot(
            raw["snapshot"],
            source=raw["source"],
            job_id=str(receipt["job_id"]),
            observed_at_utc=observed_at,
        )
        observations = run / "observations"
        observations.mkdir(exist_ok=True)
        token = uuid4().hex[:10]
        snapshot_name = f"{observed_at.replace(':', '')}-{token}-{raw['source']}.txt"
        snapshot_path = observations / snapshot_name
        with snapshot_path.open("x", encoding="utf-8", newline="\n") as stream:
            stream.write(str(raw["snapshot"]))
        record = {
            "schema_version": "catex.web-hpc-observation.v1",
            "observed_at_utc": observed_at,
            "snapshot_filename": snapshot_name,
            "report": report.to_dict(),
            "writes_performed_remotely": False,
        }
        _write_json_exclusive(observations / f"{snapshot_name}.json", record)
        return record

    def pull_results(
        self,
        project_id: str,
        run_id: str,
        profile: HpcConnectionProfile,
        *,
        approved_local_write: bool,
    ) -> dict[str, Any]:
        if not approved_local_write:
            raise PermissionError("approved_local_write=true is required")
        run = self.projects.run_directory(project_id, run_id)
        receipt_path = run / "catex-submission-receipt.json"
        receipt = self.projects._read_json(receipt_path)
        observations = sorted((run / "observations").glob("*.txt"))
        if not observations:
            raise HpcGatewayError("observe the submitted job before pulling results")
        latest_snapshot = observations[-1]
        latest_record = self.projects._read_json(
            latest_snapshot.with_name(f"{latest_snapshot.name}.json")
        )
        report = latest_record["report"]
        observation = report.get("observation")
        if not isinstance(observation, dict) or observation.get("active") is True:
            raise HpcGatewayError("results can only be pulled after a terminal scheduler state")
        session = run / "results" / f"pull-{uuid4().hex[:12]}"
        session.mkdir(parents=True, exist_ok=False)
        destination = session / run_id
        download = self.gateway.download_results(profile, run_id, destination)
        parsed = parse_vasp_output(destination)
        binding = validate_run_binding(
            destination,
            submission_receipt_path=receipt_path,
            slurm_snapshot_path=latest_snapshot,
            source=report["source"],
            observed_at_utc=latest_record["observed_at_utc"],
        )
        result = {
            "schema_version": "catex.web-run-result.v1",
            "run_id": run_id,
            "job_id": receipt["job_id"],
            "download": download,
            "vasp": parsed.to_dict(),
            "binding": binding.to_dict(),
            "scientific_result_accepted": False,
            "human_review_required": False,
        }
        result = self._enrich_result(project_id, run_id, destination, result)
        _write_json_exclusive(destination / "result.json", result)
        self.projects.append_event(
            project_id,
            "run.results_pulled",
            {"run_id": run_id, "job_id": receipt["job_id"], "status": parsed.status},
        )
        return result

    def _latest_result_directory(self, project_id: str, run_id: str) -> Path:
        run = self.projects.run_directory(project_id, run_id)
        results = sorted((run / "results").glob(f"pull-*/{run_id}/result.json"))
        if not results:
            raise HpcGatewayError("this run has no downloaded result snapshot")
        return results[-1].parent

    def latest_result(self, project_id: str, run_id: str) -> dict[str, Any]:
        directory = self._latest_result_directory(project_id, run_id)
        result = self._enrich_result(
            project_id, run_id, directory, self.projects._read_json(directory / "result.json")
        )
        review_path = directory / "scientific-review.json"
        energy_path = directory / "reviewed-energy.json"
        return {
            "result": result,
            "review": self.projects._read_json(review_path) if review_path.is_file() else None,
            "reviewed_energy": (
                self.projects._read_json(energy_path) if energy_path.is_file() else None
            ),
        }

    def result_catalog(self, project_id: str) -> list[dict[str, Any]]:
        """List latest immutable result snapshots available for plotting and comparison."""

        catalog: list[dict[str, Any]] = []
        for run_summary in self.projects.list_runs(project_id):
            run_id = str(run_summary["run_id"])
            try:
                directory = self._latest_result_directory(project_id, run_id)
            except HpcGatewayError:
                continue
            result = self._enrich_result(
                project_id, run_id, directory, self.projects._read_json(directory / "result.json")
            )
            vasp = result.get("vasp", {})
            energy = vasp.get("energy") if isinstance(vasp, dict) else None
            selected = None
            selected_kind = None
            if isinstance(energy, dict):
                for key, kind in (
                    ("sigma_zero_energy_eV", "sigma_zero"),
                    ("energy_without_entropy_eV", "without_entropy"),
                    ("free_energy_eV", "free_energy"),
                ):
                    if energy.get(key) is not None:
                        selected = energy[key]
                        selected_kind = kind
                        break
            catalog.append(
                {
                    "schema_version": "catex.web-calculation-result.v1",
                    "run_id": run_id,
                    "job_id": result.get("job_id"),
                    "status": vasp.get("status") if isinstance(vasp, dict) else "unknown",
                    "calculation_type": (
                        vasp.get("convergence", {}).get("calculation_type", "unknown")
                        if isinstance(vasp, dict)
                        else "unknown"
                    ),
                    "energy_eV": selected,
                    "energy_kind": selected_kind,
                    "energy_family_id": run_summary.get("energy_family_id"),
                    "analysis_eligible": result.get("analysis_eligible", False),
                    "final_structure": result.get("final_structure"),
                    "vibrations": vasp.get("vibrations") if isinstance(vasp, dict) else None,
                }
            )
        return catalog

    def review_result(
        self,
        project_id: str,
        run_id: str,
        *,
        accepted: bool,
        reviewer: str,
        note: str,
        energy_kind: str = "sigma_zero",
    ) -> dict[str, Any]:
        run = self.projects.run_directory(project_id, run_id)
        try:
            selected_kind = VaspEnergyKind(energy_kind)
        except ValueError as exc:
            raise HpcGatewayError("energy_kind is not supported") from exc
        directory = self._latest_result_directory(project_id, run_id)
        review_path = directory / "scientific-review.json"
        if review_path.exists():
            raise HpcGatewayError("this result snapshot already has a scientific review")
        receipt_path = run / "catex-submission-receipt.json"
        observations = sorted((run / "observations").glob("*.txt"))
        if not observations:
            raise HpcGatewayError("scheduler evidence is unavailable")
        latest_snapshot = observations[-1]
        observation_record = self.projects._read_json(
            latest_snapshot.with_name(f"{latest_snapshot.name}.json")
        )
        binding = validate_run_binding(
            directory,
            submission_receipt_path=receipt_path,
            slurm_snapshot_path=latest_snapshot,
            source=observation_record["report"]["source"],
            observed_at_utc=observation_record["observed_at_utc"],
        )
        review = record_scientific_result_review(
            binding,
            accepted=accepted,
            reviewer=reviewer,
            reviewed_at_utc=_utc_now(),
            note=note,
        )
        payload = review.to_dict()
        energy_payload = None
        if accepted:
            energy_payload = bind_reviewed_vasp_energy(
                review,
                parse_vasp_output(directory),
                energy_id=run_id,
                kind=selected_kind,
            ).to_dict()
        _write_json_exclusive(review_path, payload)
        if energy_payload is not None:
            _write_json_exclusive(directory / "reviewed-energy.json", energy_payload)
        self.projects.append_event(
            project_id,
            "run.scientific_result_reviewed",
            {
                "run_id": run_id,
                "job_id": review.job_id,
                "decision": review.decision.value,
                "review_sha256": review.review_sha256,
            },
        )
        return payload


__all__ = ["HpcWorkspaceService"]
