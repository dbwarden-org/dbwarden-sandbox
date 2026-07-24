from __future__ import annotations

from typing import Any


_current_provider: Any = None


class _TestcontainersProvider:
    CONTAINER_CLS: str | None = None
    CONTAINER_MODULE: str = ""
    DB_DRIVER: str = ""
    DB_TYPE: str = ""

    def __init__(self) -> None:
        self._container: Any = None

    def start(self) -> str:
        if self._container is not None:
            raise RuntimeError("Sandbox already started. Call stop() first.")
        if self.CONTAINER_CLS is None:
            raise RuntimeError("CONTAINER_CLS not set for this provider.")
        import importlib
        module = importlib.import_module(self.CONTAINER_MODULE)
        cls = getattr(module, self.CONTAINER_CLS)
        self._container = cls()
        self._container.start()
        return self._build_url()

    def stop(self) -> None:
        if self._container is not None:
            try:
                self._container.stop()
            except Exception:
                pass
            self._container = None

    def get_database_type(self) -> str:
        return self.DB_TYPE

    def _build_url(self) -> str:
        raise NotImplementedError


class ClickHouseTestcontainersProvider(_TestcontainersProvider):
    CONTAINER_CLS = "ClickHouseContainer"
    CONTAINER_MODULE = "testcontainers.clickhouse"
    DB_DRIVER = "clickhousedb"
    DB_TYPE = "clickhouse"

    def _build_url(self) -> str:
        port = self._container.get_exposed_port(8123)
        host = self._container.get_container_host_ip()
        return f"clickhousedb://default:@{host}:{port}/default"


class PostgresTestcontainersProvider(_TestcontainersProvider):
    CONTAINER_CLS = "PostgresContainer"
    CONTAINER_MODULE = "testcontainers.postgres"
    DB_DRIVER = "postgresql"
    DB_TYPE = "postgresql"

    def _build_url(self) -> str:
        return self._container.get_connection_url()


class MySQLTestcontainersProvider(_TestcontainersProvider):
    CONTAINER_CLS = "MySQLContainer"
    CONTAINER_MODULE = "testcontainers.mysql"
    DB_DRIVER = "mysql"
    DB_TYPE = "mysql"

    def _build_url(self) -> str:
        return self._container.get_connection_url()


_HAS_TESTCONTAINERS: bool = False
try:
    import testcontainers  # noqa: F401
    _HAS_TESTCONTAINERS = True
except ImportError:
    pass


def create_sandbox_provider(database_type: str) -> _TestcontainersProvider:
    if database_type == "clickhouse":
        return ClickHouseTestcontainersProvider()
    if database_type == "postgresql":
        return PostgresTestcontainersProvider()
    if database_type == "mysql":
        return MySQLTestcontainersProvider()
    raise ValueError(f"Unsupported sandbox database type: {database_type}")


def sandbox_provider_start_hook(database_type: str) -> tuple[str, str] | None:
    if database_type == "sqlite":
        return None
    if not _HAS_TESTCONTAINERS:
        return None
    global _current_provider
    try:
        provider = create_sandbox_provider(database_type)
        url = provider.start()
        _current_provider = provider
        return url, provider.get_database_type()
    except (ImportError, ValueError):
        return None


def sandbox_provider_stop_hook() -> None:
    global _current_provider
    if _current_provider is not None:
        try:
            _current_provider.stop()
        except Exception:
            pass
        _current_provider = None
