"""Testy silnika ekonomicznego (core.economics) — walidacja analityczna."""

import pytest

from core.economics import (
    discounted_payback_years,
    irr,
    lcoe_for_technology,
    lcoh_for_technology,
    levelized_cost,
    npv,
    project_metrics,
    residual_value_pln,
    tornado_analysis,
)
from core.prices import builtin_scenarios, eur_pln_rate

SC = builtin_scenarios()["bazowy"]


class TestBasicMetrics:
    CF = {0: -1000.0, 1: 500.0, 2: 500.0, 3: 500.0}

    def test_npv_hand_computed(self):
        """NPV(10%) = −1000 + 500·(1/1,1 + 1/1,21 + 1/1,331) = 243,43."""
        assert npv(self.CF, 0.10) == pytest.approx(243.43, abs=0.01)

    def test_irr_annuity(self):
        """IRR: 500·a(3, r) = 1000 ⇒ r ≈ 23,38% (tablice annuitetowe)."""
        assert irr(self.CF) == pytest.approx(0.2338, abs=0.001)

    def test_irr_none_when_no_payback(self):
        assert irr({0: -1000.0, 1: 10.0}) is None

    def test_dpp_interpolated(self):
        """Zdyskont. skumulowane (10%): 454,5; 867,8; 1243,4 ⇒ DPP ≈ 2,35."""
        dpp = discounted_payback_years(self.CF, 0.10)
        assert dpp == pytest.approx(2.35, abs=0.01)

    def test_dpp_none(self):
        assert discounted_payback_years({0: -100.0, 1: 10.0}, 0.10) is None

    def test_residual_value(self):
        assert residual_value_pln(1000.0, 40.0, 20.0) == pytest.approx(500.0)
        assert residual_value_pln(1000.0, 20.0, 20.0) == 0.0


class TestLevelizedCost:
    def test_against_crf_formula(self):
        """Niezależna weryfikacja: LCOx = CAPEX·CRF/Q + OPEX/Q.

        CRF(7%, 20 lat) = 0,07/(1−1,07⁻²⁰) = 0,094393.
        CAPEX=1000, OPEX=50/rok, Q=100/rok ⇒ LCOx = 0,94393 + 0,5 = 1,44393.
        """
        res = levelized_cost(
            capex_pln=1000.0,
            output_per_year=100.0,
            costs_per_year={"OPEX": 50.0},
            wacc=0.07,
            lifetime_years=20,
        )
        crf = 0.07 / (1.0 - 1.07**-20)
        assert res.lcox == pytest.approx(1000.0 * crf / 100.0 + 0.5, rel=1e-9)
        assert res.components["CAPEX"] == pytest.approx(1000.0 * crf / 100.0, rel=1e-9)

    def test_capex_schedule_two_years(self):
        """CAPEX w latach 0 i 1 (50/50) jest tańszy zdyskontowany niż w 0."""
        kw = dict(output_per_year=100.0, costs_per_year={}, wacc=0.07, lifetime_years=20)
        upfront = levelized_cost(capex_pln=1000.0, **kw)
        split = levelized_cost(capex_pln=1000.0, capex_schedule={0: 0.5, 1: 0.5}, **kw)
        assert split.lcox < upfront.lcox

    def test_revenues_reduce_lcox(self):
        kw = dict(capex_pln=1000.0, output_per_year=100.0, wacc=0.07, lifetime_years=20)
        base = levelized_cost(costs_per_year={"OPEX": 50.0}, **kw)
        with_rev = levelized_cost(
            costs_per_year={"OPEX": 50.0},
            revenues_per_year={"tlen": 20.0},
            **kw,
        )
        assert with_rev.lcox == pytest.approx(base.lcox - 0.2, rel=1e-9)

    def test_residual_value_in_lcox(self):
        kw = dict(
            capex_pln=1000.0,
            output_per_year=100.0,
            costs_per_year={},
            wacc=0.07,
            lifetime_years=20,
        )
        no_res = levelized_cost(**kw)
        with_res = levelized_cost(asset_life_years=40.0, **kw)
        assert with_res.lcox < no_res.lcox

    def test_bad_schedule(self):
        with pytest.raises(ValueError, match="Harmonogram"):
            levelized_cost(
                capex_pln=1000.0,
                output_per_year=100.0,
                costs_per_year={},
                capex_schedule={0: 0.6, 1: 0.6},
            )

    def test_project_metrics_break_even(self):
        """Sprzedaż po LCOx ⇒ NPV ≈ 0 i IRR ≈ WACC (definicja kosztu uśredn.)."""
        res = levelized_cost(
            capex_pln=1000.0,
            output_per_year=100.0,
            costs_per_year={"OPEX": 50.0},
            wacc=0.07,
            lifetime_years=20,
        )
        metrics = project_metrics(res, res.lcox, 100.0, wacc=0.07, lifetime_years=20)
        assert metrics["npv_pln"] == pytest.approx(0.0, abs=1e-6)
        assert metrics["irr"] == pytest.approx(0.07, abs=1e-4)


class TestTornado:
    def test_sorted_by_span_and_monotonic(self):
        def evaluate(p):
            return p["a"] * 10.0 + p["b"]

        entries = tornado_analysis({"a": 1.0, "b": 1.0}, evaluate, 0.2)
        assert entries[0].parameter == "a"  # większy wpływ
        assert entries[0].low_value < entries[0].base_value < entries[0].high_value
        assert entries[0].span == pytest.approx(4.0)
        assert entries[1].span == pytest.approx(0.4)


class TestLCOHandLCOE:
    def test_lcoh_ael_plausible_vs_iea(self):
        """LCOH AEL 2030 (scenariusz bazowy): 18–35 PLN/kg (~4–8 €/kg, IEA)."""
        res = lcoh_for_technology("AEL", SC, start_year=2030)
        eur_per_kg = res.lcox / eur_pln_rate()
        assert 18.0 < res.lcox < 35.0
        assert 4.0 < eur_per_kg < 8.0

    def test_lcoh_dominated_by_electricity(self):
        res = lcoh_for_technology("PEM", SC, start_year=2030)
        assert res.components["energia elektryczna"] > 0.5 * res.lcox

    def test_lcoh_o2_revenue_reduces(self):
        base = lcoh_for_technology("AEL", SC)
        with_o2 = lcoh_for_technology("AEL", SC, o2_revenue_pln_per_kg_h2=1.0)
        assert with_o2.lcox == pytest.approx(base.lcox - 1.0, rel=1e-6)

    def test_smr_ccs_has_gas_and_ets(self):
        res = lcoh_for_technology("SMR_CCS", SC, start_year=2030)
        assert res.components["gaz ziemny"] > 5.0
        assert res.components["CO2 (EUA)"] > 0.0

    def test_lcoe_pv_vs_ccgt(self):
        """PV (bez paliwa/ETS) tańsza od CCGT przy cenach bazowych 2030."""
        pv = lcoe_for_technology("pv", SC, start_year=2030)
        ccgt = lcoe_for_technology("ccgt", SC, start_year=2030)
        assert pv.lcox < ccgt.lcox
        assert "paliwo" not in pv.components
        assert ccgt.components["CO2 (EUA)"] > 0.0

    def test_lcoe_pv_plausible(self):
        """LCOE PV: 250–450 PLN/MWh (cf 11%, 600 €/kW — IRENA/ATB rzędy)."""
        pv = lcoe_for_technology("pv", SC, start_year=2030)
        assert 250.0 < pv.lcox < 450.0

    def test_heat_only_technology_rejected(self):
        with pytest.raises(ValueError, match="nie produkuje energii"):
            lcoe_for_technology("kociol_gazowy", SC)
