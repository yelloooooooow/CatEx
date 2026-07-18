from __future__ import annotations

import json
from dataclasses import replace

import pytest
from test_catalysis_identities import _approvals, _domain_chain

from catex.catalysis import assess_configuration_readiness
from catex.electronic_structure import (
    ChargePartitionInput,
    ChargePartitionMethod,
    DensityOfStatesInput,
    MagneticMomentInput,
    OrbitalFamily,
    ProjectedDosSeries,
    SpinChannel,
    analyze_charge_partition,
    analyze_density_of_states,
    analyze_magnetism,
    summarize_electronic_structure,
)


def _dos_input(configuration_hash: str) -> DensityOfStatesInput:
    return DensityOfStatesInput(
        dos_id="synthetic-pdos",
        configuration_identity_sha256=configuration_hash,
        fermi_energy_ev=0.0,
        number_of_sites=4,
        energies_ev=(-2.0, -1.0, 0.0, 1.0, 2.0),
        total_density_states_per_ev=(1.0, 3.0, 5.0, 3.0, 1.0),
        spin_up_density_states_per_ev=(0.5, 2.0, 3.0, 2.0, 0.5),
        spin_down_density_states_per_ev=(0.5, 1.0, 2.0, 1.0, 0.5),
        projected_series=(
            ProjectedDosSeries(
                label="site-0-d",
                orbital_family=OrbitalFamily.D,
                site_indices_0based=(0,),
                spin_channel=SpinChannel.TOTAL,
                densities_states_per_ev=(0.0, 1.0, 2.0, 1.0, 0.0),
            ),
            ProjectedDosSeries(
                label="adsorbate-p",
                orbital_family=OrbitalFamily.P,
                site_indices_0based=(2, 3),
                spin_channel=SpinChannel.TOTAL,
                densities_states_per_ev=(1.0, 1.0, 0.5, 0.2, 0.0),
            ),
        ),
        source_sha256s=("b" * 64, "a" * 64),
        parser_name="synthetic-array-adapter-v1",
    )


def _analysis_bundle(configuration_hash: str):
    dos = analyze_density_of_states(
        _dos_input(configuration_hash),
        d_band_window_relative_to_fermi_ev=(-2.0, 2.0),
    )
    magnetism = analyze_magnetism(
        MagneticMomentInput(
            moment_id="synthetic-magnetism",
            configuration_identity_sha256=configuration_hash,
            per_site_moments_mu_b=(1.5, -0.5, 0.1, -0.1),
            active_site_indices_0based=(1, 0),
            source_sha256s=("c" * 64,),
            parser_name="synthetic-outcar-adapter-v1",
        )
    )
    charge = analyze_charge_partition(
        ChargePartitionInput(
            charge_id="synthetic-bader",
            configuration_identity_sha256=configuration_hash,
            method=ChargePartitionMethod.BADER,
            electron_populations=(9.8, 10.1, 3.9, 6.2),
            reference_valence_electrons=(10.0, 10.0, 4.0, 6.0),
            active_site_indices_0based=(0, 1),
            source_sha256s=("d" * 64,),
            parser_name="synthetic-acf-adapter-v1",
        )
    )
    return dos, magnetism, charge


def test_dos_analysis_reports_explicit_numerical_observables() -> None:
    report = analyze_density_of_states(
        _dos_input("1" * 64),
        d_band_window_relative_to_fermi_ev=(-2.0, 2.0),
    )

    assert report.total_density_at_fermi_states_per_ev == pytest.approx(5.0)
    assert report.spin_polarization_at_fermi == pytest.approx(0.2)
    assert report.source_sha256s == ("a" * 64, "b" * 64)
    assert len(report.d_band_moments) == 1
    moment = report.d_band_moments[0]
    assert moment.integrated_weight_states == pytest.approx(4.0)
    assert moment.center_relative_to_fermi_ev == pytest.approx(0.0)
    assert moment.width_ev == pytest.approx(0.5**0.5)
    assert report.manual_interpretation_required is True
    assert report.automatic_scientific_conclusion_performed is False


def test_dos_analysis_is_input_order_stable_for_projected_series() -> None:
    supplied = _dos_input("2" * 64)
    reordered = replace(
        supplied,
        projected_series=tuple(reversed(supplied.projected_series)),
        source_sha256s=tuple(reversed(supplied.source_sha256s)),
    )

    first = analyze_density_of_states(
        supplied,
        d_band_window_relative_to_fermi_ev=(-2.0, 2.0),
    )
    second = analyze_density_of_states(
        reordered,
        d_band_window_relative_to_fermi_ev=(-2.0, 2.0),
    )

    assert second == first


@pytest.mark.parametrize(
    ("change", "message"),
    (
        ({"energies_ev": (-2.0, 0.0, -1.0)}, "strictly increasing"),
        ({"total_density_states_per_ev": (1.0, -1.0, 1.0, 1.0, 1.0)}, "non-negative"),
        ({"spin_down_density_states_per_ev": None}, "supplied together"),
        ({"fermi_energy_ev": 4.0}, "inside the energy grid"),
        ({"source_sha256s": ("not-a-hash",)}, "lowercase SHA256"),
    ),
)
def test_dos_analysis_fails_closed_on_invalid_arrays(change, message: str) -> None:
    supplied = _dos_input("3" * 64)

    with pytest.raises(ValueError, match=message):
        analyze_density_of_states(
            replace(supplied, **change),
            d_band_window_relative_to_fermi_ev=(-2.0, 2.0),
        )


def test_dos_window_and_zero_weight_are_explicit_failures() -> None:
    supplied = _dos_input("4" * 64)
    zero_d = replace(
        supplied.projected_series[0],
        densities_states_per_ev=(0.0, 0.0, 0.0, 0.0, 0.0),
    )

    with pytest.raises(ValueError, match="fully covered"):
        analyze_density_of_states(supplied)
    with pytest.raises(ValueError, match="zero weight"):
        analyze_density_of_states(
            replace(supplied, projected_series=(zero_d,)),
            d_band_window_relative_to_fermi_ev=(-2.0, 2.0),
        )


def test_magnetism_and_charge_keep_sign_conventions_explicit() -> None:
    _, magnetism, charge = _analysis_bundle("5" * 64)

    assert magnetism.total_moment_mu_b == pytest.approx(1.0)
    assert magnetism.absolute_moment_sum_mu_b == pytest.approx(2.2)
    assert magnetism.active_site_indices_0based == (0, 1)
    assert magnetism.active_site_total_moment_mu_b == pytest.approx(1.0)
    assert charge.electron_deficit_by_site_e == pytest.approx((0.2, -0.1, 0.1, -0.2))
    assert charge.total_electron_deficit_e == pytest.approx(0.0)
    assert charge.active_site_electron_deficit_e == pytest.approx(0.1)
    assert charge.positive_deficit_means_electron_loss is True
    assert charge.automatic_oxidation_state_assignment_performed is False


def test_charge_and_magnetism_reject_ambiguous_inputs() -> None:
    with pytest.raises(ValueError, match="valid 0-based"):
        analyze_magnetism(
            MagneticMomentInput(
                moment_id="bad",
                configuration_identity_sha256="6" * 64,
                per_site_moments_mu_b=(1.0,),
                active_site_indices_0based=(1,),
                source_sha256s=("a" * 64,),
            )
        )
    with pytest.raises(ValueError, match="same length"):
        analyze_charge_partition(
            ChargePartitionInput(
                charge_id="bad",
                configuration_identity_sha256="6" * 64,
                method=ChargePartitionMethod.BADER,
                electron_populations=(1.0, 2.0),
                reference_valence_electrons=(1.0,),
                active_site_indices_0based=(0,),
                source_sha256s=("a" * 64,),
            )
        )
    with pytest.raises(ValueError, match="method_label"):
        analyze_charge_partition(
            ChargePartitionInput(
                charge_id="bad-other",
                configuration_identity_sha256="6" * 64,
                method=ChargePartitionMethod.OTHER,
                electron_populations=(1.0,),
                reference_valence_electrons=(1.0,),
                active_site_indices_0based=(0,),
                source_sha256s=("a" * 64,),
            )
        )


def test_summary_requires_reviewed_configuration_and_intact_bound_reports() -> None:
    _, catalyst, site, _, adsorbate, _, configuration = _domain_chain()
    readiness = assess_configuration_readiness(
        catalyst,
        site,
        adsorbate,
        configuration,
        _approvals(catalyst, site, adsorbate, configuration),
    )
    dos, magnetism, charge = _analysis_bundle(configuration.identity_sha256)

    summary = summarize_electronic_structure(
        configuration,
        readiness,
        dos,
        magnetism,
        charge,
    )

    assert summary.configuration_identity_sha256 == configuration.identity_sha256
    assert len(summary.configuration_review_sha256s) == 4
    assert summary.source_sha256s == ("a" * 64, "b" * 64, "c" * 64, "d" * 64)
    assert summary.manual_interpretation_required is True
    assert summary.writes_performed is False
    assert "path" not in json.dumps(summary.to_dict()).lower()
    with pytest.raises(ValueError, match="intact"):
        summarize_electronic_structure(
            configuration,
            readiness,
            replace(dos, total_density_at_fermi_states_per_ev=99.0),
            magnetism,
            charge,
        )
    with pytest.raises(ValueError, match="bound"):
        summarize_electronic_structure(
            configuration,
            readiness,
            analyze_density_of_states(
                _dos_input("f" * 64),
                d_band_window_relative_to_fermi_ev=(-2.0, 2.0),
            ),
            magnetism,
            charge,
        )
    with pytest.raises(ValueError, match="cover exactly"):
        summarize_electronic_structure(
            configuration,
            readiness,
            analyze_density_of_states(
                replace(_dos_input(configuration.identity_sha256), number_of_sites=5),
                d_band_window_relative_to_fermi_ev=(-2.0, 2.0),
            ),
            magnetism,
            charge,
        )
