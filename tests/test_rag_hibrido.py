"""Recuperación híbrida (TF-IDF + embeddings con RRF) y embeddings simulados."""
from dataclasses import replace

import pytest

from finlens.domain.cost import Tariffs
from finlens.domain.ingest import Chunk
from finlens.domain.rag import HybridRetriever, reciprocal_rank_fusion
from finlens.orchestration.pipeline import AnalysisInput, analyze, answer_followup
from finlens.providers.base import EmbeddingProvider, EmbeddingResult, ProviderError
from finlens.providers.mock import MockEmbeddings
from finlens.providers.registry import build_mock_providers
from finlens.ui.demo_samples import demo_pdf

CHUNKS = [
    Chunk(1, "Letter from the chairman about the year."),
    Chunk(5, "Net sales 39,864 38,632 gross profit percentage 58.3% 57.8%."),
    Chunk(20, "For 2026 Inditex expects a stable gross margin."),
]

# «Multilingüe» de juguete: cada concepto es un eje, en cualquier idioma.
CONCEPTOS = {"sales": 0, "ventas": 0, "margin": 1, "margen": 1, "chairman": 2, "presidente": 2}


class EmbedderConceptos:
    model = "vendor/concepto-3"

    def __init__(self, falla_en_consulta: bool = False) -> None:
        self.llamadas: list[str] = []
        self._falla = falla_en_consulta

    def embed(self, texts, kind="document"):
        self.llamadas.append(kind)
        if kind == "query" and self._falla:
            raise ProviderError("embeddings caídos")
        vectores = []
        for t in texts:
            v = [0.0, 0.0, 0.0]
            for palabra in t.lower().replace(".", " ").replace(",", " ").split():
                if palabra in CONCEPTOS:
                    v[CONCEPTOS[palabra]] += 1.0
            vectores.append(v)
        return EmbeddingResult(vectores, self.model, tokens=len(texts), cost_usd=0.001)


def hibrido(embedder=None) -> HybridRetriever:
    emb = embedder or EmbedderConceptos()
    vectores = emb.embed([c.text for c in CHUNKS], "document").vectors
    return HybridRetriever(CHUNKS).with_embeddings(vectores, emb)


def test_rrf_premia_lo_que_aparece_en_ambas_listas() -> None:
    puntos = reciprocal_rank_fusion([[0, 1, 2], [2, 0]])
    assert puntos[0] > puntos[2] > puntos[1]
    assert puntos[0] == pytest.approx(1 / 61 + 1 / 62)


def test_solo_lexico_si_no_hay_embeddings() -> None:
    r = HybridRetriever(CHUNKS)
    assert not r.semantic and r.search_detailed("gross margin").mode == "solo TF-IDF"
    assert r.search("astronomía") == []


def test_pregunta_en_espanol_encuentra_el_informe_en_ingles() -> None:
    # TF-IDF solo no encuentra nada: no comparte términos con el texto inglés.
    assert HybridRetriever(CHUNKS).search("¿cuáles fueron las ventas?") == []
    r = hibrido().search_detailed("ventas del ejercicio", k=2)
    assert r.mode == "híbrida" and r.results[0].chunk.page == 5
    assert r.embedding is not None and r.embedding.cost_usd == 0.001


def test_la_fusion_combina_lexico_y_semantico() -> None:
    r = hibrido().search("margen gross", k=3)
    assert r[0].chunk.page in (5, 20) and len(r) == 3


def test_respeta_k_y_devuelve_siempre_algo_con_embeddings() -> None:
    assert len(hibrido().search("zzz", k=2)) == 2


def test_si_falla_la_consulta_degrada_a_tfidf_con_motivo() -> None:
    r = hibrido(EmbedderConceptos(falla_en_consulta=True)).search_detailed("gross margin")
    assert r.mode == "solo TF-IDF" and r.error == "embeddings caídos" and r.embedding is None
    assert r.results and r.results[0].chunk.page in (5, 20)


def test_los_vectores_deben_coincidir_con_los_fragmentos() -> None:
    with pytest.raises(ValueError, match="un vector por fragmento"):
        HybridRetriever(CHUNKS, [[1.0]], EmbedderConceptos())


def test_with_embeddings_no_modifica_el_original() -> None:
    base = HybridRetriever(CHUNKS)
    nuevo = base.with_embeddings([[1.0, 0, 0]] * 3, EmbedderConceptos())
    assert nuevo.semantic and not base.semantic and nuevo.embedder_model == "vendor/concepto-3"


# --- Embeddings simulados -------------------------------------------------------------------


def test_mock_embeddings_son_deterministas_normalizados_y_sin_acentos() -> None:
    emb = MockEmbeddings()
    a, b, _ = emb.embed(["Margen operativo", "margen operativo", "deuda neta"]).vectors
    c = emb.embed(["margen operativo"], "query").vectors[0]
    assert a == b == c and len(a) == MockEmbeddings.DIMS
    assert sum(x * x for x in a) == pytest.approx(1.0)
    assert sum(x * y for x, y in zip(a, emb.embed(["deuda neta"]).vectors[0], strict=True)) < 0.5
    assert isinstance(emb, EmbeddingProvider) and emb.embed([""]).vectors[0] == [0.0] * MockEmbeddings.DIMS


# --- Pipeline -------------------------------------------------------------------------------

TARIFAS = Tariffs(3.0, 15.0, 0.006, 15.0, 0.04)


def paso(resultado, nombre):
    return next(s for s in resultado.trace if s.step == nombre)


def test_el_pipeline_construye_el_indice_semantico_y_lo_anota() -> None:
    resultado = analyze(build_mock_providers(), TARIFAS, AnalysisInput(pdf=demo_pdf(), question="margen"))
    indice = paso(resultado, "Índice semántico (embeddings)")
    assert indice.ok and indice.model == "mock-embeddings" and "fragmentos" in indice.note
    assert "híbrida (TF-IDF + mock-embeddings)" in paso(resultado, "Recuperación").note
    assert resultado.retriever.semantic


def test_si_fallan_los_embeddings_el_analisis_sigue_con_tfidf_y_aviso() -> None:
    class Roto:
        model = "emb-roto"

        def embed(self, texts, kind="document"):
            raise ProviderError("sin saldo")

    providers = replace(build_mock_providers(), embeddings=Roto())
    resultado = analyze(providers, TARIFAS, AnalysisInput(pdf=demo_pdf(), question="margen"))
    assert not paso(resultado, "Índice semántico (embeddings)").ok
    assert "solo TF-IDF" in paso(resultado, "Recuperación").note and not resultado.retriever.semantic
    assert any("Índice semántico" in w and "sin saldo" in w for w in resultado.warnings)
    assert resultado.report.summary


def test_si_falla_embeber_la_consulta_se_avisa_y_se_degrada() -> None:
    class UnaVez(MockEmbeddings):
        def embed(self, texts, kind="document"):
            if kind == "query":
                raise ProviderError("timeout")
            return super().embed(texts, kind)

    providers = replace(build_mock_providers(), embeddings=UnaVez())
    resultado = analyze(providers, TARIFAS, AnalysisInput(pdf=demo_pdf(), question="margen"))
    assert "solo TF-IDF" in paso(resultado, "Recuperación").note
    assert any("Recuperación semántica no disponible" in w for w in resultado.warnings)


def test_el_chat_reutiliza_el_indice_y_solo_embebe_la_pregunta() -> None:
    llamadas: list[tuple[str, int]] = []

    class Espia(MockEmbeddings):
        def embed(self, texts, kind="document"):
            llamadas.append((kind, len(texts)))
            return super().embed(texts, kind)

    providers = replace(build_mock_providers(), embeddings=Espia())
    resultado = analyze(providers, TARIFAS, AnalysisInput(pdf=demo_pdf(), question="margen"))
    antes = list(llamadas)
    respuesta = answer_followup(providers, TARIFAS, resultado, [], "¿y la deuda?")
    assert llamadas[len(antes):] == [("query", 1)] and respuesta.step.cost_usd > 0
    assert antes[0][0] == "document" and antes.count(("document", antes[0][1])) == 1


def test_on_step_notifica_inicio_y_fin_de_cada_paso_y_started_s() -> None:
    eventos: list[tuple[str, str, bool]] = []
    resultado = analyze(
        build_mock_providers(), TARIFAS, AnalysisInput(pdf=demo_pdf(), question="margen"),
        on_step=lambda nombre, evento, registro: eventos.append((nombre, evento, registro is not None)),
    )
    nombres = [s.step for s in resultado.trace]
    for n in nombres:
        assert (n, "start", False) in eventos and (n, "end", True) in eventos
        assert eventos.index((n, "start", False)) < eventos.index((n, "end", True))
    assert all(s.started_s is not None and s.started_s >= 0 for s in resultado.trace)
    assert paso(resultado, "Análisis (LLM)").started_s >= paso(resultado, "Recuperación").started_s


def test_un_callback_defectuoso_no_tumba_el_analisis() -> None:
    def malo(nombre, evento, registro):
        raise RuntimeError("UI rota")

    resultado = analyze(
        build_mock_providers(), TARIFAS, AnalysisInput(pdf=demo_pdf(), question="x"), on_step=malo
    )
    assert resultado.report.summary


def test_on_step_en_generate_media() -> None:
    from finlens.orchestration.pipeline import generate_media

    providers = build_mock_providers()
    resultado = analyze(providers, TARIFAS, AnalysisInput(pdf=demo_pdf(), question="x"))
    finales: list[str] = []
    medios = generate_media(
        providers, TARIFAS, resultado,
        on_step=lambda n, e, r: finales.append(n) if e == "end" else None,
    )
    assert sorted(finales) == sorted(s.step for s in medios.trace)
    assert all(s.started_s is not None for s in medios.trace)


def test_las_contradicciones_se_sanean_y_estan_en_el_esquema() -> None:
    from finlens.domain.guardrails import apply_guardrails
    from finlens.domain.schemas import AnalysisReport, Citation, Finding

    cita = [Citation(origin="documento", location="p.1")]
    informe = AnalysisReport(
        summary="r", spoken_summary="r",
        contradictions=[
            Finding(statement="El gráfico cae pero el informe sube.", citations=cita),
            Finding(statement="Recomendamos comprar la acción.", citations=cita),
        ],
    )
    guard = apply_guardrails(informe)
    assert [f.statement for f in guard.report.contradictions] == ["El gráfico cae pero el informe sube."]
    assert guard.blocked and AnalysisReport(summary="a", spoken_summary="b").contradictions == []
