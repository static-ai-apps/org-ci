"""Shared helpers for org-ci scripts: config, GitHub API, front matter."""

import base64
import json
import os
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CONFIG = json.loads((ROOT / "config" / "config.json").read_text())
ORG = CONFIG["org"]
API = "https://api.github.com"


def log(*args):
    print(*args, file=sys.stderr, flush=True)


# ---------- GitHub API ----------

class GitHubError(Exception):
    def __init__(self, status, message, body=None):
        super().__init__(f"{status}: {message}")
        self.status = status
        self.body = body


def gh(method, path, body=None, token=None, accept="application/vnd.github+json", raw=False, ok404=False):
    """Call the GitHub REST API. Returns parsed JSON (or text if raw), None on 404 if ok404."""
    token = token if token is not None else os.environ.get("GH_TOKEN", "")
    url = path if path.startswith("http") else f"{API}{path}"
    data = json.dumps(body).encode() if body is not None else None
    headers = {"Accept": accept, "X-GitHub-Api-Version": "2022-11-28", "User-Agent": f"{ORG}-org-ci"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    if data is not None:
        headers["Content-Type"] = "application/json"
    for attempt in range(4):
        req = urllib.request.Request(url, data=data, method=method, headers=headers)
        try:
            with urllib.request.urlopen(req, timeout=60) as resp:
                text = resp.read().decode("utf-8", "replace")
                if raw:
                    return text
                return json.loads(text) if text.strip() else None
        except urllib.error.HTTPError as e:
            text = e.read().decode("utf-8", "replace")
            if e.code == 404 and ok404:
                return None
            if e.code in (502, 503, 504) and attempt < 3:
                time.sleep(2 ** attempt)
                continue
            try:
                msg = json.loads(text).get("message", text)
            except ValueError:
                msg = text
            raise GitHubError(e.code, msg, text) from None
        except urllib.error.URLError:
            if attempt < 3:
                time.sleep(2 ** attempt)
                continue
            raise


def paginate(path, token=None, per_page=100):
    sep = "&" if "?" in path else "?"
    page = 1
    while True:
        items = gh("GET", f"{path}{sep}per_page={per_page}&page={page}", token=token)
        if not items:
            return
        yield from items
        if len(items) < per_page:
            return
        page += 1


def org_repos(token=None):
    return list(paginate(f"/orgs/{ORG}/repos?type=public", token=token))


def managed_repos(repos):
    """Published repos CI manages: every repo with a workspace pair (`name` and `.name`), not archived.
    The template, org-ci, alerts and anything else without a workspace are left alone."""
    names = {r["name"] for r in repos}
    return [r for r in repos if not r["name"].startswith(".") and f".{r['name']}" in names and not r.get("archived")]


def workspace_of(repo_name):
    return f".{repo_name}"


def is_library(repo_name):
    return repo_name == CONFIG["library_repo"]


def expected_identity(repo_name):
    return CONFIG["identities"]["curator" if is_library(repo_name) else "ic"]


def get_file(repo, path, ref=None, token=None):
    """Text of a file in an org repo, or None if absent."""
    q = f"?ref={urllib.parse.quote(ref)}" if ref else ""
    return gh("GET", f"/repos/{ORG}/{repo}/contents/{urllib.parse.quote(path)}{q}",
              token=token, accept="application/vnd.github.raw+json", raw=True, ok404=True)


def put_file(repo, path, text, message, token, sha=None, branch=None):
    body = {"message": message, "content": base64.b64encode(text.encode()).decode()}
    if sha:
        body["sha"] = sha
    if branch:
        body["branch"] = branch
    return gh("PUT", f"/repos/{ORG}/{repo}/contents/{urllib.parse.quote(path)}", body, token=token)


def set_output(name, value):
    out = os.environ.get("GITHUB_OUTPUT")
    line = f"{name}={value}\n"
    if out:
        with open(out, "a") as f:
            f.write(line)
    else:
        print(line, end="")


# ---------- Alerts ----------

def defang(text):
    """Make untrusted text safe to post: no @mentions, no closing our HTML comments."""
    return str(text).replace("@", "@​").replace("-->", "--​>")


def raise_alert(title, body, token):
    """Open an issue in the private alerts repo, or comment on an open one with the same title.
    Also posts to ALERT_WEBHOOK_URL if set (any service that accepts {"text": ...})."""
    repo = CONFIG["alerts_repo"]
    existing = None
    for issue in paginate(f"/repos/{ORG}/{repo}/issues?state=open", token=token):
        if issue["title"] == title and "pull_request" not in issue:
            existing = issue
            break
    if existing:
        gh("POST", f"/repos/{ORG}/{repo}/issues/{existing['number']}/comments", {"body": body}, token=token)
        url = existing["html_url"]
    else:
        url = gh("POST", f"/repos/{ORG}/{repo}/issues", {"title": title, "body": body}, token=token)["html_url"]
    hook = os.environ.get("ALERT_WEBHOOK_URL")
    if hook:
        try:
            req = urllib.request.Request(hook, data=json.dumps({"text": f"{title}\n{url}"}).encode(),
                                         headers={"Content-Type": "application/json"}, method="POST")
            urllib.request.urlopen(req, timeout=20).read()
        except Exception as e:  # the issue is the record; the webhook is a courtesy
            log(f"webhook failed: {e}")
    return url
