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

## Uruchomienie lokalne

Wymagania: Python ≥ 3.11.

```bash
python -m venv .venv && source .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install -r requirements.txt
cp .env.example .env                                 # opcjonalnie
streamlit run app/main.py
```

Aplikacja wystartuje pod `http://localhost:8501`.

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
| 2 | M2 — sprężanie, M3 — gazociągi | 🔜 |
| 3 | M4 — ekspandery, M13 — zimna redukcja | 🔜 |
| 4 | M5 — ścieżki cenowe, M8–M9 — emisje | 🔜 |
| 5 | M6 — produkcja wodoru, M7 — charakterystyki wytwarzania | 🔜 |
| 6 | M10 — ekonomia, M11 — benchmarking, M12 — linepack | 🔜 |
| 7 | M14 — karta projektu, eksporty XLSX/CSV/PDF, dokumentacja wdrożenia | 🔜 |

## Ścieżka wdrożenia webowego (docelowo)

1. **Konteneryzacja** — gotowy `Dockerfile` (Streamlit, port 8501).
2. **Azure** — Azure Container Apps lub App Service (Web App for Containers);
   konfiguracja przez zmienne środowiskowe (patrz `.env.example`).
3. **Uwierzytelnianie** — Microsoft Entra ID (App Service Easy Auth lub MSAL);
   struktura aplikacji nie wymaga zmian w `core/`.
4. **Power BI** — eksporty XLSX/CSV (etap 7), docelowo REST API (FastAPI)
   na tym samym silniku `core/`.
