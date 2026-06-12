"""
tests/_comum.py
===============

Utilidades compartilhadas pelos scripts de validação (validar_*.py).

Inclui:
  - resolução do e-mail SoDa: config (~/.radiacao_solar/config.json) > variável
    de ambiente SODA_EMAIL > argumento de linha de comando --email;
  - o PERÍODO PADRÃO de 3 dias (terminando há ≥3 dias) usado por TODOS os
    scripts, para que o cache absorva as repetições e a suíte faça no máximo
    ~1-2 requisições reais à API;
  - status padronizados (APROVADO / REPROVADO / PULADO) e um helper de impressão.

Os scripts garantem a raiz do projeto (a pasta "Programa") no sys.path.
"""

from __future__ import annotations

import os
import sys
from datetime import date, timedelta
from pathlib import Path

# Garante a raiz do projeto (pasta acima de tests/) no sys.path.
RAIZ = Path(__file__).resolve().parent.parent
if str(RAIZ) not in sys.path:
    sys.path.insert(0, str(RAIZ))

from core import credenciais  # noqa: E402  (após ajustar o sys.path)

# Status possíveis de cada verificação.
APROVADO = "APROVADO"
REPROVADO = "REPROVADO"
PULADO = "PULADO"

# Passo temporal padrão da validação.
PASSO_PADRAO = "PT01H"


def periodo_padrao() -> tuple[date, date]:
    """Período de 3 dias terminando há ≥3 dias (dados sempre disponíveis).

    Ex.: (hoje-5, hoje-3). São 3 dias inteiros -> 72 instantes horários.
    """
    fim = date.today() - timedelta(days=3)
    inicio = fim - timedelta(days=2)
    return inicio, fim


def obter_email(argv: list[str] | None = None) -> str | None:
    """Resolve o e-mail SoDa: config > SODA_EMAIL > --email <valor>.

    Retorna None se nenhum e-mail válido for encontrado.
    """
    argv = sys.argv if argv is None else argv

    # 1) argumento de linha de comando --email valor  ou  --email=valor
    for i, arg in enumerate(argv):
        if arg == "--email" and i + 1 < len(argv):
            cand = argv[i + 1]
            if credenciais.email_valido(cand):
                return cand.strip()
        if arg.startswith("--email="):
            cand = arg.split("=", 1)[1]
            if credenciais.email_valido(cand):
                return cand.strip()

    # 2) variável de ambiente
    cand = os.getenv("SODA_EMAIL")
    if credenciais.email_valido(cand):
        return cand.strip()

    # 3) configuração salva na máquina
    cand = credenciais.carregar_email()
    if credenciais.email_valido(cand):
        return cand
    return None


def imprimir_item(nome: str, status: str, detalhe: str = "") -> None:
    """Imprime uma linha padronizada de resultado."""
    simbolo = {APROVADO: "✓", REPROVADO: "✗", PULADO: "—"}.get(status, "?")
    linha = f"  [{simbolo}] {status:<9} {nome}"
    if detalhe:
        linha += f"  ({detalhe})"
    print(linha)
