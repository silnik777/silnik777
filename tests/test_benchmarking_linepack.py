"""Testy M11 (benchmarking) i M12 (linepack)."""

import pytest

from core.benchmarking import (
    battery_lcos_pln_per_mwh,
    build_benchmark_entries,
    rank_technologies,
)
from core.composition import GasComposition
from core.linepack import linepack
from core.prices import builtin_scenarios
from core.units import R_UNIVERSAL_J_PER_MOL_K, bar_to_pa

SC = builtin_scenarios()["bazowy"]
E_GAS = GasComposition.predefined("gaz_E_typowy")


class TestBenchmarking:
    def test_entries_complete(self):
        entries = build_benchmark_entries(SC, 2030)
        keys = {e.key for e in entries}
        assert {"pv", "wiatr_ladowy", "ccgt", "bateria", "ogniwo_pemfc"} <= keys
        for e in entries:
            assert e.lcox_pln_per_mwh > 0
            assert 0 <= e.dispatchability <= 1
            assert 1 <= e.trl <= 9

    def test_battery_lcos_above_electricity_price(self):
        """LCOS > cena energii ładowania (CAPEX + straty RT)."""
        lcos = battery_lcos_pln_per_mwh(SC, 2030)
        assert lcos > SC.price("energia_elektryczna", 2030) / 0.88

    def test_equal_weights_ranking_sorted(self):
        ranked = rank_technologies(build_benchmark_entries(SC, 2030))
        scores = [r.score for r in ranked]
        assert scores == sorted(scores, reverse=True)
        assert all(0 <= s <= 1 for s in scores)

    def test_emission_weight_promotes_clean(self):
        """Waga 100% na emisje ⇒ technologia bezemisyjna na czele."""
        entries = build_benchmark_entries(SC, 2030)
        ranked = rank_technologies(
            entries, weights={"koszt": 0, "emisje": 1, "dyspozycyjnosc": 0, "trl": 0}
        )
        assert ranked[0].entry.co2_g_per_kwh == min(e.co2_g_per_kwh for e in entries)

    def test_cost_weight_promotes_cheapest(self):
        entries = build_benchmark_entries(SC, 2030)
        ranked = rank_technologies(
            entries, weights={"koszt": 1, "emisje": 0, "dyspozycyjnosc": 0, "trl": 0}
        )
        assert ranked[0].entry.lcox_pln_per_mwh == min(e.lcox_pln_per_mwh for e in entries)

    def test_weights_validation(self):
        entries = build_benchmark_entries(SC, 2030)
        with pytest.raises(ValueError, match="Suma wag"):
            rank_technologies(
                entries, weights={"koszt": 0, "emisje": 0, "dyspozycyjnosc": 0, "trl": 0}
            )
        with pytest.raises(ValueError, match="Nieznane kryteria"):
            rank_technologies(entries, weights={"uroda": 1.0})


class TestLinepack:
    ARGS = dict(
        diameter_m=0.5,
        length_m=50_000.0,
        pressure_min_pa=bar_to_pa(45),
        pressure_max_pa=bar_to_pa(55),
        temperature_k=283.15,
    )

    def test_real_gas_cross_check(self):
        """Δm = V·M/(R·T)·(p_max/Z_max − p_min/Z_min) — relacja ścisła.

        Uwaga: zmienność Z(p) podbija bufor o ~12% względem przybliżenia
        ze stałym Z̄ — stąd porównanie na poziomach, nie na różnicy ciśnień.
        """
        res = linepack(E_GAS, **self.ARGS)
        from core.gas_properties import compute_properties

        m_molar = E_GAS.molar_mass_kg_per_kmol / 1e3
        factor = res.geometric_volume_m3 * m_molar / (R_UNIVERSAL_J_PER_MOL_K * 283.15)
        z_max = compute_properties(E_GAS, self.ARGS["pressure_max_pa"], 283.15).z_factor
        z_min = compute_properties(E_GAS, self.ARGS["pressure_min_pa"], 283.15).z_factor
        dm_exact = factor * (
            self.ARGS["pressure_max_pa"] / z_max - self.ARGS["pressure_min_pa"] / z_min
        )
        assert res.buffer_mass_kg == pytest.approx(dm_exact, rel=0.005)

    def test_energy_and_dynamics(self):
        res = linepack(E_GAS, **self.ARGS)
        assert res.buffer_energy_mwh > 0
        assert res.energy_total_at_pmax_mwh > res.buffer_energy_mwh
        # bufor [h] przy poborze: E/P
        assert res.buffer_hours_at_load(10.0) == pytest.approx(res.buffer_energy_mwh / 10.0)

    def test_round_trip_cost_plausible(self):
        """Sprężanie 45→55 bar: ~0,2–3 kWh el./MWh bufora (mały spręż)."""
        res = linepack(E_GAS, **self.ARGS)
        assert 0.2 < res.compression_kwh_el_per_mwh < 3.0

    def test_h2_lower_volumetric_buffer(self):
        """H2: bufor energetyczny ~3× mniejszy niż GZ (gęstość energii)."""
        gas = linepack(E_GAS, **self.ARGS)
        h2 = linepack(GasComposition.pure("H2"), **self.ARGS)
        assert 0.2 < h2.buffer_energy_mwh / gas.buffer_energy_mwh < 0.45
        # ale koszt sprężania na MWh — wyraźnie wyższy
        assert h2.compression_kwh_el_per_mwh > 2.0 * gas.compression_kwh_el_per_mwh

    def test_validation(self):
        with pytest.raises(ValueError, match="p_max"):
            linepack(E_GAS, 0.5, 1000.0, bar_to_pa(55), bar_to_pa(45))
        res = linepack(E_GAS, **self.ARGS)
        with pytest.raises(ValueError, match="dodatni"):
            res.buffer_hours_at_load(0.0)
