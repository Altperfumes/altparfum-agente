"""El panel de AltParfum: estadísticas del agente y editor del prompt.

Es una app separada del webhook que atiende WhatsApp (otra imagen, otro
dominio en Coolify — prompt.altparfum.cloud). Comparte el mismo repo y el
mismo código del agente (`agente.metricas`, `agente.config`) pero no toca
las conversaciones en vivo: solo lee lo que el agente ya guardó.
"""
