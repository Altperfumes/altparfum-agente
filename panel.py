"""El panel de AltParfum: estadísticas del agente y editor del prompt.

    python panel.py

Corre como una aplicación separada del webhook de WhatsApp (otro dominio en
Coolify: prompt.altparfum.cloud). Necesita, además de lo que ya usa el
agente (POSTGRES_DSN para las estadísticas, y un proveedor de IA para poder
probar el prompt editado):

    PANEL_USUARIO, PANEL_CLAVE   ← quién puede entrar (HTTP Basic)
    GIT_REPO, GIT_BRANCH         ← el repo del agente, para leer y publicar
    GIT_DEPLOY_KEY               ← una llave con permiso de escritura ahí
    COOLIFY_URL, COOLIFY_TOKEN, COOLIFY_APP_UUID
                                  ← para redesplegar el agente al publicar

Para cortar: Ctrl+C.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent / "src"))

from agente.consola import preparar  # noqa: E402

preparar()

import logging  # noqa: E402

import uvicorn  # noqa: E402

from panel.app import app  # noqa: E402

AMBAR = "\033[38;5;214m"
GRIS = "\033[90m"
FIN = "\033[0m"


def main() -> int:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )

    puerto = int(os.getenv("PANEL_PUERTO", "8100"))

    print(f"\n{AMBAR}Panel escuchando{FIN} - puerto {puerto}")
    print(f"{GRIS}   GET / (con usuario y clave)   ·   GET /salud{FIN}\n")

    uvicorn.run(app, host="0.0.0.0", port=puerto, log_level="info")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
