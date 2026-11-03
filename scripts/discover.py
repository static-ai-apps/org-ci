"""Find open pull requests on published repos and sort them (SPEC.md §3).

Outputs (to $GITHUB_OUTPUT):
  matrix   JSON list of pull requests to validate
  count    how many
  foreign  JSON list of pull requests to close: wrong head repo, author or base
Read-only: works with any token that can read public repos.

Env: ONLY_REPO (optional) limits the run to one published repo.
"""

import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from common import CONFIG, ORG, expected_identity, log, org_repos, paginate, managed_repos, set_output, workspace_of  # noqa: E402

MARKER = "<!-- org-ci:result"


def last_result(repo, number):
    """(sha, state) from CI's own comment on this pull request, if any."""
    ci = CONFIG["identities"]["ci"]
    found = (None, None)
    for c in paginate(f"/repos/{ORG}/{repo}/issues/{number}/comments"):
        body = c.get("body") or ""
        if c["user"]["login"] == ci and MARKER in body:
            line = body[body.index(MARKER):].split("-->")[0]
            parts = dict(p.split("=", 1) for p in line.split()[1:] if "=" in p)
            found = (parts.get("sha"), parts.get("state"))
    return found


def main():
    only = os.environ.get("ONLY_REPO", "").strip()
    repos = managed_repos(org_repos())
    if only:
        repos = [r for r in repos if r["name"] == only]
    matrix, foreign = [], []
    for r in repos:
        name = r["name"]
        for pr in paginate(f"/repos/{ORG}/{name}/pulls?state=open"):
            head_repo = (pr["head"].get("repo") or {}).get("full_name")
            entry = {"repo": name, "number": pr["number"], "head_sha": pr["head"]["sha"],
                     "head_repo": head_repo, "head_ref": pr["head"]["ref"], "author": pr["user"]["login"]}
            reasons = []
            if head_repo != f"{ORG}/{workspace_of(name)}":
                reasons.append(f"it comes from {head_repo or 'a deleted repository'}, not {ORG}/{workspace_of(name)}")
            if pr["user"]["login"] != expected_identity(name):
                reasons.append(f"it was opened by {pr['user']['login']}")
            if pr["base"]["ref"] != "main":
                reasons.append(f"it targets {pr['base']['ref']}, not main")
            if reasons:
                foreign.append({**entry, "reasons": reasons})
                continue
            sha, state = last_result(name, pr["number"])
            if sha == pr["head"]["sha"] and state == "blocked":
                log(f"skip {name}#{pr['number']}: already blocked at {sha[:7]}, nothing new pushed")
                continue
            matrix.append(entry)
    log(f"{len(matrix)} to validate, {len(foreign)} to close")
    set_output("matrix", json.dumps(matrix))
    set_output("count", str(len(matrix)))
    set_output("foreign", json.dumps(foreign))


if __name__ == "__main__":
    main()
