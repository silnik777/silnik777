"""Testy domieszek i korekty jakości gazu E (core.blending)."""

import pytest

from core.blending import (
    _wobbe,
    biomethane_compositions,
    group_e_wobbe_limits,
    hydrogen_grade_composition,
    hydrogen_grades,
    max_hydrogen_for_group_e,
    propane_enrichment_for_group_e,
)
from core.composition import GasComposition
from core.methane_number import methane_number

E_GAS = GasComposition.predefined("gaz_E_typowy")


class TestFromMixture:
    def test_matches_blend_with_hydrogen(self):
        """Mieszanie N strumieni = sekwencyjne blendowanie dla 2 strumieni."""
        mix = GasComposition.from_mixture([(E_GAS, 0.8), (GasComposition.pure("H2"), 0.2)])
        seq = E_GAS.blend_with_hydrogen(0.2)
        assert mix.as_dict() == pytest.approx(seq.as_dict())

    def test_three_streams_sum(self):
        bm = GasComposition.predefined("biometan")
        mix = GasComposition.from_mixture(
            [(E_GAS, 0.5), (bm, 0.3), (GasComposition.pure("H2"), 0.2)]
        )
        assert mix.fraction("H2") == pytest.approx(0.2, abs=1e-6)

    def test_bad_sum_raises(self):
        with pytest.raises(ValueError, match="sumować"):
            GasComposition.from_mixture([(E_GAS, 0.5), (GasComposition.pure("H2"), 0.2)])


class TestMaxHydrogen:
    def test_wobbe_never_binds_for_h2(self):
        """Ws czystego H2 ≈ 48 MJ/m³ jest w paśmie E — Wobbe nie ogranicza H2."""
        lim = max_hydrogen_for_group_e(E_GAS)
        assert lim.wobbe_limited_pct == pytest.approx(100.0)

    def test_methane_number_is_the_binding_constraint(self):
        """Bez progu politycznego wiąże liczba metanowa (spada z H2)."""
        lim = max_hydrogen_for_group_e(E_GAS)
        assert lim.binding == "liczba metanowa"
        assert 25.0 < lim.mn_limited_pct < 45.0
        # przy maksymalnym H2 liczba metanowa jest ~na limicie
        blend = E_GAS.blend_with_hydrogen(lim.max_h2_mole_pct / 100.0)
        assert methane_number(blend) == pytest.approx(65.0, abs=0.5)

    def test_policy_threshold_can_govern(self):
        lim = max_hydrogen_for_group_e(E_GAS, h2_policy_mole_pct=10.0)
        assert lim.binding == "próg %H₂"
        assert lim.max_h2_mole_pct == pytest.approx(10.0)

    def test_purity_grade_stream_accepted(self):
        stream = hydrogen_grade_composition("h2_elektrolizer")
        lim = max_hydrogen_for_group_e(E_GAS, h2_stream=stream)
        assert lim.max_h2_mole_pct > 0.0


class TestPropaneEnrichment:
    def test_not_needed_when_compliant(self):
        res = propane_enrichment_for_group_e(E_GAS)
        assert not res.needed
        assert res.propane_mole_pct == 0.0

    def test_restores_wobbe_to_band_edge(self):
        """Gaz o niskim Wobbe: propan przywraca Ws do dolnej granicy pasma E."""
        wobbe_min, _ = group_e_wobbe_limits()
        bm = GasComposition.from_percent(
            biomethane_compositions()["biometan_czesciowo_uzdatniony"]["mole_percent"]
        )
        low = GasComposition.from_mixture([(bm, 0.6), (GasComposition.pure("H2"), 0.4)])
        assert _wobbe(low) < wobbe_min  # scenariusz wymaga korekty
        res = propane_enrichment_for_group_e(low)
        assert res.needed and res.feasible
        assert res.propane_mole_pct > 0.0
        assert res.wobbe_after_mj_per_m3 == pytest.approx(wobbe_min, abs=0.05)

    def test_propane_worsens_methane_number(self):
        """Propan podnosi Wobbe, ale obniża liczbę metanową (uczciwy kompromis)."""
        bm = GasComposition.from_percent(
            biomethane_compositions()["biometan_czesciowo_uzdatniony"]["mole_percent"]
        )
        low = GasComposition.from_mixture([(bm, 0.6), (GasComposition.pure("H2"), 0.4)])
        res = propane_enrichment_for_group_e(low)
        assert res.mn_after < res.mn_before

    def test_infeasible_when_cap_too_small(self):
        bm = GasComposition.from_percent(
            biomethane_compositions()["biometan_czesciowo_uzdatniony"]["mole_percent"]
        )
        low = GasComposition.from_mixture([(bm, 0.6), (GasComposition.pure("H2"), 0.4)])
        res = propane_enrichment_for_group_e(low, max_propane_mole_pct=0.5)
        assert res.needed and not res.feasible


class TestDataLibraries:
    def test_hydrogen_grades_load(self):
        grades = hydrogen_grades()
        assert "h2_idealny" in grades
        assert hydrogen_grade_composition("h2_idealny").h2_mole_percent == pytest.approx(100.0)

    def test_unknown_grade_raises(self):
        with pytest.raises(ValueError, match="Nieznana klasa"):
            hydrogen_grade_composition("nie_ma")

    def test_biomethane_library_load(self):
        lib = biomethane_compositions()
        assert "biometan_sieciowy" in lib
        # każdy skład da się zbudować i jest palny
        for key, item in lib.items():
            comp = GasComposition.from_percent(item["mole_percent"])
            assert comp.is_combustible, key
