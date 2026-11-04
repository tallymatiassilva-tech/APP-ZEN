import re
from dataclasses import dataclass

MODELO_NFE = "55"


def so_digitos(valor) -> str:
    return re.sub(r"\D", "", str(valor or ""))


def modelo(chave) -> str:
    d = so_digitos(chave)
    return d[20:22] if len(d) == 44 else ""


@dataclass(frozen=True)
class CodigoBarras:
    original: str
    digitos48: str
    codigo44: str


def ler_codigo_barras(campo26: str) -> CodigoBarras:
    original = str(campo26 or "").strip()
    blocos = original.split()
    if len(blocos) != 4:
        raise ValueError(f"campo 26: esperados 4 blocos, encontrados {len(blocos)}")
    limpos = [so_digitos(b) for b in blocos]
    for i, b in enumerate(limpos, start=1):
        if len(b) != 12:
            raise ValueError(f"campo 26, bloco {i}: {len(b)} digitos, esperados 12")
    return CodigoBarras(
        original=original,
        digitos48="".join(limpos),
        codigo44="".join(b[:-1] for b in limpos),
    )


def _candidatos_44(texto: str) -> list:
    achados = re.findall(r"\d[\d\s.\-/]{40,80}\d", str(texto or ""))
    return [d for d in (so_digitos(b) for b in achados) if len(d) == 44]


def ler_chave_nfe(campo24: str) -> str:
    for d in _candidatos_44(campo24):
        if modelo(d) == MODELO_NFE:
            return d
    return ""


def conferir_origens(codigo: CodigoBarras, chave: str) -> None:
    if len(codigo.codigo44) != 44:
        raise ValueError(f"codigo de barras com {len(codigo.codigo44)} digitos")
    if len(chave) != 44:
        raise ValueError(f"chave NF-e com {len(chave)} digitos")
    if codigo.codigo44 == chave:
        raise ValueError("codigo de barras e chave NF-e iguais: leitura cruzada")
    if modelo(chave) != MODELO_NFE:
        raise ValueError(f"chave com modelo {modelo(chave)}, esperado {MODELO_NFE}")


def validar_guia(campo05, chave_guia, remetente, destinatario, chaves_remessa):
    ident = so_digitos(campo05)
    if not ident:
        return False, "INCOMPLETO: identificador ausente no campo 05"

    papeis = {
        "remetente": so_digitos(remetente),
        "destinatario": so_digitos(destinatario),
    }
    papeis = {k: v for k, v in papeis.items() if v}

    lado = next((k for k, v in papeis.items() if v == ident), None)
    if not lado:
        return False, "QUARENTENA: identificador nao consta na remessa"

    chave = so_digitos(chave_guia)
    if len(chave) != 44:
        return False, "INCOMPLETO: chave da guia nao localizada no campo 24"

    notas = {so_digitos(c) for c in chaves_remessa if modelo(c) == MODELO_NFE}
    if chave not in notas:
        return False, "QUARENTENA: chave da guia nao e de NF-e desta remessa"

    return True, f"OK: identificador ({lado}) e chave NF-e conferem"


# ----------------------------- teste -----------------------------

CAMPO_24 = (
    "NAO RECEBER APOS: 09/11/2026   "
    "Chave de Acesso: 33260913121476000122550010001447611862291617"
)
CAMPO_26 = "85670000003-2 07890463202-9 61109300516-7 50601415000-3"

codigo = ler_codigo_barras(CAMPO_26)
chave = ler_chave_nfe(CAMPO_24)

assert codigo.original == CAMPO_26, "original alterado"
assert len(codigo.digitos48) == 48, f"48 esperado, veio {len(codigo.digitos48)}"
assert codigo.codigo44 == "85670000003078904632026110930051650601415000", codigo.codigo44
assert chave == "33260913121476000122550010001447611862291617", chave
conferir_origens(codigo, chave)

chaves_remessa = [
    "35260904884082000135570020093542021093542025",  # DACTE modelo 57
    "33260913121476000122550010001447611862291617",  # NF 000144761
    "33260903007331019837570010743112191210443038",  # NF 074311219
]

ok, motivo = validar_guia(
    campo05="868.902.472-72",
    chave_guia=chave,
    remetente="13121476000122",
    destinatario="86890247272",
    chaves_remessa=chaves_remessa,
)
assert ok, motivo

print("codigo44 :", codigo.codigo44)
print("chave    :", chave)
print("modelo   :", modelo(chave))
print("validacao:", motivo)
print("\nTODOS OS TESTES PASSARAM")