from src.app_legacy import ZendeskAppGUI
from src.settings import SETTINGS
from src.utils.logging_config import get_logger

logger = get_logger("jadlog")


def main():
    logger.info(f"Iniciando {SETTINGS.app_name} v{SETTINGS.version}")
    ZendeskAppGUI()


if __name__ == "__main__":
    main()
