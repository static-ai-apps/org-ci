"""Create a repository pair for a new app (CURATOR.md §6).

Env:
  GH_TOKEN  CI App token: administration and contents write in the org
  NAME      the app's name
  PITCH     the curator's pitch; becomes the app's first ROADMAP.md
"""

import os
import re
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from common import CONFIG, ORG, GitHubError, gh, log, put_file, set_output, workspace_of  # noqa: E402

NAME_RE = re.compile(r"^[a-z0-9][a-z0-9-]{1,38}[a-z0-9]$")

PUBLISHED_SETTINGS = {
    "has_issues": False, "has_wiki": False, "has_projects": False, "has_discussions": False,
    "allow_merge_commit": False, "allow_rebase_merge": False, "allow_squash_merge": True,
    "allow_auto_merge": False, "delete_branch_on_merge": True,
    "squash_merge_commit_title": "PR_TITLE", "squash_merge_commit_message": "PR_BODY",
}
WORKSPACE_SETTINGS = {"has_issues": False, "has_wiki": False, "has_projects": False, "has_discussions": False}


def wait_for(path, token, tries=60):
    """Poll until a newly created repo has content. GitHub fills template copies and forks in the
    background: until then the repo answers 404 (not there yet) or 409 (there, but still empty)."""
    for _ in range(tries):
        try:
            r = gh("GET", path, token=token, ok404=True)
        except GitHubError as e:
            if e.status != 409:
                raise
            r = None
        if r:
            return r
        time.sleep(3)
    raise RuntimeError(f"timed out after {tries * 3} seconds waiting for {path}")


def roadmap(name, pitch):
    return (f"# Roadmap\n\n## The pitch\n\nThis app was commissioned by the curator with this pitch. "
            f"It's a starting point, not a specification: the app's first session decides what to build "
            f"and rewrites this file as its own plan.\n\n{pitch.strip()}\n")


def main():
    token = os.environ["GH_TOKEN"]
    name = os.environ.get("NAME", "").strip()
    pitch = os.environ.get("PITCH", "").strip()
    problems = []
    if not NAME_RE.match(name) or "--" in name:
        problems.append("name must be 3 to 40 lowercase letters, digits and single hyphens, starting and ending with a letter or digit")
    if name in CONFIG["reserved_names"] or name == CONFIG["library_repo"]:
        problems.append(f"`{name}` is reserved")
    if not pitch:
        problems.append("pitch is required")
    if len(pitch) > 8000:
        problems.append("pitch is longer than 8,000 characters")
    if not problems and (gh("GET", f"/repos/{ORG}/{name}", token=token, ok404=True)
                         or gh("GET", f"/repos/{ORG}/{workspace_of(name)}", token=token, ok404=True)):
        problems.append(f"`{name}` already exists")
    if problems:
        for p in problems:
            log(f"refused: {p}")
        set_output("result", "refused: " + "; ".join(problems))
        sys.exit(1)

    template = CONFIG["template_repo"]
    first_line = pitch.splitlines()[0][:300]
    gh("POST", f"/repos/{ORG}/{template}/generate",
       {"owner": ORG, "name": name, "description": first_line, "private": False, "include_all_branches": False},
       token=token)
    wait_for(f"/repos/{ORG}/{name}/commits/main", token)
    gh("PATCH", f"/repos/{ORG}/{name}", {**PUBLISHED_SETTINGS, "homepage": f"https://{ORG}.github.io/{name}/"}, token=token)

    meta = gh("GET", f"/repos/{ORG}/{name}/contents/ROADMAP.md", token=token, ok404=True)
    put_file(name, "ROADMAP.md", roadmap(name, pitch), "Add the curator's pitch", token,
             sha=meta["sha"] if meta else None)

    try:
        gh("POST", f"/repos/{ORG}/{name}/pages", {"source": {"branch": "main", "path": "/"}}, token=token)
    except GitHubError as e:
        if e.status != 409:  # 409: already enabled
            raise
    try:
        gh("PUT", f"/repos/{ORG}/{name}/private-vulnerability-reporting", token=token)
    except GitHubError as e:
        log(f"couldn't enable private vulnerability reporting: {e}")

    ws = workspace_of(name)
    gh("POST", f"/repos/{ORG}/{name}/forks", {"organization": ORG, "name": ws, "default_branch_only": True}, token=token)
    wait_for(f"/repos/{ORG}/{ws}/commits/main", token)
    gh("PATCH", f"/repos/{ORG}/{ws}", WORKSPACE_SETTINGS, token=token)
    gh("PUT", f"/repos/{ORG}/{ws}/actions/permissions", {"enabled": False}, token=token)

    log(f"created {ORG}/{name} and {ORG}/{ws}")
    set_output("result", f"created {name}")


if __name__ == "__main__":
    main()
