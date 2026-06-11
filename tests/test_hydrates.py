"""Testy korelacji hydratowej Towlera-Mokhataba (core.hydrates)."""

import pytest

from core.composition import GasComposition
from core.hydrates import check_hydrates, hydrate_temperature_k
from core.units import mpa_to_pa

CH4 = GasComposition.pure("CH4")
E_GAS = GasComposition.predefined("gaz_E_typowy")


class TestCorrelation:
    def test_regression_sg06_1000psia(self):
        """Punkt kontrolny: SG≈0,6; 1000 psia (6,895 MPa) ⇒ ~61°F ≈ 16,2 °C.

        Wartość referencyjna z wykresu Katza (GPSA): dla gazu SG = 0,6 przy
        1000 psia temperatura hydratów ≈ 60–62 °F. Skład 94,4% CH4 / 5,6%
        C2H6 daje SG = 0,600.
        """
        comp = GasComposition.from_fractions({"CH4": 0.944, "C2H6": 0.056})
        t_hyd, _ = hydrate_temperature_k(comp, 1000.0 * 6894.757)
        assert t_hyd == pytest.approx(273.15 + 16.2, abs=1.5)

    def test_methane_conservative_vs_experiment(self):
        """Czysty CH4, 6,9 MPa: eksperyment ~283 K (Sloan & Koh) — korelacja
        musi być konserwatywna (zawyżać T_hyd), nie więcej niż o ~7 K."""
        t_hyd, _ = hydrate_temperature_k(CH4, mpa_to_pa(6.9))
        t_experimental = 283.0
        assert t_experimental - 0.5 <= t_hyd <= t_experimental + 7.0

    def test_monotonic_in_pressure(self):
        """T_hyd rośnie z ciśnieniem (fizyka równowagi hydratów)."""
        temps = [hydrate_temperature_k(E_GAS, mpa_to_pa(p))[0] for p in (1.0, 3.0, 6.0, 10.0)]
        assert temps == sorted(temps)

    def test_heavier_gas_higher_hydrate_temp(self):
        """Cięższy gaz (więcej C2+) ⇒ wyższa T_hyd przy tym samym p."""
        light = hydrate_temperature_k(CH4, mpa_to_pa(5.0))[0]
        heavy = hydrate_temperature_k(
            GasComposition.from_fractions({"CH4": 0.90, "C3H8": 0.10}), mpa_to_pa(5.0)
        )[0]
        assert heavy > light

    def test_invalid_pressure(self):
        with pytest.raises(ValueError, match="dodatnie"):
            hydrate_temperature_k(CH4, -1.0)


class TestHydrogenHandling:
    def test_pure_h2_no_risk(self):
        t_hyd, warnings = hydrate_temperature_k(GasComposition.pure("H2"), mpa_to_pa(5.0))
        assert t_hyd is None
        assert any("brak ryzyka" in w.lower() for w in warnings)

    def test_blend_conservative_warning(self):
        """Mieszanina 20% H2: T_hyd liczona konserwatywnie + ostrzeżenie."""
        blend = E_GAS.blend_with_hydrogen(0.20)
        t_blend, warnings = hydrate_temperature_k(blend, mpa_to_pa(5.0))
        t_base, _ = hydrate_temperature_k(E_GAS, mpa_to_pa(5.0))
        # konserwatywnie: frakcja GZ przy pełnym p ⇒ wynik ≈ jak dla GZ
        assert t_blend == pytest.approx(t_base, abs=0.5)
        assert any("konserwatywnie" in w for w in warnings)

    def test_check_hydrates_margin(self):
        check = check_hydrates(E_GAS, mpa_to_pa(1.7))
        assert check.min_safe_temperature_k == pytest.approx(
            check.hydrate_temperature_k + check.margin_k
        )
        assert check.is_at_risk(check.min_safe_temperature_k - 1.0)
        assert not check.is_at_risk(check.min_safe_temperature_k + 1.0)

    def test_pure_h2_never_at_risk(self):
        check = check_hydrates(GasComposition.pure("H2"), mpa_to_pa(5.0))
        assert not check.is_at_risk(200.0)
