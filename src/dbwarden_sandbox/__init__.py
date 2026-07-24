from __future__ import annotations

from dbwarden_sandbox.providers import sandbox_provider_start_hook, sandbox_provider_stop_hook
from dbwarden_sandbox.sandbox import (
    RestrictedFileLoader,
    RestrictedModuleFinder,
    SecurityError,
    load_config_module,
    load_model_module,
    validate_model_path,
    validate_path,
)

__version__ = "0.1.0"

# The DBWarden plugin contract this package targets. Core refuses to load a
# plugin declaring a version it does not provide, so a mismatched pairing fails
# at load with one clear message instead of somewhere inside a migration.
DBWARDEN_PLUGIN_API = 1


def setup(registrar) -> None:
    registrar.register("load_config_module", load_config_module)
    registrar.register("load_model_module", load_model_module)
    registrar.register("sandbox_provider_start", sandbox_provider_start_hook)
    registrar.register("sandbox_provider_stop", sandbox_provider_stop_hook)


__all__ = [
    "RestrictedFileLoader",
    "RestrictedModuleFinder",
    "SecurityError",
    "load_config_module",
    "load_model_module",
    "sandbox_provider_start_hook",
    "sandbox_provider_stop_hook",
    "setup",
    "validate_model_path",
    "validate_path",
]
