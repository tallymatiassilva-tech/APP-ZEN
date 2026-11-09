import requests

from src.app_legacy import ZendeskAPI as LegacyZendeskAPI
from src.services import zendesk_api_service
from src.services.zendesk_api_service import ZendeskAPI


class FakeResponse:
    def __init__(self, status_code, payload=None, content=b"", headers=None):
        self.status_code = status_code
        self.payload = payload or {}
        self.content = content
        self.headers = headers or {}

    def json(self):
        return self.payload


class FakeSession:
    def __init__(self):
        self.headers = {}
        self.mounts = []
        self.get_calls = []
        self.get_results = []
        self.put_calls = []
        self.put_result = FakeResponse(200)

    def mount(self, prefix, adapter):
        self.mounts.append((prefix, adapter))

    def get(self, url, **kwargs):
        self.get_calls.append((url, kwargs))
        result = self.get_results.pop(0)
        if isinstance(result, Exception):
            raise result
        return result

    def put(self, url, **kwargs):
        self.put_calls.append((url, kwargs))
        return self.put_result


def install_fake_session(monkeypatch):
    session = FakeSession()
    monkeypatch.setattr(zendesk_api_service.requests, "Session", lambda: session)
    monkeypatch.setattr(
        zendesk_api_service,
        "HTTPAdapter",
        lambda **kwargs: ("adapter", kwargs),
    )
    return session


def test_cliente_legado_reexporta_servico_e_configura_sessao_por_thread(monkeypatch):
    session = install_fake_session(monkeypatch)
    api = ZendeskAPI("empresa", " Cookie: session=abc\r\noutra=def ")

    assert LegacyZendeskAPI is ZendeskAPI
    assert api.cookie_limpo == "session=abcoutra=def"
    assert api.session is api.session
    assert session.headers["Cookie"] == "session=abcoutra=def"
    assert session.headers["Accept"] == "application/json"
    assert session.mounts == [
        ("https://", ("adapter", {"pool_connections": 20, "pool_maxsize": 20})),
        ("http://", ("adapter", {"pool_connections": 20, "pool_maxsize": 20})),
    ]


def test_cliente_consulta_ticket_comentarios_autenticacao_e_responde(monkeypatch):
    session = install_fake_session(monkeypatch)
    session.get_results = [
        FakeResponse(200, {"user": {"name": "Talita"}}),
        FakeResponse(200, {"ticket": {"id": 42}}),
        FakeResponse(200, {"comments": [{"id": 5}]}),
    ]
    api = ZendeskAPI("empresa", "session=abc")

    assert api.validar_autenticacao() == (True, "Talita")
    assert api.obter_ticket("42") == {"id": 42}
    assert api.obter_comentarios("42") == [{"id": 5}]
    assert api.responder_ticket("42", "Resolvido", "solved") is True
    assert [call[0] for call in session.get_calls] == [
        "https://empresa.zendesk.com/api/v2/users/me.json",
        "https://empresa.zendesk.com/api/v2/tickets/42.json",
        "https://empresa.zendesk.com/api/v2/tickets/42/comments.json",
    ]
    assert session.put_calls == [
        (
            "https://empresa.zendesk.com/api/v2/tickets/42.json",
            {
                "json": {
                    "ticket": {
                        "comment": {"body": "Resolvido", "public": True},
                        "status": "solved",
                    }
                },
                "timeout": 15,
            },
        )
    ]


def test_download_reutiliza_redirecionamento_para_storage(monkeypatch):
    session = install_fake_session(monkeypatch)
    session.get_results = [
        FakeResponse(302, headers={"Location": "https://storage.example/file"})
    ]
    chamadas_storage = []

    def fake_get(url, **kwargs):
        chamadas_storage.append((url, kwargs))
        return FakeResponse(200, content=b"pdf")

    monkeypatch.setattr(zendesk_api_service.requests, "get", fake_get)

    conteudo, status = ZendeskAPI("empresa", "session=abc").baixar_conteudo(
        "https://empresa.zendesk.com/file"
    )

    assert (conteudo, status) == (b"pdf", "OK")
    assert chamadas_storage == [
        (
            "https://storage.example/file",
            {"timeout": (10, 60), "headers": {"User-Agent": "Mozilla/5.0"}},
        )
    ]


def test_download_repete_em_timeout_e_usa_pausa_crescente(monkeypatch):
    session = install_fake_session(monkeypatch)
    session.get_results = [
        requests.exceptions.Timeout("instável"),
        FakeResponse(200, content=b"conteudo"),
    ]
    pausas = []
    monkeypatch.setattr(zendesk_api_service.time, "sleep", pausas.append)
    api = ZendeskAPI("empresa", "session=abc")

    assert api.baixar_conteudo("https://empresa.zendesk.com/file", retries=2) == (
        b"conteudo",
        "OK",
    )
    assert pausas == [1.5]
    assert [call[1]["timeout"] for call in session.get_calls] == [(10, 45), (10, 45)]
