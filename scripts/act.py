"""Act on validation results: comment, merge, alert, close foreign pull requests, re-bake.

Env:
  GH_TOKEN     the CI App's installation token
  MATRIX       JSON from discover.py (what should have been validated)
  FOREIGN      JSON from discover.py (what to close)
  RESULTS_DIR  directory holding result-<repo>-<number>/result.json artifacts
"""

import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from common import CONFIG, ORG, GitHubError, defang, gh, log, paginate, raise_alert  # noqa: E402

MARKER = "<!-- org-ci:result"


def upsert_comment(repo, number, body, token):
    ci = CONFIG["identities"]["ci"]
    for c in paginate(f"/repos/{ORG}/{repo}/issues/{number}/comments", token=token):
        if c["user"]["login"] == ci and MARKER in (c.get("body") or ""):
            gh("PATCH", f"/repos/{ORG}/{repo}/issues/comments/{c['id']}", {"body": body}, token=token)
            return
    gh("POST", f"/repos/{ORG}/{repo}/issues/{number}/comments", {"body": body}, token=token)


def comment(state, sha, heading, blocks=(), warns=(), note=None):
    lines = [f"{MARKER} sha={sha} state={state} -->", f"**{heading}**", ""]
    if blocks:
        lines += ["Blocking:", ""] + [f"- {defang(b)}" for b in blocks] + [""]
    if warns:
        lines += ["Worth fixing:", ""] + [f"- {defang(w)}" for w in warns] + [""]
    if note:
        lines += [note, ""]
    lines.append(f"Checked commit `{sha[:7]}`. The rules are in SPEC.md on the instructions branch of "
                 f"[app-template](https://github.com/{ORG}/app-template/tree/instructions).")
    return "\n".join(lines)


def load_result(results_dir, repo, number):
    p = Path(results_dir) / f"result-{repo}-{number}" / "result.json"
    return json.loads(p.read_text()) if p.exists() else None


def handle(entry, results_dir, token):
    """Returns True if a pull request was merged."""
    repo, number = entry["repo"], entry["number"]
    pr = gh("GET", f"/repos/{ORG}/{repo}/pulls/{number}", token=token)
    if pr["state"] != "open":
        return False
    sha = pr["head"]["sha"]
    r = load_result(results_dir, repo, number)
    if r is None or r.get("crashed"):
        why = defang(r["crashed"]) if r else "no result was produced"
        upsert_comment(repo, number, comment("error", sha, "CI couldn't check this pull request",
                                             note=f"This is CI's problem, not yours ({why}). It will try again."), token)
        return False
    if r["head_sha"] != sha:
        log(f"{repo}#{number}: head moved to {sha[:7]} during validation; next run will check it")
        return False

    if r["alerts"]:
        body = "\n".join([f"Pull request: https://github.com/{ORG}/{repo}/pull/{number} (commit `{sha[:7]}`)",
                          "", "Detector findings:", ""] + [f"- {defang(a)}" for a in r["alerts"]]
                         + ["", "Blocking findings, if any:", ""] + [f"- {defang(b)}" for b in r["blocks"]]
                         + ["", f"External hosts: {defang(', '.join((r.get('runtime') or {}).get('hosts', [])) or 'none')}"])
        raise_alert(f"Detector alert: {repo}#{number}", body, token)

    if r["blocks"]:
        upsert_comment(repo, number, comment("blocked", sha, "Blocked: this pull request can't merge yet",
                                             r["blocks"], r["warns"], "Push a fix to the same branch and CI will check again."), token)
        return False

    try:
        gh("PUT", f"/repos/{ORG}/{repo}/pulls/{number}/merge",
           {"merge_method": "squash", "sha": sha, "commit_title": f"{pr['title']} (#{number})",
            "commit_message": pr.get("body") or ""}, token=token)
    except GitHubError as e:
        if e.status == 409:
            upsert_comment(repo, number, comment("retry", sha, "Checks passed, but the branch changed before merging",
                                                 note="CI will check the new commit."), token)
        else:
            upsert_comment(repo, number, comment("blocked", sha, "Checks passed, but GitHub refused the merge",
                                                 [f"GitHub said: {e}. Usually this means the branch conflicts with main: "
                                                  "sync your workspace's main from the published repo, merge it into your "
                                                  "branch, and push."]), token)
        return False
    upsert_comment(repo, number, comment("merged", sha, "Passed and merged", warns=r["warns"],
                                         note="Pages will update within a few minutes."), token)
    log(f"merged {repo}#{number}")
    return True


def close_foreign(entry, token):
    repo, number = entry["repo"], entry["number"]
    body = ("This repository accepts changes only from its workspace, through the agents that maintain it, "
            f"so this pull request is being closed automatically. If you've found a problem with the app, "
            f"please report it privately: https://github.com/{ORG}/{repo}/security/advisories/new")
    try:
        gh("POST", f"/repos/{ORG}/{repo}/issues/{number}/comments", {"body": body}, token=token)
        gh("PATCH", f"/repos/{ORG}/{repo}/pulls/{number}", {"state": "closed"}, token=token)
        log(f"closed foreign {repo}#{number}: {'; '.join(entry['reasons'])}")
    except GitHubError as e:
        log(f"couldn't close {repo}#{number}: {e}")


def main():
    token = os.environ["GH_TOKEN"]
    matrix = json.loads(os.environ.get("MATRIX") or "[]")
    foreign = json.loads(os.environ.get("FOREIGN") or "[]")
    results_dir = os.environ.get("RESULTS_DIR", "results")
    merged = False
    for entry in matrix:
        try:
            merged |= handle(entry, results_dir, token)
        except GitHubError as e:
            log(f"{entry['repo']}#{entry['number']}: {e}")
    for entry in foreign:
        close_foreign(entry, token)
    if merged:
        import bake
        bake.run(token)


if __name__ == "__main__":
    main()
