"""Utilidades de texto: normalización, coincidencia de términos y tokenización."""
from __future__ import annotations

import html
import re
import unicodedata
from functools import lru_cache

_ESPACIOS = re.compile(r"\s+")
_ETIQUETAS = re.compile(r"<[^>]+>")
# Escrituras sin espacios entre palabras: la coincidencia se hace por subcadena.
_SIN_ESPACIOS = re.compile(r"[぀-ヿ㐀-鿿가-힯฀-๿]")


def limpiar_html(texto: str | None, maximo: int | None = None) -> str:
    """Quita etiquetas HTML y entidades; colapsa espacios; recorta en límite de palabra."""
    if not texto:
        return ""
    t = html.unescape(_ETIQUETAS.sub(" ", texto))
    t = _ESPACIOS.sub(" ", t).strip()
    if maximo and len(t) > maximo:
        corte = t.rfind(" ", 0, maximo)
        t = t[: corte if corte > maximo * 0.6 else maximo].rstrip(" ,;:.-") + "…"
    return t


def sin_acentos(texto: str) -> str:
    nfkd = unicodedata.normalize("NFKD", texto)
    return "".join(c for c in nfkd if not unicodedata.combining(c))


def normalizar(texto: str) -> str:
    """Minúsculas, sin acentos, comillas y guiones unificados, espacios colapsados."""
    t = unicodedata.normalize("NFKC", texto or "")
    t = t.replace("’", "'").replace("‘", "'").replace("“", '"').replace("”", '"')
    t = t.replace("–", "-").replace("—", "-")
    t = sin_acentos(t).lower()
    return _ESPACIOS.sub(" ", t).strip()


def _es_sigla(termino: str) -> bool:
    letras = re.sub(r"[^A-Za-z0-9]", "", termino)
    return termino == termino.upper() and 2 <= len(letras) <= 5 and any(c.isalpha() for c in letras)


@lru_cache(maxsize=4096)
def _patron(termino: str) -> tuple[re.Pattern, bool]:
    """Compila un término a regex. Devuelve (patrón, distingue_mayúsculas)."""
    prefijo = termino.endswith("*")
    base = termino[:-1] if prefijo else termino
    sigla = _es_sigla(base)
    if not sigla:
        base = normalizar(base)
    cuerpo = re.escape(base).replace(r"\ ", r"\s+")
    if _SIN_ESPACIOS.search(base):
        return re.compile(cuerpo), sigla
    inicio = r"(?<![\w])"
    fin = r"" if prefijo else r"(?![\w])"
    flags = 0 if sigla else re.IGNORECASE
    return re.compile(inicio + cuerpo + fin, flags), sigla


class Buscador:
    """Busca una lista de términos en textos (original y normalizado)."""

    def __init__(self, terminos: list[str] | None):
        self.terminos = [t for t in (terminos or []) if t and str(t).strip()]
        self._patrones = [(_patron(str(t)), str(t)) for t in self.terminos]

    def __bool__(self) -> bool:
        return bool(self.terminos)

    def encontrar(self, original: str, normalizado: str) -> list[str]:
        hallados = []
        for (patron, sigla), termino in self._patrones:
            objetivo = original if sigla else normalizado
            if patron.search(objetivo):
                hallados.append(termino)
        return hallados

    def hay(self, original: str, normalizado: str) -> bool:
        for (patron, sigla), _ in self._patrones:
            if patron.search(original if sigla else normalizado):
                return True
        return False


def quitar_frases(texto: str, frases: list[str]) -> str:
    """Elimina frases (insensible a mayúsculas/acentos) de un texto ya normalizado."""
    for f in frases or []:
        patron, _ = _patron(f)
        texto = patron.sub(" ", texto)
    return texto


# ---------------------------------------------------------------- tokenización

STOPWORDS = set(normalizar(" ".join("""
a al algo ante antes aquel aqui asi aun bajo cada como con contra cual cuando de del desde donde dos
el ella ellos en entre era es esa ese eso esta este esto estos fue ha han hasta hay la las le les lo los
mas me mientras muy ni no nos o otra otro para pero por porque que quien se sea segun ser si sin sobre
son su sus tambien tan te tras tu un una uno unos unas y ya yo dijo dice tras despues hoy ayer
the a an and are as at be been by for from has have he her his in is it its of on or that the their
this to was were will with after over says said new more than into about amid as up out not
""".split())).split())


def tokens(texto: str) -> set[str]:
    """Conjunto de tokens significativos (≥3 caracteres o números) de un texto."""
    t = normalizar(texto)
    t = re.sub(r"[^\w\s-]", " ", t)
    resultado = set()
    for palabra in t.replace("-", " ").split():
        if palabra in STOPWORDS:
            continue
        if palabra.isdigit():
            if len(palabra) >= 2:
                resultado.add(palabra)
            continue
        if len(palabra) < 3:
            continue
        # Plural simple (quita la "s" final) para mejorar coincidencias dentro de un idioma.
        if len(palabra) > 3 and palabra.endswith("s") and not palabra.endswith("ss"):
            palabra = palabra[:-1]
        resultado.add(palabra)
    return resultado


_SUFIJO_MEDIO = re.compile(r"\s+[-|–—]\s+[^-|–—]{2,60}$")


def titulo_normalizado_para_copias(titulo: str) -> str:
    """Normaliza un título para detectar reproducciones casi idénticas de una misma nota."""
    t = _SUFIJO_MEDIO.sub("", titulo or "")
    t = normalizar(t)
    t = re.sub(r"[^\w\s]", " ", t)
    return _ESPACIOS.sub(" ", t).strip()
