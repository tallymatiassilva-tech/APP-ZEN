from src.app_legacy import ZendeskAppGUI
from src.services.update_service import verificar_atualizacao_na_abertura
from src.settings import SETTINGS
from src.utils.logging_config import get_logger

logger = get_logger("jadlog")


def main():
    logger.info(f"Iniciando {SETTINGS.app_name} v{SETTINGS.version}")
    if verificar_atualizacao_na_abertura():
        return  # o atualizador vai substituir os arquivos e reabrir o app
    ZendeskAppGUI()


if __name__ == "__main__":
    main()
