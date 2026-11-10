import contextlib
import ctypes
import json
import os
import re
import threading
import tkinter as tk
import webbrowser
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
from decimal import Decimal, InvalidOperation
from functools import wraps
from pathlib import Path
from tkinter import filedialog, messagebox, ttk
from typing import Any, cast

import customtkinter as ctk
import requests

from src.services import pdf_service as _pdf_service
from src.services.document_classifier import (
    chave_nfe_valida as chave_nfe_valida,
)
from src.services.document_classifier import (
    e_dar_documento,
    e_nota_fiscal,
    e_termo_documento,
    extrair_chaves_nfe_pdf,
    extrair_vencimento_e_valor_pdf,
    extrair_vencimento_nota,
)
from src.services.document_classifier import (
    extrair_codigo_barras_pdf as extrair_codigo_barras_pdf,
)
from src.services.document_classifier import (
    extrair_numero_termo_pdf as extrair_numero_termo_pdf,
)
from src.services.document_classifier import (
    linha_digitavel_para_codigo_barras as linha_digitavel_para_codigo_barras,
)
from src.services.extraction_service import extrair_documento
from src.services.fraction_service import (
    coordenar_conciliacao_fraction,
)
from src.services.layout_service import (
    GerenciadorLayouts as _GerenciadorLayouts,
)
from src.services.local_report_service import processar_pasta_local_para_relatorio
from src.services.memory_storage_service import (
    carregar_memoria_diaria as _carregar_memoria_diaria,
)
from src.services.memory_storage_service import (
    salvar_checkpoint as _salvar_checkpoint,
)
from src.services.memory_storage_service import (
    salvar_memoria_diaria as _salvar_memoria_diaria,
)
from src.services.pdf_service import (
    extrair_texto_por_caixa as extrair_texto_por_caixa,
)
from src.services.pdf_service import (
    mesclar_pdfs as _mesclar_pdfs,
)
from src.services.report_compilation_service import (
    compilar_relatorio_e_atualizar_dados,
)
from src.services.report_rows_service import (
    cabecalho_relatorio,
    linhas_relatorio_conciliacao,
    linhas_relatorio_final,
)
from src.services.spreadsheet_import_service import (
    carregar_planilha_conferencia,
    mesclar_dados_conferencia,
)
from src.services.spreadsheet_service import (
    HAS_OPENPYXL,
)
from src.services.spreadsheet_service import (
    salvar_planilha_multisheets as _salvar_planilha_multisheets,
)
from src.services.ufs.al import (
    AL_CAMPOS_PLANILHA,
)
from src.services.ufs.al import (
    _extrair_campos_al_pdf as _extrair_campos_al_pdf,
)
from src.services.ufs.ap import (
    extrair_id_controle_ap as extrair_id_controle_ap,
)
from src.services.ufs.ap import (
    extrair_remessas_ap,
    separar_guias_ap,
)
from src.services.ufs.ap_validacao import (
    marcar_status_guia_ap_processada as _marcar_status_guia_ap_processada,
)
from src.services.ufs.ap_validacao import (
    resumo_nfe_map,
    validar_guia_ap,
)
from src.services.ufs.ap_validacao import (
    validar_chaves_ap as validar_chaves_ap,
)
from src.services.zendesk_api_service import ZendeskAPI
from src.services.zendesk_auth_service import limpar_e_formatar_cookie
from src.services.zendesk_pdf_service import (
    analisar_anexo_baixado,
    identificar_uf_ticket,
    processar_e_agregar_ticket_para_planilha,
    processar_e_salvar_anexos_ticket,
)
from src.utils.text_mono import (
    documento_esta_vencido,
    formatar_texto_excel,
    limpar_texto_excel,
    normalizar_valor_monetario,
    separar_valores_monetarios,
)
from src.utils.text_mono import (
    formatar_numero_arquivo_legado as formatar_numero_arquivo,
)
from src.utils.text_mono import (
    padronizar_data_ddmmyyyy_legado as padronizar_data_ddmmyyyy,
)

__all__ = [
    "_extrair_campos_al_pdf",
    "chave_nfe_valida",
    "documento_esta_vencido",
    "e_dar_documento",
    "e_nota_fiscal",
    "e_termo_documento",
    "extrair_chaves_nfe_pdf",
    "extrair_codigo_barras_pdf",
    "extrair_id_controle_ap",
    "extrair_numero_termo_pdf",
    "extrair_remessas_ap",
    "extrair_texto_por_caixa",
    "extrair_vencimento_e_valor_pdf",
    "extrair_vencimento_nota",
    "formatar_numero_arquivo",
    "formatar_texto_excel",
    "limpar_texto_excel",
    "linha_digitavel_para_codigo_barras",
    "padronizar_data_ddmmyyyy",
    "separar_guias_ap",
    "validar_chaves_ap",
]


def log_terminal(marcador: str, mensagem: str) -> None:
    timestamp = datetime.now().strftime("%d/%m/%Y %H:%M:%S")
    print(f"[{timestamp}] [{marcador}] {mensagem}", flush=True)


def timestamp_processamento() -> str:
    return datetime.now().strftime("%d/%m/%Y %H:%M:%S")


def registrar_execucao(nome: str):
    def decorador(funcao):
        @wraps(funcao)
        def wrapper(*args, **kwargs):
            log_terminal("INÍCIO", f"{nome} iniciado.")
            try:
                resultado = funcao(*args, **kwargs)
                log_terminal("SUCESSO", f"{nome} concluído com sucesso.")
                return resultado
            except Exception as erro:
                log_terminal("ERRO", f"{nome} falhou: {erro}")
                raise
            finally:
                log_terminal("CONCLUÍDO", f"Finalizada execução de {nome}.")

        return wrapper

    return decorador


keyring: Any = None
with contextlib.suppress(ImportError):
    import keyring


def obter_credencial(nome: str, padrao: str = "") -> str:
    if keyring is None:
        return padrao
    try:
        return keyring.get_password("ZendeskApp", nome) or padrao
    except Exception:  # noqa: BLE001
        return padrao


def salvar_credencial(nome: str, valor: str) -> None:
    if keyring is None:
        return
    with contextlib.suppress(Exception):
        keyring.set_password("ZendeskApp", nome, valor)
        pass


# ==========================================
# CONFIGURAÇÃO DE DPI, ÍCONE E INTERFACE
# ==========================================
ICONE_APP = "icons8-coordenada-z-48.ico"

if os.name == "nt":
    try:
        myappid = "jadlog.automacao.total.app.1.3"
        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(myappid)
        ctypes.windll.shcore.SetProcessDpiAwareness(2)
    except Exception:  # noqa: BLE001, S110
        pass


def definir_icone(janela):
    if os.path.exists(ICONE_APP):
        try:
            janela.iconbitmap(ICONE_APP)
        except Exception:  # noqa: BLE001, S110
            pass


ctk.set_appearance_mode("Light")
ctk.set_default_color_theme("blue")


# ==========================================
# FUNÇÕES UTILITÁRIAS E EXTRAÇÃO DE PDF
# ==========================================
@registrar_execucao("Mesclagem de PDFs")
def mesclar_pdfs(pdf_bytes_list: list[bytes]) -> bytes:
    return _mesclar_pdfs(pdf_bytes_list)


@registrar_execucao("Extração de texto do PDF")
def extrair_texto_pdf(pdf_bytes: bytes) -> tuple[str, str]:
    if not pdf_bytes:
        return "", "PDF sem texto extraível mesmo com OCR."
    return _pdf_service.extrair_texto_pdf(pdf_bytes)


@registrar_execucao("Gravação da planilha")
def salvar_planilha_multisheets(
    caminho_arquivo: str,
    cabecalho: list,
    linhas_totais: list,
) -> str:
    return _salvar_planilha_multisheets(caminho_arquivo, cabecalho, linhas_totais)


class GerenciadorLayouts(_GerenciadorLayouts):
    @registrar_execucao("Identificação e extração por layout")
    def identificar_e_extrair(
        self, texto_pdf: str, nome_anexo: str, pdf_bytes: bytes | None = None
    ) -> dict | None:
        return super().identificar_e_extrair(texto_pdf, nome_anexo, pdf_bytes)


# ==========================================
# MÓDULO EXTRATOR ISOLADO POR UF
# ==========================================
def extrair_documento_legado(
    uf: str,
    txt_pdf: str,
    nome_anexo: str,
    nfe_map: dict,
    pdf_bytes: bytes | None = None,
) -> tuple[str, list, str, str, str, str, str]:
    return extrair_documento(uf, txt_pdf, nome_anexo, nfe_map, pdf_bytes)


def _extrair_regras_al(
    txt_pdf: str,
    nome_anexo: str,
    nfe_map: dict,
    pdf_bytes: bytes | None = None,
):
    return extrair_documento("AL", txt_pdf, nome_anexo, nfe_map, pdf_bytes)


def _extrair_regras_ap(txt_pdf: str, nome_anexo: str, nfe_map: dict):
    return extrair_documento("AP", txt_pdf, nome_anexo, nfe_map)


def _extrair_regras_ac(txt_pdf: str, nome_anexo: str, nfe_map: dict):
    return extrair_documento("AC", txt_pdf, nome_anexo, nfe_map)


def _extrair_regras_ms(txt_pdf: str, nome_anexo: str, nfe_map: dict):
    from src.services.ufs.ms import _extrair_regras_ms as _ms

    return _ms(txt_pdf, nome_anexo, nfe_map)


def _extrair_regras_am(txt_pdf: str, nome_anexo: str, nfe_map: dict):
    return extrair_documento("AM", txt_pdf, nome_anexo, nfe_map)


def _extrair_regras_geral(txt_pdf: str, nome_anexo: str, nfe_map: dict):
    return extrair_documento("GERAL", txt_pdf, nome_anexo, nfe_map)


# ==========================================
# JANELA UNIFICADA DE CONFIGURAÇÕES (APRENDIZADO DUPLO LADO A LADO)
# ==========================================
class JanelaConfiguracoes(ctk.CTkToplevel):
    def __init__(
        self,
        parent,
        gerenciador_layouts: GerenciadorLayouts,
        app_gui,
    ):
        super().__init__(parent)
        self.gerenciador_layouts = gerenciador_layouts
        self.app_gui = app_gui

        self.title("⚙️ Painel de Aprendizado de Layouts Lado a Lado (Guia DAR + Termo/Nota)")
        self.geometry("1340x880")
        self.minsize(1100, 720)
        self.configure(fg_color="#DCE1E7")
        definir_icone(self)
        self.after(100, self.focar_janela)

        self.texto_pdf1 = ""
        self.pdf1_bytes = None
        self.nome_pdf1 = ""

        self.texto_pdf2 = ""
        self.pdf2_bytes = None
        self.nome_pdf2 = ""

        self.construir_interface()

    def focar_janela(self):
        self.lift()
        self.focus_force()

    def construir_interface(self):
        self.tabview = ctk.CTkTabview(
            self,
            fg_color="#F1F5F9",
            segmented_button_selected_color="#D31145",
            segmented_button_selected_hover_color="#E61A54",
        )
        self.tabview.pack(fill="both", expand=True, padx=15, pady=15)

        self.tab_layouts = self.tabview.add("🎓 Gestor Layouts (Aprendizado Duplo)")

        self._construir_aba_layouts()

    def _construir_aba_layouts(self):
        top_frame = ctk.CTkFrame(self.tab_layouts, fg_color="#E2E8F0")
        top_frame.pack(fill="x", padx=10, pady=8)

        ctk.CTkLabel(
            top_frame,
            text="Carregar Arquivos para Cruzar Layout:",
            font=("Segoe UI", 11, "bold"),
        ).pack(side="left", padx=(10, 5), pady=8)

        ctk.CTkButton(
            top_frame,
            text="📂 Carregar DAR",
            fg_color="#1976D2",
            height=28,
            command=lambda: self.carregar_pdf_exemplo(1),
        ).pack(side="left", padx=4, pady=8)
        ctk.CTkButton(
            top_frame,
            text="📂 Carregar Termo/Nota",
            fg_color="#0284C7",
            height=28,
            command=lambda: self.carregar_pdf_exemplo(2),
        ).pack(side="left", padx=4, pady=8)
        ctk.CTkButton(
            top_frame,
            text="✨ Sugerir Palavras-chave",
            fg_color="#475569",
            height=28,
            command=self.sugerir_palavras_chave,
        ).pack(side="left", padx=4, pady=8)

        ctk.CTkButton(
            top_frame,
            text="📤 Exportar layouts",
            fg_color="#334155",
            width=125,
            height=28,
            command=self.exportar_json,
        ).pack(side="right", padx=10, pady=8)
        ctk.CTkButton(
            top_frame,
            text="📥 Importar layouts",
            fg_color="#334155",
            width=125,
            height=28,
            command=self.importar_json,
        ).pack(side="right", padx=5, pady=8)

        self.ent_busca_layout = ctk.CTkEntry(
            top_frame, placeholder_text="Filtrar layout ou UF", width=180, height=28
        )
        self.ent_busca_layout.pack(side="right", padx=8, pady=8)
        self.ent_busca_layout.bind("<KeyRelease>", lambda event: self.atualizar_tabela_layouts())
        ctk.CTkButton(
            top_frame,
            text="↺ Restaurar padrão",
            fg_color="#64748B",
            width=125,
            height=28,
            command=self.restaurar_layout_padrao,
        ).pack(side="right", padx=4, pady=8)
        ctk.CTkButton(
            top_frame,
            text="🧾 Ver histórico",
            fg_color="#475569",
            width=110,
            height=28,
            command=self.mostrar_historico_layouts,
        ).pack(side="right", padx=4, pady=8)

        center_frame = ctk.CTkFrame(self.tab_layouts, fg_color="transparent")
        center_frame.pack(fill="both", expand=True, padx=5, pady=5)

        left_box = ctk.CTkFrame(center_frame, fg_color="#FFFFFF", width=420)
        left_box.pack(side="left", fill="both", expand=True, padx=(0, 4))

        lbl_pdfs = ctk.CTkLabel(
            left_box,
            text="Inspeção Visual Lado a Lado (Texto Extraído):",
            font=("Segoe UI", 11, "bold"),
            text_color="#0F172A",
        )
        lbl_pdfs.pack(anchor="w", padx=10, pady=5)

        f_split = ctk.CTkFrame(left_box, fg_color="transparent")
        f_split.pack(fill="both", expand=True, padx=5, pady=5)

        f_p1 = ctk.CTkFrame(f_split, fg_color="#F8FAFC")
        f_p1.pack(side="left", fill="both", expand=True, padx=(0, 2))
        self.lbl_nome_p1 = ctk.CTkLabel(
            f_p1,
            text="PDF 1: (Nenhum)",
            font=("Segoe UI", 9, "bold"),
            text_color="#1976D2",
        )
        self.lbl_nome_p1.pack(anchor="w", padx=5, pady=2)
        self.txt_preview1 = ctk.CTkTextbox(
            f_p1, font=("Consolas", 8), fg_color="#FFFFFF", text_color="#000000"
        )
        self.txt_preview1.pack(fill="both", expand=True, padx=4, pady=4)

        f_p2 = ctk.CTkFrame(f_split, fg_color="#F8FAFC")
        f_p2.pack(side="right", fill="both", expand=True, padx=(2, 0))
        self.lbl_nome_p2 = ctk.CTkLabel(
            f_p2,
            text="PDF 2: (Nenhum)",
            font=("Segoe UI", 9, "bold"),
            text_color="#0284C7",
        )
        self.lbl_nome_p2.pack(anchor="w", padx=5, pady=2)
        self.txt_preview2 = ctk.CTkTextbox(
            f_p2, font=("Consolas", 8), fg_color="#FFFFFF", text_color="#000000"
        )
        self.txt_preview2.pack(fill="both", expand=True, padx=4, pady=4)

        mid_box = ctk.CTkScrollableFrame(center_frame, fg_color="#FFFFFF", width=380)
        mid_box.pack(side="left", fill="both", expand=True, padx=4)

        def add_field(label_text, placeholder="", default_val=""):
            ctk.CTkLabel(
                mid_box,
                text=label_text,
                font=("Segoe UI", 10, "bold"),
                text_color="#0F172A",
            ).pack(anchor="w", padx=10, pady=(4, 0))
            entry = ctk.CTkEntry(
                mid_box,
                placeholder_text=placeholder,
                fg_color="#F8FAFC",
                text_color="#000000",
            )
            if default_val:
                entry.insert(0, default_val)
            entry.pack(fill="x", padx=10, pady=2)
            return entry

        self.ent_nome_layout = add_field(
            "Nome do Layout (ex: SEFAZ_ALAGOAS, TERMO_MS):", "Identificador único"
        )
        self.ent_uf = add_field("UF do Estado (ex: AL, AP, AC, MS, GERAL):", "UF", "AL")
        self.ent_palavras_chave = add_field(
            "Palavras-chave (separadas por vírgula):", "Ex: SEFAZ, TERMO, DAEMS, DANFE"
        )

        ctk.CTkFrame(mid_box, height=2, fg_color="#CBD5E1").pack(fill="x", pady=8, padx=10)
        ctk.CTkLabel(
            mid_box,
            text="🧩 Mapeamento dos Campos (Regras Múltiplas):",
            font=("Segoe UI", 11, "bold"),
            text_color="#D31145",
        ).pack(anchor="w", padx=10, pady=2)

        def add_anchor_builder(label, default_regex):
            frame = ctk.CTkFrame(mid_box, fg_color="#F1F5F9", corner_radius=6)
            frame.pack(fill="x", padx=10, pady=4)
            ctk.CTkLabel(frame, text=label, font=("Segoe UI", 9, "bold")).pack(
                anchor="w", padx=6, pady=(2, 0)
            )
            reg_entry = ctk.CTkEntry(frame, height=26, font=("Consolas", 9), fg_color="#FFFFFF")
            reg_entry.insert(0, default_regex)
            reg_entry.pack(fill="x", padx=6, pady=(2, 4))
            return reg_entry

        self.ent_reg_termo = add_anchor_builder(
            "1. Termo/Controle:",
            r"(?:TERMO\s*DE\s*APREENSÃO|AVERIGUAÇÃO|N[º°o\.]*)\s*[-:]?\s*(\d{6,15})",
        )
        self.ent_reg_venc = add_anchor_builder(
            "2. Vencimento / Validade:",
            r"(?:NÃO\s*RECEBER\s*APÓS|Vencimento)[\s\n\r]*[:|]?[\s\n\r]*(\d{2}/\d{2}/\d{4})",
        )
        self.ent_reg_valor = add_anchor_builder(
            "3. Valor Total (R$):",
            r"(?:10\s*-\s*TOTAL|Valor\s+Total)[\s\n\r]*[:|]?[\s\n\r]*(?:R\$\s*)?(\d{1,3}(?:\.\d{3})*,\d{2})",
        )
        self.ent_reg_barras = add_anchor_builder(
            "4. Código de Barras:",
            r"(\b8\d{10}[\s\.-]*\d[\s\.-]*\d{11}[\s\.-]*\d[\s\.-]*\d{11}[\s\.-]*\d[\s\.-]*\d{11}[\s\.-]*\d\b|\b8\d{43,47}\b)",
        )
        self.ent_reg_cte = add_anchor_builder(
            "5. CTE / Remessa:", r"(?:CTE|Conhecimento|Remessa)\s*[:=-]?\s*([\d/]+)"
        )
        self.ent_reg_num_arq = add_anchor_builder(
            "6. Número do Arquivo (N° Nota/DANFE):",
            r"(?:NOTAS\s*FISCAIS|DANFE|NF-E)\s*[:=-]?\s*(\d+)",
        )
        self.ent_reg_chave_arq = add_anchor_builder(
            "7. Chave do Arquivo (44 dígitos / DACTE):",
            r"(?:Chave\s*de\s*Acesso)?\s*(\b\d{44}\b)",
        )

        btn_box = ctk.CTkFrame(mid_box, fg_color="transparent")
        btn_box.pack(fill="x", padx=10, pady=10)

        ctk.CTkButton(
            btn_box,
            text="🧪 Validar layout com os PDFs",
            fg_color="#1976D2",
            command=self.testar_regex,
        ).pack(fill="x", pady=3)
        ctk.CTkButton(
            btn_box,
            text="💾 Salvar configuração do layout",
            fg_color="#D31145",
            command=self.salvar_layout,
        ).pack(fill="x", pady=3)

        right_box = ctk.CTkFrame(center_frame, fg_color="#FFFFFF", width=340)
        right_box.pack(side="right", fill="both", expand=True, padx=(4, 0))

        ctk.CTkLabel(
            right_box,
            text="📊 Resultado Cruzado (Simulação Excel):",
            font=("Segoe UI", 11, "bold"),
            text_color="#1976D2",
        ).pack(anchor="w", padx=10, pady=5)

        self.txt_resultado_lado = ctk.CTkTextbox(
            right_box,
            font=("Consolas", 9),
            fg_color="#F8FAFC",
            text_color="#0F172A",
            height=250,
        )
        self.txt_resultado_lado.pack(fill="x", padx=8, pady=5)
        self.txt_resultado_lado.insert("0.0", "Aguardando carregamento e teste de cruzamento...")

        ctk.CTkFrame(right_box, height=2, fg_color="#CBD5E1").pack(fill="x", pady=5, padx=8)
        ctk.CTkLabel(
            right_box, text="Layouts Salvos no Sistema:", font=("Segoe UI", 11, "bold")
        ).pack(anchor="w", padx=10, pady=2)

        tabla_frame = tk.Frame(right_box, bg="#FFFFFF")
        tabla_frame.pack(fill="both", expand=True, padx=8, pady=5)

        self.tree_layouts = ttk.Treeview(
            tabla_frame, columns=["nome", "uf", "status"], show="headings", height=8
        )
        self.tree_layouts.heading("nome", text="NOME LAYOUT")
        self.tree_layouts.heading("uf", text="UF")
        self.tree_layouts.heading("status", text="STATUS")
        self.tree_layouts.column("nome", width=180, anchor="w")
        self.tree_layouts.column("uf", width=50, anchor="center")
        self.tree_layouts.column("status", width=100, anchor="center")
        self.tree_layouts.pack(side="left", fill="both", expand=True)

        sc_tree = ttk.Scrollbar(tabla_frame, orient="vertical", command=self.tree_layouts.yview)
        self.tree_layouts.configure(yscrollcommand=sc_tree.set)
        sc_tree.pack(side="right", fill="y")

        self.tree_layouts.bind("<<TreeviewSelect>>", self.carregar_layout_selecionado)
        self.tree_layouts.bind("<Double-1>", lambda event: self.testar_regex())
        ctk.CTkButton(
            right_box,
            text="📄 Duplicar layout selecionado",
            fg_color="#1976D2",
            command=self.duplicar_layout,
        ).pack(fill="x", padx=8, pady=(0, 5))
        ctk.CTkButton(
            right_box,
            text="🗑️ Excluir layout selecionado",
            fg_color="#B71C1C",
            command=self.excluir_layout,
        ).pack(fill="x", padx=8, pady=8)

        self.atualizar_tabela_layouts()

    def carregar_pdf_exemplo(self, num_pdf: int):
        arq = filedialog.askopenfilename(
            title=f"Selecione o PDF {num_pdf}", filetypes=[("PDF", "*.pdf")]
        )
        if arq:
            try:
                nome = os.path.basename(arq)
                with open(arq, "rb") as f:
                    b_bytes = f.read()
                    txt, status = extrair_texto_pdf(b_bytes)

                if num_pdf == 1:
                    self.nome_pdf1 = nome
                    self.pdf1_bytes = b_bytes
                    self.texto_pdf1 = txt
                    self.lbl_nome_p1.configure(text=f"PDF 1: {nome}")
                    self.txt_preview1.delete("0.0", tk.END)
                    self.txt_preview1.insert(tk.END, self.texto_pdf1 or f"[{status}]")
                else:
                    self.nome_pdf2 = nome
                    self.pdf2_bytes = b_bytes
                    self.texto_pdf2 = txt
                    self.lbl_nome_p2.configure(text=f"PDF 2: {nome}")
                    self.txt_preview2.delete("0.0", tk.END)
                    self.txt_preview2.insert(tk.END, self.texto_pdf2 or f"[{status}]")

                self.testar_regex()
            except Exception as e:
                messagebox.showerror("Erro", f"Falha ao ler PDF #{num_pdf}: {e}")

    def sugerir_palavras_chave(self):
        txt_alvo = self.texto_pdf1 or self.texto_pdf2
        if not txt_alvo:
            return messagebox.showwarning("Atenção", "Carregue ao menos um PDF de exemplo!")
        primeiras_linhas = txt_alvo[:600].upper()
        palavras = re.findall(r"\b[A-ZÁÉÍÓÚÂÊÔÃÕÇ]{4,}\b", primeiras_linhas)
        ignoradas = {
            "DOCUMENTO",
            "ARRECADAÇÃO",
            "ESTADO",
            "RECEITA",
            "FISCAL",
            "NÚMERO",
            "VALOR",
            "DATA",
            "PAGAMENTO",
        }
        sugeridas = [p for p in dict.fromkeys(palavras) if p not in ignoradas][:4]
        if sugeridas:
            self.ent_palavras_chave.delete(0, tk.END)
            self.ent_palavras_chave.insert(0, ", ".join(sugeridas))
            messagebox.showinfo("Sugestão", f"Palavras-chave detectadas:\n{', '.join(sugeridas)}")

    def testar_regex(self):
        txt_comb = (self.texto_pdf1 + "\n" + self.texto_pdf2).strip()
        if not txt_comb:
            self.txt_resultado_lado.delete("0.0", tk.END)
            self.txt_resultado_lado.insert(
                "0.0",
                "Carregue PDF 1 (Guia) e/ou PDF 2 (Termo/Nota) para iniciar a verificação.",
            )
            return

        def buscar_em(txt_alvo, pattern):
            if not pattern or not txt_alvo:
                return "Não configurado"
            try:
                m = re.search(pattern, txt_alvo, re.IGNORECASE)
                if m:
                    return m.group(1 if m.groups() else 0).strip()
                return "❌ Não Encontrado"
            except re.error as err:
                return f"⚠️ Regex Inválida: {err}"

        termo_p1 = buscar_em(self.texto_pdf1, self.ent_reg_termo.get().strip())
        termo_p2 = buscar_em(self.texto_pdf2, self.ent_reg_termo.get().strip())
        termo_final = termo_p1 if termo_p1 != "❌ Não Encontrado" else termo_p2

        venc_p1 = padronizar_data_ddmmyyyy(
            buscar_em(self.texto_pdf1, self.ent_reg_venc.get().strip())
        )
        valor_p1 = buscar_em(self.texto_pdf1, self.ent_reg_valor.get().strip())
        barras_p1 = buscar_em(self.texto_pdf1, self.ent_reg_barras.get().strip())

        cte_p1 = buscar_em(self.texto_pdf1, self.ent_reg_cte.get().strip())
        cte_p2 = buscar_em(self.texto_pdf2, self.ent_reg_cte.get().strip())
        cte_final = cte_p1 if cte_p1 != "❌ Não Encontrado" else cte_p2

        num_arq_p1 = buscar_em(self.texto_pdf1, self.ent_reg_num_arq.get().strip())
        num_arq_p2 = buscar_em(self.texto_pdf2, self.ent_reg_num_arq.get().strip())
        num_arq_final = formatar_numero_arquivo(
            num_arq_p1 if num_arq_p1 != "❌ Não Encontrado" else num_arq_p2
        )

        chaves_p1 = re.findall(r"\b(\d{44})\b", self.texto_pdf1)
        chaves_p2 = re.findall(r"\b(\d{44})\b", self.texto_pdf2)
        chaves_todas = list(dict.fromkeys(chaves_p1 + chaves_p2))

        chaves_55, dactes_57 = [], []
        for ch in chaves_todas:
            if ch != re.sub(r"\D", "", barras_p1):
                if ch[20:22] == "57":
                    dactes_57.append(ch)
                else:
                    chaves_55.append(ch)

        chave_fmt = " ".join(chaves_55) if chaves_55 else "Sem Arquivo Válido"
        dacte_fmt = " ".join(dactes_57) if dactes_57 else "Sem DACTE"

        msg_lado = (
            f"=== RESULTADO COMBINADO NO EXCEL ===\n"
            f"• TERMO/CONTROLE : {termo_final}\n"
            f"• VENCIMENTO     : {venc_p1}\n"
            f"• VALOR (R$)     : {valor_p1}\n"
            f"• BARRAS (44)    : {barras_p1}\n"
            f"• CTE / REMESSA  : {cte_final}\n"
            f"• NÚMERO ARQUIVO : {num_arq_final}\n"
            f"• CHAVE ARQUIVO  : {chave_fmt}\n"
            f"• DACTE (57)     : {dacte_fmt}\n"
            f"------------------------------------\n"
            f"Status Cruzamento: {'✅ PERFEITO' if (termo_final != '❌ Não Encontrado' and barras_p1 != '❌ Não Encontrado') else '⚠️ INCOMPLETO'}"
        )
        self.txt_resultado_lado.delete("0.0", tk.END)
        self.txt_resultado_lado.insert(tk.END, msg_lado)

    def salvar_layout(self):
        nome = self.ent_nome_layout.get().strip().upper()
        if not nome:
            return messagebox.showwarning("Campo Requerido", "Informe um Nome para o Layout!")

        kw_list = [k.strip() for k in self.ent_palavras_chave.get().split(",") if k.strip()]
        config = {
            "uf": self.ent_uf.get().strip().upper(),
            "palavras_chave": kw_list,
            "regex_termo": self.ent_reg_termo.get().strip(),
            "regex_vencimento": self.ent_reg_venc.get().strip(),
            "regex_valor": self.ent_reg_valor.get().strip(),
            "regex_cod_barras": self.ent_reg_barras.get().strip(),
            "regex_cte": self.ent_reg_cte.get().strip(),
            "regex_num_arquivo": self.ent_reg_num_arq.get().strip(),
            "regex_chave_arquivo": self.ent_reg_chave_arq.get().strip(),
        }
        erros = self.gerenciador_layouts.validar_layout(nome, config)
        if erros:
            return messagebox.showerror(
                "Layout inválido", "Corrija os campos:\n\n" + "\n".join(erros)
            )
        acao = "EDIÇÃO" if nome in self.gerenciador_layouts.layouts else "CADASTRO"
        self.gerenciador_layouts.layouts[nome] = config
        self.gerenciador_layouts.registrar_historico(acao, nome)
        self.gerenciador_layouts.salvar_layouts()
        self.atualizar_tabela_layouts()
        messagebox.showinfo("Sucesso", f"Layout '{nome}' salvo com sucesso!")

    def atualizar_tabela_layouts(self):
        filtro = (
            self.ent_busca_layout.get().strip().upper() if hasattr(self, "ent_busca_layout") else ""
        )
        for item in self.tree_layouts.get_children():
            self.tree_layouts.delete(item)
        for nome, cfg in self.gerenciador_layouts.layouts.items():
            if filtro and filtro not in f"{nome} {cfg.get('uf', 'GERAL')}".upper():
                continue
            status = "OK" if not self.gerenciador_layouts.validar_layout(nome, cfg) else "INVÁLIDO"
            self.tree_layouts.insert("", tk.END, values=(nome, cfg.get("uf", "GERAL"), status))

    def carregar_layout_selecionado(self, event):
        item = self.tree_layouts.selection()
        if not item:
            return
        nome_layout = self.tree_layouts.item(item[0], "values")[0]
        cfg = self.gerenciador_layouts.layouts.get(nome_layout)
        if cfg:
            self.ent_nome_layout.delete(0, tk.END)
            self.ent_nome_layout.insert(0, nome_layout)
            self.ent_uf.delete(0, tk.END)
            self.ent_uf.insert(0, cfg.get("uf", ""))
            self.ent_palavras_chave.delete(0, tk.END)
            self.ent_palavras_chave.insert(0, ", ".join(cfg.get("palavras_chave", [])))
            for ent, k in [
                (self.ent_reg_termo, "regex_termo"),
                (self.ent_reg_venc, "regex_vencimento"),
                (self.ent_reg_valor, "regex_valor"),
                (self.ent_reg_barras, "regex_cod_barras"),
                (self.ent_reg_cte, "regex_cte"),
                (self.ent_reg_num_arq, "regex_num_arquivo"),
                (self.ent_reg_chave_arq, "regex_chave_arquivo"),
            ]:
                ent.delete(0, tk.END)
                ent.insert(0, cfg.get(k, ""))
            self.testar_regex()

    def excluir_layout(self):
        item = self.tree_layouts.selection()
        if not item:
            return
        nome = self.tree_layouts.item(item[0], "values")[0]
        if messagebox.askyesno("Excluir", f"Excluir layout '{nome}'?"):
            self.gerenciador_layouts.layouts.pop(nome, None)
            self.gerenciador_layouts.registrar_historico("EXCLUSÃO", nome)
            self.gerenciador_layouts.salvar_layouts()
            self.atualizar_tabela_layouts()

    def duplicar_layout(self):
        item = self.tree_layouts.selection()
        if not item:
            return messagebox.showwarning("Duplicar", "Selecione um layout.")
        nome = self.tree_layouts.item(item[0], "values")[0]
        novo = f"{nome}_COPIA"
        indice = 2
        while novo in self.gerenciador_layouts.layouts:
            novo = f"{nome}_COPIA_{indice}"
            indice += 1
        self.gerenciador_layouts.layouts[novo] = json.loads(
            json.dumps(self.gerenciador_layouts.layouts[nome])
        )
        self.gerenciador_layouts.registrar_historico("DUPLICAÇÃO", novo)
        self.gerenciador_layouts.salvar_layouts()
        self.atualizar_tabela_layouts()

    def restaurar_layout_padrao(self):
        item = self.tree_layouts.selection()
        if not item:
            return messagebox.showwarning("Padrões", "Selecione um layout padrão.")
        nome = self.tree_layouts.item(item[0], "values")[0]
        if self.gerenciador_layouts.restaurar_padrao(nome):
            self.carregar_layout_selecionado(None)
            self.atualizar_tabela_layouts()
            messagebox.showinfo("Padrões", f"Layout '{nome}' restaurado.")
        else:
            messagebox.showwarning("Padrões", "Esse layout não possui uma versão padrão.")

    def mostrar_historico_layouts(self):
        texto = (
            "\n".join(
                f"{x.get('data')} | {x.get('acao')} | {x.get('layout')}"
                for x in self.gerenciador_layouts.historico[-50:]
            )
            or "Nenhuma alteração registrada."
        )
        messagebox.showinfo("Histórico de layouts", texto)

    def exportar_json(self):
        arq = filedialog.asksaveasfilename(
            title="Exportar Base Layouts",
            initialfile="layouts_custom.json",
            defaultextension=".json",
            filetypes=[("JSON", "*.json")],
        )
        if arq:
            dados = dict(self.gerenciador_layouts.layouts)
            dados["_historico"] = self.gerenciador_layouts.historico
            with open(arq, "w", encoding="utf-8") as f:
                json.dump(dados, f, ensure_ascii=False, indent=4)

    def importar_json(self):
        arq = filedialog.askopenfilename(
            title="Importar Base Layouts", filetypes=[("JSON", "*.json")]
        )
        if arq:
            with open(arq, "r", encoding="utf-8") as f:
                dados = json.load(f)
                historico = dados.pop("_historico", []) if isinstance(dados, dict) else []
                invalidos = []
                for nome, config in dados.items():
                    if not isinstance(config, dict):
                        invalidos.append(f"{nome}: configuração inválida")
                    else:
                        invalidos.extend(
                            f"{nome}: {erro}"
                            for erro in self.gerenciador_layouts.validar_layout(nome, config)
                        )
                if invalidos:
                    return messagebox.showerror("Importação inválida", "\n".join(invalidos[:20]))
                self.gerenciador_layouts.historico.extend(historico)
                self.gerenciador_layouts.layouts.update(dados)
                self.gerenciador_layouts.registrar_historico("IMPORTAÇÃO", os.path.basename(arq))
                self.gerenciador_layouts.salvar_layouts()
                self.atualizar_tabela_layouts()


# ==========================================
# WIDGET CUSTOMIZADO: BOTÃO 3D MODERNO
# ==========================================
class BotaoArredondado3D(tk.Canvas):
    def __init__(
        self,
        master,
        text,
        command=None,
        width=190,
        height=36,
        depth=6,
        cor_base="#D31145",
        cor_hover="#E61A54",
        cor_sombra="#8E0B2E",
        cor_texto="white",
        font=("Segoe UI", 9, "bold"),
        bg_app="#FFFFFF",
        **kwargs,
    ):
        super().__init__(
            master,
            width=width,
            height=height + depth,
            bg=bg_app,
            highlightthickness=0,
            **kwargs,
        )
        self.command = command
        self.pressed = False
        self.enabled = True
        self.depth = depth
        self.cor_base = cor_base
        self.cor_hover = cor_hover
        self.cor_sombra = cor_sombra

        self.sombra_ids = self._draw_capsule(0, depth, width, height, self.cor_sombra)
        self.topo_ids = self._draw_capsule(0, 0, width, height, self.cor_base)
        self.texto_id = self.create_text(
            width // 2, height // 2, text=text, fill=cor_texto, font=font
        )

        self.bind("<ButtonPress-1>", self.on_press)
        self.bind("<ButtonRelease-1>", self.on_release)
        self.bind("<Enter>", self.on_enter)
        self.bind("<Leave>", self.on_leave)

    def _draw_capsule(self, x, y, w, h, color):
        r = h / 2
        o1 = self.create_oval(x, y, x + 2 * r, y + h, fill=color, outline=color, width=1)
        o2 = self.create_oval(x + w - 2 * r, y, x + w, y + h, fill=color, outline=color, width=1)
        rct = self.create_rectangle(
            x + r - 1, y, x + w - r + 1, y + h, fill=color, outline=color, width=1
        )
        return [o1, o2, rct]

    def config_state(self, state, text=None):
        if state == tk.DISABLED:
            self.enabled = False
            for item in self.topo_ids:
                self.itemconfig(item, fill="#A0AEC0", outline="#A0AEC0")
            for item in self.sombra_ids:
                self.itemconfig(item, fill="#718096", outline="#718096")
        else:
            self.enabled = True
            for item in self.topo_ids:
                self.itemconfig(item, fill=self.cor_base, outline=self.cor_base)
            for item in self.sombra_ids:
                self.itemconfig(item, fill=self.cor_sombra, outline=self.cor_sombra)
        if text:
            self.itemconfig(self.texto_id, text=text)

    def on_enter(self, event):
        if self.enabled:
            self.config(cursor="hand2")
            for item in self.topo_ids:
                self.itemconfig(item, fill=self.cor_hover, outline=self.cor_hover)

    def on_leave(self, event):
        self.config(cursor="")
        if self.enabled:
            for item in self.topo_ids:
                self.itemconfig(item, fill=self.cor_base, outline=self.cor_base)
        if self.pressed and self.enabled:
            for item in self.topo_ids:
                self.move(item, 0, -self.depth)
            self.move(self.texto_id, 0, -self.depth)
            self.pressed = False

    def on_press(self, event):
        if self.enabled:
            for item in self.topo_ids:
                self.move(item, 0, self.depth)
            self.move(self.texto_id, 0, self.depth)
            self.pressed = True

    def on_release(self, event):
        if self.pressed and self.enabled:
            for item in self.topo_ids:
                self.move(item, 0, -self.depth)
            self.move(self.texto_id, 0, -self.depth)
            self.pressed = False
            if self.command:
                self.after(50, self.command)


# ==========================================
# INTERFACE GRÁFICA PRINCIPAL
# ==========================================
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
    BTN_CINZA_ESCURO = ("#475569", "#64748B", "#1E293B")

    def __init__(self):
        self.api: ZendeskAPI | None = None
        self.cookie_jadlog = ""
        self.cancelar_operacao = False
        self.janela_config = None
        self.janela_sobre = None

        self.lock = threading.Lock()
        self.dados_em_memoria = []
        self._divergencias_fraction_por_iid: dict[str, list[dict[str, str]]] = {}
        base_dir = os.path.dirname(os.path.abspath(__file__)) or os.getcwd()
        self.arquivo_memoria = os.path.join(base_dir, "memoria_diaria_jadlog.json")
        self.memoria_termos = {}
        self.tickets_processados = {}
        self.ctes_consultados_cache = {}
        self.gerenciador_layouts = GerenciadorLayouts()

        pasta_docs = os.path.join(os.path.expanduser("~"), "Documents")
        if not os.path.exists(pasta_docs):
            pasta_docs = os.getcwd()
        self.ultimo_dir_base = pasta_docs

        self.carregar_memoria_diaria()
        self.construir_tela_login()

    def _api_pronto(self) -> ZendeskAPI:
        if self.api is None:
            raise RuntimeError("A API do Zendesk ainda não foi autenticada")
        return self.api

    def copiar_para_clipboard(self, texto: str):
        def _task():
            try:
                self.janela.clipboard_clear()
                self.janela.clipboard_append(texto)
            except Exception as e:
                print(f"[Erro Clipboard] {e}")

        if hasattr(self, "janela") and self.janela:
            self.janela.after(0, _task)

    def obter_do_clipboard(self) -> str:
        try:
            return self.janela.clipboard_get()
        except Exception:
            return ""

    def exibir_mensagem(self, tipo: str, titulo: str, mensagem: str):
        def _task():
            if tipo == "info":
                messagebox.showinfo(titulo, mensagem)
            elif tipo == "warning":
                messagebox.showwarning(titulo, mensagem)
            elif tipo == "error":
                messagebox.showerror(titulo, mensagem)

        if hasattr(self, "janela") and self.janela:
            self.janela.after(0, _task)
        elif hasattr(self, "tela_login") and self.tela_login:
            self.tela_login.after(0, _task)

    def criar_estilo_tabelas(self):
        style = ttk.Style()
        style.theme_use("clam")
        style.configure(
            "Treeview",
            background="#FFFFFF",
            foreground=self.COR_TEXTO,
            rowheight=30,
            fieldbackground="#FFFFFF",
            borderwidth=0,
            font=("Segoe UI", 9),
        )
        style.map(
            "Treeview",
            background=[("selected", self.BTN_ALTA[0])],
            foreground=[("selected", "white")],
        )
        style.configure(
            "Treeview.Heading",
            background="#CBD5E1",
            foreground=self.COR_TEXTO,
            font=("Segoe UI", 9, "bold"),
            borderwidth=0,
            padding=5,
        )
        style.map("Treeview.Heading", background=[("active", "#94A3B8")])

    def carregar_memoria_diaria(self):
        dados = _carregar_memoria_diaria(self.arquivo_memoria)
        if isinstance(dados, list):
            self.dados_em_memoria = dados
            return
        if isinstance(dados, dict):
            self.dados_em_memoria = dados.get("dados_em_memoria", [])
            self.memoria_termos = dados.get("memoria_termos", {})
            self.tickets_processados = dados.get("tickets_processados", {})
            self.ctes_consultados_cache = dados.get("ctes_consultados_cache", {})
            return
        self.dados_em_memoria = []

    def salvar_memoria_diaria(self):
        with self.lock:
            _salvar_memoria_diaria(
                self.arquivo_memoria,
                self.dados_em_memoria,
                self.memoria_termos,
                self.tickets_processados,
                self.ctes_consultados_cache,
            )

    def salvar_checkpoint(self, motivo: str = "lote") -> None:
        pasta_checkpoint = Path(__file__).resolve().parent / "checkpoints"
        with self.lock:
            _salvar_checkpoint(
                pasta_checkpoint,
                motivo,
                self.dados_em_memoria,
                self.memoria_termos,
                self.tickets_processados,
                self.ctes_consultados_cache,
            )

    def construir_tela_login(self):
        self.tela_login = ctk.CTk()
        self.tela_login.title("Autenticação - Automação Total")
        self.tela_login.geometry("520x560")
        self.tela_login.configure(fg_color=self.COR_FUNDO)
        definir_icone(self.tela_login)
        self.tela_login.eval("tk::PlaceWindow . center")

        frame = ctk.CTkFrame(self.tela_login, fg_color=self.COR_CARD, corner_radius=15)
        frame.pack(pady=25, padx=40, fill="both", expand=True)

        ctk.CTkLabel(
            frame,
            text="Automação Total JadLog",
            font=ctk.CTkFont("Segoe UI", 22, "bold"),
            text_color=self.BTN_ALTA[0],
        ).pack(pady=(15, 10))

        saved_subdomain = "jadloglogsticahelp"
        saved_cookie = ""
        saved_jadlog = ""
        saved_subdomain = obter_credencial("subdomain", saved_subdomain)
        saved_cookie = obter_credencial("zendesk_cookie")
        saved_jadlog = obter_credencial("jadlog_cookie")

        ctk.CTkLabel(
            frame,
            text="🔴 AUTENTICAÇÃO ZENDESK",
            font=("Segoe UI", 11, "bold"),
            text_color=self.BTN_ALTA[0],
        ).pack(anchor="w", padx=20, pady=(10, 2))

        self.entry_subdomain = ctk.CTkEntry(
            frame,
            placeholder_text="Subdomínio Zendesk (ex: jadloglogsticahelp)",
            width=360,
            height=38,
            font=("Segoe UI", 12),
            fg_color="#FFFFFF",
            border_color="#64748B",
            border_width=2,
            text_color="#000000",
        )
        self.entry_subdomain.insert(0, saved_subdomain)
        self.entry_subdomain.pack(pady=(0, 6))

        self.entry_cookie = ctk.CTkEntry(
            frame,
            placeholder_text="Cookie Zendesk (Obrigatório - Copiar do DevTools)",
            width=360,
            height=38,
            show="*",
            font=("Segoe UI", 12),
            fg_color="#FFFFFF",
            border_color="#64748B",
            border_width=2,
            text_color="#000000",
        )
        self.entry_cookie.insert(0, saved_cookie)
        self.entry_cookie.pack(pady=(0, 12))

        ctk.CTkLabel(
            frame,
            text="🔵 AUTENTICAÇÃO FRACTION / JADLOG",
            font=("Segoe UI", 11, "bold"),
            text_color="#1976D2",
        ).pack(anchor="w", padx=20, pady=(5, 2))

        self.entry_cookie_jadlog = ctk.CTkEntry(
            frame,
            placeholder_text="Cookie Fraction/Jadlog (Opcional - Lê CTE Automático)",
            width=360,
            height=38,
            show="*",
            font=("Segoe UI", 12),
            fg_color="#FFFFFF",
            border_color="#1976D2",
            border_width=2,
            text_color="#000000",
        )
        self.entry_cookie_jadlog.insert(0, saved_jadlog)
        self.entry_cookie_jadlog.pack(pady=(0, 15))

        self.btn_login = BotaoArredondado3D(
            frame,
            text="ACESSAR SISTEMA",
            cor_base=self.BTN_ALTA[0],
            cor_hover=self.BTN_ALTA[1],
            cor_sombra=self.BTN_ALTA[2],
            width=360,
            height=42,
            depth=6,
            bg_app=self.COR_CARD,
            command=self.validar_login,
        )
        self.btn_login.pack(pady=(5, 15))

        self.tela_login.mainloop()

    def validar_login(self):
        subdomain = self.entry_subdomain.get().strip()
        cookie = self.entry_cookie.get().strip()
        self.cookie_jadlog = self.entry_cookie_jadlog.get().strip()

        if not subdomain or not cookie:
            messagebox.showwarning(
                "Campos Requeridos", "Preencha o subdomínio e o Cookie do Zendesk."
            )
            return

        self.btn_login.config_state(tk.DISABLED, text="VALIDANDO...")
        self.tela_login.update()

        api_temp = ZendeskAPI(subdomain, cookie)
        sucesso, msg = api_temp.validar_autenticacao()

        if sucesso:
            salvar_credencial("subdomain", subdomain)
            salvar_credencial("zendesk_cookie", cookie)
            salvar_credencial("jadlog_cookie", self.cookie_jadlog)

            self.api = api_temp
            self.tela_login.withdraw()
            self.construir_painel_principal(msg)
        else:
            messagebox.showerror("Acesso Negado", f"Falha na autenticação:\n{msg}")
            self.btn_login.config_state(tk.NORMAL, text="ACESSAR SISTEMA")

    def construir_painel_principal(self, nome_agente):
        self.janela = ctk.CTk()
        self.janela.title(f"Painel de Automação Jadlog - Operador: {nome_agente}")
        self.janela.geometry("1350x850")
        self.janela.minsize(1050, 650)
        self.janela.configure(fg_color=self.COR_FUNDO)
        definir_icone(self.janela)
        self.criar_estilo_tabelas()

        self.janela.protocol(
            "WM_DELETE_WINDOW",
            lambda: (self.tela_login.destroy(), self.janela.destroy()),
        )

        sidebar = ctk.CTkScrollableFrame(
            self.janela,
            width=240,
            corner_radius=0,
            fg_color=self.COR_CARD,
            scrollbar_button_color="#94A3B8",
            scrollbar_button_hover_color="#64748B",
        )
        sidebar.pack(side="left", fill="y", expand=False)

        ctk.CTkFrame(sidebar, height=10, fg_color="transparent").pack(pady=(0, 5))
        ctk.CTkLabel(
            sidebar,
            text="Painel de Ações",
            font=ctk.CTkFont(size=16, weight="bold"),
            text_color=self.BTN_ALTA[0],
        ).pack(anchor="center", pady=(5, 10))

        def add_btn(text, paleta, acao, altura=38):
            btn = BotaoArredondado3D(
                sidebar,
                text=text,
                cor_base=paleta[0],
                cor_hover=paleta[1],
                cor_sombra=paleta[2],
                width=200,
                height=altura,
                depth=6,
                bg_app=self.COR_CARD,
                command=lambda: self.iniciar_thread(acao),
            )
            btn.pack(pady=6, anchor="center")

        add_btn("📥 Baixar anexos", self.BTN_NEUTRO, "anexos")
        add_btn("📊 Relat. Zendesk", self.BTN_ALTA, "planilha")
        add_btn("📁 Relat. pasta local", self.BTN_NEUTRO, "planilha_pasta")
        add_btn("📄 Carregar Excel/CSV", self.BTN_NEUTRO, "planilha_carregar")
        add_btn("⚙️ Configurações", self.BTN_AZUL, "abrir_configuracoes")

        ctk.CTkFrame(sidebar, height=2, fg_color="#CBD5E1").pack(fill="x", pady=6, padx=15)

        ctk.CTkFrame(sidebar, height=2, fg_color="#CBD5E1").pack(fill="x", pady=6, padx=15)

        self.entry_cookie_jadlog_main = ctk.CTkEntry(
            sidebar,
            placeholder_text="Cole o Cookie Fraction...",
            show="*",
            width=200,
            height=32,
            font=("Segoe UI", 12),
            fg_color="#FFFFFF",
            border_color="#1976D2",
            border_width=2,
            text_color="#000000",
        )
        self.entry_cookie_jadlog_main.pack(pady=(2, 4), anchor="center")
        if self.cookie_jadlog:
            self.entry_cookie_jadlog_main.insert(0, self.cookie_jadlog)

        def _acao_atualizar_cookie():
            novo = self.entry_cookie_jadlog_main.get().strip()
            if novo:
                cookie_tratado = limpar_e_formatar_cookie(novo)
                self.cookie_jadlog = cookie_tratado
                salvar_credencial("jadlog_cookie", cookie_tratado)
                self.log("[✓] Sessão Jadlog salva! Validando conexão com o Fraction...")

                def _validar_conexao():
                    try:
                        s_test = requests.Session()
                        s_test.headers.update(
                            {
                                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
                                "Cookie": cookie_tratado,
                            }
                        )
                        r_test = s_test.get(
                            "https://jadlog.com.br/FractionWeb/jad/pesquisar",
                            timeout=10,
                        )
                        if (
                            "login" in r_test.url.lower()
                            or "j_spring_security_check" in r_test.text
                        ):
                            self.log(
                                "[⚠️ AVISO] O Cookie inserido está EXPIRADO ou INVÁLIDO no Fraction (redirecionou para login). Dê F5 no navegador na tela do Fraction, copie o Cookie atualizado no F12 e cole aqui."
                            )
                        else:
                            self.log(
                                "[✅ SUCESSO] Cookie Fraction AUTENTICADO com sucesso no portal Jadlog!"
                            )
                    except Exception as err_test:
                        self.log(f"[i] Teste de resposta Fraction: {err_test}")

                threading.Thread(target=_validar_conexao, daemon=True).start()
            else:
                self.log("[!] Cole o código/cookie primeiro.")

        btn_att_cookie = BotaoArredondado3D(
            sidebar,
            text="Atualizar Fraction",
            cor_base=self.BTN_MEDIA[0],
            cor_hover=self.BTN_MEDIA[1],
            cor_sombra=self.BTN_MEDIA[2],
            width=200,
            height=36,
            depth=6,
            bg_app=self.COR_CARD,
            command=_acao_atualizar_cookie,
        )
        btn_att_cookie.pack(pady=2, anchor="center")

        ctk.CTkFrame(sidebar, height=2, fg_color="#CBD5E1").pack(fill="x", pady=6, padx=15)

        add_btn("🔎 Buscar tomadores", self.BTN_AZUL, "conciliar_tomador")
        add_btn("🔄 Atualizar tabela", self.BTN_NEUTRO, "atualizar_tabela")

        ctk.CTkFrame(sidebar, height=2, fg_color="#CBD5E1").pack(fill="x", pady=12, padx=15)

        add_btn("💾 Relatório final", self.BTN_BAIXA, "salvar_final")

        ctk.CTkFrame(sidebar, height=2, fg_color="#CBD5E1").pack(fill="x", pady=12, padx=15)
        add_btn("⏹ Cancelar operação", self.BTN_CANC, "solicitar_cancelamento")
        ctk.CTkFrame(sidebar, height=2, fg_color="#CBD5E1").pack(fill="x", pady=12, padx=15)

        def add_btn_claro(text, acao):
            btn = BotaoArredondado3D(
                sidebar,
                text=text,
                cor_base=self.BTN_LIGHT[0],
                cor_hover=self.BTN_LIGHT[1],
                cor_sombra=self.BTN_LIGHT[2],
                cor_texto=self.COR_TEXTO,
                width=200,
                height=32,
                depth=4,
                bg_app=self.COR_CARD,
                command=lambda: self.iniciar_thread(acao),
            )
            btn.pack(pady=4, anchor="center")

        add_btn_claro("🕘 Histórico tickets", "visualizar_app")
        add_btn_claro("🌐 Abrir navegador", "abrir")
        add_btn_claro("🧹 Limpar cache tomador", "limpar_cache_tomadores")
        add_btn_claro("ℹ️ Sobre", "abrir_sobre")

        ctk.CTkFrame(sidebar, height=20, fg_color="transparent").pack(pady=(5, 10))

        main_content = ctk.CTkFrame(self.janela, fg_color="transparent")
        main_content.pack(side="right", fill="both", expand=True, padx=25, pady=20)

        ctk.CTkLabel(
            main_content,
            text="Central de Processamento em Lote",
            font=ctk.CTkFont(size=22, weight="bold"),
            text_color=self.BTN_ALTA[0],
        ).pack(anchor="w", pady=(0, 10))

        # ==========================================
        # 1ª MELHORIA: CARDS / DASHBOARD DE MÉTRICAS
        # ==========================================
        cards_frame = ctk.CTkFrame(main_content, fg_color="transparent")
        cards_frame.pack(fill="x", pady=(0, 10))

        def criar_card(parent, titulo, valor_inicial, cor_borda):
            card = ctk.CTkFrame(
                parent,
                fg_color=self.COR_CARD,
                corner_radius=10,
                border_width=2,
                border_color=cor_borda,
            )
            card.pack(side="left", fill="both", expand=True, padx=4)
            ctk.CTkLabel(
                card,
                text=titulo,
                font=ctk.CTkFont("Segoe UI", 10, "bold"),
                text_color=self.COR_TEXTO,
            ).pack(anchor="w", padx=10, pady=(6, 0))
            lbl_val = ctk.CTkLabel(
                card,
                text=valor_inicial,
                font=ctk.CTkFont("Segoe UI", 14, "bold"),
                text_color=cor_borda,
            )
            lbl_val.pack(anchor="w", padx=10, pady=(0, 6))
            return lbl_val

        self.lbl_card_ok = criar_card(cards_frame, "🟢 GUIAS OK", "0", "#2E7D32")
        self.lbl_card_vencidas = criar_card(cards_frame, "🟧 VENCIDAS", "0", "#D97706")
        self.lbl_card_quarentena = criar_card(cards_frame, "🔴 QUARENTENA", "0", "#D31145")
        self.lbl_card_valor = criar_card(cards_frame, "💰 VALOR TOTAL", "R$ 0,00", "#1976D2")

        input_frame = ctk.CTkFrame(
            main_content,
            fg_color=self.COR_CARD,
            corner_radius=10,
            border_width=1,
            border_color="#CBD5E1",
        )
        input_frame.pack(fill="x", pady=(0, 10))
        ctk.CTkLabel(
            input_frame,
            text="IDs dos Tickets (1 por linha):",
            font=ctk.CTkFont(weight="bold"),
            text_color=self.COR_TEXTO,
        ).pack(anchor="w", padx=15, pady=(8, 0))
        self.entry_tickets = ctk.CTkTextbox(
            input_frame,
            font=("Consolas", 13),
            height=75,
            fg_color="#FFFFFF",
            text_color="#000000",
            border_color="#64748B",
            border_width=2,
        )
        self.entry_tickets.pack(fill="both", expand=True, padx=15, pady=(5, 10))

        bottom_container = ctk.CTkFrame(main_content, fg_color="transparent")
        bottom_container.pack(side="bottom", fill="x", pady=(5, 0))

        progresso_frame = ctk.CTkFrame(bottom_container, fg_color="transparent")
        progresso_frame.pack(fill="x", pady=(0, 5))

        self.lbl_progresso = ctk.CTkLabel(
            progresso_frame,
            text="Aguardando ação...",
            font=ctk.CTkFont(weight="bold"),
            text_color=self.BTN_NEUTRO[0],
        )
        self.lbl_progresso.pack(anchor="w")

        self.progresso_var = tk.DoubleVar()
        self.barra_progresso = ctk.CTkProgressBar(
            progresso_frame,
            variable=self.progresso_var,
            progress_color=self.BTN_ALTA[0],
            fg_color="#CBD5E1",
            height=12,
        )
        self.barra_progresso.set(0)
        self.barra_progresso.pack(fill="x", pady=(2, 5))

        ctk.CTkLabel(
            bottom_container,
            text="Console de Registros:",
            font=ctk.CTkFont(weight="bold"),
            text_color=self.COR_TEXTO,
        ).pack(anchor="w")
        self.caixa_logs = ctk.CTkTextbox(
            bottom_container,
            height=110,
            font=("Consolas", 11),
            fg_color="#FFFFFF",
            text_color="#000000",
            border_color="#64748B",
            border_width=2,
        )
        self.caixa_logs.pack(fill="x", pady=(2, 0))

        tabela_frame = ctk.CTkFrame(
            main_content,
            fg_color=self.COR_CARD,
            corner_radius=10,
            border_width=1,
            border_color="#CBD5E1",
        )
        tabela_frame.pack(side="top", fill="both", expand=True, pady=5)
        ctk.CTkLabel(
            tabela_frame,
            text="Painel de Monitoramento (Busca Atual)",
            font=ctk.CTkFont(weight="bold"),
            text_color=self.COR_TEXTO,
        ).pack(anchor="w", padx=15, pady=8)

        tabela_inner = tk.Frame(tabela_frame, bg=self.COR_CARD)
        tabela_inner.pack(fill="both", expand=True, padx=15, pady=(0, 10))
        tabela_inner.columnconfigure(0, weight=1)
        tabela_inner.rowconfigure(0, weight=1)

        self.colunas_config = [
            ("termo", "TERMO/CONTROLE", 120, "center"),
            ("uf", "UF", 60, "center"),
            ("ticket", "TICKET", 100, "center"),
            ("doc_guia", "CPF/CNPJ GUIA", 150, "center"),
            ("status_conf", "STATUS CONF.", 160, "center"),
            ("cod_barras_orig", "BARRAS ORIG (COMPLETO)", 430, "w"),
            ("cod_barras", "BARRAS (44)", 380, "w"),
            ("data", "DATA", 100, "center"),
            ("vencimento", "VENCIMENTO", 110, "center"),
            ("valor", "VALOR (R$)", 100, "e"),
            ("cte", "CTE / REMESSA", 160, "w"),
            ("tomador", "TOMADOR", 200, "w"),
            ("num_arquivo", "NÚMERO ARQUIVO", 120, "center"),
            ("chave", "CHAVE ARQUIVO (55)", 180, "w"),
            ("dacte", "DACTE (57)", 180, "w"),
        ]

        self.tabela = ttk.Treeview(
            tabela_inner, columns=[c[0] for c in self.colunas_config], show="headings"
        )
        self.tabela.tag_configure("vencido", background="#FFD8D8", foreground="#780927")
        self.tabela.tag_configure("incompleto", background="#FFF2CC", foreground="#7F6000")
        self.tabela.tag_configure(
            "divergencia_fraction", background="#FFE0B2", foreground="#7C2D12"
        )

        for col, nome_exibicao, largura, ancoragem in self.colunas_config:
            self.tabela.heading(
                col,
                text=nome_exibicao,
                command=lambda c=col: self._ordenar_tabela(c, False),
            )
            self.tabela.column(col, width=largura, anchor=cast(Any, ancoragem), stretch=False)
        self.tabela.bind("<Button-3>", self._mostrar_menu_contexto)
        self.tabela.bind("<Double-1>", self._mostrar_detalhes_divergencias_fraction)

        scroll_y = ttk.Scrollbar(tabela_inner, orient="vertical", command=self.tabela.yview)
        scroll_x = ttk.Scrollbar(tabela_inner, orient="horizontal", command=self.tabela.xview)
        self.tabela.configure(yscrollcommand=scroll_y.set, xscrollcommand=scroll_x.set)

        self.tabela.grid(row=0, column=0, sticky="nsew")
        scroll_y.grid(row=0, column=1, sticky="ns")
        scroll_x.grid(row=1, column=0, sticky="ew")

        self.log(
            f"Sistema inicializado. Histórico salvo: {len(self.memoria_termos)} termo(s) e {len(self.tickets_processados)} ticket(s)."
        )
        self.janela.mainloop()

    def _atualizar_cards_metricas(self):
        """Calcula e atualiza os valores dos cards de métricas em tempo real"""
        qtd_ok = 0
        qtd_vencidas = 0
        qtd_quarentena = 0
        valor_total_acumulado = 0.0
        hoje = datetime.now().date()
        with self.lock:
            dados_copia = list(self.dados_em_memoria)

        for item in dados_copia:
            st = str(item.get("STATUS CONFERÊNCIA", "OK"))
            venc_str = str(item.get("VENCIMENTO", "Não informado"))
            val_str = str(item.get("VALOR", "Não informado"))

            # 1. Checagem de Vencimento
            esta_vencido = False
            if venc_str != "Não informado":
                for dt_p in venc_str.split(","):
                    try:
                        if datetime.strptime(dt_p.strip(), "%d/%m/%Y").date() < hoje:
                            esta_vencido = True
                    except Exception:
                        pass

            if esta_vencido:
                qtd_vencidas += 1
            elif "INCOMPLETO" in st or "Falta" in st or "DIVERGÊNCIA" in st:
                qtd_quarentena += 1
            else:
                qtd_ok += 1

            # 2. Soma os valores monetários sem dividir os centavos pela vírgula decimal.
            for valor in separar_valores_monetarios(val_str):
                try:
                    valor_normalizado = normalizar_valor_monetario(valor).replace(",", ".")
                    valor_total_acumulado += float(Decimal(valor_normalizado))
                except (InvalidOperation, ValueError):
                    log_terminal(
                        "AVISO",
                        f"Valor monetário inválido ignorado no painel: {valor!r}",
                    )

        def _task_ui():
            self.lbl_card_ok.configure(text=str(qtd_ok))
            self.lbl_card_vencidas.configure(text=str(qtd_vencidas))
            self.lbl_card_quarentena.configure(text=str(qtd_quarentena))
            val_fmt = (
                f"R$ {valor_total_acumulado:,.2f}".replace(",", "X")
                .replace(".", ",")
                .replace("X", ".")
            )
            self.lbl_card_valor.configure(text=val_fmt)

        if hasattr(self, "janela") and self.janela:
            self.janela.after(0, _task_ui)

    def _ordenar_tabela(self, coluna, reverso):
        dados = [(self.tabela.set(k, coluna), k) for k in self.tabela.get_children("")]
        dados.sort(reverse=reverso)
        for index, (val, k) in enumerate(dados):
            self.tabela.move(k, "", index)
        self.tabela.heading(coluna, command=lambda: self._ordenar_tabela(coluna, not reverso))

    def _mostrar_detalhes_divergencias_fraction(self, event=None, iid=None):
        item_id = iid or (self.tabela.identify_row(event.y) if event else "")
        if not item_id:
            return
        divergencias = getattr(self, "_divergencias_fraction_por_iid", {}).get(item_id, [])
        if not divergencias:
            return

        janela = tk.Toplevel(self.janela)
        janela.title("Divergências encontradas no Fraction")
        janela.geometry("760x420")
        janela.transient(self.janela)
        janela.configure(bg="#FFF7ED")

        tk.Label(
            janela,
            text="Divergências encontradas — valores da guia e do Fraction",
            font=("Segoe UI", 12, "bold"),
            fg="#9A3412",
            bg="#FFF7ED",
            anchor="w",
        ).pack(fill="x", padx=16, pady=(14, 10))

        corpo = tk.Frame(janela, bg="#FFF7ED")
        corpo.pack(fill="both", expand=True, padx=16, pady=(0, 12))
        for divergencia in divergencias:
            campo = tk.Frame(
                corpo, bg="#FED7AA", highlightbackground="#F97316", highlightthickness=1
            )
            campo.pack(fill="x", pady=4)
            tk.Label(
                campo,
                text=divergencia["campo"],
                font=("Segoe UI", 10, "bold"),
                fg="#9A3412",
                bg="#FED7AA",
                anchor="w",
            ).pack(fill="x", padx=10, pady=(7, 2))
            tk.Label(
                campo,
                text=f"Guia: {divergencia['guia']}",
                font=("Segoe UI", 9),
                fg="#7C2D12",
                bg="#FED7AA",
                anchor="w",
                justify="left",
                wraplength=710,
            ).pack(fill="x", padx=10, pady=2)
            tk.Label(
                campo,
                text=f"Fraction: {divergencia['fraction']}",
                font=("Segoe UI", 9),
                fg="#7C2D12",
                bg="#FED7AA",
                anchor="w",
                justify="left",
                wraplength=710,
            ).pack(fill="x", padx=10, pady=(2, 7))

        tk.Button(janela, text="Fechar", command=janela.destroy).pack(pady=(0, 12))

    def _mostrar_menu_contexto(self, event):
        item = self.tabela.identify_row(event.y)
        if item:
            self.tabela.selection_set(item)
            menu = tk.Menu(self.janela, tearoff=0)
            menu.add_command(
                label="📋 Copiar LINHA Completa",
                command=lambda: self._copiar_celula_tabela(item, "tudo"),
            )
            if getattr(self, "_divergencias_fraction_por_iid", {}).get(item):
                menu.add_command(
                    label="🟠 Ver divergências do Fraction",
                    command=lambda: self._mostrar_detalhes_divergencias_fraction(iid=item),
                )
            menu.add_separator()
            menu.add_command(
                label="📋 Copiar apenas CTE",
                command=lambda: self._copiar_celula_tabela(item, "cte"),
            )
            menu.add_command(
                label="📋 Copiar apenas TERMO",
                command=lambda: self._copiar_celula_tabela(item, "termo"),
            )
            menu.add_command(
                label="📋 Copiar apenas TOMADOR",
                command=lambda: self._copiar_celula_tabela(item, "tomador"),
            )
            menu.add_separator()
            menu.add_command(
                label="📥 Copiar TODOS os CTEs da Tabela",
                command=lambda: self._copiar_coluna_inteira("cte"),
            )
            menu.post(event.x_root, event.y_root)

    def _copiar_celula_tabela(self, item, coluna_id):
        valores = self.tabela.item(item, "values")
        if coluna_id == "tudo":
            texto, msg = "\t".join(str(v) for v in valores), "Linha completa copiada!"
        else:
            colunas_ids = [c[0] for c in self.colunas_config]
            texto, msg = str(valores[colunas_ids.index(coluna_id)]), "Valor copiado!"
        self.copiar_para_clipboard(texto)
        self.log(f"[App] {msg}")

    def _copiar_coluna_inteira(self, coluna_id):
        idx = [c[0] for c in self.colunas_config].index(coluna_id)
        lista = [
            str(self.tabela.item(c, "values")[idx]).strip()
            for c in self.tabela.get_children()
            if str(self.tabela.item(c, "values")[idx]).strip() not in ["", "Sem CTE"]
        ]
        self.copiar_para_clipboard("\n".join(lista))
        self.log(f"[App] {len(lista)} itens copiados!")

    def log(self, mensagem: str):
        if hasattr(self, "janela") and self.janela:
            self.janela.after(
                0,
                lambda: (
                    self.caixa_logs.insert(
                        tk.END, f"[{datetime.now().strftime('%H:%M:%S')}] {mensagem}\n"
                    ),
                    self.caixa_logs.see(tk.END),
                ),
            )

    def atualizar_tabela_gui(self):
        def _task():
            with self.lock:
                dados_copia = list(self.dados_em_memoria)
            self._divergencias_fraction_por_iid = {}

            for item in self.tabela.get_children():
                self.tabela.delete(item)
            hoje = datetime.now().date()

            for item in dados_copia:
                tomador = item.get("TOMADOR", "Aguardando Conciliação")
                venc_str = str(item.get("VENCIMENTO", "Não informado"))
                status_conf = str(item.get("STATUS CONFERÊNCIA", "OK"))

                esta_vencido = False
                if venc_str != "Não informado":
                    for data_p in venc_str.split(","):
                        try:
                            if datetime.strptime(data_p.strip(), "%d/%m/%Y").date() < hoje:
                                esta_vencido = True
                        except Exception:
                            pass

                divergencias_fraction = item.get("DIVERGENCIAS_FRACTION", [])
                tags_item = ()
                if divergencias_fraction:
                    tags_item = ("divergencia_fraction",)
                elif esta_vencido:
                    tags_item = ("vencido",)
                elif "INCOMPLETO" in status_conf or "Falta" in status_conf:
                    tags_item = ("incompleto",)

                campos_destacados = {
                    divergencia.get("coluna") for divergencia in divergencias_fraction
                }
                valores = (
                    limpar_texto_excel(item.get("TERMO")),
                    limpar_texto_excel(item.get("UF", "GERAL")),
                    limpar_texto_excel(item.get("TICKET")),
                    ("⚠ " if "doc_guia" in campos_destacados else "")
                    + limpar_texto_excel(item.get("CPF/CNPJ DA GUIA", "")),
                    status_conf,
                    limpar_texto_excel(item.get("CODIGO BARRAS ORIGINAL", "Sem Código")),
                    limpar_texto_excel(item.get("CODIGO BARRAS", "Sem Código")),
                    limpar_texto_excel(item.get("DATA", "Não Informado")),
                    limpar_texto_excel(item.get("VENCIMENTO", "Não informado")),
                    limpar_texto_excel(item.get("VALOR", "Não informado")),
                    limpar_texto_excel(item.get("CTE", "Sem CTE")),
                    tomador,
                    ("⚠ " if "num_arquivo" in campos_destacados else "")
                    + limpar_texto_excel(item.get("NÚMERO ARQUIVO", "Sem Número")),
                    ("⚠ " if "chave" in campos_destacados else "")
                    + limpar_texto_excel(item.get("CHAVE ARQUIVO", "Sem Arquivo Válido")),
                    ("⚠ " if "dacte" in campos_destacados else "")
                    + limpar_texto_excel(item.get("DACTE", "Sem DACTE")),
                )
                iid = self.tabela.insert("", tk.END, values=valores, tags=tags_item)
                if divergencias_fraction:
                    self._divergencias_fraction_por_iid[iid] = divergencias_fraction

            # Atualiza os Cards de Métricas do Dashboard
            self._atualizar_cards_metricas()

        if hasattr(self, "janela") and self.janela:
            self.janela.after(0, _task)

    def atualizar_progresso(self, atual: int, total: int):
        def _task():
            self.progresso_var.set(atual / total if total > 0 else 0)
            self.lbl_progresso.configure(
                text=f"✅ Operação Concluída! ({total} itens)"
                if atual == total
                else f"Processando: {atual} de {total}...",
                text_color=self.BTN_ALTA[0] if atual == total else self.BTN_NEUTRO[0],
            )

        if hasattr(self, "janela") and self.janela:
            self.janela.after(0, _task)

    def resetar_progresso(self):
        if hasattr(self, "janela") and self.janela:
            self.janela.after(0, lambda: self.progresso_var.set(0))
            self.janela.after(
                0,
                lambda: self.lbl_progresso.configure(
                    text="Aguardando ação...", text_color=self.BTN_NEUTRO[0]
                ),
            )

    def solicitar_cancelamento(self):
        self.cancelar_operacao = True
        self.log("[!] Parada solicitada.")

    def obter_lista_tickets(self) -> list[str]:
        texto = self.entry_tickets.get("0.0", tk.END).strip()
        tickets = re.findall(r"\b\d{6,9}\b", texto)
        if tickets:
            self.entry_tickets.delete("0.0", tk.END)
            self.entry_tickets.insert(tk.END, "\n".join(tickets))
        return tickets

    def _identificar_uf(self, ticket_data: dict | None, txt_pdf: str = "") -> str:
        return identificar_uf_ticket(ticket_data, txt_pdf)

    def iniciar_thread(self, acao: str):
        if acao == "solicitar_cancelamento":
            return self.solicitar_cancelamento()

        if acao == "atualizar_tabela":
            self.atualizar_tabela_gui()
            self.log("[✓] Tabela visualizada atualizada com os dados em memória.")
            return

        if acao == "planilha_carregar":
            arq = filedialog.askopenfilename(
                title="Selecione a Planilha de Conferência",
                filetypes=[("Excel Workbooks", "*.xlsx"), ("CSV", "*.csv")],
                initialdir=self.ultimo_dir_base,
            )
            if arq:
                self.ultimo_dir_base = os.path.dirname(arq)
                self.salvar_memoria_diaria()
                threading.Thread(
                    target=self._acao_carregar_planilha_conferencia,
                    args=(arq,),
                    daemon=True,
                ).start()
            return

        if acao == "abrir_sobre":

            def _abrir_sobre():
                if self.janela_sobre is not None and self.janela_sobre.winfo_exists():
                    self.janela_sobre.focar_janela()
                else:
                    self.janela_sobre = JanelaSobre(self.janela)

            self.janela.after(0, _abrir_sobre)
            return

        if acao == "abrir_configuracoes":

            def _abrir_config():
                if self.janela_config is not None and self.janela_config.winfo_exists():
                    self.janela_config.focar_janela()
                else:
                    self.janela_config = JanelaConfiguracoes(
                        self.janela,
                        self.gerenciador_layouts,
                        self,
                    )

            self.janela.after(0, _abrir_config)
            return

        if acao == "limpar_cache_tomadores":
            with self.lock:
                quantidade_cache = len(self.ctes_consultados_cache)
                self.ctes_consultados_cache.clear()
            self.salvar_memoria_diaria()
            self.log(f"[✓] Cache de tomadores limpo: {quantidade_cache} registro(s) removido(s).")
            return

        tickets = self.obter_lista_tickets()
        if not tickets and acao in [
            "planilha",
            "anexos",
            "abrir",
            "visualizar_app",
        ]:
            return messagebox.showwarning("Atenção", "Cole IDs de Ticket válidos!")

        self.cancelar_operacao = False
        self.resetar_progresso()

        if acao == "conciliar_tomador":
            clipboard_txt = self.obter_do_clipboard()
            threading.Thread(
                target=self._acao_conciliar_tomador, args=(clipboard_txt,), daemon=True
            ).start()
            return

        acoes_dir = {
            "abrir": lambda: [
                webbrowser.open(
                    f"https://{self._api_pronto().subdomain}.zendesk.com/agent/tickets/{t}"
                )
                for t in tickets
            ],
            "visualizar_app": lambda: webbrowser.open(
                f"https://{self._api_pronto().subdomain}.zendesk.com/agent/tickets/{tickets[0]}"
            ),
        }

        if acao in acoes_dir:
            threading.Thread(target=acoes_dir[acao], daemon=True).start()

        elif acao == "planilha":
            arq = filedialog.asksaveasfilename(
                title="Onde salvar a Conferência Zendesk?",
                initialdir=self.ultimo_dir_base,
                initialfile=f"Conferencia_Zendesk_{datetime.now().strftime('%Y%m%d_%H%M%S')}.xlsx",
                defaultextension=".xlsx",
                filetypes=[("Excel Workbooks", "*.xlsx"), ("CSV", "*.csv")],
            )
            if arq:
                self.ultimo_dir_base = os.path.dirname(arq)
                self.salvar_memoria_diaria()
                threading.Thread(
                    target=self._acao_planilha, args=(tickets, arq), daemon=True
                ).start()

        elif acao == "anexos":
            pasta = filedialog.askdirectory(
                title="Onde salvar a pasta raiz de Anexos?",
                initialdir=self.ultimo_dir_base,
            )
            if pasta:
                self.ultimo_dir_base = pasta
                self.salvar_memoria_diaria()
                threading.Thread(
                    target=self._acao_anexos, args=(tickets, pasta), daemon=True
                ).start()

        elif acao == "planilha_pasta":
            p_orig = filedialog.askdirectory(
                title="Selecione a Pasta de Origem dos PDFs:",
                initialdir=self.ultimo_dir_base,
            )
            if p_orig:
                self.ultimo_dir_base = p_orig
                self.salvar_memoria_diaria()
                arq = filedialog.asksaveasfilename(
                    title="Onde salvar a Conferência da Pasta?",
                    initialdir=self.ultimo_dir_base,
                    initialfile=f"Conferencia_Local_{datetime.now().strftime('%Y%m%d_%H%M%S')}.xlsx",
                    defaultextension=".xlsx",
                    filetypes=[("Excel Workbooks", "*.xlsx"), ("CSV", "*.csv")],
                )
                if arq:
                    self.ultimo_dir_base = os.path.dirname(arq)
                    self.salvar_memoria_diaria()
                    threading.Thread(
                        target=self._acao_planilha_pasta,
                        args=(p_orig, arq),
                        daemon=True,
                    ).start()

        elif acao == "salvar_final":
            arq = filedialog.asksaveasfilename(
                title="Onde salvar o Relatório Final?",
                initialdir=self.ultimo_dir_base,
                initialfile=f"Relatorio_Final_{datetime.now().strftime('%Y%m%d_%H%M%S')}.xlsx",
                defaultextension=".xlsx",
                filetypes=[("Excel Workbooks", "*.xlsx"), ("CSV", "*.csv")],
            )
            if arq:
                self.ultimo_dir_base = os.path.dirname(arq)
                self.salvar_memoria_diaria()
                threading.Thread(
                    target=self._acao_salvar_relatorio_final, args=(arq,), daemon=True
                ).start()

    @registrar_execucao("Download e organização de anexos")
    def _acao_anexos(self, tickets: list[str], pasta_destino: str):
        self.log(
            f"[Anexos] Iniciando download e organização por Estado de {len(tickets)} ticket(s)..."
        )

        now_str = datetime.now().strftime("%d/%m/%Y %H:%M")
        for tid in tickets:
            with self.lock:
                if tid in self.tickets_processados:
                    self.log(
                        f"[i] Ticket #{tid} já consta no histórico ({self.tickets_processados[tid]}). Rebaixando anexos..."
                    )
                self.tickets_processados[tid] = now_str
        self.salvar_memoria_diaria()

        hashes_baixados = set()

        for i, tid in enumerate(tickets, 1):
            if self.cancelar_operacao:
                return self.resetar_progresso()
            log_terminal(
                "PROGRESSO",
                f"Baixando anexos do ticket {i} de {len(tickets)}: #{tid}...",
            )
            resultado_ticket = processar_e_salvar_anexos_ticket(
                tid,
                pasta_destino,
                hashes_baixados,
                obter_ticket=lambda ticket_id: self._api_pronto().obter_ticket(ticket_id),
                obter_comentarios=lambda ticket_id: self._api_pronto().obter_comentarios(ticket_id),
                identificar_uf=self._identificar_uf,
                cancelar=lambda: self.cancelar_operacao,
                baixar_conteudo=self._api_pronto().baixar_conteudo,
                analisar_anexo=lambda ticket_id, nome, conteudo, uf, duplicado: (
                    analisar_anexo_baixado(
                        ticket_id,
                        nome,
                        conteudo,
                        uf,
                        duplicado,
                        extrair_texto=extrair_texto_pdf,
                        identificar_uf=lambda texto: self._identificar_uf(None, texto),
                        identificar_layout=self.gerenciador_layouts.identificar_e_extrair,
                        eh_dar=e_dar_documento,
                        eh_termo=e_termo_documento,
                        eh_nota_fiscal=e_nota_fiscal,
                        extrair_vencimento_valor=extrair_vencimento_e_valor_pdf,
                        padronizar_data=padronizar_data_ddmmyyyy,
                        documento_vencido=documento_esta_vencido,
                        extrair_vencimento_nota=extrair_vencimento_nota,
                    )
                ),
                ao_erro_download=lambda nome, ticket_id, status: self.log(
                    f"[!] Erro ao baixar '{nome}' (Ticket #{ticket_id}): {status}"
                ),
                ao_detectar_duplicado=lambda nome, ticket_id: self.log(
                    f"[!] Arquivo duplicado detectado: '{nome}' (Ticket #{ticket_id})."
                ),
                ao_entrar_quarentena=lambda ticket_id, resultado: self.log(
                    f"[⚠️ INCONSISTÊNCIA] Ticket #{ticket_id}: "
                    f"{resultado.motivo_quarentena}. Enviando para 'QUARENTENA'."
                ),
            )
            if not resultado_ticket:
                self.log(f"[!] Ticket #{tid} não encontrado ou sem acesso.")
                continue

            uf_ticket_tag, resultado_anexos = resultado_ticket

            self.log(
                f"[✓] Ticket #{tid} ({uf_ticket_tag}): "
                f"{len(resultado_anexos.anexos)} anexo(s) salvo(s) "
                f"na estrutura do estado {uf_ticket_tag}."
            )
            self.salvar_checkpoint(f"ticket de anexos #{tid}")
            self.atualizar_progresso(i, len(tickets))

        self.log(f"[🏆] Downloads e organização finalizados em: {pasta_destino}")

    @registrar_execucao("Geração de planilha via Zendesk")
    def _acao_planilha(self, tickets: list[str], caminho_csv: str):
        self.log(f"[Zendesk] Processando {len(tickets)} ticket(s) em lote paralelo...")

        with self.lock:
            self.dados_em_memoria = []
        self.atualizar_tabela_gui()

        termos_map = {}
        now_str = datetime.now().strftime("%d/%m/%Y %H:%M")
        lock_termos = threading.Lock()

        def processar_single_ticket(ticket_id):
            if self.cancelar_operacao:
                return None

            with self.lock:
                self.tickets_processados[ticket_id] = now_str

            resp_ticket = self._api_pronto().obter_ticket(ticket_id)
            if not resp_ticket:
                self.log(f"[!] Ticket #{ticket_id} não retornado pela API.")
                return None

            processar_e_agregar_ticket_para_planilha(
                ticket_id,
                resp_ticket,
                self._api_pronto().obter_comentarios(ticket_id),
                self.memoria_termos,
                termos_map,
                opcoes_processamento={
                    "padronizar_data": padronizar_data_ddmmyyyy,
                    "identificar_uf": self._identificar_uf,
                    "baixar_conteudo": self._api_pronto().baixar_conteudo,
                    "extrair_texto": extrair_texto_pdf,
                    "eh_nota_fiscal": e_nota_fiscal,
                    "eh_dar": e_dar_documento,
                    "eh_termo": e_termo_documento,
                    "extrair_remessas_ap": extrair_remessas_ap,
                    "obter_chaves_nfe": extrair_chaves_nfe_pdf,
                    "formatar_numero": formatar_numero_arquivo,
                    "separar_guias_ap": separar_guias_ap,
                    "extrair_documento": extrair_documento,
                    "validar_guia_ap": validar_guia_ap,
                    "marcar_ap_processada": _marcar_status_guia_ap_processada,
                    "resumir_nfe_map": resumo_nfe_map,
                    "ao_log": log_terminal,
                    "identificar_layout": self.gerenciador_layouts.identificar_e_extrair,
                },
                lock_termos=lock_termos,
                campos_al=AL_CAMPOS_PLANILHA,
                limpar_texto=limpar_texto_excel,
                formatar_numero=formatar_numero_arquivo,
                padronizar_data=padronizar_data_ddmmyyyy,
                marcar_ap_processada=_marcar_status_guia_ap_processada,
            )

            return ticket_id

        concluidos = 0
        with ThreadPoolExecutor(max_workers=8) as executor:
            futuros = [executor.submit(processar_single_ticket, tid) for tid in tickets]
            for futuro in as_completed(futuros):
                res = futuro.result()
                if res:
                    concluidos += 1
                    log_terminal(
                        "PROGRESSO",
                        f"Processando ticket {concluidos} de {len(tickets)}...",
                    )
                    self.log(f"[✓] Ticket #{res} processado.")
                    self.salvar_checkpoint(f"ticket Zendesk #{res}")
                    self.atualizar_progresso(concluidos, len(tickets))

        self._compilar_e_salvar(termos_map, caminho_csv)

        if self.cookie_jadlog:
            self.log(
                "[Automático] Cookie Jadlog ativo! Iniciando conciliação automática do Tomador pelo Número do Arquivo / CTE..."
            )
            clipboard_txt = self.obter_do_clipboard()
            self._acao_conciliar_tomador(clipboard_txt)
            self._atualizar_relatorio_zendesk_apos_conciliacao(caminho_csv)

    @registrar_execucao("Geração de planilha via pasta local")
    def _acao_planilha_pasta(self, pasta_origem: str, caminho_csv: str):
        self.log(f"[Pasta] Lendo PDFs recursivamente em pastas e subpastas de: {pasta_origem}...")

        with self.lock:
            self.dados_em_memoria = []
        self.atualizar_tabela_gui()

        termos_map = {}
        try:
            resultado_pasta = processar_pasta_local_para_relatorio(
                pasta_origem,
                self.memoria_termos,
                limpar_texto=limpar_texto_excel,
                formatar_numero_relatorio=formatar_numero_arquivo,
                padronizar_data_relatorio=padronizar_data_ddmmyyyy,
                identificar_uf=lambda texto: self._identificar_uf(None, texto),
                eh_nota_fiscal=e_nota_fiscal,
                separar_guias_ap=separar_guias_ap,
                identificar_layout=self.gerenciador_layouts.identificar_e_extrair,
                historico_termos=self.memoria_termos,
                marcar_ap_processada=_marcar_status_guia_ap_processada,
                obter_chaves_nfe=extrair_chaves_nfe_pdf,
                formatar_numero=formatar_numero_arquivo,
                padronizar_data=padronizar_data_ddmmyyyy,
                cancelado=lambda: self.cancelar_operacao,
                ao_inicio=lambda quantidade: self.log(
                    f"[Pasta] Encontrados {quantidade} arquivo(s) PDF para leitura..."
                ),
                ao_progresso=self.atualizar_progresso,
                ao_log=log_terminal,
                ao_aviso=self.log,
                ao_erro=lambda nome, erro: self.log(f"[!] Erro ao abrir arquivo {nome}: {erro}"),
            )
            lote_pdf = resultado_pasta.lote_pdf
            if lote_pdf.cancelado:
                return self.resetar_progresso()
            if not lote_pdf.quantidade_arquivos:
                return self.log("[!] Nenhum arquivo PDF encontrado na pasta ou nas subpastas.")

            termos_map = resultado_pasta.termos_map
            self._doc_ap05_por_chave = lote_pdf.doc_ap05_por_chave
            self._compilar_e_salvar(termos_map, caminho_csv)
            self.salvar_checkpoint("lote de PDFs da pasta local")

            if self.cookie_jadlog:
                self.log(
                    "[Pasta] Cookie Jadlog ativo! Iniciando conciliação automática do Tomador pelo Número do Arquivo / CTE..."
                )
                clipboard_txt = self.obter_do_clipboard()
                self._acao_conciliar_tomador(clipboard_txt)
                self._atualizar_relatorio_zendesk_apos_conciliacao(caminho_csv)

        except Exception as e:  # noqa: BLE001
            self.log(f"[!] Erro geral no processamento da pasta: {e}")

    def _limpar_historico_uf(self, uf: str) -> None:
        uf_normalizada = uf.upper()
        with self.lock:
            controles_removidos = [
                termo
                for termo, dados in self.memoria_termos.items()
                if uf_normalizada
                in {
                    str(valor).upper()
                    for valor in (
                        dados.get("UF", [])
                        if isinstance(dados.get("UF", []), list)
                        else [dados.get("UF", "")]
                    )
                }
            ]
            for termo in controles_removidos:
                del self.memoria_termos[termo]

        log_terminal(
            "LIMPEZA",
            f"Histórico de {uf_normalizada} zerado antes do novo lote: {len(controles_removidos)} controle(s).",
        )

    def _compilar_e_salvar(self, termos_map, caminho_csv):
        processamento_atual = timestamp_processamento()

        resultado = compilar_relatorio_e_atualizar_dados(
            termos_map,
            self.memoria_termos,
            self.dados_em_memoria,
            processamento_atual,
            lock=self.lock,
            persistir_memoria=self.salvar_memoria_diaria,
            limpar_texto=limpar_texto_excel,
            formatar_texto=formatar_texto_excel,
            formatar_numero=formatar_numero_arquivo,
            padronizar_data=padronizar_data_ddmmyyyy,
            normalizar_valor=normalizar_valor_monetario,
            separar_valores=separar_valores_monetarios,
        )

        cabecalho = resultado.cabecalho
        linhas_csv = resultado.linhas

        try:
            caminho_gerado = salvar_planilha_multisheets(caminho_csv, cabecalho, linhas_csv)
            self.atualizar_tabela_gui()
            self.log(f"[🏆] Relatório Gerado com {len(linhas_csv)} linha(s) em: {caminho_gerado}")
        except Exception as e:
            self.log(f"[!] Falha ao gravar arquivo: {e}")

    def _atualizar_relatorio_zendesk_apos_conciliacao(self, caminho_csv: str):
        with self.lock:
            dados_copia = [dict(item) for item in self.dados_em_memoria]

        cabecalho = cabecalho_relatorio()
        linhas = linhas_relatorio_conciliacao(
            dados_copia,
            limpar_texto=limpar_texto_excel,
            formatar_texto=formatar_texto_excel,
            padronizar_data=padronizar_data_ddmmyyyy,
            timestamp=timestamp_processamento,
        )

        try:
            caminho_gerado = salvar_planilha_multisheets(caminho_csv, cabecalho, linhas)
            self.log(f"[Zendesk] Relatório de Tomadores atualizado e salvo: {caminho_gerado}")
        except Exception as e:
            self.log(f"[!] Falha ao atualizar relatório após conciliação: {e}")

    @registrar_execucao("Carregamento de planilha de conferência (Excel/CSV)")
    def _acao_carregar_planilha_conferencia(self, caminho_arquivo: str):
        self.log(
            f"[Carregar] Lendo planilha de conferência: {os.path.basename(caminho_arquivo)}..."
        )

        try:
            with self.lock:
                self.dados_em_memoria = []
                self.memoria_termos = {}
                self.ctes_consultados_cache = {}  # Limpa o cache para permitir reconsulta limpa
            self.atualizar_tabela_gui()
            self.log(
                "[Limpeza] Dados da planilha anterior e cache de tomadores limpos com sucesso."
            )

            if not caminho_arquivo.lower().endswith(".csv") and not HAS_OPENPYXL:
                return self.log("[!] Biblioteca 'openpyxl' não encontrada para ler .xlsx.")

            resultado_importacao = carregar_planilha_conferencia(
                caminho_arquivo,
                campos_al=AL_CAMPOS_PLANILHA,
                limpar_texto=limpar_texto_excel,
                padronizar_data=padronizar_data_ddmmyyyy,
                timestamp=timestamp_processamento,
                ao_progresso=lambda atual, total: log_terminal(
                    "PROGRESSO", f"Carregando registro {atual} de {total}..."
                ),
            )
            novos_dados = resultado_importacao.dados
            termos_lidos = len(novos_dados)

            if resultado_importacao.abas_lidas:
                self.log(
                    f"[Excel] {resultado_importacao.abas_lidas} aba(s) lida(s), "
                    f"{resultado_importacao.linhas_lidas} registro(s) único(s) carregado(s); "
                    f"{resultado_importacao.duplicados_ignorados} duplicado(s) ignorado(s)."
                )

            if not resultado_importacao.linhas_lidas or not resultado_importacao.tem_cabecalho:
                return self.log("[!] Planilha vazia ou formato inválido.")

            with self.lock:
                self.dados_em_memoria = novos_dados
                mesclar_dados_conferencia(
                    novos_dados,
                    self.memoria_termos,
                    campos_al=AL_CAMPOS_PLANILHA,
                    padronizar_data=padronizar_data_ddmmyyyy,
                    normalizar_valor=normalizar_valor_monetario,
                    separar_valores=separar_valores_monetarios,
                )

            self.salvar_memoria_diaria()
            self.atualizar_tabela_gui()
            self.log(
                f"[🏆] Sucesso! {termos_lidos} registros da conferência carregados e exibidos na tela."
            )

            if self.cookie_jadlog:
                self.log("[Fraction] Cookie ativo! Conciliando automático...")
                self._acao_conciliar_tomador()
            else:
                self.log(
                    "[Fraction] Cookie não informado. Atualize o Cookie Fraction e clique em 'Buscar tomadores'."
                )

        except Exception as e:
            self.log(f"[!] Erro ao carregar planilha: {e}")

    @registrar_execucao("Conciliação Fraction Exclusiva por CTe e Validação Pós-Leitura")
    def _acao_conciliar_tomador(self, clipboard_inicial: str = ""):
        with self.lock:
            base_vazia = not bool(self.dados_em_memoria)
        if base_vazia:
            return self.log("[!] Base vazia na tela. Extraia os dados da conferência primeiro.")

        with self.lock:
            dados_copia = list(self.dados_em_memoria)

        cookie_limpo = limpar_e_formatar_cookie(self.cookie_jadlog)

        coordenar_conciliacao_fraction(
            dados_copia,
            cookie_limpo,
            self.ctes_consultados_cache,
            self.lock,
            ao_log=self.log,
            ao_progresso=self.atualizar_progresso,
            deve_cancelar=lambda: self.cancelar_operacao,
        )

        self.atualizar_tabela_gui()
        self.salvar_memoria_diaria()

    @registrar_execucao("Salvamento do relatório final")
    def _acao_salvar_relatorio_final(self, caminho_final: str):
        with self.lock:
            if not self.dados_em_memoria:
                return self.log("[!] Processe os tickets antes de salvar.")
            dados_copia = list(self.dados_em_memoria)

        cabecalho = cabecalho_relatorio()
        linhas = linhas_relatorio_final(
            dados_copia,
            limpar_texto=limpar_texto_excel,
            formatar_texto=formatar_texto_excel,
            padronizar_data=padronizar_data_ddmmyyyy,
            timestamp=timestamp_processamento,
        )

        try:
            caminho_gerado = salvar_planilha_multisheets(caminho_final, cabecalho, linhas)
            self.log(f"[🏆] Relatório Final Salvo em: {caminho_gerado}")
            self.atualizar_progresso(100, 100)
        except Exception as e:
            self.log(f"[!] Erro ao salvar relatório final: {e}")


# ==========================================
# JANELA SOBRE / CRÉDITOS E VERSÃO
# ==========================================
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
        container = ctk.CTkFrame(self, fg_color="#F1F5F9", corner_radius=12)
        container.pack(fill="both", expand=True, padx=20, pady=20)

        ctk.CTkLabel(
            container,
            text="Automação Total JadLog",
            font=("Segoe UI", 18, "bold"),
            text_color="#D31145",
        ).pack(pady=(15, 5))
        ctk.CTkFrame(container, height=2, fg_color="#CBD5E1").pack(fill="x", pady=5, padx=15)

        ctk.CTkLabel(
            container,
            text="✍️ Desenvolvido por:",
            font=("Segoe UI", 11, "bold"),
            text_color="#0F172A",
        ).pack(anchor="w", padx=20, pady=(10, 0))
        ctk.CTkLabel(
            container,
            text="TALITA MATIAS SILVA",
            font=("Segoe UI", 13, "bold"),
            text_color="#1976D2",
        ).pack(anchor="w", padx=20, pady=(0, 5))

        ctk.CTkLabel(
            container,
            text="🚀 Versão do Sistema:",
            font=("Segoe UI", 11, "bold"),
            text_color="#0F172A",
        ).pack(anchor="w", padx=20, pady=(5, 0))
        ctk.CTkLabel(
            container,
            text="1.3 - Versão Produção",
            font=("Segoe UI", 11),
            text_color="#334155",
        ).pack(anchor="w", padx=20, pady=(0, 5))

        ctk.CTkLabel(
            container,
            text="📅 Mês / Ano de Criação:",
            font=("Segoe UI", 11, "bold"),
            text_color="#0F172A",
        ).pack(anchor="w", padx=20, pady=(5, 0))
        ctk.CTkLabel(
            container,
            text="Setembro / 2026",
            font=("Segoe UI", 11),
            text_color="#334155",
        ).pack(anchor="w", padx=20, pady=(0, 5))

        ctk.CTkLabel(
            container,
            text="📌 Uso do App:",
            font=("Segoe UI", 11, "bold"),
            text_color="#0F172A",
        ).pack(anchor="w", padx=20, pady=(5, 0))
        ctk.CTkLabel(
            container,
            text="Automação, leitura, validação e organização de guias (DAR), termos de averiguação e notas fiscais com integração Zendesk e conciliação de tomadores.",
            font=("Segoe UI", 10),
            text_color="#334155",
            justify="left",
            wraplength=400,
        ).pack(anchor="w", padx=20, pady=(0, 15))

        ctk.CTkButton(
            container,
            text="Fechar",
            width=120,
            fg_color="#475569",
            command=self.destroy,
        ).pack(pady=(5, 10))


if __name__ == "__main__":
    log_terminal("INÍCIO", "Aplicativo Automação Total JadLog iniciando.")
    app = ZendeskAppGUI()
    log_terminal("CONCLUÍDO", "Aplicativo encerrado.")
