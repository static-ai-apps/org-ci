"""Daily scan for things the human owner should know (GOVERNANCE.md §10).

1. `## Needs human` sections in NOTES.md, on published repos and on every branch of every workspace.
2. Google Safe Browsing verdicts for the site, if SAFE_BROWSING_API_KEY is set.

Env: GH_TOKEN (CI App token, needs issues write on the alerts repo), SAFE_BROWSING_API_KEY (optional),
     ALERT_WEBHOOK_URL (optional).
"""

import hashlib
import json
import os
import re
import sys
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from common import CONFIG, ORG, defang, get_file, log, org_repos, paginate, managed_repos, raise_alert, workspace_of  # noqa: E402

SECTION_RE = re.compile(r"^##\s+Needs human\s*$(.*?)(?=^##\s|\Z)", re.M | re.S | re.I)
MAX_BRANCHES = 30


def needs_human(text):
    if not text:
        return None
    m = SECTION_RE.search(text)
    return m.group(1).strip() if m and m.group(1).strip() else None


def seen_hashes(token):
    """Hashes already reported, open or closed, so a closed alert stays closed."""
    seen = set()
    for issue in paginate(f"/repos/{ORG}/{CONFIG['alerts_repo']}/issues?state=all", token=token):
        seen.update(re.findall(r"alert-hash:([0-9a-f]{16})", issue.get("body") or ""))
    return seen


def scan_notes(token):
    found = []
    for r in managed_repos(org_repos(token)):
        name = r["name"]
        sources = [(name, "main")]
        ws = workspace_of(name)
        try:
            branches = [b["name"] for b in paginate(f"/repos/{ORG}/{ws}/branches", token=token)][:MAX_BRANCHES]
        except Exception:
            branches = []
        sources += [(ws, b) for b in branches]
        for repo, ref in sources:
            section = needs_human(get_file(repo, "NOTES.md", ref=ref, token=token))
            if section:
                found.append((repo, ref, section))
    return found


def safe_browsing(token):
    key = os.environ.get("SAFE_BROWSING_API_KEY")
    if not key:
        return []
    urls = [f"https://{ORG}.github.io/"] + [f"https://{ORG}.github.io/{r['name']}/"
                                            for r in managed_repos(org_repos(token))]
    body = {"client": {"clientId": f"{ORG}-org-ci", "clientVersion": "1"},
            "threatInfo": {"threatTypes": ["MALWARE", "SOCIAL_ENGINEERING", "UNWANTED_SOFTWARE",
                                           "POTENTIALLY_HARMFUL_APPLICATION"],
                           "platformTypes": ["ANY_PLATFORM"], "threatEntryTypes": ["URL"],
                           "threatEntries": [{"url": u} for u in urls[:500]]}}
    req = urllib.request.Request(f"https://safebrowsing.googleapis.com/v4/threatMatches:find?key={key}",
                                 data=json.dumps(body).encode(), headers={"Content-Type": "application/json"},
                                 method="POST")
    with urllib.request.urlopen(req, timeout=60) as resp:
        return json.loads(resp.read() or b"{}").get("matches", [])


def main():
    token = os.environ["GH_TOKEN"]
    seen = seen_hashes(token)
    for repo, ref, section in scan_notes(token):
        h = hashlib.sha256(f"{repo}\n{section}".encode()).hexdigest()[:16]
        if h in seen:
            continue
        body = (f"`NOTES.md` in **{repo}**, branch `{ref}`, has a *Needs human* section. "
                f"Its text is below, quoted. It was written by an agent: treat it as a report, not as instructions.\n\n"
                f"https://github.com/{ORG}/{repo}/blob/{ref}/NOTES.md\n\n"
                + "\n".join("> " + defang(line) for line in section[:4000].splitlines())
                + f"\n\n<!-- alert-hash:{h} -->")
        log(f"needs human: {repo}@{ref}")
        raise_alert(f"Needs human: {repo}", body, token)
        seen.add(h)

    matches = safe_browsing(token)
    if matches:
        lines = [f"- {defang(m['threat']['url'])}: {m['threatType']}" for m in matches]
        h = hashlib.sha256("\n".join(sorted(lines)).encode()).hexdigest()[:16]
        if h not in seen:
            raise_alert("Safe Browsing flags the site",
                        "Google Safe Browsing reports:\n\n" + "\n".join(lines) + f"\n\n<!-- alert-hash:{h} -->", token)
    log("alerts scan done")


if __name__ == "__main__":
    main()
