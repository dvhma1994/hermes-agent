"""Tests for utils.env_bool — environment-variable-as-boolean helper."""

from utils import env_bool


def test_env_bool_unset_returns_default_true(monkeypatch):
    """When the var is unset, default=True must be honoured."""
    monkeypatch.delenv("HERMES_TEST_ENV_BOOL", raising=False)
    assert env_bool("HERMES_TEST_ENV_BOOL", default=True) is True


def test_env_bool_unset_returns_default_false(monkeypatch):
    """When the var is unset, default=False must be honoured."""
    monkeypatch.delenv("HERMES_TEST_ENV_BOOL", raising=False)
    assert env_bool("HERMES_TEST_ENV_BOOL", default=False) is False


def test_env_bool_truthy_value(monkeypatch):
    monkeypatch.setenv("HERMES_TEST_ENV_BOOL", "true")
    assert env_bool("HERMES_TEST_ENV_BOOL", default=False) is True


def test_env_bool_falsy_value(monkeypatch):
    monkeypatch.setenv("HERMES_TEST_ENV_BOOL", "0")
    assert env_bool("HERMES_TEST_ENV_BOOL", default=True) is False


def test_env_bool_empty_string_treated_as_unset(monkeypatch):
    """An explicitly-set empty string should fall back to the default."""
    monkeypatch.setenv("HERMES_TEST_ENV_BOOL", "")
    assert env_bool("HERMES_TEST_ENV_BOOL", default=True) is True
