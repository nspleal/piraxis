"""
Testes do exportador Excel (output/exporta_excel.py) — formato do MODELO
oficial (planilha_modelo_para_IC.xlsx):

  - duas abas: Resumo e Dados (a antiga "Comparação" foi aposentada);
  - aba Dados com a tabela estruturada ``TabDados`` (colunas "Timestamp" +
    "<COMPONENTE> (W/m²)") e a tabela auxiliar de Energia Diária;
  - aba Resumo com metadados, estatísticas por FÓRMULA sobre a TabDados
    (AVERAGE/AVERAGEIF/MAX/MINIFS/SUM/kWh por dia) e legenda;
  - três gráficos (barras no Resumo; linha + barras de energia nos Dados);
  - kt presente nos dados mas fora das estatísticas; NaN vira célula vazia.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
from openpyxl import load_workbook

from output.exporta_excel import exporta


def _df_uma_fonte(n_horas: int = 72) -> pd.DataFrame:
    ts = pd.date_range("2026-01-01 00:00", periods=n_horas, freq="h")
    h = ts.hour.values.astype(float)
    ghi = np.clip(np.cos((h - 15) / 5.0 * (np.pi / 2)), 0, None) * 600.0
    ghi = np.where((h >= 10) & (h <= 20), ghi, 0.0)
    return pd.DataFrame(
        {
            "timestamp": ts,
            "GHI": ghi.round(1),
            "DNI": (ghi * 1.3).round(1),
            "DHI": (ghi * 0.2).round(1),
            "BHI": (ghi * 0.8).round(1),
        }
    )


def _df_duas_fontes() -> pd.DataFrame:
    df = _df_uma_fonte()
    return pd.DataFrame(
        {
            "timestamp": df["timestamp"],
            "GHI_McClear": df["GHI"],
            "GHI_NASA": df["GHI"] * 0.7,
            "kt": np.where(df["GHI"] > 0, 0.7, np.nan),
        }
    )


def _metadados() -> dict:
    return {
        "local": "Botucatu",
        "latitude": -22.8867,
        "longitude": -48.4450,
        "altitude": 786.0,
        "periodo": "01/01/2026 a 03/01/2026",
        "fontes": "CAMS McClear",
        "passo_temporal": "1 hora",
        "email_soda": "pesquisador@unesp.br",
    }


def test_estrutura_basica_do_modelo(tmp_path):
    caminho = tmp_path / "saida.xlsx"
    exporta(_df_uma_fonte(), _metadados(), caminho)

    wb = load_workbook(caminho)
    # Só as duas abas do modelo, na ordem Resumo -> Dados.
    assert wb.sheetnames == ["Resumo", "Dados"]

    ws = wb["Dados"]
    assert ws.freeze_panes == "A2"
    # Tabela estruturada com os nomes de coluna do modelo.
    tab = ws.tables["TabDados"]
    assert tab.ref == "A1:E73"
    assert [c.name for c in tab.tableColumns] == [
        "Período (UTC)", "GHI (W/m²)", "DNI (W/m²)", "DHI (W/m²)", "BHI (W/m²)",
    ]
    # A 1ª coluna mostra a FAIXA início–fim (UTC), espelhando o site.
    assert ws["A2"].value == "01/01/2026 00:00–01:00"


def test_resumo_formulas_e_metadados(tmp_path):
    caminho = tmp_path / "saida.xlsx"
    exporta(_df_uma_fonte(), _metadados(), caminho)

    r = load_workbook(caminho)["Resumo"]
    assert r["A1"].value == "Relatório de Radiação Solar"
    assert r["A2"].value == '=B4&" • "&B8'  # subtítulo dinâmico do modelo
    assert r["A3"].value == "Informações Gerais"
    rotulos = [r.cell(row=i, column=1).value for i in range(4, 13)]
    assert rotulos == [
        "Local", "Latitude", "Longitude", "Altitude (m)", "Período",
        "Fontes usadas", "Passo temporal", "E-mail SoDa usado",
        "Data de geração",
    ]
    assert r["B12"].number_format == "@"

    # Cabeçalho e fórmulas da tabela de estatísticas (linha do GHI).
    assert [r.cell(row=3, column=j).value for j in range(6, 13)] == [
        "Componente", "Média", "Média Diurna", "Máximo", "Mínimo Diurno",
        "Energia (Wh/m²)", "kWh/m²/dia",
    ]
    assert r["F4"].value == "GHI"
    assert r["G4"].value == "=AVERAGE(TabDados[GHI (W/m²)])"
    assert r["H4"].value == '=AVERAGEIF(TabDados[GHI (W/m²)],">0")'
    assert r["I4"].value == "=MAX(TabDados[GHI (W/m²)])"
    assert r["J4"].value == (
        '=_xlfn.MINIFS(TabDados[GHI (W/m²)],TabDados[GHI (W/m²)],">0")'
    )
    assert r["K4"].value == "=SUM(TabDados[GHI (W/m²)])"
    assert r["L4"].value == "=K4/3/1000"  # 72 h = 3 dias


def test_graficos_do_modelo(tmp_path):
    caminho = tmp_path / "saida.xlsx"
    exporta(_df_uma_fonte(), _metadados(), caminho)

    wb = load_workbook(caminho)
    tipos = [
        (aba.title, type(ch).__name__)
        for aba in wb.worksheets
        for ch in aba._charts
    ]
    # Resumo: barras comparativas; Dados: linha ao longo do tempo. (A tabela e o
    # gráfico de Energia Diária por data saíram porque a coluna de período virou
    # texto, faixa início–fim, igual ao site.)
    assert tipos == [
        ("Resumo", "BarChart"),
        ("Dados", "LineChart"),
    ]


def test_duas_fontes_kt_fora_das_estatisticas(tmp_path):
    caminho = tmp_path / "saida2.xlsx"
    exporta(_df_duas_fontes(), _metadados(), caminho)

    wb = load_workbook(caminho)
    assert wb.sheetnames == ["Resumo", "Dados"]  # nunca há aba Comparação

    # kt entra na TabDados (sem unidade), mas não nas estatísticas.
    tab = wb["Dados"].tables["TabDados"]
    nomes = [c.name for c in tab.tableColumns]
    assert "kt" in nomes
    assert "GHI_McClear (W/m²)" in nomes

    r = wb["Resumo"]
    componentes = []
    i = 4
    while r.cell(row=i, column=7).value:  # enquanto houver fórmula de Média
        componentes.append(r.cell(row=i, column=6).value)
        i += 1
    assert componentes == ["GHI_McClear", "GHI_NASA"]
    assert "kt" not in componentes


def test_nan_vira_celula_vazia_e_sem_erros(tmp_path):
    df = _df_uma_fonte()
    df.loc[5, "GHI"] = np.nan
    caminho = tmp_path / "saida3.xlsx"
    exporta(df, _metadados(), caminho)

    wb = load_workbook(caminho)
    # Linha 7 (índice 5 + cabeçalho) com GHI vazio, não zero.
    assert wb["Dados"]["B7"].value is None
    # Nenhuma célula com erro de fórmula em nenhuma aba.
    for ws in wb.worksheets:
        for linha in ws.iter_rows():
            for cel in linha:
                if isinstance(cel.value, str):
                    assert not cel.value.startswith("#"), (
                        f"Erro em {ws.title}!{cel.coordinate}: {cel.value}"
                    )


def test_abas_qualidade_e_reprodutibilidade(tmp_path):
    """Com QC e reprodutibilidade, surgem as duas abas extras sem quebrar as outras."""
    from datetime import date

    from core.config import BOTUCATU
    from core.qualidade import analisar_qualidade
    from core.reprodutibilidade import gerar_reprodutibilidade

    df = _df_uma_fonte()
    qc = analisar_qualidade(df, BOTUCATU, "PT01H", ["CAMS McClear"])
    repro = gerar_reprodutibilidade(
        BOTUCATU, date(2026, 1, 1), date(2026, 1, 3), "PT01H", "1 hora",
        ["CAMS McClear"], ["GHI", "DNI", "DHI", "BHI"],
    )
    caminho = tmp_path / "saida_qc.xlsx"
    exporta(df, _metadados(), caminho, relatorio_qc=qc, reprodutibilidade=repro)

    wb = load_workbook(caminho)
    assert wb.sheetnames == ["Resumo", "Dados", "Qualidade", "Reprodutibilidade"]
    # Conteúdos-chave presentes.
    q_txt = " ".join(
        str(c.value) for row in wb["Qualidade"].iter_rows()
        for c in row if c.value is not None
    )
    assert "Controle de Qualidade" in q_txt
    assert "Completude" in q_txt
    r_txt = " ".join(
        str(c.value) for row in wb["Reprodutibilidade"].iter_rows()
        for c in row if c.value is not None
    )
    assert "Holmgren" in r_txt  # citação do pvlib
    assert "pesquisador@unesp.br" not in r_txt  # e-mail nunca na reprodutibilidade


def test_dados_exibidos_com_4_casas_sem_arredondar(tmp_path):
    """Os valores de radiação devem ser exibidos com 4 casas (precisão da fonte),
    não arredondados para 1 casa; o valor guardado é o float completo."""
    caminho = tmp_path / "saida_fmt.xlsx"
    exporta(_df_uma_fonte(), _metadados(), caminho)
    wb = load_workbook(caminho)
    ws = wb["Dados"]
    assert ws["B2"].number_format == "0.0000"   # célula de dado (GHI)
    # A estatística (Média do GHI no Resumo) também usa 4 casas.
    assert wb["Resumo"]["G4"].number_format == "0.0000"


def test_passo_diario_usa_unidade_wh(tmp_path):
    ts = pd.date_range("2026-01-01", periods=10, freq="D")
    df = pd.DataFrame({"timestamp": ts, "GHI": np.full(10, 6500.0)})
    caminho = tmp_path / "saida4.xlsx"
    exporta(df, _metadados() | {"passo_temporal": "1 dia"}, caminho)

    wb = load_workbook(caminho)
    assert wb["Dados"]["B1"].value == "GHI (Wh/m²)"
    assert wb["Resumo"]["L4"].value == "=K4/10/1000"  # 10 dias
