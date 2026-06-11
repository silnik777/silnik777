"""Testy walidacyjne metody ISO 6976 (core.calorific)."""

import pytest

from core.calorific import calorific_values, energy_density_at_state, quality_flags
from core.composition import GasComposition
from core.gas_properties import compute_properties
from core.units import NORMAL_0C, STANDARD_15C, bar_to_pa
from tests.reference_data import CALORIFIC_REFERENCES


class TestValidationAgainstReferences:
    @pytest.mark.parametrize(
        "ref", CALORIFIC_REFERENCES, ids=[r.label for r in CALORIFIC_REFERENCES]
    )
    def test_reference_value(self, ref):
        result = calorific_values(GasComposition.pure(ref.component))
        value = getattr(result, ref.quantity)
        assert value == pytest.approx(ref.reference_value, rel=ref.rel_tolerance), (
            f"{ref.label}: obliczone {value:.6g}, referencja {ref.reference_value:.6g} "
            f"({ref.source})"
        )

    def test_z_air_matches_iso6976(self):
        """ISO 6976: Z powietrza (0 °C; 101,325 kPa) = 0,99941."""
        from core.calorific import _z_pure_air

        z = _z_pure_air(NORMAL_0C.temperature_k, NORMAL_0C.pressure_pa)
        assert z == pytest.approx(0.99941, rel=1e-4)


class TestMethodConsistency:
    def test_molar_values_mix_linearly(self):
        """Hs_molar mieszaniny = Σ x_j·Hs_j (dokładna liniowość metody)."""
        mix = GasComposition.from_fractions({"CH4": 0.6, "H2": 0.4})
        r_mix = calorific_values(mix)
        r_ch4 = calorific_values(GasComposition.pure("CH4"))
        r_h2 = calorific_values(GasComposition.pure("H2"))
        expected = 0.6 * r_ch4.hs_molar_kj_per_mol + 0.4 * r_h2.hs_molar_kj_per_mol
        assert r_mix.hs_molar_kj_per_mol == pytest.approx(expected, rel=1e-12)

    def test_hi_below_hs(self):
        for key in ("CH4", "H2"):
            r = calorific_values(GasComposition.pure(key))
            assert r.hi_molar_kj_per_mol < r.hs_molar_kj_per_mol

    def test_inert_dilution_lowers_calorific_value(self):
        diluted = GasComposition.from_fractions({"CH4": 0.9, "N2": 0.1})
        r_pure = calorific_values(GasComposition.pure("CH4"))
        r_dil = calorific_values(diluted)
        assert r_dil.hs_mj_per_m3 < r_pure.hs_mj_per_m3

    def test_volume_reference_15c(self):
        """Hs na m³ przy 15 °C ≈ Hs(0 °C) · 273,15/288,15 (gęstszy gaz w 0 °C)."""
        r0 = calorific_values(GasComposition.pure("CH4"), NORMAL_0C)
        r15 = calorific_values(GasComposition.pure("CH4"), STANDARD_15C)
        assert r15.hs_mj_per_m3 == pytest.approx(r0.hs_mj_per_m3 * 273.15 / 288.15, rel=2e-3)

    def test_e_gas_plausible_range(self):
        """Gaz E: Hs ≈ 39–41 MJ/m³, Ws ≈ 49–57 MJ/m³ (zakres rozliczeniowy PL)."""
        r = calorific_values(GasComposition.predefined("gaz_E_typowy"))
        assert 39.0 < r.hs_mj_per_m3 < 41.5
        assert 49.0 < r.wobbe_superior_mj_per_m3 < 57.0

    def test_energy_density_at_state(self):
        comp = GasComposition.pure("CH4")
        cal = calorific_values(comp)
        props = compute_properties(comp, bar_to_pa(50), 293.15)
        e = energy_density_at_state(cal, props)
        # 50 bar → ok. 50× gęstość energii względem warunków normalnych
        assert e["hi_mj_per_m3_at_state"] == pytest.approx(
            cal.hi_mj_per_m3 * 50 * 273.15 / 293.15 / props.z_factor, rel=0.02
        )


class TestQualityFlags:
    def test_e_gas_wobbe_ok(self):
        comp = GasComposition.predefined("gaz_E_typowy")
        flags = quality_flags(comp, calorific_values(comp))
        wobbe = next(f for f in flags if "Wobbego" in f.name_pl)
        assert wobbe.ok

    def test_pure_h2_wobbe_within_group_e(self):
        """Ws(H2) ≈ 48,3 MJ/m³ mieści się w widełkach grupy E (45,0–56,9) —
        kluczowy argument w dyskusji o domieszkowaniu wodoru."""
        comp = GasComposition.pure("H2")
        flags = quality_flags(comp, calorific_values(comp))
        wobbe = next(f for f in flags if "Wobbego" in f.name_pl)
        assert wobbe.ok
        assert wobbe.value == pytest.approx(48.3, rel=0.005)

    def test_diluted_gas_wobbe_fails_group_e(self):
        """Gaz silnie zaazotowany (60% CH4 / 40% N2) wypada poniżej widełek E."""
        comp = GasComposition.from_fractions({"CH4": 0.6, "N2": 0.4})
        flags = quality_flags(comp, calorific_values(comp))
        wobbe = next(f for f in flags if "Wobbego" in f.name_pl)
        assert not wobbe.ok

    def test_h2_threshold_flag(self):
        comp = GasComposition.predefined("gaz_E_typowy").blend_with_hydrogen(0.1)
        flags = quality_flags(comp, calorific_values(comp), h2_limit_mol_pct=5.0)
        h2_flag = next(f for f in flags if "H2" in f.name_pl)
        assert not h2_flag.ok
        assert h2_flag.value == pytest.approx(10.0)

    def test_blend_within_threshold_ok(self):
        comp = GasComposition.predefined("gaz_E_typowy").blend_with_hydrogen(0.02)
        flags = quality_flags(comp, calorific_values(comp), h2_limit_mol_pct=5.0)
        assert all(f.ok for f in flags)
