"""
Programa/autoteste.py — verificação rápida da instalação (pacote portátil).

Roda OFFLINE em segundos, com o Python embutido, e diz se o pacote está
íntegro: interpretador, biblioteca padrão (o histórico "No module named
'urllib'" vinha de extração truncada pelo limite MAX_PATH do Windows),
dependências científicas e os módulos do próprio PIRAXIS.

Uso (o launcher "VERIFICAR INSTALACAO.bat" chama isto):
    python autoteste.py
Sai com código 0 se tudo certo; 1 se algo falhou (com a lista do que falhou).
"""

from __future__ import annotations

import importlib
import sys
from pathlib import Path

# Raiz do Programa/ no sys.path (rodando de qualquer diretório).
RAIZ = Path(__file__).resolve().parent
if str(RAIZ) not in sys.path:
    sys.path.insert(0, str(RAIZ))

# (módulo, por que importa)
VERIFICACOES: list[tuple[str, str]] = [
    ("urllib.request", "biblioteca padrão íntegra (detecta extração truncada)"),
    ("sqlite3", "biblioteca padrão com extensões binárias"),
    ("pandas", "séries temporais"),
    ("numpy", "base numérica"),
    ("streamlit", "interface"),
    ("plotly", "gráficos"),
    ("openpyxl", "planilha Excel"),
    ("pvlib", "acesso ao CAMS + geometria solar"),
    ("requests", "acesso à NASA POWER"),
    ("dotenv", "configuração (.env)"),
    ("core.config", "módulos do PIRAXIS"),
    ("core.combinador", "combinação de fontes"),
    ("output.exporta_excel", "exportador Excel"),
]


def main() -> int:
    print("PIRAXIS — verificação da instalação")
    print(f"Python embutido: {sys.version.split()[0]} ({sys.executable})")
    try:
        from core.versao import versao_ferramenta
        print(f"Versão da ferramenta: {versao_ferramenta()}")
    except Exception as exc:  # noqa: BLE001
        print(f"Versão da ferramenta: indisponível ({exc})")
    print("-" * 60)

    falhas: list[str] = []
    for modulo, motivo in VERIFICACOES:
        try:
            importlib.import_module(modulo)
            print(f"  [OK]    {modulo:<22} {motivo}")
        except Exception as exc:  # noqa: BLE001 - queremos listar TUDO que falhou
            print(f"  [FALHA] {modulo:<22} {exc}")
            falhas.append(modulo)

    print("-" * 60)
    if falhas:
        print(f"RESULTADO: {len(falhas)} problema(s): {', '.join(falhas)}")
        print(
            "Dica: se faltar módulo da biblioteca padrão (ex.: urllib), o zip "
            "provavelmente foi extraído num caminho longo demais — apague a "
            "pasta e extraia de novo em um caminho CURTO (ex.: C:\\PIRAXIS)."
        )
        return 1
    print("RESULTADO: TUDO CERTO — a instalação está íntegra.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
