# Architektura i macierz powiązań danych między modułami

> Dokument techniczny: co każdy moduł przyjmuje, co produkuje i kto to
> konsumuje. Status powiązania: **A** = automatyczne (wywołanie funkcji
> `core`), **D** = przez pliki `data/` (edytowalne), **R** = ręczne
> (użytkownik przenosi wynik), **P** = placeholder (do zastąpienia).

## 1. Warstwy (zależności tylko „w dół")

```
units, config                         ← fundament (SI, loader YAML)
composition                           ← skład molowy (walidacja, mieszanie)
gas_properties                        ← GERG-2008/HEOS (p,T → właściwości)
calorific, methane_number, hydrates   ← ISO 6976, MN, Towler-Mokhatab
compression, expanders, pipeline, emissions
cold_reduction, network, linepack, hydrogen, generation
prices → economics → benchmarking
project_card → export
```

Graf importów `core → core` jest acykliczny (sprawdzone). Warstwa `app/`
importuje wyłącznie `core` — brak logiki obliczeniowej w UI (jedyne
przeliczenia w UI to jednostki wejść przez funkcje `core`).

## 2. Macierz powiązań wejść/wyjść

| Moduł | Kluczowe WEJŚCIA (skąd) | Kluczowe WYJŚCIA | Konsumenci (jak) |
|---|---|---|---|
| **M1** skład+właściwości | składy `data/gas_compositions` (D), p,T od użytkownika | `GasComposition`, ρ, Z, cp, μ, w, μJT; Hs/Hi/Wobbe (ISO 6976); MN; flagi jakości | M2–M15 — **A** (każdy moduł liczy na `GasComposition`) |
| **M2** sprężanie | M1 (A), biblioteka sprężarek (D) | praca kWh/kg·Nm³, T tłoczenia stopni, ciepło chłodnic | M3 (energia tłoczenia, A), M12 (napełnianie, A), **M13 ciepło odpadowe — A** (`heat_source_from_compression`: `HeatSource` z policzonego sprężania — poziom T stopni + dostępna moc; §3.2 zamknięte) |
| **M3** gazociąg | M1 (A), chropowatości (D) | P₂/przepływ/średnica, profil p,v | M15 (kalibracja oporów K — A), M12 pośrednio |
| **M4** ekspandery | M1 (A), biblioteka ekspanderów (D) | moc odzyskana, T wylotu, macierz doboru (CAPEX/kW, TRL) | M13 (wariant ekspanderowy — A), M12 CAES (A); **M10 — A** (`expander_station_economics`: LCOE/NPV/IRR przyrostowo vs JT; §3.5 zamknięte) |
| **M5** ceny | scenariusze (D + JSON użytkownika) | ścieżki cen nośników, EUA/ETS2, emisyjność miksu | M6, M7, M8–M9, M10, M11 — **A**; **M13 — A** (`variant_economics(scenario, year)`; ceny robocze tylko fallback — §3.1 zamknięte) |
| **M6** wodór | biblioteka IEA (D), M5 (A), M1 Hi(H2) (A) | kWh/kg, woda, emisje 1+2, koszt energii | M10 LCOH (A), M14 (R) |
| **M7** wytwarzanie | katalogi DEA/IEA (D), M5 (A), M8 emisje gazu (A) | η/COP/cf, g CO₂/kWh, koszt paliwowy | M10 LCOE (A), M11 (A), **M13 źródła ciepła (A — `heat_source_entries`)** |
| **M8–M9** emisje | M1 stechiometria (A), GWP AR6 (D), miks z M5 (A) | kg CO₂/Nm³·kWh·kg, CO₂eq ucieczek, zakres 2 | M7 (A), M6 (A), M10 koszt EUA (A), M14 (R) |
| **M10** ekonomia | M5 (A), M6 (A), M7 (A), WACC/okres od użytkownika | LCOH/LCOE z dekompozycją, NPV/IRR/DPP, tornado | M11 (A), M14 (R) |
| **M11** benchmark | M10 (A), M7 (A), bateria+dyspozycyjność (D) | ranking wielokryterialny | M14 (R) |
| **M12** linepack/CAES | M1 (A), M2 sprężanie (A), M4 rozprężanie (A) | bufor MWh, round-trip CAES (praca cyklu całkowana po N krokach ciśnienia — §3.4 zamknięte) | M14 (R) |
| **M13** stacja redukcyjna | M1 (A), M4 (A), hydraty (A), źródła ciepła: M7 (A) + baza (D) + sprężarki M2 (**A** — policzone), ceny: M5 (A) + robocze (fallback) | podgrzew/odzysk/chłód, porównanie wariantów, opłacalność ekspandera (M10) | M14 (R) |
| **M14** karta projektu | wskaźniki z M1–M13 — **R** (pola formularza z podpowiedzią „gdzie policzyć") | karta JSON, ranking projektów, XLSX/CSV | Power BI/Excel (eksport) |
| **M15** sieć | M1 składy źródeł (A), M3 kalibracja K (A), jakość: M1+MN (A) | ciśnienia, przepływy, składy węzłów, strefy mieszania, flagi E | eksport CSV |

Konwencje wspólne (jedno źródło prawdy): ρₙ zawsze z
`compute_properties(comp, 101 325 Pa, 273,15 K)`; kurs EUR/PLN tylko
w `price_scenarios.yaml`; wszystkie przeliczniki jednostek w `core/units.py`;
GWP tylko w `emission_factors.yaml`.

## 3. Znane luki i niespójności (stan na audyt)

> **Aktualizacja:** luki 3.1–3.5 z audytu zostały **zamknięte**
> (implementacja + testy). Opis zachowany jako zapis decyzji; poniżej,
> w każdej pozycji, wskazano rozwiązanie i miejsce w kodzie.

### 3.1 Dwa źródła cen (M13 vs M5) — priorytet 1 — ✅ ZAMKNIĘTE
`variant_economics` (M13) liczyło na cenach roboczych z
`reduction_stations.yaml`, nie na ścieżkach scenariuszy M5. Zmiana
scenariusza w M5 nie wpływała na M13.
**Rozwiązanie:** `variant_economics(..., scenario, year)` +
`_resolve_prices` (`core/cold_reduction.py`) — ceny nośników M5 są jedynym
źródłem prawdy, ceny robocze zostają wyłącznie jako fallback (nośnik
„odpadowe" zawsze po koszcie krańcowym). UI M13 ma przełącznik scenariusz
M5 / ceny robocze. Testy: `tests/test_cold_reduction.py::TestScenarioPrices`.

### 3.2 Ciepło odpadowe sprężarek = placeholder — priorytet 1 — ✅ ZAMKNIĘTE
Wpis „ciepło odpadowe sprężarek (60–80 °C)" był statycznym wpisem, nie
wynikiem M2.
**Rozwiązanie:** `heat_source_from_compression(compression_result, ṁ, …)`
(`core/cold_reduction.py`) buduje `HeatSource` z policzonego sprężania M2:
poziom temperatury zasilania = najzimniejszy stopień − pinch, dostępna moc
= ciepło chłodnic międzystopniowych + końcowej. `HeatSource.available_kw`
jest sprawdzane w `heat_source_ok` (flaga ❌ przy niedoborze mocy). UI M13:
sekcja „🔥 Policz ciepło odpadowe sprężarki (M2)". Testy:
`tests/test_cold_reduction.py::TestCompressionHeatSource`.

### 3.3 Alokacja kosztów kogeneracji w M10 — priorytet 2 — ✅ ZAMKNIĘTE
LCOE kogeneracji dzieliło paliwo i CO₂ metodą energetyczną (η_całk), ale
CAŁY CAPEX przypisywało energii elektrycznej — metodyka mieszana.
**Rozwiązanie:** `lcoe_for_technology` (`core/economics.py`) alokuje CAPEX
(i pochodny OPEX) na produkt elektryczny proporcjonalnie do udziału
energetycznego `η_el/η_całk` — spójnie z metodą energetyczną z M7. Testy:
`tests/test_economics.py::TestCHPCapexAllocation`.

### 3.4 Praca cyklu bufora w M12 przy stałych końcach — priorytet 2 — ✅ ZAMKNIĘTE
Napełnianie/opróżnianie liczone dla całej masy Δm przy stałych końcach
(p_min→p_max) zawyżało oba strumienie ~10–20%.
**Rozwiązanie:** praca cyklu **całkowana po stanie bufora** w N = 8 krokach
ciśnienia (`core/linepack.py`): porcje Δmᵢ sprężane/rozprężane względem
bieżącego (rosnącego/malejącego) ciśnienia bufora. Testy:
`tests/test_air_caes.py::TestLinepackIntegration` (oba strumienie < skok
jednorazowy, round-trip nadal 0,2–1,0).

### 3.5 Brak mostka M4 → M10 — priorytet 2 — ✅ ZAMKNIĘTE
CAPEX/kW ekspanderów był w danych, ale M10 nie miał kalkulatora
opłacalności ekspandera.
**Rozwiązanie:** `expander_station_economics(...)` (`core/economics.py`) —
rachunek przyrostowy względem wariantu JT: CAPEX = moc odzyskana × €/kW
(mapa doboru M4), koszt = dodatkowy podgrzew ponad JT wg źródła ciepła M13
i cen M5, przychód = energia elektryczna × cena energii (ścieżka M5 rok po
roku); zwraca LCOE/NPV/IRR/DPP. UI M13: sekcja „💰 Opłacalność ekspandera".
Testy: `tests/test_economics.py::TestExpanderStationEconomics`.

### 3.6 M14 zasilana ręcznie — świadoma decyzja
Karta projektu zbiera wskaźniki wpisywane przez użytkownika (z podpowiedzią
modułu źródłowego). Zaleta: audytowalność wartości; wada: brak przycisku
„przenieś wynik do karty". Kandydat na usprawnienie UX, nie błąd.

### 3.7 Konwencja: emisyjność miksu w scenariuszach M5
Ścieżka `emisyjnosc_miksu` [t CO₂/MWh] jest technicznie „nośnikiem"
w scenariuszach cen (wspólny mechanizm interpolacji). Semantycznie to
wskaźnik, nie cena — konwencja przyjęta świadomie i opisana tutaj.

## 4. Dobór bibliotek obliczeniowych (decyzja)

**Właściwości termofizyczne:** CoolProp, backend HEOS. Dla mieszanin to
model **GERG-2008** (ISO 20765-2, następca AGA8) — międzynarodowy wzorzec
równania stanu dla gazu ziemnego i mieszanin z wodorem. **Kaloryczność /
Wobbe / gęstość względna:** ISO 6976:2016.

Decyzja: **pozostać przy CoolProp/GERG-2008 + ISO 6976** dla obecnego zakresu
(gaz wysokometanowy E, domieszki H₂ 0–100%, biometan uzdatniony, powietrze/
CAES). Uzasadnienie i rozważone alternatywy (audyt bibliotek):

| Alternatywa | Werdykt |
|---|---|
| **pyaga8** (AGA8-DETAIL/GERG-2008) | Liczy TEN SAM standard co CoolProp HEOS — brak zysku fizyki. Przewaga tylko: ścisła zgodność AGA8-DETAIL do metrologii rozliczeniowej (poza zakresem narzędzia przesiewowego). |
| **NeqSim** | Silna dla przemysłu gazowego (hydraty, mokry/kwaśny gaz), ale zależność od JVM (Java) — cięższe wdrożenie na Streamlit Cloud dla nieprogramisty. |
| **REFPROP** (NIST) | Ten sam GERG-2008 dla gazu ziemnego + nowsze parametry binarne H₂; komercyjny (licencja). Marginalny zysk, realny koszt. |
| **równania sześcienne** (PR/SRK) | Szybsze, ale mniej dokładne dla ρ/Z — krok wstecz dla gazu sieciowego. |
| **fluids** (hydraulika M3) | Dobra biblioteka, ale nasze korelacje (Colebrook+Serghides) są zwalidowane analitycznie (ogólne równanie przepływu) — brak potrzeby zmiany. |
| **thermo** (czysty Python) | Realnie potrzebne TYLKO gdyby w zakres wszedł surowy biogaz mokry (H₂O, H₂S, **NH₃** — poza GERG-2008). Wtedy dołożyć dla TEGO przypadku, bez ruszania reszty. |

Wyzwalacze przyszłej zmiany (dziś niespełnione): (a) surowy mokry/kwaśny
biogaz z NH₃ → `thermo` lub NeqSim dla tego modułu; (b) wymóg certyfikacji
AGA8-DETAIL → `pyaga8` jako opcjonalny backend obok CoolProp. Oba do
dołożenia punktowo — architektura `core/gas_properties.py` (jeden punkt
liczenia właściwości) na to pozwala bez zmian w modułach M2–M15.

## 5. Rozszerzenia względem specyfikacji funkcjonalnej

Uzupełnienia wykonane po porównaniu ze specyfikacją funkcjonalną użytkownika:

| Funkcja | Realizacja (core / UI) | Testy |
|---|---|---|
| Właściwości M1: przewodność cieplna λ | `core/gas_properties.py` (λ z CoolProp) | test_flammability |
| Właściwości M1: granice wybuchowości LEL/UEL | `core/flammability.py` (Le Chatelier) + `data/flammability.yaml` | test_flammability |
| Generator tabel/wykresów właściwości p,T | zakładka w `app/views/m01_gas_properties.py` | smoke M1 |
| **Straty gazu z awarii** (nowy moduł) | `core/gas_release.py` (wypływ krytyczny/podkrytyczny, blowdown, strefa LEL) + `app/views/m16_gas_release.py` | test_gas_release |
| M10: LCOHeat (koszt ciepła) | `lcoheat_for_technology` (`core/economics.py`) | test_economics |
| M10: LCOS (koszt magazynowania) | `lcos_for_storage` (`core/economics.py`) | test_economics |
| M7: merit order + screening curves | `core/screening.py` + zakładka w `app/views/m07_generation.py` | test_screening |

Świadomie pominięte (poza zakresem lub decyzja wcześniejsza): warianty
obliczeń A/B/C w M1 (jedna metoda GERG-2008, patrz §4); T_dew wody (wymaga
H₂O poza GERG); eksport PDF/PPT (przyjęto XLSX/CSV); krzywa MAC (M9) i
dashboard strategiczny (5.5) — kandydaci na kolejny etap.
