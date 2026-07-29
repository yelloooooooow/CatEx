"""Workflow authoring/runtime and campaign API routes."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, ConfigDict, Field

from catex_app.campaigns import CampaignError, CampaignService
from catex_app.projects import ProjectStoreError
from catex_app.workflow import (
    WorkflowEdge,
    WorkflowNode,
    validate_workflow,
    workflow_template_catalog,
)
from catex_app.workflow_execution import (
    WorkflowExecutionPlanError,
    compile_workflow_execution_plan,
)
from catex_app.workflow_runtime import WorkflowRuntimeError, WorkflowRuntimeService


class PositionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    x: float
    y: float


class WorkflowNodeRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    node_id: str = Field(min_length=1, max_length=128)
    type_id: str = Field(min_length=1, max_length=128)
    position: PositionRequest
    parameters: dict[str, Any] = Field(default_factory=dict)


class WorkflowEdgeRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    edge_id: str = Field(min_length=1, max_length=128)
    source_node_id: str = Field(min_length=1, max_length=128)
    source_port_id: str = Field(min_length=1, max_length=128)
    target_node_id: str = Field(min_length=1, max_length=128)
    target_port_id: str = Field(min_length=1, max_length=128)


class WorkflowGraphRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    nodes: list[WorkflowNodeRequest] = Field(max_length=256)
    edges: list[WorkflowEdgeRequest] = Field(max_length=1024)

    def domain(self) -> tuple[tuple[WorkflowNode, ...], tuple[WorkflowEdge, ...]]:
        nodes = tuple(
            WorkflowNode(
                node_id=item.node_id,
                type_id=item.type_id,
                position_x=item.position.x,
                position_y=item.position.y,
                parameters=item.parameters,
            )
            for item in self.nodes
        )
        edges = tuple(
            WorkflowEdge(
                edge_id=item.edge_id,
                source_node_id=item.source_node_id,
                source_port_id=item.source_port_id,
                target_node_id=item.target_node_id,
                target_port_id=item.target_port_id,
            )
            for item in self.edges
        )
        return nodes, edges

    def graph(self) -> dict[str, Any]:
        return {
            "nodes": [item.model_dump() for item in self.nodes],
            "edges": [item.model_dump() for item in self.edges],
        }


class DraftSaveRequest(WorkflowGraphRequest):
    expected_draft_sha256: str | None = Field(
        default=None,
        pattern=r"^[0-9a-f]{64}$",
    )

    def graph(self) -> dict[str, Any]:
        payload = self.model_dump(exclude={"expected_draft_sha256"})
        return {"nodes": payload["nodes"], "edges": payload["edges"]}


class RevisionPublishRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    title: str = Field(default="", max_length=120)
    note: str = Field(default="", max_length=1000)


class RunGraphCreateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    revision_id: str = Field(min_length=1, max_length=128)
    label: str = Field(default="", max_length=120)
    bindings: dict[str, Any] = Field(default_factory=dict)


class NodeAttemptRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    node_id: str = Field(min_length=1, max_length=128)
    status: str = Field(min_length=1, max_length=32)
    details: dict[str, Any] = Field(default_factory=dict)


class CampaignCreateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    title: str = Field(min_length=1, max_length=120)
    objective: str = Field(default="", max_length=2000)
    workflow_revision_id: str | None = Field(default=None, max_length=128)


class CampaignStatusRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    status: str = Field(min_length=1, max_length=32)


class CampaignCandidateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    label: str = Field(min_length=1, max_length=120)
    structure_artifact_id: str | None = Field(default=None, max_length=128)
    variables: dict[str, Any] = Field(default_factory=dict)
    status: str = Field(default="proposed", max_length=32)


class CampaignDecisionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    action: str = Field(min_length=1, max_length=80)
    rationale: str = Field(min_length=1, max_length=2000)
    candidate_id: str | None = Field(default=None, max_length=128)
    evidence: dict[str, Any] = Field(default_factory=dict)


def _workflow_error(error: Exception, *, missing_status: int = 400) -> HTTPException:
    message = str(error)
    status = missing_status if "does not exist" in message else 400
    return HTTPException(status_code=status, detail=message)


def create_platform_router(
    runtime: WorkflowRuntimeService,
    campaigns: CampaignService,
) -> APIRouter:
    """Create the platform router with explicit service dependencies."""

    router = APIRouter(prefix="/api/v1")

    @router.get("/workflows/templates")
    def list_workflow_templates() -> dict[str, Any]:
        templates = workflow_template_catalog()
        return {
            "schema_version": "catex.workflow-template-catalog.v1",
            "templates": [
                {
                    **template.to_dict(),
                    "validation": validate_workflow(
                        template.nodes,
                        template.edges,
                    ).to_dict(),
                }
                for template in templates
            ],
        }

    @router.get("/projects/{project_id}/workflow/draft")
    def get_workflow_draft(project_id: str) -> dict[str, Any]:
        try:
            return {
                "schema_version": "catex.workflow-draft-response.v1",
                "draft": runtime.get_draft(project_id),
            }
        except (ProjectStoreError, WorkflowRuntimeError) as error:
            raise _workflow_error(error, missing_status=404) from error

    @router.put("/projects/{project_id}/workflow/draft")
    def save_workflow_draft(
        project_id: str,
        request: DraftSaveRequest,
    ) -> dict[str, Any]:
        nodes, edges = request.domain()
        validation = validate_workflow(nodes, edges)
        if not validation.valid:
            raise HTTPException(
                status_code=400,
                detail={
                    "message": "workflow must pass validation before saving",
                    "validation": validation.to_dict(),
                },
            )
        try:
            draft = runtime.save_draft(
                project_id,
                request.graph(),
                expected_draft_sha256=request.expected_draft_sha256,
            )
        except (ProjectStoreError, WorkflowRuntimeError) as error:
            raise _workflow_error(error) from error
        return {"draft": draft, "validation": validation.to_dict()}

    @router.get("/projects/{project_id}/workflow/revisions")
    def list_workflow_revisions(project_id: str) -> dict[str, Any]:
        try:
            records = runtime.list_revisions(project_id)
        except (ProjectStoreError, WorkflowRuntimeError) as error:
            raise _workflow_error(error, missing_status=404) from error
        return {
            "schema_version": "catex.workflow-revision-list.v1",
            "revisions": records,
        }

    @router.post("/projects/{project_id}/workflow/revisions", status_code=201)
    def publish_workflow_revision(
        project_id: str,
        request: RevisionPublishRequest,
    ) -> dict[str, Any]:
        try:
            draft = runtime.get_draft(project_id)
            if draft is None:
                raise WorkflowRuntimeError("save a workflow draft before publishing")
            graph = WorkflowGraphRequest.model_validate(
                {"nodes": draft["nodes"], "edges": draft["edges"]}
            )
            nodes, edges = graph.domain()
            validation = validate_workflow(nodes, edges)
            if not validation.valid:
                raise HTTPException(
                    status_code=400,
                    detail={
                        "message": "workflow draft must pass validation before publishing",
                        "validation": validation.to_dict(),
                    },
                )
            revision = runtime.publish_revision(
                project_id,
                title=request.title,
                note=request.note,
            )
        except HTTPException:
            raise
        except (ProjectStoreError, WorkflowRuntimeError, ValueError) as error:
            raise _workflow_error(error) from error
        return {"revision": revision, "validation": validation.to_dict()}

    @router.get("/projects/{project_id}/workflow/run-graphs")
    def list_run_graphs(project_id: str) -> dict[str, Any]:
        try:
            records = runtime.list_run_graphs(project_id)
        except (ProjectStoreError, WorkflowRuntimeError) as error:
            raise _workflow_error(error, missing_status=404) from error
        return {
            "schema_version": "catex.workflow-run-graph-list.v1",
            "run_graphs": records,
        }

    @router.post("/projects/{project_id}/workflow/run-graphs", status_code=201)
    def create_run_graph(
        project_id: str,
        request: RunGraphCreateRequest,
    ) -> dict[str, Any]:
        try:
            return runtime.create_run_graph(
                project_id,
                revision_id=request.revision_id,
                label=request.label,
                bindings=request.bindings,
            )
        except (ProjectStoreError, WorkflowRuntimeError) as error:
            raise _workflow_error(error, missing_status=404) from error

    @router.get("/projects/{project_id}/workflow/run-graphs/{run_graph_id}/attempts")
    def list_node_attempts(
        project_id: str,
        run_graph_id: str,
        node_id: str | None = None,
    ) -> dict[str, Any]:
        try:
            records = runtime.list_attempts(
                project_id,
                run_graph_id=run_graph_id,
                node_id=node_id,
            )
        except (ProjectStoreError, WorkflowRuntimeError) as error:
            raise _workflow_error(error, missing_status=404) from error
        return {
            "schema_version": "catex.workflow-node-attempt-list.v1",
            "attempts": records,
        }

    @router.post(
        "/projects/{project_id}/workflow/run-graphs/{run_graph_id}/attempts",
        status_code=201,
    )
    def record_node_attempt(
        project_id: str,
        run_graph_id: str,
        request: NodeAttemptRequest,
    ) -> dict[str, Any]:
        try:
            return runtime.record_attempt(
                project_id,
                run_graph_id=run_graph_id,
                node_id=request.node_id,
                status=request.status,
                details=request.details,
            )
        except (ProjectStoreError, WorkflowRuntimeError) as error:
            raise _workflow_error(error, missing_status=404) from error

    @router.get("/projects/{project_id}/workflow/run-graphs/{run_graph_id}/execution-plan")
    def get_execution_plan(
        project_id: str,
        run_graph_id: str,
    ) -> dict[str, Any]:
        try:
            run_graph = runtime.get_run_graph(project_id, run_graph_id)
            plan = compile_workflow_execution_plan(run_graph["workflow"])
        except (
            ProjectStoreError,
            WorkflowRuntimeError,
            WorkflowExecutionPlanError,
        ) as error:
            raise _workflow_error(error, missing_status=404) from error
        return {
            "run_graph_id": run_graph_id,
            "revision_id": run_graph["revision_id"],
            "plan": plan,
        }

    @router.get("/projects/{project_id}/campaigns")
    def list_campaigns(project_id: str) -> dict[str, Any]:
        try:
            records = campaigns.list(project_id)
        except (ProjectStoreError, CampaignError) as error:
            raise _workflow_error(error, missing_status=404) from error
        return {"schema_version": "catex.campaign-list.v1", "campaigns": records}

    @router.post("/projects/{project_id}/campaigns", status_code=201)
    def create_campaign(
        project_id: str,
        request: CampaignCreateRequest,
    ) -> dict[str, Any]:
        try:
            return campaigns.create(project_id, **request.model_dump())
        except (ProjectStoreError, CampaignError) as error:
            raise _workflow_error(error) from error

    @router.get("/projects/{project_id}/campaigns/{campaign_id}")
    def get_campaign(project_id: str, campaign_id: str) -> dict[str, Any]:
        try:
            campaign = campaigns.get(project_id, campaign_id)
            candidates = campaigns.list_candidates(project_id, campaign_id)
            decisions = campaigns.list_decisions(project_id, campaign_id)
        except (ProjectStoreError, CampaignError) as error:
            raise _workflow_error(error, missing_status=404) from error
        return {
            "schema_version": "catex.campaign-detail.v1",
            "campaign": campaign,
            "candidates": candidates,
            "decisions": decisions,
        }

    @router.patch("/projects/{project_id}/campaigns/{campaign_id}")
    def update_campaign_status(
        project_id: str,
        campaign_id: str,
        request: CampaignStatusRequest,
    ) -> dict[str, Any]:
        try:
            return campaigns.set_status(
                project_id,
                campaign_id,
                status=request.status,
            )
        except (ProjectStoreError, CampaignError) as error:
            raise _workflow_error(error, missing_status=404) from error

    @router.post(
        "/projects/{project_id}/campaigns/{campaign_id}/candidates",
        status_code=201,
    )
    def add_campaign_candidate(
        project_id: str,
        campaign_id: str,
        request: CampaignCandidateRequest,
    ) -> dict[str, Any]:
        try:
            return campaigns.add_candidate(
                project_id,
                campaign_id,
                **request.model_dump(),
            )
        except (ProjectStoreError, CampaignError) as error:
            raise _workflow_error(error, missing_status=404) from error

    @router.post(
        "/projects/{project_id}/campaigns/{campaign_id}/decisions",
        status_code=201,
    )
    def record_campaign_decision(
        project_id: str,
        campaign_id: str,
        request: CampaignDecisionRequest,
    ) -> dict[str, Any]:
        try:
            return campaigns.record_decision(
                project_id,
                campaign_id,
                **request.model_dump(),
            )
        except (ProjectStoreError, CampaignError) as error:
            raise _workflow_error(error, missing_status=404) from error

    return router
