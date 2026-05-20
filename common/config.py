from pathlib import Path
from typing import Any, Dict, Iterable

import yaml


PROJECT_ROOT = Path(__file__).resolve().parents[1]
CONFIG_FILE = PROJECT_ROOT / "config" / "config.yaml"

_CONFIG_CACHE = None


def load_config() -> Dict[str, Any]:
    global _CONFIG_CACHE
    if _CONFIG_CACHE is None:
        if not CONFIG_FILE.exists():
            raise FileNotFoundError(f"配置文件不存在: {CONFIG_FILE}")
        with CONFIG_FILE.open("r", encoding="utf-8") as fh:
            _CONFIG_CACHE = yaml.safe_load(fh) or {}
    return _CONFIG_CACHE


def get_config(path: str, default: Any = None) -> Any:
    value = load_config()
    for part in path.split("."):
        if not isinstance(value, dict) or part not in value:
            return default
        value = value[part]
    return value


def get_list(path: str, default: Iterable[Any] = None) -> list:
    value = get_config(path, default or [])
    if value is None:
        return []
    if isinstance(value, list):
        return value
    return [value]


def get_path(path: str, default: Any = None) -> Path:
    value = get_config(path, default)
    if value is None:
        return None
    result = Path(value)
    if not result.is_absolute():
        result = PROJECT_ROOT / result
    return result
