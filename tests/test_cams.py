"""
Testes do cliente CAMS McClear (sources/cams_mcclear.py).

Cobrem: parsing do CSV (ignorando linhas '#'), normalização de colunas,
comportamento do cache e ajuste do atraso de 2 dias. Nenhuma rede real.
"""

from __future__ import annotations

from datetime import date, timedelta

import pytest
import responses

from core.config import BOTUCATU
from sources.cams_mcclear import ENDPOINT_WPS, CamsMcClear

EMAIL_TESTE = "pesquisador@unesp.br"

# CSV simplificado no estilo McClear: comentários com '#', separador ';',
# coluna de tempo no formato "inicio/fim".
CSV_MCCLEAR = """\
# Coments do servico SoDa
# Latitude: -22.8867
Observation period;Clear sky GHI;Clear sky DNI;Clear sky DHI;Clear sky BHI
2024-01-01T10:00:00.0/2024-01-01T11:00:00.0;520.0;610.0;120.0;480.0
2024-01-01T11:00:00.0/2024-01-01T12:00:00.0;640.0;700.0;150.0;560.0
"""


@responses.activate
def test_parsing_csv_e_normalizacao_colunas():
    responses.add(responses.GET, ENDPOINT_WPS, body=CSV_MCCLEAR, status=200)

    fonte = CamsMcClear(EMAIL_TESTE)
    # Usa datas antigas para não esbarrar no ajuste de atraso.
    df = fonte.buscar(BOTUCATU, date(2024, 1, 1), date(2024, 1, 1), "PT01H")

    assert list(df.columns)[0] == "timestamp"
    for col in ("GHI", "DNI", "DHI", "BNI"):
        assert col in df.columns

    assert df["timestamp"].iloc[0].hour == 10
    assert df["GHI"].iloc[0] == 520.0
    assert df["BNI"].iloc[1] == 560.0  # "Clear sky BHI" -> BNI


def test_email_invalido_lanca_erro():
    fonte = CamsMcClear("")  # e-mail vazio
    with pytest.raises(ValueError, match="conta SoDa"):
        fonte.buscar(BOTUCATU, date(2024, 1, 1), date(2024, 1, 1), "PT01H")


@responses.activate
def test_ajuste_atraso_dois_dias(caplog):
    """data_fim futura deve ser ajustada para hoje - 2 dias, com aviso no log."""
    responses.add(responses.GET, ENDPOINT_WPS, body=CSV_MCCLEAR, status=200)

    hoje = date.today()
    fonte = CamsMcClear(EMAIL_TESTE)
    import logging

    with caplog.at_level(logging.WARNING):
        fonte.buscar(BOTUCATU, hoje - timedelta(days=5), hoje, "PT01H")

    assert any("Ajustando" in m or "ajustando" in m.lower() for m in caplog.messages)


@responses.activate
def test_cache_evita_segunda_chamada():
    responses.add(responses.GET, ENDPOINT_WPS, body=CSV_MCCLEAR, status=200)

    fonte = CamsMcClear(EMAIL_TESTE)
    args = (BOTUCATU, date(2024, 1, 1), date(2024, 1, 1), "PT01H")
    fonte.buscar(*args)
    fonte.buscar(*args)

    assert len(responses.calls) == 1
