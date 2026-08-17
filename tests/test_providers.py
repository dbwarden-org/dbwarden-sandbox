from __future__ import annotations

import types

import pytest

from dbwarden_sandbox import providers


@pytest.fixture(autouse=True)
def reset_provider() -> None:
    providers.sandbox_provider_stop_hook()
    yield
    providers.sandbox_provider_stop_hook()


def test_missing_optional_dependency_returns_none(monkeypatch: pytest.MonkeyPatch) -> None:
    def missing(name: str) -> types.ModuleType:
        raise ModuleNotFoundError(name="testcontainers")

    monkeypatch.setattr(providers.importlib, "import_module", missing)
    assert providers.sandbox_provider_start_hook("postgresql") is None


def test_provider_is_not_replaced_while_running(monkeypatch: pytest.MonkeyPatch) -> None:
    class Provider:
        def start(self) -> str:
            return "postgresql://example"

        def stop(self) -> None:
            pass

        def get_database_type(self) -> str:
            return "postgresql"

    monkeypatch.setattr(providers.importlib, "import_module", lambda name: types.ModuleType(name))
    monkeypatch.setattr(providers, "create_sandbox_provider", lambda database_type: Provider())
    assert providers.sandbox_provider_start_hook("postgresql") == ("postgresql://example", "postgresql")
    with pytest.raises(RuntimeError, match="already running"):
        providers.sandbox_provider_start_hook("postgresql")


def test_failed_container_start_is_cleaned_up(monkeypatch: pytest.MonkeyPatch) -> None:
    stopped = False

    class Container:
        def start(self) -> None:
            raise RuntimeError("docker unavailable")

        def stop(self) -> None:
            nonlocal stopped
            stopped = True

    module = types.ModuleType("testcontainers.postgres")
    module.PostgresContainer = Container
    monkeypatch.setattr(providers.importlib, "import_module", lambda name: module)
    provider = providers.PostgresTestcontainersProvider()
    with pytest.raises(RuntimeError, match="docker unavailable"):
        provider.start()
    assert stopped
    assert provider._container is None


def test_stop_clears_global_provider_before_teardown(monkeypatch: pytest.MonkeyPatch) -> None:
    class Provider:
        def stop(self) -> None:
            assert providers._current_provider is None
            raise RuntimeError("stop failed")

    monkeypatch.setattr(providers, "_current_provider", Provider())
    with pytest.raises(RuntimeError, match="stop failed"):
        providers.sandbox_provider_stop_hook()
    assert providers._current_provider is None
