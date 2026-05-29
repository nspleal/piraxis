"""
Testes do cliente NASA POWER (sources/nasa_power.py).

Cobrem: parsing do JSON, conversão de -999 em NaN e normalização de unidades.
Nenhuma chamada de rede real — usamos a lib ``responses`` para mockar a API.
"""

from __future__ import annotations

import math
from datetime import date

import pandas as pd
import responses

from core.config import BOTUCATU
from sources.nasa_power import ENDPOINT_HORARIO, NasaPower


def _payload_horario() -> dict:
    """JSON mínimo no formato da NASA POWER (passo horário)."""
    return {
        "properties": {
            "parameter": {
                "ALLSKY_SFC_SW_DWN": {
                    "2024010110": 500.0,
                    "2024010111": 600.0,
                    "2024010112": -999.0,  # ausente
                },
                "ALLSKY_SFC_SW_DNI": {
                    "2024010110": 300.0,
                    "2024010111": 350.0,
                    "2024010112": 400.0,
                },
                "ALLSKY_SFC_SW_DIFF": {
                    "2024010110": 200.0,
                    "2024010111": 250.0,
                    "2024010112": 100.0,
                },
                "CLRSKY_SFC_SW_DWN": {
                    "2024010110": 700.0,
                    "2024010111": 800.0,
                    "2024010112": 900.0,
                },
            }
        }
    }


@responses.activate
def test_parsing_e_normalizacao_horaria():
    responses.add(
        responses.GET,
        ENDPOINT_HORARIO,
        json=_payload_horario(),
        status=200,
    )

    fonte = NasaPower()
    df = fonte.buscar(BOTUCATU, date(2024, 1, 1), date(2024, 1, 1), "PT01H")

    # Colunas padronizadas presentes.
    assert list(df.columns)[0] == "timestamp"
    for col in ("GHI", "DNI", "DHI", "GHI_ceu_limpo"):
        assert col in df.columns

    # Timestamp convertido corretamente.
    assert df["timestamp"].iloc[0] == pd.Timestamp("2024-01-01 10:00:00")

    # -999 virou NaN.
    assert math.isnan(df["GHI"].iloc[2])

    # Horário: sem conversão de unidade (valores preservados).
    assert df["GHI"].iloc[0] == 500.0
    assert df["DNI"].iloc[1] == 350.0


@responses.activate
def test_conversao_unidade_diaria():
    """No passo diário, kWh/m²/dia deve ser multiplicado por 1000 -> Wh/m²."""
    from sources.nasa_power import ENDPOINT_DIARIO

    payload = {
        "properties": {
            "parameter": {
                "ALLSKY_SFC_SW_DWN": {"20240101": 5.0},
                "ALLSKY_SFC_SW_DNI": {"20240101": 3.0},
                "ALLSKY_SFC_SW_DIFF": {"20240101": 2.0},
                "CLRSKY_SFC_SW_DWN": {"20240101": 7.0},
            }
        }
    }
    responses.add(responses.GET, ENDPOINT_DIARIO, json=payload, status=200)

    fonte = NasaPower()
    df = fonte.buscar(BOTUCATU, date(2024, 1, 1), date(2024, 1, 1), "P01D")

    assert df["GHI"].iloc[0] == 5000.0
    assert df["GHI_ceu_limpo"].iloc[0] == 7000.0


@responses.activate
def test_cache_evita_segunda_chamada():
    """A segunda extração idêntica deve ler do cache, sem nova chamada HTTP."""
    responses.add(
        responses.GET, ENDPOINT_HORARIO, json=_payload_horario(), status=200
    )

    fonte = NasaPower()
    args = (BOTUCATU, date(2024, 1, 1), date(2024, 1, 1), "PT01H")
    fonte.buscar(*args)
    fonte.buscar(*args)  # deveria vir do cache

    # Apenas uma chamada de rede foi registrada.
    assert len(responses.calls) == 1
