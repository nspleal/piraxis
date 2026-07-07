"""
Testes do controle de qualidade (core/qualidade.py).

Usa DataFrames sintéticos e a posição solar REAL do pvlib com timestamps fixos
(sem rede). Cobre: lacunas/completude, negativos, noturno, envelope, fechamento
(não aplicável em D/M e avaliado em PT15M) e concordância entre fontes.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import pvlib

from core.config import BOTUCATU
from core.qualidade import analisar_qualidade


def _zenite_meio(ts: pd.DatetimeIndex, offset_min: float) -> np.ndarray:
    """Zênite aparente no ponto médio (mesmo cálculo do módulo)."""
    meio = pd.DatetimeIndex(ts + pd.Timedelta(minutes=offset_min)).tz_localize("UTC")
    pos = pvlib.solarposition.get_solarposition(
        meio, BOTUCATU.latitude, BOTUCATU.longitude, altitude=BOTUCATU.altitude
    )
    return pos["apparent_zenith"].to_numpy()


def test_lacunas_e_completude():
    ts = pd.date_range("2026-06-07 00:00", periods=48, freq="h")
    ghi = np.full(48, 100.0)
    ghi[10:16] = np.nan  # 6 horas sem dado -> 1 lacuna
    df = pd.DataFrame({"timestamp": ts, "GHI": ghi})
    rel = analisar_qualidade(df, BOTUCATU, "PT01H", ["CAMS McClear"])

    assert rel.total_esperado == 48
    assert rel.total_presente == 42
    assert abs(rel.completude_pct - 87.5) < 0.1
    assert len(rel.lacunas) == 1
    assert rel.lacunas[0]["n_passos"] == 6
    assert rel.nan_por_coluna["GHI"] == 6


def test_negativos_sinalizados():
    ts = pd.date_range("2026-06-07 00:00", periods=10, freq="h")
    ghi = np.full(10, 50.0)
    ghi[3] = -5.0   # negativo claro
    ghi[4] = -0.5   # dentro do ruído (não conta)
    df = pd.DataFrame({"timestamp": ts, "GHI": ghi})
    rel = analisar_qualidade(df, BOTUCATU, "PT01H", ["CAMS McClear"])

    assert rel.n_negativos == 1
    assert bool(rel.flags_por_linha["flag_negativo"].iloc[3]) is True
    assert bool(rel.flags_por_linha["flag_negativo"].iloc[4]) is False


def test_noturno_sinalizado():
    # PT15M num dia inteiro; injeta GHI alto às 03:00 UTC (noite em Botucatu).
    ts = pd.date_range("2026-06-07 00:00", "2026-06-07 23:45", freq="15min")
    df = pd.DataFrame({"timestamp": ts, "GHI": np.zeros(len(ts)), "DNI": np.zeros(len(ts))})
    idx_noite = ts.get_loc(pd.Timestamp("2026-06-07 03:00"))
    df.loc[idx_noite, "GHI"] = 300.0
    rel = analisar_qualidade(df, BOTUCATU, "PT15M", ["CAMS McClear"])

    assert rel.n_noturno_suspeito >= 1
    assert bool(rel.flags_por_linha["flag_noturno"].iloc[idx_noite]) is True


def test_envelope_violado_real_acima_de_ceu_limpo():
    ts = pd.date_range("2026-06-07 00:00", periods=24, freq="h")
    clear = np.where((ts.hour >= 10) & (ts.hour <= 16), 600.0, 0.0)
    real = clear * 0.8
    real[12] = clear[12] * 1.4  # real 40% acima do céu limpo -> viola (tol 10%)
    df = pd.DataFrame({
        "timestamp": ts,
        "GHI_McClear": clear, "GHI_NASA": real,
        "GHI_ceu_limpo_NASA": clear,
    })
    rel = analisar_qualidade(df, BOTUCATU, "PT01H", ["CAMS McClear", "NASA POWER"])

    assert rel.envelope is not None
    assert rel.envelope["n_violacoes"] >= 1
    assert rel.envelope["excesso_max_rel"] > 0.10
    assert bool(rel.flags_por_linha["flag_envelope"].iloc[12]) is True


def test_fechamento_nao_aplicavel_em_diario_e_mensal():
    for passo, freq in [("P01D", "D"), ("P01M", "MS")]:
        ts = pd.date_range("2026-01-01", periods=8, freq=freq)
        df = pd.DataFrame({
            "timestamp": ts,
            "GHI": np.full(8, 6000.0),
            "DNI": np.full(8, 7000.0),
            "DHI": np.full(8, 1500.0),
        })
        rel = analisar_qualidade(df, BOTUCATU, passo, ["CAMS McClear"])
        assert rel.fechamento["aplicavel"] is False
        assert "não aplicável" in rel.fechamento["status"]


def test_fechamento_avaliado_e_ok_em_pt15m():
    # Constrói GHI = DHI + DNI·cos(θz) usando o zênite real -> fechamento perfeito.
    ts = pd.date_range("2026-06-07 00:00", "2026-06-07 23:45", freq="15min")
    z = _zenite_meio(ts, 7.5)
    cosz = np.cos(np.radians(z))
    dia = z < 90
    dni = np.where(dia, 800.0, 0.0)
    dhi = np.where(dia, 100.0, 0.0)
    ghi = np.clip(dhi + dni * cosz, 0, None)
    df = pd.DataFrame({"timestamp": ts, "GHI": ghi, "DNI": dni, "DHI": dhi})
    rel = analisar_qualidade(df, BOTUCATU, "PT15M", ["CAMS McClear"])

    assert rel.fechamento["aplicavel"] is True
    assert rel.fechamento["n_avaliado"] > 0
    assert rel.fechamento["n_fora"] == 0
    assert rel.fechamento["status"] == "OK"


def test_concordancia_entre_fontes():
    ts = pd.date_range("2026-06-07 00:00", periods=24, freq="h")
    clear = np.where((ts.hour >= 8) & (ts.hour <= 18), 500.0, 0.0)
    df = pd.DataFrame({
        "timestamp": ts,
        "GHI_McClear": clear,
        "GHI_NASA": clear * 0.7,
        "GHI_ceu_limpo_NASA": clear * 1.05,  # +5% sistemático no céu limpo NASA
    })
    rel = analisar_qualidade(df, BOTUCATU, "PT01H", ["CAMS McClear", "NASA POWER"])

    c = rel.concordancia_fontes
    assert c is not None
    assert c["n"] > 0
    # viés positivo (NASA céu limpo 5% acima do McClear) e r ~ 1.
    assert c["mbe"] > 0
    assert c["r"] > 0.99
    assert abs(c["rmse_rel_pct"] - 5.0) < 0.6


def test_status_geral_ok_em_dados_limpos():
    ts = pd.date_range("2026-06-07 00:00", "2026-06-07 23:45", freq="15min")
    z = _zenite_meio(ts, 7.5)
    cosz = np.cos(np.radians(z))
    dia = z < 90
    dni = np.where(dia, 800.0, 0.0)
    dhi = np.where(dia, 100.0, 0.0)
    ghi = np.clip(dhi + dni * cosz, 0, None)
    df = pd.DataFrame({"timestamp": ts, "GHI": ghi, "DNI": dni, "DHI": dhi})
    rel = analisar_qualidade(df, BOTUCATU, "PT15M", ["CAMS McClear"])

    assert rel.status_geral == "OK"
    assert rel.n_negativos == 0
    assert rel.n_noturno_suspeito == 0


def test_noturno_diario_avalia_no_meio_dia_solar_local():
    """Regressão (auditoria 2026-07-07): no passo diário o zênite era avaliado
    às 12:00 UTC fixas — meia-noite local na Nova Zelândia — e TODO dia
    legítimo virava "radiação noturna suspeita". Agora usa o meio-dia SOLAR
    local (12h − longitude/15)."""
    from core.config import Local

    nz = Local("Wellington", -41.29, 174.78, 20.0)
    ts = pd.date_range("2024-01-01", periods=5, freq="D")
    df = pd.DataFrame({"timestamp": ts, "GHI": [7500.0] * 5, "DHI": [2500.0] * 5})
    rel = analisar_qualidade(df, nz, "P01D", ["CAMS McClear"])
    assert rel.n_noturno_suspeito == 0


def test_noturno_sub_horario_limiar_escala_com_o_passo():
    """Regressão (auditoria 2026-07-07): o limiar noturno fixo (5 Wh/m²) fazia
    o QC de 1 minuto ignorar artefatos de até ~300 W/m² equivalentes. Agora o
    limiar é 20 W/m² equivalentes, escalado pela duração do passo."""
    ts = pd.date_range("2024-01-01 03:00", periods=10, freq="1min")  # noite
    df = pd.DataFrame({"timestamp": ts, "GHI": [2.0] * 10})  # ≡ 120 W/m²
    rel = analisar_qualidade(df, BOTUCATU, "PT01M", ["CAMS McClear"])
    assert rel.n_noturno_suspeito == 10


def test_completude_por_coluna_expoe_lacuna_de_fonte():
    """Regressão (auditoria 2026-07-07): a completude geral conta o instante
    como presente se QUALQUER coluna tem dado — uma fonte majoritariamente
    vazia ficava escondida atrás da outra no combinado."""
    ts = pd.date_range("2024-01-01", periods=24, freq="h")
    df = pd.DataFrame(
        {
            "timestamp": ts,
            "GHI_McClear": [100.0] * 24,
            "GHI_NASA": [100.0] * 12 + [float("nan")] * 12,
        }
    )
    rel = analisar_qualidade(
        df, BOTUCATU, "PT01H", ["CAMS McClear", "NASA POWER"]
    )
    assert rel.completude_pct == 100.0
    assert rel.completude_por_coluna["GHI_NASA"] == 50.0
    assert rel.completude_por_coluna["GHI_McClear"] == 100.0
    assert "GHI_NASA" in rel.resumo_texto  # o resumo aponta a pior coluna
