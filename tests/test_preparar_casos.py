"""Re-codificación de los MP3 sintéticos con ffmpeg (sin ejecutar ffmpeg de verdad)."""
import importlib.util
import subprocess
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("preparar_casos", RAIZ / "scripts" / "preparar_casos.py")
preparar = importlib.util.module_from_spec(spec)
spec.loader.exec_module(preparar)


def mp3(tmp_path: Path) -> Path:
    ruta = tmp_path / "audio.mp3"
    ruta.write_bytes(b"ID3original")
    return ruta


def test_sin_ffmpeg_avisa_y_conserva_el_fichero(monkeypatch, tmp_path, capsys) -> None:
    monkeypatch.setattr(preparar.shutil, "which", lambda nombre: None)
    ruta = mp3(tmp_path)
    assert preparar.recodificar_mp3(ruta) is False
    assert ruta.read_bytes() == b"ID3original" and "ffmpeg no está instalado" in capsys.readouterr().out


def test_con_ffmpeg_sustituye_el_fichero_por_el_recodificado(monkeypatch, tmp_path) -> None:
    llamadas = []

    def falso(cmd, **kw):
        llamadas.append(cmd)
        Path(cmd[-1]).write_bytes(b"ID3cbr")
        return subprocess.CompletedProcess(cmd, 0, "", "")

    monkeypatch.setattr(preparar.shutil, "which", lambda nombre: "/usr/bin/ffmpeg")
    monkeypatch.setattr(preparar.subprocess, "run", falso)
    monkeypatch.setattr(preparar, "RAIZ", tmp_path)
    ruta = mp3(tmp_path)
    assert preparar.recodificar_mp3(ruta) is True and ruta.read_bytes() == b"ID3cbr"
    assert "libmp3lame" in llamadas[0] and "128k" in llamadas[0]


def test_si_ffmpeg_falla_no_toca_el_original(monkeypatch, tmp_path) -> None:
    monkeypatch.setattr(preparar.shutil, "which", lambda nombre: "/usr/bin/ffmpeg")
    monkeypatch.setattr(
        preparar.subprocess, "run", lambda cmd, **kw: subprocess.CompletedProcess(cmd, 1, "", "error")
    )
    ruta = mp3(tmp_path)
    assert preparar.recodificar_mp3(ruta) is False and ruta.read_bytes() == b"ID3original"
