#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$ROOT"

echo
echo "========================================================"
echo "  Bot Agencias - Instalación automática (Linux/macOS)"
echo "========================================================"
echo

find_python() {
  for cmd in python3 python py; do
    if command -v "$cmd" >/dev/null 2>&1; then
      if "$cmd" -c 'import sys; raise SystemExit(0 if sys.version_info >= (3, 10) else 1)' 2>/dev/null; then
        echo "$cmd"
        return 0
      fi
    fi
  done
  return 1
}

PYTHON="$(find_python || true)"
if [[ -z "$PYTHON" ]]; then
  echo "[ERROR] Python 3.10+ no encontrado."
  echo "Instalalo con tu gestor de paquetes o desde https://www.python.org/downloads/"
  exit 1
fi

PYVER="$("$PYTHON" -c 'import sys; print(f"{sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}")')"
echo "[OK] Python $PYVER detectado"

if [[ ! -d ".venv" ]]; then
  echo
  echo "Creando entorno virtual .venv ..."
  "$PYTHON" -m venv .venv
  echo "[OK] Entorno virtual creado"
else
  echo "[OK] Entorno virtual existente (.venv)"
fi

# shellcheck disable=SC1091
source ".venv/bin/activate"

echo
echo "Instalando dependencias (pip)..."
python -m pip install --upgrade pip --quiet
python -m pip install -r requirements.txt
echo "[OK] Dependencias instaladas"

echo
echo "Configurando base de datos y usuario administrador..."
python scripts/instalar.py

echo
echo "Para iniciar el sistema ejecutá:"
echo "  source .venv/bin/activate"
echo "  uvicorn app:app --reload --port 8080"
echo
