"""Config-sandboxing tests moved here from core's tests/test_config.py.

Core resolves config modules through the ``load_config_module`` hook, so these
only exercise the restricted loader when this plugin is registered (see
conftest.py).
"""

import os
import sys
import tempfile
from pathlib import Path

import pytest

from dbwarden.config import get_config, get_database, get_multi_db_config, set_dev_mode


@pytest.fixture(autouse=True)
def reset_dev_mode():
    set_dev_mode(False)
    yield
    set_dev_mode(False)


class TestConfigSandboxClassification:
    """Tests for config source classification (isolated vs in-package) and
    precedence rules.

    Verifies that:
    - Top-level ``dbwarden.py`` is sandboxed (isolated).
    - ``DBWARDEN_CONFIG_MODULE`` beats full-scan discovery.
    - Full-scan discovered package-internal files (project-root or ``src/``
      layout) import normally (no sandbox).
    - Full-scan discovered files directly at project root are sandboxed.
    - Repeated config loads work (sys.modules ejection).
    """

    _added_paths: list[str] = []

    @staticmethod
    def _purge_package_modules(prefix: str = "app") -> None:
        for mod_name in list(sys.modules.keys()):
            if mod_name == prefix or mod_name.startswith(prefix + "."):
                del sys.modules[mod_name]

    def _cleanup_paths(self) -> None:
        for p in self._added_paths:
            if p in sys.path:
                sys.path.remove(p)
        self._added_paths.clear()

    def _add_sys_path(self, p: str) -> None:
        if p not in sys.path:
            sys.path.insert(0, p)
            self._added_paths.append(p)

    @staticmethod
    def _unused_module_name() -> str:
        """Return a module name that is not currently in sys.modules."""
        idx = 0
        while True:
            name = f"_dbw_test_never_imported_{idx}"
            if name not in sys.modules:
                return name
            idx += 1

    def _ensure_git_marker(self, tmpdir: str) -> None:
        (Path(tmpdir) / ".git").mkdir()

    def _write_package(
        self, base: Path, pkg_path: str, files: dict[str, str]
    ) -> None:
        for relpath, content in files.items():
            full = base / pkg_path / relpath
            full.parent.mkdir(parents=True, exist_ok=True)
            full.write_text(content)

    def test_top_level_dbwarden_py_still_sandboxed(self):
        """dbwarden.py at project root must remain sandboxed (regression)."""
        banned_mod = self._unused_module_name()
        tmp = Path(tempfile.mkdtemp())
        old_cwd = os.getcwd()
        os.chdir(str(tmp))
        try:
            self._ensure_git_marker(str(tmp))
            (tmp / "dbwarden.py").write_text(
                "from dbwarden import database_config\n"
                f"import {banned_mod}\n\n"
                "database_config(database_name='primary', default=True, "
                "database_type='sqlite', database_url_sync='sqlite:///./test.db')\n"
            )
            from dbwarden_sandbox import SecurityError

            with pytest.raises(SecurityError, match=f"Import '{banned_mod}' not allowed"):
                get_config()
        finally:
            os.chdir(old_cwd)
            import shutil
            shutil.rmtree(str(tmp), ignore_errors=True)

    def test_package_internal_config_imports_normally(self):
        """Full-scan discovered file inside app package imports normally."""
        tmp = Path(tempfile.mkdtemp())
        old_cwd = os.getcwd()
        os.chdir(str(tmp))
        try:
            self._purge_package_modules()
            self._ensure_git_marker(str(tmp))
            self._add_sys_path(str(tmp))
            self._write_package(tmp, "app/core", {
                "__init__.py": "",
                "config.py": "DATABASE_URL = 'sqlite:///./test.db'\n",
                "databases.py": (
                    "from dbwarden import database_config\n"
                    "from app.core.config import DATABASE_URL\n\n"
                    "database_config(database_name='primary', default=True, "
                    "database_type='sqlite', database_url_sync=DATABASE_URL)\n"
                ),
            })
            (tmp / "app" / "__init__.py").write_text("")

            cfg = get_config()
            assert cfg.database_type == "sqlite"
            assert cfg.sqlalchemy_url.endswith("test.db")
        finally:
            self._purge_package_modules()
            self._cleanup_paths()
            os.chdir(old_cwd)
            import shutil
            shutil.rmtree(str(tmp), ignore_errors=True)

    def test_root_file_not_named_dbwarden_py_is_sandboxed(self):
        """Any file at project root with database_config() is sandboxed, not just dbwarden.py."""
        banned_mod = self._unused_module_name()
        tmp = Path(tempfile.mkdtemp())
        old_cwd = os.getcwd()
        os.chdir(str(tmp))
        try:
            self._ensure_git_marker(str(tmp))
            (tmp / "settings.py").write_text(
                "from dbwarden import database_config\n"
                f"import {banned_mod}\n\n"
                "database_config(database_name='primary', default=True, "
                "database_type='sqlite', database_url_sync='sqlite:///./test.db')\n"
            )
            from dbwarden_sandbox import SecurityError

            with pytest.raises(SecurityError, match=f"Import '{banned_mod}' not allowed"):
                get_config()
        finally:
            os.chdir(old_cwd)
            import shutil
            shutil.rmtree(str(tmp), ignore_errors=True)

    def test_dbwarden_config_module_beats_full_scan(self):
        """DBWARDEN_CONFIG_MODULE takes priority over full-scan-discovered files."""
        tmp = Path(tempfile.mkdtemp())
        old_cwd = os.getcwd()
        old_env = os.environ.get("DBWARDEN_CONFIG_MODULE")
        os.chdir(str(tmp))
        try:
            self._purge_package_modules()
            self._ensure_git_marker(str(tmp))
            self._add_sys_path(str(tmp))
            # Create a full-scan-discoverable file (would be found by full-scan)
            self._write_package(tmp, "app/core", {
                "__init__.py": "",
                "config.py": "DATABASE_URL = 'sqlite:///./full-scan.db'\n",
                "databases.py": (
                    "from dbwarden import database_config\n"
                    "from app.core.config import DATABASE_URL\n\n"
                    "database_config(database_name='primary', default=True, "
                    "database_type='sqlite', database_url_sync=DATABASE_URL)\n"
                ),
            })
            (tmp / "app" / "__init__.py").write_text("")

            # Also create a separate package for DBWARDEN_CONFIG_MODULE to point at
            pkg_dir = Path(tempfile.mkdtemp())
            self._add_sys_path(str(pkg_dir))
            self._write_package(pkg_dir, "other/db", {
                "__init__.py": "",
                "config.py": "OTHER_URL = 'sqlite:///./explicit.db'\n",
                "databases.py": (
                    "from dbwarden import database_config\n"
                    "from other.db.config import OTHER_URL\n\n"
                    "database_config(database_name='primary', default=True, "
                    "database_type='sqlite', database_url_sync=OTHER_URL)\n"
                ),
            })
            (pkg_dir / "other" / "__init__.py").write_text("")

            os.environ["DBWARDEN_CONFIG_MODULE"] = "other.db.databases"

            # Should resolve to explicit module (other.db.databases), not full-scan
            cfg = get_config()
            assert cfg.sqlalchemy_url.endswith("explicit.db")
        finally:
            if old_env is not None:
                os.environ["DBWARDEN_CONFIG_MODULE"] = old_env
            else:
                os.environ.pop("DBWARDEN_CONFIG_MODULE", None)
            self._purge_package_modules("other")
            self._purge_package_modules("app")
            self._cleanup_paths()
            os.chdir(old_cwd)
            import shutil
            shutil.rmtree(str(tmp), ignore_errors=True)
            shutil.rmtree(str(pkg_dir), ignore_errors=True)


    def test_src_layout_resolved_correctly(self):
        """Config file under src/ is resolved via src/ import root, not project root."""
        tmp = Path(tempfile.mkdtemp())
        old_cwd = os.getcwd()
        os.chdir(str(tmp))
        try:
            self._purge_package_modules("myapp")
            self._ensure_git_marker(str(tmp))
            self._add_sys_path(str(tmp))
            self._write_package(tmp, "src/myapp", {
                "__init__.py": "",
                "config.py": "DATABASE_URL = 'sqlite:///./test.db'\n",
                "databases.py": (
                    "from dbwarden import database_config\n"
                    "from myapp.config import DATABASE_URL\n\n"
                    "database_config(database_name='primary', default=True, "
                    "database_type='sqlite', database_url_sync=DATABASE_URL)\n"
                ),
            })
            (tmp / "src" / "__init__.py").write_text("")

            cfg = get_config()
            assert cfg.database_type == "sqlite"
            assert cfg.sqlalchemy_url.endswith("test.db")
        finally:
            self._purge_package_modules("myapp")
            self._cleanup_paths()
            os.chdir(old_cwd)
            import shutil
            shutil.rmtree(str(tmp), ignore_errors=True)

    def test_repeated_load_with_registry_reset(self):
        """Repeated get_database() + get_multi_db_config() still registers entries.

        Regression test for sys.modules ejection: the second call must re-execute
        the module so database_config(...) re-registers after reset_registry().
        """
        tmp = Path(tempfile.mkdtemp())
        old_cwd = os.getcwd()
        os.chdir(str(tmp))
        try:
            self._purge_package_modules("app")
            self._ensure_git_marker(str(tmp))
            self._add_sys_path(str(tmp))
            self._write_package(tmp, "app/core", {
                "__init__.py": "",
                "config.py": "DATABASE_URL = 'sqlite:///./test.db'\n",
                "databases.py": (
                    "from dbwarden import database_config\n"
                    "from app.core.config import DATABASE_URL\n\n"
                    "database_config(database_name='primary', default=True, "
                    "database_type='sqlite', database_url_sync=DATABASE_URL)\n"
                ),
            })
            (tmp / "app" / "__init__.py").write_text("")

            # First load (cached in sys.modules after)
            cfg1 = get_database()
            assert cfg1.sqlalchemy_url.endswith("test.db")

            # Second load from the same process, must re-register after reset
            cfg2 = get_multi_db_config()
            assert cfg2.default == "primary"
            assert len(cfg2.databases) == 1

            # Third load via get_database again
            cfg3 = get_database()
            assert cfg3.sqlalchemy_url.endswith("test.db")
        finally:
            self._purge_package_modules("app")
            self._cleanup_paths()
            os.chdir(old_cwd)
            import shutil
            shutil.rmtree(str(tmp), ignore_errors=True)


