import logging
from collections.abc import Sequence

from bambulab_metrics_exporter.diagnostics import install_log_handler

BANNER_WIDTH = 72


def configure_logging(level: str) -> None:
    logging.basicConfig(
        level=getattr(logging, level.upper(), logging.INFO),
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )
    # Keep recent exporter log lines for the diagnostic report.
    install_log_handler()


def log_banner(
    logger: logging.Logger, title: str, body: Sequence[str], level: int = logging.INFO
) -> None:
    """Log a framed block so operator instructions stand out in container logs."""
    for line in ("=" * BANNER_WIDTH, title, *body, "=" * BANNER_WIDTH):
        logger.log(level, line)
