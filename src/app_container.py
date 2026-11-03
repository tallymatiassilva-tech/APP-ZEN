from src.app_legacy import GerenciadorLayouts
from src.services.extraction_service import ExtractionService
from src.services.fraction_service import FractionService
from src.services.pdf_service import PdfService
from src.services.spreadsheet_service import SpreadsheetService
from src.services.zendesk_api import ZendeskAPI
from src.states.app_state import AppState


class AppContainer:
    def __init__(self):
        self.spreadsheet_service = SpreadsheetService()
        self.extraction_service = ExtractionService(
            gerenciador_layouts=self.gerenciador_layouts
        )
        # 1. Estado partilhado e persistência de sessão
        self.app_state = AppState()

        # 2. Gestor de layouts
        # 3. Clientes de rede
        subdomain = self.app_state.obter_credencial("subdomain", "jadloglogsticahelp")
        cookie_zd = self.app_state.obter_credencial("zendesk_cookie", "")
        cookie_frac = self.app_state.obter_credencial("jadlog_cookie", "")

        self.zendesk_api = ZendeskAPI(subdomain=subdomain, cookie=cookie_zd)
        self.fraction_service = FractionService(cookie=cookie_frac)

        # 4. Serviços de processamento de ficheiros
        self.pdf_service = PdfService()
        self.spreadsheet_service = SpreadsheetService()
        self.extraction_service = ExtractionService(gerenciador_layouts=self.gerenciador_layouts)
