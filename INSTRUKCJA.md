# Instrukcja użytkownika — narzędzie oceny projektów B+R w dystrybucji gazu

> Instrukcja dla użytkownika **nieprogramisty**. Część techniczna (dla IT)
> znajduje się w pliku `README.md`.

## 1. Pierwsze uruchomienie (jednorazowa instalacja)

### Windows

1. Zainstaluj Pythona: wejdź na **python.org/downloads**, pobierz
   „Python 3.11" (lub nowszy) i uruchom instalator.
   **WAŻNE:** na pierwszym ekranie zaznacz ☑ **„Add Python to PATH"**.
2. Rozpakuj/skopiuj katalog narzędzia w dowolne miejsce (np. `C:\Narzedzia\gaz-br`).
3. Kliknij dwukrotnie plik **`start.bat`** w katalogu narzędzia.
   - Przy pierwszym uruchomieniu skrypt sam pobierze potrzebne biblioteki
     (kilka minut, wymaga internetu) — kolejne starty trwają kilka sekund.
4. Aplikacja otworzy się w przeglądarce pod adresem `http://localhost:8501`.
   Jeśli nie otworzy się sama — wpisz ten adres w przeglądarce.

### Mac / Linux

1. Zainstaluj Pythona ≥ 3.11 (Mac: `brew install python`, Linux: z repozytorium).
2. W katalogu narzędzia uruchom **`./start.sh`** (pierwszy raz: `chmod +x start.sh`).

### Zamykanie

Zamknij okno czarnej konsoli (terminala) — aplikacja w przeglądarce przestanie
odpowiadać; kartę przeglądarki można zamknąć w dowolnym momencie.

## 2. Jak poruszać się po aplikacji

- **Menu po lewej** — moduły pogrupowane tematycznie (właściwości i przepływ,
  odzysk energii, scenariusze i emisje, technologie, ocena i porównania).
- **Strona główna** — zakładka „🚀 Jak zacząć" i „🧭 Typowe analizy"
  z gotowymi ścieżkami krok po kroku.
- Każda strona ma na dole sekcję **„📖 Założenia i wzory"** — metodyka,
  wzory i źródła danych (normy, raporty IEA/DNV itd.).
- **Żółte komunikaty** to ostrzeżenia merytoryczne (np. ryzyko hydratów) —
  warto je czytać; **czerwone** oznaczają błędne dane wejściowe.

## 3. Typowy przepływ pracy (ocena projektu)

1. **Policz wskaźniki** w modułach tematycznych, np.:
   - parametry gazu i wpływ %H₂ → **M1**,
   - energia sprężania / przepustowość rur → **M2 / M3**,
   - odzysk energii na stacji redukcyjnej → **M4 / M13**,
   - koszty i emisje wodoru → **M6, M10, M8–M9**,
   - porównanie z PV/wiatrem/baterią → **M11**.
2. **Zapisz kartę projektu** w **M14** (zakładka „📝 Nowy / edycja projektu").
   Każde pole podpowiada, w którym module wyznaczysz wartość. Pola, których
   nie masz — zostaw puste.
3. **Porównaj projekty** (zakładka „📊 Porównanie i ranking"): wybierz min. 2
   karty, ustaw wagi (technika / ekonomia / ekologia), odczytaj ranking
   i wykres radarowy.
4. **Eksportuj**: przyciski „⬇️ XLSX" / „⬇️ CSV" — pliki otwierają się
   w Excelu i wczytują do Power BI bez dodatkowych ustawień.

### Funkcje dodatkowe

- **M1 — liczba metanowa**: obok liczby Wobbego pokazywana jest liczba
  metanowa (odporność na spalanie stukowe w silnikach gazowych) z flagą
  limitu silnikowego. Spada z domieszką H₂; na osi CH₄/H₂ wynik jest ścisły.
  Wartość certyfikacyjna wymaga metody EN 16726/ASTM D8221 — narzędzie podaje
  szacunek modelem liniowym (oznaczone w UI). Udziały molowe można wpisywać
  z dokładnością do 4 miejsc po przecinku.
- **M3 / M12 — powietrze i magazyn CAES**: wybierz skład „Powietrze".
  W M3 policzysz hydraulikę przepływu powietrza starym gazociągiem; w M12
  moduł przełącza się w tryb **CAES** (magazyn sprężonego powietrza) i liczy
  energię elektryczną odzyskaną z rozprężania oraz sprawność round-trip.
- **M3 — „Co policzyć?"**: wybierz wielkość wynikową — **ciśnienie wylotowe
  P₂** (podajesz przepływ i rurę), **maksymalny przepływ** (podajesz wymagane
  P₂) albo **dobór średnicy** (podajesz przepływ i wymagane P₂) — nie trzeba
  znać wszystkiego naraz.
- **M15 — Sieć gazowa (graf)**: narysuj prostą sieć dwiema tabelami
  (węzły i odcinki, także z pętlami). Trzy typy węzłów: **zasilanie**
  (ciśnienie + skład), **pobór** (Nm³/h) oraz **wtłoczenie** — biometanownia
  lub elektrolizer H₂ o zadanym strumieniu i własnym składzie. Narzędzie
  policzy ciśnienia i przepływy, **skład gazu w każdym węźle** (mieszanie
  molowe), **strefy mieszania** (tabela pochodzenia gazu ze źródeł + mapa
  kolorowana wg %H₂ lub Wobbego) oraz oceni, czy gaz w każdym węźle spełnia
  **wymogi gazu wysokometanowego E** (Wobbe, próg %H₂, liczba metanowa).
  Uwaga: Ws czystego H₂ mieści się w widełkach E — dlatego kontrola %H₂
  i liczby metanowej jest niezbędna.

## 4. Scenariusze cenowe (M5)

- Wbudowane scenariusze: **niski / bazowy / wysoki** (ceny gazu, energii,
  H₂, EUA/ETS2, emisyjność miksu do 2050).
- Możesz je **edytować w tabeli** i zapisać pod własną nazwą — scenariusz
  pojawi się automatycznie we wszystkich modułach (M6–M11).
- Scenariusze użytkownika to pliki w `data/user_scenarios/` — można je
  kopiować między komputerami.

## 5. Zmiana danych domyślnych (bez programisty)

Wszystkie dane domyślne są w katalogu **`data/`** w plikach tekstowych
(YAML) otwieranych Notatnikiem, np.:

| Plik | Co zawiera |
|---|---|
| `gas_compositions.yaml` | składy gazów, w tym powietrze do CAES (podmień typowy skład E na własną analizę) |
| `quality_limits.yaml` | widełki Wobbego, progi %H₂ |
| `methane_number.yaml` | liczba metanowa składników i limit silnikowy |
| `compressors.yaml`, `expanders.yaml` | sprawności i mapy maszyn |
| `reduction_stations.yaml` | warianty stacji, źródła ciepła, ceny robocze |
| `price_scenarios.yaml` | scenariusze cenowe |
| `hydrogen_production.yaml`, `generation_technologies.yaml` | technologie H₂ i wytwórcze |

Zasady edycji: zachowaj wcięcia i dwukropki; po zmianie odśwież stronę
w przeglądarce (klawisz `R` lub przycisk „Rerun"). Każda wartość ma pole
`source` (źródło) — uzupełniaj je przy podmianie danych.

## 6. Najczęstsze problemy

| Objaw | Co zrobić |
|---|---|
| `start.bat` miga i znika | Python nie jest w PATH — przeinstaluj z opcją „Add Python to PATH" |
| „Suma udziałów molowych musi wynosić 100%" | Popraw skład w tabeli albo kliknij „Znormalizuj skład do 100%" |
| Czerwony komunikat o ciśnieniach | Ciśnienie wylotowe musi być niższe (redukcja) / wyższe (sprężanie) od wlotowego |
| Aplikacja działa wolno przy mieszaninach | Pierwsze obliczenie danego składu buduje model (do ~1 s); kolejne są natychmiastowe |
| Wynik wygląda podejrzanie | Sprawdź sekcję „📖 Założenia i wzory" oraz żółte ostrzeżenia |

## 7. Co dalej (wdrożenie firmowe)

Narzędzie jest przygotowane do uruchomienia jako aplikacja webowa
(bez instalacji u użytkowników): kontener Docker → Azure App Service /
Container Apps, logowanie kontami firmowymi (Microsoft Entra ID),
eksporty CSV/XLSX zasilające Power BI. Szczegóły techniczne: `README.md`,
sekcja „Ścieżka wdrożenia webowego".
