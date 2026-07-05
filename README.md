# Narzędzie oceny projektów B+R w dystrybucji gazu

Modularne narzędzie obliczeniowo-analityczne dla operatora dystrybucji gazu
(PSG) do **oceny technicznej, ekonomicznej i ekologicznej projektów B+R** oraz
**benchmarkingu technologii** (wodór, mieszaniny H₂/gaz ziemny, OZE).

## Architektura

```
core/      # silnik obliczeniowy — czysta biblioteka Pythona (bez UI)
│  ├─ units.py    # jednostki SI, warunki odniesienia 0/15/25°C, przeliczniki
│  └─ config.py   # loader danych z data/ (z walidacją metadanych źródeł)
app/       # interfejs Streamlit (PL) — korzysta wyłącznie z API core/
│  ├─ main.py            # punkt wejścia, nawigacja
│  ├─ modules_registry.py# rejestr modułów M1–M14
│  └─ views/             # strony poszczególnych modułów
data/      # współczynniki, progi, biblioteki technologii (YAML/JSON)
│          # każdy plik: sekcja meta (description, updated) + pola source/note
tests/     # pytest: testy jednostkowe + walidacyjne (referencje NIST/literatura)
```

Zasady:

- **Rozdzielenie warstw** — ten sam silnik `core/` obsłuży lokalny UI,
  przyszłe REST API (FastAPI) i Power BI.
- **Termodynamika tylko z walidowanych bibliotek** — CoolProp
  (GERG-2008/HEOS); korelacje normowe (ISO 6976) z podaniem źródła.
- **Jawność metodyki** — każda funkcja obliczeniowa ma docstring ze wzorem,
  źródłem i zakresem ważności; w UI sekcje „Założenia i wzory".
- **Konwencja jednostek** — SI z jednostką w nazwie (`pressure_pa`,
  `temperature_k`); przeliczniki wyłącznie w `core/units.py`.
- **Dane oddzielone od kodu** — wartości domyślne w `data/` z polami
  `source` i `updated`; wartości niepewne oznaczone
  `note: "wartość orientacyjna — do weryfikacji"`.

## Uruchomienie — dla użytkownika (nieprogramisty)

1. Zainstaluj Pythona ≥ 3.11 z [python.org](https://www.python.org/downloads/)
   (Windows: zaznacz **„Add Python to PATH"**).
2. **Windows:** dwuklik na `start.bat` · **Mac/Linux:** `./start.sh`.
3. Aplikacja otworzy się w przeglądarce (`http://localhost:8501`).

Pełna instrukcja obsługi (po polsku, krok po kroku, typowe analizy,
edycja danych, FAQ): **[INSTRUKCJA.md](INSTRUKCJA.md)**. W aplikacji:
strona główna → zakładki „🚀 Jak zacząć" i „🧭 Typowe analizy".

## Uruchomienie — dla dewelopera

```bash
python -m venv .venv && source .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install -r requirements.txt
cp .env.example .env                                 # opcjonalnie
streamlit run app/main.py
```

### Testy

```bash
pytest                                 # testy jednostkowe + walidacyjne + dymne UI
python scripts/validation_report.py    # tabela: obliczone vs referencje (M1)
```

Tolerancje walidacji M1: Z, gęstość, cp ≤ 0,5%; wartości kaloryczne ≤ 0,1%
(referencje: ISO 6976, NIST WebBook, entalpie tworzenia ATcT/CODATA,
literatura — pełna lista w `tests/reference_data.py`).

## Plan pracy (etapy)

| Etap | Zakres | Status |
|---|---|---|
| 0 | Szkielet projektu, `units.py`, konfiguracja, pusty Streamlit z nawigacją | ✅ |
| 1 | M1 — właściwości gazów i mieszanin + testy walidacyjne | ✅ |
| 2 | M2 — sprężanie, M3 — gazociągi | ✅ |
| 3 | M4 — ekspandery, M13 — zimna redukcja (hydraty, źródła ciepła) | ✅ |
| 4 | M5 — ścieżki cenowe, M8–M9 — emisje | ✅ |
| 5 | M6 — produkcja wodoru (IEA), M7 — benchmark technologii wytwórczych | ✅ |
| 6 | M10 — ekonomia (LCOx/NPV/IRR/tornado), M11 — benchmarking, M12 — linepack | ✅ |
| 7 | M14 — karta projektu, eksporty XLSX/CSV, instrukcja, skrypty startowe | ✅ |

### Rozszerzenia po Etapie 7

- **M1 — liczba metanowa** (`core/methane_number.py`, `data/methane_number.yaml`):
  model liniowy, ścisły na osi CH₄/H₂; zastrzeżenie EN 16726/ASTM D8221.
  Edytor składu przyjmuje udziały molowe z dokładnością do 4 miejsc po przecinku.
- **Powietrze i CAES** (`data/gas_compositions.yaml` — skład „powietrze", argon
  w `components.yaml`): M3 liczy hydraulikę powietrza, M12 działa jako magazyn
  sprężonego powietrza (energia odzyskana z rozprężania, round-trip; model
  diabatyczny).
- **M3 — elastyczne tryby obliczeń**: wybór „Co policzyć?" — ciśnienie
  wylotowe P₂ (z zadanego przepływu), maksymalny przepływ (z wymaganego P₂)
  albo dobór minimalnej średnicy rury (`core.pipeline.min_diameter_m`).
- **M15 — Sieć gazowa (graf)** (`core/network.py`): grafy węzłów i odcinków
  (w tym pętle); solver węzłowy Newtona-Raphsona na p² z oporami odcinków
  kalibrowanymi modelem marszowym M3 (GERG-2008). **Śledzenie składu:**
  składy definiowane na punktach wejścia (zasilania ciśnieniowe + węzły
  wtłoczenia biometanu/H₂ o stałym strumieniu), skład każdego węzła liczony
  mieszaniem molowym dopływów po DAG-u kierunków przepływu, udziały źródeł
  śledzone jak znaczniki (strefy zasilania/mieszania). Wynik: ciśnienia,
  przepływy, skład i parametry gazu w każdym węźle (Hs, Ws, %H₂, liczba
  metanowa) z oceną wymogów gazu wysokometanowego E; pobory objętościowe
  przeliczane wg lokalnego składu.

## Ścieżka wdrożenia webowego (Azure)

Docelowo użytkownicy nic nie instalują — wchodzą na firmowy adres www
i logują się kontem służbowym:

1. **Konteneryzacja** — gotowy `Dockerfile`:
   `docker build -t gas-rd-tool . && docker run -p 8501:8501 gas-rd-tool`.
2. **Rejestr i hosting** — obraz do Azure Container Registry, uruchomienie
   w **Azure Container Apps** (lub App Service for Containers); katalogi
   `data/user_scenarios/` i `data/projects/` zamontować jako Azure Files
   (trwałość zapisów użytkowników); zmienne środowiskowe wg `.env.example`.
3. **Logowanie** — **Microsoft Entra ID** przez wbudowane uwierzytelnianie
   Container Apps/App Service (Easy Auth) — bez zmian w kodzie aplikacji;
   dostęp ograniczony do grupy AD.
4. **Power BI** — dziś: eksporty XLSX/CSV z M14 (separator `;`, UTF-8 BOM);
   docelowo: REST API (FastAPI) na tym samym pakiecie `core/` + dataset
   odświeżany automatycznie.
