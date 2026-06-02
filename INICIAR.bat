@echo off
REM ===========================================================================
REM  EXTRATOR DE RADIACAO SOLAR (UNESP)
REM  De DOIS CLIQUES neste arquivo para abrir o programa.
REM
REM  Na PRIMEIRA vez ele instala tudo (demora alguns minutos, e' normal).
REM  Depois abre sozinho no navegador. Para fechar, feche esta janela.
REM ===========================================================================
cd /d "%~dp0"
title Extrator de Radiacao Solar

REM Garante que o Python existe.
where python >nul 2>nul
if errorlevel 1 (
  echo.
  echo [ERRO] O Python nao foi encontrado.
  echo Instale o Python 3.11+ em https://www.python.org/downloads/
  echo e marque a caixinha "Add Python to PATH" durante a instalacao.
  echo.
  pause
  exit /b 1
)

REM Cria o ambiente virtual e instala as dependencias na primeira vez.
if not exist ".venv" (
  echo Preparando o programa pela primeira vez. Isso pode demorar alguns minutos...
  python -m venv .venv
  call .venv\Scripts\activate.bat
  python -m pip install --upgrade pip
  pip install -r requirements.txt
) else (
  call .venv\Scripts\activate.bat
)

echo.
echo Abrindo o aplicativo no seu navegador...
echo (Para encerrar o programa, feche esta janela.)
echo.
streamlit run app\streamlit_app.py

pause
