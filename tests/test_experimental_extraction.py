from __future__ import annotations

import pytest

from catex.experimental import extract_characterization_summary


def test_icp_table_becomes_reviewable_composition_ranges(tmp_path) -> None:
    table = tmp_path / "icp.csv"
    table.write_text(
        "element,atomic_percent,uncertainty\nNi,62,2\nMo,38,2\n",
        encoding="utf-8",
    )

    result = extract_characterization_summary(
        table,
        kind="icp",
        evidence_id="icp-1",
        instrument_info="ICP-OES; three replicate measurements",
    )

    assert result["review_required"] is True
    assert result["metadata"]["instrument_info"].startswith("ICP-OES")
    assert result["composition_constraints"] == [
        {
            "element": "Ni",
            "minimum_atomic_fraction": pytest.approx(0.60),
            "maximum_atomic_fraction": pytest.approx(0.64),
            "scope": "bulk",
            "basis": "total_atomic_fraction",
            "evidence_ids": ["icp-1"],
        },
        {
            "element": "Mo",
            "minimum_atomic_fraction": pytest.approx(0.36),
            "maximum_atomic_fraction": pytest.approx(0.40),
            "scope": "bulk",
            "basis": "total_atomic_fraction",
            "evidence_ids": ["icp-1"],
        },
    ]


def test_xps_peak_table_and_instrument_text_extract_bounded_metadata(tmp_path) -> None:
    table = tmp_path / "xps.csv"
    table.write_text(
        "core_level,assignment,area_fraction\nMo 3d,metal,40\nMo 3d,Mo-O oxide,60\n",
        encoding="utf-8",
    )

    result = extract_characterization_summary(
        table,
        kind="xps",
        evidence_id="xps-1",
        instrument_info="Al Kalpha source",
    )

    constraint = result["local_environment_constraints"][0]
    assert result["metadata"]["xps_source"] == "AlKa"
    assert constraint["element"] == "Mo"
    assert constraint["neighbor_element"] == "O"
    assert constraint["minimum_site_fraction"] == pytest.approx(0.57)
    assert constraint["maximum_site_fraction"] == pytest.approx(0.63)


def test_tem_conclusion_and_common_instrument_fields_are_extracted() -> None:
    result = extract_characterization_summary(
        None,
        kind="tem",
        evidence_id="tem-1",
        conclusion="HRTEM gives d = 2.03 +/- 0.05 angstrom.",
        instrument_info="TEM operated at 200 kV",
    )

    assert result["metadata"]["accelerating_voltage_kv"] == 200
    assert result["lattice_spacing_constraints"] == [
        {
            "d_spacing_angstrom": 2.03,
            "tolerance_angstrom": 0.05,
            "evidence_ids": ["tem-1"],
        }
    ]


def test_xrd_phase_conclusion_suggests_elements_without_unstructured_json() -> None:
    result = extract_characterization_summary(
        None,
        kind="xrd",
        evidence_id="xrd-summary",
        conclusion="All diffraction peaks are indexed to the Ni4Mo phase.",
        instrument_info="Cu Kalpha radiation",
    )

    assert result["metadata"]["reported_phase_formulas"] == ["Ni4Mo"]
    assert result["metadata"]["radiation"] == "CuKa"
    assert result["suggested_elements"] == ["Mo", "Ni"]

    chinese = extract_characterization_summary(
        None,
        kind="xrd",
        evidence_id="xrd-zh",
        conclusion="所有衍射峰均归属于Ni4Mo物相。",
    )
    assert chinese["metadata"]["reported_phase_formulas"] == ["Ni4Mo"]


def test_tem_conclusion_converts_nanometres_to_angstroms() -> None:
    result = extract_characterization_summary(
        None,
        kind="tem",
        evidence_id="tem-nm",
        conclusion="The measured d-spacing = 0.208 +/- 0.004 nm.",
    )

    constraint = result["lattice_spacing_constraints"][0]
    assert constraint["d_spacing_angstrom"] == pytest.approx(2.08)
    assert constraint["tolerance_angstrom"] == pytest.approx(0.04)

    chinese = extract_characterization_summary(
        None,
        kind="tem",
        evidence_id="tem-zh",
        conclusion="HRTEM测得晶面间距d为0.208 nm。",
    )
    assert chinese["lattice_spacing_constraints"][0]["d_spacing_angstrom"] == pytest.approx(2.08)


def test_non_text_image_is_retained_without_inventing_measurements(tmp_path) -> None:
    image = tmp_path / "tem.png"
    image.write_bytes(b"not-an-actual-image")

    result = extract_characterization_summary(
        image,
        kind="tem",
        evidence_id="tem-image",
    )

    assert result["lattice_spacing_constraints"] == []
    assert any("TEM image alone" in item for item in result["notices"])
