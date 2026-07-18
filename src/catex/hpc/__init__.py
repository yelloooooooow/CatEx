"""Explicit HPC-boundary helpers with no SSH, scheduler command, or write implementation."""

from catex.hpc.models import PotcarMetadataExtractionReport
from catex.hpc.potcar_metadata import extract_potcar_metadata, metadata_document
from catex.hpc.run_binding import (
    parse_submission_receipt,
    parse_submission_receipt_path,
    validate_run_binding,
)
from catex.hpc.run_binding_models import (
    RunBindingReport,
    RunBindingStatus,
    RunProtocolIdentity,
    SubmissionReceipt,
    SubmissionReceiptParseReport,
)
from catex.hpc.slurm_models import (
    FailureCategory,
    RestartAssessment,
    RestartDecision,
    SlurmJobObservation,
    SlurmJobState,
    SlurmSnapshotReport,
    SlurmSnapshotSource,
    VaspRestartEvidence,
)
from catex.hpc.slurm_observation import (
    assess_restart,
    parse_slurm_snapshot,
    parse_slurm_snapshot_path,
)

__all__ = [
    "FailureCategory",
    "PotcarMetadataExtractionReport",
    "RestartAssessment",
    "RestartDecision",
    "RunBindingReport",
    "RunBindingStatus",
    "RunProtocolIdentity",
    "SlurmJobObservation",
    "SlurmJobState",
    "SlurmSnapshotReport",
    "SlurmSnapshotSource",
    "SubmissionReceipt",
    "SubmissionReceiptParseReport",
    "VaspRestartEvidence",
    "assess_restart",
    "extract_potcar_metadata",
    "metadata_document",
    "parse_slurm_snapshot",
    "parse_slurm_snapshot_path",
    "parse_submission_receipt",
    "parse_submission_receipt_path",
    "validate_run_binding",
]
