"""Linepack — pojemność energetyczna odcinka gazociągu (moduł M12).

Metodyka:
    * masa gazu w odcinku przy ciśnieniu p (T = const, rura zakopana):
          m(p) = ρ(p, T) · V,   V = π·D²/4 · L,
      gęstość rzeczywista z GERG-2008 (M1); przyjmujemy ciśnienie średnie
      odcinka równe zadanemu (uproszczenie: bufor liczony między poziomami
      ciśnień średnich p_min, p_max),
    * pojemność robocza (bufor): Δm = m(p_max) − m(p_min),
      energia CHEMICZNA: E = Δm · Hi [MWh] (wartość opałowa, M1),
    * energia CIŚNIENIA (eksergia): maksymalna odzyskiwalna praca mechaniczna
      sprężonego gazu = odwracalna praca izotermiczna Δm · w_T (T = const);
      dla gazu palnego o 2–3 rzędy mniejsza od chemicznej, dla powietrza
      (brak Hi) — jedyna magazynowana wielkość (tryb CAES),
    * dynamika: czas pokrycia poboru P [MW]: t = E/P,
    * round-trip ze sprężaniem (M2): energia elektryczna napełnienia
      bufora = Δm · w(p_min→p_max)/η_mech; wskaźnik
      kWh_el / MWh energii chemicznej bufora (koszt energetyczny cyklu),
    * analiza typów cyklu (``cycle_analysis``): porównanie sprężania/
      rozprężania izotermicznego / izentropowego / politropowego.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

from core.calorific import calorific_values
from core.composition import GasComposition
from core.compression import compress, isothermal_work_j_per_kg
from core.expanders import expand
from core.gas_properties import compute_properties
from core.units import j_to_kwh


@dataclass(frozen=True)
class LinepackResult:
    """Pojemność energetyczna odcinka między poziomami ciśnień."""

    composition: GasComposition
    diameter_m: float
    length_m: float
    temperature_k: float
    pressure_min_pa: float
    pressure_max_pa: float
    geometric_volume_m3: float
    mass_at_pmin_kg: float
    mass_at_pmax_kg: float
    energy_total_at_pmax_mwh: float  # cała zawartość przy p_max (Hi; 0 dla powietrza)
    buffer_energy_mwh: float  # robocza (p_max − p_min), energia chemiczna (Hi)
    pressure_exergy_mwh: float  # energia CIŚNIENIA bufora (eksergia izotermiczna, T=const)
    compression_kwh_el: float  # energia napełnienia bufora (M2)
    is_combustible: bool
    caes_recovered_mwh: float  # CAES: energia el. odzyskana z rozprężania bufora (M4)
    caes_round_trip_efficiency: float  # CAES: odzysk / napełnienie [-]

    @property
    def buffer_mass_kg(self) -> float:
        return self.mass_at_pmax_kg - self.mass_at_pmin_kg

    def buffer_hours_at_load(self, load_mw: float) -> float:
        """Czas pokrycia poboru [h] z bufora przy mocy ``load_mw``.

        Dla gazu palnego — z energii chemicznej (Hi); dla powietrza (CAES) —
        z energii elektrycznej odzyskanej w rozprężaniu.
        """
        if load_mw <= 0:
            raise ValueError("Pobór mocy musi być dodatni.")
        energy = self.buffer_energy_mwh if self.is_combustible else self.caes_recovered_mwh
        return energy / load_mw

    @property
    def compression_kwh_el_per_mwh(self) -> float:
        """Energia sprężania na MWh energii chemicznej bufora [kWh/MWh]."""
        if self.buffer_energy_mwh <= 0:
            return 0.0
        return self.compression_kwh_el / self.buffer_energy_mwh


def linepack(
    composition: GasComposition,
    diameter_m: float,
    length_m: float,
    pressure_min_pa: float,
    pressure_max_pa: float,
    temperature_k: float = 283.15,
    compressor_eta: float = 0.82,
    mech_el_efficiency: float = 0.95,
    expander_eta: float = 0.80,
) -> LinepackResult:
    """Pojemność energetyczna odcinka dla widełek ciśnień i składu.

    Dla gazu palnego liczona jest energia chemiczna bufora (Hi). Dla gazu
    niepalnego (powietrze) moduł działa jako **CAES** (Compressed Air Energy
    Storage): energia magazynowana to praca elektryczna odzyskiwana przy
    rozprężaniu bufora p_max→p_min w turboekspanderze (M4); sprawność
    round-trip = odzysk / napełnienie. Model diabatyczny (rura zakopana,
    T = const — ciepło sprężania oddane do gruntu), więc round-trip jest
    odpowiednio niższy niż dla CAES adiabatycznego z magazynem ciepła.

    Args:
        composition: skład gazu (M1),
        diameter_m, length_m: geometria odcinka (> 0),
        pressure_min_pa, pressure_max_pa: widełki ciśnień (p_max > p_min),
        temperature_k: temperatura gazu (stała),
        compressor_eta: sprawność politropowa sprężarki napełniającej (M2),
        mech_el_efficiency: sprawność mechaniczno-elektryczna napędu,
        expander_eta: sprawność izentropowa turboekspandera CAES (M4).
    """
    if diameter_m <= 0 or length_m <= 0:
        raise ValueError("Geometria odcinka musi być dodatnia.")
    if pressure_max_pa <= pressure_min_pa:
        raise ValueError("p_max musi być większe od p_min.")
    if not 0 < compressor_eta <= 1 or not 0 < mech_el_efficiency <= 1:
        raise ValueError("Sprawności muszą być w przedziale (0, 1].")

    volume = math.pi * diameter_m**2 / 4.0 * length_m
    rho_min = compute_properties(composition, pressure_min_pa, temperature_k).density_kg_per_m3
    rho_max = compute_properties(composition, pressure_max_pa, temperature_k).density_kg_per_m3
    m_min, m_max = rho_min * volume, rho_max * volume

    combustible = composition.is_combustible
    hi_mj_per_kg = calorific_values(composition).hi_mj_per_kg if combustible else 0.0
    buffer_mwh = (m_max - m_min) * hi_mj_per_kg / 3600.0
    total_mwh = m_max * hi_mj_per_kg / 3600.0

    # Praca cyklu CAŁKOWANA po stanie bufora (N kroków ciśnienia):
    #   napełnianie: kolejne porcje Δm_i sprężane z p_min do BIEŻĄCEGO
    #   ciśnienia bufora (rosnącego p_min→p_max),
    #   opróżnianie (CAES): porcje rozprężane z bieżącego ciśnienia bufora
    #   (malejącego p_max→p_min) do p_min.
    # Pojedynczy skok p_min→p_max dla całej masy zawyżałby oba strumienie
    # o ~10–20% (patrz ARCHITEKTURA.md §3.4).
    n_steps = 8
    dp = (pressure_max_pa - pressure_min_pa) / n_steps
    pressures = [pressure_min_pa + i * dp for i in range(n_steps + 1)]
    masses = [
        compute_properties(composition, p, temperature_k).density_kg_per_m3 * volume
        for p in pressures
    ]
    compression_kwh = 0.0
    recovered_kwh = 0.0
    exergy_kwh = 0.0  # energia ciśnienia = odwracalna praca izotermiczna (eksergia)
    for i in range(n_steps):
        dm = masses[i + 1] - masses[i]
        p_mid = 0.5 * (pressures[i] + pressures[i + 1])
        work_in = compress(
            composition,
            pressure_min_pa,
            temperature_k,
            p_mid,
            eta=compressor_eta,
            model="politropowy",
        ).work_kwh_per_kg
        compression_kwh += dm * work_in
        work_out = expand(
            composition, p_mid, temperature_k, pressure_min_pa, eta=expander_eta
        ).work_j_per_kg
        recovered_kwh += dm * j_to_kwh(work_out)
        # eksergia ciśnienia porcji Δm: |w_T(p_min→p_mid)| = maksymalna odwracalna
        # praca odzysku izotermicznego p_mid→p_min (T = const, granica II zasady).
        exergy_kwh += dm * j_to_kwh(
            isothermal_work_j_per_kg(composition, pressure_min_pa, temperature_k, p_mid)
        )
    compression_kwh /= mech_el_efficiency
    recovered_kwh *= mech_el_efficiency
    caes_recovered_mwh = recovered_kwh / 1e3
    round_trip = recovered_kwh / compression_kwh if compression_kwh > 0 else 0.0

    return LinepackResult(
        composition=composition,
        diameter_m=diameter_m,
        length_m=length_m,
        temperature_k=temperature_k,
        pressure_min_pa=pressure_min_pa,
        pressure_max_pa=pressure_max_pa,
        geometric_volume_m3=volume,
        mass_at_pmin_kg=m_min,
        mass_at_pmax_kg=m_max,
        energy_total_at_pmax_mwh=total_mwh,
        buffer_energy_mwh=buffer_mwh,
        pressure_exergy_mwh=exergy_kwh / 1e3,
        compression_kwh_el=compression_kwh,
        is_combustible=combustible,
        caes_recovered_mwh=caes_recovered_mwh,
        caes_round_trip_efficiency=round_trip,
    )


@dataclass(frozen=True)
class CycleModel:
    """Wynik jednego modelu termodynamicznego cyklu magazynowania (CAES)."""

    key: str  # "izotermiczne" | "izentropowe" | "politropowe"
    name_pl: str
    fill_mwh: float  # praca (wewnętrzna, na wale) napełnienia bufora
    recovered_mwh: float  # praca odzyskana przy opróżnianiu
    round_trip: float  # odzysk / napełnienie [-]
    note: str


def cycle_analysis(
    composition: GasComposition,
    diameter_m: float,
    length_m: float,
    pressure_min_pa: float,
    pressure_max_pa: float,
    temperature_k: float = 283.15,
    compressor_eta: float = 0.82,
    expander_eta: float = 0.80,
    n_steps: int = 8,
) -> list[CycleModel]:
    """Porównanie modeli sprężania/rozprężania bufora (analiza typów cyklu).

    Praca cyklu całkowana po stanie bufora (N kroków ciśnienia). Trzy modele
    (wartości na wale — bez sprawności mechaniczno-elektrycznej napędu):

    * **izotermiczne (idealne, odwracalne):** granica II zasady — sprężanie
      i rozprężanie przy T = const (doskonała wymiana ciepła z gruntem);
      round-trip = 100%. Napełnienie = odzysk = **energia ciśnienia** (eksergia),
    * **izentropowe (adiabatyczne, η = 1):** brak wymiany ciepła w maszynie;
      w rurze zakopanej gaz stygnie do temperatury gruntu MIĘDZY cyklami
      (magazyn diabatyczny) → odzysk < napełnienie, round-trip < 100%
      mimo idealnych maszyn (utrata ciepła sprężania),
    * **politropowe (rzeczywiste):** maszyny ze sprawnościami η
      (sprężarka politropowa, ekspander izentropowy z η).

    Zwraca listę trzech ``CycleModel`` (na wale). Sprawność napędu
    mechaniczno-elektrycznego mnoży dodatkowo round-trip w praktyce.
    """
    if diameter_m <= 0 or length_m <= 0:
        raise ValueError("Geometria odcinka musi być dodatnia.")
    if pressure_max_pa <= pressure_min_pa:
        raise ValueError("p_max musi być większe od p_min.")

    volume = math.pi * diameter_m**2 / 4.0 * length_m
    dp = (pressure_max_pa - pressure_min_pa) / n_steps
    pressures = [pressure_min_pa + i * dp for i in range(n_steps + 1)]
    masses = [
        compute_properties(composition, p, temperature_k).density_kg_per_m3 * volume
        for p in pressures
    ]

    iso_fill = iso_rec = 0.0
    isen_fill = isen_rec = 0.0
    poly_fill = poly_rec = 0.0
    for i in range(n_steps):
        dm = masses[i + 1] - masses[i]
        p_mid = 0.5 * (pressures[i] + pressures[i + 1])
        w_iso = j_to_kwh(
            isothermal_work_j_per_kg(composition, pressure_min_pa, temperature_k, p_mid)
        )
        iso_fill += dm * w_iso
        iso_rec += dm * w_iso  # odwracalne: odzysk = nakład
        isen_fill += (
            dm
            * compress(
                composition, pressure_min_pa, temperature_k, p_mid, eta=1.0, model="izentropowy"
            ).work_kwh_per_kg
        )
        isen_rec += dm * j_to_kwh(
            expand(composition, p_mid, temperature_k, pressure_min_pa, eta=1.0).work_j_per_kg
        )
        poly_fill += (
            dm
            * compress(
                composition,
                pressure_min_pa,
                temperature_k,
                p_mid,
                eta=compressor_eta,
                model="politropowy",
            ).work_kwh_per_kg
        )
        poly_rec += dm * j_to_kwh(
            expand(
                composition, p_mid, temperature_k, pressure_min_pa, eta=expander_eta
            ).work_j_per_kg
        )

    def _model(key, name, fill_kwh, rec_kwh, note):
        rt = rec_kwh / fill_kwh if fill_kwh > 0 else 0.0
        return CycleModel(key, name, fill_kwh / 1e3, rec_kwh / 1e3, rt, note)

    return [
        _model(
            "izotermiczne",
            "izotermiczne (idealne, odwracalne)",
            iso_fill,
            iso_rec,
            "granica II zasady; napełnienie = odzysk = energia ciśnienia (eksergia)",
        ),
        _model(
            "izentropowe",
            "izentropowe (adiabatyczne, η = 1)",
            isen_fill,
            isen_rec,
            "maszyny idealne, magazyn diabatyczny — ciepło sprężania oddane do gruntu",
        ),
        _model(
            "politropowe",
            f"politropowe (η sprężania {compressor_eta:.2f} / rozprężania {expander_eta:.2f})",
            poly_fill,
            poly_rec,
            "maszyny rzeczywiste (bez napędu mech.-el.)",
        ),
    ]
