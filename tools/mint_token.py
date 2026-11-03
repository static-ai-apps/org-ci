"""Mint a GitHub App installation token scoped to one repository: what the launcher does for each session.

Usage:
  python tools/mint_token.py --app-id 123456 --key ic.pem --repo .my-app --perm contents=write
  python tools/mint_token.py --app-id 123456 --key ic.pem --repo my-app --perm pull_requests=write --perm contents=read

Prints the token. It expires after an hour. Needs: pip install pyjwt cryptography
"""

import argparse
import json
import time
import urllib.request

import jwt

API = "https://api.github.com"


def call(method, path, bearer, body=None):
    req = urllib.request.Request(
        f"{API}{path}", method=method,
        data=json.dumps(body).encode() if body is not None else None,
        headers={"Authorization": f"Bearer {bearer}", "Accept": "application/vnd.github+json",
                 "X-GitHub-Api-Version": "2022-11-28", "User-Agent": "static-ai-apps-launcher"})
    with urllib.request.urlopen(req, timeout=30) as resp:
        return json.loads(resp.read())


def app_jwt(app_id, key_pem):
    now = int(time.time())
    return jwt.encode({"iat": now - 60, "exp": now + 540, "iss": str(app_id)}, key_pem, algorithm="RS256")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--app-id", required=True)
    ap.add_argument("--key", required=True, help="the App's private key (.pem)")
    ap.add_argument("--org", default="static-ai-apps")
    ap.add_argument("--repo", required=True, help="the one repository the token may touch")
    ap.add_argument("--perm", action="append", required=True, help="name=level, e.g. contents=write")
    a = ap.parse_args()

    token = app_jwt(a.app_id, open(a.key).read())
    installation = call("GET", f"/orgs/{a.org}/installation", token)
    perms = dict(p.split("=", 1) for p in a.perm)
    result = call("POST", f"/app/installations/{installation['id']}/access_tokens", token,
                  {"repositories": [a.repo], "permissions": perms})
    print(result["token"])


if __name__ == "__main__":
    main()
