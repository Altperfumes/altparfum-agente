"""Un registro de lo que hace el agente, para el panel.

Cada vez que el agente responde un mensaje de WhatsApp, guardamos una fila acá:
cuánto costó (tokens), qué herramienta usó (si usó alguna) y si la respuesta
traía un link de compra. El panel lee esta tabla para armar las estadísticas
reales — nunca inventa números.

Solo funciona en MODO=produccion (Postgres): en MODO=test no hay tabla ni
falta, el panel todavía no tiene sentido corriendo en tu computadora.

Igual que el resto del proyecto: si guardar la métrica falla, no se cae la
respuesta al cliente. Perder una fila de estadísticas es aceptable; perder
una respuesta no.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from datetime import datetime, timezone

registro = logging.getLogger("agente.metricas")

_CREAR_TABLA = """
CREATE TABLE IF NOT EXISTS eventos_agente (
    id BIGSERIAL PRIMARY KEY,
    creado_en TIMESTAMPTZ NOT NULL DEFAULT now(),
    conversacion TEXT NOT NULL,
    modelo TEXT,
    tokens_entrada INTEGER NOT NULL DEFAULT 0,
    tokens_salida INTEGER NOT NULL DEFAULT 0,
    tokens_cache_leidos INTEGER NOT NULL DEFAULT 0,
    herramientas TEXT[] NOT NULL DEFAULT '{}',
    link_producto BOOLEAN NOT NULL DEFAULT false,
    duracion_ms INTEGER NOT NULL DEFAULT 0
);
"""

# Cualquier link a un producto de la tienda: canonical_url de Tiendanube
# siempre tiene esta forma. No hace falta saber el dominio exacto de
# antemano (puede ser un dominio propio, no siempre *.tiendanube.com).
_RE_LINK_PRODUCTO = re.compile(r"https?://\S+/productos/\S+", re.IGNORECASE)


@dataclass
class Evento:
    conversacion: str
    modelo: str
    tokens_entrada: int
    tokens_salida: int
    tokens_cache_leidos: int
    herramientas: list[str]
    texto_respuesta: str
    duracion_ms: int = 0


def registrar(dsn: str, evento: Evento) -> None:
    """Guarda un evento. Si algo falla, lo loguea y sigue — nunca revienta."""
    if not dsn:
        return

    try:
        import psycopg

        with psycopg.connect(dsn, connect_timeout=5) as conexion:
            with conexion.cursor() as cursor:
                cursor.execute(_CREAR_TABLA)
                cursor.execute(
                    """
                    INSERT INTO eventos_agente
                        (conversacion, modelo, tokens_entrada, tokens_salida,
                         tokens_cache_leidos, herramientas, link_producto,
                         duracion_ms)
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                    """,
                    (
                        evento.conversacion,
                        evento.modelo,
                        evento.tokens_entrada,
                        evento.tokens_salida,
                        evento.tokens_cache_leidos,
                        evento.herramientas,
                        bool(_RE_LINK_PRODUCTO.search(evento.texto_respuesta)),
                        evento.duracion_ms,
                    ),
                )
            conexion.commit()
    except Exception as e:
        registro.warning("No se pudo guardar el evento de métricas: %s", e)


# -- Lo que lee el panel -------------------------------------------------------


def resumen(dsn: str, desde: datetime | None = None) -> dict:
    """Los números agregados que muestra el panel. Todo en cero si no hay datos.

    `desde` filtra desde qué fecha contar (por defecto, todo lo que haya).
    """
    vacio = {
        "conversaciones_con_respuesta": 0,
        "links_enviados": 0,
        "consultas_producto": 0,
        "consultas_pedido": 0,
        "incidencias": 0,
        "tokens_entrada": 0,
        "tokens_salida": 0,
        "tokens_cache_leidos": 0,
        "duracion_ms_promedio": 0,
        "top_herramientas": [],
        "por_hora": [0] * 24,
    }
    if not dsn:
        return vacio

    try:
        import psycopg

        with psycopg.connect(dsn, connect_timeout=5) as conexion:
            with conexion.cursor() as cursor:
                cursor.execute(_CREAR_TABLA)
                conexion.commit()

                condicion = "WHERE creado_en >= %s" if desde else ""
                parametros = (desde,) if desde else ()

                cursor.execute(
                    f"""
                    SELECT
                        count(DISTINCT conversacion),
                        count(*) FILTER (WHERE link_producto),
                        count(*) FILTER (WHERE 'buscar_producto' = ANY(herramientas)),
                        count(*) FILTER (WHERE 'consultar_pedido' = ANY(herramientas)),
                        count(*) FILTER (WHERE 'reportar_incidencia' = ANY(herramientas)),
                        coalesce(sum(tokens_entrada), 0),
                        coalesce(sum(tokens_salida), 0),
                        coalesce(sum(tokens_cache_leidos), 0),
                        coalesce(avg(duracion_ms), 0)
                    FROM eventos_agente
                    {condicion}
                    """,
                    parametros,
                )
                fila = cursor.fetchone()

                cursor.execute(
                    f"""
                    SELECT extract(hour FROM creado_en)::int AS hora, count(*)
                    FROM eventos_agente
                    {condicion}
                    GROUP BY hora
                    """,
                    parametros,
                )
                por_hora = [0] * 24
                for hora, cantidad in cursor.fetchall():
                    if hora is not None:
                        por_hora[hora] = cantidad

        return {
            "conversaciones_con_respuesta": fila[0] or 0,
            "links_enviados": fila[1] or 0,
            "consultas_producto": fila[2] or 0,
            "consultas_pedido": fila[3] or 0,
            "incidencias": fila[4] or 0,
            "tokens_entrada": fila[5] or 0,
            "tokens_salida": fila[6] or 0,
            "tokens_cache_leidos": fila[7] or 0,
            "duracion_ms_promedio": round(float(fila[8] or 0)),
            "top_herramientas": [],
            "por_hora": por_hora,
        }
    except Exception as e:
        registro.warning("No se pudo leer el resumen de métricas: %s", e)
        return vacio


def ahora() -> datetime:
    return datetime.now(timezone.utc)
