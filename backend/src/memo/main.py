"""ASGI entry point: ``uvicorn memo.main:app``."""

from memo.api import create_app

app = create_app()
