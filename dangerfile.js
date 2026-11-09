// The repo's first rule, enforced on every PR: never self-invent. Runs from the base branch.
// Framework: danger/danger-js@14.1.0. Rules below only read the PR's own body and file list.
const { danger, fail, schedule } = require("danger");

const pr = danger.github.pr;
const body = pr.body ?? "";
const section = (name) => {
  const match = body.match(new RegExp(`^## ${name}\\s*$([\\s\\S]*?)(?=^## |(?![\\s\\S]))`, "m"));
  return (match?.[1] ?? "").replace(/<!--[\s\S]*?-->/g, "").trim();
};

const sources = section("Upstream references");
// `owner/repo@tag`, or the manifest's own `[owner/repo](url)@tag`, then the full commit SHA.
const repoAtCommit = /[\w.-]+\/[\w.-]+(?:\]\([^)\s]*\))?@\S*[\s\S]*?\b[0-9a-f]{40}\b/;
const docsWithDate = /https?:\/\/\S+[\s\S]*?read 20\d\d-\d\d-\d\d/;
const paper = /(doi\.org\/10\.|\bdoi:10\.|arxiv\.org\/abs\/|\barXiv:\d)/i;

// Dependabot's generated body cites the upstream's own release notes, and it changes pins only.
if (pr.user.login !== "dependabot[bot]") {
  for (const name of ["What changed", "Manifest row", "Upstream references", "How verified", "How to revert"]) {
    if (!section(name)) fail(`PR body: "${name}" is empty.`);
  }

  if (!repoAtCommit.test(sources) && !docsWithDate.test(sources) && !paper.test(sources)) {
    fail(
      "Never self-invent: Upstream references must name a source repo@tag with its full commit SHA, " +
        "a docs page with `read YYYY-MM-DD`, or a paper (DOI or arXiv).",
    );
  }

  const named = [...section("Manifest row").matchAll(/"([^"]+)"/g)].map((match) => match[1]);
  schedule(async () => {
    const manifest = await danger.github.utils.fileContents("docs/manifest.md");
    const rows = manifest.split("\n").filter((row) => !row.startsWith("| Practice or pick |"));
    if (!named.some((name) => rows.some((row) => row.startsWith(`| ${name} |`)))) {
      fail('Manifest row: name a row of docs/manifest.md in "double quotes". This PR may add it.');
    }
  });
}

const changed = [...danger.git.created_files, ...danger.git.modified_files, ...(danger.git.deleted_files ?? [])];
const touchesStrategy = changed.some((path) => path.startsWith("src/sextant/strategies/"));
if (touchesStrategy && !repoAtCommit.test(sources) && !paper.test(sources)) {
  fail("Never self-invent: a strategy starts from an upstream template at a pinned commit or a cited paper.");
}
