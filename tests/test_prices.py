"""Testy scenariuszy cenowych (core.prices)."""

import pytest

from core import config
from core.prices import (
    all_scenarios,
    builtin_scenarios,
    carriers,
    delete_user_scenario,
    eur_pln_rate,
    save_user_scenario,
    user_scenarios,
)


class TestBuiltinScenarios:
    def test_three_scenarios_all_carriers(self):
        scenarios = builtin_scenarios()
        assert set(scenarios) == {"niski", "bazowy", "wysoki"}
        for sc in scenarios.values():
            assert set(sc.paths) == set(carriers())

    def test_anchor_exact_and_interpolation(self):
        sc = builtin_scenarios()["bazowy"]
        assert sc.price("gaz_ziemny", 2025) == 200.0
        assert sc.price("gaz_ziemny", 2030) == 215.0
        # liniowo w połowie odcinka 2025–2030
        assert sc.price("gaz_ziemny", 2027.5) == pytest.approx((200 + 215) / 2)

    def test_constant_outside_range(self):
        sc = builtin_scenarios()["bazowy"]
        assert sc.price("gaz_ziemny", 2010) == sc.price("gaz_ziemny", 2025)
        assert sc.price("gaz_ziemny", 2080) == sc.price("gaz_ziemny", 2050)

    def test_ets2_zero_before_start(self):
        sc = builtin_scenarios()["bazowy"]
        assert sc.price("ets2", 2025) == 0.0
        assert sc.price("ets2", 2027) > 0.0

    def test_scenario_ordering_low_below_high(self):
        low, base, high = (builtin_scenarios()[k] for k in ("niski", "bazowy", "wysoki"))
        for year in (2025, 2030, 2040, 2050):
            for carrier in ("gaz_ziemny", "energia_elektryczna", "eua"):
                assert (
                    low.price(carrier, year)
                    <= base.price(carrier, year)
                    <= high.price(carrier, year)
                )

    def test_grid_emission_factor_kobize_range_and_decline(self):
        """Wskaźnik miksu 2025 w przedziale KOBiZE 0,6–0,7 t/MWh i maleje."""
        sc = builtin_scenarios()["bazowy"]
        assert 0.6 <= sc.price("emisyjnosc_miksu", 2025) <= 0.7
        values = [sc.price("emisyjnosc_miksu", y) for y in range(2025, 2051, 5)]
        assert values == sorted(values, reverse=True)

    def test_co2_price_conversion(self):
        sc = builtin_scenarios()["bazowy"]
        assert sc.price_pln_per_t_co2("eua", 2025) == pytest.approx(75 * eur_pln_rate())
        with pytest.raises(ValueError, match="nie jest ceną CO2"):
            sc.price_pln_per_t_co2("gaz_ziemny", 2025)

    def test_unknown_carrier_polish_error(self):
        with pytest.raises(ValueError, match="Brak nośnika"):
            builtin_scenarios()["bazowy"].price("zloto", 2030)


class TestUserScenarios:
    @pytest.fixture(autouse=True)
    def _isolated_data_dir(self, tmp_path, monkeypatch):
        # kopiujemy pliki danych do katalogu tymczasowego (izolacja zapisu)
        import shutil

        for f in config.data_dir().glob("*.yaml"):
            shutil.copy(f, tmp_path / f.name)
        monkeypatch.setenv("GAS_RD_DATA_DIR", str(tmp_path))
        config.clear_cache()
        yield
        config.clear_cache()

    def test_save_load_roundtrip(self):
        paths = {"gaz_ziemny": {2025: 123.0, 2050: 222.0}}
        save_user_scenario("moj_test", paths, name_pl="Mój test")
        loaded = user_scenarios()["moj_test"]
        assert loaded.is_user_defined
        assert loaded.name_pl == "Mój test"
        assert loaded.price("gaz_ziemny", 2025) == 123.0
        assert "moj_test" in all_scenarios()

    def test_invalid_name_rejected(self):
        with pytest.raises(ValueError, match="Nazwa scenariusza"):
            save_user_scenario("../zly", {"gaz_ziemny": {2025: 1.0}})

    def test_invalid_carrier_rejected_before_write(self):
        with pytest.raises(ValueError, match="Nieznany nośnik"):
            save_user_scenario("zly_nosnik", {"platyna": {2025: 1.0}})
        assert "zly_nosnik" not in user_scenarios()

    def test_delete(self):
        save_user_scenario("do_kasacji", {"gaz_ziemny": {2025: 1.0}})
        delete_user_scenario("do_kasacji")
        assert "do_kasacji" not in user_scenarios()
        with pytest.raises(FileNotFoundError):
            delete_user_scenario("do_kasacji")
