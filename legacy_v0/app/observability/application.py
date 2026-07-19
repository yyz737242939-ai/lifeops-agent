import logging
from typing import Any

from app.observability.session import current_session_files


class ApplicationLogger:
    """Traditional diagnostic logger used for process and exception debugging."""

    def _logger(self) -> logging.Logger:
        current_session_files()
        return logging.getLogger("lifeops.application")

    def log_debug(self, message: str, *args: Any) -> None:
        self._logger().debug(message, *args)

    def log_info(self, message: str, *args: Any) -> None:
        self._logger().info(message, *args)

    def log_warning(self, message: str, *args: Any) -> None:
        self._logger().warning(message, *args)

    def log_error(self, message: str, *args: Any) -> None:
        self._logger().error(message, *args)

    def log_exception(self, message: str, *args: Any) -> None:
        self._logger().exception(message, *args)


app_log = ApplicationLogger()
