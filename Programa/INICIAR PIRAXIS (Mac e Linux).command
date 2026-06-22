#!/usr/bin/env bash
# ===========================================================================
#  PIRAXIS — extrator de radiação solar (UNESP)
#  Launcher de DESENVOLVIMENTO (para máquinas que TÊM Python).
#
#  >>> Máquina SEM Python? Use o PACOTE PORTÁTIL do PIRAXIS (gerado por
#      empacotar.py): já vem com Python embutido e não precisa instalar nada.
#
#  Dê DOIS CLIQUES neste arquivo para abrir o programa (Mac e Linux).
#  Na PRIMEIRA vez ele prepara tudo (demora alguns minutos, é normal).
# ===========================================================================
cd "$(dirname "$0")"

# Cria o ambiente virtual na primeira vez (usa o Python do sistema).
if [ ! -x ".venv/bin/python" ]; then
  if ! command -v python3 >/dev/null 2>&1; then
    echo ""
    echo "[ERRO] O Python 3 não foi encontrado nesta máquina."
    echo " - Para usar ESTE atalho, instale o Python 3.11+ em"
    echo "   https://www.python.org/downloads/ e tente de novo; ou"
    echo " - use o PACOTE PORTÁTIL do PIRAXIS (não precisa de Python)."
    echo ""
    read -r -p "Pressione ENTER para sair..." _
    exit 1
  fi
  echo "Preparando o programa pela primeira vez. Isso pode demorar alguns minutos..."
  python3 -m venv .venv
fi

# Daqui em diante usamos SEMPRE o Python do próprio ambiente (.venv), sem
# depender de PATH -- evita o erro "streamlit: command not found".
PY="./.venv/bin/python"
if [ ! -x "$PY" ]; then
  echo ""
  echo "[ERRO] Não consegui preparar o ambiente (.venv). Instale o Python 3.11+"
  echo "ou use o PACOTE PORTÁTIL do PIRAXIS."
  echo ""
  read -r -p "Pressione ENTER para sair..." _
  exit 1
fi

# Garante as dependências (instala se o streamlit ainda não estiver presente).
if ! "$PY" -m pip show streamlit >/dev/null 2>&1; then
  echo "Instalando as bibliotecas necessárias (só na primeira vez)..."
  "$PY" -m pip install --upgrade pip
  "$PY" -m pip install -r requirements.txt
fi

echo ""
echo "Abrindo o aplicativo no seu navegador..."
echo "(Para encerrar o programa, feche esta janela.)"
echo ""
"$PY" -m streamlit run app/streamlit_app.py
