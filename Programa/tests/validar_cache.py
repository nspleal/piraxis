"""
tests/validar_cache.py
======================

Comprova o comportamento cache-first do cliente CAMS: a SEGUNDA extração
idêntica faz ZERO requisições reais à API, medido pelo contador interno
``CamsMcClear.chamadas_reais_api``.

Precisa do e-mail SoDa + internet para a 1ª extração (que popula o cache).
Sem e-mail, o item é PULADO.

Uso:
    python tests/validar_cache.py [--email voce@dominio.com]
"""

from __future__ import annotations

import sys
from pathlib import Path

_RAIZ = Path(__file__).resolve().parent.parent
if str(_RAIZ) not in sys.path:
    sys.path.insert(0, str(_RAIZ))

from tests._comum import (  # type: ignore
    APROVADO,
    PULADO,
    REPROVADO,
    PASSO_PADRAO,
    obter_email,
    periodo_padrao,
)

from core.config import BOTUCATU
from sources.cams_mcclear import CamsMcClear


def executar(email: str | None = None) -> tuple[str, str]:
    if email is None:
        email = obter_email()
    if not email:
        return PULADO, "sem e-mail SoDa (config/SODA_EMAIL/--email)"

    inicio, fim = periodo_padrao()
    fonte = CamsMcClear(email)

    CamsMcClear.resetar_contador()
    try:
        df1 = fonte.buscar(BOTUCATU, inicio, fim, PASSO_PADRAO)  # 1ª (pode baixar)
        n_apos_1 = CamsMcClear.chamadas_reais_api
        df2 = fonte.buscar(BOTUCATU, inicio, fim, PASSO_PADRAO)  # 2ª (cache)
        n_apos_2 = CamsMcClear.chamadas_reais_api
    except Exception as exc:  # noqa: BLE001
        return REPROVADO, f"extração falhou: {exc}"

    delta_segunda = n_apos_2 - n_apos_1
    iguais = df1.equals(df2)
    print(
        f"      - chamadas reais após 1ª={n_apos_1}, após 2ª={n_apos_2} "
        f"(2ª adicionou {delta_segunda})"
    )
    print(f"      - {'OK ' if iguais else 'FALHA'} resultados idênticos nas duas leituras")

    if delta_segunda != 0:
        return REPROVADO, f"2ª extração fez {delta_segunda} chamada(s) à API"
    if not iguais:
        return REPROVADO, "resultados diferentes entre 1ª e 2ª leitura"
    return APROVADO, "2ª extração usou o cache (zero chamadas à API)"


if __name__ == "__main__":
    status, detalhe = executar()
    print(f"\nvalidar_cache: {status} — {detalhe}")
    sys.exit(0 if status in (APROVADO, PULADO) else 1)
