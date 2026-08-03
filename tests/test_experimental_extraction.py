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
    assert result["metadata"]["automatic_extraction"]["method"] == "transparent-rule-parser-v2"
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


def test_icp_conclusion_becomes_composition_ranges_without_a_table() -> None:
    result = extract_characterization_summary(
        None,
        kind="icp",
        evidence_id="icp-prose",
        conclusion="ICP-OES结果\uff1aNi含量为62 ± 2 at.%\uff0cMo含量为38 ± 2 at.% 。",
    )

    assert [(item["element"], item["scope"]) for item in result["composition_constraints"]] == [
        ("Ni", "bulk"),
        ("Mo", "bulk"),
    ]
    assert result["composition_constraints"][0]["minimum_atomic_fraction"] == pytest.approx(0.60)
    assert result["composition_constraints"][0]["maximum_atomic_fraction"] == pytest.approx(0.64)
    assert "No composition table was recognized" not in result["notices"]

    metal_normalized = extract_characterization_summary(
        None,
        kind="icp",
        evidence_id="icp-metal-normalized",
        conclusion="Ni: 91.45 metal at.% Mo: 8.55 metal at.%",
    )
    assert [item["element"] for item in metal_normalized["composition_constraints"]] == [
        "Ni",
        "Mo",
    ]
    assert all(
        item["basis"] == "metal_normalized_atomic_fraction"
        for item in metal_normalized["composition_constraints"]
    )


def test_eds_element_ratio_is_normalized_from_conclusion() -> None:
    result = extract_characterization_summary(
        None,
        kind="eds",
        evidence_id="eds-ratio",
        conclusion="EDS面扫显示 Ni:Mo = 4:1\uff0c分布整体均匀。",
    )

    assert [item["element"] for item in result["composition_constraints"]] == ["Ni", "Mo"]
    assert all(
        item["basis"] == "metal_normalized_atomic_fraction"
        for item in result["composition_constraints"]
    )
    assert result["composition_constraints"][0]["minimum_atomic_fraction"] == pytest.approx(0.76)
    assert result["composition_constraints"][0]["maximum_atomic_fraction"] == pytest.approx(0.84)


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


def test_xps_quantified_chinese_conclusion_extracts_surface_environment() -> None:
    result = extract_characterization_summary(
        None,
        kind="xps",
        evidence_id="xps-prose",
        conclusion="XPS拟合结果显示Mo\u2013O组分占Mo 3d总峰面积的60%。",
    )

    constraint = result["local_environment_constraints"][0]
    assert constraint["element"] == "Mo"
    assert constraint["scope"] == "surface"
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

    substrate_card = extract_characterization_summary(
        None,
        kind="xrd",
        evidence_id="xrd-pdf-card",
        conclusion=(
            "衍射峰主要来自Ni网基底\uff1b基底对应PDF #04-0850\uff1b"
            "没有检测到可明确归属于其他Ni或Mo物种的衍射峰。"
        ),
    )
    assert "reported_phase_formulas" not in substrate_card["metadata"]


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
