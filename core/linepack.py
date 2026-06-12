"""Linepack — pojemność energetyczna odcinka gazociągu (moduł M12).

Metodyka:
    * masa gazu w odcinku przy ciśnieniu p (T = const, rura zakopana):
          m(p) = ρ(p, T) · V,   V = π·D²/4 · L,
      gęstość rzeczywista z GERG-2008 (M1); przyjmujemy ciśnienie średnie
      odcinka równe zadanemu (uproszczenie: bufor liczony między poziomami
      ciśnień średnich p_min, p_max),
    * pojemność robocza (bufor): Δm = m(p_max) − m(p_min),
      energia: E = Δm · Hi [MWh] (wartość opałowa, M1),
    * dynamika: czas pokrycia poboru P [MW]: t = E/P,
    * round-trip ze sprężaniem (M2): energia elektryczna napełnienia
      bufora = Δm · w(p_min→p_max)/η_mech; wskaźnik
      kWh_el / MWh energii chemicznej bufora (koszt energetyczny cyklu).
"""

from __future__ import annotations

import math
from dataclasses import dataclass

from core.calorific import calorific_values
from core.composition import GasComposition
from core.compression import compress
from core.gas_properties import compute_properties


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
    energy_total_at_pmax_mwh: float  # cała zawartość przy p_max
    buffer_energy_mwh: float  # robocza (p_max − p_min)
    compression_kwh_el: float  # energia napełnienia bufora (M2)

    @property
    def buffer_mass_kg(self) -> float:
        return self.mass_at_pmax_kg - self.mass_at_pmin_kg

    def buffer_hours_at_load(self, load_mw: float) -> float:
        """Czas pokrycia poboru [h] z bufora przy mocy ``load_mw``."""
        if load_mw <= 0:
            raise ValueError("Pobór mocy musi być dodatni.")
        return self.buffer_energy_mwh / load_mw

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
) -> LinepackResult:
    """Pojemność energetyczna odcinka dla widełek ciśnień i składu.

    Args:
        composition: skład gazu (M1),
        diameter_m, length_m: geometria odcinka (> 0),
        pressure_min_pa, pressure_max_pa: widełki ciśnień (p_max > p_min),
        temperature_k: temperatura gazu (stała),
        compressor_eta: sprawność politropowa sprężarki napełniającej (M2),
        mech_el_efficiency: sprawność mechaniczno-elektryczna napędu.
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

    hi_mj_per_kg = calorific_values(composition).hi_mj_per_kg
    buffer_mwh = (m_max - m_min) * hi_mj_per_kg / 3600.0
    total_mwh = m_max * hi_mj_per_kg / 3600.0

    comp = compress(
        composition,
        pressure_min_pa,
        temperature_k,
        pressure_max_pa,
        eta=compressor_eta,
        model="politropowy",
    )
    compression_kwh = comp.work_kwh_per_kg * (m_max - m_min) / mech_el_efficiency

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
        compression_kwh_el=compression_kwh,
    )
