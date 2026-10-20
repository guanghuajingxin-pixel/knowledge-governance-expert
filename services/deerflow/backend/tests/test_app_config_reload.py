from __future__ import annotations

import json
import os
from pathlib import Path

import yaml
import pytest

from deerflow.config.app_config import AppConfig, get_app_config, reset_app_config


def _write_config(path: Path, *, model_name: str, supports_thinking: bool) -> None:
    path.write_text(
        yaml.safe_dump(
            {
                "sandbox": {"use": "deerflow.sandbox.local:LocalSandboxProvider"},
                "models": [
                    {
                        "name": model_name,
                        "use": "langchain_openai:ChatOpenAI",
                        "model": "gpt-test",
                        "supports_thinking": supports_thinking,
                    }
                ],
            }
        ),
        encoding="utf-8",
    )


def _write_extensions_config(path: Path) -> None:
    path.write_text(json.dumps({"mcpServers": {}, "skills": {}}), encoding="utf-8")


def test_get_app_config_reloads_when_file_changes(tmp_path, monkeypatch):
    config_path = tmp_path / "config.yaml"
    extensions_path = tmp_path / "extensions_config.json"
    _write_extensions_config(extensions_path)
    _write_config(config_path, model_name="first-model", supports_thinking=False)

    monkeypatch.setenv("DEER_FLOW_CONFIG_PATH", str(config_path))
    monkeypatch.setenv("DEER_FLOW_EXTENSIONS_CONFIG_PATH", str(extensions_path))
    reset_app_config()

    try:
        initial = get_app_config()
        assert initial.models[0].supports_thinking is False

        _write_config(config_path, model_name="first-model", supports_thinking=True)
        next_mtime = config_path.stat().st_mtime + 5
        os.utime(config_path, (next_mtime, next_mtime))

        reloaded = get_app_config()
        assert reloaded.models[0].supports_thinking is True
        assert reloaded is not initial
    finally:
        reset_app_config()


def test_get_app_config_reloads_when_config_path_changes(tmp_path, monkeypatch):
    config_a = tmp_path / "config-a.yaml"
    config_b = tmp_path / "config-b.yaml"
    extensions_path = tmp_path / "extensions_config.json"
    _write_extensions_config(extensions_path)
    _write_config(config_a, model_name="model-a", supports_thinking=False)
    _write_config(config_b, model_name="model-b", supports_thinking=True)

    monkeypatch.setenv("DEER_FLOW_EXTENSIONS_CONFIG_PATH", str(extensions_path))
    monkeypatch.setenv("DEER_FLOW_CONFIG_PATH", str(config_a))
    reset_app_config()

    try:
        first = get_app_config()
        assert first.models[0].name == "model-a"

        monkeypatch.setenv("DEER_FLOW_CONFIG_PATH", str(config_b))
        second = get_app_config()
        assert second.models[0].name == "model-b"
        assert second is not first
    finally:
        reset_app_config()


def test_resolve_env_variables_treats_non_identifier_dollar_strings_as_literals():
    """bcrypt 风格 API Key（$2b$12$...）以 $ 开头但不是合法环境变量名，必须原样透传。"""
    bcrypt_key = "$2b$12$bso5AC/NM3paYsN68rtGk.bAC8es.DZG.AJJdvWKcQwq2yu5dUSR."
    config = {"models": [{"name": "m", "api_key": bcrypt_key}]}
    resolved = AppConfig.resolve_env_variables(config)
    assert resolved["models"][0]["api_key"] == bcrypt_key


def test_resolve_env_variables_still_resolves_named_references(monkeypatch):
    """合法 $VAR 引用行为不变：存在则解析，缺失仍报错。"""
    monkeypatch.setenv("TEST_DF_API_KEY", "sk-real")
    assert AppConfig.resolve_env_variables("$TEST_DF_API_KEY") == "sk-real"
    with pytest.raises(ValueError, match="TEST_DF_MISSING"):
        AppConfig.resolve_env_variables("$TEST_DF_MISSING")
