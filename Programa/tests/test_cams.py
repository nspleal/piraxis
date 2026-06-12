"""
Testes do cliente CAMS McClear (sources/cams_mcclear.py).

Após a correção, a fonte usa ``pvlib.iotools.get_cams``. Os testes mockam essa
função (retornando um (DataFrame, dict) de exemplo) e verificam: a padronização
de colunas, o comportamento do cache e o ajuste do atraso de 2 dias. Nenhuma
chamada de rede real é feita.
"""

from __future__ import annotations

from datetime import date, timedelta

import pandas as pd
import pytest

from core.config import BOTUCATU
from sources.cams_mcclear import CamsMcClear

EMAIL_TESTE = "pesquisador@unesp.br"


def _resposta_pvlib() -> tuple[pd.DataFrame, dict]:
    """Imita o retorno de pvlib.iotools.get_cams para o McClear.

    DataFrame indexado por tempo, com nomes padronizados (map_variables=True):
    ghi_clear, dni_clear, dhi_clear, bhi_clear.
    """
    idx = pd.date_range("2024-01-01 10:00", periods=2, freq="h", tz="UTC")
    df = pd.DataFrame(
        {
            "ghi_clear": [520.0, 640.0],
            "dni_clear": [610.0, 700.0],
            "dhi_clear": [120.0, 150.0],
            "bhi_clear": [480.0, 560.0],
            "ghi_extra": [1000.0, 1010.0],  # coluna extra ignorada
        },
        index=idx,
    )
    return df, {"Time reference": "UT"}


@pytest.fixture
def mock_get_cams(monkeypatch):
    """Substitui pvlib.iotools.get_cams por uma versão que conta as chamadas."""
    chamadas = {"n": 0}

    def fake_get_cams(*args, **kwargs):
        chamadas["n"] += 1
        return _resposta_pvlib()

    import pvlib

    monkeypatch.setattr(pvlib.iotools, "get_cams", fake_get_cams)
    return chamadas


def test_parsing_e_normalizacao_colunas(mock_get_cams):
    fonte = CamsMcClear(EMAIL_TESTE)
    # Datas antigas para não esbarrar no ajuste de atraso.
    df = fonte.buscar(BOTUCATU, date(2024, 1, 1), date(2024, 1, 1), "PT01H")

    assert list(df.columns)[0] == "timestamp"
    for col in ("GHI", "DNI", "DHI", "BNI"):
        assert col in df.columns

    # Pedido de 1 dia em passo horário -> grade completa de 24 linhas.
    assert len(df) == 24

    # Timestamp sem fuso (tz removido); valores localizados pelo horário.
    por_hora = df.set_index("timestamp")
    assert por_hora.loc["2024-01-01 10:00", "GHI"] == 520.0
    assert por_hora.loc["2024-01-01 11:00", "BNI"] == 560.0  # bhi_clear -> BNI


def test_email_invalido_lanca_erro():
    fonte = CamsMcClear("")  # e-mail vazio
    with pytest.raises(ValueError, match="conta SoDa"):
        fonte.buscar(BOTUCATU, date(2024, 1, 1), date(2024, 1, 1), "PT01H")


def test_rejeita_data_recente(mock_get_cams):
    """data_fim mais recente que hoje-2 deve ser REJEITADA com mensagem amigável."""
    hoje = date.today()
    fonte = CamsMcClear(EMAIL_TESTE)
    with pytest.raises(ValueError, match="defasagem|disponível"):
        fonte.buscar(BOTUCATU, hoje - timedelta(days=5), hoje, "PT01H")
    # E não pode ter chamado a API (rejeição acontece antes).
    assert mock_get_cams["n"] == 0


def test_cache_evita_segunda_chamada(mock_get_cams):
    """A segunda extração idêntica deve ler do cache, sem nova chamada pvlib."""
    CamsMcClear.resetar_contador()
    fonte = CamsMcClear(EMAIL_TESTE)
    args = (BOTUCATU, date(2024, 1, 1), date(2024, 1, 1), "PT01H")
    fonte.buscar(*args)
    fonte.buscar(*args)  # deveria vir do cache

    assert mock_get_cams["n"] == 1
    # O contador interno de chamadas REAIS também deve registrar só uma.
    assert CamsMcClear.chamadas_reais_api == 1


def test_identifier_invalido_lanca_erro():
    """Só 'mcclear' e 'cams_radiation' são aceitos."""
    with pytest.raises(ValueError, match="identifier"):
        CamsMcClear(EMAIL_TESTE, identifier="foo")


def test_identifier_cams_radiation_aceito(mock_get_cams):
    """cams_radiation é aceito e usa cache separado do mcclear."""
    fonte = CamsMcClear(EMAIL_TESTE, identifier="cams_radiation")
    df = fonte.buscar(BOTUCATU, date(2024, 1, 1), date(2024, 1, 1), "PT01H")
    assert "GHI" in df.columns and len(df) == 24


def test_erro_amigavel_quando_pvlib_falha(monkeypatch):
    """Falha de autenticação vira RuntimeError claro sobre confirmar o e-mail."""

    def fake_falha(*args, **kwargs):
        raise ValueError("User ... is not registered")

    import pvlib

    monkeypatch.setattr(pvlib.iotools, "get_cams", fake_falha)

    fonte = CamsMcClear(EMAIL_TESTE)
    with pytest.raises(RuntimeError, match="soda-pro.com"):
        fonte.buscar(BOTUCATU, date(2024, 1, 1), date(2024, 1, 1), "PT01H")
