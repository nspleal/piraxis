"""
core/reprodutibilidade.py
=========================

Gera os artefatos de reprodutibilidade e as citações de uma extração:

  - PROVENIÊNCIA (dicionário -> JSON): registro exato da extração (ferramenta,
    data, local, período, fontes, componentes, ambiente/versões).
  - TEXTO DE METODOLOGIA (PT + EN): pronto para colar na seção de metodologia
    de um artigo, preenchido com os dados reais da extração.
  - CITAÇÕES E AGRADECIMENTOS: textos verificados (CAMS McClear, NASA POWER,
    pvlib), incluindo apenas as fontes efetivamente usadas.

IMPORTANTE: o e-mail da conta SoDa NÃO entra na proveniência nem em qualquer
saída. Ele é uma credencial pessoal e cientificamente irrelevante — o dado
baixado é idêntico independentemente da conta usada. Por isso ele é
deliberadamente omitido aqui.
"""

from __future__ import annotations

import json
import sys
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path

import pandas as pd

NOME_FERRAMENTA = "Extrator de Radiação Solar (UNESP)"
VERSAO_FERRAMENTA = "1.0"

# ---------------------------------------------------------------------------
# Textos de citação VERIFICADOS (não editar sem conferência bibliográfica)
# ---------------------------------------------------------------------------
CITACAO_MCCLEAR_PRINCIPAL = (
    "Lefèvre, M., Oumbe, A., Blanc, P., Espinar, B., Gschwind, B., Qu, Z., "
    "Wald, L., Schroedter-Homscheidt, M., Hoyer-Klick, C., Arola, A., "
    "Benedetti, A., Kaiser, J. W., and Morcrette, J.-J.: McClear: a new model "
    "estimating downwelling solar radiation at ground level in clear-sky "
    "conditions, Atmospheric Measurement Techniques, 6, 2403–2418, "
    "doi:10.5194/amt-6-2403-2013, 2013."
)
CITACAO_MCCLEAR_V3 = (
    "Gschwind, B., Wald, L., Blanc, P., Lefèvre, M., Schroedter-Homscheidt, M., "
    "Arola, A.: Improving the McClear model estimating the downwelling solar "
    "radiation at ground level in cloud-free conditions – McClear-V3, "
    "Meteorologische Zeitschrift, 28(2), 147–163, doi:10.1127/metz/2019/0946, "
    "2019."
)
ATRIBUICAO_COPERNICUS = (
    "Contains modified Copernicus Atmosphere Monitoring Service information [ANO]."
)
AGRADECIMENTO_SODA = (
    "Os autores agradecem ao serviço SoDa (www.soda-pro.com) pela "
    "disponibilização do acesso ao modelo CAMS McClear."
)
AGRADECIMENTO_NASA_POWER = (
    "These data were obtained from the NASA Langley Research Center POWER "
    "Project funded through the NASA Earth Science Directorate Applied Science "
    "Program."
)
CITACAO_PVLIB = (
    "Holmgren, W. F., Hansen, C. W., Mikofski, M. A.: pvlib python: a python "
    "package for modeling solar energy systems, Journal of Open Source "
    "Software, 3(29), 884, doi:10.21105/joss.00884, 2018."
)


@dataclass
class Reprodutibilidade:
    """Pacote com proveniência, metodologia (PT/EN), citações e Markdown."""

    proveniencia: dict
    metodologia_pt: str
    metodologia_en: str
    citacoes_md: str
    markdown: str


# ---------------------------------------------------------------------------
# Detecção das fontes usadas
# ---------------------------------------------------------------------------
def _usou(fontes: list[str], chave: str) -> bool:
    return any(chave.lower() in str(f).lower() for f in fontes)


def _info_fontes(fontes: list[str]) -> list[dict]:
    """Descreve cada fonte usada (sem credenciais)."""
    info: list[dict] = []
    if _usou(fontes, "mcclear") or _usou(fontes, "cams"):
        info.append({
            "nome": "CAMS McClear",
            "tipo": "céu limpo (clear-sky)",
            "servico": "SoDa / Copernicus CAMS",
            "endpoint": "api.soda-solardata.com",
            "identifier": "mcclear",
            "atraso_dados": "~2 dias",
        })
    if _usou(fontes, "nasa") or _usou(fontes, "power"):
        info.append({
            "nome": "NASA POWER",
            "tipo": "céu real (all-sky)",
            "servico": "NASA Langley Research Center — POWER Project",
            "endpoint": "power.larc.nasa.gov",
            "identifier": None,
            "atraso_dados": "alguns dias",
        })
    return info


# ---------------------------------------------------------------------------
# Proveniência
# ---------------------------------------------------------------------------
def montar_proveniencia(
    local,
    data_inicio: date,
    data_fim: date,
    passo_codigo: str,
    passo_rotulo: str,
    fontes: list[str],
    componentes: list[str],
    unidade: str = "Wh/m²",
) -> dict:
    """Monta o dicionário de proveniência (registro exato da extração)."""
    try:
        import pvlib
        versao_pvlib = pvlib.__version__
    except Exception:  # pragma: no cover
        versao_pvlib = "desconhecida"

    # NOTA: o e-mail do SoDa é OMITIDO de propósito (credencial pessoal,
    # irrelevante para a ciência — o dado é o mesmo independente da conta).
    return {
        "ferramenta": NOME_FERRAMENTA,
        "versao_ferramenta": VERSAO_FERRAMENTA,
        "data_extracao": datetime.now().astimezone().isoformat(),
        "local": {
            "nome": local.nome,
            "latitude": local.latitude,
            "longitude": local.longitude,
            "altitude_m": local.altitude,
        },
        "periodo": {
            "inicio": str(data_inicio),
            "fim": str(data_fim),
            "passo_codigo": passo_codigo,
            "passo_rotulo": passo_rotulo,
        },
        "fontes": _info_fontes(fontes),
        "componentes": list(componentes),
        "unidade": unidade,
        "ambiente": {
            "python": f"{sys.version_info.major}.{sys.version_info.minor}."
                      f"{sys.version_info.micro}",
            "pvlib": versao_pvlib,
            "pandas": pd.__version__,
        },
    }


def salvar_proveniencia(proveniencia: dict, caminho: str | Path) -> Path:
    """Salva a proveniência como JSON legível."""
    caminho = Path(caminho)
    caminho.parent.mkdir(parents=True, exist_ok=True)
    caminho.write_text(
        json.dumps(proveniencia, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return caminho


# ---------------------------------------------------------------------------
# Metodologia (PT + EN)
# ---------------------------------------------------------------------------
def _fmt(valor: float, casas: int, virgula: bool) -> str:
    s = f"{valor:.{casas}f}"
    return s.replace(".", ",") if virgula else s


def gerar_metodologia(
    local, data_inicio: date, data_fim: date, passo_rotulo: str, fontes: list[str]
) -> tuple[str, str]:
    """Gera os parágrafos de metodologia em português e inglês."""
    usou_mcclear = _usou(fontes, "mcclear") or _usou(fontes, "cams")
    usou_nasa = _usou(fontes, "nasa") or _usou(fontes, "power")

    # ----- Português -----
    pt = (
        f"Os dados de radiação solar foram obtidos para o município de "
        f"{local.nome} (latitude {_fmt(local.latitude, 4, True)}°, longitude "
        f"{_fmt(local.longitude, 4, True)}°, altitude {_fmt(local.altitude, 0, True)} m), "
        f"no período de {data_inicio:%d/%m/%Y} a {data_fim:%d/%m/%Y}, com "
        f"resolução temporal de {passo_rotulo}. "
    )
    if usou_mcclear:
        pt += (
            "A irradiância em condições de céu limpo foi estimada pelo modelo "
            "CAMS McClear (Lefèvre et al., 2013; Gschwind et al., 2019), "
            "acessado via serviço SoDa. "
        )
    if usou_nasa:
        pt += "A irradiância em céu real foi obtida da base NASA POWER. "
    pt += (
        "O processamento e o cálculo da geometria solar utilizaram a biblioteca "
        "pvlib (Holmgren et al., 2018)."
    )

    # ----- Inglês -----
    en = (
        f"Solar radiation data were obtained for the municipality of "
        f"{local.nome}, Brazil (latitude {_fmt(local.latitude, 4, False)}°, "
        f"longitude {_fmt(local.longitude, 4, False)}°, altitude "
        f"{_fmt(local.altitude, 0, False)} m), from {data_inicio:%Y-%m-%d} to "
        f"{data_fim:%Y-%m-%d}, at a temporal resolution of {passo_rotulo}. "
    )
    if usou_mcclear:
        en += (
            "Clear-sky irradiance was estimated using the CAMS McClear model "
            "(Lefèvre et al., 2013; Gschwind et al., 2019), accessed through the "
            "SoDa service. "
        )
    if usou_nasa:
        en += "All-sky (real) irradiance was retrieved from the NASA POWER database. "
    en += (
        "Data processing and solar geometry computations were performed with the "
        "pvlib python library (Holmgren et al., 2018)."
    )
    return pt, en


# ---------------------------------------------------------------------------
# Citações e agradecimentos
# ---------------------------------------------------------------------------
def montar_citacoes(fontes: list[str], ano_dados: str) -> str:
    """Monta o bloco Markdown de citações/agradecimentos das fontes usadas."""
    usou_mcclear = _usou(fontes, "mcclear") or _usou(fontes, "cams")
    usou_nasa = _usou(fontes, "nasa") or _usou(fontes, "power")

    ref: list[str] = ["## Referências / Citações", ""]
    agr: list[str] = ["## Agradecimentos / Acknowledgments", ""]

    if usou_mcclear:
        ref += [
            "**CAMS McClear — referência principal:**",
            f"> {CITACAO_MCCLEAR_PRINCIPAL}",
            "",
            "**CAMS McClear — versão atual do modelo (McClear-V3):**",
            f"> {CITACAO_MCCLEAR_V3}",
            "",
            "**Atribuição obrigatória do Copernicus:**",
            f"> {ATRIBUICAO_COPERNICUS.replace('[ANO]', ano_dados)}",
            "",
        ]
        agr += [f"- {AGRADECIMENTO_SODA}", ""]
    if usou_nasa:
        ref += [
            "**NASA POWER:**",
            "> NASA POWER Project — Prediction Of Worldwide Energy Resources, "
            "NASA Langley Research Center.",
            "",
        ]
        agr += [f"- {AGRADECIMENTO_NASA_POWER}", ""]

    # pvlib é sempre usada (processamento/geometria solar).
    ref += ["**pvlib (processamento e geometria solar):**", f"> {CITACAO_PVLIB}", ""]

    return "\n".join(ref + agr).rstrip() + "\n"


# ---------------------------------------------------------------------------
# Documento Markdown completo
# ---------------------------------------------------------------------------
def gerar_reprodutibilidade(
    local,
    data_inicio: date,
    data_fim: date,
    passo_codigo: str,
    passo_rotulo: str,
    fontes: list[str],
    componentes: list[str],
    unidade: str = "Wh/m²",
) -> Reprodutibilidade:
    """Constrói o pacote completo de reprodutibilidade."""
    proveniencia = montar_proveniencia(
        local, data_inicio, data_fim, passo_codigo, passo_rotulo, fontes,
        componentes, unidade,
    )
    metodologia_pt, metodologia_en = gerar_metodologia(
        local, data_inicio, data_fim, passo_rotulo, fontes
    )
    ano = (
        str(data_inicio.year)
        if data_inicio.year == data_fim.year
        else f"{data_inicio.year}–{data_fim.year}"
    )
    citacoes_md = montar_citacoes(fontes, ano)

    markdown = "\n".join([
        f"# Reprodutibilidade — {local.nome}",
        "",
        f"*Gerado por {NOME_FERRAMENTA} v{VERSAO_FERRAMENTA} em "
        f"{datetime.now():%d/%m/%Y %H:%M}.*",
        "",
        "## Metodologia (PT)",
        "",
        metodologia_pt,
        "",
        "## Methodology (EN)",
        "",
        metodologia_en,
        "",
        citacoes_md,
    ])

    return Reprodutibilidade(
        proveniencia=proveniencia,
        metodologia_pt=metodologia_pt,
        metodologia_en=metodologia_en,
        citacoes_md=citacoes_md,
        markdown=markdown,
    )


def salvar_artefatos(
    repro: Reprodutibilidade, nome_base: str, pasta: str | Path
) -> tuple[Path, Path]:
    """Salva ``<nome_base>_reprodutibilidade.md`` e ``_proveniencia.json``."""
    pasta = Path(pasta)
    pasta.mkdir(parents=True, exist_ok=True)
    caminho_md = pasta / f"{nome_base}_reprodutibilidade.md"
    caminho_json = pasta / f"{nome_base}_proveniencia.json"
    caminho_md.write_text(repro.markdown, encoding="utf-8")
    salvar_proveniencia(repro.proveniencia, caminho_json)
    return caminho_md, caminho_json
