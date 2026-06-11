"""Rejestr modułów funkcjonalnych narzędzia (M1–M14) na potrzeby nawigacji UI.

Jedno źródło prawdy o module: identyfikator, tytuł, opis, etap realizacji.
Strony zaimplementowane wskazują funkcję renderującą; pozostałe dostają
automatyczną stronę-zaślepkę z opisem zakresu.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field

from app.views import m01_gas_properties


@dataclass(frozen=True)
class ModuleInfo:
    """Opis modułu funkcjonalnego prezentowany w nawigacji i na zaślepkach."""

    code: str  # np. "M1"
    slug: str  # segment URL, np. "m01-wlasciwosci-gazow"
    title: str
    section: str  # grupa w nawigacji
    description: str
    stage: int  # etap planu pracy, w którym moduł powstaje
    icon: str = "🧩"
    render: Callable[[], None] | None = field(default=None, compare=False)


MODULES: list[ModuleInfo] = [
    ModuleInfo(
        code="M1",
        slug="m01-wlasciwosci-gazow",
        title="M1 · Właściwości gazów i mieszanin",
        section="Właściwości i przepływ",
        description=(
            "Skład molowy gazu ziemnego, H2 (ISO 14687), biometanu i mieszanin H2/GZ "
            "0–100%. Wyniki: ciepło spalania i wartość opałowa (ISO 6976), liczba "
            "Wobbego, gęstość, Z, lepkość, cp/cv, wykładnik izentropy, współczynnik "
            "Joule'a-Thomsona, prędkość dźwięku, gęstość energii; flagi zgodności "
            "jakościowej (Wobbe, %H2)."
        ),
        stage=1,
        icon="🧪",
        render=m01_gas_properties.render,
    ),
    ModuleInfo(
        code="M2",
        slug="m02-sprezanie",
        title="M2 · Energia sprężania",
        section="Właściwości i przepływ",
        description=(
            "Energia między punktami pracy (p1,T1)→(p2,T2): praca izotermiczna, "
            "izentropowa i politropowa, sprężanie wielostopniowe z chłodzeniem "
            "międzystopniowym, technologie sprężarek z bibliotekami sprawności; "
            "wyniki w kWh/kg, kWh/Nm³, moc i ciepło odpadowe."
        ),
        stage=2,
        icon="🌀",
    ),
    ModuleInfo(
        code="M3",
        slug="m03-gazociagi",
        title="M3 · Gazociągi",
        section="Właściwości i przepływ",
        description=(
            "Spadek ciśnienia Darcy-Weisbach + Colebrook-White (opcjonalnie "
            "Panhandle/Weymouth); porównanie przepustowości energetycznej [MW] "
            "tej samej rury dla GZ/H2/mieszanin; energia tłoczenia na jednostkę "
            "przesłanej energii; prędkości i limity."
        ),
        stage=2,
        icon="🛢️",
    ),
    ModuleInfo(
        code="M4",
        slug="m04-ekspandery",
        title="M4 · Ekspandery",
        section="Odzysk energii",
        description=(
            "Turboekspander, śruba, Roots, tłok, scroll: moc odzyskana, temperatura "
            "wylotowa, wymagany podgrzew (efekt JT, hydraty), macierz doboru "
            "(przepływ × spręż × moc, CAPEX/kW, TRL), rekomendacja dla punktu pracy."
        ),
        stage=3,
        icon="⚙️",
    ),
    ModuleInfo(
        code="M13",
        slug="m13-zimna-redukcja",
        title="M13 · Zimna redukcja",
        section="Odzysk energii",
        description=(
            "Bilans stacji redukcyjnej: efekt Joule'a-Thomsona, temperatura wylotowa, "
            "ryzyko hydratów, oszczędność podgrzewu, warianty z ekspanderem (M4); "
            "porównanie ekonomiczne wariantów."
        ),
        stage=3,
        icon="❄️",
    ),
    ModuleInfo(
        code="M12",
        slug="m12-linepack",
        title="M12 · Linepack",
        section="Odzysk energii",
        description=(
            "Pojemność energetyczna odcinka gazociągu dla widełek ciśnień i składu: "
            "MWh, dynamika, round-trip ze sprężaniem (M2)."
        ),
        stage=6,
        icon="📦",
    ),
    ModuleInfo(
        code="M5",
        slug="m05-sciezki-cenowe",
        title="M5 · Ścieżki cenowe",
        section="Scenariusze i emisje",
        description=(
            "Scenariusze (niski/bazowy/wysoki) do 2050: ceny GZ, H2, energii "
            "elektrycznej, biometanu, biomasy; EU ETS i ETS2; emisyjność miksu "
            "elektroenergetycznego; edycja i zapis scenariuszy użytkownika."
        ),
        stage=4,
        icon="📈",
    ),
    ModuleInfo(
        code="M8-M9",
        slug="m08-m09-emisje",
        title="M8–M9 · Emisje",
        section="Scenariusze i emisje",
        description=(
            "CH4→CO2eq dla GWP100/GWP20 (IPCC AR6); emisje CO2 z energii "
            "elektrycznej i spalania (zakres 1–2); wskaźniki na Nm³/kWh/kg H2."
        ),
        stage=4,
        icon="🌍",
    ),
    ModuleInfo(
        code="M6",
        slug="m06-produkcja-wodoru",
        title="M6 · Produkcja wodoru",
        section="Technologie",
        description=(
            "AEL, PEM, SOEC, AEM, SMR+CCS, piroliza: kWh/kg (LHV/HHV), zużycie wody "
            "i mediów, praca częściowa, degradacja, CAPEX/OPEX, ciśnienie i czystość "
            "wyjściowa; kalkulator zapotrzebowania dla zadanej produkcji."
        ),
        stage=5,
        icon="⚡",
    ),
    ModuleInfo(
        code="M7",
        slug="m07-wytwarzanie",
        title="M7 · Charakterystyki wytwarzania",
        section="Technologie",
        description=(
            "Biblioteka technologii energii i ciepła (kogeneracja, ogniwa paliwowe, "
            "turbiny, silniki, kotły) vs skala; ujednolicone wykresy porównawcze."
        ),
        stage=5,
        icon="🏭",
    ),
    ModuleInfo(
        code="M10",
        slug="m10-ekonomia",
        title="M10 · Ekonomia (LCOE/LCOH/LCOS)",
        section="Ocena i porównania",
        description=(
            "LCOE/LCOH/LCOS: CAPEX z harmonogramem, OPEX, paliwa/energia (M5), "
            "koszty ETS/ETS2, przychody z ciepła odpadowego i O2, WACC, NPV, IRR, "
            "DPP; analiza wrażliwości (wykres tornado, ±20%)."
        ),
        stage=6,
        icon="💰",
    ),
    ModuleInfo(
        code="M11",
        slug="m11-benchmarking",
        title="M11 · Benchmarking technologii",
        section="Ocena i porównania",
        description=(
            "Porównanie z PV, wiatrem, biomasą/biogazem, pompami ciepła i magazynami "
            "bateryjnymi na wspólnych wskaźnikach (LCOE/LCOH, CO2eq/MWh, "
            "dyspozycyjność, TRL); ranking."
        ),
        stage=6,
        icon="📊",
    ),
    ModuleInfo(
        code="M14",
        slug="m14-karta-projektu",
        title="M14 · Karta projektu B+R",
        section="Ocena i porównania",
        description=(
            "Złożenie wyników modułów w kartę oceny projektu B+R: wskaźniki "
            "techniczne, ekonomiczne i ekologiczne, ocena wielokryterialna "
            "z wagami użytkownika, porównanie projektów, eksport XLSX/PDF."
        ),
        stage=7,
        icon="📋",
    ),
]
