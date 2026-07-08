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

    # Pedimos 1 dia em passo horário -> a grade tem SEMPRE 24 linhas, mesmo
    # que a fonte só tenha trazido 3 horas (as demais ficam vazias/NaN).
    assert len(df) == 24
    assert df["timestamp"].iloc[0] == pd.Timestamp("2024-01-01 00:00:00")
    assert df["timestamp"].iloc[23] == pd.Timestamp("2024-01-01 23:00:00")

    # Localiza valores pelo horário (mais robusto que posição).
    por_hora = df.set_index("timestamp")
    assert por_hora.loc["2024-01-01 10:00", "GHI"] == 500.0
    assert por_hora.loc["2024-01-01 11:00", "DNI"] == 350.0

    # -999 virou NaN.
    assert math.isnan(por_hora.loc["2024-01-01 12:00", "GHI"])

    # Hora que a fonte não trouxe existe como linha vazia (NaN), não some.
    assert math.isnan(por_hora.loc["2024-01-01 00:00", "GHI"])


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
def test_grade_completa_quando_fonte_traz_dados_parciais():
    """Pedir vários dias deve render a grade horária completa, sem 'sumir' horas.

    Reproduz o problema relatado: a fonte devolve menos horas que o período, mas
    a ferramenta deve entregar exatamente as horas do intervalo solicitado.
    """
    # A fonte traz só 2 horas de um período de 2 dias (48 horas esperadas).
    payload = {
        "properties": {
            "parameter": {
                "ALLSKY_SFC_SW_DWN": {"2024010110": 500.0, "2024010111": 600.0},
                "ALLSKY_SFC_SW_DNI": {"2024010110": 300.0, "2024010111": 350.0},
                "ALLSKY_SFC_SW_DIFF": {"2024010110": 200.0, "2024010111": 250.0},
                "CLRSKY_SFC_SW_DWN": {"2024010110": 700.0, "2024010111": 800.0},
            }
        }
    }
    responses.add(responses.GET, ENDPOINT_HORARIO, json=payload, status=200)

    fonte = NasaPower()
    df = fonte.buscar(BOTUCATU, date(2024, 1, 1), date(2024, 1, 2), "PT01H")

    # 2 dias * 24 h = 48 linhas, do primeiro ao último instante do período.
    assert len(df) == 48
    assert df["timestamp"].iloc[0] == pd.Timestamp("2024-01-01 00:00:00")
    assert df["timestamp"].iloc[-1] == pd.Timestamp("2024-01-02 23:00:00")


@responses.activate
def test_requisicao_pede_fuso_utc():
    """A requisição DEVE pedir time-standard=UTC para alinhar com o McClear.

    Regressão: por padrão a NASA POWER entrega LST (hora solar local), o que
    desalinhava as fontes em ~3 h em Botucatu (kt sem sentido, picos em horas
    erradas). O cliente precisa fixar UTC explicitamente.
    """
    responses.add(
        responses.GET, ENDPOINT_HORARIO, json=_payload_horario(), status=200
    )

    fonte = NasaPower()
    fonte.buscar(BOTUCATU, date(2024, 1, 1), date(2024, 1, 1), "PT01H")

    assert len(responses.calls) == 1
    url = responses.calls[0].request.url
    assert "time-standard=UTC" in url, (
        f"A requisição não fixou o fuso UTC; URL gerada: {url}"
    )


@responses.activate
def test_resposta_crua_capturada_para_auditoria():
    """O JSON cru da NASA POWER fica disponível para a auditoria."""
    responses.add(
        responses.GET, ENDPOINT_HORARIO, json=_payload_horario(), status=200
    )
    fonte = NasaPower()
    fonte.buscar(BOTUCATU, date(2024, 1, 1), date(2024, 1, 1), "PT01H")
    assert fonte.resposta_crua is not None
    assert "properties" in fonte.resposta_crua


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


def test_rejeita_passos_nao_suportados():
    """Mensal e sub-horário são REJEITADOS com erro claro (nunca rebaixados).

    Regressão da auditoria 2026-06-22: 'P01M' caía no endpoint diário e o
    reindex mensal mantinha só o valor do dia 1º rotulado como o mês inteiro;
    '1 min'/'15 min' caíam para horário e viravam série ~98% vazia.
    """
    import pytest

    fonte = NasaPower()
    for passo in ("P01M", "PT01M", "PT15M"):
        with pytest.raises(ValueError, match="NASA POWER"):
            fonte.buscar(BOTUCATU, date(2024, 1, 1), date(2024, 1, 31), passo)


def test_passo_mensal_fora_da_interface():
    """'1 mês' saiu das opções da UI até o suporte mensal ser reprojetado."""
    from core.config import PASSOS_TEMPORAIS

    assert "P01M" not in PASSOS_TEMPORAIS.values()
    assert set(PASSOS_TEMPORAIS.values()) == {"PT01M", "PT15M", "PT01H", "P01D"}


def test_rejeita_datas_futuras_e_invertidas():
    """Regressão (auditoria 2026-06-22): datas recentes/futuras voltavam como
    -999 -> tudo NaN, sem erro ("extração vazia"). Agora rejeita com mensagem
    clara, como o CAMS já fazia."""
    import pytest
    from datetime import timedelta

    fonte = NasaPower()
    hoje = date.today()
    with pytest.raises(ValueError, match="ainda não está"):
        fonte.buscar(BOTUCATU, hoje - timedelta(days=1), hoje, "PT01H")
    with pytest.raises(ValueError, match="início não pode"):
        fonte.buscar(BOTUCATU, date(2024, 1, 5), date(2024, 1, 1), "PT01H")


@responses.activate
def test_cache_pode_ser_desligado(monkeypatch):
    """Regressão (auditoria 2026-06-22): CACHE_HABILITADO era configuração
    morta. Com false, a mesma consulta volta a bater na API (e nada é salvo)."""
    responses.add(
        responses.GET, ENDPOINT_HORARIO, json=_payload_horario(), status=200
    )
    responses.add(
        responses.GET, ENDPOINT_HORARIO, json=_payload_horario(), status=200
    )
    monkeypatch.setenv("CACHE_HABILITADO", "false")

    fonte = NasaPower()
    args = (BOTUCATU, date(2024, 1, 1), date(2024, 1, 1), "PT01H")
    fonte.buscar(*args)
    fonte.buscar(*args)  # sem cache -> segunda chamada de rede

    assert len(responses.calls) == 2


@responses.activate
def test_resposta_crua_disponivel_em_cache_hit():
    """Regressão (fila da auditoria): em cache hit a resposta_crua ficava
    None e o download de auditoria vinha silenciosamente vazio. Agora o cru
    é persistido junto do cache e recuperado."""
    responses.add(
        responses.GET, ENDPOINT_HORARIO, json=_payload_horario(), status=200
    )
    args = (BOTUCATU, date(2024, 1, 1), date(2024, 1, 1), "PT01H")

    NasaPower().buscar(*args)          # chamada real: grava dado + cru
    fonte2 = NasaPower()
    fonte2.buscar(*args)               # cache hit (sem rede)

    assert len(responses.calls) == 1   # só a primeira bateu na API
    assert fonte2.resposta_crua is not None
    assert "properties" in fonte2.resposta_crua


@responses.activate
def test_erros_http_tem_mensagens_distintas():
    """Regressão (fila da auditoria): todo erro HTTP virava "verifique sua
    conexão" — enganoso para 429 (limite) e 4xx (consulta inválida)."""
    import pytest

    args = (BOTUCATU, date(2024, 2, 1), date(2024, 2, 1), "PT01H")

    responses.add(responses.GET, ENDPOINT_HORARIO, status=429)
    with pytest.raises(RuntimeError, match="limitou temporariamente"):
        NasaPower().buscar(*args)

    responses.reset()
    responses.add(responses.GET, ENDPOINT_HORARIO, status=422)
    with pytest.raises(RuntimeError, match="recusou a consulta"):
        NasaPower().buscar(*args)

    responses.reset()
    responses.add(responses.GET, ENDPOINT_HORARIO, status=503)
    with pytest.raises(RuntimeError, match="indisponível"):
        NasaPower().buscar(*args)


def test_limpar_cache_remove_dados_e_cru(tmp_path, monkeypatch):
    from sources import base

    monkeypatch.setattr(base, "CACHE_DIR", tmp_path)
    (tmp_path / "abc.csv").write_text("x")
    (tmp_path / "abc.cru.json").write_text("{}")
    assert base.tamanho_cache_bytes() > 0
    assert base.limpar_cache() == 2
    assert base.tamanho_cache_bytes() == 0
