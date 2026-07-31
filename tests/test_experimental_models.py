from __future__ import annotations

import json
import urllib.error

import pytest
from pymatgen.core import Lattice, Structure

import catex.cli as cli_module
import catex.experimental.providers as providers_module
from catex.cli import main
from catex.experimental import (
    CandidateOperation,
    CandidateOperationKind,
    CandidateRecipe,
    CompositionScope,
    ElementConstraint,
    EvidenceKind,
    EvidenceRecord,
    EvidenceRole,
    ExperimentSpec,
    InMemoryStructureProvider,
    ModelKind,
    OptimadeCatalogFetchReport,
    ProviderRegistry,
    SampleState,
    StructureSourceKind,
    execute_candidate_recipe,
    fetch_optimade_structures,
    load_experiment_spec,
    load_local_structure_catalog,
    materialize_provider_catalog,
    parse_experiment_spec,
)


def _alloy() -> Structure:
    return Structure(
        Lattice.cubic(3.6),
        ["Ni", "Ni", "Mo", "Mo"],
        [[0, 0, 0], [0.5, 0.5, 0], [0.5, 0, 0.5], [0, 0.5, 0.5]],
    )


def _spec() -> ExperimentSpec:
    composition = EvidenceRecord(
        evidence_id="icp-1",
        kind=EvidenceKind.ICP,
        sample_state=SampleState.AS_PREPARED,
        role=EvidenceRole.HARD,
    )
    return ExperimentSpec(
        sample_id="synthetic-nimo",
        target_state=SampleState.AS_PREPARED,
        evidence=(composition,),
        composition_constraints=(
            ElementConstraint(
                "Ni",
                0.4,
                0.6,
                CompositionScope.BULK,
                ("icp-1",),
            ),
            ElementConstraint(
                "Mo",
                0.4,
                0.6,
                CompositionScope.BULK,
                ("icp-1",),
            ),
        ),
        allowed_elements=("Ni", "Mo"),
    )


def test_experiment_spec_is_strict_and_tracks_state(tmp_path) -> None:
    xrd = tmp_path / "sample.xy"
    xrd.write_text("\n".join(f"{20 + i} {i + 1}" for i in range(8)), encoding="utf-8")
    payload = {
        "sample_id": "sample-1",
        "target_state": "activated",
        "material_pack": "alloy-electrocatalyst",
        "allowed_elements": ["Ni", "Mo"],
        "excluded_elements": [],
        "composition_constraints": [
            {
                "element": "Ni",
                "minimum_atomic_fraction": 0.5,
                "maximum_atomic_fraction": 0.9,
                "scope": "bulk",
                "evidence_ids": ["icp"],
            }
        ],
        "evidence": [
            {
                "evidence_id": "icp",
                "kind": "icp",
                "sample_state": "as_prepared",
                "role": "hard",
                "metadata": {"unit": "atomic_fraction"},
            },
            {
                "evidence_id": "xrd",
                "kind": "xrd",
                "sample_state": "as_prepared",
                "role": "soft",
                "artifact": "sample.xy",
                "metadata": {"radiation": "CuKa"},
            },
        ],
    }

    parsed = parse_experiment_spec(payload, artifact_root=tmp_path)

    assert parsed.spec.target_state is SampleState.ACTIVATED
    assert parsed.spec.required_bulk_elements == ("Ni",)
    assert parsed.spec.evidence[1].artifact is not None
    assert parsed.spec.evidence[1].artifact.name == "sample.xy"
    assert parsed.artifact_paths["xrd"] == xrd.resolve()
    assert "path" not in json.dumps(parsed.spec.to_dict()).lower()

    with pytest.raises(ValueError, match="unknown fields"):
        parse_experiment_spec({**payload, "typo": True}, artifact_root=tmp_path)
    with pytest.raises(ValueError, match="inside artifact_root"):
        parse_experiment_spec(
            {
                **payload,
                "evidence": [
                    {
                        "evidence_id": "xrd",
                        "kind": "xrd",
                        "artifact": "../outside.xy",
                    }
                ],
                "composition_constraints": [],
            },
            artifact_root=tmp_path,
        )


def test_local_catalog_confines_paths_and_preserves_provenance(tmp_path) -> None:
    structure_path = tmp_path / "nimo.cif"
    _alloy().to(filename=structure_path, fmt="cif")
    catalog_path = tmp_path / "catalog.json"
    catalog_path.write_text(
        json.dumps(
            {
                "schema_version": "catex.structure-catalog.v1",
                "provider": "synthetic",
                "entries": [
                    {
                        "record_id": "nimo-1",
                        "path": "nimo.cif",
                        "source_kind": "hypothetical",
                        "source_locator": "synthetic:test",
                        "license": "CC0",
                        "citation": "Synthetic test only.",
                    }
                ],
            }
        ),
        encoding="utf-8",
    )

    catalog = load_local_structure_catalog(catalog_path)
    reference = catalog.references()[0]

    assert reference.key == "synthetic:nimo-1"
    assert reference.elements == ("Mo", "Ni")
    assert reference.artifact_sha256 is not None
    assert catalog.get(reference.key).composition.reduced_formula == "NiMo"

    bad_catalog = tmp_path / "bad.json"
    bad_catalog.write_text(
        json.dumps(
            {
                "provider": "bad",
                "entries": [
                    {
                        "record_id": "escape",
                        "path": "../outside.cif",
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="inside the catalog root"):
        load_local_structure_catalog(bad_catalog)


def test_candidate_recipe_executes_bounded_transformations() -> None:
    provider = InMemoryStructureProvider(
        "memory",
        (("nimo", _alloy(), StructureSourceKind.HYPOTHETICAL),),
    )
    registry = ProviderRegistry((provider,))
    recipe = CandidateRecipe(
        recipe_id="nimo-defect",
        parent_reference_key="memory:nimo",
        hypothesis_id="phase-family-1",
        operations=(
            CandidateOperation(CandidateOperationKind.SUPERCELL, {"scale": [2, 1, 1]}),
            CandidateOperation(
                CandidateOperationKind.SUBSTITUTE,
                {"replacements": {"0": "Mo"}},
            ),
            CandidateOperation(
                CandidateOperationKind.VACANCY,
                {"indices_0based": [1]},
            ),
            CandidateOperation(
                CandidateOperationKind.ISOTROPIC_STRAIN,
                {"strain": 0.01},
            ),
        ),
        evidence_ids=("icp-1",),
        rationale="Synthetic deterministic recipe.",
    )

    executions = execute_candidate_recipe(recipe, registry, _spec())

    assert len(executions) == 1
    assert executions[0].model_kind is ModelKind.BULK
    assert len(executions[0].structure) == 7
    assert len(executions[0].transformation_sha256s) == 4
    assert executions[0].valid is True

    unsafe = CandidateRecipe(
        recipe_id="unsafe-strain",
        parent_reference_key="memory:nimo",
        hypothesis_id="phase-family-1",
        operations=(
            CandidateOperation(
                CandidateOperationKind.ISOTROPIC_STRAIN,
                {"strain": 0.25},
            ),
        ),
        evidence_ids=("icp-1",),
        rationale="Must fail.",
    )
    with pytest.raises(ValueError, match="strain"):
        execute_candidate_recipe(unsafe, registry, _spec())


def test_candidate_recipe_generates_explicit_surface_branch_and_vacuum() -> None:
    nickel = Structure.from_spacegroup(
        "Fm-3m",
        Lattice.cubic(3.52),
        ["Ni"],
        [[0, 0, 0]],
    )
    registry = ProviderRegistry(
        (
            InMemoryStructureProvider(
                "surface-parent",
                (("ni", nickel, StructureSourceKind.HYPOTHETICAL),),
            ),
        )
    )
    recipe = CandidateRecipe(
        recipe_id="ni-surface",
        parent_reference_key="surface-parent:ni",
        hypothesis_id="surface-family",
        operations=(
            CandidateOperation(
                CandidateOperationKind.SLAB,
                {
                    "miller_index": [1, 0, 0],
                    "minimum_slab_angstrom": 4.0,
                    "minimum_vacuum_angstrom": 6.0,
                    "maximum_candidates": 1,
                    "termination_indices": [0],
                },
            ),
            CandidateOperation(
                CandidateOperationKind.SET_VACUUM,
                {"vacuum_angstrom": 14.0},
            ),
        ),
        evidence_ids=("icp-1",),
        rationale="Exercise the explicit surface branch.",
    )

    executions = execute_candidate_recipe(recipe, registry, _spec())

    assert len(executions) == 1
    assert executions[0].model_kind is ModelKind.SURFACE
    assert len(executions[0].transformation_sha256s) == 2
    assert any(
        item.code == "SURFACE_STOICHIOMETRY_NOT_BULK_COMPOSITION"
        for item in executions[0].diagnostics
    )


@pytest.mark.parametrize(
    "kind,parameters,match",
    [
        (CandidateOperationKind.SUPERCELL, {"scale": [9, 9, 9]}, "512"),
        (
            CandidateOperationKind.SUBSTITUTE,
            {"replacements": {"01": "Mo"}},
            "canonical",
        ),
        (CandidateOperationKind.VACANCY, {"indices_0based": [True]}, "integer"),
        (CandidateOperationKind.SLAB, {"miller_index": [0, 0, 0]}, "cannot be"),
        (CandidateOperationKind.SET_VACUUM, {"vacuum_angstrom": "14"}, "number"),
    ],
)
def test_candidate_recipe_rejects_unsafe_operation_parameters(kind, parameters, match) -> None:
    provider = InMemoryStructureProvider(
        "memory",
        (("nimo", _alloy(), StructureSourceKind.HYPOTHETICAL),),
    )
    recipe = CandidateRecipe(
        recipe_id=f"invalid-{kind.value}",
        parent_reference_key="memory:nimo",
        hypothesis_id="invalid-operation",
        operations=(CandidateOperation(kind, parameters),),
        evidence_ids=("icp-1",),
        rationale="Must be rejected locally.",
    )

    with pytest.raises(ValueError, match=match):
        execute_candidate_recipe(recipe, ProviderRegistry((provider,)), _spec())


def test_candidate_chemistry_diagnostics_are_fail_closed() -> None:
    nio = Structure(
        Lattice.cubic(4.2),
        ["Ni", "O"],
        [[0, 0, 0], [0.5, 0.5, 0.5]],
    )
    registry = ProviderRegistry(
        (
            InMemoryStructureProvider(
                "chemistry",
                (("nio", nio, StructureSourceKind.HYPOTHETICAL),),
            ),
        )
    )
    spec = ExperimentSpec(
        sample_id="restricted",
        target_state=SampleState.UNSPECIFIED,
        evidence=(),
        allowed_elements=("Ni", "Mo"),
        excluded_elements=("O",),
        composition_constraints=(ElementConstraint("Mo", 0.1, 0.9, CompositionScope.BULK),),
    )
    recipe = CandidateRecipe(
        recipe_id="outside-chemistry",
        parent_reference_key="chemistry:nio",
        hypothesis_id="chemistry-check",
        operations=(CandidateOperation(CandidateOperationKind.IDENTITY),),
        evidence_ids=(),
        rationale="Exercise chemistry gates.",
    )

    execution = execute_candidate_recipe(recipe, registry, spec)[0]
    codes = {item.code for item in execution.diagnostics}

    assert execution.valid is False
    assert "CANDIDATE_EXCLUDED_ELEMENT" in codes
    assert "CANDIDATE_OUTSIDE_ALLOWED_CHEMISTRY" in codes
    assert "CANDIDATE_MISSING_REQUIRED_BULK_ELEMENT" in codes
    assert "SINGLE_PHASE_COMPOSITION_INTERVAL_MISMATCH" in codes


def test_load_experiment_spec_resolves_artifacts_relative_to_document(tmp_path) -> None:
    xrd = tmp_path / "pattern.xy"
    xrd.write_text("\n".join(f"{i} {i}" for i in range(1, 7)), encoding="utf-8")
    spec_path = tmp_path / "experiment.json"
    spec_path.write_text(
        json.dumps(
            {
                "sample_id": "relative-path",
                "target_state": "as_prepared",
                "evidence": [
                    {
                        "evidence_id": "xrd",
                        "kind": "xrd",
                        "artifact": "pattern.xy",
                    }
                ],
            }
        ),
        encoding="utf-8",
    )

    result = load_experiment_spec(spec_path)

    assert result.source_path == spec_path.resolve()
    assert result.artifact_paths["xrd"] == xrd.resolve()


class _FakeJSONTransport:
    def __init__(self, payloads: list[dict[str, object]]) -> None:
        self.payloads = list(payloads)
        self.urls: list[str] = []

    def get_json(self, url: str) -> dict[str, object]:
        self.urls.append(url)
        return self.payloads.pop(0)


def _optimade_record(
    record_id: str = "db/record 1",
    *,
    disordered: bool = False,
) -> dict[str, object]:
    concentration = [0.5, 0.5] if disordered else [1.0]
    symbols = ["Ni", "Mo"] if disordered else ["Ni"]
    return {
        "id": record_id,
        "attributes": {
            "dimension_types": [1, 1, 1],
            "lattice_vectors": [[3.0, 0, 0], [0, 3.0, 0], [0, 0, 3.0]],
            "cartesian_site_positions": [[0, 0, 0], [1.5, 1.5, 1.5]],
            "species_at_sites": ["Ni-mixed" if disordered else "Ni", "Mo"],
            "species": [
                {
                    "name": "Ni-mixed" if disordered else "Ni",
                    "chemical_symbols": symbols,
                    "concentration": concentration,
                },
                {
                    "name": "Mo",
                    "chemical_symbols": ["Mo"],
                    "concentration": [1.0],
                },
            ],
        },
    }


def test_optimade_fetch_is_bounded_traceable_and_cacheable(tmp_path) -> None:
    missing_mo = _optimade_record("missing-required-mo")
    missing_mo["attributes"]["species_at_sites"] = ["Ni", "Ni"]
    implicit_atoms = _optimade_record("implicit-atoms")
    implicit_atoms["attributes"]["structure_features"] = ["implicit_atoms"]
    transport = _FakeJSONTransport(
        [
            {
                "data": [
                    _optimade_record(),
                    _optimade_record("unsupported", disordered=True),
                    missing_mo,
                    implicit_atoms,
                ],
                "links": {"next": None},
            }
        ]
    )

    fetched = fetch_optimade_structures(
        base_url="https://provider.example/v1",
        provider_id="optimade-test",
        required_elements=("Mo", "Ni"),
        maximum_results=5,
        transport=transport,
        license="CC-BY-4.0",
        citation="Synthetic provider fixture.",
    )

    assert fetched.report.received_records == 4
    assert fetched.report.accepted_records == 1
    assert fetched.report.diagnostics[0].code == "OPTIMADE_STRUCTURE_UNSUPPORTED"
    assert fetched.report.diagnostics[1].code == "OPTIMADE_CHEMISTRY_FILTER_MISMATCH"
    assert fetched.report.diagnostics[2].code == "OPTIMADE_STRUCTURE_UNSUPPORTED"
    assert "/v1/v1/" not in transport.urls[0]
    assert "elements+HAS+ALL" in transport.urls[0]
    reference = fetched.provider.references()[0]
    assert reference.source_locator.endswith("/db%2Frecord%201")
    assert reference.license == "CC-BY-4.0"

    destination = tmp_path / "offline-catalog"
    report = materialize_provider_catalog(fetched.provider, destination)
    reloaded = load_local_structure_catalog(destination / "catalog.json")
    combined = OptimadeCatalogFetchReport(fetched.report, report)

    assert report.catalog.sha256
    assert report.writes_performed is True
    assert combined.diagnostics == fetched.report.diagnostics
    assert combined.to_dict()["status"] == "materialized"
    assert reloaded.references()[0].source_locator == reference.source_locator
    assert reloaded.get(reloaded.references()[0].key).composition.reduced_formula == "NiMo"
    with pytest.raises(ValueError, match="must not already exist"):
        materialize_provider_catalog(fetched.provider, destination)


def test_optimade_fetch_rejects_unsafe_pagination_and_invalid_bounds() -> None:
    transport = _FakeJSONTransport(
        [
            {
                "data": [_optimade_record()],
                "links": {"next": "https://attacker.example/v1/structures?page=2"},
            }
        ]
    )

    with pytest.raises(ValueError, match="cannot leave"):
        fetch_optimade_structures(
            base_url="https://provider.example",
            provider_id="optimade-test",
            required_elements=("Ni",),
            transport=transport,
        )
    with pytest.raises(ValueError, match="maximum_results"):
        fetch_optimade_structures(
            base_url="https://provider.example",
            provider_id="optimade-test",
            required_elements=("Ni",),
            maximum_results=0,
            transport=transport,
        )
    with pytest.raises(ValueError, match="maximum_pages"):
        fetch_optimade_structures(
            base_url="https://provider.example",
            provider_id="optimade-test",
            required_elements=("Ni",),
            maximum_pages=0,
            transport=transport,
        )
    with pytest.raises(ValueError, match="must not be empty"):
        fetch_optimade_structures(
            base_url="https://provider.example",
            provider_id="optimade-test",
            required_elements=(),
            transport=transport,
        )
    with pytest.raises(ValueError, match="HTTPS"):
        fetch_optimade_structures(
            base_url="http://provider.example",
            provider_id="optimade-test",
            required_elements=("Ni",),
            transport=transport,
        )
    with pytest.raises(ValueError, match="credentials, a query"):
        fetch_optimade_structures(
            base_url="https://user@provider.example?token=unsafe",
            provider_id="optimade-test",
            required_elements=("Ni",),
            transport=transport,
        )


def test_optimade_fetch_records_skips_duplicates_and_follows_local_next_link() -> None:
    transport = _FakeJSONTransport(
        [
            {
                "data": [
                    None,
                    {"id": "", "attributes": {}},
                    _optimade_record("accepted"),
                    _optimade_record("same-structure"),
                ],
                "links": {"next": {"href": "/v1/structures?page=2"}},
            },
            {
                "data": [_optimade_record("same-again")],
            },
        ]
    )

    fetched = fetch_optimade_structures(
        base_url="https://provider.example",
        provider_id="optimade-test",
        required_elements=("Ni",),
        transport=transport,
    )

    assert fetched.report.received_records == 5
    assert fetched.report.accepted_records == 1
    assert len(fetched.report.diagnostics) == 2
    assert len(transport.urls) == 2
    assert transport.urls[1] == "https://provider.example/v1/structures?page=2"

    with pytest.raises(ValueError, match="data must be an array"):
        fetch_optimade_structures(
            base_url="https://provider.example",
            provider_id="optimade-test",
            required_elements=("Ni",),
            transport=_FakeJSONTransport([{"data": {}}]),
        )


class _RawResponse:
    def __init__(
        self,
        raw: bytes,
        url: str = "https://provider.example/v1/structures",
    ) -> None:
        self.raw = raw
        self.url = url

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False

    def read(self, _maximum_bytes: int) -> bytes:
        return self.raw

    def geturl(self) -> str:
        return self.url


def test_https_json_transport_is_bounded_and_fail_closed(monkeypatch) -> None:
    monkeypatch.setattr(
        providers_module.urllib.request,
        "urlopen",
        lambda request, timeout: _RawResponse(b'{"data": []}'),
    )
    transport = providers_module._URLJSONTransport(
        timeout_seconds=2,
        maximum_bytes=1000,
    )

    assert transport.get_json("https://provider.example/v1/structures") == {"data": []}
    with pytest.raises(ValueError, match="HTTPS"):
        transport.get_json("http://provider.example")
    with pytest.raises(ValueError, match="timeout_seconds"):
        providers_module._URLJSONTransport(timeout_seconds=0)
    with pytest.raises(ValueError, match="maximum_bytes"):
        providers_module._URLJSONTransport(maximum_bytes=999)

    monkeypatch.setattr(
        providers_module.urllib.request,
        "urlopen",
        lambda request, timeout: _RawResponse(
            b'{"data": []}',
            "https://redirected.example/v1/structures",
        ),
    )
    with pytest.raises(ValueError, match="redirect"):
        transport.get_json("https://provider.example/v1/structures")

    monkeypatch.setattr(
        providers_module.urllib.request,
        "urlopen",
        lambda request, timeout: _RawResponse(b"not-json"),
    )
    with pytest.raises(ValueError, match="invalid JSON"):
        transport.get_json("https://provider.example/v1/structures")

    monkeypatch.setattr(
        providers_module.urllib.request,
        "urlopen",
        lambda request, timeout: _RawResponse(b"[]"),
    )
    with pytest.raises(ValueError, match="JSON object"):
        transport.get_json("https://provider.example/v1/structures")

    def fail_urlopen(request, timeout):
        raise urllib.error.URLError("offline")

    monkeypatch.setattr(providers_module.urllib.request, "urlopen", fail_urlopen)
    with pytest.raises(ValueError, match="request failed"):
        transport.get_json("https://provider.example/v1/structures")


def test_cli_explicitly_fetches_and_materializes_offline_catalog(
    tmp_path,
    monkeypatch,
    capsys,
) -> None:
    fetched = fetch_optimade_structures(
        base_url="https://provider.example",
        provider_id="optimade-cli",
        required_elements=("Ni", "Mo"),
        transport=_FakeJSONTransport(
            [{"data": [_optimade_record("cli-record")], "links": {"next": None}}]
        ),
    )
    monkeypatch.setattr(
        cli_module,
        "fetch_optimade_structures",
        lambda **_arguments: fetched,
    )
    destination = tmp_path / "downloaded-catalog"

    exit_code = main(
        [
            "fetch-optimade-catalog",
            "https://provider.example",
            "--provider-id",
            "optimade-cli",
            "--element",
            "Ni",
            "--element",
            "Mo",
            "--destination",
            str(destination),
        ]
    )
    output = capsys.readouterr().out

    assert exit_code == 0
    assert "status: materialized" in output
    assert "network_read_performed: true" in output
    assert (destination / "catalog.json").is_file()
