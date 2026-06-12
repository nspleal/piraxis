"""
tests/validar_boot.py
=====================

Comprova automaticamente que o aplicativo SOBE com o mesmo comando usado pelos
launchers (``streamlit run app/streamlit_app.py --server.headless true``) e
responde no endpoint de saúde do Streamlit (``/_stcore/health`` -> "ok").

Não precisa de internet nem de e-mail SoDa: valida apenas que o app inicia.

Uso:
    python tests/validar_boot.py
"""

from __future__ import annotations

import socket
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

_RAIZ = Path(__file__).resolve().parent.parent
if str(_RAIZ) not in sys.path:
    sys.path.insert(0, str(_RAIZ))

from tests._comum import APROVADO, REPROVADO  # type: ignore

APP_REL = Path("app") / "streamlit_app.py"
TIMEOUT_S = 60


def _porta_livre() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def executar(email: str | None = None) -> tuple[str, str]:
    porta = _porta_livre()
    # MESMO comando dos launchers (streamlit run ... --server.headless true).
    cmd = [
        sys.executable, "-m", "streamlit", "run", str(APP_REL),
        "--server.headless", "true",
        "--server.port", str(porta),
        "--server.address", "127.0.0.1",
        "--browser.gatherUsageStats", "false",
    ]
    proc = subprocess.Popen(
        cmd, cwd=str(_RAIZ),
        stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True,
    )
    url = f"http://127.0.0.1:{porta}/_stcore/health"
    try:
        inicio = time.time()
        while time.time() - inicio < TIMEOUT_S:
            if proc.poll() is not None:  # processo morreu
                saida = proc.stdout.read() if proc.stdout else ""
                return REPROVADO, f"o app encerrou sozinho: {saida[-200:]}"
            try:
                with urllib.request.urlopen(url, timeout=2) as resp:
                    corpo = resp.read().decode("utf-8", "ignore").strip().lower()
                    if resp.status == 200 and "ok" in corpo:
                        dur = time.time() - inicio
                        return APROVADO, f"health 'ok' em {dur:.1f}s (porta {porta})"
            except Exception:
                pass
            time.sleep(1.0)
        return REPROVADO, f"health não respondeu 'ok' em {TIMEOUT_S}s"
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=10)
        except subprocess.TimeoutExpired:
            proc.kill()


if __name__ == "__main__":
    status, detalhe = executar()
    print(f"\nvalidar_boot: {status} — {detalhe}")
    sys.exit(0 if status == APROVADO else 1)
