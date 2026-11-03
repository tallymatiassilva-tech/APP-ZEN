# src/services/pdf_service.py
"""Leitura, recorte e mesclagem de PDF. Sem regra fiscal de UF."""

from __future__ import annotations

import io
import os
import shutil
import sys
from typing import Any

import pypdf

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

    if getattr(sys, "frozen", False):
        BASE_DIR = os.path.dirname(sys.executable)
    else:
        # Este arquivo fica em src/services. O Tesseract portátil fica na raiz do app,
        # igual ao script único. Três níveis acima: services -> src -> raiz.
        BASE_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

    candidatos_tesseract = [
        os.path.join(BASE_DIR, "Tesseract-OCR", "tesseract.exe"),
        os.path.join(BASE_DIR, "Tesseract-OCR", "tesseract"),
        os.path.join(os.getcwd(), "Tesseract-OCR", "tesseract.exe"),
        os.path.join(os.getcwd(), "Tesseract-OCR", "tesseract"),
        shutil.which("tesseract"),
    ]

    tesseract_local_exe = next((c for c in candidatos_tesseract if c and os.path.exists(c)), None)
    if tesseract_local_exe:
        pytesseract.pytesseract.tesseract_cmd = tesseract_local_exe
        tessdata_local_dir = os.path.join(os.path.dirname(tesseract_local_exe), "tessdata")
        if os.path.exists(tessdata_local_dir):
            os.environ["TESSDATA_PREFIX"] = tessdata_local_dir
        HAS_OCR = True
        print(f"[OCR Portátil] Tesseract carregado: {tesseract_local_exe}")
    else:
        HAS_OCR = False
        print("[OCR] Tesseract não encontrado no ambiente local nem no PATH. OCR desabilitado.")
except ImportError:
    HAS_OCR = False
    print("[OCR] Módulos de OCR não disponíveis. OCR desabilitado.")


def extrair_texto_por_caixa(
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
    except Exception as e:
        print(f"[Erro Crop BoundingBox] {e}")
    return ""


def extrair_texto_pdf(pdf_bytes: bytes) -> tuple[str, str]:
    if not pdf_bytes:
        return "", "Conteúdo do PDF vazio."
    texto = ""

    if HAS_PDFPLUMBER:
        try:
            with pdfplumber.open(io.BytesIO(pdf_bytes)) as pdf:
                for page in pdf.pages:
                    extracted = page.extract_text(layout=True)
                    if extracted:
                        texto += extracted + "\n"
            texto = texto.strip()
        except Exception as e:
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
        except Exception:
            pass

    if not texto and HAS_OCR:
        try:
            images = convert_from_bytes(pdf_bytes)
            for img in images:
                extracted = pytesseract.image_to_string(img, lang="por")
                if extracted:
                    texto += extracted + "\n"
            texto = texto.strip()
        except Exception as e:
            print(f"[Aviso] Falha no OCR: {e}")

    if not texto:
        return "", "PDF sem texto extraível mesmo com OCR."

    return texto, "OK"


def mesclar_pdfs(pdf_bytes_list: list[bytes]) -> bytes:
    writer = pypdf.PdfWriter()
    for idx, b in enumerate(pdf_bytes_list):
        try:
            reader = pypdf.PdfReader(io.BytesIO(b))
            for page in reader.pages:
                writer.add_page(page)
        except Exception as e:
            print(f"[Aviso] Falha ao ler bloco PDF #{idx} para mesclagem: {e}")
    out = io.BytesIO()
    writer.write(out)
    return out.getvalue()
