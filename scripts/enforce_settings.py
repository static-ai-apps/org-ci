"""Re-apply the standard settings to every repository pair, in case anything drifted.

Env: GH_TOKEN (CI App token with administration write). DRY_RUN=1 reports without changing anything.
"""

import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from common import ORG, GitHubError, gh, log, org_repos, managed_repos, workspace_of  # noqa: E402
from create_app import PUBLISHED_SETTINGS, WORKSPACE_SETTINGS  # noqa: E402


def drift(current, wanted):
    return {k: v for k, v in wanted.items() if current.get(k) != v}


def main():
    token = os.environ["GH_TOKEN"]
    dry = bool(os.environ.get("DRY_RUN"))
    names = {r["name"] for r in org_repos(token)}
    for r in managed_repos(org_repos(token)):
        name, ws = r["name"], workspace_of(r["name"])
        full = gh("GET", f"/repos/{ORG}/{name}", token=token)
        fix = drift(full, PUBLISHED_SETTINGS)
        if fix:
            log(f"{name}: {fix}")
            if not dry:
                gh("PATCH", f"/repos/{ORG}/{name}", fix, token=token)
        if ws not in names:
            log(f"{name}: no workspace {ws}")
            continue
        wfull = gh("GET", f"/repos/{ORG}/{ws}", token=token)
        fix = drift(wfull, WORKSPACE_SETTINGS)
        if fix:
            log(f"{ws}: {fix}")
            if not dry:
                gh("PATCH", f"/repos/{ORG}/{ws}", fix, token=token)
        perms = gh("GET", f"/repos/{ORG}/{ws}/actions/permissions", token=token)
        if perms.get("enabled"):
            log(f"{ws}: Actions enabled; disabling")
            if not dry:
                gh("PUT", f"/repos/{ORG}/{ws}/actions/permissions", {"enabled": False}, token=token)
        if wfull.get("has_pages"):
            log(f"{ws}: Pages enabled; disabling")
            if not dry:
                try:
                    gh("DELETE", f"/repos/{ORG}/{ws}/pages", token=token)
                except GitHubError as e:
                    log(f"{ws}: couldn't disable Pages: {e}")


if __name__ == "__main__":
    main()
