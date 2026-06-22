@echo off
REM ===========================================================================
REM  PIRAXIS - extrator de radiacao solar (UNESP)
REM  Launcher de DESENVOLVIMENTO (para maquinas que TEM Python).
REM
REM  >>> Maquina SEM Python (ex.: laboratorio)? Use o PACOTE PORTATIL do
REM      PIRAXIS (gerado por empacotar.py): ele ja vem com Python embutido e
REM      NAO precisa instalar nada. Este .bat aqui NAO serve para esse caso.
REM
REM  De DOIS CLIQUES neste arquivo para abrir o programa.
REM  Na PRIMEIRA vez ele prepara tudo (demora alguns minutos, e' normal).
REM ===========================================================================
cd /d "%~dp0Programa"
title PIRAXIS

REM Confere se a pasta interna existe.
if not exist "app\streamlit_app.py" (
  echo.
  echo [ERRO] Nao encontrei a pasta "Programa" ao lado deste atalho.
  echo Mantenha este arquivo na mesma pasta que a pasta "Programa".
  echo.
  pause
  exit /b 1
)

REM Cria o ambiente virtual na primeira vez (usa o Python do sistema).
if not exist ".venv\Scripts\python.exe" (
  echo Preparando o programa pela primeira vez. Isso pode demorar alguns minutos...
  where python >nul 2>nul
  if errorlevel 1 (
    echo.
    echo [ERRO] O Python nao foi encontrado nesta maquina.
    echo  - Para usar ESTE atalho, instale o Python 3.11+ em
    echo    https://www.python.org/downloads/ e marque "Add Python to PATH".
    echo  - OU use o PACOTE PORTATIL do PIRAXIS, que ja vem com tudo embutido.
    echo.
    pause
    exit /b 1
  )
  python -m venv .venv
)

REM Daqui em diante usamos SEMPRE o Python do proprio ambiente (.venv), sem
REM depender de PATH/activate -- e' isto que evita o erro
REM "streamlit nao e' reconhecido como comando".
set "PY=.venv\Scripts\python.exe"
if not exist "%PY%" (
  echo.
  echo [ERRO] Nao consegui preparar o ambiente (.venv).
  echo Isso costuma acontecer quando o "python" e' apenas o ATALHO da Microsoft
  echo Store (um stub que nao instala nada). Solucoes:
  echo  - Instale o Python oficial (https://www.python.org/downloads/) marcando
  echo    "Add Python to PATH"; ou
  echo  - Use o PACOTE PORTATIL do PIRAXIS (nao precisa de Python).
  echo.
  pause
  exit /b 1
)

REM Garante as dependencias (instala se o streamlit ainda nao estiver presente).
"%PY%" -m pip show streamlit >nul 2>nul
if errorlevel 1 (
  echo Instalando as bibliotecas necessarias (so na primeira vez)...
  "%PY%" -m pip install --upgrade pip
  "%PY%" -m pip install -r requirements.txt
  if errorlevel 1 (
    echo.
    echo [ERRO] Falha ao instalar as bibliotecas. Confira sua internet e tente de novo.
    echo.
    pause
    exit /b 1
  )
)

echo.
echo Abrindo o aplicativo no seu navegador...
echo (Para encerrar o programa, feche esta janela.)
echo.
"%PY%" -m streamlit run app\streamlit_app.py
if errorlevel 1 (
  echo.
  echo Ocorreu um erro ao iniciar. Veja a mensagem acima.
  pause
)
