"""
Testes da conferência de fidelidade (core/conferencia.py).

Cobrem: comparação idêntica, diferenças pequenas/relevantes, desalinhamento de
timestamps, remoção de sufixo de fonte, sem sobreposição, leitura do CSV do site
(pvlib.read_cams mockado) e a conferência ponta-a-ponta. Sem rede.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from core.conferencia import (
    comparar,
    conferir_mcclear,
    formatar_relatorio_md,
    parsear_mcclear_site,
)


def _ex(n: int = 6) -> pd.DataFrame:
    """Extração sintética: timestamp (naive UTC) + GHI/BHI/DHI/DNI."""
    ts = pd.date_range("2024-01-01 12:00", periods=n, freq="h")
    ghi = np.linspace(400.0, 600.0, n)
    return pd.DataFrame(
        {
            "timestamp": ts,
            "GHI": ghi,
            "BHI": ghi * 0.7,
            "DHI": ghi * 0.2,
            "DNI": ghi * 0.9,
        }
    )


def test_identico():
    rel = comparar(_ex(), _ex())
    assert rel.status == "Idêntico"
    assert rel.n_comum == 6
    assert rel.n_so_extracao == 0 and rel.n_so_referencia == 0
    assert all(m["n_fora_tol"] == 0 for m in rel.por_componente.values())
    assert rel.por_componente["GHI"]["max_abs"] == 0.0


def test_diferenca_pequena():
    ex, ref = _ex(), _ex()
    ref["GHI"] = ref["GHI"] * 1.03  # ~3% -> dentro de 5%, fora de 1%
    rel = comparar(ex, ref)
    assert rel.status == "Diferenças pequenas"
    assert rel.por_componente["GHI"]["n_fora_tol"] > 0
    assert 0.02 < rel.por_componente["GHI"]["max_rel"] < 0.05
    # Os demais componentes seguem idênticos.
    assert rel.por_componente["DNI"]["n_fora_tol"] == 0


def test_diferenca_relevante():
    ex, ref = _ex(), _ex()
    ref["GHI"] = ref["GHI"] * 1.10  # ~9% -> relevante
    rel = comparar(ex, ref)
    assert rel.status == "Diferenças relevantes"
    assert rel.por_componente["GHI"]["max_rel"] > 0.05


def test_timestamps_desalinhados():
    ex = _ex(8)
    ref = _ex(8).iloc[:6]  # mesmos valores, 2 horas a menos
    rel = comparar(ex, ref)
    assert rel.n_comum == 6
    assert rel.n_so_extracao == 2
    assert rel.n_so_referencia == 0
    assert rel.status == "Idêntico"  # nos pontos comuns, são iguais


def test_remove_sufixo_de_fonte():
    """Extração combinada (GHI_McClear...) deve casar com o site (GHI...)."""
    ex = _ex().rename(
        columns={
            "GHI": "GHI_McClear", "BHI": "BHI_McClear",
            "DHI": "DHI_McClear", "DNI": "DNI_McClear",
        }
    )
    rel = comparar(ex, _ex())
    assert rel.status == "Idêntico"
    assert rel.n_comum == 6


def test_sem_sobreposicao():
    ex = _ex()
    ref = _ex()
    ref["timestamp"] = ref["timestamp"] + pd.Timedelta(days=10)
    rel = comparar(ex, ref)
    assert rel.status == "Sem sobreposição"
    assert rel.n_comum == 0


def _fake_read_cams(periodos: int = 4):
    """Imita pvlib.iotools.read_cams: (DataFrame tz-aware UTC, metadata)."""
    idx = pd.date_range("2024-01-01 12:00", periods=periodos, freq="h", tz="UTC")
    base = np.linspace(500.0, 560.0, periodos)
    df = pd.DataFrame(
        {
            "ghi_clear": base,
            "bhi_clear": base * 0.7,
            "dhi_clear": base * 0.2,
            "dni_clear": base * 0.9,
            "ghi_extra": base * 2,  # ignorada
        },
        index=idx,
    )
    return df, {"Time reference": "UT"}


def test_parsear_site_mockado(monkeypatch):
    import pvlib

    monkeypatch.setattr(
        pvlib.iotools, "read_cams", lambda *a, **k: _fake_read_cams(3)
    )
    df = parsear_mcclear_site("arquivo_do_site.csv")
    # Colunas padronizadas, na ordem da SoDa, e timestamp sem fuso.
    assert list(df.columns) == ["timestamp", "GHI", "BHI", "DHI", "DNI"]
    assert df["timestamp"].dt.tz is None
    assert df["GHI"].iloc[0] == 500.0


def test_conferir_mcclear_ponta_a_ponta(monkeypatch):
    import pvlib

    monkeypatch.setattr(
        pvlib.iotools, "read_cams", lambda *a, **k: _fake_read_cams(4)
    )
    # Extração idêntica ao "site" (mesmos valores, timestamp naive).
    base = np.linspace(500.0, 560.0, 4)
    ex = pd.DataFrame(
        {
            "timestamp": pd.date_range("2024-01-01 12:00", periods=4, freq="h"),
            "GHI": base, "BHI": base * 0.7, "DHI": base * 0.2, "DNI": base * 0.9,
        }
    )
    rel = conferir_mcclear(ex, "site.csv")
    assert rel.status == "Idêntico"
    assert rel.n_comum == 4

    # O relatório em Markdown sai sem erro e com o cabeçalho.
    md = formatar_relatorio_md(rel)
    assert "Relatório de Fidelidade" in md
    assert "CAMS McClear" in md
