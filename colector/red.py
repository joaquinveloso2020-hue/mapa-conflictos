"""Acceso HTTP con reintentos, tiempos límite, peticiones condicionales y respeto de robots.txt."""
from __future__ import annotations

import time
import urllib.robotparser
from datetime import datetime, timedelta, timezone
from urllib.parse import urlsplit

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry


class ErrorRed(Exception):
    def __init__(self, mensaje: str, codigo: int | None = None, reintentable: bool = True):
        super().__init__(mensaje)
        self.codigo = codigo
        self.reintentable = reintentable


def crear_sesion(usuario_agente: str) -> requests.Session:
    s = requests.Session()
    reintentos = Retry(
        total=2, connect=2, read=2, backoff_factor=1.5,
        status_forcelist=(429, 500, 502, 503, 504),
        allowed_methods=("GET", "HEAD", "POST"),
        respect_retry_after_header=True,
    )
    adaptador = HTTPAdapter(max_retries=reintentos, pool_connections=20, pool_maxsize=20)
    s.mount("http://", adaptador)
    s.mount("https://", adaptador)
    s.headers.update({"User-Agent": usuario_agente, "Accept-Language": "es,en;q=0.8"})
    return s


class Robots:
    """Cache de robots.txt por host (24 h). Si robots.txt no se puede leer, se permite."""

    def __init__(self, sesion: requests.Session, cache: dict, usuario_agente: str):
        self.sesion = sesion
        self.cache = cache  # host -> {"t": iso, "txt": str|None}
        self.ua = usuario_agente.split("/")[0]

    def permitido(self, url: str) -> bool:
        partes = urlsplit(url)
        host = f"{partes.scheme}://{partes.netloc}"
        ahora = datetime.now(timezone.utc)
        entrada = self.cache.get(host)
        if not entrada or datetime.fromisoformat(entrada["t"]) < ahora - timedelta(hours=24):
            txt = None
            try:
                r = self.sesion.get(host + "/robots.txt", timeout=10)
                if r.status_code == 200 and len(r.content) < 500_000:
                    txt = r.text
            except requests.RequestException:
                txt = None
            entrada = {"t": ahora.isoformat(), "txt": txt}
            self.cache[host] = entrada
        if not entrada["txt"]:
            return True
        rp = urllib.robotparser.RobotFileParser()
        rp.parse(entrada["txt"].splitlines())
        return rp.can_fetch(self.ua, url)


def obtener(sesion: requests.Session, url: str, *, timeout: float = 25, etag: str | None = None,
            modificado: str | None = None, max_bytes: int = 60_000_000) -> requests.Response | None:
    """GET con condicionales. Devuelve None si 304 (sin cambios). Lanza ErrorRed en fallos."""
    cabeceras = {}
    if etag:
        cabeceras["If-None-Match"] = etag
    if modificado:
        cabeceras["If-Modified-Since"] = modificado
    try:
        r = sesion.get(url, timeout=timeout, headers=cabeceras, stream=True)
    except requests.RequestException as e:
        raise ErrorRed(f"{type(e).__name__}: {str(e)[:160]}") from e
    if r.status_code == 304:
        r.close()
        return None
    if r.status_code == 404:
        r.close()
        raise ErrorRed("404 no encontrado", 404, reintentable=False)
    if r.status_code == 429:
        r.close()
        raise ErrorRed("429 límite de solicitudes", 429)
    if r.status_code >= 400:
        r.close()
        raise ErrorRed(f"HTTP {r.status_code}", r.status_code, reintentable=r.status_code >= 500)
    contenido = bytearray()
    inicio = time.monotonic()
    for bloque in r.iter_content(65536):
        contenido.extend(bloque)
        if len(contenido) > max_bytes:
            r.close()
            raise ErrorRed("respuesta demasiado grande (posible truncamiento)", reintentable=False)
        if time.monotonic() - inicio > timeout * 4:
            r.close()
            raise ErrorRed("descarga demasiado lenta")
    r._content = bytes(contenido)
    return r
