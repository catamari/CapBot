import os
import platform
import logging
from capbot import run_bot
from log import init_log

def start_linux(log):
    import daemon
    import daemon.pidfile

    log.debug(os.environ)

    context = daemon.DaemonContext(
        working_directory=os.getenv("CAPBOT_CWD"),
        pidfile=daemon.pidfile.PIDLockFile(os.getenv("CAPBOT_PIDFILE")),
        files_preserve="capbot.log" # The daemon context closes an open files, so keep the log open.
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