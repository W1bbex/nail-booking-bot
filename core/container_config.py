"""Prepare the container's server binding without changing salon settings."""
import json
from pathlib import Path


def configure_container(config_path: Path) -> None:
    config = json.loads(config_path.read_text(encoding="utf-8"))
    server = config.setdefault("server", {})
    server.update(host="0.0.0.0", dev_mode=False)
    config_path.write_text(json.dumps(config, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


if __name__ == "__main__":
    configure_container(Path(__file__).resolve().parent.parent / "config.json")
