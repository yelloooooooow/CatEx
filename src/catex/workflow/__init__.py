"""Protocol resolution and safe generate-only workflow planning."""

from catex.workflow.materialize import materialize_calculation, plan_calculation
from catex.workflow.models import (
    CalculationPlan,
    KpointsSpecification,
    MaterializationResult,
    ProtocolResolutionReport,
    ResolvedProtocol,
    ReviewState,
    ScientificProtocol,
    SlurmClusterPolicy,
    SlurmExecutionProfile,
    SlurmScriptPlan,
)
from catex.workflow.protocol import (
    parse_scientific_protocol,
    record_protocol_review,
    resolve_protocol,
)
from catex.workflow.slurm import (
    parse_cluster_policy,
    parse_execution_profile,
    plan_slurm_script,
    validate_slurm_script,
)

__all__ = [
    "CalculationPlan",
    "KpointsSpecification",
    "MaterializationResult",
    "ProtocolResolutionReport",
    "ResolvedProtocol",
    "ReviewState",
    "ScientificProtocol",
    "SlurmClusterPolicy",
    "SlurmExecutionProfile",
    "SlurmScriptPlan",
    "materialize_calculation",
    "parse_cluster_policy",
    "parse_execution_profile",
    "parse_scientific_protocol",
    "plan_calculation",
    "plan_slurm_script",
    "record_protocol_review",
    "resolve_protocol",
    "validate_slurm_script",
]
