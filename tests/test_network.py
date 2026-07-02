"""Testy solvera sieci gazowej (core.network, M15) — walidacja vs M3."""

import pytest

from core.composition import GasComposition
from core.network import NetworkNode, NetworkPipe, solve_network
from core.pipeline import pressure_profile
from core.units import bar_to_pa

E_GAS = GasComposition.predefined("gaz_E_typowy")
T = 283.15


def _node_p(result, name):
    return next(n for n in result.nodes if n.name == name).pressure_pa


def _pipe_m(result, name):
    return next(p for p in result.pipes if p.pipe.name == name).mass_flow_kg_per_s


class TestSinglePipeVsM3:
    def test_reproduces_marching_model(self):
        """Sieć 1-odcinkowa odtwarza P2 z modelu marszowego M3 (< 0,2%)."""
        m_flow = 15.0
        nodes = [
            NetworkNode("Zasilanie", "cisnieniowy", pressure_pa=bar_to_pa(55)),
            NetworkNode("Odbior", "odbiorowy", offtake_kg_per_s=m_flow),
        ]
        pipes = [NetworkPipe("R1", "Zasilanie", "Odbior", 0.3, 20_000.0, 5e-5)]
        result = solve_network(E_GAS, nodes, pipes, T)

        reference = pressure_profile(E_GAS, 0.3, 20_000.0, 5e-5, m_flow, bar_to_pa(55), T)
        assert _node_p(result, "Odbior") == pytest.approx(reference.pressure_out_pa, rel=0.002)
        assert _pipe_m(result, "R1") == pytest.approx(m_flow, rel=1e-6)

    def test_series_pipes_match_single_long_pipe(self):
        """Dwa odcinki 10 km szeregowo ≈ jeden 20 km (< 0,5%)."""
        m_flow = 15.0
        nodes = [
            NetworkNode("Z", "cisnieniowy", pressure_pa=bar_to_pa(55)),
            NetworkNode("posredni", "odbiorowy", offtake_kg_per_s=0.0),
            NetworkNode("K", "odbiorowy", offtake_kg_per_s=m_flow),
        ]
        pipes = [
            NetworkPipe("R1", "Z", "posredni", 0.3, 10_000.0, 5e-5),
            NetworkPipe("R2", "posredni", "K", 0.3, 10_000.0, 5e-5),
        ]
        result = solve_network(E_GAS, nodes, pipes, T)
        reference = pressure_profile(E_GAS, 0.3, 20_000.0, 5e-5, m_flow, bar_to_pa(55), T)
        assert _node_p(result, "K") == pytest.approx(reference.pressure_out_pa, rel=0.005)


class TestLoops:
    def test_symmetric_loop_splits_evenly(self):
        """Dwie identyczne rury równolegle: przepływ dzieli się 50/50."""
        nodes = [
            NetworkNode("Z", "cisnieniowy", pressure_pa=bar_to_pa(55)),
            NetworkNode("K", "odbiorowy", offtake_kg_per_s=20.0),
        ]
        pipes = [
            NetworkPipe("gora", "Z", "K", 0.3, 15_000.0, 5e-5),
            NetworkPipe("dol", "Z", "K", 0.3, 15_000.0, 5e-5),
        ]
        result = solve_network(E_GAS, nodes, pipes, T)
        assert _pipe_m(result, "gora") == pytest.approx(10.0, rel=1e-3)
        assert _pipe_m(result, "dol") == pytest.approx(10.0, rel=1e-3)

    def test_larger_diameter_carries_more(self):
        """W pętli o różnych średnicach większa rura niesie więcej gazu."""
        nodes = [
            NetworkNode("Z", "cisnieniowy", pressure_pa=bar_to_pa(55)),
            NetworkNode("K", "odbiorowy", offtake_kg_per_s=20.0),
        ]
        pipes = [
            NetworkPipe("duza", "Z", "K", 0.4, 15_000.0, 5e-5),
            NetworkPipe("mala", "Z", "K", 0.25, 15_000.0, 5e-5),
        ]
        result = solve_network(E_GAS, nodes, pipes, T)
        m_big, m_small = _pipe_m(result, "duza"), _pipe_m(result, "mala")
        assert m_big > 2.0 * m_small
        assert m_big + m_small == pytest.approx(20.0, rel=1e-6)


class TestTreeNetwork:
    def _tree(self):
        nodes = [
            NetworkNode("Z", "cisnieniowy", pressure_pa=bar_to_pa(55)),
            NetworkNode("A", "odbiorowy", offtake_kg_per_s=5.0),
            NetworkNode("B", "odbiorowy", offtake_kg_per_s=8.0),
            NetworkNode("C", "odbiorowy", offtake_kg_per_s=4.0),
        ]
        pipes = [
            NetworkPipe("R1", "Z", "A", 0.3, 8_000.0, 5e-5),
            NetworkPipe("R2", "A", "B", 0.25, 6_000.0, 5e-5),
            NetworkPipe("R3", "A", "C", 0.2, 5_000.0, 5e-5),
        ]
        return nodes, pipes

    def test_mass_balance_and_pressure_ordering(self):
        result = solve_network(E_GAS, *self._tree(), T)
        assert result.max_imbalance_kg_per_s < 1e-5
        # R1 niesie sumę wszystkich poborów
        assert _pipe_m(result, "R1") == pytest.approx(17.0, rel=1e-6)
        # ciśnienie maleje w kierunku przepływu
        assert bar_to_pa(55) > _node_p(result, "A") > _node_p(result, "B")
        assert _node_p(result, "A") > _node_p(result, "C")

    def test_supply_balances_demand(self):
        result = solve_network(E_GAS, *self._tree(), T)
        supply = next(n for n in result.nodes if n.kind == "cisnieniowy").supply_kg_per_s
        assert supply == pytest.approx(17.0, rel=1e-5)


class TestValidationErrors:
    def test_no_pressure_node(self):
        nodes = [
            NetworkNode("A", "odbiorowy", offtake_kg_per_s=1.0),
            NetworkNode("B", "odbiorowy", offtake_kg_per_s=1.0),
        ]
        pipes = [NetworkPipe("R", "A", "B", 0.3, 1000.0, 5e-5)]
        with pytest.raises(ValueError, match="ciśnieniowego"):
            solve_network(E_GAS, nodes, pipes, T)

    def test_disconnected_node(self):
        nodes = [
            NetworkNode("Z", "cisnieniowy", pressure_pa=bar_to_pa(55)),
            NetworkNode("A", "odbiorowy", offtake_kg_per_s=1.0),
            NetworkNode("Sierota", "odbiorowy", offtake_kg_per_s=1.0),
        ]
        pipes = [NetworkPipe("R", "Z", "A", 0.3, 1000.0, 5e-5)]
        with pytest.raises(ValueError, match="Sierota"):
            solve_network(E_GAS, nodes, pipes, T)

    def test_unknown_endpoint(self):
        nodes = [NetworkNode("Z", "cisnieniowy", pressure_pa=bar_to_pa(55))]
        pipes = [NetworkPipe("R", "Z", "Widmo", 0.3, 1000.0, 5e-5)]
        with pytest.raises(ValueError, match="Widmo"):
            solve_network(E_GAS, nodes, pipes, T)

    def test_duplicate_node_name(self):
        nodes = [
            NetworkNode("Z", "cisnieniowy", pressure_pa=bar_to_pa(55)),
            NetworkNode("Z", "odbiorowy", offtake_kg_per_s=1.0),
        ]
        pipes = [NetworkPipe("R", "Z", "Z", 0.3, 1000.0, 5e-5)]
        with pytest.raises(ValueError, match="Powtórzona"):
            solve_network(E_GAS, nodes, pipes, T)

    def test_excessive_demand_clear_error(self):
        """Pobór ponad przepustowość: czytelny komunikat, nie krach solvera."""
        nodes = [
            NetworkNode("Z", "cisnieniowy", pressure_pa=bar_to_pa(20)),
            NetworkNode("K", "odbiorowy", offtake_kg_per_s=500.0),
        ]
        pipes = [NetworkPipe("R", "Z", "K", 0.15, 30_000.0, 5e-5)]
        with pytest.raises(ValueError, match="przepustowość|zbiegł|spada"):
            solve_network(E_GAS, nodes, pipes, T)
