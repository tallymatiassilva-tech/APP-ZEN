import logging  # noqa: I001


def get_logger(name: str = "jadlog"):
    logger = logging.getLogger(name)
    if logger.handlers:
        return logger
    logger.setLevel(logging.INFO)
    h = logging.StreamHandler()
    h.setFormatter(
        logging.Formatter(
            "[%(asctime)s] [%(levelname)s] %(name)s - %(message)s",
            datefmt="%d/%m/%Y %H:%M:%S",
        )
    )
    logger.addHandler(h)
    logger.propagate = False
    return logger
