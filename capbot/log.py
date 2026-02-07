import logging

LOG_NAME = "CapBot"

def init_log():
    log = logging.getLogger(LOG_NAME)
    log.setLevel(logging.DEBUG)
    formatter = logging.Formatter("%(asctime)s [%(threadName)-12.12s] [%(levelname)-5.5s]  %(message)s")

    console_handler = logging.StreamHandler()
    console_handler.setFormatter(formatter)
    console_handler.setLevel(logging.DEBUG)
    log.addHandler(console_handler)

    file_handler = logging.FileHandler("capbot.log", encoding="utf-8", mode="w")
    file_handler.setFormatter(formatter)
    file_handler.setLevel(logging.DEBUG)
    log.addHandler(file_handler)

    log.info("CapBot log opened.")
    return log
