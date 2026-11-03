"""Load an app in headless Chromium and watch it while idle (SPEC.md §6).

Usage: python runtime_check.py <app-dir> <repo-name> [--idle SECONDS]
Prints a JSON report. Set CHROME_PATH to use a specific Chrome binary.
"""

import argparse
import functools
import http.server
import json
import os
import socketserver
import sys
import tempfile
import threading
import time
from pathlib import Path
from urllib.parse import urlparse

import psutil
from playwright.sync_api import sync_playwright

sys.path.insert(0, str(Path(__file__).resolve().parent))
from common import CONFIG  # noqa: E402

LOCAL_HOSTS = {"127.0.0.1", "localhost"}

# Counts RTCPeerConnection creation, which Playwright can't observe directly.
INIT_SCRIPT = """
(() => {
  const Orig = window.RTCPeerConnection || window.webkitRTCPeerConnection;
  if (!Orig) return;
  window.__orgci_rtc = 0;
  const Wrapped = function (...args) { window.__orgci_rtc++; return new Orig(...args); };
  Wrapped.prototype = Orig.prototype;
  window.RTCPeerConnection = Wrapped;
  if (window.webkitRTCPeerConnection) window.webkitRTCPeerConnection = Wrapped;
})();
"""


class QuietHandler(http.server.SimpleHTTPRequestHandler):
    def log_message(self, *args):
        pass


def serve(app_dir, repo):
    """Serve app_dir at http://127.0.0.1:<port>/<repo>/, like Pages does."""
    root = Path(tempfile.mkdtemp(prefix="orgci-site-"))
    (root / repo).symlink_to(Path(app_dir).resolve(), target_is_directory=True)
    handler = functools.partial(QuietHandler, directory=str(root))
    httpd = socketserver.ThreadingTCPServer(("127.0.0.1", 0), handler)
    httpd.daemon_threads = True
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    return httpd, f"http://127.0.0.1:{httpd.server_address[1]}/{repo}/"


def chrome_cpu_seconds():
    """Total CPU time of every process descended from this one (browser, renderers, GPU, workers)."""
    total = 0.0
    for p in psutil.Process(os.getpid()).children(recursive=True):
        try:
            t = p.cpu_times()
            total += t.user + t.system
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            pass
    return total


def run(app_dir, repo, idle_seconds=None, settle_seconds=None):
    det = CONFIG["detectors"]
    idle = idle_seconds if idle_seconds is not None else det["idle_seconds"]
    settle = settle_seconds if settle_seconds is not None else det["settle_seconds"]
    httpd, url = serve(app_dir, repo)
    report = {"url_path": f"/{repo}/", "errors": [], "hosts": [], "requests_total": 0,
              "requests_idle": 0, "websockets": [], "webrtc": 0, "cpu_cores": None,
              "overflow_320": None, "load_error": None}
    hosts, phase = set(), {"idle": False}

    def on_request(req):
        report["requests_total"] += 1
        if phase["idle"]:
            report["requests_idle"] += 1
        host = urlparse(req.url).hostname
        if host and host not in LOCAL_HOSTS and urlparse(req.url).scheme in ("http", "https", "ws", "wss"):
            hosts.add(host.lower())

    launch = {"headless": True}
    if os.environ.get("CHROME_PATH"):
        launch["executable_path"] = os.environ["CHROME_PATH"]
    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(**launch)
            ctx = browser.new_context(viewport={"width": 390, "height": 844}, is_mobile=True, has_touch=True)
            ctx.add_init_script(INIT_SCRIPT)
            ctx.on("request", on_request)
            page = ctx.new_page()
            page.on("pageerror", lambda e: report["errors"].append(str(e)[:300]) if not phase["idle"] else None)
            page.on("websocket", lambda ws: (report["websockets"].append(ws.url[:200]),
                                             hosts.add((urlparse(ws.url).hostname or "").lower())))
            try:
                page.goto(url, wait_until="load", timeout=30000)
            except Exception as e:  # a page that won't load is reported, not crashed on
                report["load_error"] = str(e)[:300]
            page.wait_for_timeout(settle * 1000)

            phase["idle"] = True
            c0, t0 = chrome_cpu_seconds(), time.monotonic()
            page.wait_for_timeout(idle * 1000)
            c1, t1 = chrome_cpu_seconds(), time.monotonic()
            report["cpu_cores"] = round((c1 - c0) / (t1 - t0), 3)
            try:
                report["webrtc"] = page.evaluate("window.__orgci_rtc || 0")
            except Exception:
                pass
            ctx.close()

            narrow = browser.new_context(viewport={"width": 320, "height": 640})
            npage = narrow.new_page()
            try:
                npage.goto(url, wait_until="load", timeout=30000)
                npage.wait_for_timeout(1000)
                report["overflow_320"] = npage.evaluate(
                    "document.documentElement.scrollWidth > document.documentElement.clientWidth + 1")
            except Exception:
                pass
            narrow.close()
            browser.close()
    finally:
        httpd.shutdown()
    hosts.discard("")
    report["hosts"] = sorted(hosts)
    return report


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("app_dir")
    ap.add_argument("repo")
    ap.add_argument("--idle", type=int, default=None)
    a = ap.parse_args()
    print(json.dumps(run(a.app_dir, a.repo, a.idle), indent=2))
