@echo off
setlocal EnableExtensions
cd /d "%~dp0"

echo.
echo ========================================================
echo   Bot Agencias - Instalacion automatica (Windows)
echo ========================================================
echo.

REM --- Detectar Python 3.10+ ---
set "PYTHON="
where py >nul 2>&1
if %ERRORLEVEL%==0 (
  py -3 -c "import sys; raise SystemExit(0 if sys.version_info>=(3,10) else 1)" >nul 2>&1
  if %ERRORLEVEL%==0 set "PYTHON=py -3"
)

if not defined PYTHON (
  where python >nul 2>&1
  if %ERRORLEVEL%==0 (
    python -c "import sys; raise SystemExit(0 if sys.version_info>=(3,10) else 1)" >nul 2>&1
    if %ERRORLEVEL%==0 set "PYTHON=python"
  )
)

if not defined PYTHON (
  echo [ERROR] Python 3.10+ no encontrado.
  echo Descargalo desde https://www.python.org/downloads/
  echo Asegurate de marcar "Add Python to PATH" durante la instalacion.
  exit /b 1
)

for /f "delims=" %%V in ('%PYTHON% -c "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}')"') do set PYVER=%%V
echo [OK] Python %PYVER% detectado

REM --- Entorno virtual ---
if not exist ".venv\Scripts\python.exe" (
  echo.
  echo Creando entorno virtual .venv ...
  %PYTHON% -m venv .venv
  if errorlevel 1 (
    echo [ERROR] No se pudo crear el entorno virtual.
    exit /b 1
  )
  echo [OK] Entorno virtual creado
) else (
  echo [OK] Entorno virtual existente (.venv)
)

call ".venv\Scripts\activate.bat"
if errorlevel 1 (
  echo [ERROR] No se pudo activar el entorno virtual.
  exit /b 1
)

echo.
echo Instalando dependencias (pip)...
python -m pip install --upgrade pip --quiet
python -m pip install -r requirements.txt
if errorlevel 1 (
  echo [ERROR] Fallo la instalacion de requirements.txt
  exit /b 1
)
echo [OK] Dependencias instaladas

echo.
echo Configurando base de datos y usuario administrador...
python scripts\instalar.py
if errorlevel 1 (
  echo [ERROR] Fallo la configuracion inicial.
  exit /b 1
)

echo.
echo Para iniciar el sistema ejecuta:
echo   .venv\Scripts\activate.bat
echo   uvicorn app:app --reload --port 8080
echo.
endlocal
