"""Front-desk load test against a running lane API (`make perf`; docs/ops/performance-budget.md).

A closed model: N virtual staff (threads), each with its own signed-in cookie session and CSRF token, pick
weighted scenarios back to back with a short think time, for a fixed duration. Every HTTP call is timed and
recorded under a label; the run writes a JSON result (`perf/results/`) and prints a table.

`--check` compares a result's p95 per label with `perf/budget.json` and exits non-zero when one exceeds its
budget by more than the margin (`make perf-check`). Needs only httpx (an API dependency already).
"""

import argparse
import json
import os
import random
import sys
import threading
import time
import uuid
from datetime import UTC, datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

import httpx

HERE = Path(__file__).resolve().parent
PASSWORD = "courtside-demo-2026"  # the documented dev-only demo password (docs/dev/demo-accounts.md)
STAFF = "admin@courtside-demo.example.com"
ZONE = ZoneInfo("America/Chicago")  # Courtside Downtown
# A front-desk day: mostly reads (calendar, client look-ups, check-ins), a steady trickle of bookings and sales.
WEIGHTS = {
    "calendar_day": 20, "calendar_week": 6, "availability": 10, "booking": 8, "client_search": 14,
    "client_profile": 12, "check_in": 12, "pos_sale": 6, "invoices": 6, "payment": 3, "report": 1, "sign_in": 2,
}  # fmt: skip
EXPECTED_CONFLICTS = {"booking.create": {409}, "check_in.create": {409, 422}}  # a busy court, a denied entry


class Recorder:
    def __init__(self) -> None:
        self.lock = threading.Lock()
        self.samples: dict[str, list[float]] = {}
        self.errors: dict[str, dict[str, int]] = {}
        self.conflicts: dict[str, int] = {}

    def add(self, label: str, ms: float, status: int) -> None:
        with self.lock:
            self.samples.setdefault(label, []).append(ms)
            if status in EXPECTED_CONFLICTS.get(label, ()):
                self.conflicts[label] = self.conflicts.get(label, 0) + 1
            elif status >= 400 or status == 0:
                bucket = self.errors.setdefault(label, {})
                bucket[str(status)] = bucket.get(str(status), 0) + 1


class Failed(Exception):
    pass


def new_client(base: str) -> httpx.Client:
    return httpx.Client(
        base_url=base, timeout=30, headers={"x-tenant-slug": "courtside-demo", "accept": "application/json"}
    )


def call(client: httpx.Client, rec: Recorder, label: str, method: str, path: str, **kw) -> httpx.Response | None:
    if method != "GET":
        kw.setdefault("headers", {})["idempotency-key"] = str(uuid.uuid4())
    started = time.perf_counter()
    try:
        response = client.request(method, path, **kw)
    except httpx.HTTPError:
        rec.add(label, (time.perf_counter() - started) * 1000, 0)
        return None
    rec.add(label, (time.perf_counter() - started) * 1000, response.status_code)
    return response if response.is_success else None


def sign_in(client: httpx.Client, rec: Recorder) -> None:
    pre = call(client, rec, "auth.pre_session", "GET", "/auth/pre-session")
    if pre is None:
        raise Failed("pre-session")
    body = {"email": STAFF, "password": PASSWORD, "audience": "staff"}
    out = call(client, rec, "auth.sign_in", "POST", "/auth/sign-in", json=body,
               headers={"x-csrf-token": pre.json()["csrf_token"]})  # fmt: skip
    if out is None:
        raise Failed("sign-in")
    client.headers["x-csrf-token"] = out.json()["csrf_token"]


def day_span(offset: int, days: int = 1) -> dict:
    start = datetime.combine(datetime.now(ZONE).date() + timedelta(days=offset), datetime.min.time(), ZONE)
    return {"from": start.astimezone(UTC).isoformat(), "to": (start + timedelta(days=days)).astimezone(UTC).isoformat()}


class Fixture:
    """Ids the scenarios need, read once through the API as the admin."""

    def __init__(self, base: str, rec: Recorder) -> None:
        c = new_client(base)
        sign_in(c, rec)
        get = lambda path, **params: c.get(path, params=params).raise_for_status().json()  # noqa: E731
        self.location = next(x["id"] for x in get("/locations")["data"] if x["name"] == "Courtside Downtown")
        rows = get("/resources", location_id=self.location, limit=100)["data"]
        self.courts = [r["id"] for r in rows if r["name"].startswith("Perf Court")]
        if not self.courts:
            sys.exit("No perf courts: run `make perf-seed` first.")
        self.open_play = next(
            t["id"] for t in get("/reservation-types", location_id=self.location, limit=100)["data"]
            if t["name"] == "Open Play"
        )  # fmt: skip
        self.cash = next(t["id"] for t in get("/tender-types") if t["kind"] == "cash")
        self.water = get("/products", q="Water")["data"][0]["id"]
        self.clients = [x["id"] for x in get("/clients", q="perf.example.com", limit=200)["data"]]
        self.invoices = [
            (x["id"], x["bill_to_client_id"], x["location_id"])
            for x in get("/invoices", status="open", limit=200)["data"]
            if x["balance_minor"] > 1000
        ]
        self.registers = [r["id"] for r in get("/registers", limit=100)["data"] if r["name"].startswith("Perf till")]
        for register in self.registers:  # a fresh drawer per till; abandon a cart an earlier run left behind
            state = get(f"/registers/{register}/session")
            if not state.get("drawer_session"):
                c.post(f"/registers/{register}/drawer-sessions", json={"opening_float_minor": 10000},
                       headers={"idempotency-key": str(uuid.uuid4())}).raise_for_status()  # fmt: skip
            if draft := state.get("draft_sale"):
                c.post(f"/pos-sales/{draft['id']}/abandon", headers={"idempotency-key": str(uuid.uuid4())})
        self.search_terms = ["Adams1", "Chen2", "Garcia", "perf-04", "Lopez3", "Khan", "P-0012", "Hughes45", "Baker"]
        c.post("/auth/sign-out")
        c.close()


def run_scenario(name: str, c: httpx.Client, rec: Recorder, fx: Fixture, register: str | None, base: str) -> None:
    rnd = random.Random()
    if name == "calendar_day":
        call(
            c,
            rec,
            "calendar.day",
            "GET",
            "/calendar",
            params={"location_id": fx.location, **day_span(rnd.randint(0, 29))},
        )
    elif name == "calendar_week":
        call(
            c,
            rec,
            "calendar.week",
            "GET",
            "/calendar",
            params={"location_id": fx.location, **day_span(rnd.randint(0, 23), 7)},
        )
    elif name == "availability":
        params = {"location_id": fx.location, "min_free_min": 60, **day_span(rnd.randint(0, 29))}
        call(c, rec, "availability", "GET", "/availability", params=params)
    elif name == "booking":
        day = datetime.now(ZONE).date() + timedelta(days=rnd.randint(1, 29))
        starts = datetime.combine(day, datetime.min.time(), ZONE) + timedelta(hours=15, minutes=30 * rnd.randint(0, 13))
        body = {
            "location_id": fx.location, "kind": "session", "reservation_type_id": fx.open_play,
            "resources": [{"resource_id": rnd.choice(fx.courts)}], "starts_at": starts.isoformat(),
            "ends_at": (starts + timedelta(minutes=30)).isoformat(), "on_conflict": "abort", "title": "Perf booking",
        }  # fmt: skip
        created = call(c, rec, "booking.create", "POST", "/bookings", json=body)
        if created is not None and (booking := created.json().get("booking")):
            call(c, rec, "booking.cancel", "POST", f"/bookings/{booking['id']}/cancel",
                 json={"version": booking["version"], "reason": "staff"})  # fmt: skip
    elif name == "client_search":
        call(c, rec, "clients.search", "GET", "/clients", params={"q": rnd.choice(fx.search_terms), "limit": 25})
    elif name == "client_profile":
        call(c, rec, "clients.get", "GET", f"/clients/{rnd.choice(fx.clients)}")
    elif name == "check_in":
        body = {"channel": "staff_window", "client_id": rnd.choice(fx.clients), "location_id": fx.location}
        call(c, rec, "check_in.create", "POST", "/check-ins", json=body)
    elif name == "pos_sale" and register:
        sale = call(c, rec, "pos.create", "POST", "/pos-sales", json={"register_id": register})
        if sale is None:
            return
        sale_id = sale.json()["id"]
        line = call(
            c, rec, "pos.line", "POST", f"/pos-sales/{sale_id}/lines", json={"product_id": fx.water, "quantity": 1}
        )
        total = line.json()["total_minor"] if line is not None else 0
        tender = {"tender": "payment", "amount_minor": total, "tender_type_id": fx.cash, "cash_received_minor": total}
        if total and call(c, rec, "pos.tender", "POST", f"/pos-sales/{sale_id}/tenders", json=tender) is not None:
            if call(c, rec, "pos.complete", "POST", f"/pos-sales/{sale_id}/complete") is not None:
                return
        c.post(f"/pos-sales/{sale_id}/abandon", headers={"idempotency-key": str(uuid.uuid4())})
    elif name == "invoices":
        call(c, rec, "invoices.list", "GET", "/invoices", params={"status": "open", "limit": 25})
    elif name == "payment":
        invoice_id, client_id, location_id = rnd.choice(fx.invoices)
        call(c, rec, "invoices.get", "GET", f"/invoices/{invoice_id}")
        body = {"client_id": client_id, "invoice_id": invoice_id, "location_id": location_id, "amount_minor": 100,
                "tender_kind": "cash"}  # fmt: skip
        call(c, rec, "payment.take", "POST", "/payments", json=body)
    elif name == "report":
        today = datetime.now(ZONE).date()
        params = {"from_on": (today - timedelta(days=30)).isoformat(), "to_on": today.isoformat()}
        call(c, rec, "report.run", "POST", "/report-runs", json={"report_key": "revenue_summary", "params": params})
    elif name == "sign_in":
        fresh = new_client(base)
        try:
            sign_in(fresh, rec)
            call(fresh, rec, "auth.me", "GET", "/me")
            call(fresh, rec, "auth.sign_out", "POST", "/auth/sign-out")
        except Failed:
            pass
        finally:
            fresh.close()


def worker(index: int, base: str, rec: Recorder, fx: Fixture, deadline: float, think: float) -> None:
    client = new_client(base)
    try:
        sign_in(client, rec)
    except Failed:
        return
    register = fx.registers[index] if index < len(fx.registers) else None  # one till per cashier
    names = list(WEIGHTS)
    weights = [WEIGHTS[n] if (n != "pos_sale" or register) else 0 for n in names]
    while time.monotonic() < deadline:
        run_scenario(random.choices(names, weights)[0], client, rec, fx, register, base)
        time.sleep(random.uniform(0, 2 * think))
    client.close()


def pct(values: list[float], p: float) -> float:
    ordered = sorted(values)
    return ordered[min(len(ordered) - 1, max(0, round(p / 100 * len(ordered) + 0.5) - 1))]


def summarise(rec: Recorder, seconds: float) -> dict:
    out = {}
    for label, values in sorted(rec.samples.items()):
        errors = sum(rec.errors.get(label, {}).values())
        out[label] = {
            "count": len(values), "errors": errors, "error_codes": rec.errors.get(label, {}),
            "conflicts": rec.conflicts.get(label, 0), "rps": round(len(values) / seconds, 2),
            "p50": round(pct(values, 50), 1), "p95": round(pct(values, 95), 1), "p99": round(pct(values, 99), 1),
            "max": round(max(values), 1),
        }  # fmt: skip
    return out


def print_table(result: dict) -> None:
    print(f"\n{'label':<20}{'count':>7}{'err':>5}{'409':>5}{'rps':>7}{'p50':>8}{'p95':>8}{'p99':>8}{'max':>8}")
    for label, s in result["labels"].items():
        print(f"{label:<20}{s['count']:>7}{s['errors']:>5}{s['conflicts']:>5}{s['rps']:>7}"
              f"{s['p50']:>8}{s['p95']:>8}{s['p99']:>8}{s['max']:>8}")  # fmt: skip
    t = result["totals"]
    print(f"\n{t['requests']} requests, {t['rps']} req/s, error rate {t['error_rate_pct']}%, "
          f"load average {result['load_average']}")  # fmt: skip


def check(path: Path, margin: float) -> int:
    budget = json.loads((HERE / "budget.json").read_text())
    result = json.loads(path.read_text())
    failures = []
    for label, target in budget["p95_ms"].items():
        got = result["labels"].get(label)
        if got is None:
            failures.append(f"{label}: no samples")
        elif got["p95"] > target * (1 + margin):
            failures.append(f"{label}: p95 {got['p95']} ms > budget {target} ms + {margin:.0%}")
    if result["totals"]["error_rate_pct"] > budget["error_rate_pct"]:
        failures.append(f"error rate {result['totals']['error_rate_pct']}% > {budget['error_rate_pct']}%")
    print(f"perf-check {path.name}: margin {margin:.0%}")
    print("\n".join(failures) or "every label within budget")
    return 1 if failures else 0


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--base", default=f"http://127.0.0.1:{os.environ.get('FH_API_PORT', '8100')}/api/v1")
    parser.add_argument("--users", type=int, default=10)
    parser.add_argument("--duration", type=int, default=120, help="seconds of load")
    parser.add_argument("--think", type=float, default=0.25, help="mean pause between scenarios, seconds")
    parser.add_argument("--check", type=Path, help="compare this result file with perf/budget.json")
    parser.add_argument("--margin", type=float, default=0.25, help="allowed overshoot of a p95 budget")
    args = parser.parse_args()
    if args.check:
        sys.exit(check(args.check, args.margin))

    rec = Recorder()
    fx = Fixture(args.base, rec)
    rec.__init__()  # the fixture's own calls are not part of the measurement
    loads = [os.getloadavg()]
    deadline = time.monotonic() + args.duration
    threads = [
        threading.Thread(target=worker, args=(i, args.base, rec, fx, deadline, args.think), daemon=True)
        for i in range(args.users)
    ]
    started = time.monotonic()
    for t in threads:
        t.start()
    while any(t.is_alive() for t in threads):
        time.sleep(10)
        loads.append(os.getloadavg())
    seconds = time.monotonic() - started
    labels = summarise(rec, seconds)
    requests = sum(s["count"] for s in labels.values())
    errors = sum(s["errors"] for s in labels.values())
    result = {
        "started_at": datetime.now(UTC).isoformat(timespec="seconds"), "users": args.users,
        "duration_s": round(seconds, 1), "think_s": args.think, "cpu_count": os.cpu_count(),
        "load_average": {"min_1m": round(min(x[0] for x in loads), 2), "max_1m": round(max(x[0] for x in loads), 2),
                         "mean_1m": round(sum(x[0] for x in loads) / len(loads), 2)},
        "totals": {"requests": requests, "errors": errors, "rps": round(requests / seconds, 1),
                   "error_rate_pct": round(100 * errors / max(requests, 1), 2)},
        "labels": labels,
    }  # fmt: skip
    out = HERE / "results" / f"run-{datetime.now(UTC).strftime('%Y%m%d-%H%M%S')}.json"
    out.parent.mkdir(exist_ok=True)
    out.write_text(json.dumps(result, indent=2) + "\n")
    print_table(result)
    print(f"result: {out.relative_to(HERE.parent)}")


if __name__ == "__main__":
    main()
