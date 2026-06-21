#!/usr/bin/env bash
# ===========================================================================
#  PIRAXIS — EXTRATOR DE RADIAÇÃO SOLAR (UNESP)
#  Dê DOIS CLIQUES neste arquivo para abrir o programa (Mac e Linux).
#
#  Na PRIMEIRA vez ele instala tudo (demora alguns minutos, é normal).
#  Depois abre sozinho no navegador. Para fechar, feche esta janela.
# ===========================================================================
set -e
cd "$(dirname "$0")"

# Garante que o Python existe.
if ! command -v python3 >/dev/null 2>&1; then
  echo ""
  echo "[ERRO] O Python 3 não foi encontrado."
  echo "Instale o Python 3.11+ em https://www.python.org/downloads/ e tente de novo."
  echo ""
  read -r -p "Pressione ENTER para sair..." _
  exit 1
fi

# Cria o ambiente virtual e instala as dependências na primeira vez.
if [ ! -d ".venv" ]; then
  echo "Preparando o programa pela primeira vez. Isso pode demorar alguns minutos..."
  python3 -m venv .venv
  ./.venv/bin/python -m pip install --upgrade pip
  ./.venv/bin/pip install -r requirements.txt
fi

echo ""
echo "Abrindo o aplicativo no seu navegador..."
echo "(Para encerrar o programa, feche esta janela.)"
echo ""
./.venv/bin/streamlit run app/streamlit_app.py
