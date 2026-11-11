"""Demo documents: a liability waiver and a privacy consent template, a signed waiver for Morgan Member and a
pending one for Riley Reyes, and the waiver bound as the Downtown program default."""

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.modules.clients.models import Client
from app.modules.documents import service
from app.modules.documents.models import DocumentTemplate
from app.modules.platform.models import Location

WAIVER = (
    "<h2>Assumption of risk</h2><p>I, {{client.full_name}}, understand that sport and fitness activities at "
    "{{location.name}} carry a risk of injury. I take part voluntarily and accept that risk.</p>"
    "<h3>Medical</h3><p>I confirm I am fit to take part and will tell staff about any condition that matters.</p>"
    "<h3>Release</h3><p>I release {{organization.name}} and its staff from claims arising from ordinary "
    "participation, except where the law does not allow it.</p>"
)
CONSENT = (
    "<p>{{organization.name}} keeps your contact details, bookings and payments to run your membership. "
    "We never sell them. You can ask for a copy or for erasure at the front desk.</p>"
)


def seed(session: Session) -> None:
    if session.scalar(select(DocumentTemplate.id).limit(1)):
        return  # already seeded
    actor = session.info["actor"]
    waiver = service.create_template(session, actor, {"name": "Liability waiver", "is_waiver": True,
                                                      "signature_validity_days": 365})  # fmt: skip
    service.save_draft(session, actor, waiver["id"], {"body_html": WAIVER, "acceptance_text": "I have read this waiver "
                       "and agree to its terms.", "signature_blocks": [{"role": "client", "label": "Participant"},
                       {"role": "guardian", "label": "Parent or guardian"}]})  # fmt: skip
    service.publish_template(session, actor, waiver["id"])
    consent = service.create_template(session, actor, {"name": "Privacy notice", "kind": "consent"})
    service.save_draft(session, actor, consent["id"], {"body_html": CONSENT, "acceptance_text": "I agree."})
    service.publish_template(session, actor, consent["id"])
    service.upsert_binding(session, actor, {"scope_type": "program_default", "template_id": waiver["id"],
                                            "frequency": "first_purchase"})  # fmt: skip
    downtown = session.scalar(select(Location).where(Location.slug == "downtown"))
    people = {
        c.first_name: c for c in session.scalars(select(Client).where(Client.first_name.in_(["Morgan", "Riley"])))
    }
    template = session.get(DocumentTemplate, waiver["id"])
    signed = service.issue(session, client=people["Morgan"], location_id=downtown.id, template=template,
                           method="drawn_signature", origin="manual")  # fmt: skip
    service.record_decisions(
        session, signed, signed.content_sha256,
        [{"decision": "accepted", "signer_role": "client", "signer_name": "Morgan Member", "method": "typed_name",
          "typed_signature": "Morgan Member"}],
        meta={"ip": "127.0.0.1", "user_agent": "Demo seed"}, uploaded_by=("system", None), staff=True,
    )  # fmt: skip
    service.issue(session, client=people["Riley"], location_id=downtown.id, template=template, method="checkbox",
                  origin="manual")  # fmt: skip
