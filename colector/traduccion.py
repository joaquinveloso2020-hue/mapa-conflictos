"""Traducción automática local con modelos abiertos de Argos Translate (CTranslate2 + SentencePiece).

Se ejecuta dentro del runner de GitHub Actions: sin cuentas, sin cuotas y sin enviar textos a
terceros. Los idiomas sin modelo directo a español se traducen pasando por inglés (pivote).
Si un modelo no está disponible o falla, el artículo conserva el texto original y queda marcado.
"""
from __future__ import annotations

import hashlib
import json
import logging
import os
import re
import shutil
import time
import zipfile

log = logging.getLogger(__name__)

URL_INDICE = "https://raw.githubusercontent.com/argosopentech/argospm-index/main/index.json"
_ORACIONES = re.compile(r"(?<=[.!?。！？؟])\s+")


class Traductor:
    def __init__(self, directorio: str, sesion=None, max_descargas: int = 6, hilos: int = 4,
                 cache: dict | None = None):
        self.dir = directorio
        os.makedirs(self.dir, exist_ok=True)
        self.sesion = sesion
        self.max_descargas = max_descargas
        self.descargas = 0
        self.hilos = hilos
        self.cache = cache if cache is not None else {}
        self._indice: dict | None = None
        self._cargados: dict = {}
        self.sin_modelo: set[str] = set()
        self.errores: list[str] = []
        self.contador = {"traducidos": 0, "desde_cache": 0, "fallidos": 0, "sin_modelo": 0}
        self.disponible = self._importar()

    # ------------------------------------------------------------------ modelos
    def _importar(self) -> bool:
        try:
            import ctranslate2  # noqa: F401
            import sentencepiece  # noqa: F401
            return True
        except ImportError as e:
            self.errores.append(f"bibliotecas de traducción no instaladas: {e}")
            return False

    def _indice_paquetes(self) -> dict:
        if self._indice is not None:
            return self._indice
        ruta = os.path.join(self.dir, "index.json")
        datos = None
        if self.sesion is not None:
            try:
                r = self.sesion.get(URL_INDICE, timeout=30)
                if r.status_code == 200:
                    datos = r.json()
                    with open(ruta, "w", encoding="utf-8") as f:
                        json.dump(datos, f)
            except Exception as e:  # noqa: BLE001
                self.errores.append(f"índice de modelos no disponible: {type(e).__name__}")
        if datos is None and os.path.exists(ruta):
            with open(ruta, encoding="utf-8") as f:
                datos = json.load(f)
        self._indice = {(p["from_code"], p["to_code"]): p for p in (datos or [])}
        return self._indice

    def _ruta_modelo(self, origen: str, destino: str) -> str | None:
        """Devuelve la carpeta del paquete (con model/ y sentencepiece.model), descargándolo si falta."""
        base = os.path.join(self.dir, f"{origen}_{destino}")
        encontrado = self._buscar_paquete(base)
        if encontrado:
            return encontrado
        paquete = self._indice_paquetes().get((origen, destino))
        if not paquete:
            return None
        if self.sesion is None or self.descargas >= self.max_descargas:
            self.errores.append(f"modelo {origen}->{destino} pendiente de descarga")
            return None
        enlaces = [l for l in paquete.get("links", []) if l.startswith("http")]
        for enlace in enlaces:
            try:
                inicio = time.monotonic()
                r = self.sesion.get(enlace, timeout=300)
                if r.status_code != 200:
                    raise RuntimeError(f"HTTP {r.status_code}")
                tmp = base + ".zip"
                with open(tmp, "wb") as f:
                    f.write(r.content)
                with zipfile.ZipFile(tmp) as z:
                    z.extractall(base)
                os.remove(tmp)
                self.descargas += 1
                log.info("Modelo %s->%s descargado en %.0fs", origen, destino, time.monotonic() - inicio)
                return self._buscar_paquete(base)
            except Exception as e:  # noqa: BLE001
                self.errores.append(f"descarga de modelo {origen}->{destino} falló: {str(e)[:100]}")
                shutil.rmtree(base, ignore_errors=True)
        return None

    @staticmethod
    def _buscar_paquete(base: str) -> str | None:
        if not os.path.isdir(base):
            return None
        for raiz, dirs, archivos in os.walk(base):
            if "sentencepiece.model" in archivos and "model" in dirs:
                return raiz
        return None

    def _cargar(self, origen: str, destino: str):
        clave = (origen, destino)
        if clave in self._cargados:
            return self._cargados[clave]
        ruta = self._ruta_modelo(origen, destino)
        if not ruta:
            self._cargados[clave] = None
            return None
        import ctranslate2
        import sentencepiece
        if len([v for v in self._cargados.values() if v]) >= 4:  # limita memoria
            for k in list(self._cargados):
                if self._cargados[k] and k != ("en", "es"):
                    del self._cargados[k]
                    break
        try:
            traductor = ctranslate2.Translator(os.path.join(ruta, "model"), device="cpu",
                                               compute_type="int8", intra_threads=self.hilos)
            sp = sentencepiece.SentencePieceProcessor(model_file=os.path.join(ruta, "sentencepiece.model"))
        except Exception as e:  # noqa: BLE001
            self.errores.append(f"modelo {origen}->{destino} no se pudo cargar: {str(e)[:100]}")
            self._cargados[clave] = None
            return None
        self._cargados[clave] = (traductor, sp)
        return self._cargados[clave]

    def precargar(self, pares: list[tuple[str, str]]) -> list[str]:
        """Asegura que estén descargados los modelos indicados (si hay índice y red)."""
        listos = []
        if not self.disponible:
            return listos
        for o, d in pares:
            if self._ruta_modelo(o, d):
                listos.append(f"{o}->{d}")
        return listos

    def tiene_ruta(self, origen: str, destino: str = "es") -> bool:
        if origen == destino:
            return True
        indice = self._indice_paquetes()
        if (origen, destino) in indice or self._buscar_paquete(os.path.join(self.dir, f"{origen}_{destino}")):
            return True
        return ((origen, "en") in indice or origen == "en") and (("en", destino) in indice)

    # --------------------------------------------------------------- traducción
    def _directo(self, textos: list[str], origen: str, destino: str) -> list[str | None]:
        modelo = self._cargar(origen, destino)
        if not modelo:
            return [None] * len(textos)
        traductor, sp = modelo
        # Divide en oraciones para no superar la longitud útil del modelo.
        trozos, mapa = [], []
        for i, t in enumerate(textos):
            for o in _ORACIONES.split(t.strip()) or [""]:
                if o:
                    trozos.append(o[:1000])
                    mapa.append(i)
        if not trozos:
            return [""] * len(textos)
        try:
            tokenizados = sp.encode(trozos, out_type=str)
            resultados = traductor.translate_batch(tokenizados, beam_size=2, max_batch_size=32,
                                                   max_decoding_length=256)
            salidas = [sp.decode(r.hypotheses[0]) for r in resultados]
        except Exception as e:  # noqa: BLE001
            self.errores.append(f"traducción {origen}->{destino} falló: {str(e)[:100]}")
            return [None] * len(textos)
        unidos: list[list[str]] = [[] for _ in textos]
        for idx, s in zip(mapa, salidas):
            unidos[idx].append(s.replace("▁", " ").strip())
        return [" ".join(p).strip() for p in unidos]

    def traducir(self, textos: list[str], origen: str | None, destino: str = "es") -> list[dict]:
        """Traduce una lista. Cada resultado: {texto, en, estado, motor, error}."""
        resultados: list[dict] = [{} for _ in textos]
        if not origen:
            return [{"texto": None, "estado": "idioma_desconocido"} for _ in textos]
        if origen == destino:
            return [{"texto": t, "estado": "original"} for t in textos]
        if not self.disponible:
            return [{"texto": None, "estado": "fallo", "error": "motor no disponible"} for _ in textos]
        pendientes = []
        for i, t in enumerate(textos):
            if not t:
                resultados[i] = {"texto": "", "estado": "original"}
                continue
            k = hashlib.sha1(f"{origen}|{destino}|{t}".encode()).hexdigest()[:20]
            if k in self.cache:
                resultados[i] = {**self.cache[k], "estado": "ok", "motor": "argos"}
                self.contador["desde_cache"] += 1
            else:
                pendientes.append((i, t, k))
        if not pendientes:
            return resultados
        lista = [t for _, t, _ in pendientes]
        en = None
        directo_disponible = (origen, destino) in self._indice_paquetes() or \
            self._buscar_paquete(os.path.join(self.dir, f"{origen}_{destino}"))
        if directo_disponible:
            final = self._directo(lista, origen, destino)
        elif origen == "en":
            final = self._directo(lista, "en", destino)
            en = lista
        else:
            en = self._directo(lista, origen, "en")
            if all(x is None for x in en):
                final = [None] * len(lista)
            else:
                validos = [x or "" for x in en]
                final = self._directo(validos, "en", destino)
                final = [f if e else None for f, e in zip(final, en)]
        sin_ruta = not self.tiene_ruta(origen, destino)
        for (i, t, k), f, idx in zip(pendientes, final, range(len(pendientes))):
            ingles = en[idx] if en else None
            if f:
                entrada = {"texto": f, "en": ingles if origen != "en" else None}
                self.cache[k] = {**entrada, "t": int(time.time())}
                resultados[i] = {**entrada, "estado": "ok", "motor": "argos"}
                self.contador["traducidos"] += 1
            elif sin_ruta:
                self.sin_modelo.add(origen)
                resultados[i] = {"texto": None, "estado": "sin_modelo"}
                self.contador["sin_modelo"] += 1
            else:
                resultados[i] = {"texto": None, "en": ingles, "estado": "fallo",
                                 "error": "no se pudo traducir en este ciclo"}
                self.contador["fallidos"] += 1
        return resultados

    def modelos_instalados(self) -> list[str]:
        if not os.path.isdir(self.dir):
            return []
        return sorted(d for d in os.listdir(self.dir)
                      if os.path.isdir(os.path.join(self.dir, d)) and self._buscar_paquete(os.path.join(self.dir, d)))


def podar_cache(cache: dict, dias: int = 10) -> dict:
    limite = time.time() - dias * 86400
    return {k: v for k, v in cache.items() if v.get("t", 0) >= limite}
