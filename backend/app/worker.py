"""Dramatiq entry point: `dramatiq app.worker`. Importing the modules declares their actors and subscribers."""

from app.bootstrap import bootstrap
from app.core import logging
from app.core.jobs import broker  # noqa: F401  (dramatiq discovers the broker from this module)

logging.configure()
bootstrap()
