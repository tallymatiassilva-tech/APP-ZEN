import csv
import ctypes
import hashlib
import io
import json
import os
import random
import re
import shutil
import sys
import threading
import time
import tkinter as tk
import webbrowser
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timedelta
from decimal import Decimal, InvalidOperation
from functools import wraps
from pathlib import Path
from tkinter import filedialog, messagebox, ttk
from typing import Any, cast
from urllib.parse import urljoin

import customtkinter as ctk
import pypdf
import requests
from bs4 import BeautifulSoup
from requests.adapters import HTTPAdapter

from src.services.extraction_service import extrair_documento
from src.services.pdf_service import (
    extrair_texto_pdf as extrair_texto_pdf_servico,
)
from src.services.pdf_service import (
    extrair_texto_por_caixa,
    mesclar_pdfs,
)


def log_terminal(marcador: str, mensagem: str) -> None:
    timestamp = datetime.now().strftime("%d/%m/%Y %H:%M:%S")
    print(f"[{timestamp}] [{marcador}] {mensagem}", flush=True)


def calcular_hash_md5(conteudo: bytes) -> str:
    """Retorna o MD5 do conteúdo binário do arquivo."""
    return hashlib.md5(conteudo).hexdigest()


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


# Importações de bibliotecas opcionais e configuração de OCR Portátil
keyring: Any = None
try:
    import keyring
except ImportError:
    pass


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
    try:
        keyring.set_password("ZendeskApp", nome, valor)
    except Exception:  # noqa: BLE001, S110
        pass


pdfplumber: Any = None
HAS_PDFPLUMBER = False
try:
    import pdfplumber

    HAS_PDFPLUMBER = True
except ImportError:
    pass

convert_from_bytes: Any = None
pytesseract: Any = None
HAS_OCR = False
try:
    import pytesseract
    from pdf2image import convert_from_bytes

    # DETECÇÃO E CONFIGURAÇÃO DO TESSERACT OCR PORTÁTIL
    if getattr(sys, "frozen", False):
        BASE_DIR = os.path.dirname(sys.executable)
    else:
        BASE_DIR = os.path.dirname(os.path.abspath(__file__))

    candidatos_tesseract = [
        os.path.join(BASE_DIR, "Tesseract-OCR", "tesseract.exe"),
        os.path.join(BASE_DIR, "Tesseract-OCR", "tesseract"),
        shutil.which("tesseract"),
    ]

    tesseract_local_exe = next(
        (c for c in candidatos_tesseract if c and os.path.exists(c)), None
    )
    if tesseract_local_exe:
        pytesseract.pytesseract.tesseract_cmd = tesseract_local_exe
        tessdata_local_dir = os.path.join(
            os.path.dirname(tesseract_local_exe), "tessdata"
        )
        if os.path.exists(tessdata_local_dir):
            os.environ["TESSDATA_PREFIX"] = tessdata_local_dir
        HAS_OCR = True
        print(f"[OCR Portátil] Tesseract carregado: {tesseract_local_exe}")
    else:
        HAS_OCR = False
        print(
            "[OCR] Tesseract não encontrado no ambiente local nem no PATH. OCR desabilitado."
        )

except ImportError:
    HAS_OCR = False
    print("[OCR] Módulos de OCR não disponíveis. OCR desabilitado.")

openpyxl: Any = None
PatternFill: Any = None
Font: Any = None
get_column_letter: Any = None
HAS_OPENPYXL = False
try:
    import openpyxl
    from openpyxl.styles import Font, PatternFill
    from openpyxl.utils import get_column_letter

    HAS_OPENPYXL = True
except ImportError:
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
def extrair_texto_por_caixa(  # noqa: F811
    pdf_bytes: bytes, bbox_pct: tuple[float, float, float, float], page_num: int = 0
) -> str:
    if not pdf_bytes or not HAS_PDFPLUMBER:
        return ""
    try:
        with pdfplumber.open(io.BytesIO(pdf_bytes)) as pdf:
            if page_num < len(pdf.pages):
                page = pdf.pages[page_num]
                w = float(page.width)
                h = float(page.height)

                box = (
                    bbox_pct[0] * w,
                    bbox_pct[1] * h,
                    bbox_pct[2] * w,
                    bbox_pct[3] * h,
                )
                crop_page = page.crop(box)
                txt = crop_page.extract_text(layout=True)
                return txt.strip() if txt else ""
    except Exception as e:  # noqa: BLE001
        print(f"[Erro Crop BoundingBox] {e}")
    return ""


def padronizar_data_ddmmyyyy(val_data: object) -> str:
    val_texto = str(val_data or "").strip()
    if val_texto in ["Não informado", "Não Informado", "Sem Data", ""]:
        return "Não informado"

    datas_encontradas = re.findall(
        r"\b(\d{1,2})[/-](\d{1,2})[/-](\d{2,4})\b", val_texto
    )
    if not datas_encontradas:
        return val_texto

    datas_formatadas = []
    for dia, mes, ano in datas_encontradas:
        dia_f = dia.zfill(2)
        mes_f = mes.zfill(2)
        ano_f = f"20{ano}" if len(ano) == 2 else ano
        datas_formatadas.append(f"{dia_f}/{mes_f}/{ano_f}")

    return ", ".join(dict.fromkeys(datas_formatadas))


def limpar_texto_excel(valor: str) -> str:
    val_str = str(valor or "").strip()
    val_str = re.sub(r'^=\s*"([^"]*)"$', r"\1", val_str)
    while val_str.startswith("'"):
        val_str = val_str[1:]
    return val_str.strip()


def formatar_texto_excel(valor: str) -> str:
    val_str = limpar_texto_excel(valor)
    if not val_str:
        return ""
    if val_str in ["Sem Código", "Sem CTE", "Sem Arquivo Válido", "Sem Número"]:
        return val_str
    if re.match(r"^[0-9\s/\.-]+$", val_str) and len(re.sub(r"\D", "", val_str)) >= 4:
        return f'="{val_str}"'
    return val_str


def formatar_numero_arquivo(valor: str) -> str:
    val_str = limpar_texto_excel(str(valor or ""))
    if not val_str or val_str in ["Sem Número", "Sem Arquivo Válido"]:
        return "Sem Número"

    partes = re.split(r"[\s,]+", val_str)
    partes_formatadas = []
    for p in partes:
        p_limpo = p.strip()
        if not p_limpo:
            continue
        digits_only = re.sub(r"\D", "", p_limpo)
        if digits_only and len(digits_only) <= 9:
            partes_formatadas.append(digits_only.zfill(9))
        elif digits_only:
            partes_formatadas.append(digits_only)
        else:
            partes_formatadas.append(p_limpo)

    return (
        " ".join(dict.fromkeys(partes_formatadas))
        if partes_formatadas
        else "Sem Número"
    )


def ordenar_pares_documento_por_aparicao(
    txt_pdf: str, pares_documento: list[tuple[str, str]]
) -> list[tuple[str, str]]:
    if not pares_documento:
        return pares_documento

    pares_unicos = list(dict.fromkeys(pares_documento))
    posicoes = {}
    for idx, (chave, _) in enumerate(pares_unicos):
        if chave and chave != "Sem Arquivo Válido":
            posicoes[(chave, idx)] = txt_pdf.find(chave)

    def chave_ordem(item: tuple[str, str]) -> tuple[int, int]:
        chave, _ = item
        if chave and chave != "Sem Arquivo Válido":
            pos = txt_pdf.find(chave)
            if pos >= 0:
                return (0, pos)
        return (1, 10**9)

    return sorted(pares_unicos, key=chave_ordem)


def determinar_diretorio_anexo(
    pasta_destino: str | Path,
    estado_dir: str,
    subpasta: str,
    is_dar: bool,
    is_nota: bool,
    is_duplicado: bool,
    is_vencido: bool,
    em_quarentena: bool,
) -> Path:
    raiz = Path(pasta_destino)

    # REGRA EXCLUSIVA AP: Quando vencido, Guia e Nota são direcionados juntos para AP/VENCIDAS
    if estado_dir == "AP":
        if is_duplicado:
            return raiz / "AP" / "DUPLICADOS"
        if is_vencido and (is_dar or is_nota):
            return raiz / "AP" / "VENCIDAS"
        if is_dar:
            return raiz / "AP" / "DAR"
        if is_nota:
            return raiz / "AP" / "NOTAS"
        return raiz / "AP" / subpasta

    if is_duplicado:
        return raiz / estado_dir / "DUPLICADOS"
    if is_vencido:
        return raiz / estado_dir / "VENCIDAS"
    if em_quarentena and subpasta in ["DAR", "TERMO"]:
        return raiz / estado_dir / "QUARENTENA"
    if is_dar:
        return raiz / estado_dir / "DAR"
    if is_nota:
        return raiz / "NOTAS"
    return raiz / estado_dir / subpasta


def extrair_vencimento_nota(texto_pdf: str) -> str:
    match = re.search(
        r"(?:VENCIMENTO|VALIDADE|VALIDO\s+ATE|VÁLIDO\s+ATÉ)"
        r"[^\d]{0,40}(\d{2}[/-]\d{2}[/-]\d{2,4})",
        texto_pdf or "",
        re.IGNORECASE,
    )
    return padronizar_data_ddmmyyyy(match.group(1)) if match else "Não informado"


def documento_esta_vencido(vencimento: str) -> bool:
    hoje = datetime.now().date()
    for data in str(vencimento or "").split(","):
        try:
            if datetime.strptime(data.strip(), "%d/%m/%Y").date() < hoje:
                return True
        except ValueError:
            continue
    return False


def separar_valores_monetarios(valor: Any) -> list[str]:
    texto = str(valor or "").strip()
    if not texto or texto == "Não informado":
        return []

    padrao_brasileiro = re.compile(r"(?<!\d)(?:\d{1,3}(?:\.\d{3})+|\d+),\d{2}(?!\d)")
    valores = padrao_brasileiro.findall(texto)
    if valores:
        return list(dict.fromkeys(valores))

    partes = [parte.strip() for parte in texto.split(",") if parte.strip()]
    reconstruidos = []
    indice = 0
    while indice < len(partes):
        atual = partes[indice].replace("R$", "").strip()
        if (
            indice + 1 < len(partes)
            and re.fullmatch(r"\d{1,3}(?:\.\d{3})*|\d+", atual)
            and re.fullmatch(r"\d{2}", partes[indice + 1])
        ):
            atual = f"{atual},{partes[indice + 1]}"
            indice += 1
        reconstruidos.append(atual)
        indice += 1
    return list(dict.fromkeys(reconstruidos))


def extrair_valor_total_recolher_ap(texto_pdf: str) -> str:
    if not texto_pdf:
        return "Não informado"

    # 1. Procura o campo principal de Valor Total / A Recolher do DAR do Amapá
    padroes_valor_ap = [
        r"(?:14\s*-\s*TOTAL\s+A\s+RECOLHER|TOTAL\s+A\s+RECOLHER)\s*[:=-]?\s*(?:R\$\s*)?(\d{1,3}(?:[.,]\d{3})*[.,]\d{2})",
        r"(?:R\$\s*)?(\d{1,3}(?:[.,]\d{3})*[.,]\d{2})\s*(?:\r?\n)?\s*14\s*-\s*TOTAL\s+A\s+RECOLHER",
        r"(?:10\s*-\s*Valor\s+Principal|Valor\s+Principal|Total\s+do\s+DAR)\s*[:=-]?\s*(?:R\$\s*)?(\d{1,3}(?:[.,]\d{3})*[.,]\d{2})",
    ]

    for pat in padroes_valor_ap:
        match = re.search(pat, texto_pdf, re.IGNORECASE)
        if match:
            valor_raw = match.group(1).strip()
            return normalizar_valor_monetario(valor_raw)

    # 2. Fallback: Procura o último valor monetário no texto da guia
    valores = re.findall(r"\b(\d{1,3}(?:[.,]\d{3})*[.,]\d{2})\b", texto_pdf)
    if valores:
        return normalizar_valor_monetario(valores[-1])

    return "Não informado"


def normalizar_valor_monetario(valor: Any) -> str:
    texto = str(valor or "").replace("R$", "").replace(" ", "").strip()
    if "," in texto:
        texto = texto.replace(".", "").replace(",", ".")
    try:
        decimal = Decimal(texto).quantize(Decimal("0.01"))
    except (InvalidOperation, ValueError):
        return str(valor or "").strip()
    return f"{decimal:.2f}".replace(".", ",")


def limpar_e_formatar_cookie(valor: str) -> str:
    texto = str(valor or "").strip()
    if (texto.startswith('"') and texto.endswith('"')) or (
        texto.startswith("'") and texto.endswith("'")
    ):
        texto = texto[1:-1].strip()
    m_curl = re.search(
        r'(?:-H\s+["\']?Cookie:\s*|Cookie:\s*)([^;\r\n]+)', texto, re.IGNORECASE
    )
    if m_curl:
        texto = m_curl.group(1).strip()
    elif texto.lower().startswith("cookie:"):
        texto = texto[7:].strip()
    if "=" not in texto and len(texto) > 10:
        texto = f"JSESSIONID={texto}"
    return texto


def extrair_dados_tabela_fraction(soup: Any, txt: str, cte_code: str):
    tomador, remetente, destinatario = "", "", ""
    cnpjs = []

    # 1. Tenta extrair de tabelas HTML (grid de resultados do Jadlog Fraction)
    for table in soup.find_all("table"):
        header_row = table.find("tr")
        if not header_row:
            continue
        headers = [
            th.get_text(" ", strip=True).upper()
            for th in header_row.find_all(["th", "td"])
        ]

        next(
            (i for i, h in enumerate(headers) if re.search(r"CONHEC|CTE|REMESSA", h)),
            None,
        )
        idx_tom = next(
            (
                i
                for i, h in enumerate(headers)
                if re.search(r"TOMADOR|PAGADOR|CLIENTE", h)
            ),
            None,
        )
        idx_rem = next(
            (i for i, h in enumerate(headers) if re.search(r"REMET", h)), None
        )
        idx_dest = next(
            (i for i, h in enumerate(headers) if re.search(r"DESTINAT", h)), None
        )
        idx_doc = next(
            (i for i, h in enumerate(headers) if re.search(r"CNPJ|CPF|DOC", h)), None
        )

        for tr in table.find_all("tr")[1:]:
            cells = [td.get_text(" ", strip=True) for td in tr.find_all("td")]
            if not cells:
                continue
            linha_txt = " ".join(cells)
            cte_na_linha = (cte_code in re.sub(r"\D", "", linha_txt)) or (
                len(table.find_all("tr")) == 2
            )
            if cte_na_linha:
                if idx_tom is not None and idx_tom < len(cells) and cells[idx_tom]:
                    tomador = cells[idx_tom].strip()
                if idx_rem is not None and idx_rem < len(cells) and cells[idx_rem]:
                    remetente = cells[idx_rem].strip()
                if idx_dest is not None and idx_dest < len(cells) and cells[idx_dest]:
                    destinatario = cells[idx_dest].strip()
                if idx_doc is not None and idx_doc < len(cells) and cells[idx_doc]:
                    doc_c = re.sub(r"\D", "", cells[idx_doc])
                    if len(doc_c) >= 5:
                        cnpjs.append(doc_c)
                break
        if tomador:
            break

    # 2. Se não achou na tabela, busca por regex no texto da página (tela de detalhes)
    if not tomador:
        m_tom = re.search(
            r"(?:Tomador|Pagador|Cliente)\s*[:\-]?\s*([^\n\r\|;]+?)(?=\s*Remetente|\s*Destinat|\s*Informa|\s*Volume|\s*CNPJ|\s*$)",
            txt,
            re.IGNORECASE,
        )
        if m_tom:
            tomador = m_tom.group(1).strip()

    if not remetente:
        m_rem = re.search(
            r"Remetente\s*[:\-]?\s*([^\n\r\|;]+?)(?=\s*Destinat|\s*End|\s*Cidade|\s*CNPJ|\s*$)",
            txt,
            re.IGNORECASE,
        )
        if m_rem:
            remetente = m_rem.group(1).strip()

    if not destinatario:
        m_dest = re.search(
            r"Destinat[aá]rio\s*[:\-]?\s*([^\n\r\|;]+?)(?=\s*End|\s*Cidade|\s*CNPJ|\s*$)",
            txt,
            re.IGNORECASE,
        )
        if m_dest:
            destinatario = m_dest.group(1).strip()

    return tomador, remetente, destinatario, cnpjs


def _detectar_rotulo_controle_fraction(form: Any, controle: Any) -> str:
    controle_id = controle.get("id")
    if controle_id:
        label = form.find("label", attrs={"for": controle_id})
        if label:
            return label.get_text(" ", strip=True)

    label = controle.find_parent("label")
    if label:
        return label.get_text(" ", strip=True)

    for proximo in controle.next_siblings:
        if (
            getattr(proximo, "name", None) == "input"
            and str(proximo.get("type", "")).lower() == "radio"
        ):
            break
        if hasattr(proximo, "get_text"):
            rotulo = proximo.get_text(" ", strip=True)
        else:
            rotulo = str(proximo).strip()
        if rotulo:
            return rotulo

    # Procura em células vizinhas de tabelas (ex: <td>CTE</td><td><input ...></td>)
    parent_td = controle.find_parent(["td", "th"])
    if parent_td:
        prev_td = parent_td.find_previous_sibling(["td", "th"])
        if prev_td:
            rotulo = prev_td.get_text(" ", strip=True)
            if rotulo:
                return rotulo
    return ""


def _preparar_formulario_fraction(form: Any, page_url: str, cte_code: str):
    controles = form.find_all(["input", "textarea", "select", "button"])
    if not controles:
        return None

    # MODO 1: Formulário "Consulta" / "Consulta Geral" (Imagem 1)
    # Tem campo específico com rótulo/nome/id de 'CTE' / 'Conhecimento'
    campo_cte_direto = None
    for controle in controles:
        if controle.name == "input" and str(controle.get("type", "text")).lower() in (
            "text",
            "search",
            "",
        ):
            rotulo = _detectar_rotulo_controle_fraction(form, controle).lower()
            nome = str(controle.get("name", "")).lower()
            cid = str(controle.get("id", "")).lower()
            if (
                re.search(r"^\s*cte\b|\bcte\s*$|conhecimento|nrcte|numcte", rotulo)
                or re.search(r"\bcte\b|conhecimento|nrcte|numcte", nome)
                or re.search(r"\bcte\b|conhecimento|nrcte|numcte", cid)
            ):
                campo_cte_direto = controle
                break

    # MODO 2: Formulário "Procurar" (Imagem 2)
    # Tem campo genérico "Código:" (textarea ou input) e opções de rádio (Conhecimento / Remessa / Sem filtro)
    campo_codigo_generico = None
    if campo_cte_direto is None:
        for controle in controles:
            if controle.name in ("textarea", "input") and str(
                controle.get("type", "text")
            ).lower() in ("text", "textarea", ""):
                rotulo = _detectar_rotulo_controle_fraction(form, controle).lower()
                nome = str(controle.get("name", "")).lower()
                cid = str(controle.get("id", "")).lower()
                if (
                    re.search(r"c[oó]d|codigo", rotulo)
                    or re.search(r"c[oó]d|codigo", nome)
                    or re.search(r"c[oó]d|codigo", cid)
                ):
                    campo_codigo_generico = controle
                    break
        if campo_codigo_generico is None:
            campo_codigo_generico = next(
                (c for c in controles if c.name == "textarea" and c.get("name")), None
            )

    # Se não identificou nem campo direto de CTE nem campo de Código, formulário não é de busca de CTe
    if campo_cte_direto is None and campo_codigo_generico is None:
        return None

    # Se houver botões de rádio (como na Imagem 2), seleciona o melhor filtro: Conhecimento > ID da remessa > Sem filtro
    radios = [
        c
        for c in controles
        if c.name == "input" and str(c.get("type", "")).lower() == "radio"
    ]
    radio_escolhido = None
    if radios:
        # 1. Conhecimento (CTe)
        for r in radios:
            rot = _detectar_rotulo_controle_fraction(form, r).lower()
            val = str(r.get("value", "")).lower()
            if re.search(r"conhec", rot) or re.search(r"conhec", val):
                radio_escolhido = r
                break
        # 2. ID da remessa (Remessa)
        if radio_escolhido is None:
            for r in radios:
                rot = _detectar_rotulo_controle_fraction(form, r).lower()
                val = str(r.get("value", "")).lower()
                if re.search(r"remessa", rot) or re.search(r"remessa", val):
                    radio_escolhido = r
                    break
        # 3. Sem filtro
        if radio_escolhido is None:
            for r in radios:
                rot = _detectar_rotulo_controle_fraction(form, r).lower()
                val = str(r.get("value", "")).lower()
                if re.search(r"sem filtro|filtro", rot) or re.search(
                    r"sem_filtro", val
                ):
                    radio_escolhido = r
                    break
        if radio_escolhido is None:
            radio_escolhido = radios[0]

    select_conhecimento = None
    if not radios:
        for select in (c for c in controles if c.name == "select" and c.get("name")):
            opcao = next(
                (
                    op
                    for op in select.find_all("option")
                    if re.search(
                        r"conhec|remessa", op.get_text(" ", strip=True), re.IGNORECASE
                    )
                ),
                None,
            )
            if opcao is not None:
                select_conhecimento = (select, opcao)
                break

    # Monta a lista de campos para envio (payload)
    campos = []
    data_inicio_expandida = (datetime.now() - timedelta(days=90)).strftime("%d/%m/%Y")
    data_fim_hoje = (datetime.now() + timedelta(days=1)).strftime("%d/%m/%Y")

    for controle in controles:
        nome = controle.get("name")
        if not nome:
            continue
        tipo = str(controle.get("type", "")).lower()
        rotulo = _detectar_rotulo_controle_fraction(form, controle).lower()

        if controle is campo_cte_direto or controle is campo_codigo_generico:
            campos.append((nome, cte_code))
        elif radios and controle is radio_escolhido:
            campos.append((nome, str(controle.get("value", "on"))))
        elif tipo == "radio":
            # Ignora outros botões de rádio do mesmo grupo
            continue
        elif select_conhecimento and controle is select_conhecimento[0]:
            campos.append((nome, str(select_conhecimento[1].get("value", ""))))
        elif re.search(
            r"data\s*de\s*in[ií]cio|dataini|dtini|inicio", rotulo + " " + nome
        ):
            # No form Consulta (Imagem 1), a data vem com hoje. Expande para 90 dias atrás para não perder o CTE!
            campos.append((nome, data_inicio_expandida))
        elif re.search(
            r"data\s*de\s*t[eé]rmino|datafim|dtfim|termino", rotulo + " " + nome
        ):
            campos.append((nome, data_fim_hoje))
        elif tipo in ("hidden", "submit", "button"):
            val = str(controle.get("value", ""))
            # Se for botão, não envia ações de cancelamento ou saída
            if tipo in ("submit", "button"):  # noqa: SIM102
                if re.search(
                    r"cancel|voltar|limpar|sair", nome + " " + val, re.IGNORECASE
                ):
                    continue
            campos.append((nome, val))
        elif tipo == "checkbox" and controle.has_attr("checked"):
            campos.append((nome, str(controle.get("value", "on"))))
        elif controle.name == "select":
            selecionadas = controle.find_all("option", selected=True)
            if selecionadas:
                campos.extend(
                    (nome, str(op.get("value", op.get_text(strip=True))))
                    for op in selecionadas
                )
        elif controle.name == "textarea":
            campos.append((nome, controle.get_text()))
        elif controle.name == "input" and tipo in ("text", "search"):
            campos.append((nome, str(controle.get("value", ""))))

    action = urljoin(page_url, str(form.get("action") or page_url))
    method = str(form.get("method", "get")).lower()
    return action, method, campos


def chave_nfe_valida(chave: str) -> bool:
    chave_limpa = re.sub(r"\D", "", str(chave or ""))
    if len(chave_limpa) != 44:
        return False

    soma = 0
    peso = 2
    for digito in reversed(chave_limpa[:43]):
        soma += int(digito) * peso
        peso = 2 if peso == 9 else peso + 1

    digito_verificador = 11 - (soma % 11)
    if digito_verificador >= 10:
        digito_verificador = 0
    return digito_verificador == int(chave_limpa[-1])


def extrair_chaves_nfe_pdf(texto_pdf: str, pdf_bytes: bytes | None = None) -> list[str]:
    textos = [str(texto_pdf or "")]
    if pdf_bytes:
        try:
            reader = pypdf.PdfReader(io.BytesIO(pdf_bytes))
            textos.append("\n".join(page.extract_text() or "" for page in reader.pages))
        except Exception as e:  # noqa: BLE001
            print(f"[Aviso] Falha ao extrair chave NF-e com pypdf: {e}")

    chaves = []
    for texto in textos:
        for match in re.finditer(r"(?<!\d)(?:\d[\s.-]*){44}(?!\d)", texto):
            chave = re.sub(r"\D", "", match.group(0))
            if chave_nfe_valida(chave) and chave not in chaves:
                chaves.append(chave)
    return chaves


def validar_chaves_ap(pares_documento: list, chaves_nfe: set[str] | dict) -> str:
    chaves_guia = {
        re.sub(r"\D", "", str(chave or ""))
        for chave, _ in pares_documento
        if chave and chave != "Sem Arquivo Válido" and chave_nfe_valida(str(chave))
    }
    if not chaves_guia:
        return "INCOMPLETO: Chave da guia AP não localizada"

    chaves_nfe_validas = {
        re.sub(r"\D", "", str(chave or ""))
        for chave in chaves_nfe
        if chave_nfe_valida(str(chave))
    }
    if not chaves_nfe_validas:
        return "INCOMPLETO: Chave da NF-e não localizada"
    if chaves_guia.issubset(chaves_nfe_validas):
        return "OK"
    return "INCOMPLETO: Chave da guia diverge da NF-e"


@registrar_execucao("Mesclagem de PDFs")
def mesclar_pdfs(pdf_bytes_list: list[bytes]) -> bytes:  # noqa: F811
    writer = pypdf.PdfWriter()
    for idx, b in enumerate(pdf_bytes_list):
        try:
            reader = pypdf.PdfReader(io.BytesIO(b))
            for page in reader.pages:
                writer.add_page(page)
        except Exception as e:  # noqa: BLE001
            print(f"[Aviso] Falha ao ler bloco PDF #{idx} para mesclagem: {e}")
    out = io.BytesIO()
    writer.write(out)
    return out.getvalue()


def e_dar_documento(texto_pdf: str) -> bool:
    txt_upper = texto_pdf.upper()

    # 1. Palavras-chave inconfundíveis de Guias (DARE/DAR)
    if any(
        k in txt_upper
        for k in [
            "DOCUMENTO DE ARRECADA",
            "1ª VIA - BANCO",
            "2ª VIA - CONTRIBUINTE",
            "NÚMERO DO DAR",
            "TOTAL DO DAR",
            "T.DAR",
            "TDAR",
            "DAEMS",
            "DARE",
            "DAR/AL",
            "DAR MODELO 1",
            "ESTADO DO AMAP",
        ]
    ):
        return True

    # 2. Busca o código de barras respeitando o texto (Sem apagar as letras!)
    # Isto impede que o número do Termo se junte com a Chave da Nota gerando guias falsas.
    return bool(
        re.search(
            r"\b8\d{10}[\s\.-]*\d[\s\.-]*\d{11}[\s\.-]*\d[\s\.-]*\d{11}[\s\.-]*\d[\s\.-]*\d{11}[\s\.-]*\d\b|\b8\d{43,47}\b",
            texto_pdf,
        )
    )


def e_termo_documento(texto_pdf: str) -> bool:
    txt_upper = texto_pdf.upper()
    # Uma guia NUNCA é um termo, mesmo que a palavra Termo esteja impressa nela
    if e_dar_documento(texto_pdf):
        return False

    return bool(
        any(
            k in txt_upper
            for k in [
                "TERMO DE AVERIGUA",
                "AVERIGUAÇÃO",
                "TERMO DE APREENSÃO",
                "TERMO DE VERIFICAÇÃO FISCAL",
            ]
        )
    )


def e_nota_fiscal(texto_pdf: str, nome_anexo: str) -> bool:
    txt_upper = texto_pdf.upper()
    nome_lower = nome_anexo.lower()

    if e_termo_documento(texto_pdf) or "termo" in nome_lower:
        return False
    if e_dar_documento(texto_pdf) or "dar" in nome_lower:
        return False

    if any(
        k in txt_upper
        for k in ["DANFE", "DOCUMENTO AUXILIAR DA NOTA FISCAL", "RECEBEMOS DE"]
    ):
        return True
    if "NOTA FISCAL" in txt_upper and "SEFAZ" not in txt_upper:
        return True
    return bool(
        "download" in nome_lower
        and "CHAVE DE ACESSO" in txt_upper
        and "PROTOCOLO DE AUTORIZAÇÃO" in txt_upper
    )


def linha_digitavel_para_codigo_barras(linha: str) -> str:
    apenas_numeros = re.sub(r"\D", "", str(linha or ""))
    if len(apenas_numeros) == 48:
        return (
            apenas_numeros[0:11]
            + apenas_numeros[12:23]
            + apenas_numeros[24:35]
            + apenas_numeros[36:47]
        )
    elif len(apenas_numeros) == 47:
        return (
            apenas_numeros[0:3]
            + apenas_numeros[3:4]
            + apenas_numeros[32:33]
            + apenas_numeros[33:47]
            + apenas_numeros[4:9]
            + apenas_numeros[10:20]
            + apenas_numeros[21:31]
        )
    elif len(apenas_numeros) == 44:
        return apenas_numeros
    return apenas_numeros if apenas_numeros else "Sem Código"


def extrair_codigo_barras_pdf(texto_pdf: str) -> tuple[str, str]:
    if not e_dar_documento(texto_pdf):
        return "Sem Código", "Sem Código"

    match_febraban = re.search(
        r"\b(8\d{10}[\s\.-]*\d[\s\.-]*\d{11}[\s\.-]*\d[\s\.-]*\d{11}[\s\.-]*\d[\s\.-]*\d{11}[\s\.-]*\d)\b",
        texto_pdf,
    )
    if match_febraban:
        bruto = " ".join(match_febraban.group(1).split())
        digits = re.sub(r"\D", "", bruto)
        if len(digits) == 48:
            barras44 = linha_digitavel_para_codigo_barras(digits)
            return bruto, barras44

    match_boleto = re.search(
        r"\b(\d{5}[\.-]?\d{5}\s*\d{5}[\.-]?\d{6}\s*\d{5}[\.-]?\d{6}\s*\d\s*\d{14})\b",
        texto_pdf,
    )
    if match_boleto:
        bruto = " ".join(match_boleto.group(1).split())
        digits = re.sub(r"\D", "", bruto)
        if len(digits) == 47:
            barras44 = linha_digitavel_para_codigo_barras(digits)
            return bruto, barras44

    txt_nums = re.sub(r"\D", "", texto_pdf)
    m8_48 = re.search(r"(8\d{47})", txt_nums)
    if m8_48:
        nums48 = m8_48.group(1)
        barras44 = linha_digitavel_para_codigo_barras(nums48)
        return nums48, barras44

    m8_44 = re.search(r"(8\d{43})", txt_nums)
    if m8_44:
        nums44 = m8_44.group(1)
        return nums44, nums44

    return "Sem Código", "Sem Código"


def preparar_codigos_barras_ap(
    codigo_original: str, codigo_barras: str
) -> tuple[str, str]:
    cod_orig_str = " ".join(str(codigo_original or "").strip().split())
    original_digitos = re.sub(r"\D", "", cod_orig_str)

    # 1. CÓDIGO BARRAS ORIGINAL: Preserva a formatação original com traços e espaços como impresso na guia.
    # Caso venha apenas com os dígitos numéricos (48 dígitos), formata no padrão Febraban com traços e espaços.
    if len(original_digitos) == 48:
        if "-" in cod_orig_str or " " in cod_orig_str:
            codigo_original = cod_orig_str
        else:
            codigo_original = f"{original_digitos[0:11]}-{original_digitos[11]} {original_digitos[12:23]}-{original_digitos[23]} {original_digitos[24:35]}-{original_digitos[35]} {original_digitos[36:47]}-{original_digitos[47]}"
    elif cod_orig_str:
        codigo_original = cod_orig_str

    # 2. CÓDIGO BARRAS (44 dígitos Febraban): Para o Amapá, mantém os 44 dígitos completos (iniciando com 85620000006).
    barras_digitos = re.sub(r"\D", "", str(codigo_barras or ""))
    if len(barras_digitos) == 48 and barras_digitos.startswith("8"):
        codigo_barras = linha_digitavel_para_codigo_barras(barras_digitos)
    elif len(barras_digitos) == 44:
        codigo_barras = barras_digitos
    elif len(original_digitos) == 48 and original_digitos.startswith("8"):
        codigo_barras = linha_digitavel_para_codigo_barras(original_digitos)
    elif len(original_digitos) == 44:
        codigo_barras = original_digitos

    return codigo_original, codigo_barras


def extrair_vencimento_e_valor_pdf(texto_pdf: str) -> tuple[str, str]:
    vencimento, valor = "Não informado", "Não informado"

    if not e_dar_documento(texto_pdf):
        return vencimento, valor

    m_nr = re.search(
        r"NAO\s*RECEBER\s*APOS\s*[:|-]?\s*(\d{2}/\d{2}/\d{4})", texto_pdf, re.IGNORECASE
    )
    if m_nr:
        vencimento = m_nr.group(1).strip()
    else:
        match_venc = re.search(
            r"(?:07\s*-\s*Data\s+de\s+Vencimento|Vencimento\s+do\s+DAR|Vencimento\s*[:|]?|Data\s+de\s+vencimento\s+da\s+obriga[çc][ãa]o).{0,50}?\b(\d{2}/\d{2}/\d{4})\b",
            texto_pdf,
            re.IGNORECASE | re.DOTALL,
        )
        if match_venc:
            vencimento = match_venc.group(1)
        else:
            datas = re.findall(r"\b(\d{2}/\d{2}/\d{4})\b", texto_pdf)
            if datas:
                vencimento = datas[0]

    vencimento = padronizar_data_ddmmyyyy(vencimento)

    m_val = re.search(
        r"(?:14\s*-\s*TOTAL\s+A\s+RECOLHER|10\s*-\s*TOTAL|\(=\)\s*Valor\s*Total|Valor\s*Total\s*\(R\$\)|Total\s*do\s*DAR\s*\(R\$\)|Total\s*do\s*DAR).{0,50}?(?:R\$\s*)?(\d{1,3}(?:\.\d{3})*,\d{2})",
        texto_pdf,
        re.IGNORECASE | re.DOTALL,
    )
    if m_val:
        valor = m_val.group(1)
    else:
        m_dar_val = re.search(
            r"Número\s+do\s+DAR.{0,30}?\b(\d{1,3}(?:\.\d{3})*,\d{2})\b",
            texto_pdf,
            re.IGNORECASE | re.DOTALL,
        )
        if m_dar_val:
            valor = m_dar_val.group(1)
        else:
            vals = re.findall(r"\b(\d{1,3}(?:\.\d{3})*,\d{2})\b", texto_pdf)
            if vals:
                valor = vals[-1]

    return vencimento, valor


def _marcar_status_guia_ap_processada(status: str) -> str:
    if status == "OK":
        return "GUIA JÁ PROCESSADA"
    if "GUIA JÁ PROCESSADA" in status:
        return status
    return f"{status} | GUIA JÁ PROCESSADA"


def extrair_numero_termo_pdf(texto_pdf: str, nome_anexo: str) -> str | None:
    # Removemos exigências de ordem e deixamos as expressões o mais curtas e abrangentes possíveis.
    patterns = [
        # Padrões mais flexíveis e diretos
        r"(?:TERMO\s*DE\s*AVERIGUA[ÇC][ÃA]O|TERMO\s*DE\s*APREENSÃO)\s*[-:]?\s*N?[º°o\.]*\s*(\d{6,15})",
        r"18\s*-\s*N\.?\s*Controle\s*[\n\r:]*\s*(\d{6,15})",
        r"N\.?\s*Controle\s*[\n\r:]*\s*(\d{8,15})",
        r"POSTO\s*:?\s*\d+\s+TA\s*:?\s*(\d{6,15})",
        # Padrões curtos para apanhar as Guias (DARE)
        r"(?:TERMO|TDAR|T\.DAR)\s*[:=-]?\s*(\d{6,15})\b",
        r"(?:Número\s*do\s*Documento|N[º°o\.]*\s*Doc\.?|Documento|Referência|Ref\.?|Auto\s*de\s*Infra[çc][ãa]o)\s*[:=-]?\s*(\d{6,15})\b",
        r"(\d{6,12})\s*N[º°o\.]*\s*:",
        r"N[º°o\.]*\s*:\s*(\d{6,12})\b",
    ]

    for pat in patterns:
        m = re.search(pat, texto_pdf, re.IGNORECASE)
        if m:
            return m.group(1).strip()

    # Se, mesmo com tudo isso, a guia não tiver o número legível,
    # deixamos um fallback de segurança ativado para ler o nome do ficheiro apenas se ele tiver "DAR" ou "TERMO" no nome.
    match_fallback = re.search(
        r"(?:tdar|termo|dar|guia)\D*?(\d{6,15})", nome_anexo, re.IGNORECASE
    )
    if match_fallback:
        return match_fallback.group(1).strip()

    return None


@registrar_execucao("Extração de texto do PDF")
def extrair_texto_pdf(pdf_bytes: bytes) -> tuple[str, str]:
    return extrair_texto_pdf_servico(pdf_bytes)

    if HAS_PDFPLUMBER:
        try:
            with pdfplumber.open(io.BytesIO(pdf_bytes)) as pdf:
                for page in pdf.pages:
                    extracted = page.extract_text(layout=True)
                    if extracted:
                        texto += extracted + "\n"  # noqa: F821
            texto = texto.strip()
        except Exception as e:  # noqa: BLE001
            print(f"[Aviso] pdfplumber falhou: {e}. Tentando pypdf...")

    if not texto:
        try:
            pdf_file = io.BytesIO(pdf_bytes)
            reader = pypdf.PdfReader(pdf_file)
            for page in reader.pages:
                extracted = page.extract_text()
                if extracted:
                    texto += extracted + "\n"
            texto = texto.strip()
        except Exception:  # noqa: BLE001, S110
            pass

    if not texto and HAS_OCR:
        try:
            images = convert_from_bytes(pdf_bytes)
            for img in images:
                extracted = pytesseract.image_to_string(img, lang="por")
                if extracted:
                    texto += extracted + "\n"
            texto = texto.strip()
        except Exception as e:  # noqa: BLE001
            print(f"[Aviso] Falha no OCR: {e}")

    if not texto:
        return "", "PDF sem texto extraível mesmo com OCR."

    return texto, "OK"


def sanitizar_celula_excel(val):
    val_str = str(val or "").strip()
    m = re.match(r'^=\s*"([^"]*)"$', val_str)
    if m:
        return m.group(1)
    return val_str


def e_linha_valida_ok(cabecalho: list, row: list) -> tuple[bool, str]:
    idx_status = (
        cabecalho.index("STATUS CONFERÊNCIA")
        if "STATUS CONFERÊNCIA" in cabecalho
        else -1
    )
    st = (
        str(row[idx_status]).strip()
        if (idx_status != -1 and idx_status < len(row))
        else "OK"
    )
    st_norm = st.upper()

    if (
        st_norm not in ("OK", "")
        and not st_norm.startswith("OK")
        and not st_norm.startswith("VALIDADO")
    ):
        return False, st

    maldados = [
        "sem código",
        "não localizado",
        "não informado",
        "sem arquivo válido",
        "sem número",
        "sem cte",
        "",
    ]

    coluna_codigo_barras = next(
        (
            nome
            for nome in cabecalho
            if "CÓDIGO BARRAS" in str(nome).upper()
            and "ORIGINAL" not in str(nome).upper()
        ),
        None,
    )
    colunas_verificar = [
        ("TERMO/CONTROLE", "Termo"),
        ("VENCIMENTO", "Vencimento"),
        ("VALOR (R$)", "Valor"),
    ]
    if coluna_codigo_barras:
        colunas_verificar.append((coluna_codigo_barras, "Código de Barras"))

    faltantes = []
    for col_nome, nome_exibicao in colunas_verificar:
        if col_nome in cabecalho:
            idx = cabecalho.index(col_nome)
            if idx < len(row):
                val = sanitizar_celula_excel(row[idx]).strip().lower()
                if val in maldados:
                    faltantes.append(nome_exibicao)

    if faltantes:
        motivo = f"INCOMPLETO: Sem {', '.join(faltantes)}"
        return False, motivo

    return True, "OK"


def e_registro_vencido(row_list: list, cabecalho: list) -> bool:
    hoje = datetime.now().date()
    idx_venc = cabecalho.index("VENCIMENTO") if "VENCIMENTO" in cabecalho else -1

    if idx_venc != -1 and idx_venc < len(row_list):
        venc_str = str(row_list[idx_venc] or "")
        if venc_str and venc_str != "Não informado":
            for part in venc_str.split(","):
                p_clean = sanitizar_celula_excel(part).strip()
                try:
                    dt = datetime.strptime(p_clean, "%d/%m/%Y").date()
                    if dt < hoje:
                        return True
                except Exception:  # noqa: BLE001, S110
                    pass
    return False


@registrar_execucao("Gravação da planilha")
def salvar_planilha_multisheets(
    caminho_arquivo: str,
    cabecalho: list,
    linhas_totais: list,
    gerenciador_dedicados=None,
) -> str:
    idx_status = (
        cabecalho.index("STATUS CONFERÊNCIA")
        if "STATUS CONFERÊNCIA" in cabecalho
        else -1
    )
    idx_tomador = (
        cabecalho.index("TOMADOR")
        if "TOMADOR" in cabecalho
        else (cabecalho.index("TOMADORES") if "TOMADORES" in cabecalho else -1)
    )

    linhas_ok, linhas_faltando = [], []
    linhas_dedicados, linhas_nao_dedicados = [], []

    for row in linhas_totais:
        row_list = list(row)
        is_ok, motivo = e_linha_valida_ok(cabecalho, row_list)
        if is_ok:
            linhas_ok.append(row_list)
        else:
            if (
                idx_status != -1
                and idx_status < len(row_list)
                and row_list[idx_status] == "OK"
            ):
                row_list[idx_status] = motivo
            linhas_faltando.append(row_list)

        tom_val = (
            str(row_list[idx_tomador])
            if (idx_tomador != -1 and idx_tomador < len(row_list))
            else ""
        )
        if gerenciador_dedicados and gerenciador_dedicados.e_dedicado(tom_val):
            linhas_dedicados.append(row_list)
        else:
            linhas_nao_dedicados.append(row_list)

    base_path, ext = os.path.splitext(caminho_arquivo)

    if HAS_OPENPYXL:
        caminho_xlsx = (
            base_path + ".xlsx" if ext.lower() != ".xlsx" else caminho_arquivo
        )
        try:
            wb = openpyxl.Workbook()
            fill_destaque = PatternFill(
                start_color="FDE9D9", end_color="FDE9D9", fill_type="solid"
            )
            font_destaque = Font(color="7A4B1F", bold=False)

            def aplicar_destaque_vencimento(ws, row_idx, row_list):
                colunas_destaque = []
                for idx, titulo in enumerate(cabecalho):
                    titulo_norm = str(titulo).upper()
                    if (
                        "VENCIMENTO" in titulo_norm
                        or "VALOR (R$)" in titulo_norm
                        or "STATUS CONFERÊNCIA" in titulo_norm
                    ):
                        colunas_destaque.append(idx + 1)

                if not colunas_destaque:
                    return

                for col_idx in colunas_destaque:
                    celula = ws.cell(row=row_idx, column=col_idx)
                    celula.fill = fill_destaque
                    celula.font = font_destaque

            def adicionar_e_formatar_aba(ws, linhas_dados):
                col_extra = "CPF/CNPJ GUIA EM R/S/U/V"
                ja_tem_col_extra = col_extra in cabecalho
                cabecalho_export = (
                    list(cabecalho)
                    if ja_tem_col_extra
                    else list(cabecalho) + [col_extra]
                )
                ws.append([sanitizar_celula_excel(c) for c in cabecalho_export])
                for indice, titulo in enumerate(cabecalho_export, start=1):
                    titulo_normalizado = str(titulo).upper()
                    if "CÓDIGO BARRAS ORIGINAL" in titulo_normalizado:
                        ws.column_dimensions[
                            ws.cell(row=1, column=indice).column_letter
                        ].width = 56
                    elif (
                        "CÓDIGO BARRAS" in titulo_normalizado
                        and "ORIGINAL" not in titulo_normalizado
                    ):
                        ws.column_dimensions[
                            ws.cell(row=1, column=indice).column_letter
                        ].width = 50

                col_guia_idx = next(
                    (
                        idx + 1
                        for idx, col in enumerate(cabecalho)
                        if col == "CPF/CNPJ DA GUIA"
                    ),
                    None,
                )
                col_r_idx = next(
                    (
                        idx + 1
                        for idx, col in enumerate(cabecalho)
                        if col == "EMITENTE - CPF/CNPJ"
                    ),
                    None,
                )
                col_s_idx = next(
                    (
                        idx + 1
                        for idx, col in enumerate(cabecalho)
                        if col == "EMITENTE - IE"
                    ),
                    None,
                )
                col_u_idx = next(
                    (
                        idx + 1
                        for idx, col in enumerate(cabecalho)
                        if col == "DESTINATÁRIO - CPF/CNPJ"
                    ),
                    None,
                )
                col_v_idx = next(
                    (
                        idx + 1
                        for idx, col in enumerate(cabecalho)
                        if col == "DESTINATÁRIO - IE"
                    ),
                    None,
                )

                for r_idx, r in enumerate(linhas_dados, start=2):
                    row_vals = [sanitizar_celula_excel(c) for c in r]
                    if not ja_tem_col_extra:
                        if col_guia_idx is not None and get_column_letter:
                            letra_guia = get_column_letter(col_guia_idx)
                            letras_alvo = [
                                get_column_letter(c)
                                for c in [col_r_idx, col_s_idx, col_u_idx, col_v_idx]
                                if c is not None
                            ]
                            if letras_alvo:
                                comparacoes = ",".join(
                                    f"${letra_guia}{r_idx}=${alvo}{r_idx}"
                                    for alvo in letras_alvo
                                )
                                formula = f'=IF(OR({comparacoes}),"SIM","NÃO")'
                            else:
                                formula = f'=IF(OR($C{r_idx}=$R{r_idx},$C{r_idx}=$S{r_idx},$C{r_idx}=$U{r_idx},$C{r_idx}=$V{r_idx}),"SIM","NÃO")'
                            row_vals.append(formula)
                        elif "CPF/CNPJ DA GUIA" in cabecalho:
                            formula = f'=IF(OR($C{r_idx}=$R{r_idx},$C{r_idx}=$S{r_idx},$C{r_idx}=$U{r_idx},$C{r_idx}=$V{r_idx}),"SIM","NÃO")'
                            row_vals.append(formula)
                        else:
                            row_vals.append("")
                    ws.append(row_vals)
                    if e_registro_vencido(r, cabecalho):
                        aplicar_destaque_vencimento(ws, r_idx, row_vals)

            # 1. Aba DOCUMENTOS_OK
            ws_ok = wb.active
            ws_ok.title = "DOCUMENTOS_OK"
            adicionar_e_formatar_aba(ws_ok, linhas_ok)

            # 2. Aba GERAL_TOTAL
            ws_geral_total = wb.create_sheet(title="LEITURA_GERAL_TOTAL")
            adicionar_e_formatar_aba(ws_geral_total, linhas_totais)

            # 3. Aba QUARENTENA
            ws_faltando = wb.create_sheet(title="QUARENTENA")
            adicionar_e_formatar_aba(ws_faltando, linhas_faltando)

            # 4. Aba CLIENTES_DEDICADOS
            ws_dedicados = wb.create_sheet(title="CLIENTES_DEDICADOS")
            adicionar_e_formatar_aba(ws_dedicados, linhas_dedicados)

            # 5. Aba CLIENTES_NAO_DEDICADOS
            ws_nao_dedicados = wb.create_sheet(title="CLIENTES_NAO_DEDICADOS")
            adicionar_e_formatar_aba(ws_nao_dedicados, linhas_nao_dedicados)

            wb.save(caminho_xlsx)
            return caminho_xlsx
        except Exception as e:  # noqa: BLE001
            print(f"[Erro Excel] Falha ao gravar .xlsx via openpyxl: {e}")

    caminho_csv_ok = base_path + "_DOCUMENTOS_OK.csv"
    caminho_csv_quarentena = base_path + "_QUARENTENA.csv"
    caminho_csv_dedicados = base_path + "_CLIENTES_DEDICADOS.csv"
    caminho_csv_nao_dedicados = base_path + "_CLIENTES_NAO_DEDICADOS.csv"

    if linhas_ok:
        with open(caminho_csv_ok, mode="w", newline="", encoding="utf-8-sig") as f_out:
            escritor = csv.writer(f_out, delimiter=";")
            escritor.writerow(cabecalho)
            for r in linhas_ok:
                escritor.writerow(r)

    if linhas_faltando:
        with open(
            caminho_csv_quarentena, mode="w", newline="", encoding="utf-8-sig"
        ) as f_out:
            escritor = csv.writer(f_out, delimiter=";")
            escritor.writerow(cabecalho)
            for r in linhas_faltando:
                escritor.writerow(r)

    if linhas_dedicados:
        with open(
            caminho_csv_dedicados, mode="w", newline="", encoding="utf-8-sig"
        ) as f_out:
            escritor = csv.writer(f_out, delimiter=";")
            escritor.writerow(cabecalho)
            for r in linhas_dedicados:
                escritor.writerow(r)

    if linhas_nao_dedicados:
        with open(
            caminho_csv_nao_dedicados, mode="w", newline="", encoding="utf-8-sig"
        ) as f_out:
            escritor = csv.writer(f_out, delimiter=";")
            escritor.writerow(cabecalho)
            for r in linhas_nao_dedicados:
                escritor.writerow(r)

    return f"{caminho_csv_ok} / {caminho_csv_quarentena}"


# ==========================================
# GERENCIADOR DE LAYOUTS COM ÂNCORAS VISUAIS
# ==========================================
ARQUIVO_LAYOUTS = "layouts_custom.json"

LAYOUTS_PADRAO_SISTEMA = {
    "SEFAZ_ALAGOAS": {
        "uf": "AL",
        "palavras_chave": ["ALAGOAS", "SEFAZ"],
        "regex_termo": r"(?:TERMO\s*DE\s*AVERIGUAÇÃO|AVERIGUAÇÃO|N[º°o\.]*)\s*[-:]?\s*(\d{6,12})",
        "regex_vencimento": r"(?:Vencimento\s+do\s+DAR|Vencimento)[\s\n\r]*[:|]?[\s\n\r]*(\d{2}/\d{2}/\d{4})",
        "regex_valor": r"(?:Valor\s+Total\s*\(R\$\)|Valor\s+Total)[\s\n\r]*[:|]?[\s\n\r]*(?:R\$\s*)?(\d{1,3}(?:\.\d{3})*,\d{2})",
        "regex_cod_barras": r"(\b8\d{10}[\s\.-]*\d[\s\.-]*\d{11}[\s\.-]*\d[\s\.-]*\d{11}[\s\.-]*\d[\s\.-]*\d{11}[\s\.-]*\d\b|\b8\d{43,47}\b)",
        "regex_cte": r"(?:CTE|Conhecimento|Remessa)\s*[:=-]?\s*([\d/]+)",
        "regex_num_arquivo": r"(?:DANFE|CT-E|NF-E|CTE|NFE|DOCUMENTO)\s+(\d+)",
        "regex_chave_arquivo": r"(?:Chave\s*de\s*Acesso)?\s*(\b\d{44}\b)",
    },
    "SEFAZ_AMAPA": {
        "uf": "AP",
        "palavras_chave": ["AMAPÁ", "AMAPA", "GOVERNO DO ESTADO DO AMAPÁ"],
        "regex_termo": r"(?:18\s*-\s*N\.?\s*Controle|N\.?\s*Controle|Nº?\s*CONTROLE)\s*[\n\r:]*\s*(\d{6,15})",
        "regex_vencimento": r"(?:NAO\s*RECEBER\s*APOS|07\s*-\s*Data\s+de\s+Vencimento)[\s\n\r:]*(\d{2}/\d{2}/\d{4})",
        "regex_valor": r"(?:14\s*-\s*TOTAL\s+A\s+RECOLHER|10\s*-\s*Valor\s+Principal)[\s\n\r:]*(?:R\$\s*)?(\d{1,3}(?:\.\d{3})*,\d{2})",
        "regex_cod_barras": r"(\b8\d{10}[\s\.-]*\d[\s\.-]*\d{11}[\s\.-]*\d[\s\.-]*\d{11}[\s\.-]*\d[\s\.-]*\d{11}[\s\.-]*\d\b|\b8\d{43,47}\b)",
        "regex_cte": r"(?:Remessa|CTE|Conhecimento|Minuta)\s*[:=-]?\s*([\d/]+)",
        "regex_num_arquivo": r"(?:NF-e|DANFE|N[º°o\.]*)\s*[:=-]?\s*(\d{3}\.\d{3}\.\d{3}|\d+)",
        "regex_chave_arquivo": r"(?:Chave\s*de\s*Acesso)?\s*:?[\s\n\r]*(\b\d{44}\b)",
    },
    "SEFAZ_ACRE": {
        "uf": "AC",
        "palavras_chave": ["GOVERNO DO ESTADO DO ACRE", "NOTIFICAÇÃO DO ICMS"],
        "regex_termo": r"(?:Número|Nº|Nº\s*Doc)[\s\n\r:]*([\d\.]+)",
        "regex_vencimento": r"(?:Válido\s+para\s+pagamento\s+até|Data\s+de\s+Vencimento)[\s\n\r:]*(\d{2}/\d{2}/\d{2,4})",
        "regex_valor": r"(?:Total\s+do\s+ICMS\s+a\s+recolher|Total)[\s\n\r:]*(?:R\$\s*)?(\d{1,3}(?:\.\d{3})*,\d{2})",
        "regex_cod_barras": r"(\b8\d{10}[\s\.-]*\d[\s\.-]*\d{11}[\s\.-]*\d[\s\.-]*\d{11}[\s\.-]*\d[\s\.-]*\d{11}[\s\.-]*\d\b|\b8\d{43,47}\b)",
        "regex_cte": r"(?:CTE|Conhecimento|Remessa)\s*[:=-]?\s*([\d/]+)",
        "regex_num_arquivo": r"(?:Processo|Nº\s*Doc)\s*[:=-]?\s*(\d+)",
        "regex_chave_arquivo": r"(\b\d{44}\b)",
    },
    "SEFAZ_MS": {
        "uf": "MS",
        "palavras_chave": ["MATO GROSSO DO SUL", "DAEMS"],
        "regex_termo": r"(?:TERMO\s*DE\s*(?:APREENSÃO|VERIFICAÇÃO\s*FISCAL)\s*N[º°o\.]*|POSTO\s*:?\s*\d+\s+(?:TA|TVF)\s*:?)\s*(\d{6,15})",
        "regex_vencimento": r"(?:NÃO\s*RECEBER\s*APÓS|02\s*-\s*VENCIMENTO)[\s\n\r:]*(\d{2}/\d{2}/\d{4})",
        "regex_valor": r"(?:10\s*-\s*TOTAL|TOTAL\s*A\s*RECOLHER|TOTAL)[\s\n\r:]*(?:R\$\s*)?(\d{1,3}(?:\.\d{3})*,\d{2})",
        "regex_cod_barras": r"(\b8\d{10}[\s\.-]*\d[\s\.-]*\d{11}[\s\.-]*\d[\s\.-]*\d{11}[\s\.-]*\d[\s\.-]*\d{11}[\s\.-]*\d\b|\b8\d{43,47}\b)",
        "regex_cte": r"(?:CTE|Conhecimento|Remessa)\s*[:=-]?\s*([\d/]+)",
        "regex_num_arquivo": r"NOTAS\s*FISCAIS\s*[:|-]?[\s\n\r]*(\d{1,9})",
        "regex_chave_arquivo": r"(\b\d{44}\b)",
        "bbox_valor": [0.70, 0.15, 0.99, 0.35],
        "bbox_vencimento": [0.50, 0.10, 0.99, 0.25],
    },
    "PADRAO_GERAL": {
        "uf": "GERAL",
        "palavras_chave": ["DOCUMENTO", "ARRECADAÇÃO"],
        "regex_termo": r"(?:TERMO|TDAR|T\.DAR|CONTROLE)\s*[:=-]?\s*(\d{6,12})",
        "regex_vencimento": r"(?:Vencimento\s+do\s+DAR|Vencimento)\s*[:|]?\s*(\d{2}/\d{2}/\d{4})",
        "regex_valor": r"(?:Valor\s+Total\s*\(R\$\)|Valor\s+Total)\s*[:|]?\s*(?:R\$\s*)?(\d{1,3}(?:\.\d{3})*,\d{2})",
        "regex_cod_barras": r"(\b8\d{10}[\s\.-]*\d[\s\.-]*\d{11}[\s\.-]*\d[\s\.-]*\d{11}[\s\.-]*\d[\s\.-]*\d{11}[\s\.-]*\d\b|\b8\d{43,47}\b|\b\d{5}[\.-]?\d{5}\s*\d{5}[\.-]?\d{6}\s*\d{5}[\.-]?\d{6}\s*\d\s*\d{14}\b)",
        "regex_cte": r"(?:CTE|Conhecimento|Remessa)\s*[:=-]?\s*([\d/]+)",
        "regex_num_arquivo": r"(?:DANFE|NF-E|NFE|DOCUMENTO)\s*[:=-]?\s*(\d+)",
        "regex_chave_arquivo": r"(\b\d{44}\b)",
    },
}


class GerenciadorLayouts:
    def __init__(self):
        self.historico = []
        self.layouts = self.carregar_layouts()

    def validar_layout(self, nome: str, config: dict) -> list[str]:
        erros = []
        if not nome.strip():
            erros.append("Nome do layout vazio")
        if not config.get("uf", "").strip():
            erros.append("UF não informada")
        for chave in (
            "regex_termo",
            "regex_vencimento",
            "regex_valor",
            "regex_cod_barras",
            "regex_cte",
            "regex_num_arquivo",
            "regex_chave_arquivo",
        ):
            padrao = config.get(chave, "")
            if padrao:
                try:
                    re.compile(padrao)
                except re.error as erro:
                    erros.append(f"{chave}: {erro}")
        return erros

    def registrar_historico(self, acao: str, nome: str) -> None:
        self.historico.append(
            {
                "data": datetime.now().strftime("%d/%m/%Y %H:%M:%S"),
                "acao": acao,
                "layout": nome,
            }
        )
        self.historico = self.historico[-200:]

    def carregar_layouts(self) -> dict:
        layouts_carregados = {}
        if os.path.exists(ARQUIVO_LAYOUTS):
            try:
                with open(ARQUIVO_LAYOUTS, "r", encoding="utf-8") as f:
                    layouts_carregados = json.load(f)
                    if (
                        isinstance(layouts_carregados, dict)
                        and "_historico" in layouts_carregados
                    ):
                        self.historico = layouts_carregados.pop("_historico", [])
            except Exception as e:  # noqa: BLE001
                print(f"[Erro] Falha ao carregar layouts: {e}")

        houve_alteracao = False
        for nome_layout, config in LAYOUTS_PADRAO_SISTEMA.items():
            if nome_layout not in layouts_carregados:
                layouts_carregados[nome_layout] = config
                houve_alteracao = True

        self.layouts = layouts_carregados
        if houve_alteracao:
            self.salvar_layouts()

        return self.layouts

    def salvar_layouts(self):
        try:
            dados = dict(self.layouts)
            dados["_historico"] = self.historico
            with open(ARQUIVO_LAYOUTS, "w", encoding="utf-8") as f:
                json.dump(dados, f, ensure_ascii=False, indent=4)
        except Exception as e:  # noqa: BLE001
            print(f"[Erro] Falha ao salvar layouts: {e}")

    def restaurar_padrao(self, nome: str) -> bool:
        if nome not in LAYOUTS_PADRAO_SISTEMA:
            return False
        self.layouts[nome] = json.loads(json.dumps(LAYOUTS_PADRAO_SISTEMA[nome]))
        self.registrar_historico("RESTAURADO PADRÃO", nome)
        self.salvar_layouts()
        return True

    @registrar_execucao("Identificação e extração por layout")
    def identificar_e_extrair(
        self, texto_pdf: str, nome_anexo: str, pdf_bytes: bytes | None = None
    ) -> dict | None:
        txt_upper = texto_pdf.upper()

        layouts_ordenados = sorted(
            self.layouts.items(),
            key=lambda item: len(item[1].get("palavras_chave", [])),
            reverse=True,
        )

        for nome_layout, config in layouts_ordenados:
            p_chaves = config.get("palavras_chave", [])
            if p_chaves and not all(kw.upper() in txt_upper for kw in p_chaves):
                continue

            res = {
                "layout": nome_layout,
                "uf": config.get("uf", "GERAL"),
                "termo": None,
                "vencimento": "Não informado",
                "valor": "Não informado",
                "cod_barras_orig": "Sem Código",
                "cod_barras": "Sem Código",
                "cte": None,
                "num_arquivo": None,
                "chave_arquivo": None,
                "pares_documento": [],
            }

            def _safe_search(pat, alvo_texto):
                if not pat or not alvo_texto:
                    return None
                try:
                    return re.search(pat, alvo_texto, re.IGNORECASE)
                except re.error:
                    return None

            txt_venc_alvo = texto_pdf
            if pdf_bytes and config.get("bbox_vencimento"):
                txt_crop_venc = extrair_texto_por_caixa(
                    pdf_bytes, config.get("bbox_vencimento")
                )
                if txt_crop_venc:
                    txt_venc_alvo = txt_crop_venc

            txt_valor_alvo = texto_pdf
            if pdf_bytes and config.get("bbox_valor"):
                txt_crop_valor = extrair_texto_por_caixa(
                    pdf_bytes, config.get("bbox_valor")
                )
                if txt_crop_valor:
                    txt_valor_alvo = txt_crop_valor

            m = _safe_search(config.get("regex_termo"), texto_pdf)
            if m:
                res["termo"] = m.group(1 if m.groups() else 0).strip()

            m = _safe_search(config.get("regex_vencimento"), txt_venc_alvo)
            if m:
                res["vencimento"] = padronizar_data_ddmmyyyy(
                    m.group(1 if m.groups() else 0).strip()
                )

            m = _safe_search(config.get("regex_valor"), txt_valor_alvo)
            if m:
                res["valor"] = m.group(1 if m.groups() else 0).strip()

            m = _safe_search(config.get("regex_cod_barras"), texto_pdf)
            if m:
                bruto = m.group(1 if m.groups() else 0).strip()
                res["cod_barras_orig"] = bruto
                res["cod_barras"] = linha_digitavel_para_codigo_barras(bruto)

            m = _safe_search(config.get("regex_cte"), texto_pdf)
            if m:
                res["cte"] = m.group(1 if m.groups() else 0).strip()

            m = _safe_search(config.get("regex_num_arquivo"), texto_pdf)
            if m:
                raw_num = m.group(1 if m.groups() else 0).strip()
                res["num_arquivo"] = formatar_numero_arquivo(raw_num)

            # Para AL, o campo "NÚMERO ARQUIVO" deve priorizar os números das NF-es
            # encontradas no mesmo termo, na ordem de leitura. Só usamos o TERMO como
            # fallback quando não houver número de NF-e associado ao documento.
            if (
                res.get("uf") == "AL"
                and res.get("termo")
                and res["termo"] != "Não localizado"
            ) and (
                not res.get("num_arquivo")
                or res["num_arquivo"]
                in [
                    "Sem Número",
                    "Sem Arquivo Válido",
                ]
            ):
                res["num_arquivo"] = formatar_numero_arquivo(res["termo"])

            m = _safe_search(config.get("regex_chave_arquivo"), texto_pdf)
            if m:
                ch_cl = re.sub(r"\D", "", m.group(1 if m.groups() else 0).strip())
                if len(ch_cl) == 44:
                    res["chave_arquivo"] = ch_cl

            if res["chave_arquivo"]:
                num_doc = (
                    res["num_arquivo"]
                    if res["num_arquivo"]
                    else formatar_numero_arquivo(res["chave_arquivo"][25:34])
                )
                res["pares_documento"].append((res["chave_arquivo"], num_doc))

            if not res["termo"]:
                res["termo"] = extrair_numero_termo_pdf(texto_pdf, nome_anexo)

            if res["vencimento"] == "Não informado":
                v_std, _ = extrair_vencimento_e_valor_pdf(texto_pdf)
                if v_std != "Não informado":
                    res["vencimento"] = padronizar_data_ddmmyyyy(v_std)

            if res["valor"] == "Não informado":
                _, val_std = extrair_vencimento_e_valor_pdf(texto_pdf)
                if val_std != "Não informado":
                    res["valor"] = val_std

            if res["cod_barras"] in ["Sem Código", ""]:
                orig_std, bar_std = extrair_codigo_barras_pdf(texto_pdf)
                res["cod_barras_orig"] = orig_std
                res["cod_barras"] = bar_std

            chaves_enc = [p[0] for p in res["pares_documento"]]
            for ch in re.findall(r"\b(\d{44})\b", texto_pdf):
                if ch != res["cod_barras"] and ch not in chaves_enc:
                    chaves_enc.append(ch)
                    num_mat = formatar_numero_arquivo(ch[25:34])
                    res["pares_documento"].append((ch, num_mat))

            tem_dados = (
                (res["termo"] and res["termo"] != "Não localizado")
                or (res["cod_barras"] and res["cod_barras"] != "Sem Código")
                or (res["vencimento"] and res["vencimento"] != "Não informado")
                or (res["valor"] and res["valor"] != "Não informado")
                or res["cte"]
                or res["chave_arquivo"]
            )

            if tem_dados or not p_chaves:
                res["termo"] = res["termo"] or "Não localizado"
                return res

        return None


# ==========================================
# MÓDULO EXTRATOR ISOLADO POR UF
# ==========================================
AL_CAMPOS_PLANILHA = (
    "EMITENTE - NOME/RAZÃO SOCIAL",
    "EMITENTE - CPF/CNPJ",
    "EMITENTE - IE",
    "DESTINATÁRIO - NOME/RAZÃO SOCIAL",
    "DESTINATÁRIO - CPF/CNPJ",
    "DESTINATÁRIO - IE",
)


def _extrair_campos_al_pdf(pdf_bytes: bytes | None) -> dict[str, str]:
    if not pdf_bytes:
        return {}

    page = pypdf.PdfReader(io.BytesIO(pdf_bytes), strict=False).pages[0]
    elementos = []

    def capturar_texto(texto, cm, tm, font_dict, font_size):
        del cm, font_dict, font_size
        texto_limpo = " ".join(str(texto).split())
        if texto_limpo:
            elementos.append((float(tm[4]), float(tm[5]), texto_limpo))

    page.extract_text(visitor_text=capturar_texto)
    campos = {}
    rotulos_partes = (
        ("EMITENTE", re.compile(r"^Emitente$", re.IGNORECASE)),
        ("DESTINATÁRIO", re.compile(r"^Destinat", re.IGNORECASE)),
        ("TRANSPORTADOR", re.compile(r"^Transportador$", re.IGNORECASE)),
    )
    cabecalhos_partes = sorted(
        (
            (y, nome)
            for _, y, texto in elementos
            for nome, padrao in rotulos_partes
            if padrao.search(texto)
        ),
        reverse=True,
    )

    for indice, (y_cabecalho, nome_parte) in enumerate(cabecalhos_partes):
        y_limite_inferior = (
            cabecalhos_partes[indice + 1][0]
            if indice + 1 < len(cabecalhos_partes)
            else y_cabecalho - 38
        )
        itens_linha = [
            (x, y, texto)
            for x, y, texto in elementos
            if y_limite_inferior < y < y_cabecalho and y_cabecalho - y <= 32
        ]

        nomes = [
            texto
            for x, _, texto in itens_linha
            if x < 250
            and re.search(r"[A-Za-zÀ-ÿ]{2}", texto)
            and not re.search(
                r"Raz[aã]o Social|CPF/CNPJ|^IE$|^Emitente$|^Destinat|^Transportador$",
                texto,
                re.IGNORECASE,
            )
        ]
        documentos = [
            (
                x,
                re.sub(r"\D", "", texto),
            )  # Remove pontos, traços e espaços, mantendo apenas números
            for x, _, texto in itens_linha
            if x >= 250
            and re.search(r"\d", texto)
            and not re.search(r"CPF/CNPJ|Raz[aã]o Social", texto, re.IGNORECASE)
        ]
        documentos = [
            (x, valor)
            for x, valor in documentos
            if 5 <= len(re.sub(r"\D", "", valor)) <= 18
        ]

        prefixo = nome_parte
        if nomes:
            campos[f"{prefixo} - NOME/RAZÃO SOCIAL"] = max(
                nomes, key=lambda nome: len(nome)
            ).strip()

        documentos_fiscais = [valor for x, valor in documentos if 250 <= x < 430]
        inscricoes_estaduais = [valor for x, valor in documentos if x >= 430]
        if documentos_fiscais:
            campos[f"{prefixo} - CPF/CNPJ"] = documentos_fiscais[0]
        if inscricoes_estaduais:
            campos[f"{prefixo} - IE"] = inscricoes_estaduais[0]

    rotulos_nome_guia = [
        (y, x)
        for x, y, texto in elementos
        if re.search(r"Nome\s*/\s*Raz[aã]o Social", texto, re.IGNORECASE)
    ]
    if rotulos_nome_guia:
        y_rotulo, x_rotulo = max(rotulos_nome_guia)
        nomes_guia = [
            texto
            for x, y, texto in elementos
            if x >= x_rotulo
            and x < 250
            and 0 < y_rotulo - y <= 20
            and re.search(r"[A-Za-zÀ-ÿ]{2}", texto)
            and not re.search(r"Nome\s*/\s*Raz[aã]o Social", texto, re.IGNORECASE)
        ]
        if nomes_guia:
            campos["GUIA - NOME/RAZÃO SOCIAL"] = min(
                nomes_guia, key=lambda nome: len(nome)
            ).strip()

    inscricoes_caceal = []
    inscricoes_guia = []
    rotulos_inscricao = [
        (x, y)
        for x, y, texto in elementos
        if re.fullmatch(r"Inscri.{0,3}o", texto.strip(), re.IGNORECASE)
    ]
    for x_rotulo, y_rotulo in rotulos_inscricao:
        for x, y, texto in elementos:
            distancia_vertical = y_rotulo - y
            if not (0 < distancia_vertical <= 22 and abs(x - x_rotulo) <= 45):
                continue

            match_inscricao = re.search(
                r"(?:CACEAL|CNPJ\s*/\s*CPF|CPF\s*/\s*CNPJ|CNPJ|CPF|IE|"
                r"INSCRI[ÇC][ÃA]O(?:\s+ESTADUAL)?)\s*[:=-]?\s*"
                r"([\d][\d./-]{4,24})",
                texto,
                re.IGNORECASE,
            )
            if match_inscricao:
                valor_inscricao = match_inscricao.group(1).strip()
                inscricoes_guia.append((distancia_vertical, valor_inscricao))
                if re.search(r"CACEAL", texto, re.IGNORECASE):
                    inscricoes_caceal.append((y, valor_inscricao))

    if not inscricoes_guia:
        inscricoes_guia = [
            # COMO DEVE FICAR:
            (0, re.sub(r"\D", "", match.group(1)))  # Limpa os pontos
            for _, _, texto in elementos
            if (
                match := re.search(
                    r"(?:CNPJ\s*/\s*CPF|CPF\s*/\s*CNPJ|CNPJ|CPF|IE|"
                    r"INSCRI[ÇC][ÃA]O(?:\s+ESTADUAL)?)\s*[:=-]?\s*"
                    r"([\d][\d./-]{4,24})",
                    texto,
                    re.IGNORECASE,
                )
            )
        ]

    if inscricoes_guia:
        campos["GUIA - INSCRIÇÃO (CPF/CNPJ/IE)"] = min(
            inscricoes_guia, key=lambda inscricao: inscricao[0]
        )[1]
    if inscricoes_caceal:
        campos["GUIA - INSCRIÇÃO CACEAL"] = max(inscricoes_caceal)[1]

    return campos


def extrair_documento_legado(
    uf: str,
    txt_pdf: str,
    nome_anexo: str,
    nfe_map: dict,
    pdf_bytes: bytes | None = None,
) -> tuple[str, list, str, str, str, str, str]:
    uf_clean = (uf or "GERAL").upper()

    if uf_clean == "AL":
        return _extrair_regras_al(txt_pdf, nome_anexo, nfe_map, pdf_bytes)
    elif uf_clean == "AP":
        return _extrair_regras_ap(txt_pdf, nome_anexo, nfe_map)
    elif uf_clean == "AC":
        return _extrair_regras_ac(txt_pdf, nome_anexo, nfe_map)
    elif uf_clean == "MS":
        return _extrair_regras_ms(txt_pdf, nome_anexo, nfe_map)
    elif uf_clean == "AM":
        return _extrair_regras_am(txt_pdf, nome_anexo, nfe_map)

    else:
        return _extrair_regras_geral(txt_pdf, nome_anexo, nfe_map)


def _extrair_regras_al(
    txt_pdf: str,
    nome_anexo: str,
    nfe_map: dict,
    pdf_bytes: bytes | None = None,
):
    is_dar = e_dar_documento(txt_pdf)
    termo = extrair_numero_termo_pdf(txt_pdf, nome_anexo) or "Não localizado"
    if termo != "Não localizado":
        campos_al = _extrair_campos_al_pdf(pdf_bytes)
        if campos_al:
            nfe_map.setdefault(f"AL_CAMPOS_{termo}", {}).update(campos_al)
            # 1. PONTO AJUSTADO: Garante somente números (sem pontos, barras ou traços)
            inscricao_guia = re.sub(
                r"\D",
                "",
                campos_al.get("GUIA - INSCRIÇÃO (CPF/CNPJ/IE)", "")
                or campos_al.get("GUIA - INSCRIÇÃO CACEAL", ""),
            )
            if inscricao_guia:
                nfe_map[f"DOC_MS_{termo}"] = inscricao_guia
    barras_orig, barras_44 = extrair_codigo_barras_pdf(txt_pdf)
    vencimento, valor = extrair_vencimento_e_valor_pdf(txt_pdf)
    vencimento = padronizar_data_ddmmyyyy(vencimento)

    # 1. PONTO AJUSTADO: Extrai CNPJ/CPF ou Inscrição da Guia mantendo apenas dígitos numéricos
    doc_guia_al = ""
    m_doc_al = re.search(
        r"(?:CACEAL|CNPJ\s*/\s*CPF|CPF\s*/\s*CNPJ|CNPJ|CPF|I\.?E\.?|"
        r"INSCRI[ÇC][ÃA]O\s*(?:ESTADUAL)?(?:\s*/\s*CNPJ)?)"
        r"\s*[:=-]?\s*([\d\.\/-]{5,25})",
        txt_pdf,
        re.IGNORECASE,
    )
    if m_doc_al and not nfe_map.get(f"DOC_MS_{termo}"):
        doc_guia_al = re.sub(r"\D", "", m_doc_al.group(1))
        if termo != "Não localizado":
            nfe_map[f"DOC_MS_{termo}"] = doc_guia_al

    pares_documento = []
    chaves_usadas = []
    numeros_usados = []

    # 1. Coletar chaves e números em ordem de aparição para lidar com múltiplas notas no mesmo termo
    chaves_termo_al = []
    for match in re.finditer(r"\b\d{44}\b", txt_pdf):
        chave = match.group(0)
        if chave == barras_44 or chave.startswith("8"):
            continue
        if chave not in chaves_termo_al:
            chaves_termo_al.append(chave)

    termo_limpo = re.sub(r"\D", "", str(termo or ""))

    # Isola o quadro de Documentos impresso no Termo
    sec_match = re.search(
        r"Documentos\b([\s\S]*?)(?:Infra[çc][õo]es|Total\b|Autuado\b|FISCAIS\s+AUTUANTES|$)",
        txt_pdf,
        re.IGNORECASE,
    )
    trecho_alvo = sec_match.group(1) if sec_match else txt_pdf

    numeros_termo_al = []
    # 2. PONTO AJUSTADO: Lê o número da NF-e direto do texto/tabela (ex: DANFE 320), aceitando 1 a 9 dígitos e ignorando o Termo
    padroes_numero_al = [
        re.compile(
            r"(?i)\b(?:DANFE|CT-?E|NF-?E|CTE|NFE|DOCUMENTO)\b[^\d\n\r]*?(?:\b\d{44}\b[^\d\n\r]*?)?(\d{1,9})\b"
        ),
        re.compile(r"(?i)\b(?:NF|NOTA\s*FISCAL|NOTA)\s*[:=-]?\s*(\d{1,9})\b"),
    ]
    for padrao in padroes_numero_al:
        for match in padrao.finditer(trecho_alvo):
            num_raw = match.group(1).strip()
            # Descarta caso o número capturado seja o número do próprio Termo
            if termo != "Não localizado" and num_raw == termo_limpo:
                continue
            num_fmt = formatar_numero_arquivo(num_raw)
            if num_fmt != "Sem Número" and num_fmt not in numeros_termo_al:
                numeros_termo_al.append(num_fmt)

    # 2. Coletar números isolados (somente se NÃO for Guia/DAR e NÃO for o número do Termo)
    notas_termo_al = []
    if not is_dar:
        for match in re.finditer(
            r"(?i)\b(?:DANFE|NF-?E|NFE|NF|NOTA)\s*[:=-]?\s*(\d{1,9})\b", txt_pdf
        ):
            num_raw = match.group(1).strip()
            if termo != "Não localizado" and num_raw == termo_limpo:
                continue
            n_fmt = formatar_numero_arquivo(num_raw)
            if (
                n_fmt != "Sem Número"
                and n_fmt not in numeros_termo_al
                and n_fmt not in notas_termo_al
            ):
                notas_termo_al.append(n_fmt)

    numeros_ordenados = numeros_termo_al or notas_termo_al

    if chaves_termo_al or numeros_ordenados:
        total_itens = max(len(chaves_termo_al), len(numeros_ordenados))
        for idx in range(total_itens):
            chave = (
                chaves_termo_al[idx]
                if idx < len(chaves_termo_al)
                else "Sem Arquivo Válido"
            )
            num_doc = numeros_ordenados[idx] if idx < len(numeros_ordenados) else ""
            if chave != "Sem Arquivo Válido" and not num_doc:
                num_doc = nfe_map.get(chave, "Sem Número")
            if chave == "Sem Arquivo Válido" and not num_doc:
                continue
            chave_armazenada = (
                chave if chave != "Sem Arquivo Válido" else f"Sem Arquivo Válido::{idx}"
            )
            if chave_armazenada not in chaves_usadas:
                pares_documento.append((chave_armazenada, num_doc or "Sem Número"))
                chaves_usadas.append(chave_armazenada)
                if num_doc and num_doc != "Sem Número":
                    numeros_usados.append(num_doc)

    # 3. Coletar chaves de acesso sobrantes
    outras_chaves = []
    for ch in re.findall(r"\b(\d{44})\b", txt_pdf):
        if (
            ch != barras_44
            and ch not in chaves_usadas
            and ch not in outras_chaves
            and not ch.startswith("8")
        ):
            outras_chaves.append(ch)

    # 4. Emparelhar chaves e números sobrantes
    max_len = max(len(outras_chaves), len(notas_termo_al))
    for idx in range(max_len):
        chave = outras_chaves[idx] if idx < len(outras_chaves) else "Sem Arquivo Válido"
        num_doc = notas_termo_al[idx] if idx < len(notas_termo_al) else ""

        if chave != "Sem Arquivo Válido" and not num_doc:
            num_doc = nfe_map.get(chave, "Sem Número")

        if chave == "Sem Arquivo Válido" and not num_doc:
            continue
        chave_armazenada = (
            chave if chave != "Sem Arquivo Válido" else f"Sem Arquivo Válido::{idx}"
        )
        if chave_armazenada not in chaves_usadas:
            pares_documento.append((chave_armazenada, num_doc or "Sem Número"))
            chaves_usadas.append(chave_armazenada)

    pares_documento = ordenar_pares_documento_por_aparicao(txt_pdf, pares_documento)

    return (
        termo,
        list(dict.fromkeys(pares_documento)),
        barras_orig,
        barras_44,
        vencimento,
        valor,
        "AL",
    )


def _extrair_regras_ap(txt_pdf: str, nome_anexo: str, nfe_map: dict):
    is_dar = e_dar_documento(txt_pdf) or "GOVERNO DO ESTADO DO AMAPÁ" in txt_pdf.upper()
    termo = extrair_id_controle_ap(txt_pdf) or "Não localizado"
    barras_orig, barras_44 = extrair_codigo_barras_pdf(txt_pdf)
    barras_orig, barras_sem_dv = preparar_codigos_barras_ap(barras_orig, barras_44)
    vencimento, _ = extrair_vencimento_e_valor_pdf(txt_pdf)
    valor = extrair_valor_total_recolher_ap(txt_pdf)

    if termo == "Não localizado":
        termo_alt = extrair_numero_termo_pdf(txt_pdf, nome_anexo)
        if termo_alt:
            termo = termo_alt

    # Campo 05 pode conter CPF, CNPJ ou inscrição estadual; capture o maior grupo numérico.
    campo_05 = re.search(r"\b05\s*-\s*[\s\S]*?(?=\b06\s*-)", txt_pdf, re.IGNORECASE)
    if campo_05 and termo != "Não localizado":
        campo_05_sem_rotulo = re.sub(
            r"\b\d{1,2}\s*-\s*[^\r\n]*",
            " ",
            campo_05.group(0),
        )
        candidatos_doc = re.findall(
            r"(?<!\d)\d+(?:\s*[./-]\s*\d+)*(?!\d)",
            campo_05_sem_rotulo,
        )
        candidatos_doc = [
            re.sub(r"\D", "", candidato)
            for candidato in candidatos_doc
            if len(re.sub(r"\D", "", candidato)) >= 5
        ]
        if candidatos_doc:
            nfe_map[f"DOC_MS_{termo}"] = max(candidatos_doc, key=len)

    pares_documento = []

    # 1. Tentar encontrar chaves NF-e válidas, mesmo com espaços, comum no AP.
    chaves_ap = extrair_chaves_nfe_pdf(txt_pdf)

    # 2. Tentar encontrar o Número da Nota
    # TRAVA: Apenas bloqueia a leitura de "Números" curtos se for Guia (evita lixo numérico)
    notas_ap = []
    if not is_dar:
        matches_num = re.findall(
            r"N[º°o\.]*\s*(\d{1,3}(?:\.\d{3}){1,3}|\d{4,9})\b", txt_pdf, re.IGNORECASE
        )
        for n in matches_num:
            n_limpo = re.sub(r"\D", "", n)
            n_fmt = formatar_numero_arquivo(n_limpo)
            if n_fmt != "Sem Número" and n_fmt not in notas_ap:
                notas_ap.append(n_fmt)

    # 3. Emparelhar Chaves e Notas (Se achar a chave na guia, fatia o número automaticamente!)
    max_len = max(len(chaves_ap), len(notas_ap))
    for i in range(max_len):
        ch = chaves_ap[i] if i < len(chaves_ap) else "Sem Arquivo Válido"
        nm = notas_ap[i] if i < len(notas_ap) else "Sem Número"
        if ch != "Sem Arquivo Válido" and nm == "Sem Número":
            nm = nfe_map.get(ch, formatar_numero_arquivo(ch[25:34]))
        pares_documento.append((ch, nm))

    return (
        termo,
        list(dict.fromkeys(pares_documento)),
        barras_orig,
        barras_sem_dv,
        vencimento,
        valor,
        "AP",
    )


def separar_guias_ap(texto_pdf: str) -> list[tuple[str | None, str]]:
    """Separa guias AP por linhas de controle e remove IDs repetidos do mesmo lote."""
    texto_normalizado = str(texto_pdf or "").replace("\r\n", "\n").replace("\r", "\n")

    # 1. Encontrar todos os IDs de controle presentes no texto
    controles_encontrados = re.findall(
        r"(?:18\s*-\s*)?N[º°o\.]?\s*Controle[\s\S]{0,50}?\b(\d{8,15})\b",
        texto_normalizado,
        re.IGNORECASE,
    )
    controles_unicos = list(dict.fromkeys(c for c in controles_encontrados if c))

    # Se há apenas 1 controle no documento (mesmo que repetido na Ficha do Contribuinte e Ficha do Caixa)
    # ou nenhum, não divide o documento para não separar o cabeçalho do código de barras impresso na Ficha do Caixa.
    if len(controles_unicos) <= 1:
        termo = (
            controles_unicos[0]
            if controles_unicos
            else extrair_id_controle_ap(texto_normalizado)
        )
        if not termo or termo == "Não localizado":
            termo = extrair_numero_termo_pdf(texto_normalizado, "")
        return [(termo, texto_normalizado)]

    # 2. Se houver múltiplos controles DISTINTOS no mesmo arquivo (lote com guias diferentes):
    # Agrupa por cada controle distinto para manter cada guia completa (com sua Ficha do Caixa e código de barras).
    linhas = texto_normalizado.split("\n")
    marcadores = []
    controle_atual = None
    for indice, linha in enumerate(linhas):
        m = re.search(
            r"(?:18\s*-\s*)?N[º°o\.]?\s*Controle[\s\S]{0,50}?\b(\d{8,15})\b",
            linha,
            re.IGNORECASE,
        )
        if m:
            ctrl = m.group(1).strip()
            if ctrl != controle_atual and ctrl in controles_unicos:
                marcadores.append((indice, ctrl))
                controle_atual = ctrl

    if len(marcadores) <= 1:
        return [(controles_unicos[0] if controles_unicos else None, texto_normalizado)]

    guias = []
    ids_unicos = set()
    for i, (inicio, ctrl) in enumerate(marcadores):
        fim = marcadores[i + 1][0] if i + 1 < len(marcadores) else len(linhas)
        bloco = "\n".join(linhas[inicio:fim]).strip()
        if not bloco or ctrl in ids_unicos:
            continue
        ids_unicos.add(ctrl)
        guias.append((ctrl, bloco))

    return guias or [
        (controles_unicos[0] if controles_unicos else None, texto_normalizado)
    ]


def extrair_id_controle_ap(texto: str) -> str | None:
    texto_normalizado = str(texto or "").replace("\r\n", "\n").replace("\r", "\n")
    match = re.search(
        r"(?:18\s*-\s*)?N[º°o\.]?\s*Controle[\s\S]{0,50}?\b(\d{8,15})\b",
        texto_normalizado,
        re.IGNORECASE,
    )
    if match:
        return match.group(1).strip()
    match_fallback = re.search(
        r"\b(?:Controle|Número\s+do\s+DAR|N[º°o\.]*\s*DAR)[\s\S]{0,50}?\b(\d{8,15})\b",
        texto_normalizado,
        re.IGNORECASE,
    )
    if match_fallback:
        return match_fallback.group(1).strip()
    return None


def extrair_remessas_ap(texto: str) -> list[str]:
    padrao_remessa = re.compile(
        r"\b(?:REMESSA|CTE|CONHECIMENTO|MINUTA)\s*"
        r"(?:N[º°O.]?\s*)?[:=-]?\s*(\d{14})(?!\d)",
        re.IGNORECASE,
    )
    remessas = []
    for match in padrao_remessa.finditer(str(texto or "")):
        remessa = match.group(1)
        if remessa not in remessas:
            remessas.append(remessa)
    texto = str(texto or "")
    for match in re.finditer(r"(?<!\d)\d{14}(?!\d)", texto):
        remessa = match.group(0)
        contexto_anterior = texto[max(0, match.start() - 24) : match.start()]
        if re.search(r"(?:CNPJ|CPF)\s*[:\-]?\s*$", contexto_anterior, re.IGNORECASE):
            continue
        if remessa not in remessas:
            remessas.append(remessa)
    return remessas


def _extrair_regras_ac(txt_pdf: str, nome_anexo: str, nfe_map: dict):
    txt_upper = txt_pdf.upper()
    is_dar = (
        e_dar_documento(txt_pdf)
        or "NOTIFICAÇÃO DO ICMS" in txt_upper
        or "TERMO DE APREENSÃO" in txt_upper
        or "VIA BANCO" in txt_upper
    )

    # 1. Extrair Termo / Notificação (Prioriza o campo "Número", ex: 93.563)
    termo = "Não localizado"
    m_num = re.search(r"Número[\s\n\r:]*([\d\.]+)", txt_pdf, re.IGNORECASE)
    if m_num:
        termo = re.sub(r"\D", "", m_num.group(1))
    else:
        m_proc = re.search(
            r"Processo[\s\n\r]*Ativo\s*(\d+/\d{4})", txt_pdf, re.IGNORECASE
        )
        if m_proc:
            termo = m_proc.group(1).strip()
        else:
            termo_alt = extrair_numero_termo_pdf(txt_pdf, nome_anexo)
            if termo_alt:
                termo = termo_alt

    # 2. Extrair CNPJ/CPF do Contribuinte no Acre (Campo "Nº no CNPJ" ou "CNPJ/CPF")
    doc_guia_ac = ""
    m_doc_ac = re.search(
        r"(?:N[º°o]*\s*no\s*CNPJ|CNPJ/CPF|CNPJ|CPF|INSCRI[ÇC][ÃA]O\s*ESTADUAL)\s*[\n\r:]*\s*([\d\.\/-]{11,18})",
        txt_pdf,
        re.IGNORECASE,
    )
    if m_doc_ac:
        doc_guia_ac = re.sub(r"\D", "", m_doc_ac.group(1))  # Limpa os pontos

    # 3. Extrair Código de Barras (Formatado com pontos no rodapé)
    barras_orig, barras_44 = extrair_codigo_barras_pdf(txt_pdf)
    if barras_44 == "Sem Código":
        m_barras_ac = re.search(
            r"\b(8\d{11}[\s\.-]*\d{12}[\s\.-]*\d{12}[\s\.-]*\d{12})\b",
            re.sub(r"[^\d\s\.-]", "", txt_pdf),
        )
        if m_barras_ac:
            raw_b = m_barras_ac.group(1).strip()
            digits = re.sub(r"\D", "", raw_b)
            if len(digits) == 48:
                barras_orig = raw_b
                barras_44 = linha_digitavel_para_codigo_barras(digits)

    # 4. Extrair Vencimento (Captura "Data de Vencimento" ou "Válido para pagamento até")
    vencimento = "Não informado"
    m_venc = re.search(
        r"(?:Data\s*de\s*Vencimento|Válido\s*para\s*pagamento\s*até)\s*[:|-]?\s*[\n\r|]*\s*(\d{2}/\d{2}/\d{2,4})",
        txt_pdf,
        re.IGNORECASE,
    )
    if m_venc:
        venc_raw = m_venc.group(1).strip()
        if len(venc_raw) == 8:  # Ex: 05/11/26 -> 05/11/2026
            partes = venc_raw.split("/")
            vencimento = f"{partes[0]}/{partes[1]}/20{partes[2]}"
        else:
            vencimento = venc_raw

    vencimento = padronizar_data_ddmmyyyy(vencimento)

    # 5. Extrair Valor
    valor = "Não informado"
    m_val = re.search(
        r"Total\s+do\s+ICMS\s+a\s+recolher[\s\n\r:]*(?:R\$\s*)?(\d{1,3}(?:\.\d{3})*,\d{2})",
        txt_pdf,
        re.IGNORECASE,
    )
    if m_val:
        valor = m_val.group(1).strip()
    elif is_dar:
        m_val_alt = re.search(
            r"(?:Total|Valor)[\s\n\r:]*(?:R\$\s*)?(\d{1,3}(?:\.\d{3})*,\d{2})",
            txt_pdf,
            re.IGNORECASE,
        )
        if m_val_alt:
            valor = m_val_alt.group(1).strip()

    # 6. Extrair Chave de Acesso (44 dígitos) e mapear Número da Nota
    pares_documento, chaves_encontradas = [], []
    for ch in re.findall(r"\b(\d{44})\b", txt_pdf):
        if ch != barras_44 and ch not in chaves_encontradas and not ch.startswith("8"):
            chaves_encontradas.append(ch)

    for chave in chaves_encontradas:
        num_doc = nfe_map.get(chave, formatar_numero_arquivo(chave[25:34]))
        pares_documento.append((chave, num_doc))

    if not pares_documento:
        pares_documento.append(("Sem Arquivo Válido", "Sem Número"))

    return (
        termo,
        list(dict.fromkeys(pares_documento)),
        barras_orig,
        barras_44,
        vencimento,
        valor,
        "AC",
    )


def _extrair_regras_ms(txt_pdf: str, nome_anexo: str, nfe_map: dict):
    from src.services.ufs.ms import _extrair_regras_ms as _ms

    return _ms(txt_pdf, nome_anexo, nfe_map)

    # 1. Extrair Termo / TA (Aceita caracteres especiais e gregos T/A do MS)
    termo = "Não localizado"
    m_ta = re.search(
        r"(?:TERMO\s*DE\s*(?:APREENSÃO|VERIFICAÇÃO\s*FISCAL)\s*N[º°o\.]*|POSTO\s*:?\s*\d+\s+[\w\u0370-\u03ff]{2}\s*:?)\s*(\d{6,15})",
        txt_pdf,
        re.IGNORECASE,
    )
    if m_ta:
        termo = m_ta.group(1).strip()
    else:
        termo_alt = extrair_numero_termo_pdf(txt_pdf, nome_anexo)
        if termo_alt:
            termo = termo_alt

    # 2. Extrair CPF/CNPJ da Guia de MS (Campo 03-CPF/CNPJ/IE/RENAVAM)
    doc_guia_ms = ""
    m_doc = re.search(
        r"03-CPF/CNPJ[^\n]*[\s\n\r]*([\d\.\/-]{11,18})", txt_pdf, re.IGNORECASE
    )
    if m_doc:
        doc_guia_ms = re.sub(r"\D", "", m_doc.group(1))  # Limpa os pontos

    # 3. Código de barras (Febraban)
    barras_orig, barras_44 = extrair_codigo_barras_pdf(txt_pdf)

    # 4. Vencimento
    vencimento = "Não informado"
    if is_dar:
        m_nr = re.search(
            r"NÃO\s*RECEBER\s*APÓS\s*[:|-]?\s*(\d{2}/\d{2}/\d{4})",
            txt_pdf,
            re.IGNORECASE,
        )
        if m_nr:
            vencimento = m_nr.group(1).strip()
        else:
            m_venc = re.search(
                r"(?:02\s*-\s*VENCIMENTO|Data\s+de\s+Vencimento)[\s\n\r:]*(\d{2}/\d{2}/\d{4})",
                txt_pdf,
                re.IGNORECASE,
            )
            if m_venc:
                vencimento = m_venc.group(1).strip()

    vencimento = padronizar_data_ddmmyyyy(vencimento)

    # 5. Valor Total
    valor = "Não informado"
    if is_dar:
        m_val = re.search(
            r"(?:10\s*-\s*TOTAL|TOTAL\s*A\s*RECOLHER)\s*[\n\r:]*\s*(?:R\$\s*)?(\d{1,3}(?:\.\d{3})*,\d{2})",
            txt_pdf,
            re.IGNORECASE,
        )
        if m_val:
            valor = m_val.group(1).strip()
        else:
            vals = re.findall(
                r"TOTAL\s*[\n\r:]*\s*(?:R\$\s*)?(\d{1,3}(?:\.\d{3})*,\d{2})",
                txt_pdf,
                re.IGNORECASE,
            )
            if vals:
                valor = vals[0].strip()

    # 6. Notas Fiscais
    notas_guia = []
    matches_notas = re.findall(
        r"NOTAS\s*FISCAIS\s*[:|-]?[\s\n\r]*([\d\s,/-]+)", txt_pdf, re.IGNORECASE
    )
    for m in matches_notas:
        nums = re.findall(r"\b\d{1,9}\b", m)
        for n in nums:
            n_fmt = formatar_numero_arquivo(n)
            if n_fmt not in notas_guia and n_fmt != "Sem Número":
                notas_guia.append(n_fmt)

    num_nota_oficial = notas_guia[0] if notas_guia else "Sem Número"

    # 7. Chaves de Acesso
    chaves_encontradas = []
    for ch in re.findall(r"\b(\d{44})\b", txt_pdf):
        if ch != barras_44 and ch not in chaves_encontradas and not ch.startswith("8"):
            chaves_encontradas.append(ch)

    pares_documento = []
    if chaves_encontradas:
        for chave in chaves_encontradas:
            num_ref = (
                num_nota_oficial
                if num_nota_oficial != "Sem Número"
                else nfe_map.get(chave, formatar_numero_arquivo(chave[25:34]))
            )
            pares_documento.append((chave, num_ref))
    elif num_nota_oficial != "Sem Número":
        pares_documento.append(("Sem Arquivo Válido", num_nota_oficial))
    else:
        pares_documento.append(("Sem Arquivo Válido", "Sem Número"))

    # Armazena o CPF/CNPJ extraído no dicionário de retorno (se houver)
    if doc_guia_ms:
        nfe_map[f"DOC_MS_{termo}"] = doc_guia_ms

    return (
        termo,
        list(dict.fromkeys(pares_documento)),
        barras_orig,
        barras_44,
        vencimento,
        valor,
        "MS",
    )


def _extrair_regras_am(txt_pdf: str, nome_anexo: str, nfe_map: dict):
    txt_upper = txt_pdf.upper()
    is_dar = (
        e_dar_documento(txt_pdf)
        or "GOVERNO DO ESTADO DO AMAZONAS" in txt_upper
        or "AMAZONAS" in txt_upper
    )

    # 1. Extrair Termo / Controle (Campo "Controle:")
    termo = "Não localizado"
    m_ctrl = re.search(r"Controle\s*:\s*(\d+)", txt_pdf, re.IGNORECASE)
    if m_ctrl:
        termo = m_ctrl.group(1).strip()
    else:
        termo_alt = extrair_numero_termo_pdf(txt_pdf, nome_anexo)
        if termo_alt:
            termo = termo_alt

    # 2. Extrair CNPJ/CPF da Guia do Amazonas
    m_doc_am = re.search(
        r"(?:CODIGO\s*DO\s*CONTRIBUINTE|CNPJ/CPF|CNPJ|CPF)\s*[\n\r:]*\s*([\d\.\/-]{11,18})",
        txt_pdf,
        re.IGNORECASE,
    )
    if m_doc_am and termo != "Não localizado":
        nfe_map[f"DOC_MS_{termo}"] = re.sub(
            r"\D", "", m_doc_am.group(1)
        )  # Limpa os pontos

    # 3. Código de barras
    barras_orig, barras_44 = extrair_codigo_barras_pdf(txt_pdf)

    # 4. Vencimento (Campo "Válido até DD/MM/YYYY")
    vencimento = "Não informado"
    m_val_ate = re.search(
        r"Válido\s+até\s*[:|-]?\s*(\d{2}/\d{2}/\d{4})", txt_pdf, re.IGNORECASE
    )
    if m_val_ate:
        vencimento = m_val_ate.group(1).strip()
    else:
        m_venc = re.search(
            r"06\s*DATA\s*DE\s*VENCIMENTO[\s\n\r]*(\d{2}/\d{2}/\d{4})",
            txt_pdf,
            re.IGNORECASE,
        )
        if m_venc:
            vencimento = m_venc.group(1).strip()

    vencimento = padronizar_data_ddmmyyyy(vencimento)

    # 5. Valor Total
    valor = "Não informado"
    m_val = re.search(
        r"TOTAL[\s\n\r|]*(?:18\s*VALOR[\s\n\r|]*)?(\d{1,3}(?:\.\d{3})*,\d{2})",
        txt_pdf,
        re.IGNORECASE,
    )
    if m_val:
        valor = m_val.group(1).strip()

    # 6. Chaves de Acesso e Números
    chaves_encontradas = []
    for ch in re.findall(r"\b(\d{44})\b", txt_pdf):
        if ch != barras_44 and ch not in chaves_encontradas and not ch.startswith("8"):
            chaves_encontradas.append(ch)

    pares_documento = []
    for chave in chaves_encontradas:
        num_doc = nfe_map.get(chave, formatar_numero_arquivo(chave[25:34]))
        pares_documento.append((chave, num_doc))

    if not pares_documento:
        pares_documento.append(("Sem Arquivo Válido", "Sem Número"))

    return (
        termo,
        list(dict.fromkeys(pares_documento)),
        barras_orig,
        barras_44,
        vencimento,
        valor,
        "AM",
    )


def _extrair_regras_geral(txt_pdf: str, nome_anexo: str, nfe_map: dict):
    is_dar = e_dar_documento(txt_pdf)
    termo = extrair_numero_termo_pdf(txt_pdf, nome_anexo) or "Não localizado"
    barras_orig, barras_44 = extrair_codigo_barras_pdf(txt_pdf)
    vencimento, valor = extrair_vencimento_e_valor_pdf(txt_pdf)
    vencimento = padronizar_data_ddmmyyyy(vencimento)

    pares_documento, chaves_encontradas = [], []
    if not is_dar:
        for ch in re.findall(r"\b(\d{44})\b", txt_pdf):
            if ch not in chaves_encontradas:
                chaves_encontradas.append(ch)
        for chave in chaves_encontradas:
            num_doc = nfe_map.get(chave, formatar_numero_arquivo(chave[25:34]))
            pares_documento.append((chave, num_doc))
            if termo == "Não localizado":
                termo = chave

    return (
        termo,
        list(dict.fromkeys(pares_documento)),
        barras_orig,
        barras_44,
        vencimento,
        valor,
        "GERAL",
    )


# ==========================================
# JANELA UNIFICADA DE CONFIGURAÇÕES (APRENDIZADO DUPLO LADO A LADO)
# ==========================================
class JanelaConfiguracoes(ctk.CTkToplevel):
    def __init__(
        self,
        parent,
        gerenciador_layouts: GerenciadorLayouts,
        gerenciador_dedicados: GerenciadorClientesDedicados,
        app_gui,
    ):
        super().__init__(parent)
        self.gerenciador_layouts = gerenciador_layouts
        self.gerenciador_dedicados = gerenciador_dedicados
        self.app_gui = app_gui

        self.title(
            "⚙️ Painel de Aprendizado de Layouts Lado a Lado (Guia DAR + Termo/Nota)"
        )
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
        self._construir_aba_dedicados()

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
        self.ent_busca_layout.bind(
            "<KeyRelease>", lambda event: self.atualizar_tabela_layouts()
        )
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

        ctk.CTkFrame(mid_box, height=2, fg_color="#CBD5E1").pack(
            fill="x", pady=8, padx=10
        )
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
            reg_entry = ctk.CTkEntry(
                frame, height=26, font=("Consolas", 9), fg_color="#FFFFFF"
            )
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
        self.txt_resultado_lado.insert(
            "0.0", "Aguardando carregamento e teste de cruzamento..."
        )

        ctk.CTkFrame(right_box, height=2, fg_color="#CBD5E1").pack(
            fill="x", pady=5, padx=8
        )
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

        sc_tree = ttk.Scrollbar(
            tabla_frame, orient="vertical", command=self.tree_layouts.yview
        )
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
            return messagebox.showwarning(
                "Atenção", "Carregue ao menos um PDF de exemplo!"
            )
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
            messagebox.showinfo(
                "Sugestão", f"Palavras-chave detectadas:\n{', '.join(sugeridas)}"
            )

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
            return messagebox.showwarning(
                "Campo Requerido", "Informe um Nome para o Layout!"
            )

        kw_list = [
            k.strip() for k in self.ent_palavras_chave.get().split(",") if k.strip()
        ]
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
            self.ent_busca_layout.get().strip().upper()
            if hasattr(self, "ent_busca_layout")
            else ""
        )
        for item in self.tree_layouts.get_children():
            self.tree_layouts.delete(item)
        for nome, cfg in self.gerenciador_layouts.layouts.items():
            if filtro and filtro not in f"{nome} {cfg.get('uf', 'GERAL')}".upper():
                continue
            status = (
                "OK"
                if not self.gerenciador_layouts.validar_layout(nome, cfg)
                else "INVÁLIDO"
            )
            self.tree_layouts.insert(
                "", tk.END, values=(nome, cfg.get("uf", "GERAL"), status)
            )

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
            messagebox.showwarning(
                "Padrões", "Esse layout não possui uma versão padrão."
            )

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
                historico = (
                    dados.pop("_historico", []) if isinstance(dados, dict) else []
                )
                invalidos = []
                for nome, config in dados.items():
                    if not isinstance(config, dict):
                        invalidos.append(f"{nome}: configuração inválida")
                    else:
                        invalidos.extend(
                            f"{nome}: {erro}"
                            for erro in self.gerenciador_layouts.validar_layout(
                                nome, config
                            )
                        )
                if invalidos:
                    return messagebox.showerror(
                        "Importação inválida", "\n".join(invalidos[:20])
                    )
                self.gerenciador_layouts.historico.extend(historico)
                self.gerenciador_layouts.layouts.update(dados)
                self.gerenciador_layouts.registrar_historico(
                    "IMPORTAÇÃO", os.path.basename(arq)
                )
                self.gerenciador_layouts.salvar_layouts()
                self.atualizar_tabela_layouts()



# ==========================================
# CLIENTE ZENDESK API (AUTENTICAÇÃO RESILIENTE)
# ==========================================
class ZendeskAPI:
    def __init__(self, subdomain: str, cookie: str):
        self.subdomain = subdomain
        self.base_url = f"https://{subdomain}.zendesk.com/api/v2"

        cookie_limpo = cookie.strip()
        if cookie_limpo.lower().startswith("cookie:"):
            cookie_limpo = cookie_limpo[7:].strip()
        self.cookie_limpo = re.sub(r"[\r\n]+", "", cookie_limpo)
        self._local = threading.local()

    @property
    def session(self) -> requests.Session:
        if not hasattr(self._local, "session"):
            s = requests.Session()
            adapter = HTTPAdapter(pool_connections=20, pool_maxsize=20)
            s.mount("https://", adapter)
            s.mount("http://", adapter)
            s.headers.update(
                {
                    "Content-Type": "application/json",
                    "Accept": "application/json",
                    "Cookie": self.cookie_limpo,
                    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
                }
            )
            self._local.session = s
        return self._local.session

    def validar_autenticacao(self) -> tuple[bool, str]:
        try:
            resp = self.session.get(
                f"{self.base_url}/users/me.json", timeout=10, allow_redirects=False
            )
            if resp.status_code == 200 and "user" in resp.json():
                return True, resp.json().get("user", {}).get("name", "Agente")
            elif resp.status_code in (301, 302, 401, 403):
                return False, "Sessão expirada. Atualize o Cookie do Zendesk."
            return False, f"Status HTTP: {resp.status_code}"
        except Exception as e:  # noqa: BLE001
            return False, str(e)

    def obter_ticket(self, ticket_id: str) -> dict | None:
        try:
            resp = self.session.get(
                f"{self.base_url}/tickets/{ticket_id}.json",
                timeout=15,
                allow_redirects=False,
            )
            if resp.status_code == 200 and "ticket" in resp.json():
                return resp.json().get("ticket")
        except Exception:
            pass
        return None

    def obter_comentarios(self, ticket_id: str) -> list:
        try:
            resp = self.session.get(
                f"{self.base_url}/tickets/{ticket_id}/comments.json",
                timeout=15,
                allow_redirects=False,
            )
            if resp.status_code == 200 and "comments" in resp.json():
                return resp.json().get("comments", [])
        except Exception:
            pass
        return []

    def baixar_conteudo(self, url: str, retries: int = 3) -> tuple[bytes | None, str]:
        for attempt in range(1, retries + 1):
            try:
                resp = self.session.get(url, allow_redirects=False, timeout=(10, 45))
                if resp.status_code in (301, 302, 303, 307, 308):
                    location = resp.headers.get("Location")
                    if location:
                        req_s3 = requests.get(
                            location,
                            timeout=(10, 60),
                            headers={"User-Agent": "Mozilla/5.0"},
                        )
                        if req_s3.status_code == 200:
                            return req_s3.content, "OK"
                        return None, f"Erro S3 HTTP {req_s3.status_code}"
                elif resp.status_code == 200:
                    return resp.content, "OK"
                return None, f"Erro HTTP {resp.status_code}"
            except (
                requests.exceptions.Timeout,
                requests.exceptions.ConnectionError,
            ) as e:
                if attempt == retries:
                    return None, f"Timeout na rede após {retries} tentativas: {e}"
                time.sleep(1.5 * attempt)
            except Exception as e:
                return None, str(e)
        return None, "Falha no download"

    def responder_ticket(
        self, ticket_id: str, mensagem: str, status: str = "solved"
    ) -> bool:
        try:
            payload = {
                "ticket": {
                    "comment": {"body": mensagem, "public": True},
                    "status": status,
                }
            }
            resp = self.session.put(
                f"{self.base_url}/tickets/{ticket_id}.json", json=payload, timeout=15
            )
            return resp.status_code == 200
        except Exception:
            return False


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
        o1 = self.create_oval(
            x, y, x + 2 * r, y + h, fill=color, outline=color, width=1
        )
        o2 = self.create_oval(
            x + w - 2 * r, y, x + w, y + h, fill=color, outline=color, width=1
        )
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
        self.janela_unificar = None
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
        self.gerenciador_dedicados = GerenciadorClientesDedicados()

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
        try:
            if not os.path.exists(self.arquivo_memoria):
                self.dados_em_memoria = []
                return

            with open(self.arquivo_memoria, "r", encoding="utf-8") as arquivo:
                dados = json.load(arquivo)

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
        except (FileNotFoundError, json.JSONDecodeError):
            self.dados_em_memoria = []
        except Exception as e:
            print(f"[Erro] Falha ao carregar memória diária: {e}")
            self.dados_em_memoria = []

    def salvar_memoria_diaria(self):
        try:
            payload = {
                "dados_em_memoria": self.dados_em_memoria,
                "memoria_termos": self.memoria_termos,
                "tickets_processados": self.tickets_processados,
                "ctes_consultados_cache": self.ctes_consultados_cache,
                "atualizado_em": datetime.now().isoformat(timespec="seconds"),
            }
            with self.lock:
                with open(self.arquivo_memoria, "w", encoding="utf-8") as arquivo:
                    json.dump(payload, arquivo, ensure_ascii=False, indent=2)
        except Exception as e:
            print(f"[Erro] Falha ao salvar memória diária: {e}")

    def salvar_checkpoint(self, motivo: str = "lote") -> None:
        try:
            nome_base = (
                re.sub(r"[^A-Za-z0-9._-]+", "_", (motivo or "lote").strip())[:40]
                or "lote"
            )
            data_stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            pasta_checkpoint = os.path.join(
                os.path.dirname(os.path.abspath(__file__)), "checkpoints"
            )
            os.makedirs(pasta_checkpoint, exist_ok=True)
            caminho = os.path.join(
                pasta_checkpoint, f"checkpoint_{data_stamp}_{nome_base}.json"
            )

            payload = {
                "motivo": motivo,
                "salvo_em": datetime.now().isoformat(timespec="seconds"),
                "dados_em_memoria": self.dados_em_memoria,
                "memoria_termos": self.memoria_termos,
                "tickets_processados": self.tickets_processados,
                "ctes_consultados_cache": self.ctes_consultados_cache,
            }
            with self.lock:
                with open(caminho, "w", encoding="utf-8") as arquivo:
                    json.dump(payload, arquivo, ensure_ascii=False, indent=2)
        except Exception as e:
            print(f"[Erro] Falha ao salvar checkpoint: {e}")

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

        ctk.CTkFrame(sidebar, height=2, fg_color="#CBD5E1").pack(
            fill="x", pady=6, padx=15
        )

        frame_dedicados = ctk.CTkFrame(sidebar, fg_color="#E2E8F0", corner_radius=8)
        frame_dedicados.pack(fill="x", padx=10, pady=5)

        ctk.CTkLabel(
            frame_dedicados,
            text="Base Clientes Dedicados",
            font=ctk.CTkFont(size=12, weight="bold"),
            text_color=self.BTN_ALTA[0],
        ).pack(anchor="center", pady=(6, 2))
        self.lbl_qtd_dedicados = ctk.CTkLabel(
            frame_dedicados,
            text=f"Cadastrados: {len(self.gerenciador_dedicados.clientes)}",
            font=("Segoe UI", 10, "bold"),
            text_color="#0F172A",
        )
        self.lbl_qtd_dedicados.pack(anchor="w", padx=12, pady=1)
        self.lbl_data_dedicados = ctk.CTkLabel(
            frame_dedicados,
            text=f"Atualizado: {self.gerenciador_dedicados.ultima_atualizacao}",
            font=("Segoe UI", 8),
            text_color="#475569",
        )
        self.lbl_data_dedicados.pack(anchor="w", padx=12, pady=(0, 6))

        ctk.CTkFrame(sidebar, height=2, fg_color="#CBD5E1").pack(
            fill="x", pady=6, padx=15
        )

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
                self.log(
                    f"[✓] Sessão Jadlog salva! Validando conexão com o Fraction..."
                )

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

        ctk.CTkFrame(sidebar, height=2, fg_color="#CBD5E1").pack(
            fill="x", pady=6, padx=15
        )

        add_btn("🔎 Buscar tomadores", self.BTN_AZUL, "conciliar_tomador")
        add_btn("🔄 Atualizar tabela", self.BTN_NEUTRO, "atualizar_tabela")
        add_btn("📎 Unificar cliente", self.BTN_CINZA_ESCURO, "unificar_tomador_guias")

        ctk.CTkFrame(sidebar, height=2, fg_color="#CBD5E1").pack(
            fill="x", pady=12, padx=15
        )

        add_btn("💾 Relatório final", self.BTN_BAIXA, "salvar_final")
        add_btn("🔗 Consolidar planilhas", self.BTN_NEUTRO, "unificar_planilhas")

        ctk.CTkFrame(sidebar, height=2, fg_color="#CBD5E1").pack(
            fill="x", pady=12, padx=15
        )
        add_btn("⏹ Cancelar operação", self.BTN_CANC, "solicitar_cancelamento")
        ctk.CTkFrame(sidebar, height=2, fg_color="#CBD5E1").pack(
            fill="x", pady=12, padx=15
        )

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

        add_btn_claro("💬 Resposta Zendesk", "guias")
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
        self.lbl_card_quarentena = criar_card(
            cards_frame, "🔴 QUARENTENA", "0", "#D31145"
        )
        self.lbl_card_valor = criar_card(
            cards_frame, "💰 VALOR TOTAL", "R$ 0,00", "#1976D2"
        )

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
        self.tabela.tag_configure(
            "incompleto", background="#FFF2CC", foreground="#7F6000"
        )
        self.tabela.tag_configure(
            "divergencia_fraction", background="#FFE0B2", foreground="#7C2D12"
        )

        for col, nome_exibicao, largura, ancoragem in self.colunas_config:
            self.tabela.heading(
                col,
                text=nome_exibicao,
                command=lambda c=col: self._ordenar_tabela(c, False),
            )
            self.tabela.column(
                col, width=largura, anchor=cast(Any, ancoragem), stretch=False
            )
        self.tabela.bind("<Button-3>", self._mostrar_menu_contexto)
        self.tabela.bind("<Double-1>", self._mostrar_detalhes_divergencias_fraction)

        scroll_y = ttk.Scrollbar(
            tabela_inner, orient="vertical", command=self.tabela.yview
        )
        scroll_x = ttk.Scrollbar(
            tabela_inner, orient="horizontal", command=self.tabela.xview
        )
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
                    valor_normalizado = normalizar_valor_monetario(valor).replace(
                        ",", "."
                    )
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

    def _atualizar_labels_dedicados(self):
        if hasattr(self, "lbl_qtd_dedicados") and self.lbl_qtd_dedicados:
            self.lbl_qtd_dedicados.configure(
                text=f"Cadastrados: {len(self.gerenciador_dedicados.clientes)}"
            )
        if hasattr(self, "lbl_data_dedicados") and self.lbl_data_dedicados:
            self.lbl_data_dedicados.configure(
                text=f"Atualizado: {self.gerenciador_dedicados.ultima_atualizacao}"
            )

    def _gerar_resumo_dedicados(self, linhas_totais: list, cabecalho: list):
        idx_tom = (
            cabecalho.index("TOMADOR")
            if "TOMADOR" in cabecalho
            else (cabecalho.index("TOMADORES") if "TOMADORES" in cabecalho else -1)
        )
        total = len(linhas_totais)
        dedicados = 0
        for row in linhas_totais:
            tom = str(row[idx_tom]) if (idx_tom != -1 and idx_tom < len(row)) else ""
            if self.gerenciador_dedicados.e_dedicado(tom):
                dedicados += 1
        nao_dedicados = total - dedicados
        perc_d = (dedicados / total * 100) if total > 0 else 0.0
        perc_nd = (nao_dedicados / total * 100) if total > 0 else 0.0

        resumo_msg = (
            f"[📊 RESUMO DEDICADOS] Total Processado: {total} | "
            f"Dedicados: {dedicados} ({perc_d:.1f}%) | "
            f"Não Dedicados: {nao_dedicados} ({perc_nd:.1f}%)"
        )
        self.log(resumo_msg)

    def _ordenar_tabela(self, coluna, reverso):
        dados = [(self.tabela.set(k, coluna), k) for k in self.tabela.get_children("")]
        dados.sort(reverse=reverso)
        for index, (val, k) in enumerate(dados):
            self.tabela.move(k, "", index)
        self.tabela.heading(
            coluna, command=lambda: self._ordenar_tabela(coluna, not reverso)
        )

    def _mostrar_detalhes_divergencias_fraction(self, event=None, iid=None):
        item_id = iid or (self.tabela.identify_row(event.y) if event else "")
        if not item_id:
            return
        divergencias = getattr(self, "_divergencias_fraction_por_iid", {}).get(
            item_id, []
        )
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
                    command=lambda: self._mostrar_detalhes_divergencias_fraction(
                        iid=item
                    ),
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
                            if (
                                datetime.strptime(data_p.strip(), "%d/%m/%Y").date()
                                < hoje
                            ):
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
                    limpar_texto_excel(
                        item.get("CODIGO BARRAS ORIGINAL", "Sem Código")
                    ),
                    limpar_texto_excel(item.get("CODIGO BARRAS", "Sem Código")),
                    limpar_texto_excel(item.get("DATA", "Não Informado")),
                    limpar_texto_excel(item.get("VENCIMENTO", "Não informado")),
                    limpar_texto_excel(item.get("VALOR", "Não informado")),
                    limpar_texto_excel(item.get("CTE", "Sem CTE")),
                    tomador,
                    ("⚠ " if "num_arquivo" in campos_destacados else "")
                    + limpar_texto_excel(item.get("NÚMERO ARQUIVO", "Sem Número")),
                    ("⚠ " if "chave" in campos_destacados else "")
                    + limpar_texto_excel(
                        item.get("CHAVE ARQUIVO", "Sem Arquivo Válido")
                    ),
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
        UFS_VALIDAS = {
            "AC",
            "AL",
            "AP",
            "AM",
            "BA",
            "CE",
            "DF",
            "ES",
            "GO",
            "MA",
            "MT",
            "MS",
            "MG",
            "PA",
            "PB",
            "PR",
            "PE",
            "PI",
            "RJ",
            "RN",
            "RS",
            "RO",
            "RR",
            "SC",
            "SP",
            "SE",
            "TO",
        }
        if txt_pdf:
            txt_upper = txt_pdf.upper()

            mapa_nomes = [
                ("GOVERNO DO ESTADO DO AMAPÁ", "AP"),
                ("GOVERNO DO ESTADO DO ACRE", "AC"),
                ("GOVERNO DO ESTADO DO PARÁ", "PA"),
                ("GOVERNO DO ESTADO DO PARA", "PA"),
                ("ESTADO DO MATO GROSSO DO SUL", "MS"),
                ("MATO GROSSO DO SUL", "MS"),
                ("ESPÍRITO SANTO", "ES"),
                ("ESPIRITO SANTO", "ES"),
                ("RIO GRANDE DO NORTE", "RN"),
                ("RIO GRANDE DO SUL", "RS"),
                ("DISTRITO FEDERAL", "DF"),
                ("MINAS GERAIS", "MG"),
                ("SANTA CATARINA", "SC"),
                ("RIO DE JANEIRO", "RJ"),
                ("SÃO PAULO", "SP"),
                ("SAO PAULO", "SP"),
                ("PERNAMBUCO", "PE"),
                ("MARANHÃO", "MA"),
                ("MARANHAO", "MA"),
                ("TOCANTINS", "TO"),
                ("AMAZONAS", "AM"),
                ("RONDÔNIA", "RO"),
                ("RONDONIA", "RO"),
                ("RORAIMA", "RR"),
                ("PARAÍBA", "PB"),
                ("PARAIBA", "PB"),
                ("ALAGOAS", "AL"),
                ("SERGIPE", "SE"),
                ("PIAUÍ", "PI"),
                ("PIAUI", "PI"),
                ("CEARÁ", "CE"),
                ("CEARA", "CE"),
                ("GOIÁS", "GO"),
                ("GOIAS", "GO"),
                ("BAHIA", "BA"),
                ("MATO GROSSO", "MT"),
                ("AMAPÁ", "AP"),
                ("AMAPA", "AP"),
            ]
            for nome_est, uf_code in mapa_nomes:
                if re.search(r"\b" + re.escape(nome_est) + r"\b", txt_upper):
                    return uf_code

            if re.search(
                r"\bPARÁ\b|\bSEFAZ[/\s-]*PA\b|\bESTADO\s+DO\s+PAR[AÁ]\b", txt_upper
            ):
                return "PA"

            if re.search(r"\bACRE\b", txt_upper):
                return "AC"

            m_sefaz = re.search(r"\bSEFAZ[/\s-]*([A-Z]{2})\b", txt_upper)
            if m_sefaz and m_sefaz.group(1) in UFS_VALIDAS:
                return m_sefaz.group(1)

            m_uf = re.search(r"\bUF\s*[:=]?\s*([A-Z]{2})\b", txt_upper)
            if m_uf and m_uf.group(1) in UFS_VALIDAS:
                return m_uf.group(1)

        if ticket_data:
            tags = [str(t).lower() for t in ticket_data.get("tags", [])]
            for uf_candidate in [
                "ap",
                "ms",
                "ac",
                "al",
                "am",
                "ba",
                "ce",
                "df",
                "es",
                "go",
                "ma",
                "mt",
                "mg",
                "pa",
                "pb",
                "pr",
                "pe",
                "pi",
                "rj",
                "rn",
                "rs",
                "ro",
                "rr",
                "sc",
                "sp",
                "se",
                "to",
            ]:
                if uf_candidate in tags:
                    return uf_candidate.upper()

        return "GERAL"

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
                        self.gerenciador_dedicados,
                        self,
                    )

            self.janela.after(0, _abrir_config)
            return

        if acao == "limpar_cache_tomadores":
            with self.lock:
                quantidade_cache = len(self.ctes_consultados_cache)
                self.ctes_consultados_cache.clear()
            self.salvar_memoria_diaria()
            self.log(
                f"[✓] Cache de tomadores limpo: {quantidade_cache} registro(s) removido(s)."
            )
            return

        if acao == "unificar_tomador_guias":

            def _abrir_unificar():
                if (
                    self.janela_unificar is not None
                    and self.janela_unificar.winfo_exists()
                ):
                    self.janela_unificar.focar_janela()
                else:
                    self.janela_unificar = JanelaUnificarTomador(self.janela, self)

            self.janela.after(0, _abrir_unificar)
            return

        tickets = self.obter_lista_tickets()
        if not tickets and acao in [
            "guias",
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
            "guias": lambda: self._acao_guias(tickets),
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

        elif acao == "unificar_planilhas":
            arqs = filedialog.askopenfilenames(
                title="Selecione as planilhas para unir:",
                filetypes=[("Planilhas", "*.csv;*.xlsx;*.xls")],
                initialdir=self.ultimo_dir_base,
            )
            if arqs:
                self.ultimo_dir_base = os.path.dirname(arqs[0])
                self.salvar_memoria_diaria()
                arq_saida = filedialog.asksaveasfilename(
                    title="Onde salvar a Planilha Unificada?",
                    initialdir=self.ultimo_dir_base,
                    initialfile=f"Consolidado_{datetime.now().strftime('%Y%m%d_%H%M%S')}.xlsx",
                    defaultextension=".xlsx",
                    filetypes=[("Excel Workbooks", "*.xlsx"), ("CSV", "*.csv")],
                )
                if arq_saida:
                    self.ultimo_dir_base = os.path.dirname(arq_saida)
                    self.salvar_memoria_diaria()
                    threading.Thread(
                        target=self._acao_unificar_planilhas_arquivos,
                        args=(list(arqs), arq_saida),
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

    @registrar_execucao("Resposta automática de tickets")
    def _acao_guias(self, tickets: list[str]):
        msg = (
            "Bom dia, guias encaminhadas para pagamento."
            if datetime.now().hour < 12
            else "Boa tarde, guias encaminhadas para pagamento."
        )
        sucessos = 0

        self.log(
            f"[Zendesk] Iniciando resposta automática de {len(tickets)} ticket(s)..."
        )
        for i, tid in enumerate(tickets, 1):
            if self.cancelar_operacao:
                break
            log_terminal(
                "PROGRESSO", f"Processando ticket {i} de {len(tickets)}: #{tid}..."
            )
            if self._api_pronto().responder_ticket(tid, msg, "solved"):
                sucessos += 1
                self.log(f"[✓] Ticket #{tid} respondido e resolvido.")
            else:
                self.log(f"[!] Falha ao responder ticket #{tid}.")
            self.atualizar_progresso(i, len(tickets))

        self.copiar_para_clipboard(msg)
        self.log(f"[🏆] {sucessos} tickets processados na API. Mensagem copiada.")

    @registrar_execucao("Download e organização de anexos")
    def _acao_anexos(self, tickets: list[str], pasta_destino: str):
        self.log(
            f"[Anexos] Iniciando download e organização por Estado de {len(tickets)} ticket(s)..."
        )
        hoje = datetime.now().date()

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
        lock_hashes = threading.Lock()

        def baixar_e_analisar(anexo, tid, uf_ticket_tag):
            if self.cancelar_operacao:
                return None
            nome = str(anexo["file_name"])
            nome_limpo = re.sub(r"[\\/*?:|<>]", "_", nome)
            conteudo, status_download = self._api_pronto().baixar_conteudo(
                anexo["content_url"]
            )

            if not conteudo:
                self.log(
                    f"[!] Erro ao baixar '{nome}' (Ticket #{tid}): {status_download}"
                )
                return None

            md5_hash = calcular_hash_md5(conteudo)
            is_duplicado = False
            with lock_hashes:
                if md5_hash in hashes_baixados:
                    is_duplicado = True
                    self.log(
                        f"[!] Arquivo duplicado detectado: '{nome_limpo}' (Ticket #{tid})."
                    )
                else:
                    hashes_baixados.add(md5_hash)

            uf_final = "GERAL"
            subpasta = "OUTROS"
            is_dar, is_termo, is_nota = False, False, False
            vencimento_dar = "Não informado"
            texto_anexo = ""

            if nome_limpo.lower().endswith(".pdf"):
                txt_pdf, status_pdf = extrair_texto_pdf(conteudo)
                texto_anexo = txt_pdf

                uf_pdf = self._identificar_uf(None, txt_pdf)
                if uf_pdf != "GERAL":
                    uf_final = uf_pdf
                else:
                    dados_din = self.gerenciador_layouts.identificar_e_extrair(
                        txt_pdf, nome_limpo, pdf_bytes=conteudo
                    )
                    if (
                        dados_din
                        and dados_din.get("uf")
                        and dados_din.get("uf") != "GERAL"
                    ):
                        uf_final = dados_din["uf"]
                    else:
                        uf_final = uf_ticket_tag if uf_ticket_tag != "GERAL" else "AL"

                is_dar = e_dar_documento(txt_pdf)
                is_termo = e_termo_documento(txt_pdf)
                is_nota = e_nota_fiscal(txt_pdf, nome_limpo)

                if re.search(
                    r"AMAP[AÁ]|GOVERNO\s+DO\s+ESTADO\s+DO\s+AMAP[AÁ]",
                    txt_pdf,
                    re.IGNORECASE,
                ):
                    uf_final = "AP"

                # TRAVA EXCLUSIVA AP: Diferenciação exata entre DANFE e DAR no Amapá
                if uf_final == "AP":
                    eh_danfe_ap = any(
                        k in txt_pdf.upper()
                        for k in ["DOCUMENTO AUXILIAR DA NOTA", "DANFE", "RECEBEMOS DE"]
                    )
                    if eh_danfe_ap:
                        is_nota = True
                        is_dar = False
                        is_termo = False
                        subpasta = "NOTAS"
                    else:
                        is_nota = False
                        is_dar = True
                        subpasta = "DAR"

                if is_nota:
                    subpasta = "NOTAS" if uf_final == "AP" else "NOTA"
                elif is_dar:
                    subpasta = "DAR"
                    venc_str, _ = extrair_vencimento_e_valor_pdf(txt_pdf)
                    vencimento_dar = padronizar_data_ddmmyyyy(venc_str)
                    dados_din = self.gerenciador_layouts.identificar_e_extrair(
                        txt_pdf, nome_limpo, pdf_bytes=conteudo
                    )
                    if (
                        dados_din
                        and dados_din.get("vencimento")
                        and dados_din.get("vencimento") != "Não informado"
                    ):
                        vencimento_dar = padronizar_data_ddmmyyyy(
                            dados_din.get("vencimento")
                        )
                elif is_termo:
                    subpasta = "TERMO"
                else:
                    subpasta = "PDFs_GERAIS"
            else:
                uf_final = uf_ticket_tag if uf_ticket_tag != "GERAL" else "AL"

            # TRAVA EXCLUSIVA AP: No Amapá, somente a data da Guia DAR define se o lote está vencido
            is_vencido = False
            if uf_final == "AP":
                if is_dar and vencimento_dar != "Não informado":
                    is_vencido = documento_esta_vencido(vencimento_dar)
                else:
                    is_vencido = False
            else:
                # Regra original preservada para AL e demais estados
                if is_dar and vencimento_dar != "Não informado":
                    is_vencido = documento_esta_vencido(vencimento_dar)
                elif is_nota:
                    vencimento_nota = extrair_vencimento_nota(texto_anexo)
                    is_vencido = documento_esta_vencido(vencimento_nota)

            return {
                "tid": tid,
                "nome_limpo": nome_limpo,
                "conteudo": conteudo,
                "uf_final": uf_final,
                "subpasta": subpasta,
                "is_dar": is_dar,
                "is_termo": is_termo,
                "is_nota": is_nota,
                "is_duplicado": is_duplicado,
                "is_vencido": is_vencido,
                "vencimento_dar": vencimento_dar,
            }

        for i, tid in enumerate(tickets, 1):
            if self.cancelar_operacao:
                return self.resetar_progresso()
            log_terminal(
                "PROGRESSO",
                f"Baixando anexos do ticket {i} de {len(tickets)}: #{tid}...",
            )
            t_data = self._api_pronto().obter_ticket(tid)
            if not t_data:
                self.log(f"[!] Ticket #{tid} não encontrado ou sem acesso.")
                continue

            uf_ticket_tag = self._identificar_uf(t_data)
            anexos_para_baixar = []

            if "description" in t_data:
                for match_url in re.findall(
                    r'https?://[^\s<>"]+attachment[^\s<>"]+', t_data["description"]
                ):
                    anexos_para_baixar.append(
                        {"file_name": f"anexo_{tid}.pdf", "content_url": match_url}
                    )

            for com in self._api_pronto().obter_comentarios(tid):
                anexos_para_baixar.extend(com.get("attachments", []))

            anexos_processados = []
            with ThreadPoolExecutor(max_workers=8) as executor:
                futuros = [
                    executor.submit(baixar_e_analisar, anexo, tid, uf_ticket_tag)
                    for anexo in anexos_para_baixar
                ]
                for futuro in as_completed(futuros):
                    res = futuro.result()
                    if res:
                        anexos_processados.append(res)

            tem_dar = any(
                item["is_dar"]
                for item in anexos_processados
                if not item["is_duplicado"]
            )
            tem_termo = any(
                item["is_termo"]
                for item in anexos_processados
                if not item["is_duplicado"]
            )

            em_quarentena = False
            if uf_ticket_tag == "AL":
                if (tem_dar and not tem_termo) or (tem_termo and not tem_dar):
                    em_quarentena = True
                    motivo = "Falta Termo" if tem_dar else "Falta Guia (DAR)"
                    self.log(
                        f"[⚠️ INCONSISTÊNCIA] Ticket #{tid}: {motivo}. Enviando para 'QUARENTENA'."
                    )

            # REGRA EXCLUSIVA AP: Só move para VENCIDAS se o DAR de imposto do AP estiver de fato vencido
            if uf_ticket_tag == "AP" or any(
                item.get("uf_final") == "AP" for item in anexos_processados
            ):
                tem_dar_vencido_ap = any(
                    item.get("is_vencido")
                    for item in anexos_processados
                    if item.get("uf_final") == "AP"
                    and item.get("is_dar")
                    and not item.get("is_duplicado")
                )
                for item in anexos_processados:
                    if item.get("uf_final") == "AP" and (
                        item.get("is_dar") or item.get("is_nota")
                    ):
                        item["is_vencido"] = tem_dar_vencido_ap

            for item in anexos_processados:
                estado_dir = item["uf_final"]
                subpasta_final = item["subpasta"]

                caminho_dir = determinar_diretorio_anexo(
                    pasta_destino,
                    estado_dir,
                    subpasta_final,
                    item["is_dar"],
                    item["is_nota"],
                    item["is_duplicado"],
                    item["is_vencido"],
                    em_quarentena,
                )
                Path(caminho_dir).mkdir(parents=True, exist_ok=True)

                caminho_arquivo = os.path.join(caminho_dir, item["nome_limpo"])
                contador = 1
                nome_base, ext = os.path.splitext(item["nome_limpo"])
                while os.path.exists(caminho_arquivo):
                    caminho_arquivo = os.path.join(
                        caminho_dir, f"{nome_base}_{contador}{ext}"
                    )
                    contador += 1

                with open(caminho_arquivo, "wb") as f:
                    f.write(item["conteudo"])

            self.log(
                f"[✓] Ticket #{tid} ({uf_ticket_tag}): {len(anexos_processados)} anexo(s) salvo(s) na estrutura do estado {uf_ticket_tag}."
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

            data_ticket = padronizar_data_ddmmyyyy(
                str(resp_ticket.get("created_at", ""))[:10]
            )
            texto_completo = str(resp_ticket.get("description", ""))
            uf_ticket_tag = self._identificar_uf(resp_ticket)

            pdfs_extraidos = []
            for comment in self._api_pronto().obter_comentarios(ticket_id):
                for anexo in comment.get("attachments", []):
                    nome_anexo = str(anexo["file_name"]).lower()
                    if nome_anexo.endswith(".pdf"):
                        req_pdf, status_dl = self._api_pronto().baixar_conteudo(
                            anexo["content_url"]
                        )
                        if req_pdf:
                            txt_pdf, _status_pdf = extrair_texto_pdf(req_pdf)
                            pdfs_extraidos.append((nome_anexo, txt_pdf, req_pdf))

            pdfs_extraidos.sort(key=lambda x: 0 if e_nota_fiscal(x[1], x[0]) else 1)

            uf_ticket = "GERAL"
            for _, txt_pdf, _ in pdfs_extraidos:
                uf_detectada = self._identificar_uf(None, txt_pdf)
                if uf_detectada != "GERAL":
                    uf_ticket = uf_detectada
                    break
            if uf_ticket == "GERAL":
                uf_ticket = uf_ticket_tag if uf_ticket_tag != "GERAL" else "AL"
            mapa_termo_cte, lista_ctes_ordenada = {}, []
            if uf_ticket == "AP":
                lista_ctes_ordenada = extrair_remessas_ap(texto_completo)
                for line in texto_completo.splitlines():
                    line_ctes = extrair_remessas_ap(line)
                    for t in re.findall(r"\b\d{6,15}\b", line):
                        if t not in mapa_termo_cte:
                            mapa_termo_cte[t] = []
                        mapa_termo_cte[t].extend(
                            cte for cte in line_ctes if cte not in mapa_termo_cte[t]
                        )
            else:
                termo_atual = "Não localizado"
                for num in re.findall(r"\b\d+\b", texto_completo):
                    if 6 <= len(num) <= 9:
                        termo_atual = num
                        mapa_termo_cte.setdefault(termo_atual, [])
                    elif len(num) >= 14:
                        mapa_termo_cte.setdefault(termo_atual, [])
                        if num not in mapa_termo_cte[termo_atual]:
                            mapa_termo_cte[termo_atual].append(num)
                        if num not in lista_ctes_ordenada:
                            lista_ctes_ordenada.append(num)

            nfe_map, dars_pdf_data = {}, []
            tem_dar_pdf, tem_termo_pdf = False, False
            ids_guias_ap = set()
            indices_guias_ap = {}

            for nome_anexo, txt_pdf, raw_bytes in pdfs_extraidos:
                uf_deste_pdf = self._identificar_uf(None, txt_pdf)
                if uf_deste_pdf == "GERAL":
                    uf_deste_pdf = uf_ticket

                if e_dar_documento(txt_pdf):
                    tem_dar_pdf = True
                if e_termo_documento(txt_pdf):
                    tem_termo_pdf = True

                # TRAVA EXCLUSIVA AP: Garante que a DANFE seja processada como nota e nunca entre em separar_guias_ap
                eh_nfe_ap = (uf_deste_pdf == "AP" or uf_ticket == "AP") and any(
                    k in txt_pdf.upper()
                    for k in ["DOCUMENTO AUXILIAR DA NOTA", "DANFE", "RECEBEMOS DE"]
                )

                if e_nota_fiscal(txt_pdf, nome_anexo) or eh_nfe_ap:
                    match_nfe = re.search(
                        r"NF-e[\s\n\r]+N[ºo\.]*\s*([\d\.]+)", txt_pdf, re.IGNORECASE
                    )
                    num_nota_limpo = match_nfe.group(1).strip() if match_nfe else ""
                    if not num_nota_limpo:
                        match_nfe_alt = re.search(
                            r"N[ºo\.]*\s*(\d{3}\.\d{3}\.\d{3}|\d{1,9})",
                            txt_pdf,
                            re.IGNORECASE,
                        )
                        num_nota_limpo = (
                            match_nfe_alt.group(1).strip() if match_nfe_alt else ""
                        )
                    if num_nota_limpo:
                        num_nota_limpo = formatar_numero_arquivo(num_nota_limpo)

                    for chave_nfe in extrair_chaves_nfe_pdf(txt_pdf, raw_bytes):
                        nfe_map[chave_nfe] = num_nota_limpo
                    continue

                if uf_deste_pdf == "AP":
                    for id_guia, bloco_guia in separar_guias_ap(txt_pdf):
                        repetida_no_lote = bool(id_guia and id_guia in ids_guias_ap)
                        historico_ap = self.memoria_termos.get(id_guia or "")
                        if id_guia:
                            ids_guias_ap.add(id_guia)
                        if repetida_no_lote:
                            for indice_linha in indices_guias_ap.get(id_guia, []):
                                linha_existente = dars_pdf_data[indice_linha]
                                dars_pdf_data[indice_linha] = (
                                    *linha_existente[:7],
                                    _marcar_status_guia_ap_processada(
                                        linha_existente[7]
                                    ),
                                )
                            continue

                        (
                            termo_ext,
                            pares_ext,
                            cbo_ext,
                            cb_ext,
                            venc_ext,
                            val_ext,
                            uf_ext,
                        ) = extrair_documento("AP", bloco_guia, nome_anexo, nfe_map)
                        status_ap = validar_chaves_ap(pares_ext, nfe_map)
                        if historico_ap:
                            status_ap = _marcar_status_guia_ap_processada(status_ap)
                        pares_ap = pares_ext or [("Sem Arquivo Válido", "Sem Número")]
                        indices_linhas_ap = []
                        for par_ap in pares_ap:
                            linha_ap = (
                                termo_ext,
                                [par_ap],
                                cbo_ext,
                                cb_ext,
                                padronizar_data_ddmmyyyy(venc_ext),
                                val_ext,
                                uf_ext,
                                status_ap,
                            )
                            dars_pdf_data.append(linha_ap)
                            indices_linhas_ap.append(len(dars_pdf_data) - 1)
                        if id_guia:
                            indices_guias_ap[id_guia] = indices_linhas_ap
                    continue

                dados_din = self.gerenciador_layouts.identificar_e_extrair(
                    txt_pdf, nome_anexo, pdf_bytes=raw_bytes
                )
                if dados_din and uf_deste_pdf not in ["AL", "AP", "AC", "MS"]:
                    termo_deste_pdf = dados_din.get("termo") or "Não localizado"
                    cod_barras_orig = dados_din.get("cod_barras_orig", "Sem Código")
                    cod_barras_pdf = dados_din.get("cod_barras", "Sem Código")
                    vencimento_pdf = padronizar_data_ddmmyyyy(
                        dados_din.get("vencimento", "Não informado")
                    )
                    valor_pdf = dados_din.get("valor", "Não informado")
                    pares_documento = dados_din.get("pares_documento", [])
                    uf_layout = dados_din.get("uf", uf_deste_pdf)

                    cte_extraido = dados_din.get("cte")
                    if cte_extraido and cte_extraido not in lista_ctes_ordenada:
                        lista_ctes_ordenada.append(cte_extraido)
                        mapa_termo_cte.setdefault(termo_deste_pdf, []).append(
                            cte_extraido
                        )

                    dars_pdf_data.append(
                        (
                            termo_deste_pdf,
                            pares_documento,
                            cod_barras_orig,
                            cod_barras_pdf,
                            vencimento_pdf,
                            valor_pdf,
                            uf_layout,
                            "OK",
                        )
                    )
                else:
                    termo_ext, pares_ext, cbo_ext, cb_ext, venc_ext, val_ext, uf_ext = (
                        extrair_documento(
                            uf_deste_pdf, txt_pdf, nome_anexo, nfe_map, raw_bytes
                        )
                    )
                    dars_pdf_data.append(
                        (
                            termo_ext,
                            pares_ext,
                            cbo_ext,
                            cb_ext,
                            padronizar_data_ddmmyyyy(venc_ext),
                            val_ext,
                            uf_ext,
                            "OK",
                        )
                    )

            status_conf = "OK"
            if uf_ticket == "AL":
                if tem_dar_pdf and not tem_termo_pdf:
                    status_conf = "INCOMPLETO: Falta Termo"
                elif tem_termo_pdf and not tem_dar_pdf:
                    status_conf = "INCOMPLETO: Falta Guia (DAR)"

            # MÁGICA EXCLUSIVA PARA AP: Liga Notas às Guias pela Chave no Zendesk
            mapa_chaves_termo_ap_zd = {}
            for t_pdf, p_doc, _, _, _, _, uf_layout, _ in dars_pdf_data:
                if uf_layout == "AP" and t_pdf and t_pdf != "Não localizado":
                    for ch, _ in p_doc:
                        if ch and ch != "Sem Arquivo Válido":
                            mapa_chaves_termo_ap_zd[ch] = t_pdf

            controles_ap = {
                str(item_ap[0])
                for item_ap in dars_pdf_data
                if item_ap[6] == "AP" and item_ap[0] and item_ap[0] != "Não localizado"
            }
            controles_al = {
                str(item_al[0])
                for item_al in dars_pdf_data
                if item_al[6] == "AL" and item_al[0] and item_al[0] != "Não localizado"
            }
            indice_guia_ap = 0
            with lock_termos:
                for idx, pdf in enumerate(dars_pdf_data):
                    (
                        termo_pdf,
                        pares,
                        cod_barras_orig,
                        cod_barras,
                        venc,
                        val,
                        uf_item,
                        status_item,
                    ) = pdf

                    # SÓ ATUA SE FOR AP: Usa a chave para achar a qual Guia esta nota pertence
                    if uf_item == "AP" and (
                        not termo_pdf or termo_pdf == "Não localizado"
                    ):
                        for ch, _ in pares:
                            if ch in mapa_chaves_termo_ap_zd:
                                termo_pdf = mapa_chaves_termo_ap_zd[ch]
                                break

                    ctes_associados = list(mapa_termo_cte.get(termo_pdf, []))
                    if uf_item == "AP":
                        if len(controles_ap) == 1 and lista_ctes_ordenada:
                            ctes_associados = list(lista_ctes_ordenada)
                        elif not ctes_associados and indice_guia_ap < len(
                            lista_ctes_ordenada
                        ):
                            ctes_associados = [lista_ctes_ordenada[indice_guia_ap]]
                        indice_guia_ap += 1
                    elif uf_item == "AL":
                        if len(controles_al) == 1 and lista_ctes_ordenada:
                            ctes_associados = list(lista_ctes_ordenada)
                        elif not ctes_associados and idx < len(lista_ctes_ordenada):
                            ctes_associados = [lista_ctes_ordenada[idx]]
                        ctes_unicos = list(dict.fromkeys(ctes_associados))
                        ordem_cte_ticket = {
                            cte: posicao
                            for posicao, cte in enumerate(lista_ctes_ordenada)
                        }
                        ctes_associados = sorted(
                            ctes_unicos,
                            key=lambda cte: ordem_cte_ticket.get(
                                cte, len(ordem_cte_ticket)
                            ),
                        )
                    elif not ctes_associados and idx < len(lista_ctes_ordenada):
                        ctes_associados = [lista_ctes_ordenada[idx]]

                    # REGRA EXCLUSIVA AP: Separa em linhas distintas por Chave de NF-e
                    if uf_item == "AP":
                        chave_nfe_ap = next(
                            (
                                ch
                                for ch, _ in pares
                                if ch and ch != "Sem Arquivo Válido"
                            ),
                            None,
                        )
                        if chave_nfe_ap:
                            chave_linha = f"AP::{termo_pdf}::{chave_nfe_ap}"
                        elif termo_pdf and termo_pdf != "Não localizado":
                            chave_linha = f"AP::{termo_pdf}::{idx}"
                        else:
                            chave_linha = f"AP::{ticket_id}::Linha_{idx}"
                    else:
                        chave_linha = termo_pdf

                    if (
                        uf_item == "AP"
                        and chave_linha in termos_map
                        and ticket_id not in termos_map[chave_linha].get("TICKET", [])
                        and any(
                            str(uf).strip().upper() == "AP"
                            for uf in termos_map[chave_linha].get("UF", [])
                        )
                    ):
                        status_item = _marcar_status_guia_ap_processada(
                            str(
                                termos_map[chave_linha].get(
                                    "STATUS CONFERÊNCIA", status_item or "OK"
                                )
                            )
                        )
                    if chave_linha not in termos_map:
                        termos_map[chave_linha] = {
                            "TERMO_REAL": termo_pdf,
                            "TICKET": [],
                            "UF": [],
                            "DATA": [],
                            "VENCIMENTO": [],
                            "VALOR": [],
                            "CTE": [],
                            "CHAVE ARQUIVO": [],
                            "DACTE": [],
                            "NÚMERO ARQUIVO": [],
                            "CODIGO BARRAS ORIGINAL": [],
                            "CODIGO BARRAS": [],
                            "CPF/CNPJ DA GUIA": [],
                            **{campo: [] for campo in AL_CAMPOS_PLANILHA},
                            "STATUS CONFERÊNCIA": status_item or status_conf,
                        }
                    termo_linha = chave_linha
                    for cte_associado in ctes_associados:
                        if cte_associado not in termos_map[termo_linha]["CTE"]:
                            termos_map[termo_linha]["CTE"].append(cte_associado)
                    doc_guia_ap = nfe_map.get(f"DOC_MS_{termo_pdf}", "")
                    if (
                        doc_guia_ap
                        and doc_guia_ap
                        not in termos_map[termo_linha]["CPF/CNPJ DA GUIA"]
                    ):
                        termos_map[termo_linha]["CPF/CNPJ DA GUIA"].append(doc_guia_ap)
                    if uf_item == "AL":
                        campos_al = nfe_map.get(f"AL_CAMPOS_{termo_pdf}", {})
                        for campo in AL_CAMPOS_PLANILHA:
                            valor_campo = limpar_texto_excel(campos_al.get(campo, ""))
                            if (
                                valor_campo
                                and valor_campo not in termos_map[termo_linha][campo]
                            ):
                                termos_map[termo_linha][campo].append(valor_campo)

                    termos_map[termo_linha]["TICKET"].append(ticket_id)
                    termos_map[termo_linha]["UF"].append(uf_item)
                    termos_map[termo_linha]["DATA"].append(data_ticket)
                    termos_map[termo_linha]["STATUS CONFERÊNCIA"] = (
                        status_item or status_conf
                    )
                    if venc != "Não informado":
                        termos_map[termo_linha]["VENCIMENTO"].append(
                            padronizar_data_ddmmyyyy(venc)
                        )
                    if val != "Não informado":
                        termos_map[termo_linha]["VALOR"].append(val)
                    if cod_barras_orig not in ["Sem Código", "Sem Código de Barras"]:
                        termos_map[termo_linha]["CODIGO BARRAS ORIGINAL"].append(
                            cod_barras_orig
                        )
                    if cod_barras not in ["Sem Código", "Sem Código de Barras"]:
                        termos_map[termo_linha]["CODIGO BARRAS"].append(cod_barras)

                    for chave, num_doc in pares:
                        chave_clean = re.sub(r"\D", "", str(chave or ""))
                        if len(chave_clean) == 44:
                            modelo = chave_clean[20:22]
                            if modelo == "57":
                                if chave_clean not in termos_map[termo_linha]["DACTE"]:
                                    termos_map[termo_linha]["DACTE"].append(chave_clean)
                            else:
                                if (
                                    chave_clean
                                    not in termos_map[termo_linha]["CHAVE ARQUIVO"]
                                ):
                                    termos_map[termo_linha]["CHAVE ARQUIVO"].append(
                                        chave_clean
                                    )

                        num_fmt = formatar_numero_arquivo(num_doc)
                        if (
                            num_fmt not in termos_map[termo_linha]["NÚMERO ARQUIVO"]
                            and num_fmt != "Sem Número"
                        ):
                            termos_map[termo_linha]["NÚMERO ARQUIVO"].append(num_fmt)

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
        self.log(
            f"[Pasta] Lendo PDFs recursivamente em pastas e subpastas de: {pasta_origem}..."
        )

        with self.lock:
            self.dados_em_memoria = []
        self.atualizar_tabela_gui()

        termos_map = {}
        try:
            arquivos_pdf = []
            for root, _, files in os.walk(pasta_origem):
                for file in files:
                    if file.lower().endswith(".pdf"):
                        arquivos_pdf.append(os.path.join(root, file))

            if not arquivos_pdf:
                return self.log(
                    "[!] Nenhum arquivo PDF encontrado na pasta ou nas subpastas."
                )

            self.log(
                f"[Pasta] Encontrados {len(arquivos_pdf)} arquivo(s) PDF para leitura..."
            )

            arquivos_pdf.sort(
                key=lambda path: (
                    0
                    if any(
                        "nota" in parte.lower() or "danfe" in parte.lower()
                        for parte in Path(path).parts
                    )
                    else 1
                )
            )

            nfe_map, dars_pasta_data = {}, []
            ids_guias_ap = set()
            indices_guias_ap_pasta = {}
            for i, caminho_pdf in enumerate(arquivos_pdf, 1):
                if self.cancelar_operacao:
                    return self.resetar_progresso()
                log_terminal(
                    "PROGRESSO",
                    f"Lendo PDF {i} de {len(arquivos_pdf)}: {os.path.basename(caminho_pdf)}...",
                )

                nome_arquivo = os.path.basename(caminho_pdf)
                try:
                    with open(caminho_pdf, "rb") as f_pdf:
                        raw_bytes = f_pdf.read()
                        txt_pdf, status_pdf = extrair_texto_pdf(raw_bytes)
                    if not txt_pdf:
                        self.log(
                            f"[!] Leitura local do arquivo '{nome_arquivo}': {status_pdf}"
                        )

                    uf_deste_pdf = self._identificar_uf(None, txt_pdf)

                    if e_nota_fiscal(txt_pdf, nome_arquivo):
                        match_nfe = re.search(
                            r"NF-e[\s\n\r]+N[ºo\.]*\s*([\d\.]+)", txt_pdf, re.IGNORECASE
                        )
                        match_nfe_alt = re.search(
                            r"N[ºo\.]*\s*(\d{3}\.\d{3}\.\d{3}|\d{1,9})",
                            txt_pdf,
                            re.IGNORECASE,
                        )
                        num_nota_limpo = (
                            match_nfe.group(1).strip()
                            if match_nfe
                            else (
                                match_nfe_alt.group(1).strip() if match_nfe_alt else ""
                            )
                        )
                        if num_nota_limpo:
                            num_nota_limpo = formatar_numero_arquivo(num_nota_limpo)
                        for chave_nfe in extrair_chaves_nfe_pdf(txt_pdf, raw_bytes):
                            nfe_map[chave_nfe] = num_nota_limpo
                        self.atualizar_progresso(i, len(arquivos_pdf))
                        continue

                    if uf_deste_pdf in ["AL", "AP", "AC", "MS"]:
                        if uf_deste_pdf == "AP":
                            for id_guia, bloco_guia in separar_guias_ap(txt_pdf):
                                repetida_no_lote = bool(
                                    id_guia and id_guia in ids_guias_ap
                                )
                                historico_ap = self.memoria_termos.get(id_guia or "")
                                if repetida_no_lote:
                                    for indice_linha in indices_guias_ap_pasta.get(
                                        id_guia, []
                                    ):
                                        linha_existente = dars_pasta_data[indice_linha]
                                        dars_pasta_data[indice_linha] = (
                                            *linha_existente[:8],
                                            _marcar_status_guia_ap_processada(
                                                linha_existente[8]
                                            ),
                                        )
                                    continue
                                if id_guia:
                                    ids_guias_ap.add(id_guia)
                                (
                                    termo_ext,
                                    pares_ext,
                                    cbo_ext,
                                    cb_ext,
                                    venc_ext,
                                    val_ext,
                                    uf_ext,
                                ) = extrair_documento(
                                    "AP", bloco_guia, nome_arquivo, nfe_map
                                )
                                status_ap = validar_chaves_ap(pares_ext, nfe_map)
                                if historico_ap:
                                    status_ap = _marcar_status_guia_ap_processada(
                                        status_ap
                                    )
                                pares_ap = pares_ext or [
                                    ("Sem Arquivo Válido", "Sem Número")
                                ]
                                indices_linhas_ap = []
                                for par_ap in pares_ap:
                                    linha_ap = (
                                        termo_ext,
                                        [par_ap],
                                        cbo_ext,
                                        cb_ext,
                                        padronizar_data_ddmmyyyy(venc_ext),
                                        val_ext,
                                        uf_ext,
                                        caminho_pdf,
                                        status_ap,
                                    )
                                    dars_pasta_data.append(linha_ap)
                                    indices_linhas_ap.append(len(dars_pasta_data) - 1)
                                if id_guia:
                                    indices_guias_ap_pasta[id_guia] = indices_linhas_ap
                        else:
                            (
                                termo_ext,
                                pares_ext,
                                cbo_ext,
                                cb_ext,
                                venc_ext,
                                val_ext,
                                uf_ext,
                            ) = extrair_documento(
                                uf_deste_pdf, txt_pdf, nome_arquivo, nfe_map, raw_bytes
                            )
                            dars_pasta_data.append(
                                (
                                    termo_ext,
                                    pares_ext,
                                    cbo_ext,
                                    cb_ext,
                                    padronizar_data_ddmmyyyy(venc_ext),
                                    val_ext,
                                    uf_ext,
                                    caminho_pdf,
                                    "",
                                )
                            )
                    else:
                        dados_din = self.gerenciador_layouts.identificar_e_extrair(
                            txt_pdf, nome_arquivo, pdf_bytes=raw_bytes
                        )
                        if dados_din:
                            termo_deste_pdf = dados_din.get("termo") or "Não localizado"
                            cod_barras_orig = dados_din.get(
                                "cod_barras_orig", "Sem Código"
                            )
                            cod_barras_pdf = dados_din.get("cod_barras", "Sem Código")
                            vencimento_pdf = padronizar_data_ddmmyyyy(
                                dados_din.get("vencimento", "Não informado")
                            )
                            valor_pdf = dados_din.get("valor", "Não informado")
                            pares_documento = dados_din.get("pares_documento", [])
                            uf_layout = dados_din.get("uf", uf_deste_pdf)
                            dars_pasta_data.append(
                                (
                                    termo_deste_pdf,
                                    pares_documento,
                                    cod_barras_orig,
                                    cod_barras_pdf,
                                    vencimento_pdf,
                                    valor_pdf,
                                    uf_layout,
                                    caminho_pdf,
                                    "",
                                )
                            )
                        else:
                            (
                                termo_ext,
                                pares_ext,
                                cbo_ext,
                                cb_ext,
                                venc_ext,
                                val_ext,
                                uf_ext,
                            ) = extrair_documento(
                                uf_deste_pdf, txt_pdf, nome_arquivo, nfe_map, raw_bytes
                            )
                            dars_pasta_data.append(
                                (
                                    termo_ext,
                                    pares_ext,
                                    cbo_ext,
                                    cb_ext,
                                    padronizar_data_ddmmyyyy(venc_ext),
                                    val_ext,
                                    uf_ext,
                                    caminho_pdf,
                                    "",
                                )
                            )

                except Exception as e:  # noqa: BLE001
                    self.log(f"[!] Erro ao abrir arquivo {nome_arquivo}: {e}")
                self.atualizar_progresso(i, len(arquivos_pdf))

            # MÁGICA EXCLUSIVA PARA AP: Mapa para unir Notas e Guias separadas através da Chave
            mapa_chaves_termo_ap = {}
            for t_pdf, p_doc, _, _, _, _, uf_layout, _, _ in dars_pasta_data:
                if uf_layout == "AP" and t_pdf and t_pdf != "Não localizado":
                    for ch, _ in p_doc:
                        if ch and ch != "Sem Arquivo Válido":
                            mapa_chaves_termo_ap[ch] = t_pdf

            for indice_item, pdf_item in enumerate(dars_pasta_data, 1):
                (
                    termo_pdf,
                    pares,
                    cod_barras_orig,
                    cod_barras_pdf,
                    vencimento_pdf,
                    valor_pdf,
                    uf_item,
                    full_path,
                    status_ap,
                ) = pdf_item

                # SÓ ATUA SE FOR AP: Se for Nota sem termo, puxa o termo da Guia usando a Chave!
                if uf_item == "AP" and (not termo_pdf or termo_pdf == "Não localizado"):
                    for ch, _ in pares:
                        if ch in mapa_chaves_termo_ap:
                            termo_pdf = mapa_chaves_termo_ap[ch]
                            break

                if not termo_pdf or termo_pdf == "Não localizado":
                    chave_map = (
                        f"ARQ_{hashlib.md5(full_path.encode('utf-8')).hexdigest()[:10]}"
                    )
                else:
                    chave_map = termo_pdf

                # Se for AP e continuar sem termo, mantém a separação antiga. Se achou, unifica!
                if uf_item == "AP" and (not termo_pdf or termo_pdf == "Não localizado"):
                    chave_map = f"AP::{full_path}::{indice_item}::Não_localizado"

                status_conf = (
                    status_ap
                    if uf_item == "AP"
                    else (
                        "GUIA JÁ PROCESSADA"
                        if termo_pdf in self.memoria_termos
                        else "OK"
                    )
                )
                if uf_item == "AL":
                    if cod_barras_pdf == "Sem Código" and termo_pdf != "Não localizado":
                        status_conf = "INCOMPLETO: Falta Guia (DAR)"
                    elif (
                        cod_barras_pdf != "Sem Código" and termo_pdf == "Não localizado"
                    ):
                        status_conf = "INCOMPLETO: Falta Termo"

                if chave_map not in termos_map:
                    termos_map[chave_map] = {
                        "TERMO_REAL": termo_pdf or "Não localizado",
                        "TICKET": ["Local"],
                        "UF": [uf_item],
                        "DATA": [datetime.now().strftime("%d/%m/%Y")],
                        "VENCIMENTO": [],
                        "VALOR": [],
                        "CTE": [],
                        "CHAVE ARQUIVO": [],
                        "DACTE": [],
                        "NÚMERO ARQUIVO": [],
                        "CODIGO BARRAS ORIGINAL": [],
                        "CODIGO BARRAS": [],
                        "CPF/CNPJ DA GUIA": [],
                        **{campo: [] for campo in AL_CAMPOS_PLANILHA},
                        "STATUS CONFERÊNCIA": status_conf,
                    }
                doc_guia_ap = nfe_map.get(f"DOC_MS_{termo_pdf}", "")
                if (
                    doc_guia_ap
                    and doc_guia_ap not in termos_map[chave_map]["CPF/CNPJ DA GUIA"]
                ):
                    termos_map[chave_map]["CPF/CNPJ DA GUIA"].append(doc_guia_ap)
                if uf_item == "AL":
                    campos_al = nfe_map.get(f"AL_CAMPOS_{termo_pdf}", {})
                    for campo in AL_CAMPOS_PLANILHA:
                        valor_campo = limpar_texto_excel(campos_al.get(campo, ""))
                        if (
                            valor_campo
                            and valor_campo not in termos_map[chave_map][campo]
                        ):
                            termos_map[chave_map][campo].append(valor_campo)

                if (
                    vencimento_pdf != "Não informado"
                    and vencimento_pdf not in termos_map[chave_map]["VENCIMENTO"]
                ):
                    termos_map[chave_map]["VENCIMENTO"].append(
                        padronizar_data_ddmmyyyy(vencimento_pdf)
                    )
                if (
                    valor_pdf != "Não informado"
                    and valor_pdf not in termos_map[chave_map]["VALOR"]
                ):
                    termos_map[chave_map]["VALOR"].append(valor_pdf)
                if cod_barras_orig not in ["Sem Código", "Sem Código de Barras"]:
                    termos_map[chave_map]["CODIGO BARRAS ORIGINAL"].append(
                        cod_barras_orig
                    )
                if cod_barras_pdf not in ["Sem Código", "Sem Código de Barras"]:
                    termos_map[chave_map]["CODIGO BARRAS"].append(cod_barras_pdf)

                for chave, num_doc in pares:
                    chave_clean = re.sub(r"\D", "", str(chave or ""))
                    if len(chave_clean) == 44:
                        modelo = chave_clean[20:22]
                        if modelo == "57":
                            if chave_clean not in termos_map[chave_map]["DACTE"]:
                                termos_map[chave_map]["DACTE"].append(chave_clean)
                        else:
                            if (
                                chave_clean
                                not in termos_map[chave_map]["CHAVE ARQUIVO"]
                            ):
                                termos_map[chave_map]["CHAVE ARQUIVO"].append(
                                    chave_clean
                                )

                    num_fmt = formatar_numero_arquivo(num_doc)
                    if (
                        num_fmt not in termos_map[chave_map]["NÚMERO ARQUIVO"]
                        and num_fmt != "Sem Número"
                    ):
                        termos_map[chave_map]["NÚMERO ARQUIVO"].append(num_fmt)

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
        campos = [
            "TICKET",
            "UF",
            "CPF/CNPJ DA GUIA",
            "DATA",
            "VENCIMENTO",
            "VALOR",
            "CTE",
            "CHAVE ARQUIVO",
            "DACTE",
            "NÚMERO ARQUIVO",
            "CODIGO BARRAS ORIGINAL",
            "CODIGO BARRAS",
            *AL_CAMPOS_PLANILHA,
            "STATUS CONFERÊNCIA",
            "DATA PROCESSAMENTO",
        ]
        processamento_atual = timestamp_processamento()

        with self.lock:
            for termo_key, data_dict in termos_map.items():
                termo_exibicao = data_dict.get("TERMO_REAL", termo_key)
                linha_individual = str(termo_key).startswith("AP::")

                if termo_exibicao not in self.memoria_termos:
                    self.memoria_termos[termo_exibicao] = {c: [] for c in campos}
                    self.memoria_termos[termo_exibicao]["TOMADOR"] = (
                        "Aguardando Conciliação"
                    )

                for c in campos:
                    if c not in self.memoria_termos[termo_exibicao]:
                        self.memoria_termos[termo_exibicao][c] = []
                if "TOMADOR" not in self.memoria_termos[termo_exibicao]:
                    self.memoria_termos[termo_exibicao]["TOMADOR"] = (
                        "Aguardando Conciliação"
                    )
                self.memoria_termos[termo_exibicao]["DATA PROCESSAMENTO"] = (
                    processamento_atual
                )

                ufs_atual = data_dict.get("UF", [])
                if isinstance(ufs_atual, str):
                    ufs_atual = [ufs_atual]
                if any(str(uf).strip().upper() == "AP" for uf in ufs_atual):
                    self.memoria_termos[termo_exibicao]["VALOR"] = []
                    self.memoria_termos[termo_exibicao]["CPF/CNPJ DA GUIA"] = []

                if "CHAVE ARQUIVO" in data_dict:
                    for ch in data_dict["CHAVE ARQUIVO"]:
                        if (
                            ch
                            not in self.memoria_termos[termo_exibicao]["CHAVE ARQUIVO"]
                        ):
                            self.memoria_termos[termo_exibicao]["CHAVE ARQUIVO"].append(
                                ch
                            )

                if "DACTE" in data_dict:
                    for dac in data_dict["DACTE"]:
                        if dac not in self.memoria_termos[termo_exibicao]["DACTE"]:
                            self.memoria_termos[termo_exibicao]["DACTE"].append(dac)

                if "NÚMERO ARQUIVO" in data_dict:
                    for num in data_dict["NÚMERO ARQUIVO"]:
                        num_fmt = formatar_numero_arquivo(num)
                        if (
                            num_fmt
                            not in self.memoria_termos[termo_exibicao]["NÚMERO ARQUIVO"]
                        ):
                            self.memoria_termos[termo_exibicao][
                                "NÚMERO ARQUIVO"
                            ].append(num_fmt)

                outros_campos = [
                    c
                    for c in campos
                    if c
                    not in (
                        "CHAVE ARQUIVO",
                        "DACTE",
                        "NÚMERO ARQUIVO",
                        "STATUS CONFERÊNCIA",
                    )
                ]
                for campo in outros_campos:
                    for val in data_dict.get(campo, []):
                        valores_a_adicionar = (
                            separar_valores_monetarios(val)
                            if campo == "VALOR"
                            else [val]
                        )
                        for valor_item in valores_a_adicionar:
                            val_clean = (
                                padronizar_data_ddmmyyyy(valor_item)
                                if campo in ["DATA", "VENCIMENTO"]
                                else (
                                    normalizar_valor_monetario(valor_item)
                                    if campo == "VALOR"
                                    else limpar_texto_excel(valor_item)
                                )
                            )
                            if (
                                val_clean
                                and val_clean != "Não informado"
                                and val_clean
                                not in self.memoria_termos[termo_exibicao][campo]
                            ):
                                if campo == "TICKET" and val_clean == "Local":
                                    continue
                                self.memoria_termos[termo_exibicao][campo].append(
                                    val_clean
                                )
                    mem_vals = list(self.memoria_termos[termo_exibicao][campo])
                    if campo == "CTE" and any(
                        str(uf).strip().upper() == "AL" for uf in ufs_atual
                    ):
                        ctes_do_termo = [
                            limpar_texto_excel(cte)
                            for cte in data_dict.get("CTE", [])
                            if cte and limpar_texto_excel(cte)
                        ]
                        mem_vals = list(dict.fromkeys(ctes_do_termo + mem_vals))
                        self.memoria_termos[termo_exibicao][campo] = mem_vals
                    if not linha_individual:
                        if (
                            campo == "TICKET"
                            and not mem_vals
                            and "Local" in data_dict.get("TICKET", [])
                        ):
                            data_dict["TICKET"] = ["Local"]
                        else:
                            data_dict[campo] = mem_vals

                self.memoria_termos[termo_exibicao]["STATUS CONFERÊNCIA"] = (
                    data_dict.get("STATUS CONFERÊNCIA", "OK")
                )

        self.salvar_memoria_diaria()
        cabecalho = [
            "TERMO/CONTROLE",
            "UF",
            "CPF/CNPJ DA GUIA",
            "TICKET",
            "STATUS CONFERÊNCIA",
            "CÓDIGO BARRAS ORIGINAL",
            "CÓDIGO BARRAS (44)",
            "DATA",
            "VENCIMENTO",
            "VALOR (R$)",
            "CTE / REMESSA",
            "TOMADOR",
            "NÚMERO ARQUIVO",
            "CHAVE ARQUIVO (55)",
            "DACTE (57)",
            "DATA PROCESSAMENTO",
            *AL_CAMPOS_PLANILHA,
        ]

        linhas_csv = []
        with self.lock:
            for termo_key, d in termos_map.items():
                termo_exibicao = d.get("TERMO_REAL", termo_key)

                datas_limpas = [
                    padronizar_data_ddmmyyyy(x)
                    for x in d["DATA"]
                    if x and str(x).strip()
                ]
                datas_unicas = list(dict.fromkeys(datas_limpas))
                data_str = ", ".join(datas_unicas) if datas_unicas else "Não Informado"

                ufs_limpas = [
                    limpar_texto_excel(x)
                    for x in d.get("UF", [])
                    if x and x.strip() and x != "GERAL"
                ]
                uf_str = ", ".join(dict.fromkeys(ufs_limpas)) if ufs_limpas else "GERAL"

                ctes_lista = [limpar_texto_excel(c) for c in d["CTE"] if c]
                cte_str = (
                    " ".join(dict.fromkeys(ctes_lista)) if ctes_lista else "Sem CTE"
                )
                cte_formatado = (
                    formatar_texto_excel(cte_str) if cte_str != "Sem CTE" else "Sem CTE"
                )

                cb_lista = [
                    limpar_texto_excel(cb)
                    for cb in d["CODIGO BARRAS"]
                    if cb and cb != "Sem Código"
                ]
                cb_unicos = list(dict.fromkeys(cb_lista))
                cb_valido = "Sem Código"
                if cb_unicos:
                    cb_arrecadacao = [
                        c for c in cb_unicos if c.startswith("8") and len(c) in (43, 44)
                    ]
                    cb_valido = cb_arrecadacao[0] if cb_arrecadacao else cb_unicos[0]
                cb_formatado = (
                    formatar_texto_excel(cb_valido)
                    if cb_valido != "Sem Código"
                    else "Sem Código"
                )

                cbo_lista = [
                    limpar_texto_excel(cb)
                    for cb in d["CODIGO BARRAS ORIGINAL"]
                    if cb and cb != "Sem Código"
                ]
                cbo_unicos = list(dict.fromkeys(cbo_lista))
                cbo_valido = "Sem Código"
                if cbo_unicos:
                    cbo_arrecadacao = [
                        c for c in cbo_unicos if re.sub(r"\D", "", c).startswith("8")
                    ]
                    cbo_valido = (
                        cbo_arrecadacao[0] if cbo_arrecadacao else cbo_unicos[0]
                    )
                cbo_formatado = (
                    formatar_texto_excel(cbo_valido)
                    if cbo_valido != "Sem Código"
                    else "Sem Código"
                )

                num_arq_lista = []
                for x in d.get("NÚMERO ARQUIVO", []):
                    if not x or not str(x).strip() or str(x).strip() == "Sem Número":
                        continue
                    num_fmt = formatar_numero_arquivo(x)
                    if num_fmt != "Sem Número":
                        if "AL" in uf_str.upper() and re.fullmatch(r"\d{1,9}", num_fmt):
                            num_fmt = str(int(num_fmt)) if num_fmt != "0" else "0"
                        num_arq_lista.append(num_fmt)
                num_arq_unicos = list(dict.fromkeys(num_arq_lista))
                num_arq_str = (
                    " ".join(num_arq_unicos) if num_arq_unicos else "Sem Número"
                )

                chave_arq_lista = [
                    limpar_texto_excel(x)
                    for x in d.get("CHAVE ARQUIVO", [])
                    if x and x.strip() and x != "Sem Arquivo Válido"
                ]
                chave_arq_unicas = list(dict.fromkeys(chave_arq_lista))
                chave_arq_str = (
                    formatar_texto_excel(" ".join(chave_arq_unicas))
                    if chave_arq_unicas
                    else "Sem Arquivo Válido"
                )

                dacte_lista = [
                    limpar_texto_excel(x)
                    for x in d.get("DACTE", [])
                    if x and x.strip() and x != "Sem DACTE"
                ]
                dacte_unicas = list(dict.fromkeys(dacte_lista))
                dacte_str = (
                    formatar_texto_excel(" ".join(dacte_unicas))
                    if dacte_unicas
                    else "Sem DACTE"
                )

                status_conf_raw = d.get("STATUS CONFERÊNCIA", "OK")
                status_conf = (
                    status_conf_raw[0]
                    if isinstance(status_conf_raw, list) and status_conf_raw
                    else (status_conf_raw if isinstance(status_conf_raw, str) else "OK")
                )

                vencs_limpos = [
                    padronizar_data_ddmmyyyy(v)
                    for v in d.get("VENCIMENTO", [])
                    if v and limpar_texto_excel(v) != "Não informado"
                ]
                vencs_unicos = list(dict.fromkeys(vencs_limpos))
                venc_str = ", ".join(vencs_unicos) if vencs_unicos else "Não informado"

                vals_limpos = [
                    normalizar_valor_monetario(valor)
                    for item_valor in d.get("VALOR", [])
                    for valor in separar_valores_monetarios(item_valor)
                    if limpar_texto_excel(valor) != "Não informado"
                ]
                vals_unicos = list(dict.fromkeys(vals_limpos))
                valor_str = ", ".join(vals_unicos) if vals_unicos else "Não informado"
                documentos_guia = [
                    limpar_texto_excel(valor)
                    for valor in d.get("CPF/CNPJ DA GUIA", [])
                    if valor and limpar_texto_excel(valor)
                ]
                documento_guia_str = " ".join(dict.fromkeys(documentos_guia))

                faltantes_item = []
                if termo_exibicao in ["Não localizado", "Sem Número", ""]:
                    faltantes_item.append("Termo")
                if cb_valido in ["Sem Código", ""]:
                    faltantes_item.append("Código de Barras")
                if venc_str in ["Não informado", ""]:
                    faltantes_item.append("Vencimento")
                if valor_str in ["Não informado", ""]:
                    faltantes_item.append("Valor")

                if status_conf == "OK" and faltantes_item:
                    status_conf = f"INCOMPLETO: Sem {', '.join(faltantes_item)}"

                item = {
                    "TERMO": termo_exibicao,
                    "UF": uf_str,
                    "CPF/CNPJ DA GUIA": documento_guia_str,
                    "TICKET": " ".join(
                        dict.fromkeys([limpar_texto_excel(x) for x in d["TICKET"]])
                    ),
                    "STATUS CONFERÊNCIA": status_conf,
                    "DATA": data_str,
                    "VENCIMENTO": venc_str,
                    "VALOR": valor_str,
                    "CTE": cte_formatado,
                    "CHAVE ARQUIVO": chave_arq_str,
                    "DACTE": dacte_str,
                    "NÚMERO ARQUIVO": num_arq_str,
                    "CODIGO BARRAS ORIGINAL": cbo_formatado,
                    "CODIGO BARRAS": cb_formatado,
                    "TOMADOR": self.memoria_termos.get(termo_exibicao, {}).get(
                        "TOMADOR", "Aguardando Conciliação"
                    ),
                    "DATA PROCESSAMENTO": self.memoria_termos.get(
                        termo_exibicao, {}
                    ).get("DATA PROCESSAMENTO", processamento_atual),
                }
                for campo in AL_CAMPOS_PLANILHA:
                    valores_campo = [
                        limpar_texto_excel(valor)
                        for valor in d.get(campo, [])
                        if valor and limpar_texto_excel(valor)
                    ]
                    item[campo] = " | ".join(dict.fromkeys(valores_campo))
                self.dados_em_memoria.append(item)
                linhas_csv.append(
                    [
                        item["TERMO"],
                        item["UF"],
                        formatar_texto_excel(item.get("CPF/CNPJ DA GUIA", "")),
                        item["TICKET"],
                        item["STATUS CONFERÊNCIA"],
                        item["CODIGO BARRAS ORIGINAL"],
                        item["CODIGO BARRAS"],
                        item["DATA"],
                        item["VENCIMENTO"],
                        item["VALOR"],
                        item["CTE"],
                        item["TOMADOR"],
                        item["NÚMERO ARQUIVO"],
                        item["CHAVE ARQUIVO"],
                        item["DACTE"],
                        item["DATA PROCESSAMENTO"],
                        *(item[campo] for campo in AL_CAMPOS_PLANILHA),
                    ]
                )

        try:
            caminho_gerado = salvar_planilha_multisheets(
                caminho_csv, cabecalho, linhas_csv, self.gerenciador_dedicados
            )
            self._gerar_resumo_dedicados(linhas_csv, cabecalho)
            self.atualizar_tabela_gui()
            self.log(
                f"[🏆] Relatório Gerado com {len(linhas_csv)} linha(s) em: {caminho_gerado}"
            )
        except Exception as e:
            self.log(f"[!] Falha ao gravar arquivo: {e}")

    def _atualizar_relatorio_zendesk_apos_conciliacao(self, caminho_csv: str):
        cabecalho = [
            "TERMO/CONTROLE",
            "UF",
            "CPF/CNPJ DA GUIA",
            "TICKET",
            "STATUS CONFERÊNCIA",
            "CÓDIGO BARRAS ORIGINAL",
            "CÓDIGO BARRAS (44)",
            "DATA",
            "VENCIMENTO",
            "VALOR (R$)",
            "CTE / REMESSA",
            "TOMADOR",
            "NÚMERO ARQUIVO",
            "CHAVE ARQUIVO (55)",
            "DACTE (57)",
            "DATA PROCESSAMENTO",
            *AL_CAMPOS_PLANILHA,
        ]

        with self.lock:
            dados_copia = [dict(item) for item in self.dados_em_memoria]

        linhas = []
        for item in dados_copia:
            cte_remessa = item.get("CTE / REMESSA")
            if limpar_texto_excel(cte_remessa or "") in ("", "Sem CTE"):
                cte_remessa = item.get("CTE", "")

            linhas.append(
                [
                    item.get("TERMO", ""),
                    item.get("UF", "GERAL"),
                    formatar_texto_excel(item.get("CPF/CNPJ DA GUIA", "")),
                    item.get("TICKET", ""),
                    item.get("STATUS CONFERÊNCIA", "OK"),
                    item.get("CODIGO BARRAS ORIGINAL", ""),
                    item.get("CODIGO BARRAS", ""),
                    padronizar_data_ddmmyyyy(item.get("DATA", "")),
                    padronizar_data_ddmmyyyy(item.get("VENCIMENTO", "")),
                    item.get("VALOR", ""),
                    cte_remessa or "Sem CTE",
                    item.get("TOMADOR", "Aguardando Conciliação"),
                    item.get("NÚMERO ARQUIVO", ""),
                    item.get("CHAVE ARQUIVO", ""),
                    item.get("DACTE", ""),
                    item.get("DATA PROCESSAMENTO", timestamp_processamento()),
                    *(item.get(campo, "") for campo in AL_CAMPOS_PLANILHA),
                ]
            )

        try:
            caminho_gerado = salvar_planilha_multisheets(
                caminho_csv, cabecalho, linhas, self.gerenciador_dedicados
            )
            self._gerar_resumo_dedicados(linhas, cabecalho)
            self.log(
                f"[Zendesk] Relatório de Tomadores atualizado e salvo: {caminho_gerado}"
            )
        except Exception as e:
            self.log(f"[!] Falha ao atualizar relatório após conciliação: {e}")

    @registrar_execucao("Consolidação de planilhas")
    def _acao_unificar_planilhas_arquivos(
        self, lista_arquivos: list[str], caminho_saida: str
    ):
        self.log(f"[Consolidar] Unindo {len(lista_arquivos)} planilhas...")
        linhas_unificadas, cabecalho = [], None
        for idx, caminho_arq in enumerate(lista_arquivos, 1):
            log_terminal(
                "PROGRESSO",
                f"Consolidando planilha {idx} de {len(lista_arquivos)}: {os.path.basename(caminho_arq)}...",
            )
            try:
                if caminho_arq.lower().endswith(".csv"):
                    with open(caminho_arq, mode="r", encoding="utf-8-sig") as f:
                        linhas = list(csv.reader(f, delimiter=";"))
                        if linhas:
                            if cabecalho is None:
                                cabecalho = linhas[0]
                            for row in linhas[1:]:
                                linhas_unificadas.append(
                                    [formatar_texto_excel(c) for c in row]
                                )
                else:
                    try:
                        import openpyxl

                        wb = openpyxl.load_workbook(caminho_arq, data_only=True)
                        try:
                            sheet = wb.active
                            if sheet is None:
                                raise RuntimeError(
                                    "A planilha não possui uma aba ativa"
                                )
                            linhas = list(sheet.iter_rows(values_only=True))
                            if linhas:
                                if cabecalho is None:
                                    cabecalho = [str(c or "") for c in linhas[0]]
                                for row in linhas[1:]:
                                    linhas_unificadas.append(
                                        [
                                            formatar_texto_excel(str(c or ""))
                                            for c in row
                                        ]
                                    )
                        finally:
                            wb.close()
                    except ImportError:
                        pass
            except Exception as e:  # noqa: BLE001
                print(f"[Erro Consolidação] Falha ao ler {caminho_arq}: {e}")
            self.atualizar_progresso(idx, len(lista_arquivos))

        if linhas_unificadas and cabecalho:
            caminho_gerado = salvar_planilha_multisheets(
                caminho_saida, cabecalho, linhas_unificadas, self.gerenciador_dedicados
            )
            self._gerar_resumo_dedicados(linhas_unificadas, cabecalho)
            self.log(f"[🏆] Salvo: {caminho_gerado}")
            self.exibir_mensagem(
                "info",
                "Sucesso",
                f"Planilhas unificadas!\n\nSalvo em: {caminho_gerado}",
            )
        else:
            self.log("[!] Falha na unificação.")

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

            linhas = []
            cabecalho = []

            # --- LEITURA DE ARQUIVOS CSV ---
            if caminho_arquivo.lower().endswith(".csv"):
                with open(caminho_arquivo, mode="r", encoding="utf-8-sig") as f:
                    leitor = list(csv.reader(f, delimiter=";"))
                    if leitor:
                        cabecalho = [str(c).strip().upper() for c in leitor[0]]
                        linhas = leitor[1:]

            # --- LEITURA DE ARQUIVOS EXCEL (.XLSX / .XLS) ---
            elif HAS_OPENPYXL:
                import openpyxl

                wb = openpyxl.load_workbook(caminho_arquivo, data_only=True)
                try:
                    abas_lidas = 0
                    dados_abas = []
                    for ws in wb.worksheets:
                        dados_aba = list(ws.iter_rows(values_only=True))
                        if not dados_aba:
                            continue

                        cabecalho_aba = [
                            str(c or "").strip().upper() for c in dados_aba[0]
                        ]
                        if not any(cabecalho_aba):
                            continue
                        dados_abas.append((cabecalho_aba, dados_aba[1:]))
                        abas_lidas += 1

                    colunas_unificadas = []
                    for cabecalho_aba, _ in dados_abas:
                        for nome in cabecalho_aba:
                            if nome and nome not in colunas_unificadas:
                                colunas_unificadas.append(nome)
                    cabecalho = colunas_unificadas

                    for cabecalho_aba, linhas_aba in dados_abas:
                        mapa_colunas = {
                            nome: indice
                            for indice, nome in enumerate(cabecalho_aba)
                            if nome
                        }
                        for linha_aba in linhas_aba:
                            linha_alinhada = [None] * len(cabecalho)
                            for indice, nome in enumerate(cabecalho):
                                indice_origem = mapa_colunas.get(nome)
                                if indice_origem is not None and indice_origem < len(
                                    linha_aba
                                ):
                                    linha_alinhada[indice] = linha_aba[indice_origem]
                            linhas.append(tuple(linha_alinhada))

                    nomes_identidade = {
                        "TERMO/CONTROLE",
                        "TICKET",
                        "CTE / REMESSA",
                        "NÚMERO ARQUIVO",
                        "CHAVE ARQUIVO (55)",
                        "DACTE (57)",
                    }
                    indices_identidade = [
                        indice
                        for indice, nome in enumerate(cabecalho)
                        if nome in nomes_identidade
                    ]
                    linhas_unicas = []
                    identidades_vistas = set()
                    for linha in linhas:
                        identidade = tuple(
                            limpar_texto_excel(str(linha[indice] or "")).strip().upper()
                            for indice in indices_identidade
                            if indice < len(linha)
                        )
                        identidade_completa = (
                            identidade
                            if any(identidade)
                            else tuple(str(valor or "") for valor in linha)
                        )
                        if identidade_completa not in identidades_vistas:
                            identidades_vistas.add(identidade_completa)
                            linhas_unicas.append(linha)
                    removidas = len(linhas) - len(linhas_unicas)
                    linhas = linhas_unicas

                    if abas_lidas:
                        self.log(
                            f"[Excel] {abas_lidas} aba(s) lida(s), {len(linhas)} registro(s) único(s) carregado(s); {removidas} duplicado(s) ignorado(s)."
                        )
                finally:
                    wb.close()
            else:
                return self.log(
                    "[!] Biblioteca 'openpyxl' não encontrada para ler .xlsx."
                )

            if not linhas or not cabecalho:
                return self.log("[!] Planilha vazia ou formato inválido.")

            # Mapeamento dinâmico de colunas
            idx_map = {}
            for i, col_name in enumerate(cabecalho):
                nome_clean = str(col_name).strip()
                if nome_clean in AL_CAMPOS_PLANILHA:
                    idx_map[nome_clean] = i
                elif "TERMO" in nome_clean or "CONTROLE" in nome_clean:
                    idx_map["TERMO"] = i
                elif (
                    ("CPF" in nome_clean and "CNPJ" in nome_clean)
                    and "R/S/U/V" not in nome_clean
                    and "EM R" not in nome_clean
                ):
                    idx_map["CPF/CNPJ DA GUIA"] = i
                elif "UF" in nome_clean:
                    idx_map["UF"] = i
                elif "TICKET" in nome_clean:
                    idx_map["TICKET"] = i
                elif "STATUS" in nome_clean:
                    idx_map["STATUS CONFERÊNCIA"] = i
                elif "ORIGINAL" in nome_clean:
                    idx_map["CODIGO BARRAS ORIGINAL"] = i
                elif "(44)" in nome_clean or (
                    "BARRAS" in nome_clean and "ORIGINAL" not in nome_clean
                ):
                    idx_map["CODIGO BARRAS"] = i
                elif "DATA PROCESSAMENTO" in nome_clean:
                    idx_map["DATA PROCESSAMENTO"] = i
                elif "DATA" in nome_clean:
                    idx_map["DATA"] = i
                elif "VENCIMENTO" in nome_clean:
                    idx_map["VENCIMENTO"] = i
                elif "VALOR" in nome_clean:
                    idx_map["VALOR"] = i
                elif (
                    "CTE / REMESSA" == nome_clean
                    or "CTE" == nome_clean
                    or "REMESSA" in nome_clean
                ):
                    idx_map["CTE / REMESSA"] = i
                elif "TOMADOR" in nome_clean:
                    idx_map["TOMADOR"] = i
                elif "NÚMERO ARQUIVO" in nome_clean:
                    idx_map["NÚMERO ARQUIVO"] = i
                elif "CHAVE" in nome_clean:
                    idx_map["CHAVE ARQUIVO"] = i
                elif "DACTE" in nome_clean:
                    idx_map["DACTE"] = i

            novos_dados = []
            termos_lidos = 0

            for row in linhas:
                if not any(row):
                    continue
                log_terminal(
                    "PROGRESSO",
                    f"Carregando registro {termos_lidos + 1} de {len(linhas)}...",
                )

                def get_val(key):
                    idx = idx_map.get(key, -1)
                    if idx != -1 and idx < len(row):
                        v_raw = row[idx]
                        if v_raw is None:
                            return ""
                        v_str = str(v_raw).strip()
                        if v_str.endswith(".0") and re.match(r"^\d+\.0$", v_str):
                            v_str = v_str[:-2]
                        return limpar_texto_excel(v_str)
                    return ""

                termo_val = get_val("TERMO")
                if not termo_val:
                    continue

                cte_val = get_val("CTE / REMESSA")
                if not cte_val:
                    cte_val = get_val("CTE")
                num_arq_val = get_val("NÚMERO ARQUIVO")

                item = {
                    "TERMO": termo_val,
                    "UF": get_val("UF") or "GERAL",
                    "CPF/CNPJ DA GUIA": get_val("CPF/CNPJ DA GUIA"),
                    "TICKET": get_val("TICKET"),
                    "STATUS CONFERÊNCIA": get_val("STATUS CONFERÊNCIA") or "OK",
                    "DATA": padronizar_data_ddmmyyyy(get_val("DATA")),
                    "VENCIMENTO": padronizar_data_ddmmyyyy(get_val("VENCIMENTO"))
                    or "Não informado",
                    "VALOR": get_val("VALOR") or "Não informado",
                    "CTE / REMESSA": cte_val if cte_val else "Sem CTE",
                    "CHAVE ARQUIVO": get_val("CHAVE ARQUIVO") or "Sem Arquivo Válido",
                    "DACTE": get_val("DACTE") or "Sem DACTE",
                    "NÚMERO ARQUIVO": num_arq_val if num_arq_val else "Sem Número",
                    "CODIGO BARRAS ORIGINAL": get_val("CODIGO BARRAS ORIGINAL")
                    or "Sem Código",
                    "CODIGO BARRAS": get_val("CODIGO BARRAS") or "Sem Código",
                    "TOMADOR": get_val("TOMADOR") or "Aguardando Conciliação",
                    "DATA PROCESSAMENTO": get_val("DATA PROCESSAMENTO")
                    or timestamp_processamento(),
                    **{campo: get_val(campo) for campo in AL_CAMPOS_PLANILHA},
                }
                novos_dados.append(item)
                termos_lidos += 1

            with self.lock:
                self.dados_em_memoria = novos_dados

                for item in novos_dados:
                    termo = item["TERMO"]
                    if termo not in self.memoria_termos:
                        self.memoria_termos[termo] = {
                            k: []
                            for k in [
                                "TICKET",
                                "UF",
                                "CPF/CNPJ DA GUIA",
                                "DATA",
                                "VENCIMENTO",
                                "VALOR",
                                "CTE / REMESSA",
                                "CHAVE ARQUIVO",
                                "DACTE",
                                "NÚMERO ARQUIVO",
                                "CODIGO BARRAS ORIGINAL",
                                "CODIGO BARRAS",
                                *AL_CAMPOS_PLANILHA,
                            ]
                        }

                    self.memoria_termos[termo]["STATUS CONFERÊNCIA"] = item[
                        "STATUS CONFERÊNCIA"
                    ]
                    self.memoria_termos[termo]["TOMADOR"] = item["TOMADOR"]
                    self.memoria_termos[termo]["DATA PROCESSAMENTO"] = item[
                        "DATA PROCESSAMENTO"
                    ]

                    for k in [
                        "TICKET",
                        "UF",
                        "CPF/CNPJ DA GUIA",
                        "DATA",
                        "VENCIMENTO",
                        "VALOR",
                        "CTE / REMESSA",
                        "CHAVE ARQUIVO",
                        "DACTE",
                        "NÚMERO ARQUIVO",
                        "CODIGO BARRAS ORIGINAL",
                        "CODIGO BARRAS",
                        *AL_CAMPOS_PLANILHA,
                    ]:
                        val = item.get(k, "")
                        partes = (
                            separar_valores_monetarios(val)
                            if k == "VALOR"
                            else (
                                [p.strip() for p in val.split(",")]
                                if k in ["DATA", "VENCIMENTO", "UF"]
                                else (
                                    [val.strip()]
                                    if k in AL_CAMPOS_PLANILHA
                                    else [p.strip() for p in val.split(" ")]
                                )
                            )
                        )
                        for p in partes:
                            p_fmt = (
                                padronizar_data_ddmmyyyy(p)
                                if k in ["DATA", "VENCIMENTO"]
                                else (
                                    normalizar_valor_monetario(p) if k == "VALOR" else p
                                )
                            )
                            if (
                                p_fmt
                                and p_fmt not in self.memoria_termos[termo][k]
                                and p_fmt
                                not in [
                                    "Sem CTE",
                                    "Sem Código",
                                    "Sem Arquivo Válido",
                                    "Sem DACTE",
                                    "Sem Número",
                                    "Não informado",
                                ]
                            ):
                                self.memoria_termos[termo][k].append(p_fmt)

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

    @registrar_execucao(
        "Conciliação Fraction Exclusiva por CTe e Validação Pós-Leitura"
    )
    def _acao_conciliar_tomador(self, clipboard_inicial: str = ""):
        with self.lock:
            base_vazia = not bool(self.dados_em_memoria)
        if base_vazia:
            return self.log(
                "[!] Base vazia na tela. Extraia os dados da conferência primeiro."
            )

        cookie_invalido = False
        itens_pendentes = []

        with self.lock:
            for item in self.dados_em_memoria:
                uf_item = str(item.get("UF", "")).strip().upper()
                status_item = str(item.get("STATUS CONFERÊNCIA", "")).strip().upper()
                if uf_item == "AP" and status_item.startswith("INCOMPLETO: CHAVE"):
                    termo_ignorado = item.get("TERMO", "Desconhecido")
                    self.log(
                        f"[⚠️ CONFERÊNCIA MANUAL] Guia AP #{termo_ignorado}: "
                        f"{item.get('STATUS CONFERÊNCIA', 'divergência de chave')}. "
                        "A pesquisa no Fraction continuará."
                    )

                candidatos_cte = []

                # 1. BUSCA EXCLUSIVA: Extrai unicamente o CTe da coluna 'CTE / REMESSA' da planilha (ex: 18201500500971)
                cte_raw = (
                    str(item.get("CTE / REMESSA") or item.get("CTE") or "")
                    .replace("Sem CTE", "")
                    .strip()
                )
                for c_limpo in re.findall(r"(?<!\d)\d{6,15}(?!\d)", cte_raw):
                    if c_limpo not in candidatos_cte:
                        candidatos_cte.append(c_limpo)

                # Fallback: Se a coluna CTE / REMESSA estiver vazia, tenta extrair da Chave DACTE (57)
                if not candidatos_cte:
                    dacte_raw = (
                        str(item.get("DACTE", "")).replace("Sem DACTE", "").strip()
                    )
                    for dac in re.split(r"[\s,]+", dacte_raw):
                        dac_limpo = re.sub(r"\D", "", dac)
                        if len(dac_limpo) == 44 and dac_limpo[20:22] == "57":
                            if dac_limpo not in candidatos_cte:
                                candidatos_cte.append(dac_limpo)

                # REGRA ESTRITA: O número do Termo JAMAIS entra na busca. Se não houver CTe, ignora a busca no Fraction.
                if candidatos_cte:
                    itens_pendentes.append((item, candidatos_cte))
                else:
                    termo_ignorado = item.get("TERMO", "Desconhecido")
                    self.log(
                        f"[i] Termo #{termo_ignorado} -> Busca no Fraction ignorada (Sem CTe na coluna 'CTE / REMESSA')."
                    )

        if not itens_pendentes:
            return self.log(
                "[!] Nenhum CTe válido encontrado na coluna CTE para buscar no Fraction."
            )

        total_itens = len(itens_pendentes)
        concluidos, encontrados, divergencias, sem_resultado = 0, 0, 0, 0
        estatisticas_lock = threading.Lock()

        cookie_limpo = limpar_e_formatar_cookie(self.cookie_jadlog)

        _thread_local = threading.local()

        def consultar_e_ler_pagina_fraction(cte_code):
            """Pesquisa exclusivamente pelo CTe no Fraction Web enviando o parâmetro do filtro Conhecimento e lê os dados da tela."""
            nonlocal cookie_invalido
            if self.cancelar_operacao or cookie_invalido:
                return cte_code, None, {}

            # 1. Verifica cache em memória
            with self.lock:
                if cte_code in self.ctes_consultados_cache:
                    c_val = self.ctes_consultados_cache[cte_code]
                    if isinstance(c_val, tuple) and c_val[0] is not None:
                        return cte_code, c_val[0], c_val[1]

            if not hasattr(_thread_local, "session"):
                s = requests.Session()
                s.headers.update(
                    {
                        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
                        "Content-Type": "application/x-www-form-urlencoded",
                        "Cookie": cookie_limpo,
                    }
                )
                _thread_local.session = s

            session = _thread_local.session

            urls_para_testar = [
                "https://jadlog.com.br/FractionWeb/jad/pesquisar",
                "https://jadlog.com.br/FractionWeb/jad/consulta",
                "https://jadlog.com.br/FractionWeb/jad/consultaGeral",
                "https://jadlog.com.br/FractionWeb/jad/consultar",
                "https://jadlog.com.br/FractionWeb/jad/tracking",
                "https://jadlog.com.br/FractionWeb/jad/",
                "https://jadlog.com.br/FractionWeb/pesquisar.jad",
                "https://jadlog.com.br/FractionWeb/jad/tracking.jadlog",
            ]

            formulario_localizado = False
            for url in urls_para_testar:
                try:
                    pagina = session.get(url, timeout=15)
                    if (
                        "login" in pagina.url.lower()
                        or "j_spring_security_check" in pagina.text
                    ):
                        cookie_invalido = True
                        self.log(
                            "[ERRO] Sessão/Cookie Fraction expirado! Atualize a credencial."
                        )
                        return cte_code, "COOKIE_EXPIRADO", {}
                    if pagina.status_code >= 400:
                        continue

                    soup_form = BeautifulSoup(pagina.content, "html.parser")
                    for form in soup_form.find_all("form"):
                        preparado = _preparar_formulario_fraction(
                            form, pagina.url, cte_code
                        )
                        if not preparado:
                            continue
                        formulario_localizado = True
                        action, method, campos = preparado
                        if method == "post":
                            resp = session.post(
                                action,
                                data=campos,
                                headers={"Referer": pagina.url},
                                timeout=15,
                            )
                        else:
                            resp = session.get(
                                action,
                                params=campos,
                                headers={"Referer": pagina.url},
                                timeout=15,
                            )

                        if (
                            "login" in resp.url.lower()
                            or "j_spring_security_check" in resp.text
                        ):
                            cookie_invalido = True
                            self.log(
                                "[ERRO] Sessão/Cookie Fraction expirado! Atualize a credencial."
                            )
                            return cte_code, "COOKIE_EXPIRADO", {}
                        if resp.status_code >= 400:
                            continue

                        soup = BeautifulSoup(resp.content, "html.parser")
                        txt = re.sub(r"\s+", " ", soup.get_text(separator=" "))

                        # Se a resposta foi uma tabela de resultados com link para detalhes do CTE
                        if "Tomador" not in txt:
                            for link in soup.find_all("a", href=True):
                                href = str(link.get("href", "") or "")
                                texto_link = str(link.get_text()).strip()
                                if (
                                    cte_code in href
                                    or cte_code in texto_link
                                    or re.search(
                                        r"detalhe|tracking|visualizar",
                                        href,
                                        re.IGNORECASE,
                                    )
                                ):
                                    url_det = urljoin(str(resp.url), href)
                                    try:
                                        resp_det = session.get(url_det, timeout=15)
                                        soup_det = BeautifulSoup(
                                            resp_det.content, "html.parser"
                                        )
                                        txt_det = re.sub(
                                            r"\s+",
                                            " ",
                                            soup_det.get_text(separator=" "),
                                        )
                                        if "Tomador" in txt_det:
                                            soup = soup_det
                                            txt = txt_det
                                            break
                                    except Exception:
                                        pass

                        # 3. Extração do Tomador (suporta grid tabular da Imagem 1 e tela detalhada da Imagem 2)
                        tomador_encontrado, rem_tab, dest_tab, docs_tab = (
                            extrair_dados_tabela_fraction(soup, txt, cte_code)
                        )

                        # Se encontrou os dados na tela do Fraction
                        if tomador_encontrado and len(tomador_encontrado) > 2:
                            m_rem = re.search(
                                r"Nome\s*:\s*(.*?)(?=\s*End\.|\s*Cidade/UF|\s*CNPJ)",
                                txt,
                                re.IGNORECASE,
                            )
                            remetente = m_rem.group(1).strip() if m_rem else ""

                            m_dest = re.search(
                                r"Dest\.\s*:\s*(.*?)(?=\s*End\.|\s*Cidade/UF|\s*CNPJ)",
                                txt,
                                re.IGNORECASE,
                            )
                            destinatario = m_dest.group(1).strip() if m_dest else ""

                            documentos_brutos = re.findall(
                                r"(?:Inscri[çc][ãa]o\s+Estadual|IE|CNPJ|CPF)"
                                r"(?:\s*/\s*(?:CNPJ|CPF))?\s*[:\-]?\s*([\d\.\/-]{5,25})",
                                txt,
                                re.IGNORECASE,
                            )
                            documentos_limpos = sorted(
                                {
                                    re.sub(r"\D", "", c)
                                    for c in documentos_brutos
                                    if 5 <= len(re.sub(r"\D", "", c)) <= 18
                                }
                            )

                            chaves_fraction = extrair_chaves_nfe_pdf(txt)
                            dactes_fraction = [
                                chave
                                for chave in chaves_fraction
                                if chave[20:22] == "57"
                            ]
                            m_dacte = re.search(
                                r"Dacte\s*:\s*(\b\d{44}\b)", txt, re.IGNORECASE
                            )
                            dacte_rotulado = m_dacte.group(1).strip() if m_dacte else ""
                            if dacte_rotulado and dacte_rotulado[20:22] == "57":
                                dacte = dacte_rotulado
                            else:
                                dacte = dactes_fraction[0] if dactes_fraction else ""

                            numeros_notas = [
                                re.sub(r"\D", "", n)
                                for n in re.findall(
                                    r"NF\s*:\s*(\d{1,9})", txt, re.IGNORECASE
                                )
                            ]
                            chaves_nfe = [
                                chave
                                for chave in chaves_fraction
                                if chave[20:22] == "55"
                            ]
                            numeros_nota_por_chave = [
                                chave[25:34].lstrip("0") or "0" for chave in chaves_nfe
                            ]
                            numeros_notas = list(
                                dict.fromkeys(numeros_notas + numeros_nota_por_chave)
                            )

                            dados_fraction = {
                                "cte_consultado": cte_code,
                                "tomador": tomador_encontrado,
                                "remetente": remetente,
                                "destinatario": destinatario,
                                "cnpjs": documentos_limpos,
                                "chaves_nfe": list(set(chaves_nfe)),
                                "dacte": dacte,
                                "dactes": dactes_fraction,
                                "numeros_notas": list(set(numeros_notas)),
                                "texto_completo": txt,
                            }

                            with self.lock:
                                self.ctes_consultados_cache[cte_code] = (
                                    tomador_encontrado,
                                    dados_fraction,
                                )
                            return cte_code, tomador_encontrado, dados_fraction
                except requests.RequestException as erro:
                    self.log(
                        f"[AVISO FRACTION] Falha ao consultar CTe {cte_code}: {type(erro).__name__}"
                    )

            # Fallback direto: consulta via endpoint clássico de tracking
            try:
                resp_direto = session.post(
                    "https://jadlog.com.br/FractionWeb/jad/tracking",
                    data={
                        "cte": cte_code,
                        "conhecimento": cte_code,
                        "remessa": cte_code,
                    },
                    headers={"Referer": "https://jadlog.com.br/FractionWeb/jad/"},
                    timeout=12,
                )
                if (
                    resp_direto.status_code == 200
                    and "login" not in resp_direto.url.lower()
                ):
                    soup_dir = BeautifulSoup(resp_direto.content, "html.parser")
                    txt_dir = re.sub(r"\s+", " ", soup_dir.get_text(separator=" "))
                    tomador_direto, rem_dir, dest_dir, docs_dir = (
                        extrair_dados_tabela_fraction(soup_dir, txt_dir, cte_code)
                    )
                    if tomador_direto and len(tomador_direto) > 2:
                        dados_fraction = {
                            "cte_consultado": cte_code,
                            "tomador": tomador_direto,
                            "remetente": "",
                            "destinatario": "",
                            "cnpjs": [],
                            "chaves_nfe": [],
                            "dacte": "",
                            "dactes": [],
                            "numeros_notas": [],
                            "texto_completo": txt_dir,
                        }
                        with self.lock:
                            self.ctes_consultados_cache[cte_code] = (
                                tomador_direto,
                                dados_fraction,
                            )
                        return cte_code, tomador_direto, dados_fraction
            except Exception:
                pass

            if not formulario_localizado:
                self.log(
                    f"[AVISO FRACTION] Não foi localizado o formulário de pesquisa (Consulta Geral ou Procurar) "
                    f"para o CTe {cte_code}; confirme a sessão e cookie Fraction."
                )
            return cte_code, None, {}

        def processar_e_validar_cruzamento(pair):
            nonlocal concluidos, encontrados, divergencias, sem_resultado
            item_ref, ctes = pair
            if self.cancelar_operacao or cookie_invalido:
                return

            ctes_limpos = []
            for c in ctes:
                txt_c = str(c or "").replace("Sem CTE", "").strip()
                if "e+" in txt_c.lower():
                    try:
                        txt_c = f"{Decimal(txt_c):.0f}"
                    except:
                        pass
                if txt_c.endswith(".0"):
                    txt_c = txt_c[:-2]
                for n_achado in re.findall(
                    r"\b\d{6,15}\b", re.sub(r"[^\d\s]", " ", txt_c)
                ):
                    if n_achado not in ctes_limpos:
                        ctes_limpos.append(n_achado)

            resultados_fraction = []
            # Mantém estritamente o mesmo fluxo de consultas sem alterar rede
            for cte_code in ctes_limpos:
                time.sleep(random.uniform(0.8, 1.5))
                for tentativa in range(1, 3):
                    _, tom_res, meta_res = consultar_e_ler_pagina_fraction(cte_code)
                    if tom_res == "COOKIE_EXPIRADO":
                        return
                    if tom_res:
                        resultados_fraction.append((cte_code, tom_res, meta_res))
                        break
                    time.sleep(1.0)

            if not resultados_fraction:
                with estatisticas_lock:
                    sem_resultado += 1
                concluidos += 1
                self.atualizar_progresso(concluidos, total_itens)
                return

            cte_confirmado, tomador_fraction, dados_frac = resultados_fraction[0]
            with estatisticas_lock:
                encontrados += 1

            txt = dados_frac.get("texto_completo", "")

            # 1. EXTRAÇÃO DE EMITENTE E DESTINATÁRIO DO TEXTO DO FRACTION
            m_rem = re.search(
                r"Remetente\b([\s\S]*?)(?:Destinat[áa]rio|Local\s+de\s+Coleta|Informa[çc][õo]es|$)",
                txt,
                re.IGNORECASE,
            )
            txt_rem = m_rem.group(1) if m_rem else ""
            m_r_nome = re.search(
                r"Nome\s*:\s*(.*?)(?=\s*End\.|\s*Cidade|\s*Bairro|\s*Cep|\s*Telefone|\s*CNPJ|\s*CPF|\s*IE|$)",
                txt_rem,
                re.IGNORECASE,
            )
            rem_nome = (
                m_r_nome.group(1).strip()
                if m_r_nome
                else (dados_frac.get("rem_nome") or dados_frac.get("remetente", ""))
            )
            m_r_cnpj = re.search(
                r"(?:CNPJ|CPF)\s*:\s*([\d\.\/-]+)", txt_rem, re.IGNORECASE
            )
            rem_cnpj = (
                re.sub(r"\D", "", m_r_cnpj.group(1))
                if m_r_cnpj
                else dados_frac.get("rem_cnpj", "")
            )
            m_r_ie = re.search(r"IE\s*:\s*([\d\.\/-]+)", txt_rem, re.IGNORECASE)
            rem_ie = (
                re.sub(r"\D", "", m_r_ie.group(1))
                if m_r_ie
                else dados_frac.get("rem_ie", "")
            )

            m_dest = re.search(
                r"Destinat[áa]rio\b([\s\S]*?)(?:Local\s+de\s+Coleta|Informa[çc][õo]es|Nota\s+Fiscal|$)",
                txt,
                re.IGNORECASE,
            )
            txt_dest = m_dest.group(1) if m_dest else ""
            m_d_nome = re.search(
                r"(?:Dest\.|Nome)\s*:\s*(.*?)(?=\s*End\.|\s*Cidade|\s*Bairro|\s*Cep|\s*Telefone|\s*CNPJ|\s*CPF|\s*IE|$)",
                txt_dest,
                re.IGNORECASE,
            )
            dest_nome = (
                m_d_nome.group(1).strip()
                if m_d_nome
                else (dados_frac.get("dest_nome") or dados_frac.get("destinatario", ""))
            )
            m_d_cnpj = re.search(
                r"(?:CNPJ|CPF)\s*:\s*([\d\.\/-]+)", txt_dest, re.IGNORECASE
            )
            dest_cnpj = (
                re.sub(r"\D", "", m_d_cnpj.group(1))
                if m_d_cnpj
                else dados_frac.get("dest_cnpj", "")
            )
            m_d_ie = re.search(r"IE\s*:\s*([\d\.\/-]+)", txt_dest, re.IGNORECASE)
            dest_ie = (
                re.sub(r"\D", "", m_d_ie.group(1))
                if m_d_ie
                else dados_frac.get("dest_ie", "")
            )

            dacte_frac = dados_frac.get("dacte", "")

            def campo_vazio(chave):
                v = str(item_ref.get(chave, "")).strip()
                return v in (
                    "",
                    "None",
                    "nan",
                    "Sem DACTE",
                    "Sem Número",
                    "Sem Arquivo Válido",
                    "Sem Código",
                    "Não informado",
                    "Aguardando Conciliação",
                )

            # 2. PREENCHIMENTO SEM SOBRESCREVER (COLUNAS Q, R, S, T, U, V E DACTE)
            # Os dados do Fraction são gravados mesmo se a guia for para Quarentena
            with self.lock:
                item_ref["TOMADOR"] = tomador_fraction

                if campo_vazio("DACTE") and dacte_frac:
                    item_ref["DACTE"] = formatar_texto_excel(dacte_frac)

                # Colunas Q, R, S (Emitente / Remetente)
                if campo_vazio("EMITENTE - NOME/RAZÃO SOCIAL") and rem_nome:
                    item_ref["EMITENTE - NOME/RAZÃO SOCIAL"] = rem_nome
                if campo_vazio("EMITENTE - CPF/CNPJ") and rem_cnpj:
                    item_ref["EMITENTE - CPF/CNPJ"] = re.sub(r"\D", "", str(rem_cnpj))
                if campo_vazio("EMITENTE - IE") and rem_ie:
                    item_ref["EMITENTE - IE"] = re.sub(r"\D", "", str(rem_ie))

                # Colunas T, U, V (Destinatário)
                if campo_vazio("DESTINATÁRIO - NOME/RAZÃO SOCIAL") and dest_nome:
                    item_ref["DESTINATÁRIO - NOME/RAZÃO SOCIAL"] = dest_nome
                if campo_vazio("DESTINATÁRIO - CPF/CNPJ") and dest_cnpj:
                    item_ref["DESTINATÁRIO - CPF/CNPJ"] = re.sub(
                        r"\D", "", str(dest_cnpj)
                    )
                if campo_vazio("DESTINATÁRIO - IE") and dest_ie:
                    item_ref["DESTINATÁRIO - IE"] = re.sub(r"\D", "", str(dest_ie))

                termo_chave = item_ref.get("TERMO")
                if termo_chave in self.memoria_termos:
                    self.memoria_termos[termo_chave]["TOMADOR"] = tomador_fraction
                    if dacte_frac:
                        self.memoria_termos[termo_chave]["DACTE"] = [dacte_frac]
                    for col_extra in [
                        "EMITENTE - NOME/RAZÃO SOCIAL",
                        "EMITENTE - CPF/CNPJ",
                        "EMITENTE - IE",
                        "DESTINATÁRIO - NOME/RAZÃO SOCIAL",
                        "DESTINATÁRIO - CPF/CNPJ",
                        "DESTINATÁRIO - IE",
                    ]:
                        if item_ref.get(col_extra):
                            self.memoria_termos[termo_chave][col_extra] = [
                                item_ref[col_extra]
                            ]

            # 3. LÓGICA DE VALIDAÇÃO (CRUZAMENTO SEGURO)
            # Reúne todos os documentos do Fraction (incluindo CNPJ embutido na NF-e)
            docs_fraction = set(dados_frac.get("cnpjs", []))
            for d in [rem_cnpj, rem_ie, dest_cnpj, dest_ie]:
                d_c = re.sub(r"\D", "", str(d))
                if len(d_c) >= 5:
                    docs_fraction.add(d_c)

            for ch in dados_frac.get("chaves_nfe", []):
                if len(ch) == 44 and ch[20:22] == "55":
                    docs_fraction.add(ch[6:20])

            doc_guia_c = re.sub(
                r"\D", "", str(item_ref.get("CPF/CNPJ DA GUIA", "")).strip()
            )

            # Documentos das Colunas R, S, U, V da Planilha
            docs_r_s_u_v = {
                re.sub(r"\D", "", str(item_ref.get(c, "")))
                for c in [
                    "EMITENTE - CPF/CNPJ",
                    "EMITENTE - IE",
                    "DESTINATÁRIO - CPF/CNPJ",
                    "DESTINATÁRIO - IE",
                ]
                if len(re.sub(r"\D", "", str(item_ref.get(c, "")))) >= 5
            }

            # Regra da Coluna W: confere se a Coluna C bate com R, S, U ou V OU com o Fraction
            col_w_bateu = (
                (doc_guia_c in docs_r_s_u_v) if (doc_guia_c and docs_r_s_u_v) else False
            )
            fraction_doc_bateu = (
                bool((docs_r_s_u_v | {doc_guia_c}) & docs_fraction)
                if docs_fraction
                else False
            )
            doc_bateu = col_w_bateu or fraction_doc_bateu

            # Validação da Chave NF-e
            chaves_guia = set(
                re.findall(r"\b\d{44}\b", str(item_ref.get("CHAVE ARQUIVO", "")))
            )
            chaves_frac = set(dados_frac.get("chaves_nfe", []))
            chave_bateu = (
                bool(chaves_guia & chaves_frac)
                if (chaves_guia and chaves_frac)
                else True
            )

            # Validação do Número NF-e (descarta número de Termo)
            termo_limpo = re.sub(r"\D", "", str(item_ref.get("TERMO", "")))
            numeros_guia = [
                re.sub(r"\D", "", n).lstrip("0") or "0"
                for n in re.findall(
                    r"(?<!\d)\d{1,9}(?!\d)", str(item_ref.get("NÚMERO ARQUIVO", ""))
                )
                if re.sub(r"\D", "", n) != termo_limpo
            ]
            numeros_fraction = {
                re.sub(r"\D", "", str(n)).lstrip("0") or "0"
                for n in dados_frac.get("numeros_notas", [])
                if str(n).strip()
            }
            num_bateu = (
                any(n in numeros_fraction for n in numeros_guia)
                if (numeros_guia and numeros_fraction)
                else True
            )

            # 4. ATUALIZAÇÃO DO STATUS DE CONFERÊNCIA
            motivos = []
            if not doc_bateu and doc_guia_c:
                motivos.append(
                    f"Doc Guia ({doc_guia_c}) não confere com R/S/U/V nem com CTe"
                )
            if not chave_bateu:
                motivos.append("Chave NF-e divergente do CTe")
            if not num_bateu and numeros_guia and numeros_fraction:
                motivos.append("Número NF-e divergente")

            with self.lock:
                st_atual = str(item_ref.get("STATUS CONFERÊNCIA", "OK"))
                if not motivos:
                    if st_atual in ["OK", "Aguardando Conciliação", ""]:
                        item_ref["STATUS CONFERÊNCIA"] = "VALIDADO NO FRACTION"
                    self.log(
                        f"[✓ VALIDADO] CTe {cte_confirmado} -> Tomador: {item_ref['TOMADOR']}"
                    )
                else:
                    status_erro = f"DIVERGÊNCIA CTI ({' | '.join(motivos)})"
                    item_ref["STATUS CONFERÊNCIA"] = status_erro
                    self.log(f"[⚠️ DIVERGÊNCIA] CTe {cte_confirmado}: {status_erro}")
                    with estatisticas_lock:
                        divergencias += 1

            concluidos += 1
            self.atualizar_progresso(concluidos, total_itens)

        if self.cookie_jadlog and not self.cancelar_operacao:
            self.log(
                "[Fraction Pro] 1º Pesquisando CTe -> 2º Lendo Página Fraction -> 3º Validando CNPJ, NF e DACTE..."
            )
            with ThreadPoolExecutor(max_workers=1) as executor:
                futuros = [
                    executor.submit(processar_e_validar_cruzamento, p)
                    for p in itens_pendentes
                ]
                for futuro in as_completed(futuros):
                    if cookie_invalido or self.cancelar_operacao:
                        break

        if cookie_invalido:
            self.log(
                "[!] Sessão/Cookie expirado na Jadlog. Atualize a credencial na tela principal."
            )

        self.log(
            f"[📊 RESUMO CONCILIAÇÃO] Total: {total_itens} | Encontrados: {encontrados} | Divergências: {divergencias} | Sem resultado: {sem_resultado}"
        )
        self.atualizar_tabela_gui()
        self.salvar_memoria_diaria()
        self.atualizar_progresso(100, 100)

    @registrar_execucao("Salvamento do relatório final")
    def _acao_salvar_relatorio_final(self, caminho_final: str):
        with self.lock:
            if not self.dados_em_memoria:
                return self.log("[!] Processe os tickets antes de salvar.")
            dados_copia = list(self.dados_em_memoria)

        cabecalho = [
            "TERMO/CONTROLE",
            "UF",
            "CPF/CNPJ DA GUIA",
            "TICKET",
            "STATUS CONFERÊNCIA",
            "CÓDIGO BARRAS ORIGINAL",
            "CÓDIGO BARRAS (44)",
            "DATA",
            "VENCIMENTO",
            "VALOR (R$)",
            "CTE / REMESSA",
            "TOMADOR",
            "NÚMERO ARQUIVO",
            "CHAVE ARQUIVO (55)",
            "DACTE (57)",
            "DATA PROCESSAMENTO",
            *AL_CAMPOS_PLANILHA,
        ]
        linhas = [
            [
                i.get("TERMO", ""),
                i.get("UF", "GERAL"),
                formatar_texto_excel(i.get("CPF/CNPJ DA GUIA", "")),
                i.get("TICKET", ""),
                i.get("STATUS CONFERÊNCIA", "OK"),
                i.get("CODIGO BARRAS ORIGINAL", ""),
                i.get("CODIGO BARRAS", ""),
                padronizar_data_ddmmyyyy(i.get("DATA", "")),
                padronizar_data_ddmmyyyy(i.get("VENCIMENTO", "")),
                i.get("VALOR", ""),
                (
                    i.get("CTE / REMESSA")
                    if limpar_texto_excel(i.get("CTE / REMESSA", ""))
                    not in ("", "Sem CTE")
                    else i.get("CTE", "")
                ),
                i.get("TOMADOR", "Não Conciliado"),
                i.get("NÚMERO ARQUIVO", ""),
                i.get("CHAVE ARQUIVO (55)") or i.get("CHAVE ARQUIVO", ""),
                i.get("DACTE (57)") or i.get("DACTE", ""),
                i.get("DATA PROCESSAMENTO", timestamp_processamento()),
                *(i.get(campo, "") for campo in AL_CAMPOS_PLANILHA),
            ]
            for i in dados_copia
        ]

        try:
            caminho_gerado = salvar_planilha_multisheets(
                caminho_final, cabecalho, linhas, self.gerenciador_dedicados
            )
            self._gerar_resumo_dedicados(linhas, cabecalho)
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
        ctk.CTkFrame(container, height=2, fg_color="#CBD5E1").pack(
            fill="x", pady=5, padx=15
        )

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


# ==========================================
# JANELA UNIFICAR GUIA + TERMO POR TOMADOR
# ==========================================
class JanelaUnificarTomador(ctk.CTkToplevel):
    def __init__(self, parent, app_gui):
        super().__init__(parent)
        self.app_gui = app_gui
        self.title("📄 Unificador Arquivos (Cliente)")
        self.geometry("620x520")
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
            text="Unificação Selecionada por Cliente",
            font=("Segoe UI", 16, "bold"),
            text_color="#D31145",
        ).pack(anchor="w", padx=20, pady=(15, 5))
        ctk.CTkLabel(
            container,
            text="Escolha um cliente/tomador para procurar as Guias (DAR) e Termos correspondentes e uni-los em um único arquivo PDF.",
            font=("Segoe UI", 10),
            text_color="#334155",
            justify="left",
            wraplength=540,
        ).pack(anchor="w", padx=20, pady=(0, 15))

        tomadores_unicos = set()
        with self.app_gui.lock:
            for item in self.app_gui.dados_em_memoria:
                tom = str(item.get("TOMADOR", "")).strip()
                if tom and tom not in [
                    "Aguardando Conciliação",
                    "Não Conciliado",
                    "Não Encontrado",
                    "Pendente",
                ]:
                    partes = [p.strip() for p in tom.split(",")]
                    tomadores_unicos.update(partes)

        lista_tomadores = sorted(list(tomadores_unicos))
        if not lista_tomadores:
            lista_tomadores = ["Nenhum tomador conciliado encontrado"]

        ctk.CTkLabel(
            container,
            text="1. Selecione o Cliente / Tomador:",
            font=("Segoe UI", 10, "bold"),
        ).pack(anchor="w", padx=20, pady=(5, 2))
        self.combo_tomador = ctk.CTkComboBox(
            container,
            values=lista_tomadores,
            width=540,
            height=35,
            fg_color="#FFFFFF",
            text_color="#000000",
        )
        self.combo_tomador.pack(padx=20, pady=(0, 10))
        if lista_tomadores:
            self.combo_tomador.set(lista_tomadores[0])

        ctk.CTkLabel(
            container,
            text="2. Pasta de Origem dos PDFs Baixados:",
            font=("Segoe UI", 10, "bold"),
        ).pack(anchor="w", padx=20, pady=(5, 2))
        f_orig = ctk.CTkFrame(container, fg_color="transparent")
        f_orig.pack(fill="x", padx=20, pady=(0, 10))
        self.ent_origem = ctk.CTkEntry(
            f_orig, fg_color="#FFFFFF", text_color="#000000", height=32
        )
        self.ent_origem.insert(0, self.app_gui.ultimo_dir_base)
        self.ent_origem.pack(side="left", fill="x", expand=True, padx=(0, 5))
        ctk.CTkButton(
            f_orig,
            text="📂 Selecionar",
            width=100,
            fg_color="#1976D2",
            command=self.selecionar_origem,
        ).pack(side="right")

        ctk.CTkLabel(
            container,
            text="3. Pasta para Salvar PDFs Unificados:",
            font=("Segoe UI", 10, "bold"),
        ).pack(anchor="w", padx=20, pady=(5, 2))
        f_dest = ctk.CTkFrame(container, fg_color="transparent")
        f_dest.pack(fill="x", padx=20, pady=(0, 15))
        self.ent_destino = ctk.CTkEntry(
            f_dest, fg_color="#FFFFFF", text_color="#000000", height=32
        )
        self.ent_destino.insert(
            0, os.path.join(self.app_gui.ultimo_dir_base, "UNIFICADOS_CLIENTE")
        )
        self.ent_destino.pack(side="left", fill="x", expand=True, padx=(0, 5))
        ctk.CTkButton(
            f_dest,
            text="📂 Selecionar",
            width=100,
            fg_color="#1976D2",
            command=self.selecionar_destino,
        ).pack(side="right")

        btn_exec = BotaoArredondado3D(
            container,
            text="⚡ UNIFICAR GUIAS DO CLIENTE",
            width=540,
            height=40,
            depth=6,
            cor_base="#475569",
            cor_hover="#64748B",
            cor_sombra="#1E293B",
            bg_app="#F1F5F9",
            command=self.executar_unificacao,
        )
        btn_exec.pack(pady=(10, 15))

    def selecionar_origem(self):
        p = filedialog.askdirectory(
            title="Selecione a Pasta dos PDFs Baixados",
            initialdir=self.app_gui.ultimo_dir_base,
        )
        if p:
            self.ent_origem.delete(0, tk.END)
            self.ent_origem.insert(0, p)

    def selecionar_destino(self):
        p = filedialog.askdirectory(
            title="Selecione a Pasta de Destino",
            initialdir=self.app_gui.ultimo_dir_base,
        )
        if p:
            self.ent_destino.delete(0, tk.END)
            self.ent_destino.insert(0, p)

    def executar_unificacao(self):
        tomador_sel = self.combo_tomador.get().strip()
        pasta_orig = self.ent_origem.get().strip()
        pasta_dest = self.ent_destino.get().strip()

        if not tomador_sel or tomador_sel == "Nenhum tomador conciliado encontrado":
            return messagebox.showwarning(
                "Atenção", "Selecione um Cliente/Tomador válido!"
            )
        if not os.path.exists(pasta_orig):
            return messagebox.showwarning(
                "Atenção", "Selecione uma Pasta de Origem válida!"
            )

        termos_cliente = set()
        with self.app_gui.lock:
            for item in self.app_gui.dados_em_memoria:
                tom = str(item.get("TOMADOR", ""))
                termo = str(item.get("TERMO", ""))
                if tomador_sel in tom and termo and termo != "Não localizado":
                    termos_cliente.add(termo)

        if not termos_cliente:
            return messagebox.showwarning(
                "Atenção",
                f"Nenhum Termo registrado na memória para o cliente '{tomador_sel}'.",
            )

        self.destroy()
        threading.Thread(
            target=self._processar_unificacao_thread,
            args=(tomador_sel, termos_cliente, pasta_orig, pasta_dest),
            daemon=True,
        ).start()

    def _processar_unificacao_thread(
        self, tomador, termos_cliente, pasta_orig, pasta_dest
    ):
        self.app_gui.log(
            f"[Unificação] Iniciando junção de Guias + Termos para o cliente: '{tomador}'..."
        )

        arquivos_encontrados = []
        for root, _, files in os.walk(pasta_orig):
            for file in files:
                if file.lower().endswith(".pdf"):
                    arquivos_encontrados.append(os.path.join(root, file))

        if not arquivos_encontrados:
            return self.app_gui.log(
                "[!] Nenhum PDF encontrado na pasta de origem para unificar."
            )

        agrupamento = {
            t: {"dars": [], "termos": [], "outros": []} for t in termos_cliente
        }

        for path_pdf in arquivos_encontrados:
            try:
                nome_arq = os.path.basename(path_pdf)
                with open(path_pdf, "rb") as f:
                    content_bytes = f.read()

                txt_pdf, _ = extrair_texto_pdf(content_bytes)
                if not txt_pdf:
                    continue

                termo_encontrado = extrair_numero_termo_pdf(txt_pdf, nome_arq)
                if termo_encontrado in agrupamento:
                    is_dar = e_dar_documento(txt_pdf)
                    is_termo = e_termo_documento(txt_pdf)

                    if is_dar:
                        agrupamento[termo_encontrado]["dars"].append(
                            (nome_arq, content_bytes)
                        )
                    elif is_termo:
                        agrupamento[termo_encontrado]["termos"].append(
                            (nome_arq, content_bytes)
                        )
                    else:
                        agrupamento[termo_encontrado]["outros"].append(
                            (nome_arq, content_bytes)
                        )
            except Exception as e:
                print(f"[Erro] Falha ao agrupar arquivo {path_pdf}: {e}")

        pasta_quarentena = os.path.join(pasta_dest, "QUARENTENA")
        sucessos = 0

        for termo_num, grupo in agrupamento.items():
            dars = grupo["dars"]
            termos = grupo["termos"]

            if dars and termos:
                os.makedirs(pasta_dest, exist_ok=True)
                list_to_merge = [dars[0][1], termos[0][1]]
                pdf_mesclado = mesclar_pdfs(list_to_merge)

                nome_unificado = f"Guia_Termo_{termo_num}.pdf"
                caminho_out = os.path.join(pasta_dest, nome_unificado)

                with open(caminho_out, "wb") as f_out:
                    f_out.write(pdf_mesclado)

                sucessos += 1
                self.app_gui.log(
                    f"[✓] Cliente '{tomador}': 1 Guia + 1 Termo do Controle #{termo_num} unificados em '{nome_unificado}'."
                )
            else:
                os.makedirs(pasta_quarentena, exist_ok=True)
                faltante = (
                    "TERMO"
                    if dars
                    else ("DAR" if termos else "AMBOS (Nenhum PDF encontrado)")
                )
                self.app_gui.log(
                    f"[!] INCOMPLETO para cliente '{tomador}' (Controle #{termo_num}): Falta {faltante}. Salvando em 'QUARENTENA'."
                )

                for f_nome, f_bytes in dars + termos + grupo["outros"]:
                    caminho_out = os.path.join(pasta_quarentena, f_nome)
                    with open(caminho_out, "wb") as f_out:
                        f_out.write(f_bytes)

        self.app_gui.log(
            f"[🏆] UNIFICAÇÃO CONCLUÍDA! {sucessos} documento(s) unificado(s) salvos em: {pasta_dest}"
        )
        self.app_gui.atualizar_progresso(100, 100)


if __name__ == "__main__":
    log_terminal("INÍCIO", "Aplicativo Automação Total JadLog iniciando.")
    app = ZendeskAppGUI()
    log_terminal("CONCLUÍDO", "Aplicativo encerrado.")
