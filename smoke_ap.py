from src.services.ufs.ap import (
    ler_codigo_barras, ler_chave_nfe, conferir_origens, validar_guia,
)

CAMPO_24 = (
    "NAO RECEBER APOS: 09/11/2026   "
    "Chave de Acesso: 33260913121476000122550010001447611862291617"
)
CAMPO_26 = "85670000003-2 07890463202-9 61109300516-7 50601415000-3"

codigo = ler_codigo_barras(CAMPO_26)
chave = ler_chave_nfe(CAMPO_24)

assert codigo.codigo44 == "85670000003078904632026110930051650601415000", codigo.codigo44
assert chave == "33260913121476000122550010001447611862291617", chave
conferir_origens(codigo, chave)

chaves = [
    "35260904884082000135570020093542021093542025",
    "33260913121476000122550010001447611862291617",
    "33260903007331019837570010743112191210443038",
]

ok, motivo = validar_guia(
    campo05="868.902.472-72",
    chave_guia=chave,
    remetente="13121476000122",
    destinatario="86890247272",
    chaves_remessa=chaves,
)

print("codigo44 :", codigo.codigo44)
print("chave    :", chave)
print("validacao:", motivo)
assert ok, motivo
print("SMOKE OK")
