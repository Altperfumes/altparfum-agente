"""Le pide a Coolify que redespliegue el agente, después de publicar un prompt.

Publicar el prompt (git_publish.py) deja el código nuevo en GitHub, pero el
contenedor que corre en agente.altparfum.cloud sigue con la imagen vieja
hasta que alguien lo redespliega. Esto automatiza ese último paso llamando
a la misma API de Coolify que se usó para armar la aplicación.
"""

from __future__ import annotations

import json
import os
import urllib.error
import urllib.request


class ErrorDeCoolify(Exception):
    """Coolify no pudo redesplegar (URL/token mal puestos, o la API falló)."""


def redeploy_agente() -> dict:
    base = os.getenv("COOLIFY_URL", "").rstrip("/")
    token = os.getenv("COOLIFY_TOKEN", "")
    app_uuid = os.getenv("COOLIFY_APP_UUID", "")

    if not (base and token and app_uuid):
        raise ErrorDeCoolify(
            "Faltan COOLIFY_URL, COOLIFY_TOKEN o COOLIFY_APP_UUID en el .env "
            "del panel: el prompt se publicó en GitHub, pero no se pudo "
            "avisarle a Coolify que redespliegue."
        )

    peticion = urllib.request.Request(
        f"{base}/api/v1/deploy?uuid={app_uuid}", method="POST"
    )
    peticion.add_header("Authorization", f"Bearer {token}")
    peticion.add_header("Accept", "application/json")

    try:
        with urllib.request.urlopen(peticion, timeout=15) as respuesta:
            return json.loads(respuesta.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        raise ErrorDeCoolify(
            f"Coolify devolvió {e.code}: {e.read().decode('utf-8', 'replace')[:300]}"
        ) from None
    except urllib.error.URLError as e:
        raise ErrorDeCoolify(f"No se pudo contactar a Coolify: {e}") from None
