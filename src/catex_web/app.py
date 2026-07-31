"""Loopback-oriented FastAPI adapter for the CatEx Web POC."""

from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path
from typing import Annotated

from fastapi import FastAPI, File, HTTPException, Response, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, ConfigDict, Field

from catex import __version__
from catex.mlip import (
    ChgnetPreRelaxationConfig,
    ChgnetPreRelaxationError,
    ChgnetUnavailableError,
)
from catex.reactions.electrocatalysis import analyze_electrocatalysis, reaction_templates
from catex.vasp import (
    SUPPORTED_RESULT_FILES,
    VaspResultDocumentError,
    build_vasp_result_document,
    parse_vasp_output,
)
from catex.vasp.thermochemistry import harmonic_thermochemistry
from catex_app.analysis import EnergyAnalysisService
from catex_app.calculations import CalculationServiceError, CalculationWorkspaceService
from catex_app.campaigns import CampaignService
from catex_app.chgnet import ChgnetPreRelaxationService, ChgnetRunner
from catex_app.experimental_modeling import ExperimentalModelingService
from catex_app.hpc import HpcWorkspaceService
from catex_app.hpc_gateway import (
    HpcConnectionProfile,
    HpcGateway,
    HpcGatewayError,
    ParamikoHpcGateway,
)
from catex_app.projects import ProjectStore, ProjectStoreError
from catex_app.reference_cases import ReferenceCaseService
from catex_app.services import (
    MAX_STRUCTURE_UPLOAD_BYTES,
    UploadRejected,
    constrain_poscar,
    convert_cif_upload_to_poscar,
    inspect_structure_upload,
    parse_demo_vasp_output,
)
from catex_app.workflow import (
    WorkflowEdge,
    WorkflowNode,
    default_workflow_template,
    node_registry_payload,
    validate_workflow,
)
from catex_app.workflow_runtime import WorkflowRuntimeService
from catex_web.routes.experimental_modeling import create_experimental_modeling_router
from catex_web.routes.platform import create_platform_router

MAX_VASP_OUTPUT_UPLOAD_BYTES = 512 * 1024 * 1024
_VASP_OUTPUT_FILENAMES = {"OUTCAR", "OSZICAR"}
_VASP_RESULT_CANONICAL_NAMES = {name.upper(): name for name in SUPPORTED_RESULT_FILES}


def _scrub_temporary_output_paths(value: object) -> object:
    """Replace ephemeral server paths with portable artifact filenames."""

    if isinstance(value, list):
        return [_scrub_temporary_output_paths(item) for item in value]
    if isinstance(value, dict):
        scrubbed: dict[str, object] = {}
        for key, item in value.items():
            if key in {"path", "artifact_path"} and isinstance(item, str):
                scrubbed[key] = Path(item).name
            else:
                scrubbed[key] = _scrub_temporary_output_paths(item)
        return scrubbed
    return value


class PositionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    x: float
    y: float


class WorkflowNodeRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    node_id: str = Field(min_length=1, max_length=128)
    type_id: str = Field(min_length=1, max_length=128)
    position: PositionRequest
    parameters: dict[str, object] = Field(default_factory=dict)


class WorkflowEdgeRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    edge_id: str = Field(min_length=1, max_length=128)
    source_node_id: str = Field(min_length=1, max_length=128)
    source_port_id: str = Field(min_length=1, max_length=128)
    target_node_id: str = Field(min_length=1, max_length=128)
    target_port_id: str = Field(min_length=1, max_length=128)


class WorkflowValidationRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    nodes: list[WorkflowNodeRequest] = Field(max_length=256)
    edges: list[WorkflowEdgeRequest] = Field(max_length=1024)


class ProjectCreateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    title: str = Field(min_length=1, max_length=120)
    purpose: str = Field(min_length=1, max_length=64)
    description: str = Field(default="", max_length=2000)
    template_id: str = Field(default="structure-to-results", min_length=1, max_length=100)


class CalculationConfigRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: str
    protocol: dict[str, object]
    potcar_metadata: dict[str, object]
    execution_profile: dict[str, object]
    cluster_policy: dict[str, object]


class ArtifactPlanRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    artifact_id: str = Field(min_length=1, max_length=128)


class StructureReviewRequest(ArtifactPlanRequest):
    approved: bool
    reviewer: str = Field(min_length=1, max_length=100)
    note: str = Field(min_length=1, max_length=500)


class ProtocolApprovalRequest(ArtifactPlanRequest):
    reviewer: str = Field(min_length=1, max_length=100)
    note: str = Field(default="", max_length=500)


class MaterializationRequest(ArtifactPlanRequest):
    confirm_plan_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    approved_write: bool


class CifConversionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    filename: str = Field(min_length=1, max_length=255)
    content: str = Field(min_length=1, max_length=MAX_STRUCTURE_UPLOAD_BYTES)


class SelectiveDynamicsRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    poscar_text: str = Field(min_length=1, max_length=MAX_STRUCTURE_UPLOAD_BYTES)
    strategy: str = Field(pattern=r"^(none|adsorbate_indices|bottom_layers)$")
    mobile_indices_1based: list[int] = Field(default_factory=list, max_length=20000)
    bottom_layer_count: int = Field(default=1, ge=0, le=1000)
    layer_tolerance_angstrom: float = Field(default=0.5, ge=0.01, le=5.0)


class ChgnetPreRelaxationRequest(ArtifactPlanRequest):
    model_config = ConfigDict(extra="forbid")

    model_name: str = Field(default="0.3.0", pattern=r"^(0\.3\.0|r2scan)$")
    optimizer: str = Field(default="FIRE", pattern=r"^(FIRE|BFGS|LBFGS)$")
    fmax_eV_per_angstrom: float = Field(default=0.05, ge=0.005, le=1.0)
    max_steps: int = Field(default=500, ge=1, le=5000)
    relax_cell: bool = False
    device: str = Field(default="auto", pattern=r"^(auto|cpu|cuda)$")

    def config(self) -> ChgnetPreRelaxationConfig:
        payload = self.model_dump(exclude={"artifact_id"})
        return ChgnetPreRelaxationConfig(**payload)


class HpcProfileRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    host: str = Field(min_length=1, max_length=253)
    port: int = Field(ge=1, le=65535)
    username: str = Field(min_length=1, max_length=64)
    private_key_path: str = Field(min_length=1, max_length=1000)
    allowed_root: str = Field(min_length=2, max_length=1000)
    potcar_builder: str | None = Field(default=None, max_length=1000)
    potcar_root: str | None = Field(default=None, max_length=1000)
    host_key_sha256: str | None = Field(default=None, max_length=80)
    connect_timeout_seconds: int = Field(default=15, ge=3, le=60)

    def profile(self) -> HpcConnectionProfile:
        payload = self.model_dump()
        if payload["host_key_sha256"] == "":
            payload["host_key_sha256"] = None
        return HpcConnectionProfile(**payload)


class HpcProbeRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    profile: HpcProfileRequest


class PotcarMetadataProbeRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    profile: HpcProfileRequest
    labels: list[str] = Field(min_length=1, max_length=32)


class RemoteStageRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    profile: HpcProfileRequest
    run_id: str = Field(min_length=1, max_length=64)
    confirm_plan_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    approved_remote_write: bool


class RemoteSubmitRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    profile: HpcProfileRequest
    run_id: str = Field(min_length=1, max_length=64)
    confirm_plan_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    approved_submit: bool


class RemoteRunRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    profile: HpcProfileRequest
    run_id: str = Field(min_length=1, max_length=64)


class RemoteCancelRequest(RemoteRunRequest):
    approved_cancel: bool


class ResultPullRequest(RemoteRunRequest):
    approved_local_write: bool


class PotcarCopyRequest(RemoteRunRequest):
    approved_local_write: bool


class ResultReviewRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    run_id: str = Field(min_length=1, max_length=64)
    accepted: bool
    reviewer: str = Field(min_length=1, max_length=100)
    note: str = Field(min_length=1, max_length=500)
    energy_kind: str = Field(default="sigma_zero", max_length=40)


class EnergyDerivationRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    derivation_id: str = Field(pattern=r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,99}$")
    coefficients: dict[str, float] = Field(min_length=1, max_length=1000)
    approved_write: bool


class VibrationalModeRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    wavenumber_cm1: float
    energy_mev: float
    imaginary: bool = False


class HarmonicThermochemistryRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    modes: list[VibrationalModeRequest] = Field(max_length=10000)
    temperature_kelvin: float = Field(default=298.15, gt=0, le=5000)
    low_frequency_cutoff_cm1: float = Field(default=50.0, ge=0, le=1000)


class ReactionStateEnergyRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    energy_eV: float
    correction_eV: float = 0.0
    run_id: str | None = Field(default=None, max_length=64)
    energy_family_id: str | None = Field(default=None, max_length=128)


class ElectrocatalysisAnalysisRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    template_id: str = Field(pattern=r"^(her-che|oer-aem-che)$")
    states: dict[str, ReactionStateEnergyRequest] = Field(min_length=1, max_length=10)
    h2_free_energy_eV: float
    h2o_free_energy_eV: float | None = None
    oer_equilibrium_free_energy_eV: float = 4.92
    temperature_kelvin: float = Field(default=298.15, gt=0, le=5000)
    potential_volts: float = Field(default=0.0, ge=-10, le=10)
    pH: float = Field(default=0.0, ge=0, le=14)
    reference_electrode: str = Field(default="RHE", pattern=r"^(RHE|SHE)$")


def _persistent_root(explicit: str | Path | None) -> Path:
    if explicit is not None:
        return Path(explicit)
    configured = os.environ.get("CATEX_WORKBENCH_DATA_ROOT")
    return Path(configured) if configured else Path.cwd() / "staging" / "catex-workbench"


def create_app(
    *,
    data_root: str | Path | None = None,
    hpc_gateway: HpcGateway | None = None,
    chgnet_runner: ChgnetRunner | None = None,
) -> FastAPI:
    store = ProjectStore(_persistent_root(data_root))
    calculations = CalculationWorkspaceService(store)
    chgnet = ChgnetPreRelaxationService(store, chgnet_runner)
    hpc = HpcWorkspaceService(store, hpc_gateway or ParamikoHpcGateway())
    reference_cases = ReferenceCaseService(store, Path(__file__).resolve().parents[2])
    analysis = EnergyAnalysisService(store)
    workflow_runtime = WorkflowRuntimeService(store)
    campaigns = CampaignService(store)
    experimental_modeling = ExperimentalModelingService(store)
    application = FastAPI(
        title="CatEx Workbench API",
        version=__version__,
        description="Local, persistent API for CatEx calculation and result analysis.",
    )
    application.add_middleware(
        CORSMiddleware,
        allow_origins=["http://127.0.0.1:5173", "http://localhost:5173"],
        allow_credentials=False,
        allow_methods=["GET", "POST", "PUT", "PATCH"],
        allow_headers=["content-type"],
    )
    application.include_router(create_platform_router(workflow_runtime, campaigns))
    application.include_router(create_experimental_modeling_router(experimental_modeling))

    @application.get("/api/v1/capabilities")
    def capabilities() -> dict[str, object]:
        chgnet_status = chgnet.capabilities()
        return {
            "schema_version": "catex.web-capabilities.v1",
            "catex_version": __version__,
            "mode": "local_workbench",
            "hpc_enabled": True,
            "ssh_enabled": True,
            "hpc_default_active": False,
            "credentials_persisted": False,
            "project_persistence_enabled": True,
            "protocol_editor_enabled": True,
            "local_materialization_enabled": True,
            "writes_outside_ephemeral_storage": True,
            "persistent_storage_root": str(store.root),
            "scientific_acceptance_enabled": False,
            "result_first_enabled": True,
            "reaction_analysis_enabled": True,
            "mlip_pre_relaxation_enabled": bool(chgnet_status["available"]),
            "experimental_modeling_enabled": True,
            "experimental_modeling": experimental_modeling.capabilities(),
            "chgnet": chgnet_status,
            "max_structure_upload_bytes": MAX_STRUCTURE_UPLOAD_BYTES,
        }

    @application.get("/api/v1/chgnet/capabilities")
    def chgnet_runtime_capabilities() -> dict[str, object]:
        return chgnet.capabilities()

    @application.get("/api/v1/workflows/registry")
    def workflow_registry() -> dict[str, object]:
        return {
            "schema_version": "catex.node-registry.v1",
            "nodes": node_registry_payload(),
        }

    @application.get("/api/v1/workflows/templates/default")
    def workflow_template() -> dict[str, object]:
        template = default_workflow_template()
        validation = validate_workflow(template.nodes, template.edges)
        return {"template": template.to_dict(), "validation": validation.to_dict()}

    @application.post("/api/v1/workflows/validate")
    def validate_workflow_request(request: WorkflowValidationRequest) -> dict[str, object]:
        nodes = tuple(
            WorkflowNode(
                node_id=item.node_id,
                type_id=item.type_id,
                position_x=item.position.x,
                position_y=item.position.y,
                parameters=item.parameters,
            )
            for item in request.nodes
        )
        edges = tuple(
            WorkflowEdge(
                edge_id=item.edge_id,
                source_node_id=item.source_node_id,
                source_port_id=item.source_port_id,
                target_node_id=item.target_node_id,
                target_port_id=item.target_port_id,
            )
            for item in request.edges
        )
        return validate_workflow(nodes, edges).to_dict()

    @application.get("/api/v1/projects")
    def list_projects() -> dict[str, object]:
        return {"schema_version": "catex.web-project-list.v1", "projects": store.list_projects()}

    @application.post("/api/v1/projects", status_code=201)
    def create_project(request: ProjectCreateRequest) -> dict[str, object]:
        try:
            return store.create_project(**request.model_dump())
        except ProjectStoreError as error:
            raise HTTPException(status_code=400, detail=str(error)) from error

    @application.get("/api/v1/reference-cases/paper4")
    def paper4_reference_case() -> dict[str, object]:
        try:
            return reference_cases.paper4_summary()
        except (OSError, ValueError, KeyError, json.JSONDecodeError) as error:
            raise HTTPException(status_code=500, detail=str(error)) from error

    @application.post("/api/v1/projects/from-reference/paper4", status_code=201)
    def create_paper4_reference_project() -> dict[str, object]:
        try:
            return reference_cases.create_paper4_project()
        except (ProjectStoreError, OSError, ValueError, KeyError) as error:
            raise HTTPException(status_code=400, detail=str(error)) from error

    @application.get("/api/v1/projects/{project_id}")
    def get_project(project_id: str) -> dict[str, object]:
        try:
            return store.get_project(project_id)
        except ProjectStoreError as error:
            raise HTTPException(status_code=404, detail=str(error)) from error

    @application.get("/api/v1/projects/{project_id}/artifacts")
    def list_project_artifacts(project_id: str) -> dict[str, object]:
        try:
            return {
                "schema_version": "catex.web-artifact-list.v1",
                "artifacts": store.list_artifacts(project_id),
            }
        except ProjectStoreError as error:
            raise HTTPException(status_code=404, detail=str(error)) from error

    @application.post("/api/v1/projects/{project_id}/structures", status_code=201)
    async def add_project_structure(
        project_id: str,
        file: Annotated[UploadFile, File(description="POSCAR, CONTCAR, .poscar, .vasp, or .cif")],
    ) -> dict[str, object]:
        content = await file.read(MAX_STRUCTURE_UPLOAD_BYTES + 1)
        await file.close()
        try:
            return store.add_structure(project_id, file.filename or "", content)
        except (ProjectStoreError, UploadRejected) as error:
            raise HTTPException(status_code=400, detail=str(error)) from error

    @application.post(
        "/api/v1/projects/{project_id}/chgnet-pre-relaxations",
        status_code=201,
    )
    def pre_relax_project_structure(
        project_id: str,
        request: ChgnetPreRelaxationRequest,
    ) -> dict[str, object]:
        try:
            return chgnet.relax(project_id, request.artifact_id, request.config())
        except ChgnetUnavailableError as error:
            raise HTTPException(status_code=503, detail=str(error)) from error
        except (ProjectStoreError, ChgnetPreRelaxationError, OSError, ValueError) as error:
            raise HTTPException(status_code=400, detail=str(error)) from error

    @application.get("/api/v1/projects/{project_id}/structure-reviews/{artifact_id}")
    def get_structure_review(project_id: str, artifact_id: str) -> dict[str, object]:
        try:
            return {"review": store.get_structure_review(project_id, artifact_id)}
        except ProjectStoreError as error:
            raise HTTPException(status_code=404, detail=str(error)) from error

    @application.get("/api/v1/projects/{project_id}/artifacts/{artifact_id}/source")
    def get_project_artifact_source(project_id: str, artifact_id: str) -> dict[str, object]:
        try:
            return store.artifact_source(project_id, artifact_id)
        except ProjectStoreError as error:
            raise HTTPException(status_code=404, detail=str(error)) from error

    @application.post("/api/v1/projects/{project_id}/structure-reviews", status_code=201)
    def record_structure_review(
        project_id: str, request: StructureReviewRequest
    ) -> dict[str, object]:
        try:
            return store.record_structure_review(
                project_id,
                request.artifact_id,
                approved=request.approved,
                reviewer=request.reviewer,
                note=request.note,
            )
        except ProjectStoreError as error:
            raise HTTPException(status_code=400, detail=str(error)) from error

    @application.get("/api/v1/projects/{project_id}/workflow")
    def get_project_workflow(project_id: str) -> dict[str, object]:
        try:
            workflow = store.get_workflow(project_id)
        except ProjectStoreError as error:
            raise HTTPException(status_code=404, detail=str(error)) from error
        return {
            "schema_version": "catex.web-saved-workflow.v1",
            "workflow": workflow,
        }

    @application.post("/api/v1/projects/{project_id}/workflow")
    def save_project_workflow(
        project_id: str, request: WorkflowValidationRequest
    ) -> dict[str, object]:
        nodes = tuple(
            WorkflowNode(
                node_id=item.node_id,
                type_id=item.type_id,
                position_x=item.position.x,
                position_y=item.position.y,
                parameters=item.parameters,
            )
            for item in request.nodes
        )
        edges = tuple(
            WorkflowEdge(
                edge_id=item.edge_id,
                source_node_id=item.source_node_id,
                source_port_id=item.source_port_id,
                target_node_id=item.target_node_id,
                target_port_id=item.target_port_id,
            )
            for item in request.edges
        )
        validation = validate_workflow(nodes, edges)
        if not validation.valid:
            raise HTTPException(
                status_code=400, detail="workflow must pass validation before saving"
            )
        payload = {
            "schema_version": "catex.web-workflow.v1",
            "nodes": [item.model_dump() for item in request.nodes],
            "edges": [item.model_dump() for item in request.edges],
        }
        try:
            store.save_workflow(project_id, payload)
        except ProjectStoreError as error:
            raise HTTPException(status_code=400, detail=str(error)) from error
        return {"workflow": payload, "validation": validation.to_dict()}

    @application.get("/api/v1/projects/{project_id}/export")
    def export_project(project_id: str) -> Response:
        try:
            content = store.export_bundle(project_id)
        except ProjectStoreError as error:
            raise HTTPException(status_code=404, detail=str(error)) from error
        return Response(
            content=content,
            media_type="application/zip",
            headers={"Content-Disposition": f'attachment; filename="{project_id}.catex.zip"'},
        )

    @application.get("/api/v1/calculation-config/default")
    def default_calculation_config() -> dict[str, object]:
        return calculations.default_bundle()

    @application.get("/api/v1/projects/{project_id}/calculation-config")
    def get_calculation_config(project_id: str) -> dict[str, object]:
        try:
            bundle = calculations.get_bundle(project_id)
        except (ProjectStoreError, CalculationServiceError) as error:
            raise HTTPException(status_code=404, detail=str(error)) from error
        return {"bundle": bundle}

    @application.post("/api/v1/projects/{project_id}/calculation-config")
    def save_calculation_config(
        project_id: str, request: CalculationConfigRequest
    ) -> dict[str, object]:
        try:
            return calculations.save_bundle(project_id, request.model_dump())
        except (ProjectStoreError, CalculationServiceError, ValueError) as error:
            raise HTTPException(status_code=400, detail=str(error)) from error

    @application.post("/api/v1/projects/{project_id}/calculation-plan")
    def plan_project_calculation(
        project_id: str, request: ArtifactPlanRequest
    ) -> dict[str, object]:
        try:
            return calculations.plan(project_id, request.artifact_id)
        except (ProjectStoreError, CalculationServiceError, ValueError, OSError) as error:
            raise HTTPException(status_code=400, detail=str(error)) from error

    @application.post("/api/v1/projects/{project_id}/protocol-review")
    def approve_project_protocol(
        project_id: str, request: ProtocolApprovalRequest
    ) -> dict[str, object]:
        try:
            return calculations.approve_protocol(
                project_id,
                request.artifact_id,
                reviewer=request.reviewer,
                note=request.note,
            )
        except (ProjectStoreError, CalculationServiceError, ValueError, OSError) as error:
            raise HTTPException(status_code=400, detail=str(error)) from error

    @application.post("/api/v1/projects/{project_id}/materializations", status_code=201)
    def materialize_project_calculation(
        project_id: str, request: MaterializationRequest
    ) -> dict[str, object]:
        try:
            return calculations.materialize(
                project_id,
                request.artifact_id,
                confirm_plan_sha256=request.confirm_plan_sha256,
                approved_write=request.approved_write,
            )
        except PermissionError as error:
            raise HTTPException(status_code=403, detail=str(error)) from error
        except (ProjectStoreError, CalculationServiceError, ValueError, OSError) as error:
            raise HTTPException(status_code=400, detail=str(error)) from error

    @application.get("/api/v1/projects/{project_id}/runs")
    def list_project_runs(project_id: str) -> dict[str, object]:
        try:
            return {
                "schema_version": "catex.web-run-list.v1",
                "runs": store.list_runs(project_id),
            }
        except (ProjectStoreError, OSError, ValueError) as error:
            raise HTTPException(status_code=404, detail=str(error)) from error

    @application.post("/api/v1/hpc/probe")
    def probe_hpc(request: HpcProbeRequest) -> dict[str, object]:
        try:
            return hpc.probe(request.profile.profile())
        except (HpcGatewayError, OSError, ValueError) as error:
            raise HTTPException(status_code=400, detail=str(error)) from error

    @application.post("/api/v1/hpc/potcar-metadata")
    def inspect_remote_potcar_metadata(
        request: PotcarMetadataProbeRequest,
    ) -> dict[str, object]:
        try:
            return hpc.inspect_potcar_metadata(request.profile.profile(), tuple(request.labels))
        except (HpcGatewayError, OSError, ValueError) as error:
            raise HTTPException(status_code=400, detail=str(error)) from error

    @application.post("/api/v1/projects/{project_id}/remote-stage", status_code=201)
    def stage_remote_run(project_id: str, request: RemoteStageRequest) -> dict[str, object]:
        try:
            return hpc.stage(
                project_id,
                request.run_id,
                request.profile.profile(),
                confirm_plan_sha256=request.confirm_plan_sha256,
                approved_remote_write=request.approved_remote_write,
            )
        except PermissionError as error:
            raise HTTPException(status_code=403, detail=str(error)) from error
        except (ProjectStoreError, HpcGatewayError, OSError, ValueError) as error:
            raise HTTPException(status_code=400, detail=str(error)) from error

    @application.post("/api/v1/projects/{project_id}/remote-submit", status_code=201)
    def submit_remote_run(project_id: str, request: RemoteSubmitRequest) -> dict[str, object]:
        try:
            return hpc.submit(
                project_id,
                request.run_id,
                request.profile.profile(),
                confirm_plan_sha256=request.confirm_plan_sha256,
                approved_submit=request.approved_submit,
            )
        except PermissionError as error:
            raise HTTPException(status_code=403, detail=str(error)) from error
        except (ProjectStoreError, HpcGatewayError, OSError, ValueError) as error:
            raise HTTPException(status_code=400, detail=str(error)) from error

    @application.post("/api/v1/projects/{project_id}/remote-potcar")
    def copy_remote_potcar(project_id: str, request: PotcarCopyRequest) -> dict[str, object]:
        try:
            return hpc.copy_potcar(
                project_id,
                request.run_id,
                request.profile.profile(),
                approved_local_write=request.approved_local_write,
            )
        except PermissionError as error:
            raise HTTPException(status_code=403, detail=str(error)) from error
        except (ProjectStoreError, HpcGatewayError, OSError, ValueError) as error:
            raise HTTPException(status_code=400, detail=str(error)) from error

    @application.post("/api/v1/projects/{project_id}/remote-observe")
    def observe_remote_run(project_id: str, request: RemoteRunRequest) -> dict[str, object]:
        try:
            return hpc.observe(
                project_id,
                request.run_id,
                request.profile.profile(),
            )
        except (ProjectStoreError, HpcGatewayError, OSError, ValueError) as error:
            raise HTTPException(status_code=400, detail=str(error)) from error

    @application.post("/api/v1/projects/{project_id}/remote-cancel", status_code=201)
    def cancel_remote_run(
        project_id: str,
        request: RemoteCancelRequest,
    ) -> dict[str, object]:
        try:
            return hpc.cancel(
                project_id,
                request.run_id,
                request.profile.profile(),
                approved_cancel=request.approved_cancel,
            )
        except PermissionError as error:
            raise HTTPException(status_code=403, detail=str(error)) from error
        except (ProjectStoreError, HpcGatewayError, OSError, ValueError) as error:
            raise HTTPException(status_code=400, detail=str(error)) from error

    @application.post("/api/v1/projects/{project_id}/remote-results", status_code=201)
    def pull_remote_results(project_id: str, request: ResultPullRequest) -> dict[str, object]:
        try:
            return hpc.pull_results(
                project_id,
                request.run_id,
                request.profile.profile(),
                approved_local_write=request.approved_local_write,
            )
        except PermissionError as error:
            raise HTTPException(status_code=403, detail=str(error)) from error
        except (ProjectStoreError, HpcGatewayError, OSError, ValueError) as error:
            raise HTTPException(status_code=400, detail=str(error)) from error

    @application.get("/api/v1/projects/{project_id}/results/latest")
    def latest_project_result(project_id: str, run_id: str) -> dict[str, object]:
        try:
            return hpc.latest_result(project_id, run_id)
        except (ProjectStoreError, HpcGatewayError, OSError, ValueError) as error:
            raise HTTPException(status_code=404, detail=str(error)) from error

    @application.get("/api/v1/projects/{project_id}/calculation-results")
    def project_calculation_results(project_id: str) -> dict[str, object]:
        try:
            return {
                "schema_version": "catex.web-calculation-result-list.v1",
                "results": hpc.result_catalog(project_id),
            }
        except (ProjectStoreError, HpcGatewayError, OSError, ValueError) as error:
            raise HTTPException(status_code=400, detail=str(error)) from error

    @application.post("/api/v1/projects/{project_id}/result-reviews", status_code=201)
    def review_project_result(project_id: str, request: ResultReviewRequest) -> dict[str, object]:
        try:
            return hpc.review_result(
                project_id,
                request.run_id,
                accepted=request.accepted,
                reviewer=request.reviewer,
                note=request.note,
                energy_kind=request.energy_kind,
            )
        except (ProjectStoreError, HpcGatewayError, OSError, ValueError) as error:
            raise HTTPException(status_code=400, detail=str(error)) from error

    @application.get("/api/v1/projects/{project_id}/reviewed-energies")
    def list_reviewed_energies(project_id: str) -> dict[str, object]:
        try:
            return {
                "schema_version": "catex.web-reviewed-energy-list.v1",
                "energies": analysis.energy_payloads(project_id),
            }
        except (ProjectStoreError, OSError, ValueError, KeyError) as error:
            raise HTTPException(status_code=400, detail=str(error)) from error

    @application.post("/api/v1/projects/{project_id}/energy-derivations", status_code=201)
    def derive_project_energy(
        project_id: str, request: EnergyDerivationRequest
    ) -> dict[str, object]:
        try:
            return analysis.derive(
                project_id,
                derivation_id=request.derivation_id,
                coefficients=request.coefficients,
                approved_write=request.approved_write,
            )
        except PermissionError as error:
            raise HTTPException(status_code=403, detail=str(error)) from error
        except (ProjectStoreError, OSError, ValueError, KeyError) as error:
            raise HTTPException(status_code=400, detail=str(error)) from error

    @application.post("/api/v1/structures/inspect")
    async def inspect_structure_endpoint(
        file: Annotated[UploadFile, File(description="POSCAR, CONTCAR, .poscar, .vasp, or .cif")],
    ) -> dict[str, object]:
        content = await file.read(MAX_STRUCTURE_UPLOAD_BYTES + 1)
        await file.close()
        try:
            return inspect_structure_upload(file.filename or "", content)
        except UploadRejected as error:
            raise HTTPException(status_code=400, detail=str(error)) from error

    @application.post("/api/v1/structures/cif-to-poscar")
    def convert_cif_to_poscar(request: CifConversionRequest) -> dict[str, object]:
        try:
            return convert_cif_upload_to_poscar(
                request.filename,
                request.content.encode("utf-8"),
            )
        except UploadRejected as error:
            raise HTTPException(status_code=400, detail=str(error)) from error

    @application.post("/api/v1/structures/selective-dynamics")
    def apply_selective_dynamics(request: SelectiveDynamicsRequest) -> dict[str, object]:
        try:
            return constrain_poscar(
                request.poscar_text.encode("utf-8"),
                strategy=request.strategy,
                mobile_indices_1based=tuple(request.mobile_indices_1based),
                bottom_layer_count=request.bottom_layer_count,
                layer_tolerance_angstrom=request.layer_tolerance_angstrom,
            )
        except UploadRejected as error:
            raise HTTPException(status_code=400, detail=str(error)) from error

    @application.post("/api/v1/vasp-output/parse")
    async def parse_uploaded_vasp_output(
        files: Annotated[
            list[UploadFile],
            File(description="One or both of OUTCAR and OSZICAR"),
        ],
    ) -> dict[str, object]:
        """Parse user-selected VASP outputs ephemerally without retaining uploads."""

        if not 1 <= len(files) <= 2:
            raise HTTPException(status_code=400, detail="Upload one or both of OUTCAR and OSZICAR")
        normalized: list[tuple[UploadFile, str]] = []
        seen: set[str] = set()
        for upload in files:
            filename = upload.filename or ""
            if filename != Path(filename).name or "\\" in filename:
                raise HTTPException(
                    status_code=400,
                    detail="VASP output filenames must be basenames",
                )
            canonical = filename.upper()
            if canonical not in _VASP_OUTPUT_FILENAMES:
                raise HTTPException(
                    status_code=400,
                    detail="Only files named OUTCAR and OSZICAR are supported",
                )
            if canonical in seen:
                raise HTTPException(status_code=400, detail=f"Duplicate uploaded file: {canonical}")
            seen.add(canonical)
            normalized.append((upload, canonical))

        try:
            with tempfile.TemporaryDirectory(prefix="catex-output-upload-") as temporary:
                root = Path(temporary)
                total_bytes = 0
                for upload, canonical in normalized:
                    with (root / canonical).open("xb") as destination:
                        while chunk := await upload.read(1024 * 1024):
                            total_bytes += len(chunk)
                            if total_bytes > MAX_VASP_OUTPUT_UPLOAD_BYTES:
                                raise HTTPException(
                                    status_code=413,
                                    detail="Combined VASP output upload exceeds the 512 MiB limit",
                                )
                            destination.write(chunk)
                payload = parse_vasp_output(root).to_dict()
                payload["directory"] = "browser-upload"
                payload["upload"] = {
                    "filenames": [canonical for _, canonical in normalized],
                    "retained": False,
                    "hpc_contacted": False,
                }
                return _scrub_temporary_output_paths(payload)  # type: ignore[return-value]
        finally:
            for upload, _ in normalized:
                await upload.close()

    @application.post("/api/v1/vasp-results/parse")
    async def parse_uploaded_vasp_results(
        files: Annotated[
            list[UploadFile],
            File(description="Supported VASP output and analysis artifacts"),
        ],
    ) -> dict[str, object]:
        """Build one ephemeral result document from common VASP artifacts."""

        if not 1 <= len(files) <= len(SUPPORTED_RESULT_FILES):
            raise HTTPException(
                status_code=400,
                detail="Upload between 1 and 8 supported VASP result files",
            )
        normalized: list[tuple[UploadFile, str]] = []
        seen: set[str] = set()
        for upload in files:
            filename = upload.filename or ""
            if filename != Path(filename).name or "\\" in filename:
                raise HTTPException(
                    status_code=400,
                    detail="VASP result filenames must be basenames",
                )
            canonical = _VASP_RESULT_CANONICAL_NAMES.get(filename.upper())
            if canonical is None:
                raise HTTPException(
                    status_code=400,
                    detail=(
                        "Supported names are OUTCAR, OSZICAR, CONTCAR, vasprun.xml, "
                        "XDATCAR, CHGCAR, LOCPOT, and ELFCAR"
                    ),
                )
            if canonical in seen:
                raise HTTPException(
                    status_code=400,
                    detail=f"Duplicate uploaded file: {canonical}",
                )
            seen.add(canonical)
            normalized.append((upload, canonical))

        try:
            with tempfile.TemporaryDirectory(prefix="catex-result-document-") as temporary:
                root = Path(temporary)
                total_bytes = 0
                for upload, canonical in normalized:
                    with (root / canonical).open("xb") as destination:
                        while chunk := await upload.read(1024 * 1024):
                            total_bytes += len(chunk)
                            if total_bytes > MAX_VASP_OUTPUT_UPLOAD_BYTES:
                                raise HTTPException(
                                    status_code=413,
                                    detail=(
                                        "Combined VASP result upload exceeds the 512 MiB limit"
                                    ),
                                )
                            destination.write(chunk)
                payload = build_vasp_result_document(root)
                payload["directory"] = "browser-upload"
                payload["upload"] = {
                    "filenames": [canonical for _, canonical in normalized],
                    "retained": False,
                    "hpc_contacted": False,
                }
                return _scrub_temporary_output_paths(payload)  # type: ignore[return-value]
        except VaspResultDocumentError as error:
            raise HTTPException(status_code=400, detail=str(error)) from error
        finally:
            for upload, _ in normalized:
                await upload.close()

    @application.post("/api/v1/thermochemistry/harmonic")
    def calculate_harmonic_thermochemistry(
        request: HarmonicThermochemistryRequest,
    ) -> dict[str, object]:
        try:
            return harmonic_thermochemistry(
                ((item.wavenumber_cm1, item.energy_mev, item.imaginary) for item in request.modes),
                temperature_kelvin=request.temperature_kelvin,
                low_frequency_cutoff_cm1=request.low_frequency_cutoff_cm1,
            ).to_dict()
        except ValueError as error:
            raise HTTPException(status_code=400, detail=str(error)) from error

    @application.get("/api/v1/reaction-analysis/templates")
    def electrocatalysis_templates() -> dict[str, object]:
        return {
            "schema_version": "catex.reaction-template-list.v1",
            "templates": reaction_templates(),
        }

    @application.post("/api/v1/reaction-analysis")
    def calculate_electrocatalysis_analysis(
        request: ElectrocatalysisAnalysisRequest,
    ) -> dict[str, object]:
        families = {
            item.energy_family_id for item in request.states.values() if item.energy_family_id
        }
        if len(families) > 1:
            raise HTTPException(
                status_code=400,
                detail="bound calculation results do not share one energy family",
            )
        try:
            return analyze_electrocatalysis(
                request.template_id,
                {key: item.energy_eV for key, item in request.states.items()},
                corrections_ev={key: item.correction_eV for key, item in request.states.items()},
                h2_free_energy_ev=request.h2_free_energy_eV,
                h2o_free_energy_ev=request.h2o_free_energy_eV,
                oer_equilibrium_free_energy_ev=request.oer_equilibrium_free_energy_eV,
                temperature_kelvin=request.temperature_kelvin,
                potential_volts=request.potential_volts,
                ph=request.pH,
                reference_electrode=request.reference_electrode,
                energy_family_id=next(iter(families), None),
            ).to_dict()
        except ValueError as error:
            raise HTTPException(status_code=400, detail=str(error)) from error

    @application.get("/api/v1/demo/vasp-output")
    def demo_vasp_output() -> dict[str, object]:
        return parse_demo_vasp_output()

    if os.environ.get("CATEX_SERVE_WEB") == "1":
        web_dist = Path(__file__).resolve().parents[2] / "apps" / "web" / "dist"
        if not (web_dist / "index.html").is_file():
            raise RuntimeError("CATEX_SERVE_WEB=1 requires a built apps/web/dist directory")
        application.mount(
            "/",
            StaticFiles(directory=web_dist, html=True),
            name="catex-workbench",
        )

    return application


app = create_app()
