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
    ler_altitude_site,
    parsear_mcclear_site,
)

# CSV do McClear como sai quando foi ABERTO/SALVO no Excel pt-BR: o ponto decimal
# virou separador de milhar (valores ~10.000× maiores; ex.: 1066.6589 -> 10.666.589).
CSV_CORROMPIDO = (
    "# Title: CAMS McClear v3.6;;;;;\n"
    "# Altitude (m): 786.00;;;;;\n"
    "# Time reference: Universal time (UT);;;;;\n"
    "# Observation period;TOA;Clear sky GHI;Clear sky BHI;Clear sky DHI;Clear sky BNI\n"
    "2026-03-01T15:00:00.0/2026-03-01T16:00:00.0;13.334.834;10.666.589;9.597.211;1.069.379;9.986.248\n"
    "2026-03-01T16:00:00.0/2026-03-01T17:00:00.0;12.846.257;10.223.154;9.151.938;1.071.216;9.883.879\n"
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


def test_parsear_site_corrompido_pelo_excel(tmp_path):
    """CSV corrompido (ponto decimal -> milhar) deve ser decodificado (÷10.000)."""
    p = tmp_path / "site_excel.csv"
    p.write_text(CSV_CORROMPIDO, encoding="utf-8")
    df = parsear_mcclear_site(str(p))
    assert list(df.columns) == ["timestamp", "GHI", "BHI", "DHI", "DNI"]
    assert abs(df["GHI"].iloc[0] - 1066.6589) < 1e-6
    assert abs(df["DNI"].iloc[0] - 998.6248) < 1e-6   # BNI da SoDa -> DNI
    assert df["timestamp"].iloc[0] == pd.Timestamp("2026-03-01 15:00")
    # Fechamento GHI = BHI + DHI continua válido após decodificar.
    assert abs(df["GHI"].iloc[0] - (df["BHI"].iloc[0] + df["DHI"].iloc[0])) < 1e-3


def test_ler_altitude_do_cabecalho(tmp_path):
    p = tmp_path / "site.csv"
    p.write_text(CSV_CORROMPIDO, encoding="utf-8")
    assert ler_altitude_site(str(p)) == 786.0


def test_conferir_avisa_corrompido_e_altitude(tmp_path):
    """Conferência decodifica o arquivo corrompido (status Idêntico) e avisa sobre
    a corrupção e a diferença de altitude."""
    p = tmp_path / "site.csv"
    p.write_text(CSV_CORROMPIDO, encoding="utf-8")
    ex = pd.DataFrame(
        {
            "timestamp": [
                pd.Timestamp("2026-03-01 15:00"), pd.Timestamp("2026-03-01 16:00"),
            ],
            "GHI": [1066.6589, 1022.3154],
            "BHI": [959.7211, 915.1938],
            "DHI": [106.9379, 107.1216],
            "DNI": [998.6248, 988.3879],
        }
    )
    rel = conferir_mcclear(ex, str(p), altitude_extracao=840.0)
    assert rel.status == "Idêntico"  # decodificou certo -> bate
    assert any("editor de planilha" in a for a in rel.avisos)
    assert any("Altitude diferente" in a for a in rel.avisos)
    # Avisos aparecem no relatório em Markdown.
    assert "Altitude diferente" in formatar_relatorio_md(rel)
