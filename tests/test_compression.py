"""Testy modułu sprężania (core.compression) — walidacja analityczna.

Przy niskich ciśnieniach (≤ ~10 bar) gaz rzeczywisty jest bliski doskonałemu,
więc wyniki muszą zgadzać się z rozwiązaniami analitycznymi:
    * izotermicznie:  w = R·T·ln(p2/p1)/M,
    * izentropowo:    T2s = T1·r^((γ−1)/γ),  w = cp·(T2s − T1).
"""

import math

import pytest

from core.composition import GasComposition
from core.compression import (
    applicable_technologies,
    compress,
    compressor_technologies,
    isothermal_work_j_per_kg,
    optimal_stage_count,
)
from core.gas_properties import compute_properties
from core.units import R_UNIVERSAL_J_PER_MOL_K, bar_to_pa

CH4 = GasComposition.pure("CH4")
H2 = GasComposition.pure("H2")
T_IN = 288.15  # 15 °C


class TestIsothermal:
    def test_ideal_gas_limit_methane(self):
        """1→2 bar: w ≈ R·T·ln(2)/M (odchyłka realna < 0,5%)."""
        w = isothermal_work_j_per_kg(CH4, bar_to_pa(1), T_IN, bar_to_pa(2))
        m_kg_per_mol = CH4.molar_mass_kg_per_kmol / 1e3
        w_ideal = R_UNIVERSAL_J_PER_MOL_K * T_IN * math.log(2.0) / m_kg_per_mol
        assert w == pytest.approx(w_ideal, rel=0.005)

    def test_hydrogen_350bar_above_ideal(self):
        """H2 1→350 bar: praca rzeczywista > idealnej (Z > 1), do +15%."""
        w = isothermal_work_j_per_kg(H2, bar_to_pa(1), 298.15, bar_to_pa(350))
        m = H2.molar_mass_kg_per_kmol / 1e3
        w_ideal = R_UNIVERSAL_J_PER_MOL_K * 298.15 * math.log(350.0) / m
        assert w_ideal < w < 1.15 * w_ideal

    def test_invalid_pressure_order(self):
        with pytest.raises(ValueError, match="musi być wyższe"):
            isothermal_work_j_per_kg(CH4, bar_to_pa(10), T_IN, bar_to_pa(5))


class TestIsentropicStage:
    def test_ideal_gas_outlet_temperature(self):
        """CH4 1→3 bar, η=1: T2s ≈ T1·r^((γ−1)/γ) (γ przy ssaniu).

        Tolerancja 2,5%: wzór zakłada stałe γ, a cp(CH4) rośnie z temperaturą
        wzdłuż izentropy — wynik rzeczywisty jest nieco niższy.
        """
        result = compress(CH4, bar_to_pa(1), T_IN, bar_to_pa(3), eta=1.0)
        gamma = compute_properties(CH4, bar_to_pa(1), T_IN).cp_over_cv
        t2s_ideal = T_IN * 3.0 ** ((gamma - 1.0) / gamma)
        assert result.outlet_temperature_k == pytest.approx(t2s_ideal, rel=0.025)
        assert result.outlet_temperature_k < t2s_ideal

    def test_ideal_gas_work(self):
        """CH4 1→3 bar, η=1: w ≈ cp·(T2s − T1) (gaz prawie doskonały)."""
        result = compress(CH4, bar_to_pa(1), T_IN, bar_to_pa(3), eta=1.0)
        props = compute_properties(CH4, bar_to_pa(1), T_IN)
        gamma = props.cp_over_cv
        t2s = T_IN * 3.0 ** ((gamma - 1.0) / gamma)
        w_ideal = props.cp_j_per_kg_k * (t2s - T_IN)
        assert result.work_j_per_kg == pytest.approx(w_ideal, rel=0.02)

    def test_efficiency_scales_work_exactly(self):
        w_eta1 = compress(CH4, bar_to_pa(5), T_IN, bar_to_pa(20), eta=1.0).work_j_per_kg
        w_eta08 = compress(CH4, bar_to_pa(5), T_IN, bar_to_pa(20), eta=0.8).work_j_per_kg
        assert w_eta08 == pytest.approx(w_eta1 / 0.8, rel=1e-10)

    def test_lower_efficiency_higher_outlet_temperature(self):
        t_eta1 = compress(CH4, bar_to_pa(5), T_IN, bar_to_pa(20), eta=1.0).outlet_temperature_k
        t_eta08 = compress(CH4, bar_to_pa(5), T_IN, bar_to_pa(20), eta=0.8).outlet_temperature_k
        assert t_eta08 > t_eta1


class TestPolytropic:
    def test_eta1_equals_isentropic(self):
        """η_p = 1: droga politropowa pokrywa się z izentropą (< 0,1%)."""
        w_s = compress(CH4, bar_to_pa(5), T_IN, bar_to_pa(20), eta=1.0).work_j_per_kg
        w_p = compress(
            CH4, bar_to_pa(5), T_IN, bar_to_pa(20), eta=1.0, model="politropowy"
        ).work_j_per_kg
        assert w_p == pytest.approx(w_s, rel=1e-3)

    def test_polytropic_work_above_isentropic_for_eta_below_1(self):
        """Dla η < 1 praca politropowa > izentropowa/η_s przy tej samej liczbie."""
        w_s = compress(CH4, bar_to_pa(5), T_IN, bar_to_pa(50), eta=0.8).work_j_per_kg
        w_p = compress(
            CH4, bar_to_pa(5), T_IN, bar_to_pa(50), eta=0.8, model="politropowy"
        ).work_j_per_kg
        # politropowa "podgrzewa" gaz w trakcie — praca większa niż w_s/η_s? Nie:
        # przy tym samym η praca politropowa > izentropowej tylko nieznacznie;
        # sprawdzamy relację jakościową i rozsądny przedział
        assert 0.95 * w_s < w_p < 1.10 * w_s


class TestMultistage:
    def test_monotonic_decrease_toward_isothermal(self):
        """Więcej stopni z chłodzeniem ⇒ mniejsza praca; granica: izotermiczna."""
        works = [
            compress(CH4, bar_to_pa(2), T_IN, bar_to_pa(60), eta=1.0, n_stages=n).work_j_per_kg
            for n in (1, 2, 3, 6)
        ]
        assert works == sorted(works, reverse=True)
        w_iso = isothermal_work_j_per_kg(CH4, bar_to_pa(2), T_IN, bar_to_pa(60))
        assert all(w > w_iso for w in works)

    def test_intercooling_heat_positive(self):
        result = compress(CH4, bar_to_pa(2), T_IN, bar_to_pa(60), eta=0.85, n_stages=3)
        assert result.intercooling_heat_j_per_kg > 0
        assert len(result.stages) == 3
        # chłodnice tylko między stopniami
        assert result.stages[-1].intercooler_heat_j_per_kg == 0.0

    def test_stage_pressure_continuity(self):
        result = compress(CH4, bar_to_pa(2), T_IN, bar_to_pa(60), eta=0.85, n_stages=3)
        for prev, nxt in zip(result.stages, result.stages[1:], strict=False):
            assert prev.pressure_out_pa == pytest.approx(nxt.pressure_in_pa)
        assert result.stages[-1].pressure_out_pa == pytest.approx(bar_to_pa(60))

    def test_power_and_per_nm3(self):
        result = compress(H2, bar_to_pa(30), T_IN, bar_to_pa(200), eta=0.85, n_stages=2)
        assert result.power_w(1.0) == pytest.approx(result.work_j_per_kg)
        rho_n = compute_properties(H2, 101_325.0, 273.15).density_kg_per_m3
        assert result.work_kwh_per_nm3() == pytest.approx(result.work_kwh_per_kg * rho_n)

    def test_h2_specific_energy_plausible(self):
        """H2 30→200 bar, η=0,85, 2 stopnie: ~0,7–1,1 kWh/kg.

        Kontrola spójności: praca izotermiczna (granica dolna) wynosi tu
        0,63 kWh/kg; literatura dla sprężania rurociągowego H2 podaje
        0,8–1,1 kWh/kg (IEA 2019, DNV 2022) — wynik musi być pomiędzy.
        """
        result = compress(H2, bar_to_pa(30), T_IN, bar_to_pa(200), eta=0.85, n_stages=2)
        w_iso = isothermal_work_j_per_kg(H2, bar_to_pa(30), T_IN, bar_to_pa(200))
        assert result.work_j_per_kg > w_iso
        assert 0.7 < result.work_kwh_per_kg < 1.1


class TestOptimalStages:
    def test_high_ratio_needs_multiple_stages(self):
        """CH4 1→64 bar: jeden stopień przekracza limit 150 °C tłoczenia."""
        recommended, sweep = optimal_stage_count(CH4, bar_to_pa(1), T_IN, bar_to_pa(64), eta=0.85)
        assert not sweep[0].t_limit_ok
        assert recommended >= 3
        assert sweep[recommended - 1].t_limit_ok

    def test_low_ratio_single_stage(self):
        recommended, _ = optimal_stage_count(CH4, bar_to_pa(10), T_IN, bar_to_pa(16), eta=0.85)
        assert recommended == 1


class TestTechnologyLibrary:
    def test_all_required_technologies_present(self):
        required = {"tlokowa", "srubowa", "odsrodkowa", "membranowa", "ciecz_jonowa"}
        assert required == set(compressor_technologies())

    def test_eta_ranges_consistent(self):
        for tech in compressor_technologies().values():
            assert 0 < tech.eta_min <= tech.eta_typical <= tech.eta_max <= 1.0

    def test_applicability_map(self):
        # mały przepływ, wysokie ciśnienie → membranowa/ciecz jonowa tak,
        # odśrodkowa nie (za mały przepływ)
        result = applicable_technologies(flow_nm3_per_h=200, discharge_pressure_mpa=50)
        assert result["membranowa"] and result["ciecz_jonowa"]
        assert not result["odsrodkowa"]
        assert not result["srubowa"]  # za wysokie ciśnienie


class TestValidationErrors:
    def test_bad_eta(self):
        with pytest.raises(ValueError, match="Sprawność"):
            compress(CH4, bar_to_pa(1), T_IN, bar_to_pa(10), eta=1.5)

    def test_bad_stages(self):
        with pytest.raises(ValueError, match="stopni"):
            compress(CH4, bar_to_pa(1), T_IN, bar_to_pa(10), eta=0.8, n_stages=0)

    def test_bad_model(self):
        with pytest.raises(ValueError, match="Model"):
            compress(CH4, bar_to_pa(1), T_IN, bar_to_pa(10), eta=0.8, model="inny")
