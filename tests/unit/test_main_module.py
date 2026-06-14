import runpy

import pytest


def test_python_module_entrypoint_propagates_main_exit_code(monkeypatch):
    import site_agent.cli

    monkeypatch.setattr(site_agent.cli, "main", lambda: 7)

    with pytest.raises(SystemExit) as exc:
        runpy.run_module("site_agent.__main__", run_name="__main__")

    assert exc.value.code == 7
