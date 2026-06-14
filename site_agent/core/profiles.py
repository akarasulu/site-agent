from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
import shutil
from urllib.parse import urlparse

from .models import new_id, utc_now
from .storage import ensure_dir, read_json, write_json


@dataclass
class AuthConfig:
    strategy: str = "manual-session"
    storage_state_path: str = "auth/storage-state.json"
    username_env: str | None = None
    password_env: str | None = None
    verified_at: str | None = None


@dataclass
class CrawlPolicy:
    max_pages: int = 50
    read_only: bool = True
    browser_backend: str = "playwright"
    allow_subdomains: bool = False
    ignore_https_errors: bool = False
    max_crawl_seconds: int = 300
    js_navigation_texts: list[str] = field(default_factory=list)
    discover_js_states: bool = False
    max_js_states: int = 50
    max_js_depth: int = 4
    ai_navigation_planning: bool = True
    ai_navigation_budget: int = 3
    click_deny_patterns: list[str] = field(default_factory=list)
    navigation_wait_ms: int = 1200
    discover_form_flows: bool = True
    max_form_flow_probes: int = 8
    include_globs: list[str] = field(default_factory=list)
    exclude_globs: list[str] = field(default_factory=list)
    redaction_patterns: list[str] = field(default_factory=list)


@dataclass
class RiskPolicy:
    high_risk_requires_confirmation: bool = True
    write_mode: str = "dry-run"


@dataclass
class Profile:
    id: str
    name: str
    base_url: str
    host_allowlist: list[str]
    created_at: str
    auth: AuthConfig = field(default_factory=AuthConfig)
    crawl: CrawlPolicy = field(default_factory=CrawlPolicy)
    risk: RiskPolicy = field(default_factory=RiskPolicy)
    ontology_seed_path: str = "ontology.seed.json"
    docs_path: str = "docs"
    tool_aliases: dict[str, str] = field(default_factory=dict)

    @property
    def directory_name(self) -> str:
        return self.name


def profile_root(workspace: Path, name: str) -> Path:
    return workspace / "profiles" / name


def output_root(workspace: Path, profile_name: str) -> Path:
    return workspace / "output" / profile_name


def init_profile(workspace: Path, name: str, base_url: str) -> Profile:
    parsed = urlparse(base_url)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise ValueError("base-url must be an absolute http(s) URL, for example https://example.com")

    root = profile_root(workspace, name)
    ensure_dir(root / "docs")
    ensure_dir(root / "auth")
    profile = Profile(
        id=new_id("profile"),
        name=name,
        base_url=base_url.rstrip("/"),
        host_allowlist=[parsed.netloc],
        created_at=utc_now(),
    )
    write_json(root / "profile.json", profile)
    write_json(root / "ontology.seed.json", {"terms": []})
    (root / "docs" / ".gitkeep").touch()
    return profile


def load_profile(workspace: Path, name: str) -> Profile:
    path = profile_root(workspace, name) / "profile.json"
    if not path.exists():
        raise FileNotFoundError(f"Profile '{name}' does not exist. Run: site-agent profile init --name {name} --base-url https://example.com")
    raw = read_json(path)
    return Profile(
        id=raw["id"],
        name=raw["name"],
        base_url=raw["base_url"],
        host_allowlist=list(raw.get("host_allowlist", [])),
        created_at=raw["created_at"],
        auth=AuthConfig(**raw.get("auth", {})),
        crawl=CrawlPolicy(**raw.get("crawl", {})),
        risk=RiskPolicy(**raw.get("risk", {})),
        ontology_seed_path=raw.get("ontology_seed_path", "ontology.seed.json"),
        docs_path=raw.get("docs_path", "docs"),
        tool_aliases=dict(raw.get("tool_aliases", {})),
    )


def save_profile(workspace: Path, profile: Profile) -> None:
    write_json(profile_root(workspace, profile.name) / "profile.json", profile)


def configure_auth(workspace: Path, profile_name: str, username_env: str | None, password_env: str | None) -> Profile:
    profile = load_profile(workspace, profile_name)
    profile.auth.username_env = username_env
    profile.auth.password_env = password_env
    profile.auth.verified_at = utc_now()
    save_profile(workspace, profile)
    return profile


def import_example_profile(workspace: Path, source: Path, name: str | None = None) -> Profile:
    if not source.exists():
        raise FileNotFoundError(f"Example profile does not exist: {source}")
    raw = read_json(source / "profile.json")
    profile_name = name or raw["name"]
    target = profile_root(workspace, profile_name)
    if target.exists():
        raise FileExistsError(f"Profile '{profile_name}' already exists at {target}")
    shutil.copytree(source, target)
    if profile_name != raw["name"]:
        raw["name"] = profile_name
        write_json(target / "profile.json", raw)
    return load_profile(workspace, profile_name)
