"""El panel: estadísticas del agente + editor del prompt.

    python -m panel

Protegido con usuario y clave (PANEL_USUARIO / PANEL_CLAVE en el .env) — acá
adentro se puede reescribir toda la personalidad del agente y redesplegarlo,
así que no puede quedar abierto.

Rutas:

    GET  /                 el panel (HTML)
    GET  /api/prompt       el prompt completo, tal cual está en el repo
    POST /api/prompt       guarda un prompt nuevo (probar u definitivo)
    POST /api/probar       le manda un mensaje suelto al modelo con un prompt
                           editado, sin tocar el repo ni el agente real
    GET  /api/stats        las estadísticas reales (Postgres); en cero si
                           todavía no hay conversaciones
    GET  /salud            para el health check de Coolify
"""

from __future__ import annotations

import logging
import os
import secrets
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

from fastapi import Depends, FastAPI, HTTPException
from fastapi.responses import FileResponse, JSONResponse
from fastapi.security import HTTPBasic, HTTPBasicCredentials

# El panel vive en src/panel/ y necesita importar src/agente/ — son paquetes
# hermanos, no uno adentro del otro.
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from agente import metricas  # noqa: E402
from agente.config import Config as ConfigAgente  # noqa: E402
from agente.config import ErrorDeConfiguracion  # noqa: E402
from agente.modelos import crear_modelo  # noqa: E402

from . import coolify, git_publish  # noqa: E402

registro = logging.getLogger("panel")

ESTATICOS = Path(__file__).parent / "static"
RANGOS_DIAS = {"hoy": 1, "7d": 7, "30d": 30}

app = FastAPI(title="Panel AltParfum")
seguridad = HTTPBasic()


def _verificar(credenciales: HTTPBasicCredentials = Depends(seguridad)) -> None:
    """HTTP Basic contra PANEL_USUARIO / PANEL_CLAVE.

    compare_digest en vez de == para no filtrar por tiempo de respuesta
    cuánto de la clave adivinaron.
    """
    usuario = os.getenv("PANEL_USUARIO", "")
    clave = os.getenv("PANEL_CLAVE", "")

    coincide_usuario = secrets.compare_digest(credenciales.username, usuario)
    coincide_clave = secrets.compare_digest(credenciales.password, clave)

    if not (usuario and clave and coincide_usuario and coincide_clave):
        raise HTTPException(
            status_code=401,
            detail="usuario o clave incorrectos",
            headers={"WWW-Authenticate": "Basic"},
        )


@app.get("/salud")
def salud() -> dict:
    return {"estado": "ok"}


@app.get("/", dependencies=[Depends(_verificar)])
def index() -> FileResponse:
    return FileResponse(ESTATICOS / "index.html")


@app.get("/api/prompt", dependencies=[Depends(_verificar)])
def obtener_prompt() -> dict:
    try:
        return {"texto": git_publish.leer_prompt_actual()}
    except git_publish.ErrorDePublicacion as e:
        raise HTTPException(status_code=502, detail=str(e)) from None


@app.post("/api/prompt", dependencies=[Depends(_verificar)])
async def guardar_prompt(payload: dict) -> dict:
    texto = (payload.get("texto") or "").strip()
    if not texto:
        raise HTTPException(status_code=400, detail="el prompt no puede quedar vacío")

    if not payload.get("definitivo"):
        # "Guardar y probar" no toca el repo: el probador de acá abajo prueba
        # el texto tal cual está en el editor, sin publicar nada todavía.
        return {"ok": True, "definitivo": False}

    try:
        commit = git_publish.publicar_prompt(texto)
    except git_publish.ErrorDePublicacion as e:
        raise HTTPException(status_code=502, detail=str(e)) from None

    try:
        despliegue = coolify.redeploy_agente()
    except coolify.ErrorDeCoolify as e:
        # El prompt YA está publicado en GitHub en este punto — decirlo así,
        # para que no se piense que no pasó nada y lo intente de nuevo.
        return {
            "ok": True,
            "definitivo": True,
            "commit": commit,
            "aviso": f"Se publicó en GitHub ({commit[:7]}), pero el redeploy automático falló: {e}",
        }

    return {"ok": True, "definitivo": True, "commit": commit, "despliegue": despliegue}


@app.post("/api/probar", dependencies=[Depends(_verificar)])
async def probar_prompt(payload: dict) -> dict:
    """Prueba un prompt editado contra el modelo de verdad, sin publicar nada."""
    texto_prompt = (payload.get("texto_prompt") or "").strip()
    mensaje = (payload.get("mensaje") or "").strip()
    if not texto_prompt or not mensaje:
        raise HTTPException(status_code=400, detail="faltan texto_prompt o mensaje")

    from langchain_core.messages import HumanMessage, SystemMessage

    try:
        config = ConfigAgente.desde_entorno()
    except ErrorDeConfiguracion as e:
        raise HTTPException(status_code=500, detail=str(e)) from None

    modelo = crear_modelo(
        proveedor=config.proveedor,
        api_key=config.api_key,
        modelo=config.modelo,
        max_tokens=config.max_tokens,
    )

    try:
        respuesta = modelo.invoke(
            [SystemMessage(texto_prompt), HumanMessage(mensaje)]
        )
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"{type(e).__name__}: {e}") from None

    contenido = respuesta.content
    if isinstance(contenido, list):
        contenido = "".join(
            b.get("text", "") for b in contenido if isinstance(b, dict)
        )
    return {"respuesta": contenido}


@app.get("/api/config", dependencies=[Depends(_verificar)])
def obtener_config() -> dict:
    """Los ajustes reales del agente — no inventados, leídos de su .env."""
    try:
        config = ConfigAgente.desde_entorno()
    except ErrorDeConfiguracion as e:
        raise HTTPException(status_code=500, detail=str(e)) from None

    return {
        "proveedor": config.proveedor,
        "modelo": config.modelo,
        "memoria_mensajes": config.memoria_mensajes,
        "chatwoot_conectado": bool(config.chatwoot_url and config.chatwoot_token),
        "tiendanube_conectado": bool(
            os.getenv("TIENDANUBE_STORE_ID") and os.getenv("TIENDANUBE_ACCESS_TOKEN")
        ),
        "etiqueta_humano": config.chatwoot_etiqueta_humano,
    }


@app.get("/api/stats", dependencies=[Depends(_verificar)])
def stats(rango: str = "7d") -> JSONResponse:
    dias = RANGOS_DIAS.get(rango, 7)
    desde = datetime.now(timezone.utc) - timedelta(days=dias)

    try:
        config = ConfigAgente.desde_entorno()
        dsn = config.postgres_dsn
    except ErrorDeConfiguracion:
        dsn = os.getenv("POSTGRES_DSN", "")

    return JSONResponse(metricas.resumen(dsn, desde=desde))
