"""Helpers for preparing Zendesk authentication values."""

import re


def limpar_e_formatar_cookie(valor: str) -> str:
    texto = str(valor or "").strip()
    if (texto.startswith('"') and texto.endswith('"')) or (
        texto.startswith("'") and texto.endswith("'")
    ):
        texto = texto[1:-1].strip()
    match = re.search(
        r'(?:-H\s+["\']?Cookie:\s*|Cookie:\s*)([^;\r\n]+)',
        texto,
        re.IGNORECASE,
    )
    if match:
        texto = match.group(1).strip()
    elif texto.lower().startswith("cookie:"):
        texto = texto[7:].strip()
    if "=" not in texto and len(texto) > 10:
        texto = f"JSESSIONID={texto}"
    return texto
