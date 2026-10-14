"""Cifrado simétrico (Fernet) de las preferencias privadas de Telegram."""
from __future__ import annotations

import json


class ErrorCifrado(Exception):
    pass


def _fernet(clave: str):
    from cryptography.fernet import Fernet
    try:
        return Fernet(clave.encode() if isinstance(clave, str) else clave)
    except (ValueError, TypeError) as e:
        raise ErrorCifrado("ESTADO_CLAVE no es una clave Fernet válida") from e


def cifrar(datos: dict, clave: str) -> str:
    return _fernet(clave).encrypt(json.dumps(datos, ensure_ascii=False).encode()).decode()


def descifrar(texto: str | None, clave: str) -> dict:
    if not texto:
        return {}
    from cryptography.fernet import InvalidToken
    try:
        return json.loads(_fernet(clave).decrypt(texto.encode()).decode())
    except InvalidToken as e:
        raise ErrorCifrado("No se pudieron descifrar las preferencias (¿cambió ESTADO_CLAVE?)") from e


def derivar_clave(secreto: str) -> str:
    """Clave Fernet determinística derivada de otro secreto (p. ej. el token del bot)."""
    import base64
    import hashlib
    digest = hashlib.sha256(("mapa-conflictos/preferencias/v1|" + secreto).encode()).digest()
    return base64.urlsafe_b64encode(digest).decode()


def nueva_clave() -> str:
    from cryptography.fernet import Fernet
    return Fernet.generate_key().decode()
