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
| **M2** sprężanie | M1 (A), biblioteka sprężarek (D) | praca kWh/kg·Nm³, T tłoczenia stopni, ciepło chłodnic | M3 (energia tłoczenia, A), M12 (napełnianie, A), M13 (⚠ ciepło odpadowe — **P**: statyczny wpis 70 °C w danych, nie wynik M2) |
| **M3** gazociąg | M1 (A), chropowatości (D) | P₂/przepływ/średnica, profil p,v | M15 (kalibracja oporów K — A), M12 pośrednio |
| **M4** ekspandery | M1 (A), biblioteka ekspanderów (D) | moc odzyskana, T wylotu, macierz doboru (CAPEX/kW, TRL) | M13 (wariant ekspanderowy — A), M12 CAES (A); ⚠ M10 — **brak mostka** (LCOE ekspandera tylko ręcznie przez M14 — R) |
| **M5** ceny | scenariusze (D + JSON użytkownika) | ścieżki cen nośników, EUA/ETS2, emisyjność miksu | M6, M7, M8–M9, M10, M11 — **A**; ⚠ M13 — **NIE** (własne ceny robocze — patrz §3.1) |
| **M6** wodór | biblioteka IEA (D), M5 (A), M1 Hi(H2) (A) | kWh/kg, woda, emisje 1+2, koszt energii | M10 LCOH (A), M14 (R) |
| **M7** wytwarzanie | katalogi DEA/IEA (D), M5 (A), M8 emisje gazu (A) | η/COP/cf, g CO₂/kWh, koszt paliwowy | M10 LCOE (A), M11 (A), **M13 źródła ciepła (A — `heat_source_entries`)** |
| **M8–M9** emisje | M1 stechiometria (A), GWP AR6 (D), miks z M5 (A) | kg CO₂/Nm³·kWh·kg, CO₂eq ucieczek, zakres 2 | M7 (A), M6 (A), M10 koszt EUA (A), M14 (R) |
| **M10** ekonomia | M5 (A), M6 (A), M7 (A), WACC/okres od użytkownika | LCOH/LCOE z dekompozycją, NPV/IRR/DPP, tornado | M11 (A), M14 (R) |
| **M11** benchmark | M10 (A), M7 (A), bateria+dyspozycyjność (D) | ranking wielokryterialny | M14 (R) |
| **M12** linepack/CAES | M1 (A), M2 sprężanie (A), M4 rozprężanie (A) | bufor MWh, round-trip CAES | M14 (R) |
| **M13** stacja redukcyjna | M1 (A), M4 (A), hydraty (A), źródła ciepła: M7 (A) + baza (D) + sprężarki (**P**) | podgrzew/odzysk/chłód, porównanie wariantów | M14 (R); ⚠ ceny: własne robocze (**P**), nie M5 |
| **M14** karta projektu | wskaźniki z M1–M13 — **R** (pola formularza z podpowiedzią „gdzie policzyć") | karta JSON, ranking projektów, XLSX/CSV | Power BI/Excel (eksport) |
| **M15** sieć | M1 składy źródeł (A), M3 kalibracja K (A), jakość: M1+MN (A) | ciśnienia, przepływy, składy węzłów, strefy mieszania, flagi E | eksport CSV |

Konwencje wspólne (jedno źródło prawdy): ρₙ zawsze z
`compute_properties(comp, 101 325 Pa, 273,15 K)`; kurs EUR/PLN tylko
w `price_scenarios.yaml`; wszystkie przeliczniki jednostek w `core/units.py`;
GWP tylko w `emission_factors.yaml`.

## 3. Znane luki i niespójności (stan na audyt)

### 3.1 Dwa źródła cen (M13 vs M5) — priorytet 1
`variant_economics` (M13) liczy na cenach roboczych z
`reduction_stations.yaml`, nie na ścieżkach scenariuszy M5. Zmiana
scenariusza w M5 nie wpływa na M13. Docelowo: `variant_economics`
przyjmuje `(scenario, year)`; ceny robocze zostają wyłącznie jako fallback.

### 3.2 Ciepło odpadowe sprężarek = placeholder — priorytet 1
Wpis „ciepło odpadowe sprężarek (60–80 °C)" to statyczne dane, nie wynik
M2. Docelowo: funkcja w M2 budująca `HeatSource` z policzonego sprężania
(poziomy T stopni, dostępna moc), podawana do M13.

### 3.3 Alokacja kosztów kogeneracji w M10 — priorytet 2
LCOE dla kogeneracji: paliwo i CO₂ dzielone metodą energetyczną (η_całk),
ale CAŁY CAPEX przypisany energii elektrycznej, a produkcja = tylko MWh el.
Mieszana metodyka (dokumentowana w M7, nieopisana w M10). Docelowo: spójna
alokacja albo jawny kredyt ciepła jako parametr.

### 3.4 Praca cyklu bufora w M12 przy stałych końcach — priorytet 2
Napełnianie: cała masa Δm sprężana od p_min do p_max (rzeczywiste
przeciwciśnienie rośnie stopniowo → praca zawyżona); opróżnianie (CAES):
cała Δm rozprężana od p_max (ciśnienie bufora spada → odzysk zawyżony).
Błędy częściowo znoszą się w round-trip; oba strumienie zawyżone
~10–20%. Docelowo: całkowanie napełniania/opróżniania w N krokach ciśnienia.

### 3.5 Brak mostka M4 → M10 — priorytet 2
CAPEX/kW ekspanderów jest w danych i macierzy doboru, ale M10 nie ma
kalkulatora opłacalności ekspandera (przychód = energia odzyskana,
koszty = CAPEX + podgrzew netto z M13). Dziś ścieżka ręczna przez M14.

### 3.6 M14 zasilana ręcznie — świadoma decyzja
Karta projektu zbiera wskaźniki wpisywane przez użytkownika (z podpowiedzią
modułu źródłowego). Zaleta: audytowalność wartości; wada: brak przycisku
„przenieś wynik do karty". Kandydat na usprawnienie UX, nie błąd.

### 3.7 Konwencja: emisyjność miksu w scenariuszach M5
Ścieżka `emisyjnosc_miksu` [t CO₂/MWh] jest technicznie „nośnikiem"
w scenariuszach cen (wspólny mechanizm interpolacji). Semantycznie to
wskaźnik, nie cena — konwencja przyjęta świadomie i opisana tutaj.
