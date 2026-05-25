from __future__ import annotations

import argparse
from pathlib import Path


def action_expects_value(action: argparse.Action) -> bool:
    return not isinstance(action, (argparse._StoreTrueAction, argparse._StoreFalseAction, argparse._HelpAction))


def option_actions(parser: argparse.ArgumentParser) -> dict[str, argparse.Action]:
    actions: dict[str, argparse.Action] = {}
    for action in parser._actions:
        for option in action.option_strings:
            actions[option] = action
    return actions


def subparser_action(parser: argparse.ArgumentParser) -> argparse._SubParsersAction | None:
    for action in parser._actions:
        if isinstance(action, argparse._SubParsersAction):
            return action
    return None


def profile_names(workspace: Path) -> list[str]:
    profiles = workspace / "profiles"
    if not profiles.exists():
        return []
    return sorted(path.name for path in profiles.iterdir() if path.is_dir())


def value_completions(action: argparse.Action, workspace: Path) -> list[str]:
    if action.dest == "profile":
        return profile_names(workspace)
    if action.choices:
        return sorted(str(choice) for choice in action.choices)
    return []


def filter_prefix(values: list[str], prefix: str) -> list[str]:
    return [value for value in values if value.startswith(prefix)]


def complete(parser: argparse.ArgumentParser, words: list[str], cword: int, workspace: Path) -> list[str]:
    current = words[cword] if cword < len(words) else ""
    tokens = words[1:cword]
    active = parser
    active_subparser: argparse._SubParsersAction | None = None
    previous_option: argparse.Action | None = None

    index = 0
    while index < len(tokens):
        token = tokens[index]
        options = option_actions(active)
        if previous_option:
            previous_option = None
            index += 1
            continue
        if token in options:
            action = options[token]
            if action_expects_value(action):
                previous_option = action
            index += 1
            continue
        sub = subparser_action(active)
        if sub and token in sub.choices:
            active = sub.choices[token]
            active_subparser = None
            index += 1
            continue
        active_subparser = sub
        index += 1

    options = option_actions(active)
    if tokens and tokens[-1] in options and action_expects_value(options[tokens[-1]]):
        return filter_prefix(value_completions(options[tokens[-1]], workspace), current)

    if current.startswith("-"):
        values = sorted(option for action in active._actions for option in action.option_strings)
        return filter_prefix(values, current)

    sub = active_subparser or subparser_action(active)
    if sub:
        return filter_prefix(sorted(sub.choices), current)
    return []


def bash_script(program: str = "site-agent") -> str:
    return f"""# site-agent bash completion
_site_agent_completion() {{
  local IFS=$'\\n'
  COMPREPLY=($(COMP_WORDS=("${{COMP_WORDS[@]}}") {program} completion complete --cword "$COMP_CWORD" -- "${{COMP_WORDS[@]}}"))
}}
complete -F _site_agent_completion {program}
"""


def zsh_script(program: str = "site-agent") -> str:
    return f"""#compdef {program}
# site-agent zsh completion
_site_agent_completion() {{
  local -a completions
  completions=("${{(@f)$({program} completion complete --cword "$((CURRENT - 1))" -- "${{words[@]}}")}}")
  _describe 'site-agent completions' completions
}}
_site_agent_completion "$@"
"""


def fish_script(program: str = "site-agent") -> str:
    return f"""# site-agent fish completion
function __site_agent_complete
  set -l tokens (commandline -opc)
  set -l current (commandline -ct)
  set -l words {program} $tokens $current
  set -l cword (math (count $words) - 1)
  {program} completion complete --cword $cword -- $words
end
complete -c {program} -f -a '(__site_agent_complete)'
"""
