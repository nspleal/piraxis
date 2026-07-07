#!/usr/bin/env python3
"""
empacotar.py — Build do pacote PORTÁTIL do PIRAXIS (sem exigir Python instalado)
================================================================================

Gera um pacote autocontido em ``dist/PIRAXIS/`` com **duas camadas**:

  - **runtime** (pesado, muda raramente): interpretador Python autossuficiente
    (python-build-standalone, build ``install_only``, relocável) + as
    dependências do ``Programa/requirements.txt`` já instaladas dentro do pacote;
  - **código** (leve, muda toda hora): os ``.py`` do app em ``Programa/``.

O pesquisador roda com **duplo clique**, sem instalar Python, sem PATH, sem admin
e offline já no primeiro uso. O runtime fica **pinado** → todos rodam a mesma
versão validada (reforça o princípio de fidelidade Δ=0).

ESTE SCRIPT NÃO ALTERA A LÓGICA DO APP. Ele só baixa o runtime, instala as
dependências dentro do pacote, copia a camada de código, gera os launchers do
pacote, valida e zipa.

Uso típico (na máquina/CI do SO alvo)::

    python empacotar.py                 # alvo padrão: Windows x64
    python empacotar.py --alvo linux-x64
    python empacotar.py --locked        # instala a partir do requirements.lock

IMPORTANTE (limite de plataforma): a etapa de instalar dependências roda o
interpretador EMBUTIDO. Por isso o pacote de um SO precisa ser gerado NAQUELE SO
(não dá para instalar/validar um ``python.exe`` de Windows a partir do Linux).
O download/extração/launchers funcionam em qualquer host; a instalação e a
validação exigem o interpretador alvo executável.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import logging
import os
import shutil
import subprocess
import sys
import tarfile
import time
import urllib.request
from datetime import date
from pathlib import Path

# ---------------------------------------------------------------------------
# CONSTANTES (ajuste consciente — ver §8 do prompt; reportadas no resumo final)
# ---------------------------------------------------------------------------
PY_VERSION = "3.12"            # série bem suportada pela stack científica
CPYTHON_VERSION = "3.12.11"    # patch exato embutido (casa com PBS_RELEASE)
# Tag PINADA de astral-sh/python-build-standalone (determinismo). Resolva uma
# release com build `install_only` para PY_VERSION e grave a tag aqui. Para subir
# de versão, troque CPYTHON_VERSION + PBS_RELEASE juntos e rode o build de novo.
PBS_RELEASE = "20250612"

PBS_BASE = (
    "https://github.com/astral-sh/python-build-standalone/releases/download"
)

# Plataformas suportadas: nome amigável -> (triple PBS, caminho relativo do
# interpretador dentro de python/, é Windows?).
ALVOS: dict[str, dict] = {
    "windows-x64": {
        "triple": "x86_64-pc-windows-msvc",
        "py_rel": "python/python.exe",
        "windows": True,
    },
    "linux-x64": {
        "triple": "x86_64-unknown-linux-gnu",
        "py_rel": "python/bin/python3",
        "windows": False,
    },
    "macos-arm64": {
        "triple": "aarch64-apple-darwin",
        "py_rel": "python/bin/python3",
        "windows": False,
    },
    "macos-x64": {
        "triple": "x86_64-apple-darwin",
        "py_rel": "python/bin/python3",
        "windows": False,
    },
}
ALVO_PADRAO = "windows-x64"

# Camada de código copiada para o pacote (o que é o app). Pastas + arquivos.
COPIAR_DIRS = ("app", "core", "sources", "output", ".streamlit")
COPIAR_ARQS = (
    "atualizar.py", ".env.example", "requirements.txt", "requirements.lock",
    "LEIA-ME.txt",
)
# Nunca entram no pacote (runtime/efêmero/dev/segredos).
EXCLUIR = {
    "cache", "data", "__pycache__", ".venv", "venv", "env", ".git",
    ".pytest_cache", ".mypy_cache", "tests", ".env",
}

RAIZ = Path(__file__).resolve().parent          # raiz do repo
PROGRAMA = RAIZ / "Programa"
DIST = RAIZ / "dist"
CACHE = RAIZ / ".empacotar_cache"

log = logging.getLogger("empacotar")


# ---------------------------------------------------------------------------
# Utilidades
# ---------------------------------------------------------------------------
def _config_log() -> None:
    DIST.mkdir(parents=True, exist_ok=True)
    fmt = logging.Formatter("%(asctime)s [%(levelname)s] %(message)s")
    log.setLevel(logging.INFO)
    sh = logging.StreamHandler(sys.stdout)
    sh.setFormatter(fmt)
    log.addHandler(sh)
    fh = logging.FileHandler(RAIZ / "empacotar.log", mode="w", encoding="utf-8")
    fh.setFormatter(fmt)
    log.addHandler(fh)


def run(cmd: list[str], cwd: Path | None = None, check: bool = True,
        env: dict | None = None) -> subprocess.CompletedProcess:
    """Executa um comando, ecoando no log. Levanta em falha se ``check``."""
    log.info("$ %s", " ".join(str(c) for c in cmd))
    proc = subprocess.run(
        [str(c) for c in cmd], cwd=str(cwd) if cwd else None,
        capture_output=True, text=True, env=env,
    )
    if proc.stdout.strip():
        log.info(proc.stdout.strip()[-4000:])
    if proc.returncode != 0:
        log.error("STDERR: %s", proc.stderr.strip()[-4000:])
        if check:
            raise RuntimeError(f"comando falhou ({proc.returncode}): {cmd[:2]}…")
    return proc


def _baixar(url: str, destino: Path) -> None:
    """Baixa ``url`` para ``destino`` (segue redirects; sem credenciais)."""
    log.info("baixando %s", url)
    req = urllib.request.Request(url, headers={"User-Agent": "piraxis-build"})
    with urllib.request.urlopen(req, timeout=120) as resp, open(destino, "wb") as fh:
        shutil.copyfileobj(resp, fh)


def _sha256(caminho: Path) -> str:
    h = hashlib.sha256()
    with open(caminho, "rb") as fh:
        for bloco in iter(lambda: fh.read(1 << 20), b""):
            h.update(bloco)
    return h.hexdigest()


# ---------------------------------------------------------------------------
# Passos do build
# ---------------------------------------------------------------------------
def baixar_runtime(triple: str) -> Path:
    """Baixa (com cache) e verifica o asset install_only do PBS. Retorna o .tar.gz."""
    asset = f"cpython-{CPYTHON_VERSION}+{PBS_RELEASE}-{triple}-install_only.tar.gz"
    url = f"{PBS_BASE}/{PBS_RELEASE}/{asset}"
    CACHE.mkdir(parents=True, exist_ok=True)
    tgz = CACHE / asset
    if not tgz.exists():
        _baixar(url, tgz)
    else:
        log.info("runtime em cache: %s", tgz.name)

    # Verificação de integridade contra o .sha256 publicado pela release.
    esperado_path = CACHE / (asset + ".sha256")
    try:
        _baixar(url + ".sha256", esperado_path)
        esperado = esperado_path.read_text().split()[0].strip().lower()
        obtido = _sha256(tgz)
        if obtido != esperado:
            tgz.unlink(missing_ok=True)
            raise RuntimeError(
                f"SHA256 não confere para {asset}\n  esperado={esperado}\n  obtido={obtido}"
            )
        log.info("SHA256 OK (%s…)", obtido[:16])
    except RuntimeError:
        raise
    except Exception as exc:  # rede instável no .sha256 não deve travar o cache
        log.warning("não verifiquei o SHA256 (%s) — seguindo com o asset baixado", exc)
    return tgz


def extrair_runtime(tgz: Path, pkg: Path) -> None:
    """Extrai o runtime para ``pkg/python/`` (o tar tem topo ``python/``)."""
    destino_py = pkg / "python"
    if destino_py.exists():
        shutil.rmtree(destino_py)
    log.info("extraindo runtime em %s", destino_py)
    with tarfile.open(tgz, "r:gz") as tar:
        tar.extractall(pkg)  # cria pkg/python/
    if not destino_py.is_dir():
        raise RuntimeError("estrutura inesperada do tar (esperava topo 'python/').")


def garantir_pip(py: Path) -> None:
    """Garante pip no interpretador embutido (defensivo)."""
    run([py, "-m", "ensurepip", "--upgrade"], check=False)
    run([py, "-m", "pip", "install", "--upgrade", "pip"], check=False)


def instalar_deps(py: Path, locked: bool) -> None:
    """Instala as dependências no interpretador embutido a partir do
    requirements.txt (ou do .lock se ``locked``)."""
    if locked:
        lock = PROGRAMA / "requirements.lock"
        if not lock.exists():
            raise RuntimeError("--locked pedido mas Programa/requirements.lock não existe.")
        run([py, "-m", "pip", "install", "--no-input", "-r", lock])
    else:
        run([py, "-m", "pip", "install", "--no-input", "-r",
             PROGRAMA / "requirements.txt"])


def congelar_lock(py: Path) -> Path:
    """``pip freeze`` → Programa/requirements.lock (registro de reprodutibilidade)."""
    proc = run([py, "-m", "pip", "freeze"])
    lock = PROGRAMA / "requirements.lock"
    cabecalho = (
        "# requirements.lock — gerado por empacotar.py (NÃO editar à mão).\n"
        f"# Python {CPYTHON_VERSION} (PBS {PBS_RELEASE}). Versões EXATAS do pacote.\n"
        "# Fonte de verdade editável: requirements.txt.\n"
    )
    linhas = [l for l in proc.stdout.splitlines() if l and not l.startswith("#")]
    lock.write_text(cabecalho + "\n".join(sorted(linhas, key=str.lower)) + "\n",
                    encoding="utf-8")
    log.info("lock congelado: %d pacotes", len(linhas))
    return lock


def _freeze_nomes(py: Path) -> set[str]:
    """Nomes (minúsculos) dos pacotes instalados no interpretador embutido."""
    proc = run([py, "-m", "pip", "freeze"])
    return {
        linha.split("==")[0].strip().lower()
        for linha in proc.stdout.splitlines()
        if "==" in linha
    }


def instalar_deps_dev(py: Path) -> set[str]:
    """Instala as deps de TESTE (requirements-dev.txt) só para a validação.

    Retorna o conjunto de pacotes que a instalação ACRESCENTOU — é exatamente
    o que ``remover_deps_dev`` desinstala depois, para que pytest/responses e
    suas dependências exclusivas NÃO viajem dentro do pacote do usuário final
    (bloat + mais arquivos profundos, que agravam o limite MAX_PATH).
    """
    antes = _freeze_nomes(py)
    run([py, "-m", "pip", "install", "--no-input", "-r",
         PROGRAMA / "requirements-dev.txt"])
    return _freeze_nomes(py) - antes


def remover_deps_dev(py: Path, extras: set[str]) -> None:
    """Desinstala do interpretador embutido o que só entrou para a validação."""
    if extras:
        run([py, "-m", "pip", "uninstall", "-y", *sorted(extras)], check=False)


def _ignore(_dir, nomes):
    return [n for n in nomes if n in EXCLUIR or n.endswith(".pyc")]


def copiar_codigo(pkg: Path, versao: str) -> None:
    """Copia a camada de código para ``pkg/Programa/`` (sem cache/data/tests/segredos)."""
    destino = pkg / "Programa"
    if destino.exists():
        shutil.rmtree(destino)
    destino.mkdir(parents=True)
    for d in COPIAR_DIRS:
        src = PROGRAMA / d
        if src.is_dir():
            shutil.copytree(src, destino / d, ignore=_ignore)
    for a in COPIAR_ARQS:
        src = PROGRAMA / a
        if src.exists():
            shutil.copy2(src, destino / a)
    (destino / "VERSAO.txt").write_text(versao + "\n", encoding="utf-8")
    # Saneamento: nada de cache/data/.env/__pycache__ no pacote.
    for proibido in ("cache", "data", ".env"):
        p = destino / proibido
        if p.exists():
            shutil.rmtree(p, ignore_errors=True) if p.is_dir() else p.unlink()


def gerar_launchers(pkg: Path, alvo: dict) -> None:
    """Gera os launchers do PACOTE (distintos dos venv-based do repo)."""
    bat = (
        "@echo off\r\n"
        "chcp 65001 >nul\r\n"
        'cd /d "%~dp0"\r\n'
        "echo Iniciando o PIRAXIS...\r\n"
        "rem (1) tentativa de atualizacao leve do codigo — nunca bloqueia\r\n"
        '"%~dp0python\\python.exe" "%~dp0Programa\\atualizar.py" 2>nul\r\n'
        "rem (2) sobe o app a partir de Programa\\ (acha o .streamlit\\config.toml por CWD)\r\n"
        'cd /d "%~dp0Programa"\r\n'
        '"%~dp0python\\python.exe" -m streamlit run "app\\streamlit_app.py"\r\n'
        "if errorlevel 1 (\r\n"
        "  echo.\r\n"
        "  echo Ocorreu um erro ao iniciar. Pressione uma tecla para sair.\r\n"
        "  pause >nul\r\n"
        ")\r\n"
    )
    (pkg / "INICIAR PIRAXIS.bat").write_text(bat, encoding="utf-8")

    command = (
        "#!/bin/bash\n"
        '# Launcher de PACOTE (runtime embutido) — nao cria venv, nao chama pip.\n'
        'BUNDLE="$(cd "$(dirname "$0")/.." && pwd)"\n'
        'echo "Iniciando o PIRAXIS..."\n'
        '"$BUNDLE/python/bin/python3" "$BUNDLE/Programa/atualizar.py" 2>/dev/null || true\n'
        'cd "$BUNDLE/Programa"\n'
        '"$BUNDLE/python/bin/python3" -m streamlit run "app/streamlit_app.py"\n'
        'code=$?\n'
        'if [ "$code" -ne 0 ]; then\n'
        '  echo ""\n'
        '  echo "Ocorreu um erro ao iniciar. Pressione ENTER para sair."\n'
        '  read -r _\n'
        'fi\n'
    )
    cmd_path = pkg / "Programa" / "INICIAR PIRAXIS (Mac e Linux).command"
    cmd_path.write_text(command, encoding="utf-8")
    os.chmod(cmd_path, 0o755)


def escrever_leiame_raiz(pkg: Path) -> None:
    """Copia o LEIA-ME do usuário também para a RAIZ do pacote (descoberta)."""
    src = PROGRAMA / "LEIA-ME.txt"
    if src.exists():
        shutil.copy2(src, pkg / "LEIA-ME.txt")


# ---------------------------------------------------------------------------
# Validação (§7 — execute e prove)
# ---------------------------------------------------------------------------
def validar(py: Path, pkg: Path) -> list[str]:
    """Roda a bateria de validação com o INTERPRETADOR EMBUTIDO. Retorna o relatório."""
    rel: list[str] = []

    # AC3a — pip check (árvore de dependências consistente).
    p = run([py, "-m", "pip", "check"], check=False)
    rel.append(("OK  " if p.returncode == 0 else "FALHA ") + "pip check")

    # AC3b — suíte de testes do projeto com o runtime embutido (tests/ ficam no
    # REPO, não no pacote; rodamos contra o código-fonte para provar o runtime).
    p = run([py, "-m", "pytest", "-q", "tests"], cwd=PROGRAMA, check=False)
    rel.append(("OK  " if p.returncode == 0 else "FALHA ") + "pytest tests/")

    # AC4 — boot headless do Streamlit até HTTP 200, depois encerra.
    rel.append(_validar_boot(py, pkg))

    # AC5a — atualizador no-op (URL vazia) não bloqueia e sai 0.
    p = run([py, str(pkg / "Programa" / "atualizar.py")], check=False)
    rel.append(("OK  " if p.returncode == 0 else "FALHA ") + "atualizar.py no-op (sai 0)")

    return rel


def _validar_boot(py: Path, pkg: Path) -> str:
    import urllib.error

    porta = 8599
    prog = pkg / "Programa"
    proc = subprocess.Popen(
        [str(py), "-m", "streamlit", "run", "app/streamlit_app.py",
         "--server.headless", "true", "--server.port", str(porta),
         "--browser.gatherUsageStats", "false"],
        cwd=str(prog), stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
    )
    try:
        url = f"http://127.0.0.1:{porta}/_stcore/health"
        prazo = time.time() + 60
        while time.time() < prazo:
            if proc.poll() is not None:
                return "FALHA boot headless (processo encerrou cedo)"
            try:
                with urllib.request.urlopen(url, timeout=2) as r:
                    if r.status == 200 and r.read().strip() == b"ok":
                        return "OK  boot headless (HTTP 200 em /_stcore/health)"
            except Exception:
                time.sleep(1)
        return "FALHA boot headless (timeout sem HTTP 200)"
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=10)
        except Exception:
            proc.kill()


# ---------------------------------------------------------------------------
# Empacotamento final
# ---------------------------------------------------------------------------
def versao_do_repo() -> str:
    try:
        sha = subprocess.run(
            ["git", "-C", str(RAIZ), "rev-parse", "--short", "HEAD"],
            capture_output=True, text=True, check=True,
        ).stdout.strip()
    except Exception:
        sha = ""
    iso = date.today().isoformat()
    return f"{sha}-{iso}" if sha else iso


def zipar(pkg: Path, versao: str, alvo_nome: str) -> tuple[Path, Path]:
    """Gera o zip COMPLETO (1º install) e o zip SÓ-CÓDIGO (update leve).

    O zip completo tem o CONTEÚDO do pacote na RAIZ (python/, Programa/ e o
    launcher lado a lado) — mesma estrutura do artefato do CI, que foi a
    validada em campo. NÃO reintroduzir uma pasta de topo: o nível extra
    aprofunda os caminhos no Windows (limite MAX_PATH de 260) e faz o usuário
    extrair em C:\\PIRAXIS e cair em C:\\PIRAXIS\\PIRAXIS\\.
    """
    completo = DIST / f"PIRAXIS-{versao}-{alvo_nome}"
    shutil.make_archive(str(completo), "zip", root_dir=str(pkg))

    # Só-código: zip de Programa/ sem python/.
    tmp = DIST / "_codigo"
    if tmp.exists():
        shutil.rmtree(tmp)
    (tmp / "PIRAXIS").mkdir(parents=True)
    shutil.copytree(pkg / "Programa", tmp / "PIRAXIS" / "Programa", ignore=_ignore)
    codigo = DIST / f"PIRAXIS-codigo-{versao}"
    shutil.make_archive(str(codigo), "zip", root_dir=str(tmp), base_dir="PIRAXIS")
    shutil.rmtree(tmp, ignore_errors=True)
    return Path(str(completo) + ".zip"), Path(str(codigo) + ".zip")


def escrever_manifesto(versao: str, lock: Path, url_zip: str = "") -> Path:
    manifesto = {
        "versao": versao,
        "requirements_hash": _sha256(lock),
        "url_zip": url_zip or "<PREENCHER>",
    }
    p = DIST / "manifesto.json"
    p.write_text(json.dumps(manifesto, indent=2, ensure_ascii=False) + "\n",
                 encoding="utf-8")
    return p


# ---------------------------------------------------------------------------
def main() -> int:
    ap = argparse.ArgumentParser(description="Empacota o PIRAXIS como pacote portátil.")
    ap.add_argument("--alvo", choices=list(ALVOS), default=ALVO_PADRAO,
                    help=f"plataforma alvo (padrão: {ALVO_PADRAO})")
    ap.add_argument("--locked", action="store_true",
                    help="instala a partir do requirements.lock (rebuild reprodutível)")
    args = ap.parse_args()

    _config_log()
    alvo = ALVOS[args.alvo]
    log.info("=== Build PIRAXIS · alvo=%s · Python %s (PBS %s) ===",
             args.alvo, CPYTHON_VERSION, PBS_RELEASE)

    # Guarda de plataforma: instalar/validar exige rodar o interpretador alvo.
    host_windows = os.name == "nt"
    if alvo["windows"] != host_windows:
        log.error(
            "Alvo '%s' precisa ser empacotado no próprio SO: a instalação de "
            "dependências roda o interpretador EMBUTIDO, e não é possível executar "
            "um interpretador de %s a partir deste host (%s). Rode este script na "
            "máquina/CI do SO alvo.",
            args.alvo, "Windows" if alvo["windows"] else "Unix",
            "Windows" if host_windows else "Unix",
        )
        return 2

    pkg = DIST / "PIRAXIS"
    pkg.mkdir(parents=True, exist_ok=True)
    py = pkg / alvo["py_rel"]

    tgz = baixar_runtime(alvo["triple"])
    extrair_runtime(tgz, pkg)
    garantir_pip(py)
    instalar_deps(py, args.locked)
    lock = congelar_lock(py)

    versao = versao_do_repo()
    copiar_codigo(pkg, versao)
    gerar_launchers(pkg, alvo)
    escrever_leiame_raiz(pkg)

    # Deps de teste entram SÓ para a validação e saem antes de zipar.
    extras_dev = instalar_deps_dev(py)
    relatorio = validar(py, pkg)
    remover_deps_dev(py, extras_dev)
    # Reafirma as versões de produção: o delta por NOME não pega o caso de a
    # instalação de teste ter feito UPGRADE de uma transitiva compartilhada
    # (ex.: packaging). Reinstalar do lock (--locked) traz qualquer pacote
    # divergente de volta à versão pinada; com requirements.txt é no-op.
    instalar_deps(py, args.locked)
    p = run([py, "-m", "pip", "check"], check=False)
    relatorio.append(
        ("OK  " if p.returncode == 0 else "FALHA ")
        + "pip check pós-remoção das deps de teste"
    )

    zip_completo, zip_codigo = zipar(pkg, versao, args.alvo)
    manifesto = escrever_manifesto(versao, lock)

    falhou = any(linha.startswith("FALHA") for linha in relatorio)

    def _mb(p: Path) -> str:
        return f"{p.stat().st_size / 1e6:.1f} MB" if p.exists() else "—"

    log.info("================= RESUMO =================")
    log.info("Versão: %s", versao)
    log.info("Python embutido: %s (PBS %s) · alvo %s", CPYTHON_VERSION,
             PBS_RELEASE, args.alvo)
    log.info("Pacote: %s", pkg)
    log.info("Zip completo: %s (%s)", zip_completo.name, _mb(zip_completo))
    log.info("Zip só-código: %s (%s)", zip_codigo.name, _mb(zip_codigo))
    log.info("Manifesto: %s", manifesto)
    log.info("Lock: %s", lock)
    log.info("Validação:")
    for linha in relatorio:
        log.info("  - %s", linha)
    log.info("Resultado: %s", "FALHOU ❌" if falhou else "TUDO VERDE ✅")
    log.info("=========================================")
    return 1 if falhou else 0


if __name__ == "__main__":
    raise SystemExit(main())
