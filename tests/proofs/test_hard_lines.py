"""AGENTS.md's hard-line commands, refused natively by each runtime's own engine.

One probe table, deploy/wsl/hard-lines/probes.json, drives every check:
- Claude Code: `.claude/settings.json` `permissions.deny`, proven by its own engine in a recorded
  bypass-mode session (claude-receipt.json).
- Codex: `.codex/rules/default.rules`, proven by `codex execpolicy check`, its own evaluator.
- dsh: `config/dsh/hard-lines/`, a `ctx.tools.guard` on the same rules, plus AGENTS.md's /mnt/wsl
  write line for every file tool and shell write, proven against the ToolGuard contract and its
  profiles' trees.
- Antigravity: `antigravity.json`, checked against its published settings schema and its
  documented matching. Its engine has no offline check, so its session receipt is the lead's step
  after install.
"""

import ast
import base64
import hashlib
import json
import os
import re
import runpy
import shlex
import shutil
import stat
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).parents[2]
KIT = ROOT / "deploy" / "wsl" / "hard-lines"
PROBES = json.loads((KIT / "probes.json").read_text())
REFUSED = [probe for line in PROBES["hard_lines"] for probe in line["refused"]]
LANE = PROBES["lane_commands"]
# A prefix rule cannot see where a refspec lands, so Codex forbids every explicit push to origin.
CODEX_FORBIDS = PROBES["codex_forbids"]
CLAUDE = json.loads((ROOT / ".claude" / "settings.json").read_text())
DENY = CLAUDE["permissions"]["deny"]
RULES = ROOT / ".codex" / "rules" / "default.rules"
GUARD = ROOT / "config" / "dsh" / "hard-lines"
# Antigravity's settings schema, $defs.permissionRule.pattern
# (antigravity.google/schemas/v1/settings.json, read 2026-11-08). Its docs: "The CLI ignores rules
# it can't parse".
AGY_RULE = re.compile(
    r"^(command|read_file|write_file|read_url|execute_url|mcp|unsandboxed)\(.*\)$"
)


def test_each_probed_line_is_quoted_from_agents_md() -> None:
    agents = (ROOT / "AGENTS.md").read_text()
    assert len(PROBES["hard_lines"]) == 5
    assert all(line["line"] in agents for line in PROBES["hard_lines"])
    # Each refused form names its bypass class, so each class has its own witnesses.
    # Interpreter one-liners are a residual by design, not a class with rules: our own scripts
    # run `python3 -I -c` everywhere, so a block would break the harness (the lead, 08:51 EST).
    assert {probe["class"] for probe in REFUSED} >= {
        "plain",
        "path",
        "case",
        "wrapper",
        "shell",
        "branch-set",
        "redirection",
        "compound",
        "write",
    }


# Claude's Edit rules guard its file tools and the target of a Bash redirection or tee, with
# gitignore patterns from the filesystem root and `**` across directories
# (code.claude.com/docs/en/permissions.md, read 2026-11-08, "Read and Edit", "Redirections" and
# "How path patterns match"). The recorded receipt shows one `**` rule reaching each write probe,
# where a rule per name under /mnt/wsl reached none.
EDIT = ["Edit(//mnt/wsl/**)"]


def test_claude_denies_exactly_the_rules_the_probes_exercise() -> None:
    bash = [rule for rule in DENY if rule.startswith("Bash(")]
    # The list is generated from the matrix, so a probe names one of its rules rather than the
    # other way round; test_the_generated_rule_files_match_the_matrix holds the list itself.
    named = {probe["claude"] for probe in REFUSED if (probe["claude"] or "").startswith("Bash(")}
    assert named and named <= set(bash), sorted(named - set(bash))
    assert [rule for rule in DENY if not rule.startswith("Bash(")] == EDIT
    assert {probe["claude"] for probe in REFUSED if probe["class"] == "write"} == set(EDIT)
    # Deferred until coordination moves to Orca messages: "hold" would hold each lane's message.
    assert "crossSessionInbound" not in CLAUDE
    # ADR-0022: Claude auto memory stays a separate native facility (reconciliation D14).
    assert "autoMemoryEnabled" not in CLAUDE


def test_claudes_own_engine_refused_each_probe_and_ran_each_lane_command() -> None:
    receipt = json.loads((KIT / "claude-receipt.json").read_text())
    digest = hashlib.sha256(json.dumps(DENY).encode()).hexdigest()
    assert receipt["deny_sha256"] == digest, (
        "rules changed: python3 deploy/wsl/hard-lines/claude-receipt.py"
    )
    assert receipt["permission_mode"] == "bypassPermissions"
    assert receipt["model"] == CLAUDE["model"]
    # ADR-0030's 2026-11-09 second amendment: the project's top-level effortLevel is the pin.
    assert receipt["effort"] == CLAUDE["effortLevel"]
    assert receipt["exit_code"] == 0
    assert receipt["extra_calls"] == []
    outcome = {row["command"]: row["outcome"] for row in receipt["probes"]}
    for probe in REFUSED:
        want = "denied" if probe["claude"] else "ran"
        if probe.get("execute") is False:
            # Every wsl form is matcher-only under the Codex handover, including plain forms
            # that the earlier 09:47 ruling would have permitted against stubs.
            matched = "matcher-denied" if probe["claude"] else "matcher-allowed"
            assert outcome[probe["command"]] == matched, probe
            continue
        assert outcome[probe["command"]] == want, probe
    assert all(outcome[command] == "ran" for command in LANE)
    assert receipt["canary_seen"] is False, receipt.get("canary_commands")
    # What stood in front of the real binary, measured in the receipt's own sandbox.
    sandbox = receipt["sandbox_facts"]
    assert sandbox["path_has_windows_entry"] is False
    assert sandbox["resolved_is_our_stub"] is True
    assert sandbox["cwd_has_destructive_binary"] is False
    assert sandbox["git_resolved_is_our_stub"] is True
    assert sandbox["cwd_has_git_binary"] is False
    assert sandbox["append_windows_path"] is True
    assert receipt["matcher_only"], "a destructive probe must stay matcher-only"
    # Each row says where its verdict came from, and a matcher-only row is never engine-verified
    # coverage (the lead, 2026-11-08 09:47 EST).
    for row in receipt["probes"]:
        source = row["verdict_source"]
        assert source.startswith("engine: " if row["executed"] else "matcher-only: "), row
    executed = [row["command"] for row in receipt["probes"] if row["executed"]]
    assert not any(re.search(r"\bwsl(?:\.exe)?(?=\s|['\"]|$)", c, re.I) for c in executed)
    harness = runpy.run_path(str(KIT / "claude-receipt.py"))
    assert all(
        not harness["DESTRUCTIVE"].search(c) or harness["PLAIN"].fullmatch(c) for c in executed
    )


def test_receipt_refuses_every_wsl_form_before_opening_a_session(tmp_path: Path) -> None:
    harness = runpy.run_path(str(KIT / "claude-receipt.py"))
    for probe in PROBES["hard_lines"][0]["refused"]:
        assert probe["execute"] is False
        with pytest.raises(SystemExit, match="refusing to run"):
            harness["refuse_unsafe"]([probe["command"]], tmp_path / "stubs", tmp_path)


def test_receipt_requires_plain_text_and_a_git_stub_for_destructive_forms(tmp_path: Path) -> None:
    harness = runpy.run_path(str(KIT / "claude-receipt.py"))
    stubs = tmp_path / "stubs"
    stubs.mkdir()
    refuse = harness["refuse_unsafe"]
    with pytest.raises(SystemExit, match="git must be the proven stub"):
        refuse(["git push origin main"], stubs, tmp_path)
    (stubs / "git").write_text(harness["STUB"].format(name="git"))
    refuse(["git push origin main"], stubs, tmp_path)
    for command in (
        "/usr/bin/git push origin main",
        "bash -c 'git push origin main'",
        "git worktree add ../probe",
    ):
        with pytest.raises(SystemExit, match="refusing to run"):
            refuse([command], stubs, tmp_path)
    (tmp_path / "git").touch()
    with pytest.raises(SystemExit, match="cwd contains a git binary"):
        refuse(["git push origin main"], stubs, tmp_path)


def _codex_rules() -> list[dict]:
    rules = []
    for node in ast.parse(RULES.read_text()).body:
        assert isinstance(node, ast.Expr) and isinstance(node.value, ast.Call)
        assert isinstance(node.value.func, ast.Name) and node.value.func.id == "prefix_rule"
        rules.append({kw.arg: ast.literal_eval(kw.value) for kw in node.value.keywords})
    return rules


def test_codex_rules_forbid_and_explain_each_hard_line() -> None:
    rules = _codex_rules()
    assert len(rules) > 100, len(rules)
    for rule in rules:
        assert rule["decision"] == "forbidden" and rule["match"] and rule["not_match"]
        assert rule["justification"].startswith("AGENTS.md")
    programs = set()
    for rule in rules:
        first = rule["pattern"][0]
        programs |= set(first) if isinstance(first, list) else {first}
    # Every program spelling the matrix generates: each target's programs in each path form and
    # case, the wrappers, and the shells whose script is one word.
    matrix = json.loads((KIT / "matrix.json").read_text())
    expected = set()
    for target in matrix["targets"]:
        if target.get("shell_builtin"):
            continue
        for program in target["programs"]:
            expected |= {f"{path}{program}" for path in matrix["paths"] if path != "*/"}
            expected |= {f"{path}{program}" for path in target.get("windows_paths", [])}
        expected |= set(target.get("cases", [])[1:])
    expected |= {
        f"{path}{wrapper['name']}"
        for wrapper in matrix["wrappers"]
        for path in ([""] if wrapper.get("shell_builtin") else matrix["wrapper_paths"])
    }
    expected |= set(matrix["shells"]["posix"])
    expected |= {"cmd", "cmd.exe", "powershell", "powershell.exe", "pwsh", "pwsh.exe"}
    assert programs == expected, sorted(programs ^ expected)
    # No rule names main: a refspec lands there from any source and a branch-set flag needs no
    # destination, which a prefix rule cannot tell apart, so the push rules forbid the whole
    # explicit push to origin and every branch-set push.
    pushes = [rule for rule in rules if "never push to main" in rule["justification"].lower()]
    assert pushes and all("git push" in rule["justification"] for rule in pushes)
    assert not any("main" in json.dumps(rule["pattern"]) and rule not in pushes for rule in rules)


@pytest.mark.local
def test_codex_forbids_each_hard_line_and_runs_each_lane_command() -> None:
    codex = shutil.which("codex")
    assert codex, "codex is not on PATH"
    pin = json.loads((ROOT / ".devcontainer/agents/package.json").read_text())["dependencies"]
    version = subprocess.run([codex, "--version"], capture_output=True, text=True, check=True)
    assert pin["@openai/codex"] in version.stdout

    def decision(*command: str) -> str | None:
        # Loading the file also checks each rule's own match and not_match examples.
        done = subprocess.run(
            [
                codex,
                "execpolicy",
                "check",
                "--rules",
                str(RULES),
                "--resolve-host-executables",
                *command,
            ],
            capture_output=True,
            text=True,
            check=True,
        )
        return json.loads(done.stdout).get("decision")

    # The CLI checks a command's words. A session first splits a plain `bash -lc` script into its
    # commands (codex-rs/shell-command/src/bash.rs:29-98): shell syntax is the session's to check.
    for probe in REFUSED:
        if probe["codex"] is None:
            # Shell syntax: only a Codex session's own bash -lc split sees inside it.
            assert re.search(r"&&|\||['\"]|\$\(|<\(|#|>", probe["command"]), probe
            continue
        expected = "forbidden" if probe["codex"] else None
        assert decision(*shlex.split(probe["command"])) == expected, probe
    assert set(CODEX_FORBIDS) < set(LANE)
    for command in LANE:
        expected = "forbidden" if command in CODEX_FORBIDS else None
        assert decision(*command.split()) == expected, command
    for command in ("bash script.sh", "bash -x script.sh"):
        assert decision(*shlex.split(command)) is None, command
    # Wrapped and cased forms nothing runs here.
    assert decision("sudo", "/mnt/c/Windows/System32/WSL.EXE", "--shutdown") == "forbidden"
    # Nothing runs here, so the real path and its case-insensitive drive's spelling can be checked.
    assert decision("/mnt/c/Windows/System32/wsl.exe", "--shutdown") == "forbidden"
    assert decision("/mnt/c/Windows/System32/WSL.EXE", "--shutdown") == "forbidden"


AGY_DENY = json.loads((KIT / "antigravity.json").read_text())["permissions"]["deny"]
AGY_COMMANDS = [rule for rule in AGY_DENY if rule.startswith("command(")]
# Antigravity's documented transparent wrappers, "whose inner command is evaluated on its own"
# (antigravity.google/docs/permissions.md, read 2026-11-08).
AGY_WRAPPERS = {"timeout", "nohup", "nice", "env"}
# The same page: a substitution, brace expansion, non-literal command name or file descriptor
# redirection "disables prefix matching for the entire command line", and then only a rule that
# matches the full line, a regex: rule across the whole raw line, applies.
AGY_OPAQUE = re.compile(r"\$\(|`|<\(|>\(|\{[^}]*,[^}]*\}|\d*[<>]&|^\s*\$")


def _agy_rule_matches(rule: str, words: list[str]) -> bool:
    # "Matches by exact word or token prefix literally by default"; with `regex:`, "each
    # whitespace-separated token is evaluated as an anchored regular expression ^(?:pattern)$".
    target = rule[len("command(") : -1]
    regex = target.startswith("regex:")
    tokens = target.removeprefix("regex:").split()
    if len(words) < len(tokens):
        return False
    if regex:
        return all(re.fullmatch(f"(?:{t})", w) for t, w in zip(tokens, words, strict=False))
    return words[: len(tokens)] == tokens


def _agy_inner(words: list[str]) -> list[str]:
    """A transparent wrapper's inner command, or the words themselves when it runs none."""
    head, rest = words[0], words[1:]
    if head not in AGY_WRAPPERS:
        return words
    if head == "timeout":
        while rest and rest[0].startswith("-"):
            rest = rest[2:] if rest[0] in ("-s", "-k") else rest[1:]
        rest = rest[1:]
    elif head == "nice" and rest[:1] == ["-n"]:
        rest = rest[2:]
    elif head == "nice" and rest and re.match(r"^-n?-?\d+$|^--adjustment=", rest[0]):
        rest = rest[1:]
    elif head == "env":
        while rest and (rest[0].startswith("-") or "=" in rest[0]):
            rest = rest[2:] if rest[0] in ("-u", "-C", "-S") else rest[1:]
    return _agy_inner(rest) if rest else words


def _agy_first_rule(command: str) -> str | None:
    """The first deny rule Antigravity's documented matching applies: chains and pipelines split,
    simple file redirects and comments dropped, then each command matched on its own; or, for a
    line it cannot prefix-match, the first rule matching the whole line."""
    if AGY_OPAQUE.search(command):
        line = command.strip()
        for rule in AGY_COMMANDS:
            target = rule[len("command(") : -1]
            if target.startswith("regex:") and re.fullmatch(f"(?:{target[6:]})", line):
                return rule
            if target == line:
                return rule
        return None
    lexer = shlex.shlex(command, posix=True, punctuation_chars=True)
    lexer.whitespace_split = True  # words split only at blanks and shell operators
    commands, words, tokens = [], [], list(lexer)
    for i, token in enumerate(tokens):
        if token in ("&&", "||", ";", "|", "&"):
            commands.append(words)
            words = []
        elif token.startswith((">", "<")) or (
            token.isdigit() and i + 1 < len(tokens) and tokens[i + 1].startswith((">", "<"))
        ):
            continue
        elif i and tokens[i - 1].startswith((">", "<")):
            continue
        else:
            words.append(token)
    commands.append(words)
    for words in filter(None, commands):
        inner = _agy_inner(words)
        hit = next((rule for rule in AGY_COMMANDS if _agy_rule_matches(rule, inner)), None)
        if hit:
            return hit
    return None


def test_antigravity_rules_parse_and_cover_each_hard_line() -> None:
    agy = json.loads((KIT / "antigravity.json").read_text())
    assert set(agy) == {"permissions"} and set(agy["permissions"]) == {"deny"}
    for rule in AGY_DENY:
        assert AGY_RULE.match(rule), rule
        target = rule[len("command(") : -1]
        if rule.startswith("command(regex:"):
            # Each whitespace-separated token is one anchored regular expression, and the whole is
            # one for a line it cannot prefix-match; one that fails to compile would make the CLI
            # drop the whole rule without a word.
            for token in [*target[len("regex:") :].split(), target[len("regex:") :]]:
                re.compile(token)
    # write_file(/path) covers a path and everything under it, with no exclusion, and deny wins
    # over allow: so the file tool's write line denies all of /mnt/wsl, /mnt/wsl/sextant included.
    files = [rule for rule in AGY_DENY if not rule.startswith("command(")]
    assert files == ["write_file(/mnt/wsl)"]
    # The probes name rules from the generated set, and no generated rule is dead: every one is
    # matched by some combination of the matrix's cross product.
    named = {p["antigravity"] for p in REFUSED if p["antigravity"]}
    assert named and named <= set(AGY_COMMANDS), sorted(named - set(AGY_COMMANDS))
    words = [command.split() for _, command in COMBINATIONS]
    lines = [command for _, command in COMBINATIONS]

    def exercised(rule: str) -> bool:
        if any(_agy_rule_matches(rule, w) for w in words):
            return True
        # A whole-line expression applies to a command Antigravity cannot prefix-match.
        target = rule[len("command(") : -1]
        if not target.startswith("regex:"):
            return False
        return any(re.fullmatch(f"(?:{target[6:]})", line) for line in lines)

    dead = [rule for rule in AGY_COMMANDS if rule not in named and not exercised(rule)]
    assert not dead, dead
    for probe in REFUSED:
        if probe["antigravity"]:
            assert _agy_first_rule(probe["command"]) == probe["antigravity"], probe
    assert all(_agy_first_rule(command) is None for command in LANE)


@pytest.mark.local
@pytest.mark.parametrize(
    "probe",
    [probe for probe in REFUSED if probe.get("shell_options_before_c")],
    ids=lambda probe: probe["command"],
)
def test_shell_options_before_c_have_explicit_verdicts(probe: dict) -> None:
    """Bash 6.1: `bash [options] -c string`, including -o, -O and long options.
    https://www.gnu.org/software/bash/manual/html_node/Invoking-Bash.html, read 2026-11-08.
    The CLI evaluates argv without running it; Antigravity is matcher-only. Git scripts remain
    explicit residuals for both prefix matchers, even when their shell options precede -c.
    """
    done = subprocess.run(
        ["codex", "execpolicy", "check", "--rules", str(RULES), *shlex.split(probe["command"])],
        capture_output=True,
        text=True,
        check=True,
    )
    assert json.loads(done.stdout).get("decision") == ("forbidden" if probe["codex"] else None), (
        probe
    )
    assert _agy_first_rule(probe["command"]) == probe["antigravity"], probe
    assert set(probe["verdict_sources"]) == {"codex", "antigravity"}


def test_bash_option_residuals_remain_explicit_p1s() -> None:
    """A finite literal matcher cannot claim arbitrary FILE values or unbounded clusters."""
    invocation = MATRIX["shells"]["bash_invocation"]
    assert invocation["residual_severity"].startswith("P1:")
    assert invocation["file_options"] == ["--rcfile", "--init-file"]
    assert invocation["file_literals"] == ["/dev/null"]
    assert {"posix", "pipefail"} <= set(invocation["set_names"])
    assert {"nullglob", "extglob", "array_expand_once"} <= set(invocation["shopt_names"])
    corrected = [probe for probe in REFUSED if probe.get("round5") == "corrected"]
    residuals = [probe for probe in REFUSED if probe.get("round5") == "residual"]
    assert len(corrected) == 20 and all(probe["codex"] for probe in corrected)
    assert len(residuals) == 12 and all(probe["codex"] is False for probe in residuals)
    assert all(
        probe["execute"] is False
        for probe in corrected + residuals
        if "wsl.exe" in probe["command"]
    )


def _guard(calls: list[dict]) -> dict:
    harness = """
import fs from 'node:fs';
const plugin = await import(process.argv[1]);
const guards = [];
plugin.apply({ tools: { guard: (guard) => { guards.push(guard); return () => {}; } } });
const calls = JSON.parse(fs.readFileSync(0, 'utf8'));
const answer = (call) => guards.map((guard) => guard(Object.freeze(call))).find(Boolean) ?? null;
const { name, inject, rules } = plugin;
const reasons = calls.map(answer);
console.log(JSON.stringify({ name, inject, rules, guards: guards.length, reasons }));
"""
    done = subprocess.run(
        ["node", "--input-type=module", "-e", harness, str(GUARD / "hard-lines.mjs")],
        input=json.dumps(calls),
        capture_output=True,
        text=True,
        check=True,
    )
    return json.loads(done.stdout)


def test_dsh_guard_applies_the_claude_rules_to_each_command_tool() -> None:
    def calls(command: str) -> list[dict]:
        return [
            {"name": "bash", "arguments": {"command": command}},
            {"name": "pwsh", "arguments": {"command": command}},
            {"name": "terminal_send", "arguments": {"text": command, "submit": True}},
        ]

    commands = [probe["command"] for probe in REFUSED] + LANE
    result = _guard([call for command in commands for call in calls(command)])
    assert result["name"] == "sextant-hard-lines" and result["inject"] == ["tools"]
    assert result["guards"] == 1
    bash = [rule for rule in DENY if rule.startswith("Bash(")]
    assert result["rules"] == bash, "the guard carries .claude/settings.json's Bash rules verbatim"
    reasons = iter(result["reasons"])
    for command in commands:
        probe = next((p for p in REFUSED if p["command"] == command), None)
        for _ in range(3):  # bash, pwsh, terminal_send
            reason = next(reasons)
            if probe is None:
                assert reason is None, (command, reason)
                continue
            # Every probed form is refused; where the guard names Claude's own rule, the probe
            # records which, so a rule that stops matching is caught.
            assert probe["dsh"] and reason and "AGENTS.md" in reason, (command, reason)
            if probe.get("dsh_rule"):
                assert probe["dsh_rule"] in reason, (command, reason)


def test_dsh_guard_reads_each_tools_own_argument_and_leaves_other_tools_alone() -> None:
    result = _guard(
        [
            {"name": "bash", "arguments": {"command": "echo 'git push origin main'"}},
            {"name": "bash", "arguments": {"command": "bash -c 'git push origin main'"}},
            {"name": "bash", "arguments": {"command": "(cd /tmp; printenv)"}},
            {"name": "bash", "arguments": {"command": "echo $(printenv HOME)"}},
            {"name": "bash", "arguments": {"command": "for x in 1; do wsl.exe; done"}},
            {"name": "terminal_send", "arguments": {"text": "printenv\n"}},
            {"name": "read", "arguments": {"command": "printenv"}},
            {"name": "bash", "arguments": {}},
        ]
    )
    quoted, nested, subshell, substitution, loop, typed, other, empty = result["reasons"]
    assert quoted is None, "a quoted string is an argument, not a command"
    assert nested and "git push" in nested
    assert subshell and substitution and loop and typed
    assert other is None and empty is None


def _bash(*commands: str, tool: str = "bash") -> list[str | None]:
    field = "text" if tool == "terminal_send" else "command"
    return _guard([{"name": tool, "arguments": {field: command}} for command in commands])[
        "reasons"
    ]


def test_dsh_guard_drops_comments_and_redirections_and_reads_heredocs_as_bash_does() -> None:
    """Bash: a word beginning with # starts a comment; redirections may precede or appear anywhere
    in a command; a quoted here-document's lines are not expanded, an unquoted one's are
    (gnu.org/software/bash/manual/bash.html 3.1.3, 3.6 and 3.6.6, read 2026-11-08)."""
    refused = _bash(
        "env # inspect the environment",
        "env 2>/dev/null",
        "2>/dev/null printenv",
        "&>/dev/null env",
        "printenv>/tmp/out",
        "git push origin main>/dev/null",
        "git push origin main 2>&1 | tee log",
        "echo a#b; wsl.exe --shutdown",
        "cat <<EOF\n$(printenv HOME)\nEOF",
        "cat <<'EOF' > notes.md\nliteral\nEOF\nwsl.exe --version",
        "bash <<'EOF'\nwsl.exe --shutdown\nEOF",
        "cat <(printenv)",
        "echo $(printf '%s' \"$(printenv HOME)\")",
    )
    assert all(refused), refused
    allowed = _bash(
        "echo hi # ; wsl.exe --shutdown",
        "cat <<'EOF'\nprintenv\nwsl.exe --shutdown\nEOF",
        "cat <<-EOF > notes.md\n\tgit push origin main\n\tEOF",
        "grep -n 'env' AGENTS.md > /tmp/hits",
    )
    assert allowed == [None] * len(allowed), allowed


def test_dsh_guard_strips_each_wrapper_by_its_own_option_grammar() -> None:
    """sudo(8) (sudo.ws/docs/man/sudo.man), doas(1) (man.openbsd.org/doas), bash's exec builtin,
    xargs(1) (man7.org/linux/man-pages/man1/xargs.1.html) and GNU coreutils' nice, timeout and
    stdbuf (gnu.org/software/coreutils/manual), all read 2026-11-08: each runs its command
    argument after its own options, some of which take a value."""
    refused = _bash(
        "sudo wsl.exe --shutdown",
        "sudo -n -u root wsl.exe --shutdown",
        "sudo --user=root -- wsl.exe",
        "sudo -E FOO=1 printenv",
        "doas -u root wsl.exe",
        "exec -a probe wsl.exe",
        "nohup sudo timeout 5 wsl.exe --list",
        "sudo git push origin main",
        "exec git worktree add ../x",
        "sudo bash -c 'wsl.exe --shutdown'",
        "nice -n5 wsl.exe --shutdown",
        "nice --adjustment 5 wsl.exe --shutdown",
        "timeout --signal KILL 5 wsl.exe --list",
        "timeout -k 1 5 printenv",
        "stdbuf --output L printenv",
        "xargs -n 1 -P 2 wsl.exe",
        "xargs --max-args=1 env",
        "setsid -f wsl.exe --shutdown",
    )
    assert all(refused), refused
    sudo_push, worktree = refused[7], refused[8]
    assert sudo_push and "git push" in sudo_push
    assert worktree and "git worktree add" in worktree
    allowed = _bash("command -v wsl.exe", "sudo -l", "sudo -n true", "exec 3>&1", "nice -n 5 true")
    assert allowed == [None] * len(allowed), allowed


def test_dsh_guard_matches_wsl_exe_in_any_case() -> None:
    """A Windows path resolves in any case on its drive, so dsh, unlike Claude Code's exact rules,
    reads wsl.exe caselessly."""
    refused = _bash("WSL.EXE --shutdown", "/mnt/c/Windows/System32/Wsl.Exe -l", "sudo WSL.exe")
    assert all(reason and "Never run `wsl.exe`" in reason for reason in refused), refused


def test_dsh_guard_reads_each_shells_script_by_its_own_grammar() -> None:
    """bash reads -c's script from "the first non-option argument" (bash manual 6.1), so -c may
    sit anywhere in a cluster and options with values may come first; pwsh takes -Command | -c
    and -EncodedCommand | -e | -ec, base64 of UTF-16LE text (learn.microsoft.com/powershell/module/
    microsoft.powershell.core/about/about_pwsh); cmd takes /c and /k (learn.microsoft.com/
    windows-server/administration/windows-commands/cmd), where bare set prints every variable; all
    read 2026-11-08."""
    encoded = base64.b64encode("Get-ChildItem Env:".encode("utf-16-le")).decode()
    refused = _bash(
        "bash -cl 'env'",
        "bash -ce 'printenv'",
        "bash -ic 'wsl.exe --version'",
        "bash -o pipefail -c 'env'",
        "bash -c -o pipefail 'git -C . push origin main'",
        "bash --login -c 'printenv HOME'",
        "bash -c -x 'env'",
        "bash -x -c 'git push origin main'",
        "/bin/sh -ec 'wsl.exe'",
        "zsh -fc 'printenv'",
        f"pwsh -EncodedCommand {encoded}",
        "pwsh -NoProfile -c 'wsl.exe --version'",
        'powershell.exe -Command "wsl --shutdown"',
        "cmd.exe /c wsl --shutdown",
        "/mnt/c/Windows/System32/cmd.exe /C WSL -l",
        "cmd.exe /c set",
    )
    assert all(refused), refused
    allowed = _bash(
        "bash -c 'git status'",
        "bash -n deploy/wsl/ao.sh",
        "sh -ec 'echo ok'",
        "pwsh -c 'Get-ChildItem ./src'",
        "cmd.exe /c dir",
    )
    assert allowed == [None] * len(allowed), allowed
    # A glob and a prefix rule cannot require that `set` have no argument, so an assignment, which
    # only sets a variable, is refused too: the over-block the body names.
    assert _bash("cmd.exe /c set FOO=bar") != [None]


def test_dsh_guard_leaves_interpreter_one_liners_to_the_other_guards() -> None:
    """The harness runs `python3 -I -c` everywhere, so no rule reads an interpreter's program text
    (the lead, 2026-11-08). The PR's "Residuals by design" names what holds instead: main's
    ruleset for a push, the devc sandbox for a write, and scripts/with-keys.sh for a key."""
    allowed = _bash(
        "python3 -I -c 'print(1)'",
        "python3 -c 'import os; print(len(os.environ))'",
        "node -e 'console.log(1)'",
        "node --eval='console.log(2)'",
        "perl -e 'print 1'",
        "python3 -m pytest -q",
    )
    assert allowed == [None] * len(allowed), allowed
    # The interpreter itself is still a command: a hard-line word in its own argv is refused.
    assert _bash("python3 -c 'print(1)' && wsl.exe --shutdown") != [None]


def test_dsh_guard_judges_every_directory_a_call_runs_in() -> None:
    """bash and pwsh take `workdir`, terminal_open `cwd`, subagent and subagent_fork a child's
    `cwd`, and working_directory `cd` (deepseek-harness@dsh-v0.2.2-rc.1 docs/tool-catalog.md).
    From any of them under /mnt, a relative path would reach /mnt/wsl without naming it."""

    def call(name: str, **arguments: str) -> dict:
        return {"name": name, "arguments": arguments}

    refused = [
        call("bash", command="touch state", workdir="/mnt/wsl/other"),
        call("bash", command="ls", workdir="/mnt"),
        call("bash", command="cp x y", workdir="/mnt/c/Users"),
        call("bash", command="true", workdir="../../../mnt/wsl"),
        call("pwsh", command="New-Item state", workdir="/mnt/wsl/other"),
        call("terminal_open", type="bash", cwd="/mnt/wsl/other"),
        call("subagent", prompt="write the state", cwd="/mnt/wsl/other"),
        call("subagent_fork", prompt="write the state", cwd="/mnt/wsl"),
        call("working_directory", cd="/mnt/c"),
        call("bash", command="cd /mnt/c/x && cp ../wsl/other/f ."),
    ]
    allowed = [
        call("bash", command="ls", workdir="docs"),
        call("bash", command="ls", workdir="/home/sextant"),
        call("terminal_open", type="bash"),
        call("subagent", prompt="read the docs"),
        call("bash", command="cat /mnt/wsl/x /mnt/c/Users/x"),
    ]
    result = _guard(refused + allowed)["reasons"]
    head, tail = result[: len(refused)], result[len(refused) :]
    pairs = list(zip(refused, head, strict=True))
    assert all(reason and "/mnt" in reason for reason in head), pairs
    assert tail == [None] * len(allowed), list(zip(allowed, tail, strict=True))


def test_dsh_guard_keeps_every_write_path_out_of_other_distros_state() -> None:
    """AGENTS.md Start: never write under /mnt/wsl outside /mnt/wsl/sextant; reading is allowed.
    dsh's file tools take `file_path` (write, edit), `path` (str_replace_editor) and a patch
    (apply_patch), and resolve relative paths against the Session directory, which
    `working_directory` changes and a guard never sees (deepseek-harness@dsh-v0.2.2-rc.1
    docs/tool-catalog.md, packages/fs/tool-fs/README.md:28 and :263)."""

    def patch(*headers: str) -> dict:
        body = "\n".join(["*** Begin Patch", *headers, "+x", "*** End Patch"])
        return {"name": "apply_patch", "arguments": {"input": body}}

    def call(name: str, **arguments: str) -> dict:
        return {"name": name, "arguments": arguments}

    refused = [
        patch("*** Add File: /mnt/wsl/other-distro/state.json"),
        patch("*** Update File: /mnt/wsl/sextant/../shared/x"),
        patch("*** Update File: notes.md", "*** Move to: /mnt/wsl/x"),
        call("write", file_path="/mnt/wsl/other-distro/state.json", content="x"),
        call("write", file_path="../../../../../../mnt/wsl/other/state.json", content="x"),
        call("write", file_path="mnt/wsl/other/state.json", content="x"),
        call("edit", file_path="/mnt/wsl/x", old_string="a", new_string="b"),
        call("str_replace_editor", command="create", path="/mnt/wsl/x", file_text="x"),
        call("str_replace_editor", command="insert", path="/mnt/wsl/x", new_str="x"),
        call("working_directory", cd="/mnt/wsl/other"),
        call("working_directory", cd="/mnt"),
        call("working_directory", cd="/mnt/wsl/sextant"),
        call("working_directory", cd="../../../mnt"),
        call("create_worktree"),
        call("bash", command="echo x > /mnt/wsl/other/f"),
        call("bash", command="cp notes.md /mnt/wsl/other/"),
        call("bash", command="tee /mnt/wsl/x < notes.md"),
        call("bash", command="cd /mnt/wsl/other && touch f"),
        call("bash", command="find /mnt/wsl -name x -delete"),
        call("bash", command="printf x >> ../../../../mnt/wsl/other/f"),
        call("pwsh", command="Set-Content -Path /mnt/wsl/x -Value 1"),
    ]
    allowed = [
        patch("*** Add File: /mnt/wsl/sextant/handoff.md"),
        patch("*** Update File: docs/handbook/notes.md"),
        call("write", file_path="/mnt/wsl/sextant/handoff.md", content="x"),
        call("write", file_path="docs/notes.md", content="x"),
        call("edit", file_path="src/x.py", old_string="a", new_string="b"),
        call("str_replace_editor", command="view", path="/mnt/wsl/x"),
        call("read", file_path="/mnt/wsl/x"),
        call("working_directory", cd="docs"),
        call("working_directory"),
        call("bash", command="cat /mnt/wsl/x"),
        call("bash", command="ls -la /mnt/wsl"),
        call("bash", command="grep -r x /mnt/wsl > /tmp/hits"),
        call("bash", command="echo ok > /mnt/wsl/sextant/f"),
        call("bash", command="find /mnt/wsl -name x"),
    ]
    result = _guard(refused + allowed)["reasons"]
    head, tail = result[: len(refused)], result[len(refused) :]
    assert all(head), list(zip(refused, head, strict=True))
    assert tail == [None] * len(allowed), list(zip(allowed, tail, strict=True))
    # dsh's own worktree tool is the hand-made worktree Orca's lifecycle never sees.
    assert "git worktree add" in head.pop(refused.index(call("create_worktree")))
    assert all("/mnt/wsl" in reason for reason in head), head


def test_dsh_guard_refuses_powershells_environment_drive_on_pwsh() -> None:
    """PowerShell lists and reads variables through the Env: drive
    (learn.microsoft.com/powershell/module/microsoft.powershell.core/about/about_environment_provider,
    read 2026-11-08) and .NET's Environment.GetEnvironmentVariable(s)."""
    refused = _bash(
        "Get-ChildItem Env:",
        "gci env:",
        "Get-Item -Path Env:HOME",
        "dir 'Env:\\'",
        "(Get-ChildItem -Path Env:).Count",
        "[Environment]::GetEnvironmentVariables()",
        "[System.Environment]::GetEnvironmentVariable('HOME')",
        tool="pwsh",
    )
    assert all(reason and "environment variable" in reason for reason in refused), refused
    allowed = _bash("$env:FOO = 'x'", "Get-ChildItem ./src", "Get-Content notes.md", tool="pwsh")
    assert allowed == [None] * len(allowed), allowed
    # A bash word that only looks like the drive is a file name there.
    assert _bash("ls env:") == [None]


def test_dsh_guard_bundle_composes_its_one_patch() -> None:
    package = json.loads((GUARD / "package.json").read_text())
    assert package["engines"] == {"dsh": "0.2.2-rc.1"}
    assert package["dsh"] == {"bundle": {"patch": ["./hard-lines.cordis.yml"]}}
    patch = (GUARD / "hard-lines.cordis.yml").read_text()
    assert "id: sextant-hard-lines" in patch and "name: ./hard-lines.mjs" in patch


def _install(tmp: Path, home: Path) -> tuple[subprocess.CompletedProcess, list[str]]:
    fake = tmp / "dsh"
    fake.write_text('#!/usr/bin/env bash\nprintf "%s\\n" "$*" >> "$FAKE_LOG"\n')
    fake.chmod(0o755)
    env = {
        "HOME": str(home),
        "PATH": os.defpath,
        "DSH_BIN": str(fake),
        "FAKE_LOG": str(tmp / "dsh.log"),
    }
    run = subprocess.run(
        ["bash", str(KIT / "install.sh")], env=env, capture_output=True, text=True, cwd=tmp
    )
    log = tmp / "dsh.log"
    return run, log.read_text().splitlines() if log.exists() else []


def test_the_installer_writes_each_user_layer_and_keeps_what_is_there(tmp_path: Path) -> None:
    home = tmp_path / "home"
    settings = home / ".gemini" / "antigravity-cli" / "settings.json"
    settings.parent.mkdir(parents=True)
    kept = tmp_path / "worktree"
    kept.mkdir()
    file_entry = tmp_path / "notes.md"
    file_entry.write_text("x")
    gone = "/srv/another-checkout"
    owner = {
        "trustedWorkspaces": [str(kept), gone, str(file_entry)],
        "permissions": {"deny": ["command(sudo)"], "allow": ["command(ls)"]},
    }
    settings.write_text(json.dumps(owner))
    run, calls = _install(tmp_path, home)
    assert run.returncode == 0, run.stderr

    # Codex loads only regular *.rules files; Orca copies each into its own Codex homes at launch.
    copy = home / ".codex" / "rules" / "sextant-hard-lines.rules"
    assert stat.S_ISREG(copy.lstat().st_mode) and copy.read_bytes() == RULES.read_bytes()
    assert not (home / ".codex" / "rules" / "default.rules").exists(), (
        "default.rules holds Codex's approvals"
    )

    # The prune drops only the trusted path that no longer exists, prints it, and keeps every other
    # entry and key, so the doctor's antigravity.repository rule can pass on this file.
    assert f"removed Antigravity trusted workspace: {gone}" in run.stdout.splitlines()
    assert str(kept) not in run.stdout and str(file_entry) not in run.stdout
    merged = json.loads(settings.read_text())
    ours = json.loads((KIT / "antigravity.json").read_text())["permissions"]["deny"]
    assert merged["trustedWorkspaces"] == [str(kept), str(file_entry)]
    assert merged["permissions"]["allow"] == ["command(ls)"]
    assert merged["permissions"]["deny"] == ["command(sudo)", *ours]
    assert stat.S_IMODE(settings.stat().st_mode) == 0o600

    main = (
        subprocess.run(
            ["git", "-C", str(ROOT), "worktree", "list", "--porcelain"],
            capture_output=True,
            text=True,
        )
        .stdout.splitlines()[0]
        .removeprefix("worktree ")
    )
    assert calls == [
        f"plugin --profile {profile} add {main}/config/dsh/hard-lines"
        for profile in ("acp", "headless", "dsh-tui")
    ]

    before = (copy.read_bytes(), settings.read_bytes())
    again, _ = _install(tmp_path, home)
    assert again.returncode == 0 and (copy.read_bytes(), settings.read_bytes()) == before
    assert gone not in again.stdout, "a second run has nothing left to prune"


def test_the_installer_publishes_the_rules_into_the_lane_codex_home(tmp_path: Path) -> None:
    """Orca copies ~/.codex/rules into only the Codex homes it manages, and the lane Codex home
    is the launcher's own, from parity.json's spec. The installer publishes its copy there too."""
    home = tmp_path / "home"
    run, _ = _install(tmp_path, home)
    assert run.returncode == 0, run.stderr

    spec = json.loads((ROOT / "deploy/wsl/lane-runtimes/parity.json").read_text())
    lane = home / spec["runtimes"]["codex"]["home"]
    installed = lane / "rules" / "sextant-hard-lines.rules"
    assert installed.is_file(), "the lane Codex home must carry the hard-line rules"
    assert stat.S_ISREG(installed.lstat().st_mode)
    assert installed.read_bytes() == RULES.read_bytes()
    assert stat.S_IMODE(lane.stat().st_mode) == 0o700
    assert not (lane / "rules" / "default.rules").exists(), "default.rules holds Codex's approvals"

    before = (installed.read_bytes(), lane.stat().st_mode)
    again, _ = _install(tmp_path, home)
    assert again.returncode == 0
    assert (installed.read_bytes(), lane.stat().st_mode) == before


MATRIX = json.loads((KIT / "matrix.json").read_text())


def _combinations() -> list[tuple[str, str]]:
    """Every (class, command) the matrix's cross product spells: each target's programs in each
    path form and case, 0 to `option_slots` option words before each positional, and each wrapper
    past its own options. One list, walked by every engine's own evaluator."""
    out: list[tuple[str, str]] = []
    options = ["-f", "--no-verify", "-q"]
    for target in MATRIX["targets"]:
        head = target.get("subcommand", [])
        for program in target["programs"]:
            paths = (
                [""] if target.get("shell_builtin") else [p for p in MATRIX["paths"] if p != "*/"]
            )
            names = [f"{path}{program}" for path in paths]
            names += [f"{path}{program}" for path in target.get("windows_paths", [])]
            names += target.get("cases", [])[1:]
            for name in dict.fromkeys(names):
                for argument in target["arguments"]:
                    for slots in range(MATRIX["option_slots"] + 1):
                        middle = options[:slots]
                        tail = list(argument)
                        if target.get("destination_tail") and tail:
                            spelled = tail[0]
                            remote = target.get("remotes", ["origin"])[0]
                            tail = (
                                [remote, spelled]
                                if spelled[0].isalnum()
                                else [remote, f"HEAD{spelled}"]
                            )
                            if spelled.startswith("+"):
                                tail = [remote, spelled]
                        elif target.get("remotes") and tail:
                            tail = [target["remotes"][0], *tail]
                        words = [name, *head, *middle, *tail]
                        out.append((target["key"], " ".join(words)))
                        if target.get("shell_builtin") or slots:
                            continue
                        for wrapper in MATRIX["wrappers"]:
                            if wrapper["name"] == "env" and target["key"] == "env":
                                continue
                            prefix = [wrapper["name"]]
                            if wrapper.get("positional"):
                                prefix.append("5")
                            out.append((f"wrap-{wrapper['name']}", " ".join([*prefix, *words])))
                            # Each wrapper in its own path forms, which Google's #270 named; a
                            # shell builtin has none.
                            paths_for = (
                                [""] if wrapper.get("shell_builtin") else MATRIX["wrapper_paths"]
                            )
                            for at in paths_for:
                                out.append(
                                    (
                                        f"wrap-{wrapper['name']}",
                                        " ".join([f"{at}{wrapper['name']}", *prefix[1:], *words]),
                                    )
                                )
                            for flag in wrapper.get("flags", [])[:1]:
                                out.append(
                                    (
                                        f"wrap-{wrapper['name']}",
                                        " ".join(
                                            [
                                                wrapper["name"],
                                                flag,
                                                *(["5"] if wrapper.get("positional") else []),
                                                *words,
                                            ]
                                        ),
                                    )
                                )
                            for flag, allowed in (wrapper.get("values") or {}).items():
                                out.append(
                                    (
                                        f"wrap-{wrapper['name']}",
                                        " ".join([wrapper["name"], flag, allowed[0], *words]),
                                    )
                                )
                            # Deeper option slots, as many as the wrapper's own flags can fill
                            # and the generated rules cover.
                            own = wrapper.get("flags", [])
                            for count in range(2, min(2, len(own)) + 1):
                                out.append(
                                    (
                                        f"wrap-{wrapper['name']}",
                                        " ".join(
                                            [
                                                wrapper["name"],
                                                *own[:count],
                                                *(["5"] if wrapper.get("positional") else []),
                                                *words,
                                            ]
                                        ),
                                    )
                                )
    # git's own options before the subcommand (git-scm.com/docs/git), and a wrapper before those.
    forms = [["push", "origin", "main"], ["push", "--all"], ["worktree", "add", "../probe"]]
    flag, valued = MATRIX["git_options"]["flags"][0], MATRIX["git_options"]["valued"][0]
    for path in [p for p in MATRIX["paths"] if p != "*/"]:
        for form in forms:
            for options in ([flag], [valued, "."], [flag, valued, "."]):
                out.append(("git-options", " ".join([f"{path}git", *options, *form])))
                for wrapper in MATRIX["wrappers"][:4]:
                    for count in range(min(3, len(wrapper.get("flags", [])) + 1)):  # 0..2
                        out.append(
                            (
                                f"wrap-{wrapper['name']}",
                                " ".join(
                                    [
                                        wrapper["name"],
                                        *wrapper.get("flags", [])[:count],
                                        f"{path}git",
                                        *options,
                                        *form,
                                    ]
                                ),
                            )
                        )
    # A Windows shell's command, and a line Antigravity cannot prefix-match, which it checks whole.
    for shell in MATRIX["windows_shells"]["programs"]:
        cmd = shell.startswith("cmd")
        flag = "/c" if cmd else "-Command"
        # Each shell's own environment printer: `set` inside cmd, the Env: drive inside PowerShell.
        for inner in ("wsl",) + (("set",) if cmd else ("Get-ChildItem Env:", "gci env:")):
            out.append(("shell", f"{shell} {flag} {inner}"))
    # A substitution hides what it expands to, so a line whose own program carries the hard line is
    # still refused; a push whose destination is computed is a residual the body names.
    for whole in (
        "wsl.exe $(echo --shutdown)",
        "printenv $(echo HOME)",
        "git worktree add $(echo ../probe)",
        "env 2>&1",
    ):
        out.append(("opaque", whole))
    # A shell's -c script, where an option before it may take a value of its own (bash manual 6.1).
    for shell in MATRIX["shells"]["posix"]:
        for script in ("env", "printenv", "wsl.exe"):
            for extra in (
                [],
                ["-x"],
                ["-o", "pipefail"],
                ["-o", "pipefail", "-x"],
                ["-O", "extglob"],
                ["--noprofile"],
            ):
                out.append(("shell", " ".join([shell, "-c", *extra, script])))
                if extra:
                    out.append(("shell", " ".join([shell, *extra, "-c", script])))
    # Every documented terminal, not just the review's examples. These are matcher inputs,
    # never executed, and do not claim arbitrary clusters or FILE operands are expressible.
    invocation = MATRIX["shells"]["bash_invocation"]
    letters = sorted(
        set(
            invocation["set_letters"]
            + invocation["invocation_letters"]
            + invocation["synopsis_letters"]
        )
        - {"c"}
    )
    options = [[f"{sign}{c}"] for sign in ("-", "+") for c in letters]
    options += [[flag, name] for flag in ("-o", "+o") for name in invocation["set_names"]]
    options += [[flag, name] for flag in ("-O", "+O") for name in invocation["shopt_names"]]
    options += [
        [flag] for flag in invocation["long_options"] if flag not in invocation["file_options"]
    ]
    options += [
        [flag, file] for flag in invocation["file_options"] for file in invocation["file_literals"]
    ]
    clusters = sorted(set(invocation["c_cluster_literals"] + [f"-{c}c" for c in letters]))
    for script in ("env", "printenv", "wsl.exe"):
        out += [("shell", " ".join(["bash", *extra, "-c", script])) for extra in options]
        out += [("shell", " ".join(["bash", flag, script])) for flag in clusters]
    return out


COMBINATIONS = _combinations()


def test_every_directory_parameter_in_the_pinned_bundles_is_guarded() -> None:
    """The tool names and parameters come from the installed bundles' own schemas, not a list:
    the fork tool is named subagent_fork, and no tool is named subagent_oar (Google's #269)."""
    done = subprocess.run(
        ["python3", "-I", str(KIT / "tools.py")], capture_output=True, text=True, cwd=ROOT
    )
    assert done.returncode == 0, done.stdout + done.stderr
    report = json.loads(done.stdout)
    assert report["missing_from_guard"] == []
    assert "subagent_fork.cwd" in report["directories"]
    guard = (GUARD / "hard-lines.mjs").read_text()
    assert "subagent_fork: 'cwd'" in guard


def _justfile_commands() -> list[str]:
    """Every command line the justfile's recipes run, with just's own placeholders filled in."""
    out = []
    for line in (ROOT / "justfile").read_text().splitlines():
        if not line.startswith("    ") or line.strip().startswith("#"):
            continue
        command = line.strip().replace("{{args}}", "status").replace("{{title}}", "t")
        command = command.replace("{{body_file}}", "body.md").replace("{{automerge}}", "false")
        command = command.replace("{{fixture}}", "f.json")
        if command.startswith(("@", "-")) or "mapfile" in command:
            continue
        out.append(command)
    return out


# What the harness itself runs, beyond the justfile: the scripts' own interpreter calls, the
# sanctioned writes under /mnt/wsl/sextant (ADR-0028), and the lane's own git and gh commands.
LEGITIMATE = [
    "python3 -I scripts/omni_keys.py status",
    "python3 -I scripts/omni_receipt.py 123 --write out.json",
    "python3 -I deploy/wsl/hard-lines/claude-receipt.py",
    "python3 -I deploy/wsl/hard-lines/generate.py --check",
    "python3 -I deploy/wsl/hard-lines/tools.py",
    "python3 -c 'import os; print(len(os.environ))'",
    "uv run --frozen pytest tests/proofs -m ''",
    "git push",
    "git push -u",
    "git push --force-with-lease",
    "git fetch origin main",
    "git pull --ff-only origin main",
    "git log --oneline -1 main",
    "git switch -c lane-x",
    "git worktree list",
    "git worktree prune",
    "git -C . status",
    "git -C . log --oneline -1",
    "git -c user.name=Sextant commit -m probe",
    "gh pr create --title t --body-file body.md",
    "gh pr merge --auto --squash",
    "just ci",
    "just prove",
    "scripts/with-keys.sh --strict -k EXA_API_KEY -- true",
    "install -d -o sextant -g sextant /mnt/wsl/sextant",
    "cat /mnt/wsl/sextant/first-login.log",
    "mkfifo /mnt/wsl/sextant/keys/EXA_API_KEY",
    "echo ready > /mnt/wsl/sextant/keys/status",
    "export FOO=bar",
    "FOO=bar true",
    "command -v claude",
    "command -v wsl" + ".exe",  # a lookup names a program without running it
    "command -V git",
    "timeout 5 just --list",
    "nice -n 5 uv run --frozen pytest",
    "xargs -r git status",
    "bash -c 'git status'",
    "bash script.sh",
    "bash -x script.sh",
    "bash -n deploy/wsl/ao.sh",
    "sudo -n true",
    "cmd.exe /c dir",
]


def test_no_command_the_harness_runs_is_refused() -> None:
    """The owner's 2026-11-08 preference: quality first, never over-engineered security. A rule
    that blocks a legitimate command is a P1, so every command the justfile's recipes and the
    scripts themselves run must pass each engine, Codex's named 4a over-block aside."""
    commands = _justfile_commands() + LEGITIMATE
    assert len(commands) > 40, len(commands)
    calls = [{"name": "bash", "arguments": {"command": command}} for command in commands]
    refused = [
        (command, reason)
        for command, reason in zip(commands, _guard(calls)["reasons"], strict=True)
        if reason
    ]
    assert not refused, refused
    denied = [c for c in commands if _agy_first_rule(c) is not None]
    assert not denied, denied
    # The write line still holds: the same shapes outside /mnt/wsl/sextant are refused.
    assert _bash("echo ready > /mnt/wsl/other/status") != [None]
    assert _bash("cat /mnt/wsl/other/status") == [None], "reading another distro stays allowed"


def test_the_generated_rule_files_match_the_matrix() -> None:
    """One canonical table writes every rule set, so a spelling is added there and regenerated."""
    done = subprocess.run(
        ["python3", "-I", str(KIT / "generate.py"), "--check"],
        capture_output=True,
        text=True,
        cwd=ROOT,
    )
    assert done.returncode == 0, done.stderr or done.stdout
    assert "matches the matrix" in done.stdout


def test_every_generated_combination_is_refused_by_the_guard() -> None:
    """The dsh guard, which carries Claude's generated globs, over the whole cross product."""
    assert len(COMBINATIONS) > 1200, len(COMBINATIONS)
    calls = [{"name": "bash", "arguments": {"command": command}} for _, command in COMBINATIONS]
    reasons = _guard(calls)["reasons"]
    missed = [
        command for (_, command), reason in zip(COMBINATIONS, reasons, strict=True) if not reason
    ]
    assert not missed, f"{len(missed)} of {len(COMBINATIONS)} unrefused, first: {missed[:8]}"
    for line in MATRIX["lines"].values():
        assert any(line in (reason or "") for reason in reasons), line


def test_every_generated_combination_is_denied_by_antigravity() -> None:
    """Antigravity's documented matching over the same cross product."""
    missed = [command for _, command in COMBINATIONS if _agy_first_rule(command) is None]
    assert not missed, f"{len(missed)} of {len(COMBINATIONS)} unmatched, first: {missed[:8]}"


def test_every_generated_combination_matches_a_codex_rule() -> None:
    """Codex's own token-prefix semantics, read from the generated rules, over the cross product."""
    rules = [rule["pattern"] for rule in _codex_rules()]

    def matches(words: list[str]) -> bool:
        for pattern in rules:
            if len(words) < len(pattern):
                continue
            if all(
                (word in token if isinstance(token, list) else word == token)
                or (word.casefold() == token.casefold() if isinstance(token, str) else False)
                for token, word in zip(pattern, words, strict=False)
            ):
                return True
        return False

    missed = [
        command
        for key, command in COMBINATIONS
        if key != "export-p" and not matches(command.split())
    ]
    assert not missed, f"{len(missed)} of {len(COMBINATIONS)} unmatched, first: {missed[:8]}"


@pytest.mark.local
def test_each_dsh_profile_composes_the_guard(tmp_path: Path) -> None:
    """acp and headless take the installer's link, on copies; dsh-tui takes a --patch overlay."""
    dsh = Path.home() / ".local/share/sextant-agents/node_modules/.bin/dsh"
    assert dsh.exists(), "the sandbox lock's dsh is not installed"
    tools = Path.home() / ".local/share/sextant-host-tools/node_modules/.bin"
    env = {
        "HOME": str(Path.home()),
        "PATH": f"{tools}:{os.defpath}:{Path(shutil.which('node') or '').parent}",
    }

    def dump(profile: str, *extra: str, home: Path | None = None) -> str:
        done = subprocess.run(
            [str(dsh), "--profile", profile, *extra, "--dump-config"],
            env={**env, **({"DSH_HOME": str(home)} if home else {})},
            capture_output=True,
            text=True,
            timeout=120,
        )
        assert done.returncode == 0, done.stderr[-2000:]
        return done.stdout

    home = tmp_path / "dsh-home"
    for profile in ("acp", "headless"):
        source, target = Path.home() / ".dsh/profiles" / profile, home / "profiles" / profile
        target.mkdir(parents=True)
        for name in ("cordis.yml", "cordis.patch.yml", "package.json", "pnpm-workspace.yaml"):
            if (source / name).exists():
                shutil.copy2(source / name, target / name)
        assert "sextant-hard-lines" not in dump(profile, home=home)
        added = subprocess.run(
            [str(dsh), "plugin", "--profile", profile, "add", str(GUARD)],
            env={**env, "DSH_HOME": str(home)},
            capture_output=True,
            text=True,
            timeout=300,
        )
        assert added.returncode == 0, added.stderr[-2000:]
        assert "sextant-hard-lines" in dump(profile, home=home), profile
    overlay = dump("dsh-tui", "--patch", str(GUARD / "hard-lines.cordis.yml"))
    assert "sextant-hard-lines" in overlay
