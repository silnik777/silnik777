"""Testy walidacyjne i spójności właściwości gazów (core.gas_properties)."""

import pytest

from core.composition import GasComposition
from core.gas_properties import compute_properties
from core.units import R_UNIVERSAL_J_PER_MOL_K, bar_to_pa, celsius_to_kelvin
from tests.reference_data import PROPERTY_REFERENCES


class TestValidationAgainstReferences:
    @pytest.mark.parametrize(
        "ref",
        PROPERTY_REFERENCES,
        ids=[f"{r.component}-{r.quantity}-{r.temperature_k:g}K" for r in PROPERTY_REFERENCES],
    )
    def test_reference_value(self, ref):
        props = compute_properties(
            GasComposition.pure(ref.component), ref.pressure_pa, ref.temperature_k
        )
        value = getattr(props, ref.quantity)
        assert value == pytest.approx(ref.reference_value, rel=ref.rel_tolerance), (
            f"{ref.component}/{ref.quantity}: obliczone {value:.6g}, "
            f"referencja {ref.reference_value:.6g} ({ref.source})"
        )


class TestPhysicalConsistency:
    def test_ideal_gas_limit_low_pressure(self):
        """Przy p → 0: Z → 1 oraz cp − cv → R/M."""
        props = compute_properties(GasComposition.pure("CH4"), 1_000.0, 293.15)
        assert props.z_factor == pytest.approx(1.0, abs=1e-4)
        r_specific = R_UNIVERSAL_J_PER_MOL_K / (props.molar_mass_kg_per_kmol * 1e-3) * 1e3
        assert (props.cp_j_per_kg_k - props.cv_j_per_kg_k) == pytest.approx(
            r_specific / 1e3, rel=5e-3
        )

    def test_isentropic_exponent_near_gamma_at_low_p(self):
        """Dla gazu bliskiego doskonałemu κ ≈ cp/cv."""
        props = compute_properties(GasComposition.pure("CH4"), 101_325.0, 293.15)
        assert props.isentropic_exponent == pytest.approx(props.cp_over_cv, rel=0.01)

    def test_jt_sign_methane_positive_hydrogen_negative(self):
        """μ_JT(CH4) > 0 (chłodzenie przy dławieniu), μ_JT(H2) < 0 przy otoczeniu."""
        ch4 = compute_properties(GasComposition.pure("CH4"), bar_to_pa(50), 293.15)
        h2 = compute_properties(GasComposition.pure("H2"), bar_to_pa(50), 293.15)
        assert ch4.joule_thomson_k_per_bar > 0.2
        assert h2.joule_thomson_k_per_bar < 0.0

    def test_mixture_z_between_endpoints(self):
        """Z mieszaniny 50/50 CH4/H2 pomiędzy Z czystych składników (10 MPa)."""
        p, t = bar_to_pa(100), 293.15
        z_ch4 = compute_properties(GasComposition.pure("CH4"), p, t).z_factor
        z_h2 = compute_properties(GasComposition.pure("H2"), p, t).z_factor
        z_mix = compute_properties(
            GasComposition.from_fractions({"CH4": 0.5, "H2": 0.5}), p, t
        ).z_factor
        assert min(z_ch4, z_h2) < z_mix < max(z_ch4, z_h2)

    def test_full_e_gas_with_viscosity(self):
        """Pełny skład gazu E: wszystkie wielkości policzalne w (5 MPa, 20 °C)."""
        props = compute_properties(GasComposition.predefined("gaz_E_typowy"), bar_to_pa(50), 293.15)
        assert 0.85 < props.z_factor < 1.0
        assert props.viscosity_pa_s is not None
        assert props.viscosity_method == "CoolProp"
        assert 1.0e-5 < props.viscosity_pa_s < 2.0e-5


class TestRangeAndErrors:
    def test_warning_above_10mpa(self):
        props = compute_properties(GasComposition.pure("CH4"), 2.0e7, 293.15)
        assert any("10 MPa" in w for w in props.warnings)

    def test_warning_temperature_out_of_range(self):
        props = compute_properties(GasComposition.pure("CH4"), 101_325.0, celsius_to_kelvin(80.0))
        assert any("zakresem" in w for w in props.warnings)

    def test_no_warnings_in_default_range(self):
        props = compute_properties(GasComposition.pure("CH4"), bar_to_pa(50), 293.15)
        assert props.warnings == []

    def test_invalid_pressure_polish(self):
        with pytest.raises(ValueError, match="Ciśnienie musi być dodatnie"):
            compute_properties(GasComposition.pure("CH4"), -1.0, 293.15)
