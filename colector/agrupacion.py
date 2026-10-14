"""Agrupación de artículos en acontecimientos y reglas explícitas de corroboración.

Conceptos:
  - Conflicto: situación del registro (puede abarcar varios países).
  - Acontecimiento: un hecho concreto dentro de un conflicto; lo describen uno o más artículos.
  - Artículo: una URL (deduplicada por URL canónica).

Origen de un artículo (para contar fuentes independientes):
  - si el artículo atribuye su contenido a una agencia (Reuters, AFP, EFE...), el origen es la agencia;
  - si no, es la organización del medio (dominios del mismo grupo cuentan como uno);
  - titulares casi idénticos de distintos medios se consideran reproducciones de un mismo origen.
Las fuentes oficiales o estatales de una de las partes del conflicto NO cuentan como corroboración
independiente: se identifican como "declaración de [parte]".
"""
from __future__ import annotations

import math
from collections import Counter
from datetime import datetime, timedelta, timezone

from .geografia import ubicar_evento
from .texto import titulo_normalizado_para_copias, tokens

UMBRAL_SIMILITUD = 0.5
VENTANA_HORAS = 48


def _dt(iso: str | None) -> datetime | None:
    if not iso:
        return None
    try:
        return datetime.fromisoformat(iso)
    except ValueError:
        return None


def fecha_referencia(art: dict) -> str:
    """Fecha para ordenar/filtrar: publicación si existe; si no, detección (nunca se presenta como publicación)."""
    return art.get("pub") or art.get("detectado")


class Origenes:
    def __init__(self, conf):
        f = conf.fuentes
        self.dominio_a_grupo = {d: g for g, ds in (f.get("grupos_dominios") or {}).items() for d in ds}
        self.agencias = f.get("agencias") or {}
        self.oficiales = {d: p for p, ds in (f.get("dominios_oficiales") or {}).items() for d in ds}
        self.estatales = {d: p for p, ds in (f.get("dominios_estatales") or {}).items() for d in ds}

    def agencia(self, art: dict) -> str | None:
        texto = " ".join(x for x in (art.get("resumen_privado") or art.get("resumen"), art.get("autor"),
                                     art.get("titulo")) if x)
        if not texto:
            return None
        for nombre, marcas in self.agencias.items():
            for m in marcas:
                if m in texto:
                    return nombre
        return None

    def organizacion(self, art: dict) -> str:
        dom = art.get("dominio") or ""
        if art.get("fuente_id") not in (None, "gdelt"):
            grupo = self.dominio_a_grupo.get(dom)
            return grupo or art.get("fuente_nombre") or dom
        return self.dominio_a_grupo.get(dom, dom)

    def pais_oficial(self, art: dict) -> tuple[str | None, str | None]:
        """(país, tipo) si la fuente es oficial o estatal de un país; tipo: oficial|estatal."""
        if art.get("tipo_fuente") == "oficial" and art.get("pais_medio"):
            return art["pais_medio"], "oficial"
        if art.get("propiedad") == "estatal" and art.get("pais_medio"):
            return art["pais_medio"], "estatal"
        dom = art.get("dominio") or ""
        if dom in self.oficiales:
            return self.oficiales[dom], "oficial"
        for d, p in self.oficiales.items():
            if dom.endswith("." + d):
                return p, "oficial"
        if dom in self.estatales:
            return self.estatales[dom], "estatal"
        return None, None

    def completar(self, art: dict) -> None:
        agencia = self.agencia(art)
        organizacion = self.organizacion(art)
        art["organizacion"] = organizacion
        art["agencia"] = agencia if agencia and agencia != organizacion else None
        art["origen"] = f"agencia:{agencia}" if art["agencia"] else f"medio:{organizacion}"
        pais, tipo = self.pais_oficial(art)
        art["fuente_estatal_de"] = pais
        art["fuente_estatal_tipo"] = tipo
        art["titulo_copia"] = titulo_normalizado_para_copias(art.get("titulo_en") or art.get("titulo") or "")


def tokens_articulo(art: dict) -> list[str]:
    base = art.get("titulo_en") or art.get("titulo_es") or art.get("titulo") or ""
    return sorted(tokens(base))


class Agrupador:
    def __init__(self, eventos: dict, articulos: dict, conf, geografia, ahora: datetime):
        self.eventos = eventos
        self.articulos = articulos
        self.conf = conf
        self.geo = geografia
        self.ahora = ahora
        self._idf: dict[str, float] = {}
        self._n = 1

    def preparar_idf(self) -> None:
        df: Counter = Counter()
        n = 0
        for a in self.articulos.values():
            toks = a.get("tokens")
            if toks:
                df.update(set(toks))
                n += 1
        self._n = max(n, 1)
        self._idf = {t: math.log((self._n + 1) / (c + 1)) + 1 for t, c in df.items()}

    def idf(self, t: str) -> float:
        return self._idf.get(t, math.log(self._n + 1) + 1)

    def similitud(self, a: set[str], firma: dict[str, int]) -> float:
        if not a or not firma:
            return 0.0
        b = set(firma)
        comunes = a & b
        if len(comunes) < 2:
            return 0.0
        peso_comun = sum(self.idf(t) for t in comunes)
        peso_a = sum(self.idf(t) for t in a)
        peso_b = sum(self.idf(t) for t in b)
        return peso_comun / max(min(peso_a, peso_b), 1e-6)

    def asignar(self, clave: str, conflicto_id: str) -> str:
        art = self.articulos[clave]
        toks = set(art.get("tokens") or [])
        momento = _dt(fecha_referencia(art)) or self.ahora
        mejor, mejor_sim = None, 0.0
        for ev in self.eventos.values():
            if ev["conflicto"] != conflicto_id:
                continue
            if clave in ev["articulos"]:
                return ev["id"]
            ultimo = _dt(ev["actualizado"]) or self.ahora
            if abs((momento - ultimo).total_seconds()) > VENTANA_HORAS * 3600:
                continue
            # Copia literal de un titular ya presente: mismo acontecimiento.
            if art.get("titulo_copia") and art["titulo_copia"] in ev.get("titulos_copia", []):
                mejor, mejor_sim = ev, 1.0
                break
            sim = self.similitud(toks, ev.get("firma") or {})
            if sim < UMBRAL_SIMILITUD and self._mismo_lugar_y_cifra(art, toks, ev, momento, ultimo):
                sim = UMBRAL_SIMILITUD  # coberturas en distintos idiomas sin traducción disponible
            if sim > mejor_sim and not self._lugares_incompatibles(art, ev):
                mejor, mejor_sim = ev, sim
        if mejor is None or mejor_sim < UMBRAL_SIMILITUD:
            eid = f"{conflicto_id}-{clave[:10]}"
            mejor = {"id": eid, "conflicto": conflicto_id, "creado": self.ahora.isoformat(),
                     "actualizado": fecha_referencia(art), "articulos": [], "firma": {},
                     "titulos_copia": []}
            self.eventos[eid] = mejor
        mejor["articulos"].append(clave)
        if len(mejor["articulos"]) <= 15:
            firma = Counter(mejor.get("firma") or {})
            firma.update(toks)
            mejor["firma"] = dict(firma.most_common(30))
        if art.get("titulo_copia") and art["titulo_copia"] not in mejor["titulos_copia"]:
            mejor["titulos_copia"] = (mejor["titulos_copia"] + [art["titulo_copia"]])[-30:]
        ref = fecha_referencia(art)
        if ref and (not mejor.get("actualizado") or ref > mejor["actualizado"]):
            mejor["actualizado"] = ref
        return mejor["id"]

    @staticmethod
    def _mismo_lugar_y_cifra(art: dict, toks: set[str], ev: dict, momento, ultimo) -> bool:
        """Misma ciudad del hecho + una cifra en común + menos de 12 h: mismo acontecimiento."""
        la, le = art.get("lugar") or {}, ev.get("lugar") or {}
        if la.get("precision") != "ciudad" or le.get("precision") != "ciudad" or la.get("nombre") != le.get("nombre"):
            return False
        if abs((momento - ultimo).total_seconds()) > 12 * 3600:
            return False
        cifras = {t for t in toks if t.isdigit()}
        return bool(cifras & set(ev.get("firma") or {}))

    def _lugares_incompatibles(self, art: dict, ev: dict) -> bool:
        la = (art.get("lugar") or {})
        le = (ev.get("lugar") or {})
        if la.get("precision") == "ciudad" and le.get("precision") == "ciudad" and la.get("coord") and le.get("coord"):
            (x1, y1), (x2, y2) = la["coord"], le["coord"]
            distancia_km = math.hypot((x1 - x2) * 111 * math.cos(math.radians((y1 + y2) / 2)), (y1 - y2) * 111)
            return distancia_km > 150
        return False


def estado_corroboracion(ev: dict, arts: list[dict], conflicto) -> dict:
    """Aplica las reglas explícitas de corroboración a un acontecimiento."""
    # Agrupar reproducciones: titulares casi idénticos -> origen del primero.
    por_titulo: dict[str, str] = {}
    origenes_independientes: set[str] = set()
    partes_con_fuente: dict[str, set] = {}
    for a in sorted(arts, key=lambda x: fecha_referencia(x) or ""):
        origen = a.get("origen") or f"medio:{a.get('dominio')}"
        tc = a.get("titulo_copia")
        if tc:
            if tc in por_titulo:
                origen = por_titulo[tc]
            else:
                por_titulo[tc] = origen
        a["_origen_efectivo"] = origen
        parte = conflicto.parte_de_pais(a.get("fuente_estatal_de")) if conflicto else None
        if parte:
            partes_con_fuente.setdefault(parte, set()).add(a.get("fuente_estatal_tipo") or "oficial")
            continue
        origenes_independientes.add(origen)
    n_ind = len(origenes_independientes)
    marcas = [a.get("marcas") or {} for a in arts]
    desmentidos = sum(1 for m in marcas if m.get("desmentido"))
    atribuidos = sum(1 for m in marcas if m.get("atribucion"))
    preliminares = sum(1 for m in marcas if m.get("preliminar"))
    contrapuestas = desmentidos > 0 or len(partes_con_fuente) >= 2
    if n_ind == 0 and partes_con_fuente:
        estado = "declaracion_parte"
    elif n_ind >= 2 and not (preliminares and n_ind < 3):
        estado = "varias_fuentes"
    else:
        estado = "preliminar"
    return {
        "estado": estado,
        "fuentes_independientes": n_ind,
        "origenes": sorted(o.split(":", 1)[1] for o in origenes_independientes),
        "partes_con_fuente": {p: sorted(t) for p, t in partes_con_fuente.items()},
        "contrapuestas": contrapuestas,
        "atribuida": atribuidos * 2 >= len(arts) and atribuidos > 0,
        "marcado_preliminar": preliminares > 0,
        "reglas": _explicacion(estado, n_ind, partes_con_fuente, contrapuestas, desmentidos),
    }


def _explicacion(estado, n_ind, partes, contrapuestas, desmentidos) -> str:
    if estado == "declaracion_parte":
        base = "Solo hay declaraciones o medios estatales de una parte: " + ", ".join(partes) + "."
    elif estado == "varias_fuentes":
        base = f"{n_ind} orígenes independientes (agencias y reproducciones contadas una vez)."
    else:
        base = "Un solo origen independiente o titular marcado como preliminar."
    if contrapuestas:
        base += " Hay desmentidos o versiones de partes enfrentadas." if desmentidos else \
            " Hay versiones de partes enfrentadas."
    return base


def resumir_evento(ev: dict, arts: list[dict], conflicto, geo) -> dict:
    """Arma la vista pública de un acontecimiento (sin inventar contenido)."""
    corro = estado_corroboracion(ev, arts, conflicto)
    orden = sorted(arts, key=lambda a: fecha_referencia(a) or "")
    independientes = [a for a in orden if not (conflicto and conflicto.parte_de_pais(a.get("fuente_estatal_de")))]
    candidatos = independientes or orden
    con_resumen = [a for a in candidatos if a.get("resumen_es")] or [a for a in candidatos if a.get("resumen")]
    representativo = (con_resumen or candidatos)[0]
    lugar = ubicar_evento(arts)
    fechas_pub = [a["pub"] for a in arts if a.get("pub")]
    fechas_det = [a["detectado"] for a in arts if a.get("detectado")]
    fechas_hecho = sorted({a["fecha_hecho"] for a in arts if a.get("fecha_hecho")})
    return {
        "id": ev["id"],
        "conflicto": ev["conflicto"],
        "titulo": representativo.get("titulo_es") or representativo.get("titulo"),
        "titulo_traducido": bool(representativo.get("titulo_es")) and representativo.get("idioma") != "es",
        "articulo_principal": representativo["k"],
        "lugar": lugar,
        "primera_publicacion": min(fechas_pub) if fechas_pub else None,
        "ultima_publicacion": max(fechas_pub) if fechas_pub else None,
        "primera_deteccion": min(fechas_det) if fechas_det else None,
        "ultima_deteccion": max(fechas_det) if fechas_det else None,
        "fechas_hecho": fechas_hecho[-3:],
        "referencia": max((fecha_referencia(a) or "") for a in arts),
        "n_articulos": len(arts),
        **corro,
    }
