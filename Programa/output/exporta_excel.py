"""
output/exporta_excel.py
=======================

Geração da planilha Excel (.xlsx) formatada profissionalmente, com até três
abas:

  - "Resumo": metadados do estudo + estatísticas (média/máx/mín) calculadas
    com FÓRMULAS Excel (=AVERAGE/=MAX/=MIN), nunca valores hardcoded.
  - "Dados": a série temporal completa (uma linha por timestamp).
  - "Comparação": só quando há duas fontes — índice de claridade e diferença
    McClear vs NASA, com gráfico de linha nativo do Excel.

Formatação: cabeçalhos com fundo azul (1F5C8B) e texto branco em negrito,
fonte Arial, painel congelado no cabeçalho, larguras ajustadas, datas em
DD/MM/AAAA HH:MM e números com 1 casa decimal.
"""

from __future__ import annotations

import logging
from datetime import datetime
from pathlib import Path

import pandas as pd
from openpyxl import Workbook
from openpyxl.chart import LineChart, Reference
from openpyxl.styles import Alignment, Font, PatternFill
from openpyxl.utils import get_column_letter
from openpyxl.worksheet.worksheet import Worksheet

from core.config import OUTPUT_DIR

logger = logging.getLogger(__name__)

# Paleta e estilos de formatação.
AZUL_CABECALHO = "1F5C8B"
FONTE_NOME = "Arial"
FORMATO_DATA = "DD/MM/YYYY HH:MM"
FORMATO_NUMERO = "0.0"

_fill_cabecalho = PatternFill("solid", fgColor=AZUL_CABECALHO)
_fonte_cabecalho = Font(name=FONTE_NOME, bold=True, color="FFFFFF")
_fonte_normal = Font(name=FONTE_NOME)
_centro = Alignment(horizontal="center", vertical="center")


def exporta(df: pd.DataFrame, metadados: dict, caminho_saida: str | Path) -> Path:
    """Gera o arquivo .xlsx com as abas Resumo/Dados/(Comparação).

    Parâmetros
    ----------
    df:
        DataFrame combinado (com coluna ``timestamp`` e colunas de componentes).
    metadados:
        Dicionário com chaves como local, latitude, longitude, altitude,
        periodo, fontes, passo_temporal, email_soda.
    caminho_saida:
        Caminho do arquivo .xlsx a gerar.

    Retorna o ``Path`` do arquivo gerado.
    """
    caminho_saida = Path(caminho_saida)
    caminho_saida.parent.mkdir(parents=True, exist_ok=True)

    wb = Workbook()

    # A aba de Dados é a base para as referências de fórmula do Resumo.
    aba_dados = wb.active
    aba_dados.title = "Dados"
    colunas_numericas = _escrever_dados(aba_dados, df)

    aba_resumo = wb.create_sheet("Resumo", index=0)
    _escrever_resumo(aba_resumo, df, metadados, colunas_numericas, len(df))

    # Aba de comparação apenas se houver índice de claridade (duas fontes).
    if "kt" in df.columns:
        aba_comp = wb.create_sheet("Comparação")
        _escrever_comparacao(aba_comp, df)

    wb.save(caminho_saida)
    logger.info("Planilha gerada em %s.", caminho_saida)
    return caminho_saida


# ---------------------------------------------------------------------------
def _estilizar_cabecalho(ws: Worksheet, n_colunas: int, linha: int = 1) -> None:
    """Aplica o estilo de cabeçalho a uma linha e congela abaixo dela."""
    for col in range(1, n_colunas + 1):
        celula = ws.cell(row=linha, column=col)
        celula.fill = _fill_cabecalho
        celula.font = _fonte_cabecalho
        celula.alignment = _centro
    ws.freeze_panes = ws.cell(row=linha + 1, column=1)


def _ajustar_larguras(ws: Worksheet, larguras: dict[int, int]) -> None:
    for col, largura in larguras.items():
        ws.column_dimensions[get_column_letter(col)].width = largura


def _escrever_dados(ws: Worksheet, df: pd.DataFrame) -> list[str]:
    """Escreve a série temporal na aba Dados. Retorna as colunas numéricas."""
    colunas = list(df.columns)
    # Cabeçalho.
    for j, nome in enumerate(colunas, start=1):
        ws.cell(row=1, column=j, value=nome)
    _estilizar_cabecalho(ws, len(colunas))

    colunas_numericas: list[str] = []
    for nome in colunas:
        if nome != "timestamp" and pd.api.types.is_numeric_dtype(df[nome]):
            colunas_numericas.append(nome)

    # Linhas de dados.
    for i, (_, linha) in enumerate(df.iterrows(), start=2):
        for j, nome in enumerate(colunas, start=1):
            valor = linha[nome]
            celula = ws.cell(row=i, column=j)
            if nome == "timestamp":
                ts = pd.to_datetime(valor)
                celula.value = ts.to_pydatetime() if not pd.isna(ts) else None
                celula.number_format = FORMATO_DATA
            else:
                # NaN -> célula vazia (não inventar zeros).
                celula.value = None if pd.isna(valor) else float(valor)
                celula.number_format = FORMATO_NUMERO
            celula.font = _fonte_normal

    # Larguras: timestamp mais larga, demais médias.
    larguras = {1: 20}
    for j in range(2, len(colunas) + 1):
        larguras[j] = 16
    _ajustar_larguras(ws, larguras)

    return colunas_numericas


def _escrever_resumo(
    ws: Worksheet,
    df: pd.DataFrame,
    metadados: dict,
    colunas_numericas: list[str],
    n_linhas_dados: int,
) -> None:
    """Escreve metadados e estatísticas (com fórmulas Excel) na aba Resumo."""
    ws.cell(row=1, column=1, value="Relatório de Radiação Solar")
    ws.cell(row=1, column=1).font = Font(name=FONTE_NOME, bold=True, size=14)

    # Bloco de metadados.
    linhas_meta = [
        ("Local", metadados.get("local", "")),
        ("Latitude", metadados.get("latitude", "")),
        ("Longitude", metadados.get("longitude", "")),
        ("Altitude (m)", metadados.get("altitude", "")),
        ("Período", metadados.get("periodo", "")),
        ("Fontes usadas", metadados.get("fontes", "")),
        ("Passo temporal", metadados.get("passo_temporal", "")),
        ("E-mail SoDa usado", metadados.get("email_soda", "(não aplicável)")),
        (
            "Data de geração",
            metadados.get(
                "data_geracao", datetime.now().strftime("%d/%m/%Y %H:%M")
            ),
        ),
    ]
    linha = 3
    for rotulo, valor in linhas_meta:
        ws.cell(row=linha, column=1, value=rotulo).font = Font(
            name=FONTE_NOME, bold=True
        )
        ws.cell(row=linha, column=2, value=valor).font = _fonte_normal
        linha += 1

    # Tabela de estatísticas com fórmulas Excel referenciando a aba Dados.
    linha += 1
    cab_stats = ["Componente", "Média", "Máximo", "Mínimo"]
    for j, nome in enumerate(cab_stats, start=1):
        ws.cell(row=linha, column=j, value=nome)
    _estilizar_cabecalho(ws, len(cab_stats), linha=linha)
    linha_cab_stats = linha
    linha += 1

    # Mapa nome de coluna -> letra na aba Dados.
    colunas_dados = list(df.columns)
    primeira_dado = 2
    ultima_dado = n_linhas_dados + 1  # +1 por causa do cabeçalho
    for nome in colunas_numericas:
        idx = colunas_dados.index(nome) + 1
        letra = get_column_letter(idx)
        intervalo = f"Dados!{letra}{primeira_dado}:{letra}{ultima_dado}"
        ws.cell(row=linha, column=1, value=nome).font = _fonte_normal
        # Fórmulas Excel (não valores hardcoded).
        if n_linhas_dados > 0:
            ws.cell(row=linha, column=2, value=f"=AVERAGE({intervalo})")
            ws.cell(row=linha, column=3, value=f"=MAX({intervalo})")
            ws.cell(row=linha, column=4, value=f"=MIN({intervalo})")
        for col in (2, 3, 4):
            ws.cell(row=linha, column=col).number_format = FORMATO_NUMERO
            ws.cell(row=linha, column=col).font = _fonte_normal
        linha += 1

    _ajustar_larguras(ws, {1: 28, 2: 14, 3: 14, 4: 14})
    # Congela abaixo do cabeçalho de estatísticas para facilitar leitura.
    ws.freeze_panes = ws.cell(row=linha_cab_stats + 1, column=1)


def _escrever_comparacao(ws: Worksheet, df: pd.DataFrame) -> None:
    """Escreve a aba Comparação: kt, diferença McClear vs NASA, e gráfico."""
    ghi_mc = "GHI_McClear"
    ghi_nasa = "GHI_NASA"

    colunas = ["timestamp"]
    if ghi_mc in df.columns:
        colunas.append(ghi_mc)
    if ghi_nasa in df.columns:
        colunas.append(ghi_nasa)
    colunas.append("kt")

    # Cabeçalho (inclui coluna calculada de diferença).
    cabecalho = list(colunas) + ["Diferenca_McClear_menos_NASA"]
    for j, nome in enumerate(cabecalho, start=1):
        ws.cell(row=1, column=j, value=nome)
    _estilizar_cabecalho(ws, len(cabecalho))

    idx_mc = colunas.index(ghi_mc) + 1 if ghi_mc in colunas else None
    idx_nasa = colunas.index(ghi_nasa) + 1 if ghi_nasa in colunas else None
    col_dif = len(cabecalho)

    for i, (_, linha_df) in enumerate(df.iterrows(), start=2):
        for j, nome in enumerate(colunas, start=1):
            valor = linha_df[nome]
            celula = ws.cell(row=i, column=j)
            if nome == "timestamp":
                ts = pd.to_datetime(valor)
                celula.value = ts.to_pydatetime() if not pd.isna(ts) else None
                celula.number_format = FORMATO_DATA
            else:
                celula.value = None if pd.isna(valor) else float(valor)
                celula.number_format = FORMATO_NUMERO
            celula.font = _fonte_normal
        # Diferença via fórmula Excel, quando ambas as colunas existem.
        if idx_mc and idx_nasa:
            la, lb = get_column_letter(idx_mc), get_column_letter(idx_nasa)
            celula = ws.cell(row=i, column=col_dif, value=f"={la}{i}-{lb}{i}")
            celula.number_format = FORMATO_NUMERO
            celula.font = _fonte_normal

    _ajustar_larguras(
        ws, {j: (20 if j == 1 else 22) for j in range(1, len(cabecalho) + 1)}
    )

    # Gráfico de linha nativo do Excel: GHI das duas fontes ao longo do tempo.
    n_linhas = len(df)
    if n_linhas > 0 and idx_mc and idx_nasa:
        grafico = LineChart()
        grafico.title = "GHI: McClear (céu limpo) vs NASA (real)"
        grafico.y_axis.title = "Wh/m²"
        grafico.x_axis.title = "Tempo"
        dados = Reference(
            ws, min_col=idx_mc, max_col=idx_nasa, min_row=1, max_row=n_linhas + 1
        )
        categorias = Reference(ws, min_col=1, min_row=2, max_row=n_linhas + 1)
        grafico.add_data(dados, titles_from_data=True)
        grafico.set_categories(categorias)
        grafico.height = 10
        grafico.width = 24
        ws.add_chart(grafico, f"{get_column_letter(col_dif + 2)}2")


def nome_arquivo_saida(local: str, data_inicio, data_fim) -> Path:
    """Monta o caminho padrão de saída: radiacao_<local>_<ini>_<fim>.xlsx."""
    local_limpo = "".join(
        c if c.isalnum() else "_" for c in str(local)
    ).strip("_") or "local"
    nome = f"radiacao_{local_limpo}_{data_inicio}_{data_fim}.xlsx"
    return OUTPUT_DIR / nome
