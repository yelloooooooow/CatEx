"""Conservative SSH/SFTP gateway used only after explicit Web approval gates."""

from __future__ import annotations

import base64
import hashlib
import json
import re
import shlex
import stat
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Any, Protocol

_SAFE_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$")
_HOST = re.compile(r"^[A-Za-z0-9][A-Za-z0-9.:-]{0,252}$")
_USERNAME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$")
_JOB_ID = re.compile(r"^[0-9]+(?:[_+][0-9]+)?$")
_HASH = re.compile(r"^[0-9a-f]{64}$")
_STAGE_FILES = (
    "POSCAR",
    "INCAR",
    "KPOINTS",
    "catex-potcar-metadata.json",
    "slurm.sh",
)
_REMOTE_BUILDER_NAME = "catex-build-potcar.py"
_RESULT_FILES = {
    "OUTCAR": 128 * 1024 * 1024,
    "OSZICAR": 16 * 1024 * 1024,
    "CONTCAR": 16 * 1024 * 1024,
    "vasprun.xml": 128 * 1024 * 1024,
    "catex-manifest.json": 512 * 1024,
    "slurm.sh": 1024 * 1024,
}


class HpcGatewayError(RuntimeError):
    """Safe, user-facing HPC boundary failure."""


@dataclass(frozen=True, slots=True)
class HpcConnectionProfile:
    """Ephemeral connection material; callers must never persist this object."""

    host: str
    port: int
    username: str
    private_key_path: str
    allowed_root: str
    potcar_builder: str | None = None
    potcar_root: str | None = None
    host_key_sha256: str | None = None
    connect_timeout_seconds: int = 15

    def __post_init__(self) -> None:
        if _HOST.fullmatch(self.host) is None:
            raise ValueError("host has an invalid format")
        if not 1 <= self.port <= 65535:
            raise ValueError("port must be between 1 and 65535")
        if _USERNAME.fullmatch(self.username) is None:
            raise ValueError("username has an invalid format")
        root = PurePosixPath(self.allowed_root)
        builder = PurePosixPath(self.potcar_builder) if self.potcar_builder else None
        potcar_root = PurePosixPath(self.potcar_root) if self.potcar_root else None
        if not root.is_absolute() or root == PurePosixPath("/") or ".." in root.parts:
            raise ValueError("allowed_root must be a non-root absolute POSIX path")
        if builder is not None and (not builder.is_absolute() or ".." in builder.parts):
            raise ValueError("potcar_builder must be an absolute POSIX path")
        if potcar_root is not None and (not potcar_root.is_absolute() or ".." in potcar_root.parts):
            raise ValueError("potcar_root must be an absolute POSIX path")
        if self.host_key_sha256 is not None and not re.fullmatch(
            r"SHA256:[A-Za-z0-9+/]{20,60}", self.host_key_sha256
        ):
            raise ValueError("host_key_sha256 has an invalid format")
        if not 3 <= self.connect_timeout_seconds <= 60:
            raise ValueError("connect_timeout_seconds must be between 3 and 60")

    def remote_job_directory(self, run_id: str) -> str:
        if _SAFE_ID.fullmatch(run_id) is None:
            raise ValueError("run_id has an invalid format")
        root = PurePosixPath(self.allowed_root)
        target = root / run_id
        if target.parent != root:
            raise ValueError("remote job directory escaped the allowed root")
        return target.as_posix()


class HpcGateway(Protocol):
    def probe(self, profile: HpcConnectionProfile) -> dict[str, Any]: ...

    def stage(
        self, profile: HpcConnectionProfile, local_run: Path, run_id: str
    ) -> dict[str, Any]: ...

    def submit(
        self, profile: HpcConnectionProfile, run_id: str, plan_sha256: str
    ) -> dict[str, Any]: ...

    def observe(
        self, profile: HpcConnectionProfile, run_id: str, job_id: str
    ) -> dict[str, Any]: ...

    def download_results(
        self,
        profile: HpcConnectionProfile,
        run_id: str,
        destination: Path,
    ) -> dict[str, Any]: ...

    def download_potcar(self, profile: HpcConnectionProfile, run_id: str) -> dict[str, Any]: ...

    def inspect_potcar_metadata(
        self, profile: HpcConnectionProfile, labels: tuple[str, ...]
    ) -> dict[str, Any]: ...


class _PinnedHostKeyPolicy:
    def __init__(self, expected: str):
        self.expected = expected

    def missing_host_key(self, client: Any, hostname: str, key: Any) -> None:
        digest = base64.b64encode(hashlib.sha256(key.asbytes()).digest()).decode().rstrip("=")
        actual = f"SHA256:{digest}"
        if actual != self.expected:
            raise HpcGatewayError("SSH host key fingerprint does not match the approved value")
        client.get_host_keys().add(hostname, key.get_name(), key)


class ParamikoHpcGateway:
    """One-shot operations with pinned/system host keys and fixed commands only."""

    @staticmethod
    def _connect(profile: HpcConnectionProfile) -> Any:
        try:
            import paramiko
        except ImportError as exc:
            raise HpcGatewayError(
                "Paramiko is not installed; install the CatEx hpc optional dependency"
            ) from exc
        key_path = Path(profile.private_key_path).expanduser()
        if not key_path.is_file():
            raise HpcGatewayError("the selected private key file is unavailable")
        client = paramiko.SSHClient()
        client.load_system_host_keys()
        if profile.host_key_sha256:
            client.set_missing_host_key_policy(_PinnedHostKeyPolicy(profile.host_key_sha256))
        else:
            client.set_missing_host_key_policy(paramiko.RejectPolicy())
        try:
            client.connect(
                hostname=profile.host,
                port=profile.port,
                username=profile.username,
                key_filename=str(key_path),
                look_for_keys=False,
                allow_agent=False,
                timeout=profile.connect_timeout_seconds,
                banner_timeout=profile.connect_timeout_seconds,
                auth_timeout=profile.connect_timeout_seconds,
            )
        except Exception as exc:
            client.close()
            raise HpcGatewayError(
                f"SSH connection failed ({type(exc).__name__}); credentials were not retained"
            ) from exc
        return client

    @staticmethod
    def _exec(client: Any, command: str, *, maximum: int = 1024 * 1024) -> bytes:
        _, stdout, stderr = client.exec_command(command, timeout=30)
        output = stdout.read(maximum + 1)
        error = stderr.read(64 * 1024 + 1)
        status = stdout.channel.recv_exit_status()
        if len(output) > maximum or len(error) > 64 * 1024:
            raise HpcGatewayError("remote command output exceeded its safety limit")
        if status != 0:
            raise HpcGatewayError(f"approved remote command failed with exit status {status}")
        return output

    @staticmethod
    def _write_exclusive(sftp: Any, remote_path: str, local_path: Path) -> str:
        digest = hashlib.sha256()
        try:
            with local_path.open("rb") as source, sftp.open(remote_path, "wx") as target:
                while chunk := source.read(1024 * 1024):
                    digest.update(chunk)
                    target.write(chunk)
        except OSError as exc:
            raise HpcGatewayError(
                f"exclusive remote upload failed for {local_path.name} ({type(exc).__name__})"
            ) from exc
        return digest.hexdigest()

    @staticmethod
    def _write_bytes_exclusive(sftp: Any, remote_path: str, content: bytes) -> str:
        try:
            with sftp.open(remote_path, "wx") as target:
                target.write(content)
        except OSError as exc:
            raise HpcGatewayError(f"exclusive remote upload failed ({type(exc).__name__})") from exc
        return hashlib.sha256(content).hexdigest()

    @staticmethod
    def _validate_potcar_build_output(output: bytes, metadata: dict[str, Any]) -> dict[str, Any]:
        try:
            report = json.loads(output.decode("utf-8", errors="strict"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise HpcGatewayError("remote POTCAR builder returned an invalid report") from exc
        datasets = metadata.get("datasets")
        if not isinstance(report, dict) or not isinstance(datasets, list):
            raise HpcGatewayError("remote POTCAR builder report or metadata is invalid")
        expected_labels = [item.get("potential_label") for item in datasets]
        expected_hashes = [item.get("sha256") for item in datasets]
        if (
            report.get("schema_version") != "catex.remote-potcar-build.v1"
            or report.get("datasets") != expected_labels
            or report.get("dataset_sha256") != expected_hashes
            or _HASH.fullmatch(str(report.get("sha256", ""))) is None
            or report.get("overwrite_performed") is not False
            or report.get("deletion_performed") is not False
        ):
            raise HpcGatewayError(
                "remote POTCAR builder report does not match the approved metadata"
            )
        return report

    @staticmethod
    def _mark_potcar_materialized(manifest: dict[str, Any]) -> dict[str, Any]:
        updated = dict(manifest)
        updated["potcar_materialized"] = True
        return updated

    def probe(self, profile: HpcConnectionProfile) -> dict[str, Any]:
        client = self._connect(profile)
        try:
            sftp = client.open_sftp()
            attributes = sftp.stat(profile.allowed_root)
            if not stat.S_ISDIR(attributes.st_mode):
                raise HpcGatewayError("approved remote root is not a directory")
            entries = sftp.listdir_attr(profile.allowed_root)
            potcar_root_exists = None
            if profile.potcar_root:
                potcar_root = sftp.stat(profile.potcar_root)
                if not stat.S_ISDIR(potcar_root.st_mode):
                    raise HpcGatewayError("approved POTCAR root is not a directory")
                potcar_root_exists = True
            return {
                "schema_version": "catex.hpc-probe.v1",
                "connected": True,
                "allowed_root_exists": True,
                "visible_entry_count": len(entries),
                "potcar_builder_mode": "bundled-exclusive-upload",
                "potcar_root_exists": potcar_root_exists,
                "writes_performed": False,
                "commands_executed": False,
                "credentials_retained": False,
            }
        finally:
            client.close()

    def inspect_potcar_metadata(
        self, profile: HpcConnectionProfile, labels: tuple[str, ...]
    ) -> dict[str, Any]:
        if not profile.potcar_root:
            raise HpcGatewayError("an approved POTCAR library root is required")
        unsafe_label = any(_SAFE_ID.fullmatch(label) is None for label in labels)
        if not labels or len(labels) > 32 or unsafe_label:
            raise HpcGatewayError("POTCAR labels are missing or unsafe")
        client = self._connect(profile)
        datasets: list[dict[str, Any]] = []
        try:
            sftp = client.open_sftp()
            for label in labels:
                path = f"{profile.potcar_root.rstrip('/')}/{label}/POTCAR"
                attributes = sftp.stat(path)
                supported_size = 0 < attributes.st_size <= 32 * 1024 * 1024
                if not stat.S_ISREG(attributes.st_mode) or not supported_size:
                    raise HpcGatewayError(f"POTCAR dataset is missing or unsupported: {label}")
                digest = hashlib.sha256()
                header = bytearray()
                with sftp.open(path, "rb") as stream:
                    while chunk := stream.read(1024 * 1024):
                        digest.update(chunk)
                        if len(header) < 256 * 1024:
                            header.extend(chunk[: 256 * 1024 - len(header)])
                text = header.decode("latin-1")
                titel = re.search(r"(?m)^\s*TITEL\s*=\s*(.+?)\s*$", text)
                lexch = re.search(r"(?m)^\s*LEXCH\s*=\s*([^;\s]+)", text)
                zval = re.search(r"(?m)^\s*POMASS\s*=\s*[^;]+;\s*ZVAL\s*=\s*([0-9.Ee+-]+)", text)
                enmax = re.search(r"(?m)^\s*ENMAX\s*=\s*([0-9.Ee+-]+)", text)
                if not all((titel, lexch, zval, enmax)):
                    raise HpcGatewayError(f"POTCAR metadata fields are incomplete: {label}")
                element = label.split("_", 1)[0]
                datasets.append(
                    {
                        "element": element,
                        "potential_label": label,
                        "titel": titel.group(1).strip(),
                        "lexch": lexch.group(1).strip(),
                        "zval": float(zval.group(1)),
                        "enmax_eV": float(enmax.group(1)),
                        "sha256": digest.hexdigest(),
                    }
                )
        finally:
            client.close()
        return {
            "schema_version": "catex.potcar-metadata.v1",
            "potential_family": PurePosixPath(profile.potcar_root).name,
            "datasets": datasets,
            "raw_potcar_returned": False,
            "writes_performed": False,
        }

    def download_potcar(self, profile: HpcConnectionProfile, run_id: str) -> dict[str, Any]:
        remote_directory = profile.remote_job_directory(run_id)
        remote_path = f"{remote_directory}/POTCAR"
        client = self._connect(profile)
        try:
            sftp = client.open_sftp()
            attributes = sftp.stat(remote_path)
            supported_size = 0 < attributes.st_size <= 64 * 1024 * 1024
            if not stat.S_ISREG(attributes.st_mode) or not supported_size:
                raise HpcGatewayError("remote POTCAR is missing, unsupported, or too large")
            with sftp.open(remote_path, "rb") as stream:
                content = stream.read(attributes.st_size + 1)
            if len(content) != attributes.st_size:
                raise HpcGatewayError("remote POTCAR changed while it was being copied")
            return {
                "schema_version": "catex.hpc-potcar-copy.v1",
                "run_id": run_id,
                "filename": "POTCAR",
                "content_base64": base64.b64encode(content).decode("ascii"),
                "sha256": hashlib.sha256(content).hexdigest(),
                "writes_performed_remotely": False,
            }
        finally:
            client.close()

    def stage(self, profile: HpcConnectionProfile, local_run: Path, run_id: str) -> dict[str, Any]:
        remote_directory = profile.remote_job_directory(run_id)
        manifest_path = local_run / "catex-manifest.json"
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        metadata = json.loads(
            (local_run / "catex-potcar-metadata.json").read_text(encoding="utf-8")
        )
        if manifest.get("job_name") != run_id or manifest.get("potcar_materialized") is not False:
            raise HpcGatewayError("local run manifest is not eligible for first remote staging")
        missing = [name for name in _STAGE_FILES if not (local_run / name).is_file()]
        if missing:
            raise HpcGatewayError(f"required local input is missing: {missing[0]}")
        if not profile.potcar_root:
            raise HpcGatewayError("an approved POTCAR library root is required")
        builder_path = Path(__file__).with_name("remote_potcar_builder.py")
        if not builder_path.is_file():
            raise HpcGatewayError("bundled remote POTCAR builder is missing")
        client = self._connect(profile)
        uploaded: dict[str, str] = {}
        try:
            sftp = client.open_sftp()
            try:
                sftp.stat(remote_directory)
            except OSError:
                pass
            else:
                raise HpcGatewayError("remote run directory already exists; overwrite is forbidden")
            sftp.mkdir(remote_directory, mode=0o750)
            for name in _STAGE_FILES:
                local_path = local_run / name
                uploaded[name] = self._write_exclusive(
                    sftp, f"{remote_directory}/{name}", local_path
                )
            uploaded[_REMOTE_BUILDER_NAME] = self._write_exclusive(
                sftp,
                f"{remote_directory}/{_REMOTE_BUILDER_NAME}",
                builder_path,
            )
            command = (
                f"cd -- {shlex.quote(remote_directory)} && python3 {_REMOTE_BUILDER_NAME} "
                f"--potcar-root {shlex.quote(profile.potcar_root)}"
            )
            builder_output = self._exec(client, command, maximum=64 * 1024)
            build_report = self._validate_potcar_build_output(builder_output, metadata)
            potcar = sftp.stat(f"{remote_directory}/POTCAR")
            if not stat.S_ISREG(potcar.st_mode) or potcar.st_size <= 0:
                raise HpcGatewayError("remote POTCAR builder did not create a non-empty POTCAR")
            manifest = self._mark_potcar_materialized(manifest)
            remote_manifest = (
                json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
            ).encode()
            uploaded["catex-manifest.json"] = self._write_bytes_exclusive(
                sftp, f"{remote_directory}/catex-manifest.json", remote_manifest
            )
            return {
                "schema_version": "catex.hpc-stage.v1",
                "run_id": run_id,
                "uploaded_sha256": uploaded,
                "potcar_materialized_on_hpc": True,
                "potcar_sha256": build_report["sha256"],
                "potcar_downloaded": False,
                "new_directory_created": True,
                "overwrite_performed": False,
                "deletion_performed": False,
                "submitted": False,
            }
        finally:
            client.close()

    def submit(
        self, profile: HpcConnectionProfile, run_id: str, plan_sha256: str
    ) -> dict[str, Any]:
        if _HASH.fullmatch(plan_sha256) is None:
            raise ValueError("plan_sha256 has an invalid format")
        remote_directory = profile.remote_job_directory(run_id)
        command = shlex.join(
            [
                "sbatch",
                f"--chdir={remote_directory}",
                "--parsable",
                f"{remote_directory}/slurm.sh",
            ]
        )
        client = self._connect(profile)
        try:
            output = self._exec(client, command, maximum=4096)
        finally:
            client.close()
        text = output.decode("utf-8", errors="strict").strip()
        job_id = text.split(";", 1)[0]
        if _JOB_ID.fullmatch(job_id) is None:
            raise HpcGatewayError("sbatch did not return a supported numeric job id")
        return {
            "schema_version": "catex.hpc-submission.v1",
            "run_id": run_id,
            "job_id": job_id,
            "plan_sha256": plan_sha256,
            "raw_submission_output_sha256": hashlib.sha256(output).hexdigest(),
            "submission_performed": True,
            "overwrite_performed": False,
            "deletion_performed": False,
        }

    def observe(self, profile: HpcConnectionProfile, run_id: str, job_id: str) -> dict[str, Any]:
        profile.remote_job_directory(run_id)
        if _JOB_ID.fullmatch(job_id) is None:
            raise ValueError("job_id has an invalid format")
        client = self._connect(profile)
        try:
            squeue = self._exec(
                client,
                shlex.join(["squeue", "-h", "-j", job_id, "-o", "%i|%T|%M"]),
            )
            if squeue.strip():
                return {
                    "schema_version": "catex.hpc-observation.v1",
                    "source": "squeue",
                    "snapshot": squeue.decode("utf-8", errors="strict"),
                    "commands_executed": True,
                    "writes_performed": False,
                }
            sacct = self._exec(
                client,
                shlex.join(
                    [
                        "sacct",
                        "-n",
                        "-X",
                        "-j",
                        job_id,
                        "--format=JobIDRaw,State,ExitCode,ElapsedRaw",
                        "--parsable2",
                    ]
                ),
            )
            return {
                "schema_version": "catex.hpc-observation.v1",
                "source": "sacct",
                "snapshot": sacct.decode("utf-8", errors="strict"),
                "commands_executed": True,
                "writes_performed": False,
            }
        finally:
            client.close()

    def download_results(
        self,
        profile: HpcConnectionProfile,
        run_id: str,
        destination: Path,
    ) -> dict[str, Any]:
        remote_directory = profile.remote_job_directory(run_id)
        destination.mkdir(parents=False, exist_ok=False)
        downloaded: dict[str, str] = {}
        client = self._connect(profile)
        try:
            sftp = client.open_sftp()
            for name, maximum in _RESULT_FILES.items():
                remote_path = f"{remote_directory}/{name}"
                try:
                    attributes = sftp.stat(remote_path)
                except OSError:
                    continue
                if not stat.S_ISREG(attributes.st_mode) or attributes.st_size > maximum:
                    raise HpcGatewayError(f"remote result is unsupported or too large: {name}")
                digest = hashlib.sha256()
                with (
                    sftp.open(remote_path, "rb") as source,
                    (destination / name).open("xb") as target,
                ):
                    while chunk := source.read(1024 * 1024):
                        digest.update(chunk)
                        target.write(chunk)
                downloaded[name] = digest.hexdigest()
        finally:
            client.close()
        if "OUTCAR" not in downloaded and "OSZICAR" not in downloaded:
            raise HpcGatewayError("no bounded VASP output was available for download")
        return {
            "schema_version": "catex.hpc-download.v1",
            "run_id": run_id,
            "downloaded_sha256": downloaded,
            "potcar_downloaded": False,
            "overwrite_performed": False,
            "deletion_performed": False,
        }
