@echo off
chcp 65001 >nul
title Ocena projektow B+R - dystrybucja gazu
cd /d "%~dp0"

where python >nul 2>nul
if errorlevel 1 (
    echo [BLAD] Nie znaleziono Pythona. Zainstaluj go z python.org
    echo        i zaznacz opcje "Add Python to PATH".
    pause
    exit /b 1
)

if not exist ".venv" (
    echo [1/3] Pierwsze uruchomienie: tworzenie srodowiska...
    python -m venv .venv || (echo [BLAD] Nie udalo sie utworzyc srodowiska & pause & exit /b 1)
    echo [2/3] Instalacja bibliotek (kilka minut, wymaga internetu)...
    .venv\Scripts\python -m pip install --quiet --upgrade pip
    .venv\Scripts\python -m pip install --quiet -r requirements.txt || (
        echo [BLAD] Instalacja bibliotek nie powiodla sie. Sprawdz internet. & pause & exit /b 1
    )
)

echo [3/3] Start aplikacji - otworzy sie w przegladarce (http://localhost:8501)
echo       Aby zakonczyc prace, zamknij to okno.
.venv\Scripts\python -m streamlit run app\main.py
pause
