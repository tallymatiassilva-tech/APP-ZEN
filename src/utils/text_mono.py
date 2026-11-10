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


def formatar_numero_arquivo_legado(valor: str) -> str:
    v = limpar_texto_excel(str(valor or ""))
    if not v or v in ["Sem Número", "Sem Arquivo Válido"]:
        return "Sem Número"
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
    return " ".join(dict.fromkeys(out)) if out else "Sem Número"


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


def padronizar_data_ddmmyyyy_legado(val_data: object) -> str:
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
        ano_formatado = f"20{ano}" if len(ano) == 2 else ano
        datas_formatadas.append(
            f"{dia.zfill(2)}/{mes.zfill(2)}/{ano_formatado}"
        )

    return ", ".join(dict.fromkeys(datas_formatadas))


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
    texto = str(valor or "").strip()
    if not texto or texto in ("Nao informado", "Não informado"):
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
