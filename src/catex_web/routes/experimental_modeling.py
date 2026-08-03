"""Project-scoped experiment-informed modeling API routes."""

from __future__ import annotations

from typing import Annotated, Any, Literal

from fastapi import APIRouter, File, HTTPException, UploadFile
from pydantic import BaseModel, ConfigDict, Field, SecretStr

from catex_app.experimental_modeling import (
    MAX_EVIDENCE_UPLOAD_BYTES,
    ExperimentalModelingError,
    ExperimentalModelingService,
)
from catex_app.projects import ProjectStoreError


class ExperimentalEvidenceInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    evidence_id: str = Field(pattern=r"^[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}$")
    kind: Literal[
        "xrd",
        "gixrd",
        "icp",
        "eds",
        "xps",
        "raman",
        "sem",
        "tem",
        "synthesis",
        "electrochemistry",
        "literature",
        "other",
    ]
    # Accepted only for backward compatibility with stored v1 projects.  The
    # workbench no longer asks for or uses sample lifecycle labels.
    sample_state: (
        Literal[
            "as_prepared",
            "activated",
            "operando_approximation",
            "post_mortem",
            "unspecified",
        ]
        | None
    ) = Field(default=None, exclude=True)
    role: Literal["hard", "soft", "context"] = "context"
    metadata: dict[str, Any] = Field(default_factory=dict)
    evidence_artifact_id: str | None = Field(
        default=None,
        pattern=r"^evidence-[0-9a-f]{20}$",
    )
    note: str = Field(default="", max_length=1000)


class CompositionConstraintInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    element: str = Field(min_length=1, max_length=3)
    minimum_atomic_fraction: float = Field(ge=0, le=1)
    maximum_atomic_fraction: float = Field(ge=0, le=1)
    scope: Literal["bulk", "surface", "local", "unspecified"] = "bulk"
    basis: Literal[
        "total_atomic_fraction",
        "metal_normalized_atomic_fraction",
        "weight_fraction",
    ] = "total_atomic_fraction"
    evidence_ids: list[str] = Field(default_factory=list, max_length=100)


class LocalEnvironmentConstraintInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    element: str = Field(min_length=1, max_length=3)
    neighbor_element: str = Field(min_length=1, max_length=3)
    minimum_site_fraction: float = Field(ge=0, le=1)
    maximum_site_fraction: float = Field(ge=0, le=1)
    cutoff_angstrom: float = Field(default=2.6, ge=0.5, le=6.0)
    scope: Literal["surface", "local"] = "surface"
    evidence_ids: list[str] = Field(default_factory=list, max_length=100)


class LatticeSpacingConstraintInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    d_spacing_angstrom: float = Field(gt=0, le=100)
    tolerance_angstrom: float = Field(gt=0, le=100)
    evidence_ids: list[str] = Field(default_factory=list, max_length=100)


class ExperimentalSpecRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: Literal["catex.experiment-spec.v1"] = "catex.experiment-spec.v1"
    sample_id: str = Field(pattern=r"^[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}$")
    # Backward-compatible input only; omitted from normalized new records.
    target_state: (
        Literal[
            "as_prepared",
            "activated",
            "operando_approximation",
            "post_mortem",
            "unspecified",
        ]
        | None
    ) = Field(default=None, exclude=True)
    material_pack: str = Field(
        default="generic",
        pattern=r"^[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}$",
    )
    allowed_elements: list[str] = Field(default_factory=list, max_length=118)
    excluded_elements: list[str] = Field(default_factory=list, max_length=118)
    composition_constraints: list[CompositionConstraintInput] = Field(
        default_factory=list,
        max_length=118,
    )
    local_environment_constraints: list[LocalEnvironmentConstraintInput] = Field(
        default_factory=list,
        max_length=200,
    )
    lattice_spacing_constraints: list[LatticeSpacingConstraintInput] = Field(
        default_factory=list,
        max_length=200,
    )
    evidence: list[ExperimentalEvidenceInput] = Field(default_factory=list, max_length=200)


class EvidenceExtractionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    evidence_id: str = Field(pattern=r"^[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}$")
    evidence_artifact_id: str | None = Field(
        default=None,
        pattern=r"^evidence-[0-9a-f]{20}$",
    )
    kind: Literal["xrd", "gixrd", "icp", "eds", "xps", "tem"]
    conclusion: str = Field(default="", max_length=1000)
    instrument_info: str = Field(default="", max_length=1000)


class OptimadeSearchRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    base_url: str = Field(min_length=8, max_length=1000)
    provider_id: str = Field(
        default="optimade",
        pattern=r"^[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}$",
    )
    required_elements: list[str] = Field(min_length=1, max_length=20)
    maximum_results: int = Field(default=50, ge=1, le=1000)
    maximum_pages: int = Field(default=5, ge=1, le=20)
    license: str = Field(default="", max_length=255)
    citation: str = Field(default="", max_length=1000)


class MaterialsProjectSearchRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    required_elements: list[str] = Field(min_length=1, max_length=20)
    maximum_results: int = Field(default=50, ge=1, le=1000)


class CredentialSaveRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    secret: SecretStr


class XRDSettingsRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    wavelength: str = Field(default="CuKa", min_length=1, max_length=32)
    shift_values_degrees: list[float] = Field(
        default_factory=lambda: [-0.2, -0.1, 0.0, 0.1, 0.2],
        min_length=1,
        max_length=101,
    )
    fwhm_values_degrees: list[float] = Field(
        default_factory=lambda: [0.1, 0.2, 0.4],
        min_length=1,
        max_length=50,
    )
    baseline_window_points: int = Field(default=0, ge=0, le=100_000)
    peak_relative_threshold: float = Field(default=0.05, gt=0, lt=1)
    peak_tolerance_degrees: float = Field(default=0.25, gt=0, le=10)
    single_phase_pool: int = Field(default=8, ge=1, le=50)
    maximum_phases: int = Field(default=3, ge=1, le=3)
    complexity_penalty: float = Field(default=0.02, ge=0, lt=1)
    minimum_supported_score: float = Field(default=0.55, ge=0, le=1)
    ambiguity_margin: float = Field(default=0.03, ge=0, le=1)


class InferenceRunRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    planner_kind: Literal["rule", "gpt"] = "rule"
    catalog_ids: list[str] = Field(default_factory=list, max_length=100)
    maximum_representatives: int = Field(default=10, ge=1, le=50)
    xrd_settings: XRDSettingsRequest = Field(default_factory=XRDSettingsRequest)


class CandidateReviewRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    approved_candidate_ids: list[str] = Field(min_length=1, max_length=50)
    reviewer: str = Field(min_length=1, max_length=100)
    note: str = Field(min_length=1, max_length=1000)


class CandidateMaterializationRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    candidate_ids: list[str] = Field(min_length=1, max_length=50)
    confirm_report_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    approved_write: bool


def _api_error(error: Exception, *, missing_status: int = 400) -> HTTPException:
    message = str(error)
    missing = "does not exist" in message or "unavailable" in message
    return HTTPException(status_code=missing_status if missing else 400, detail=message)


def create_experimental_modeling_router(
    service: ExperimentalModelingService,
) -> APIRouter:
    """Create routes with one explicit project-scoped service dependency."""

    router = APIRouter(prefix="/api/v1")

    @router.get("/experimental-modeling/capabilities")
    def capabilities() -> dict[str, Any]:
        return service.capabilities()

    @router.put("/experimental-modeling/credentials/{provider}")
    def save_credential(
        provider: Literal["materials_project", "openai"],
        request: CredentialSaveRequest,
    ) -> dict[str, Any]:
        try:
            return service.save_credential(provider, request.secret.get_secret_value())
        except ExperimentalModelingError as error:
            raise _api_error(error) from error

    @router.delete("/experimental-modeling/credentials/{provider}")
    def delete_credential(
        provider: Literal["materials_project", "openai"],
    ) -> dict[str, Any]:
        try:
            return service.delete_credential(provider)
        except ExperimentalModelingError as error:
            raise _api_error(error) from error

    @router.get("/projects/{project_id}/experimental-modeling/evidence")
    def list_evidence(project_id: str) -> dict[str, Any]:
        try:
            records = service.list_evidence(project_id)
        except (ProjectStoreError, ExperimentalModelingError) as error:
            raise _api_error(error, missing_status=404) from error
        return {
            "schema_version": "catex.web-experimental-evidence-list.v1",
            "evidence": records,
        }

    @router.post(
        "/projects/{project_id}/experimental-modeling/evidence",
        status_code=201,
    )
    async def add_evidence(
        project_id: str,
        file: Annotated[UploadFile, File(description="Bounded characterization artifact")],
    ) -> dict[str, Any]:
        content = await file.read(MAX_EVIDENCE_UPLOAD_BYTES + 1)
        await file.close()
        try:
            return service.add_evidence(project_id, file.filename or "", content)
        except (ProjectStoreError, ExperimentalModelingError) as error:
            raise _api_error(error, missing_status=404) from error

    @router.post(
        "/projects/{project_id}/experimental-modeling/evidence/{evidence_artifact_id}/extract"
    )
    def extract_evidence(
        project_id: str,
        evidence_artifact_id: str,
        request: EvidenceExtractionRequest,
    ) -> dict[str, Any]:
        try:
            return service.extract_evidence(
                project_id,
                **{
                    **request.model_dump(exclude={"evidence_artifact_id"}),
                    "evidence_artifact_id": evidence_artifact_id,
                },
            )
        except (ProjectStoreError, ExperimentalModelingError) as error:
            raise _api_error(error, missing_status=404) from error

    @router.post("/projects/{project_id}/experimental-modeling/evidence/extract")
    @router.post("/projects/{project_id}/experimental-modeling/evidence-extraction")
    def extract_evidence_without_required_file(
        project_id: str,
        request: EvidenceExtractionRequest,
    ) -> dict[str, Any]:
        try:
            return service.extract_evidence(project_id, **request.model_dump())
        except (ProjectStoreError, ExperimentalModelingError) as error:
            raise _api_error(error, missing_status=404) from error

    @router.get("/projects/{project_id}/experimental-modeling/spec")
    def get_spec(project_id: str) -> dict[str, Any]:
        try:
            revision = service.current_spec(project_id)
        except (ProjectStoreError, ExperimentalModelingError) as error:
            raise _api_error(error, missing_status=404) from error
        return {
            "schema_version": "catex.web-experimental-spec-response.v1",
            "revision": revision,
        }

    @router.put("/projects/{project_id}/experimental-modeling/spec")
    def save_spec(
        project_id: str,
        request: ExperimentalSpecRequest,
    ) -> dict[str, Any]:
        try:
            return service.save_spec(project_id, request.model_dump())
        except (ProjectStoreError, ExperimentalModelingError) as error:
            raise _api_error(error, missing_status=404) from error

    @router.get("/projects/{project_id}/experimental-modeling/catalogs")
    def list_catalogs(project_id: str) -> dict[str, Any]:
        try:
            catalogs = service.list_catalogs(project_id)
        except (ProjectStoreError, ExperimentalModelingError) as error:
            raise _api_error(error, missing_status=404) from error
        return {
            "schema_version": "catex.web-structure-catalog-list.v1",
            "catalogs": catalogs,
        }

    @router.post(
        "/projects/{project_id}/experimental-modeling/providers/optimade/search",
        status_code=201,
    )
    def fetch_optimade_catalog(
        project_id: str,
        request: OptimadeSearchRequest,
    ) -> dict[str, Any]:
        try:
            return service.fetch_optimade(project_id, **request.model_dump())
        except (ProjectStoreError, ExperimentalModelingError) as error:
            raise _api_error(error, missing_status=404) from error

    @router.post(
        "/projects/{project_id}/experimental-modeling/providers/materials-project/search",
        status_code=201,
    )
    def fetch_materials_project_catalog(
        project_id: str,
        request: MaterialsProjectSearchRequest,
    ) -> dict[str, Any]:
        try:
            return service.fetch_materials_project(project_id, **request.model_dump())
        except (ProjectStoreError, ExperimentalModelingError) as error:
            raise _api_error(error, missing_status=404) from error

    @router.get("/projects/{project_id}/experimental-modeling/runs")
    def list_runs(project_id: str) -> dict[str, Any]:
        try:
            runs = service.list_runs(project_id)
        except (ProjectStoreError, ExperimentalModelingError) as error:
            raise _api_error(error, missing_status=404) from error
        return {
            "schema_version": "catex.web-experimental-modeling-run-list.v1",
            "runs": runs,
        }

    @router.post(
        "/projects/{project_id}/experimental-modeling/runs",
        status_code=201,
    )
    def create_run(
        project_id: str,
        request: InferenceRunRequest,
    ) -> dict[str, Any]:
        payload = request.model_dump()
        try:
            return service.infer(project_id, **payload)
        except (ProjectStoreError, ExperimentalModelingError) as error:
            raise _api_error(error, missing_status=404) from error

    @router.get("/projects/{project_id}/experimental-modeling/runs/{run_id}")
    def get_run(project_id: str, run_id: str) -> dict[str, Any]:
        try:
            return service.get_run(project_id, run_id)
        except (ProjectStoreError, ExperimentalModelingError) as error:
            raise _api_error(error, missing_status=404) from error

    @router.get("/projects/{project_id}/experimental-modeling/runs/{run_id}/reviews")
    def list_reviews(project_id: str, run_id: str) -> dict[str, Any]:
        try:
            reviews = service.list_reviews(project_id, run_id)
        except (ProjectStoreError, ExperimentalModelingError) as error:
            raise _api_error(error, missing_status=404) from error
        return {
            "schema_version": "catex.web-experimental-model-review-list.v1",
            "reviews": reviews,
        }

    @router.post(
        "/projects/{project_id}/experimental-modeling/runs/{run_id}/reviews",
        status_code=201,
    )
    def review_candidates(
        project_id: str,
        run_id: str,
        request: CandidateReviewRequest,
    ) -> dict[str, Any]:
        try:
            return service.record_review(
                project_id,
                run_id,
                **request.model_dump(),
            )
        except (ProjectStoreError, ExperimentalModelingError) as error:
            raise _api_error(error, missing_status=404) from error

    @router.post(
        "/projects/{project_id}/experimental-modeling/runs/{run_id}/materializations",
        status_code=201,
    )
    def materialize_candidates(
        project_id: str,
        run_id: str,
        request: CandidateMaterializationRequest,
    ) -> dict[str, Any]:
        try:
            return service.materialize(
                project_id,
                run_id,
                **request.model_dump(),
            )
        except (ProjectStoreError, ExperimentalModelingError) as error:
            raise _api_error(error, missing_status=404) from error

    return router
