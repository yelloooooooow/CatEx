"""Allowlisted Slurm rendering and static validation with no submission function."""

from __future__ import annotations

import hashlib
import json
import re
from typing import Any

from catex.models import Diagnostic, Severity
from catex.workflow.models import SlurmClusterPolicy, SlurmExecutionProfile, SlurmScriptPlan

_IDENTIFIER = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$")
_TOKEN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._+:/-]{0,127}$")
_BASENAME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._+-]{0,63}$")
_PATH_COMPONENT = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._+-]{0,127}$")
_SHELL_MODES = frozenset({"nonlogin", "login"})
_WALLTIME = re.compile(
    r"^(?:(?P<days>\d+)-)?(?P<hours>\d{2}):(?P<minutes>\d{2}):(?P<seconds>\d{2})$"
)
_FORBIDDEN = re.compile(
    r"(?:(?<!#)\bsbatch\b|\bscancel\b|\brm\b|\bdel\b|\brmdir\b|Remove-Item|[;&|`<>$])",
    re.IGNORECASE,
)


def _json_object(text: str, *, label: str) -> dict[str, Any]:
    try:
        value = json.loads(text)
    except json.JSONDecodeError as exc:
        raise ValueError(f"{label} JSON is invalid at line {exc.lineno}") from exc
    if not isinstance(value, dict):
        raise ValueError(f"{label} root must be a JSON object")
    return value


def _safe_identifier(value: Any, *, field: str) -> str:
    if not isinstance(value, str) or not _IDENTIFIER.fullmatch(value):
        raise ValueError(f"{field} must be a safe 1-64 character identifier")
    return value


def _safe_executable(value: Any) -> str:
    if not isinstance(value, str) or len(value) > 512:
        raise ValueError("executable must be an allowlistable basename or absolute POSIX path")
    if _BASENAME.fullmatch(value):
        return value
    if not value.startswith("/") or value.startswith("//"):
        raise ValueError("executable must be an allowlistable basename or absolute POSIX path")
    parts = value.split("/")[1:]
    if not parts or any(
        part in {"", ".", ".."} or _PATH_COMPONENT.fullmatch(part) is None for part in parts
    ):
        raise ValueError("executable must be an allowlistable basename or absolute POSIX path")
    return value


def _positive_int(raw: dict[str, Any], field: str) -> int:
    value = raw.get(field)
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise ValueError(f"{field} must be a positive integer")
    return value


def _string_tuple(raw: dict[str, Any], field: str, *, pattern: re.Pattern[str]) -> tuple[str, ...]:
    value = raw.get(field)
    if not isinstance(value, list) or not value:
        raise ValueError(f"{field} must be a non-empty JSON array")
    if any(not isinstance(item, str) or not pattern.fullmatch(item) for item in value):
        raise ValueError(f"{field} contains an unsafe value")
    if len(set(value)) != len(value):
        raise ValueError(f"{field} must not contain duplicates")
    return tuple(value)


def _executable_tuple(raw: dict[str, Any], field: str) -> tuple[str, ...]:
    value = raw.get(field)
    if not isinstance(value, list) or not value:
        raise ValueError(f"{field} must be a non-empty JSON array")
    try:
        parsed = tuple(_safe_executable(item) for item in value)
    except ValueError as exc:
        raise ValueError(f"{field} contains an unsafe value") from exc
    if len(set(parsed)) != len(parsed):
        raise ValueError(f"{field} must not contain duplicates")
    return parsed


def parse_execution_profile(text: str) -> SlurmExecutionProfile:
    """Parse a strict Slurm profile; no command strings are accepted."""

    raw = _json_object(text, label="execution profile")
    expected = {
        "schema_version",
        "profile_id",
        "job_name",
        "partition",
        "nodes",
        "tasks_per_node",
        "cpus_per_task",
        "walltime",
        "module_loads",
        "executable",
        "mpi_plugin",
        "shell_mode",
    }
    unknown = sorted(set(raw) - expected)
    if unknown:
        raise ValueError(f"unsupported execution profile fields: {', '.join(unknown)}")
    if raw.get("schema_version") != "catex.slurm-execution-profile.v1":
        raise ValueError("execution profile schema must be catex.slurm-execution-profile.v1")
    walltime = raw.get("walltime")
    if not isinstance(walltime, str) or _WALLTIME.fullmatch(walltime) is None:
        raise ValueError("walltime must use [D-]HH:MM:SS")
    executable = _safe_executable(raw.get("executable"))
    module_loads = raw.get("module_loads")
    if not isinstance(module_loads, list):
        raise ValueError("module_loads must be a JSON array")
    if any(not isinstance(item, str) or not _TOKEN.fullmatch(item) for item in module_loads):
        raise ValueError("module_loads contains an unsafe value")
    if len(set(module_loads)) != len(module_loads):
        raise ValueError("module_loads must not contain duplicates")
    mpi_plugin = raw.get("mpi_plugin", "pmi2")
    if not isinstance(mpi_plugin, str) or not _BASENAME.fullmatch(mpi_plugin):
        raise ValueError("mpi_plugin must be an allowlistable token")
    shell_mode = raw.get("shell_mode", "nonlogin")
    if shell_mode not in _SHELL_MODES:
        raise ValueError("shell_mode must be nonlogin or login")
    return SlurmExecutionProfile(
        profile_id=_safe_identifier(raw.get("profile_id"), field="profile_id"),
        job_name=_safe_identifier(raw.get("job_name"), field="job_name"),
        partition=_safe_identifier(raw.get("partition"), field="partition"),
        nodes=_positive_int(raw, "nodes"),
        tasks_per_node=_positive_int(raw, "tasks_per_node"),
        cpus_per_task=_positive_int(raw, "cpus_per_task"),
        walltime=walltime,
        module_loads=tuple(module_loads),
        executable=executable,
        mpi_plugin=mpi_plugin,
        shell_mode=shell_mode,
    )


def parse_cluster_policy(text: str) -> SlurmClusterPolicy:
    """Parse an explicit site policy used only for static validation."""

    raw = _json_object(text, label="cluster policy")
    expected = {
        "schema_version",
        "policy_id",
        "allowed_partitions",
        "allowed_modules",
        "allowed_executables",
        "allowed_mpi_plugins",
        "max_nodes",
        "max_cores_per_node",
        "max_walltime_minutes",
        "allowed_shell_modes",
    }
    unknown = sorted(set(raw) - expected)
    if unknown:
        raise ValueError(f"unsupported cluster policy fields: {', '.join(unknown)}")
    if raw.get("schema_version") != "catex.slurm-cluster-policy.v1":
        raise ValueError("cluster policy schema must be catex.slurm-cluster-policy.v1")
    allowed_shell_modes = raw.get("allowed_shell_modes", ["nonlogin"])
    if (
        not isinstance(allowed_shell_modes, list)
        or not allowed_shell_modes
        or any(
            not isinstance(item, str) or item not in _SHELL_MODES for item in allowed_shell_modes
        )
        or len(set(allowed_shell_modes)) != len(allowed_shell_modes)
    ):
        raise ValueError("allowed_shell_modes must contain unique nonlogin/login values")
    return SlurmClusterPolicy(
        policy_id=_safe_identifier(raw.get("policy_id"), field="policy_id"),
        allowed_partitions=_string_tuple(raw, "allowed_partitions", pattern=_IDENTIFIER),
        allowed_modules=_string_tuple(raw, "allowed_modules", pattern=_TOKEN),
        allowed_executables=_executable_tuple(raw, "allowed_executables"),
        allowed_mpi_plugins=_string_tuple(raw, "allowed_mpi_plugins", pattern=_BASENAME),
        max_nodes=_positive_int(raw, "max_nodes"),
        max_cores_per_node=_positive_int(raw, "max_cores_per_node"),
        max_walltime_minutes=_positive_int(raw, "max_walltime_minutes"),
        allowed_shell_modes=tuple(allowed_shell_modes),
    )


def _walltime_minutes(value: str) -> int:
    match = _WALLTIME.fullmatch(value)
    if match is None:
        raise ValueError("walltime must use [D-]HH:MM:SS")
    days = int(match.group("days") or 0)
    hours = int(match.group("hours"))
    minutes = int(match.group("minutes"))
    seconds = int(match.group("seconds"))
    if minutes >= 60 or seconds >= 60:
        raise ValueError("walltime minutes and seconds must be below 60")
    return days * 1440 + hours * 60 + minutes + (1 if seconds else 0)


def validate_execution_profile(
    profile: SlurmExecutionProfile,
    policy: SlurmClusterPolicy,
) -> tuple[Diagnostic, ...]:
    """Validate resources and every executable/module token against the site policy."""

    diagnostics: list[Diagnostic] = []
    checks = (
        (
            profile.partition in policy.allowed_partitions,
            "SLURM_PARTITION_NOT_ALLOWED",
            "partition",
        ),
        (
            profile.executable in policy.allowed_executables,
            "SLURM_EXECUTABLE_NOT_ALLOWED",
            "executable",
        ),
        (
            profile.mpi_plugin in policy.allowed_mpi_plugins,
            "SLURM_MPI_PLUGIN_NOT_ALLOWED",
            "mpi_plugin",
        ),
        (
            profile.shell_mode in _SHELL_MODES and profile.shell_mode in policy.allowed_shell_modes,
            "SLURM_SHELL_MODE_NOT_ALLOWED",
            "shell_mode",
        ),
    )
    for accepted, code, field in checks:
        if not accepted:
            diagnostics.append(
                Diagnostic(
                    code,
                    Severity.ERROR,
                    "The execution profile value is outside the configured cluster allowlist.",
                    {field: getattr(profile, field)},
                )
            )
    for module in profile.module_loads:
        if module not in policy.allowed_modules:
            diagnostics.append(
                Diagnostic(
                    "SLURM_MODULE_NOT_ALLOWED",
                    Severity.ERROR,
                    "A requested module is outside the configured cluster allowlist.",
                    {"module": module},
                )
            )
    if profile.nodes > policy.max_nodes:
        diagnostics.append(
            Diagnostic(
                "SLURM_NODE_LIMIT_EXCEEDED",
                Severity.ERROR,
                "Requested nodes exceed the configured static limit.",
                {"requested": profile.nodes, "maximum": policy.max_nodes},
            )
        )
    requested_cores = profile.tasks_per_node * profile.cpus_per_task
    if requested_cores > policy.max_cores_per_node:
        diagnostics.append(
            Diagnostic(
                "SLURM_CORES_PER_NODE_EXCEEDED",
                Severity.ERROR,
                "tasks_per_node x cpus_per_task exceeds the node core limit.",
                {"requested": requested_cores, "maximum": policy.max_cores_per_node},
            )
        )
    try:
        walltime_minutes = _walltime_minutes(profile.walltime)
    except ValueError as exc:
        diagnostics.append(Diagnostic("SLURM_WALLTIME_INVALID", Severity.ERROR, str(exc)))
    else:
        if walltime_minutes > policy.max_walltime_minutes:
            diagnostics.append(
                Diagnostic(
                    "SLURM_WALLTIME_LIMIT_EXCEEDED",
                    Severity.ERROR,
                    (
                        f"Requested walltime ({walltime_minutes} minutes) exceeds the "
                        f"configured project limit ({policy.max_walltime_minutes} minutes)."
                    ),
                    {
                        "requested_minutes": walltime_minutes,
                        "maximum_minutes": policy.max_walltime_minutes,
                    },
                )
            )
    return tuple(diagnostics)


def render_slurm_script(profile: SlurmExecutionProfile) -> str:
    """Render a fixed command grammar. This function never invokes a process."""

    if profile.shell_mode not in _SHELL_MODES:
        raise ValueError("shell_mode must be nonlogin or login")
    shebang = "#!/bin/bash -l" if profile.shell_mode == "login" else "#!/bin/bash"
    lines = [
        shebang,
        f"#SBATCH --job-name={profile.job_name}",
        f"#SBATCH --partition={profile.partition}",
        f"#SBATCH --nodes={profile.nodes}",
        f"#SBATCH --ntasks-per-node={profile.tasks_per_node}",
        f"#SBATCH --cpus-per-task={profile.cpus_per_task}",
        f"#SBATCH --time={profile.walltime}",
        "#SBATCH --output=slurm-%j.out",
        "set -euo pipefail",
        "module purge",
    ]
    lines.extend(f"module load {module}" for module in profile.module_loads)
    lines.extend(("export OMP_NUM_THREADS=1", "export MKL_NUM_THREADS=1"))
    lines.append(f"srun --mpi={profile.mpi_plugin} {profile.executable}")
    return "\n".join(lines) + "\n"


def validate_slurm_script(text: str, policy: SlurmClusterPolicy) -> tuple[Diagnostic, ...]:
    """Reject arbitrary shell and accept only the renderer's small grammar."""

    diagnostics: list[Diagnostic] = []
    if _FORBIDDEN.search(text):
        diagnostics.append(
            Diagnostic(
                "SLURM_SCRIPT_FORBIDDEN_TOKEN",
                Severity.ERROR,
                "The script contains submission, deletion, redirection, or shell-control syntax.",
            )
        )
    lines = [line for line in text.splitlines() if line]
    shebang_modes = {"#!/bin/bash": "nonlogin", "#!/bin/bash -l": "login"}
    shell_mode = shebang_modes.get(lines[0]) if lines else None
    if shell_mode is None:
        diagnostics.append(
            Diagnostic(
                "SLURM_SCRIPT_SHEBANG_INVALID",
                Severity.ERROR,
                "Expected the fixed non-login or login Bash shebang.",
            )
        )
    elif shell_mode not in policy.allowed_shell_modes:
        diagnostics.append(
            Diagnostic(
                "SLURM_SHELL_MODE_NOT_ALLOWED",
                Severity.ERROR,
                "The script shell mode is outside the configured cluster allowlist.",
                {"shell_mode": shell_mode},
            )
        )
    allowed_directives = {
        "job-name",
        "partition",
        "nodes",
        "ntasks-per-node",
        "cpus-per-task",
        "time",
        "output",
    }
    seen: set[str] = set()
    directive_values: dict[str, str] = {}
    body_started = False
    for line in lines[1:]:
        if line.startswith("#SBATCH --"):
            if body_started or "=" not in line:
                diagnostics.append(
                    Diagnostic(
                        "SLURM_DIRECTIVE_INVALID",
                        Severity.ERROR,
                        "Slurm directives must precede the body and use --name=value.",
                        {"line": line},
                    )
                )
                continue
            name, value = line[len("#SBATCH --") :].split("=", 1)
            if name not in allowed_directives or name in seen:
                diagnostics.append(
                    Diagnostic(
                        "SLURM_DIRECTIVE_NOT_ALLOWED",
                        Severity.ERROR,
                        "The directive is unknown or duplicated.",
                        {"directive": name},
                    )
                )
            elif name in allowed_directives:
                directive_values[name] = value
            seen.add(name)
            if name == "output" and value != "slurm-%j.out":
                diagnostics.append(
                    Diagnostic(
                        "SLURM_OUTPUT_PATH_NOT_ALLOWED",
                        Severity.ERROR,
                        "Output must use the local slurm-%j.out filename.",
                    )
                )
            continue
        body_started = True
        if line in {
            "set -euo pipefail",
            "module purge",
            "export OMP_NUM_THREADS=1",
            "export MKL_NUM_THREADS=1",
        }:
            continue
        if line.startswith("module load "):
            module = line.removeprefix("module load ")
            if module not in policy.allowed_modules:
                diagnostics.append(
                    Diagnostic(
                        "SLURM_SCRIPT_BODY_NOT_ALLOWED",
                        Severity.ERROR,
                        "The module command is outside the configured allowlist.",
                        {"line": line},
                    )
                )
            continue
        match = re.fullmatch(r"srun --mpi=([A-Za-z0-9._+-]+) (\S+)", line)
        try:
            executable = _safe_executable(match.group(2)) if match else None
        except ValueError:
            executable = None
        if (
            match
            and match.group(1) in policy.allowed_mpi_plugins
            and executable in policy.allowed_executables
        ):
            continue
        diagnostics.append(
            Diagnostic(
                "SLURM_SCRIPT_BODY_NOT_ALLOWED",
                Severity.ERROR,
                "The script body contains a command outside the fixed grammar.",
                {"line": line},
            )
        )
    missing = sorted(allowed_directives - seen)
    if missing:
        diagnostics.append(
            Diagnostic(
                "SLURM_DIRECTIVE_MISSING",
                Severity.ERROR,
                "The generated script is missing required directives.",
                {"directives": missing},
            )
        )
    job_name = directive_values.get("job-name")
    if job_name is not None and not _IDENTIFIER.fullmatch(job_name):
        diagnostics.append(
            Diagnostic(
                "SLURM_JOB_NAME_INVALID",
                Severity.ERROR,
                "The job name is outside the fixed safe-token grammar.",
            )
        )
    partition = directive_values.get("partition")
    if partition is not None and partition not in policy.allowed_partitions:
        diagnostics.append(
            Diagnostic(
                "SLURM_PARTITION_NOT_ALLOWED",
                Severity.ERROR,
                "The script partition is outside the configured allowlist.",
            )
        )
    resource_values: dict[str, int] = {}
    for name in ("nodes", "ntasks-per-node", "cpus-per-task"):
        value = directive_values.get(name)
        if value is None:
            continue
        try:
            parsed = int(value)
        except ValueError:
            parsed = 0
        if parsed <= 0 or str(parsed) != value:
            diagnostics.append(
                Diagnostic(
                    "SLURM_RESOURCE_DIRECTIVE_INVALID",
                    Severity.ERROR,
                    "Resource directives must contain canonical positive integers.",
                    {"directive": name},
                )
            )
        else:
            resource_values[name] = parsed
    if resource_values.get("nodes", 0) > policy.max_nodes:
        diagnostics.append(
            Diagnostic(
                "SLURM_NODE_LIMIT_EXCEEDED",
                Severity.ERROR,
                "The script exceeds the configured node limit.",
            )
        )
    cores = resource_values.get("ntasks-per-node", 0) * resource_values.get("cpus-per-task", 0)
    if cores > policy.max_cores_per_node:
        diagnostics.append(
            Diagnostic(
                "SLURM_CORES_PER_NODE_EXCEEDED",
                Severity.ERROR,
                "The script exceeds the configured core limit.",
            )
        )
    walltime = directive_values.get("time")
    if walltime is not None:
        try:
            requested_minutes = _walltime_minutes(walltime)
        except ValueError:
            diagnostics.append(
                Diagnostic(
                    "SLURM_WALLTIME_INVALID",
                    Severity.ERROR,
                    "The script walltime is invalid.",
                )
            )
        else:
            if requested_minutes > policy.max_walltime_minutes:
                diagnostics.append(
                    Diagnostic(
                        "SLURM_WALLTIME_LIMIT_EXCEEDED",
                        Severity.ERROR,
                        "The script exceeds the configured walltime limit.",
                    )
                )
    for required_body_line in (
        "set -euo pipefail",
        "module purge",
        "export OMP_NUM_THREADS=1",
        "export MKL_NUM_THREADS=1",
    ):
        if lines.count(required_body_line) != 1:
            diagnostics.append(
                Diagnostic(
                    "SLURM_SCRIPT_PREAMBLE_INVALID",
                    Severity.ERROR,
                    "The fixed safety preamble must occur exactly once.",
                    {"line": required_body_line},
                )
            )
    if text.count("srun ") != 1:
        diagnostics.append(
            Diagnostic(
                "SLURM_SRUN_COUNT_INVALID",
                Severity.ERROR,
                "Exactly one allowlisted srun command is required.",
            )
        )
    return tuple(diagnostics)


def plan_slurm_script(
    profile: SlurmExecutionProfile,
    policy: SlurmClusterPolicy,
) -> SlurmScriptPlan:
    """Render and statically validate without calling Slurm or a shell."""

    script = render_slurm_script(profile)
    diagnostics = validate_execution_profile(profile, policy) + validate_slurm_script(
        script, policy
    )
    return SlurmScriptPlan(
        profile=profile,
        policy_id=policy.policy_id,
        script_text=script,
        script_sha256=hashlib.sha256(script.encode("utf-8")).hexdigest(),
        diagnostics=diagnostics,
    )
