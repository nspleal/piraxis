@echo off
REM ---------------------------------------------------------------------------
REM Inicia o Extrator de Radiacao Solar (Windows).
REM De dois cliques neste arquivo. Na primeira vez cria o ambiente virtual,
REM instala as dependencias e abre o app no navegador.
REM ---------------------------------------------------------------------------
cd /d "%~dp0"

if not exist ".venv" (
  echo Criando ambiente virtual ^(.venv^)...
  python -m venv .venv
  call .venv\Scripts\activate.bat
  python -m pip install --upgrade pip
  pip install -r requirements.txt
) else (
  call .venv\Scripts\activate.bat
)

echo Abrindo o aplicativo no navegador...
streamlit run app\streamlit_app.py

pause
