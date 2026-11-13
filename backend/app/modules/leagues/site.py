"""Phase 14 B2, the public league site: options and branding (LGE-19, PLT-12), links (LGE-20), photo gallery
(LGE-21), sponsors (LGE-33), news (MKT-18), the class and clinic listing read from programs (CLS-07), the TV
board (LGE-24), public teams, players, stats and brackets (LGE-18), and moderated classifieds and pickup games
(LGE-22, LGE-23).

Site content is tenant-wide: reads need `leagues.public_site.manage` (sponsors `leagues.sponsor.manage`), writes go
through `authorize_tenant_wide`. Posts belong to a location and are moderated under `leagues.classified.moderate`
at that location. The public functions take no principal and serve published rows only (README, privacy)."""

from datetime import date, datetime, time, timedelta
from uuid import UUID
from zoneinfo import ZoneInfo

from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session as Db

from app.core import audit, clock
from app.core.auth import Principal, authorize, scope_query
from app.core.auth.permissions import authorize_tenant_wide
from app.core.errors import Conflict, NotFound, ValidationFailed
from app.core.pagination import ListQuery, paginate
from app.modules import clients, platform, programs, resources
from app.modules.leagues import depth
from app.modules.leagues import service as core
from app.modules.leagues.models import (
    Bracket,
    BracketSlot,
    Competition,
    CompetitionTeam,
    Division,
    Game,
    LeagueNewsStory,
    LeaguePost,
    LeagueSite,
    LeagueSiteLink,
    LeagueSitePhoto,
    LeagueSponsor,
    RosterEntry,
    Sport,
    Team,
)
from app.modules.platform import files
from app.ports import notifications

SITE, MODERATE, SPONSORS = "leagues.public_site.manage", "leagues.classified.moderate", "leagues.sponsor.manage"
PHOTO, LOGO = "league_photo", "league_sponsor_logo"
IMAGE_MAX_BYTES = 900_000  # inside the 1 MiB body cap, like form header images
POST_DAYS = 30  # decision: posts expire 30 days after posting
POST_LIMIT = 5  # live (pending or approved) posts per client at once
_CLASS_KINDS = ("program", "camp", "clinic", "class_series")
_SECTIONS = {
    "links": "shows_links", "news": "shows_news", "gallery": "shows_gallery", "sponsors": "shows_sponsors",
    "classes": "shows_classes", "classified": "shows_classifieds", "pickup": "shows_pickup_games",
}  # fmt: skip

notifications.register_template(
    "leagues.post_contact",
    subject="Reply to your post: $title",
    body='$sender_name replied to your post "$title" on the league site.\n\n$message\n\n'
    "Reply to them at $sender_email. Your own address was not shared.",
)


def _set(row, data: dict, nullable=()) -> dict:
    """PATCH: set the given fields (None only where clearable) and return the redacted audit diff."""
    for name, value in core._given(data, nullable).items():
        setattr(row, name, value)
    return audit.diff(row)


def _tenant_wide(session: Db, principal: Principal, model, row_id: UUID, key: str = SITE):
    authorize_tenant_wide(principal, key)
    return core._get(session, model, row_id, lock=True)


def _create(session: Db, principal: Principal, model, data: dict, key: str = SITE):
    authorize_tenant_wide(principal, key)
    row = model(**data)
    session.add(row)
    session.flush()
    audit.record(session, key, row, changes={"created": True})
    return row


def _delete(session: Db, row, key: str = SITE, *file_ids) -> None:
    audit.record(session, key, row, changes={"deleted": [False, True]})
    session.delete(row)
    session.flush()
    for file_id in file_ids:
        if file_id is not None:
            files.remove(session, file_id)


# --- site options (LGE-19, PLT-12) ------------------------------------------------------------------------------


def _site_row(session: Db) -> LeagueSite | None:
    return session.scalar(select(LeagueSite))


def site_view(row: LeagueSite | None) -> dict:
    if row is None:  # the defaults, before the site is first saved
        row = LeagueSite(
            is_enabled=False, title="Leagues", shows_facility_info=True, shows_classes=True, shows_news=True,
            shows_gallery=True, shows_sponsors=True, shows_links=True, shows_classifieds=False,
            shows_pickup_games=False, board_refresh_sec=60,
        )  # fmt: skip
    return {c: getattr(row, c) for c in LeagueSite.__table__.columns.keys() if c not in ("id", "tenant_id")}


def get_site(session: Db, principal: Principal) -> dict:
    authorize(principal, SITE)
    return site_view(_site_row(session))


def put_site(session: Db, principal: Principal, data: dict) -> dict:
    authorize_tenant_wide(principal, SITE)
    row = session.scalar(select(LeagueSite).with_for_update())
    if row is None:
        row = LeagueSite(**data)
        session.add(row)
        session.flush()
        audit.record(session, SITE, row, changes={"created": True})
    else:
        changes = _set(row, data, nullable=("tagline", "about_text", "accent_color"))
        audit.record(session, SITE, row, changes=changes)
        session.flush()
    return site_view(row)


def _live(session: Db, section: str | None = None) -> LeagueSite:
    """The enabled site, and the section switched on; anything else is 404."""
    row = _site_row(session)
    if row is None or not row.is_enabled or (section and not getattr(row, _SECTIONS[section])):
        raise NotFound()
    return row


def _locations(session: Db) -> dict[UUID, dict]:
    """Active locations by id, in the tenant's own order. shortcut: one page of 200 covers any real tenant."""
    page = platform.service.list_public_locations(session, ListQuery(limit=200))
    return {loc["id"]: loc for loc in page["data"]}


def public_site(session: Db) -> dict:
    row = _live(session)
    fields = ("address_line1", "address_line2", "city", "region", "postal_code", "phone", "email", "website_url")
    facilities = [
        {"id": loc["id"], "name": loc["public_name"]} | {k: loc[k] for k in fields}
        for loc in _locations(session).values()
    ]
    return site_view(row) | {"facilities": facilities if row.shows_facility_info else []}


# --- links (LGE-20) ---------------------------------------------------------------------------------------------


def _links(session: Db) -> list[LeagueSiteLink]:
    return list(session.scalars(select(LeagueSiteLink).order_by(LeagueSiteLink.sort_order, LeagueSiteLink.title)))


def list_links(session: Db, principal: Principal) -> list[LeagueSiteLink]:
    authorize(principal, SITE)
    return _links(session)


def create_link(session: Db, principal: Principal, data: dict) -> LeagueSiteLink:
    return _create(session, principal, LeagueSiteLink, data)


def update_link(session: Db, principal: Principal, link_id: UUID, data: dict) -> LeagueSiteLink:
    row = _tenant_wide(session, principal, LeagueSiteLink, link_id)
    audit.record(session, SITE, row, changes=_set(row, data, nullable=("category",)))
    session.flush()
    return row


def delete_link(session: Db, principal: Principal, link_id: UUID) -> None:
    _delete(session, _tenant_wide(session, principal, LeagueSiteLink, link_id))


def public_links(session: Db) -> list[LeagueSiteLink]:
    _live(session, "links")
    return _links(session)


# --- photo gallery (LGE-21): bytes only through platform.files --------------------------------------------------


def _image(session: Db, principal: Principal, data: bytes, content_type: str, purpose: str):
    cleaned, kind = files.clean(data, content_type, allowed=(files.JPEG, files.PNG), max_bytes=IMAGE_MAX_BYTES)
    return files.store(session, cleaned, purpose=purpose, content_type=kind,
                       uploaded_by=("staff", principal.staff_user_id))  # fmt: skip


def _photos(session: Db, published_only: bool = False) -> list[LeagueSitePhoto]:
    stmt = select(LeagueSitePhoto).order_by(LeagueSitePhoto.album.nulls_last(), LeagueSitePhoto.sort_order,
                                            LeagueSitePhoto.created_at)  # fmt: skip
    if published_only:
        stmt = stmt.where(LeagueSitePhoto.is_published.is_(True))
    return list(session.scalars(stmt))


def list_photos(session: Db, principal: Principal) -> list[LeagueSitePhoto]:
    authorize(principal, SITE)
    return _photos(session)


def upload_photo(session: Db, principal: Principal, data: bytes, content_type: str, meta: dict) -> LeagueSitePhoto:
    """JPEG or PNG up to 900 KB, re-encoded and malware-scanned by platform.files."""
    authorize_tenant_wide(principal, SITE)
    stored = _image(session, principal, data, content_type, PHOTO)
    return _create(session, principal, LeagueSitePhoto, {"file_id": stored.id} | core._given(meta))


def update_photo(session: Db, principal: Principal, photo_id: UUID, data: dict) -> LeagueSitePhoto:
    row = _tenant_wide(session, principal, LeagueSitePhoto, photo_id)
    audit.record(session, SITE, row, changes=_set(row, data, nullable=("caption", "album")))
    session.flush()
    return row


def delete_photo(session: Db, principal: Principal, photo_id: UUID) -> None:
    row = _tenant_wide(session, principal, LeagueSitePhoto, photo_id)
    _delete(session, row, SITE, row.file_id)


def public_photos(session: Db) -> list[LeagueSitePhoto]:
    _live(session, "gallery")
    return _photos(session, published_only=True)


def public_photo_image(session: Db, photo_id: UUID):
    _live(session, "gallery")
    row = session.get(LeagueSitePhoto, photo_id)
    if row is None or not row.is_published:
        raise NotFound()
    return files.read(session, row.file_id)


# --- sponsors (LGE-33) ------------------------------------------------------------------------------------------


def _sponsor_view(row: LeagueSponsor) -> dict:
    return core._columns(row) | {"has_logo": row.logo_file_id is not None}


def list_sponsors(session: Db, principal: Principal) -> list[dict]:
    authorize(principal, SPONSORS)
    rows = session.scalars(select(LeagueSponsor).order_by(LeagueSponsor.sort_order, LeagueSponsor.name))
    return [_sponsor_view(r) for r in rows]


def create_sponsor(session: Db, principal: Principal, data: dict) -> dict:
    return _sponsor_view(_create(session, principal, LeagueSponsor, data, SPONSORS))


def update_sponsor(session: Db, principal: Principal, sponsor_id: UUID, data: dict) -> dict:
    row = _tenant_wide(session, principal, LeagueSponsor, sponsor_id, SPONSORS)
    changes = _set(row, data, nullable=("url", "blurb", "starts_on", "ends_on"))
    if row.starts_on and row.ends_on and row.ends_on < row.starts_on:
        raise ValidationFailed("The end date is before the start date.", pointer="/ends_on")
    audit.record(session, SPONSORS, row, changes=changes)
    session.flush()
    return _sponsor_view(row)


def set_sponsor_logo(session: Db, principal: Principal, sponsor_id: UUID, data: bytes, content_type: str) -> dict:
    row = _tenant_wide(session, principal, LeagueSponsor, sponsor_id, SPONSORS)
    stored = _image(session, principal, data, content_type, LOGO)
    replaced, row.logo_file_id = row.logo_file_id, stored.id
    session.flush()
    if replaced is not None:
        files.remove(session, replaced)
    audit.record(session, SPONSORS, row, changes={"logo_file_id": [None if replaced is None else "set", "set"]})
    return _sponsor_view(row)


def delete_sponsor(session: Db, principal: Principal, sponsor_id: UUID) -> None:
    row = _tenant_wide(session, principal, LeagueSponsor, sponsor_id, SPONSORS)
    _delete(session, row, SPONSORS, row.logo_file_id)


def _running(today: date):
    s = LeagueSponsor
    return select(s).where(
        s.is_active.is_(True),
        or_(s.starts_on.is_(None), s.starts_on <= today),
        or_(s.ends_on.is_(None), s.ends_on >= today),
    )


def public_sponsors(session: Db) -> list[dict]:
    """Active sponsors whose dates include today. shortcut: today is the UTC date (sponsors are tenant-wide, not
    per location); a sponsor can show or hide a few hours early. Move to a tenant zone if one is ever added."""
    _live(session, "sponsors")
    rows = session.scalars(_running(clock.now().date()).order_by(LeagueSponsor.sort_order, LeagueSponsor.name))
    return [_sponsor_view(r) for r in rows]


def public_sponsor_logo(session: Db, sponsor_id: UUID):
    _live(session, "sponsors")
    row = session.scalar(_running(clock.now().date()).where(LeagueSponsor.id == sponsor_id))
    if row is None or row.logo_file_id is None:
        raise NotFound()
    return files.read(session, row.logo_file_id)


# --- news stories (MKT-18) --------------------------------------------------------------------------------------


def list_news(session: Db, principal: Principal, query: ListQuery) -> dict:
    authorize(principal, SITE)
    n = LeagueNewsStory
    return paginate(
        session, select(n), query, id_column=n.id,
        sort_fields={"published_at": n.published_at, "title": n.title, "created_at": n.created_at},
        default_sort="-created_at", filter_fields={"is_pinned": n.is_pinned}, search=(n.title,),
    )  # fmt: skip


def get_news(session: Db, principal: Principal, story_id: UUID) -> LeagueNewsStory:
    authorize(principal, SITE)
    return core._get(session, LeagueNewsStory, story_id)


def create_news(session: Db, principal: Principal, data: dict) -> LeagueNewsStory:
    return _create(session, principal, LeagueNewsStory, data)


def update_news(session: Db, principal: Principal, story_id: UUID, data: dict) -> LeagueNewsStory:
    row = _tenant_wide(session, principal, LeagueNewsStory, story_id)
    audit.record(session, SITE, row, changes=_set(row, data, nullable=("summary", "published_at")))
    session.flush()
    return row


def delete_news(session: Db, principal: Principal, story_id: UUID) -> None:
    _delete(session, _tenant_wide(session, principal, LeagueNewsStory, story_id))


def _published():
    n = LeagueNewsStory
    return select(n).where(n.published_at.is_not(None), n.published_at <= clock.now())


def public_news(session: Db) -> list[LeagueNewsStory]:
    """The 50 latest published stories, pinned first."""
    _live(session, "news")
    n = LeagueNewsStory
    return list(session.scalars(_published().order_by(n.is_pinned.desc(), n.published_at.desc(), n.id).limit(50)))


def public_news_story(session: Db, story_id: UUID) -> LeagueNewsStory:
    _live(session, "news")
    row = session.scalar(_published().where(LeagueNewsStory.id == story_id))
    if row is None:
        raise NotFound()
    return row


# --- classes and clinics, read from programs (CLS-07) -----------------------------------------------------------


def public_classes(session: Db, location_id: UUID | None = None) -> list[dict]:
    """Root program groups (programs, camps, clinics, class series) published to the portal and not yet over.
    Openings only where the group shows them; registration happens in the portal."""
    _live(session, "classes")
    pg, rc = programs.models.ProgramGroup, programs.models.RegistrationConfig
    earliest = clock.now().date() - timedelta(days=1)  # no zone is more than a day behind UTC; exact per group below
    stmt = (
        select(pg, rc).join(rc, rc.program_group_id == pg.id)
        .where(rc.is_portal_visible.is_(True), pg.deleted_at.is_(None), pg.status == "active", pg.depth == 0,
               pg.kind.in_(_CLASS_KINDS), or_(pg.ends_on.is_(None), pg.ends_on >= earliest))
        .order_by(pg.starts_on.nulls_last(), pg.name)
    )  # fmt: skip
    if location_id is not None:
        stmt = stmt.where(pg.location_id == location_id)
    places = _locations(session)
    out = []
    for group, config in session.execute(stmt).all():
        place = places.get(group.location_id)
        if place is None:
            continue
        today = clock.now().astimezone(ZoneInfo(place["time_zone"])).date()
        if group.ends_on is not None and group.ends_on < today:
            continue
        open_now = config.is_enabled and (config.opens_on is None or config.opens_on <= today) and (
            config.closes_on is None or config.closes_on >= today)  # fmt: skip
        out.append({
            "id": group.id, "location_name": place["public_name"], "kind": group.kind,
            "name": config.portal_publish_name or group.name,
            "description": config.online_description or group.description, "starts_on": group.starts_on,
            "ends_on": group.ends_on, "price_minor": group.price_minor, "is_open": open_now,
            "spots_left": programs.groups.spots_left(session, group) if config.displays_openings else None,
        })  # fmt: skip
    return out


# --- public competitions: teams, players, stats, brackets (LGE-18) ----------------------------------------------


def _public(session: Db, competition_id: UUID) -> Competition:
    return core._public_competition(session, competition_id)


def public_teams(session: Db, competition_id: UUID) -> list[dict]:
    """Team names by division; player names only when the competition shows players (default off)."""
    competition = _public(session, competition_id)
    entries = session.execute(
        select(CompetitionTeam, Team).join(Team, Team.id == CompetitionTeam.team_id)
        .where(CompetitionTeam.competition_id == competition.id, CompetitionTeam.status == "active")
    ).all()  # fmt: skip
    divisions = dict(
        session.execute(select(Division.id, Division.name).where(Division.competition_id == competition.id)).all()
    )
    players: dict[UUID, list[str]] = {e.id: [] for e, _ in entries}
    if competition.show_players and entries:
        roster = session.scalars(select(RosterEntry).where(
            RosterEntry.competition_team_id.in_(list(players)), RosterEntry.status == "active"))  # fmt: skip
        for view in core._roster_views(session, list(roster)):
            players[view["competition_team_id"]].append(view["name"])
    rows = [
        {"name": e.display_name or t.name, "division_name": divisions.get(e.division_id),
         "players": sorted(players[e.id]) if competition.show_players else None}
        for e, t in entries
    ]  # fmt: skip
    return sorted(rows, key=lambda r: (r["division_name"] or "", r["name"]))


def public_player_stats(session: Db, competition_id: UUID) -> list[dict]:
    competition = _public(session, competition_id)
    if not competition.show_players:
        raise NotFound()
    rows = depth.player_totals(session, competition)
    names = core._names(session, [r["competition_team_id"] for r in rows])
    return [{"player_name": r["player_name"], "team_name": names.get(r["competition_team_id"], ""), "stats": r["stats"]}
            for r in rows]  # fmt: skip


def public_brackets(session: Db, competition_id: UUID) -> list[dict]:
    """Published and completed brackets with team names in place of ids, and scores from the slot's game."""
    competition = _public(session, competition_id)
    brackets = list(session.scalars(
        select(Bracket).where(Bracket.competition_id == competition.id, Bracket.status != "draft")
        .order_by(Bracket.created_at)
    ))  # fmt: skip
    if not brackets:
        return []
    slots = list(session.scalars(
        select(BracketSlot).where(BracketSlot.bracket_id.in_([b.id for b in brackets]))
        .order_by(BracketSlot.side.desc(), BracketSlot.round_no, BracketSlot.position)
    ))  # fmt: skip
    games = {g["id"]: g for g in core.game_views(session, list(session.scalars(
        select(Game).where(Game.id.in_([s.game_id for s in slots if s.game_id]))
    )))}  # fmt: skip
    names: dict = core._names(session, [i for s in slots for i in (s.home_team_id, s.away_team_id)])
    by_bracket: dict[UUID, list[dict]] = {b.id: [] for b in brackets}
    for s in slots:
        game = games.get(s.game_id, {}) if s.game_id else {}
        by_bracket[s.bracket_id].append({
            "side": s.side, "round_no": s.round_no, "round_name": s.round_name, "position": s.position,
            "home_seed": s.home_seed, "away_seed": s.away_seed, "home_name": names.get(s.home_team_id),
            "away_name": names.get(s.away_team_id), "home_score": game.get("home_score"),
            "away_score": game.get("away_score"), "starts_at": game.get("starts_at"), "is_bye": s.is_bye,
            "winner": None if s.winner_competition_team_id is None
            else "home" if s.winner_competition_team_id == s.home_team_id else "away",
        })  # fmt: skip
    return [{"name": b.name, "bracket_type": b.bracket_type, "status": b.status, "slots": by_bracket[b.id]}
            for b in brackets]  # fmt: skip


# --- TV display board (LGE-24) ----------------------------------------------------------------------------------


def public_board(session: Db, location_id: UUID) -> dict:
    """Today's games at one location (its own time zone) in public competitions, with scores. Served whether
    or not the site is enabled: the board stands alone on a lobby screen."""
    loc = _locations(session).get(location_id)
    if loc is None:
        raise NotFound()
    zone = core._zone(session, location_id)
    today = clock.now().astimezone(zone).date()
    start = datetime.combine(today, time.min, zone)
    games = list(session.scalars(
        select(Game).join(Competition, Competition.id == Game.competition_id)
        .where(Game.location_id == location_id, Game.starts_at >= start, Game.starts_at < start + timedelta(days=1),
               Game.status.in_(("scheduled", "played", "postponed", "cancelled")),
               Competition.is_public.is_(True), Competition.status.in_(core._PUBLIC_STATUSES))
        .order_by(Game.starts_at, Game.id)
    ))  # fmt: skip
    competitions = dict(session.execute(
        select(Competition.id, Competition.name).where(Competition.id.in_({g.competition_id for g in games}))
    ).all()) if games else {}  # fmt: skip
    courts = {g.resource_id for g in games if g.resource_id}
    venues = {r.id: r.name for r in resources.service.get_many(session, courts)}
    site = _site_row(session)
    return {
        "location_name": loc["public_name"], "time_zone": loc["time_zone"], "on_date": today,
        "refresh_sec": site.board_refresh_sec if site else 60, "generated_at": clock.now(),
        "games": [
            {"starts_at": v["starts_at"], "competition_name": competitions.get(v["competition_id"], ""),
             "venue": venues.get(v["resource_id"]), "status": v["status"],
             "home_name": v["home_name"] or v["home_label"], "away_name": v["away_name"] or v["away_label"],
             "home_score": v["home_score"], "away_score": v["away_score"]}
            for v in core.game_views(session, games)
        ],
    }  # fmt: skip


# --- classifieds and pickup games (LGE-22, LGE-23) --------------------------------------------------------------


def _sports(session: Db, ids) -> dict:
    ids = {i for i in ids if i}
    return dict(session.execute(select(Sport.id, Sport.name).where(Sport.id.in_(ids))).all()) if ids else {}


def _post_views(session: Db, rows: list[LeaguePost], *, staff: bool = False) -> list[dict]:
    sports = _sports(session, [r.sport_id for r in rows])
    places = {i: loc["public_name"] for i, loc in _locations(session).items()}
    names = clients.service.display_names(session, list({r.client_id for r in rows})) if staff and rows else {}
    out = []
    for r in rows:
        view = {
            "id": r.id, "kind": r.kind, "category": r.category, "location_name": places.get(r.location_id, ""),
            "sport_name": sports.get(r.sport_id), "title": r.title, "body": r.body, "starts_at": r.starts_at,
            "skill_level": r.skill_level, "players_needed": r.players_needed, "posted_at": r.created_at,
            "expires_at": r.expires_at,
        }  # fmt: skip
        if staff:
            view |= {"location_id": r.location_id, "status": r.status, "client_name": names.get(r.client_id, ""),
                     "moderated_at": r.moderated_at, "reject_reason": r.reject_reason}  # fmt: skip
        out.append(view)
    return out


def _live_posts():
    p = LeaguePost
    return select(p).where(p.status == "approved", p.expires_at > clock.now())


def public_posts(session: Db, kind: str, location_id: UUID | None = None) -> list[dict]:
    """Approved, unexpired posts of one kind, newest first; never the poster's name or address."""
    _live(session, kind)
    stmt = _live_posts().where(LeaguePost.kind == kind)
    if location_id is not None:
        stmt = stmt.where(LeaguePost.location_id == location_id)
    rows = list(session.scalars(stmt.order_by(LeaguePost.created_at.desc(), LeaguePost.id).limit(100)))
    return _post_views(session, rows)


def list_posts(session: Db, principal: Principal, query: ListQuery) -> dict:
    """The moderation queue at the caller's locations. Filters: status, kind, location_id."""
    authorize(principal, MODERATE)
    p = LeaguePost
    page = paginate(
        session, scope_query(select(p), principal, p.location_id), query, id_column=p.id,
        sort_fields={"created_at": p.created_at, "expires_at": p.expires_at}, default_sort="-created_at",
        filter_fields={"status": p.status, "kind": p.kind, "location_id": p.location_id}, search=(p.title,),
    )  # fmt: skip
    return page | {"data": _post_views(session, list(page["data"]), staff=True)}


def _moderate(session: Db, principal: Principal, post_id: UUID, to: str, allowed: tuple[str, ...], reason=None):
    row = core._scoped(session, principal, LeaguePost, post_id, MODERATE, lock=True)
    if row.status not in allowed:
        raise Conflict(f"The post is {row.status}.", code="post-not-pending")
    if to == "approved" and row.expires_at <= clock.now():
        raise Conflict("The post has expired.", code="post-expired")
    before = row.status
    row.status, row.moderated_at, row.moderated_by_staff_user_id = to, clock.now(), principal.staff_user_id
    row.reject_reason = reason
    audit.record(session, MODERATE, row, location_id=row.location_id, changes={"status": [before, to]})
    session.flush()
    return _post_views(session, [row], staff=True)[0]


def approve_post(session: Db, principal: Principal, post_id: UUID) -> dict:
    return _moderate(session, principal, post_id, "approved", ("pending",))


def reject_post(session: Db, principal: Principal, post_id: UUID, reason: str | None) -> dict:
    """Refuse a pending post or take down an approved one."""
    return _moderate(session, principal, post_id, "rejected", ("pending", "approved"), reason)


def _me(session: Db, principal: Principal) -> UUID:
    """The signed-in client's own record (the identity's primary access row comes first)."""
    if principal.kind != "client" or principal.identity_id is None:
        raise NotFound()
    mine = clients.households.actable_client_ids(session, principal.identity_id)
    if not mine:
        raise NotFound()
    return mine[0]


def portal_list_posts(session: Db, principal: Principal) -> list[dict]:
    me = _me(session, principal)
    rows = list(session.scalars(
        select(LeaguePost).where(LeaguePost.client_id == me).order_by(LeaguePost.created_at.desc()).limit(100)
    ))  # fmt: skip
    views = _post_views(session, rows)
    for view, row in zip(views, rows, strict=True):
        view["status"] = "expired" if row.status == "approved" and row.expires_at <= clock.now() else row.status
    return views


def _lock_poster(session: Db, client_id: UUID) -> None:
    """Serialise one client's submissions until commit, so two parallel posts cannot both pass the live-post cap."""
    session.execute(select(func.pg_advisory_xact_lock(func.hashtextextended(f"league-post:{client_id}", 0))))


def portal_create_post(session: Db, principal: Principal, data: dict) -> dict:
    """Waits for staff approval; shown for 30 days from posting. Errors: post-limit (5 live posts)."""
    me = _me(session, principal)
    _live(session, data["kind"])
    if data["location_id"] not in _locations(session):
        raise ValidationFailed("Unknown location.", pointer="/location_id")
    if data.get("sport_id") and session.get(Sport, data["sport_id"]) is None:
        raise ValidationFailed("Unknown sport.", pointer="/sport_id")
    now = clock.now()
    if data["kind"] == "pickup":
        if data.get("starts_at") is None or data["starts_at"] <= now:
            raise ValidationFailed("A pickup game needs a start time in the future.", pointer="/starts_at")
        data["category"] = "other"
    _lock_poster(session, me)
    live = session.scalar(
        select(func.count()).select_from(LeaguePost)
        .where(LeaguePost.client_id == me, LeaguePost.status.in_(("pending", "approved")), LeaguePost.expires_at > now)
    )  # fmt: skip
    if (live or 0) >= POST_LIMIT:
        raise Conflict(f"You already have {POST_LIMIT} posts up; withdraw one first.", code="post-limit")
    expires_at = now + timedelta(days=POST_DAYS)
    if data["kind"] == "pickup":
        expires_at = min(expires_at, data["starts_at"])  # a game comes down once it starts
    row = LeaguePost(**data, client_id=me, status="pending", expires_at=expires_at)
    session.add(row)
    session.flush()
    audit.record(
        session, "leagues.post.submit", row, location_id=row.location_id, changes={"status": [None, "pending"]}
    )
    return _post_views(session, [row])[0] | {"status": row.status}


def portal_withdraw_post(session: Db, principal: Principal, post_id: UUID) -> None:
    me = _me(session, principal)
    row = core._get(session, LeaguePost, post_id, lock=True)
    if row.client_id != me:
        raise NotFound()
    if row.status in ("pending", "approved"):
        before, row.status = row.status, "withdrawn"
        audit.record(session, "leagues.post.withdraw", row, location_id=row.location_id,
                     changes={"status": [before, "withdrawn"]})  # fmt: skip
        session.flush()


def portal_contact_post(session: Db, principal: Principal, post_id: UUID, message: str) -> None:
    """The relay: the poster gets the message and the sender's name and address; the poster's address is never
    shown to the sender. Errors: contact-unavailable (the poster has no email on file)."""
    me = _me(session, principal)
    row = session.scalar(_live_posts().where(LeaguePost.id == post_id))
    if row is None or row.client_id == me:
        raise NotFound()
    _live(session, row.kind)
    poster, sender = clients.service.get(session, row.client_id), clients.service.get(session, me)
    if not poster.primary_email or not sender.primary_email:
        raise Conflict("Contact needs an email address on both sides.", code="contact-unavailable")
    notifications.send(session, "leagues.post_contact", poster.primary_email, {
        "title": row.title, "message": message, "sender_name": clients.service.display_name(sender),
        "sender_email": sender.primary_email,
    })  # fmt: skip
