"""Direct tests for the restricted config/model loader this plugin provides."""

from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path

import pytest

from dbwarden.exceptions import ConfigurationError

from dbwarden_sandbox import (
    RestrictedModuleFinder,
    SecurityError,
    load_config_module,
    load_model_module,
    validate_model_path,
    validate_path,
)


@pytest.fixture
def project(tmp_path: Path) -> Path:
    (tmp_path / ".git").mkdir()
    return tmp_path


def _unused_module_name() -> str:
    idx = 0
    while f"_dbw_sandbox_never_imported_{idx}" in sys.modules:
        idx += 1
    return f"_dbw_sandbox_never_imported_{idx}"


class TestValidatePath:
    def test_relative_path_inside_project_is_accepted(self, project: Path) -> None:
        (project / "dbwarden.py").write_text("")
        validate_path(Path("dbwarden.py"), project)

    def test_absolute_path_inside_project_is_accepted(self, project: Path) -> None:
        config = project / "dbwarden.py"
        config.write_text("")
        validate_path(config, project)

    def test_path_traversal_is_rejected(self, project: Path) -> None:
        with pytest.raises(SecurityError, match="path traversal"):
            validate_path(Path("../outside.py"), project)

    def test_path_outside_project_tree_is_rejected(self, project: Path) -> None:
        with tempfile.TemporaryDirectory() as other:
            outside = Path(other) / "dbwarden.py"
            outside.write_text("")
            with pytest.raises(SecurityError, match="outside project tree"):
                validate_path(outside, project)


class TestValidateModelPath:
    def test_traversal_is_rejected(self, project: Path) -> None:
        with pytest.raises(SecurityError, match="path traversal"):
            validate_model_path(Path("../models/user.py"), project)

    def test_path_outside_project_is_allowed(self, project: Path) -> None:
        """Model paths are user-configured, so only traversal is blocked."""
        with tempfile.TemporaryDirectory() as other:
            validate_model_path(Path(other) / "user.py", project)


class TestRestrictedModuleFinder:
    def test_dbwarden_imports_are_permitted(self, project: Path) -> None:
        finder = RestrictedModuleFinder(project)
        assert finder.find_spec("dbwarden") is None
        assert finder.find_spec("dbwarden.config") is None

    def test_other_imports_raise(self, project: Path) -> None:
        finder = RestrictedModuleFinder(project)
        with pytest.raises(SecurityError, match="Import 'requests' not allowed"):
            finder.find_spec("requests")


class TestLoadConfigModule:
    def test_dbwarden_only_config_loads(self, project: Path) -> None:
        config = project / "dbwarden.py"
        config.write_text(
            "from dbwarden import database_config\n\n"
            "database_config(database_name='primary', default=True, "
            "database_type='sqlite', database_url_sync='sqlite:///./test.db')\n"
        )
        load_config_module(config, project)

    def test_disallowed_import_raises_security_error(self, project: Path) -> None:
        banned = _unused_module_name()
        config = project / "dbwarden.py"
        config.write_text(f"import {banned}\n")
        with pytest.raises(SecurityError, match=f"Import '{banned}' not allowed"):
            load_config_module(config, project)

    def test_other_failures_surface_as_configuration_error(self, project: Path) -> None:
        config = project / "dbwarden.py"
        config.write_text("raise ValueError('boom')\n")
        with pytest.raises(ConfigurationError, match="Failed to load config"):
            load_config_module(config, project)

    def test_module_is_not_left_in_sys_modules(self, project: Path) -> None:
        config = project / "dbwarden.py"
        config.write_text("x = 1\n")
        before = set(sys.modules)
        load_config_module(config, project)
        assert {n for n in set(sys.modules) - before if n.startswith("_dbwarden_config_")} == set()

    def test_finder_is_removed_from_meta_path(self, project: Path) -> None:
        config = project / "dbwarden.py"
        config.write_text(f"import {_unused_module_name()}\n")
        depth = len(sys.meta_path)
        with pytest.raises(SecurityError):
            load_config_module(config, project)
        assert len(sys.meta_path) == depth

    def test_disable_sandbox_env_var_falls_back_to_plain_import(
        self, project: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("DBWARDEN_DISABLE_SANDBOX", "1")
        config = project / "dbwarden.py"
        config.write_text("import os\n\nSENTINEL = os.sep\n")
        load_config_module(config, project)  # would raise SecurityError when sandboxed


class TestLoadModelModule:
    def test_model_module_may_import_freely(self, project: Path) -> None:
        model = project / "models" / "user.py"
        model.parent.mkdir()
        model.write_text("import json\n\nSENTINEL = json.dumps({'ok': True})\n")
        module = load_model_module(model, project)
        assert module.SENTINEL == '{"ok": true}'

    def test_traversal_is_rejected(self, project: Path) -> None:
        with pytest.raises(SecurityError, match="path traversal"):
            load_model_module(Path("../models/user.py"), project)


class TestHookRegistration:
    def test_setup_registers_both_loader_hooks(self) -> None:
        from dbwarden.plugin_conformance import assert_setup_registers

        import dbwarden_sandbox

        registrar = assert_setup_registers(
            dbwarden_sandbox.setup,
            plugin="dbwarden-sandbox",
            value_hooks=("load_config_module", "load_model_module"),
        )
        assert set(registrar.hooks) == {"load_config_module", "load_model_module"}
