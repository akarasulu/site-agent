from pathlib import Path

from site_agent.cli import main


def test_completion_suggests_top_level_and_nested_commands(capsys):
    assert main(["completion", "complete", "--cword", "1", "--", "site-agent", "m"]) == 0
    assert "mcp" in capsys.readouterr().out.splitlines()

    assert main(["completion", "complete", "--cword", "2", "--", "site-agent", "mcp", "i"]) == 0
    assert "import" in capsys.readouterr().out.splitlines()


def test_completion_suggests_options_choices_and_profiles(tmp_path, monkeypatch, capsys):
    monkeypatch.chdir(tmp_path)
    (Path("profiles") / "zte-router").mkdir(parents=True)
    (Path("profiles") / "mock-app").mkdir(parents=True)

    assert main(["completion", "complete", "--cword", "3", "--", "site-agent", "mcp", "import", "--"]) == 0
    option_lines = capsys.readouterr().out.splitlines()
    assert "--profile" in option_lines
    assert "--target" in option_lines

    assert main(["completion", "complete", "--cword", "4", "--", "site-agent", "mcp", "import", "--target", "c"]) == 0
    assert capsys.readouterr().out.splitlines() == ["codex"]

    assert main(["completion", "complete", "--cword", "4", "--", "site-agent", "mcp", "import", "--profile", "z"]) == 0
    assert capsys.readouterr().out.splitlines() == ["zte-router"]


def test_completion_prints_shell_scripts(capsys):
    assert main(["completion", "bash"]) == 0
    assert "complete -F _site_agent_completion site-agent" in capsys.readouterr().out

    assert main(["completion", "zsh"]) == 0
    assert "#compdef site-agent" in capsys.readouterr().out

    assert main(["completion", "fish"]) == 0
    assert "complete -c site-agent" in capsys.readouterr().out

