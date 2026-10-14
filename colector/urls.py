"""Normalización de URLs para deduplicar artículos."""
from __future__ import annotations

import hashlib
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

PARAMETROS_DESCARTABLES = {
    "fbclid", "gclid", "dclid", "mc_cid", "mc_eid", "ref", "ref_src", "refsrc", "cmpid", "cmp",
    "ito", "ns_mchannel", "ns_source", "ns_campaign", "ns_linkname", "ns_fee", "at_medium",
    "at_campaign", "at_custom1", "at_custom2", "at_custom3", "at_custom4", "outputtype", "amp",
    "rss", "rssfeed", "feed", "from", "src", "spm", "partner", "share", "smid", "taid",
    "xtor", "s_cid", "sr_share", "utm", "ocid", "guccounter", "guce_referrer", "guce_referrer_sig",
}
PREFIJOS_HOST = ("www.", "m.", "amp.", "mobile.", "edition.")
SUFIJOS_DOBLES = {"co.uk", "com.au", "co.jp", "co.kr", "com.br", "com.ar", "com.mx", "co.za",
                  "com.tr", "com.pk", "co.in", "com.ng", "co.ke", "com.cn", "com.hk", "gov.uk",
                  "org.uk", "ac.uk", "gov.ua", "com.ua", "co.il", "gov.il", "gob.ar", "com.co",
                  "com.ec", "com.ve", "gob.mx", "gov.in", "gov.pk", "gov.cn", "go.jp", "go.kr",
                  "gov.sa", "com.sa", "com.eg", "org.eg", "co.rw", "gov.tw", "com.tw", "net.au",
                  "com.sg", "com.my", "com.ph", "co.id", "or.jp", "ne.jp", "rep.kp", "gob.ve"}


def canonica(url: str) -> str:
    """URL canónica: sin parámetros de seguimiento, fragmentos, prefijos móviles ni /amp."""
    try:
        partes = urlsplit(url.strip())
    except ValueError:
        return url.strip()
    host = (partes.hostname or "").lower()
    for prefijo in PREFIJOS_HOST:
        if host.startswith(prefijo):
            host = host[len(prefijo):]
            break
    ruta = partes.path or "/"
    for sufijo in ("/amp", "/amp/", ".amp", "/amp.html"):
        if ruta.endswith(sufijo):
            ruta = ruta[: -len(sufijo)] or "/"
    if ruta.startswith("/amp/"):
        ruta = ruta[4:]
    ruta = ruta.rstrip("/") or "/"
    consulta = [(k, v) for k, v in parse_qsl(partes.query, keep_blank_values=False)
                if not k.lower().startswith("utm_") and k.lower() not in PARAMETROS_DESCARTABLES]
    consulta.sort()
    return urlunsplit(("https", host, ruta, urlencode(consulta), ""))


def clave(url: str) -> str:
    return hashlib.sha1(canonica(url).encode("utf-8")).hexdigest()[:16]


def dominio(url: str) -> str:
    """Dominio registrable aproximado (ej.: news.bbc.co.uk -> bbc.co.uk)."""
    try:
        host = (urlsplit(url).hostname or "").lower()
    except ValueError:
        return ""
    for prefijo in PREFIJOS_HOST:
        if host.startswith(prefijo):
            host = host[len(prefijo):]
    partes = host.split(".")
    if len(partes) >= 3 and ".".join(partes[-2:]) in SUFIJOS_DOBLES:
        return ".".join(partes[-3:])
    return ".".join(partes[-2:]) if len(partes) >= 2 else host


def host(url: str) -> str:
    try:
        return (urlsplit(url).hostname or "").lower()
    except ValueError:
        return ""
