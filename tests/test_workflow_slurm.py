from __future__ import annotations

import json
from pathlib import Path

import pytest

from catex.workflow.slurm import (
    parse_cluster_policy,
    parse_execution_profile,
    plan_slurm_script,
    validate_execution_profile,
    validate_slurm_script,
)

FIXTURE = Path(__file__).parent / "fixtures" / "synthetic" / "workflow"


def _profile():
    return parse_execution_profile((FIXTURE / "execution-profile.json").read_text())


def _policy():
    return parse_cluster_policy((FIXTURE / "cluster-policy.json").read_text())


def test_fixed_slurm_plan_is_validated_and_never_submitted() -> None:
    plan = plan_slurm_script(_profile(), _policy())

    assert plan.status == "validated_not_submitted"
    assert not plan.has_errors
    assert plan.submitted is False
    assert "#SBATCH --ntasks-per-node=64" in plan.script_text
    assert "srun --mpi=pmi2 vasp_std" in plan.script_text
    assert "export OMP_NUM_THREADS=1" in plan.script_text
    assert "export MKL_NUM_THREADS=1" in plan.script_text
    assert plan.script_text.startswith("#!/bin/bash\n")
    assert plan.profile.shell_mode == "nonlogin"
    assert "sbatch" not in plan.script_text
    assert "scancel" not in plan.script_text


def test_profile_resource_limits_are_static_errors() -> None:
    payload = json.loads((FIXTURE / "execution-profile.json").read_text())
    payload["nodes"] = 3
    payload["tasks_per_node"] = 65
    payload["walltime"] = "2-00:00:00"
    profile = parse_execution_profile(json.dumps(payload))

    diagnostics = validate_execution_profile(profile, _policy())
    codes = {item.code for item in diagnostics}

    assert "SLURM_NODE_LIMIT_EXCEEDED" in codes
    assert "SLURM_CORES_PER_NODE_EXCEEDED" in codes
    assert "SLURM_WALLTIME_LIMIT_EXCEEDED" in codes
    walltime = next(item for item in diagnostics if item.code == "SLURM_WALLTIME_LIMIT_EXCEEDED")
    assert walltime.context == {"requested_minutes": 2880, "maximum_minutes": 1440}
    assert "2880 minutes" in walltime.message
    assert "1440 minutes" in walltime.message


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("executable", "vasp_std;sbatch"),
        ("job_name", "../escape"),
        ("module_loads", ["ok", "bad && command"]),
        ("walltime", "1:00"),
        ("shell_mode", "login -x"),
    ],
)
def test_profile_parser_rejects_command_and_path_injection(field, value) -> None:
    payload = json.loads((FIXTURE / "execution-profile.json").read_text())
    payload[field] = value

    with pytest.raises(ValueError):
        parse_execution_profile(json.dumps(payload))


def test_static_validator_rejects_submission_deletion_and_unsafe_output() -> None:
    plan = plan_slurm_script(_profile(), _policy())
    malicious = plan.script_text.replace(
        "srun --mpi=pmi2 vasp_std",
        "sbatch next.sh\nrm victim\nsrun --mpi=pmi2 vasp_std",
    ).replace("slurm-%j.out", "../outside.out")

    codes = {item.code for item in validate_slurm_script(malicious, _policy())}

    assert "SLURM_SCRIPT_FORBIDDEN_TOKEN" in codes
    assert "SLURM_OUTPUT_PATH_NOT_ALLOWED" in codes
    assert "SLURM_SCRIPT_BODY_NOT_ALLOWED" in codes


def test_static_validator_independently_checks_resource_directives() -> None:
    plan = plan_slurm_script(_profile(), _policy())
    oversized = plan.script_text.replace("--nodes=1", "--nodes=9").replace(
        "--ntasks-per-node=64", "--ntasks-per-node=128"
    )

    codes = {item.code for item in validate_slurm_script(oversized, _policy())}

    assert "SLURM_NODE_LIMIT_EXCEEDED" in codes
    assert "SLURM_CORES_PER_NODE_EXCEEDED" in codes


def test_policy_parser_rejects_unknown_fields_and_empty_allowlists() -> None:
    payload = json.loads((FIXTURE / "cluster-policy.json").read_text())
    payload["unexpected"] = True
    with pytest.raises(ValueError):
        parse_cluster_policy(json.dumps(payload))

    payload.pop("unexpected")
    payload["allowed_modules"] = []
    with pytest.raises(ValueError):
        parse_cluster_policy(json.dumps(payload))

    payload["allowed_modules"] = ["intel/oneapi2023.2_impi"]
    payload["allowed_shell_modes"] = ["login", "login"]
    with pytest.raises(ValueError):
        parse_cluster_policy(json.dumps(payload))

    payload["allowed_shell_modes"] = [["login"]]
    with pytest.raises(ValueError):
        parse_cluster_policy(json.dumps(payload))


def test_login_shell_requires_an_explicit_policy_allowlist() -> None:
    profile_payload = json.loads((FIXTURE / "execution-profile.json").read_text())
    policy_payload = json.loads((FIXTURE / "cluster-policy.json").read_text())
    profile_payload["shell_mode"] = "login"
    profile = parse_execution_profile(json.dumps(profile_payload))

    default_policy = parse_cluster_policy(json.dumps(policy_payload))
    rejected = plan_slurm_script(profile, default_policy)
    assert "SLURM_SHELL_MODE_NOT_ALLOWED" in {item.code for item in rejected.diagnostics}

    policy_payload["allowed_shell_modes"] = ["nonlogin", "login"]
    login_policy = parse_cluster_policy(json.dumps(policy_payload))
    accepted = plan_slurm_script(profile, login_policy)

    assert not accepted.has_errors
    assert accepted.script_text.startswith("#!/bin/bash -l\n")
    assert accepted.profile.shell_mode == "login"
    assert accepted.profile.to_dict()["shell_mode"] == "login"
    assert login_policy.to_dict()["allowed_shell_modes"] == ["nonlogin", "login"]

    tampered = accepted.script_text.replace("#!/bin/bash -l", "#!/bin/bash -x", 1)
    assert "SLURM_SCRIPT_SHEBANG_INVALID" in {
        item.code for item in validate_slurm_script(tampered, login_policy)
    }


def test_absolute_posix_executable_requires_exact_policy_allowlist() -> None:
    profile_payload = json.loads((FIXTURE / "execution-profile.json").read_text())
    policy_payload = json.loads((FIXTURE / "cluster-policy.json").read_text())
    executable = "/opt/catex-synthetic/vasp.5.4.4/bin/vasp_std"
    profile_payload["executable"] = executable
    policy_payload["allowed_executables"] = [executable]
    profile = parse_execution_profile(json.dumps(profile_payload))
    policy = parse_cluster_policy(json.dumps(policy_payload))

    plan = plan_slurm_script(profile, policy)

    assert not plan.has_errors
    assert f"srun --mpi=pmi2 {executable}" in plan.script_text

    policy_payload["allowed_executables"] = ["/opt/catex-synthetic/other/vasp_std"]
    mismatched = parse_cluster_policy(json.dumps(policy_payload))
    assert "SLURM_EXECUTABLE_NOT_ALLOWED" in {
        item.code for item in validate_execution_profile(profile, mismatched)
    }


@pytest.mark.parametrize(
    "executable",
    [
        "/opt/vasp/../escape/vasp_std",
        "//server/share/vasp_std",
        "/opt/vasp path/vasp_std",
        "/opt/vasp/vasp_std;sbatch",
        "/opt/vasp/",
        "/",
        "relative/path/vasp_std",
    ],
)
def test_executable_path_grammar_rejects_traversal_and_shell_syntax(executable) -> None:
    payload = json.loads((FIXTURE / "execution-profile.json").read_text())
    payload["executable"] = executable

    with pytest.raises(ValueError):
        parse_execution_profile(json.dumps(payload))
