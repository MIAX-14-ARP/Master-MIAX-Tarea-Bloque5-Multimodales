"""Utilidades para generar y reconocer medios mínimos (PNG, WAV) sin dependencias externas."""
from __future__ import annotations

import io
import struct
import wave
import zlib

_FIRMA_PNG = b"\x89PNG\r\n\x1a\n"


def encode_png(width: int, height: int, rgb: bytes) -> bytes:
    """Codifica un PNG RGB de 8 bits a partir de píxeles en bruto (ancho*alto*3 bytes)."""
    if len(rgb) != width * height * 3:
        raise ValueError("el tamaño de los píxeles no coincide con las dimensiones")

    def bloque(tipo: bytes, datos: bytes) -> bytes:
        crc = zlib.crc32(tipo + datos) & 0xFFFFFFFF
        return struct.pack(">I", len(datos)) + tipo + datos + struct.pack(">I", crc)

    paso = width * 3
    filas = b"".join(b"\x00" + rgb[y * paso : (y + 1) * paso] for y in range(height))
    cabecera = struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0)
    return (
        _FIRMA_PNG + bloque(b"IHDR", cabecera)
        + bloque(b"IDAT", zlib.compress(filas)) + bloque(b"IEND", b"")
    )


def solid_png(width: int, height: int, color: tuple[int, int, int]) -> bytes:
    """PNG de un solo color."""
    return encode_png(width, height, bytes(color) * (width * height))


def silent_wav(seconds: int = 1, rate: int = 8000) -> bytes:
    """WAV mono de 16 bits en silencio."""
    buffer = io.BytesIO()
    with wave.open(buffer, "wb") as wav:
        wav.setnchannels(1)
        wav.setsampwidth(2)
        wav.setframerate(rate)
        wav.writeframes(b"\x00\x00" * rate * seconds)
    return buffer.getvalue()


def measure_audio_duration(audio: bytes) -> float | None:
    """Duración real (s) de un audio mp3/m4a/ogg/flac/wav con mutagen; None si no se puede medir."""
    try:
        with wave.open(io.BytesIO(audio)) as wav:
            return wav.getnframes() / wav.getframerate()
    except (wave.Error, EOFError, ZeroDivisionError):
        pass
    try:
        import mutagen

        ficha = mutagen.File(io.BytesIO(audio))
        largo = getattr(getattr(ficha, "info", None), "length", None)
        return float(largo) if largo else None
    except Exception:  # mutagen lanza tipos muy variados con ficheros corruptos
        return None


def detect_image_mime(data: bytes) -> str | None:
    """Tipo MIME real de una imagen según su firma, o None si no es PNG, JPEG, GIF ni WebP."""
    if data.startswith(_FIRMA_PNG):
        return "image/png"
    if data.startswith(b"\xff\xd8\xff"):
        return "image/jpeg"
    if data.startswith((b"GIF87a", b"GIF89a")):
        return "image/gif"
    if data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return "image/webp"
    return None
