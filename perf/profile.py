"""Hot-spot profile (`make perf-profile LABELS="calendar.week clients.search"`): runs chosen load-test requests
in process against the lane database, counts their SQL statements and times them, and prints EXPLAIN ANALYZE
for each request's slowest statement, run inside the tenant (RLS on) so the plan is the one the app gets.

Read-only apart from the booking pair, which creates and cancels one booking.
"""

import os
import sys
import time
import traceback
import uuid
from datetime import UTC, datetime, timedelta
from zoneinfo import ZoneInfo

from fastapi.testclient import TestClient
from sqlalchemy import event

from app.core.db.platform import resolve_tenant
from app.core.db.session import app_engine
from app.main import app

ZONE = ZoneInfo("America/Chicago")
captured: list[tuple[str, object, float]] | None = None


@event.listens_for(app_engine(), "before_cursor_execute")
def _start(conn, cursor, statement, params, context, executemany):
    conn.info.setdefault("t0", []).append(time.perf_counter())


@event.listens_for(app_engine(), "after_cursor_execute")
def _stop(conn, cursor, statement, params, context, executemany):
    elapsed = (time.perf_counter() - conn.info["t0"].pop()) * 1000
    if captured is not None:
        captured.append((statement, params, elapsed))
        if (trace := os.environ.get("PERF_TRACE")) and trace in statement:  # who issues this statement?
            frames = [f for f in traceback.extract_stack() if "/app/" in f.filename and "/core/db/" not in f.filename]
            print("  trace:", " <- ".join(f"{f.filename.split('/app/')[-1]}:{f.lineno}" for f in reversed(frames[-4:])))


def span(offset: int, days: int) -> dict:
    start = datetime.combine(datetime.now(ZONE).date() + timedelta(days=offset), datetime.min.time(), ZONE)
    return {"from": start.astimezone(UTC).isoformat(), "to": (start + timedelta(days=days)).astimezone(UTC).isoformat()}


def main() -> None:
    global captured
    labels = sys.argv[1:] or ["calendar.week", "calendar.day", "clients.search"]
    client = TestClient(app, base_url="http://localhost", headers={"x-tenant-slug": "courtside-demo"})
    pre = client.get("/api/v1/auth/pre-session").json()["csrf_token"]
    out = client.post("/api/v1/auth/sign-in", headers={"x-csrf-token": pre}, json={
        "email": "admin@courtside-demo.example.com", "password": "courtside-demo-2026", "audience": "staff"})  # fmt: skip
    client.headers["x-csrf-token"] = out.json()["csrf_token"]
    get = lambda path, **params: client.get(f"/api/v1{path}", params=params).json()  # noqa: E731
    location = next(x["id"] for x in get("/locations")["data"] if x["name"] == "Courtside Downtown")
    a_client = get("/clients", q="perf.example.com", limit=1)["data"][0]["id"]
    an_invoice = get("/invoices", status="open", limit=1)["data"][0]["id"]
    requests = {
        "calendar.day": ("GET", "/calendar", {"location_id": location, **span(3, 1)}, None),
        "calendar.week": ("GET", "/calendar", {"location_id": location, **span(3, 7)}, None),
        "availability": ("GET", "/availability", {"location_id": location, "min_free_min": 60, **span(3, 1)}, None),
        "clients.search": ("GET", "/clients", {"q": "Garcia", "limit": 25}, None),
        "clients.get": ("GET", f"/clients/{a_client}", {}, None),
        "invoices.list": ("GET", "/invoices", {"status": "open", "limit": 25}, None),
        "invoices.get": ("GET", f"/invoices/{an_invoice}", {}, None),
        "check_in.create": ("POST", "/check-ins", {}, {"channel": "staff_window", "client_id": a_client, "location_id": location}),
        "report.run": ("POST", "/report-runs", {}, {"report_key": "revenue_summary", "params": {
            "from_on": (datetime.now(ZONE).date() - timedelta(days=30)).isoformat(), "to_on": datetime.now(ZONE).date().isoformat()}}),
    }  # fmt: skip
    invoice = get(f"/invoices/{an_invoice}")
    requests["payment.take"] = ("POST", "/payments", {}, {
        "client_id": invoice["bill_to_client_id"], "invoice_id": an_invoice, "location_id": invoice["location_id"],
        "amount_minor": 100, "tender_kind": "cash"})  # fmt: skip
    till = next(r["id"] for r in get("/registers", limit=100)["data"] if r["name"] == "Perf till 10")
    cash = next(t["id"] for t in get("/tender-types") if t["kind"] == "cash")
    water = get("/products", q="Water")["data"][0]["id"]

    def sale_step(step: str):
        """A fresh draft sale on the last perf till, advanced to just before `step`; returns that request."""
        state = get(f"/registers/{till}/session")
        if draft := state["draft_sale"]:  # a paid draft cannot be abandoned: finish it
            for action in ("complete", "abandon"):
                client.post(f"/api/v1/pos-sales/{draft['id']}/{action}", headers={"idempotency-key": str(uuid.uuid4())})
        if not state["drawer_session"]:
            client.post(f"/api/v1/registers/{till}/drawer-sessions", json={"opening_float_minor": 0},
                        headers={"idempotency-key": str(uuid.uuid4())})  # fmt: skip
        if step == "pos.create":
            return ("POST", "/pos-sales", {}, {"register_id": till})

        def post(path, body=None):
            return client.post(f"/api/v1{path}", json=body, headers={"idempotency-key": str(uuid.uuid4())}).json()

        sale = post("/pos-sales", {"register_id": till})["id"]
        if step == "pos.line":
            return ("POST", f"/pos-sales/{sale}/lines", {}, {"product_id": water, "quantity": 1})
        total = post(f"/pos-sales/{sale}/lines", {"product_id": water, "quantity": 1})["total_minor"]
        tender = {"tender": "payment", "amount_minor": total, "tender_type_id": cash, "cash_received_minor": total}
        if step == "pos.tender":
            return ("POST", f"/pos-sales/{sale}/tenders", {}, tender)
        post(f"/pos-sales/{sale}/tenders", tender)
        return ("POST", f"/pos-sales/{sale}/complete", {}, None)

    tenant = resolve_tenant(slug="courtside-demo")
    for label in labels:
        method, path, params, body = requests[label] if label in requests else (None, None, None, None)
        for _ in range(3):  # warm caches; keep the last run
            if label.startswith("pos."):
                method, path, params, body = sale_step(label)
            captured = []
            started = time.perf_counter()
            response = client.request(method, f"/api/v1{path}", params=params, json=body,
                                      headers={"idempotency-key": str(uuid.uuid4())} if method != "GET" else {})  # fmt: skip
            wall = (time.perf_counter() - started) * 1000
            runs, captured = captured, None
        sql_ms = sum(ms for *_, ms in runs)
        statement, sql_params, slowest = max(runs, key=lambda r: r[2])
        print(f"\n## {label}  status {response.status_code}  wall {wall:.1f} ms  {len(runs)} statements  "
              f"{sql_ms:.1f} ms in SQL  slowest {slowest:.1f} ms")  # fmt: skip
        repeated: dict[str, int] = {}
        for text, *_ in runs:
            repeated[text] = repeated.get(text, 0) + 1
        for text, count in sorted(repeated.items(), key=lambda kv: -kv[1])[:3]:
            if count > 1:
                print(f"  repeated x{count}: {' '.join(text.split())[:160]}")
        print("  slowest: " + " ".join(statement.split())[:400])
        if statement.lstrip().upper().startswith(("SELECT", "WITH")):
            with app_engine().connect() as conn:
                conn.exec_driver_sql("SELECT set_config('app.tenant_id', %(t)s, false)", {"t": str(tenant.id)})
                plan = conn.exec_driver_sql(f"EXPLAIN (ANALYZE, BUFFERS) {statement}", sql_params).fetchall()
                conn.exec_driver_sql("SELECT set_config('app.tenant_id', '', false)")
            print("\n".join("    " + row[0] for row in plan))


if __name__ == "__main__":
    main()
