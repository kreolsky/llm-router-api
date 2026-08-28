"""Dashboard HTML page at /stat/ showing token usage charts."""
# SYSTEM: stat-dashboard — the /stat/ usage HTML page (JSON endpoints in stat_routes.py)

import os

from fastapi import Request
from fastapi.responses import HTMLResponse

STATIC_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "static")
_HTML_PATH = os.path.join(STATIC_DIR, "stat.html")


async def stat_page(request: Request) -> HTMLResponse:
    # WHY noqa ASYNC230: the HTML is (re)read per request on purpose — editing
    # src/static/stat.html shows up on the next reload without a container
    # restart; a home-lab dashboard is worth that blocking millisecond.
    with open(_HTML_PATH) as f:  # noqa: ASYNC230
        return HTMLResponse(content=f.read())
