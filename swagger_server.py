from __future__ import annotations

import json
from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import HTMLResponse
from fastapi.openapi.docs import get_swagger_ui_html

app = FastAPI(title="AgentRouters API Docs", docs_url=None, openapi_url=None, redoc_url=None)

# Load the generated OpenAPI schema
_schema: dict | None = None


def _load_schema() -> dict:
    global _schema
    if _schema is None:
        path = Path(__file__).parent / "openapi.json"
        with open(path, encoding="utf-8") as f:
            _schema = json.load(f)
    return _schema


@app.get("/openapi.json", include_in_schema=False)
def openapi_json() -> dict:
    return _load_schema()


@app.get("/docs", response_class=HTMLResponse, include_in_schema=False)
def swagger_ui() -> str:
    return get_swagger_ui_html(
        openapi_url="/openapi.json",
        title="AgentRouters API Docs",
    )


@app.get("/", include_in_schema=False)
def root() -> dict:
    return {"message": "AgentRouters API Docs", "docs": "/docs"}
