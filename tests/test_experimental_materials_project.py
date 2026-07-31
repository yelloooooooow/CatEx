from __future__ import annotations

from pathlib import Path

import pytest
from pymatgen.core import Lattice, Structure

from catex.experimental import (
    MPAPISummaryClient,
    fetch_materials_project_structures,
)
from catex_app.experimental_modeling import ExperimentalModelingService
from catex_app.projects import ProjectStore


class _FakeMaterialsProjectClient:
    def __init__(self, documents):
        self.documents = documents
        self.calls = []

    def fetch_summaries(self, *, required_elements, maximum_results):
        self.calls.append((required_elements, maximum_results))
        return "2026.07.01", self.documents


def _nimo() -> Structure:
    return Structure(
        Lattice.cubic(3.6),
        ["Ni", "Mo"],
        [[0, 0, 0], [0.5, 0.5, 0.5]],
    )


def test_materials_project_provider_records_version_and_stability_metadata() -> None:
    client = _FakeMaterialsProjectClient(
        [
            {
                "material_id": "mp-test",
                "formula_pretty": "NiMo",
                "structure": _nimo(),
                "energy_above_hull": 0.025,
                "is_stable": False,
                "deprecated": False,
            }
        ]
    )

    result = fetch_materials_project_structures(
        provider_id="materials-project-test",
        required_elements=("Mo", "Ni"),
        maximum_results=10,
        client=client,
    )

    assert client.calls == [(("Mo", "Ni"), 10)]
    assert result.report.database_version == "2026.07.01"
    assert result.report.accepted_records == 1
    assert result.report.records[0]["material_id"] == "mp-test"
    assert result.report.records[0]["energy_above_hull_eV_per_atom"] == pytest.approx(0.025)
    reference = result.provider.references()[0]
    assert reference.formula == "NiMo"
    assert reference.source_locator.endswith("/mp-test")
    assert result.provider.get(reference.key).composition.reduced_formula == "NiMo"
    assert "api_key" not in result.report.to_dict()


def test_materials_project_provider_skips_deprecated_and_rejects_missing_key(
    monkeypatch,
) -> None:
    client = _FakeMaterialsProjectClient(
        [
            {
                "material_id": "mp-deprecated",
                "formula_pretty": "NiMo",
                "structure": _nimo(),
                "deprecated": True,
            }
        ]
    )
    with pytest.raises(ValueError, match="no accepted"):
        fetch_materials_project_structures(
            provider_id="materials-project-test",
            required_elements=("Ni", "Mo"),
            client=client,
        )

    monkeypatch.delenv("CATEX_TEST_MP_KEY", raising=False)
    with pytest.raises(ValueError, match="required at runtime"):
        MPAPISummaryClient(api_key_environment_variable="CATEX_TEST_MP_KEY").fetch_summaries(
            required_elements=("Ni", "Mo"),
            maximum_results=1,
        )


def test_materials_project_client_wraps_external_failures_without_credential_detail(
    monkeypatch,
) -> None:
    import mp_api.client

    class _FailingMPRester:
        def __init__(self, api_key: str) -> None:
            assert api_key == "synthetic-test-key"

        def __enter__(self):
            raise RuntimeError("remote failure containing implementation detail")

        def __exit__(self, *_args):
            return False

    monkeypatch.setenv("CATEX_TEST_MP_KEY", "synthetic-test-key")
    monkeypatch.setattr(mp_api.client, "MPRester", _FailingMPRester)

    with pytest.raises(ValueError, match="Materials Project API request failed") as captured:
        MPAPISummaryClient(api_key_environment_variable="CATEX_TEST_MP_KEY").fetch_summaries(
            required_elements=("Ni", "Mo"),
            maximum_results=1,
        )

    assert "synthetic-test-key" not in str(captured.value)


def test_application_run_records_implicitly_selected_catalog_revision(tmp_path: Path) -> None:
    service = ExperimentalModelingService(ProjectStore(tmp_path))
    project_id = service.store.create_project(
        title="MP provenance",
        purpose="experimental_interpretation",
    )["project_id"]
    client = _FakeMaterialsProjectClient(
        [
            {
                "material_id": "mp-test",
                "formula_pretty": "NiMo",
                "structure": _nimo(),
                "energy_above_hull": 0.0,
                "is_stable": True,
                "deprecated": False,
            }
        ]
    )
    catalog = service.fetch_materials_project(
        project_id,
        required_elements=("Ni", "Mo"),
        maximum_results=10,
        client=client,
    )
    service.save_spec(
        project_id,
        {
            "schema_version": "catex.experiment-spec.v1",
            "sample_id": "mp-provenance",
            "target_state": "unspecified",
            "allowed_elements": ["Ni", "Mo"],
        },
    )

    run = service.infer(
        project_id,
        planner_kind="rule",
        catalog_ids=(),
        maximum_representatives=2,
        xrd_settings=None,
    )

    assert run["catalog_ids"] == [catalog["catalog_id"]]
    assert run["candidates"]
    assert len(run["candidates"][0]["cif_sha256"]) == 64
    assert run["candidates"][0]["size_bytes"] > 0
