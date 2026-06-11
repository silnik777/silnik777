"""Testy emisji GHG (core.emissions) — walidacja vs wskaźniki referencyjne."""

import pytest

from core.composition import GasComposition
from core.emissions import (
    ch4_to_co2eq_kg,
    combustion_emissions,
    electricity_emissions_t_co2,
    leak_emissions,
)
from core.prices import builtin_scenarios

CH4 = GasComposition.pure("CH4")
E_GAS = GasComposition.predefined("gaz_E_typowy")
H2 = GasComposition.pure("H2")


class TestCombustionStoichiometry:
    def test_methane_mass_basis_exact(self):
        """CH4: 1 kg → 44,0095/16,043 = 2,743 kg CO2 (stechiometria ścisła)."""
        e = combustion_emissions(CH4)
        assert e.kg_co2_per_kg == pytest.approx(44.0095 / 16.043, rel=1e-3)

    def test_methane_per_nm3(self):
        """CH4: ~1,96–1,97 kg CO2/Nm³ (44,0095 / 22,36 m³/kmol rzecz.)."""
        e = combustion_emissions(CH4)
        assert e.kg_co2_per_m3_ref == pytest.approx(1.968, rel=0.005)

    def test_methane_per_kwh_vs_literature(self):
        """CH4: ~198–202 g CO2/kWh Hi (literatura ~200)."""
        e = combustion_emissions(CH4)
        assert 195.0 < e.g_co2_per_kwh_hi < 205.0

    def test_e_gas_vs_ipcc_default(self):
        """Gaz E stechiometrycznie vs wskaźnik IPCC 56,1 kg CO2/GJ (±5%)."""
        e = combustion_emissions(E_GAS)
        assert e.kg_co2_per_gj_hi == pytest.approx(56.1, rel=0.05)

    def test_hydrogen_zero(self):
        e = combustion_emissions(H2)
        assert e.kg_co2_per_m3_ref == 0.0
        assert e.g_co2_per_kwh_hi == 0.0

    def test_h2_blend_reduces_emissions_per_kwh(self):
        """Domieszka H2 obniża g CO2/kWh — mniej niż proporcjonalnie do %vol
        (H2 ma ~3× mniejszą gęstość energii na m³)."""
        base = combustion_emissions(E_GAS).g_co2_per_kwh_hi
        blend20 = combustion_emissions(E_GAS.blend_with_hydrogen(0.20)).g_co2_per_kwh_hi
        reduction = 1 - blend20 / base
        assert 0.04 < reduction < 0.12  # ~6–8% redukcji energetycznej przy 20% mol

    def test_co2_in_fuel_passes_to_flue(self):
        """CO2 zawarty w paliwie (biometan) zwiększa wskaźnik objętościowy."""
        with_co2 = combustion_emissions(GasComposition.from_percent({"CH4": 95, "CO2": 5}))
        pure = combustion_emissions(CH4)
        assert with_co2.kg_co2_per_m3_ref > 0.95 * pure.kg_co2_per_m3_ref


class TestGWP:
    def test_ar6_factors_exact(self):
        assert ch4_to_co2eq_kg(1.0, "GWP100", fossil=True) == 29.8
        assert ch4_to_co2eq_kg(1.0, "GWP20", fossil=True) == 82.5
        assert ch4_to_co2eq_kg(1.0, "GWP100", fossil=False) == 27.0
        assert ch4_to_co2eq_kg(1.0, "GWP20", fossil=False) == 80.8

    def test_invalid_horizon(self):
        with pytest.raises(ValueError, match="Horyzont"):
            ch4_to_co2eq_kg(1.0, "GWP500")

    def test_negative_mass(self):
        with pytest.raises(ValueError, match="ujemna"):
            ch4_to_co2eq_kg(-1.0)


class TestLeaks:
    def test_e_gas_leak(self):
        """1000 Nm³ gazu E: ~0,69 t CH4 → ~20,6 t CO2eq (GWP100)."""
        leak = leak_emissions(E_GAS, 1000.0)
        assert leak.ch4_mass_kg == pytest.approx(1000.0 / 22.36 * 0.964 * 16.043, rel=0.01)
        assert leak.co2eq_gwp100_kg == pytest.approx(leak.ch4_mass_kg * 29.8)
        assert leak.co2eq_gwp20_kg > 2.5 * leak.co2eq_gwp100_kg

    def test_pure_h2_leak_no_ch4(self):
        leak = leak_emissions(H2, 1000.0)
        assert leak.ch4_mass_kg == 0.0
        assert leak.co2eq_gwp100_kg == 0.0

    def test_blend_scales_with_ch4_fraction(self):
        full = leak_emissions(E_GAS, 1000.0).ch4_mass_kg
        half = leak_emissions(E_GAS.blend_with_hydrogen(0.5), 1000.0).ch4_mass_kg
        # 50% mol H2 ⇒ połowa moli CH4 w tej samej objętości (≈, różnica Z)
        assert half == pytest.approx(0.5 * full, rel=0.02)


class TestElectricity:
    def test_scope2_uses_scenario_path(self):
        sc = builtin_scenarios()["bazowy"]
        e_2025 = electricity_emissions_t_co2(100.0, sc, 2025)
        e_2050 = electricity_emissions_t_co2(100.0, sc, 2050)
        assert e_2025 == pytest.approx(100.0 * sc.price("emisyjnosc_miksu", 2025))
        assert e_2050 < 0.2 * e_2025  # dekarbonizacja miksu

    def test_negative_energy(self):
        with pytest.raises(ValueError, match="ujemna"):
            electricity_emissions_t_co2(-1.0, builtin_scenarios()["bazowy"], 2030)
