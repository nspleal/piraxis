"""
core/combinador.py
==================

Lógica de combinação das fontes de radiação (McClear + NASA POWER) num único
DataFrame alinhado por ``timestamp``.

Conceito científico:
  - McClear  = envelope teórico (radiação em céu limpo).
  - NASA POWER = realidade (radiação com nuvens).
  - índice de claridade kt = GHI_real / GHI_ceu_limpo (entre 0 e 1).

Quando ambas as fontes são escolhidas, as colunas de componentes recebem
sufixo da fonte (ex.: GHI_McClear, GHI_NASA) e calculamos kt. Se as fontes
tiverem passos temporais diferentes, reamostramos para o passo comum mais
grosso (documentado em ``_reamostrar_para_passo_comum``).
"""

from __future__ import annotations

import logging

import pandas as pd

logger = logging.getLogger(__name__)

# Sufixos de fonte usados nas colunas combinadas.
SUFIXO_MCCLEAR = "McClear"
SUFIXO_NASA = "NASA"

# Frequências pandas correspondentes a cada passo temporal ISO, da mais fina
# para a mais grossa. Usado para escolher o passo comum mais grosso.
_FREQ_POR_PASSO: dict[str, str] = {
    "PT01M": "1min",
    "PT15M": "15min",
    "PT01H": "1h",
    "P01D": "1D",
    "P01M": "1MS",
}
# Ordem de granularidade (índice maior = mais grosso).
_ORDEM_PASSOS = ["PT01M", "PT15M", "PT01H", "P01D", "P01M"]

# Duração de cada passo em horas (usada para escalar o limiar do kt).
_HORAS_POR_PASSO: dict[str, float] = {
    "PT01M": 1 / 60,
    "PT15M": 0.25,
    "PT01H": 1.0,
    "P01D": 24.0,
    "P01M": 720.0,
}

# Limiar mínimo de irradiância de céu limpo para calcular o kt, em W/m².
# Abaixo disso (amanhecer/anoitecer, sol rasante) a divisão amplifica ruído e
# descasamento de modelo: kt "explode" para 5–50 e polui médias e máximos.
LIMIAR_KT_WM2 = 10.0


def combinar(
    resultados: dict[str, pd.DataFrame],
    passos: dict[str, str] | None = None,
) -> pd.DataFrame:
    """Combina os DataFrames das fontes selecionadas, alinhados por timestamp.

    Parâmetros
    ----------
    resultados:
        Mapa nome_da_fonte -> DataFrame padronizado. Ex.: {"CAMS McClear": df1,
        "NASA POWER": df2}. Pode conter uma ou duas fontes.
    passos:
        Mapa opcional nome_da_fonte -> código do passo temporal ISO (ex.:
        "PT01H"). Usado para reamostrar quando as fontes têm passos diferentes.

    Retorna
    -------
    pd.DataFrame
        Quando há uma única fonte: o próprio DataFrame padronizado.
        Quando há duas fontes: colunas sufixadas por fonte + coluna kt.
    """
    if not resultados:
        return pd.DataFrame(columns=["timestamp"])

    if len(resultados) == 1:
        # Uma única fonte: devolve como está (já padronizado).
        (df,) = resultados.values()
        return df.copy()

    # Duas fontes: separa McClear (céu limpo) e NASA (real).
    df_mcclear = _localizar(resultados, "McClear")
    df_nasa = _localizar(resultados, "NASA")

    # Reamostra ambas para o passo comum mais grosso, se necessário.
    if passos:
        df_mcclear, df_nasa = _reamostrar_para_passo_comum(
            df_mcclear, df_nasa, passos
        )

    # Renomeia componentes com sufixo da fonte (preserva timestamp).
    esq = _sufixar(df_mcclear, SUFIXO_MCCLEAR)
    dir_ = _sufixar(df_nasa, SUFIXO_NASA)

    combinado = pd.merge(esq, dir_, on="timestamp", how="outer").sort_values(
        "timestamp"
    )
    combinado = combinado.reset_index(drop=True)

    # Índice de claridade kt = GHI real / GHI céu limpo.
    # GHI céu limpo: prefere a coluna do McClear; cai para GHI_ceu_limpo (NASA).
    ghi_real = combinado.get(f"GHI_{SUFIXO_NASA}")
    ghi_ceu_limpo = combinado.get(f"GHI_{SUFIXO_MCCLEAR}")
    if ghi_ceu_limpo is None:
        ghi_ceu_limpo = combinado.get(f"GHI_ceu_limpo_{SUFIXO_NASA}")

    if ghi_real is not None and ghi_ceu_limpo is not None:
        passo_kt = None
        if passos:
            candidatos = [p for p in passos.values() if p in _ORDEM_PASSOS]
            if candidatos:
                passo_kt = max(candidatos, key=_ORDEM_PASSOS.index)
        combinado["kt"] = _indice_claridade(ghi_real, ghi_ceu_limpo, passo_kt)

    return combinado


# ---------------------------------------------------------------------------
def _localizar(resultados: dict[str, pd.DataFrame], chave: str) -> pd.DataFrame:
    """Encontra o DataFrame cuja fonte contém ``chave`` no nome."""
    for nome, df in resultados.items():
        if chave.lower() in nome.lower():
            return df
    raise KeyError(f"Nenhuma fonte com '{chave}' no nome em {list(resultados)}.")


def _sufixar(df: pd.DataFrame, sufixo: str) -> pd.DataFrame:
    """Adiciona sufixo de fonte a todas as colunas exceto timestamp."""
    renomear = {c: f"{c}_{sufixo}" for c in df.columns if c != "timestamp"}
    return df.rename(columns=renomear)


def _indice_claridade(
    ghi_real: pd.Series,
    ghi_ceu_limpo: pd.Series,
    passo_temporal: str | None = None,
) -> pd.Series:
    """Calcula kt = GHI_real / GHI_ceu_limpo com limiar físico no denominador.

    À noite o resultado é NaN. No amanhecer/anoitecer o céu limpo é positivo
    porém minúsculo (poucos Wh/m²) e a divisão amplifica ruído/descasamento de
    modelo — kt iria a 5–50 e poluiria médias e máximos. Por isso o kt só é
    calculado onde o céu limpo ≥ ``LIMIAR_KT_WM2`` (equivalente em Wh/m² para
    a duração do passo); fora disso é NaN. Acima do limiar, valores levemente
    maiores que 1 são preservados (realce por nuvens é fisicamente esperado).
    """
    real = pd.to_numeric(ghi_real, errors="coerce")
    limpo = pd.to_numeric(ghi_ceu_limpo, errors="coerce")
    horas = _HORAS_POR_PASSO.get(passo_temporal or "PT01H", 1.0)
    limiar_wh = LIMIAR_KT_WM2 * horas
    kt = real / limpo.where(limpo >= limiar_wh)
    return kt


def _reamostrar_para_passo_comum(
    df_mcclear: pd.DataFrame,
    df_nasa: pd.DataFrame,
    passos: dict[str, str],
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Reamostra ambas as fontes para o passo comum mais GROSSO.

    Ex.: McClear em 1 min comparado com NASA horário -> tudo vira horário.
    A agregação usa a SOMA dos valores dentro de cada intervalo: os dados são
    energia integrada por passo (Wh/m²), e energia se soma — a média deixaria
    o passo grosso ~N× menor que o real (ex.: dia = média horária ≈ total/24)
    e quebraria a escala do kt entre fontes de passos diferentes.
    """
    passo_mc = _passo_da_fonte(passos, "McClear")
    passo_nasa = _passo_da_fonte(passos, "NASA")
    if passo_mc is None or passo_nasa is None or passo_mc == passo_nasa:
        return df_mcclear, df_nasa

    # Escolhe o mais grosso pela ordem de granularidade.
    idx_mc = _ORDEM_PASSOS.index(passo_mc)
    idx_nasa = _ORDEM_PASSOS.index(passo_nasa)
    passo_comum = passo_mc if idx_mc >= idx_nasa else passo_nasa
    freq = _FREQ_POR_PASSO[passo_comum]

    logger.info(
        "Passos temporais diferentes (%s vs %s). Reamostrando ambos para %s.",
        passo_mc,
        passo_nasa,
        passo_comum,
    )
    return _reamostrar(df_mcclear, freq), _reamostrar(df_nasa, freq)


def _passo_da_fonte(passos: dict[str, str], chave: str) -> str | None:
    for nome, passo in passos.items():
        if chave.lower() in nome.lower():
            return passo
    return None


def _reamostrar(df: pd.DataFrame, freq: str) -> pd.DataFrame:
    """Reamostra um DataFrame padronizado para ``freq`` somando a energia.

    ``min_count=1`` preserva o "não inventar zeros": um intervalo sem nenhum
    dado vira NaN (a soma padrão do pandas transformaria vazio em 0.0).
    """
    if df.empty:
        return df
    indexado = df.set_index("timestamp").sort_index()
    numericas = indexado.select_dtypes("number")
    agregado = numericas.resample(freq).sum(min_count=1)
    return agregado.reset_index()
