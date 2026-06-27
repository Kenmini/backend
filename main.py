"""Uvicorn entrypoint: uvicorn main:app --reload --port 8000."""

from app.api import create_app
from app.observability import configure_logging
from config import SETTINGS


configure_logging()
app = create_app(settings=SETTINGS)
