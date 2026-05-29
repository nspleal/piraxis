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
        combinado["kt"] = _indice_claridade(ghi_real, ghi_ceu_limpo)

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


def _indice_claridade(ghi_real: pd.Series, ghi_ceu_limpo: pd.Series) -> pd.Series:
    """Calcula kt = GHI_real / GHI_ceu_limpo, tratando divisão por zero.

    À noite (céu limpo = 0 ou ausente) o resultado é NaN. O valor é mantido no
    intervalo plausível [0, ~1] sem recortar artificialmente (pode passar
    levemente de 1 por ruído de medição, o que é cientificamente esperado).
    """
    real = pd.to_numeric(ghi_real, errors="coerce")
    limpo = pd.to_numeric(ghi_ceu_limpo, errors="coerce")
    kt = real / limpo.where(limpo > 0)
    return kt


def _reamostrar_para_passo_comum(
    df_mcclear: pd.DataFrame,
    df_nasa: pd.DataFrame,
    passos: dict[str, str],
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Reamostra ambas as fontes para o passo comum mais GROSSO.

    Ex.: McClear em 1 min comparado com NASA horário -> tudo vira horário.
    A agregação usa a média dos valores dentro de cada intervalo (apropriado
    para irradiância média; para totais integrados a escolha seria a soma, mas
    como normalizamos para Wh/m² por passo, a média mantém a comparabilidade).
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
    """Reamostra um DataFrame padronizado para a frequência ``freq`` (média)."""
    if df.empty:
        return df
    indexado = df.set_index("timestamp").sort_index()
    agregado = indexado.resample(freq).mean(numeric_only=True)
    return agregado.reset_index()
