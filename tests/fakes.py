"""Servicios simulados SOLO PARA PRUEBAS AUTOMÁTICAS.

Todo el contenido de este archivo es ficticio (titulares marcados con "[PRUEBA]") y nunca se
publica en la web: las pruebas escriben en carpetas temporales.
"""
from __future__ import annotations

import io
import json
import zipfile
from datetime import datetime, timedelta, timezone


class Respuesta:
    def __init__(self, status: int = 200, contenido: bytes = b"", cabeceras: dict | None = None, js=None):
        self.status_code = status
        self.content = contenido if js is None else json.dumps(js).encode()
        self.headers = cabeceras or {}
        self._js = js
        self._content = self.content

    def iter_content(self, n):
        for i in range(0, len(self.content), n):
            yield self.content[i:i + n]

    def close(self):
        pass

    def json(self):
        if self._js is not None:
            return self._js
        return json.loads(self.content)

    @property
    def text(self):
        return self.content.decode("utf-8", errors="replace")


def rss(items: list[dict]) -> bytes:
    cuerpo = "".join(
        f"<item><title>{i['titulo']}</title><link>{i['url']}</link>"
        f"<description>{i.get('resumen', '')}</description>"
        f"<pubDate>{i['pub']}</pubDate></item>" for i in items)
    return f'<?xml version="1.0"?><rss version="2.0"><channel><title>Prueba</title>{cuerpo}</channel></rss>'.encode()


def zip_texto(nombre: str, texto: str) -> bytes:
    b = io.BytesIO()
    with zipfile.ZipFile(b, "w") as z:
        z.writestr(nombre, texto)
    return b.getvalue()


def fila_gkg(url: str, titulo: str, temas: str, lugares: str, ts: str, srclc: str | None = None,
             dominio: str = "ejemplo-prueba.org") -> str:
    c = [""] * 27
    c[0] = f"{ts}-1"
    c[1] = ts
    c[2] = "1"
    c[3] = dominio
    c[4] = url
    c[7] = temas
    c[10] = lugares
    c[25] = f"srclc:{srclc};eng:GT-{srclc}" if srclc else ""
    c[26] = f"<PAGE_TITLE>{titulo}</PAGE_TITLE><PAGE_PRECISEPUBTIMESTAMP>{ts}</PAGE_PRECISEPUBTIMESTAMP>"
    return "\t".join(c)


def fila_evento(url: str, fips: str, tipo: int, nombre: str, lat: float, lon: float, raiz: str = "19",
                dia: str = "20261013") -> str:
    c = [""] * 61
    c[0] = "1"
    c[1] = dia
    c[25] = "1"
    c[26] = raiz + "0"
    c[28] = raiz
    c[51] = str(tipo)
    c[52] = nombre
    c[53] = fips
    c[56] = str(lat)
    c[57] = str(lon)
    c[59] = dia + "120000"
    c[60] = url
    return "\t".join(c)


class SesionFalsa:
    """Imita requests.Session para RSS, GDELT, índice de modelos y la API de Telegram."""

    def __init__(self):
        self.rutas: dict[str, Respuesta] = {}
        self.fallos: dict[str, int] = {}
        self.telegram_actualizaciones: list[dict] = []
        self.telegram_enviados: list[dict] = []
        self.telegram_falla_envio = None  # None | int (código HTTP) | "red"
        self.headers = {}
        self.pedidos: list[str] = []

    def get(self, url, timeout=None, headers=None, stream=False):
        self.pedidos.append(url)
        if url.endswith("/robots.txt"):
            return Respuesta(404)
        if url in self.fallos:
            return Respuesta(self.fallos[url])
        if url in self.rutas:
            return self.rutas[url]
        return Respuesta(404)

    def post(self, url, json=None, timeout=None):
        metodo = url.rsplit("/", 1)[-1]
        if metodo == "getUpdates":
            offset = (json or {}).get("offset", 0)
            pendientes = [u for u in self.telegram_actualizaciones if u["update_id"] >= offset]
            return Respuesta(200, js={"ok": True, "result": pendientes})
        if metodo == "sendMessage":
            assert "allow_paid_broadcast" not in json, "nunca se deben usar difusiones pagas"
            if self.telegram_falla_envio == "red":
                import requests
                raise requests.ConnectionError("red caída (simulada)")
            if self.telegram_falla_envio:
                return Respuesta(self.telegram_falla_envio, js={"ok": False, "description": "error simulado"})
            self.telegram_enviados.append(json)
            return Respuesta(200, js={"ok": True, "result": {"message_id": len(self.telegram_enviados)}})
        return Respuesta(404, js={"ok": False})


def ts_franja(ahora: datetime, atras: int = 0) -> str:
    limite = ahora - timedelta(minutes=6)
    base = limite.replace(minute=(limite.minute // 15) * 15, second=0, microsecond=0)
    return (base - timedelta(minutes=15 * atras)).strftime("%Y%m%d%H%M%S")


def rfc822(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).strftime("%a, %d %b %Y %H:%M:%S +0000")
