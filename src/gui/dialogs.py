import json
import os
import re
import threading
import tkinter as tk
from tkinter import filedialog, messagebox, ttk

import customtkinter as ctk

from src.gui.widgets import BotaoArredondado3D, definir_icone
from src.services.document_classifier import e_dar_documento, e_termo_documento
from src.services.pdf_service import extrair_texto_pdf, mesclar_pdfs
from src.services.uf_rules import (
    extrair_numero_termo_pdf,
    formatar_numero_arquivo,
    padronizar_data_ddmmyyyy,
)


class JanelaSobre(ctk.CTkToplevel):
    def __init__(self, parent):
        super().__init__(parent)
        self.title("ℹ️ Sobre o Aplicativo")
        self.geometry("480x420")
        self.resizable(False, False)
        self.configure(fg_color="#DCE1E7")
        definir_icone(self)
        self.after(100, self.focar_janela)
        self.construir_interface()

    def focar_janela(self):
        self.lift()
        self.focus_force()

    def construir_interface(self):
        c = ctk.CTkFrame(self, fg_color="#F1F5F9", corner_radius=12)
        c.pack(fill="both", expand=True, padx=20, pady=20)
        ctk.CTkLabel(
            c,
            text="Automação Total JadLog",
            font=("Segoe UI", 18, "bold"),
            text_color="#D31145",
        ).pack(pady=(15, 5))
        ctk.CTkFrame(c, height=2, fg_color="#CBD5E1").pack(fill="x", pady=5, padx=15)
        ctk.CTkLabel(
            c,
            text="Desenvolvido por: TALITA MATIAS SILVA",
            font=("Segoe UI", 11, "bold"),
        ).pack(anchor="w", padx=20, pady=(10, 2))
        ctk.CTkLabel(
            c, text="Versão: 1.3 - Arquitetura Modular", font=("Segoe UI", 10)
        ).pack(anchor="w", padx=20, pady=2)
        ctk.CTkLabel(
            c,
            text="Automação, conferência de guias (DAR/DARE), termos e conciliação de tomadores.",
            font=("Segoe UI", 10),
            wraplength=400,
            justify="left",
        ).pack(anchor="w", padx=20, pady=(10, 20))
        ctk.CTkButton(
            c, text="Fechar", width=120, fg_color="#475569", command=self.destroy
        ).pack(pady=10)


class JanelaConfiguracoes(ctk.CTkToplevel):
    def __init__(self, parent, gerenciador_layouts, gerenciador_dedicados, app_gui):
        super().__init__(parent)
        self.gerenciador_layouts = gerenciador_layouts
        self.gerenciador_dedicados = gerenciador_dedicados
        self.app_gui = app_gui

        self.title("⚙️ Painel de Configurações e Layouts")
        self.geometry("1340x880")
        self.minsize(1100, 720)
        self.configure(fg_color="#DCE1E7")
        definir_icone(self)

        self.texto_pdf1, self.pdf1_bytes, self.nome_pdf1 = "", None, ""
        self.texto_pdf2, self.pdf2_bytes, self.nome_pdf2 = "", None, ""

        self.construir_interface()
        self.after(100, lambda: (self.lift(), self.focus_force()))

    def construir_interface(self):
        self.tabview = ctk.CTkTabview(
            self, fg_color="#F1F5F9", segmented_button_selected_color="#D31145"
        )
        self.tabview.pack(fill="both", expand=True, padx=15, pady=15)
        self.tab_layouts = self.tabview.add("🎓 Gestor Layouts (Aprendizado Duplo)")
        self.tab_dedicados = self.tabview.add("👥 Clientes Dedicados")
        self._construir_aba_layouts()
        self._construir_aba_dedicados()

    def _construir_aba_layouts(self):
        top = ctk.CTkFrame(self.tab_layouts, fg_color="#E2E8F0")
        top.pack(fill="x", padx=10, pady=8)

        ctk.CTkLabel(top, text="Inspeção Dupla:", font=("Segoe UI", 11, "bold")).pack(
            side="left", padx=5
        )
        ctk.CTkButton(
            top,
            text="📂 Carregar DAR",
            fg_color="#1976D2",
            height=28,
            command=lambda: self.carregar_pdf(1),
        ).pack(side="left", padx=3)
        ctk.CTkButton(
            top,
            text="📂 Carregar Termo/Nota",
            fg_color="#0284C7",
            height=28,
            command=lambda: self.carregar_pdf(2),
        ).pack(side="left", padx=3)
        ctk.CTkButton(
            top,
            text="✨ Sugerir Chaves",
            fg_color="#475569",
            height=28,
            command=self.sugerir_chaves,
        ).pack(side="left", padx=3)

        self.ent_busca_layout = ctk.CTkEntry(
            top, placeholder_text="Filtrar...", width=160, height=28
        )
        self.ent_busca_layout.pack(side="right", padx=5)
        self.ent_busca_layout.bind(
            "<KeyRelease>", lambda e: self.atualizar_tabela_layouts()
        )

        center = ctk.CTkFrame(self.tab_layouts, fg_color="transparent")
        center.pack(fill="both", expand=True, padx=5, pady=5)

        # Lado Esquerdo - Previews
        left = ctk.CTkFrame(center, fg_color="#FFFFFF", width=380)
        left.pack(side="left", fill="both", expand=True, padx=3)
        self.txt_p1 = ctk.CTkTextbox(left, font=("Consolas", 8))
        self.txt_p1.pack(fill="both", expand=True, pady=2, padx=4)
        self.txt_p2 = ctk.CTkTextbox(left, font=("Consolas", 8))
        self.txt_p2.pack(fill="both", expand=True, pady=2, padx=4)

        # Centro - Entradas de Regex
        mid = ctk.CTkScrollableFrame(center, fg_color="#FFFFFF", width=380)
        mid.pack(side="left", fill="both", expand=True, padx=3)

        self.ent_nome = self._add_entry(mid, "Nome Layout:")
        self.ent_uf = self._add_entry(mid, "UF:", "AL")
        self.ent_chaves = self._add_entry(
            mid, "Palavras-chave (separadas por vírgula):"
        )
        self.ent_r_termo = self._add_entry(mid, "Regex Termo:", r"(\d{6,15})")
        self.ent_r_venc = self._add_entry(
            mid, "Regex Vencimento:", r"(\d{2}/\d{2}/\d{4})"
        )
        self.ent_r_valor = self._add_entry(
            mid, "Regex Valor:", r"(\d{1,3}(?:\.\d{3})*,\d{2})"
        )
        self.ent_r_barras = self._add_entry(mid, "Regex Barras:", r"(\b8\d{43,47}\b)")
        self.ent_r_cte = self._add_entry(
            mid, "Regex CTE:", r"(?:CTE|Remessa)\s*[:=-]?\s*([\d/]+)"
        )
        self.ent_r_nota = self._add_entry(
            mid, "Regex Número Arquivo:", r"(?:DANFE|NF-E)\s*[:=-]?\s*(\d+)"
        )

        ctk.CTkButton(
            mid,
            text="🧪 Validar Cruzamento",
            fg_color="#1976D2",
            command=self.testar_regex,
        ).pack(fill="x", padx=10, pady=5)
        ctk.CTkButton(
            mid, text="💾 Salvar Layout", fg_color="#D31145", command=self.salvar_layout
        ).pack(fill="x", padx=10, pady=5)

        # Lado Direito - Resultados e Lista de Layouts
        right = ctk.CTkFrame(center, fg_color="#FFFFFF", width=340)
        right.pack(side="right", fill="both", expand=True, padx=3)
        self.txt_res = ctk.CTkTextbox(right, font=("Consolas", 9), height=200)
        self.txt_res.pack(fill="x", padx=6, pady=4)

        self.tree_layouts = ttk.Treeview(
            right, columns=("nome", "uf"), show="headings", height=8
        )
        self.tree_layouts.heading("nome", text="NOME")
        self.tree_layouts.heading("uf", text="UF")
        self.tree_layouts.pack(fill="both", expand=True, padx=6, pady=4)
        self.tree_layouts.bind("<<TreeviewSelect>>", self.carregar_layout_selecionado)

        self.atualizar_tabela_layouts()

    def _add_entry(self, parent, label, default=""):
        ctk.CTkLabel(parent, text=label, font=("Segoe UI", 9, "bold")).pack(
            anchor="w", padx=10, pady=(4, 0)
        )
        e = ctk.CTkEntry(parent, font=("Consolas", 9), height=26)
        if default:
            e.insert(0, default)
        e.pack(fill="x", padx=10, pady=2)
        return e

    def _construir_aba_dedicados(self):
        c = ctk.CTkFrame(self.tab_dedicados, fg_color="#FFFFFF")
        c.pack(fill="both", expand=True, padx=10, pady=10)

        f_form = ctk.CTkFrame(c, fg_color="#F8FAFC")
        f_form.pack(fill="x", padx=10, pady=5)
        self.ent_ded_nome = ctk.CTkEntry(
            f_form, placeholder_text="Cliente/Tomador", width=250
        )
        self.ent_ded_nome.pack(side="left", padx=4, pady=6)
        self.ent_ded_doc = ctk.CTkEntry(f_form, placeholder_text="CNPJ/CPF", width=160)
        self.ent_ded_doc.pack(side="left", padx=4, pady=6)
        self.ent_ded_obs = ctk.CTkEntry(
            f_form, placeholder_text="Observação", width=220
        )
        self.ent_ded_obs.pack(side="left", padx=4, pady=6)
        ctk.CTkButton(
            f_form,
            text="Salvar",
            width=90,
            fg_color="#1976D2",
            command=self.salvar_dedicado,
        ).pack(side="left", padx=4)

        tabela_frame = tk.Frame(c)
        tabela_frame.pack(fill="both", expand=True, padx=10, pady=5)
        self.tree_dedicados = ttk.Treeview(
            tabela_frame, columns=("nome", "doc", "obs"), show="headings"
        )
        self.tree_dedicados.heading("nome", text="CLIENTE")
        self.tree_dedicados.heading("doc", text="CNPJ / CPF")
        self.tree_dedicados.heading("obs", text="OBSERVAÇÃO")
        self.tree_dedicados.pack(side="left", fill="both", expand=True)

        sc = ttk.Scrollbar(tabela_frame, command=self.tree_dedicados.yview)
        sc.pack(side="right", fill="y")
        self.tree_dedicados.configure(yscrollcommand=sc.set)

        botoes = ctk.CTkFrame(c, fg_color="transparent")
        botoes.pack(fill="x", padx=10, pady=5)
        ctk.CTkButton(
            botoes,
            text="🗑️ Excluir Selecionado",
            fg_color="#B71C1C",
            command=self.excluir_dedicado,
        ).pack(side="left")

        self.atualizar_tabela_dedicados()

    def carregar_pdf(self, n):
        arq = filedialog.askopenfilename(filetypes=[("PDF", "*.pdf")])
        if not arq:
            return
        with open(arq, "rb") as f:
            b = f.read()
        txt, _ = extrair_texto_pdf(b)
        if n == 1:
            self.texto_pdf1, self.pdf1_bytes = txt, b
            self.txt_p1.delete("0.0", tk.END)
            self.txt_p1.insert(tk.END, txt)
        else:
            self.texto_pdf2, self.pdf2_bytes = txt, b
            self.txt_p2.delete("0.0", tk.END)
            self.txt_p2.insert(tk.END, txt)
        self.testar_regex()

    def sugerir_chaves(self):
        txt = (self.texto_pdf1 or self.texto_pdf2)[:600].upper()
        palavras = [
            p
            for p in re.findall(r"\b[A-ZÁÉÍÓÚ]{4,}\b", txt)
            if p not in ("DOCUMENTO", "VALOR", "DATA", "ESTADO")
        ]
        if palavras:
            self.ent_chaves.delete(0, tk.END)
            self.ent_chaves.insert(0, ", ".join(dict.fromkeys(palavras[:4])))

    def testar_regex(self):
        txt = (self.texto_pdf1 + "\n" + self.texto_pdf2).strip()
        if not txt:
            return

        def _get(reg, target):
            try:
                m = re.search(reg, target, re.IGNORECASE)
                return (
                    m.group(1 if m.groups() else 0).strip() if m else "Não localizado"
                )
            except Exception as e:
                return f"Erro: {e}"

        termo = _get(self.ent_r_termo.get(), txt)
        venc = padronizar_data_ddmmyyyy(
            _get(self.ent_r_venc.get(), self.texto_pdf1 or txt)
        )
        valor = _get(self.ent_r_valor.get(), self.texto_pdf1 or txt)
        barras = _get(self.ent_r_barras.get(), txt)

        self.txt_res.delete("0.0", tk.END)
        self.txt_res.insert(
            tk.END,
            f"TERMO: {termo}\nVENCIMENTO: {venc}\nVALOR: {valor}\nBARRAS: {barras}",
        )

    def salvar_layout(self):
        nome = self.ent_nome.get().strip().upper()
        if not nome:
            return messagebox.showwarning("Atenção", "Informe o nome.")
        cfg = {
            "uf": self.ent_uf.get().strip().upper(),
            "palavras_chave": [
                k.strip() for k in self.ent_chaves.get().split(",") if k.strip()
            ],
            "regex_termo": self.ent_r_termo.get().strip(),
            "regex_vencimento": self.ent_r_venc.get().strip(),
            "regex_valor": self.ent_r_valor.get().strip(),
            "regex_cod_barras": self.ent_r_barras.get().strip(),
            "regex_cte": self.ent_r_cte.get().strip(),
            "regex_num_arquivo": self.ent_r_nota.get().strip(),
        }
        self.gerenciador_layouts.layouts[nome] = cfg
        self.gerenciador_layouts.salvar_layouts()
        self.atualizar_tabela_layouts()
        messagebox.showinfo("Sucesso", f"Layout {nome} salvo!")

    def atualizar_tabela_layouts(self):
        for i in self.tree_layouts.get_children():
            self.tree_layouts.delete(i)
        filtro = self.ent_busca_layout.get().strip().upper()
        for k, v in self.gerenciador_layouts.layouts.items():
            if not filtro or filtro in k.upper():
                self.tree_layouts.insert("", tk.END, values=(k, v.get("uf", "GERAL")))

    def carregar_layout_selecionado(self, event):
        sel = self.tree_layouts.selection()
        if not sel:
            return
        nome = self.tree_layouts.item(sel[0], "values")[0]
        cfg = self.gerenciador_layouts.layouts.get(nome, {})
        self.ent_nome.delete(0, tk.END)
        self.ent_nome.insert(0, nome)
        self.ent_uf.delete(0, tk.END)
        self.ent_uf.insert(0, cfg.get("uf", ""))
        self.ent_chaves.delete(0, tk.END)
        self.ent_chaves.insert(0, ", ".join(cfg.get("palavras_chave", [])))
        self.ent_r_termo.delete(0, tk.END)
        self.ent_r_termo.insert(0, cfg.get("regex_termo", ""))
        self.ent_r_venc.delete(0, tk.END)
        self.ent_r_venc.insert(0, cfg.get("regex_vencimento", ""))
        self.ent_r_valor.delete(0, tk.END)
        self.ent_r_valor.insert(0, cfg.get("regex_valor", ""))
        self.ent_r_barras.delete(0, tk.END)
        self.ent_r_barras.insert(0, cfg.get("regex_cod_barras", ""))
        self.testar_regex()

    def salvar_dedicado(self):
        nome = self.ent_ded_nome.get().strip()
        doc = self.ent_ded_doc.get().strip()
        obs = self.ent_ded_obs.get().strip()
        ok, msg = self.gerenciador_dedicados.adicionar_ou_atualizar(nome, doc, obs)
        if not ok:
            return messagebox.showwarning("Aviso", msg)
        self.ent_ded_nome.delete(0, tk.END)
        self.ent_ded_doc.delete(0, tk.END)
        self.ent_ded_obs.delete(0, tk.END)
        self.atualizar_tabela_dedicados()
        self.app_gui.atualizar_labels_dedicados()

    def excluir_dedicado(self):
        sel = self.tree_dedicados.selection()
        if not sel:
            return
        nome = self.tree_dedicados.item(sel[0], "values")[0]
        self.gerenciador_dedicados.remover(nome)
        self.atualizar_tabela_dedicados()
        self.app_gui.atualizar_labels_dedicados()

    def atualizar_tabela_dedicados(self):
        for i in self.tree_dedicados.get_children():
            self.tree_dedicados.delete(i)


class JanelaUnificarTomador(ctk.CTkToplevel):
    def __init__(self, parent, app_gui):
        super().__init__(parent)
        self.app_gui = app_gui
        self.title("📄 Unificador de Guias por Tomador")
        self.geometry("620x460")
        self.configure(fg_color="#DCE1E7")
        definir_icone(self)
        self.after(100, lambda: (self.lift(), self.focus_force()))
        self.construir_interface()

    def construir_interface(self):
        c = ctk.CTkFrame(self, fg_color="#F1F5F9", corner_radius=12)
        c.pack(fill="both", expand=True, padx=20, pady=20)
        ctk.CTkLabel(
            c,
            text="Unificar Documentos por Cliente",
            font=("Segoe UI", 16, "bold"),
            text_color="#D31145",
        ).pack(anchor="w", padx=15, pady=(10, 5))

        tomadores = sorted(
            {
                str(i.get("TOMADOR", "")).strip()
                for i in self.app_gui.app_state.dados_em_memoria
                if str(i.get("TOMADOR", "")).strip()
                not in ("", "Aguardando Conciliação", "Não Conciliado")
            }
        )
        self.combo_tomador = ctk.CTkComboBox(
            c, values=tomadores or ["Nenhum conciliado"], width=520, height=34
        )
        self.combo_tomador.pack(padx=15, pady=8)

        ctk.CTkLabel(c, text="Pasta Origem PDFs:").pack(anchor="w", padx=15)
        self.ent_origem = ctk.CTkEntry(c, width=520)
        self.ent_origem.insert(0, self.app_gui.ultimo_dir_base)
        self.ent_origem.pack(padx=15, pady=4)

        ctk.CTkLabel(c, text="Pasta Destino Unificados:").pack(anchor="w", padx=15)
        self.ent_destino = ctk.CTkEntry(c, width=520)
        self.ent_destino.insert(
            0, os.path.join(self.app_gui.ultimo_dir_base, "UNIFICADOS")
        )
        self.ent_destino.pack(padx=15, pady=4)

        BotaoArredondado3D(
            c,
            text="⚡ EXECUTAR UNIFICAÇÃO",
            width=520,
            height=38,
            command=self.executar,
        ).pack(pady=15)

    def executar(self):
        tomador = self.combo_tomador.get()
        orig = self.ent_origem.get()
        dest = self.ent_destino.get()
        if not tomador or tomador.startswith("Nenhum") or not os.path.exists(orig):
            return messagebox.showwarning("Atenção", "Preencha os campos corretamente.")
        self.destroy()
        threading.Thread(
            target=self._processar_thread, args=(tomador, orig, dest), daemon=True
        ).start()

    def _processar_thread(self, tomador, orig, dest):
        self.app_gui.log(f"[Unificação] Buscando arquivos do cliente '{tomador}'...")
        termos = {
            str(i.get("TERMO"))
            for i in self.app_gui.app_state.dados_em_memoria
            if tomador in str(i.get("TOMADOR"))
        }
        agrupados = {
            t: {"dars": [], "termos": []} for t in termos if t != "Não localizado"
        }

        for root, _, files in os.walk(orig):
            for file in files:
                if file.lower().endswith(".pdf"):
                    path = os.path.join(root, file)
                    with open(path, "rb") as f:
                        b = f.read()
                    txt, _ = extrair_texto_pdf(b)
                    t_enc = extrair_numero_termo_pdf(txt, file)
                    if t_enc in agrupados:
                        if e_dar_documento(txt):
                            agrupados[t_enc]["dars"].append(b)
                        elif e_termo_documento(txt):
                            agrupados[t_enc]["termos"].append(b)

        os.makedirs(dest, exist_ok=True)
        sucessos = 0
        for termo, grupo in agrupados.items():
            if grupo["dars"] and grupo["termos"]:
                merged = mesclar_pdfs([grupo["dars"][0], grupo["termos"][0]])
                with open(os.path.join(dest, f"Guia_Termo_{termo}.pdf"), "wb") as f_out:
                    f_out.write(merged)
                sucessos += 1

        self.app_gui.log(
            f"[Unificação] Concluída. {sucessos} arquivo(s) mesclado(s) salvos em {dest}."
        )
