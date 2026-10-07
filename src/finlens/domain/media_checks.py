"""Validaciones previas a las llamadas de pago: tamaño de los ficheros y audio decodificable.

Evita gastar una petición de transcripción o de visión con un fichero vacío, corrupto o enorme.
(`providers/media.py` mantiene su propio `measure_audio_duration` para los proveedores.)
"""
from __future__ import annotations

import io
import wave

MAX_AUDIO_BYTES = 25 * 1024 * 1024  # límite de subida de las APIs de transcripción
MAX_IMAGE_BYTES = 10 * 1024 * 1024
# Formatos que mutagen/wave saben medir; para el resto (p.ej. webm) no se puede validar y se deja pasar.
_MEDIBLES = (".wav", ".mp3", ".flac", ".m4a", ".ogg", ".aac")


def audio_duration(audio: bytes) -> float | None:
    """Duración real (s) de un audio wav/mp3/m4a/ogg/flac con wave o mutagen; None si no se puede decodificar."""
    try:
        with wave.open(io.BytesIO(audio)) as wav:
            return wav.getnframes() / wav.getframerate()
    except (wave.Error, EOFError, ZeroDivisionError):
        pass
    try:
        import mutagen

        ficha = mutagen.File(io.BytesIO(audio))
        largo = getattr(getattr(ficha, "info", None), "length", None)
        return float(largo) if largo is not None else None
    except Exception:  # mutagen lanza tipos muy variados con ficheros corruptos
        return None


def check_audio(audio: bytes, filename: str) -> str | None:
    """Motivo (apto para la UI) por el que el audio no debe enviarse al STT, o None si es válido."""
    if not audio:
        return "El audio está vacío."
    if len(audio) > MAX_AUDIO_BYTES:
        return f"El audio supera el límite de {MAX_AUDIO_BYTES // (1024 * 1024)} MB: recórtalo o comprímelo."
    if filename.lower().endswith(_MEDIBLES):
        duracion = audio_duration(audio)
        if duracion is None:
            return "El fichero no es un audio decodificable (¿está dañado o no es del formato indicado?)."
        if duracion <= 0:
            return "El audio no contiene muestras (duración 0 s): está vacío."
    return None


def check_image(image: bytes) -> str | None:
    """Motivo por el que la imagen no debe enviarse al modelo de visión, o None si es válida."""
    if len(image) > MAX_IMAGE_BYTES:
        return f"La imagen supera el límite de {MAX_IMAGE_BYTES // (1024 * 1024)} MB: reduce su tamaño."
    return None
