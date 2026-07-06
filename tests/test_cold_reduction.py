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


class TestScenarioPrices:
    """Fix 3.1: M13 liczy na cenach scenariusza M5 (jedno źródło prawdy)."""

    def test_scenario_electricity_revenue_matches_m5_price(self):
        from core.prices import builtin_scenarios

        sc = builtin_scenarios()["bazowy"]
        variants = station_balance(E_GAS, P1, T_IN, P2, mass_flow_kg_per_s=2.0)
        exp = variants[1]
        eco = variant_economics(
            exp, heat_sources()["kociol_gazowy"], hours_per_year=8000.0, scenario=sc, year=2030
        )
        expected = exp.power_recovered_w / 1e6 * 8000.0 * sc.price("energia_elektryczna", 2030)
        assert eco.electricity_revenue_pln_per_year == pytest.approx(expected)

    def test_scenario_changes_result_vs_working_prices(self):
        from core.prices import builtin_scenarios

        sc_low = builtin_scenarios()["niski"]
        sc_high = builtin_scenarios()["wysoki"]
        variants = station_balance(E_GAS, P1, T_IN, P2, mass_flow_kg_per_s=2.0)
        jt = variants[0]
        c_low = variant_economics(
            jt, heat_sources()["kociol_gazowy"], scenario=sc_low, year=2030
        ).preheat_cost_pln_per_year
        c_high = variant_economics(
            jt, heat_sources()["kociol_gazowy"], scenario=sc_high, year=2030
        ).preheat_cost_pln_per_year
        # różne scenariusze cen gazu → różny koszt podgrzewu
        assert c_low != c_high

    def test_fallback_working_prices_without_scenario(self):
        """Bez scenariusza — ceny robocze (zachowanie niezmienione)."""
        variants = station_balance(E_GAS, P1, T_IN, P2, mass_flow_kg_per_s=2.0)
        eco = variant_economics(variants[0], heat_sources()["kociol_gazowy"])
        assert eco.preheat_cost_pln_per_year > 0.0

    def test_year_required_with_scenario(self):
        from core.prices import builtin_scenarios

        variants = station_balance(E_GAS, P1, T_IN, P2, mass_flow_kg_per_s=2.0)
        with pytest.raises(ValueError, match="rok analizy"):
            variant_economics(
                variants[0],
                heat_sources()["kociol_gazowy"],
                scenario=builtin_scenarios()["bazowy"],
            )


class TestCompressionHeatSource:
    """Fix 3.2: źródło ciepła z POLICZONEGO sprężania M2 (nie z danych)."""

    def _comp(self, p_out_bar=55.0, stages=2):
        from core.compression import compress
        from core.units import bar_to_pa

        return compress(
            E_GAS,
            bar_to_pa(4.0),
            293.15,
            bar_to_pa(p_out_bar),
            eta=0.78,
            n_stages=stages,
            model="politropowy",
        )

    def test_supply_temp_is_min_stage_minus_approach(self):
        from core.cold_reduction import heat_source_from_compression

        comp = self._comp()
        src = heat_source_from_compression(comp, mass_flow_kg_per_s=3.0, approach_k=10.0)
        min_stage_c = min(s.temperature_out_k for s in comp.stages) - 273.15
        assert src.supply_temp_c == pytest.approx(min_stage_c - 10.0)
        assert src.energy_carrier == "odpadowe"
        assert src.key == "m2_sprezarka_policzona"

    def test_available_kw_is_cooling_plus_aftercooler(self):
        from core.cold_reduction import heat_source_from_compression

        comp = self._comp()
        m = 3.0
        src = heat_source_from_compression(comp, mass_flow_kg_per_s=m)
        expected_w = (
            comp.cooling_duty_w(m) + comp.aftercooler_heat_j_per_kg(comp.temperature_in_k) * m
        )
        assert src.available_kw == pytest.approx(expected_w / 1e3)
        assert src.available_kw > 0.0

    def test_capacity_flag_fails_when_demand_exceeds_available(self):
        """Gdy zapotrzebowanie podgrzewu > dostępna moc — flaga ❌."""
        from core.cold_reduction import HeatSource

        variants = station_balance(E_GAS, P1, T_IN, P2, mass_flow_kg_per_s=2.0)
        jt = variants[0]
        duty_kw = jt.preheat_duty_w / 1e3
        # źródło gorące, ale o mocy 10× mniejszej niż potrzeba
        tiny = HeatSource(
            key="m2_sprezarka_policzona",
            name_pl="mała sprężarka",
            supply_temp_c=120.0,
            energy_carrier="odpadowe",
            efficiency_hi=1.0,
            cop=None,
            source="test",
            available_kw=duty_kw / 10.0,
        )
        big = HeatSource(
            key="m2_sprezarka_policzona",
            name_pl="duża sprężarka",
            supply_temp_c=120.0,
            energy_carrier="odpadowe",
            efficiency_hi=1.0,
            cop=None,
            source="test",
            available_kw=duty_kw * 10.0,
        )
        assert not variant_economics(jt, tiny).heat_source_ok
        assert variant_economics(jt, big).heat_source_ok

    def test_too_cold_compressor_raises(self):
        from core.cold_reduction import heat_source_from_compression
        from core.compression import compress
        from core.units import bar_to_pa

        # zimne ssanie + niski spręż → tłoczenie ≈ ssanie, brak użytecznego ciepła
        comp = compress(
            E_GAS,
            bar_to_pa(4.0),
            278.15,
            bar_to_pa(4.2),
            eta=0.78,
            n_stages=1,
            model="politropowy",
        )
        with pytest.raises(ValueError, match="zbyt niskiej temperaturze"):
            heat_source_from_compression(comp, mass_flow_kg_per_s=3.0)

    def test_zero_mass_flow_raises(self):
        from core.cold_reduction import heat_source_from_compression

        comp = self._comp()
        with pytest.raises(ValueError, match="dodatni"):
            heat_source_from_compression(comp, mass_flow_kg_per_s=0.0)
