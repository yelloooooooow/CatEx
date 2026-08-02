"""Rule-based and optional GPT planners for bounded candidate recipes."""

from __future__ import annotations

import json
import os
import urllib.error
import urllib.request
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any, Protocol

from catex.experimental.models import (
    CandidateOperation,
    CandidateOperationKind,
    CandidateRecipe,
    EvidenceKind,
    ExperimentSpec,
    StructuralHypothesis,
)
from catex.experimental.providers import ProviderRegistry
from catex.experimental.xrd import PhaseSearchReport
from catex.models import Diagnostic, Severity


@dataclass(frozen=True, slots=True)
class CandidatePlan:
    """Validated hypotheses and recipes emitted by one planner."""

    hypotheses: tuple[StructuralHypothesis, ...]
    recipes: tuple[CandidateRecipe, ...]
    diagnostics: tuple[Diagnostic, ...]
    planner: str
    external_api_called: bool = False
    schema_version: str = "catex.candidate-plan.v1"

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "planner": self.planner,
            "external_api_called": self.external_api_called,
            "hypotheses": [item.to_dict() for item in self.hypotheses],
            "recipes": [item.to_dict() for item in self.recipes],
            "diagnostics": [item.to_dict() for item in self.diagnostics],
        }


class CandidatePlanner(Protocol):
    """Planner boundary consumed by the deterministic inference workflow."""

    @property
    def planner_id(self) -> str: ...

    def plan(
        self,
        spec: ExperimentSpec,
        registry: ProviderRegistry,
        phase_search: PhaseSearchReport | None,
    ) -> CandidatePlan: ...


@dataclass(frozen=True, slots=True)
class RulePlannerSettings:
    """Bounded recipe expansion limits for the deterministic baseline."""

    maximum_parent_phases: int = 4
    include_bulk_models: bool = True
    surface_miller_indices: tuple[tuple[int, int, int], ...] = (
        (1, 0, 0),
        (1, 1, 0),
        (1, 1, 1),
    )
    minimum_slab_angstrom: float = 8.0
    minimum_vacuum_angstrom: float = 12.0
    maximum_terminations_per_surface: int = 4
    maximum_recipes: int = 20

    def __post_init__(self) -> None:
        if not 1 <= self.maximum_parent_phases <= 20:
            raise ValueError("maximum_parent_phases must be between 1 and 20")
        if not self.surface_miller_indices:
            raise ValueError("surface_miller_indices must not be empty")
        if any(index == (0, 0, 0) or len(index) != 3 for index in self.surface_miller_indices):
            raise ValueError("surface Miller indices must contain three integers and be nonzero")
        if self.minimum_slab_angstrom <= 0 or self.minimum_vacuum_angstrom <= 0:
            raise ValueError("slab and vacuum dimensions must be positive")
        if not 1 <= self.maximum_terminations_per_surface <= 32:
            raise ValueError("maximum_terminations_per_surface must be between 1 and 32")
        if not 1 <= self.maximum_recipes <= 100:
            raise ValueError("maximum_recipes must be between 1 and 100")


def _relevant_evidence_ids(spec: ExperimentSpec) -> tuple[str, ...]:
    primary = {
        EvidenceKind.XRD,
        EvidenceKind.GIXRD,
        EvidenceKind.ICP,
        EvidenceKind.EDS,
        EvidenceKind.XPS,
        EvidenceKind.TEM,
        EvidenceKind.SYNTHESIS,
    }
    return tuple(item.evidence_id for item in spec.evidence if item.kind in primary)


def _metadata_mentions_surface_oxygen(spec: ExperimentSpec) -> bool:
    for evidence in spec.evidence:
        if evidence.kind is not EvidenceKind.XPS:
            continue
        text = json.dumps(dict(evidence.metadata), ensure_ascii=False).lower()
        if any(token in text for token in ('"o"', "oxide", "oxidized", "hydrox")):
            return True
    return False


def _metadata_mentions_disorder(spec: ExperimentSpec) -> bool:
    for evidence in spec.evidence:
        if evidence.kind not in {EvidenceKind.XRD, EvidenceKind.GIXRD, EvidenceKind.TEM}:
            continue
        text = json.dumps(dict(evidence.metadata), ensure_ascii=False).lower()
        if any(token in text for token in ("amorphous", "poorly_crystalline", "broad_halo")):
            return True
    return False


class RuleCandidatePlanner:
    """Deterministic database-first baseline with no external API calls."""

    planner_id = "rule"

    def __init__(self, settings: RulePlannerSettings | None = None) -> None:
        self.settings = settings or RulePlannerSettings()

    def _parent_keys(
        self,
        spec: ExperimentSpec,
        registry: ProviderRegistry,
        phase_search: PhaseSearchReport | None,
    ) -> tuple[str, ...]:
        if phase_search is not None and phase_search.single_phase_matches:
            support = phase_search.ranked_reference_support()
            return tuple(
                key
                for key, _ in sorted(
                    support.items(),
                    key=lambda item: (-item[1], item[0]),
                )[: self.settings.maximum_parent_phases]
            )
        references = registry.search(
            allowed_elements=spec.allowed_elements,
            excluded_elements=spec.excluded_elements,
        )
        return tuple(item.key for item in references[: self.settings.maximum_parent_phases])

    def plan(
        self,
        spec: ExperimentSpec,
        registry: ProviderRegistry,
        phase_search: PhaseSearchReport | None,
    ) -> CandidatePlan:
        evidence_ids = _relevant_evidence_ids(spec)
        parent_keys = self._parent_keys(spec, registry, phase_search)
        hypotheses: list[StructuralHypothesis] = []
        recipes: list[CandidateRecipe] = []
        diagnostics: list[Diagnostic] = []
        electrocatalyst = "electrocatalyst" in spec.material_pack.lower()
        for index, parent_key in enumerate(parent_keys):
            reference = registry.get_reference(parent_key)
            hypothesis_id = f"phase-family-{index + 1}"
            hypotheses.append(
                StructuralHypothesis(
                    hypothesis_id=hypothesis_id,
                    summary=(
                        f"{reference.formula} is a parent crystalline phase family "
                        "compatible with the current catalog and evidence."
                    ),
                    target_state=spec.target_state,
                    evidence_ids=evidence_ids,
                    parent_reference_keys=(parent_key,),
                    assumptions=(
                        "Database coordinates represent an ideal parent phase, "
                        "not the exact sample.",
                    ),
                    generated_atomistic_candidate=True,
                )
            )
            if self.settings.include_bulk_models:
                recipes.append(
                    CandidateRecipe(
                        recipe_id=f"bulk-{index + 1}",
                        parent_reference_key=parent_key,
                        hypothesis_id=hypothesis_id,
                        operations=(CandidateOperation(CandidateOperationKind.IDENTITY),),
                        evidence_ids=evidence_ids,
                        rationale="Retain the retrieved parent phase as a bulk reference model.",
                        assumptions=("The database unit cell is an idealized bulk reference.",),
                    )
                )
            if electrocatalyst:
                structure = registry.get_structure(parent_key)
                if len(structure) > 100:
                    diagnostics.append(
                        Diagnostic(
                            "RULE_PLANNER_SURFACE_SKIPPED_LARGE_PARENT",
                            Severity.WARNING,
                            "Surface expansion was skipped for a large parent unit cell.",
                            {"reference_key": parent_key, "num_sites": len(structure)},
                        )
                    )
                    continue
                for miller in self.settings.surface_miller_indices:
                    recipes.append(
                        CandidateRecipe(
                            recipe_id=(f"surface-{index + 1}-{miller[0]}{miller[1]}{miller[2]}"),
                            parent_reference_key=parent_key,
                            hypothesis_id=hypothesis_id,
                            operations=(
                                CandidateOperation(
                                    CandidateOperationKind.SLAB,
                                    {
                                        "miller_index": list(miller),
                                        "minimum_slab_angstrom": (
                                            self.settings.minimum_slab_angstrom
                                        ),
                                        "minimum_vacuum_angstrom": (
                                            self.settings.minimum_vacuum_angstrom
                                        ),
                                        "maximum_candidates": (
                                            self.settings.maximum_terminations_per_surface
                                        ),
                                    },
                                ),
                            ),
                            evidence_ids=evidence_ids,
                            rationale=(
                                "Generate low-index surface terminations for downstream "
                                "electrocatalysis calculations."
                            ),
                            assumptions=(
                                "Powder XRD supports the parent bulk phase, not this termination.",
                                "Surface reconstruction and adsorbate coverage remain unresolved.",
                            ),
                        )
                    )

        if _metadata_mentions_surface_oxygen(spec):
            hypotheses.append(
                StructuralHypothesis(
                    hypothesis_id="surface-oxygen-unresolved",
                    summary=(
                        "Surface oxygenated or hydroxylated motifs are plausible, but ordinary "
                        "XPS does not define unique atomic coordinates."
                    ),
                    target_state=spec.target_state,
                    evidence_ids=tuple(
                        item.evidence_id for item in spec.evidence if item.kind is EvidenceKind.XPS
                    ),
                    assumptions=(
                        "A dedicated oxide/hydroxide parent structure or interface "
                        "model is needed.",
                    ),
                    generated_atomistic_candidate=False,
                )
            )
        if _metadata_mentions_disorder(spec):
            hypotheses.append(
                StructuralHypothesis(
                    hypothesis_id="disordered-motif-ensemble-unresolved",
                    summary=(
                        "A disordered or poorly crystalline motif ensemble is plausible; "
                        "the crystalline catalog does not uniquely represent it."
                    ),
                    target_state=spec.target_state,
                    evidence_ids=tuple(
                        item.evidence_id
                        for item in spec.evidence
                        if item.kind in {EvidenceKind.XRD, EvidenceKind.GIXRD, EvidenceKind.TEM}
                    ),
                    assumptions=(
                        "PDF/RMC, atomistic melt-quench, or motif-specific constraints are absent.",
                    ),
                    generated_atomistic_candidate=False,
                )
            )
        if not parent_keys:
            diagnostics.append(
                Diagnostic(
                    "RULE_PLANNER_NO_PARENT_PHASE",
                    Severity.ERROR,
                    "No parent structure is compatible with the declared chemical system.",
                )
            )
        if len(recipes) > self.settings.maximum_recipes:
            recipes = recipes[: self.settings.maximum_recipes]
            diagnostics.append(
                Diagnostic(
                    "RULE_PLANNER_RECIPE_LIMIT_REACHED",
                    Severity.INFO,
                    "Candidate recipes were truncated at the explicit planner limit.",
                    {"maximum_recipes": self.settings.maximum_recipes},
                )
            )
        return CandidatePlan(
            hypotheses=tuple(hypotheses),
            recipes=tuple(recipes),
            diagnostics=tuple(diagnostics),
            planner=self.planner_id,
        )


class JSONPlannerTransport(Protocol):
    """Transport boundary for a model that returns one schema-constrained JSON object."""

    def complete_json(
        self,
        *,
        system_prompt: str,
        user_payload: Mapping[str, Any],
        output_schema: Mapping[str, Any],
    ) -> Mapping[str, Any]: ...


class OpenAIResponsesTransport:
    """Minimal optional Responses API transport with no SDK or credential persistence."""

    def __init__(
        self,
        *,
        model: str,
        api_key: str | None = None,
        api_key_environment_variable: str = "OPENAI_API_KEY",
        endpoint: str = "https://api.openai.com/v1/responses",
        timeout_seconds: float = 60.0,
    ) -> None:
        if not model.strip():
            raise ValueError("an explicit OpenAI model is required")
        if endpoint != "https://api.openai.com/v1/responses":
            raise ValueError("custom OpenAI endpoints are not accepted by this transport")
        if not 1 <= timeout_seconds <= 300:
            raise ValueError("timeout_seconds must be between 1 and 300")
        self.model = model.strip()
        self.api_key = api_key
        self.api_key_environment_variable = api_key_environment_variable
        self.endpoint = endpoint
        self.timeout_seconds = timeout_seconds

    def _resolved_api_key(self) -> str:
        api_key = self.api_key or os.environ.get(self.api_key_environment_variable)
        if not api_key:
            raise ValueError(
                f"{self.api_key_environment_variable} or a system credential is required at runtime"
            )
        return api_key

    def verify_api_key(self) -> int:
        """Validate the credential with the documented read-only models endpoint."""

        request = urllib.request.Request(
            "https://api.openai.com/v1/models",
            headers={"Authorization": f"Bearer {self._resolved_api_key()}"},
            method="GET",
        )
        try:
            with urllib.request.urlopen(request, timeout=self.timeout_seconds) as response:
                payload = json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            raise ValueError(f"OpenAI credential verification returned HTTP {exc.code}") from exc
        except (urllib.error.URLError, UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise ValueError("OpenAI credential verification failed") from exc
        if not isinstance(payload, Mapping):
            raise ValueError("OpenAI credential verification returned an invalid response")
        models = payload.get("data")
        if not isinstance(models, Sequence) or isinstance(models, str | bytes):
            raise ValueError("OpenAI credential verification returned an invalid response")
        return len(models)

    @staticmethod
    def _output_text(response: Mapping[str, Any]) -> str:
        direct = response.get("output_text")
        if isinstance(direct, str) and direct.strip():
            return direct
        for item in response.get("output", []):
            if not isinstance(item, Mapping):
                continue
            for content in item.get("content", []):
                if not isinstance(content, Mapping):
                    continue
                text = content.get("text")
                if isinstance(text, str) and text.strip():
                    return text
        raise ValueError("OpenAI response did not contain output text")

    def complete_json(
        self,
        *,
        system_prompt: str,
        user_payload: Mapping[str, Any],
        output_schema: Mapping[str, Any],
    ) -> Mapping[str, Any]:
        api_key = self._resolved_api_key()
        request_payload = {
            "model": self.model,
            "store": False,
            "input": [
                {
                    "role": "system",
                    "content": [{"type": "input_text", "text": system_prompt}],
                },
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "input_text",
                            "text": json.dumps(
                                user_payload,
                                allow_nan=False,
                                ensure_ascii=False,
                                sort_keys=True,
                            ),
                        }
                    ],
                },
            ],
            "text": {
                "format": {
                    "type": "json_schema",
                    "name": "candidate_plan",
                    "strict": True,
                    "schema": output_schema,
                }
            },
        }
        request = urllib.request.Request(
            self.endpoint,
            data=json.dumps(request_payload).encode("utf-8"),
            headers={
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json",
            },
            method="POST",
        )
        try:
            with urllib.request.urlopen(
                request,
                timeout=self.timeout_seconds,
            ) as response:
                payload = json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            raise ValueError(f"OpenAI API returned HTTP {exc.code}") from exc
        except urllib.error.URLError as exc:
            raise ValueError("OpenAI API request failed") from exc
        if not isinstance(payload, Mapping):
            raise ValueError("OpenAI API returned a non-object response")
        parsed = json.loads(self._output_text(payload))
        if not isinstance(parsed, Mapping):
            raise ValueError("OpenAI structured output must be a JSON object")
        return parsed


def _planner_schema() -> dict[str, Any]:
    operation_kinds = [item.value for item in CandidateOperationKind]
    return {
        "type": "object",
        "additionalProperties": False,
        "required": ["hypotheses", "recipes"],
        "properties": {
            "hypotheses": {
                "type": "array",
                "maxItems": 20,
                "items": {
                    "type": "object",
                    "additionalProperties": False,
                    "required": [
                        "hypothesis_id",
                        "summary",
                        "evidence_ids",
                        "parent_reference_keys",
                        "assumptions",
                        "generated_atomistic_candidate",
                    ],
                    "properties": {
                        "hypothesis_id": {"type": "string"},
                        "summary": {"type": "string"},
                        "evidence_ids": {"type": "array", "items": {"type": "string"}},
                        "parent_reference_keys": {
                            "type": "array",
                            "items": {"type": "string"},
                        },
                        "assumptions": {"type": "array", "items": {"type": "string"}},
                        "generated_atomistic_candidate": {"type": "boolean"},
                    },
                },
            },
            "recipes": {
                "type": "array",
                "maxItems": 40,
                "items": {
                    "type": "object",
                    "additionalProperties": False,
                    "required": [
                        "recipe_id",
                        "parent_reference_key",
                        "hypothesis_id",
                        "operations",
                        "evidence_ids",
                        "rationale",
                        "assumptions",
                        "random_seed",
                    ],
                    "properties": {
                        "recipe_id": {"type": "string"},
                        "parent_reference_key": {"type": "string"},
                        "hypothesis_id": {"type": "string"},
                        "operations": {
                            "type": "array",
                            "minItems": 1,
                            "maxItems": 8,
                            "items": {
                                "type": "object",
                                "additionalProperties": False,
                                "required": ["kind", "parameters_json"],
                                "properties": {
                                    "kind": {"type": "string", "enum": operation_kinds},
                                    "parameters_json": {
                                        "type": "string",
                                        "maxLength": 4000,
                                    },
                                },
                            },
                        },
                        "evidence_ids": {"type": "array", "items": {"type": "string"}},
                        "rationale": {"type": "string"},
                        "assumptions": {"type": "array", "items": {"type": "string"}},
                        "random_seed": {"type": "integer"},
                    },
                },
            },
        },
    }


class GPTCandidatePlanner:
    """Schema-constrained planner; local validators remain authoritative."""

    planner_id = "gpt"

    def __init__(self, transport: JSONPlannerTransport, *, maximum_recipes: int = 40) -> None:
        if not 1 <= maximum_recipes <= 100:
            raise ValueError("maximum_recipes must be between 1 and 100")
        self.transport = transport
        self.maximum_recipes = maximum_recipes

    def plan(
        self,
        spec: ExperimentSpec,
        registry: ProviderRegistry,
        phase_search: PhaseSearchReport | None,
    ) -> CandidatePlan:
        references = {item.key: item for item in registry.references()}
        evidence_ids = {item.evidence_id for item in spec.evidence}
        payload = {
            "experiment": spec.to_dict(),
            "available_parent_structures": [item.to_dict() for item in references.values()],
            "phase_search": phase_search.to_dict() if phase_search is not None else None,
            "allowed_operations": [item.value for item in CandidateOperationKind],
        }
        result = self.transport.complete_json(
            system_prompt=(
                "Propose auditable atomistic model hypotheses and bounded recipes. "
                "Use only listed parent_reference_keys, evidence_ids, and allowed operations. "
                "Do not generate code, coordinates, citations, or claims of a unique "
                "real structure. "
                "Encode each allowlisted operation's parameter object in parameters_json. "
                "XRD supports parent bulk phases, not a particular surface termination. "
                "If evidence is insufficient, emit a hypothesis without a generated candidate."
            ),
            user_payload=payload,
            output_schema=_planner_schema(),
        )
        raw_hypotheses = result.get("hypotheses")
        raw_recipes = result.get("recipes")
        if not isinstance(raw_hypotheses, Sequence) or isinstance(raw_hypotheses, str | bytes):
            raise ValueError("GPT planner hypotheses must be an array")
        if not isinstance(raw_recipes, Sequence) or isinstance(raw_recipes, str | bytes):
            raise ValueError("GPT planner recipes must be an array")
        hypotheses: list[StructuralHypothesis] = []
        for raw in raw_hypotheses:
            if not isinstance(raw, Mapping):
                raise ValueError("GPT planner hypothesis must be an object")
            parent_keys = tuple(str(item) for item in raw["parent_reference_keys"])
            if any(item not in references for item in parent_keys):
                raise ValueError("GPT planner referenced an unknown parent structure")
            linked_evidence = tuple(str(item) for item in raw["evidence_ids"])
            if any(item not in evidence_ids for item in linked_evidence):
                raise ValueError("GPT planner referenced unknown evidence")
            hypotheses.append(
                StructuralHypothesis(
                    hypothesis_id=str(raw["hypothesis_id"]),
                    summary=str(raw["summary"]),
                    target_state=spec.target_state,
                    evidence_ids=linked_evidence,
                    parent_reference_keys=parent_keys,
                    assumptions=tuple(str(item) for item in raw["assumptions"]),
                    generated_atomistic_candidate=bool(raw["generated_atomistic_candidate"]),
                )
            )
        hypothesis_ids = {item.hypothesis_id for item in hypotheses}
        if len(hypothesis_ids) != len(hypotheses):
            raise ValueError("GPT planner hypothesis IDs must be unique")
        recipes: list[CandidateRecipe] = []
        for raw in raw_recipes[: self.maximum_recipes]:
            if not isinstance(raw, Mapping):
                raise ValueError("GPT planner recipe must be an object")
            parent_key = str(raw["parent_reference_key"])
            if parent_key not in references:
                raise ValueError("GPT planner recipe referenced an unknown parent structure")
            hypothesis_id = str(raw["hypothesis_id"])
            if hypothesis_id not in hypothesis_ids:
                raise ValueError("GPT planner recipe referenced an unknown hypothesis")
            linked_evidence = tuple(str(item) for item in raw["evidence_ids"])
            if any(item not in evidence_ids for item in linked_evidence):
                raise ValueError("GPT planner recipe referenced unknown evidence")
            operations = []
            for operation in raw["operations"]:
                if not isinstance(operation, Mapping):
                    raise ValueError("GPT planner operation must be an object")
                try:
                    parameters = json.loads(str(operation["parameters_json"]))
                except json.JSONDecodeError as exc:
                    raise ValueError(
                        "GPT planner operation parameters_json must be valid JSON"
                    ) from exc
                if not isinstance(parameters, Mapping):
                    raise ValueError("GPT planner operation parameters_json must encode an object")
                operations.append(
                    CandidateOperation(
                        CandidateOperationKind(str(operation["kind"])),
                        parameters,
                    )
                )
            recipes.append(
                CandidateRecipe(
                    recipe_id=str(raw["recipe_id"]),
                    parent_reference_key=parent_key,
                    hypothesis_id=hypothesis_id,
                    operations=tuple(operations),
                    evidence_ids=linked_evidence,
                    rationale=str(raw["rationale"]),
                    assumptions=tuple(str(item) for item in raw["assumptions"]),
                    random_seed=int(raw["random_seed"]),
                    planner=self.planner_id,
                )
            )
        if len({item.recipe_id for item in recipes}) != len(recipes):
            raise ValueError("GPT planner recipe IDs must be unique")
        diagnostics = ()
        if len(raw_recipes) > self.maximum_recipes:
            diagnostics = (
                Diagnostic(
                    "GPT_PLANNER_RECIPE_LIMIT_REACHED",
                    Severity.INFO,
                    "GPT recipes were truncated at the local explicit limit.",
                    {"maximum_recipes": self.maximum_recipes},
                ),
            )
        return CandidatePlan(
            hypotheses=tuple(hypotheses),
            recipes=tuple(recipes),
            diagnostics=diagnostics,
            planner=self.planner_id,
            external_api_called=True,
        )
