import os
import re
import threading
import tkinter as tk
from datetime import datetime
from decimal import Decimal
from tkinter import filedialog, messagebox, ttk

import customtkinter as ctk

from src.gui.widgets import BotaoArredondado3D, configurar_dpi, definir_icone
from src.services.uf_rules import (
    limpar_texto_excel,
    normalizar_valor_monetario,
)


class ZendeskAppGUI:
    COR_FUNDO = "#DCE1E7"
    COR_CARD = "#F1F5F9"
    COR_TEXTO = "#0F172A"

    BTN_ALTA = ("#D31145", "#E61A54", "#8E0B2E")
    BTN_MEDIA = ("#E53935", "#EF5350", "#B71C1C")
    BTN_BAIXA = ("#8E0B2E", "#A30D35", "#4F0619")
    BTN_AZUL = ("#1976D2", "#2196F3", "#0D47A1")
    BTN_NEUTRO = ("#64748B", "#94A3B8", "#334155")
    BTN_CANC = ("#334155", "#475569", "#0F172A")
    BTN_LIGHT = ("#E2E8F0", "#FFFFFF", "#CBD5E1")
    BTN_CINZA = ("#475569", "#64748B", "#1E293B")

    def __init__(self, container):
        configurar_dpi()
        ctk.set_appearance_mode("Light")
        ctk.set_default_color_theme("blue")

        self.container = container
        self.app_state = container.app_state
        self.zendesk_api = container.zendesk_api
        self.fraction_service = container.fraction_service
        self.extraction_service = container.extraction_service
        self.spreadsheet_service = container.spreadsheet_service
        self.gerenciador_layouts = container.gerenciador_layouts

        self.cancelar_operacao = False
        self.ultimo_dir_base = os.path.join(os.path.expanduser("~"), "Documents")
        if not os.path.exists(self.ultimo_dir_base):
            self.ultimo_dir_base = os.getcwd()

        self.janela = None
        self.janela_config = None
        self.janela_sobre = None

        self.construir_tela_login()

    def construir_tela_login(self):
        self.tela_login = ctk.CTk()
        self.tela_login.title("Autenticação - JadLog Automação")
        self.tela_login.geometry("520x560")
        self.tela_login.configure(fg_color=self.COR_FUNDO)
        definir_icone(self.tela_login)
        self.tela_login.eval("tk::PlaceWindow . center")

        f = ctk.CTkFrame(self.tela_login, fg_color=self.COR_CARD, corner_radius=15)
        f.pack(pady=25, padx=40, fill="both", expand=True)

        ctk.CTkLabel(
            f,
            text="Automação Total JadLog",
            font=("Segoe UI", 22, "bold"),
            text_color=self.BTN_ALTA[0],
        ).pack(pady=(15, 10))

        subdomain_padrao = self.app_state.obter_credencial("subdomain", "jadloglogsticahelp")
        cookie_zd = self.app_state.obter_credencial("zendesk_cookie", "")
        cookie_frac = self.app_state.obter_credencial("jadlog_cookie", "")

        ctk.CTkLabel(
            f,
            text="🔴 AUTENTICAÇÃO ZENDESK",
            font=("Segoe UI", 11, "bold"),
            text_color=self.BTN_ALTA[0],
        ).pack(anchor="w", padx=20, pady=(10, 2))
        self.ent_subdomain = ctk.CTkEntry(f, placeholder_text="Subdomínio", width=360, height=36)
        self.ent_subdomain.insert(0, subdomain_padrao)
        self.ent_subdomain.pack(pady=4)

        self.ent_cookie_zd = ctk.CTkEntry(
            f, placeholder_text="Cookie Zendesk", show="*", width=360, height=36
        )
        self.ent_cookie_zd.insert(0, cookie_zd)
        self.ent_cookie_zd.pack(pady=4)

        ctk.CTkLabel(
            f,
            text="🔵 AUTENTICAÇÃO FRACTION",
            font=("Segoe UI", 11, "bold"),
            text_color=self.BTN_AZUL[0],
        ).pack(anchor="w", padx=20, pady=(10, 2))
        self.ent_cookie_frac = ctk.CTkEntry(
            f,
            placeholder_text="Cookie Fraction (Opcional)",
            show="*",
            width=360,
            height=36,
        )
        self.ent_cookie_frac.insert(0, cookie_frac)
        self.ent_cookie_frac.pack(pady=4)

        self.btn_login = BotaoArredondado3D(
            f, text="ACESSAR SISTEMA", width=360, height=42, command=self.validar_login
        )
        self.btn_login.pack(pady=20)

        self.tela_login.mainloop()

    def validar_login(self):
        sub = self.ent_subdomain.get().strip()
        ck_zd = self.ent_cookie_zd.get().strip()
        ck_fr = self.ent_cookie_frac.get().strip()

        if not sub or not ck_zd:
            return messagebox.showwarning("Aviso", "Preencha subdomínio e Cookie Zendesk.")

        self.btn_login.config_state(tk.DISABLED, text="VALIDANDO...")
        self.tela_login.update()

        self.zendesk_api.subdomain = sub
        self.zendesk_api.atualizar_cookie(ck_zd)
        self.fraction_service.atualizar_cookie(ck_fr)

        ok, msg = self.zendesk_api.validar_autenticacao()
        if ok:
            self.app_state.salvar_credencial("subdomain", sub)
            self.app_state.salvar_credencial("zendesk_cookie", ck_zd)
            self.app_state.salvar_credencial("jadlog_cookie", ck_fr)
            self.tela_login.withdraw()
            self.construir_painel_principal(msg)
        else:
            messagebox.showerror("Erro", f"Falha na autenticação:\n{msg}")
            self.btn_login.config_state(tk.NORMAL, text="ACESSAR SISTEMA")

    def construir_painel_principal(self, operador: str):
        self.janela = ctk.CTk()
        self.janela.title(f"Automação Jadlog - Operador: {operador}")
        self.janela.geometry("1350x850")
        self.janela.minsize(1050, 650)
        self.janela.configure(fg_color=self.COR_FUNDO)
        definir_icone(self.janela)

        self.janela.protocol(
            "WM_DELETE_WINDOW",
            lambda: (self.tela_login.destroy(), self.janela.destroy()),
        )

        # Sidebar
        sidebar = ctk.CTkScrollableFrame(self.janela, width=240, fg_color=self.COR_CARD)
        sidebar.pack(side="left", fill="y", expand=False)

        ctk.CTkLabel(
            sidebar,
            text="Painel de Ações",
            font=("Segoe UI", 16, "bold"),
            text_color=self.BTN_ALTA[0],
        ).pack(pady=10)

        def _b(txt, paleta, acao, h=36):
            btn = BotaoArredondado3D(
                sidebar,
                text=txt,
                cor_base=paleta[0],
                cor_hover=paleta[1],
                cor_sombra=paleta[2],
                width=200,
                height=h,
                bg_app=self.COR_CARD,
                command=lambda: self.executar_acao(acao),
            )
            btn.pack(pady=4)

        _b("📥 Baixar Anexos", self.BTN_NEUTRO, "anexos")
        _b("📊 Relatório Zendesk", self.BTN_ALTA, "planilha_zd")
        _b("📁 Relatório Pasta", self.BTN_NEUTRO, "planilha_pasta")
        _b("📄 Carregar Planilha", self.BTN_NEUTRO, "planilha_carregar")
        _b("⚙️ Configurações", self.BTN_AZUL, "configuracoes")

        _b("🔎 Buscar Tomadores", self.BTN_AZUL, "conciliar_tomador")
        _b("🔄 Atualizar Tabela", self.BTN_NEUTRO, "atualizar_tabela")

        _b("💾 Salvar Final", self.BTN_BAIXA, "salvar_final")
        _b("⏹ Cancelar Ação", self.BTN_CANC, "cancelar")
        _b("ℹ️ Sobre", self.BTN_LIGHT, "sobre", 30)

        # Main Workspace
        main = ctk.CTkFrame(self.janela, fg_color="transparent")
        main.pack(side="right", fill="both", expand=True, padx=20, pady=15)

        # Cards KPI
        cards = ctk.CTkFrame(main, fg_color="transparent")
        cards.pack(fill="x", pady=(0, 10))

        def _card(titulo, valor, cor):
            cd = ctk.CTkFrame(cards, fg_color=self.COR_CARD, border_width=2, border_color=cor)
            cd.pack(side="left", fill="both", expand=True, padx=4)
            ctk.CTkLabel(cd, text=titulo, font=("Segoe UI", 9, "bold")).pack(
                anchor="w", padx=8, pady=(4, 0)
            )
            lbl = ctk.CTkLabel(cd, text=valor, font=("Segoe UI", 13, "bold"), text_color=cor)
            lbl.pack(anchor="w", padx=8, pady=(0, 4))
            return lbl

        self.lbl_card_ok = _card("🟢 GUIAS OK", "0", "#2E7D32")
        self.lbl_card_venc = _card("🟧 VENCIDAS", "0", "#D97706")
        self.lbl_card_quar = _card("🔴 QUARENTENA", "0", "#D31145")
        self.lbl_card_val = _card("💰 VALOR TOTAL", "R$ 0,00", "#1976D2")

        # Entrada de tickets
        f_in = ctk.CTkFrame(main, fg_color=self.COR_CARD)
        f_in.pack(fill="x", pady=(0, 8))
        ctk.CTkLabel(
            f_in, text="IDs dos Tickets (1 por linha):", font=("Segoe UI", 10, "bold")
        ).pack(anchor="w", padx=10, pady=(4, 0))
        self.txt_tickets = ctk.CTkTextbox(f_in, height=65, font=("Consolas", 12))
        self.txt_tickets.pack(fill="both", expand=True, padx=10, pady=(2, 6))

        # Tabela Central
        self.colunas = [
            ("termo", "TERMO/CONTROLE", 120),
            ("uf", "UF", 50),
            ("ticket", "TICKET", 90),
            ("doc_guia", "CPF/CNPJ GUIA", 140),
            ("status", "STATUS CONF.", 160),
            ("barras", "BARRAS (44)", 380),
            ("vencimento", "VENCIMENTO", 100),
            ("valor", "VALOR (R$)", 90),
            ("cte", "CTE / REMESSA", 150),
            ("tomador", "TOMADOR", 180),
            ("num_arquivo", "NÚMERO ARQUIVO", 110),
            ("chave", "CHAVE ARQUIVO", 170),
        ]

        t_frame = ctk.CTkFrame(main, fg_color=self.COR_CARD)
        t_frame.pack(fill="both", expand=True, pady=4)
        self.tabela = ttk.Treeview(t_frame, columns=[c[0] for c in self.colunas], show="headings")
        for col, titulo, largura in self.colunas:
            self.tabela.heading(col, text=titulo)
            self.tabela.column(
                col,
                width=largura,
                anchor="center" if col in ("uf", "ticket", "vencimento") else "w",
            )

        sc_y = ttk.Scrollbar(t_frame, orient="vertical", command=self.tabela.yview)
        sc_x = ttk.Scrollbar(t_frame, orient="horizontal", command=self.tabela.xview)
        self.tabela.configure(yscrollcommand=sc_y.set, xscrollcommand=sc_x.set)
        self.tabela.pack(side="left", fill="both", expand=True)
        sc_y.pack(side="right", fill="y")
        sc_x.pack(side="bottom", fill="x")

        # Barra de Progresso e Logs
        b_frame = ctk.CTkFrame(main, fg_color="transparent")
        b_frame.pack(fill="x", pady=(4, 0))
        self.progresso_var = tk.DoubleVar()
        self.barra = ctk.CTkProgressBar(
            b_frame,
            variable=self.progresso_var,
            progress_color=self.BTN_ALTA[0],
            height=10,
        )
        self.barra.pack(fill="x", pady=2)
        self.txt_logs = ctk.CTkTextbox(b_frame, height=90, font=("Consolas", 10))
        self.txt_logs.pack(fill="x")

        self.atualizar_tabela_gui()
        self.janela.mainloop()

    def log(self, msg: str):
        if self.janela:
            self.janela.after(
                0,
                lambda: (
                    self.txt_logs.insert(
                        tk.END, f"[{datetime.now().strftime('%H:%M:%S')}] {msg}\n"
                    ),
                    self.txt_logs.see(tk.END),
                ),
            )

    def atualizar_progresso(self, atual: int, total: int):
        if self.janela:
            self.janela.after(0, lambda: self.progresso_var.set(atual / total if total > 0 else 0))

    def atualizar_cards_metricas(self):
        dados = self.app_state.dados_em_memoria
        ok, venc, quar = 0, 0, 0
        total_val = Decimal("0.00")
        hoje = datetime.now().date()

        for item in dados:
            st = str(item.get("STATUS CONFERÊNCIA", "OK")).upper()
            venc_str = str(item.get("VENCIMENTO", ""))
            val_str = str(item.get("VALOR", ""))

            esta_venc = False
            for p in venc_str.split(","):
                try:
                    if datetime.strptime(p.strip(), "%d/%m/%Y").date() < hoje:
                        esta_venc = True
                except Exception:  # noqa: BLE001, S110
                    pass

            if esta_venc:
                venc += 1
            elif "INCOMPLETO" in st or "DIVERGÊNCIA" in st:
                quar += 1
            else:
                ok += 1

            for v in val_str.split(","):
                try:
                    total_val += Decimal(normalizar_valor_monetario(v).replace(",", "."))
                except Exception:  # noqa: BLE001, S110
                    pass

        val_fmt = f"R$ {total_val:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")
        self.lbl_card_ok.configure(text=str(ok))
        self.lbl_card_venc.configure(text=str(venc))
        self.lbl_card_quar.configure(text=str(quar))
        self.lbl_card_val.configure(text=val_fmt)

    def atualizar_tabela_gui(self):
        for item in self.tabela.get_children():
            self.tabela.delete(item)

        for d in self.app_state.dados_em_memoria:
            valores = (
                limpar_texto_excel(d.get("TERMO")),
                limpar_texto_excel(d.get("UF", "GERAL")),
                limpar_texto_excel(d.get("TICKET")),
                limpar_texto_excel(d.get("CPF/CNPJ DA GUIA")),
                limpar_texto_excel(d.get("STATUS CONFERÊNCIA", "OK")),
                limpar_texto_excel(d.get("CODIGO BARRAS", "Sem Código")),
                limpar_texto_excel(d.get("VENCIMENTO")),
                limpar_texto_excel(d.get("VALOR")),
                limpar_texto_excel(d.get("CTE / REMESSA") or d.get("CTE")),
                limpar_texto_excel(d.get("TOMADOR")),
                limpar_texto_excel(d.get("NÚMERO ARQUIVO")),
                limpar_texto_excel(d.get("CHAVE ARQUIVO")),
            )
            self.tabela.insert("", tk.END, values=valores)

        self.atualizar_cards_metricas()

    def obter_tickets(self) -> list[str]:
        txt = self.txt_tickets.get("0.0", tk.END).strip()
        return re.findall(r"\b\d{6,9}\b", txt)

    def executar_acao(self, acao: str):
        if acao == "cancelar":
            self.cancelar_operacao = True
            self.log("[!] Parada solicitada pelo usuário.")
            return

        if acao == "atualizar_tabela":
            self.atualizar_tabela_gui()
            return

        if acao == "planilha_carregar":
            arq = filedialog.askopenfilename(filetypes=[("Planilhas", "*.xlsx;*.csv")])
            if arq:
                threading.Thread(
                    target=self._carregar_planilha_thread, args=(arq,), daemon=True
                ).start()
            return

        if acao == "conciliar_tomador":
            threading.Thread(target=self._conciliar_tomador_thread, daemon=True).start()
            return

        if acao == "salvar_final":
            arq = filedialog.asksaveasfilename(
                defaultextension=".xlsx", filetypes=[("Excel", "*.xlsx")]
            )
            if arq:
                self.spreadsheet_service.exportar_multisheets()
                self.log(f"[✓] Relatório final salvo em: {arq}")
            return

        tickets = self.obter_tickets()
        if not tickets:
            return messagebox.showwarning("Aviso", "Informe ao menos um número de ticket.")

        elif acao == "anexos":
            pasta = filedialog.askdirectory(title="Destino dos Anexos")
            if pasta:
                threading.Thread(
                    target=self._baixar_anexos_thread,
                    args=(tickets, pasta),
                    daemon=True,
                ).start()
        elif acao == "planilha_zd":
            arq = filedialog.asksaveasfilename(
                defaultextension=".xlsx", filetypes=[("Excel", "*.xlsx")]
            )
            if arq:
                threading.Thread(
                    target=self._extrair_zendesk_thread,
                    args=(tickets, arq),
                    daemon=True,
                ).start()

    def _carregar_planilha_thread(self, caminho: str):
        self.log(f"[Carregar] Lendo planilha: {os.path.basename(caminho)}...")
        dados = self.spreadsheet_service.carregar_planilha(caminho)
        self.app_state.dados_em_memoria = dados
        self.app_state.salvar_memoria()
        self.janela.after(0, self.atualizar_tabela_gui)
        self.log(f"[✓] {len(dados)} registro(s) carregado(s) com sucesso.")

    def _conciliar_tomador_thread(self):
        dados = self.app_state.dados_em_memoria
        if not dados:
            return self.log("[!] Nenhum dado na memória para conciliar.")

        self.log("[Fraction] Iniciando consulta automatizada de tomadores...")
        total = len(dados)
        for idx, item in enumerate(dados, 1):
            if self.cancelar_operacao:
                break

            cte_raw = (
                str(item.get("CTE / REMESSA") or item.get("CTE") or "")
                .replace("Sem CTE", "")
                .strip()
            )
            ctes = re.findall(r"\b\d{6,15}\b", cte_raw)
            if not ctes:
                continue

            _, tomador, meta = self.fraction_service.consultar_cte(ctes[0])
            if tomador == "COOKIE_EXPIRADO":
                self.log("[ERRO] Sessão Fraction expirada.")
                break
            if tomador:
                item["TOMADOR"] = tomador
                if meta.get("dacte"):
                    item["DACTE"] = meta["dacte"]
                item["STATUS CONFERÊNCIA"] = "VALIDADO NO FRACTION"
                self.log(f"[✓] CTe {ctes[0]} -> Tomador: {tomador}")

            self.atualizar_progresso(idx, total)

        self.app_state.salvar_memoria()
        self.janela.after(0, self.atualizar_tabela_gui)
        self.log("[✓] Conciliação com Fraction finalizada.")

    def _baixar_anexos_thread(self, tickets: list[str], pasta_destino: str):
        self.log(f"[Anexos] Iniciando download de {len(tickets)} tickets...")
        self.extraction_service.baixar_e_organizar_anexos(
            tickets,
            pasta_destino,
            self.zendesk_api,
            lambda at, tot: self.atualizar_progresso(at, tot),
        )
        self.log(f"[✓] Downloads concluídos em {pasta_destino}.")

    def _extrair_zendesk_thread(self, tickets: list[str], caminho_saida: str):
        self.log(f"[Zendesk] Extraindo dados de {len(tickets)} tickets...")
        dados = self.extraction_service.processar_lote_tickets(
            tickets, self.zendesk_api, lambda at, tot: self.atualizar_progresso(at, tot)
        )
        self.app_state.dados_em_memoria = dados
        self.spreadsheet_service.exportar_multisheets()
        self.app_state.salvar_memoria()
        self.janela.after(0, self.atualizar_tabela_gui)
        self.log(f"[✓] Extração concluída e salva em: {caminho_saida}")
