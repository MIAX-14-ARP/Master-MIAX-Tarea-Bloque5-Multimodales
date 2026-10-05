"""Tests de la caché por hash de entrada."""
from finlens.orchestration.cache import AnalysisCache, cache_key
from finlens.orchestration.pipeline import AnalysisInput

BASE = AnalysisInput(pdf=b"pdf", question="¿margen?", chart=b"img", audio=b"aud")


def clave(inp: AnalysisInput = BASE, demo: bool = True, max_chars: int = 1000) -> str:
    return cache_key(inp, demo=demo, max_pdf_chars=max_chars)


def test_misma_entrada_misma_clave() -> None:
    assert clave() == clave(AnalysisInput(pdf=b"pdf", question="  ¿margen?  ", chart=b"img", audio=b"aud"))


def test_cualquier_cambio_relevante_cambia_la_clave() -> None:
    variantes = [
        AnalysisInput(pdf=b"otro", question="¿margen?", chart=b"img", audio=b"aud"),
        AnalysisInput(pdf=b"pdf", question="otra", chart=b"img", audio=b"aud"),
        AnalysisInput(pdf=b"pdf", question="¿margen?", chart=None, audio=b"aud"),
        AnalysisInput(pdf=b"pdf", question="¿margen?", chart=b"img", audio=None),
        AnalysisInput(pdf=b"pdf", question="¿margen?", chart=b"img", audio=b"aud", audio_role="pregunta"),
    ]
    claves = {clave(v) for v in variantes} | {clave(), clave(demo=False), clave(max_chars=5)}
    assert len(claves) == len(variantes) + 3


def test_no_hay_colisiones_por_concatenacion() -> None:
    a = AnalysisInput(pdf=b"ab", chart=b"c")
    b = AnalysisInput(pdf=b"a", chart=b"bc")
    assert clave(a) != clave(b)


def test_guarda_y_recupera() -> None:
    cache = AnalysisCache()
    assert cache.get_analysis("k") is None and cache.get_media("k") is None
    cache.put_analysis("k", "analisis")  # type: ignore[arg-type]
    cache.put_media("k", "medios")  # type: ignore[arg-type]
    assert cache.get_analysis("k") == "analisis" and cache.get_media("k") == "medios"


def test_los_medios_se_cachean_por_separado_segun_lo_solicitado() -> None:
    cache = AnalysisCache()
    cache.put_media("k", "completo")  # type: ignore[arg-type]
    cache.put_media("k", "solo audio", with_image=False)  # type: ignore[arg-type]
    assert cache.get_media("k") == "completo"
    assert cache.get_media("k", with_image=False) == "solo audio"
    assert cache.get_media("k", with_audio=False) is None
