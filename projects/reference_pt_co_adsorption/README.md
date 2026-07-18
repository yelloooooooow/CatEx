# Generic Pt/CO integration reference

This is a synthetic, non-Paper-4 acceptance case for the shared CatEx core. It is not a
literature reproduction and none of its numerical values may be cited as research data.

The executable acceptance test is `tests/test_nonpaper4_end_to_end.py`. It covers one
reviewed vacuum transformation, catalyst/site/adsorbate identities, rule-based adsorption
placement, configuration deduplication, the four-identity readiness gate, multi-spin VASP
protocol planning, a balanced adsorption reaction, reviewed synthetic VASP-energy binding,
thermochemical correction, and DOS/magnetism/charge summaries.

The case deliberately uses a simple Pt slab and CO adsorption so it cannot inherit the DAC,
metal-pair, or CO2RR assumptions of Paper 4. All output artifacts used by the test are generated
under pytest's temporary directory. The test writes no calculation inputs, submits no job, and
does not contact an HPC system.

Acceptance criteria:

- every structural and scientific identity is hash-bound and explicitly reviewed;
- the reaction is element- and charge-balanced and uses explicit reference states;
- energies are accepted synthetic fixtures from one compatible energy family;
- electronic observables remain numerical summaries requiring human interpretation;
- no Paper-4-specific catalyst, reaction, path, credential, or HPC configuration is required.
