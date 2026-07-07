"""
core/qualidade.py
=================

Controle de qualidade (QC) automático dos dados de radiação, no padrão da
radiometria solar (BSRN / Long & Dutton). Recebe o DataFrame unificado do
``combinador``, o ``Local`` e o passo temporal, e devolve um ``RelatorioQC``.

Verificações implementadas:
  1. Lacunas / completude — grade temporal completa esperada vs. presente.
  2. Faixa física / plausibilidade — radiação ≥ 0 e ≈ 0 à noite.
  3. Envelope de céu limpo — radiação real não pode exceder o céu limpo (+tol).
  4. Equação de fechamento — GHI ≈ DHI + DNI·cos(θz) (só alta frequência).
  5. Concordância entre fontes — céu limpo McClear × CLRSKY NASA (sem rede).

A posição solar usa ``pvlib.solarposition`` (sem rede). Os dados são UTC.

Esta camada NÃO altera a extração nem o combinador — apenas analisa o que já
foi baixado.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field

import numpy as np
import pandas as pd

logger = logging.getLogger(__name__)

# Passo ISO -> frequência pandas para montar a grade temporal esperada.
FREQ_POR_PASSO: dict[str, str] = {
    "PT01M": "1min",
    "PT15M": "15min",
    "PT01H": "1h",
    "P01D": "1D",
    "P01M": "MS",
}

# Deslocamento até o ponto médio de cada período (para a geometria solar).
# Passos diário/mensal NÃO estão aqui: usam o meio-dia SOLAR local (função
# _offset_meio), que depende da longitude do ponto.
_OFFSET_MEIO = {
    "PT01M": pd.Timedelta(seconds=30),
    "PT15M": pd.Timedelta(minutes=7, seconds=30),
    "PT01H": pd.Timedelta(minutes=30),
}


def _offset_meio(passo_temporal: str, local) -> pd.Timedelta:
    """Deslocamento do rótulo até o instante de avaliação da geometria solar.

    Passos ≤ 1 h: o meio do intervalo. Passos diário/mensal: o **meio-dia
    solar local** do período (12 h − longitude/15°/h). Usar 12:00 UTC fixo
    avaliaria o zênite de madrugada em longitudes distantes do meridiano de
    Greenwich (ex.: Nova Zelândia) e marcaria dias inteiros legítimos como
    "radiação noturna suspeita".
    """
    if passo_temporal in ("P01D", "P01M"):
        base = pd.Timedelta(days=15) if passo_temporal == "P01M" else pd.Timedelta(0)
        return base + pd.Timedelta(hours=12.0 - local.longitude / 15.0)
    return _OFFSET_MEIO.get(passo_temporal, pd.Timedelta(0))

# Duração do passo em horas (para limiares proporcionais ao passo).
_DT_HORAS = {"PT01M": 1 / 60, "PT15M": 0.25, "PT01H": 1.0, "P01D": 24.0, "P01M": 720.0}

# Tolerância do envelope de céu limpo (real ≤ céu_limpo × (1+tol)).
_TOL_ENVELOPE = {"PT01M": 0.25, "PT15M": 0.25, "PT01H": 0.10, "P01D": 0.10, "P01M": 0.10}

# Ruído de arredondamento tolerado em valores negativos (Wh/m²).
TOL_NEGATIVO = -1.0

# Limiar do check noturno sub-horário, em POTÊNCIA equivalente (W/m²). Os
# dados são energia POR PASSO (Wh/m²), então o limiar em Wh escala com a
# duração do passo — o mesmo artefato físico dispara igual em 1 e em 15 min
# (fixo em 5 Wh, 1 min só flagrava a partir de ~300 W/m² equivalentes).
LIMIAR_NOTURNO_WM2 = 20.0


@dataclass
class RelatorioQC:
    """Resultado estruturado do controle de qualidade."""

    status_geral: str  # "OK" | "Atenção" | "Problemas"
    completude_pct: float
    total_esperado: int
    total_presente: int
    lacunas: list[dict]
    n_negativos: int
    n_noturno_suspeito: int
    nan_por_coluna: dict[str, int]
    envelope: dict | None
    fechamento: dict
    concordancia_fontes: dict | None
    flags_por_linha: pd.DataFrame
    resumo_texto: str
    # Tolerâncias usadas (para a legenda autoexplicativa no Excel).
    criterios: dict = field(default_factory=dict)
    # Completude POR COLUNA (%): a completude geral conta um instante como
    # presente se QUALQUER coluna tem dado — numa extração combinada, uma
    # fonte majoritariamente vazia ficava escondida atrás da outra.
    completude_por_coluna: dict = field(default_factory=dict)


# ---------------------------------------------------------------------------
# Resolução de papéis das colunas (real / céu limpo / fechamento)
# ---------------------------------------------------------------------------
@dataclass
class _Papeis:
    ghi_real: pd.Series | None = None
    dni_real: pd.Series | None = None
    dhi_real: pd.Series | None = None
    ghi_clear: pd.Series | None = None
    ghi_clear_mcclear: pd.Series | None = None
    ghi_clear_nasa: pd.Series | None = None
    ghi_fech: pd.Series | None = None
    dni_fech: pd.Series | None = None
    dhi_fech: pd.Series | None = None
    cols_radiacao: list[str] = field(default_factory=list)


def _resolver_papeis(df: pd.DataFrame, nomes_fontes: list[str] | None) -> _Papeis:
    """Identifica, pelas colunas, os papéis físicos (real, céu limpo, etc.)."""
    cols = list(df.columns)
    get = lambda nome: df[nome] if nome in cols else None  # noqa: E731

    p = _Papeis()
    p.cols_radiacao = [
        c
        for c in cols
        if c != "timestamp"
        and c != "kt"
        and pd.api.types.is_numeric_dtype(df[c])
    ]

    suffixado = any(c.endswith("_McClear") or c.endswith("_NASA") for c in cols)
    if suffixado:
        # Extração combinada: McClear (céu limpo) + NASA (real), com sufixos.
        p.ghi_real = get("GHI_NASA")
        p.dni_real = get("DNI_NASA")
        p.dhi_real = get("DHI_NASA")
        p.ghi_clear_mcclear = get("GHI_McClear")
        p.ghi_clear_nasa = get("GHI_ceu_limpo_NASA")
        if all(s is not None for s in (p.ghi_real, p.dni_real, p.dhi_real)):
            p.ghi_fech, p.dni_fech, p.dhi_fech = p.ghi_real, p.dni_real, p.dhi_real
        else:
            p.ghi_fech = get("GHI_McClear")
            p.dni_fech = get("DNI_McClear")
            p.dhi_fech = get("DHI_McClear")
    else:
        # Fonte única: descobrir se é NASA (real) ou McClear (céu limpo).
        nomes = " ".join(nomes_fontes or []).lower()
        tem_clrsky = "GHI_ceu_limpo" in cols
        eh_nasa = tem_clrsky or "nasa" in nomes or "power" in nomes
        eh_mcclear = (
            ("BHI" in cols and not tem_clrsky) or "mcclear" in nomes or "cams" in nomes
        )
        if eh_nasa and not (eh_mcclear and not tem_clrsky):
            p.ghi_real, p.dni_real, p.dhi_real = get("GHI"), get("DNI"), get("DHI")
            p.ghi_clear_nasa = get("GHI_ceu_limpo")
            p.ghi_fech, p.dni_fech, p.dhi_fech = p.ghi_real, p.dni_real, p.dhi_real
        else:
            p.ghi_clear_mcclear = get("GHI")
            p.ghi_fech, p.dni_fech, p.dhi_fech = get("GHI"), get("DNI"), get("DHI")

    # Referência de céu limpo: McClear preferencial, senão CLRSKY da NASA.
    p.ghi_clear = (
        p.ghi_clear_mcclear if p.ghi_clear_mcclear is not None else p.ghi_clear_nasa
    )
    return p


# ---------------------------------------------------------------------------
# Geometria solar
# ---------------------------------------------------------------------------
def _zenite(meio_periodo: pd.DatetimeIndex, local) -> pd.Series:
    """Ângulo zenital aparente (graus) no ponto médio de cada período (UTC)."""
    import pvlib

    times = pd.DatetimeIndex(meio_periodo)
    if times.tz is None:
        times = times.tz_localize("UTC")
    pos = pvlib.solarposition.get_solarposition(
        times, local.latitude, local.longitude,
        altitude=(local.altitude if local.altitude and local.altitude > 0 else 0),
    )
    return pd.Series(pos["apparent_zenith"].to_numpy(), index=range(len(times)))


# ---------------------------------------------------------------------------
# Função principal
# ---------------------------------------------------------------------------
def analisar_qualidade(
    df: pd.DataFrame,
    local,
    passo_temporal: str,
    nomes_fontes: list[str] | None = None,
) -> RelatorioQC:
    """Roda as cinco verificações de QC e devolve o ``RelatorioQC``."""
    df = df.reset_index(drop=True)
    n = len(df)
    flags = pd.DataFrame(index=df.index)
    if "timestamp" in df.columns:
        flags["timestamp"] = pd.to_datetime(df["timestamp"]).values

    papeis = _resolver_papeis(df, nomes_fontes)
    dt_horas = _DT_HORAS.get(passo_temporal, 1.0)

    # --- 1. Lacunas / completude -------------------------------------------
    total_esperado, total_presente, completude, lacunas = _verificar_lacunas(
        df, passo_temporal, papeis
    )
    nan_por_coluna = {
        c: int(df[c].isna().sum()) for c in papeis.cols_radiacao
    }
    completude_por_coluna = {
        c: round(
            float(df[c].notna().sum()) / total_esperado * 100, 1
        ) if total_esperado else 100.0
        for c in papeis.cols_radiacao
    }

    # --- Geometria solar (zênite no ponto médio) ---------------------------
    zenite = None
    if n > 0 and "timestamp" in df.columns and df["timestamp"].notna().any():
        meio = pd.to_datetime(df["timestamp"]) + _offset_meio(passo_temporal, local)
        try:
            zenite = _zenite(pd.DatetimeIndex(meio), local)
        except Exception as exc:  # pragma: no cover - pvlib robustez
            logger.warning("Não foi possível calcular a posição solar: %s", exc)

    # --- 2. Faixa física: negativos e noturno ------------------------------
    flag_neg, n_negativos = _verificar_negativos(df, papeis)
    flags["flag_negativo"] = flag_neg
    flag_noite, n_noturno = _verificar_noturno(df, papeis, zenite, passo_temporal)
    flags["flag_noturno"] = flag_noite

    # --- 3. Envelope de céu limpo ------------------------------------------
    envelope, flag_env = _verificar_envelope(papeis, passo_temporal, n)
    flags["flag_envelope"] = flag_env

    # --- 4. Equação de fechamento ------------------------------------------
    fechamento, flag_fech = _verificar_fechamento(
        papeis, zenite, passo_temporal, dt_horas, n
    )
    flags["flag_fechamento"] = flag_fech

    # --- 5. Concordância entre fontes --------------------------------------
    concordancia = _verificar_concordancia(papeis, zenite)

    # --- Status geral + resumo ---------------------------------------------
    status = _classificar(
        completude, n_negativos, n_noturno, envelope, fechamento, concordancia, n
    )
    criterios = {
        "tolerancia_envelope": _TOL_ENVELOPE.get(passo_temporal, 0.10),
        "fechamento_tolerancia": "|razão−1| < 0,08 (zênite<75°); < 0,15 (75–93°)",
        "fechamento_aplicavel": fechamento["aplicavel"],
        "negativo_tolerancia_whm2": TOL_NEGATIVO,
        "concordancia_faixas": "RMSE rel. <5% boa; 5–15% aceitável; >15% investigar",
    }
    resumo = _montar_resumo(
        status, completude, total_esperado, total_presente, lacunas, n_negativos,
        n_noturno, envelope, fechamento, concordancia,
    )
    if completude_por_coluna:
        pior_col = min(completude_por_coluna, key=completude_por_coluna.get)
        pior_pct = completude_por_coluna[pior_col]
        if pior_pct < completude - 5.0:
            resumo += (
                f"\n⚠️ Completude por coluna: {pior_col} tem só {pior_pct:.1f}% "
                "dos instantes com dado (a completude geral conta o instante "
                "como presente se qualquer coluna tem dado)."
            )

    return RelatorioQC(
        status_geral=status,
        completude_pct=round(completude, 1),
        total_esperado=total_esperado,
        total_presente=total_presente,
        lacunas=lacunas,
        n_negativos=n_negativos,
        n_noturno_suspeito=n_noturno,
        nan_por_coluna=nan_por_coluna,
        envelope=envelope,
        fechamento=fechamento,
        concordancia_fontes=concordancia,
        flags_por_linha=flags,
        resumo_texto=resumo,
        criterios=criterios,
        completude_por_coluna=completude_por_coluna,
    )


# ---------------------------------------------------------------------------
# Verificações individuais
# ---------------------------------------------------------------------------
def _verificar_lacunas(df, passo_temporal, papeis):
    """Completude da grade temporal; lacuna = trecho sem nenhum dado válido."""
    if "timestamp" not in df.columns or df["timestamp"].dropna().empty:
        return len(df), len(df), 100.0, []

    ts = pd.to_datetime(df["timestamp"]).dropna().sort_values()
    freq = FREQ_POR_PASSO.get(passo_temporal, "1h")
    grade = pd.date_range(ts.min(), ts.max(), freq=freq)
    total_esperado = len(grade)

    # "Presente" = instante com ao menos um componente de radiação não-nulo (NaN).
    if papeis.cols_radiacao:
        tem_dado = df[papeis.cols_radiacao].notna().any(axis=1)
    else:
        tem_dado = pd.Series(True, index=df.index)
    presentes = pd.DatetimeIndex(
        pd.to_datetime(df.loc[tem_dado.values, "timestamp"]).dropna().unique()
    )
    total_presente = len(presentes)
    completude = (total_presente / total_esperado * 100) if total_esperado else 100.0

    faltantes = grade.difference(presentes).sort_values()
    lacunas = _agrupar_lacunas(faltantes, freq)
    return total_esperado, total_presente, completude, lacunas


def _agrupar_lacunas(faltantes: pd.DatetimeIndex, freq: str) -> list[dict]:
    """Agrupa timestamps ausentes consecutivos em intervalos resumidos."""
    if len(faltantes) == 0:
        return []
    passo = pd.tseries.frequencies.to_offset(freq)
    lacunas: list[dict] = []
    inicio = anterior = faltantes[0]
    n_passos = 1
    for t in faltantes[1:]:
        if t == anterior + passo:
            anterior = t
            n_passos += 1
        else:
            lacunas.append(_lacuna(inicio, anterior, n_passos))
            inicio = anterior = t
            n_passos = 1
    lacunas.append(_lacuna(inicio, anterior, n_passos))
    # Resumo: no máximo 20 intervalos no relatório.
    return lacunas[:20]


def _lacuna(inicio, fim, n_passos) -> dict:
    return {
        "inicio": pd.Timestamp(inicio).isoformat(),
        "fim": pd.Timestamp(fim).isoformat(),
        "n_passos": int(n_passos),
        "duracao": str(pd.Timestamp(fim) - pd.Timestamp(inicio)),
    }


def _verificar_negativos(df, papeis):
    """Sinaliza valores < -1 Wh/m² (abaixo do ruído de arredondamento)."""
    flag = pd.Series(False, index=df.index)
    for c in papeis.cols_radiacao:
        flag = flag | (df[c] < TOL_NEGATIVO)
    return flag.fillna(False), int(flag.sum())


def _verificar_noturno(df, papeis, zenite, passo_temporal):
    """Sinaliza radiação claramente não-nula quando o Sol está abaixo do horizonte."""
    flag = pd.Series(False, index=df.index)
    if zenite is None:
        return flag, 0

    sub_horario = passo_temporal in ("PT01M", "PT15M")
    # Sub-horário: noite = zênite>90 e limiar proporcional ao passo (20 W/m²
    # equivalentes). Agregado (≥1h): só o fisicamente impossível -> zênite
    # bem abaixo (>96° no instante avaliado) e valor alto no período.
    if sub_horario:
        noite = zenite > 90.0
        limiar = LIMIAR_NOTURNO_WM2 * _DT_HORAS.get(passo_temporal, 1.0)
    else:
        noite = zenite > 96.0
        limiar = 50.0

    noite = noite.reindex(df.index).fillna(False).to_numpy()
    cols_gd = [
        c
        for c in papeis.cols_radiacao
        if c.upper().startswith("GHI") or c.upper().startswith("DNI")
    ]
    for c in cols_gd:
        flag = flag | (noite & (df[c].fillna(0).to_numpy() > limiar))
    return flag.fillna(False), int(flag.sum())


def _verificar_envelope(papeis, passo_temporal, n):
    """Radiação real não pode exceder o céu limpo além da tolerância."""
    flag = pd.Series(False, index=range(n))
    if papeis.ghi_real is None or papeis.ghi_clear is None:
        return None, flag

    tol = _TOL_ENVELOPE.get(passo_temporal, 0.10)
    real = pd.to_numeric(papeis.ghi_real, errors="coerce").reset_index(drop=True)
    clear = pd.to_numeric(papeis.ghi_clear, errors="coerce").reset_index(drop=True)
    valido = real.notna() & clear.notna() & (clear > 0)
    excesso_rel = (real - clear) / clear.where(clear > 0)
    violacao = valido & (excesso_rel > tol)
    flag = violacao.fillna(False)

    n_viol = int(flag.sum())
    excesso_max = float(excesso_rel[flag].max()) if n_viol else 0.0
    envelope = {
        "n_violacoes": n_viol,
        "excesso_max_rel": round(excesso_max, 4),
        "tolerancia": tol,
        "n_avaliado": int(valido.sum()),
    }
    return envelope, flag


def _verificar_fechamento(papeis, zenite, passo_temporal, dt_horas, n):
    """GHI ≈ DHI + DNI·cos(θz); robusto só em alta frequência."""
    flag = pd.Series(False, index=range(n))
    aplicavel = passo_temporal in ("PT01M", "PT15M", "PT01H")
    base = {
        "aplicavel": aplicavel,
        "status": "não aplicável",
        "n_fora": 0,
        "n_avaliado": 0,
        "passo": passo_temporal,
    }
    if not aplicavel:
        base["status"] = "não aplicável (valores integrados em D/M)"
        return base, flag
    if zenite is None or any(
        s is None for s in (papeis.ghi_fech, papeis.dni_fech, papeis.dhi_fech)
    ):
        base["status"] = "não avaliado (dados insuficientes)"
        return base, flag

    ghi = pd.to_numeric(papeis.ghi_fech, errors="coerce").reset_index(drop=True)
    dni = pd.to_numeric(papeis.dni_fech, errors="coerce").reset_index(drop=True)
    dhi = pd.to_numeric(papeis.dhi_fech, errors="coerce").reset_index(drop=True)
    z = zenite.reset_index(drop=True)
    cosz = np.cos(np.radians(z))

    limiar_ghi = 50.0 * dt_horas
    if passo_temporal == "PT01H":
        # Horário: tolerância relaxada e só com Sol alto (exclui Sol baixo).
        mask = ghi.notna() & dni.notna() & dhi.notna() & (ghi > limiar_ghi) & (z < 75)
        tol = pd.Series(0.15, index=ghi.index)
    else:
        mask = ghi.notna() & dni.notna() & dhi.notna() & (ghi > limiar_ghi) & (z < 93)
        tol = pd.Series(np.where(z < 75, 0.08, 0.15), index=ghi.index)

    razao = (dhi + dni * cosz) / ghi.where(ghi > 0)
    fora = mask & ((razao - 1).abs() > tol)
    flag = fora.fillna(False)

    n_aval = int(mask.sum())
    n_fora = int(flag.sum())
    if n_aval == 0:
        status = "não avaliado (sem pontos com Sol alto)"
    elif n_fora / n_aval > 0.30:
        status = "Problemas"
    elif n_fora > 0:
        status = "Atenção"
    else:
        status = "OK"
    base.update(status=status, n_fora=n_fora, n_avaliado=n_aval)
    return base, flag


def _verificar_concordancia(papeis, zenite):
    """Concordância McClear (céu limpo) × CLRSKY NASA, em pontos diurnos."""
    a = papeis.ghi_clear_mcclear
    b = papeis.ghi_clear_nasa
    if a is None or b is None:
        return None

    a = pd.to_numeric(a, errors="coerce").reset_index(drop=True)
    b = pd.to_numeric(b, errors="coerce").reset_index(drop=True)
    mask = a.notna() & b.notna()
    if zenite is not None:
        diurno = (zenite.reset_index(drop=True) < 90).reindex(a.index).fillna(False)
        mask = mask & diurno
    if int(mask.sum()) < 3:
        return None

    av, bv = a[mask].to_numpy(), b[mask].to_numpy()
    mbe = float(np.mean(bv - av))  # NASA menos McClear
    rmse = float(np.sqrt(np.mean((bv - av) ** 2)))
    ref = float(np.mean(av))
    rmse_rel = (rmse / ref * 100) if ref > 0 else float("nan")
    r = float(np.corrcoef(av, bv)[0, 1]) if len(av) > 1 else float("nan")

    if rmse_rel < 5:
        interp = "boa concordância"
    elif rmse_rel <= 15:
        interp = "aceitável (modelos diferentes)"
    else:
        interp = "investigar"
    return {
        "n": int(mask.sum()),
        "mbe": round(mbe, 2),
        "rmse": round(rmse, 2),
        "rmse_rel_pct": round(rmse_rel, 1),
        "r": round(r, 4),
        "interpretacao": interp,
    }


# ---------------------------------------------------------------------------
# Classificação e resumo
# ---------------------------------------------------------------------------
def _classificar(completude, n_neg, n_noite, envelope, fechamento, concord, n):
    problemas = False
    atencao = False

    if completude < 90:
        problemas = True
    elif completude < 99:
        atencao = True

    if n_neg > 0:
        atencao = True
    if n_noite > 0:
        atencao = True

    if envelope and envelope["n_avaliado"]:
        # Poucas violações perto do nascer/pôr do sol são normais; muitas indicam
        # problema. Por isso só é "Problemas" acima de 15% dos pontos avaliados.
        frac = envelope["n_violacoes"] / max(1, envelope["n_avaliado"])
        if frac > 0.15:
            problemas = True
        elif envelope["n_violacoes"] > 0:
            atencao = True

    if fechamento["aplicavel"] and fechamento["n_avaliado"]:
        frac = fechamento["n_fora"] / max(1, fechamento["n_avaliado"])
        if frac > 0.30:
            problemas = True
        elif fechamento["n_fora"] > 0:
            atencao = True

    if concord and not np.isnan(concord["rmse_rel_pct"]) and concord["rmse_rel_pct"] > 15:
        atencao = True

    if problemas:
        return "Problemas"
    if atencao:
        return "Atenção"
    return "OK"


def _montar_resumo(
    status, completude, total_esp, total_pres, lacunas, n_neg, n_noite,
    envelope, fechamento, concord,
) -> str:
    linhas = [f"Status geral: {status}."]
    linhas.append(
        f"Completude: {completude:.1f}% ({total_pres}/{total_esp} instantes com "
        f"dado). Lacunas: {len(lacunas)}."
    )
    linhas.append(
        f"Valores negativos (abaixo do ruído): {n_neg}. "
        f"Valores suspeitos à noite: {n_noite}."
    )
    if envelope is None:
        linhas.append("Envelope de céu limpo: não aplicável (sem real + céu limpo).")
    else:
        linhas.append(
            f"Envelope de céu limpo: {envelope['n_violacoes']} violação(ões) em "
            f"{envelope['n_avaliado']} pontos (tol. {envelope['tolerancia']:.0%}); "
            f"maior excesso {envelope['excesso_max_rel']:.1%}."
        )
    if not fechamento["aplicavel"]:
        linhas.append(f"Fechamento GHI=DHI+DNI·cosθz: {fechamento['status']}.")
    else:
        linhas.append(
            f"Fechamento GHI=DHI+DNI·cosθz: {fechamento['status']} "
            f"({fechamento['n_fora']} fora de tolerância em "
            f"{fechamento['n_avaliado']} pontos avaliados)."
        )
    if concord is None:
        linhas.append("Concordância McClear×NASA: não aplicável (só uma fonte).")
    else:
        linhas.append(
            f"Concordância McClear×NASA (céu limpo): RMSE {concord['rmse']:.1f}, "
            f"RMSE rel. {concord['rmse_rel_pct']:.1f}% ({concord['interpretacao']}), "
            f"viés {concord['mbe']:.1f}, r {concord['r']:.3f}, n={concord['n']}."
        )
    return "\n".join(linhas)
