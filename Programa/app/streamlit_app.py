"""
app/streamlit_app.py
====================

Interface visual (Streamlit) do PIRAXIS (extrator de radiação solar) — ponto de
entrada do pesquisador. Tudo em português.

Identidade visual (2026-06-21): **tema escuro** sóbrio, no espírito de um painel
de instrumento científico (não um dashboard chamativo). Fundo carvão levemente
azulado, superfícies por contraste (não por sombra), cor de baixa saturação que
destaca o dado — nunca decora. Tipografia: Space Grotesk (títulos), JetBrains
Mono (números) e fonte do sistema (texto). Elemento de assinatura: a **cascata
de atenuação** (TOA → GHI → DHI → BHI → DNI). Esta camada cuida apenas da
APRESENTAÇÃO — a lógica de extração/combinação/exportação vem dos módulos core/,
sources/ e output/ e não é alterada aqui.

Quatro telas (abas), com barra lateral fixa de configuração:
  1. **Painel** — resumo: cards de integrais diárias + kt, cascata de atenuação,
     fechamento (GHI = BHI + DHI) e a série temporal horária.
  2. **Série temporal** — o gráfico horário em destaque (real cheia · céu limpo
     tracejada), com filtro de componentes.
  3. **Conferência** — fechamento por registro, controle de qualidade, conferência
     de fidelidade com o site da SoDa e auditoria (respostas cruas).
  4. **Dados** — a tabela completa + exportação (Excel/CSV) e reprodutibilidade.

Precedência do e-mail: digitado na sessão > salvo na máquina.
Convenção de horário: tudo em **UTC** (igual nas duas fontes).

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
from core.config import (
    BOTUCATU,
    CORES,
    CORES_CEU_LIMPO,
    NOMES_COMPONENTES,
    ORDEM_CASCATA,
    PASSOS_TEMPORAIS,
)
from core.qualidade import analisar_qualidade
from core.reprodutibilidade import gerar_reprodutibilidade
from output.exporta_excel import exporta, nome_arquivo_saida
from sources.cams_mcclear import ATRASO_DIAS, CamsMcClear
from sources.nasa_power import NasaPower

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)

# Favicon = símbolo PIRAXIS (pyranômetro + arco zenital). Cai para ☀️ se faltar.
_FAVICON = Path(__file__).resolve().parent / "assets" / "piraxis-icon.png"
st.set_page_config(
    page_title="PIRAXIS — UNESP",
    page_icon=str(_FAVICON) if _FAVICON.exists() else "☀️",
    layout="wide",
)

# ---------------------------------------------------------------------------
# Paleta da identidade visual (tema escuro) e ativos
# ---------------------------------------------------------------------------
BG = "#14181F"          # fundo do app (carvão azulado)
SURF = "#1B212B"        # superfície (cards, barra lateral)
ELEV = "#222A36"        # superfície elevada
TXT = "#E6E9EF"         # texto principal
TXT2 = "#9AA5B3"        # texto secundário
TXT3 = "#646F7E"        # texto terciário / rótulos
AZUL = "#34618F"        # azul institucional dessaturado (base interativa)
AZUL_CLARO = "#4A7AA8"  # azul interativo (hover / borda ativa)
AZUL_TXT = "#8FB0CC"    # azul claro para texto/links
AMBAR = "#E0A050"       # âmbar solar (acento parcimonioso — só o kt)
VERDE = "#6FA67E"       # validação OK
VERDE_TXT = "#8FC79E"
VERMELHO = "#C9776B"    # alerta
BORDA = "rgba(255,255,255,0.07)"

ASSETS_DIR = Path(__file__).resolve().parent / "assets"

# Símbolo PIRAXIS (piranômetro + arco zenital) embutido inline no cabeçalho —
# vetorial, sempre nítido. Mesma geometria do ícone/favicon (assets/).
LOGO_SVG = (
    "<svg width='34' height='34' viewBox='0 0 56 56' fill='none' "
    "xmlns='http://www.w3.org/2000/svg' style='display:block'>"
    "<circle cx='28' cy='28' r='22' fill='none' stroke='#4A7AA8' stroke-width='2'/>"
    "<circle cx='28' cy='28' r='13' fill='none' stroke='#4A7AA8' stroke-width='1.5'/>"
    "<line x1='5' y1='28' x2='51' y2='28' stroke='#34618F' stroke-width='0.75'/>"
    "<line x1='28' y1='6' x2='28' y2='25' stroke='#4A7AA8' stroke-width='1.5' "
    "stroke-dasharray='2.5,1.8'/>"
    "<circle cx='28' cy='6' r='4.5' fill='#E0A050'/>"
    "<circle cx='28' cy='28' r='3' fill='#E0A050'/></svg>"
)

# Ordem em que os cards de métrica aparecem no Painel (componentes da superfície
# primeiro; TOA por último — é o teto teórico).
ORDEM_CARDS = ("GHI", "DNI", "DHI", "BHI", "TOA")

# Tolerância (Wh/m²) do fechamento GHI = BHI + DHI exibido no app.
TOL_FECHAMENTO = 0.5


# ---------------------------------------------------------------------------
# CSS global — fontes, superfícies escuras, abas, cards e limpeza do chrome
# ---------------------------------------------------------------------------
def _injeta_css() -> None:
    css = f"""
    <style>
    @import url('https://fonts.googleapis.com/css2?family=Space+Grotesk:wght@400;500&family=JetBrains+Mono:wght@400;500&display=swap');

    /* O app é LOCAL (nunca publicado): esconde o chrome do Streamlit. */
    [data-testid="stToolbar"], [data-testid="stDecoration"],
    #MainMenu, footer, header {{ visibility: hidden; }}

    .stApp {{ background: {BG}; }}
    .block-container {{ padding-top: 1.4rem; padding-bottom: 2.5rem; max-width: 1180px; }}

    /* Tipografia: títulos em Space Grotesk; números/dados em JetBrains Mono. */
    h1, h2, h3, h4 {{
        font-family: 'Space Grotesk', sans-serif !important;
        font-weight: 500 !important;
        color: {TXT} !important;
        letter-spacing: 0.2px;
    }}
    html, body, [class*="css"] {{ font-family: system-ui, -apple-system, "Segoe UI", sans-serif; }}
    [data-testid="stMetricValue"] {{
        font-family: 'JetBrains Mono', monospace !important;
        font-weight: 500 !important; color: {TXT} !important;
    }}
    [data-testid="stMetricLabel"] {{ color: {TXT2} !important; }}

    /* Barra lateral: superfície escura + borda fina. */
    [data-testid="stSidebar"] {{
        background: {SURF};
        border-right: 0.5px solid {BORDA};
    }}
    [data-testid="stSidebar"] h2, [data-testid="stSidebar"] h3 {{
        font-size: 0.72rem !important; text-transform: uppercase;
        letter-spacing: 0.6px; color: {TXT3} !important; font-weight: 500 !important;
    }}

    /* Abas (Painel · Série temporal · Conferência · Dados) — barra de navegação. */
    [data-baseweb="tab-list"] {{
        gap: 4px; border-bottom: 0.5px solid {BORDA};
        background: transparent;
    }}
    [data-baseweb="tab"] {{
        height: 46px; padding: 0 16px; background: transparent !important;
        font-family: system-ui, sans-serif; font-size: 14px; color: {TXT2};
    }}
    [data-baseweb="tab"][aria-selected="true"] {{
        color: {TXT} !important;
        border-bottom: 2px solid {AZUL_CLARO} !important;
    }}
    [data-baseweb="tab-highlight"], [data-baseweb="tab-border"] {{ background: transparent !important; }}

    /* Botão primário sólido no azul institucional. */
    [data-testid="stSidebar"] .stButton > button[kind="primary"],
    .stButton > button[kind="primary"] {{
        background: {AZUL}; color: #FFFFFF; border: none; border-radius: 8px;
        font-weight: 500;
    }}
    .stButton > button[kind="primary"]:hover {{ background: {AZUL_CLARO}; color: #FFFFFF; }}
    .stButton > button[kind="secondary"] {{
        background: transparent; border: 0.5px solid {AZUL_CLARO}; color: {AZUL_TXT};
        border-radius: 8px;
    }}

    /* Cantos e bordas finas nos containers nativos (gráficos). */
    [data-testid="stVerticalBlockBorderWrapper"] {{ border-radius: 12px; }}

    /* ---- Componentes HTML próprios da identidade visual ---- */
    .rad-header {{
        display:flex; align-items:center; justify-content:space-between;
        padding: 4px 2px 14px 2px; margin-bottom: 6px;
        border-bottom: 0.5px solid {BORDA};
    }}
    .rad-header-left {{ display:flex; align-items:center; gap:16px; }}
    .rad-title {{
        font-family:'Space Grotesk',sans-serif; font-weight:500; font-size:19px;
        color:{TXT}; line-height:1.1; letter-spacing:0.2px;
    }}
    .rad-subtitle {{ font-size:12px; color:{TXT2}; margin-top:2px; }}
    .rad-pill {{
        display:inline-flex; align-items:center; gap:8px; padding:6px 12px;
        background:{ELEV}; border:0.5px solid {BORDA}; border-radius:8px;
        font-size:12px; color:{TXT2}; margin-left:10px;
    }}
    .rad-pill-mono {{ font-family:'JetBrains Mono',monospace; font-size:11px; color:{TXT3}; }}
    .rad-pill-date {{
        background:rgba(74,122,168,0.16); border:0.5px solid rgba(74,122,168,0.30);
        color:{AZUL_TXT};
    }}
    .rad-dot {{ width:8px; height:8px; border-radius:50%; display:inline-block; }}

    .rad-cards {{ display:grid; grid-template-columns:repeat(3,1fr); gap:14px; margin:6px 0 4px 0; }}
    .rad-card {{
        background:{SURF}; border:0.5px solid {BORDA}; border-radius:12px;
        padding:16px 18px; display:flex; flex-direction:column; gap:10px;
    }}
    .rad-card-head {{ display:flex; align-items:center; gap:8px; }}
    .rad-card-label {{
        font-size:11px; font-weight:500; text-transform:uppercase;
        letter-spacing:0.5px; color:{TXT2};
    }}
    .rad-card-val {{ font-family:'JetBrains Mono',monospace; font-size:24px; font-weight:500; line-height:1; color:{TXT}; }}
    .rad-card-unit {{ font-family:'JetBrains Mono',monospace; font-size:12px; color:{TXT3}; margin-left:5px; }}
    .rad-card-sub {{ font-family:'JetBrains Mono',monospace; font-size:12px; color:{TXT3}; }}

    .rad-panel {{
        background:{SURF}; border:0.5px solid {BORDA}; border-radius:12px;
        padding:18px 20px; height:100%;
    }}
    .rad-panel-title {{
        font-family:'Space Grotesk',sans-serif; font-weight:500; font-size:17px;
        color:{TXT}; margin-bottom:14px;
    }}
    .rad-casc {{ display:flex; align-items:flex-end; gap:10px; height:172px; padding-top:4px; }}
    .rad-casc-col {{ flex:1; display:flex; flex-direction:column; align-items:center; gap:6px; height:100%; justify-content:flex-end; }}
    .rad-casc-val {{ font-family:'JetBrains Mono',monospace; font-size:12px; color:{TXT}; }}
    .rad-casc-bar {{ width:100%; border-radius:4px 4px 0 0; min-height:4px; }}
    .rad-casc-pct {{ font-family:'JetBrains Mono',monospace; font-size:11px; color:{TXT3}; }}
    .rad-casc-key {{ font-family:'JetBrains Mono',monospace; font-size:11px; font-weight:500; }}
    .rad-note {{ font-size:12px; color:{TXT2}; line-height:1.5; margin-top:14px; }}

    .rad-eq {{ display:flex; align-items:center; justify-content:center; gap:10px;
        font-family:'JetBrains Mono',monospace; font-size:16px; margin:6px 0; }}
    .rad-eq-num {{ display:flex; align-items:center; justify-content:center; gap:10px;
        font-family:'JetBrains Mono',monospace; font-size:18px; color:{TXT}; }}
    .rad-ok {{
        background:rgba(111,166,126,0.12); border:0.5px solid rgba(111,166,126,0.32);
        border-radius:8px; padding:10px 12px; display:flex; align-items:center; gap:9px;
        font-size:12px; color:{VERDE_TXT}; margin-top:14px;
    }}
    .rad-bad {{
        background:rgba(201,119,107,0.12); border:0.5px solid rgba(201,119,107,0.32);
        border-radius:8px; padding:10px 12px; display:flex; align-items:center; gap:9px;
        font-size:12px; color:{VERMELHO}; margin-top:14px;
    }}
    .rad-check {{ width:16px; height:16px; border-radius:50%; background:{VERDE};
        display:flex; align-items:center; justify-content:center; color:{BG}; font-size:10px; flex:none; }}
    </style>
    """
    st.markdown(css, unsafe_allow_html=True)


_injeta_css()


# ---------------------------------------------------------------------------
# Helpers de apresentação
# ---------------------------------------------------------------------------
def _fmt_num(valor: float | None, casas: int = 0) -> str:
    """Formata número no padrão brasileiro (1.234,5). '—' quando vazio."""
    if valor is None or (isinstance(valor, float) and pd.isna(valor)):
        return "—"
    s = f"{valor:,.{casas}f}"
    return s.replace(",", "X").replace(".", ",").replace("X", ".")


def _serie(df: pd.DataFrame, comp: str) -> pd.Series | None:
    """Série representativa do componente: prefere o real (NASA), depois a base,
    depois o céu limpo (McClear) — cobre extração única e combinada."""
    for cand in (f"{comp}_NASA", comp, f"{comp}_McClear"):
        if cand in df.columns:
            return df[cand]
    return None


def _combinado_duas_fontes(df: pd.DataFrame) -> bool:
    """True quando o DataFrame traz McClear e NASA lado a lado (sufixadas)."""
    tem_mc = any(c.endswith("_McClear") for c in df.columns)
    tem_na = any(c.endswith("_NASA") for c in df.columns)
    return tem_mc and tem_na


def _componentes_presentes(df: pd.DataFrame) -> list[str]:
    """Componentes da identidade presentes, na ordem física da cascata."""
    return [c for c in ORDEM_CASCATA if _serie(df, c) is not None]


def _n_dias(df: pd.DataFrame) -> int:
    """Número de dias distintos no período (mínimo 1)."""
    if "timestamp" not in df.columns or df["timestamp"].isna().all():
        return 1
    return max(1, int(df["timestamp"].dt.normalize().nunique()))


def _unidade_dado(metadados: dict | None) -> str:
    """Unidade do dado conforme o passo (Wh/m² em todos os passos do projeto)."""
    return "Wh/m²"


def _kt_medio(df: pd.DataFrame) -> float | None:
    """Índice de claridade diário kt = ΣGHI / ΣTOA (ou média da coluna kt)."""
    if "kt" in df.columns and df["kt"].notna().any():
        return float(df["kt"].mean())
    ghi, toa = _serie(df, "GHI"), _serie(df, "TOA")
    if ghi is None or toa is None:
        return None
    soma_toa = toa.sum()
    if not soma_toa or pd.isna(soma_toa):
        return None
    return float(ghi.sum() / soma_toa)


def _layout_dark(fig: go.Figure, ylab: str = "Irradiância (Wh/m²)") -> go.Figure:
    """Aplica o layout escuro padrão a um gráfico Plotly."""
    fig.update_layout(
        template="plotly_dark",
        paper_bgcolor="rgba(0,0,0,0)",
        plot_bgcolor="rgba(0,0,0,0)",
        font=dict(family="JetBrains Mono, monospace", color=TXT2, size=12),
        xaxis=dict(
            title="Hora (UTC)", gridcolor="rgba(255,255,255,0.06)",
            zeroline=False, linecolor="rgba(255,255,255,0.14)",
        ),
        yaxis=dict(
            title=ylab, gridcolor="rgba(255,255,255,0.06)", zeroline=False,
        ),
        legend=dict(
            orientation="h", yanchor="bottom", y=1.02, xanchor="left", x=0,
            font=dict(size=11),
        ),
        margin=dict(l=10, r=10, t=28, b=10),
        hovermode="x unified",
    )
    return fig


def _figura_series(
    df: pd.DataFrame, ativos: list[str], mostrar_ceu_limpo: bool = True
) -> go.Figure:
    """Série temporal: real (NASA) em linha cheia, céu limpo (McClear) tracejado.

    Em extração de fonte única, desenha linhas cheias na cor do componente
    (mais legível); a distinção cheia/tracejada só aparece quando as duas
    fontes estão presentes.
    """
    fig = go.Figure()
    duas = _combinado_duas_fontes(df)
    for comp in ORDEM_CASCATA:
        if comp not in ativos:
            continue
        if duas:
            real_col = f"{comp}_NASA"
            clear_col = f"{comp}_McClear"
            if real_col in df.columns:
                fig.add_trace(
                    go.Scatter(
                        x=df["timestamp"], y=df[real_col],
                        name=f"{comp} · real",
                        line=dict(color=CORES[comp], width=2.4),
                        mode="lines",
                    )
                )
            if mostrar_ceu_limpo and clear_col in df.columns:
                fig.add_trace(
                    go.Scatter(
                        x=df["timestamp"], y=df[clear_col],
                        name=f"{comp} · céu limpo",
                        line=dict(color=CORES_CEU_LIMPO[comp], width=1.6, dash="dash"),
                        mode="lines", opacity=0.8,
                    )
                )
        else:
            serie = _serie(df, comp)
            if serie is not None:
                fig.add_trace(
                    go.Scatter(
                        x=df["timestamp"], y=serie, name=comp,
                        line=dict(color=CORES[comp], width=2.2),
                        mode="lines",
                    )
                )
    return _layout_dark(fig)


def _html_cards(df: pd.DataFrame, metadados: dict | None) -> str:
    """Grade de cards de métrica (integral diária + pico) por componente + kt."""
    n_dias = _n_dias(df)
    unidade = _unidade_dado(metadados)
    cartoes: list[str] = []
    for comp in ORDEM_CARDS:
        serie = _serie(df, comp)
        if serie is None or not serie.notna().any():
            continue
        integral = serie.sum() / n_dias / 1000.0  # kWh/m²/dia
        pico = serie.max()
        cor = CORES[comp]
        cartoes.append(
            f"<div class='rad-card'>"
            f"<div class='rad-card-head'><span class='rad-dot' style='background:{cor}'></span>"
            f"<span class='rad-card-label'>{comp} · {NOMES_COMPONENTES[comp]}</span></div>"
            f"<div class='rad-card-val'>{_fmt_num(integral, 2)}"
            f"<span class='rad-card-unit'>kWh/m²</span></div>"
            f"<div class='rad-card-sub'>pico {_fmt_num(pico, 0)} {unidade}</div>"
            f"</div>"
        )
    kt = _kt_medio(df)
    if kt is not None:
        cartoes.append(
            f"<div class='rad-card'>"
            f"<div class='rad-card-head'><span class='rad-dot' style='background:{AMBAR}'></span>"
            f"<span class='rad-card-label'>kt · índice de claridade</span></div>"
            f"<div class='rad-card-val' style='color:{AMBAR}'>{_fmt_num(kt, 3)}"
            f"<span class='rad-card-unit'>GHI / TOA</span></div>"
            f"<div class='rad-card-sub'>diário · adimensional</div>"
            f"</div>"
        )
    if not cartoes:
        return ""
    return "<div class='rad-cards'>" + "".join(cartoes) + "</div>"


def _html_cascata(df: pd.DataFrame) -> str | None:
    """Cascata de atenuação: barras em % da irradiância no topo da atmosfera."""
    toa = _serie(df, "TOA")
    n_dias = _n_dias(df)
    if toa is None or not toa.sum():
        return None
    toa_int = toa.sum()
    colunas: list[str] = []
    for comp in ORDEM_CASCATA:
        serie = _serie(df, comp)
        if serie is None:
            continue
        integ = serie.sum()
        pct = (integ / toa_int * 100) if toa_int else 0
        altura = max(4, round(pct / 100 * 150))
        cor = CORES[comp]
        colunas.append(
            f"<div class='rad-casc-col'>"
            f"<div class='rad-casc-val'>{_fmt_num(integ / n_dias / 1000.0, 2)}</div>"
            f"<div class='rad-casc-bar' style='background:{cor};height:{altura}px'></div>"
            f"<div class='rad-casc-pct'>{_fmt_num(pct, 0)}%</div>"
            f"<div class='rad-casc-key' style='color:{cor}'>{comp}</div>"
            f"</div>"
        )
    return (
        "<div class='rad-panel'>"
        "<div class='rad-panel-title'>Cascata de atenuação</div>"
        "<div class='rad-casc'>" + "".join(colunas) + "</div>"
        "<div class='rad-note'>Atenuação física da luz do topo da atmosfera (TOA) "
        "à superfície. Barras em % da irradiância no topo; valores em kWh/m²·dia. "
        "GHI separa-se em feixe (BHI) e difusa (DHI); DNI é o feixe na normal.</div>"
        "</div>"
    )


def _html_fechamento(df: pd.DataFrame) -> str | None:
    """Painel de fechamento GHI = BHI + DHI com o resíduo Δ validado."""
    ghi, bhi, dhi = _serie(df, "GHI"), _serie(df, "BHI"), _serie(df, "DHI")
    if ghi is None or bhi is None or dhi is None:
        return None
    n_dias = _n_dias(df)
    soma = bhi + dhi
    resid = (ghi - soma).abs()
    dmax = float(resid.max()) if resid.notna().any() else 0.0
    valido = dmax < TOL_FECHAMENTO
    di = lambda s: _fmt_num(s.sum() / n_dias / 1000.0, 2)  # noqa: E731
    selo = (
        f"<div class='rad-ok'><span class='rad-check'>✓</span>"
        f"<span>Δ validado = <span style='font-family:JetBrains Mono,monospace'>"
        f"{_fmt_num(dmax, 6)}</span> {_unidade_dado(None)}</span></div>"
        if valido
        else
        f"<div class='rad-bad'><span>Δ máximo = "
        f"<span style='font-family:JetBrains Mono,monospace'>{_fmt_num(dmax, 6)}</span> "
        f"{_unidade_dado(None)} — verifique o fechamento</span></div>"
    )
    return (
        "<div class='rad-panel'>"
        "<div class='rad-panel-title'>Fechamento</div>"
        "<div class='rad-eq'>"
        f"<span style='color:{CORES['GHI']};font-weight:500'>GHI</span><span style='color:{TXT3}'>=</span>"
        f"<span style='color:{CORES['BHI']};font-weight:500'>BHI</span><span style='color:{TXT3}'>+</span>"
        f"<span style='color:{CORES['DHI']};font-weight:500'>DHI</span></div>"
        "<div class='rad-eq-num'>"
        f"<span>{di(ghi)}</span><span style='color:{TXT3}'>=</span>"
        f"<span>{di(bhi)}</span><span style='color:{TXT3}'>+</span>"
        f"<span>{di(dhi)}</span></div>"
        f"<div style='font-size:11px;color:{TXT3};text-align:center'>kWh/m² · dia</div>"
        f"{selo}</div>"
    )


# ---------------------------------------------------------------------------
# Barra lateral (configuração) — executa primeiro para alimentar o cabeçalho
# ---------------------------------------------------------------------------
LIMITE_DATA = date.today() - timedelta(days=ATRASO_DIAS)
email_salvo = credenciais.carregar_email()

with st.sidebar:
    st.markdown(
        "<div style='font-size:11px;text-transform:uppercase;letter-spacing:0.6px;"
        f"color:{TXT3};font-weight:500;margin-bottom:8px'>Conta SoDa (CAMS McClear)</div>",
        unsafe_allow_html=True,
    )
    email_sessao = st.text_input(
        "E-mail SoDa",
        value=email_salvo or "",
        help="Necessário só para o CAMS McClear. A NASA POWER dispensa cadastro.",
        label_visibility="collapsed",
    )
    if st.button("Salvar e-mail nesta máquina"):
        try:
            credenciais.salvar_email(email_sessao)
            st.success("E-mail salvo nesta máquina! ✅")
        except ValueError as exc:
            st.error(str(exc))

    st.subheader("Local")
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
        help="Para a extração bater 100% com o site, use no formulário da SoDa "
             "exatamente esta mesma altitude. Se deixar 0 (ou em branco), a "
             "fonte estima pelo SRTM.",
    )

    st.subheader("Período")
    tipo_periodo = st.radio(
        "Tipo", ["Dia único", "Período"], horizontal=True,
        label_visibility="collapsed",
    )
    if tipo_periodo == "Dia único":
        dia = st.date_input(
            "Dia", value=LIMITE_DATA, max_value=LIMITE_DATA,
        )
        data_inicio = data_fim = dia
    else:
        data_inicio = st.date_input(
            "De", value=LIMITE_DATA - timedelta(days=6), max_value=LIMITE_DATA,
        )
        data_fim = st.date_input(
            "Até", value=LIMITE_DATA, max_value=LIMITE_DATA,
        )
    rotulo_passo = st.selectbox("Resolução", list(PASSOS_TEMPORAIS.keys()), index=2)
    passo_temporal = PASSOS_TEMPORAIS[rotulo_passo]
    st.caption(
        f"Limite de data: {LIMITE_DATA:%d/%m/%Y} (hoje − {ATRASO_DIAS} dias) · "
        "horários em **UTC**."
    )

    st.subheader("Fontes de dados")
    usar_nasa = st.checkbox("NASA POWER (real, com nuvens)", value=False)
    usar_mcclear = st.checkbox("CAMS McClear (céu limpo)", value=True)

    st.subheader("Componentes (gráficos)")
    _defaults_comp = {"TOA": False, "GHI": True, "DHI": True, "BHI": True, "DNI": True}
    componentes_ativos = [
        comp
        for comp in ORDEM_CASCATA
        if st.checkbox(
            f"{comp} — {NOMES_COMPONENTES[comp]}",
            value=_defaults_comp[comp], key=f"comp_{comp}",
        )
    ]

    st.markdown("<div style='height:6px'></div>", unsafe_allow_html=True)
    extrair = st.button(
        "Extrair dados", type="primary", use_container_width=True
    )


# ---------------------------------------------------------------------------
# Cabeçalho institucional (usa os valores da barra lateral)
# ---------------------------------------------------------------------------
def _cabecalho() -> None:
    logo_html = (
        f"{LOGO_SVG}"
        "<div style='width:0.5px;height:30px;background:rgba(255,255,255,0.12)'></div>"
    )
    if data_inicio == data_fim:
        kind, valor = "Dia", f"{data_inicio:%d/%m/%Y}"
    else:
        kind, valor = "Período", f"{data_inicio:%d/%m}–{data_fim:%d/%m/%Y}"
    st.markdown(
        "<div class='rad-header'>"
        "<div class='rad-header-left'>"
        f"{logo_html}"
        "<div><div class='rad-title' style='letter-spacing:4px;font-weight:500'>PIRAXIS</div>"
        "<div class='rad-subtitle'>extrator de radiação solar · UNESP / FCA Botucatu</div></div>"
        "</div>"
        "<div style='display:flex;align-items:center'>"
        f"<span class='rad-pill'><span class='rad-dot' style='background:{AMBAR}'></span>"
        f"{nome_local}<span class='rad-pill-mono'>"
        f"{latitude:.4f}, {longitude:.4f} · {altitude:.0f} m</span></span>"
        f"<span class='rad-pill rad-pill-date'>{kind} "
        f"<span style='font-family:JetBrains Mono,monospace;font-weight:500;color:#A9C4DC'>{valor}</span></span>"
        "</div></div>",
        unsafe_allow_html=True,
    )


_cabecalho()

# Assistente de primeira configuração do e-mail SoDa (só se necessário).
if not email_salvo:
    with st.container(border=True):
        st.warning(
            "👋 **Primeiro uso:** para usar o **CAMS McClear** você precisa de "
            "uma conta gratuita e individual no SoDa. A **NASA POWER** funciona "
            "sem nenhum cadastro."
        )
        st.markdown(
            "Crie sua conta em [soda-pro.com](https://www.soda-pro.com) e "
            "informe na barra lateral o **e-mail cadastrado** (ele fica salvo "
            "só nesta máquina)."
        )


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
# Extração (dispara ao clicar em "Extrair dados")
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
                    progresso.progress(feitas / n_fontes, text="Consultando NASA POWER…")
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
                    progresso.progress(feitas / n_fontes, text="Consultando CAMS McClear…")
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

            # Guarda na sessão para os painéis e o download.
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
                if c not in ("timestamp", "kt")
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
                f"{data_inicio:%d/%m/%Y} a {data_fim:%d/%m/%Y} (UTC)."
            )

            colunas_radiacao = [
                c
                for c in combinado.columns
                if c != "timestamp" and pd.api.types.is_numeric_dtype(combinado[c])
            ]
            if colunas_radiacao and len(combinado) > 0:
                frac_vazios = combinado[colunas_radiacao].isna().all(axis=1).mean()
                if frac_vazios > 0.1:
                    st.warning(
                        f"⚠️ Cerca de {frac_vazios:.0%} dos horários do período "
                        "voltaram **sem dados** das fontes. Isso é comum em datas "
                        "muito recentes (os dados levam alguns dias para ficar "
                        "completos). Para uma série completa, experimente um "
                        "período que termine alguns dias antes de hoje."
                    )
        except (RuntimeError, ValueError) as exc:
            st.error(f"Não foi possível concluir a extração: {exc}")
        except Exception as exc:  # pragma: no cover - rede de segurança
            st.error(
                "Ocorreu um erro inesperado durante a extração. Detalhe técnico: "
                f"{exc}"
            )


# ---------------------------------------------------------------------------
# Telas (abas): Painel · Série temporal · Conferência · Dados
# ---------------------------------------------------------------------------
PLOTLY_CFG = {"displayModeBar": False, "displaylogo": False}
aba_painel, aba_serie, aba_conf, aba_dados = st.tabs(
    ["Painel", "Série temporal", "Conferência", "Dados"]
)


def _aviso_vazio(msg: str = "Configure e clique em **Extrair dados** na barra lateral.") -> None:
    st.caption(msg)


# ----- Painel --------------------------------------------------------------
with aba_painel:
    if "combinado" not in st.session_state:
        _aviso_vazio()
    else:
        df: pd.DataFrame = st.session_state["combinado"]
        meta = st.session_state.get("metadados")

        st.markdown(
            "<div style='display:flex;align-items:baseline;justify-content:space-between'>"
            "<div style='font-family:Space Grotesk,sans-serif;font-weight:500;font-size:22px;"
            f"color:{TXT}'>Resumo da extração</div>"
            f"<div style='font-size:13px;color:{TXT2}'>Integrais diárias · "
            f"{(meta or {}).get('periodo', '')}</div></div>",
            unsafe_allow_html=True,
        )

        cards = _html_cards(df, meta)
        if cards:
            st.markdown(cards, unsafe_allow_html=True)

        col_casc, col_fech = st.columns([1.5, 1])
        with col_casc:
            casc = _html_cascata(df)
            if casc:
                st.markdown(casc, unsafe_allow_html=True)
            else:
                st.caption(
                    "Cascata de atenuação indisponível: requer o componente TOA "
                    "(presente na extração do CAMS McClear)."
                )
        with col_fech:
            fech = _html_fechamento(df)
            if fech:
                st.markdown(fech, unsafe_allow_html=True)
            else:
                st.caption(
                    "Fechamento indisponível: requer GHI, BHI e DHI na extração."
                )

        ativos = [c for c in componentes_ativos if _serie(df, c) is not None]
        if not ativos:
            ativos = _componentes_presentes(df)
        if ativos:
            st.markdown(
                "<div class='rad-panel-title' style='margin-top:8px'>"
                "Série temporal — irradiância horária</div>"
                f"<div style='font-size:12px;color:{TXT3};margin-bottom:8px'>"
                "— real (cheia) · ┈ céu limpo (tracejada)</div>",
                unsafe_allow_html=True,
            )
            with st.container(border=True):
                st.plotly_chart(
                    _figura_series(df, ativos), use_container_width=True,
                    config=PLOTLY_CFG, key="grafico_painel",
                )


# ----- Série temporal ------------------------------------------------------
with aba_serie:
    if "combinado" not in st.session_state:
        _aviso_vazio()
    else:
        df = st.session_state["combinado"]
        st.markdown(
            "<div style='font-family:Space Grotesk,sans-serif;font-weight:500;"
            f"font-size:22px;color:{TXT}'>Série temporal</div>",
            unsafe_allow_html=True,
        )
        mostrar_ceu = st.toggle(
            "Mostrar céu limpo (McClear, tracejado)", value=True,
            help="Quando as duas fontes são extraídas, mostra a curva de céu "
                 "limpo tracejada sobre a real.",
        )
        ativos = [c for c in componentes_ativos if _serie(df, c) is not None]
        if not ativos:
            ativos = _componentes_presentes(df)
        st.caption(
            "Componentes exibidos definidos na barra lateral (seção "
            "*Componentes*). Real (NASA POWER) em linha cheia; céu limpo "
            "(CAMS McClear) tracejado."
        )
        with st.container(border=True):
            st.plotly_chart(
                _figura_series(df, ativos, mostrar_ceu_limpo=mostrar_ceu),
                use_container_width=True, config=PLOTLY_CFG, key="grafico_serie",
            )


# ----- Conferência ---------------------------------------------------------
with aba_conf:
    if "combinado" not in st.session_state:
        _aviso_vazio()
    else:
        df = st.session_state["combinado"]
        st.markdown(
            "<div style='font-family:Space Grotesk,sans-serif;font-weight:500;"
            f"font-size:22px;color:{TXT}'>Conferência de fechamento</div>"
            f"<div style='font-size:13px;color:{TXT2};margin-bottom:6px'>"
            "GHI = BHI + DHI · por registro</div>",
            unsafe_allow_html=True,
        )

        ghi, bhi, dhi = _serie(df, "GHI"), _serie(df, "BHI"), _serie(df, "DHI")
        if ghi is not None and bhi is not None and dhi is not None:
            soma = bhi + dhi
            resid = (ghi - soma).abs()
            mask = ghi.notna() & soma.notna()
            n_total = int(mask.sum())
            n_ok = int((resid[mask] < TOL_FECHAMENTO).sum())
            dmax = float(resid[mask].max()) if n_total else 0.0
            if n_ok == n_total and n_total > 0:
                st.success(
                    f"✓ Fechamento validado em {n_ok}/{n_total} registros · "
                    f"resíduo máximo Δ = {_fmt_num(dmax, 6)} Wh/m²."
                )
            else:
                st.warning(
                    f"Fechamento: {n_ok}/{n_total} registros dentro da tolerância · "
                    f"resíduo máximo Δ = {_fmt_num(dmax, 6)} Wh/m²."
                )
            tabela = pd.DataFrame(
                {
                    "Hora (UTC)": df["timestamp"],
                    "GHI": ghi,
                    "BHI + DHI": soma,
                    "Δ": resid,
                    "Status": resid.lt(TOL_FECHAMENTO).map({True: "✓", False: "✗"}),
                }
            )
            st.dataframe(tabela, use_container_width=True, height=360, hide_index=True)
        else:
            st.caption(
                "Conferência de fechamento indisponível: requer GHI, BHI e DHI "
                "(presentes na extração do CAMS McClear)."
            )

        # Controle de qualidade automático.
        qc = st.session_state.get("qc")
        if qc is not None:
            st.divider()
            st.markdown("#### Controle de qualidade")
            cols_qc = st.columns(3)
            cols_qc[0].metric("Status geral", qc.status_geral)
            cols_qc[1].metric("Completude", f"{qc.completude_pct:.1f}%")
            n_alertas = (
                qc.n_negativos
                + qc.n_noturno_suspeito
                + (qc.envelope["n_violacoes"] if qc.envelope else 0)
                + (qc.fechamento["n_fora"] if qc.fechamento["aplicavel"] else 0)
            )
            cols_qc[2].metric("Alertas", _fmt_num(n_alertas, 0))
            with st.expander("Ver relatório de qualidade completo"):
                st.text(qc.resumo_texto)
                if qc.lacunas:
                    st.caption(f"Lacunas: {len(qc.lacunas)} intervalo(s).")
                    st.dataframe(pd.DataFrame(qc.lacunas), use_container_width=True)
                nan_itens = {k: v for k, v in qc.nan_por_coluna.items() if v}
                if nan_itens:
                    st.caption("Valores ausentes (NaN) por coluna:")
                    st.json(nan_itens)

        # Conferência de fidelidade com o site da SoDa + auditoria.
        st.divider()
        st.markdown("#### Fidelidade com o site (SoDa) e auditoria")
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
        tem_mcclear = any(c in df.columns for c in ("GHI", "GHI_McClear"))
        if arquivo_site is not None and not tem_mcclear:
            st.info(
                "A conferência atual é do CAMS McClear — inclua o McClear na "
                "extração para comparar."
            )
        elif arquivo_site is not None:
            import tempfile

            try:
                with tempfile.NamedTemporaryFile("wb", suffix=".csv", delete=False) as tmp:
                    tmp.write(arquivo_site.getvalue())
                    caminho_tmp = tmp.name
                meta_alt = (st.session_state.get("metadados") or {}).get("altitude")
                rel = conferencia.conferir_mcclear(
                    df, caminho_tmp, altitude_extracao=meta_alt
                )
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
                for aviso in rel.avisos:
                    st.warning("⚠️ " + aviso)
                st.text(rel.resumo_texto)
                if rel.por_componente:
                    st.dataframe(
                        pd.DataFrame(rel.por_componente).T, use_container_width=True
                    )
                st.download_button(
                    "⬇️ Baixar relatório de fidelidade (.md)",
                    data=conferencia.formatar_relatorio_md(rel).encode("utf-8"),
                    file_name=f"{base_nome2}_fidelidade.md",
                    mime="text/markdown",
                )

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
                        mime="text/csv", key=f"cru_{slug}",
                    )
                else:
                    st.download_button(
                        f"⬇️ {nome_fonte} — resposta crua (.json)",
                        data=_json_audit.dumps(
                            bruto, ensure_ascii=False, indent=2
                        ).encode("utf-8"),
                        file_name=f"{base_nome2}_cru_{slug}.json",
                        mime="application/json", key=f"cru_{slug}",
                    )


# ----- Dados ---------------------------------------------------------------
with aba_dados:
    if "combinado" not in st.session_state:
        _aviso_vazio()
    else:
        df = st.session_state["combinado"]
        st.markdown(
            "<div style='font-family:Space Grotesk,sans-serif;font-weight:500;"
            f"font-size:22px;color:{TXT}'>Dados extraídos</div>",
            unsafe_allow_html=True,
        )
        st.caption(
            f"Tabela completa com **{len(df)}** registros do período (UTC). A "
            "planilha Excel inclui exatamente estes dados."
        )
        st.dataframe(df, use_container_width=True, height=420, hide_index=True)

        data_ini, data_f, nome_loc = st.session_state["periodo_arquivo"]
        base_nome = nome_arquivo_saida(nome_loc, data_ini, data_f).stem

        col_xlsx, col_csv = st.columns(2)
        with col_xlsx:
            if st.button("📊 Gerar planilha Excel", use_container_width=True):
                try:
                    caminho = nome_arquivo_saida(nome_loc, data_ini, data_f)
                    exporta(
                        df, st.session_state["metadados"], caminho,
                        relatorio_qc=st.session_state.get("qc"),
                        reprodutibilidade=st.session_state.get("repro"),
                    )
                    with open(caminho, "rb") as fh:
                        st.download_button(
                            "⬇️ Baixar planilha (.xlsx)",
                            data=fh.read(), file_name=caminho.name,
                            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                            use_container_width=True,
                        )
                    st.success(f"Planilha gerada: {caminho.name}")
                except Exception as exc:  # pragma: no cover
                    st.error(f"Não foi possível gerar a planilha: {exc}")
        with col_csv:
            st.download_button(
                "⬇️ Exportar CSV",
                data=df.to_csv(index=False).encode("utf-8"),
                file_name=f"{base_nome}.csv", mime="text/csv",
                use_container_width=True,
            )

        # Reprodutibilidade e citações.
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


# ---------------------------------------------------------------------------
# Rodapé
# ---------------------------------------------------------------------------
st.markdown(
    f"<div style='margin-top:28px;padding-top:14px;border-top:0.5px solid {BORDA};"
    f"font-size:11px;color:{TXT3}'>PIRAXIS · extrator de radiação solar · "
    f"Ferramenta acadêmica da UNESP · {date.today().year} · horários em UTC</div>",
    unsafe_allow_html=True,
)
