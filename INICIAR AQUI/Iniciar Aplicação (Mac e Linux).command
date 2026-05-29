#!/usr/bin/env bash
# ---------------------------------------------------------------------------
# Inicia o Extrator de Radiação Solar (Mac e Linux).
# Dê DOIS CLIQUES neste arquivo. Na primeira vez cria o ambiente virtual,
# instala as dependências e abre o app no navegador.
#
# Usamos a extensão .command para que no Mac o duplo clique abra direto.
# Como este atalho fica na subpasta "INICIAR AQUI", subimos um nível (..)
# para a pasta-pai do projeto antes de rodar.
# ---------------------------------------------------------------------------
set -e
cd "$(dirname "$0")/.."

if [ ! -d ".venv" ]; then
  echo "Criando ambiente virtual (.venv)..."
  python3 -m venv .venv
  ./.venv/bin/python -m pip install --upgrade pip
  ./.venv/bin/pip install -r requirements.txt
fi

echo "Abrindo o aplicativo no navegador..."
./.venv/bin/streamlit run app/streamlit_app.py
