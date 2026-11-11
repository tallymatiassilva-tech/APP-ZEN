"""Atualização automática pelo GitHub Releases.

Na abertura do executável, consulta a última versão publicada em
https://github.com/tallymatiassilva-tech/APP-ZEN/releases. Se houver versão
mais nova, pergunta ao usuário, baixa o AppZen-windows.zip, e um script .bat
substitui os arquivos do programa depois que o app fecha, preservando
memória, checkpoints e layouts personalizados. Qualquer falha (sem internet,
GitHub fora do ar) é ignorada e o app abre normalmente.
"""

from __future__ import annotations

import os
import re
import subprocess
import sys
import tempfile
import zipfile
from pathlib import Path

import requests

from src.settings import SETTINGS

REPOSITORIO = "tallymatiassilva-tech/APP-ZEN"
NOME_ASSET = "AppZen-windows.zip"
URL_ULTIMA = f"https://api.github.com/repos/{REPOSITORIO}/releases/latest"

# Nunca sobrescritos pela atualização.
ARQUIVOS_PRESERVADOS = ["layouts_custom.json", "memoria_diaria_jadlog.json", "*.corrompido_*.json"]
PASTAS_PRESERVADAS = ["checkpoints"]


def versao_para_tupla(versao: str) -> tuple[int, ...]:
    numeros = re.findall(r"\d+", versao or "")
    partes = [int(n) for n in numeros[:3]]
    while len(partes) < 3:
        partes.append(0)
    return tuple(partes)


def versao_mais_nova(remota: str, local: str) -> bool:
    return versao_para_tupla(remota) > versao_para_tupla(local)


def buscar_ultima_versao(timeout: float = 5) -> dict | None:
    """Retorna {versao, url, notas} da última release com o zip, ou None."""
    try:
        resp = requests.get(URL_ULTIMA, timeout=timeout, headers={"Accept": "application/vnd.github+json"})
        if resp.status_code != 200:
            return None
        dados = resp.json()
        for asset in dados.get("assets", []):
            if asset.get("name") == NOME_ASSET:
                return {
                    "versao": dados.get("tag_name", ""),
                    "url": asset.get("browser_download_url"),
                    "notas": (dados.get("body") or "").strip(),
                }
    except Exception:
        return None
    return None


def montar_script_bat(pasta_nova: str, pasta_app: str, exe: str, pid: int) -> str:
    excluir_arquivos = " ".join(f'"{a}"' for a in ARQUIVOS_PRESERVADOS)
    excluir_pastas = " ".join(f'"{p}"' for p in PASTAS_PRESERVADAS)
    return f"""@echo off
chcp 65001 >nul
:espera
tasklist /FI "PID eq {pid}" | find "{pid}" >nul
if not errorlevel 1 (
  timeout /t 1 /nobreak >nul
  goto espera
)
robocopy "{pasta_nova}" "{pasta_app}" /E /R:3 /W:1 /NFL /NDL /NJH /NJS /XF {excluir_arquivos} /XD {excluir_pastas}
if not exist "{pasta_app}\\layouts_custom.json" copy "{pasta_nova}\\layouts_custom.json" "{pasta_app}\\" >nul
start "" "{exe}"
rmdir /s /q "{pasta_nova}"
(goto) 2>nul & del "%~f0"
"""


def baixar_e_preparar(info: dict) -> bool:
    """Baixa o zip, extrai e dispara o .bat. Retorna True se o app deve fechar."""
    temp = Path(tempfile.mkdtemp(prefix="appzen_update_"))
    zip_path = temp / NOME_ASSET
    with requests.get(info["url"], stream=True, timeout=60) as resp:
        resp.raise_for_status()
        with open(zip_path, "wb") as f:
            for bloco in resp.iter_content(1024 * 256):
                f.write(bloco)
    pasta_nova = temp / "novo"
    with zipfile.ZipFile(zip_path) as z:
        z.extractall(pasta_nova)
    # O zip contém a pasta AppZen/; usa o conteúdo dela.
    internos = [p for p in pasta_nova.iterdir() if p.is_dir()]
    if len(internos) == 1 and (internos[0] / "AppZen.exe").exists():
        pasta_nova = internos[0]
    if not (pasta_nova / "AppZen.exe").exists():
        raise RuntimeError("Pacote de atualização inválido (AppZen.exe não encontrado).")

    exe = sys.executable
    pasta_app = os.path.dirname(exe)
    bat = temp / "atualizar_appzen.bat"
    bat.write_text(montar_script_bat(str(pasta_nova), pasta_app, exe, os.getpid()), encoding="utf-8")
    subprocess.Popen(
        ["cmd", "/c", str(bat)],
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        close_fds=True,
    )
    return True


def verificar_atualizacao_na_abertura() -> bool:
    """Só roda no executável do Windows. True = fechar o app para atualizar."""
    if not getattr(sys, "frozen", False) or os.name != "nt":
        return False
    info = buscar_ultima_versao()
    if not info or not versao_mais_nova(info["versao"], SETTINGS.version):
        return False

    import tkinter as tk
    from tkinter import messagebox

    raiz = tk.Tk()
    raiz.withdraw()
    try:
        notas = info["notas"][:600]
        texto = (
            f"Nova versão disponível: {info['versao']} (você tem a {SETTINGS.version}).\n\n"
            + (f"Novidades:\n{notas}\n\n" if notas else "")
            + "Deseja atualizar agora? O app vai fechar e reabrir sozinho."
        )
        if not messagebox.askyesno("Atualização disponível", texto, parent=raiz):
            return False
        try:
            return baixar_e_preparar(info)
        except Exception as exc:
            messagebox.showwarning(
                "Atualização", f"Não foi possível atualizar agora:\n{exc}\n\nO app vai abrir normalmente.", parent=raiz
            )
            return False
    finally:
        raiz.destroy()
