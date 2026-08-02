from __future__ import annotations

import json

import pytest
from pymatgen.core import Lattice, Structure

import catex.experimental.planning as planning_module
from catex.experimental import (
    EvidenceKind,
    EvidenceRecord,
    EvidenceRole,
    ExperimentSpec,
    GPTCandidatePlanner,
    InMemoryStructureProvider,
    OpenAIResponsesTransport,
    ProviderRegistry,
    RuleCandidatePlanner,
    RulePlannerSettings,
    SampleState,
    StructureSourceKind,
)


def _registry() -> ProviderRegistry:
    structure = Structure(
        Lattice.cubic(3.6),
        ["Ni", "Mo"],
        [[0, 0, 0], [0.5, 0.5, 0.5]],
    )
    provider = InMemoryStructureProvider(
        "synthetic",
        (("nimo", structure, StructureSourceKind.HYPOTHETICAL),),
    )
    return ProviderRegistry((provider,))


def _spec() -> ExperimentSpec:
    return ExperimentSpec(
        sample_id="nimo",
        target_state=SampleState.ACTIVATED,
        evidence=(
            EvidenceRecord(
                evidence_id="xps",
                kind=EvidenceKind.XPS,
                sample_state=SampleState.ACTIVATED,
                role=EvidenceRole.SOFT,
                metadata={"elements": ["Ni", "Mo", "O"], "assignment": "oxide"},
            ),
        ),
        allowed_elements=("Ni", "Mo"),
        material_pack="alloy-electrocatalyst",
    )


def test_rule_planner_generates_bulk_surfaces_and_unresolved_surface_oxygen() -> None:
    planner = RuleCandidatePlanner(
        RulePlannerSettings(
            surface_miller_indices=((1, 0, 0),),
            maximum_terminations_per_surface=2,
        )
    )

    plan = planner.plan(_spec(), _registry(), None)

    assert plan.external_api_called is False
    assert {item.recipe_id for item in plan.recipes} == {"bulk-1", "surface-1-100"}
    assert "surface-oxygen-unresolved" in {item.hypothesis_id for item in plan.hypotheses}
    unresolved = next(
        item for item in plan.hypotheses if item.hypothesis_id == "surface-oxygen-unresolved"
    )
    assert unresolved.generated_atomistic_candidate is False


class _FakeTransport:
    def __init__(self, *, bad_parent: bool = False) -> None:
        self.bad_parent = bad_parent
        self.calls = 0

    def complete_json(self, *, system_prompt, user_payload, output_schema):
        self.calls += 1
        assert "Do not generate code" in system_prompt
        assert output_schema["additionalProperties"] is False
        parent = "synthetic:missing" if self.bad_parent else "synthetic:nimo"
        return {
            "hypotheses": [
                {
                    "hypothesis_id": "gpt-phase",
                    "summary": "A bounded parent-phase hypothesis.",
                    "evidence_ids": ["xps"],
                    "parent_reference_keys": [parent],
                    "assumptions": ["XPS does not determine atomic coordinates."],
                    "generated_atomistic_candidate": True,
                }
            ],
            "recipes": [
                {
                    "recipe_id": "gpt-bulk",
                    "parent_reference_key": parent,
                    "hypothesis_id": "gpt-phase",
                    "operations": [{"kind": "identity", "parameters_json": "{}"}],
                    "evidence_ids": ["xps"],
                    "rationale": "Retain a parent reference.",
                    "assumptions": ["Ideal parent structure."],
                    "random_seed": 0,
                }
            ],
        }


def test_gpt_planner_accepts_only_schema_valid_local_references() -> None:
    transport = _FakeTransport()
    plan = GPTCandidatePlanner(transport).plan(_spec(), _registry(), None)

    assert transport.calls == 1
    assert plan.external_api_called is True
    assert plan.recipes[0].planner == "gpt"

    with pytest.raises(ValueError, match="unknown parent"):
        GPTCandidatePlanner(_FakeTransport(bad_parent=True)).plan(
            _spec(),
            _registry(),
            None,
        )


def test_openai_transport_requires_runtime_key_and_explicit_model(monkeypatch) -> None:
    with pytest.raises(ValueError, match="explicit OpenAI model"):
        OpenAIResponsesTransport(model="")
    monkeypatch.delenv("CATEX_TEST_OPENAI_KEY", raising=False)
    transport = OpenAIResponsesTransport(
        model="test-model",
        api_key_environment_variable="CATEX_TEST_OPENAI_KEY",
    )

    with pytest.raises(ValueError, match="required at runtime"):
        transport.complete_json(
            system_prompt="test",
            user_payload={},
            output_schema={"type": "object"},
        )


def test_rule_planner_reports_disorder_limits_large_parents_and_no_match() -> None:
    large = _registry().get_structure("synthetic:nimo")
    large.make_supercell((4, 4, 4))
    large_registry = ProviderRegistry(
        (
            InMemoryStructureProvider(
                "large",
                (("large-nimo", large, StructureSourceKind.HYPOTHETICAL),),
            ),
        )
    )
    disorder_spec = ExperimentSpec(
        sample_id="disordered",
        target_state=SampleState.ACTIVATED,
        evidence=(
            EvidenceRecord(
                evidence_id="tem",
                kind=EvidenceKind.TEM,
                sample_state=SampleState.ACTIVATED,
                role=EvidenceRole.SOFT,
                metadata={"observation": "broad_halo"},
            ),
        ),
        allowed_elements=("Ni", "Mo"),
        material_pack="alloy-electrocatalyst",
    )

    large_plan = RuleCandidatePlanner(
        RulePlannerSettings(maximum_recipes=1),
    ).plan(disorder_spec, large_registry, None)

    codes = {item.code for item in large_plan.diagnostics}
    assert "RULE_PLANNER_SURFACE_SKIPPED_LARGE_PARENT" in codes
    assert "disordered-motif-ensemble-unresolved" in {
        item.hypothesis_id for item in large_plan.hypotheses
    }

    no_match_spec = ExperimentSpec(
        sample_id="no-match",
        target_state=SampleState.UNSPECIFIED,
        evidence=(),
        allowed_elements=("Fe",),
    )
    no_match = RuleCandidatePlanner().plan(no_match_spec, _registry(), None)
    assert no_match.recipes == ()
    assert no_match.diagnostics[0].code == "RULE_PLANNER_NO_PARENT_PHASE"

    limited = RuleCandidatePlanner(
        RulePlannerSettings(
            surface_miller_indices=((1, 0, 0),),
            maximum_recipes=1,
        )
    ).plan(_spec(), _registry(), None)
    assert limited.diagnostics[-1].code == "RULE_PLANNER_RECIPE_LIMIT_REACHED"
    assert len(limited.recipes) == 1


@pytest.mark.parametrize(
    "settings,match",
    [
        ({"maximum_parent_phases": 0}, "maximum_parent_phases"),
        ({"surface_miller_indices": ()}, "must not be empty"),
        ({"surface_miller_indices": ((0, 0, 0),)}, "Miller"),
        ({"minimum_slab_angstrom": 0}, "dimensions"),
        ({"maximum_terminations_per_surface": 0}, "maximum_terminations"),
        ({"maximum_recipes": 0}, "maximum_recipes"),
    ],
)
def test_rule_planner_settings_reject_invalid_bounds(settings, match) -> None:
    with pytest.raises(ValueError, match=match):
        RulePlannerSettings(**settings)


class _Response:
    def __init__(self, payload: object) -> None:
        self.raw = json.dumps(payload).encode("utf-8")

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False

    def read(self) -> bytes:
        return self.raw


def test_openai_transport_uses_strict_responses_payload_without_persistence(
    monkeypatch,
) -> None:
    captured = {}

    def fake_urlopen(request, *, timeout):
        captured["request"] = request
        captured["timeout"] = timeout
        return _Response({"output_text": '{"hypotheses": [], "recipes": []}'})

    monkeypatch.setenv("CATEX_TEST_OPENAI_KEY", "test-only-secret")
    monkeypatch.setattr(planning_module.urllib.request, "urlopen", fake_urlopen)
    transport = OpenAIResponsesTransport(
        model="explicit-test-model",
        api_key_environment_variable="CATEX_TEST_OPENAI_KEY",
        timeout_seconds=12,
    )

    result = transport.complete_json(
        system_prompt="bounded",
        user_payload={"sample": "synthetic"},
        output_schema={"type": "object", "additionalProperties": False},
    )
    posted = json.loads(captured["request"].data)

    assert result == {"hypotheses": [], "recipes": []}
    assert posted["store"] is False
    assert posted["model"] == "explicit-test-model"
    assert posted["text"]["format"]["strict"] is True
    assert captured["timeout"] == 12
    assert (
        OpenAIResponsesTransport._output_text({"output": [{"content": [{"text": '{"ok": true}'}]}]})
        == '{"ok": true}'
    )
    with pytest.raises(ValueError, match="output text"):
        OpenAIResponsesTransport._output_text({"output": [None, {"content": [None]}]})

    with pytest.raises(ValueError, match="custom OpenAI endpoints"):
        OpenAIResponsesTransport(model="x", endpoint="https://example.invalid")
    with pytest.raises(ValueError, match="timeout_seconds"):
        OpenAIResponsesTransport(model="x", timeout_seconds=0)


def test_openai_transport_verifies_one_ephemeral_direct_key(monkeypatch) -> None:
    captured = {}

    def fake_urlopen(request, *, timeout):
        captured["authorization"] = request.headers["Authorization"]
        captured["method"] = request.method
        captured["timeout"] = timeout
        return _Response({"object": "list", "data": [{"id": "test-model"}]})

    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.setattr(planning_module.urllib.request, "urlopen", fake_urlopen)
    transport = OpenAIResponsesTransport(
        model="explicit-test-model",
        api_key="direct-openai-test-key",
        timeout_seconds=9,
    )

    assert transport.verify_api_key() == 1
    assert captured == {
        "authorization": "Bearer direct-openai-test-key",
        "method": "GET",
        "timeout": 9,
    }
