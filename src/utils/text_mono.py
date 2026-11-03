"""Text, date and monetary helpers. No fiscal behavior changed."""

import re
from datetime import datetime
from decimal import Decimal, InvalidOperation


def limpar_texto_excel(valor: str) -> str:
    v = str(valor or "").strip()
    v = re.sub(r'^=\s*"([^"]*)"$', r"\1", v)
    while v.startswith("'"):
        v = v[1:]
    return v.strip()


def formatar_texto_excel(valor: str) -> str:
    v = limpar_texto_excel(valor)
    if not v:
        return ""
    if v in ["Sem Codigo", "Sem CTE", "Sem Arquivo Valido", "Sem Numero"]:
        return v
    if re.match(r"^[0-9\s/\.-]+$", v) and len(re.sub(r"\D", "", v)) >= 4:
        return f'="{v}"'
    return v


def formatar_numero_arquivo(valor: str) -> str:
    v = limpar_texto_excel(str(valor or ""))
    if not v or v in ["Sem Numero", "Sem Arquivo Valido"]:
        return "Sem Numero"
    out = []
    for p in re.split(r"[\s,]+", v):
        p = p.strip()
        if not p:
            continue
        d = re.sub(r"\D", "", p)
        if d and len(d) <= 9:
            out.append(d.zfill(9))
        elif d:
            out.append(d)
        else:
            out.append(p)
    return " ".join(dict.fromkeys(out)) if out else "Sem Numero"


def padronizar_data_ddmmyyyy(val) -> str:
    t = str(val or "").strip()
    if t in ["Nao informado", "Nao Informado", "Sem Data", ""]:
        return "Nao informado"
    found = re.findall(r"\b(\d{1,2})[/-](\d{1,2})[/-](\d{2,4})\b", t)
    if not found:
        return t
    res = []
    for d, m, y in found:
        y = f"20{y}" if len(y) == 2 else y
        res.append(f"{d.zfill(2)}/{m.zfill(2)}/{y}")
    return ", ".join(dict.fromkeys(res))


def documento_esta_vencido(vencimento: str) -> bool:
    hoje = datetime.now().date()
    for part in str(vencimento or "").split(","):
        try:
            if datetime.strptime(part.strip(), "%d/%m/%Y").date() < hoje:
                return True
        except ValueError:
            continue
    return False


def normalizar_valor_monetario(valor) -> str:
    t = str(valor or "").replace("R$", "").replace(" ", "").strip()
    if "," in t:
        t = t.replace(".", "").replace(",", ".")
    try:
        d = Decimal(t).quantize(Decimal("0.01"))
    except (InvalidOperation, ValueError):
        return str(valor or "").strip()
    return f"{d:.2f}".replace(".", ",")


def separar_valores_monetarios(valor) -> list[str]:
    t = str(valor or "").strip()
    if not t or t == "Nao informado":
        return []
    pat = re.compile(r"(?<!\d)(?:\d{1,3}(?:\.\d{3})+|\d+),\d{2}(?!\d)")
    vals = pat.findall(t)
    if vals:
        return list(dict.fromkeys(vals))
    return [t]
