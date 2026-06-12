#!/usr/bin/env bash
# Uruchomienie narzędzia (Mac/Linux). Pierwszy start instaluje biblioteki.
set -e
cd "$(dirname "$0")"

if ! command -v python3 >/dev/null; then
    echo "[BŁĄD] Nie znaleziono Pythona 3. Zainstaluj go (≥ 3.11) i spróbuj ponownie."
    exit 1
fi

if [ ! -d ".venv" ]; then
    echo "[1/3] Pierwsze uruchomienie: tworzenie środowiska..."
    python3 -m venv .venv
    echo "[2/3] Instalacja bibliotek (kilka minut, wymaga internetu)..."
    .venv/bin/python -m pip install --quiet --upgrade pip
    .venv/bin/python -m pip install --quiet -r requirements.txt
fi

echo "[3/3] Start aplikacji — otworzy się w przeglądarce (http://localhost:8501)"
echo "      Aby zakończyć pracę, naciśnij Ctrl+C."
.venv/bin/python -m streamlit run app/main.py
