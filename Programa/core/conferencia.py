"""
core/conferencia.py
===================

Auditoria e conferência de fidelidade.

Compara a extração da ferramenta com um **download oficial do site da fonte**
(ex.: o CSV do CAMS McClear baixado da SoDa), alinhando por ``timestamp`` e
medindo, componente a componente, o quanto diferem. Produz um RELATÓRIO DE
FIDELIDADE — onde e quanto a extração se afasta do site.

Por que existe: o destino do projeto (patente + venda a pesquisadores) exige
provar que a extração reproduz EXATAMENTE o que a fonte entrega. Esta camada é a
ferramenta objetiva dessa prova; não altera a extração, apenas a confere.

Notas de comparabilidade (devem casar com a extração da ferramenta):
  - O CSV do site é lido pela própria ``pvlib.iotools.read_cams`` com
    ``integrated=True`` (valores em Wh/m², iguais à extração) e
    ``map_variables=True`` (nomes padronizados).
  - Os horários são tratados em UTC, sem fuso (como em todo o projeto).
  - O componente "DNI" do projeto é o "BNI" (feixe normal) da SoDa — mesmo dado.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field

import numpy as np
import pandas as pd

logger = logging.getLogger(__name__)

# Componentes comparáveis, na ordem do arquivo da SoDa.
COMPONENTES = ("GHI", "BHI", "DHI", "DNI")

# Nomes da pvlib (céu limpo) -> nomes do projeto.
_PVLIB_PARA_PROJETO: dict[str, str] = {
    "ghi_clear": "GHI",
    "bhi_clear": "BHI",
    "dhi_clear": "DHI",
    "dni_clear": "DNI",
}

# Tolerâncias padrão para considerar "igual".
TOL_ABS_WHM2 = 0.5   # Wh/m² — ruído de arredondamento aceitável
TOL_REL = 0.01       # 1% — diferença relativa aceitável
LIMIAR_RELEVANTE = 0.05  # acima de 5% relativo, a diferença é "relevante"


@dataclass
class RelatorioFidelidade:
    """Resultado estruturado de uma conferência extração × site."""

    fonte: str
    tol_abs: float
    tol_rel: float
    n_comum: int            # timestamps presentes nos dois
    n_so_extracao: int      # timestamps só na extração
    n_so_referencia: int    # timestamps só no arquivo do site
    por_componente: dict[str, dict]  # comp -> métricas
    status: str             # "Idêntico" | "Diferenças pequenas" | "Diferenças relevantes" | "Sem sobreposição"
    resumo_texto: str = ""
    componentes_so_extracao: list[str] = field(default_factory=list)
    componentes_so_referencia: list[str] = field(default_factory=list)
    avisos: list[str] = field(default_factory=list)


# ---------------------------------------------------------------------------
# Leitura do CSV do site (SoDa / CAMS McClear) via pvlib
# ---------------------------------------------------------------------------
def parsear_mcclear_site(caminho) -> pd.DataFrame:
    """Lê um CSV do CAMS McClear baixado do site da SoDa e padroniza.

    Caminho feliz: usa ``pvlib.iotools.read_cams`` (integrated=True -> Wh/m²,
    igual à extração). Mas se o arquivo tiver passado por um editor de planilha
    com locale pt-BR — que troca o ponto decimal por separador de milhar e infla
    os valores ~10.000× (ex.: ``1066.6589`` vira ``"10.666.589"``) — esse formato
    é DETECTADO e decodificado automaticamente, para a conferência não acusar uma
    diferença falsa. Devolve timestamp (UTC, sem fuso) + GHI/BHI/DHI/DNI.
    """
    texto = _ler_texto(caminho)
    if texto and _eh_corrompido(texto):
        return _parsear_corrompido(texto)

    import pvlib

    dados, _meta = pvlib.iotools.read_cams(
        caminho, integrated=True, map_variables=True
    )
    return _padronizar_pvlib(dados)


def _ler_texto(caminho) -> str:
    """Lê o arquivo como texto; devolve '' se não for possível (ex.: file-like)."""
    try:
        with open(caminho, "r", encoding="utf-8", errors="ignore") as fh:
            return fh.read()
    except (OSError, TypeError, ValueError):
        return ""


# Valor numérico "corrompido": tem 2+ pontos (ex.: "10.666.589"), o que só
# ocorre quando o ponto decimal virou separador de milhar.
_RE_MULTIPONTO = re.compile(r"\d\.\d{3}\.\d")


def _eh_corrompido(texto: str) -> bool:
    """True se algum valor numérico aparece com separador de milhar (2+ pontos)."""
    for linha in texto.splitlines():
        if not linha or linha.startswith("#"):
            continue
        if "/" not in linha.split(";", 1)[0]:
            continue
        if _RE_MULTIPONTO.search(linha):
            return True
    return False


def _decodificar(token: str) -> float:
    """Decodifica um valor do arquivo corrompido: tira os pontos e divide por
    10.000 (o McClear sempre traz 4 casas decimais)."""
    token = token.strip()
    if not token:
        return float("nan")
    try:
        return int(token.replace(".", "")) / 10000.0
    except ValueError:
        return float("nan")


def _parsear_corrompido(texto: str) -> pd.DataFrame:
    """Parser do CSV McClear corrompido por editor de planilha (pt-BR)."""
    mapa = {
        "Clear sky GHI": "GHI", "Clear sky BHI": "BHI",
        "Clear sky DHI": "DHI", "Clear sky BNI": "DNI",
    }
    nomes = None
    linhas_dados = []
    for linha in texto.splitlines():
        linha = linha.rstrip()
        if not linha:
            continue
        if "Clear sky GHI" in linha and ";" in linha:
            nomes = [c.strip().lstrip("# ").strip() for c in linha.split(";")]
            continue
        if linha.startswith("#"):
            continue
        if "/" in linha.split(";", 1)[0]:
            linhas_dados.append(linha.split(";"))

    if nomes:
        idx = {mapa[n]: i for i, n in enumerate(nomes) if n in mapa}
    else:  # ordem padrão do McClear: período;TOA;GHI;BHI;DHI;BNI
        idx = {"GHI": 2, "BHI": 3, "DHI": 4, "DNI": 5}

    registros = []
    for campos in linhas_dados:
        ts = pd.Timestamp(campos[0].split("/")[0].replace(".0", ""))
        reg = {"timestamp": ts}
        for comp, i in idx.items():
            reg[comp] = _decodificar(campos[i]) if i < len(campos) else float("nan")
        registros.append(reg)
    df = pd.DataFrame(registros)
    cols = ["timestamp"] + [c for c in COMPONENTES if c in df.columns]
    return df[cols]


def ler_altitude_site(caminho) -> float | None:
    """Extrai a altitude (m) do cabeçalho do CSV do site, se houver."""
    m = re.search(
        r"Altitude\s*\(m\)\s*:\s*([0-9]+(?:\.[0-9]+)?)", _ler_texto(caminho)
    )
    if not m:
        return None
    try:
        return float(m.group(1))
    except ValueError:
        return None


def _padronizar_pvlib(dados: pd.DataFrame) -> pd.DataFrame:
    """Converte o DataFrame da pvlib (indexado por tempo) no padrão do projeto."""
    df = dados.reset_index()
    col_tempo = df.columns[0]
    df = df.rename(columns={col_tempo: "timestamp"})
    out = pd.DataFrame({"timestamp": _sem_fuso(df["timestamp"])})
    for nome_pvlib, nome_proj in _PVLIB_PARA_PROJETO.items():
        if nome_pvlib in df.columns:
            out[nome_proj] = pd.to_numeric(df[nome_pvlib], errors="coerce")
    return out


# ---------------------------------------------------------------------------
# Núcleo da comparação
# ---------------------------------------------------------------------------
def _sem_fuso(serie: pd.Series) -> pd.Series:
    """Garante timestamps datetime sem fuso (naive), tratando tz-aware."""
    ts = pd.to_datetime(serie)
    try:
        ts = ts.dt.tz_localize(None)
    except (TypeError, AttributeError):
        # Já é naive (tz_localize(None) só vale para tz-aware).
        pass
    return ts


def _normalizar(df: pd.DataFrame) -> pd.DataFrame:
    """Prepara um DataFrame para conferência: tira sufixo de fonte (_McClear),
    mantém timestamp + componentes conhecidos e remove o fuso do timestamp."""
    renomear = {}
    for c in df.columns:
        base = c.replace("_McClear", "").replace("_NASA", "")
        if base in COMPONENTES and c != base:
            renomear[c] = base
    df = df.rename(columns=renomear)
    if "timestamp" not in df.columns:
        raise ValueError("DataFrame sem coluna 'timestamp' para conferência.")
    cols = ["timestamp"] + [c for c in COMPONENTES if c in df.columns]
    saida = df[cols].copy()
    saida["timestamp"] = _sem_fuso(saida["timestamp"])
    return saida.dropna(subset=["timestamp"]).drop_duplicates(subset="timestamp")


def comparar(
    extracao: pd.DataFrame,
    referencia: pd.DataFrame,
    fonte: str = "CAMS McClear",
    tol_abs: float = TOL_ABS_WHM2,
    tol_rel: float = TOL_REL,
) -> RelatorioFidelidade:
    """Compara a ``extracao`` da ferramenta com a ``referencia`` (site), alinhando
    por timestamp, e devolve um ``RelatorioFidelidade``.
    """
    ex = _normalizar(extracao).set_index("timestamp").sort_index()
    ref = _normalizar(referencia).set_index("timestamp").sort_index()

    comuns = ex.index.intersection(ref.index)
    n_so_ex = len(ex.index.difference(ref.index))
    n_so_ref = len(ref.index.difference(ex.index))

    comp_ex = [c for c in COMPONENTES if c in ex.columns]
    comp_ref = [c for c in COMPONENTES if c in ref.columns]
    componentes = [c for c in COMPONENTES if c in comp_ex and c in comp_ref]

    por_componente: dict[str, dict] = {}
    if len(comuns) == 0:
        rel = RelatorioFidelidade(
            fonte, tol_abs, tol_rel, 0, n_so_ex, n_so_ref, {},
            "Sem sobreposição",
            componentes_so_extracao=[c for c in comp_ex if c not in comp_ref],
            componentes_so_referencia=[c for c in comp_ref if c not in comp_ex],
        )
        rel.resumo_texto = _montar_resumo(rel)
        return rel

    a = ex.loc[comuns]
    b = ref.loc[comuns]
    status = "Idêntico"
    for c in componentes:
        va = pd.to_numeric(a[c], errors="coerce")
        vb = pd.to_numeric(b[c], errors="coerce")
        valido = va.notna() & vb.notna()
        n_aval = int(valido.sum())
        metrica = {
            "n_avaliado": n_aval,
            "max_abs": 0.0,
            "media_abs": 0.0,
            "max_rel": 0.0,
            "n_fora_tol": 0,
        }
        if n_aval:
            diff = (va - vb).abs()
            denom = vb.abs().where(vb.abs() > tol_abs)
            rel = diff / denom
            rel_validos = rel[valido].dropna()
            max_rel = float(rel_validos.max()) if len(rel_validos) else 0.0
            fora = valido & (diff > tol_abs) & (rel.fillna(0.0) > tol_rel)
            metrica.update(
                max_abs=round(float(diff[valido].max()), 4),
                media_abs=round(float(diff[valido].mean()), 4),
                max_rel=round(max_rel, 4),
                n_fora_tol=int(fora.sum()),
            )
            status = _pior(status, _status_componente(metrica))
        por_componente[c] = metrica

    rel = RelatorioFidelidade(
        fonte, tol_abs, tol_rel, len(comuns), n_so_ex, n_so_ref,
        por_componente, status,
        componentes_so_extracao=[c for c in comp_ex if c not in comp_ref],
        componentes_so_referencia=[c for c in comp_ref if c not in comp_ex],
    )
    rel.resumo_texto = _montar_resumo(rel)
    return rel


def conferir_mcclear(
    extracao: pd.DataFrame,
    caminho_csv_site,
    tol_abs: float = TOL_ABS_WHM2,
    tol_rel: float = TOL_REL,
    altitude_extracao: float | None = None,
) -> RelatorioFidelidade:
    """Confere a ``extracao`` contra um CSV do CAMS McClear baixado da SoDa.

    Detecta arquivo corrompido por editor de planilha (decodifica sozinho) e, se
    ``altitude_extracao`` for informada, avisa quando difere da altitude do site
    (causa típica de diferença sistemática). Avisos vão em ``rel.avisos``.
    """
    texto = _ler_texto(caminho_csv_site)
    referencia = parsear_mcclear_site(caminho_csv_site)
    rel = comparar(extracao, referencia, "CAMS McClear", tol_abs, tol_rel)

    avisos: list[str] = []
    if texto and _eh_corrompido(texto):
        avisos.append(
            "O arquivo do site parecia alterado por editor de planilha (o ponto "
            "decimal virou separador de milhar); os valores foram decodificados "
            "automaticamente (÷10.000). Para evitar, use o CSV original da SoDa."
        )
    alt_site = ler_altitude_site(caminho_csv_site)
    if (
        altitude_extracao is not None and alt_site is not None
        and altitude_extracao > 0 and abs(alt_site - altitude_extracao) > 1.0
    ):
        avisos.append(
            f"Altitude diferente: o site usou {alt_site:.0f} m e a extração usou "
            f"{altitude_extracao:.0f} m. Para bater 100%, re-extraia com "
            f"{alt_site:.0f} m (a mesma altitude do site)."
        )
    rel.avisos = avisos
    return rel


# ---------------------------------------------------------------------------
# Classificação e texto
# ---------------------------------------------------------------------------
_ORDEM_STATUS = ["Idêntico", "Diferenças pequenas", "Diferenças relevantes"]


def _status_componente(metrica: dict) -> str:
    if metrica["n_fora_tol"] == 0:
        return "Idêntico"
    if metrica["max_rel"] > LIMIAR_RELEVANTE:
        return "Diferenças relevantes"
    return "Diferenças pequenas"


def _pior(a: str, b: str) -> str:
    return a if _ORDEM_STATUS.index(a) >= _ORDEM_STATUS.index(b) else b


def _montar_resumo(rel: RelatorioFidelidade) -> str:
    linhas = [f"Conferência com {rel.fonte} — {rel.status}."]
    if rel.status == "Sem sobreposição":
        linhas.append(
            "Nenhum timestamp em comum entre a extração e o arquivo do site. "
            "Confira período e fuso (a ferramenta usa UTC)."
        )
        return "\n".join(linhas)
    linhas.append(
        f"Linhas comparadas: {rel.n_comum} "
        f"({rel.n_so_extracao} só na extração, {rel.n_so_referencia} só no site)."
    )
    for comp, m in rel.por_componente.items():
        linhas.append(
            f"{comp}: máx |Δ| {m['max_abs']:.2f} Wh/m² · máx rel "
            f"{m['max_rel'] * 100:.2f}% · {m['n_fora_tol']} fora de tolerância "
            f"({m['n_avaliado']} avaliados)."
        )
    if rel.componentes_so_extracao:
        linhas.append(
            "Componentes só na extração: "
            + ", ".join(rel.componentes_so_extracao) + "."
        )
    if rel.componentes_so_referencia:
        linhas.append(
            "Componentes só no site: "
            + ", ".join(rel.componentes_so_referencia) + "."
        )
    linhas.append(
        f"Tolerâncias: |Δ| ≤ {rel.tol_abs:g} Wh/m² ou ≤ {rel.tol_rel:.0%} relativo."
    )
    return "\n".join(linhas)


def formatar_relatorio_md(rel: RelatorioFidelidade) -> str:
    """Gera o relatório de fidelidade em Markdown (para salvar/baixar)."""
    md = [
        f"# Relatório de Fidelidade — {rel.fonte}",
        "",
        f"**Status:** {rel.status}",
        "",
        f"- Linhas comparadas: **{rel.n_comum}**",
        f"- Só na extração: {rel.n_so_extracao} · Só no site: {rel.n_so_referencia}",
        f"- Tolerâncias: |Δ| ≤ {rel.tol_abs:g} Wh/m² ou ≤ {rel.tol_rel:.0%} relativo",
        "",
    ]
    if rel.por_componente:
        md += [
            "| Componente | Avaliados | Máx \\|Δ\\| (Wh/m²) | Máx rel. | Fora da tol. |",
            "|---|---:|---:|---:|---:|",
        ]
        for comp, m in rel.por_componente.items():
            md.append(
                f"| {comp} | {m['n_avaliado']} | {m['max_abs']:.2f} | "
                f"{m['max_rel'] * 100:.2f}% | {m['n_fora_tol']} |"
            )
        md.append("")
    for a in rel.avisos:
        md.append(f"> ⚠️ {a}")
    if rel.avisos:
        md.append("")
    md.append("> " + rel.resumo_texto.replace("\n", "  \n> "))
    return "\n".join(md)
