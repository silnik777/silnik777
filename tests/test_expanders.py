"""Testy modułu ekspanderów (core.expanders) — bilanse energii i fizyka."""

import pytest

from core.composition import GasComposition
from core.expanders import (
    expand,
    expander_technologies,
    isenthalpic_outlet_temperature_k,
    selection_matrix,
)
from core.gas_properties import compute_properties
from core.units import bar_to_pa

CH4 = GasComposition.pure("CH4")
E_GAS = GasComposition.predefined("gaz_E_typowy")
T_IN = 293.15


class TestIsenthalpicJT:
    def test_methane_cools_on_throttling(self):
        """CH4 55→17 bar od 20 °C: ochłodzenie ~14–20 K (μ_JT ≈ 0,4–0,5 K/bar)."""
        t_out = isenthalpic_outlet_temperature_k(CH4, bar_to_pa(55), T_IN, bar_to_pa(17))
        dt = T_IN - t_out
        assert 13.0 < dt < 21.0

    def test_hydrogen_warms_on_throttling(self):
        """H2 ma ujemny μ_JT przy otoczeniu — dławienie lekko podgrzewa."""
        t_out = isenthalpic_outlet_temperature_k(
            GasComposition.pure("H2"), bar_to_pa(55), T_IN, bar_to_pa(17)
        )
        assert t_out > T_IN

    def test_enthalpy_conserved(self):
        """Definicja dławienia: h(p1,T1) = h(p2,T2) z dokładnością flashu."""
        from core.cold_reduction import _enthalpy

        t_out = isenthalpic_outlet_temperature_k(E_GAS, bar_to_pa(55), T_IN, bar_to_pa(17))
        h1 = _enthalpy(E_GAS, bar_to_pa(55), T_IN)
        h2 = _enthalpy(E_GAS, bar_to_pa(17), t_out)
        assert h2 == pytest.approx(h1, rel=1e-6)


class TestExpansion:
    def test_energy_balance(self):
        """w = h1 − h2 (bilans energii maszyny przepływowej)."""
        from core.cold_reduction import _enthalpy

        res = expand(CH4, bar_to_pa(55), T_IN, bar_to_pa(17), eta=0.8)
        h1 = _enthalpy(CH4, bar_to_pa(55), T_IN)
        h2 = _enthalpy(CH4, bar_to_pa(17), res.temperature_out_k)
        assert res.work_j_per_kg == pytest.approx(h1 - h2, rel=1e-6)

    def test_eta1_ideal_gas_temperature(self):
        """η=1, niskie p: T2s ≈ T1·r^((γ−1)/γ) — ekspansja izentropowa."""
        res = expand(CH4, bar_to_pa(3), T_IN, bar_to_pa(1), eta=1.0)
        gamma = compute_properties(CH4, bar_to_pa(3), T_IN).cp_over_cv
        t2s = T_IN * (1.0 / 3.0) ** ((gamma - 1.0) / gamma)
        assert res.temperature_expander_out_k == pytest.approx(t2s, rel=0.02)

    def test_work_scales_with_eta(self):
        w1 = expand(CH4, bar_to_pa(55), T_IN, bar_to_pa(17), eta=1.0).work_j_per_kg
        w08 = expand(CH4, bar_to_pa(55), T_IN, bar_to_pa(17), eta=0.8).work_j_per_kg
        assert w08 == pytest.approx(0.8 * w1, rel=1e-10)

    def test_expander_colder_than_jt(self):
        """Ekspansja z odbiorem pracy chłodzi mocniej niż dławienie."""
        t_jt = isenthalpic_outlet_temperature_k(CH4, bar_to_pa(55), T_IN, bar_to_pa(17))
        t_exp = expand(CH4, bar_to_pa(55), T_IN, bar_to_pa(17), eta=0.8).temperature_out_k
        assert t_exp < t_jt - 20.0  # różnica jest znacząca (dziesiątki K)


class TestRatioSplitWithJT:
    ARGS = dict(
        pressure_in_pa=bar_to_pa(80),  # 8,0 MPa → 0,4 MPa: r = 20
        temperature_in_k=333.15,
        pressure_out_pa=bar_to_pa(4),
        eta=0.8,
    )

    def test_no_limit_no_jt(self):
        res = expand(CH4, max_expansion_ratio=None, **self.ARGS)
        assert res.jt_position == "brak"
        assert res.expansion_ratio_expander == pytest.approx(20.0)

    def test_jt_after_expander(self):
        res = expand(CH4, max_expansion_ratio=5.0, jt_position="za", **self.ARGS)
        assert res.jt_position == "za"
        assert res.expansion_ratio_expander == pytest.approx(5.0)
        assert res.expander_pressure_in_pa == pytest.approx(bar_to_pa(80))

    def test_jt_before_expander(self):
        res = expand(CH4, max_expansion_ratio=5.0, jt_position="przed", **self.ARGS)
        assert res.jt_position == "przed"
        assert res.expansion_ratio_expander == pytest.approx(5.0)
        assert res.expander_pressure_out_pa == pytest.approx(bar_to_pa(4))

    def test_limited_expander_recovers_less(self):
        """Reduktor JT 'marnuje' część spadku ciśnienia ⇒ mniejsza praca."""
        w_full = expand(CH4, max_expansion_ratio=None, **self.ARGS).work_j_per_kg
        w_lim = expand(CH4, max_expansion_ratio=5.0, **self.ARGS).work_j_per_kg
        assert w_lim < w_full

    def test_jt_positions_energetically_similar(self):
        """JT przed i za ekspanderem: praca odzyskana niemal identyczna
        (dla gazu doskonałego zależy tylko od r i T1; efekty realne < 5%).
        Różnice praktyczne to temperatury pośrednie i wielkość maszyny."""
        w_za = expand(CH4, max_expansion_ratio=5.0, jt_position="za", **self.ARGS)
        w_przed = expand(CH4, max_expansion_ratio=5.0, jt_position="przed", **self.ARGS)
        assert w_przed.work_j_per_kg == pytest.approx(w_za.work_j_per_kg, rel=0.05)


class TestSelectionMatrix:
    def test_matrix_covers_all_technologies(self):
        entries = selection_matrix(
            E_GAS, bar_to_pa(55), 313.15, bar_to_pa(17), flow_nm3_per_h=5000.0
        )
        assert {e.technology.key for e in entries} == set(expander_technologies())

    def test_feasible_sorted_first(self):
        entries = selection_matrix(
            E_GAS, bar_to_pa(55), 313.15, bar_to_pa(17), flow_nm3_per_h=5000.0
        )
        feas_flags = [e.feasible for e in entries]
        assert feas_flags == sorted(feas_flags, reverse=True)

    def test_small_station_excludes_turboexpander(self):
        """Mała stacja (300 Nm³/h): turboekspander poza mapą przepływu."""
        entries = selection_matrix(E_GAS, bar_to_pa(17), 293.15, bar_to_pa(4), flow_nm3_per_h=300.0)
        by_key = {e.technology.key: e for e in entries}
        assert not by_key["turboekspander"].flow_ok
        assert by_key["srubowy"].flow_ok

    def test_library_consistency(self):
        for tech in expander_technologies().values():
            assert 0 < tech.eta_min <= tech.eta_typical <= tech.eta_max <= 1.0
            assert tech.max_expansion_ratio >= 1.0
            lo, hi = tech.capex_eur_per_kw_range
            assert lo <= tech.capex_eur_per_kw_typical <= hi


class TestValidationErrors:
    def test_wrong_pressure_order(self):
        with pytest.raises(ValueError, match="niższe"):
            expand(CH4, bar_to_pa(10), T_IN, bar_to_pa(20), eta=0.8)

    def test_bad_jt_position(self):
        with pytest.raises(ValueError, match="jt_position"):
            expand(CH4, bar_to_pa(20), T_IN, bar_to_pa(10), eta=0.8, jt_position="obok")
