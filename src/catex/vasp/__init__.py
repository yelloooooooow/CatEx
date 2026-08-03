"""Read-only VASP 5.4.4 input validation and output parsing."""

from catex.vasp.models import ValidationMode, VaspInputValidationReport
from catex.vasp.output import parse_vasp_output
from catex.vasp.output_models import VaspOutputParseReport
from catex.vasp.registry import Vasp544IncarRegistry, vasp544_incar_registry
from catex.vasp.result_document import (
    SUPPORTED_RESULT_FILES,
    VaspResultDocumentError,
    build_vasp_result_document,
)
from catex.vasp.thermochemistry import HarmonicThermochemistryResult, harmonic_thermochemistry
from catex.vasp.validation import validate_vasp_input

__all__ = [
    "SUPPORTED_RESULT_FILES",
    "HarmonicThermochemistryResult",
    "ValidationMode",
    "Vasp544IncarRegistry",
    "VaspInputValidationReport",
    "VaspOutputParseReport",
    "VaspResultDocumentError",
    "build_vasp_result_document",
    "harmonic_thermochemistry",
    "parse_vasp_output",
    "validate_vasp_input",
    "vasp544_incar_registry",
]
