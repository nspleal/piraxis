"""
tests/validar_extracao.py
=========================

Validação da CHAMADA DIRETA à pvlib + sanidade física dos dados do CAMS McClear.

Faz a chamada exata validada contra a API real e roda verificações físicas:
chamada sem erro; colunas esperadas; 72 linhas (3 dias horários); índice UTC
horário sem buracos; sem NaN nem negativos; GHI ≈ 0 à noite; pico diurno
plausível em torno do meio-dia solar (≈14–16h UTC); fechamento GHI = BHI + DHI.

E-mail: config (~/.radiacao_solar/config.json) > SODA_EMAIL > --email.
Sem e-mail/rede, o item é PULADO (rode na sua máquina com a conta SoDa).

Flag opcional --com-radiation: verifica também identifier="cams_radiation"
(desligada por padrão para poupar cota; a cobertura de Botucatu já foi
confirmada).

Uso:
    python tests/validar_extracao.py [--email voce@dominio.com] [--com-radiation]
"""

from __future__ import annotations

import sys
from pathlib import Path

# Garante a raiz do projeto (pasta "Programa") no sys.path mesmo rodando como
# "python tests/validar_extracao.py".
_RAIZ = Path(__file__).resolve().parent.parent
if str(_RAIZ) not in sys.path:
    sys.path.insert(0, str(_RAIZ))

import pandas as pd

from tests._comum import (  # type: ignore  (script-style import)
    APROVADO,
    PULADO,
    REPROVADO,
    obter_email,
    periodo_padrao,
)

# Botucatu (constantes da configuração existente).
from core.config import BOTUCATU

COLUNAS_ESPERADAS = {"ghi_clear", "bhi_clear", "dhi_clear", "dni_clear"}


def _verificacoes_fisicas(df: pd.DataFrame) -> list[tuple[str, bool, str]]:
    """Roda as verificações de sanidade física; retorna (nome, ok, detalhe)."""
    checks: list[tuple[str, bool, str]] = []

    # Colunas esperadas presentes.
    faltando = COLUNAS_ESPERADAS - set(df.columns)
    checks.append(("colunas esperadas", not faltando, f"faltando={faltando}"))

    # 72 linhas (3 dias horários).
    checks.append(("72 linhas (3 dias)", len(df) == 72, f"linhas={len(df)}"))

    # Índice UTC horário sem buracos.
    idx_ok = isinstance(df.index, pd.DatetimeIndex)
    tz_ok = idx_ok and str(df.index.tz) in {"UTC", "UTC+00:00"}
    if idx_ok and len(df) > 1:
        difs = df.index.to_series().diff().dropna().unique()
        passo_ok = len(difs) == 1 and difs[0] == pd.Timedelta(hours=1)
    else:
        passo_ok = False
    checks.append(
        ("índice UTC horário sem buracos", bool(tz_ok and passo_ok),
         f"tz={getattr(df.index, 'tz', None)}")
    )

    cols = [c for c in COLUNAS_ESPERADAS if c in df.columns]
    sub = df[cols] if cols else df

    # Sem NaN.
    checks.append(("sem valores ausentes (NaN)", not sub.isna().any().any(), ""))
    # Sem negativos.
    checks.append(("sem valores negativos", bool((sub.fillna(0) >= 0).all().all()), ""))

    if "ghi_clear" in df.columns:
        ghi = df["ghi_clear"]
        horas = df.index.hour

        # GHI ≈ 0 à noite (noite local ≈ 21h–08h UTC -> usamos o miolo da noite).
        mascara_noite = horas.isin([23, 0, 1, 2, 3, 4, 5, 6, 7, 8])
        noite_max = float(ghi[mascara_noite].max()) if mascara_noite.any() else 0.0
        checks.append(
            ("GHI ≈ 0 à noite", noite_max < 10.0, f"máx noturno={noite_max:.1f}")
        )

        # Pico diurno por dia: magnitude plausível e por volta do meio-dia solar.
        # Janela 14–16h UTC (robusta o ano todo em Botucatu, solar noon ≈ 15h UTC).
        # Banda esperada em junho: 450–850 W/m²; aqui aceitamos 400–1000 para não
        # falhar por variação sazonal, ainda capturando erros grosseiros.
        picos_ok = True
        detalhes_pico = []
        for dia, grupo in ghi.groupby(df.index.date):
            valor_pico = float(grupo.max())
            hora_pico = int(grupo.idxmax().hour)
            ok_dia = (400.0 <= valor_pico <= 1000.0) and (14 <= hora_pico <= 16)
            picos_ok = picos_ok and ok_dia
            detalhes_pico.append(f"{dia}:{valor_pico:.0f}W/m²@{hora_pico}hUTC")
        checks.append(
            ("pico diurno plausível (≈14–16h UTC)", picos_ok,
             "; ".join(detalhes_pico))
        )

        # Fechamento GHI = BHI + DHI (desvio médio < 5 W/m²).
        if {"bhi_clear", "dhi_clear"}.issubset(df.columns):
            desvio = (df["ghi_clear"] - (df["bhi_clear"] + df["dhi_clear"])).abs()
            desvio_medio = float(desvio.mean())
            checks.append(
                ("fechamento GHI=BHI+DHI (<5 W/m²)", desvio_medio < 5.0,
                 f"desvio médio={desvio_medio:.2f} W/m²")
            )

    return checks


def executar(email: str | None = None) -> tuple[str, str]:
    """Roda a validação. Retorna (status, detalhe)."""
    if email is None:
        email = obter_email()
    if not email:
        return PULADO, "sem e-mail SoDa (config/SODA_EMAIL/--email)"

    import pvlib

    inicio, fim = periodo_padrao()
    try:
        df, _meta = pvlib.iotools.get_cams(
            latitude=BOTUCATU.latitude,
            longitude=BOTUCATU.longitude,
            start=pd.Timestamp(inicio, tz="UTC"),
            end=pd.Timestamp(fim, tz="UTC"),
            email=email,
            identifier="mcclear",
            altitude=int(BOTUCATU.altitude),
            time_step="1h",
            map_variables=True,
            timeout=60,
        )
    except Exception as exc:  # noqa: BLE001
        return REPROVADO, f"chamada pvlib falhou: {exc}"

    checks = _verificacoes_fisicas(df)
    falhas = [c for c in checks if not c[1]]
    for nome, ok, det in checks:
        print(f"      - {'OK ' if ok else 'FALHA'} {nome} {('· ' + det) if det else ''}")

    # Verificação extra opcional do cams_radiation.
    if "--com-radiation" in sys.argv:
        try:
            dfr, _ = pvlib.iotools.get_cams(
                latitude=BOTUCATU.latitude, longitude=BOTUCATU.longitude,
                start=pd.Timestamp(inicio, tz="UTC"),
                end=pd.Timestamp(fim, tz="UTC"),
                email=email, identifier="cams_radiation",
                altitude=int(BOTUCATU.altitude), time_step="1h",
                map_variables=True, timeout=60,
            )
            tem_real = "ghi" in dfr.columns
            print(f"      - {'OK ' if tem_real else 'FALHA'} cams_radiation traz GHI real")
            if not tem_real:
                falhas.append(("cams_radiation GHI real", False, ""))
        except Exception as exc:  # noqa: BLE001
            falhas.append(("cams_radiation", False, str(exc)))
            print(f"      - FALHA cams_radiation: {exc}")

    if falhas:
        return REPROVADO, f"{len(falhas)} verificação(ões) falharam"
    return APROVADO, f"{len(checks)} verificações físicas OK"


if __name__ == "__main__":
    status, detalhe = executar()
    print(f"\nvalidar_extracao: {status} — {detalhe}")
    sys.exit(0 if status in (APROVADO, PULADO) else 1)
