"""
core/pipeline.py
================

Função de extração ponta-a-ponta SEM interface (headless): McClear -> Excel.

Existe para que scripts de validação (e usos automatizados futuros) possam
exercitar o mesmo caminho lógico da interface — extrair, combinar e exportar —
sem subir o Streamlit. A interface continua intacta; ela apenas compartilha as
mesmas peças (CamsMcClear, combinar, exporta) que esta função orquestra.
"""

from __future__ import annotations

from datetime import date
from pathlib import Path

import pandas as pd

from core.combinador import combinar
from core.config import BOTUCATU, PASSOS_TEMPORAIS
from core.qualidade import analisar_qualidade
from core.reprodutibilidade import gerar_reprodutibilidade
from output.exporta_excel import exporta, nome_arquivo_saida
from sources.cams_mcclear import CamsMcClear

# Rótulo amigável -> código ISO, para montar os metadados como na interface.
_ROTULO_POR_CODIGO = {codigo: rotulo for rotulo, codigo in PASSOS_TEMPORAIS.items()}


def extrair_mcclear_para_excel(
    email: str,
    data_inicio: date,
    data_fim: date,
    passo_temporal: str = "PT01H",
    local=BOTUCATU,
    identifier: str = "mcclear",
    caminho_saida: str | Path | None = None,
) -> tuple[Path, pd.DataFrame]:
    """Extrai o CAMS McClear e gera a planilha Excel, devolvendo (caminho, df).

    Reaproveita exatamente o cliente, o combinador e o exportador usados pela
    interface — só sem a camada visual.
    """
    fonte = CamsMcClear(email, identifier=identifier)
    df = fonte.buscar(local, data_inicio, data_fim, passo_temporal)
    combinado = combinar({fonte.nome: df}, {fonte.nome: passo_temporal})

    rotulo = _ROTULO_POR_CODIGO.get(passo_temporal, passo_temporal)
    metadados = {
        "local": local.nome,
        "latitude": local.latitude,
        "longitude": local.longitude,
        "altitude": local.altitude,
        "periodo": f"{data_inicio:%d/%m/%Y} a {data_fim:%d/%m/%Y}",
        "fontes": fonte.nome,
        "passo_temporal": rotulo,
        # Sem "email_soda": credencial pessoal não entra em saída compartilhável.
    }

    # Controle de qualidade + reprodutibilidade (mesmo caminho da interface).
    bases = [c for c in combinado.columns if c not in ("timestamp", "kt")]
    relatorio_qc = analisar_qualidade(
        combinado, local, passo_temporal, [fonte.nome]
    )
    repro = gerar_reprodutibilidade(
        local, data_inicio, data_fim, passo_temporal, rotulo, [fonte.nome], bases
    )

    if caminho_saida is None:
        caminho_saida = nome_arquivo_saida(local.nome, data_inicio, data_fim)
    caminho = exporta(
        combinado, metadados, caminho_saida,
        relatorio_qc=relatorio_qc, reprodutibilidade=repro,
    )
    return caminho, combinado
