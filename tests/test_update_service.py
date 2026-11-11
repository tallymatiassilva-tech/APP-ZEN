from src.services import update_service as u


def test_versao_mais_nova_compara_numeros():
    assert u.versao_mais_nova("v1.3.1", "1.3.0")
    assert u.versao_mais_nova("v1.10.0", "1.9.9")
    assert not u.versao_mais_nova("v1.3.0", "1.3")
    assert not u.versao_mais_nova("v1.2.9", "1.3.0")


def test_script_preserva_dados_do_usuario():
    bat = u.montar_script_bat(r"C:\t\novo", r"C:\AppZen", r"C:\AppZen\AppZen.exe", 123)
    assert '"memoria_diaria_jadlog.json"' in bat and '"layouts_custom.json"' in bat
    assert '/XD "checkpoints"' in bat
    assert 'PID eq 123' in bat


def test_fora_do_executavel_nao_verifica(monkeypatch):
    chamado = []
    monkeypatch.setattr(u, "buscar_ultima_versao", lambda: chamado.append(1))
    assert u.verificar_atualizacao_na_abertura() is False
    assert chamado == []


def test_sem_internet_retorna_none(monkeypatch):
    def falha(*a, **k):
        raise OSError("offline")
    monkeypatch.setattr(u.requests, "get", falha)
    assert u.buscar_ultima_versao() is None
