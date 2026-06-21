"""
output/exporta_excel.py
=======================

Geração da planilha Excel (.xlsx) no formato do MODELO oficial do projeto
(planilha_modelo_para_IC.xlsx, fornecido pelo pesquisador). Toda extração gera
exatamente esta estrutura, com duas abas:

  - "Resumo":
      · título "Relatório de Radiação Solar" (A1:D1, fundo azul 1F5C8B);
      · subtítulo dinâmico ``=B4&" • "&B8`` (Local • Período);
      · bloco "Informações Gerais" (Local, Latitude, Longitude, Altitude,
        Período, Fontes usadas, Passo temporal, E-mail SoDa, Data de geração);
      · tabela "Estatísticas de Radiação" com FÓRMULAS Excel sobre a tabela
        estruturada TabDados: Média (AVERAGE), Média Diurna (AVERAGEIF >0),
        Máximo (MAX), Mínimo Diurno (MINIFS >0), Energia (SUM) e kWh/m²/dia;
      · legenda dos componentes;
      · gráfico de barras "Comparativo de Radiação por Componente".

  - "Dados":
      · tabela ESTRUTURADA do Excel chamada ``TabDados`` (estilo
        TableStyleMedium9, listras de linha), colunas "Timestamp" +
        "<COMPONENTE> (W/m²)" — é ela que as fórmulas do Resumo referenciam;
      · tabela auxiliar de Energia Diária (SUMIFS por dia) a partir de G24;
      · gráfico de linha da radiação ao longo do tempo;
      · gráfico de barras de Energia Diária.

Adaptações dinâmicas (o modelo foi desenhado para CAMS McClear horário com
GHI/DNI/DHI/BHI; o exportador generaliza sem mudar o visual):
  - as linhas de estatística acompanham os componentes presentes no DataFrame
    (ex.: extração só NASA, ou combinada com sufixos por fonte);
  - a coluna ``kt`` (índice de claridade, adimensional) entra na TabDados mas
    fica FORA da tabela de estatísticas em W/m² (não faz sentido físico lá);
  - unidade dos rótulos: no passo HORÁRIO os valores integrados (Wh/m² por
    hora) são numericamente iguais à irradiância média em W/m², e o modelo usa
    "(W/m²)" — mantido. Nos demais passos o rótulo vira "(Wh/m²)", que é a
    unidade verdadeira dos valores por passo;
  - o divisor do kWh/m²/dia acompanha o passo (24 passos/dia no horário,
    96 no de 15 min, 1440 no de 1 min, 1 no diário; no mensal usa o nº de
    dias do período calculado em Python);
  - a tabela/gráfico de Energia Diária usa as duas primeiras colunas de
    radiação (preferindo GHI e DNI) e uma linha por dia do período; é omitida
    no passo mensal.

A antiga aba "Comparação" foi aposentada pelo modelo: na extração combinada,
as colunas por fonte e o kt continuam disponíveis na própria TabDados.
"""

from __future__ import annotations

import logging
from datetime import datetime
from pathlib import Path

import pandas as pd
from openpyxl import Workbook
from openpyxl.chart import BarChart, LineChart, Reference
from openpyxl.chart.shapes import GraphicalProperties
from openpyxl.drawing.line import LineProperties
from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
from openpyxl.utils import get_column_letter
from openpyxl.worksheet.table import Table, TableStyleInfo
from openpyxl.worksheet.worksheet import Worksheet

from core.config import OUTPUT_DIR

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Paleta e estilos do modelo
# ---------------------------------------------------------------------------
AZUL_CABECALHO = "1F5C8B"   # fundo dos títulos/cabeçalhos
AZUL_TITULO = "FF1F5C8B"    # cor de fonte dos títulos de seção
CINZA_TEXTO = "FF595959"    # subtítulo e legenda
ZEBRA = "EAF1F8"            # listra alternada da tabela de estatísticas
FONTE = "Arial"

FORMATO_TIMESTAMP = "m/d/yy h:mm"   # formato 22 do Excel: exibe conforme o
                                    # idioma do sistema (dd/mm/aaaa hh:mm no
                                    # Windows em português)
FORMATO_VALOR = "0.0"
# Valores de radiação na tabela e nas estatísticas: 4 casas decimais (a mesma
# precisão da fonte SoDa/McClear), para mostrar os dados EXATOS — sem arredondar
# para 1 casa. O valor guardado na célula sempre foi exato; isto é só a exibição.
FORMATO_DADOS = "0.0000"
FORMATO_ENERGIA = "#,##0"
FORMATO_KWH = "0.00"
FORMATO_DIA = "dd/mm"

_fill_azul = PatternFill("solid", fgColor=f"FF{AZUL_CABECALHO}")
_fill_zebra = PatternFill("solid", fgColor=f"FF{ZEBRA}")
_fonte_cab = Font(name=FONTE, size=11, bold=True, color="FFFFFF")
_fonte_normal = Font(name=FONTE, size=11)
_fonte_rotulo = Font(name=FONTE, size=11, bold=True)
_fonte_titulo = Font(name=FONTE, size=16, bold=True, color="FFFFFF")
_fonte_secao = Font(name=FONTE, size=12, bold=True, color=AZUL_TITULO)
_fonte_sub = Font(name=FONTE, size=10, italic=True, color=CINZA_TEXTO)
_fonte_legenda = Font(name=FONTE, size=9, italic=True, color=CINZA_TEXTO)
_centro = Alignment(horizontal="center")
_centro_total = Alignment(horizontal="center", vertical="center")
_vcentro = Alignment(vertical="center")
_lado = Side(style="thin")
_borda_fina = Border(top=_lado, bottom=_lado, left=_lado, right=_lado)

# Largura de linha das séries do gráfico temporal (EMU; 28575 = 2,25 pt).
LARGURA_LINHA_GRAFICO = 28575

# Limite de linhas da tabela de Energia Diária (1 ano), por sanidade visual.
MAX_DIAS_ENERGIA = 366


# ---------------------------------------------------------------------------
# Inferência do passo temporal a partir dos timestamps
# ---------------------------------------------------------------------------
def _inferir_passo(ts: pd.Series) -> str:
    """Retorna o passo inferido dos timestamps: 1min/15min/1h/1d/1M."""
    if len(ts) < 2:
        return "1h"
    delta = pd.to_datetime(ts).diff().dropna().mode()
    minutos = delta.iloc[0].total_seconds() / 60 if len(delta) else 60
    if minutos <= 1.5:
        return "1min"
    if minutos <= 30:
        return "15min"
    if minutos <= 120:
        return "1h"
    if minutos <= 2 * 1440:
        return "1d"
    return "1M"


def _rotulo_coluna(col: str, unidade: str) -> str:
    """Rótulo de coluna no padrão do modelo: 'GHI (W/m²)'; kt fica sem unidade."""
    if col == "kt":
        return "kt"
    return f"{col} ({unidade})"


# ---------------------------------------------------------------------------
# Função principal
# ---------------------------------------------------------------------------
def exporta(
    df: pd.DataFrame,
    metadados: dict,
    caminho_saida: str | Path,
    relatorio_qc=None,
    reprodutibilidade=None,
) -> Path:
    """Gera o .xlsx no formato do modelo oficial. Retorna o Path gerado.

    Parâmetros opcionais:
      - ``relatorio_qc``: um ``core.qualidade.RelatorioQC``; se presente, gera a
        aba "Qualidade".
      - ``reprodutibilidade``: um ``core.reprodutibilidade.Reprodutibilidade``;
        se presente, gera a aba "Reprodutibilidade".
    As abas existentes (Resumo, Dados) não são alteradas por esses parâmetros.
    """
    caminho_saida = Path(caminho_saida)
    caminho_saida.parent.mkdir(parents=True, exist_ok=True)

    df = df.copy()
    if "timestamp" in df.columns:
        df["timestamp"] = pd.to_datetime(df["timestamp"])

    # Colunas numéricas na ordem do DataFrame; kt separado das de radiação.
    colunas_numericas = [
        c
        for c in df.columns
        if c != "timestamp" and pd.api.types.is_numeric_dtype(df[c])
    ]
    componentes = [c for c in colunas_numericas if c != "kt"]

    passo = _inferir_passo(
        df["timestamp"] if "timestamp" in df.columns else pd.Series(dtype="datetime64[ns]")
    )
    # No passo horário o modelo rotula em W/m² (≡ Wh/m² por hora); nos demais,
    # a unidade verdadeira dos valores integrados por passo é Wh/m².
    unidade = "W/m²" if passo == "1h" else "Wh/m²"

    n_dias = 1
    if "timestamp" in df.columns and df["timestamp"].notna().any():
        ts = df["timestamp"].dropna()
        fim = ts.max().normalize()
        if passo == "1M":
            # No passo mensal o timestamp marca o INÍCIO do mês; o período
            # coberto vai até o fim do último mês.
            fim = fim + pd.offsets.MonthEnd(0)
        n_dias = max(1, (fim - ts.min().normalize()).days + 1)

    wb = Workbook()
    aba_dados = wb.active
    aba_dados.title = "Dados"
    rotulos = _escrever_dados(
        aba_dados, df, colunas_numericas, componentes, unidade, passo, n_dias
    )

    aba_resumo = wb.create_sheet("Resumo", index=0)
    _escrever_resumo(
        aba_resumo,
        metadados,
        componentes,
        unidade,
        passo,
        n_dias,
        rotulos,
        tem_dados=len(df) > 0,
    )

    # Abas novas (QC e reprodutibilidade), sem tocar nas existentes.
    if relatorio_qc is not None:
        _escrever_qualidade(wb.create_sheet("Qualidade"), relatorio_qc)
    if reprodutibilidade is not None:
        _escrever_reprodutibilidade(
            wb.create_sheet("Reprodutibilidade"), reprodutibilidade
        )

    wb.active = 0
    wb.save(caminho_saida)
    logger.info("Planilha (modelo IC) gerada em %s.", caminho_saida)
    return caminho_saida


# ---------------------------------------------------------------------------
# Aba "Dados"
# ---------------------------------------------------------------------------
def _escrever_dados(
    ws: Worksheet,
    df: pd.DataFrame,
    colunas_numericas: list[str],
    componentes: list[str],
    unidade: str,
    passo: str,
    n_dias: int,
) -> dict[str, str]:
    """Escreve a TabDados, a tabela de Energia Diária e os dois gráficos."""
    rotulos = {c: _rotulo_coluna(c, unidade) for c in colunas_numericas}
    cabecalho = ["Timestamp"] + [rotulos[c] for c in colunas_numericas]
    n_linhas = len(df)

    # --- Cabeçalho (branco/negrito sobre azul, centralizado) ----------------
    for j, nome in enumerate(cabecalho, start=1):
        cel = ws.cell(row=1, column=j, value=nome)
        cel.font = _fonte_cab
        cel.fill = _fill_azul
        cel.alignment = _centro

    # --- Linhas de dados (NaN -> célula vazia, nunca zero inventado) --------
    for i, (_, linha) in enumerate(df.iterrows(), start=2):
        cel = ws.cell(row=i, column=1)
        ts = pd.to_datetime(linha.get("timestamp"))
        cel.value = None if pd.isna(ts) else ts.to_pydatetime()
        cel.number_format = FORMATO_TIMESTAMP
        cel.font = _fonte_normal
        for j, col in enumerate(colunas_numericas, start=2):
            valor = linha[col]
            cel = ws.cell(row=i, column=j)
            cel.value = None if pd.isna(valor) else float(valor)
            cel.number_format = FORMATO_DADOS
            cel.font = _fonte_normal

    # --- Tabela estruturada TabDados (referenciada pelas fórmulas) ----------
    ultima_linha = max(2, n_linhas + 1)
    ref = f"A1:{get_column_letter(len(cabecalho))}{ultima_linha}"
    tabela = Table(displayName="TabDados", ref=ref)
    tabela.tableStyleInfo = TableStyleInfo(
        name="TableStyleMedium9",
        showRowStripes=True,
        showColumnStripes=False,
        showFirstColumn=False,
        showLastColumn=False,
    )
    ws.add_table(tabela)

    ws.freeze_panes = "A2"
    ws.column_dimensions["A"].width = 24.7
    for j in range(2, len(cabecalho) + 1):
        ws.column_dimensions[get_column_letter(j)].width = 16.0

    # --- Tabela auxiliar de Energia Diária (G24 no modelo) ------------------
    # Usa as duas primeiras colunas de radiação, preferindo GHI e depois DNI.
    preferidas = [c for c in componentes if c.upper().startswith("GHI")]
    preferidas += [c for c in componentes if c.upper().startswith("DNI")]
    preferidas += [c for c in componentes if c not in preferidas]
    cols_energia = preferidas[:2]

    # G no modelo; desloca para a direita se a TabDados for mais larga.
    col_ini = max(7, len(cabecalho) + 2)
    letra_dia = get_column_letter(col_ini)
    linha_cab = 24
    gerar_energia = (
        passo != "1M" and bool(cols_energia) and n_linhas > 0
        and n_dias <= MAX_DIAS_ENERGIA
    )

    if gerar_energia:
        ws.column_dimensions[letra_dia].width = 13.3
        cel = ws.cell(row=linha_cab, column=col_ini, value="Dia")
        cel.font = _fonte_cab
        cel.fill = _fill_azul
        cel.alignment = _centro
        for k, col in enumerate(cols_energia, start=1):
            letra = get_column_letter(col_ini + k)
            ws.column_dimensions[letra].width = 20.0
            cel = ws.cell(row=linha_cab, column=col_ini + k, value=f"{col} (Wh/m²)")
            cel.font = _fonte_cab
            cel.fill = _fill_azul
            cel.alignment = _centro

        primeiro_dia = df["timestamp"].dropna().min()
        for d in range(n_dias):
            r = linha_cab + 1 + d
            cel = ws.cell(row=r, column=col_ini)
            if d == 0:
                cel.value = (
                    f"=DATE({primeiro_dia.year},{primeiro_dia.month},"
                    f"{primeiro_dia.day})"
                )
            else:
                cel.value = f"={letra_dia}{r - 1}+1"
            cel.number_format = FORMATO_DIA
            cel.font = _fonte_normal
            for k, col in enumerate(cols_energia, start=1):
                rot = rotulos[col]
                cel = ws.cell(row=r, column=col_ini + k)
                cel.value = (
                    f"=SUMIFS(TabDados[{rot}],"
                    f'TabDados[Timestamp],">="&${letra_dia}{r},'
                    f'TabDados[Timestamp],"<"&${letra_dia}{r}+1)'
                )
                cel.number_format = FORMATO_ENERGIA
                cel.font = _fonte_normal

    # --- Gráfico de linha: radiação ao longo do tempo -----------------------
    # Séries: até duas colunas, preferindo GHI* e depois DNI* (como no modelo).
    cols_linha = cols_energia
    if n_linhas > 0 and cols_linha:
        grafico = LineChart()
        nomes = " e ".join(cols_linha)
        titulo_passo = {
            "1min": "Radiação", "15min": "Radiação",
            "1h": "Radiação Horária", "1d": "Radiação Diária",
            "1M": "Radiação Mensal",
        }[passo]
        grafico.title = f"{titulo_passo} — {nomes} ({unidade})"
        grafico.legend.position = "b"
        grafico.height = 7.5
        grafico.width = 15
        grafico.y_axis.number_format = FORMATO_VALOR
        cats = Reference(ws, min_col=1, min_row=2, max_row=ultima_linha)
        for col in cols_linha:
            idx = colunas_numericas.index(col) + 2
            dados = Reference(ws, min_col=idx, min_row=1, max_row=ultima_linha)
            grafico.add_data(dados, titles_from_data=True)
        grafico.set_categories(cats)
        for serie in grafico.series:
            serie.smooth = False
            serie.graphicalProperties = GraphicalProperties(
                ln=LineProperties(w=LARGURA_LINHA_GRAFICO)
            )
        ws.add_chart(grafico, f"{letra_dia}2")

    # --- Gráfico de barras: Energia Diária -----------------------------------
    if gerar_energia:
        grafico = BarChart()
        grafico.type = "col"
        grafico.grouping = "clustered"
        grafico.gapWidth = 219
        grafico.overlap = -27
        grafico.title = "Energia Diária (Wh/m²)"
        grafico.legend.position = "b"
        grafico.height = 7.5
        grafico.width = 15
        grafico.y_axis.number_format = FORMATO_ENERGIA
        grafico.x_axis.number_format = FORMATO_DIA
        dados = Reference(
            ws,
            min_col=col_ini + 1,
            max_col=col_ini + len(cols_energia),
            min_row=linha_cab,
            max_row=linha_cab + n_dias,
        )
        cats = Reference(
            ws, min_col=col_ini, min_row=linha_cab + 1, max_row=linha_cab + n_dias
        )
        grafico.add_data(dados, titles_from_data=True)
        grafico.set_categories(cats)
        ws.add_chart(grafico, f"{get_column_letter(col_ini + 4)}{linha_cab}")

    return rotulos


# ---------------------------------------------------------------------------
# Aba "Resumo"
# ---------------------------------------------------------------------------
def _escrever_resumo(
    ws: Worksheet,
    metadados: dict,
    componentes: list[str],
    unidade: str,
    passo: str,
    n_dias: int,
    rotulos: dict[str, str],
    tem_dados: bool,
) -> None:
    """Escreve título, metadados, estatísticas (fórmulas TabDados) e gráfico."""
    # Larguras e alturas do modelo.
    for letra, largura in {
        "A": 24.7, "B": 28.6, "C": 17.1, "F": 21.0, "G": 18.1, "K": 21.0,
        "L": 18.1,
    }.items():
        ws.column_dimensions[letra].width = largura
    ws.row_dimensions[1].height = 32.1
    ws.row_dimensions[2].height = 15.95
    ws.row_dimensions[3].height = 30.0

    # --- Título (A1:D1) ------------------------------------------------------
    ws.merge_cells("A1:D1")
    cel = ws["A1"]
    cel.value = "Relatório de Radiação Solar"
    cel.font = _fonte_titulo
    cel.alignment = _centro
    for c in ws["A1:D1"][0]:
        c.fill = _fill_azul

    # --- Subtítulo dinâmico (A2:D2): Local • Período -------------------------
    ws.merge_cells("A2:D2")
    cel = ws["A2"]
    cel.value = '=B4&" • "&B8'
    cel.font = _fonte_sub
    cel.alignment = _centro

    # --- "Informações Gerais" (A3:D3) + pares rótulo/valor -------------------
    ws.merge_cells("A3:D3")
    cel = ws["A3"]
    cel.value = "Informações Gerais"
    cel.font = _fonte_secao

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
    for k, (rotulo, valor) in enumerate(linhas_meta, start=4):
        ws.cell(row=k, column=1, value=rotulo).font = _fonte_rotulo
        ws.cell(row=k, column=2, value=valor).font = _fonte_normal
    # "Data de geração" como texto alinhado à esquerda (formato '@' do modelo).
    cel = ws.cell(row=3 + len(linhas_meta), column=2)
    cel.number_format = "@"
    cel.alignment = Alignment(horizontal="left")

    # --- Estatísticas de Radiação (F1:L1 título; F3:L3 cabeçalho) ------------
    ws.merge_cells("F1:L1")
    cel = ws["F1"]
    cel.value = f"Estatísticas de Radiação ({unidade})"
    cel.font = _fonte_secao
    cel.alignment = _vcentro

    cab_stats = [
        "Componente", "Média", "Média Diurna", "Máximo", "Mínimo Diurno",
        "Energia (Wh/m²)", "kWh/m²/dia",
    ]
    for j, nome in enumerate(cab_stats, start=6):
        cel = ws.cell(row=3, column=j, value=nome)
        cel.font = _fonte_cab
        cel.fill = _fill_azul
        cel.alignment = _centro_total
        cel.border = _borda_fina

    # Divisor do kWh/m²/dia conforme o passo (ver docstring do módulo).
    passos_por_dia = {"1min": 1440, "15min": 96, "1h": 24, "1d": 1}.get(passo)

    linha = 4
    for k, comp in enumerate(componentes):
        rot = rotulos[comp]
        zebra = k % 2 == 1  # 2ª, 4ª... linhas listradas, como no modelo
        valores: list[str | None] = [comp, None, None, None, None, None, None]
        if tem_dados:
            valores[1] = f"=AVERAGE(TabDados[{rot}])"
            valores[2] = f'=AVERAGEIF(TabDados[{rot}],">0")'
            valores[3] = f"=MAX(TabDados[{rot}])"
            valores[4] = f'=_xlfn.MINIFS(TabDados[{rot}],TabDados[{rot}],">0")'
            valores[5] = f"=SUM(TabDados[{rot}])"
            if passos_por_dia is not None:
                valores[6] = (
                    f"=K{linha}/(COUNT(TabDados[Timestamp])/{passos_por_dia})/1000"
                )
            else:  # passo mensal: nº de dias calculado em Python
                valores[6] = f"=K{linha}/{n_dias}/1000"
        formatos = [None, FORMATO_DADOS, FORMATO_DADOS, FORMATO_DADOS,
                    FORMATO_DADOS, FORMATO_ENERGIA, FORMATO_KWH]
        for j, (valor, fmt) in enumerate(zip(valores, formatos), start=6):
            cel = ws.cell(row=linha, column=j, value=valor)
            cel.font = _fonte_normal
            cel.border = _borda_fina
            if fmt:
                cel.number_format = fmt
            if zebra:
                cel.fill = _fill_zebra
        linha += 1
    linha_fim_stats = linha - 1

    # --- Legenda (mesclada, 2 linhas abaixo da tabela; F9 no modelo) ---------
    linha_legenda = max(9, linha_fim_stats + 2)
    ws.merge_cells(
        start_row=linha_legenda, start_column=6,
        end_row=linha_legenda, end_column=12,
    )
    cel = ws.cell(row=linha_legenda, column=6)
    cel.value = (
        "GHI: Global Horizontal · BHI: Feixe Horizontal · DHI: Difusa Horizontal · "
        f"DNI: Direta Normal (BNI na SoDa) — irradiâncias em {unidade}"
    )
    cel.font = _fonte_legenda

    # --- Gráfico comparativo (Média / Média Diurna / Máximo por componente) --
    if tem_dados and componentes:
        grafico = BarChart()
        grafico.type = "col"
        grafico.grouping = "clustered"
        grafico.gapWidth = 219
        grafico.overlap = -27
        grafico.title = f"Comparativo de Radiação por Componente ({unidade})"
        grafico.legend.position = "b"
        grafico.height = 7.5
        grafico.width = 15
        grafico.y_axis.title = unidade
        grafico.y_axis.number_format = FORMATO_VALOR
        dados = Reference(
            ws, min_col=7, max_col=9, min_row=3, max_row=linha_fim_stats
        )
        cats = Reference(ws, min_col=6, min_row=4, max_row=linha_fim_stats)
        grafico.add_data(dados, titles_from_data=True)
        grafico.set_categories(cats)
        # Âncora A14 no modelo; desce se a tabela de estatísticas for maior.
        linha_grafico = max(14, linha_legenda + 2)
        ws.row_dimensions[linha_grafico - 1].height = 9.95
        ws.add_chart(grafico, f"A{linha_grafico}")


# ---------------------------------------------------------------------------
# Aba "Qualidade" (controle de qualidade dos dados)
# ---------------------------------------------------------------------------
_FILL_STATUS = {
    "OK": PatternFill("solid", fgColor="FFC6EFCE"),
    "Atenção": PatternFill("solid", fgColor="FFFFEB9C"),
    "Problemas": PatternFill("solid", fgColor="FFFFC7CE"),
}


def _titulo_secao(ws: Worksheet, linha: int, texto: str, larg: int = 4) -> None:
    """Escreve um título de seção com fundo azul mesclado em ``larg`` colunas."""
    ws.merge_cells(start_row=linha, start_column=1, end_row=linha, end_column=larg)
    cel = ws.cell(row=linha, column=1, value=texto)
    cel.font = _fonte_cab
    cel.fill = _fill_azul
    cel.alignment = _centro


def _escrever_qualidade(ws: Worksheet, qc) -> None:
    """Escreve o resumo do RelatorioQC com formatação profissional."""
    ws.column_dimensions["A"].width = 34
    ws.column_dimensions["B"].width = 26
    ws.column_dimensions["C"].width = 22
    ws.column_dimensions["D"].width = 22

    ws.merge_cells("A1:D1")
    cel = ws["A1"]
    cel.value = "Controle de Qualidade dos Dados"
    cel.font = _fonte_titulo
    cel.alignment = _centro
    for c in ws["A1:D1"][0]:
        c.fill = _fill_azul

    # Status geral, destacado pela cor.
    ws.cell(row=3, column=1, value="Status geral").font = _fonte_rotulo
    cel = ws.cell(row=3, column=2, value=qc.status_geral)
    cel.font = Font(name=FONTE, size=12, bold=True)
    cel.fill = _FILL_STATUS.get(qc.status_geral, _fill_zebra)
    cel.alignment = _centro

    pares = [
        ("Completude (%)", f"{qc.completude_pct:.1f}"),
        ("Instantes esperados", qc.total_esperado),
        ("Instantes com dado", qc.total_presente),
        ("Lacunas (intervalos)", len(qc.lacunas)),
        ("Valores negativos", qc.n_negativos),
        ("Suspeitos à noite", qc.n_noturno_suspeito),
    ]
    linha = 4
    for rotulo, valor in pares:
        ws.cell(row=linha, column=1, value=rotulo).font = _fonte_rotulo
        ws.cell(row=linha, column=2, value=valor).font = _fonte_normal
        linha += 1

    # Tabela de verificações.
    linha += 1
    _titulo_secao(ws, linha, "Verificações")
    linha += 1
    cab = ["Verificação", "Resultado", "Detalhe", ""]
    for j, nome in enumerate(cab[:3], start=1):
        cel = ws.cell(row=linha, column=j, value=nome)
        cel.font = _fonte_cab
        cel.fill = _fill_azul
        cel.alignment = _centro
        cel.border = _borda_fina
    linha += 1

    def linha_verif(nome, resultado, detalhe):
        nonlocal linha
        ws.cell(row=linha, column=1, value=nome).font = _fonte_normal
        cel = ws.cell(row=linha, column=2, value=resultado)
        cel.font = _fonte_normal
        if resultado in _FILL_STATUS:
            cel.fill = _FILL_STATUS[resultado]
        ws.cell(row=linha, column=3, value=detalhe).font = _fonte_normal
        for j in range(1, 4):
            ws.cell(row=linha, column=j).border = _borda_fina
        linha += 1

    # Completude
    res_compl = "OK" if qc.completude_pct >= 99 else (
        "Atenção" if qc.completude_pct >= 90 else "Problemas"
    )
    linha_verif("Completude / lacunas", res_compl,
                f"{qc.completude_pct:.1f}% · {len(qc.lacunas)} lacuna(s)")
    # Negativos
    linha_verif("Valores negativos (< -1)", "OK" if qc.n_negativos == 0 else "Atenção",
                f"{qc.n_negativos} valor(es)")
    # Noturno
    linha_verif("Radiação noturna", "OK" if qc.n_noturno_suspeito == 0 else "Atenção",
                f"{qc.n_noturno_suspeito} suspeito(s)")
    # Envelope
    if qc.envelope is None:
        linha_verif("Envelope de céu limpo", "Não aplicável", "sem real + céu limpo")
    else:
        env = qc.envelope
        res = "OK" if env["n_violacoes"] == 0 else (
            "Problemas" if env["n_violacoes"] / max(1, env["n_avaliado"]) > 0.15
            else "Atenção"
        )
        linha_verif("Envelope de céu limpo", res,
                    f"{env['n_violacoes']} viol. · máx {env['excesso_max_rel']:.1%} "
                    f"(tol. {env['tolerancia']:.0%})")
    # Fechamento
    fch = qc.fechamento
    if not fch["aplicavel"]:
        linha_verif("Fechamento GHI=DHI+DNI·cosθz", "Não aplicável", fch["status"])
    else:
        res = fch["status"] if fch["status"] in _FILL_STATUS else "Atenção"
        linha_verif("Fechamento GHI=DHI+DNI·cosθz", res,
                    f"{fch['n_fora']} fora / {fch['n_avaliado']} avaliados")
    # Concordância
    if qc.concordancia_fontes is None:
        linha_verif("Concordância McClear × NASA", "Não aplicável", "só uma fonte")
    else:
        c = qc.concordancia_fontes
        res = "OK" if c["rmse_rel_pct"] < 5 else (
            "Atenção" if c["rmse_rel_pct"] <= 15 else "Problemas"
        )
        linha_verif("Concordância McClear × NASA", res,
                    f"RMSE {c['rmse']:.1f} ({c['rmse_rel_pct']:.1f}%) · "
                    f"viés {c['mbe']:.1f} · r {c['r']:.3f}")

    # NaN por coluna, se houver.
    nan_itens = {k: v for k, v in qc.nan_por_coluna.items() if v}
    if nan_itens:
        linha += 1
        _titulo_secao(ws, linha, "Valores ausentes (NaN) por coluna")
        linha += 1
        for col, qtd in nan_itens.items():
            ws.cell(row=linha, column=1, value=col).font = _fonte_normal
            ws.cell(row=linha, column=2, value=qtd).font = _fonte_normal
            linha += 1

    # Legenda dos critérios (autoexplicativa).
    linha += 1
    _titulo_secao(ws, linha, "Critérios e tolerâncias")
    linha += 1
    crit = qc.criterios
    legenda = [
        f"Envelope de céu limpo: real ≤ céu limpo × (1 + {crit.get('tolerancia_envelope', 0.1):.0%}).",
        f"Fechamento: {crit.get('fechamento_tolerancia', '')} — "
        "não aplicável em resolução diária/mensal (valores integrados).",
        f"Negativos tolerados até {crit.get('negativo_tolerancia_whm2', -1)} Wh/m² (ruído).",
        f"Concordância entre fontes: {crit.get('concordancia_faixas', '')}.",
        "Geometria solar calculada com pvlib (ângulo zenital no ponto médio do período).",
    ]
    for texto in legenda:
        cel = ws.cell(row=linha, column=1, value=texto)
        cel.font = _fonte_legenda
        ws.merge_cells(start_row=linha, start_column=1, end_row=linha, end_column=4)
        linha += 1


# ---------------------------------------------------------------------------
# Aba "Reprodutibilidade" (proveniência + citações)
# ---------------------------------------------------------------------------
def _escrever_reprodutibilidade(ws: Worksheet, repro) -> None:
    """Escreve a proveniência (chave→valor) e o bloco de citações."""
    ws.column_dimensions["A"].width = 30
    ws.column_dimensions["B"].width = 80

    ws.merge_cells("A1:B1")
    cel = ws["A1"]
    cel.value = "Reprodutibilidade e Citações"
    cel.font = _fonte_titulo
    cel.alignment = _centro
    for c in ws["A1:B1"][0]:
        c.fill = _fill_azul

    proveniencia = getattr(repro, "proveniencia", None) or {}
    metodologia_pt = getattr(repro, "metodologia_pt", "")
    metodologia_en = getattr(repro, "metodologia_en", "")
    citacoes_md = getattr(repro, "citacoes_md", "")

    linha = 3
    _titulo_secao(ws, linha, "Proveniência da extração", larg=2)
    linha += 1
    for chave, valor in _achatar(proveniencia):
        ws.cell(row=linha, column=1, value=chave).font = _fonte_rotulo
        cel = ws.cell(row=linha, column=2, value=valor)
        cel.font = _fonte_normal
        cel.alignment = Alignment(wrap_text=True, vertical="top")
        linha += 1

    # Metodologia (PT/EN).
    linha += 1
    _titulo_secao(ws, linha, "Metodologia (PT / EN)", larg=2)
    linha += 1
    for texto in (metodologia_pt, metodologia_en):
        ws.merge_cells(start_row=linha, start_column=1, end_row=linha, end_column=2)
        cel = ws.cell(row=linha, column=1, value=texto)
        cel.font = _fonte_normal
        cel.alignment = Alignment(wrap_text=True, vertical="top")
        ws.row_dimensions[linha].height = 60
        linha += 1

    # Citações / agradecimentos (uma linha por linha do Markdown).
    linha += 1
    _titulo_secao(ws, linha, "Referências e agradecimentos", larg=2)
    linha += 1
    for texto in citacoes_md.splitlines():
        limpo = texto.lstrip("#> ").strip()
        if not limpo:
            continue
        ws.merge_cells(start_row=linha, start_column=1, end_row=linha, end_column=2)
        cel = ws.cell(row=linha, column=1, value=limpo)
        cel.font = (
            _fonte_rotulo if texto.startswith("#") or texto.startswith("**")
            else _fonte_normal
        )
        cel.alignment = Alignment(wrap_text=True, vertical="top")
        linha += 1


def _achatar(d: dict, prefixo: str = "") -> list[tuple[str, str]]:
    """Achata um dicionário aninhado em pares (chave legível, valor texto)."""
    itens: list[tuple[str, str]] = []
    for chave, valor in d.items():
        nome = f"{prefixo}{chave}"
        if isinstance(valor, dict):
            itens.extend(_achatar(valor, f"{nome} · "))
        elif isinstance(valor, list):
            partes = []
            for v in valor:
                partes.append(v.get("nome", str(v)) if isinstance(v, dict) else str(v))
            itens.append((nome, "; ".join(partes)))
        else:
            itens.append((nome, "" if valor is None else str(valor)))
    return itens


# ---------------------------------------------------------------------------
def nome_arquivo_saida(local: str, data_inicio, data_fim) -> Path:
    """Monta o caminho padrão de saída: radiacao_<local>_<ini>_<fim>.xlsx."""
    local_limpo = "".join(
        c if c.isalnum() else "_" for c in str(local)
    ).strip("_") or "local"
    nome = f"radiacao_{local_limpo}_{data_inicio}_{data_fim}.xlsx"
    return OUTPUT_DIR / nome
