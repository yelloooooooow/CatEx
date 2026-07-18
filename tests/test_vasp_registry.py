from __future__ import annotations

import json
from pathlib import Path

from catex.cli import main
from catex.models import Severity
from catex.vasp.incar import parse_incar_text, validate_incar
from catex.vasp.models import ValidationMode
from catex.vasp.registry import (
    INCAR_TAG_RULES,
    is_energy_family_relevant,
    vasp544_incar_registry,
)
from catex.workflow.protocol import resolve_protocol

WORKFLOW_FIXTURE = Path(__file__).parent / "fixtures" / "synthetic" / "workflow"


def _diagnostics(text: str, mode: ValidationMode):
    summary, parse_diagnostics = parse_incar_text(text)
    assert not any(item.severity is Severity.ERROR for item in parse_diagnostics)
    return validate_incar(summary, num_sites=2, num_species=2, mode=mode)


def test_registry_is_sorted_unique_and_declares_scope() -> None:
    registry = vasp544_incar_registry()
    tags = [item.tag for item in registry.rules]

    assert tags == sorted(tags)
    assert len(tags) == len(set(tags)) == len(INCAR_TAG_RULES)
    assert len(tags) >= 75
    assert registry.to_dict()["scope"] == "catex-supported-tags-not-exhaustive-vasp-manual"
    assert INCAR_TAG_RULES["LSOL"].provider == "vaspsol-1.0"


def test_registry_energy_policy_is_the_single_documented_exclusion_set() -> None:
    excluded = {tag for tag in INCAR_TAG_RULES if not is_energy_family_relevant(tag)}

    assert excluded == {
        "KPAR",
        "LCHARG",
        "LPLANE",
        "LWAVE",
        "NCORE",
        "NPAR",
        "NSIM",
        "NWRITE",
        "SYSTEM",
    }


def test_unregistered_tag_is_error_in_strict_and_warning_in_exploration() -> None:
    strict = _diagnostics("ENCUT=500\nNOT_A_SUPPORTED_TAG=1\n", ValidationMode.STRICT)
    exploration = _diagnostics("ENCUT=500\nNOT_A_SUPPORTED_TAG=1\n", ValidationMode.EXPLORATION)

    strict_finding = next(
        item for item in strict if item.code == "INCAR_TAG_NOT_IN_VASP544_REGISTRY"
    )
    exploration_finding = next(
        item for item in exploration if item.code == "INCAR_TAG_NOT_IN_VASP544_REGISTRY"
    )
    assert strict_finding.severity is Severity.ERROR
    assert exploration_finding.severity is Severity.WARNING


def test_registered_value_kinds_reject_ambiguous_syntax() -> None:
    diagnostics = _diagnostics(
        "ENCUT=word\nNCORE=2.5\nLWAVE=maybe\nDIPOL=1 2\nPREC=Accurate extra\n",
        ValidationMode.STRICT,
    )

    invalid_tags = {
        item.context["tag"] for item in diagnostics if item.code == "INCAR_REGISTERED_VALUE_INVALID"
    }
    assert invalid_tags == {"ENCUT", "NCORE", "LWAVE", "DIPOL", "PREC"}


def test_paper4_smoke_incar_is_inside_registry() -> None:
    incar_path = (
        Path(__file__).resolve().parents[1]
        / "projects"
        / "paper4_co2rr_dac_reproduction"
        / "structures"
        / "environment_smoke_test"
        / "NiZn_NC"
        / "INCAR"
    )
    diagnostics = _diagnostics(incar_path.read_text(encoding="utf-8"), ValidationMode.EXPLORATION)

    assert "INCAR_TAG_NOT_IN_VASP544_REGISTRY" not in {item.code for item in diagnostics}


def test_protocol_resolution_blocks_unregistered_tag(tmp_path) -> None:
    payload = json.loads((WORKFLOW_FIXTURE / "protocol.json").read_text(encoding="utf-8"))
    payload["incar"]["UNSUPPORTED_TAG"] = "1"
    protocol = tmp_path / "protocol.json"
    protocol.write_text(json.dumps(payload), encoding="utf-8")

    report = resolve_protocol(
        protocol,
        poscar_path=WORKFLOW_FIXTURE / "POSCAR",
        potcar_metadata_path=WORKFLOW_FIXTURE / "potcar-metadata.json",
    )

    assert report.has_errors
    assert report.resolved is None
    assert "INCAR_TAG_NOT_IN_VASP544_REGISTRY" in {item.code for item in report.diagnostics}


def test_registry_cli_emits_json_and_text(capsys) -> None:
    json_exit = main(["show-vasp544-registry", "--format", "json"])
    payload = json.loads(capsys.readouterr().out)
    text_exit = main(["show-vasp544-registry"])
    text = capsys.readouterr().out

    assert json_exit == 0
    assert payload["schema_version"] == "catex.vasp544-incar-registry.v1"
    assert text_exit == 0
    assert "target_vasp_version: 5.4.4" in text
    assert "registered_tags:" in text
