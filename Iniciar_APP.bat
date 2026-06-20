@echo off
setlocal EnableExtensions
cd /d "%~dp0"

echo.
echo ========================================================
echo   Bot Agencias - Iniciar panel
echo ========================================================
echo.

REM Si no hay entorno virtual, ejecutar instalacion automatica
if not exist ".venv\Scripts\python.exe" (
  echo No se detecto instalacion. Ejecutando setup.bat ...
  echo.
  call "%~dp0setup.bat"
  if errorlevel 1 (
    echo.
    echo [ERROR] La instalacion fallo. Revisá los mensajes de arriba.
    pause
    exit /b 1
  )
)

call ".venv\Scripts\activate.bat"
if errorlevel 1 (
  echo [ERROR] No se pudo activar el entorno virtual (.venv).
  pause
  exit /b 1
)

echo Iniciando el panel de gestion en http://127.0.0.1:8080
echo Presiona Ctrl+C para detener el servidor.
echo.

uvicorn app:app --reload --port 8080

echo.
echo El servidor se detuvo.
pause
endlocal
