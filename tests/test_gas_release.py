"""Testy modułu strat gazu z awarii (core.gas_release)."""

import math

import pytest

from core.composition import GasComposition
from core.gas_properties import compute_properties
from core.gas_release import (
    blowdown,
    critical_pressure_ratio,
    flammable_jet_extent,
    gas_release_rate,
)
from core.units import NORMAL_0C

E_GAS = GasComposition.predefined("gaz_E_typowy")


class TestCriticalRatio:
    def test_known_value(self):
        """r_kryt dla k=1,3: (2,3/2)^(1,3/0,3) ≈ 1,832."""
        assert critical_pressure_ratio(1.3) == pytest.approx(1.832, abs=0.005)

    def test_ideal_diatomic(self):
        """k=1,4 → r_kryt ≈ 1,893 (klasyczna wartość)."""
        assert critical_pressure_ratio(1.4) == pytest.approx(1.893, abs=0.005)


class TestReleaseRate:
    def test_choked_at_high_pressure(self):
        r = gas_release_rate(E_GAS, 5.5e6, 283.15, 0.05)
        assert r.choked
        assert r.pressure_ratio > r.critical_pressure_ratio
        assert r.mass_flow_kg_per_s > 0
        assert r.velocity_at_hole_m_per_s > 200.0  # sonic w gardzieli

    def test_subsonic_at_low_overpressure(self):
        r = gas_release_rate(E_GAS, 1.2e5, 283.15, 0.05)
        assert not r.choked
        assert r.pressure_ratio < r.critical_pressure_ratio

    def test_mass_flow_scales_with_area(self):
        """Podwojenie średnicy → 4× natężenie (A ∝ d²)."""
        r1 = gas_release_rate(E_GAS, 5.5e6, 283.15, 0.05)
        r2 = gas_release_rate(E_GAS, 5.5e6, 283.15, 0.10)
        assert r2.mass_flow_kg_per_s == pytest.approx(4.0 * r1.mass_flow_kg_per_s, rel=1e-6)

    def test_mass_flow_proportional_to_upstream_pressure_when_choked(self):
        """Wypływ krytyczny: ṁ ∝ p₁ (przy tym samym T, składzie, ~Z)."""
        r1 = gas_release_rate(E_GAS, 4.0e6, 283.15, 0.05)
        r2 = gas_release_rate(E_GAS, 8.0e6, 283.15, 0.05)
        # nie idealnie liniowe (Z(p)), ale w granicach ~8%
        assert r2.mass_flow_kg_per_s / r1.mass_flow_kg_per_s == pytest.approx(2.0, rel=0.08)

    def test_volumetric_conversions_consistent(self):
        r = gas_release_rate(E_GAS, 5.5e6, 283.15, 0.05)
        assert r.volumetric_flow_nm3_per_min == pytest.approx(r.volumetric_flow_nm3_per_h / 60.0)
        # Nm³/h = masa / ρ_n
        assert r.volumetric_flow_nm3_per_h == pytest.approx(
            r.mass_flow_kg_per_s / r.density_normal_kg_per_m3 * 3600.0
        )

    def test_cd_scales_linearly(self):
        r1 = gas_release_rate(E_GAS, 5.5e6, 283.15, 0.05, discharge_coefficient=0.6)
        r2 = gas_release_rate(E_GAS, 5.5e6, 283.15, 0.05, discharge_coefficient=1.0)
        assert r2.mass_flow_kg_per_s / r1.mass_flow_kg_per_s == pytest.approx(1.0 / 0.6, rel=1e-9)

    def test_rejects_pressure_below_ambient(self):
        with pytest.raises(ValueError, match="przekracza"):
            gas_release_rate(E_GAS, 1.0e5, 283.15, 0.05)

    def test_rejects_bad_hole(self):
        with pytest.raises(ValueError, match="Średnica"):
            gas_release_rate(E_GAS, 5.5e6, 283.15, 0.0)


class TestBlowdown:
    PIPE_V = math.pi * 0.15**2 * 1000.0  # 1 km DN300

    def test_total_lost_matches_density_difference(self):
        b = blowdown(E_GAS, self.PIPE_V, 5.5e6, 283.15, 0.05)
        rho_hi = compute_properties(E_GAS, 5.5e6, 283.15).density_kg_per_m3
        rho_lo = compute_properties(E_GAS, 101_325.0, 283.15).density_kg_per_m3
        expected_kg = (rho_hi - rho_lo) * self.PIPE_V
        assert b.total_lost_kg == pytest.approx(expected_kg, rel=1e-6)
        rho_n = compute_properties(
            E_GAS, NORMAL_0C.pressure_pa, NORMAL_0C.temperature_k
        ).density_kg_per_m3
        assert b.total_lost_nm3 == pytest.approx(expected_kg / rho_n, rel=1e-6)

    def test_time_positive_and_pressure_monotone(self):
        b = blowdown(E_GAS, self.PIPE_V, 5.5e6, 283.15, 0.05)
        assert b.blowdown_time_s > 0
        assert b.blowdown_time_min == pytest.approx(b.blowdown_time_s / 60.0)
        assert all(
            b.pressures_pa[i] > b.pressures_pa[i + 1] for i in range(len(b.pressures_pa) - 1)
        )
        assert all(t2 > t1 for t1, t2 in zip(b.times_s, b.times_s[1:], strict=False))

    def test_bigger_hole_faster_blowdown(self):
        slow = blowdown(E_GAS, self.PIPE_V, 5.5e6, 283.15, 0.03)
        fast = blowdown(E_GAS, self.PIPE_V, 5.5e6, 283.15, 0.10)
        assert fast.blowdown_time_s < slow.blowdown_time_s
        # ilość utraconego gazu nie zależy od średnicy otworu
        assert fast.total_lost_nm3 == pytest.approx(slow.total_lost_nm3, rel=1e-6)


class TestHazardZone:
    def test_extent_positive_for_combustible(self):
        r = gas_release_rate(E_GAS, 5.5e6, 283.15, 0.05)
        h = flammable_jet_extent(E_GAS, r)
        assert h is not None
        assert h.distance_to_lel_m > 0
        assert h.lel_vol_pct > 0

    def test_none_for_noncombustible(self):
        air = GasComposition.predefined("powietrze")
        r = gas_release_rate(air, 5.5e6, 283.15, 0.05)
        assert flammable_jet_extent(air, r) is None
