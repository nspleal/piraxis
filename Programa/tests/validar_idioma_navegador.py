"""Verifica os rótulos e a proteção de idioma no navegador, sem chamar APIs."""
from __future__ import annotations

import subprocess
import sys
import time
import urllib.request
from pathlib import Path

from playwright.sync_api import sync_playwright

RAIZ = Path(__file__).resolve().parent.parent


def main() -> None:
    import socket

    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        porta = sock.getsockname()[1]
    url = f"http://127.0.0.1:{porta}"
    processo = subprocess.Popen(
        [sys.executable, "-m", "streamlit", "run", "app/streamlit_app.py",
         "--server.headless=true", "--server.address=127.0.0.1",
         f"--server.port={porta}", "--browser.gatherUsageStats=false"],
        cwd=RAIZ,
    )
    try:
        for _ in range(120):
            if processo.poll() is not None:
                raise RuntimeError("Streamlit encerrou antes de abrir a interface")
            try:
                with urllib.request.urlopen(f"{url}/_stcore/health", timeout=1) as resposta:
                    if resposta.status == 200:
                        break
            except OSError:
                time.sleep(0.5)
        else:
            raise TimeoutError("Streamlit não abriu em 60 segundos")
        with sync_playwright() as p:
            navegador = p.chromium.launch()
            pagina = navegador.new_page(locale="pt-BR")
            pagina.goto(url)
            pagina.locator("html[lang='pt-BR'][translate='no'].notranslate").wait_for()
            assert pagina.locator('meta[name="google"]').get_attribute("content") == "notranslate"
            pagina.get_by_role("tab", name="Dados", exact=True).wait_for()
            assert pagina.get_by_role("tab").all_text_contents() == [
                "Painel", "Série temporal", "Conferência", "Dados",
            ]
            pagina.get_by_role("radio", name="Período", exact=True).check()
            pagina.get_by_text("Até", exact=True).wait_for()
            labels = pagina.locator('[data-testid="stDateInput"] label').all_text_contents()
            assert labels == ["De", "Até"], labels
            # Re-renderizar widgets não deve remover a proteção do documento.
            assert pagina.locator("html").get_attribute("translate") == "no"
            assert pagina.get_by_text("Comeu", exact=True).count() == 0
            assert pagina.get_by_text("dia D", exact=True).count() == 0
            pagina.screenshot(path=str(RAIZ.parent / "dist" / "interface-1.1.png"), full_page=True)
            navegador.close()
        print("APROVADO: abas, De/Até e proteção de idioma no Chromium; sem APIs.")
    finally:
        processo.terminate()
        try:
            processo.wait(timeout=10)
        except subprocess.TimeoutExpired:
            processo.kill()
            processo.wait(timeout=10)


if __name__ == "__main__":
    main()
