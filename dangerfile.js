// The repo's first rule, enforced on every PR: never self-invent. Runs from the base branch.
// Framework: danger/danger-js@14.1.0. Rules below only read the PR's own body and file list.
const { danger, fail } = require("danger");

const body = danger.github.pr.body ?? "";
const section = (name) => {
  const match = body.match(new RegExp(`^## ${name}\\s*$([\\s\\S]*?)(?=^## |\\Z)`, "m"));
  return (match?.[1] ?? "").replace(/<!--[\s\S]*?-->/g, "").trim();
};

for (const name of ["What changed", "Manifest row", "Upstream references", "How verified", "How to revert"]) {
  if (!section(name)) fail(`PR body: "${name}" is empty.`);
}

const sources = section("Upstream references");
const repoAtCommit = /[\w.-]+\/[\w.-]+@\S*[\s\S]*?\b[0-9a-f]{40}\b/;
const docsWithDate = /https?:\/\/\S+[\s\S]*?read 20\d\d-\d\d-\d\d/;
const paper = /(doi\.org\/10\.|\bdoi:10\.|arxiv\.org\/abs\/|\barXiv:\d)/i;

const isDependabot = danger.github.pr.user.login === "dependabot[bot]";
if (!isDependabot && !repoAtCommit.test(sources) && !docsWithDate.test(sources) && !paper.test(sources)) {
  fail(
    "Never self-invent: Upstream references must name a source repo@tag with its full commit SHA, " +
      "a docs page with `read YYYY-MM-DD`, or a paper (DOI or arXiv).",
  );
}

const changed = [...danger.git.created_files, ...danger.git.modified_files];
const touchesStrategy = changed.some((path) => path.startsWith("src/sextant/strategies/"));
if (touchesStrategy && !repoAtCommit.test(sources) && !paper.test(sources)) {
  fail("A strategy starts from an upstream template at a pinned commit or a cited paper.");
}
