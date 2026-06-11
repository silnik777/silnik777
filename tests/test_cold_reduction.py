"""Testy bilansu stacji redukcyjnej (core.cold_reduction)."""

import pytest

from core.cold_reduction import (
    _enthalpy,
    heat_sources,
    required_inlet_temp_expander_k,
    required_inlet_temp_jt_k,
    station_balance,
    station_presets,
    variant_economics,
)
from core.composition import GasComposition
from core.units import mpa_to_pa

E_GAS = GasComposition.predefined("gaz_E_typowy")
P1, P2 = mpa_to_pa(5.5), mpa_to_pa(1.7)  # stacja I°
T_IN = 283.15


class TestRequiredInletTemp:
    def test_jt_enthalpy_balance_exact(self):
        """h(p1, T1_req) = h(p2, T_min) — bilans dławienia (ścisły)."""
        t_min = 276.15
        t_req = required_inlet_temp_jt_k(E_GAS, P1, P2, t_min)
        assert _enthalpy(E_GAS, P1, t_req) == pytest.approx(_enthalpy(E_GAS, P2, t_min), rel=1e-6)

    def test_jt_preheat_magnitude(self):
        """Stacja I° (5,5→1,7 MPa): podgrzew nad T_min ~ 15–22 K
        (efekt JT ≈ 0,4–0,55 K/bar × 38 bar)."""
        t_min = 276.15
        t_req = required_inlet_temp_jt_k(E_GAS, P1, P2, t_min)
        assert 13.0 < t_req - t_min < 23.0

    def test_expander_outlet_hits_t_min(self):
        t_min = 276.15
        t_req, result = required_inlet_temp_expander_k(
            E_GAS, P1, P2, t_min, eta=0.8, max_expansion_ratio=5.0
        )
        assert result.temperature_out_k == pytest.approx(t_min, abs=0.05)

    def test_expander_needs_more_preheat_than_jt(self):
        """Ekspansja z odbiorem pracy chłodzi mocniej ⇒ wyższy podgrzew."""
        t_min = 276.15
        t_jt = required_inlet_temp_jt_k(E_GAS, P1, P2, t_min)
        t_exp, _ = required_inlet_temp_expander_k(
            E_GAS, P1, P2, t_min, eta=0.8, max_expansion_ratio=5.0
        )
        assert t_exp > t_jt + 10.0


class TestStationBalance:
    def test_three_variants(self):
        variants = station_balance(E_GAS, P1, T_IN, P2, mass_flow_kg_per_s=2.0)
        assert [v.variant_key for v in variants] == ["jt", "ekspander", "zimna_redukcja"]

    def test_expander_recovers_power_jt_does_not(self):
        variants = station_balance(E_GAS, P1, T_IN, P2, mass_flow_kg_per_s=2.0)
        jt, exp, cold = variants
        assert jt.power_recovered_w == 0.0
        assert exp.power_recovered_w > 10_000.0  # co najmniej dziesiątki kW
        assert cold.preheat_duty_w == 0.0

    def test_cold_reduction_has_cooling_and_flags(self):
        variants = station_balance(
            E_GAS, mpa_to_pa(8.0), T_IN, mpa_to_pa(0.4), mass_flow_kg_per_s=2.0
        )
        cold = variants[2]
        assert cold.cooling_potential_w > 0.0
        assert cold.t_out_k < T_IN - 25.0  # silne wychłodzenie przy r=20
        assert any("hydrat" in w.lower() or "0 °C" in w for w in cold.warnings)

    def test_auto_t_min_from_hydrates(self):
        variants = station_balance(E_GAS, P1, T_IN, P2, mass_flow_kg_per_s=1.0)
        assert any("hydratów" in w.lower() for w in variants[0].warnings)
        hydrate = variants[0].hydrate_check
        assert variants[0].t_out_k == pytest.approx(hydrate.min_safe_temperature_k, abs=0.5)

    def test_presets_loaded(self):
        presets = station_presets()
        assert {"stopien_I", "stopien_II", "podwyzszone_srednie"} == set(presets)
        assert presets["podwyzszone_srednie"]["p_in_mpa"] == 8.0


class TestEconomics:
    def test_heat_source_temperature_constraint(self):
        """Źródło 60 °C (pompa ciepła) może nie wystarczyć dla ekspandera
        przy dużym stosunku rozprężania; kocioł 90 °C — tak."""
        variants = station_balance(
            E_GAS,
            mpa_to_pa(8.0),
            T_IN,
            mpa_to_pa(0.4),
            mass_flow_kg_per_s=2.0,
            expander_max_ratio=5.0,
        )
        exp = variants[1]
        sources = heat_sources()
        eco_pc = variant_economics(exp, sources["pompa_ciepla"])
        eco_kociol = variant_economics(exp, sources["kociol_gazowy"])
        assert exp.t_preheat_required_k is not None
        if exp.t_preheat_required_k > 60.0 + 273.15 - 10.0:
            assert not eco_pc.heat_source_ok
        assert eco_kociol.heat_source_ok or exp.t_preheat_required_k > 353.15

    def test_expander_generates_revenue(self):
        variants = station_balance(E_GAS, P1, T_IN, P2, mass_flow_kg_per_s=2.0)
        eco = variant_economics(variants[1], heat_sources()["kociol_gazowy"])
        assert eco.electricity_revenue_pln_per_year > 0.0

    def test_waste_heat_cheapest(self):
        """Ciepło odpadowe sprężarek (M2↔M13) ma najniższy koszt podgrzewu."""
        variants = station_balance(E_GAS, P1, T_IN, P2, mass_flow_kg_per_s=2.0)
        jt = variants[0]
        sources = heat_sources()
        costs = {
            key: variant_economics(jt, src).preheat_cost_pln_per_year
            for key, src in sources.items()
        }
        assert costs["cieplo_odpadowe_sprezarek"] == min(costs.values())

    def test_cold_reduction_zero_preheat_cost(self):
        variants = station_balance(E_GAS, P1, T_IN, P2, mass_flow_kg_per_s=2.0)
        eco = variant_economics(variants[2], heat_sources()["kociol_gazowy"])
        assert eco.preheat_cost_pln_per_year == 0.0
        assert eco.net_cost_pln_per_year == 0.0
