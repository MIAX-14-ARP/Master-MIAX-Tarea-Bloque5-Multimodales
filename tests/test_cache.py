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


def test_expulsa_el_analisis_menos_usado_al_superar_el_tope() -> None:
    cache = AnalysisCache(max_entries=2)
    cache.put_analysis("a", "A")  # type: ignore[arg-type]
    cache.put_analysis("b", "B")  # type: ignore[arg-type]
    assert cache.get_analysis("a") == "A"  # "a" pasa a ser la más reciente
    cache.put_analysis("c", "C")  # type: ignore[arg-type]
    assert cache.get_analysis("b") is None
    assert cache.get_analysis("a") == "A" and cache.get_analysis("c") == "C"


def test_el_tope_por_defecto_es_16() -> None:
    cache = AnalysisCache()
    for i in range(20):
        cache.put_analysis(f"k{i}", i)  # type: ignore[arg-type]
    assert cache.get_analysis("k0") is None and cache.get_analysis("k3") is None
    assert cache.get_analysis("k4") == 4 and cache.get_analysis("k19") == 19
    assert sum(cache.get_analysis(f"k{i}") is not None for i in range(20)) == 16


def test_reescribir_una_clave_no_cuenta_dos_veces() -> None:
    cache = AnalysisCache(max_entries=2)
    for valor in ("1", "2", "3"):
        cache.put_analysis("a", valor)  # type: ignore[arg-type]
    cache.put_analysis("b", "B")  # type: ignore[arg-type]
    assert cache.get_analysis("a") == "3" and cache.get_analysis("b") == "B"


def test_los_medios_tambien_tienen_tope() -> None:
    cache = AnalysisCache(max_entries=1)
    for i in range(10):
        cache.put_media(f"k{i}", i)  # type: ignore[arg-type]
    assert cache.get_media("k0") is None and cache.get_media("k9") == 9


def test_tope_invalido() -> None:
    import pytest

    with pytest.raises(ValueError):
        AnalysisCache(max_entries=0)


def test_la_clave_cambia_con_los_modelos_y_backends() -> None:
    from finlens.providers.base import ProviderInfo

    a = (ProviderInfo("llm", "openrouter", "m1"),)
    b = (ProviderInfo("llm", "openrouter", "m2"),)
    c = (ProviderInfo("llm", "anthropic", "m1"),)
    claves = {cache_key(BASE, demo=False, max_pdf_chars=10, providers_info=i) for i in (a, b, c, ())}
    assert len(claves) == 4


def test_la_cache_es_segura_entre_hilos() -> None:
    from concurrent.futures import ThreadPoolExecutor

    cache = AnalysisCache(max_entries=8)

    def usar(i: int) -> None:
        for j in range(50):
            cache.put_analysis(f"k{(i * 7 + j) % 20}", j)  # type: ignore[arg-type]
            cache.get_analysis(f"k{j % 20}")
            cache.put_media(f"k{j % 20}", j)  # type: ignore[arg-type]

    with ThreadPoolExecutor(max_workers=6) as pool:
        list(pool.map(usar, range(6)))
    assert len(cache._analisis) <= 8 and len(cache._medios) <= 32
