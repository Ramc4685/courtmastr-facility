"""The access decision and the app-card QR scheme, as pure functions."""

from datetime import UTC, datetime, timedelta
from uuid import uuid4

from app.modules.access.domain import cards
from app.modules.access.domain.evaluate import Facts, evaluate

AT = datetime(2030, 5, 1, 12, 0, tzinfo=UTC)


def test_active_member_is_granted_and_counted():
    d = evaluate(Facts(client_active=True, membership_reason=None, membership_contract_id=uuid4()))
    assert (d.would_grant, d.denial_reason, d.alerts, d.counts_visit) == (True, None, [], True)


def test_no_membership_is_granted_uncounted():
    d = evaluate(Facts(client_active=True, membership_reason="none"))
    assert d.would_grant and not d.counts_visit and d.alerts == []


def test_disabled_client_is_denied_first():
    d = evaluate(Facts(client_active=False, membership_reason="frozen", balance_due_minor=100))
    assert d.denial_reason == "client_disabled"
    assert d.alerts == ["client_disabled", "access_denied", "membership_frozen", "balance_due"]


def test_frozen_suspended_cancelled_depleted_deny_and_others_alert():
    for reason, code in (("frozen", "membership_frozen"), ("suspended", "membership_suspended")):
        d = evaluate(Facts(client_active=True, membership_reason=reason, membership_contract_id=uuid4()))
        assert d.denial_reason == reason and "access_denied" in d.alerts and code in d.alerts
    assert evaluate(Facts(client_active=True, membership_reason="cancelled")).denial_reason == "cancelled"
    d = evaluate(Facts(client_active=True, membership_reason="daily_limit_reached", membership_contract_id=uuid4()))
    assert d.would_grant and "over_daily_limit" in d.alerts and not d.counts_visit
    d = evaluate(Facts(client_active=True, membership_reason="depleted", membership_contract_id=uuid4()))
    assert d.denial_reason == "depleted" and "visits_depleted" in d.alerts  # owner question 12


def test_waiver_balance_and_staff_note_alerts_in_priority_order():
    d = evaluate(Facts(True, None, has_waiver=False, balance_due_minor=1, has_staff_alert=True))
    assert d.would_grant and d.alerts == ["balance_due", "waiver_unsigned", "staff_note"]


def test_qr_codes_rotate_and_verify_for_two_steps_only():
    credential_id, secret = uuid4(), b"s" * 32
    seed = cards.seed(credential_id, secret)
    text = cards.qr_text(seed, AT)
    parsed = cards.parse(text)
    assert parsed is not None and parsed[0] == credential_id
    _, step, mac = parsed
    assert cards.verify(secret, credential_id, step, mac, AT)
    assert cards.verify(secret, credential_id, step, mac, AT + timedelta(seconds=cards.STEP_SECONDS))
    assert not cards.verify(secret, credential_id, step, mac, AT + timedelta(seconds=3 * cards.STEP_SECONDS))
    assert not cards.verify(b"x" * 32, credential_id, step, mac, AT)
    assert not cards.verify(secret, uuid4(), step, mac, AT)
    assert cards.qr_text(seed, AT + timedelta(seconds=cards.STEP_SECONDS)) != text


def test_parse_rejects_anything_else():
    for text in ("", "12345", "fhq.not-a-uuid.1.x", "fhq.a.b", f"fhq.{uuid4()}.x.y", f"zzz.{uuid4()}.1.x"):
        assert cards.parse(text) is None


def test_a_booked_entry_ignores_membership_rules_but_not_the_person():
    from app.modules.access.domain.evaluate import for_booking

    for reason in ("frozen", "suspended", "depleted", "cancelled"):
        d = for_booking(evaluate(Facts(client_active=True, membership_reason=reason, membership_contract_id=uuid4())))
        assert d.would_grant and d.denial_reason is None and "access_denied" not in d.alerts and not d.counts_visit
    outside = Facts(client_active=True, membership_reason=None, membership_contract_id=uuid4(), schedule_open=False)
    assert for_booking(evaluate(outside)).would_grant
    assert for_booking(evaluate(Facts(client_active=False, membership_reason=None))).denial_reason == "client_disabled"
    banned = Facts(client_active=True, membership_reason=None, access_mode="always_deny")
    assert for_booking(evaluate(banned)).denial_reason == "access_mode_deny"
