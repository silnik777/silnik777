"""Testy śledzenia składu i stref mieszania w sieci (core.network, M15)."""

import pytest

from core.composition import GasComposition
from core.gas_properties import compute_properties
from core.network import NetworkNode, NetworkPipe, solve_network
from core.units import bar_to_pa

E_GAS = GasComposition.predefined("gaz_E_typowy")
BIOMETHANE = GasComposition.predefined("biometan")
H2 = GasComposition.pure("H2")
T = 283.15


def _node(result, name):
    return next(n for n in result.nodes if n.name == name)


def _pipe(result, name):
    return next(p for p in result.pipes if p.pipe.name == name)


class TestUniformNetwork:
    def test_single_source_propagates_composition(self):
        """Jedno źródło: wszystkie węzły mają skład źródła i 100% jego udziału."""
        nodes = [
            NetworkNode("Z", "cisnieniowy", pressure_pa=bar_to_pa(55), composition=E_GAS),
            NetworkNode("A", "odbiorowy", offtake_kg_per_s=5.0),
            NetworkNode("B", "odbiorowy", offtake_kg_per_s=5.0),
        ]
        pipes = [
            NetworkPipe("R1", "Z", "A", 0.3, 5_000.0, 5e-5),
            NetworkPipe("R2", "A", "B", 0.25, 5_000.0, 5e-5),
        ]
        result = solve_network(E_GAS, nodes, pipes, T)
        for name in ("A", "B"):
            node = _node(result, name)
            assert node.composition.fraction("CH4") == pytest.approx(
                E_GAS.fraction("CH4"), abs=1e-9
            )
            assert node.source_shares == pytest.approx({"Z": 1.0})


class TestHydrogenInjection:
    def _network(self, h2_nm3_h: float):
        nodes = [
            NetworkNode("Z", "cisnieniowy", pressure_pa=bar_to_pa(55), composition=E_GAS),
            NetworkNode("przed", "odbiorowy", offtake_kg_per_s=0.0),
            NetworkNode(
                "Elektrolizer",
                "zrodlowy",
                injection_nm3_per_h=h2_nm3_h,
                composition=H2,
            ),
            NetworkNode("za", "odbiorowy", offtake_nm3_per_h=50_000.0),
        ]
        pipes = [
            NetworkPipe("R1", "Z", "przed", 0.3, 5_000.0, 5e-5),
            NetworkPipe("R2", "przed", "Elektrolizer", 0.3, 100.0, 5e-5),
            NetworkPipe("R3", "Elektrolizer", "za", 0.3, 5_000.0, 5e-5),
        ]
        return solve_network(E_GAS, nodes, pipes, T)

    def test_upstream_unaffected_downstream_blended(self):
        """H2 wtłoczony w środku: przed — czysty gaz E; za — mieszanina."""
        result = self._network(2_500.0)
        assert _node(result, "przed").composition.h2_mole_percent == pytest.approx(0.0, abs=1e-9)
        downstream = _node(result, "za")
        assert downstream.composition.h2_mole_percent > 1.0
        # udziały źródeł sumują się do 1 i zawierają oba źródła
        assert sum(downstream.source_shares.values()) == pytest.approx(1.0, abs=1e-9)
        assert set(downstream.source_shares) == {"Z", "Elektrolizer"}

    def test_h2_share_matches_exact_molar_balance(self):
        """%H2 za wtłoczeniem = ṅ_H2/(ṅ_H2+ṅ_GZ) — ścisły bilans molowy.

        Strumienie w Nm³ są proporcjonalne do strumieni molowych (wspólne
        V_m idealne w warunkach odniesienia; różnica Z rzędu 0,3%).
        """
        h2_nm3, offtake_nm3 = 2_500.0, 50_000.0
        result = self._network(h2_nm3)
        # gaz E dopływający do węzła wtłoczenia [Nm³/h] ≈ pobór − wtłoczenie H2
        expected_h2_pct = h2_nm3 / offtake_nm3 * 100.0
        got = _node(result, "za").composition.h2_mole_percent
        assert got == pytest.approx(expected_h2_pct, rel=0.01)

    def test_pipe_carries_upstream_composition(self):
        result = self._network(2_500.0)
        assert _pipe(result, "R1").composition.h2_mole_percent == pytest.approx(0.0)
        assert _pipe(result, "R3").composition.h2_mole_percent > 1.0


class TestBiomethaneAndQuality:
    def test_two_sources_molar_mixing(self):
        """Gaz E + biometan do wspólnego odbioru: skład = mieszanie molowe."""
        nodes = [
            NetworkNode("GZ", "cisnieniowy", pressure_pa=bar_to_pa(20), composition=E_GAS),
            NetworkNode("Bio", "zrodlowy", injection_nm3_per_h=5_000.0, composition=BIOMETHANE),
            NetworkNode("Odbior", "odbiorowy", offtake_nm3_per_h=25_000.0),
        ]
        pipes = [
            NetworkPipe("R1", "GZ", "Odbior", 0.25, 4_000.0, 5e-5),
            NetworkPipe("R2", "Bio", "Odbior", 0.15, 1_000.0, 5e-5),
        ]
        result = solve_network(E_GAS, nodes, pipes, T)
        mix = _node(result, "Odbior").composition
        shares = _node(result, "Odbior").source_shares
        # skład CO2 mieszaniny = udział_bio × CO2_bio + udział_GZ × CO2_GZ
        expected_co2 = shares["Bio"] * BIOMETHANE.fraction("CO2") + shares["GZ"] * E_GAS.fraction(
            "CO2"
        )
        assert mix.fraction("CO2") == pytest.approx(expected_co2, rel=1e-6)
        assert shares["Bio"] == pytest.approx(5_000.0 / 25_000.0, rel=0.02)

    def test_quality_flags_downstream_of_big_h2(self):
        """Strefa dużego wtłoczenia H2 vs wymogi gazu wysokometanowego (M1).

        Pouczające: Ws mieszaniny ~40% H2 (≈48 MJ/m³) NADAL mieści się
        w widełkach gr. E (45,0–56,9) — Wobbe sam nie wykrywa domieszki;
        łapią ją flaga %H2 i liczba metanowa (limit silnikowy).
        """
        from core.calorific import calorific_values, quality_flags
        from core.methane_number import methane_number_assessment

        nodes = [
            NetworkNode("Z", "cisnieniowy", pressure_pa=bar_to_pa(55), composition=E_GAS),
            NetworkNode("H2w", "zrodlowy", injection_nm3_per_h=20_000.0, composition=H2),
            NetworkNode("K", "odbiorowy", offtake_nm3_per_h=50_000.0),
        ]
        pipes = [
            NetworkPipe("R1", "Z", "H2w", 0.3, 3_000.0, 5e-5),
            NetworkPipe("R2", "H2w", "K", 0.3, 3_000.0, 5e-5),
        ]
        result = solve_network(E_GAS, nodes, pipes, T)
        mix = _node(result, "K").composition
        assert mix.h2_mole_percent > 30.0
        flags = quality_flags(mix, calorific_values(mix), h2_limit_mol_pct=10.0)
        wobbe_flag = next(f for f in flags if "Wobbego" in f.name_pl)
        h2_flag = next(f for f in flags if "H2" in f.name_pl)
        assert wobbe_flag.ok  # Ws(H2)≈48 w widełkach E — znany fakt
        assert not h2_flag.ok  # próg %H2 przekroczony
        assert not methane_number_assessment(mix).ok  # MN poniżej limitu silnik.


class TestVolumetricOfftakeUsesLocalComposition:
    def test_offtake_mass_reflects_local_density(self):
        """Pobór 10 000 Nm³/h czystego H2 to ~8× mniejsza masa niż gazu E."""

        def build(source_comp):
            nodes = [
                NetworkNode("Z", "cisnieniowy", pressure_pa=bar_to_pa(30), composition=source_comp),
                NetworkNode("K", "odbiorowy", offtake_nm3_per_h=10_000.0),
            ]
            pipes = [NetworkPipe("R", "Z", "K", 0.25, 3_000.0, 5e-5)]
            return solve_network(source_comp, nodes, pipes, T)

        m_e = abs(_node(build(E_GAS), "K").supply_kg_per_s)
        m_h2 = abs(_node(build(H2), "K").supply_kg_per_s)
        rho_e = compute_properties(E_GAS, 101_325.0, 273.15).density_kg_per_m3
        rho_h2 = compute_properties(H2, 101_325.0, 273.15).density_kg_per_m3
        assert m_e / m_h2 == pytest.approx(rho_e / rho_h2, rel=0.01)


class TestZrodlowyValidation:
    def test_injection_requires_composition(self):
        nodes = [
            NetworkNode("Z", "cisnieniowy", pressure_pa=bar_to_pa(55), composition=E_GAS),
            NetworkNode("W", "zrodlowy", injection_nm3_per_h=1000.0),
        ]
        pipes = [NetworkPipe("R", "Z", "W", 0.3, 1000.0, 5e-5)]
        with pytest.raises(ValueError, match="składu"):
            solve_network(E_GAS, nodes, pipes, T)

    def test_injection_requires_positive_flow(self):
        nodes = [
            NetworkNode("Z", "cisnieniowy", pressure_pa=bar_to_pa(55), composition=E_GAS),
            NetworkNode("W", "zrodlowy", injection_nm3_per_h=0.0, composition=H2),
        ]
        pipes = [NetworkPipe("R", "Z", "W", 0.3, 1000.0, 5e-5)]
        with pytest.raises(ValueError, match="dodatniego strumienia"):
            solve_network(E_GAS, nodes, pipes, T)
