"""Validate a proposed version of a published repo (SPEC.md §4, §6, §10).

Usage:
  python validate.py --repo NAME --pr-dir DIR [--base-dir DIR] --license FILE --out result.json
                     [--number N --head-sha SHA] [--idle SECONDS] [--no-runtime]

Runs without any secrets. Writes a JSON result; always exits 0 unless it crashes,
so a failed check is a result, not a job failure.
"""

import argparse
import json
import re
import struct
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from common import CONFIG, is_library, log  # noqa: E402

CODE_PATTERNS = [
    (re.compile(r"\beval\s*\("), "calls eval()"),
    (re.compile(r"\bnew\s+Function\s*\("), "uses new Function()"),
    (re.compile(r"\bset(?:Timeout|Interval)\s*\(\s*[\"'`]"), "passes a string to a timer"),
]
SW_IMPORT = re.compile(r"\bimportScripts\s*\(\s*[\"'`]\s*(?:https?:)?//", re.I)


def png_size(data):
    if data[:8] != b"\x89PNG\r\n\x1a\n" or data[12:16] != b"IHDR":
        return None
    return struct.unpack(">II", data[16:24])


def load_blocklist():
    path = Path(__file__).resolve().parent.parent / "config" / "blocklist.txt"
    return [l.strip().lower() for l in path.read_text().splitlines() if l.strip() and not l.startswith("#")]


def blocked(host, blocklist):
    return any(host == b or host.endswith("." + b) for b in blocklist)


def tree(dir_):
    """Top-level entries, excluding .git."""
    return sorted(p for p in Path(dir_).iterdir() if p.name != ".git")


def static_checks(repo, pr_dir, base_dir, license_path):
    blocks, warns, alerts = [], [], []
    wl = CONFIG["whitelist"]
    entries = tree(pr_dir)

    # Whitelist and sizes (SPEC §4.1–4.2)
    total = 0
    for p in entries:
        if p.is_dir() or p.is_symlink():
            blocks.append(f"`{p.name}` isn't allowed: the published repo may contain only whitelisted files, and no directories or links")
            continue
        if p.name not in wl:
            blocks.append(f"`{p.name}` isn't on the whitelist ({', '.join(wl)})")
            continue
        size = p.stat().st_size
        total += size
        if size > wl[p.name]["max_bytes"]:
            blocks.append(f"`{p.name}` is {size:,} bytes; the limit is {wl[p.name]['max_bytes']:,}")
    if total > CONFIG["max_tree_bytes"]:
        blocks.append(f"the files total {total:,} bytes; the limit is {CONFIG['max_tree_bytes']:,}")
    names = {p.name for p in entries}
    for name, rule in wl.items():
        if rule["required"] and name not in names:
            blocks.append(f"`{name}` is required")

    pr = Path(pr_dir)
    if is_library(repo) and "sw.js" in names:
        blocks.append("the library can't have a service worker: at the site root it would intercept every app (SPEC.md §7.3)")

    # LICENSE (SPEC §4.3)
    if "LICENSE" in names and Path(license_path).read_bytes() != (pr / "LICENSE").read_bytes():
        blocks.append("`LICENSE` must be byte-identical to app-template's")

    # index.html basics
    if "index.html" in names:
        html = (pr / "index.html").read_text("utf-8", "replace")
        if not re.search(r"<html\b[^>]*\blang\s*=\s*[\"']?[A-Za-z]", html, re.I):
            blocks.append("`index.html` needs `<html lang=\"…\">`")
        if not re.search(r"<meta\s+charset\s*=\s*[\"']?utf-8", html, re.I):
            blocks.append("`index.html` needs `<meta charset=\"utf-8\">`")
        if not re.search(r"<meta\b[^>]*name\s*=\s*[\"']?viewport", html, re.I):
            blocks.append("`index.html` needs a viewport `<meta>`")
        t = re.search(r"<title>(.*?)</title>", html, re.I | re.S)
        if not t or not t.group(1).strip():
            blocks.append("`index.html` needs a non-empty `<title>`")
        for rx, what in CODE_PATTERNS:
            if rx.search(html):
                alerts.append(f"index.html {what}")

    if "sw.js" in names:
        sw = (pr / "sw.js").read_text("utf-8", "replace")
        if SW_IMPORT.search(sw):
            alerts.append("sw.js imports an external script")
        for rx, what in CODE_PATTERNS:
            if rx.search(sw):
                alerts.append(f"sw.js {what}")

    if "manifest.webmanifest" in names:
        try:
            json.loads((pr / "manifest.webmanifest").read_text("utf-8"))
        except ValueError:
            blocks.append("`manifest.webmanifest` isn't valid JSON")

    if "icon.png" in names:
        size = png_size((pr / "icon.png").read_bytes())
        if not size:
            blocks.append("`icon.png` isn't a PNG")
        elif size[0] != size[1] or not 192 <= size[0] <= 1024:
            blocks.append(f"`icon.png` is {size[0]}×{size[1]}; it must be square, 192 to 1024 pixels")

    # Structured data (SPEC §10). The library describes itself however the curator likes.
    if "index.html" in names and not is_library(repo):
        import jsonld
        b, w, _ = jsonld.check((pr / "index.html").read_text("utf-8", "replace"), repo)
        blocks += b
        warns += w
    return blocks, warns, alerts


def runtime_checks(repo, pr_dir, base_dir, idle):
    import runtime_check
    det = CONFIG["detectors"]
    blocks, warns, alerts = [], [], []
    r = runtime_check.run(pr_dir, repo, idle)
    blocklist = load_blocklist()

    if r["load_error"]:
        blocks.append(f"the page didn't load in the test browser: {r['load_error']}")
    for e in r["errors"][:3]:
        blocks.append(f"uncaught error while loading: `{e}`")
    bad = [h for h in r["hosts"] if blocked(h, blocklist)]
    if bad:
        blocks.append(f"loads from a blocked host: {', '.join(bad)}")
    cpu = r["cpu_cores"] or 0
    if cpu >= det["cpu_block_cores"]:
        blocks.append(f"uses {cpu:.2f} CPU cores while idle; the limit is {det['cpu_block_cores']}. "
                      "Stop work when nothing is happening (ADVICE.md §16)")
    elif cpu >= det["cpu_alert_cores"]:
        alerts.append(f"idle CPU {cpu:.2f} cores")
    if r["websockets"]:
        alerts.append(f"opened WebSockets without interaction: {', '.join(r['websockets'][:5])}")
    if r["webrtc"]:
        alerts.append(f"created {r['webrtc']} WebRTC connection(s) without interaction")
    if len(r["hosts"]) > det["max_external_hosts"]:
        alerts.append(f"{len(r['hosts'])} external hosts: {', '.join(r['hosts'][:20])}")
    if r["requests_idle"] > det["max_idle_requests"]:
        alerts.append(f"{r['requests_idle']} requests while idle")
    if r["overflow_320"]:
        warns.append("the page scrolls horizontally at 320 px wide (ADVICE.md §5)")

    new_hosts = []
    if base_dir and (Path(base_dir) / "index.html").exists():
        try:
            base = runtime_check.run(base_dir, repo, idle_seconds=3, settle_seconds=3)
            new_hosts = sorted(set(r["hosts"]) - set(base["hosts"]))
        except Exception as e:  # the old version failing is not this pull request's problem
            log(f"base runtime check failed: {e}")
    if new_hosts:
        alerts.append(f"new external hosts: {', '.join(new_hosts)}")
    return blocks, warns, alerts, r


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--repo", required=True)
    ap.add_argument("--pr-dir", required=True)
    ap.add_argument("--base-dir")
    ap.add_argument("--license", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--number", type=int)
    ap.add_argument("--head-sha")
    ap.add_argument("--idle", type=int)
    ap.add_argument("--no-runtime", action="store_true")
    a = ap.parse_args()

    result = {"repo": a.repo, "number": a.number, "head_sha": a.head_sha,
              "blocks": [], "warns": [], "alerts": [], "runtime": None, "crashed": None}
    try:
        b, w, al = static_checks(a.repo, a.pr_dir, a.base_dir, a.license)
        result["blocks"] += b; result["warns"] += w; result["alerts"] += al
        has_index = (Path(a.pr_dir) / "index.html").is_file()
        if not a.no_runtime and has_index:
            b, w, al, r = runtime_checks(a.repo, a.pr_dir, a.base_dir, a.idle)
            result["blocks"] += b; result["warns"] += w; result["alerts"] += al
            result["runtime"] = r
    except Exception as e:  # report, don't hide: act.py treats a crash as "not merged"
        result["crashed"] = f"{type(e).__name__}: {e}"
        log(f"validate crashed: {result['crashed']}")
    Path(a.out).write_text(json.dumps(result, indent=2))
    print(json.dumps({k: result[k] for k in ("repo", "number", "blocks", "warns", "alerts", "crashed")}, indent=2))


if __name__ == "__main__":
    main()
