# dbwarden-sandbox

[![Python](https://img.shields.io/badge/Python-3.12.7%2B-3776AB?logo=python&logoColor=white&style=for-the-badge)](https://www.python.org/downloads/)
[![PyPI](https://img.shields.io/pypi/v/dbwarden-sandbox?logo=pypi&logoColor=white&style=for-the-badge)](https://pypi.org/project/dbwarden-sandbox/)
[![CI](https://img.shields.io/github/actions/workflow/status/dbwarden-org/dbwarden-sandbox/test.yml?logo=github&logoColor=white&style=for-the-badge)](https://github.com/dbwarden-org/dbwarden-sandbox/actions/workflows/test.yml)

Safe declaration parsing and model loading for [dbwarden](https://github.com/dbwarden-org/dbwarden).

dbwarden discovers configuration by scanning your project for `database_config()` calls. Files found at the project root are *isolated*: they are not part of any package, so importing them normally would execute arbitrary code found by a filesystem scan. This plugin parses those files without executing them.

## Hooks

| Hook | Behavior |
|---|---|
| `load_config_module` | Rejects path traversal and paths outside the project tree, then parses literal `database_config()` declarations without executing the file. |
| `load_model_module` | Rejects path traversal. Model paths are user-declared in `database_config()`, so they import normally otherwise. |
| `sandbox_provider_start` | Starts a testcontainers database for the configured `database_type` (PostgreSQL, MySQL, ClickHouse) and returns the connection URL and container id. |
| `sandbox_provider_stop` | Tears down the running testcontainers database. |

An isolated config file may contain a docstring, `from dbwarden import database_config`, and direct `database_config()` calls with literal keyword values. Other code raises `SecurityError`; there is no environment-variable bypass. Config files that live inside your application package are imported normally, since they are already part of code you ship.

## Installation

```bash
dbwarden plugin add dbwarden-sandbox
```

## Trust tier

This is an **official** dbwarden plugin. Its distribution name is classified before any of its code is imported, and `dbwarden plugin add` verifies the PyPI Trusted-Publishing attestation (PEP 740) against `dbwarden-org/dbwarden-sandbox` before installing. It loads automatically once installed, with no `dbwarden plugin trust` step.

## Development

```bash
uv venv && uv pip install -e . -e ../dbwarden pytest
pytest -q
```

The `tests/test_conformance.py` suite runs dbwarden's shared conformance harness (`dbwarden.plugin_conformance`): entry point resolution, no import-time side effects, hook signatures, public-API-only imports, and idempotent `setup()`.

## License

MIT
