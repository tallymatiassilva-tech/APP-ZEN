"""Persistencia e extração de campos por layouts configuráveis."""

from __future__ import annotations

import json
import os
import re
from datetime import datetime

from src.services.document_classifier import (
    extrair_codigo_barras_pdf,
    extrair_numero_termo_pdf,
    extrair_vencimento_e_valor_pdf,
    linha_digitavel_para_codigo_barras,
)
from src.services.pdf_service import extrair_texto_por_caixa
from src.utils.text_mono import formatar_numero_arquivo, padronizar_data_ddmmyyyy

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
                with open(ARQUIVO_LAYOUTS, "r", encoding="utf-8") as arquivo:
                    layouts_carregados = json.load(arquivo)
                    if isinstance(layouts_carregados, dict) and "_historico" in layouts_carregados:
                        self.historico = layouts_carregados.pop("_historico", [])
            except Exception as erro:  # noqa: BLE001
                print(f"[Erro] Falha ao carregar layouts: {erro}")
                layouts_carregados = {}
            if not isinstance(layouts_carregados, dict):
                print("[Erro] Arquivo de layouts em formato inválido; usando padrões.")
                layouts_carregados = {}

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
            with open(ARQUIVO_LAYOUTS, "w", encoding="utf-8") as arquivo:
                json.dump(dados, arquivo, ensure_ascii=False, indent=4)
        except Exception as erro:  # noqa: BLE001
            print(f"[Erro] Falha ao salvar layouts: {erro}")

    def restaurar_padrao(self, nome: str) -> bool:
        if nome not in LAYOUTS_PADRAO_SISTEMA:
            return False
        self.layouts[nome] = json.loads(json.dumps(LAYOUTS_PADRAO_SISTEMA[nome]))
        self.registrar_historico("RESTAURADO PADRÃO", nome)
        self.salvar_layouts()
        return True

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
                    match = re.search(pat, alvo_texto, re.IGNORECASE)
                    if match and match.group(1 if match.groups() else 0):
                        return match
                    return None
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
                txt_crop_valor = extrair_texto_por_caixa(pdf_bytes, config.get("bbox_valor"))
                if txt_crop_valor:
                    txt_valor_alvo = txt_crop_valor

            match = _safe_search(config.get("regex_termo"), texto_pdf)
            if match:
                res["termo"] = match.group(1 if match.groups() else 0).strip()

            match = _safe_search(config.get("regex_vencimento"), txt_venc_alvo)
            if match:
                res["vencimento"] = padronizar_data_ddmmyyyy(
                    match.group(1 if match.groups() else 0).strip()
                )

            match = _safe_search(config.get("regex_valor"), txt_valor_alvo)
            if match:
                res["valor"] = match.group(1 if match.groups() else 0).strip()

            match = _safe_search(config.get("regex_cod_barras"), texto_pdf)
            if match:
                bruto = match.group(1 if match.groups() else 0).strip()
                res["cod_barras_orig"] = bruto
                res["cod_barras"] = linha_digitavel_para_codigo_barras(bruto)

            match = _safe_search(config.get("regex_cte"), texto_pdf)
            if match:
                res["cte"] = match.group(1 if match.groups() else 0).strip()

            match = _safe_search(config.get("regex_num_arquivo"), texto_pdf)
            if match:
                raw_num = match.group(1 if match.groups() else 0).strip()
                res["num_arquivo"] = formatar_numero_arquivo(raw_num)

            if (
                res.get("uf") == "AL" and res.get("termo") and res["termo"] != "Não localizado"
            ) and (
                not res.get("num_arquivo")
                or res["num_arquivo"] in ["Sem Número", "Sem Arquivo Válido"]
            ):
                res["num_arquivo"] = formatar_numero_arquivo(res["termo"])

            match = _safe_search(config.get("regex_chave_arquivo"), texto_pdf)
            if match:
                chave = re.sub(r"\D", "", match.group(1 if match.groups() else 0).strip())
                if len(chave) == 44:
                    res["chave_arquivo"] = chave

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
                vencimento, _ = extrair_vencimento_e_valor_pdf(texto_pdf)
                if vencimento != "Não informado":
                    res["vencimento"] = padronizar_data_ddmmyyyy(vencimento)

            if res["valor"] == "Não informado":
                _, valor = extrair_vencimento_e_valor_pdf(texto_pdf)
                if valor != "Não informado":
                    res["valor"] = valor

            if res["cod_barras"] in ["Sem Código", ""]:
                original, barras = extrair_codigo_barras_pdf(texto_pdf)
                res["cod_barras_orig"] = original
                res["cod_barras"] = barras

            chaves_enc = [par[0] for par in res["pares_documento"]]
            for chave in re.findall(r"\b(\d{44})\b", texto_pdf):
                if chave != res["cod_barras"] and chave not in chaves_enc:
                    chaves_enc.append(chave)
                    numero = formatar_numero_arquivo(chave[25:34])
                    res["pares_documento"].append((chave, numero))

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
