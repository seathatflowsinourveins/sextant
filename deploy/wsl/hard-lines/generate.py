"""Generate every engine's hard-line rules from deploy/wsl/hard-lines/matrix.json.

One canonical table, four rule sets: `.claude/settings.json`'s `permissions.deny`,
`.codex/rules/default.rules`, `deploy/wsl/hard-lines/antigravity.json` and the dsh guard's own
`rules` array (which carries Claude's Bash rules verbatim). A spelling is added to the matrix,
never to a rule file, and `tests/proofs/test_hard_lines.py` walks the whole cross product.

Each engine gets what its own matcher can express (docs read 2026-11-08):
- Claude Code (code.claude.com/docs/en/permissions.md): globs over the command text, where `*` is
  any text including spaces, so one `*` covers any number of option words. Case is exact.
- Codex (openai/codex@rust-v0.167.0 codex-rs/execpolicy/README.md): token prefixes, each token a
  literal or a list of literals, with `canonical_matching` for caseless comparison. An option slot
  is one more token position, so 0 to N slots are N+1 rules.
- Antigravity (antigravity.google/docs/permissions.md): `command(prefix)` word by word, or
  `command(regex:…)` where each whitespace-separated token is one anchored expression; an option
  slot is a `\\S+` token.
- dsh (deepseek-harness ctx.tools.guard): Claude's own globs, applied after its parser strips the
  wrappers each matrix row describes.

Run from the checkout: python3 -I deploy/wsl/hard-lines/generate.py [--check]
"""

import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
KIT = ROOT / "deploy" / "wsl" / "hard-lines"
MATRIX = json.loads((KIT / "matrix.json").read_text())
SLOTS = MATRIX["option_slots"]
WRAPPERS = [w["name"] for w in MATRIX["wrappers"]]
# The wrappers Claude Code strips itself, so a rule written for the inner command already covers
# them; the rest need a rule of their own (permissions.md, "Wrappers").
CLAUDE_STRIPS = {"timeout", "time", "nice", "nohup", "stdbuf", "command", "builtin", "noglob"}
CLAUDE_WRAPPERS = [name for name in WRAPPERS if name not in CLAUDE_STRIPS]


def words(target: dict) -> list[list[str]]:
    """The target's own words after the program: its subcommand, then each argument form."""
    head = target.get("subcommand", [])
    return [head + argument for argument in target["arguments"]]


def glob_paths(paths: list[str]) -> list[str]:
    """The path forms a glob needs for the table's paths: the bare name, and one `*/` when the
    table lists any prefixed form, since `*/x` spans every directory."""
    out = [""] if "" in paths else []
    if any(path for path in paths):
        out.append("*/")
    return out


def claude_rules() -> list[str]:
    """A glob per target, path form and argument form; `*` spans any option words."""
    rules: list[str] = []
    target_paths = glob_paths(MATRIX["paths"])
    wrapper_globs = glob_paths(MATRIX["wrapper_paths"])
    for target in MATRIX["targets"]:
        for program in target["programs"]:
            for path in target_paths:
                if target.get("shell_builtin") and path:
                    continue  # a builtin has no path form
                for rest in words(target):
                    name = f"{path}{program}"
                    if not rest:
                        rules += (
                            [f"Bash({name} *)"]
                            if not path
                            else [f"Bash({name})", f"Bash({name} *)"]
                        )
                        continue
                    if target["key"] == "push-branch-set":
                        rules.append(f"Bash({name} {rest[0]} *{rest[1]}*)")
                        continue
                    if target.get("destination_tail"):
                        # `*` spans the options and the remote; a tail that starts a word needs the
                        # space, one that continues a refspec does not.
                        head, last = " ".join(rest[:-1]), rest[-1]
                        # `*` spans a space too, so only a bare word needs one: `* main` must not
                        # match "domain", while `*refs/heads/main` covers both ` ` and `:` before
                        # it.
                        glue = "* " if last == "main" else "*"
                        rules += [
                            f"Bash({name} {head} {glue}{last})",
                            f"Bash({name} {head} {glue}{last} *)",
                        ]
                        continue
                    if target.get("shell_builtin"):
                        # bash's own options may precede the printing one (`export -f -p`), and a
                        # builtin takes no path: one glob spans whatever comes between.
                        rules += [f"Bash({name} *{rest[-1]})", f"Bash({name} *{rest[-1]} *)"]
                        continue
                    joined = " ".join(rest)
                    # Two wildcards mean a trailing ` *` no longer covers the bare command
                    # (permissions.md, "Wildcard patterns"), so a path form needs the exact rule.
                    rules += [f"Bash({name} {joined})"] if path else []
                    rules += [f"Bash({name} {joined} *)"]
    # A glob per wrapper, path form and program. Claude Code strips some wrappers itself, but not
    # every option form of them: the recorded receipt shows `nice -n5 wsl.exe` reaching no rule,
    # so each wrapper gets its own glob whether Claude Code strips it or not.
    # `command` is left out: a glob cannot tell its run form from its query form, and
    # `command -v <name>` only looks a program up (permissions.md, "Wrappers"). Claude Code strips
    # the run form itself, so `command wsl.exe` still matches the inner rule.
    for wrapper in (name for name in WRAPPERS if name != "command"):
        for path in wrapper_globs:
            for needle in ("wsl.exe", "env", "git push", "git worktree add"):
                rules.append(f"Bash({path}{wrapper} *{needle}*)")
    # git's own options come before the subcommand (`git -C <dir> push origin main`).
    for path in target_paths:
        for needle in (
            "push * main",
            "push *:main",
            "push *+main",
            "push *refs/heads/main",
            "push *--all*",
            "push *--branches*",
            "push *--mirror*",
            "worktree add *",
        ):
            rules.append(f"Bash({path}git -* {needle})")
            rules.append(f"Bash({path}git --* {needle})")
    # A shell's -c script and a Windows shell's command line carry the words themselves.
    for needle in ("wsl.exe", "printenv", "env", "git push", "git worktree add"):
        rules.append(f"Bash(*sh -*c* *{needle}*)")
    # `set` with no argument prints every variable inside cmd; a glob cannot require "no
    # argument", so `cmd /c set FOO=bar`, which only sets one, is refused too: a named over-block.
    for needle in ("wsl", "Env", "env", "set"):
        rules.append(f"Bash(*cmd.exe *{needle}*)")
        rules.append(f"Bash(*powershell* *{needle}*)")
        rules.append(f"Bash(*pwsh *{needle}*)")
    return list(dict.fromkeys(rules))


EDIT = ["Edit(//mnt/wsl/**)"]


def codex_rules() -> list[dict]:
    """A prefix rule per target, path form, option-slot count and argument form."""
    flags = sorted(
        {f for w in MATRIX["wrappers"] for f in w.get("flags", []) + w.get("valued", [])}
    )
    push_flags = [
        "-u",
        "--set-upstream",
        "-f",
        "--force",
        "--force-with-lease",
        "--force-if-includes",
        "--no-verify",
        "--atomic",
        "-n",
        "--dry-run",
        "-q",
        "--quiet",
        "-v",
        "--verbose",
        "--tags",
        "--follow-tags",
        "--porcelain",
        "--progress",
        "--prune",
        "--repo",
        "--thin",
        "-4",
        "-6",
        "--ipv4",
        "--ipv6",
        "--signed",
        "--no-signed",
        "--no-thin",
    ]
    rules: list[dict] = []
    for target in MATRIX["targets"]:
        if target.get("shell_builtin"):
            continue
        programs: list[str] = []
        for program in target["programs"]:
            programs += [f"{path}{program}" for path in MATRIX["paths"] if path != "*/"]
            programs += [f"{path}{program}" for path in target.get("windows_paths", [])]
            programs += target.get("cases", [])[1:]
        programs = list(dict.fromkeys(programs))
        caseless = bool(target.get("cases"))
        for rest in words(target):
            for slots in range(SLOTS + 1):
                pattern: list = [programs if len(programs) > 1 else programs[0]]
                if rest[:1]:
                    pattern.append(rest[0])
                    option = push_flags if target["line"] == "push" else flags
                    pattern += [option] * slots
                    tail = rest[1:]
                    if target.get("remotes"):
                        pattern.append(
                            target["remotes"]
                            if len(target["remotes"]) > 1
                            else target["remotes"][0]
                        )
                    if tail and target.get("destination_tail"):
                        # Codex matches whole tokens, so a refspec tail becomes the tokens that
                        # carry it: `main`, `HEAD:main`, `lane-x:main`, `+main`, `refs/heads/main`.
                        spelled = (
                            [tail[0]]
                            if tail[0][0].isalnum() or tail[0].startswith("+")
                            else [f"HEAD{tail[0]}", f"lane-x{tail[0]}", "HEAD:refs/heads/main"]
                        )
                        pattern.append(spelled if len(spelled) > 1 else spelled[0])
                    elif tail:
                        pattern.append(tail if len(tail) > 1 else tail[0])
                elif slots:
                    continue
                rules.append(
                    {
                        "pattern": pattern,
                        "line": target["line"],
                        "caseless": caseless,
                        "key": target["key"],
                    }
                )
    # 4a, kept by the lead on 2026-11-08: a prefix rule cannot see where a refspec lands, so every
    # explicit push to origin is forbidden, with 0 to N option words before the remote. A lane
    # pushes with plain `git push` or `just pr`.
    git_paths = [f"{path}git" for path in MATRIX["paths"] if path != "*/"]
    for slots in range(SLOTS + 1):
        pattern: list = [git_paths, "push", *([push_flags] * slots), "origin"]
        rules.append({"pattern": pattern, "line": "push", "caseless": False, "key": "push-origin"})
    # Every wrapper before every hard-line program, past the wrapper's own option words.
    targets = sorted(
        {
            f"{path}{program}"
            for target in MATRIX["targets"]
            if not target.get("shell_builtin")
            for program in target["programs"]
            for path in MATRIX["paths"]
            if path != "*/"
        }
        | {case for target in MATRIX["targets"] for case in target.get("cases", [])[1:]}
        | {
            f"{path}{program}"
            for target in MATRIX["targets"]
            for program in target["programs"]
            for path in target.get("windows_paths", [])
        }
    )
    for wrapper in MATRIX["wrappers"]:
        own = sorted(set(wrapper.get("flags", []))) or None
        valued = sorted(set(wrapper.get("valued", [])))
        durations = [
            "1",
            "2",
            "3",
            "5",
            "10",
            "15",
            "20",
            "30",
            "45",
            "60",
            "90",
            "120",
            "180",
            "300",
            "600",
            "900",
            "1200",
            "1800",
            "3600",
            "1s",
            "5s",
            "10s",
            "30s",
            "60s",
            "1m",
            "2m",
            "5m",
            "10m",
            "15m",
            "30m",
            "1h",
        ]
        paths_for = [""] if wrapper.get("shell_builtin") else MATRIX["wrapper_paths"]
        names = [f"{p}{wrapper['name']}" for p in paths_for]
        for slots in range(min(SLOTS, len(own or [])) + 1):
            pattern: list = [names if len(names) > 1 else names[0]]
            if slots:
                if not own:
                    continue
                pattern += [own] * slots
            if wrapper.get("positional"):
                pattern.append(durations)
            pattern.append(targets)
            rules.append(
                {
                    "pattern": pattern,
                    "line": "wrapper",
                    "caseless": True,
                    "key": f"wrap-{wrapper['name']}",
                }
            )
        for flag, allowed in (wrapper.get("values") or {}).items():
            rules.append(
                {
                    "pattern": [names, flag, allowed[0], targets],
                    "line": "wrapper",
                    "caseless": True,
                    "key": f"wrap-{wrapper['name']}-{flag}",
                }
            )
        if valued:
            values = [str(n) for n in range(-20, 21)] + ["L", "KILL", "TERM", "INT", "1s", "1m"]
            pattern = [names, valued, values]
            if wrapper.get("positional"):
                pattern.append(durations)
            rules.append(
                {
                    "pattern": [*pattern, targets],
                    "line": "wrapper",
                    "caseless": True,
                    "key": f"wrap-{wrapper['name']}-valued",
                }
            )
    # git behind a wrapper: the subcommand carries the line, whatever follows.
    for wrapper in MATRIX["wrappers"]:
        paths_for = [""] if wrapper.get("shell_builtin") else MATRIX["wrapper_paths"]
        names = [f"{p}{wrapper['name']}" for p in paths_for]
        own = sorted(set(wrapper.get("flags", [])))
        git_names = [f"{path}git" for path in MATRIX["paths"] if path != "*/"]
        git_flags = MATRIX["git_options"]["flags"] + MATRIX["git_options"]["valued"] + ["."]
        for slots in range(min(2, len(own)) + 1):
            for inner in range(SLOTS + 1):
                pattern = [names] + [own] * slots + [git_names] + [git_flags] * inner
                rules.append(
                    {
                        "pattern": [*pattern, ["push", "worktree"]],
                        "line": "git-wrapper",
                        "caseless": False,
                        "key": f"git-{wrapper['name']}-{slots}-{inner}",
                    }
                )
    # git's own options before the subcommand (git-scm.com/docs/git).
    # One slot token spans a flag, an option that takes a value, and the value itself, so a mix
    # such as `git --no-pager -C . push` is covered by three slots.
    git_words = (
        MATRIX["git_options"]["flags"]
        + MATRIX["git_options"]["valued"]
        + ["."]
        + [f"{k}=v" for k in MATRIX["git_options"]["glued"]]
    )
    git_paths_all = [f"{path}git" for path in MATRIX["paths"] if path != "*/"]
    for slots in range(1, SLOTS + 1):
        rules.append(
            {
                "pattern": [git_paths_all, *([git_words] * slots), ["push", "worktree"]],
                "line": "git-wrapper",
                "caseless": False,
                "key": f"git-options-{slots}",
            }
        )
    # Bash Reference Manual section 6.1, Invoking Bash, and its linked set/shopt lists,
    # read 2026-11-08; the whole documented terminal vocabulary lives in the matrix.
    # Codex rust-v0.167.0 execpolicy/src/parser.rs:171-215 and rule.rs:21-26,46-72 accept
    # only literal tokens or lists of literals: '*' is literal, not a per-position wildcard.
    # Thus FILE and unrestricted clusters cannot be covered exactly by finite prefix rules.
    # Keep their unlisted forms as explicit P1 residuals, never broaden to banning bash.
    invocation = MATRIX["shells"]["bash_invocation"]
    letters = sorted(
        set(
            invocation["set_letters"]
            + invocation["invocation_letters"]
            + invocation["synopsis_letters"]
        )
        - {"c"}
    )
    c_flags = sorted(set(invocation["c_cluster_literals"] + [f"-{c}c" for c in letters]))
    shell_words = sorted(
        {f"{sign}{c}" for sign in ("-", "+") for c in letters}
        | set(invocation["named_option_flags"])
        | set(invocation["set_names"])
        | set(invocation["shopt_names"])
        | set(invocation["long_options"])
        | set(invocation["file_literals"])
        | set(invocation["terminators"])
    )
    scripts = ["env", "printenv", "wsl.exe", "WSL.EXE"]
    for slots in range(SLOTS + 1):
        for before in (True, False) if slots else (True,):
            options = [shell_words] * slots
            middle = [*options, c_flags] if before else [c_flags, *options]
            rules.append(
                {
                    "pattern": [MATRIX["shells"]["posix"], *middle, scripts],
                    "line": "env",
                    "caseless": False,
                    "key": f"shell-c-{before}-{slots}",
                }
            )
    rules.append(
        {
            "pattern": [["cmd", "cmd.exe"], ["/c", "/k"], ["wsl", "wsl.exe", "set"]],
            "line": "wsl",
            "caseless": True,
            "key": "cmd",
        }
    )
    rules.append(
        {
            "pattern": [
                ["powershell", "powershell.exe", "pwsh", "pwsh.exe"],
                ["-c", "-Command"],
                ["wsl", "wsl.exe"],
            ],
            "line": "wsl",
            "caseless": True,
            "key": "pwsh",
        }
    )
    # PowerShell's own environment printers, whose Env: drive lists every variable.
    rules.append(
        {
            "pattern": [
                ["powershell", "powershell.exe", "pwsh", "pwsh.exe"],
                ["-c", "-Command"],
                ["Get-ChildItem", "gci", "Get-Item", "dir", "ls"],
            ],
            "line": "env",
            "caseless": True,
            "key": "pwsh-env",
        }
    )
    return rules


JUSTIFICATION = {
    "wsl": (
        "AGENTS.md Start: never run wsl.exe; --shutdown or --terminate would stop other distros."
    ),
    "push": (
        "AGENTS.md Landing: never push to main. A refspec such as lane-x:main lands on main from "
        "any"
        "source, and --all, --branches and --mirror push every branch, which a prefix rule cannot "
        "tell apart: every explicit push to origin and every branch-set push is forbidden. Run "
        "plain"
        "`git push`, which updates your branch's own upstream, or open the PR with `just pr`."
    ),
    "worktree": (
        "AGENTS.md Start: don't git worktree add by hand. Orca creates and removes each task's "
        "worktree."
    ),
    "env": (
        "AGENTS.md Hard lines: never print an environment variable's value. With no command, env "
        "prints them all, and a prefix rule cannot tell that from `env NAME=value command`: write "
        "`NAME=value command` instead."
    ),
    "wrapper": (
        "AGENTS.md: never run wsl.exe and never print an environment variable's value, behind a "
        "wrapper too."
    ),
    "git-wrapper": (
        "AGENTS.md Landing: never push to main, and don't git worktree add by hand, behind a "
        "wrapper"
        "too. Push your branch with plain `git push`, or open the PR with `just pr`; Orca makes "
        "each"
        "worktree."
    ),
}


def codex_text() -> str:
    header = (KIT / "rules-header.txt").read_text()
    out = [header]
    seen = set()
    for rule in codex_rules():
        pattern = json.dumps(rule["pattern"], ensure_ascii=False)
        if pattern in seen:
            continue
        seen.add(pattern)
        match, not_match = codex_examples(rule)
        body = [
            "prefix_rule(",
            f"    pattern = {pattern},",
            '    decision = "forbidden",',
        ]
        if rule["caseless"]:
            body.append("    canonical_matching = True,")
        body += [
            f"    justification = {json.dumps(JUSTIFICATION[rule['line']], ensure_ascii=False)},",
            f"    match = {json.dumps(match, ensure_ascii=False)},",
            f"    not_match = {json.dumps(not_match, ensure_ascii=False)},",
            ")",
            "",
        ]
        out.append("\n".join(body))
    return "\n".join(out)


SENTINEL = "sextant-no-such-program"


def codex_examples(rule: dict) -> tuple[list[str], list[str]]:
    """One matching and one non-matching invocation, which Codex checks when it loads the file.
    The non-matching one replaces the program, the only token a longer command cannot restore."""
    example = [token[0] if isinstance(token, list) else token for token in rule["pattern"]]
    return [" ".join(example)], [" ".join([SENTINEL, *example[1:]])]


def antigravity_rules() -> list[str]:
    """Per-token expressions: one token per word, an option slot an explicit `\\S+`, no spaces
    inside a token and no trailing wildcard, since a prefix match needs none."""
    wrap = "(" + "|".join(sorted(WRAPPERS)) + ")"
    rules: list[str] = []

    def case(word: str) -> str:
        return "".join(f"[{c.lower()}{c.upper()}]" if c.isalpha() else re.escape(c) for c in word)

    def slot(n: int) -> list[str]:
        return ["\\S+"] * n

    for target in MATRIX["targets"]:
        for program in target["programs"]:
            spelled = case(program) if target.get("cases") else re.escape(program)
            head = f"(\\S*/)?{spelled}"
            for argument in target["arguments"]:
                rest = target.get("subcommand", []) + argument
                if target.get("destination_tail"):
                    tail = argument[0]
                    destination = (
                        "\\+?(\\S*:)?(refs/heads/)?main"
                        if not tail.startswith("+")
                        else "\\+(\\S*:)?(refs/heads/)?main"
                    )
                    for slots in range(1, SLOTS + 2):
                        tokens = [head, "push", *slot(slots), destination]
                        rules.append("command(regex:" + " ".join(tokens) + ")")
                    continue
                if target["key"] == "push-branch-set":
                    flags = "(--all|--branches|--mirror)"
                    for slots in range(SLOTS + 1):
                        rules.append(
                            "command(regex:" + " ".join([head, "push", *slot(slots), flags]) + ")"
                        )
                    continue
                if target.get("shell_builtin"):
                    for slots in range(SLOTS + 1):
                        tokens = [re.escape(program), *slot(slots), re.escape(argument[-1])]
                        rules.append("command(regex:" + " ".join(tokens) + ")")
                    continue
                tokens = [head, *[re.escape(word) for word in rest]]
                rules.append("command(regex:" + " ".join(tokens) + ")")
    programs = "(\\S*/)?([wW][sS][lL]\\.[eE][xX][eE]|printenv|env)"
    # `command` is not one of Antigravity's transparent wrappers, so it needs its own rules; its
    # slot is restricted to the options that still run a program, since `command -v <name>` only
    # looks one up (code.claude.com/docs/en/permissions.md, read 2026-11-08).
    rules.append(f"command(regex:(\\S*/)?command {programs})")
    rules.append(f"command(regex:(\\S*/)?command (-p|--) {programs})")
    rules.append("command(regex:(\\S*/)?command (\\S*/)?git (push|worktree))")
    rules.append("command(regex:(\\S*/)?command (-p|--) (\\S*/)?git (push|worktree))")
    wrap = "(" + "|".join(name for name in sorted(WRAPPERS) if name != "command") + ")"
    wrapped = f"(\\S*/)?{wrap}"
    # A slot is only generated where a wrapper's own grammar can fill it: two option words, a
    # value, and timeout's duration, which is what the enumeration walks.
    for slots in range(SLOTS + 1):
        rules.append("command(regex:" + " ".join([wrapped, *slot(slots), programs]) + ")")
        # git behind a wrapper, with git's own option words before the subcommand. Two wrapper
        # slots, the deepest the enumeration walks, so no generated rule is dead.
        for inner in range(SLOTS + 1) if slots <= 2 else []:
            rules.append(
                "command(regex:"
                + " ".join([wrapped, *slot(slots), "(\\S*/)?git", *slot(inner), "(push|worktree)"])
                + ")"
            )
    # git's own option words before the subcommand.
    for slots in range(1, SLOTS + 1):
        rules.append(
            "command(regex:" + " ".join(["(\\S*/)?git", *slot(slots), "(push|worktree)"]) + ")"
        )
    posix = "(" + "|".join(MATRIX["shells"]["posix"]) + ")"
    script = "['\"]?(env|printenv|[wW][sS][lL]\\.[eE][xX][eE])['\"]?"
    # Bash 6.1's invocation grammar puts options before -c (read 2026-11-08, URL above).
    for slots in range(SLOTS + 1):
        for before in (True, False) if slots else (True,):
            middle = [*slot(slots), "-\\S*c\\S*"] if before else ["-\\S*c\\S*", *slot(slots)]
            rules.append("command(regex:" + " ".join([f"(\\S*/)?{posix}", *middle, script]) + ")")
    windows = "(" + "|".join(case(name) for name in ("cmd", "powershell", "pwsh")) + ")"
    for flag in ("(/[cCkK])", "(-[cC]\\S*)"):
        rules.append(
            "command(regex:"
            + " ".join(
                [
                    f"(\\S*/)?{windows}([.][eE][xX][eE])?",
                    flag,
                    "['\"]?([wW][sS][lL]([.][eE][xX][eE])?|[sS][eE][tT]|[gG][cC][iI]|[gG]et-[cC]hild[iI]tem)['\"]?",
                ]
            )
            + ")"
        )
    # A line Antigravity cannot prefix-match (a substitution or descriptor redirection) is matched
    # across the whole raw line, where one expression with \s is still a single token.
    for whole in (
        "(\\S*/)?[wW][sS][lL]\\.[eE][xX][eE]\\s.*",
        "(\\S*/)?(printenv|env)\\s.*",
        "(\\S*/)?git\\s+push\\s.*(main|--all|--branches|--mirror).*",
        "(\\S*/)?git\\s+worktree\\s+add\\s.*",
    ):
        rules.append(f"command(regex:{whole})")
    rules.append("write_file(/mnt/wsl)")
    return list(dict.fromkeys(rules))


def write(path: Path, text: str, check: bool) -> bool:
    if check:
        return path.read_text() == text
    path.write_text(text)
    return True


def main() -> int:
    check = "--check" in sys.argv
    settings_path = ROOT / ".claude" / "settings.json"
    settings = settings_path.read_text()
    deny = claude_rules() + EDIT
    block = '    "deny": [\n' + ",\n".join("      " + json.dumps(rule) for rule in deny) + "\n    ]"
    start = settings.index('    "deny": [')
    end = settings.index("    ]", start) + len("    ]")
    settings_text = settings[:start] + block + settings[end:]

    guard_path = ROOT / "config" / "dsh" / "hard-lines" / "hard-lines.mjs"
    guard = guard_path.read_text()
    bash = [rule for rule in deny if rule.startswith("Bash(")]
    assert all("'" not in rule for rule in bash), "a single quote would break the array"
    body = "\n".join(f"  '{rule}'," for rule in bash)
    gstart = guard.index("export const rules = [")
    gend = guard.index("\n]\n", gstart) + len("\n]\n")
    guard_text = guard[:gstart] + "export const rules = [\n" + body + "\n]\n" + guard[gend:]

    agy_text = json.dumps({"permissions": {"deny": antigravity_rules()}}, indent=2) + "\n"
    ok = [
        write(settings_path, settings_text, check),
        write(guard_path, guard_text, check),
        write(KIT / "antigravity.json", agy_text, check),
        write(ROOT / ".codex" / "rules" / "default.rules", codex_text(), check),
    ]
    if check:
        names = [".claude/settings.json", "hard-lines.mjs", "antigravity.json", "default.rules"]
        stale = [name for name, good in zip(names, ok, strict=True) if not good]
        if stale:
            print("stale, run generate.py:", ", ".join(stale), file=sys.stderr)
            return 1
        print("every rule file matches the matrix")
        return 0
    print(
        f"{len(bash)} Bash rules, {len(EDIT)} Edit, {len(antigravity_rules())} Antigravity, "
        f"{codex_text().count('prefix_rule(')} Codex"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
