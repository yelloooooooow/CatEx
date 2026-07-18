"""Source-bound DOS, magnetism, and charge analysis interfaces."""

from catex.electronic_structure.analysis import (
    analyze_charge_partition,
    analyze_density_of_states,
    analyze_magnetism,
    summarize_electronic_structure,
)
from catex.electronic_structure.models import (
    ChargeAnalysisReport,
    ChargePartitionInput,
    ChargePartitionMethod,
    DbandMoment,
    DensityOfStatesAnalysisReport,
    DensityOfStatesInput,
    ElectronicStructureSummary,
    MagneticMomentInput,
    MagnetismAnalysisReport,
    OrbitalFamily,
    ProjectedDosSeries,
    SpinChannel,
)

__all__ = [
    "ChargeAnalysisReport",
    "ChargePartitionInput",
    "ChargePartitionMethod",
    "DbandMoment",
    "DensityOfStatesAnalysisReport",
    "DensityOfStatesInput",
    "ElectronicStructureSummary",
    "MagneticMomentInput",
    "MagnetismAnalysisReport",
    "OrbitalFamily",
    "ProjectedDosSeries",
    "SpinChannel",
    "analyze_charge_partition",
    "analyze_density_of_states",
    "analyze_magnetism",
    "summarize_electronic_structure",
]
