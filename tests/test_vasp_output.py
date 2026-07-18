from __future__ import annotations

import math
from pathlib import Path

import pytest

from catex.vasp.output import _float, parse_vasp_output
from catex.vasp.output_models import ConvergenceState, ParseConfidence, VaspRunOutcome

FIXTURES = Path(__file__).parent / "fixtures" / "synthetic" / "vasp_output"


def test_parse_normal_relaxation_with_provenance() -> None:
    report = parse_vasp_output(FIXTURES / "normal")

    assert report.status == "normal"
    assert report.scientifically_complete is True
    assert report.detected_vasp_version == "5.4.4"
    assert report.termination.outcome is VaspRunOutcome.NORMAL
    assert report.termination.normal_footer_found is True
    assert report.convergence.electronic is ConvergenceState.CONVERGED
    assert report.convergence.ionic is ConvergenceState.CONVERGED
    assert report.convergence.ionic_steps_completed == 2
    assert report.convergence.final_electronic_step == 1
    assert len(report.artifacts) == 2
    assert all(len(artifact.sha256) == 64 for artifact in report.artifacts)

    assert report.energy is not None
    assert report.energy.free_energy_ev == pytest.approx(-10.25)
    assert report.energy.energy_without_entropy_ev == pytest.approx(-10.24)
    assert report.energy.sigma_zero_energy_ev == pytest.approx(-10.245)
    assert report.energy.ionic_step == 2
    assert report.energy.confidence is ParseConfidence.HIGH
    assert {item.parser_rule for item in report.energy.evidence} == {
        "outcar.final_free_energy_block",
        "oszicar.final_ionic_summary",
    }

    assert report.forces is not None
    assert report.forces.ionic_step == 2
    assert report.forces.maximum_atom_index_1based == 1
    assert report.forces.maximum_norm_ev_per_angstrom == pytest.approx(math.sqrt(0.0013))
    assert report.forces.vectors_ev_per_angstrom[1] == pytest.approx((-0.02, -0.03, 0.0))

    assert report.magnetization is not None
    projected = report.magnetization.projected_components[0]
    assert projected.component == "x"
    assert projected.site_projected_totals_mub == pytest.approx((0.9, 0.8))
    assert projected.projected_sum_mub == pytest.approx(1.7)
    assert report.magnetization.cell_moment_mub == pytest.approx((2.0,))
    assert projected.projected_sum_mub != report.magnetization.cell_moment_mub[0]

    payload = report.to_dict()
    assert payload["schema_version"] == "catex.vasp-output-parse.v1"
    assert payload["scientifically_complete"] is True
    assert "not interchangeable" in payload["magnetization"]["interpretation"]


def test_normal_footer_with_nelm_exhaustion_is_unconverged() -> None:
    report = parse_vasp_output(FIXTURES / "unconverged")

    assert report.status == "unconverged"
    assert report.scientifically_complete is False
    assert report.convergence.electronic is ConvergenceState.NOT_CONVERGED
    assert report.convergence.ionic is ConvergenceState.NOT_APPLICABLE
    assert report.termination.normal_footer_found is True
    assert "VASP_RUN_UNCONVERGED" in {item.code for item in report.diagnostics}
    assert report.has_errors is True


def test_truncated_output_keeps_only_complete_force_block() -> None:
    report = parse_vasp_output(FIXTURES / "truncated")

    assert report.status == "truncated"
    assert report.energy is not None
    assert report.energy.free_energy_ev == pytest.approx(-3.1)
    assert report.energy.confidence is ParseConfidence.MEDIUM
    assert report.forces is not None
    assert report.forces.ionic_step == 1
    assert report.forces.confidence is ParseConfidence.MEDIUM
    assert report.convergence.electronic is ConvergenceState.UNKNOWN
    codes = {item.code for item in report.diagnostics}
    assert "VASP_OUTPUT_TRUNCATED_OR_RUNNING" in codes
    assert "OUTCAR_FORCE_BLOCK_INCOMPLETE" in codes


def test_fatal_marker_takes_precedence_over_missing_footer() -> None:
    report = parse_vasp_output(FIXTURES / "failed")

    assert report.status == "failed"
    assert report.termination.fatal_error_codes == ("VASP_INTERNAL_ERROR",)
    assert report.termination.confidence is ParseConfidence.HIGH
    assert report.has_errors is True
    assert report.energy is None
    assert "VASP_RUN_FAILED" in {item.code for item in report.diagnostics}


def test_oszicar_only_fallback_has_reduced_confidence(tmp_path: Path) -> None:
    text = (FIXTURES / "normal" / "OSZICAR").read_text(encoding="utf-8")
    (tmp_path / "OSZICAR").write_text(text, encoding="utf-8")

    report = parse_vasp_output(tmp_path)

    assert report.status == "truncated"
    assert report.detected_vasp_version is None
    assert report.energy is not None
    assert report.energy.free_energy_ev == pytest.approx(-10.25)
    assert report.energy.energy_without_entropy_ev is None
    assert report.energy.confidence is ParseConfidence.MEDIUM
    assert report.magnetization is not None
    assert report.magnetization.projected_components == ()
    assert report.magnetization.cell_moment_mub == pytest.approx((2.0,))
    assert "OUTCAR_MISSING" in {item.code for item in report.diagnostics}


@pytest.mark.parametrize("kind", ["missing", "file", "empty"])
def test_missing_or_empty_outputs_are_unknown(tmp_path: Path, kind: str) -> None:
    target = tmp_path / "target"
    if kind == "file":
        target.write_text("not a directory", encoding="utf-8")
    elif kind == "empty":
        target.mkdir()
        (target / "OUTCAR").write_text("", encoding="utf-8")
        (target / "OSZICAR").write_text("", encoding="utf-8")

    report = parse_vasp_output(target)

    assert report.status == "unknown"
    assert report.scientifically_complete is False
    assert report.has_errors is True


def test_noncollinear_components_and_vector_cell_moment(tmp_path: Path) -> None:
    blocks = []
    for component, total in (("x", 0.5), ("y", -0.2), ("z", 1.1)):
        blocks.append(
            f"""magnetization ({component})
 # of ion       s       p       d       tot
 --------------------------------------------------
 1  0.0  0.0  {total:.3f}  {total:.3f}
 --------------------------------------------------
 tot  0.0  0.0  {total:.3f}  {total:.3f}
"""
        )
    outcar = f"""vasp.5.4.4
 NIONS = 1
 NELM = 10
 NSW = 0
 IBRION = -1
 Iteration 1(1)
 aborting loop because EDIFF is reached
 free energy TOTEN = -2.000000 eV
 energy without entropy= -1.990000 energy(sigma->0) = -1.995000
{"".join(blocks)}General timing and accounting informations for this job:
"""
    (tmp_path / "OUTCAR").write_text(outcar, encoding="utf-8")
    (tmp_path / "OSZICAR").write_text(
        "1 F= -2.000000 E0= -1.995000 d E = -2.0 mag= 0.5 -0.2 1.1\n",
        encoding="utf-8",
    )

    report = parse_vasp_output(tmp_path)

    assert report.status == "normal"
    assert report.magnetization is not None
    assert [item.component for item in report.magnetization.projected_components] == [
        "x",
        "y",
        "z",
    ]
    assert report.magnetization.cell_moment_mub == pytest.approx((0.5, -0.2, 1.1))
    assert report.magnetization.confidence is ParseConfidence.HIGH


def test_version_warning_energy_disagreement_and_unknown_convergence(tmp_path: Path) -> None:
    (tmp_path / "OUTCAR").write_text(
        """vasp.6.4.3
NIONS = 1
free energy TOTEN = -1.000000 eV
energy without entropy= -0.990000 energy(sigma->0) = -0.995000
General timing and accounting informations for this job:
""",
        encoding="utf-8",
    )
    (tmp_path / "OSZICAR").write_text("1 F= -1.100000 E0= -1.095000 d E = -1.1\n", encoding="utf-8")

    report = parse_vasp_output(tmp_path)
    codes = {item.code for item in report.diagnostics}

    assert report.status == "normal"
    assert report.scientifically_complete is False
    assert report.energy is not None
    assert report.energy.confidence is ParseConfidence.LOW
    assert "VASP_VERSION_OUTSIDE_TARGET" in codes
    assert "ENERGY_SOURCE_DISAGREEMENT" in codes
    assert "VASP_CONVERGENCE_UNKNOWN" in codes


def test_invalid_encoding_and_incomplete_magnetization_are_reported(tmp_path: Path) -> None:
    content = b"""NIONS = 2
NELM = 2
NSW = 0
IBRION = -1
Iteration 1(1)
aborting loop because EDIFF is reached
magnetization (x)
# of ion s p d tot
1 0 0 0 0.1
\xff
"""
    (tmp_path / "OUTCAR").write_bytes(content)

    report = parse_vasp_output(tmp_path)
    codes = {item.code for item in report.diagnostics}

    assert report.status == "truncated"
    assert report.magnetization is None
    assert "VASP_OUTPUT_DECODING_REPLACED" in codes
    assert "OUTCAR_MAGNETIZATION_BLOCK_INCOMPLETE" in codes
    assert "VASP_VERSION_NOT_DETECTED" in codes


@pytest.mark.parametrize(
    ("marker", "code"),
    [
        ("BRMIX: very serious problems", "BRMIX_FAILURE"),
        ("ZBRENT: fatal error", "ZBRENT_FAILURE"),
        ("ERROR FEXCP: supplied exchange-correlation table", "FEXCP_FAILURE"),
        ("segmentation fault", "SEGMENTATION_FAULT"),
        ("MPI_ABORT was invoked", "MPI_ABORT"),
        ("forrtl: severe (174): SIGSEGV", "FORTRAN_RUNTIME_FAILURE"),
    ],
)
def test_known_fatal_markers_are_coded(tmp_path: Path, marker: str, code: str) -> None:
    (tmp_path / "OUTCAR").write_text(
        f"vasp.5.4.4\n{marker}\nGeneral timing and accounting informations for this job:\n",
        encoding="utf-8",
    )

    report = parse_vasp_output(tmp_path)

    assert report.status == "failed"
    assert code in report.termination.fatal_error_codes


def test_float_parser_supports_fortran_exponents_and_rejects_nonfinite() -> None:
    assert _float("-.123D+02") == pytest.approx(-12.3)
    assert _float("not-a-number") is None
    assert _float("NaN") is None


def test_vibration_modes_criteria_and_completion_reason_are_exposed(tmp_path: Path) -> None:
    (tmp_path / "OUTCAR").write_text(
        """vasp.5.4.4
 NIONS = 1   NELM = 60   NSW = 1   IBRION = 5
 EDIFF = 1E-06   EDIFFG = -2E-02
 Iteration    1(   1)
 aborting loop because EDIFF is reached
 free  energy   TOTEN  =      -10.000000 eV
 energy  without entropy=     -9.990000  energy(sigma->0) = -9.995000
   1 f  =   10.000000 THz   62.831853 2PiTHz  333.5641 cm-1   41.3567 meV
   2 f/i=    1.000000 THz    6.283185 2PiTHz   33.3564 cm-1    4.1357 meV
 General timing and accounting informations for this job:
""",
        encoding="utf-8",
    )

    report = parse_vasp_output(tmp_path)
    payload = report.to_dict()

    assert report.scientifically_complete is True
    assert payload["completion_reason"] == "requested_calculation_completed"
    assert payload["convergence"]["calculation_type"] == "vibration"
    assert payload["convergence"]["criteria"] == {
        "EDIFF_eV": pytest.approx(1e-6),
        "EDIFFG_eV_per_angstrom": pytest.approx(-0.02),
        "NELM": 60,
        "NSW": 1,
        "IBRION": 5,
    }
    assert payload["vibrations"]["mode_count"] == 2
    assert payload["vibrations"]["imaginary_mode_count"] == 1
    assert payload["vibrations"]["zero_point_energy_eV"] == pytest.approx(0.02067835)
