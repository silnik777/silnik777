"""Testy obsługi powietrza (M3) i trybu CAES w linepacku (M12)."""

import pytest

from core.composition import GasComposition
from core.gas_properties import compute_properties
from core.linepack import linepack
from core.pipeline import max_mass_flow_kg_per_s, pressure_profile
from core.units import bar_to_pa

AIR = GasComposition.predefined("powietrze")
E_GAS = GasComposition.predefined("gaz_E_typowy")


class TestAirComposition:
    def test_air_not_combustible(self):
        assert not AIR.is_combustible
        assert E_GAS.is_combustible

    def test_air_density_reference(self):
        """Gęstość suchego powietrza w war. normalnych ≈ 1,293 kg/m³."""
        rho = compute_properties(AIR, 101_325.0, 273.15).density_kg_per_m3
        assert rho == pytest.approx(1.293, rel=0.01)

    def test_air_molar_mass(self):
        """Masa molowa powietrza ≈ 28,96 kg/kmol."""
        assert AIR.molar_mass_kg_per_kmol == pytest.approx(28.96, rel=0.005)

    def test_argon_present(self):
        from core.composition import components_registry

        assert "Ar" in components_registry()


class TestAirPipeline:
    def test_air_flow_computable(self):
        """M3 liczy hydraulikę dla powietrza (mimo zerowej wartości opałowej)."""
        d, length, rough = 0.3, 10_000.0, 5e-5
        m_max = max_mass_flow_kg_per_s(AIR, d, length, rough, bar_to_pa(55), bar_to_pa(45), 283.15)
        res = pressure_profile(AIR, d, length, rough, m_max, bar_to_pa(55), 283.15)
        assert res.mass_flow_kg_per_s > 0
        assert res.max_velocity_m_per_s > 0
        assert res.energy_flow_mw() == 0.0  # niepalny


class TestCAES:
    ARGS = dict(
        diameter_m=0.5,
        length_m=50_000.0,
        pressure_min_pa=bar_to_pa(40),
        pressure_max_pa=bar_to_pa(70),
        temperature_k=283.15,
    )

    def test_air_caes_mode(self):
        res = linepack(AIR, **self.ARGS)
        assert not res.is_combustible
        assert res.buffer_energy_mwh == 0.0  # brak energii chemicznej
        assert res.caes_recovered_mwh > 0.0
        assert res.compression_kwh_el > 0.0

    def test_round_trip_below_one_and_plausible(self):
        """Round-trip diabatyczny CAES: dodatni, < 1, rozsądnie 30–80%."""
        res = linepack(AIR, **self.ARGS)
        assert 0.2 < res.caes_round_trip_efficiency < 1.0

    def test_recovered_less_than_input(self):
        """Energia odzyskana < energia napełnienia (II zasada)."""
        res = linepack(AIR, **self.ARGS)
        assert res.caes_recovered_mwh * 1e3 < res.compression_kwh_el

    def test_buffer_hours_uses_caes_energy_for_air(self):
        res = linepack(AIR, **self.ARGS)
        assert res.buffer_hours_at_load(10.0) == pytest.approx(res.caes_recovered_mwh / 10.0)

    def test_combustible_gas_keeps_chemical_buffer(self):
        res = linepack(E_GAS, **self.ARGS)
        assert res.is_combustible
        assert res.buffer_energy_mwh > 0.0
        # czas pokrycia liczony z energii chemicznej
        assert res.buffer_hours_at_load(10.0) == pytest.approx(res.buffer_energy_mwh / 10.0)


class TestLinepackIntegration:
    """Fix 3.4: praca cyklu bufora całkowana po N krokach ciśnienia."""

    ARGS = dict(
        diameter_m=0.5,
        length_m=50_000.0,
        pressure_min_pa=bar_to_pa(40),
        pressure_max_pa=bar_to_pa(70),
        temperature_k=283.15,
    )

    def _single_shot_fill_kwh(self, comp):
        """Pojedynczy skok: cała Δm sprężana p_min→p_max (zawyżenie)."""
        import math

        from core.compression import compress

        p_min, p_max = self.ARGS["pressure_min_pa"], self.ARGS["pressure_max_pa"]

        def rho(p):
            return compute_properties(comp, p, self.ARGS["temperature_k"]).density_kg_per_m3

        vol = math.pi * self.ARGS["diameter_m"] ** 2 / 4.0 * self.ARGS["length_m"]
        dm = (rho(p_max) - rho(p_min)) * vol
        w = compress(
            comp, p_min, self.ARGS["temperature_k"], p_max, eta=0.82, model="politropowy"
        ).work_kwh_per_kg
        return dm * w / 0.95  # napęd mech-el jak w linepack()

    def test_integrated_fill_below_single_shot(self):
        """Całkowanie po ciśnieniu daje mniej energii niż skok całej masy."""
        res = linepack(AIR, **self.ARGS)
        single = self._single_shot_fill_kwh(AIR)
        assert res.compression_kwh_el < single
        # ale nie drastycznie mniej — ten sam rząd wielkości
        assert res.compression_kwh_el > 0.5 * single

    def test_recovery_below_single_shot_expand(self):
        """Odzysk CAES < rozprężanie całej Δm od p_max (zawyżenie)."""
        import math

        from core.expanders import expand
        from core.units import j_to_kwh

        p_min, p_max = self.ARGS["pressure_min_pa"], self.ARGS["pressure_max_pa"]

        def rho(p):
            return compute_properties(AIR, p, self.ARGS["temperature_k"]).density_kg_per_m3

        vol = math.pi * self.ARGS["diameter_m"] ** 2 / 4.0 * self.ARGS["length_m"]
        dm = (rho(p_max) - rho(p_min)) * vol
        w_out = expand(AIR, p_max, self.ARGS["temperature_k"], p_min, eta=0.80).work_j_per_kg
        single_recovered_mwh = dm * j_to_kwh(w_out) * 0.95 / 1e3
        res = linepack(AIR, **self.ARGS)
        assert res.caes_recovered_mwh < single_recovered_mwh
        assert res.caes_recovered_mwh > 0.5 * single_recovered_mwh

    def test_round_trip_still_plausible_after_integration(self):
        res = linepack(AIR, **self.ARGS)
        assert 0.2 < res.caes_round_trip_efficiency < 1.0


class TestPressureExergy:
    """Energia ciśnienia (eksergia izotermiczna) bufora."""

    ARGS = dict(
        diameter_m=0.5,
        length_m=50_000.0,
        pressure_min_pa=bar_to_pa(40),
        pressure_max_pa=bar_to_pa(70),
        temperature_k=283.15,
    )

    def test_pressure_exergy_positive(self):
        assert linepack(AIR, **self.ARGS).pressure_exergy_mwh > 0.0
        assert linepack(E_GAS, **self.ARGS).pressure_exergy_mwh > 0.0

    def test_chemical_dominates_pressure_for_fuel_gas(self):
        """Dla gazu palnego energia chemiczna ≫ energia ciśnienia (≥100×)."""
        res = linepack(E_GAS, **self.ARGS)
        assert res.buffer_energy_mwh > 100.0 * res.pressure_exergy_mwh

    def test_air_has_no_chemical_only_pressure(self):
        res = linepack(AIR, **self.ARGS)
        assert res.buffer_energy_mwh == 0.0
        assert res.pressure_exergy_mwh > 0.0

    def test_exergy_matches_isothermal_cycle_fill(self):
        """Energia ciśnienia = napełnianie modelu izotermicznego (ta sama całka)."""
        from core.linepack import cycle_analysis

        res = linepack(AIR, **self.ARGS)
        iso = cycle_analysis(
            AIR,
            self.ARGS["diameter_m"],
            self.ARGS["length_m"],
            self.ARGS["pressure_min_pa"],
            self.ARGS["pressure_max_pa"],
            self.ARGS["temperature_k"],
        )[0]
        assert res.pressure_exergy_mwh == pytest.approx(iso.fill_mwh, rel=1e-9)


class TestCycleAnalysis:
    """Analiza typów sprężania/rozprężania (izotermiczne/izentropowe/politropowe)."""

    ARGS = dict(
        diameter_m=0.5,
        length_m=50_000.0,
        pressure_min_pa=bar_to_pa(40),
        pressure_max_pa=bar_to_pa(70),
        temperature_k=283.15,
    )

    def _models(self):
        from core.linepack import cycle_analysis

        return cycle_analysis(
            AIR,
            self.ARGS["diameter_m"],
            self.ARGS["length_m"],
            self.ARGS["pressure_min_pa"],
            self.ARGS["pressure_max_pa"],
            self.ARGS["temperature_k"],
        )

    def test_three_models(self):
        keys = [m.key for m in self._models()]
        assert keys == ["izotermiczne", "izentropowe", "politropowe"]

    def test_isothermal_round_trip_unity(self):
        """Izotermiczny odwracalny: round-trip = 100%, odzysk = napełnienie."""
        iso = self._models()[0]
        assert iso.round_trip == pytest.approx(1.0, abs=1e-9)
        assert iso.recovered_mwh == pytest.approx(iso.fill_mwh, rel=1e-9)

    def test_isothermal_is_min_work_max_recovery(self):
        """Izotermiczne: najmniejszy nakład i największy odzysk (granica II zas.)."""
        iso, isen, poly = self._models()
        assert iso.fill_mwh < isen.fill_mwh < poly.fill_mwh
        assert iso.recovered_mwh > isen.recovered_mwh > poly.recovered_mwh

    def test_round_trip_ordering(self):
        """Round-trip: izotermiczny (1) > izentropowy > politropowy."""
        iso, isen, poly = self._models()
        assert iso.round_trip > isen.round_trip > poly.round_trip
        assert isen.round_trip < 1.0  # diabatyczność mimo idealnych maszyn

    def test_bad_geometry_raises(self):
        from core.linepack import cycle_analysis

        with pytest.raises(ValueError, match="p_max"):
            cycle_analysis(AIR, 0.5, 50_000.0, bar_to_pa(70), bar_to_pa(40), 283.15)
