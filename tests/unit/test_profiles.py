from pathlib import Path

import pytest

from site_agent.core.profiles import configure_auth, import_example_profile, init_profile, load_profile, profile_root
from site_agent.core.storage import read_json


def test_init_profile_rejects_non_http_urls(tmp_path):
    with pytest.raises(ValueError, match="absolute http"):
        init_profile(tmp_path, "bad", "file:///tmp/site")


def test_profile_init_load_and_auth_store_references_only(tmp_path):
    profile = init_profile(tmp_path, "demo", "https://example.test/")

    root = profile_root(tmp_path, "demo")
    assert profile.base_url == "https://example.test"
    assert profile.host_allowlist == ["example.test"]
    assert (root / "docs").is_dir()
    assert (root / "auth").is_dir()
    assert read_json(root / "ontology.seed.json") == {"terms": []}

    configured = configure_auth(tmp_path, "demo", "DEMO_USER", "DEMO_PASSWORD")
    loaded = load_profile(tmp_path, "demo")

    assert configured.auth.username_env == "DEMO_USER"
    assert loaded.auth.password_env == "DEMO_PASSWORD"
    assert "DEMO_PASSWORD" in (root / "profile.json").read_text(encoding="utf-8")
    assert "secret" not in (root / "profile.json").read_text(encoding="utf-8").lower()


def test_import_example_profile_can_rename_and_refuses_clobber(tmp_path):
    source = tmp_path / "source"
    source.mkdir()
    profile = init_profile(source.parent, "source", "https://example.test")
    source = profile_root(source.parent, profile.name)

    imported = import_example_profile(tmp_path, source, "renamed")

    assert imported.name == "renamed"
    assert Path(tmp_path / "profiles" / "renamed" / "profile.json").exists()
    assert load_profile(tmp_path, "renamed").base_url == "https://example.test"

    with pytest.raises(FileExistsError):
        import_example_profile(tmp_path, source, "renamed")
