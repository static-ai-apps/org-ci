"""The app description: one JSON-LD block of schema.org terms in index.html (SPEC.md §10).
An app is listed in the library only if this passes.

check(html, repo) -> (blocks, warns, cleaned)
  cleaned is the description reduced to the allowed terms, or None if there's no valid block.
"""

import json
import re

from common import CONFIG, ORG

LD_RE = re.compile(r"<script\b[^>]*\btype\s*=\s*[\"']application/ld\+json[\"'][^>]*>(.*?)</script\s*>", re.I | re.S)
CONTEXTS = {"https://schema.org", "https://schema.org/", "http://schema.org", "http://schema.org/"}
LANG_RE = re.compile(r"^[A-Za-z]{2,3}(-[A-Za-z0-9]{2,8})*$")
CURRENCY_RE = re.compile(r"^[A-Z]{3}$")

# Terms that claim popularity or endorsement. Never allowed: they'd be self-reported.
FORBIDDEN = {"aggregateRating", "review", "reviews", "interactionStatistic", "award", "awards"}


def app_url(repo):
    return f"https://{ORG}.github.io/{repo}/"


def _text(limit):
    def check(v, repo):
        if not isinstance(v, str) or not v.strip():
            return "must be non-empty text"
        if len(v) > limit:
            return f"is {len(v)} characters; the limit is {limit}"
    return check


def _texts(max_items, limit):
    """Text, or a list of text."""
    def check(v, repo):
        items = v if isinstance(v, list) else [v]
        if not items or not all(isinstance(i, str) and i.strip() for i in items):
            return "must be text or a list of text"
        if len(items) > max_items:
            return f"has {len(items)} items; the limit is {max_items}"
        long = [i for i in items if len(i) > limit]
        if long:
            return f"has an item of {len(long[0])} characters; the limit is {limit}"
    return check


def _url(v, repo):
    if v != app_url(repo):
        return f"must be exactly {app_url(repo)}"


def _image(v, repo):
    if not isinstance(v, str) or not v.startswith(app_url(repo)):
        return f"must be a URL under {app_url(repo)}, such as {app_url(repo)}icon.png"


def _free(v, repo):
    if v is not True:
        return "must be true: every app here is free"


def _language(v, repo):
    items = v if isinstance(v, list) else [v]
    if not items or len(items) > 10 or not all(isinstance(i, str) and LANG_RE.match(i) for i in items):
        return "must be a language code such as \"en\" or \"pt-BR\", or a list of up to 10"


def _audience(v, repo):
    if not isinstance(v, dict) or v.get("@type") != "Audience" or set(v) - {"@type", "audienceType"}:
        return 'must be {"@type": "Audience", "audienceType": "…"}'
    return _text(120)(v.get("audienceType"), repo)


def _offers(v, repo):
    if not isinstance(v, dict) or v.get("@type") != "Offer" or set(v) - {"@type", "price", "priceCurrency"}:
        return 'must be {"@type": "Offer", "price": "0", "priceCurrency": "USD"}'
    if str(v.get("price")) not in ("0", "0.0", "0.00"):
        return "price must be 0"
    if not isinstance(v.get("priceCurrency"), str) or not CURRENCY_RE.match(v["priceCurrency"]):
        return "priceCurrency must be a three-letter currency code"


def _is_part_of(v, repo):
    want = {"@type": "WebSite", "name": CONFIG["site_name"], "url": f"https://{ORG}.github.io/"}
    if v != want:
        return f"must be exactly {json.dumps(want)}"


# The fixed vocabulary: term -> (required, check)
TERMS = {
    "name": (True, _text(40)),
    "disambiguatingDescription": (True, _text(100)),
    "description": (True, _text(300)),
    "url": (True, _url),
    "applicationCategory": (False, _text(40)),
    "applicationSubCategory": (False, _text(40)),
    "featureList": (False, _texts(10, 100)),
    "keywords": (False, _texts(8, 40)),
    "audience": (False, _audience),
    "inLanguage": (False, _language),
    "operatingSystem": (False, _text(60)),
    "browserRequirements": (False, _text(200)),
    "accessibilityFeature": (False, _texts(10, 60)),
    "isAccessibleForFree": (False, _free),
    "offers": (False, _offers),
    "image": (False, _image),
    "isPartOf": (False, _is_part_of),
}


def check(html, repo):
    blocks, warns = [], []
    found = LD_RE.findall(html)
    if not found:
        warns.append("`index.html` has no JSON-LD description, so the app won't be listed in the library (SPEC.md §10)")
        return blocks, warns, None
    if len(found) > 1:
        blocks.append(f"`index.html` has {len(found)} JSON-LD blocks; it may have one (SPEC.md §10)")
        return blocks, warns, None
    try:
        data = json.loads(found[0])
    except ValueError as e:
        blocks.append(f"the JSON-LD block isn't valid JSON: {e}")
        return blocks, warns, None
    if not isinstance(data, dict):
        blocks.append("the JSON-LD block must be a single object")
        return blocks, warns, None
    if data.get("@context") not in CONTEXTS:
        blocks.append('JSON-LD `@context` must be "https://schema.org"')
    if data.get("@type") != "WebApplication":
        blocks.append('JSON-LD `@type` must be "WebApplication"')

    for term in sorted(FORBIDDEN & set(data)):
        blocks.append(f"JSON-LD `{term}` isn't allowed: apps don't describe their own popularity or reviews")
    unknown = sorted(set(data) - set(TERMS) - FORBIDDEN - {"@context", "@type"})
    if unknown:
        warns.append(f"JSON-LD terms outside SPEC.md §10 are ignored: {', '.join(unknown)}")

    for term, (required, fn) in TERMS.items():
        if term not in data:
            if required:
                blocks.append(f"JSON-LD is missing `{term}`")
            continue
        problem = fn(data[term], repo)
        if problem:
            blocks.append(f"JSON-LD `{term}` {problem}")


    if blocks:
        return blocks, warns, None
    cleaned = {"@type": "WebApplication", **{t: data[t] for t in TERMS if t in data}}
    return blocks, warns, cleaned
