import os
import sys

from loguru import logger


def get_app_mode() -> str:
    return (os.getenv("MODE") or os.getenv("mode") or "production").strip().lower()


def configure_logging() -> tuple[str, str]:
    mode = get_app_mode()
    default_level = "DEBUG" if mode == "debug" else "INFO"
    level = (os.getenv("LOG_LEVEL") or default_level).upper()

    logger.remove()
    logger.add(
        sys.stdout,
        level=level,
        backtrace=mode == "debug",
        diagnose=mode == "debug",
        enqueue=True,
        format=(
            "{time:YYYY-MM-DD HH:mm:ss.SSS} | {level:<8} | "
            "{name}:{function}:{line} - {message}"
        ),
    )

    logger.info(f"Logging configured: mode={mode}, level={level}")
    return mode, level
