"""
tests/validar_app.py
====================

Simula o fluxo completo do usuário na interface com
``streamlit.testing.v1.AppTest``: carrega o app, preenche o e-mail na barra
lateral, aciona a extração e verifica que não há exceções e que o estado de
SUCESSO aparece.

Para rodar em qualquer máquina SEM consumir cota da API (e sem depender de
internet), a fonte CAMS é substituída por um STUB que devolve dados sintéticos
de 72 linhas. O objetivo deste teste é validar a LIGAÇÃO da interface
(widgets -> extração -> estado de sucesso -> métricas/gráficos), não os dados
reais (isso é feito por validar_extracao.py / validar_pipeline.py).

Uso:
    python tests/validar_app.py
"""

from __future__ import annotations

import sys
from pathlib import Path

_RAIZ = Path(__file__).resolve().parent.parent
if str(_RAIZ) not in sys.path:
    sys.path.insert(0, str(_RAIZ))

import pandas as pd

from tests._comum import APROVADO, REPROVADO  # type: ignore

APP = _RAIZ / "app" / "streamlit_app.py"
EMAIL_TESTE = "pesquisador@unesp.br"


def _df_sintetico(*_args, **_kwargs) -> pd.DataFrame:
    """Stub de CamsMcClear.buscar: 72 linhas horárias com valores plausíveis."""
    ts = pd.date_range("2026-06-07 00:00", periods=72, freq="h")
    hora = ts.hour
    # Curva diurna simples (0 à noite, pico ~600 ao meio-dia).
    import numpy as np

    base = np.clip(np.sin((hora - 6) / 12 * 3.14159), 0, None) * 600
    return pd.DataFrame(
        {
            "timestamp": ts,
            "GHI": base.round(1),
            "DNI": (base * 1.2).round(1),
            "DHI": (base * 0.2).round(1),
            "BHI": (base * 0.8).round(1),
        }
    )


def executar(email: str | None = None) -> tuple[str, str]:
    try:
        from streamlit.testing.v1 import AppTest
    except Exception as exc:  # noqa: BLE001
        return REPROVADO, f"streamlit.testing indisponível: {exc}"

    # Substitui a fonte real por dados sintéticos (sem rede / sem cota).
    import sources.cams_mcclear as cam

    original = cam.CamsMcClear.buscar
    cam.CamsMcClear.buscar = _df_sintetico  # type: ignore[assignment]
    try:
        at = AppTest.from_file(str(APP), default_timeout=60)
        at.run()
        if at.exception:
            return REPROVADO, f"exceção ao carregar o app: {at.exception[0].value}"

        # Preenche o e-mail SoDa na barra lateral (label exato).
        achou_email = False
        for ti in at.text_input:
            if ti.label == "E-mail SoDa":
                ti.set_value(EMAIL_TESTE)
                achou_email = True
        if not achou_email:
            return REPROVADO, "campo 'E-mail SoDa' não encontrado na interface"

        # Garante o CAMS McClear marcado.
        for cb in at.checkbox:
            if "McClear" in cb.label:
                cb.set_value(True)

        # Aciona a extração.
        clicado = False
        for botao in at.button:
            if "Extrair dados" in botao.label:
                botao.click()
                clicado = True
        if not clicado:
            return REPROVADO, "botão 'Extrair dados' não encontrado"

        at.run()

        if at.exception:
            return REPROVADO, f"exceção durante a extração: {at.exception[0].value}"
        if len(at.success) == 0:
            return REPROVADO, "nenhuma mensagem de sucesso após a extração"

        textos = " ".join(s.value for s in at.success)
        return APROVADO, f"fluxo OK; sucesso: '{textos[:60]}…'"
    finally:
        cam.CamsMcClear.buscar = original  # type: ignore[assignment]


if __name__ == "__main__":
    status, detalhe = executar()
    print(f"\nvalidar_app: {status} — {detalhe}")
    sys.exit(0 if status == APROVADO else 1)
