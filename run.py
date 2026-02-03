import os
import platform
import logging
from capbot import run_bot, LOG_NAME

def init_log():
    log = logging.getLogger(LOG_NAME)
    log.setLevel(logging.DEBUG)
    formatter = logging.Formatter("%(asctime)s [%(threadName)-12.12s] [%(levelname)-5.5s]  %(message)s")

    console_handler = logging.StreamHandler()
    console_handler.setFormatter(formatter)
    log.addHandler(console_handler)

    file_handler = logging.FileHandler("capbot.log", "w")
    file_handler.setFormatter(formatter)
    log.addHandler(file_handler)

    log.info("CapBot log opened.")
    return log

def start_linux(log):
    import daemon
    import daemon.pidfile

    log.debug(os.environ)

    context = daemon.DaemonContext(
        working_directory=os.getenv("CAPBOT_CWD"),
        pidfile=daemon.pidfile.PIDLockFile(os.getenv("CAPBOT_PIDFILE"))
    )

    with context:
        log.info("Starting bot daemon")
        run_bot()

def start_windows(log):
    log.info("Starting bot on Windows")
    run_bot()

if __name__ == "__main__":
    log = init_log()
    try:
        log.info("Starting bot script")

        if platform.system() == "Windows":
            start_windows(log)
        else:
            start_linux(log)
    except Exception as ex:
        log.exception(ex)