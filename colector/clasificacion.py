"""Asignación de artículos a conflictos del registro y detección de marcas en los titulares.

Reglas (en este orden; un artículo puede pertenecer a más de un conflicto, máximo 3):
  1. Término fuerte del conflicto en el título/resumen (original, inglés o español)   -> puntaje 3
  2. Lugar o actor del conflicto + vocabulario de su categoría                          -> puntaje 2
  3. Todos los grupos de términos del conflicto + vocabulario de su categoría            -> puntaje 2
Los lugares que GDELT detecta en el artículo NO bastan para asignarlo (en la primera prueba real
esa regla producía mucho ruido); se usan solo para geolocalizar.
"""
from __future__ import annotations

import re

from .texto import _es_sigla, normalizar, quitar_frases

CATEGORIAS_ARMADAS = {"guerra_estados", "guerra_civil", "otro_armado"}
_PALABRA = re.compile(r"[\w'-]+", re.UNICODE)


def textos_de(art: dict) -> tuple[str, str]:
    partes = [art.get("titulo"), art.get("resumen_privado") or art.get("resumen"),
              art.get("titulo_en"), art.get("resumen_en"), art.get("titulo_es"), art.get("resumen_es")]
    original = " \n ".join(p for p in partes if p)
    return original, normalizar(original)


def clasificar(art: dict, conf, maximo: int = 3) -> list[dict]:
    original, norm = textos_de(art)
    vocab_cache: dict[str, bool] = {}
    resultados = []
    for c in conf.conflictos:
        if c.estado != "activo":
            continue
        puntaje, motivo = 0, None
        hallados = c.fuertes.encontrar(original, norm) if c.fuertes else []
        if hallados:
            puntaje, motivo = 3, f"término: {hallados[0]}"
        else:
            if c.vocabulario not in vocab_cache:
                vocab_cache[c.vocabulario] = conf.vocabulario[c.vocabulario].hay(original, norm)
            vocab = vocab_cache[c.vocabulario]
            norm_q = quitar_frases(norm, c.quitar) if c.quitar else norm
            orig_q = original
            if c.quitar:
                for f in c.quitar:
                    orig_q = orig_q.replace(f, " ")
            if vocab and c.lugares:
                lug = c.lugares.encontrar(orig_q, norm_q)
                if lug:
                    puntaje, motivo = 2, f"lugar/actor: {lug[0]} + vocabulario"
            if not puntaje and vocab and c.grupos and all(g.hay(orig_q, norm_q) for g in c.grupos):
                puntaje, motivo = 2, "combinación de términos + vocabulario"
        if puntaje:
            resultados.append({"id": c.id, "puntaje": puntaje, "motivo": motivo})
    resultados.sort(key=lambda r: -r["puntaje"])
    if resultados and resultados[0]["puntaje"] >= 2:
        resultados = [r for r in resultados if r["puntaje"] >= 2]
    return resultados[:maximo]


def marcas(art: dict, conf) -> dict:
    """Marcas explícitas del titular: atribución a una parte, desmentido y carácter preliminar."""
    partes = [art.get("titulo"), art.get("titulo_en"), art.get("titulo_es")]
    original = " \n ".join(p for p in partes if p)
    norm = normalizar(original)
    return {k: conf.marcadores[k].hay(original, norm) for k in ("atribucion", "desmentido", "preliminar")}


class Prefiltro:
    """Filtro rápido por n-gramas para descartar titulares sin ningún término del registro."""

    def __init__(self, conf):
        self.exactos: set[str] = set()
        self.siglas: set[str] = set()
        self.prefijos: list[str] = []
        for c in conf.conflictos:
            terminos = list(c.fuertes.terminos) + list(c.lugares.terminos)
            for g in c.grupos:
                terminos += g.terminos
            for t in terminos:
                t = str(t)
                if t.endswith("*"):
                    if len(t) > 5:
                        self.prefijos.append(normalizar(t[:-1]))
                elif _es_sigla(t):
                    self.siglas.add(t)
                else:
                    self.exactos.add(normalizar(t))
        self.prefijos = sorted(set(self.prefijos))
        self.max_n = max((len(t.split()) for t in self.exactos), default=1)

    def __call__(self, titulo: str) -> bool:
        palabras_orig = _PALABRA.findall(titulo or "")
        if any(p in self.siglas for p in palabras_orig):
            return True
        palabras = [normalizar(p) for p in palabras_orig]
        for i in range(len(palabras)):
            for n in range(1, min(self.max_n, len(palabras) - i) + 1):
                if " ".join(palabras[i:i + n]) in self.exactos:
                    return True
            for pref in self.prefijos:
                if palabras[i].startswith(pref):
                    return True
        return False
