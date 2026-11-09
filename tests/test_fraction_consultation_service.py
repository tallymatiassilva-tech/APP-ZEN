from threading import Lock

from src.services import fraction_service


class FakeResponse:
    def __init__(self, *, url, content=b"", text="", status_code=200):
        self.url = url
        self.content = content
        self.text = text
        self.status_code = status_code


class FakeSession:
    def __init__(self, get_responses=(), post_responses=()):
        self.get_responses = list(get_responses)
        self.post_responses = list(post_responses)
        self.get_calls = []
        self.post_calls = []

    def get(self, url, **kwargs):
        self.get_calls.append((url, kwargs))
        return self.get_responses.pop(0)

    def post(self, url, **kwargs):
        self.post_calls.append((url, kwargs))
        return self.post_responses.pop(0)


def _callbacks(**overrides):
    callbacks = {
        "ao_cookie_expirado": lambda: None,
        "ao_erro_consulta": lambda _error: None,
        "ao_formulario_ausente": lambda _cte: None,
    }
    callbacks.update(overrides)
    return callbacks


def test_consulta_fraction_por_formulario_e_guarda_resultado_no_cache(monkeypatch):
    session = FakeSession(
        get_responses=[
            FakeResponse(
                url="https://jadlog.com.br/FractionWeb/jad/pesquisar",
                content=b"<form></form>",
            )
        ],
        post_responses=[
            FakeResponse(
                url="https://jadlog.com.br/FractionWeb/jad/pesquisar",
                content=b"resultado",
            )
        ],
    )
    monkeypatch.setattr(
        fraction_service,
        "preparar_formulario_fraction",
        lambda *_args: ("https://jadlog.com.br/pesquisar", "post", [("cte", "123456")]),
    )
    monkeypatch.setattr(
        fraction_service,
        "extrair_texto_pagina_fraction",
        lambda _content: ("soup", "Tomador: Cliente A"),
    )
    metadados = {"texto_completo": "Tomador: Cliente A"}
    monkeypatch.setattr(
        fraction_service,
        "extrair_resultado_consulta_fraction",
        lambda *_args, **_kwargs: ("Cliente A", metadados),
    )
    cache = {}

    resultado = fraction_service.consultar_fraction_por_cte(
        "123456", session, cache, Lock(), **_callbacks()
    )

    assert resultado == ("123456", "Cliente A", metadados)
    assert cache == {"123456": ("Cliente A", metadados)}
    assert session.post_calls[0][1]["data"] == [("cte", "123456")]

    resultado_cache = fraction_service.consultar_fraction_por_cte(
        "123456", session, cache, Lock(), **_callbacks()
    )
    assert resultado_cache == resultado
    assert len(session.get_calls) == 1


def test_consulta_fraction_sinaliza_sessao_expirada():
    session = FakeSession(
        get_responses=[
            FakeResponse(url="https://jadlog.com.br/login", text="login")
        ]
    )
    expiracoes = []

    resultado = fraction_service.consultar_fraction_por_cte(
        "123456",
        session,
        {},
        Lock(),
        **_callbacks(ao_cookie_expirado=lambda: expiracoes.append(True)),
    )

    assert resultado == ("123456", "COOKIE_EXPIRADO", {})
    assert expiracoes == [True]
    assert session.post_calls == []


def test_consulta_fraction_usa_fallback_tracking_sem_formulario(monkeypatch):
    session = FakeSession(
        get_responses=[
            FakeResponse(
                url="https://jadlog.com.br/FractionWeb/jad/pesquisar",
                content=b"sem formulario",
            )
        ],
        post_responses=[
            FakeResponse(
                url="https://jadlog.com.br/FractionWeb/jad/tracking",
                content=b"resultado",
            )
        ],
    )
    monkeypatch.setattr(
        fraction_service,
        "extrair_texto_pagina_fraction",
        lambda _content: ("soup", "resultado"),
    )
    metadados = {"texto_completo": "Tomador: Cliente B"}
    monkeypatch.setattr(
        fraction_service,
        "extrair_resultado_consulta_fraction",
        lambda _soup, _text, _cte, fallback=False: (
            ("Cliente B", metadados) if fallback else (None, {})
        ),
    )
    avisos = []
    cache = {}

    resultado = fraction_service.consultar_fraction_por_cte(
        "654321",
        session,
        cache,
        Lock(),
        **_callbacks(ao_formulario_ausente=avisos.append),
    )

    assert resultado == ("654321", "Cliente B", metadados)
    assert session.post_calls[0][0].endswith("/tracking")
    assert session.post_calls[0][1]["data"] == {
        "cte": "654321",
        "conhecimento": "654321",
        "remessa": "654321",
    }
    assert avisos == []
    assert cache == {"654321": ("Cliente B", metadados)}
