# Keep the Claude shelf declarative

Use Claude's own project marketplaces and relative-source plugins. Pin a supported release ref, turn off automatic updates, and record the verified commit; a marketplace `ref` is not a commit-SHA field. For untagged catalogs, a small verbatim copy can use Claude's native local marketplace. Hash all copied files, including skill scripts and references.

Disable an opt-in plugin at the plugin boundary as well as through its documented switch when its pinned scripts do not all implement that switch. Apply the opt-in through native session settings, keeping ordinary sessions free of that bundle's hooks and MCP server.

Evidence and the upstream references: [2026-11-06 Claude shelf](../research/2026-11-06-claude-shelf.md). The changes implementing these lessons are `.claude/settings.json`, `.claude/lsp/`, `.claude/shelf.lock.json` and `just omc`.
