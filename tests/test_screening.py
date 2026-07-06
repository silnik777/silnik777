"""Testy merit order i screening curves (core.screening)."""

import pytest

from core.generation import generation_technologies
from core.prices import builtin_scenarios
from core.screening import (
    annual_cost_per_kw,
    merit_order,
    screening_curves,
    variable_cost_pln_per_mwh,
)

SC = builtin_scenarios()["bazowy"]
EL_TECHS = [k for k, t in generation_technologies().items() if t.eta_el is not None]


class TestVariableCost:
    def test_free_fuel_zero(self):
        assert variable_cost_pln_per_mwh("pv", SC, 2030) == 0.0
        assert variable_cost_pln_per_mwh("wiatr_ladowy", SC, 2030) == 0.0

    def test_gas_positive(self):
        assert variable_cost_pln_per_mwh("ccgt", SC, 2030) > 100.0

    def test_ets_increases_fossil_cost(self):
        with_ets = variable_cost_pln_per_mwh("ccgt", SC, 2030, include_ets=True)
        without = variable_cost_pln_per_mwh("ccgt", SC, 2030, include_ets=False)
        assert with_ets > without

    def test_rejects_non_electric(self):
        with pytest.raises(ValueError, match="energii elektrycznej"):
            variable_cost_pln_per_mwh("kociol_gazowy", SC, 2030)


class TestMeritOrder:
    def test_sorted_ascending(self):
        mo = merit_order(EL_TECHS, SC, 2030)
        costs = [e.marginal_cost_pln_per_mwh for e in mo]
        assert costs == sorted(costs)

    def test_renewables_first(self):
        """PV i wiatr (koszt krańcowy 0) na początku merit order."""
        mo = merit_order(EL_TECHS, SC, 2030)
        assert mo[0].marginal_cost_pln_per_mwh == 0.0
        assert {mo[0].technology_key, mo[1].technology_key} == {"pv", "wiatr_ladowy"}

    def test_skips_heat_only(self):
        """Technologie bez produkcji el. pomijane."""
        mo = merit_order(EL_TECHS + ["kociol_gazowy"], SC, 2030)
        assert all(e.technology_key != "kociol_gazowy" for e in mo)


class TestScreeningCurves:
    def test_pv_flat_curve(self):
        """PV: koszt zmienny 0 → krzywa pozioma (koszt niezależny od cf)."""
        c = screening_curves(["pv"], SC, 2030)[0]
        assert c.variable_cost_pln_per_mwh == 0.0
        assert c.cost_per_kw_year[0] == pytest.approx(c.cost_per_kw_year[-1])

    def test_fixed_cost_formula(self):
        """Koszt stały = CAPEX/kW·(CRF + OPEX%)."""
        c = screening_curves(["ccgt"], SC, 2030, wacc=0.07, lifetime_years=20)[0]
        from core.prices import eur_pln_rate

        tech = generation_technologies()["ccgt"]
        capex_kw = tech.capex_eur_per_kw * eur_pln_rate()
        crf = 0.07 / (1.0 - 1.07**-20)
        assert c.fixed_cost_per_kw_year == pytest.approx(capex_kw * (crf + 0.03), rel=1e-9)

    def test_curve_linear_in_cf(self):
        c = screening_curves(["ccgt"], SC, 2030)[0]
        # nachylenie = 8,760 · koszt zmienny
        slope = (c.cost_per_kw_year[-1] - c.cost_per_kw_year[0]) / (
            c.capacity_factors[-1] - c.capacity_factors[0]
        )
        assert slope == pytest.approx(8.760 * c.variable_cost_pln_per_mwh, rel=1e-9)

    def test_matches_annual_cost_per_kw(self):
        c = screening_curves(["ccgt"], SC, 2030)[0]
        direct = annual_cost_per_kw("ccgt", SC, 2030, 0.5)
        # cf=0.5 to punkt środkowy przy 21 punktach (indeks 10)
        assert c.cost_per_kw_year[10] == pytest.approx(direct, rel=1e-9)

    def test_baseload_vs_peak_crossover(self):
        """PV (tania stała) tańsza przy niskim cf; gaz może wygrać przy wysokim
        cf tylko gdy stała gazu niższa — tu sprawdzamy istnienie różnicy nachyleń."""
        curves = screening_curves(["pv", "ccgt"], SC, 2030)
        pv, ccgt = curves[0], curves[1]
        # przy cf=0 decyduje koszt stały; nachylenia różne (PV płaskie)
        assert pv.variable_cost_pln_per_mwh < ccgt.variable_cost_pln_per_mwh
