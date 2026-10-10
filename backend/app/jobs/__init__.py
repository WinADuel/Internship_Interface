"""Background jobs, each run as its own Docker Compose service."""

import logging

LOG_FORMAT = "%(asctime)s %(levelname)s %(name)s: %(message)s"
# HTTP client libraries log every request at INFO, URL included. Some URLs are
# secret (a Google Drive resumable upload session URL is a bearer credential
# for that upload), so only their warnings reach the container logs.
QUIET_LOGGERS = ("httpx", "httpcore")


def configure_job_logging() -> None:
    """INFO logging for a job's own messages, as every job's main() sets up."""
    logging.basicConfig(level=logging.INFO, format=LOG_FORMAT)
    for name in QUIET_LOGGERS:
        logging.getLogger(name).setLevel(logging.WARNING)
