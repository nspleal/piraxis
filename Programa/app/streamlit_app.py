"""
app/streamlit_app.py
====================

Interface visual (Streamlit) do Extrator de Radiação Solar — ponto de entrada
do pesquisador. Tudo em português.

Fluxo:
  1. Título e descrição curtos.
  2. Assistente de primeira configuração do e-mail SoDa (só se necessário).
  3. Barra lateral: e-mail SoDa (editável), local, período, passo, fontes.
  4. Botão "Extrair dados" com spinner e barra de progresso.
  5. Pré-visualização (tabela + gráfico Plotly).
  6. Botão "Baixar Excel".
  7. Tratamento de erros amigável (sem stack trace cru).

Precedência do e-mail: digitado na sessão > salvo na máquina.

Execute com:  streamlit run app/streamlit_app.py
"""

from __future__ import annotations

import logging
import sys
from datetime import date, timedelta
from pathlib import Path

# Garante que a raiz do projeto esteja no sys.path quando rodado via Streamlit.
RAIZ = Path(__file__).resolve().parent.parent
if str(RAIZ) not in sys.path:
    sys.path.insert(0, str(RAIZ))

import pandas as pd
import plotly.express as px
import streamlit as st

from core import credenciais
from core.combinador import combinar
from core.config import BOTUCATU, PASSOS_TEMPORAIS
from output.exporta_excel import exporta, nome_arquivo_saida
from sources.cams_mcclear import ATRASO_DIAS, CamsMcClear
from sources.nasa_power import NasaPower

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)

st.set_page_config(page_title="Extrator de Radiação Solar — UNESP", page_icon="☀️")


# ---------------------------------------------------------------------------
# 1. Título e descrição
# ---------------------------------------------------------------------------
st.title("☀️ Extrator de Radiação Solar")
st.caption(
    "Ferramenta local da UNESP para extrair, comparar e exportar dados de "
    "radiação solar (CAMS McClear + NASA POWER) para uma planilha Excel."
)

# Data limite (hoje - 2 dias) por causa da defasagem do McClear.
LIMITE_DATA = date.today() - timedelta(days=ATRASO_DIAS)


# ---------------------------------------------------------------------------
# 2. Assistente de primeira configuração do e-mail SoDa
# ---------------------------------------------------------------------------
email_salvo = credenciais.carregar_email()

if not email_salvo:
    with st.container(border=True):
        st.warning(
            "👋 **Primeiro uso:** para usar o **CAMS McClear** você precisa de "
            "uma conta gratuita e individual no SoDa. A **NASA POWER** funciona "
            "sem nenhum cadastro."
        )
        st.markdown(
            "Crie sua conta em [soda-pro.com](https://www.soda-pro.com) e "
            "informe abaixo o **e-mail cadastrado** (ele fica salvo só nesta "
            "máquina)."
        )
        email_inicial = st.text_input(
            "E-mail da sua conta SoDa", key="email_assistente"
        )
        if st.button("Salvar", key="salvar_assistente"):
            try:
                credenciais.salvar_email(email_inicial)
                st.success("E-mail salvo nesta máquina! ✅")
                st.rerun()
            except ValueError as exc:
                st.error(str(exc))


# ---------------------------------------------------------------------------
# 3. Barra lateral
# ---------------------------------------------------------------------------
with st.sidebar:
    st.header("Configurações")

    st.subheader("Conta SoDa (CAMS McClear)")
    email_sessao = st.text_input(
        "E-mail SoDa",
        value=email_salvo or "",
        help="Necessário só para o CAMS McClear. A NASA POWER dispensa cadastro.",
    )
    if st.button("Salvar como padrão desta máquina"):
        try:
            credenciais.salvar_email(email_sessao)
            st.success("E-mail salvo nesta máquina! ✅")
        except ValueError as exc:
            st.error(str(exc))

    st.subheader("Local de estudo")
    nome_local = st.text_input("Nome", value=BOTUCATU.nome)
    latitude = st.number_input(
        "Latitude", value=BOTUCATU.latitude, min_value=-90.0, max_value=90.0,
        format="%.4f",
    )
    longitude = st.number_input(
        "Longitude", value=BOTUCATU.longitude, min_value=-180.0, max_value=180.0,
        format="%.4f",
    )
    altitude = st.number_input("Altitude (m)", value=BOTUCATU.altitude, format="%.1f")

    st.subheader("Período")
    data_inicio = st.date_input(
        "Data início", value=LIMITE_DATA - timedelta(days=1), max_value=LIMITE_DATA
    )
    data_fim = st.date_input(
        "Data fim", value=LIMITE_DATA, max_value=LIMITE_DATA
    )
    st.caption(f"Limite de data: {LIMITE_DATA:%d/%m/%Y} (hoje − {ATRASO_DIAS} dias).")

    st.subheader("Passo temporal")
    rotulo_passo = st.selectbox("Resolução", list(PASSOS_TEMPORAIS.keys()), index=2)
    passo_temporal = PASSOS_TEMPORAIS[rotulo_passo]

    st.subheader("Fontes de dados")
    # CAMS McClear é a fonte principal: já vem marcada por padrão.
    usar_mcclear = st.checkbox("CAMS McClear (céu limpo)", value=True)
    usar_nasa = st.checkbox("NASA POWER (real, com nuvens)", value=False)

    extrair = st.button("🚀 Extrair dados", type="primary", use_container_width=True)


# ---------------------------------------------------------------------------
# Funções auxiliares de extração
# ---------------------------------------------------------------------------
def _construir_local():
    from core.config import Local

    return Local(nome_local, float(latitude), float(longitude), float(altitude))


def _email_efetivo() -> str:
    """Precedência: e-mail digitado na sessão > e-mail salvo na máquina."""
    if email_sessao and email_sessao.strip():
        return email_sessao.strip()
    return email_salvo or ""


# ---------------------------------------------------------------------------
# 4. Extração
# ---------------------------------------------------------------------------
if extrair:
    erros: list[str] = []
    if not (usar_mcclear or usar_nasa):
        erros.append("Selecione ao menos uma fonte de dados.")
    if data_inicio > data_fim:
        erros.append("A data de início deve ser anterior ou igual à data de fim.")
    if usar_mcclear and not credenciais.email_valido(_email_efetivo()):
        erros.append(
            "Você marcou o **CAMS McClear**, mas não há um e-mail SoDa válido. "
            "Preencha o campo **E-mail SoDa** na barra lateral."
        )

    if erros:
        for e in erros:
            st.error(e)
    else:
        local = _construir_local()
        resultados: dict[str, pd.DataFrame] = {}
        passos: dict[str, str] = {}
        progresso = st.progress(0.0, text="Iniciando extração…")
        n_fontes = sum([usar_mcclear, usar_nasa])
        feitas = 0

        try:
            with st.spinner("Coletando dados das fontes selecionadas…"):
                if usar_nasa:
                    progresso.progress(
                        feitas / n_fontes, text="Consultando NASA POWER…"
                    )
                    fonte = NasaPower()
                    resultados[fonte.nome] = fonte.buscar(
                        local, data_inicio, data_fim, passo_temporal
                    )
                    passos[fonte.nome] = passo_temporal
                    feitas += 1
                    progresso.progress(feitas / n_fontes)

                if usar_mcclear:
                    progresso.progress(
                        feitas / n_fontes, text="Consultando CAMS McClear…"
                    )
                    fonte = CamsMcClear(_email_efetivo())
                    resultados[fonte.nome] = fonte.buscar(
                        local, data_inicio, data_fim, passo_temporal
                    )
                    passos[fonte.nome] = passo_temporal
                    feitas += 1
                    progresso.progress(feitas / n_fontes)

            combinado = combinar(resultados, passos)
            progresso.progress(1.0, text="Concluído!")

            # Guarda na sessão para o download e a pré-visualização.
            st.session_state["combinado"] = combinado
            st.session_state["metadados"] = {
                "local": local.nome,
                "latitude": local.latitude,
                "longitude": local.longitude,
                "altitude": local.altitude,
                "periodo": f"{data_inicio:%d/%m/%Y} a {data_fim:%d/%m/%Y}",
                "fontes": ", ".join(resultados.keys()),
                "passo_temporal": rotulo_passo,
                "email_soda": _email_efetivo() if usar_mcclear else "(não aplicável)",
            }
            st.session_state["periodo_arquivo"] = (data_inicio, data_fim, local.nome)
            st.success(
                f"Dados extraídos com sucesso! ✅ "
                f"{len(combinado)} registros para o período solicitado."
            )

            # Avisa se muitos valores vieram vazios (típico de datas recentes,
            # cujos dados ainda não foram totalmente processados pelas fontes).
            colunas_radiacao = [
                c
                for c in combinado.columns
                if c != "timestamp" and pd.api.types.is_numeric_dtype(combinado[c])
            ]
            if colunas_radiacao and len(combinado) > 0:
                frac_vazios = (
                    combinado[colunas_radiacao].isna().all(axis=1).mean()
                )
                if frac_vazios > 0.1:
                    st.warning(
                        f"⚠️ Cerca de {frac_vazios:.0%} dos horários do período "
                        "voltaram **sem dados** das fontes. Isso é comum em datas "
                        "muito recentes (os dados levam alguns dias para ficar "
                        "completos). Para uma série completa, experimente um "
                        "período que termine alguns dias antes de hoje."
                    )
        except (RuntimeError, ValueError) as exc:
            # Mensagem amigável, sem stack trace cru.
            st.error(f"Não foi possível concluir a extração: {exc}")
        except Exception as exc:  # pragma: no cover - rede de segurança
            st.error(
                "Ocorreu um erro inesperado durante a extração. Detalhe técnico: "
                f"{exc}"
            )


# ---------------------------------------------------------------------------
# 5. Pré-visualização e 6. Download
# ---------------------------------------------------------------------------
if "combinado" in st.session_state:
    combinado: pd.DataFrame = st.session_state["combinado"]

    st.subheader("Pré-visualização dos dados")
    st.caption(
        f"Tabela completa com **{len(combinado)}** registros do período "
        "(role para ver todos). A planilha Excel inclui exatamente estes dados."
    )
    st.dataframe(combinado, use_container_width=True, height=420)

    # Gráfico Plotly: uma linha por componente/fonte numérico.
    colunas_plot = [
        c
        for c in combinado.columns
        if c != "timestamp" and pd.api.types.is_numeric_dtype(combinado[c])
    ]
    if colunas_plot:
        fig = px.line(
            combinado,
            x="timestamp",
            y=colunas_plot,
            labels={"value": "Radiação (Wh/m²)", "timestamp": "Tempo", "variable": "Série"},
            title="Radiação ao longo do tempo",
        )
        st.plotly_chart(fig, use_container_width=True)

    st.subheader("Exportar")
    if st.button("📊 Baixar Excel"):
        try:
            data_ini, data_f, nome_loc = st.session_state["periodo_arquivo"]
            caminho = nome_arquivo_saida(nome_loc, data_ini, data_f)
            exporta(combinado, st.session_state["metadados"], caminho)
            with open(caminho, "rb") as fh:
                st.download_button(
                    "⬇️ Clique para baixar a planilha",
                    data=fh.read(),
                    file_name=caminho.name,
                    mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                )
            st.success(f"Planilha gerada: {caminho.name}")
        except Exception as exc:  # pragma: no cover
            st.error(f"Não foi possível gerar a planilha: {exc}")
