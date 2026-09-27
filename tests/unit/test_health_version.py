"""The running version: read from src/VERSION (written by deploy-server), served by /health."""

import httpx
import pytest

from src.api import main
from src.api.main import app, read_app_version


class TestReadAppVersion:

    def test_absent_file_is_dev(self, tmp_path):
        assert read_app_version(tmp_path / "VERSION") == "dev"

    def test_file_content_is_stripped(self, tmp_path):
        path = tmp_path / "VERSION"
        path.write_text("v1.0.0-3-gabc1234\n")
        assert read_app_version(path) == "v1.0.0-3-gabc1234"

    def test_blank_file_is_dev(self, tmp_path):
        path = tmp_path / "VERSION"
        path.write_text("  \n")
        assert read_app_version(path) == "dev"


@pytest.mark.asyncio
async def test_health_reports_the_loaded_version(monkeypatch):
    monkeypatch.setattr(main, "APP_VERSION", "v9.9.9-test")
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://t") as client:
        response = await client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok", "version": "v9.9.9-test"}
