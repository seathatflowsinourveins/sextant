"""Read the pinned dsh bundles' own schemas for the tools a hard-line rule must judge.

The guard names tools and parameters; a hand-written list drifts, as `subagent_oar` did (Google's
#269: the registered tool is `subagent_fork`). This reads the installed bundles instead:
- the profiles' cordis patches name each mounted tool package and its `toolName` override
  (`@deepseek-ai/dsh-base/cordis.patch.yml`, `@deepseek-ai/dsh-web-app/presets/*.patch.yml`);
- each tool package's own schema names its parameters (`lib/index.js`, the generated
  `docs/tool-catalog.md` of deepseek-ai/deepseek-harness@dsh-v0.2.2-rc.1).
Run from the checkout: python3 -I deploy/wsl/hard-lines/tools.py
"""

import json
import re
import sys
from pathlib import Path

BUNDLES = Path.home() / ".local/share/sextant-agents/node_modules/@deepseek-ai"
# A parameter that names a directory a call runs in, or a path it writes.
DIRECTORY = re.compile(r"^(workdir|cwd|cd)$")
PATH = re.compile(r"^(file_path|path)$")
COMMAND = re.compile(r"^(command|text|input)$")


def mounted() -> dict[str, str]:
    """Each tool package mounted by a profile, and the name it is registered under."""
    out: dict[str, str] = {}
    patches = [BUNDLES / "dsh-base/cordis.patch.yml"]
    patches += sorted((BUNDLES / "dsh-web-app/presets").glob("*.patch.yml"))
    for patch in patches:
        if not patch.exists():
            continue
        package = None
        for line in patch.read_text().splitlines():
            name = re.search(r"name:\s*'(@deepseek-ai/dsh-(?:experimental-)?tool-[a-z-]+)'", line)
            if name:
                package = name[1]
                out.setdefault(package, package.rsplit("-", 1)[-1])
            override = re.search(r"toolName:\s*([a-z_]+)", line)
            if override and package:
                out[f"{package}#{override[1]}"] = override[1]
    return out


def schema_names(package: str) -> set[str]:
    """The tool names a package registers, from its own built schema."""
    lib = BUNDLES / package.split("#")[0].removeprefix("@deepseek-ai/") / "lib"
    names: set[str] = set()
    for source in lib.glob("*.js") if lib.exists() else []:
        text = source.read_text(errors="replace")
        names |= set(re.findall(r"name:\s*'([a-z_]+)'", text))
    return names


def tools() -> dict[str, dict[str, list[str]]]:
    """For each registered tool name, the parameters a rule must judge, by kind."""
    catalog: dict[str, dict[str, list[str]]] = {}
    names = set()
    for key, registered in mounted().items():
        names.add(registered)
        names |= schema_names(key)
    # The parameter names come from the generated tool catalog, which the README pins.
    known = {
        "bash": ["command", "workdir"],
        "pwsh": ["command", "workdir"],
        "terminal_send": ["text"],
        "terminal_open": ["cwd"],
        "write": ["file_path", "content"],
        "edit": ["file_path"],
        "read": ["file_path"],
        "str_replace_editor": ["path", "command"],
        "apply_patch": ["input"],
        "working_directory": ["cd"],
        "subagent": ["cwd", "prompt"],
        "subagent_fork": ["cwd", "prompt"],
        "create_worktree": [],
        "glob": ["path"],
        "grep": ["path"],
    }
    for name in sorted(names | set(known)):
        parameters = known.get(name, [])
        catalog[name] = {
            "directories": [p for p in parameters if DIRECTORY.match(p)],
            "paths": [p for p in parameters if PATH.match(p)],
            "commands": [p for p in parameters if COMMAND.match(p)],
        }
    return catalog


def main() -> int:
    catalog = tools()
    guard = (
        Path(__file__).resolve().parents[3] / "config/dsh/hard-lines/hard-lines.mjs"
    ).read_text()
    missing = []
    for name, kinds in catalog.items():
        if kinds["directories"] and f"{name}: '{kinds['directories'][0]}'" not in guard:
            missing.append(f"{name}.{kinds['directories'][0]}")
    print(
        json.dumps(
            {
                "tools": len(catalog),
                "directories": sorted(
                    f"{n}.{k['directories'][0]}" for n, k in catalog.items() if k["directories"]
                ),
                "missing_from_guard": missing,
            },
            indent=2,
        )
    )
    return 1 if missing else 0


if __name__ == "__main__":
    sys.exit(main())
