#!/usr/bin/env bash
# ---------------------------------------------------------------------------
# Inicia o Extrator de Radiação Solar (Linux/Mac).
# Dê dois cliques (ou rode ./iniciar.sh). Cria o ambiente virtual na primeira
# vez, instala as dependências e abre o app no navegador.
# ---------------------------------------------------------------------------
set -e
cd "$(dirname "$0")"

if [ ! -d ".venv" ]; then
  echo "Criando ambiente virtual (.venv)..."
  python3 -m venv .venv
  ./.venv/bin/python -m pip install --upgrade pip
  ./.venv/bin/pip install -r requirements.txt
fi

echo "Abrindo o aplicativo no navegador..."
./.venv/bin/streamlit run app/streamlit_app.py
