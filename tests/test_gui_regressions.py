"""Testes da janela desktop; executar com Tkinter e tela gráfica disponível."""
import time
import pytest
from src import app_legacy as app


def pump(root, seconds=.4):
    deadline=time.monotonic()+seconds
    while time.monotonic()<deadline:
        root.update()
        time.sleep(.005)


@pytest.fixture
def root():
    window=app.ctk.CTk()
    window.geometry('1100x720')
    yield window
    window.destroy()


def test_botao_desativado_restaura_posicao(root):
    button=app.BotaoArredondado3D(root, 'Teste')
    button.pack(); root.update()
    before=button.coords(button.texto_id)
    button.on_press(None); button.config_state(app.tk.DISABLED)
    button.on_release(None);button.config_state(app.tk.NORMAL)
    assert button.coords(button.texto_id)==before
    assert button.pressed is False


@pytest.mark.parametrize('key',['space','Return'])
def test_botao_teclado_aciona_uma_vez(root,key):
    calls=[]
    button=app.BotaoArredondado3D(root,'Teste',command=lambda:calls.append(True))
    button.pack();root.update();button.focus_force();root.update()
    button.event_generate(f'<KeyPress-{key}>')
    button.event_generate(f'<KeyPress-{key}>')
    button.event_generate(f'<KeyRelease-{key}>')
    pump(root,.1)
    assert calls==[True]
    button.config_state(app.tk.DISABLED)
    button.event_generate(f'<KeyPress-{key}>');button.event_generate(f'<KeyRelease-{key}>')
    pump(root,.1)
    assert calls==[True]


@pytest.mark.parametrize('success',[False,True])
def test_acesso_mantem_janela_ativa_e_conclui(root,monkeypatch,success):
    class FakeAPI:
        def __init__(self,*args): pass
        def validar_autenticacao(self):
            time.sleep(.15)
            return success,'Teste simulado'
    monkeypatch.setattr(app,'ZendeskAPI',FakeAPI)
    monkeypatch.setattr(app,'salvar_credencial',lambda *args:None)
    errors=[]
    monkeypatch.setattr(app.messagebox,'showerror',lambda *args:errors.append(args))
    gui=object.__new__(app.ZendeskAppGUI)
    gui.tela_login=root
    for name in ['entry_subdomain','entry_cookie','entry_cookie_jadlog']:
        entry=app.ctk.CTkEntry(root);entry.insert(0,'simulado');setattr(gui,name,entry)
    gui.btn_login=app.BotaoArredondado3D(root,'ACESSAR SISTEMA')
    opened=[]
    gui.construir_painel_principal=opened.append
    pulse=[];root.after(30,lambda:pulse.append(True))
    start=time.monotonic();gui.validar_login()
    assert time.monotonic()-start < .1
    assert gui.btn_login.enabled is False
    pump(root,.08)
    assert pulse==[True]
    assert not opened and not errors
    pump(root,.3)
    if success:
        assert opened==['Teste simulado']
        assert isinstance(gui.api,FakeAPI)
    else:
        assert len(errors)==1
        assert gui.btn_login.enabled is True


def test_configuracoes_controles_visiveis_na_largura_minima(root,monkeypatch,tmp_path):
    monkeypatch.chdir(tmp_path)
    manager=app.GerenciadorLayouts()
    config=app.JanelaConfiguracoes(root,manager,None)
    config.geometry('1100x720');pump(root,.15)
    def descendants(widget):
        for child in widget.winfo_children():
            yield child
            yield from descendants(child)
    labels={'📂 Carregar DAR','📂 Carregar Termo/Nota','✨ Sugerir Palavras-chave','↺ Restaurar padrão','🧾 Ver histórico','📥 Importar layouts','📤 Exportar layouts'}
    buttons=[w for w in descendants(config) if isinstance(w,app.ctk.CTkButton) and w.cget('text') in labels]
    assert len(buttons)==7
    for button in buttons:
        assert button.winfo_ismapped()
        assert button.winfo_rootx()>=config.winfo_rootx()
        assert button.winfo_rootx()+button.winfo_width()<=config.winfo_rootx()+config.winfo_width()
        assert button.winfo_width()>=button.winfo_reqwidth()
    config.destroy()
