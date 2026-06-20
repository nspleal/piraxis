"""
app/streamlit_app.py
====================

Interface visual (Streamlit) do Extrator de Radiação Solar — ponto de entrada
do pesquisador. Tudo em português.

Estilo: acadêmico sóbrio (azul institucional UNESP, cinzas neutros, âmbar como
detalhe nos dados de radiação). Esta camada cuida apenas da APRESENTAÇÃO — a
lógica de extração/combinação/exportação vem dos módulos core/, sources/ e
output/ e não é alterada aqui.

Fluxo:
  1. Cabeçalho institucional (logo + título).
  2. Assistente de primeira configuração do e-mail SoDa (só se necessário).
  3. Barra lateral: e-mail SoDa (editável), local, período, passo, fontes.
  4. Botão "Extrair dados" com spinner e barra de progresso.
  5. Resultados: cards de métricas + gráficos Plotly + tabela.
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
import plotly.graph_objects as go
import streamlit as st

from core import conferencia, credenciais
from core.combinador import combinar
from core.config import BOTUCATU, PASSOS_TEMPORAIS
from core.qualidade import analisar_qualidade
from core.reprodutibilidade import gerar_reprodutibilidade
from output.exporta_excel import exporta, nome_arquivo_saida
from sources.cams_mcclear import ATRASO_DIAS, CamsMcClear
from sources.nasa_power import NasaPower

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)

st.set_page_config(
    page_title="Extrator de Radiação Solar — UNESP",
    page_icon="☀️",
    layout="wide",
)

# O app é LOCAL (nunca publicado na web): escondemos o botão "Deploy", o menu
# nativo e o rodapé do Streamlit, que só distraem o pesquisador. O config.toml
# (toolbarMode="minimal") já remove o Deploy; este CSS é reforço.
st.markdown(
    """
    <style>
    [data-testid="stToolbar"] {visibility: hidden;}
    [data-testid="stDecoration"] {display: none;}
    #MainMenu {visibility: hidden;}
    footer {visibility: hidden;}
    </style>
    """,
    unsafe_allow_html=True,
)

# ---------------------------------------------------------------------------
# Paleta institucional e helpers de apresentação
# ---------------------------------------------------------------------------
# Azul institucional (primária). Ponto de partida sóbrio; troque aqui pelo azul
# oficial da UNESP quando disponível (manual de identidade: Pantone 2758 C).
AZUL = "#1F4E79"
# Âmbar/dourado: detalhe "solar", usado com parcimônia nos dados de radiação.
AMBAR = "#E8A33D"
CINZA_GRADE = "#E0E0E0"
CINZA_TEXTO = "#1A1A1A"

# Pasta de imagens (logo opcional).
ASSETS_DIR = Path(__file__).resolve().parent / "assets"
LOGO_UNESP = ASSETS_DIR / "logo_unesp.png"


def _fmt_num(valor: float, casas: int = 0) -> str:
    """Formata número no padrão brasileiro (1.234,5)."""
    if valor is None or (isinstance(valor, float) and pd.isna(valor)):
        return "—"
    s = f"{valor:,.{casas}f}"
    return s.replace(",", "X").replace(".", ",").replace("X", ".")


def _layout_padrao(fig: go.Figure, titulo: str, ylab: str = "Radiação (Wh/m²)") -> go.Figure:
    """Aplica o layout visual padrão (sóbrio, claro) a um gráfico Plotly."""
    fig.update_layout(
        title=dict(text=titulo, font=dict(size=18, color=AZUL)),
        template="plotly_white",
        font=dict(family="sans-serif", color=CINZA_TEXTO),
        xaxis=dict(title="Tempo", gridcolor=CINZA_GRADE),
        yaxis=dict(title=ylab, gridcolor=CINZA_GRADE),
        legend=dict(
            orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1
        ),
        margin=dict(l=10, r=10, t=70, b=10),
        hovermode="x unified",
        plot_bgcolor="white",
        paper_bgcolor="white",
    )
    return fig


def _serie_ghi(df: pd.DataFrame) -> pd.Series | None:
    """Encontra a coluna de GHI mais representativa para as métricas."""
    for c in ("GHI", "GHI_NASA", "GHI_McClear"):
        if c in df.columns:
            return df[c]
    return None


def _tem_duas_fontes(df: pd.DataFrame) -> bool:
    """Indica se o DataFrame combinado traz McClear e NASA lado a lado."""
    return "GHI_McClear" in df.columns and "GHI_NASA" in df.columns


def _figura_series(df: pd.DataFrame) -> go.Figure:
    """Curva de radiação ao longo do tempo (uma linha por série)."""
    fig = go.Figure()
    if _tem_duas_fontes(df):
        fig.add_trace(
            go.Scatter(
                x=df["timestamp"], y=df["GHI_McClear"],
                name="GHI céu limpo (McClear)",
                line=dict(color=AZUL, width=2.5),
            )
        )
        fig.add_trace(
            go.Scatter(
                x=df["timestamp"], y=df["GHI_NASA"],
                name="GHI real (NASA)",
                line=dict(color=AMBAR, width=2.5),
            )
        )
    else:
        cores = {"GHI": AZUL, "BHI": "#C8822E", "DHI": "#6B8FB5", "DNI": AMBAR}
        for comp in ("GHI", "BHI", "DHI", "DNI"):
            if comp in df.columns:
                fig.add_trace(
                    go.Scatter(
                        x=df["timestamp"], y=df[comp], name=comp,
                        line=dict(color=cores.get(comp), width=2),
                    )
                )
    return _layout_padrao(fig, "Radiação ao longo do tempo")


def _figura_area_nuvens(df: pd.DataFrame) -> go.Figure:
    """Área entre céu limpo (McClear) e real (NASA): perda por nuvens."""
    fig = go.Figure()
    # Linha superior: céu limpo (referência teórica).
    fig.add_trace(
        go.Scatter(
            x=df["timestamp"], y=df["GHI_McClear"],
            name="Céu limpo (McClear)",
            line=dict(color=AZUL, width=2),
        )
    )
    # Linha inferior: real; preenche a área entre ela e a anterior (âmbar).
    fig.add_trace(
        go.Scatter(
            x=df["timestamp"], y=df["GHI_NASA"],
            name="Real (NASA)",
            line=dict(color=AMBAR, width=2),
            fill="tonexty",
            fillcolor="rgba(232, 163, 61, 0.25)",
        )
    )
    return _layout_padrao(fig, "Efeito das nuvens (radiação perdida)")


def _cabecalho() -> None:
    """Cabeçalho institucional: logo (ou placeholder) + título + subtítulo."""
    col_logo, col_titulo = st.columns([1, 4], vertical_alignment="center")
    with col_logo:
        if LOGO_UNESP.exists():
            st.image(str(LOGO_UNESP), use_container_width=True)
        else:
            # Placeholder discreto — nunca quebra se o logo não existir.
            st.markdown(
                "<div style='border:1px dashed #B7C2D0;border-radius:8px;"
                "padding:18px 6px;text-align:center;color:#7A8699;"
                "background:#F2F5F9;font-size:0.78rem;line-height:1.2;'>"
                "Logo<br>UNESP</div>",
                unsafe_allow_html=True,
            )
    with col_titulo:
        st.markdown("## ☀️ Extrator de Radiação Solar")
        st.caption(
            "Ferramenta acadêmica da UNESP para extração e análise de radiação "
            "solar — CAMS McClear (céu limpo) & NASA POWER (real)."
        )


# ---------------------------------------------------------------------------
# 1. Cabeçalho
# ---------------------------------------------------------------------------
_cabecalho()
st.divider()

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
    st.header("⚙️ Configurações")

    st.subheader("🔑 Conta SoDa (CAMS McClear)")
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

    st.subheader("📍 Local de estudo")
    nome_local = st.text_input("Nome", value=BOTUCATU.nome)
    latitude = st.number_input(
        "Latitude", value=BOTUCATU.latitude, min_value=-90.0, max_value=90.0,
        format="%.4f",
    )
    longitude = st.number_input(
        "Longitude", value=BOTUCATU.longitude, min_value=-180.0, max_value=180.0,
        format="%.4f",
    )
    altitude = st.number_input(
        "Altitude (m)", value=BOTUCATU.altitude, format="%.1f",
        help="Informativo. O CAMS McClear estima a altitude pela própria fonte "
             "(SRTM), igual ao site da SoDa, para a extração bater com o "
             "download oficial.",
    )

    st.subheader("📅 Período")
    data_inicio = st.date_input(
        "Data início", value=LIMITE_DATA - timedelta(days=1), max_value=LIMITE_DATA
    )
    data_fim = st.date_input(
        "Data fim", value=LIMITE_DATA, max_value=LIMITE_DATA
    )
    st.caption(f"Limite de data: {LIMITE_DATA:%d/%m/%Y} (hoje − {ATRASO_DIAS} dias).")

    st.subheader("⏱️ Resolução")
    rotulo_passo = st.selectbox("Passo temporal", list(PASSOS_TEMPORAIS.keys()), index=2)
    passo_temporal = PASSOS_TEMPORAIS[rotulo_passo]

    st.subheader("🛰️ Fontes de dados")
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
            brutos: dict[str, object] = {}
            with st.spinner("Consultando fontes de radiação…"):
                if usar_nasa:
                    progresso.progress(
                        feitas / n_fontes, text="Consultando NASA POWER…"
                    )
                    fonte = NasaPower()
                    resultados[fonte.nome] = fonte.buscar(
                        local, data_inicio, data_fim, passo_temporal
                    )
                    if getattr(fonte, "resposta_crua", None) is not None:
                        brutos[fonte.nome] = fonte.resposta_crua
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
                    if getattr(fonte, "resposta_crua", None) is not None:
                        brutos[fonte.nome] = fonte.resposta_crua
                    passos[fonte.nome] = passo_temporal
                    feitas += 1
                    progresso.progress(feitas / n_fontes)

            combinado = combinar(resultados, passos)
            progresso.progress(1.0, text="Concluído!")

            # Guarda na sessão para o download e a pré-visualização.
            st.session_state["combinado"] = combinado
            st.session_state["brutos"] = brutos
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

            # Controle de qualidade + reprodutibilidade (não quebram a extração).
            nomes_fontes = list(resultados.keys())
            colunas_rad = [
                c
                for c in combinado.columns
                if c != "timestamp" and c != "kt"
                and pd.api.types.is_numeric_dtype(combinado[c])
            ]
            bases: list[str] = []
            for c in colunas_rad:
                base = (
                    c.replace("_McClear", "").replace("_NASA", "")
                    .replace("_ceu_limpo", "")
                )
                if base not in bases:
                    bases.append(base)
            try:
                st.session_state["qc"] = analisar_qualidade(
                    combinado, local, passo_temporal, nomes_fontes
                )
            except Exception as exc:  # pragma: no cover - QC nunca derruba a UI
                st.session_state["qc"] = None
                logging.getLogger(__name__).warning("Falha no QC: %s", exc)
            try:
                st.session_state["repro"] = gerar_reprodutibilidade(
                    local, data_inicio, data_fim, passo_temporal, rotulo_passo,
                    nomes_fontes, bases,
                )
            except Exception as exc:  # pragma: no cover
                st.session_state["repro"] = None
                logging.getLogger(__name__).warning("Falha na reprodutibilidade: %s", exc)

            st.success(
                f"✓ Extração concluída: {len(combinado)} registros de "
                f"{data_inicio:%d/%m/%Y} a {data_fim:%d/%m/%Y}."
            )
            st.caption(
                "🕒 Todos os horários estão em **UTC** (Tempo Universal "
                "Coordenado), igual nas duas fontes. Botucatu está em UTC−3, "
                "então o meio-dia solar local aparece por volta das 15h UTC. "
                "Ao comparar com o site de uma fonte, use o mesmo fuso (UTC)."
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
# 5. Resultados: métricas, gráficos, tabela e 6. Download
# ---------------------------------------------------------------------------
if "combinado" in st.session_state:
    combinado: pd.DataFrame = st.session_state["combinado"]

    st.divider()
    st.subheader("📊 Resumo do período")

    # --- Cards de métricas -------------------------------------------------
    cards: list[tuple[str, str]] = []
    ghi = _serie_ghi(combinado)
    if ghi is not None and ghi.notna().any():
        cards.append(("Radiação média (GHI)", f"{_fmt_num(ghi.mean(), 1)} Wh/m²"))
        cards.append(("Pico de radiação (GHI máx.)", f"{_fmt_num(ghi.max(), 1)} Wh/m²"))
    if "kt" in combinado.columns and combinado["kt"].notna().any():
        cards.append(
            ("Índice de claridade médio (kt)", _fmt_num(combinado["kt"].mean(), 2))
        )
    cards.append(("Registros extraídos", _fmt_num(len(combinado), 0)))

    for coluna, (rotulo, valor) in zip(st.columns(len(cards)), cards):
        coluna.metric(rotulo, valor)

    # --- Painel de qualidade ----------------------------------------------
    qc = st.session_state.get("qc")
    if qc is not None:
        st.divider()
        st.subheader("🔎 Qualidade dos dados")
        msg = f"Status geral: **{qc.status_geral}**"
        if qc.status_geral == "OK":
            st.success(f"✓ {msg} — os dados passaram nas verificações automáticas.")
        elif qc.status_geral == "Atenção":
            st.warning(f"⚠️ {msg} — há pontos a conferir (detalhes abaixo).")
        else:
            st.error(f"✗ {msg} — verifique os alertas antes de usar os dados.")

        n_alertas = (
            qc.n_negativos
            + qc.n_noturno_suspeito
            + (qc.envelope["n_violacoes"] if qc.envelope else 0)
            + (qc.fechamento["n_fora"] if qc.fechamento["aplicavel"] else 0)
        )
        cols_qc = st.columns(3)
        cols_qc[0].metric("Completude", f"{qc.completude_pct:.1f}%")
        cols_qc[1].metric("Alertas", _fmt_num(n_alertas, 0))
        if qc.concordancia_fontes is not None:
            cols_qc[2].metric(
                "RMSE rel. (fontes)",
                f"{qc.concordancia_fontes['rmse_rel_pct']:.1f}%",
            )
        else:
            cols_qc[2].metric("Lacunas", _fmt_num(len(qc.lacunas), 0))

        with st.expander("Ver relatório de qualidade"):
            st.text(qc.resumo_texto)
            if qc.lacunas:
                st.caption(f"Lacunas (até 20): {len(qc.lacunas)} intervalo(s).")
                st.dataframe(pd.DataFrame(qc.lacunas), use_container_width=True)
            nan_itens = {k: v for k, v in qc.nan_por_coluna.items() if v}
            if nan_itens:
                st.caption("Valores ausentes (NaN) por coluna:")
                st.json(nan_itens)

    # --- Reprodutibilidade e citações -------------------------------------
    repro = st.session_state.get("repro")
    if repro is not None:
        with st.expander("📑 Reprodutibilidade e citações"):
            st.markdown("**Metodologia (PT)**")
            st.write(repro.metodologia_pt)
            st.markdown("**Methodology (EN)**")
            st.write(repro.metodologia_en)
            st.markdown("**Referências e agradecimentos**")
            st.markdown(repro.citacoes_md)
            import json as _json

            data_ini, data_f, nome_loc = st.session_state["periodo_arquivo"]
            base_nome = nome_arquivo_saida(nome_loc, data_ini, data_f).stem
            col_md, col_js = st.columns(2)
            col_md.download_button(
                "⬇️ Baixar metodologia (.md)",
                data=repro.markdown.encode("utf-8"),
                file_name=f"{base_nome}_reprodutibilidade.md",
                mime="text/markdown",
            )
            col_js.download_button(
                "⬇️ Baixar proveniência (.json)",
                data=_json.dumps(
                    repro.proveniencia, ensure_ascii=False, indent=2
                ).encode("utf-8"),
                file_name=f"{base_nome}_proveniencia.json",
                mime="application/json",
            )

    # --- Conferência com o site (fidelidade) e auditoria ------------------
    with st.expander("🔬 Conferência com o site (fidelidade) e auditoria"):
        st.caption(
            "Para comprovar que a extração reproduz a fonte: baixe na SoDa o CSV "
            "do CAMS McClear para o MESMO ponto e período (em UTC) e suba aqui. A "
            "ferramenta compara linha a linha e gera o relatório de fidelidade."
        )
        data_ini2, data_f2, nome_loc2 = st.session_state["periodo_arquivo"]
        base_nome2 = nome_arquivo_saida(nome_loc2, data_ini2, data_f2).stem

        arquivo_site = st.file_uploader(
            "CSV do CAMS McClear baixado da SoDa", type=["csv"], key="conf_csv"
        )
        tem_mcclear = any(c in combinado.columns for c in ("GHI", "GHI_McClear"))
        if arquivo_site is not None and not tem_mcclear:
            st.info(
                "A conferência atual é do CAMS McClear — inclua o McClear na "
                "extração para comparar."
            )
        elif arquivo_site is not None:
            import tempfile

            try:
                with tempfile.NamedTemporaryFile(
                    "wb", suffix=".csv", delete=False
                ) as tmp:
                    tmp.write(arquivo_site.getvalue())
                    caminho_tmp = tmp.name
                referencia = conferencia.parsear_mcclear_site(caminho_tmp)
                rel = conferencia.comparar(combinado, referencia, "CAMS McClear")
            except Exception as exc:  # pragma: no cover - robustez de UI
                st.error(
                    "Não consegui ler esse arquivo como CSV do McClear da SoDa. "
                    f"Baixe no formato CSV padrão do site. Detalhe técnico: {exc}"
                )
            else:
                icone = {
                    "Idêntico": "✅", "Diferenças pequenas": "⚠️",
                    "Diferenças relevantes": "❌", "Sem sobreposição": "❌",
                }.get(rel.status, "ℹ️")
                st.markdown(f"**Fidelidade: {icone} {rel.status}**")
                st.text(rel.resumo_texto)
                if rel.por_componente:
                    st.dataframe(
                        pd.DataFrame(rel.por_componente).T,
                        use_container_width=True,
                    )
                st.download_button(
                    "⬇️ Baixar relatório de fidelidade (.md)",
                    data=conferencia.formatar_relatorio_md(rel).encode("utf-8"),
                    file_name=f"{base_nome2}_fidelidade.md",
                    mime="text/markdown",
                )

        # Auditoria: respostas CRUAS das fontes (quando vieram da rede).
        brutos = st.session_state.get("brutos") or {}
        if brutos:
            st.markdown("**Auditoria — respostas cruas da fonte**")
            st.caption(
                "Exatamente o que a fonte devolveu nesta extração, antes do "
                "processamento. Fica vazio quando a extração veio do cache."
            )
            import json as _json_audit

            for nome_fonte, bruto in brutos.items():
                slug = nome_fonte.replace(" ", "_")
                if isinstance(bruto, pd.DataFrame):
                    st.download_button(
                        f"⬇️ {nome_fonte} — resposta crua (.csv)",
                        data=bruto.to_csv().encode("utf-8"),
                        file_name=f"{base_nome2}_cru_{slug}.csv",
                        mime="text/csv",
                        key=f"cru_{slug}",
                    )
                else:
                    st.download_button(
                        f"⬇️ {nome_fonte} — resposta crua (.json)",
                        data=_json_audit.dumps(
                            bruto, ensure_ascii=False, indent=2
                        ).encode("utf-8"),
                        file_name=f"{base_nome2}_cru_{slug}.json",
                        mime="application/json",
                        key=f"cru_{slug}",
                    )

    # --- Gráficos ----------------------------------------------------------
    st.divider()
    tem_serie = any(
        c in combinado.columns
        for c in ("GHI", "BHI", "DHI", "DNI", "GHI_McClear", "GHI_NASA")
    )
    if tem_serie:
        st.plotly_chart(_figura_series(combinado), use_container_width=True)

    if _tem_duas_fontes(combinado):
        st.plotly_chart(_figura_area_nuvens(combinado), use_container_width=True)
        st.caption(
            "A área âmbar mostra a radiação **perdida por causa das nuvens** — a "
            "diferença entre o céu limpo teórico (McClear) e o real (NASA)."
        )

    # --- Tabela completa ---------------------------------------------------
    st.divider()
    st.subheader("🔢 Dados detalhados")
    st.caption(
        f"Tabela completa com **{len(combinado)}** registros do período "
        "(role para ver todos). A planilha Excel inclui exatamente estes dados."
    )
    st.dataframe(combinado, use_container_width=True, height=420)

    # --- Download ----------------------------------------------------------
    st.divider()
    st.subheader("⬇️ Exportar para Excel")
    if st.button("📊 Gerar planilha"):
        try:
            data_ini, data_f, nome_loc = st.session_state["periodo_arquivo"]
            caminho = nome_arquivo_saida(nome_loc, data_ini, data_f)
            exporta(
                combinado,
                st.session_state["metadados"],
                caminho,
                relatorio_qc=st.session_state.get("qc"),
                reprodutibilidade=st.session_state.get("repro"),
            )
            with open(caminho, "rb") as fh:
                st.download_button(
                    "Clique para baixar a planilha",
                    data=fh.read(),
                    file_name=caminho.name,
                    mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                )
            st.success(f"Planilha gerada: {caminho.name}")
        except Exception as exc:  # pragma: no cover
            st.error(f"Não foi possível gerar a planilha: {exc}")


# ---------------------------------------------------------------------------
# Rodapé
# ---------------------------------------------------------------------------
st.divider()
st.caption(
    f"Extrator de Radiação Solar · Ferramenta acadêmica da UNESP · "
    f"{date.today().year}"
)
