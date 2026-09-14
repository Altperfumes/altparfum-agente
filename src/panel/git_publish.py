"""Leer y publicar el prompt del agente, de verdad.

El panel no comparte disco con el agente (son dos contenedores separados),
así que para editar `prompts/sistema.md` mantiene su propio clon del repo
en `/tmp` y lo sincroniza en cada lectura.

"Publicar" es, literalmente:

    escribir el archivo → git commit → git push

Después de eso el repo tiene el prompt nuevo, y le toca a Coolify
redesplegar el agente para que lo levante (ver coolify.py).

La llave para pushear viaje por `GIT_DEPLOY_KEY` (el contenido de una
private key, no una ruta) — es la misma deploy key que ya tiene acceso de
escritura al repo en GitHub.
"""

from __future__ import annotations

import os
import stat
import subprocess
import tempfile
from pathlib import Path

REPO_LOCAL = Path(tempfile.gettempdir()) / "altparfum-agente-repo"
RUTA_PROMPT = "prompts/sistema.md"


class ErrorDePublicacion(Exception):
    """Algo falló al leer o publicar el prompt (git, la llave, la red)."""


def _clave_temporal() -> str:
    clave = os.getenv("GIT_DEPLOY_KEY", "").strip()
    if not clave:
        raise ErrorDePublicacion(
            "Falta GIT_DEPLOY_KEY en el .env del panel: la llave privada para "
            "pushear al repo del agente."
        )

    archivo = Path(tempfile.gettempdir()) / "panel_deploy_key"
    archivo.write_text(clave + "\n", encoding="utf-8")
    # SSH se niega a usar una llave que otros puedan leer.
    archivo.chmod(stat.S_IRUSR | stat.S_IWUSR)
    return str(archivo)


def _git(*args: str, cwd: Path | None = None) -> str:
    entorno = os.environ.copy()
    entorno["GIT_SSH_COMMAND"] = (
        f"ssh -i {_clave_temporal()} -o IdentitiesOnly=yes "
        f"-o StrictHostKeyChecking=accept-new"
    )
    resultado = subprocess.run(
        ["git", *args],
        cwd=cwd,
        env=entorno,
        capture_output=True,
        text=True,
        timeout=30,
    )
    if resultado.returncode != 0:
        raise ErrorDePublicacion(
            f"git {' '.join(args)} falló: {resultado.stderr.strip()[:300]}"
        )
    return resultado.stdout.strip()


def _rama() -> str:
    return os.getenv("GIT_BRANCH", "master")


def _asegurar_clon() -> Path:
    repo_url = os.getenv("GIT_REPO", "").strip()
    if not repo_url:
        raise ErrorDePublicacion("Falta GIT_REPO en el .env del panel.")

    if not (REPO_LOCAL / ".git").exists():
        REPO_LOCAL.parent.mkdir(parents=True, exist_ok=True)
        _git("clone", "--branch", _rama(), repo_url, str(REPO_LOCAL))
    else:
        _git("fetch", "origin", _rama(), cwd=REPO_LOCAL)
        _git("reset", "--hard", f"origin/{_rama()}", cwd=REPO_LOCAL)

    return REPO_LOCAL


def leer_prompt_actual() -> str:
    """El texto completo de prompts/sistema.md, tal cual está en el repo ahora."""
    repo = _asegurar_clon()
    return (repo / RUTA_PROMPT).read_text(encoding="utf-8")


def publicar_prompt(texto: str) -> str:
    """Escribe el prompt nuevo, comitea y pushea. Devuelve el hash del commit.

    Si el texto es igual al que ya estaba, no crea un commit vacío: devuelve
    el HEAD actual tal cual.
    """
    repo = _asegurar_clon()
    (repo / RUTA_PROMPT).write_text(texto.strip() + "\n", encoding="utf-8")

    _git("add", RUTA_PROMPT, cwd=repo)

    sin_cambios = subprocess.run(
        ["git", "diff", "--cached", "--quiet"], cwd=repo
    ).returncode == 0
    if sin_cambios:
        return _git("rev-parse", "HEAD", cwd=repo)

    _git(
        "-c",
        "user.name=Panel AltParfum",
        "-c",
        "user.email=panel@altparfum.cloud",
        "commit",
        "-m",
        "Actualiza el prompt desde el panel",
        cwd=repo,
    )
    _git("push", "origin", f"HEAD:{_rama()}", cwd=repo)
    return _git("rev-parse", "HEAD", cwd=repo)
