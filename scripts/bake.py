"""Rewrite the library's org-data block (SPEC.md §9.1).

Env: GH_TOKEN (CI App token, needs contents write on the library). DRY_RUN=1 prints instead of committing.
"""

import json
import os
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from common import CONFIG, ORG, gh, get_file, log, managed_repos, org_repos, put_file  # noqa: E402
import jsonld  # noqa: E402

BLOCK_RE = re.compile(
    r'(<!-- BEGIN CI DATA[^>]*-->\s*<script type="application/json" id="org-data">)(.*?)(</script>\s*<!-- END CI DATA -->)',
    re.S)


def _words(v, limit):
    items = v if isinstance(v, list) else [w.strip() for w in v.split(",")] if isinstance(v, str) else []
    return [w for w in items if isinstance(w, str) and w][:limit]


def collect(token=None):
    """Listed apps: managed repos whose published index.html has a valid description (SPEC.md §10)."""
    repos = []
    for r in managed_repos(org_repos(token)):
        name = r["name"]
        if name == CONFIG["library_repo"]:
            continue
        _, _, ld = jsonld.check(get_file(name, "index.html", token=token) or "", name)
        if not ld:
            continue
        files = {f["name"] for f in (gh("GET", f"/repos/{ORG}/{name}/contents/", token=token, ok404=True) or [])}
        audience = ld.get("audience") or {}
        repos.append({
            "repo": name,
            "name": ld["name"],
            "tagline": ld["disambiguatingDescription"],
            "audience": audience.get("audienceType", "") if isinstance(audience, dict) else "",
            "keywords": _words(ld.get("keywords"), 8),
            "stars": r["stargazers_count"],
            "created": r["created_at"],
            "updated": r["pushed_at"],
            "repo_url": r["html_url"],
            "app_url": f"https://{ORG}.github.io/{name}/",
            "has_icon": "icon.png" in files,
            "has_changelog": "CHANGELOG.md" in files,
            "has_roadmap": "ROADMAP.md" in files,
            "ld": ld,
        })
    repos.sort(key=lambda x: x["repo"])
    return repos


def render(html, repos):
    data = {"generated": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"), "repos": repos}
    # "</" can't appear inside a script element; escape it so data can't close the block.
    payload = json.dumps(data, ensure_ascii=False, separators=(",", ":")).replace("</", "<\\/")
    if not BLOCK_RE.search(html):
        raise ValueError("the library's index.html has no CI data block (SPEC.md §9.1)")
    return BLOCK_RE.sub(lambda m: m.group(1) + payload + m.group(3), html, count=1)


def current_repos(html):
    m = BLOCK_RE.search(html)
    try:
        return json.loads(m.group(2)).get("repos") if m else None
    except ValueError:
        return None


def run(token=None):
    lib = CONFIG["library_repo"]
    meta = gh("GET", f"/repos/{ORG}/{lib}/contents/index.html", token=token)
    html = get_file(lib, "index.html", token=token)
    repos = collect(token)
    if current_repos(html) == repos and not os.environ.get("FORCE"):
        log("library data unchanged")
        return False
    new_html = render(html, repos)
    if os.environ.get("DRY_RUN"):
        print(BLOCK_RE.search(new_html).group(2))
        return False
    put_file(lib, "index.html", new_html, f"Update library data: {len(repos)} apps", token, sha=meta["sha"])
    log(f"library data updated: {len(repos)} apps")
    return True


if __name__ == "__main__":
    run(os.environ.get("GH_TOKEN"))
