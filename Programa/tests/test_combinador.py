"""
Testes do combinador de fontes (core/combinador.py).

Cobrem: kt com limiar físico no denominador (crepúsculo vira NaN, não 5–50),
kt normal no meio do dia e reamostragem por SOMA (energia integra). Sem rede.
"""

from __future__ import annotations

import math

import pandas as pd

from core.combinador import combinar


def _fontes(ghi_limpo, ghi_real, freq="h"):
    ts = pd.date_range("2024-01-01 10:00", periods=len(ghi_limpo), freq=freq)
    mc = pd.DataFrame({"timestamp": ts, "GHI": ghi_limpo})
    nasa = pd.DataFrame({"timestamp": ts, "GHI": ghi_real})
    return {"CAMS McClear": mc, "NASA POWER": nasa}


def test_kt_no_meio_do_dia():
    res = _fontes([800.0, 1000.0], [400.0, 800.0])
    combinado = combinar(res, {"CAMS McClear": "PT01H", "NASA POWER": "PT01H"})
    assert list(combinado["kt"].round(2)) == [0.5, 0.8]


def test_kt_crepusculo_vira_nan_nao_explode():
    """Regressão (auditoria 2026-06-22): céu limpo minúsculo (sol rasante)
    fazia kt explodir para 5–50 e poluir médias/máximos. Abaixo do limiar
    físico (10 W/m² equivalente), kt agora é NaN."""
    # 2 Wh/m² de céu limpo às 10:00 (crepúsculo) e 800 ao meio-dia.
    res = _fontes([2.0, 800.0], [10.0, 400.0])
    combinado = combinar(res, {"CAMS McClear": "PT01H", "NASA POWER": "PT01H"})
    assert math.isnan(combinado["kt"].iloc[0])  # antes: kt = 5.0
    assert combinado["kt"].iloc[1] == 0.5


def test_kt_noite_continua_nan():
    res = _fontes([0.0, 800.0], [0.0, 400.0])
    combinado = combinar(res, {"CAMS McClear": "PT01H", "NASA POWER": "PT01H"})
    assert math.isnan(combinado["kt"].iloc[0])


def test_reamostragem_soma_energia():
    """Regressão (auditoria 2026-06-22): passos diferentes eram reamostrados
    por MÉDIA — energia integrada (Wh/m²) tem de ser SOMADA, senão o passo
    grosso fica ~N× menor e o kt quebra a escala."""
    ts_fino = pd.date_range("2024-01-01 10:00", periods=4, freq="15min")
    mc = pd.DataFrame({"timestamp": ts_fino, "GHI": [100.0, 100.0, 100.0, 100.0]})
    ts_grosso = pd.date_range("2024-01-01 10:00", periods=1, freq="h")
    nasa = pd.DataFrame({"timestamp": ts_grosso, "GHI": [300.0]})

    combinado = combinar(
        {"CAMS McClear": mc, "NASA POWER": nasa},
        {"CAMS McClear": "PT15M", "NASA POWER": "PT01H"},
    )
    linha = combinado.iloc[0]
    # 4 × 100 Wh/15min somam 400 Wh na hora (a média daria 100).
    assert linha["GHI_McClear"] == 400.0
    assert linha["kt"] == 0.75  # 300 / 400 — com média seria 3.0
