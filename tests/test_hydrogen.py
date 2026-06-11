"""Testy produkcji wodoru (core.hydrogen) — spójność z danymi IEA."""

import pytest

from core.hydrogen import (
    energy_cost_pln_per_kg,
    h2_lhv_kwh_per_kg,
    hydrogen_demand,
    hydrogen_technologies,
)
from core.prices import builtin_scenarios

SC = builtin_scenarios()["bazowy"]


class TestLibrary:
    def test_six_technologies(self):
        assert set(hydrogen_technologies()) == {
            "AEL",
            "PEM",
            "SOEC",
            "AEM",
            "SMR_CCS",
            "piroliza",
        }

    def test_lhv_from_iso6976(self):
        """Hi(H2) = 33,33 kWh/kg (M1/ISO 6976) — podstawa sprawności."""
        assert h2_lhv_kwh_per_kg() == pytest.approx(33.33, rel=0.002)

    def test_electrolyzer_efficiencies_plausible(self):
        """Sprawności LHV elektrolizerów: 55–90% (IEA GHR: AEL/PEM ~60–65%,
        SOEC ~70–84% z ciepłem)."""
        lhv = h2_lhv_kwh_per_kg()
        for key in ("AEL", "PEM", "SOEC", "AEM"):
            tech = hydrogen_technologies()[key]
            eta = lhv / tech.total_energy_kwh_per_kg
            assert 0.5 < eta < 0.9, f"{key}: eta={eta:.2f}"

    def test_soec_lowest_electricity(self):
        techs = hydrogen_technologies()
        assert techs["SOEC"].electricity_kwh_per_kg == min(
            techs[k].electricity_kwh_per_kg for k in ("AEL", "PEM", "SOEC", "AEM")
        )

    def test_smr_ccs_residual_emissions(self):
        smr = hydrogen_technologies()["SMR_CCS"]
        assert 0.5 <= smr.direct_co2_kg_per_kg_h2 <= 1.5
        assert smr.fuel_gas_kwh_per_kg > 40.0

    def test_ranges_consistent(self):
        for tech in hydrogen_technologies().values():
            lo, hi = tech.electricity_range
            assert lo <= tech.electricity_kwh_per_kg <= hi
            assert tech.part_load_pct[0] < tech.part_load_pct[1]
            assert 1 <= tech.trl <= 9


class TestDemandCalculator:
    def test_energy_balance(self):
        """100 kg/h × 52 kWh/kg × 8760 h × cf ⇒ MWh/rok (bilans ścisły)."""
        res = hydrogen_demand("AEL", 100.0, SC, year=2030, capacity_factor=0.9)
        expected_mwh = 52.0 * 100.0 * 8760.0 * 0.9 / 1e3
        assert res.energy_el_mwh_per_year == pytest.approx(expected_mwh)
        assert res.power_el_mw == pytest.approx(5.2)
        assert res.production_t_per_year == pytest.approx(100.0 * 8760 * 0.9 / 1e3)

    def test_degradation_increases_consumption(self):
        fresh = hydrogen_demand("PEM", 100.0, SC, years_of_degradation=0.0)
        aged = hydrogen_demand("PEM", 100.0, SC, years_of_degradation=5.0)
        assert aged.electricity_kwh_per_kg_aged == pytest.approx(
            fresh.electricity_kwh_per_kg_aged * 1.05
        )
        assert aged.efficiency_lhv < fresh.efficiency_lhv

    def test_scope2_pem_2025_vs_2050(self):
        """PEM przy miksie 2025 (0,66 t/MWh): ~36 kg CO2/kg H2 — gorzej niż
        SMR bez CCS (~10); przy miksie 2050 spada poniżej 2."""
        r2025 = hydrogen_demand("PEM", 100.0, SC, year=2025)
        r2050 = hydrogen_demand("PEM", 100.0, SC, year=2050)
        assert r2025.co2_scope2_kg_per_kg == pytest.approx(55.0 * 0.66, rel=0.01)
        assert r2050.co2_scope2_kg_per_kg < 3.0

    def test_smr_gas_demand_and_scope1(self):
        res = hydrogen_demand("SMR_CCS", 100.0, SC)
        assert res.gas_mwh_per_year > 0
        assert res.co2_scope1_kg_per_kg == pytest.approx(1.0)
        # zakres 2 mały (tylko 2,5 kWh el./kg)
        assert res.co2_scope2_kg_per_kg < 2.0

    def test_energy_cost(self):
        res = hydrogen_demand("AEL", 100.0, SC, year=2030)
        cost = energy_cost_pln_per_kg(res, SC, 2030)
        # 52 kWh × 420 PLN/MWh = ~21,8 PLN/kg
        assert cost == pytest.approx(52.0 / 1e3 * 420.0, rel=0.01)

    def test_validation_errors(self):
        with pytest.raises(ValueError, match="Nieznana technologia"):
            hydrogen_demand("fuzja", 100.0, SC)
        with pytest.raises(ValueError, match="dodatnia"):
            hydrogen_demand("AEL", -1.0, SC)
        with pytest.raises(ValueError, match="wykorzystania"):
            hydrogen_demand("AEL", 100.0, SC, capacity_factor=1.5)
