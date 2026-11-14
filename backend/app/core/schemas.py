"""Base request and response models shared by every context's schemas.py (overview 3.13, 3.14)."""

import html as html_text
import re
from typing import Any

from pydantic import BaseModel, ConfigDict, ValidationInfo, field_validator
from pydantic_core import PydanticCustomError

from app.core.pan import contains_card_number

# Card numbers in request bodies (security-baseline section 3). Every string field on an `In` schema is scanned on
# write, at any depth, unless its name is in NOT_FREE_TEXT below, so a new field is scanned until someone decides
# otherwise (fail closed). tests/test_pan_detector.py walks every request schema in the OpenAPI document and fails on
# a string field that is in neither list, so each new name is classified on purpose. The scan is best effort, not a
# guarantee (app.core.pan); the log scrub is the stricter guard.
#
# Not free text: values that are legitimately long digit runs or are not typed prose, so a scan could only refuse
# real input. Grouped by why.
NOT_FREE_TEXT = frozenset({
    # identifiers, references and codes (member, jersey and product numbers, barcodes, provider and external refs)
    "account_id", "account_reference", "asset_code", "client_id", "code", "coupon_code", "external_id", "external_ref",
    "host_external_user_id", "jersey_number", "member_number", "member_number_prefix",
    "number", "plan_code", "product_code", "realm_id", "sku", "terms_version_id", "pairing_code",
    # access credentials and card scans: a fob or member-card number is a long digit run by design
    "value", "card_payload", "combination", "exit_pin", "staff_pin",
    # secrets and tokens (never prose; never logged either)
    "client_secret", "credential_value", "current_password", "new_password", "owner_password", "password", "passcode",
    "direct_link_token", "guest_token", "match_token", "mfa_token", "method_token", "provider_confirmation_token",
    "provider_payment_token", "push_token", "refresh_token", "token", "visit_token", "content_sha256", "signature_png",
    # machine keys and enumerations kept as plain strings
    "choice_key", "choice_keys", "field_key", "item_key", "key", "local_key", "permission_key", "question_key",
    "report_key", "page_key", "provider", "event_types", "exit_event_types", "trigger_event_type", "type", "scopes", "sort",
    "accepted_card_brands", "app_version", "locale", "currency", "country_code", "time_zone", "default_time_zone",
    "slug", "public_slug", "accent_color", "brand_accent_color", "brand_primary_color", "color",
    # contact details, addresses on the wire and networks: phone numbers are digit runs
    "email", "emails", "contact_email", "allowed_email_domains", "phone", "phone_alt", "phone_home", "phone_mobile",
    "phone_work", "mobile_phone", "contact_phone", "allowed_networks", "staff_ip_allowlist",
    "time_clock_networks", "redirect_domains",
    # URLs and paths
    "group_redirect_urls", "issuer_url", "join_url", "link_url", "redirect_path", "redirect_url", "registration_url",
    "return_url", "social_links", "url", "website_url",
    # times of day and instants sent as text
    "autopay_run_time", "closes_time", "end_time", "ends_at", "ends_time", "membership_renewal_run_time", "opens_time",
    "package_renewal_run_time", "return_time", "send_time", "start_time", "starts_at", "starts_time",
    # numbers sent as decimal strings
    "adjustment_points", "bonus_points", "coach_share_pct", "commission_pct", "default_discount_pct", "deposit_pct", "discount_pct",
    "late_cancel_fee_pct", "min_sportsmanship", "points_default_loss", "points_forfeit_loss", "points_forfeit_win",
    "points_loss", "points_overtime_loss", "points_tie", "points_win", "quantity", "quantity_total", "rate",
    "renewal_discount_pct", "session_commission_pct", "sportsmanship",
    # structured configuration (ids and filters, not prose). `settings` is not here: tenant and connection settings
    # carry staff-typed values.
    "column_mapping", "columns", "conditions", "filters", "formula", "params",
    # client custom values: clients.service scans the text-type fields only, as a fob number is a valid number field
    "custom_values",
})  # fmt: skip
# Free text: scanned. Listed so the OpenAPI walk can tell a reviewed name from a new one; the runtime scans any
# name outside NOT_FREE_TEXT whether or not it is here. CSV imports skip these schemas and check this list in
# imports.service. `*_html` values have their tags stripped before the scan.
FREE_TEXT_FIELDS = frozenset({
    "about_text", "acceptance_text", "additional_description", "additional_income_note", "address", "address_line1",
    "address_line2", "album", "app_name", "away_label", "blurb", "body", "body_html", "body_text", "caption",
    "category", "change_note", "external_reference", "postal_code", "role", "settings", "child_label", "choices", "city", "client_description", "closed_message", "comment",
    "comments", "confirmation", "confirmation_message", "contact_name", "custom_text", "description", "detail",
    "device_label", "directory_name", "display_name", "division_label", "edit_reason", "error", "event_name",
    "event_text", "external_name", "fees_text", "first_name", "heading", "hint", "home_label", "interest",
    "internal_description", "internal_note", "internal_notes", "internal_remarks", "invoice_description",
    "invoice_email_subject", "invoice_footer", "label", "last_name", "last_name_prefix", "medical_notes", "memo",
    "message", "minor_override_reason", "more_info", "name", "name_prefix", "note", "notes", "online_description",
    "organization_name", "payment_reference",
    "override_reason", "owner_first_name", "owner_last_name", "portal_publish_name", "position", "preferred_name",
    "public_name", "public_title", "reason", "receipt_footer", "referral_source", "region", "registrant_comment",
    "relationship_label", "remarks", "removal_remarks", "renewal_description", "renewal_remark", "round_label",
    "rules_text", "series_label", "signer_name", "size_label", "skill_level", "sold_out_memo", "state",
    "statement_email_body", "statement_email_subject", "statement_footer", "subject", "subject_text", "summary",
    "tagline", "team_fee_text", "text", "text_answers", "text_value", "title", "typed_signature", "unit_label",
    "values", "welcome_message", "welcome_text",
})  # fmt: skip
# Bounded and stopping at the next `<`, so a body of unclosed `<` stays linear. A tag longer than 1000 characters
# is left in place: the scan then sees more text, never less. The size cap is each field's own max_length.
_TAG = re.compile(r"<[^<>]{0,1000}>")
CARD_DATA = "card-data-not-allowed"
CARD_DATA_DETAIL = "Card numbers cannot be stored here. Take payments through the payment form."


def _has_card(value: Any, html: bool = False) -> bool:
    if isinstance(value, str):
        if html:  # what a reader sees: tags, stray brackets and entities (&nbsp;) between groups would hide them
            value = html_text.unescape(_TAG.sub(" ", value).replace("<", " ").replace(">", " "))
        return contains_card_number(value)
    if isinstance(value, dict):
        return any(_has_card(v, html) for v in value.values())
    if isinstance(value, (list, tuple, set)):
        return any(_has_card(v, html) for v in value)
    return False


class Out(BaseModel):
    model_config = ConfigDict(from_attributes=True)


class In(BaseModel):
    model_config = ConfigDict(extra="forbid")

    @field_validator("*", mode="after")
    @classmethod
    def refuse_card_data(cls, value: Any, info: ValidationInfo) -> Any:
        # A field-level error, so the location is the full path inside nested models (core.api turns a body with
        # one into a `card-data-not-allowed` problem); the value is never echoed.
        name = info.field_name or ""
        if name not in NOT_FREE_TEXT and _has_card(value, html=name.endswith("_html")):
            raise PydanticCustomError(CARD_DATA, CARD_DATA_DETAIL)
        return value


class PageInfo(BaseModel):
    next_cursor: str | None
    has_more: bool
    total: int | None = None


class Page[T](BaseModel):
    data: list[T]
    page: PageInfo
