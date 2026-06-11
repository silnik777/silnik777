"""Testy modułu gazociągów (core.pipeline) — walidacja vs wykres Moody'ego."""

import pytest

from core.composition import GasComposition
from core.pipeline import (
    friction_factor,
    max_mass_flow_kg_per_s,
    pipe_materials,
    pressure_profile,
)
from core.units import bar_to_pa

CH4 = GasComposition.pure("CH4")
H2 = GasComposition.pure("H2")
T = 283.15  # 10 °C


class TestFrictionFactor:
    def test_laminar(self):
        """Re < 2300: λ = 64/Re (rozwiązanie ścisłe Hagena-Poiseuille'a)."""
        assert friction_factor(1000.0, 0.0) == pytest.approx(0.064)

    def test_smooth_turbulent_moody(self):
        """Rura gładka, Re = 1e5: λ ≈ 0,0180 (wykres Moody'ego)."""
        assert friction_factor(1.0e5, 0.0) == pytest.approx(0.0180, rel=0.02)

    def test_fully_rough_limit(self):
        """Re→∞, k/D = 1e-4: λ → [−2·log10(k/D/3,7)]⁻² ≈ 0,0120 (Nikuradse)."""
        lam_inf = (-2.0 * __import__("math").log10(1e-4 / 3.7)) ** -2
        assert friction_factor(1.0e9, 1e-4) == pytest.approx(lam_inf, rel=0.01)

    def test_colebrook_satisfied(self):
        """Wynik spełnia równanie Colebrooka-White'a (residuum < 1e-9)."""
        import math

        re, rr = 5.0e5, 5e-5
        lam = friction_factor(re, rr)
        lhs = 1.0 / math.sqrt(lam)
        rhs = -2.0 * math.log10(rr / 3.7 + 2.51 / (re * math.sqrt(lam)))
        assert lhs == pytest.approx(rhs, abs=1e-9)

    def test_invalid_reynolds(self):
        with pytest.raises(ValueError, match="Reynoldsa"):
            friction_factor(-1.0, 0.0)


class TestPressureProfile:
    KWARGS = dict(
        diameter_m=0.3,
        length_m=20_000.0,
        roughness_m=5e-5,
        pressure_in_pa=bar_to_pa(55),
        temperature_k=T,
    )

    def test_pressure_decreases_velocity_increases(self):
        res = pressure_profile(CH4, mass_flow_kg_per_s=20.0, **self.KWARGS)
        p = res.pressure_profile_pa
        v = res.velocity_profile_m_per_s
        assert all(a > b for a, b in zip(p, p[1:], strict=False))
        assert all(a <= b for a, b in zip(v, v[1:], strict=False))

    def test_double_length_doubles_p2_drop(self):
        """Δ(p²) ≈ proporcjonalne do L (równanie przepływu izotermicznego)."""
        kw = dict(self.KWARGS)
        res1 = pressure_profile(CH4, mass_flow_kg_per_s=15.0, **kw)
        kw["length_m"] = 40_000.0
        res2 = pressure_profile(CH4, mass_flow_kg_per_s=15.0, **kw)
        dp2_1 = res1.pressure_in_pa**2 - res1.pressure_out_pa**2
        dp2_2 = res2.pressure_in_pa**2 - res2.pressure_out_pa**2
        assert dp2_2 / dp2_1 == pytest.approx(2.0, rel=0.03)

    def test_capacity_exceeded_polish_error(self):
        with pytest.raises(ValueError, match="przepustowość"):
            pressure_profile(CH4, mass_flow_kg_per_s=500.0, **self.KWARGS)

    def test_invalid_inputs(self):
        with pytest.raises(ValueError, match="Średnica"):
            pressure_profile(
                CH4,
                mass_flow_kg_per_s=1.0,
                diameter_m=-0.3,
                length_m=1000.0,
                roughness_m=5e-5,
                pressure_in_pa=bar_to_pa(10),
                temperature_k=T,
            )


class TestMaxFlowAndEnergy:
    ARGS = dict(
        diameter_m=0.3,
        length_m=20_000.0,
        roughness_m=5e-5,
        pressure_in_pa=bar_to_pa(55),
        pressure_out_min_pa=bar_to_pa(45),
        temperature_k=T,
    )

    def test_bisection_hits_target_pressure(self):
        m_max = max_mass_flow_kg_per_s(CH4, **self.ARGS)
        res = pressure_profile(CH4, 0.3, 20_000.0, 5e-5, m_max, bar_to_pa(55), T)
        assert res.pressure_out_pa == pytest.approx(bar_to_pa(45), rel=0.01)

    def test_h2_vs_ng_energy_throughput(self):
        """Ta sama rura: przepustowość energetyczna H2 ≈ 0,7–1,1 × GZ.

        Literatura (np. Haeseldonckx & D'haeseleer 2007; DNV): mimo ~3×
        mniejszej gęstości energii na m³, H2 płynie ~3× szybciej — strumień
        energii jest zbliżony (80–98% GZ przy tych samych ciśnieniach).
        """
        m_ch4 = max_mass_flow_kg_per_s(CH4, **self.ARGS)
        m_h2 = max_mass_flow_kg_per_s(H2, **self.ARGS)
        mw_ch4 = pressure_profile(
            CH4, 0.3, 20_000.0, 5e-5, m_ch4, bar_to_pa(55), T
        ).energy_flow_mw()
        mw_h2 = pressure_profile(H2, 0.3, 20_000.0, 5e-5, m_h2, bar_to_pa(55), T).energy_flow_mw()
        assert 0.7 < mw_h2 / mw_ch4 < 1.1
        # masowo H2 płynie mniej kg/s, ale ma ~6× wyższą wartość opałową
        assert m_h2 < m_ch4

    def test_energy_flow_consistency(self):
        res = pressure_profile(CH4, 0.3, 20_000.0, 5e-5, 10.0, bar_to_pa(55), T)
        # Hi(CH4) ≈ 50 MJ/kg → 10 kg/s ≈ 500 MW
        assert res.energy_flow_mw() == pytest.approx(500.0, rel=0.01)


class TestAnalyticCrossCheck:
    def test_marching_model_vs_general_flow_equation(self):
        """Model marszowy vs analityczne równanie przepływu izotermicznego.

        Dla stałych Z̄, T, λ całka równania Darcy-Weisbacha po długości daje:
            p₁² − p₂² = λ · (16/π²) · (Z̄·R·T/M) · ṁ² · L / D⁵
        (ogólne równanie przepływu, np. Menon "Gas Pipeline Hydraulics" 2005,
        z pominięciem członu kinetycznego). Model marszowy z lokalnymi
        właściwościami musi się z nim zgadzać przy umiarkowanym spadku
        ciśnienia (tu ~10%), gdzie Z i λ są niemal stałe.
        """
        import math

        from core.units import R_UNIVERSAL_J_PER_MOL_K

        d, length, rough, m_flow = 0.3, 20_000.0, 5e-5, 15.0
        res = pressure_profile(CH4, d, length, rough, m_flow, bar_to_pa(55), T)

        p_mean = (res.pressure_in_pa + res.pressure_out_pa) / 2.0
        from core.gas_properties import compute_properties

        props_mean = compute_properties(CH4, p_mean, T)
        z_mean = props_mean.z_factor
        m_molar = CH4.molar_mass_kg_per_kmol / 1e3  # kg/mol
        lam = res.friction_factor_inlet

        dp2_analytic = (
            lam
            * (16.0 / math.pi**2)
            * (z_mean * R_UNIVERSAL_J_PER_MOL_K * T / m_molar)
            * m_flow**2
            * length
            / d**5
        )
        dp2_model = res.pressure_in_pa**2 - res.pressure_out_pa**2
        assert dp2_model == pytest.approx(dp2_analytic, rel=0.03)


class TestMaterials:
    def test_three_materials_with_hdpe(self):
        mats = pipe_materials()
        assert {"stal", "pe_nowe", "hdpe_starsze"} == set(mats)
        assert mats["hdpe_starsze"].note  # oznaczenie wartości orientacyjnej

    def test_roughness_ordering(self):
        mats = pipe_materials()
        assert (
            mats["pe_nowe"].roughness_typical_mm
            < mats["hdpe_starsze"].roughness_typical_mm
            < mats["stal"].roughness_typical_mm
        )
