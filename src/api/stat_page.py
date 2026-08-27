"""Dashboard HTML page at /stat/ showing token usage charts."""
# SYSTEM: stat-dashboard — /stat/ usage page and its JSON endpoints

import os

from fastapi import Request
from fastapi.responses import HTMLResponse

STATIC_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "static")
_HTML_PATH = os.path.join(STATIC_DIR, "stat.html")


async def stat_page(request: Request) -> HTMLResponse:
    with open(_HTML_PATH) as f:
        return HTMLResponse(content=f.read())
