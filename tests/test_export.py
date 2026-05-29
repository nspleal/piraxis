"""
Testes do exportador Excel (output/exporta_excel.py).

Cobrem: a planilha é criada, tem as abas esperadas e as fórmulas não geram
erro (verificamos que as células de estatística contêm fórmulas =AVERAGE/
=MAX/=MIN e que nenhuma célula contém um erro do Excel do tipo "#...!").
"""

from __future__ import annotations

import pandas as pd
from openpyxl import load_workbook

from output.exporta_excel import exporta


def _df_uma_fonte() -> pd.DataFrame:
    return pd.DataFrame(
        {
            "timestamp": pd.date_range("2024-01-01 10:00", periods=3, freq="h"),
            "GHI": [500.0, 600.0, 550.0],
            "DNI": [300.0, 350.0, 320.0],
        }
    )


def _df_duas_fontes() -> pd.DataFrame:
    return pd.DataFrame(
        {
            "timestamp": pd.date_range("2024-01-01 10:00", periods=3, freq="h"),
            "GHI_McClear": [700.0, 800.0, 750.0],
            "GHI_NASA": [500.0, 600.0, 550.0],
            "kt": [0.714, 0.75, 0.733],
        }
    )


def _metadados() -> dict:
    return {
        "local": "Botucatu",
        "latitude": -22.8867,
        "longitude": -48.4450,
        "altitude": 786.0,
        "periodo": "01/01/2024 a 01/01/2024",
        "fontes": "NASA POWER",
        "passo_temporal": "1 hora",
        "email_soda": "(não aplicável)",
    }


def test_planilha_uma_fonte(tmp_path):
    caminho = tmp_path / "saida.xlsx"
    exporta(_df_uma_fonte(), _metadados(), caminho)

    assert caminho.exists()
    wb = load_workbook(caminho)
    assert "Resumo" in wb.sheetnames
    assert "Dados" in wb.sheetnames
    # Sem duas fontes, não há aba Comparação.
    assert "Comparação" not in wb.sheetnames


def test_planilha_duas_fontes_tem_comparacao(tmp_path):
    caminho = tmp_path / "saida2.xlsx"
    exporta(_df_duas_fontes(), _metadados(), caminho)

    wb = load_workbook(caminho)
    assert set(["Resumo", "Dados", "Comparação"]).issubset(set(wb.sheetnames))


def test_estatisticas_usam_formulas_e_sem_erros(tmp_path):
    caminho = tmp_path / "saida3.xlsx"
    exporta(_df_uma_fonte(), _metadados(), caminho)

    wb = load_workbook(caminho)
    resumo = wb["Resumo"]

    # Procura ao menos uma fórmula de estatística.
    formulas = [
        cel.value
        for linha in resumo.iter_rows()
        for cel in linha
        if isinstance(cel.value, str) and cel.value.startswith("=")
    ]
    assert any(f.startswith("=AVERAGE(") for f in formulas)
    assert any(f.startswith("=MAX(") for f in formulas)
    assert any(f.startswith("=MIN(") for f in formulas)

    # Nenhuma célula deve conter um erro de fórmula do Excel.
    for ws in wb.worksheets:
        for linha in ws.iter_rows():
            for cel in linha:
                if isinstance(cel.value, str):
                    assert not cel.value.startswith("#"), (
                        f"Erro de fórmula em {ws.title}!{cel.coordinate}: {cel.value}"
                    )
