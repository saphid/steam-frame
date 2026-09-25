"""Mac side: search the Steam store and look up each result's Steam Frame rating.

Uses the store's public endpoints (no key, no login):
  api/storesearch                              name search, price in the IP's currency
  saleaction/ajaxgetdeckappcompatibilityreport  per-app Deck/SteamOS/Machine/Frame ratings;
                                               `frame_resolved_category` is the Frame's
Buying happens on the store page, signed in as the user; nothing here buys.
"""
import http.client
import json
import threading
import time
import urllib.parse
import urllib.request
from concurrent.futures import ThreadPoolExecutor

STORE = "https://store.steampowered.com"
UA = {"User-Agent": "FrameControl/1 (+local)"}
COMPAT_TTL = 24 * 3600

_compat = {}  # appid -> (time, category)
_lock = threading.Lock()


def _get(path, params, timeout=10):
    url = f"{STORE}/{path}?{urllib.parse.urlencode(params)}"
    with urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=timeout) as r:
        return json.load(r)


def frame_rating(appid):
    """0 unknown, 1 unsupported, 2 playable, 3 verified (same scale as the client's)."""
    with _lock:
        hit = _compat.get(appid)
    if hit and time.time() - hit[0] < COMPAT_TTL:
        return hit[1]
    try:
        r = _get("saleaction/ajaxgetdeckappcompatibilityreport", {"nAppID": appid, "l": "english"})
        cat = int((r.get("results") or {}).get("frame_resolved_category") or 0)
        cat = cat if 0 <= cat <= 3 else 0
    except (OSError, ValueError, TypeError, AttributeError, http.client.HTTPException):
        return 0  # not cached, so the next search retries
    with _lock:
        _compat[appid] = (time.time(), cat)
    return cat


def search(term, cc):
    """cc: two-letter store country; storesearch returns nothing without one."""
    term = term.strip()[:100]
    if not term:
        return []
    items = _get("api/storesearch", {"term": term, "l": "english", "cc": cc}).get("items") or []
    apps = [i for i in items if i.get("type") == "app" and str(i.get("id", "")).isdigit()]
    with ThreadPoolExecutor(8) as pool:
        ratings = list(pool.map(lambda i: frame_rating(int(i["id"])), apps))
    return [{"id": int(i["id"]), "name": i.get("name", ""), "price": i.get("price"),
             "image": i.get("tiny_image"), "metascore": i.get("metascore") or None, "frame": f}
            for i, f in zip(apps, ratings)]
