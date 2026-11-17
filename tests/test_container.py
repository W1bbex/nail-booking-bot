import importlib
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_container_dependencies_are_not_installed_only_for_root():
    dockerfile = (ROOT / "Dockerfile").read_text(encoding="utf-8")
    assert "pip install --no-cache-dir --user" not in dockerfile
    assert "/root/.local" not in dockerfile
    assert "USER appuser" in dockerfile


def test_docker_context_excludes_secrets_and_runtime_data():
    patterns = set((ROOT / ".dockerignore").read_text(encoding="utf-8").splitlines())
    assert {".env", ".env.*", "*.db", "data/", "logs/", ".venv/", ".git/"} <= patterns
    assert "!.env.example" in patterns


def test_container_configuration_preserves_salon_and_admins(tmp_path):
    config = {"server": {"host": "127.0.0.1", "dev_mode": True, "port": 8080},
              "admin_telegram_ids": [123], "salon": {"name": "Synthetic salon"}}
    path = tmp_path / "config.json"
    path.write_text(json.dumps(config), encoding="utf-8")
    module = importlib.import_module("core.container_config")
    module.configure_container(path)
    configured = json.loads(path.read_text(encoding="utf-8"))
    assert configured["server"] == {"host": "0.0.0.0", "dev_mode": False, "port": 8080}
    assert configured["admin_telegram_ids"] == [123]
    assert configured["salon"] == config["salon"]
    assert "python -m core.container_config" in (ROOT / "Dockerfile").read_text(encoding="utf-8")
