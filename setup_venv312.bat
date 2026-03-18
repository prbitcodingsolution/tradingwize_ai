@echo off
setlocal enabledelayedexpansion
cd /d D:\trader_agent_29-01

echo ============================================================
echo  Setting up Python 3.12 venv for trader_agent project
echo ============================================================

echo.
echo [1/4] Deactivating any active venv and removing old venv...
call deactivate 2>nul
set VIRTUAL_ENV=
set PATH=%PATH:D:\trader_agent_29-01\venv\Scripts;=%

if exist venv (
    echo   Removing old venv...
    rmdir /s /q venv 2>nul
    if exist venv (
        echo   WARNING: Could not fully remove venv (files in use).
        echo   Please close all terminals that have the venv activated,
        echo   then run this script again.
        pause
        exit /b 1
    )
    echo   Old venv removed.
) else (
    echo   No old venv found, skipping.
)

echo.
echo [2/4] Creating new venv with Python 3.12...
py -3.12 -m venv venv
if errorlevel 1 (
    echo ERROR: Failed to create venv with Python 3.12
    echo Make sure Python 3.12 is installed: py --list
    pause
    exit /b 1
)
echo   venv created with Python 3.12

echo.
echo [3/4] Upgrading pip...
venv\Scripts\python.exe -m pip install --upgrade pip setuptools wheel --quiet
if errorlevel 1 (
    echo ERROR: Failed to upgrade pip
    pause
    exit /b 1
)
echo   pip upgraded

echo.
echo [4/4] Installing requirements from requirements_312.txt...
echo   This will take 5-15 minutes depending on your internet speed.
echo   Please wait...
echo.
venv\Scripts\pip.exe install -r requirements_312.txt --no-warn-script-location
if errorlevel 1 (
    echo.
    echo WARNING: Some packages may have failed. Trying with --ignore-requires-python...
    venv\Scripts\pip.exe install -r requirements_312.txt --ignore-requires-python --no-warn-script-location
)

echo.
echo ============================================================
echo  Verifying key imports...
echo ============================================================
echo.

venv\Scripts\python.exe -c "import pydantic_ai; print('  pydantic_ai:', pydantic_ai.__version__)"
if errorlevel 1 echo   ERROR: pydantic_ai failed

venv\Scripts\python.exe -c "import streamlit; print('  streamlit:', streamlit.__version__)"
if errorlevel 1 echo   ERROR: streamlit failed

venv\Scripts\python.exe -c "import yfinance; print('  yfinance:', yfinance.__version__)"
if errorlevel 1 echo   ERROR: yfinance failed

venv\Scripts\python.exe -c "import psycopg2; print('  psycopg2:', psycopg2.__version__)"
if errorlevel 1 echo   ERROR: psycopg2 failed

venv\Scripts\python.exe -c "import openai; print('  openai:', openai.__version__)"
if errorlevel 1 echo   ERROR: openai failed

venv\Scripts\python.exe -c "import langsmith; print('  langsmith:', langsmith.__version__)"
if errorlevel 1 echo   ERROR: langsmith failed

venv\Scripts\python.exe -c "import plotly; print('  plotly:', plotly.__version__)"
if errorlevel 1 echo   ERROR: plotly failed

echo.
echo ============================================================
echo  Setup complete!
echo  To run the app:
echo    venv\Scripts\activate
echo    streamlit run app_advanced.py
echo ============================================================
pause
