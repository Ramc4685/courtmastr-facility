"""Pure rules for the member-app configuration (APP-01, APP-04, APP-05, APP-18): what a theme, a home layout,
schedule flags and feature switches may hold. Each returns the cleaned value or raises Invalid(pointer, message).
"""

import re

# APP-05 tile catalogue. The app keeps the same list in mobile/src/lib/tiles.tsx; add a type in both (one line each).
TILE_TYPES = (
    "book",
    "card",
    "memberships",
    "invoices",
    "notifications",
    "facility",
)
TILE_STYLES = ("large", "small")
MAX_TILES = 12
MAX_CAPTION = 40
FEATURES = ("booking", "purchases", "membership_card", "wallet_pass")
DEFAULT_SCHEDULE = {"shows_spots_left": True, "shows_full_sessions": True, "days_ahead": None}
_HEX = re.compile(r"^#[0-9A-Fa-f]{6}$")


class Invalid(ValueError):
    def __init__(self, pointer: str, message: str):
        super().__init__(message)
        self.pointer = pointer


def _only(value: object, keys: tuple[str, ...], pointer: str) -> dict:
    if not isinstance(value, dict):
        raise Invalid(pointer, "Must be an object.")
    extra = sorted(set(value) - set(keys))
    if extra:
        raise Invalid(f"{pointer}/{extra[0]}", "Unknown field.")
    return value


def clean_theme(theme: dict) -> dict:
    """Brand colours only; the app derives readable on-colours itself (mobile/src/lib/theme.ts)."""
    theme = _only(theme, ("primary", "accent"), "/theme")
    for key, value in theme.items():
        if value is not None and (not isinstance(value, str) or not _HEX.match(value)):
            raise Invalid(f"/theme/{key}", "Use a colour like #1F6FEB.")
    return {k: v.upper() for k, v in theme.items() if v is not None}


def clean_home_screen(layout: dict | None) -> dict | None:
    """APP-04: ordered tiles (type from TILE_TYPES, plain-text caption, size) and a global design. None means the
    app's built-in layout."""
    if layout is None:
        return None
    layout = _only(layout, ("tiles", "design"), "/home_screen")
    tiles = layout.get("tiles") or []
    if not isinstance(tiles, list) or len(tiles) > MAX_TILES:
        raise Invalid("/home_screen/tiles", f"Use at most {MAX_TILES} tiles.")
    out = []
    for i, tile in enumerate(tiles):
        at = f"/home_screen/tiles/{i}"
        tile = _only(tile, ("type", "caption", "style"), at)
        if tile.get("type") not in TILE_TYPES:
            raise Invalid(f"{at}/type", "Unknown tile type.")
        caption = tile.get("caption")
        if caption is not None:
            if not isinstance(caption, str) or len(caption.strip()) > MAX_CAPTION or "<" in caption:
                raise Invalid(f"{at}/caption", f"Plain text, at most {MAX_CAPTION} characters.")
            caption = caption.strip() or None
        style = tile.get("style", "small")
        if style not in TILE_STYLES:
            raise Invalid(f"{at}/style", "Use large or small.")
        out.append({"type": tile["type"], "caption": caption, "style": style})
    design = _only(layout.get("design") or {}, ("columns", "corners"), "/home_screen/design")
    columns, corners = design.get("columns", 2), design.get("corners", "rounded")
    if columns not in (1, 2) or isinstance(columns, bool):
        raise Invalid("/home_screen/design/columns", "Use 1 or 2 columns.")
    if corners not in ("rounded", "square"):
        raise Invalid("/home_screen/design/corners", "Use rounded or square.")
    return {"tiles": out, "design": {"columns": columns, "corners": corners}}


def clean_schedule(schedule: dict) -> dict:
    """APP-18 presentation flags, applied on top of each session booking policy (never loosening it)."""
    schedule = _only(schedule, tuple(DEFAULT_SCHEDULE), "/schedule")
    out = {**DEFAULT_SCHEDULE, **schedule}
    for key in ("shows_spots_left", "shows_full_sessions"):
        if not isinstance(out[key], bool):
            raise Invalid(f"/schedule/{key}", "Must be true or false.")
    days = out["days_ahead"]
    if days is not None and (isinstance(days, bool) or not isinstance(days, int) or not 1 <= days <= 365):
        raise Invalid("/schedule/days_ahead", "Use 1 to 365 days, or leave it empty.")
    return out


def clean_features(features: dict) -> dict:
    features = _only(features, FEATURES, "/features")
    for key, value in features.items():
        if not isinstance(value, bool):
            raise Invalid(f"/features/{key}", "Must be true or false.")
    return {key: features.get(key, True) for key in FEATURES}


def present_listing(listing: dict, schedule: dict, horizon) -> dict | None:
    """One portal session listing after the tenant's schedule flags: None hides it. `horizon` is the latest start
    shown (or None)."""
    if horizon is not None and listing["starts_at"] >= horizon:
        return None
    if not schedule["shows_full_sessions"] and listing["reason"] == "full":
        return None
    if not schedule["shows_spots_left"]:
        return {**listing, "spots_left": None}
    return listing
