"""Lectura de feeds RSS/Atom de medios y fuentes oficiales."""
from __future__ import annotations

import calendar
import logging
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone

import feedparser

from . import urls
from .red import ErrorRed, Robots, obtener
from .texto import limpiar_html

log = logging.getLogger(__name__)


def _fecha(entrada) -> str | None:
    for campo in ("published_parsed", "updated_parsed", "created_parsed"):
        valor = entrada.get(campo)
        if valor:
            try:
                return datetime.fromtimestamp(calendar.timegm(valor), tz=timezone.utc).isoformat()
            except (OverflowError, ValueError):
                continue
    return None


def _leer_feed(fuente: dict, sesion, robots: Robots, estado_fuente: dict, ahora: str) -> tuple[list[dict], dict]:
    url = fuente["url"]
    resultado = dict(estado_fuente)
    resultado.update({"ultimo_intento": ahora})
    if not robots.permitido(url):
        resultado.update({"estado": "bloqueada_robots", "error": "robots.txt no permite la descarga"})
        return [], resultado
    try:
        r = obtener(sesion, url, timeout=20, etag=estado_fuente.get("etag"),
                    modificado=estado_fuente.get("modificado"), max_bytes=8_000_000)
    except ErrorRed as e:
        fallos = estado_fuente.get("fallos_seguidos", 0) + 1
        resultado.update({"estado": "error", "error": str(e), "fallos_seguidos": fallos})
        return [], resultado
    if r is None:
        resultado.update({"estado": "ok", "error": None, "fallos_seguidos": 0, "ultimo_ok": ahora,
                          "sin_cambios": True})
        return [], resultado
    feed = feedparser.parse(r.content)
    if feed.bozo and not feed.entries:
        fallos = estado_fuente.get("fallos_seguidos", 0) + 1
        resultado.update({"estado": "error", "error": f"feed ilegible: {str(feed.bozo_exception)[:120]}",
                          "fallos_seguidos": fallos})
        return [], resultado
    articulos = []
    for e in feed.entries[:80]:
        enlace = e.get("link") or ""
        titulo = limpiar_html(e.get("title"), 400)
        if not enlace.startswith("http") or not titulo:
            continue
        resumen = limpiar_html(e.get("summary") or e.get("description") or "", 700)
        if resumen and resumen.lower().startswith(titulo.lower()[:60]):
            resumen = resumen[len(titulo):].strip(" .:-")
        articulos.append({
            "url": enlace,
            "titulo": titulo,
            "resumen": resumen if fuente.get("extracto", True) else "",
            "resumen_privado": resumen,  # solo para clasificar; no se publica si extracto=false
            "autor": limpiar_html(e.get("author") or "", 120),
            "pub": _fecha(e),
            "idioma": fuente.get("idioma"),
            "fuente_id": fuente["id"],
            "fuente_nombre": fuente["nombre"],
            "tipo_fuente": fuente.get("tipo", "medio"),
            "pais_medio": fuente.get("pais"),
            "propiedad": fuente.get("propiedad"),
            "dominio": urls.dominio(enlace),
            "via": "rss",
        })
    resultado.update({
        "estado": "ok", "error": None, "fallos_seguidos": 0, "ultimo_ok": ahora,
        "etag": r.headers.get("ETag"), "modificado": r.headers.get("Last-Modified"),
        "items": len(articulos), "sin_cambios": False,
    })
    return articulos, resultado


def recopilar(fuentes: list[dict], sesion, robots: Robots, estado: dict, ahora: str,
              hilos: int = 8) -> tuple[list[dict], dict]:
    """Lee todas las fuentes RSS en paralelo. Devuelve (artículos, estado_por_fuente)."""
    salida: list[dict] = []
    nuevo_estado: dict = {}

    def tarea(f):
        try:
            return f["id"], _leer_feed(f, sesion, robots, estado.get(f["id"], {}), ahora)
        except Exception as e:  # una fuente nunca debe romper el ciclo
            log.exception("Fallo inesperado en %s", f["id"])
            previo = dict(estado.get(f["id"], {}))
            previo.update({"estado": "error", "error": f"error interno: {type(e).__name__}",
                           "ultimo_intento": ahora,
                           "fallos_seguidos": previo.get("fallos_seguidos", 0) + 1})
            return f["id"], ([], previo)

    with ThreadPoolExecutor(max_workers=hilos) as ex:
        for fid, (arts, est) in ex.map(tarea, fuentes):
            salida.extend(arts)
            nuevo_estado[fid] = est
    return salida, nuevo_estado
