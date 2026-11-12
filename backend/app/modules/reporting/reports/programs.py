"""Program and marketing reports (phase 12 chip C): group rosters (RPT-27), group waitlists (RPT-28) and email
campaign history (RPT-29, over the counters and messages `engagement` records; provider events are Phase 13's)."""

from typing import Literal
from uuid import UUID

from pydantic import Field
from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from app.modules.reporting import views as v
from app.modules.reporting.registry import Col, Params, RangeParams, ReportSpec, Scope, _between, _key, _loc

PROGRAM, MARKETING = "reporting.program.run", "reporting.marketing.run"


class GroupParams(Params):
    program_group_ids: list[UUID] | None = Field(None, description="Groups, each with its sub-groups")


# --- RPT-27 group roster -------------------------------------------------------------------------------------


class RosterParams(GroupParams):
    include_inactive: bool = Field(False, description="Include completed and archived groups")


def _roster(session: Session, p: RosterParams, scope: Scope) -> dict:
    r = v.group_roster.c
    where = [] if p.include_inactive else [r.group_status == "active"]
    if p.program_group_ids:
        where.append(or_(r.program_group_id.in_(p.program_group_ids), r.parent_group_id.in_(p.program_group_ids)))
    details = [dict(row._mapping) for row in session.execute(_loc(
        select(r.program_group_id, r.group_name, r.parent_group_name, r.last_name, r.first_name, r.email, r.phone,
               r.enrolled_on, r.channel, r.fee_minor, r.paid_minor)
        .where(*where).order_by(r.group_name, r.program_group_id, r.last_name, r.first_name, r.enrollment_id),
        v.group_roster, scope,
    ))]  # fmt: skip
    groups: dict[str, dict] = {}
    for row in details:
        row["group_key"] = _key(row.pop("program_group_id"))
        row["balance_minor"] = max(int(row["fee_minor"]) - int(row["paid_minor"]), 0)
        group = groups.setdefault(row["group_key"], {
            "group_key": row["group_key"], "group_name": row["group_name"], "parent_group_name": row["parent_group_name"],
            "registrant_count": 0, "fee_minor": 0, "paid_minor": 0, "balance_minor": 0,
        })  # fmt: skip
        group["registrant_count"] += 1
        for k in ("fee_minor", "paid_minor", "balance_minor"):
            group[k] += int(row[k])
    rows = list(groups.values())
    keys = ("registrant_count", "fee_minor", "paid_minor", "balance_minor")
    return {"rows": rows, "totals": {k: sum(g[k] for g in rows) for k in keys}, "details": details}


# --- RPT-28 group waitlists ----------------------------------------------------------------------------------


def _waitlists(session: Session, p: GroupParams, scope: Scope) -> dict:
    w = v.group_waitlist.c
    where = [w.program_group_id.in_(p.program_group_ids)] if p.program_group_ids else []
    rows = [dict(row._mapping) for row in session.execute(_loc(
        select(w.group_name, w.parent_group_name, w.position, w.client_name, w.status, w.mode, w.queued_on)
        .where(*where).order_by(w.group_name, w.program_group_id, w.position), v.group_waitlist, scope,
    ))]  # fmt: skip
    offered = sum(1 for r in rows if r["status"] == "offered")
    return {"rows": rows, "totals": {"entry_count": len(rows), "offered_count": offered}, "details": None}


# --- RPT-29 email campaign history ---------------------------------------------------------------------------

_COUNTS = ("attempted_count", "duplicate_count", "invalid_count", "unverified_count", "unsubscribed_skip_count",
           "suppressed_count", "sent_count", "delivered_count", "opened_count", "clicked_count", "bounced_count",
           "complaint_count", "unsubscribed_count")  # fmt: skip


class CampaignParams(RangeParams):
    channel: Literal["email", "push"] | None = None
    subject_contains: str | None = Field(None, max_length=200, description="Part of the subject or campaign name")


def _campaigns(session: Session, p: CampaignParams, scope: Scope) -> dict:
    c, m = v.campaign.c, v.campaign_message.c
    where = [_between(c.sent_on, p, scope)]
    if p.channel:
        where.append(c.channel == p.channel)
    if p.subject_contains:
        pattern = "%" + p.subject_contains.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_") + "%"
        where.append(or_(c.subject.ilike(pattern), c.name.ilike(pattern)))
    rows = [dict(r._mapping) for r in session.execute(_loc(
        select(c.campaign_id, c.sent_on, c.name, c.subject, c.channel, c.sender_name, c.status, *(c[k] for k in _COUNTS))
        .where(*where).order_by(c.sent_on.desc(), c.campaign_id), v.campaign, scope,
    ))]  # fmt: skip
    ids = []
    for row in rows:
        ids.append(row.pop("campaign_id"))
        row["group_key"] = _key(ids[-1])
    details = []
    if ids:
        for r in session.execute(_loc(
            select(m.campaign_id, m.client_name, m.to_address, m.status, m.skip_reason)
            .where(m.campaign_id.in_(ids)).order_by(m.campaign_id, m.client_name, m.message_id),
            v.campaign_message, scope,
        )):  # fmt: skip
            details.append({"group_key": _key(r.campaign_id), "client_name": r.client_name, "to_address": r.to_address,
                            "status": r.status, "skip_reason": r.skip_reason})  # fmt: skip
    totals = {"campaign_count": len(rows)} | {k: sum(int(r[k]) for r in rows) for k in _COUNTS}
    return {"rows": rows, "totals": totals, "details": details}


# --- the specs -----------------------------------------------------------------------------------------------

_MONEY = (Col("fee_minor", "Fee", "money"), Col("paid_minor", "Paid", "money"), Col("balance_minor", "Balance", "money"))
_COUNT_COLS = (Col("attempted_count", "Clients attempted", "count"), Col("duplicate_count", "Duplicates", "count"),
               Col("invalid_count", "Invalid", "count"), Col("unverified_count", "Unverified", "count"),
               Col("unsubscribed_skip_count", "Unsubscribed (skipped)", "count"),
               Col("suppressed_count", "Suppressed", "count"), Col("sent_count", "Sent", "count"),
               Col("delivered_count", "Delivered", "count"), Col("opened_count", "Opened", "count"),
               Col("clicked_count", "Clicked", "count"), Col("bounced_count", "Bounced", "count"),
               Col("complaint_count", "Spam reports", "count"), Col("unsubscribed_count", "Unsubscribed", "count"))

SPECS = (
    ReportSpec(
        "group_roster", "Group roster",
        "Registrants of each group and its sub-groups, with what their fee has been paid and what is still owed.",
        "programs", PROGRAM, "none", RosterParams,
        (Col("group_name", "Group"), Col("parent_group_name", "Parent group"),
         Col("registrant_count", "Registrants", "count"), *_MONEY),
        (Col("registrant_count", "Registrants", "count"), *_MONEY),
        _roster,
        (Col("last_name", "Last name"), Col("first_name", "First name"), Col("email", "Email"), Col("phone", "Phone"),
         Col("enrolled_on", "Registered", "date"), Col("channel", "Channel"), *_MONEY),
        ("RPT-27",),
    ),
    ReportSpec(
        "group_waitlists", "Group waitlists",
        "Everyone waiting for a place in an active group or sub-group, in queue order.",
        "programs", PROGRAM, "none", GroupParams,
        (Col("group_name", "Group"), Col("parent_group_name", "Parent group"), Col("position", "Position", "count"),
         Col("client_name", "Client"), Col("status", "Status"), Col("mode", "Waitlist mode"),
         Col("queued_on", "Joined", "date")),
        (Col("entry_count", "Waiting", "count"), Col("offered_count", "Offered a place", "count")),
        _waitlists, None, ("RPT-28",),
    ),
    ReportSpec(
        "campaign_history", "Campaign history",
        "Campaigns sent in the period with their audience and delivery counts, and each recipient's latest status. "
        "Opens, clicks and bounces appear once the email provider reports them.",
        "marketing", MARKETING, "sent_date", CampaignParams,
        (Col("sent_on", "Sent", "date"), Col("name", "Campaign"), Col("subject", "Subject"), Col("channel", "Channel"),
         Col("sender_name", "From"), Col("status", "Status"), *_COUNT_COLS),
        (Col("campaign_count", "Campaigns", "count"), *_COUNT_COLS),
        _campaigns,
        (Col("client_name", "Client"), Col("to_address", "Address"), Col("status", "Status"),
         Col("skip_reason", "Skipped because")),
        ("RPT-29",),
    ),
)  # fmt: skip
