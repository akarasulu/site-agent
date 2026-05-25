from __future__ import annotations

import json
import os
import sys
from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class McpImportSpec:
    name: str
    command: str
    args: list[str]
    cwd: str
    env: dict[str, str] = field(default_factory=dict)


def build_mcp_import_spec(
    profile_name: str,
    server_name: str | None = None,
    project_dir: Path | None = None,
    python_bin: Path | None = None,
    engine_dir: Path | None = None,
    env: dict[str, str] | None = None,
) -> McpImportSpec:
    merged_env = dict(env or {})
    if engine_dir:
        merged_env["PYTHONPATH"] = str(engine_dir.resolve())
    elif os.environ.get("PYTHONPATH"):
        merged_env["PYTHONPATH"] = os.environ["PYTHONPATH"]
    command_path = python_bin or Path(sys.executable)
    if not command_path.is_absolute():
        command_path = (Path.cwd() / command_path).absolute()
    return McpImportSpec(
        name=server_name or profile_name.replace("-", "_"),
        command=str(command_path),
        args=["-m", "site_agent", "mcp", "serve", "--profile", profile_name],
        cwd=str((project_dir or Path.cwd()).resolve()),
        env=merged_env,
    )


def render_mcp_json(spec: McpImportSpec) -> str:
    server = {"command": spec.command, "args": spec.args, "cwd": spec.cwd}
    if spec.env:
        server["env"] = spec.env
    return json.dumps({"mcpServers": {spec.name: server}}, indent=2)


def render_codex_toml(spec: McpImportSpec) -> str:
    args = ", ".join(json.dumps(value) for value in spec.args)
    lines = [
        f"[mcp_servers.{spec.name}]",
        f"command = {json.dumps(spec.command)}",
        f"args = [{args}]",
        f"cwd = {json.dumps(spec.cwd)}",
    ]
    if spec.env:
        lines.extend(["", f"[mcp_servers.{spec.name}.env]"])
        lines.extend(f"{key} = {json.dumps(value)}" for key, value in sorted(spec.env.items()))
    return "\n".join(lines) + "\n"


def marked_block(target: str, server_name: str, body: str) -> str:
    return (
        f"# BEGIN site-agent mcp import: {target}:{server_name}\n"
        f"{body.rstrip()}\n"
        f"# END site-agent mcp import: {target}:{server_name}\n"
    )


def replace_marked_block(existing: str, block: str, target: str, server_name: str) -> str:
    start = f"# BEGIN site-agent mcp import: {target}:{server_name}"
    end = f"# END site-agent mcp import: {target}:{server_name}"
    if start in existing and end in existing:
        before, rest = existing.split(start, 1)
        _, after = rest.split(end, 1)
        return before.rstrip() + "\n\n" + block.rstrip() + "\n" + after.lstrip()
    suffix = "\n" if existing.endswith("\n") or not existing else "\n\n"
    return existing + suffix + block


def install_codex_config(config_path: Path, spec: McpImportSpec) -> None:
    config_path = config_path.expanduser()
    config_path.parent.mkdir(parents=True, exist_ok=True)
    existing = config_path.read_text(encoding="utf-8") if config_path.exists() else ""
    block = marked_block("codex", spec.name, render_codex_toml(spec))
    config_path.write_text(replace_marked_block(existing, block, "codex", spec.name), encoding="utf-8")
