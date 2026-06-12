"""
tests/rodar_validacao_completa.py
=================================

Orquestrador da suíte de validação da migração para pvlib. Executa, em
sequência, os cinco validadores e imprime um relatório consolidado
(APROVADO / REPROVADO / PULADO por item + resumo final).

E-mail SoDa: config (~/.radiacao_solar/config.json) > SODA_EMAIL > --email.
Todos os validadores reutilizam o MESMO período de 3 dias, então o cache
absorve as repetições e a suíte faz no máximo ~1–2 requisições reais à API.

Códigos de saída:
    0  -> nenhum item REPROVADO (pode haver PULADO por falta de e-mail/rede)
    1  -> ao menos um item REPROVADO

Uso:
    python tests/rodar_validacao_completa.py [--email voce@dominio.com] [--com-radiation]
"""

from __future__ import annotations

import sys
from pathlib import Path

_RAIZ = Path(__file__).resolve().parent.parent
if str(_RAIZ) not in sys.path:
    sys.path.insert(0, str(_RAIZ))

from tests import (  # type: ignore
    validar_app,
    validar_boot,
    validar_cache,
    validar_extracao,
    validar_pipeline,
)
from tests._comum import APROVADO, PULADO, REPROVADO, imprimir_item, obter_email

# Ordem de execução e rótulo de cada validador.
VALIDADORES = [
    ("Extração direta + sanidade física (validar_extracao)", validar_extracao),
    ("Pipeline -> Excel + erros amigáveis (validar_pipeline)", validar_pipeline),
    ("Cache-first por contador (validar_cache)", validar_cache),
    ("Fluxo do usuário via AppTest (validar_app)", validar_app),
    ("Boot do app + health-check (validar_boot)", validar_boot),
]


def main() -> int:
    email = obter_email()
    print("=" * 70)
    print("  SUÍTE DE VALIDAÇÃO — Migração CAMS para pvlib")
    print("=" * 70)
    print(f"  E-mail SoDa: {email or '(não configurado — itens de API serão PULADOS)'}")
    print("-" * 70)

    resultados: list[tuple[str, str, str]] = []
    for titulo, modulo in VALIDADORES:
        print(f"\n► {titulo}")
        try:
            status, detalhe = modulo.executar(email)
        except Exception as exc:  # noqa: BLE001 - um validador nunca derruba a suíte
            status, detalhe = REPROVADO, f"erro inesperado: {exc}"
        imprimir_item(titulo, status, detalhe)
        resultados.append((titulo, status, detalhe))

    # Relatório consolidado.
    print("\n" + "=" * 70)
    print("  RELATÓRIO CONSOLIDADO")
    print("=" * 70)
    n_aprov = sum(1 for _, s, _ in resultados if s == APROVADO)
    n_pulado = sum(1 for _, s, _ in resultados if s == PULADO)
    n_reprov = sum(1 for _, s, _ in resultados if s == REPROVADO)
    for titulo, status, detalhe in resultados:
        imprimir_item(titulo, status, detalhe)
    print("-" * 70)
    print(f"  APROVADO: {n_aprov}   PULADO: {n_pulado}   REPROVADO: {n_reprov}")

    if n_reprov:
        print("\n  RESULTADO FINAL: ✗ REPROVADO (corrija os itens acima).")
        return 1
    if n_pulado:
        print(
            "\n  RESULTADO FINAL: ✓ sem reprovações, mas há itens PULADOS por "
            "falta de e-mail/rede.\n  Rode novamente na máquina do pesquisador "
            "(com a conta SoDa configurada) para a validação 100% real."
        )
        return 0
    print("\n  RESULTADO FINAL: ✓ APROVADO — 100% das verificações passaram.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
