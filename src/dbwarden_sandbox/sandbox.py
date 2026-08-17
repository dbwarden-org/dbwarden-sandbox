import ast
import logging
import os
import sys
from importlib.abc import Loader, MetaPathFinder
from importlib.machinery import ModuleSpec
from pathlib import Path
from types import ModuleType
from typing import Any, Optional, Set

from dbwarden.exceptions import ConfigurationError

logger = logging.getLogger("dbwarden.sandbox")


ALLOWED_IMPORTS: Set[str] = {
    "dbwarden",
    "dbwarden.database_config",
}

ALLOWED_IMPORTS_PREFIXES: Set[str] = {
    "dbwarden.",
}


class SecurityError(ConfigurationError):
    """Raised when a security check fails."""
    pass


class RestrictedFileLoader(Loader):
    """Legacy loader API that parses declarations without executing source."""

    _base_dir: Path
    _filepath: str

    def __init__(self, filepath: str, base_dir: Path) -> None:
        self._filepath = filepath
        self._base_dir = base_dir.resolve()

    def create_module(self, spec: ModuleSpec) -> None:
        return None

    def exec_module(self, module: ModuleType) -> None:
        module.__loader__ = self
        _load_config_declarations(Path(self._filepath))

    def find_module(
        self, fullname: str, path: str | None = None, target: ModuleSpec | None = None
    ) -> "RestrictedFileLoader | None":
        """Check if module can be imported."""
        if self._is_allowed_import(fullname):
            return self
        return None

    def _is_allowed_import(self, fullname: str) -> bool:
        """Check if import is allowed."""
        if fullname in ALLOWED_IMPORTS:
            return True
        for prefix in ALLOWED_IMPORTS_PREFIXES:
            if fullname.startswith(prefix):
                return True
        return False


class RestrictedModuleFinder(MetaPathFinder):
    """
    Meta path finder that restricts which modules can be loaded.

    Use with RestrictedFileLoader for complete sandboxing.
    """

    _base_dir: Path
    _allowed_imports: Set[str]

    def __init__(self, base_dir: Path) -> None:
        self._base_dir = base_dir.resolve()
        self._allowed_imports = ALLOWED_IMPORTS.copy()

    def find_spec(
        self,
        fullname: str,
        path: str | None = None,
        target: ModuleSpec | None = None,
    ) -> ModuleSpec | None:
        """Find and validate module spec."""
        if not self._is_allowed(fullname):
            raise SecurityError(
                f"Import '{fullname}' not allowed. "
                f"Only dbwarden imports are permitted in isolated config files.\n\n"
                f"This file was loaded as an isolated config module (sandboxed). "
                f"If it is part of your application package, move the database_config() "
                f"call into a package module instead; dbwarden will import it normally."
            )
        return None

    def _is_allowed(self, fullname: str) -> bool:
        """Check if module is allowed."""
        if fullname in self._allowed_imports:
            return True
        for prefix in ALLOWED_IMPORTS_PREFIXES:
            if fullname.startswith(prefix):
                return True
        return False


def validate_path(path: Path, base_dir: Path) -> None:
    """
    Validate that a config path is safe to load.

    Raises SecurityError if:
    - Path is outside the project tree
    - Path contains path traversal sequences
    - Path is absolute and points outside project

    Args:
        path: Path to the config file
        base_dir: Project root directory

    Raises:
        SecurityError: If path is not safe
    """
    resolved = path.resolve()
    base = base_dir.resolve()

    # Check for path traversal
    path_str = str(path)
    if ".." in path_str.split("/"):
        raise SecurityError(
            f"Refusing to load config with path traversal: {path}"
        )

    # Check if within project tree for relative paths
    if not path.is_absolute():
        try:
            resolved = (base / path).resolve()
        except Exception as e:
            raise SecurityError(f"Invalid path: {path}") from e

    # Verify resolved path is under base_dir
    try:
        resolved.relative_to(base)
    except ValueError:
        raise SecurityError(
            f"Refusing to load config from outside project tree: {path}\n"
            f"Project root: {base}\n"
            f"Config path: {resolved}"
        )


def validate_model_path(path: Path, base_dir: Path) -> None:
    """
    Validate that a model path is safe to load.

    For model files, we only block path traversal attacks.
    Model paths are already user-configured in database_config(),
    so we trust them more than arbitrary discovered config files.

    Args:
        path: Path to the model file
        base_dir: Project root directory (used for temp dir resolution)

    Raises:
        SecurityError: If path contains traversal sequences
    """
    # Only check for path traversal - model paths are user-configured
    path_str = str(path)
    if ".." in path_str.split("/"):
        raise SecurityError(
            f"Refusing to load model with path traversal: {path}"
        )


def load_config_module(path: Path, base_dir: Path) -> None:
    """Load literal ``database_config`` declarations from an isolated config.

    Isolated files are discovered from the filesystem and are therefore treated
    as untrusted input.  They are parsed, never executed: only a docstring, an
    optional ``from dbwarden import database_config`` statement, and direct
    calls with literal keyword values are accepted.
    """
    validate_path(path, base_dir)
    _sandboxed_load(path, base_dir)


def _sandboxed_load(path: Path, base_dir: Path) -> None:
    try:
        _load_config_declarations(path)
    except SecurityError:
        raise
    except Exception as e:
        raise ConfigurationError(f"Failed to load config from {path}: {e}") from e


def _load_config_declarations(path: Path) -> None:
    """Validate and register the literal declarations in *path*."""
    try:
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    except (OSError, SyntaxError) as e:
        raise SecurityError(f"Could not parse isolated config {path}: {e}") from e

    from dbwarden import database_config

    declarations = []
    for statement in tree.body:
        if _is_docstring(statement) or _is_database_config_import(statement):
            continue
        if not isinstance(statement, ast.Expr) or not isinstance(statement.value, ast.Call):
            raise SecurityError(
                "Isolated config files may contain only literal database_config() declarations."
            )
        call = statement.value
        if not _is_database_config_call(call):
            raise SecurityError(
                "Isolated config files may call only database_config() directly."
            )
        if call.args or any(keyword.arg is None for keyword in call.keywords):
            raise SecurityError("database_config() declarations must use literal keyword arguments.")
        try:
            values = {keyword.arg: ast.literal_eval(keyword.value) for keyword in call.keywords}
        except ValueError as e:
            raise SecurityError(
                "database_config() declarations may contain only literal values."
            ) from e
        declarations.append(values)

    for values in declarations:
        database_config(**values)


def _is_docstring(statement: ast.stmt) -> bool:
    return (
        isinstance(statement, ast.Expr)
        and isinstance(statement.value, ast.Constant)
        and isinstance(statement.value.value, str)
    )


def _is_database_config_import(statement: ast.stmt) -> bool:
    return (
        isinstance(statement, ast.ImportFrom)
        and statement.module == "dbwarden"
        and statement.level == 0
        and len(statement.names) == 1
        and statement.names[0].name == "database_config"
        and statement.names[0].asname is None
    )


def _is_database_config_call(call: ast.Call) -> bool:
    return isinstance(call.func, ast.Name) and call.func.id == "database_config"


def _module_name_for_path(filepath: Path, base_dir: Path) -> str:
    """Derive a unique module name from the file path relative to base_dir."""
    relative = filepath.resolve().relative_to(base_dir.resolve())
    return relative.with_suffix('').as_posix().replace('/', '.')


def load_model_module(filepath: Path, base_dir: Path) -> Any:
    """
    Load a model module with path validation.

    For model files (unlike config), we allow sqlalchemy and other model-related
    imports - we're just validating the path is within project.

    Args:
        filepath: Path to the model file
        base_dir: Project root directory

    Returns:
        Loaded module or None if failed
    """
    validate_model_path(filepath, base_dir)

    # Derive a module name for cache lookups and registration.
    # Files outside base_dir (e.g. /tmp during tests) get no cache key.
    try:
        module_name = _module_name_for_path(filepath, base_dir)
    except ValueError:
        module_name = None

    try:
        file_stat = filepath.stat()
    except OSError:
        file_stat = None

    # Reuse cached modules only when the source file is unchanged.
    # If the module was pre-imported by the app (no cache attrs), set attrs
    # and return it to avoid re-execution (which would crash on duplicate tables).
    if module_name is not None and module_name in sys.modules:
        cached = sys.modules[module_name]
        cached_mtime = getattr(cached, "__dbwarden_source_mtime_ns__", None)
        cached_size = getattr(cached, "__dbwarden_source_size__", None)
        cached_path = getattr(cached, "__dbwarden_source_path__", None)
        if cached_mtime is None and file_stat is not None:
            if cached_path is not None and cached_path != str(filepath.resolve()):
                del sys.modules[module_name]
            else:
                cache_attrs0 = str(filepath.resolve())
                cache_attrs1 = file_stat.st_mtime_ns
                cache_attrs2 = file_stat.st_size
                cached.__dbwarden_source_path__ = cache_attrs0
                cached.__dbwarden_source_mtime_ns__ = cache_attrs1
                cached.__dbwarden_source_size__ = cache_attrs2
                return cached
        if (
            file_stat is not None
            and cached_mtime == file_stat.st_mtime_ns
            and cached_size == file_stat.st_size
            and cached_path == str(filepath.resolve())
        ):
            return cached
        del sys.modules[module_name]

    # Check DBWARDEN_DISABLE_SANDBOX env var
    if os.environ.get("DBWARDEN_DISABLE_SANDBOX"):
        return _unsafe_load_model(filepath, base_dir)

    try:
        import importlib.util

        name = module_name or f"_dbwarden_imported_{filepath.stem}"
        spec = importlib.util.spec_from_file_location(name, filepath)
        if spec is None or spec.loader is None:
            logger.warning("Could not create module spec for model: %s", filepath)
            return None

        module = importlib.util.module_from_spec(spec)
        if module_name is not None:
            sys.modules[module_name] = module
        spec.loader.exec_module(module)
        if file_stat is None:
            file_stat = filepath.stat()
        module.__dbwarden_source_path__ = str(filepath.resolve())
        module.__dbwarden_source_mtime_ns__ = file_stat.st_mtime_ns
        module.__dbwarden_source_size__ = file_stat.st_size

        return module
    except Exception as e:
        logger.warning("Failed to load model %s: %s", filepath, str(e))
        if module_name is not None and module_name in sys.modules:
            del sys.modules[module_name]
        return None


def _unsafe_load_model(filepath: Path, base_dir: Optional[Path] = None) -> Any:
    """Unsandboxed model load."""
    import importlib.util

    module_name = "models"
    if base_dir is not None:
        try:
            module_name = _module_name_for_path(filepath, base_dir)
        except ValueError:
            pass  # file not under base_dir; use fallback name

    spec = importlib.util.spec_from_file_location(module_name, filepath)
    if spec is None or spec.loader is None:
        return None

    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)

    return module
