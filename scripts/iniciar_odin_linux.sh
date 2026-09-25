#!/usr/bin/env bash
set -Eeuo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(cd -- "$SCRIPT_DIR/.." && pwd)"
LOG_DIR="$PROJECT_DIR/data/logs"
LOG_FILE="$LOG_DIR/odin_launcher.log"

mkdir -p "$LOG_DIR"
cd "$PROJECT_DIR"

if [[ -x "$PROJECT_DIR/.venv/bin/python" ]]; then
    PYTHON_BIN="$PROJECT_DIR/.venv/bin/python"
elif [[ -x "$PROJECT_DIR/venv/bin/python" ]]; then
    PYTHON_BIN="$PROJECT_DIR/venv/bin/python"
elif command -v python3 >/dev/null 2>&1; then
    PYTHON_BIN="$(command -v python3)"
else
    {
        echo "[$(date '+%Y-%m-%d %H:%M:%S')] ERRO: Python 3 não encontrado."
    } >> "$LOG_FILE"
    exit 127
fi

{
    echo
    echo "============================================================"
    echo "[$(date '+%Y-%m-%d %H:%M:%S')] Iniciando ODIN"
    echo "Projeto: $PROJECT_DIR"
    echo "Python:  $PYTHON_BIN"
} >> "$LOG_FILE"

export PYTHONUNBUFFERED=1
exec "$PYTHON_BIN" "$PROJECT_DIR/main.py" >> "$LOG_FILE" 2>&1
