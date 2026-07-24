# dbwarden-sandbox

Sandboxed config and model loading for [DBWarden](https://github.com/dbwarden-org/dbwarden).

DBWarden discovers configuration by scanning your project for `database_config()` calls. Files found at the project root are *isolated*: they are not part of any package, so importing them normally would execute arbitrary code found by a filesystem scan. This plugin loads them under a restricted importer instead.

## Hooks

| Hook | Behavior |
|---|---|
| `load_config_module` | Rejects path traversal and paths outside the project tree, then executes the file with a meta-path finder that permits only `dbwarden` imports. |
| `load_model_module` | Rejects path traversal. Model paths are user-declared in `database_config()`, so they import normally otherwise. |

An isolated config file that imports anything but `dbwarden` raises `SecurityError`. Config files that live inside your application package are imported normally, since they are already part of code you ship. Set `DBWARDEN_DISABLE_SANDBOX=1` to fall back to a plain import when debugging.

## Installation

```bash
dbwarden plugin add dbwarden-sandbox
```

## Trust tier

This is an **official** DBWarden plugin. Its distribution name is classified before any of its code is imported, and `dbwarden plugin add` verifies the PyPI Trusted-Publishing attestation (PEP 740) against `dbwarden-org/dbwarden-sandbox` before installing. It loads automatically once installed, with no `dbwarden plugin trust` step.

## Development

```bash
uv venv && uv pip install -e . -e ../dbwarden pytest
pytest -q
```

The `tests/test_conformance.py` suite runs DBWarden's shared conformance harness (`dbwarden.plugin_conformance`): entry point resolution, no import-time side effects, hook signatures, public-API-only imports, and idempotent `setup()`.

## License

MIT
