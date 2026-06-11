"""Testy biblioteki technologii wytwórczych (core.generation, M7)."""

import pytest

from core.cold_reduction import heat_sources
from core.generation import (
    fuel_emission_g_co2_per_kwh,
    generation_technologies,
    heat_source_entries,
    technology_indicators,
)
from core.prices import builtin_scenarios

SC = builtin_scenarios()["bazowy"]


class TestLibrary:
    def test_minimum_breadth(self):
        techs = generation_technologies()
        assert len(techs) >= 14
        classes = {t.emission_class for t in techs.values()}
        assert classes == {"kopalne", "alternatywne", "niskoemisyjne", "bezemisyjne"}
        categories = {t.category for t in techs.values()}
        assert categories == {"cieplo", "energia_elektryczna", "kogeneracja"}

    def test_chp_total_efficiency_plausible(self):
        chp = generation_technologies()["silnik_kogeneracyjny"]
        assert 0.80 <= chp.eta_total <= 0.95

    def test_heat_pump_cop_above_one(self):
        hp = generation_technologies()["pompa_ciepla_gruntowa"]
        assert hp.eta_heat > 3.0

    def test_ranges_consistent(self):
        for tech in generation_technologies().values():
            if tech.eta_el_range:
                lo, hi = tech.eta_el_range
                assert lo <= tech.eta_el <= hi
            lo, hi = tech.capex_range
            assert lo <= tech.capex_eur_per_kw <= hi


class TestEmissions:
    def test_gas_boiler_heat_emissions(self):
        """Kocioł gazowy: ~195–235 g CO2/kWh ciepła (202 g/kWh paliwa / η)."""
        ind = technology_indicators(generation_technologies()["kociol_gazowy"], SC, 2030)
        assert 195.0 < ind.g_co2_per_kwh_heat < 235.0

    def test_condensing_boiler_below_conventional(self):
        cond = technology_indicators(
            generation_technologies()["kociol_gazowy_kondensacyjny"], SC, 2030
        )
        conv = technology_indicators(generation_technologies()["kociol_gazowy"], SC, 2030)
        assert cond.g_co2_per_kwh_heat < conv.g_co2_per_kwh_heat

    def test_coal_dirtier_than_gas(self):
        """Węgiel: 94,7 kg/GJ → ~341 g/kWh paliwa; ciepło > 380 g/kWh."""
        coal = technology_indicators(generation_technologies()["kociol_weglowy"], SC, 2030)
        gas = technology_indicators(generation_technologies()["kociol_gazowy"], SC, 2030)
        assert coal.g_co2_per_kwh_heat > 1.6 * gas.g_co2_per_kwh_heat

    def test_heat_pump_follows_grid_decarbonization(self):
        hp = generation_technologies()["pompa_ciepla_gruntowa"]
        e2025 = technology_indicators(hp, SC, 2025).g_co2_per_kwh_heat
        e2050 = technology_indicators(hp, SC, 2050).g_co2_per_kwh_heat
        assert e2025 == pytest.approx(0.66 * 1e3 / 3.8, rel=0.01)
        assert e2050 < 0.1 * e2025

    def test_zero_emission_technologies(self):
        for key in ("pv", "wiatr_ladowy", "kolektor_sloneczny", "ogniwo_pemfc"):
            ind = technology_indicators(generation_technologies()[key], SC, 2030)
            for value in (ind.g_co2_per_kwh_el, ind.g_co2_per_kwh_heat):
                assert value in (None, 0.0)

    def test_biomass_zero_scope1(self):
        assert fuel_emission_g_co2_per_kwh("biomasa") == 0.0

    def test_unknown_fuel(self):
        with pytest.raises(ValueError, match="Brak wskaźnika"):
            fuel_emission_g_co2_per_kwh("tor")


class TestCosts:
    def test_fuel_cost_gas_boiler(self):
        """Koszt paliwowy ciepła z kotła gazowego = cena gazu / η."""
        ind = technology_indicators(generation_technologies()["kociol_gazowy"], SC, 2030)
        assert ind.fuel_cost_pln_per_mwh_heat == pytest.approx(215.0 / 0.92, rel=0.01)

    def test_free_fuels_zero_cost(self):
        ind = technology_indicators(generation_technologies()["pv"], SC, 2030)
        assert ind.fuel_cost_pln_per_mwh_el == 0.0


class TestM13Integration:
    def test_heat_entries_only_heat_capable(self):
        entries = heat_source_entries()
        assert len(entries) >= 8
        for e in entries:
            assert e["supply_temp_c"] > 0
            assert e["key"].startswith("m7_")

    def test_m13_heat_sources_include_m7(self):
        sources = heat_sources()
        assert "m7_kociol_gazowy_kondensacyjny" in sources
        assert "m7_pompa_ciepla_gruntowa" in sources
        # pompa ciepła z M7 ma COP, kocioł — sprawność
        assert sources["m7_pompa_ciepla_gruntowa"].cop == pytest.approx(3.8)
        assert sources["m7_kociol_gazowy_kondensacyjny"].efficiency_hi == pytest.approx(1.03)

    def test_m7_sources_economics_computable(self):
        """Każde źródło z M7 ma cenę nośnika w cenach roboczych M13."""
        from core.cold_reduction import station_balance, variant_economics
        from core.composition import GasComposition
        from core.units import mpa_to_pa

        variants = station_balance(
            GasComposition.predefined("gaz_E_typowy"),
            mpa_to_pa(5.5),
            283.15,
            mpa_to_pa(1.7),
            mass_flow_kg_per_s=1.0,
        )
        for source in heat_sources().values():
            eco = variant_economics(variants[0], source)
            assert eco.preheat_cost_pln_per_year >= 0.0
