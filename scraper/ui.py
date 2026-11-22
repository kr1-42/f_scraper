"""Local web UI:  python3 -m scraper.ui  ->  http://localhost:8000"""
from __future__ import annotations

import json
import threading
import time
from dataclasses import replace
from concurrent.futures import ThreadPoolExecutor
from datetime import date
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from .base import get_provider
from .cheap import add_stays, cheap_round_trips
from .dates import find_dates
from .config import ORIGINS, PROVIDERS

PAGE = (Path(__file__).parent / "index.html").read_bytes()


PAGE_SIZE = 8
_cache: dict = {}
_cache_lock = threading.Lock()


def _flights(day: date, ret: date, max_price: float | None, ttl: float = 600):
    """cheap_round_trips() with a short-lived cache so paging doesn't redo the flight search."""
    key = (day, ret, max_price)
    with _cache_lock:
        hit = _cache.get(key)
        if hit and time.monotonic() - hit[0] < ttl:
            return hit[1]
    trips = cheap_round_trips(day, ret, max_price=max_price)
    with _cache_lock:
        _cache[key] = (time.monotonic(), trips)
        for k in [k for k, v in _cache.items() if time.monotonic() - v[0] > ttl]:
            del _cache[k]
    return trips


def run_search(depart: date, ret: date, destination: str | None) -> dict:
    jobs = []
    for prov in PROVIDERS:
        for o in ORIGINS:
            jobs.append((prov, o.iata, destination))

    def work(job):
        prov, origin, dest = job
        try:
            trips = get_provider(prov).search_round_trip(origin, dest, depart, ret)
            return [t.to_dict() for t in trips[:30]], None
        except BaseException as e:  # keep one failing provider from killing the page
            return [], f"{prov} {origin}: {e}"

    with ThreadPoolExecutor(len(jobs) or 1) as ex:
        results = list(ex.map(work, jobs))
    trips = sorted((t for r, _ in results for t in r), key=lambda t: t["price"])
    errors = [e for _, e in results if e]
    return {"trips": trips, "errors": errors}


class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        u = urlparse(self.path)
        if u.path == "/":
            return self._send(200, PAGE, "text/html; charset=utf-8")
        if u.path == "/api/search":
            q = {k: v[0] for k, v in parse_qs(u.query).items()}
            try:
                out = run_search(date.fromisoformat(q["depart"]), date.fromisoformat(q["return"]), q.get("destination") or None)
                return self._send(200, json.dumps(out).encode(), "application/json")
            except (KeyError, ValueError):
                return self._send(400, b'{"error":"need depart and return as YYYY-MM-DD"}', "application/json")
        if u.path == "/api/cheap":
            q = {k: v[0] for k, v in parse_qs(u.query).items()}
            try:
                day, ret = date.fromisoformat(q["day"]), date.fromisoformat(q["return"])
                max_price = float(q["max"]) if q.get("max") else None
                max_stay = float(q["max_stay"]) if q.get("max_stay") else None
                offset, limit = max(int(q.get("offset") or 0), 0), min(max(int(q.get("limit") or PAGE_SIZE), 1), 50)
            except (KeyError, ValueError):
                return self._send(400, b'{"error":"need day and return as YYYY-MM-DD; numbers must be numbers"}', "application/json")
            try:
                # Flights are found once (cached); each page then only looks up stays for its own slice.
                all_trips = _flights(day, ret, max_price)
                page, errors = [replace(t, stays=[]) for t in all_trips[offset:offset + limit]], []
                if q.get("stays") and page:
                    page, errors = add_stays(page, max_stay=max_stay, top=len(page))
                out = {"trips": [t.to_dict() for t in page], "errors": errors,
                       "next_offset": offset + limit, "has_more": offset + limit < len(all_trips), "total": len(all_trips)}
            except BaseException as e:
                out = {"trips": [], "errors": [str(e)]}
            return self._send(200, json.dumps(out).encode(), "application/json")
        if u.path == "/api/dates":
            q = {k: v[0] for k, v in parse_qs(u.query).items()}
            try:
                first, last = date.fromisoformat(q["from"]), date.fromisoformat(q["to"])
                lo, hi = int(q.get("min_nights") or 2), int(q.get("max_nights") or q.get("min_nights") or 5)
                max_price = float(q["max"]) if q.get("max") else None
                max_stay = float(q["max_stay"]) if q.get("max_stay") else None
                dest = q["destination"].strip()
                if not dest or hi < lo or last < first:
                    raise ValueError
            except (KeyError, ValueError):
                return self._send(400, b'{"error":"need destination, a valid from/to window and nights (min <= max)"}', "application/json")
            try:
                trips, errors = find_dates(dest, first, last, lo, hi, max_price=max_price)
                if q.get("stays"):
                    trips, e2 = add_stays(trips, max_stay=max_stay)
                    errors += e2
                out = {"trips": [t.to_dict() for t in trips], "errors": errors}
            except BaseException as e:
                out = {"trips": [], "errors": [str(e)]}
            return self._send(200, json.dumps(out).encode(), "application/json")
        self._send(404, b"not found", "text/plain")

    def _send(self, code, body, ctype):
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *a):
        pass


if __name__ == "__main__":
    print("http://localhost:8000")
    ThreadingHTTPServer(("127.0.0.1", 8000), Handler).serve_forever()
