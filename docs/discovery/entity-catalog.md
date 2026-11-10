# Entity Catalog — inferred data entities

Phase 0 output 4. Entities, fields, enumerations and relationships inferred from public material. Names are ours; types are guesses for Phase 1 to confirm. Overlaps between clusters are deliberate inputs to the Phase 1 domain model, not yet reconciled.

## Platform, Locations & Resources, Import, Onboarding

All tables carry `tenant_id` (RLS) and audit columns unless noted. Types are guesses. "Their label" = source UI label.

### Tenant
Customer account that owns locations, users and all business data.

| field | type guess | notes / allowed values |
|---|---|---|
| id | uuid | |
| name | text | |
| plan_id | fk SubscriptionPlan | |
| billing_cycle | enum | monthly, annual |
| status | enum | trial, active, suspended, cancelled (inferred) |
| gdpr_region | bool | derived from locations (inferred) |

- Relationships: 1-n Location, StaffUser, Role; 1-n TenantEntitlement.
- Evidence: PLT-01, PLT-14

### SubscriptionPlan
Platform-level plan definition with metered limits.

| field | type guess | notes / allowed values |
|---|---|---|
| code | text | starter, basic, premium, ultimate (their tiers) |
| member_limit | int null | 500, 1500, 3000, null = unlimited |
| resource_limit | int null | 5, 15, 30, null = unlimited |
| support_channels | text[] | chat, email, phone |
| feature_tier | enum | limited, basic, all |

- Relationships: 1-n Tenant. Not tenant-scoped.
- Evidence: PLT-14

### TenantEntitlement
Add-on or module switched on for a tenant.

| field | type guess | notes / allowed values |
|---|---|---|
| tenant_id | fk | |
| module_code | enum | branded_app, advanced_email, leagues, accounting_sync, lockers, league_advertising (list from evidence; extend) |
| source | enum | plan_included, purchased |
| active_from / active_to | date | |

- Relationships: n-1 Tenant. Gates UI and API (e.g. locker reports hidden without `lockers`).
- Evidence: PLT-14, RES-07, PLT-11

### Location
A physical site of a tenant; carries identity, branding and batch-job settings.

| field | type guess | notes / allowed values |
|---|---|---|
| id | uuid | |
| label | text | internal name (their "Location Label") |
| public_name | text | customer-facing |
| address fields | text | street, city, region, postal code, country |
| phone | text | |
| email | text | visible to customers |
| alert_email | text | receives failed-card notices only |
| website | text | |
| time_zone | text (IANA) | inferred; drives timestamps and day boundaries |
| accepted_card_brands | text[] | editable only when a processor is connected |
| membership_renewal_run_time | time | local time |
| package_renewal_run_time | time | replenish quantity + charge |
| autopay_run_time | time | |
| decline_email_mode | enum | daily_digest, per_decline (their "Send One Failed Transaction Email" yes/no) |
| time_clock_rounding | enum | none, up, down (increment unknown) |
| drag_drop_default | enum | reschedule, move_booking, no_default |
| gdpr_enabled | bool | EU only |
| vaccine_status_enabled | bool | default false; legacy |
| default_ui | enum | classic, new (legacy; not built) |

- Relationships: n-1 Tenant; 1-n FacilityHours, Resource, ResourceGroup, LocationBrandAsset, LockerRoom; referenced by Client.home_location (Clients cluster).
- Evidence: RES-01, PLT-01, PLT-09, PLT-16

### LocationBrandAsset
Image slot per location.

| field | type guess | notes / allowed values |
|---|---|---|
| location_id | fk | |
| slot | enum | primary (header, receipts, invoices, reports, campaigns), back_office (their "vanity logo"), public, online_registration, self_service, league_site |
| object_key | text | S3 key |
| width / height | int | source constraints: 240x80 GIF (Classic), 240x240 (New), JPG only (league site) |
| content_type | text | we accept png, jpg, gif, svg and render variants |

- Relationships: n-1 Location; unique (location_id, slot).
- Evidence: PLT-08, PLT-12

### FacilityHours
Weekly opening window per location that bounds the schedule grid.

| field | type guess | notes / allowed values |
|---|---|---|
| location_id | fk | |
| weekday | smallint | 0-6 |
| opens_at / closes_at | time | local |
| closed | bool | |

- Relationships: n-1 Location; unique (location_id, weekday). Holiday/blackout dates are a separate entity owned by Scheduling.
- Evidence: RES-02

### StaffUser
Back-office login for an employee.

| field | type guess | notes / allowed values |
|---|---|---|
| id | uuid | |
| username | citext unique per tenant | their uniqueness may be global (unknown) |
| email | citext | reply-to for mail the user sends |
| first_name / last_name | text | |
| password_hash | text | policy: min 12, 1 digit, 1 uppercase (New); 6 alnum mix (Classic) |
| must_change_password | bool | set by admin reset (inferred) |
| role_id | fk Role | exactly one |
| mobile_phone | text | |
| sms_carrier | text null | their carrier gateway list or "Don't use SMS"; we use an SMS API and drop this |
| linked_resource_id | fk Resource null | unlocks resource-scoped permissions |
| notify_attendance_changes | bool | their "Send Email Notifications For" |
| ip_restriction_mode | enum | any, allow_list |
| status | enum | active, inactive |
| scope | enum | back_office, app_portal, league (our unification of three user tables) |

- Relationships: n-1 Tenant, Role; n-n Location via UserLocationAccess; 1-n UserPermissionOverride, AllowedIp, UserPreference.
- Evidence: PLT-02, PLT-03, PLT-05, PLT-07, PLT-11, PLT-13

### UserLocationAccess
Which locations a user may act in and with what scope.

| field | type guess | notes / allowed values |
|---|---|---|
| user_id | fk | |
| location_id | fk | |
| is_primary | bool | mandatory for app-portal users |
| app_permission | enum null | manage_location, send_notifications (app portal only) |

- Relationships: join StaffUser-Location. For back-office users the source does not publish location scoping (inferred).
- Evidence: PLT-13, PLT-01

### Role
Named permission set; built-in or custom.

| field | type guess | notes / allowed values |
|---|---|---|
| id | uuid | |
| name | text | built-ins: Manager, Staff, Trainer, View Only; league: Super User, Admin, Scorekeeper, Advertising Manager |
| is_system | bool | |
| cloned_from_role_id | fk null | provenance only; no live inheritance |
| scope | enum | back_office, league |

- Relationships: 1-n RolePermission; 1-n StaffUser.
- Evidence: PLT-04, PLT-11

### Permission
Static catalogue of grantable actions.

| field | type guess | notes / allowed values |
|---|---|---|
| code | text pk | ours |
| area | enum | hidden, general, administration, report, billing, pos, document, membership, reservation, package, predefined_items, client, group_subgroup, email_campaign |
| kind | enum | boolean, level |
| levels | text[] null | email_campaign: publisher, editor, viewer, none |
| subject_type | enum null | reservation_type (dynamic per-record grants) |
| manager_only | bool | assumed; demos suggest a few permissions (e.g. billing statements) are not grantable to lower roles |

- Relationships: referenced by RolePermission and UserPermissionOverride. Not tenant-scoped.
- Evidence: PLT-04, PLT-06

### RolePermission
Grant of a permission to a role.

| field | type guess | notes / allowed values |
|---|---|---|
| role_id | fk | |
| permission_code | fk | |
| subject_id | uuid null | e.g. reservation type id |
| allowed | bool | checked = granted |
| level | text null | for level-type permissions |

- Relationships: n-1 Role, Permission.
- Evidence: PLT-04, PLT-06

### UserPermissionOverride
Per-user deviation from the role template.

| field | type guess | notes / allowed values |
|---|---|---|
| user_id | fk | |
| permission_code | fk | |
| subject_id | uuid null | |
| allowed | bool | |
| level | text null | |

- Relationships: n-1 StaffUser. Presence of any row = the "edited from template" marker (their asterisk).
- Evidence: PLT-05, PLT-06

### AllowedIp
Network allow-list entry for a user.

| field | type guess | notes / allowed values |
|---|---|---|
| user_id | fk | scope per user assumed; source ambiguous |
| cidr | inet | source stores single addresses |
| note | text | |

- Relationships: n-1 StaffUser.
- Evidence: PLT-07

### UserPreference
Per-user UI state.

| field | type guess | notes / allowed values |
|---|---|---|
| user_id | fk | |
| key | text | sidebar_collapsed, theme |
| value | jsonb | theme: light, dark, system |

- Relationships: n-1 StaffUser.
- Evidence: PLT-10

### ResourceGroup
Calendar category for resources (their "Schedule Group", renamed "Resource Group" in the 2026 scheduling refresh). Header only: never bookable itself.

| field | type guess | notes / allowed values |
|---|---|---|
| id | uuid | |
| location_id | fk | |
| name | text | |
| sort_order | int | |

- Relationships: 1-n Resource.
- Evidence: RES-04

### Resource
Anything with its own calendar column that can be booked or held.

| field | type guess | notes / allowed values |
|---|---|---|
| id | uuid | |
| location_id | fk | |
| kind | enum | venue, trainer, equipment (their venue list includes equipment) |
| name | text | their "Venue Name" |
| group_id | fk ResourceGroup | |
| parent_id | fk Resource null | sub-venues (2026); booking a child blocks the parent and booking the parent blocks every child; a child can carry its own rates and rental types |
| sort_order | int | |
| status | enum | active, archived (inferred) |
| counts_toward_plan | bool | salespeople are not resources |

- Relationships: n-1 Location, ResourceGroup; self-tree; 1-n BookingResourceHold; n-n LeagueVenue via LeagueVenueMapping; 0-1 StaffUser.linked_resource.
- Evidence: RES-03, RES-04, PLT-14

### BookingResourceHold
One occupied interval on one resource, belonging to a booking (the row the exclusion constraint guards).

| field | type guess | notes / allowed values |
|---|---|---|
| booking_id | fk Booking (Scheduling cluster) | all holds of a booking move and die together |
| resource_id | fk | |
| period | tstzrange | |
| role | enum | primary (trainer/session row), hold (their grey "Unavailable") |

- Relationships: n-1 Booking, Resource. EXCLUDE USING gist (resource_id WITH =, period WITH &&).
- Evidence: RES-05, RES-06

### LeagueVenue
Venue as presented in league scheduling and on the public league site.

| field | type guess | notes / allowed values |
|---|---|---|
| id | uuid | |
| name | text | |
| public_description | text | |

- Relationships: n-n Resource via LeagueVenueMapping(league_venue_id, resource_id). Candidate to collapse into Resource + public fields (see unknowns).
- Evidence: RES-06

### LeagueSiteSettings
Public league-site presentation per tenant/location.

| field | type guess | notes / allowed values |
|---|---|---|
| menu_visibility | jsonb | bool per menu item |
| colors | jsonb | hex per slot incl. primary, link |
| leagues_page_defaults | jsonb | filters: status, sport, season, age_group, division; sort |
| tournaments_page_defaults | jsonb | same shape |
| default_schedule_view | enum | list, grid |

- Relationships: 1-1 Tenant or Location (unknown which); logo via LocationBrandAsset(slot=league_site).
- Evidence: PLT-12

### LockerRoom
Group of lockers.

| field | type guess | notes / allowed values |
|---|---|---|
| id | uuid | |
| location_id | fk | |
| name | text | |
| gender | enum | values not published; assume male, female, unisex |

- Relationships: 1-n Locker.
- Evidence: RES-07

### Locker
Single rentable locker.

| field | type guess | notes / allowed values |
|---|---|---|
| room_id | fk | |
| number | int | unique per room (assumed) |
| size | text | list not published |
| status | enum | available, rented, expired (inferred from reports) |

- Relationships: n-1 LockerRoom; 1-n LockerContract (Scheduling cluster); 0-1 Padlock (inferred).
- Evidence: RES-07

### LockerTerm
Named rental period for lockers.

| field | type guess | notes / allowed values |
|---|---|---|
| name | text | |
| starts_on / ends_on | date | |
| sort_order | int | |

- Relationships: referenced by LockerContract.
- Evidence: RES-08

### Padlock
Physical lock issued with a locker.

| field | type guess | notes / allowed values |
|---|---|---|
| number | text | |
| combination | text (encrypted) | plain in source; we encrypt and permission-gate |
| status | enum | active, disabled |
| deleted_at | timestamptz null | purge = hard delete |

- Relationships: 0-1 Locker (inferred).
- Evidence: RES-09

### ImportJob
One uploaded data file and its processing result.

| field | type guess | notes / allowed values |
|---|---|---|
| id | uuid | |
| type | enum | contacts_basic, contacts_advanced, pos_products |
| file_key | text | |
| dob_format | enum | mdy, dmy (explicit; source accepts both silently) |
| status | enum | uploaded, validating, needs_review, importing, completed, failed (ours) |
| submitted_by | fk StaffUser | |
| counts | jsonb | rows, created, updated, rejected |
| create_first_term_invoice | bool | advanced only |

- Relationships: 1-n ImportRowError(row_no, column, message); optionally n-1 SupportTicket.
- Evidence: IMP-01, IMP-02

### ExportJob
Asynchronous data export.

| field | type guess | notes / allowed values |
|---|---|---|
| kind | enum | client_demographics, client_personal_data (source delivers the latter as Excel only) |
| filters | jsonb | client set; include_membership bool |
| format | enum | xlsx, csv, pdf |
| status | enum | queued, running, ready, expired |
| file_key | text | |

- Relationships: n-1 StaffUser (requester); optionally n-1 Client for personal-data export.
- Evidence: IMP-03, IMP-04

### DataSubjectRequest
GDPR access or erasure action on a client.

| field | type guess | notes / allowed values |
|---|---|---|
| client_id | fk | |
| type | enum | export, erase |
| erase_scope | enum | personal_data_only (source behaviour: invoices and payments kept but detached; renewals stopped) |
| confirmation_text | text | erase requires typing "delete"; irreversible |
| retention_reason | text null | why an erasure was refused (e.g. open invoice, current member) |
| status | enum | requested, completed, rejected |
| performed_by | fk StaffUser | |

- Relationships: n-1 Client; 0-1 ExportJob.
- Evidence: IMP-04, PLT-16

### SupportTicket
Request from a tenant to the platform operator.

| field | type guess | notes / allowed values |
|---|---|---|
| type | enum | import (only published value), general, billing (assumed); feedback_general, bug, development_request (New UI Give Feedback) |
| source | enum | request_form, chat_bot, feedback_button |
| subject / body | text | |
| attachments | file[] | |
| status | enum | open, pending, closed (assumed) |

- Relationships: n-1 Tenant, StaffUser. Likely delegated to an external helpdesk (adapter).
- Evidence: ONB-03, IMP-02

### AuditEvent
One staff action on a record (their "account activity report").

| field | type guess | notes / allowed values |
|---|---|---|
| id | uuid | |
| actor_user_id | fk StaffUser | individual logins required for this to be meaningful |
| action | enum | created, changed, deleted (source names changed and deleted) |
| entity_type / entity_id | text / uuid | source example: a schedule item |
| occurred_at | timestamptz | exact time shown in the report |
| summary | jsonb | before/after values (ours; source columns not shown) |

- Relationships: n-1 Tenant, StaffUser. Append-only.
- Evidence: PLT-17

## Scheduling, Rentals, Classes

All tables carry `tenant_id` (RLS), `location_id` where location-scoped, `id`, audit columns; omitted below. Times stored UTC, rendered in location time zone. Names are ours; the reference product's label is given in notes.

### ActivityType
Purpose: master definition of a schedulable and/or sellable kind of session (their "Reservation Type").

| field | type guess | notes / allowed values |
|---|---|---|
| name | text | "Reservation Type" |
| is_schedulable | bool | "Can Schedule" |
| is_sellable | bool | "Can Sell"; sell-only types allowed |
| revenue_category_id | fk | default for packages of this type |
| default_capacity | int | "Class Size"; 0 allowed; not used for rentals |
| default_duration_min | int null | "Session Length" (one Classic article only) |
| color | text | palette value; system default colours are immutable |
| category_id | fk null | -> ActivityCategory ("Res. Category") |
| subcategory_id | fk null | "Reservation Sub-category" |
| default_allow_free_booking | bool | "Default Allow Free Booking(s)" |
| buffer_before_min / buffer_after_min | int null | NSE buffer times; split is our assumption; video: choices 5 min to 1 h; a location-level default exists and a session can override it |
| sort_order | int | reorder arrows |
| deleted_at | timestamptz null | their delete cascades to package plans; we soft-delete |

Relationships: 1-1 ActivityTypeOnlinePolicy; 1-n Reservation; 1-n PackagePlan (other cluster); n-n StaffUser via ActivityTypePermission.
Evidence: SCH-02, SCH-04, SCH-06, SCH-14, CLS-04, CLS-05

### ActivityCategory
Purpose: member-facing grouping of activity types for app/portal schedule tiles (their "Reservation Category").

| field | type guess | notes / allowed values |
|---|---|---|
| label | text | renameable |
| parent_id | fk null | sub-category (inferred hierarchy of depth 2) |
| sort_order | int | inferred |

Relationships: 1-n ActivityType.
Evidence: SCH-04

### ActivityTypeOnlinePolicy
Purpose: self-service booking rules for an activity type (their wrench/gear "Self Service" settings).

| field | type guess | notes / allowed values |
|---|---|---|
| activity_type_id | fk | |
| use_location_default | bool | "Use Location Default"; false = override |
| listing_mode | enum | LISTED, UNLISTED ("Do Not List"); other values not documented |
| online_description | text | "Online Description" |
| allowed_package_type_ids | fk[] / join table | "Allowed Packages" |
| booking_cutoff_min | int null | cut-off shown to clients; setting location unconfirmed |

Relationships: n-n PackagePlan/ActivityType (allowed packages).
Evidence: SCH-03, SCH-17, CLS-09

### ActivityTypePermission
Purpose: per-staff-user access to an activity type.

| field | type guess | notes / allowed values |
|---|---|---|
| user_id | fk | |
| activity_type_id | fk | |
| access | enum | ALLOW/DENY (granularity undocumented) |

Relationships: StaffUser n-n ActivityType. New types back-populated from existing grants.
Evidence: SCH-05

### ReservationSeries
Purpose: groups occurrences generated together or appended later (their "linked reservations").

| field | type guess | notes / allowed values |
|---|---|---|
| kind | enum | SESSION, RENTAL, SPECIAL |
| recurrence_rules | jsonb | list of RecurrenceRule (several passes may be stacked) |
| created_by | fk | |
| occurrence_count | int | must scale to 1,500+ |

RecurrenceRule (embedded value): pattern enum SINGLE, DAILY, WEEKLY, BIWEEKLY, MONTHLY_BY_DATE, YEARLY, NTH_WEEKDAY_OF_MONTH; weekdays smallint[]; nth int; range_type enum COUNT, UNTIL_DATE; count int; until date; start/end local time with day offset for overnight spans.
Relationships: 1-n Reservation. Two series can be merged into one by reservation number (SCH-21).
Evidence: SCH-09, SCH-10, SCH-11, RNT-04

### Reservation
Purpose: one calendar occurrence of a session, rental or block.

| field | type guess | notes / allowed values |
|---|---|---|
| series_id | fk null | |
| kind | enum | SESSION, RENTAL, SPECIAL |
| activity_type_id | fk null | SESSION only; null while "TBD" |
| special_subtype | enum null | FLOOR_HOURS, PROGRAM_INSTRUCTION, UNPAID_TIME, UNAVAILABLE |
| rental_type_id | fk null | RENTAL only |
| time_range | tstzrange | start/end; overnight allowed |
| buffered_range | tstzrange | time_range widened by buffers (assumption: this is what conflicts) |
| use_location_default_buffer | bool | "use location default" on the session form; false = per-session buffer minutes (video, SCH-14) |
| title | text | staff-facing; rentals get client name appended |
| public_title | text null | portal/app |
| capacity | int null | "Class Size"; copied from type, overridable; null for rental/special |
| self_booking_enabled | bool | "Self-Booking" |
| allow_free_booking | bool | per-session override |
| split_group / slot_minutes | uuid / int null | set when created by Split (15/30/45/60...) |
| client_id | fk null | renter (RENTAL) |
| additional_client_ids | join | a second client can be added to a rental, charged or not (video, RNT-03); storage shape is our guess |
| has_unpaid_balance | derived | $ icon on rental tile (pre-NSE) / owed-vs-paid line in the NSE hover card |
| show_on_public_league_site | bool | "Show On EZLeagues" |
| direct_link_token | text | opaque token behind the direct registration URL |
| virtual_meeting_url | text null | Zoom |
| fill_state | derived | EMPTY, PARTIAL, FULL (Classic) = yellow/green/red (New) |
| billing_state | enum | UNBILLED, BILLED, NO_CHARGE (RENTAL; inferred) |
| status | enum | ACTIVE, CANCELLED (soft delete; inferred) |

Relationships: n-1 ReservationSeries; 1-n ReservationResource; 1-n SessionBooking; 1-n RentalChargeLine (via join); n-1 Client (renter).
Evidence: SCH-06, SCH-07, SCH-08, SCH-10, SCH-11, SCH-16, RNT-03, RNT-13, CLS-04, CLS-08

### ReservationResource
Purpose: allocation of a reservation to a bookable resource or trainer; carrier of the DB exclusion constraint.

| field | type guess | notes / allowed values |
|---|---|---|
| reservation_id | fk | |
| resource_id | fk | venue, sub-venue, or trainer-as-resource |
| occupied_range | tstzrange | = Reservation.buffered_range; EXCLUDE USING gist (resource_id WITH =, occupied_range WITH &&) WHERE active |
| role | enum | PRIMARY, ADDITIONAL, TRAINER (inferred) |

Relationships: n-1 Resource (resources cluster; parent/child for sub-venues, so a booking on a parent must also write rows for each child and vice versa, assumption). Mutual parent/child blocking confirmed by the NSE webinar (SCH-15).
Evidence: SCH-12, SCH-13, SCH-15, SCH-18

### SessionBooking
Purpose: a client's place (or waitlist position) in a session occurrence.

| field | type guess | notes / allowed values |
|---|---|---|
| reservation_id | fk | |
| client_id | fk | |
| client_package_id | fk null | null when free booking |
| status | enum | RESERVED, SCHEDULED, ATTENDED, WAITLISTED, CANCELLED, NO_SHOW (first four seen in sources; last two inferred); EARLY_CANCELLED seen in a New UI demo (CLS-03) |
| waitlist_position | int null | ordering rule undocumented; assume FIFO |
| booked_via | enum | STAFF, PORTAL, APP, DIRECT_LINK, API (inferred) |
| booked_scope | enum | SINGLE, ALL_LINKED, CUSTOM (audit of "Book Using" choice) |
| attended_at | timestamptz null | |
| shared_from_client_id | fk null | when consuming a package shared by a related client |

Relationships: n-1 Reservation; n-1 Client; n-1 ClientPackage (packages cluster).
Evidence: CLS-01, CLS-02, CLS-03, CLS-06, SCH-17

### RentalType
Purpose: category of facility rental with revenue mapping and online policy.

| field | type guess | notes / allowed values |
|---|---|---|
| name | text | |
| revenue_category_id | fk | |
| color | text | |
| sort_order | int | |
| buffer_before_min / buffer_after_min | int null | NSE; shape assumed |
| online_enabled | bool | "Available for Self-Booking" |
| online_rate_id | fk null | "Rental Rate" |
| min_lead_time_min | int null | "Rental Cutoff Times" |
| min_length_min / max_length_min | int null | per booking |
| requires_active_paid_membership | bool | "Default Requirements" |
| online_payment_mode | enum | PAY_IN_FULL, PAY_LATER (2016 blog) |
| slot_granularity_min | int | 60 (on-the-hour rule) |
| access | enum | ADMIN_ONLY, SELF_BOOK (NSE "Access"; SELF_BOOK equals online_enabled) |
| default_length_min | int null | NSE default rental length, alongside min/max |
| client_eligibility | enum | ALL_CLIENTS, MEMBERS_ONLY (rental plans video) |
| allowed_rental_plan_ids | join | "rental plans" multi-select; empty = any plan accepted |

Relationships: n-n Resource (allowed venues); 1-n RentalRate; n-n RentalPlan.
Evidence: RNT-01, RNT-05, RNT-07

### RentalRate
Purpose: priced template for a rental type.

| field | type guess | notes / allowed values |
|---|---|---|
| rental_type_id | fk | |
| label | text | becomes invoice line description |
| internal_description | text null | staff-only, never shown to clients (NSE) |
| amount | numeric(12,2) | >= 0; NSE: member_amount and non_member_amount on the same rate |
| basis | enum | PER_HOUR, PER_OCCURRENCE, FLAT ("Custom") |
| multi_resource_qty_mode | enum | ONCE, PER_RESOURCE |
| line_grouping | enum | COMBINED, PER_RESOURCE, PER_OCCURRENCE, PER_RESOURCE_OCCURRENCE ("Separate") |
| time_bands | jsonb null | peak/off-peak tiers (NSE; structure unknown); video: list of RateRule {kind RATE or DISCOUNT; time_of_day range; date range; weekdays; membership_type_id; amount} |
| tax_code_ids | fk[] | taxes selectable per rental |

Relationships: n-1 RentalType; referenced by RentalChargeLine.
Evidence: RNT-02

### RentalChargeLine
Purpose: billing item generated from rental occurrences, handed to Billing as an invoice/cart line.

| field | type guess | notes / allowed values |
|---|---|---|
| client_id | fk | |
| rental_rate_id | fk null | null = custom rate |
| description | text | rate label |
| quantity | numeric | hours or occurrences or 1 |
| unit_amount / total | numeric | |
| invoice_routing | enum | NEW_SINGLE, NEW_PER_LINE, DATE_BASED, EXISTING_OPEN, CART ("Invoice Later") |
| revenue_date | date | "Revenue date" under More options in the cart step; default today |
| invoice_line_id | fk null | billing cluster |
| rental_plan_purchase_id | fk null | when tendered from a plan |

Relationships: n-n Reservation (covered occurrences).
Evidence: RNT-03, RNT-04

### RentalPlan
Purpose: sellable prepaid rental bundle.

| field | type guess | notes / allowed values |
|---|---|---|
| name | text | |
| model | enum | PER_HOUR, PER_OCCURRENCE |
| quantity | numeric | hours or bookings |
| member_price / non_member_price | numeric | |
| valid_from / valid_until | date null | |
| auto_renew | bool | rolling |
| online_sale_enabled | bool | "selling status": on = self-service purchase, off = staff sale only |
| rental_type_id | fk | required home rental type on the plan form (video) |
| internal_description / client_description | text null | internal-only vs client-visible notes/terms |
| members_only | bool | |
| start_on_sale_date | bool | "default to sale date"; false = fixed future start |
| is_unlimited | bool | Unlimited checkbox instead of a quantity |
| is_flat_rate | bool | true = price covers the whole plan; false = price x quantity |
| discount | numeric null | discount section on pricing screen |
| revenue_category_id | fk | |
| default_invoice_option | enum | defaults to single invoice |
| auto_pay | bool | applies when the plan has a payment schedule |
| share_across_relationships | bool | siblings, parents, spouse |
| archived_at | timestamptz null | archive is reversible; trash is permanent |

Relationships: n-n RentalType; 1-n RentalPlanPurchase.
Evidence: RNT-09

### RentalPlanPurchase
Purpose: a client's owned plan instance with balance.

| field | type guess | notes / allowed values |
|---|---|---|
| rental_plan_id | fk | |
| client_id | fk | owner |
| shared_with_client_ids | join | RNT-10 (title only); shared from the client's Rental plans tab with related clients (video) |
| balance | numeric | hours or occurrences remaining |
| price_paid | numeric | |
| sold_channel | enum | STAFF, SELF_SERVICE |
| starts_on / expires_on | date | |
| status | enum | ACTIVE, EXPIRED, REMOVED, REFUNDED (inferred) |
| removal_mode | enum null | REVERSE_BILLING_AND_REMOVE, DELETE_KEEP_BILLING (third UI choice just opens the invoice) |
| terms_acknowledged_at | timestamptz null | |

Relationships: 1-n RentalPlanLedgerEntry (DEBIT on booking, CREDIT on cancel, RENEW, REFUND; inferred, needed for auditability).
Evidence: RNT-09, RNT-10, RNT-11, RNT-12

### EquipmentCategory
Purpose: grouping of rentable equipment.

| field | type guess | notes / allowed values |
|---|---|---|
| name | text | |
| deleted_at | timestamptz null | soft delete; "Show Deleted Categories" |

Relationships: 1-n EquipmentItem.
Evidence: RNT-14

### EquipmentItem
Purpose: rentable asset type shown on the POS equipment panel.

| field | type guess | notes / allowed values |
|---|---|---|
| category_id | fk | |
| name | text | |
| code | text unique per tenant | "Equipment ID" |
| description | text | |
| rental_fee | numeric | pre-tax |
| max_loan_days | int | "Rental Days" |
| due_time | time | "Return Time" |
| late_fee | numeric | informational |
| replacement_fee | numeric | informational |
| tax_code_ids | fk[] | older variant: single tax percent |
| sort_order | int | |
| deleted_at | timestamptz null | |

Relationships: 1-n EquipmentLoan.
Evidence: RNT-14

### EquipmentLoan
Purpose: a checked-out unit against a client and POS sale.

| field | type guess | notes / allowed values |
|---|---|---|
| equipment_item_id | fk | |
| client_id | fk | mandatory |
| sale_line_id | fk | POS cluster |
| quantity | int | |
| checked_out_at | timestamptz | |
| due_at | timestamptz | derived from max_loan_days + due_time (inferred) |
| returned_at | timestamptz null | |
| status | enum | OUT, RETURNED, OVERDUE (derived) |

Relationships: n-1 Client ("Check Out Items" list on profile).
Evidence: RNT-15, RNT-16

### LockerLease
Purpose: assignment of a locker to a client for a term.

| field | type guess | notes / allowed values |
|---|---|---|
| locker_id | fk | resources cluster |
| client_id | fk | |
| term | enum/fk | DAY, WEEK, YEAR or custom LockerTerm |
| fee | numeric | predefined or manual; 0 for no charge |
| starts_on / expires_on | date | expiry derived from term (inferred) |
| invoice_line_id | fk null | null while in cart or no charge |
| cleared_at | timestamptz null | manual or bulk "Clear Expired" |

Relationships: n-1 Locker; n-1 Client.
Evidence: RNT-17, RNT-18

### PublicClassListing
Purpose: static class/clinic card on the public league site.

| field | type guess | notes / allowed values |
|---|---|---|
| title | text | required |
| sport | fk/text | required |
| start_date | date | required |
| description | text | required |
| registration_url | text null | link to a Group registration page |

Relationships: optional soft link to Group (registration cluster).
Evidence: CLS-07

### Enumerations (consolidated)
- ReservationKind: SESSION, RENTAL, SPECIAL
- SpecialSubtype: FLOOR_HOURS, PROGRAM_INSTRUCTION, UNPAID_TIME, UNAVAILABLE
- RecurrencePattern: SINGLE, DAILY, WEEKLY, BIWEEKLY, MONTHLY_BY_DATE, YEARLY, NTH_WEEKDAY_OF_MONTH
- RecurrenceRange: COUNT, UNTIL_DATE
- SplitInterval: 15, 30, 45, 60 (+ further increments, list not exhaustive in source)
- DeleteScope: THIS_ONE, ALL_LINKED, TODAY, PAST, FUTURE, CUSTOM
- FillState: EMPTY, PARTIAL, FULL
- ConflictPreviewState: CLEAR (green), CONFLICT (orange)
- CalendarView: DAY_BY_RESOURCE (Datebook), TIMELINE_DAY, TIMELINE_WEEK, TIMELINE_MONTH, plus NSE RESOURCE, DAY, WEEK, MONTH
- BookScope: SINGLE ("This Package"), ALL_LINKED ("All Sessions"), CUSTOM
- BookingStatus: RESERVED, SCHEDULED, ATTENDED, WAITLISTED (+ CANCELLED, NO_SHOW inferred); EARLY_CANCELLED seen in video
- ListingMode: LISTED, UNLISTED
- RateBasis: PER_HOUR, PER_OCCURRENCE, FLAT
- MultiResourceQtyMode: ONCE, PER_RESOURCE
- LineGrouping: COMBINED, PER_RESOURCE, PER_OCCURRENCE, PER_RESOURCE_OCCURRENCE
- RentalChargeDecision: ADD_TO_CART, NO_CHARGE
- InvoiceRouting: NEW_SINGLE, NEW_PER_LINE, DATE_BASED, EXISTING_OPEN, CART (all four staff options confirmed for rentals in NSE)
- RentalPlanModel: PER_HOUR, PER_OCCURRENCE
- TermsAckMode: FIRST_PURCHASE, EVERY_PURCHASE
- LockerTerm: DAY, WEEK, YEAR, CUSTOM
- CalendarSyncProvider: GOOGLE, OUTLOOK
- RentalAccess: ADMIN_ONLY, SELF_BOOK
- RentalClientEligibility: ALL_CLIENTS, MEMBERS_ONLY
- RateRuleKind: RATE, DISCOUNT
- RentalPlanRemovalMode: REVERSE_BILLING_AND_REMOVE, DELETE_KEEP_BILLING
- WaitlistMode: AUTO_QUEUE, OPEN_FIRST_CLICK (member app setting)
- BufferMinutes: 5 up to 60 (exact step list not shown)

## Clients, Households, Waivers & Documents, Fitness Assessments

All entities carry `tenant_id` (RLS), `id`, `created_at`, `updated_at` unless noted. "Their label" = EZFacility UI term.

### Client
Person record; the aggregate root for this cluster. One per individual.

| field | type guess | notes / allowed values |
|---|---|---|
| first_name, last_name | text | always required, policy-locked |
| gender | enum/text | their label "Gender" (was "Sex" before 2024-05); tenant default value |
| date_of_birth | date | drives birthday views |
| phones (home, cell, work) | text | "Mobile Phone" label in UK |
| address fields | text | standard postal block (inferred) |
| organization | text | company name; surfaced on invoices report and POS |
| home_location_id | fk Location | warning when paying elsewhere |
| category_id | fk ClientCategory, null | single-valued |
| referral_category_id | fk ReferralCategory, null | |
| referral_source | text | free text |
| default_trainer_id | fk User, null | list filter + access scoping |
| default_salesperson_id | fk User, null | list filter + access scoping |
| custom_1 .. custom_6 | text | labels from CustomFieldDefinition; we would model as jsonb keyed by definition id |
| photo_asset_id | fk File, null | webcam/upload; client-editable if location allows |
| sms_opt_in | bool | their "SMS subscription" |
| sms_carrier | text, null | their "Service Provider"; not needed with a real SMS gateway |
| global_discount_pct | numeric(5,2) | carries to POS |
| waiver_on_file | bool | their profile "waiver" checkbox: auto-set by group-registration acceptance and by an active Smartwaiver waiver (auto-cleared when all expire), manual otherwise; we would derive it (DOC-15) |
| comments, medical_conditions | text | staff note sections; group-registration notes are appended to comments tagged with the group name |
| legacy_membership_number / type / start / end | text/date | their "Simple Membership" block; belongs to Memberships module, listed for completeness |
| status | enum | active, disabled (their Classic label: deleted), merged (ours, inferred) |
| merged_into_id | fk Client, null | ours |
| created_by, modified_by | fk User | shown on profile |
| last_accessed (per user) | separate table | powers Recently Accessed |

- Relationships: 1-n ClientEmail, EmergencyContact, ClientActivity, ClientTask, ClientDocument, AssessmentEntry; n-n Tag via ClientTag; n-n Client via ClientRelationship; 0-1 PortalAccount.
- Evidence: CLI-01, CLI-02, CLI-03, CLI-14, CLI-17, CLI-19

### ClientEmail
Multiple addresses per client with verification and consent.

| field | type guess | notes |
|---|---|---|
| client_id | fk | |
| address | citext | not unique across clients (parent/child may share) |
| is_primary | bool | (inferred) |
| verified_at | timestamptz, null | verification mail sent on create |
| subscriptions | jsonb / child rows | per-address subscription flags; type list unknown |
| suppressed_reason | enum, null | bounce, spam (engagement module owns suppression) |

- Relationships: n-1 Client.
- Evidence: CLI-01, CLI-02, CLI-16

### ClientFieldPolicy
Per-field, per-context visibility/requirement (their "Contact Preferences").

| field | type guess | notes |
|---|---|---|
| field_key | text | built-in field or custom slot |
| context | enum | staff_create (their "Client Options"/"Client Profiles"), group_registration ("Online Registration Options"), portal_completion ("Self-Service Options") |
| state | enum | hidden, optional, required, locked |

- Relationships: tenant-scoped; unique (tenant, field_key, context).
- Evidence: CLI-04

### CustomFieldDefinition
Label for a tenant-defined client field.

| field | type guess | notes |
|---|---|---|
| slot | smallint | 1..6 in source; we would not hard-cap |
| label | text | slot inactive until labelled |
| display_column | enum | left (1-3), right (4-6) in source |

- Relationships: referenced by ClientFieldPolicy.field_key and Client custom values.
- Evidence: CLI-05

### ClientCategory
Single primary segment per client.

| field | type guess | notes |
|---|---|---|
| name | text | unique per tenant |

- Relationships: 1-n Client. Consumed by campaigns, billing statements, reports.
- Evidence: CLI-06

### ReferralCategory
Acquisition-channel list.

| field | type guess | notes |
|---|---|---|
| name | text | |

- Relationships: 1-n Client.
- Evidence: CLI-07

### Tag / ClientTag
Multi-valued labels in three families.

| field | type guess | notes |
|---|---|---|
| kind | enum | sport (system preset), season (Fall, Spring, Summer, Winter), custom |
| label | text | custom tags tenant-wide once created |
| client_id, tag_id (ClientTag) | fk | their "Active" list |

- Relationships: n-n Client.
- Evidence: CLI-08

### EmergencyContact

| field | type guess | notes |
|---|---|---|
| client_id | fk | |
| position | smallint | 1 or 2 (max two in source) |
| name, phone, relationship | text | sub-fields inferred |

- Relationships: n-1 Client.
- Evidence: CLI-18

### ActivitySubject
Reusable subject vocabulary for activities and tasks.

| field | type guess | notes |
|---|---|---|
| text | text | |

- Evidence: CLI-10

### ClientActivity
Logged interaction, optionally with a staff-only attachment.

| field | type guess | notes |
|---|---|---|
| client_id | fk | |
| type | enum | phone, email, task, other |
| subject_id | fk ActivitySubject | |
| user_id | fk User | performer |
| message | text | |
| attachment_asset_id | fk File, null | internal only |
| occurred_at | timestamptz | |

- Relationships: n-1 Client, User.
- Evidence: CLI-09

### ClientTask
Assigned follow-up. Could be a ClientActivity subtype; kept separate because of lifecycle.

| field | type guess | notes |
|---|---|---|
| client_id | fk | |
| subject_id | fk ActivitySubject | |
| assignee_id | fk User | header counter per assignee |
| status | enum | values not published; assume open, in_progress, completed, cancelled |
| due_on | date | |
| completed_on | date, null | |
| message | text | |
| attachment_asset_id | fk File, null | |
| email_reminder | bool | reminder email to the assignee (legacy-era video only) |

- Evidence: CLI-11

### ClientAlert
Staff-facing note surfaced on open/check-in. Blog-level evidence only.

| field | type guess | notes |
|---|---|---|
| client_id | fk | |
| kind | enum | note, injury, system (birthday, past_due, expired derived, not stored) |
| text | text | |
| show_at | set | profile, check_in (inferred) |

- Evidence: CLI-20

### ClientMergeLog
Audit of a merge operation (ours; source has no visible log).

| field | type guess | notes |
|---|---|---|
| survivor_id | fk Client | |
| merged_ids | uuid[] | |
| field_backfill | jsonb | which blanks were filled; never card data |
| performed_by, performed_at | fk / ts | |

- Evidence: CLI-13

### PortalAccount
Self-service credential state for a client.

| field | type guess | notes |
|---|---|---|
| client_id | fk, unique | |
| enabled | bool | requires an email |
| username | text | chosen by client |
| invite_sent_at | timestamptz | |
| last_password_reset_by | fk User, null | staff-initiated reset |

- Relationships: 1-1 Client; in our design maps to Platform-core identity (OIDC/magic link) with a client link.
- Evidence: CLI-15

### RelationshipType
Directed type with inverse.

| field | type guess | notes |
|---|---|---|
| code | text | evidenced: child_of, parent_of (also set automatically for minors on a Smartwaiver waiver), spouse; sibling and parent named in the rental-plan sharing demo; full list unpublished |
| inverse_code | text | |
| implies_guardianship | bool | ours, for minor signing/booking rules |

- Evidence: FAM-01

### ClientRelationship
Pairwise directed link; non-transitive.

| field | type guess | notes |
|---|---|---|
| from_client_id | fk | |
| to_client_id | fk | |
| type_code | fk RelationshipType | read from -> to |
| status | enum | active, pending_confirmation (portal link to an existing account) |
| created_via | enum | staff, portal |
| confirmed_at | timestamptz, null | |

- Relationships: store one row per pair and derive the inverse; unique (from, to).
- Evidence: FAM-01, FAM-02, FAM-03

### EntitlementShare
Grants another client use of a sold membership contract, package or rental plan.

| field | type guess | notes |
|---|---|---|
| entitlement_type | enum | membership_contract, package, rental_plan |
| entitlement_id | uuid | owning modules hold the entitlement |
| client_id | fk | sharer; need not be related |
| source | enum | manual, auto_on_sale |
| revoked_at | timestamptz, null | (inferred) |

- Relationships: n-1 Client; polymorphic to Memberships/Packages/Rentals modules.
- Evidence: FAM-04, FAM-05, FAM-06

### DocumentTemplate
Authorable waiver/policy text.

| field | type guess | notes |
|---|---|---|
| document_type | enum | client_document, gdpr_consent (max one active per tenant) |
| name | text | shown in binding dropdowns |
| description | varchar(240) | doubles as subject line |
| body | text (rich) | |
| acceptance_text | varchar(1000) | |
| version | int | ours; source shows no versioning |
| last_used_at | timestamptz | drives recent list |
| archived_at | timestamptz, null | source hard-deletes |

- Relationships: 1-n ClientDocument, ServiceDocumentBinding.
- Evidence: DOC-01, DOC-09

### ServiceDocumentBinding
Which template a sale must have accepted.

| field | type guess | notes |
|---|---|---|
| scope | enum | membership_plan (one per plan), package_plan (one per plan; staff-side acceptance only in source), group_registration_global (one per tenant), rental_plan_terms (video-confirmed, via self-service terms acknowledgment); not available for rentals or POS items |
| scope_id | uuid, null | plan id; null for global |
| template_id | fk DocumentTemplate | |
| custom_text | text, null | self-service terms acknowledgment may use custom text instead of a template |
| frequency | enum | once_at_sale, first_purchase, every_purchase (latter two evidenced only for rental plan terms) |

- Evidence: DOC-08, DOC-14

### ClientDocument
An issued instance of a template for one client.

| field | type guess | notes |
|---|---|---|
| client_id | fk | |
| template_id, template_version | fk / int | snapshot rendered body + hash (ours) |
| location_id | fk | history filter |
| name, description | text | copied from template |
| acceptance_method | enum | paper, digital_checkbox (their "Digital Copy"), digital_signature, email |
| status | enum | pending, signed, declined, deleted (all four shown in New-UI history; deleted is recoverable for 30 days), expired (ours), voided (ours) |
| deleted_at | timestamptz, null | soft delete with 30-day recovery window |
| accepted_at | timestamptz, null | |
| co_signer_name | text, null | free text in source; we add co_signer_client_id |
| signature_text | text, null | name typed by the client on the emailed path, stored as the signature |
| guardian_signature_asset_id | fk File, null | New-UI signature view takes a child signature and a separate guardian signature |
| signature_asset_id | fk File, null | drawn signature image |
| uploaded_pdf_asset_id | fk File, null | paper path, PDF only |
| paper_signed | bool | |
| source_context | enum | manual, membership_sale, group_registration, bulk_audit, gdpr, external_provider |
| source_ref_id | uuid, null | contract/registration id |
| ip, user_agent | text | IP address, timestamp and generating staff user are shown on the source's acceptance record; user agent is ours |
| generated_by | fk User | staff user who issued the document |
| provider_expires_at, provider_participant_count, provider_has_minors | timestamptz / int / bool | only for external_provider rows (Smartwaiver table columns) |

- Relationships: n-1 Client, DocumentTemplate; 1-n DocumentDelivery.
- Evidence: DOC-02..DOC-09, DOC-13

### DocumentDelivery
Emailed acceptance link.

| field | type guess | notes |
|---|---|---|
| client_document_id | fk | |
| sent_to | citext[] | chosen from client's addresses |
| token_hash | text | ours |
| sent_at, expires_at | timestamptz | 24h vs 48h in sources; make tenant-configurable |
| outcome | enum | none, accepted, declined, expired |

- Evidence: DOC-04, DOC-07, DOC-09

### LocationPrivacySettings
Location-level consent switches.

| field | type guess | notes |
|---|---|---|
| location_id | fk | |
| gdpr_enabled | bool | requires a GDPR template |
| client_can_edit_photo | bool | setting name unpublished |

- Evidence: DOC-09, CLI-12

### AgreementTemplate (legacy)
Classic three-section membership agreement. Likely collapsed into DocumentTemplate in our build.

| field | type guess | notes |
|---|---|---|
| contract_fields | jsonb | include flag + label per contract field |
| contract_text, autopay_text, terms_text | text | |
| required_signers | jsonb | per section: contract_owner, other_contract_users, invoice_holder |
| warn_missing_signature | bool | |
| allow_online | bool | |

- Evidence: DOC-10

### MembershipAgreement (legacy)
Per-contract executed agreement.

| field | type guess | notes |
|---|---|---|
| contract_id | fk | Memberships module |
| signed | bool | manual toggle when no pad |
| signatures | jsonb | per signer role, image ref |
| exported_formats | n-a | Word, PDF generated on demand |

- Evidence: DOC-11, DOC-12

### WaiverProviderConnection
Adapter config for an external waiver provider.

| field | type guess | notes |
|---|---|---|
| provider | enum | smartwaiver |
| location_id | fk | default routing target |
| api_key_ref | secret ref | provider API v4 key; shown once at provider |
| active | bool | |
| email_validation | bool | Yes = hold the waiver until the signer confirms their email; overridable per waiver at the provider |
| template_routes | jsonb | provider template id -> location (configured provider-side in source) |

- Relationships: produces ClientDocument rows with source_context external_provider and creates/updates Client.
- Evidence: DOC-13

### AssessmentCategory

| field | type guess | notes |
|---|---|---|
| name | text | |
| sort_order | int | ours |

- Evidence: FIT-01

### AssessmentField

| field | type guess | notes |
|---|---|---|
| category_id | fk AssessmentCategory | exactly one |
| name | text | |
| decimal_places | smallint | |
| unit, direction (higher_is_better) | text / bool | ours; needed for personal bests |
| archived_at | timestamptz, null | ours; source deletes |

- Evidence: FIT-01

### AssessmentEntry / AssessmentValue
A dated measurement session and its values.

| field | type guess | notes |
|---|---|---|
| client_id | fk | |
| recorded_at | timestamptz | their "Assessment Date and Time" |
| recorded_by | fk User | ours |
| field_id (value row) | fk AssessmentField | |
| value (value row) | numeric | rounded to field precision |

- Relationships: Entry 1-n Value; summary report = per field, first value at/before start (within max age) vs value at/before end.
- Evidence: FIT-02, FIT-03, FIT-04, FIT-05

### Enumerations (consolidated)
- Client list views: recently_accessed, recently_created, birthdays_this_month, birthdays_next_month, all_members, all_contacts, search_results, deleted, possible_duplicates, no_category, category:<id>.
- Field policy state: hidden, optional, required, locked. Contexts: staff_create, group_registration, portal_completion.
- Activity type: phone, email, task, other.
- Tag kind: sport, season, custom. Seasons: Fall, Spring, Summer, Winter.
- Document type: client_document, gdpr_consent.
- Acceptance method: paper, digital_checkbox, digital_signature, email.
- Document status: pending, signed, declined, deleted (New-UI history, video); expired and voided are ours.
- Agreement signer roles: contract_owner, other_contract_users, invoice_holder. Agreement sections: contract, autopay, terms.
- Agreement export formats: Word, PDF.
- Client status: active, disabled/deleted.

## Memberships, Packages & Sessions

All tables carry `tenant_id` (RLS) and `location_id` where location-scoped; omitted below. Money = integer minor units + tenant currency. Dates that define access/billing days are `date` in the location time zone; event timestamps are `timestamptz` UTC.

### MembershipType
Reporting/GL grouping for plans and contracts.

| field | type guess | notes / allowed values |
|---|---|---|
| id | uuid | |
| name | text | unique per tenant |
| revenue_category_id | fk | required; their label "Revenue Category" |
| sort_order | int | manual ordering |
| archived_at | timestamptz null | soft delete (ours) |

- Relationships: 1..n MembershipPlan; 1..n MembershipContract; n..1 RevenueCategory (billing).
- Evidence: MEM-01

### MembershipPlan
Sellable template for contracts ("advanced" plan).

| field | type guess | notes / allowed values |
|---|---|---|
| id | uuid | |
| membership_type_id | fk | |
| description | text | display name |
| fixed_start_date | date null | forces all contracts to this start |
| billing_interval_unit | enum | BillingIntervalUnit; month and year confirmed |
| billing_interval_count | int | default 1 (ours; source only shows unit) |
| billing_occurrences | int | their "Duration" / "Bill How Many Times" |
| auto_renew_lead | interval null | null = no auto-renew |
| renews_as_plan_id | fk self null | null = RenewalTarget.copy_of_contract |
| default_document_id | fk null | document template (waivers/documents module) |
| max_visits | int null | per term; null = unlimited |
| initiation_fee | money | first invoice only |
| term_fee | money | "Fee Billed Each Term" |
| payment_due_day | smallint | also autopay charge day |
| default_discount | jsonb null | percent or flat (shape not documented) |
| revenue_category_id | fk null | plan-level override of type's category (inferred) |
| default_invoice_option | enum | PlanInvoiceOption |
| default_autopay | bool | |
| additional_description | text | customer-facing; max 100 chars, prints on the client invoice (video) |
| sell_online | bool | |
| proration_mode | enum | ProrationMode |
| proration_tail | enum null | ProrationTail; set when mode = to_first_of_month |
| sort_order | int | |
| archived_at | timestamptz null | ours |

- Relationships: n..1 MembershipType; 0..n MembershipPlanAddOn; 0..n MembershipContract (source plan); self-reference for renewal chaining.
- Evidence: MEM-02, MEM-03, MEM-09, MEM-11

### MembershipPlanAddOn
Package plan or pre-defined item bundled into a plan.

| field | type guess | notes / allowed values |
|---|---|---|
| id | uuid | |
| plan_id | fk | |
| addon_kind | enum | package_plan / predefined_item |
| package_plan_id | fk null | |
| predefined_item_id | fk null | billing/POS catalogue item |
| sort_order | int | |

- Relationships: n..1 MembershipPlan; n..1 PackagePlan or catalogue item. Copied per sale into ContractAddOn rows (ours) so per-sale edits do not touch the plan.
- Evidence: MEM-04

### MembershipSettings
Tenant-level policy row (their "Membership Preferences").

| field | type guess | notes / allowed values |
|---|---|---|
| require_status_change_remark | bool | covers freeze / suspend / cancel |
| auto_generate_member_number | bool | |
| payment_method_capture | enum | PaymentCaptureMode |
| one_visit_per_day_rule | bool | access rule for visit-limited contracts (owned jointly with check-in) |
| over_daily_limit_alert | bool | self-check-in alert |
| online_card_save_mode | enum | OnlineCardSaveMode; card storage rule for online membership sales (their self-service preference; video) |

- Relationships: 1..1 Tenant (or per location, undecided).
- Evidence: MEM-05, MEM-20

### MembershipContract
One sold term of membership for an owning client; renewals create successor rows.

| field | type guess | notes / allowed values |
|---|---|---|
| id | uuid | |
| owner_client_id | fk | billed party |
| source_plan_id | fk null | null for Classic-style manual contracts |
| membership_type_id | fk | snapshot |
| description | text | snapshot |
| sold_by_user_id | fk | salesperson |
| referred_by_client_id | fk null | must be an existing client |
| start_date | date | |
| end_date | date | derived from cadence x occurrences unless overridden |
| billing_interval_unit / count / occurrences | enum / int / int | snapshot; explicit end date collapses to days x 1 |
| term_fee | money | snapshot (price lock for copy renewals) |
| initiation_fee | money | |
| revenue_date | date null | editable only when occurrences = 1 |
| payment_due_day | smallint | |
| max_visits | int null | editable while active |
| autopay | bool | switched off by freeze |
| auto_renew_enabled | bool | off by freeze or member opt-out |
| auto_renew_lead | interval null | |
| renews_as_plan_id | fk null | null = copy |
| renewal_discount | jsonb null | percent or flat, description, internal remark |
| renewal_additional_description | text null | |
| renewal_internal_remark | text null | |
| prorated | bool | plus computed first-period amount |
| coupon_id | fk null | |
| additional_discount | money null | |
| internal_notes | text | |
| invoice_option | enum | SaleInvoiceOption |
| sales_channel | enum | staff / portal / app / pos (ours) |
| previous_contract_id | fk self null | renewal chain |
| status | enum (derived) | ContractStatus; derive from dates + status events, do not store free-hand |
| cancelled_on | date null | |
| cancel_reason | enum null | CancelReason |
| auto_renew_disabled_by | enum null | staff / member (ours, for audit) |
| created_at | timestamptz | UTC |

- Relationships: n..1 Client (owner); 0..n ContractCoverage (shared clients); 0..n ContractStatusEvent; 1..n ContractBillingPeriod; 0..n ContractAddOn -> ClientPackage; 0..1 ContractAcceptance; 0..n MembershipVisit; successor/predecessor self-links. Constraint (video): one active contract per owning client; a future-dated successor may be queued behind it.
- Evidence: MEM-07, MEM-10, MEM-11, MEM-15, MEM-17, MEM-22

### ContractBillingPeriod
Scheduled charge for one billing period of a contract (their un-invoiced "billing item"); owned here, invoiced by the billing module.

| field | type guess | notes / allowed values |
|---|---|---|
| id | uuid | |
| contract_id | fk | |
| sequence | int | 1..occurrences |
| period | daterange | service period covered |
| due_date | date | |
| revenue_date | date | drives recognition in the deferred-revenue report |
| amount | money | includes proration; initiation fee as separate line on sequence 1 |
| kind | enum | dues / initiation / suspension_fee / addon_item |
| invoice_line_id | fk null | null = un-invoiced |
| state | enum | scheduled / invoiced / withdrawn_by_freeze / reversed / void |

- Relationships: n..1 MembershipContract; 0..1 InvoiceLine (billing).
- Evidence: MEM-07, MEM-13, MEM-21

### ContractStatusEvent
Dated freeze, suspension or cancellation applied to a contract (their "status change history").

| field | type guess | notes / allowed values |
|---|---|---|
| id | uuid | |
| contract_id | fk | |
| kind | enum | StatusEventKind |
| effective | daterange | open upper bound allowed for freeze/suspension; cancel = single date |
| fee | money null | suspension only; charged on top of normal dues, never on a freeze (video) |
| resume_invoicing | enum null | FreezeResumeInvoicing; chosen when a freeze end date is saved (video) |
| reason | enum null | CancelReason, cancel only |
| remarks | text null | required when settings demand |
| created_by / created_at | fk / timestamptz | |
| removed_by / removed_at | fk / timestamptz null | soft removal with its own remark |

- Relationships: n..1 MembershipContract. Constraint: no overlapping freeze/suspension periods per contract (exclusion on contract_id, effective). A freeze shifts the contract end_date out by its duration and billing restarts on the freeze end date; a suspension moves no dates (video).
- Evidence: MEM-12, MEM-13, MEM-14, MEM-15

### ContractCoverage
Additional clients covered by a shared contract.

| field | type guess | notes / allowed values |
|---|---|---|
| contract_id | fk | |
| client_id | fk | related or unrelated client |
| added_by / added_at | fk / timestamptz | |

- Relationships: n..1 MembershipContract; n..1 Client. Owner is implicit; covered-client count and total billed are derived.
- Evidence: MEM-17, MEM-22

### ContractAcceptance
Proof that the buyer agreed to the plan's document.

| field | type guess | notes / allowed values |
|---|---|---|
| contract_id | fk | |
| document_template_id | fk | version pinned |
| method | enum | AcceptanceMethod |
| state | enum | pending / accepted / declined |
| client_document_id | fk null | stored signed copy |
| signed_at | timestamptz null | |

- Relationships: 1..1 MembershipContract; n..1 DocumentTemplate; 0..1 ClientDocument (documents module).
- Evidence: MEM-08

### SimpleMembership
Record-only member flag without billing.

| field | type guess | notes / allowed values |
|---|---|---|
| client_id | fk | |
| membership_type_id | fk | |
| start_date / expires_on | date / date null | |
| fee_memo / initiation_memo / payment_memo | text | informational only |
| notes | text | |

- Relationships: n..1 Client; n..1 MembershipType. Member status = active SimpleMembership OR covering active MembershipContract.
- Evidence: MEM-06

### MemberNumber
Scannable identifier of a client (their "Membership #"); may exist without any membership.

| field | type guess | notes / allowed values |
|---|---|---|
| client_id | fk | one current number per client |
| value | text | alphanumeric; unique per tenant |
| source | enum | generated / manual / scanned_tag |
| assigned_at | timestamptz | |

- Relationships: 1..1 Client. Card/RFID media are adapter-side credentials pointing at this value.
- Evidence: MEM-19

### MembershipVisit
Check-in counted against a contract's visit cap.

| field | type guess | notes / allowed values |
|---|---|---|
| contract_id | fk | resolved covering contract |
| client_id | fk | who entered (owner or covered client) |
| checkin_id | fk | check-in module record |
| visited_at | timestamptz | |
| local_day | date | location-local, for the daily rule |

- Relationships: n..1 MembershipContract; 1..1 CheckIn.
- Evidence: MEM-20

### PackagePlan
Sellable template for session credits bound to one reservation type.

| field | type guess | notes / allowed values |
|---|---|---|
| id | uuid | |
| kind | enum | PackageKind (individual / recurring); post-billed is rate-driven, see PostBilledRate |
| reservation_type_id | fk | scheduling module |
| description | text | |
| session_mode | enum | SessionMode |
| session_count | int null | fixed multiple |
| min_sessions / max_sessions | int null | buyer-chosen range |
| is_comp | bool | reporting only |
| category | enum | paid / free |
| fee | money null | |
| fee_basis | enum null | per_session / per_package; single forces per_session |
| start_rule | enum | sale_date / fixed_date |
| fixed_start_date | date null | |
| validity_length | interval null | their "Package Length" |
| allow_booking_after_expiry | bool | their "Booking Out of Range" |
| auto_renew_lead | interval null | must be <= validity_length |
| renews_as | enum + fk null | copy / this_plan / other_plan |
| renewal_threshold | int null | sessions remaining |
| share_with | enum | none / all_related_clients (relationship filter possible) |
| recurrence_unit / recurrence_interval | enum / int null | recurring only: day, week, month, year |
| recurrence_occurrences | int null | "End After Occurrences" |
| recurring_auto_renew | bool null | |
| default_invoice_option | enum | PackageInvoiceOption |
| default_autopay | bool | |
| sell_online | enum | OnlineSaleMode |
| members_only_online | bool | |
| discount | jsonb null | |
| revenue_category_id | fk null | |
| default_document_id | fk null | |
| additional_description / internal_remarks | text | |

- Relationships: n..1 ReservationType; 0..n ClientPackage; 0..n MembershipPlanAddOn.
- Evidence: PKG-01, PKG-02, PKG-03, PKG-04, PKG-05, PKG-06, PKG-09, PKG-10

### PostBilledRate
Usage rate for bill-after-use packages.

| field | type guess | notes / allowed values |
|---|---|---|
| id | uuid | |
| reservation_type_id | fk | |
| min_sessions | int | "with at least" |
| per_session_amount | money | |
| extra_item_ids | fk[] | pre-defined items added per billed session |

- Relationships: n..1 ReservationType; 0..n ClientPackage (post-billed).
- Evidence: PKG-11

### ClientPackage
A package owned by a client: balance, validity and renewal state (their "package").

| field | type guess | notes / allowed values |
|---|---|---|
| id | uuid | |
| owner_client_id | fk | |
| plan_id | fk null | null for ad-hoc packages |
| billing_mode | enum | prepaid / post_billed |
| reservation_type_id | fk | snapshot |
| description | text | snapshot |
| sessions_purchased | int null | null = unlimited or post-billed |
| valid | daterange | start/end |
| allow_booking_after_expiry | bool | snapshot |
| price / fee_basis | money / enum | snapshot after customisation |
| sold_by_user_id | fk | |
| coupon_id | fk null | |
| share_with | enum | none / all_related_clients / explicit |
| autopay | bool | |
| auto_renew_enabled | bool | member can switch off |
| renewal_threshold | int null | |
| post_billed_rate_id | fk null | |
| source_contract_id | fk null | set when granted as a membership add-on |
| recurrence_series_id | uuid null | groups occurrences of a recurring plan |
| previous_package_id | fk self null | renewal chain |
| state | enum | PackageState |
| closed_at | timestamptz null | post-billed close |
| removed_at / removal_mode | timestamptz / enum null | reversed_billing / kept_billing |

- Relationships: n..1 Client; n..1 PackagePlan; 0..n PackageShare; 0..n SessionCreditEntry; 0..n InvoiceLine; 0..1 MembershipContract.
- Derived: sessions_scheduled, sessions_completed, sessions_remaining (from the ledger).
- Evidence: PKG-07, PKG-11, PKG-13, PKG-14, PKG-16

### PackageShare
Client authorised to draw on someone else's package.

| field | type guess | notes / allowed values |
|---|---|---|
| package_id | fk | |
| client_id | fk | |
| origin | enum | plan_preset / post_sale |

- Relationships: n..1 ClientPackage; n..1 Client.
- Evidence: PKG-06

### SessionCreditEntry
Append-only ledger of credit movements on a package (ours; their UI shows purchased / remaining / scheduled counts).

| field | type guess | notes / allowed values |
|---|---|---|
| id | uuid | |
| package_id | fk | |
| registration_id | fk null | session registration that caused it |
| client_id | fk | consuming client (owner or sharer) |
| delta | int | +grant, -reserve/consume, +release |
| reason | enum | CreditReason |
| occurred_at | timestamptz | |

- Relationships: n..1 ClientPackage; 0..1 SessionRegistration.
- Evidence: PKG-12, PKG-14

### SessionRegistration
A client's place in a scheduled session, paid by a package (roster row). Session/reservation itself is owned by scheduling.

| field | type guess | notes / allowed values |
|---|---|---|
| id | uuid | |
| session_id | fk | scheduling module |
| client_id | fk | |
| package_id | fk null | funding package |
| state | enum | RegistrationState |
| attendance | enum | AttendanceMark |
| booked_by | fk | staff user or client |
| booking_scope | enum | single / all_linked / custom (audit of how it was booked) |

- Relationships: n..1 Session; n..1 Client; 0..1 ClientPackage; 1..n SessionCreditEntry.
- Evidence: PKG-12

## Enumerations

| enum | values | source notes |
|---|---|---|
| BillingIntervalUnit | month, year (confirmed); day (arises when an end date is forced); week (inferred) | MEM-02, MEM-07 |
| RenewalTarget | copy_of_contract, named_plan (may be the same plan) | MEM-11 |
| PlanInvoiceOption | no_default, multiple_invoices, single_invoice | MEM-02 |
| SaleInvoiceOption | invoice_now_per_item, invoice_now_single, invoice_later, leave_in_cart | MEM-07 |
| ProrationMode | none, to_first_of_next_month, seller_choice | MEM-03 |
| ProrationTail | extend_last_term_to_full_month, drop_last_partial_term, prorate_final_term | MEM-03 |
| PaymentCaptureMode | hidden, optional, required | MEM-05 |
| ContractStatus | upcoming, active, frozen, suspended, expired, cancelled | MEM-10; reports label upcoming as "pending" (video) |
| StatusEventKind | freeze, suspension, cancellation | MEM-12, MEM-14, MEM-15 |
| CancelReason | voluntary, upgrade, downgrade, administrative_error (excluded from attrition), other_modification | MEM-15 |
| AcceptanceMethod | paper_upload, digital_checkbox, digital_signature, email_link | MEM-08 |
| RefundMethod | original_card, different_card, external_manual (direct debit always manual) | MEM-16 |
| MembershipKind | simple, advanced | MEM-06 |
| MembershipAlert | depleted, over_daily_limit (lowest priority); frozen and suspended markers | MEM-20 |
| PackageKind | individual, recurring | PKG-01, PKG-03 |
| PackageBillingMode | prepaid, post_billed | PKG-11 |
| SessionMode | single, multiple_fixed, multiple_range, unlimited | PKG-01 |
| PackageCategory | paid, free | PKG-02 |
| FeeBasis | per_session, per_package | PKG-01 |
| PackageInvoiceOption | no_default, single_invoice, multiple_invoices (recurring only), leave_in_cart | PKG-01, PKG-03 |
| OnlineSaleMode | no, yes_allow_balance, yes_paid_in_full | PKG-09 |
| RecurrenceUnit | day, week, month, year | PKG-03 |
| PackageRenewsAs | copy, this_plan, other_plan | PKG-05 |
| ShareWith | none, all_related_clients, explicit_clients | PKG-06 |
| PackageState | active, expired, depleted, open (post-billed), closed (post-billed), removed (inferred set; source shows only view filters) | PKG-14 |
| PackageDeleteChoice | reverse_billing, delete_keep_billing, show_billing, abort | PKG-13 |
| PackageViewFilter | all, reserved, waitlist | PKG-14 |
| RegistrationState | reserved, waitlisted, removed | PKG-12, PKG-14 |
| AttendanceMark | unmarked, attended, absent (values inferred; source only says attendance is marked). Video shows the real set: scheduled (default), attended, early_cancel, late_cancel, no_show; only attended is confirmed to consume a credit, early_cancel returns it | PKG-12 |
| OnlineCardSaveMode | always_require_and_save, save_when_nothing_due, ask_client (default when neither switch is on); the first overrides the second | MEM-09 |
| FreezeResumeInvoicing | invoice_per_item, single_invoice, leave_uninvoiced | MEM-13 |
| CreditReason | purchase_grant, addon_grant, renewal_grant, reserve, release, consume, expire, removal_reversal (ours) | PKG-12 |
| SessionCapacityState | empty, partial, full | PKG-12 |

## Billing & Invoicing, Payments & Merchant

Conventions: every table carries `tenant_id` (RLS) and `location_id` where location-scoped; money = `numeric(12,2)` + tenant currency; timestamps UTC. Their UI label is given in notes where ours differs.

### Charge
Purpose: one billable line owed by a client (their "billing item" / "billed item"); the unit taxes, revenue recognition and payment allocation attach to.

| field | type guess | notes / allowed values |
|---|---|---|
| id | uuid | |
| client_id | fk Client | beneficiary of the product |
| invoice_id | fk Invoice, nullable | null = uninvoiced (their "in cart") |
| source_type / source_id | enum + uuid | membership_contract, package, rental, registration, pos_sale, catalog_item, manual |
| description | text | |
| additional_description | text | client-visible, prints on invoice |
| internal_remarks | text | staff-only |
| quantity | numeric | sessions for per-session pricing |
| unit_price | money | their "Price Per Session" |
| discount_type | enum | none, amount, percent |
| discount_value | numeric | |
| coupon_id | fk Coupon, nullable | |
| revenue_category_id | fk RevenueCategory | defaulted from source type, overridable |
| bill_date | date | when the charge was created |
| revenue_date | date | drives tax rate selection and revenue reports; editable |
| net_amount / tax_amount / total_amount | money | derived, stored |
| status | enum | active, reversed, voided |
| reversed_at / reversal_reason / reversal_revenue_date | ts / text / date | reversal date mode: today, original_bill_date, custom |
| voided_at | ts | irreversible |
| created_by | fk User | also drives per-user cart scope |

- Relationships: Client 1-n Charge; Invoice 1-n Charge; Charge n-n TaxRate via ChargeTax; Charge 1-n PaymentAllocation; Charge 1-n BillingAuditEvent.
- Evidence: BIL-01, BIL-03, BIL-07, BIL-08, BIL-12, BIL-13

### ChargeTax
Purpose: snapshot of each tax applied to a charge (supports per-item opt-out and non-compounding multi-tax).

| field | type guess | notes / allowed values |
|---|---|---|
| charge_id | fk Charge | |
| tax_id | fk Tax | |
| rate_percent | numeric(6,3) | snapshot of rate effective at revenue_date |
| amount | money | computed on net amount, not on other taxes |
| removed | bool | true when staff unticked the tax on this item |

- Relationships: Charge 1-n ChargeTax; Tax 1-n ChargeTax.
- Evidence: BIL-01, BIL-12

### Invoice
Purpose: numbered grouping of charges billed to one payer, with due schedule and autopay flag.

| field | type guess | notes / allowed values |
|---|---|---|
| id | uuid | |
| number | text/int, unique per tenant | token {InvoiceNumber} in email subject |
| client_id | fk Client | original purchaser |
| bill_to_client_id | fk Client | payer; changeable (their "Bill to") |
| invoice_date | date | editable |
| status | enum | open, partially_paid, paid, voided (open/paid/voided evidenced; partially_paid inferred) |
| autopay | bool | defaulted from plan + account preference, switchable at payment |
| comments | text | |
| organization | text, nullable | company name surfaced on invoice report |
| created_by | fk User | |
| voided_at | ts | |
| total / balance | money | derived |

- Relationships: Invoice 1-n Charge; Invoice 1-n InvoiceInstalment; Invoice n-n Payment via PaymentAllocation (through charges); Invoice 1-n BillingAuditEvent. A Charge can be moved to another invoice by changing its invoice number; the emptied source invoice remains until a manager voids it (video).
- Evidence: BIL-02, BIL-04, BIL-05, BIL-08, BIL-17, BIL-23

### InvoiceInstalment
Purpose: one dated amount due on an invoice (their "Payments Due" / payment schedule row).

| field | type guess | notes / allowed values |
|---|---|---|
| id | uuid | |
| invoice_id | fk Invoice | |
| due_date | date | >= invoice_date |
| amount_due | money | sum over invoice = invoice amount due |
| sequence | int | |
| generated_from | jsonb, nullable | generator inputs: start_date, every_n, unit (day, week, half_month, month, year), count |
| collection_status | enum | pending, collected, failed (inferred, for autopay) |

- Relationships: Invoice 1-n InvoiceInstalment; AutopayAttempt n-1 InvoiceInstalment.
- Evidence: BIL-06, PAY-09

### Payment
Purpose: money received from (or returned to) a payer; their "payment" / "receipt".

| field | type guess | notes / allowed values |
|---|---|---|
| id | uuid | |
| receipt_number | text, unique per tenant | |
| payer_client_id | fk Client | |
| location_id | fk Location | warn if != client home location |
| kind | enum | payment, refund |
| amount | money | their "Total Received"; negative for refunds |
| applied_amount | money, derived | their "Total Applied" |
| method_id | fk PaymentMethodType | |
| card_brand / last4 | text | hidden without refund permission |
| memo | text | |
| processor_txn_id | text, nullable | joins to payout detail |
| terminal_id | fk PaymentTerminal, nullable | |
| origin | enum | staff, autopay, self_service, pos, api |
| status | enum | succeeded, failed, voided, pending (pending for ACH, inferred) |
| void_reason / voided_at / voided_by | text / ts / fk | |
| received_at | ts | |
| taken_by | fk User | |

- Relationships: Payment 1-n PaymentAllocation; Payment 1-n Refund (as original); Payment n-1 StoredPaymentMethod (nullable); Payment n-1 ProcessorPayout (nullable).
- Evidence: PAY-01, PAY-03, PAY-04, PAY-05, PAY-09

### PaymentAllocation
Purpose: amount of a payment applied to a specific charge (API name on their side: "Disbursements").

| field | type guess | notes / allowed values |
|---|---|---|
| id | uuid | |
| payment_id | fk Payment | |
| charge_id | fk Charge | |
| amount | money | |
| applied_at / unapplied_at | ts | "Unpay" removes the allocation |

- Relationships: Payment 1-n PaymentAllocation n-1 Charge. Unallocated payment remainder = account credit.
- Evidence: PAY-01, PAY-05, BIL-21, BIL-23

### Refund
Purpose: return of funds against an original payment or against account credit.

| field | type guess | notes / allowed values |
|---|---|---|
| id | uuid | |
| original_payment_id | fk Payment, nullable | null when refunding pooled account credit |
| refund_payment_id | fk Payment | the negative payment row |
| client_id | fk Client | "client to refund to" |
| amount | money | <= unapplied amount; read-only when several payments refunded together |
| method | enum | original_card, different_card, external, cash, check, other (last three inferred) |
| is_external | bool | recorded only; operator refunds in gateway portal |
| issue_date | date | editable for reporting |
| comments | text | |
| issued_by | fk User | requires refund permission |
| processor_refund_id | text, nullable | |

- Relationships: Payment 1-n Refund.
- Evidence: PAY-05, BIL-21

### ClientAccountCredit (derived view)
Purpose: spendable balance per client (their "On Account" / "Remaining" / "Money on Account").

| field | type guess | notes / allowed values |
|---|---|---|
| client_id | fk Client | |
| balance | money | sum(payments.amount) - sum(allocations) - sum(refunds) for non-voided payments |

- Relationships: derived from Payment, PaymentAllocation, Refund; consumed by POS tender and refund flow.
- Evidence: BIL-21, PAY-01, PAY-05

### BillingAuditEvent
Purpose: append-only history for charges and invoices (their "View History").

| field | type guess | notes / allowed values |
|---|---|---|
| id | uuid | |
| subject_type / subject_id | enum + uuid | charge, invoice, payment |
| action | enum | invoice_created, payment_taken, payment_applied, payment_unapplied, payment_voided, refund_issued, item_reversed, item_voided, discount_applied, schedule_changed, bill_to_changed, item_edited, invoice_voided, invoice_emailed |
| actor_user_id | fk User, nullable | null = system/autopay |
| at | ts | |
| before / after | jsonb | |
| reason | text | reversal and void reasons |

- Relationships: n-1 to Charge / Invoice / Payment.
- Evidence: BIL-09

### Tax
Purpose: named tax applied to charges.

| field | type guess | notes / allowed values |
|---|---|---|
| id | uuid | |
| code | text | free text, e.g. HST, PST, GST, VAT |
| label | text | |
| remarks | text | |
| active | bool | |
| deactivated_on | date | stops applying from this date |

- Relationships: Tax 1-n TaxRate; Tax n-n RevenueCategory.
- Evidence: BIL-12

### TaxRate
Purpose: effective-dated percentage for a tax.

| field | type guess | notes / allowed values |
|---|---|---|
| tax_id | fk Tax | |
| percent | numeric(6,3) | |
| effective_from | date | matched against charge.revenue_date |

- Relationships: Tax 1-n TaxRate.
- Evidence: BIL-12

### RevenueCategory
Purpose: accounting classification of charges with default taxes; hierarchical.

| field | type guess | notes / allowed values |
|---|---|---|
| id | uuid | |
| code | text, unique per tenant | alphanumeric; may mirror GL code |
| label | text | |
| remarks | text | |
| parent_id | fk RevenueCategory, nullable | their "Subcategory of" |
| active | bool | deactivated ones can be shown/reactivated |
| tax_ids | n-n Tax | empty = untaxed |

- Relationships: referenced by MembershipType, PackagePlan, RentalType/ReservationType, Group (optional cascade to subgroups), POS product, CatalogItem, Charge.
- Evidence: BIL-13

### CatalogItem
Purpose: reusable priced fee sold from a client profile (their "Pre-Defined Item" / "Generic Item").

| field | type guess | notes / allowed values |
|---|---|---|
| id | uuid | |
| location_id | fk Location | |
| kind | enum | individual, recurring |
| description | text | |
| start_mode / start_date | enum + date | sale_date, fixed_date |
| length_value / length_unit | int + enum, nullable | individual only |
| auto_renew | bool | |
| renew_lead_days | int | how far ahead the renewal is created |
| renews_as_item_id | fk CatalogItem | self or another item |
| recurrence_pattern | enum | daily, weekly, monthly, yearly |
| recurrence_every | int | |
| recurrence_count | int | "End After" N occurrences |
| fee | money | |
| default_invoice_option | enum | single_invoice, invoice_per_occurrence, leave_uninvoiced |
| autopay_default | bool | |
| discount_type / discount_value | enum + numeric | percent or amount; blank allowed |
| revenue_category_id | fk RevenueCategory | |
| additional_description / internal_remarks | text | |

- Relationships: CatalogItem 1-n Charge; self-reference for renewal; bundled into MembershipPlan (other cluster).
- Evidence: BIL-14

### Coupon
Purpose: promo code giving an amount or percentage off.

| field | type guess | notes / allowed values |
|---|---|---|
| id | uuid | |
| name | text | |
| code | text, unique per tenant | |
| starts_at / ends_at | timestamptz | help shows dates; 2016 note shows hour/minute precision at POS |
| discount_type | enum | amount, percent |
| discount_value | numeric | |
| limit_per_person | int, nullable | null = unlimited |
| self_service_enabled | bool | |

- Relationships: Coupon 1-n CouponRedemption (client_id, charge_id, redeemed_at) to enforce the per-person cap, including purchases made for relatives. No per-product scope field is evidenced: a webinar shows one coupon usable on memberships, packages and POS items.
- Evidence: BIL-15

### BillingPreferences
Purpose: one row per tenant (or location, see unknowns) of billing defaults and document text.

| field | type guess | notes / allowed values |
|---|---|---|
| enabled_optional_method_ids | fk[] PaymentMethodType | |
| package_invoice_session_dates | enum | values not enumerated publicly |
| package_booking_out_of_range_default | enum | allow, disallow |
| membership_autopay_default_in_facility | bool | |
| membership_autopay_default_self_service | bool | |
| invoice_include_group_description | bool | |
| invoice_group_description_source | enum | parent_group, subgroup |
| bill_to_block_options | jsonb | options not enumerated publicly |
| save_card_default | enum | includes yes, always_save; remaining values unknown (assume no, ask) |
| card_expiry_notice_leads | int[] | subset of {1 month, 2 months} |
| card_expiry_notice_scope | enum | all_cards, autopay_cards |
| card_decline_notice_scope | enum | off (inferred), all_cards, autopay_cards |
| invoice_email_subject | text | supports {InvoiceNumber} |
| statement_email_subject / statement_email_body | text | |
| invoice_footer / receipt_footer / statement_footer | text | |

- Relationships: 1-1 Tenant (or Location).
- Evidence: BIL-16, BIL-17, PAY-02, PAY-06, PAY-07, PAY-08

### PaymentMethodType
Purpose: tender types selectable when recording a payment.

| field | type guess | notes / allowed values |
|---|---|---|
| id | uuid | |
| code | enum | card, direct_debit, cash, check, bank_transfer, external_card, external_wallet, gift_card, account_credit |
| label | text | locale-aware ("cheque") |
| processed | bool | false = record-only ("Ext") |
| optional | bool | can be hidden in preferences |
| enabled | bool | |

- Relationships: Payment n-1 PaymentMethodType.
- Evidence: PAY-02

### StoredPaymentMethod
Purpose: tokenised card or bank account on a client (their "Billing Details" / card on file / direct debit account).

| field | type guess | notes / allowed values |
|---|---|---|
| id | uuid | |
| client_id | fk Client | |
| type | enum | card, bank_account |
| processor_token | text | never raw PAN |
| brand / last4 | text | redacted display |
| exp_month / exp_year | int | card only |
| use_for_autopay | bool | default true |
| status | enum | active, suspended, removed |
| suspended_on | date | bank account |
| verified_at | ts | bank account "Verify" |
| mandate_ref | text, nullable | direct debit authorisation |

- Relationships: Client 1-n StoredPaymentMethod; Payment n-1 StoredPaymentMethod; CardExpiryNotice n-1 StoredPaymentMethod.
- Evidence: PAY-06, PAY-07, PAY-10

### AutopayAttempt
Purpose: one automated collection attempt for an instalment.

| field | type guess | notes / allowed values |
|---|---|---|
| id | uuid | |
| run_id | uuid | groups one job execution |
| instalment_id | fk InvoiceInstalment | |
| stored_method_id | fk StoredPaymentMethod | |
| requested_date / scheduled_date | date | scheduled may be later for direct debit lead times |
| status | enum | scheduled, succeeded, failed |
| failure_code / failure_message | text | shown on AR report |
| error_cleared_at | timestamp, nullable | inferred; set when the entry is cleared from "Auto Pay Errors" (PAY-06) |
| payment_id | fk Payment, nullable | |
| idempotency_key | text unique | |

- Relationships: InvoiceInstalment 1-n AutopayAttempt; AutopayAttempt 0-1 Payment.
- Evidence: PAY-09, PAY-08, BIL-19, PAY-06

### DirectDebitBatch
Purpose: grouping of direct-debit collections submitted together.

| field | type guess | notes / allowed values |
|---|---|---|
| id | uuid | |
| location_id | fk Location | |
| processor | enum | values seen on their side: L&Z, NACHA |
| submitted_at | ts | |
| status | enum | draft, submitted, settled, partially_failed (inferred) |
| item_count / total | int / money | |

- Relationships: DirectDebitBatch 1-n AutopayAttempt/Payment.
- Evidence: PAY-10

### MerchantConnection
Purpose: link between a location and a payment processor account.

| field | type guess | notes / allowed values |
|---|---|---|
| id | uuid | |
| location_id | fk Location | |
| provider | enum | ours: stripe; theirs: EZPayments, Constellation/CSI Pay, Global Payments, Clover, L&Z, NACHA, other gateway |
| external_account_id | text | their Clover "Merchant ID" |
| credentials_ref | text | secret-store reference (their "API Token") |
| capabilities | jsonb | card, ach, refund_to_card, card_present, surcharge, wallets |
| status | enum | pending, active, disabled, past |
| surcharge_enabled / surcharge_percent | bool / numeric | <= ~3%, credit only |
| connected_at | ts | |

- Relationships: Location 1-n MerchantConnection; MerchantConnection 1-n PaymentTerminal, ProcessorPayout.
- Evidence: PAY-11, PAY-13, PAY-14

### PaymentTerminal
Purpose: card-present device registered to a location.

| field | type guess | notes / allowed values |
|---|---|---|
| id | uuid | |
| location_id | fk Location | |
| merchant_connection_id | fk MerchantConnection | |
| name | text | |
| terminal_code | text | issued by processor |
| active | bool | |
| is_default | bool | at most one per location (inferred) |
| device_model | text, nullable | e.g. Clover Flex (portable, Wi-Fi) per UK webinar |

- Relationships: Location 1-n PaymentTerminal; Payment n-1 PaymentTerminal. User permission "use terminals" gates access. For Clover the amount is pushed to the device and is not editable there.
- Evidence: PAY-12, PAY-13

### LocationPaymentAlertSettings
Purpose: staff-facing decline alerting per location.

| field | type guess | notes / allowed values |
|---|---|---|
| location_id | fk Location | |
| alert_email | text | |
| failed_txn_email_mode | enum | digest, per_transaction |

- Relationships: 1-1 Location.
- Evidence: PAY-08

### ProcessorPayout
Purpose: bank deposit from the processor and its constituent transactions (their "Pyxis Disbursements").

| field | type guess | notes / allowed values |
|---|---|---|
| id | uuid | |
| merchant_connection_id | fk | |
| payout_date | date | |
| amount | money | |
| external_payout_id | text | |
| lines | 1-n ProcessorPayoutLine | transaction_date, card_holder, client_id, card_last4, card_brand, txn_id, amount |

- Relationships: ProcessorPayoutLine.txn_id = Payment.processor_txn_id.
- Evidence: PAY-16

### PaymentDispute
Purpose: chargeback raised against a payment.

| field | type guess | notes / allowed values |
|---|---|---|
| id | uuid | |
| payment_id | fk Payment | |
| amount | money | |
| reason | text | |
| status | enum | open, won, lost (inferred) |
| opened_at / closed_at | ts | |

- Relationships: Payment 1-n PaymentDispute.
- Evidence: PAY-17

### PostBillingClose
Purpose: record of a period close that billed post-billed packages.

| field | type guess | notes / allowed values |
|---|---|---|
| id | uuid | |
| location_id | fk Location | |
| closing_date | date | |
| closed_by / closed_at | fk User / ts | |
| lines | 1-n | client_id, package_id, sessions_billed, invoice_id |

- Relationships: PostBillingClose 1-n Invoice.
- Evidence: BIL-18

### StatementBatch
Purpose: bulk statement send.

| field | type guess | notes / allowed values |
|---|---|---|
| id | uuid | |
| requested_by | fk User | must be manager + permission |
| client_category_id / client_filter_id | fk, nullable | |
| client_tag_ids | fk[] , nullable | wizard also filters by client tags (video) |
| date_from / date_to | date, nullable | webinar says max one-year span; help text implies open-ended (conflict, see unknowns) |
| basis | enum | invoice_date, due_date |
| only_open_invoices | bool | |
| recipients | 1-n | client_id, email, delivery_status |

- Relationships: StatementBatch 1-n recipient rows.
- Evidence: BIL-11

### ClientCollectionsState (columns on Client)
Purpose: delinquency flag used by collections and AR reports.

| field | type guess | notes / allowed values |
|---|---|---|
| billing_status | enum | normal, tagged_for_collections, in_collections (a webinar names the visible values "active" and "on hold/in collections"; caption uncertain, see unknowns) |
| tagged_at / placed_at | ts | |
| home_location_id | fk Location | used for the out-of-home-location payment warning |

- Relationships: columns on Client (owned by clients cluster).
- Evidence: BIL-20, BIL-19, PAY-01

### DunningNotice
Purpose: log of reminder / expiry / decline messages sent to clients.

| field | type guess | notes / allowed values |
|---|---|---|
| id | uuid | |
| client_id | fk Client | |
| kind | enum | due_soon, past_due, card_expiring, card_declined |
| channel | enum | email, sms |
| subject_ref | uuid | instalment or stored method |
| sent_at | ts | |

- Relationships: Client 1-n DunningNotice.
- Evidence: BIL-22, PAY-07, PAY-08

### Billing permissions (enumeration, owned by platform RBAC)
- refund_payments (their "billing refund" permission; also unmasks card type / bank data)
- send_billing_statements (their "Billing Statements"; grantable only to manager users)
- use_card_terminals (their "EMV Permission")
- manage_merchant_connection (their "Account Administration")
- Evidence: PAY-05, BIL-11, PAY-12, PAY-13

## POS & Inventory, Check-in & Access Control

All entities carry `id`, `tenant_id` (RLS), `created_at`, `updated_at` unless noted; `location_id` where the source scopes by location. Money = numeric(12,2) + tenant currency. "Their label" = short UI label observed publicly.

### Register
Purpose: a named till at a location to which sales are attributed.

| field | type guess | notes / allowed values |
|---|---|---|
| location_id | fk Location | registers of connected locations are selectable in POS |
| name | text | their label "Register Name" |
| favorites_enabled | bool | "Enable Favorite" |
| is_active | bool | soft delete (inferred) |

Relationships: has many RegisterFavorite, Sale. Evidence: POS-01, POS-02

### RegisterFavorite
Purpose: product pinned to a register's quick grid.

| field | type guess | notes |
|---|---|---|
| register_id | fk Register | |
| product_id | fk Product | |
| sort_order | int | (inferred) |

Relationships: Register 1-n, Product 1-n. Evidence: POS-02

### ProductCategory
Purpose: hierarchical grouping of products with default ledger/tax mapping.

| field | type guess | notes |
|---|---|---|
| parent_id | fk ProductCategory null | subcategory support |
| name | text | |
| revenue_category_id | fk RevenueCategory null | Billing-owned; optional |
| tax_code_ids | m2m TaxCode | multiple allowed; pre-filled from revenue category default tax |
| sort_order | int | (inferred) |

Relationships: self-tree; has many Product. Evidence: POS-03

### ProductBrand
Purpose: brand lookup.

| field | type guess | notes |
|---|---|---|
| name | text | |

Relationships: has many Product. Evidence: POS-04

### Supplier
Purpose: vendor a product is bought from.

| field | type guess | notes |
|---|---|---|
| name | text | |
| contact_info | jsonb | fields not published ("supplier's information") |
| contract_notes | text | press mentions supplier-contract tracking (inferred) |

Relationships: has many Product. Evidence: POS-04

### Product
Purpose: sellable retail item with price, cost and stock.

| field | type guess | notes |
|---|---|---|
| category_id | fk ProductCategory | |
| brand_id | fk ProductBrand null | |
| supplier_id | fk Supplier null | |
| name | text | register button label |
| product_code | text unique per tenant | their "Product ID" (unique) |
| sku | text | scannable barcode value; uniqueness assumed per tenant |
| description | text | admin-facing (e.g. size) |
| unit_price | money | pre-tax, pre-discount |
| cost_price | money | their "Buying Price"; feeds margin |
| qty_per_unit | int | their "Qty per Unit"; semantics ambiguous |
| default_discount_pct | numeric(5,2) | their "Discount %" |
| reorder_level | int | -1 = exclude from reorder report |
| revenue_category_id | fk null | null = inherit from category |
| tax_code_ids | m2m TaxCode | null/empty = inherit (assumed) |
| on_hand_qty | int | their "Units in Stock"; derived from StockMovement, cached per location |
| is_active | bool | |

Relationships: belongs to category/brand/supplier; has many StockMovement, SaleLine, RegisterFavorite. Evidence: POS-05, POS-06, POS-22

### StockMovement
Purpose: append-only inventory ledger (manual adjustments, sales, returns).

| field | type guess | notes |
|---|---|---|
| product_id | fk Product | |
| location_id | fk Location | |
| kind | enum | adjustment_delta, adjustment_set, sale, return (last two inferred) |
| quantity | int | signed delta; for adjustment_set store resulting delta + target |
| set_to_qty | int null | when kind = adjustment_set ("Set Inventory") |
| reason | enum | other (default), discrepancy, bought_new_stock |
| effective_at | timestamptz | "Date/Time of Adjustment", default now, back-datable |
| comment | text null | |
| sale_line_id | fk SaleLine null | |
| created_by | fk User | |

Relationships: Product 1-n. Evidence: POS-06

### DiscountPreset
Purpose: facility-defined quick discount offered in the cart.

| field | type guess | notes |
|---|---|---|
| name | text | |
| kind | enum | flat, percent |
| value | numeric | |
| is_active | bool | |

Relationships: referenced by SaleDiscount. Evidence: POS-10

### Sale
Purpose: a POS transaction (retail and/or equipment lines).

| field | type guess | notes |
|---|---|---|
| location_id | fk Location | |
| register_id | fk Register | |
| cashier_user_id | fk User | attribution = logged-in user |
| client_id | fk Client null | null = walk-in (their 2013 POS posted walk-in sales to a system client "Point of Sale Customer") |
| invoice_id | fk Invoice | Billing-owned; POS receipts visible on client invoice tab; "invoice number" is the search key |
| status | enum | open_cart, completed, pay_later (open invoice), partially_refunded, refunded, voided (last inferred) |
| note | text null | their "NOTE" |
| subtotal, discount_total, tax_total, total | money | |
| completed_at | timestamptz | |

Relationships: has many SaleLine, SaleDiscount, SaleTender, SaleReturn, ReceiptDelivery. Evidence: POS-07, POS-08, POS-12, POS-16

### SaleLine
Purpose: one cart line.

| field | type guess | notes |
|---|---|---|
| sale_id | fk Sale | |
| line_type | enum | product, equipment_rental, package (title-only evidence) |
| product_id / equipment_item_id / package_plan_id | fk null | per line_type |
| description | text | snapshot |
| quantity | int | starts at 1 |
| list_unit_price | money | snapshot |
| unit_price | money | after manual override |
| price_overridden_by | fk User null | permission-gated |
| discount_amount | money | allocated, penny-exact |
| tax_amount | money | |
| revenue_category_id | fk | snapshot |

Relationships: Sale 1-n; may create StockMovement or EquipmentLoan. Evidence: POS-07, POS-09, POS-18, POS-19

### SaleDiscount
Purpose: discount applied to a sale or to selected lines.

| field | type guess | notes |
|---|---|---|
| sale_id | fk Sale | |
| source | enum | preset, custom, coupon, client_global_pct, product_default (inferred) |
| preset_id | fk DiscountPreset null | |
| coupon_id | fk Coupon null | Billing-owned |
| kind | enum | flat, percent |
| value | numeric | |
| scope | enum | sale ("Apply to Sale"), lines ("Apply To Selected") |
| line_ids | m2m SaleLine | when scope = lines |

Relationships: Sale 1-n. Evidence: POS-10, POS-11

### SaleTender
Purpose: one payment leg of a sale (several = split tender).

| field | type guess | notes |
|---|---|---|
| sale_id | fk Sale | |
| tender_type | enum | card, cash, check, gift_card, account_credit ("Money on Account"), pay_later, card_on_file (variant of card) |
| amount | money | |
| payment_id | fk Payment null | Billing/Stripe reference |
| terminal_ref | text null | card-present adapter reference |

Relationships: Sale 1-n. Evidence: POS-12, POS-21

### SaleReturn
Purpose: refund/return against a completed sale.

| field | type guess | notes |
|---|---|---|
| sale_id | fk Sale | |
| refund_tender_type | enum | same list as tender_type minus pay_later (assumed) |
| amount | money | |
| processed_by | fk User | |
| processed_at | timestamptz | |
| restock | bool | our design choice (not evidenced) |

Relationships: has many SaleReturnLine(sale_line_id, quantity, amount). Evidence: POS-16

### ReceiptDelivery
Purpose: audit of receipt print/email actions.

| field | type guess | notes |
|---|---|---|
| sale_id | fk Sale | |
| channel | enum | print, email |
| email_to | text null | ad-hoc address is not written to client profile |
| sent_at | timestamptz | |
| sent_by | fk User | |

Relationships: Sale 1-n. Evidence: POS-13

### PosSettings
Purpose: per-location POS preferences.

| field | type guess | notes |
|---|---|---|
| location_id | fk Location unique | |
| email_receipt_enabled | bool | "Enable Email Receipt Option" |
| auto_print_receipts | bool | "Auto-Print Receipts" |
| allow_cart_price_qty_edit | bool | Classic general preference (name unpublished) |
| receipt_footer | text | their label "Receipt Footer" (sits in Billing Preferences) |
| ip_allowlist | cidr[] | account-level login restriction; role flag `ip_restriction_bypass` lives in RBAC |

Relationships: Location 1-1. Evidence: POS-01, POS-09, POS-13, POS-14

### EquipmentCategory
Purpose: grouping of rentable equipment.

| field | type guess | notes |
|---|---|---|
| name | text | |
| revenue_category_id | fk null | |
| deleted_at | timestamptz null | "Show Deleted Categories" |

Relationships: has many EquipmentItem. Evidence: POS-17

### EquipmentItem
Purpose: rentable asset offered in POS.

| field | type guess | notes |
|---|---|---|
| category_id | fk EquipmentCategory | |
| name | text | POS label |
| asset_code | text unique | their "Equipment ID" |
| description | text | printed on invoice |
| rental_fee | money | pre-tax |
| rental_days | int | allowed duration |
| return_time | time | time of day due back (location tz) |
| late_fee | money | |
| replace_fee | money | |
| revenue_category_id | fk null | null = inherit from category |
| tax_code_ids | m2m TaxCode | Classic; older variant used a free-text tax % |
| sort_order | int | Classic reorder arrows |
| status | enum | available, checked_out, needs_restocking (marketing wording), retired |
| deleted_at | timestamptz null | |

Relationships: has many EquipmentLoan. Evidence: POS-17, POS-18

### EquipmentLoan
Purpose: a checkout of an equipment item to a client.

| field | type guess | notes |
|---|---|---|
| equipment_item_id | fk EquipmentItem | |
| client_id | fk Client | mandatory |
| sale_line_id | fk SaleLine | |
| checked_out_at | timestamptz | |
| due_at | timestamptz | derived: checkout date + rental_days at return_time (inferred) |
| returned_at | timestamptz null | set in back office |
| returned_by | fk User null | |
| outcome | enum | open, returned, late, lost_or_damaged (inferred) |

Relationships: EquipmentItem 1-n, Client 1-n. Evidence: POS-18

### CheckInStation
Purpose: a named point where check-ins are recorded.

| field | type guess | notes |
|---|---|---|
| location_id | fk Location | |
| name | text | |
| tier | enum | main, secondary |
| mode | enum | staff, self |
| max_capacity | int null | for secondary stations; location-level max stored on Location |

Relationships: has many CheckIn. Evidence: CHK-07, CHK-06, CHK-20

### CheckIn
Purpose: one entry event (and optional exit) of a client.

| field | type guess | notes |
|---|---|---|
| client_id | fk Client | |
| location_id | fk Location | may differ from client's home location (shared clients) |
| station_id | fk CheckInStation null | |
| channel | enum | staff_window, client_profile, kiosk, pos (check-in from inside the register, video), mobile_app (inferred; videos show the app only displays a barcode, no phone-only check-in), door (adapter) |
| identified_by | enum | membership_number, name, barcode, fingerprint, app_card |
| checked_in_at | timestamptz | |
| checked_out_at | timestamptz null | editable by staff |
| result | enum | allowed, denied, allowed_override |
| denial_reason | enum null | expired, cancelled, suspended, frozen, depleted, past_due, over_daily_limit, outside_schedule, wrong_location, access_mode_deny, vaccine_gate |
| membership_id | fk Membership null | membership/contract the visit counted against |
| visit_consumed | bool | false when denied |
| attendance_booking_id | fk Booking null | session auto-marked attended |
| created_by | fk User null | null for kiosk |

Relationships: Client 1-n; Station 1-n. Evidence: CHK-01, CHK-05, CHK-07, CHK-08, CHK-18, CHK-19, CHK-20

### StaffCheckInSettings
Purpose: per-location staff check-in window behaviour.

| field | type guess | notes |
|---|---|---|
| location_id | fk Location unique | |
| visible_fields | jsonb (flags) | DOB (default shown), other "Client Details" fields; applies to users without 'Full Details on Check-in' |
| apply_access_rules | bool | "Apply Access Control Rules To Check In" |
| show_free_booking | bool | "Free Booking" |
| show_custom_gate_flag | bool | vaccine status display |
| checkout_enabled | bool | "Enable Checkout Preference" |

Relationships: Location 1-1. Evidence: CHK-02, CHK-07

### KioskSettings
Purpose: per-location self check-in configuration.

| field | type guess | notes |
|---|---|---|
| location_id | fk Location unique | |
| visible_range_minutes | int | "Visible Range" (minutes/hours) |
| early_window_minutes | int | "Early Check-In Window" |
| late_window_minutes | int | "Late Check-In Window" |
| welcome_message | text | |
| colors | jsonb | |
| default_view | enum | card, row |
| show_client_photo | bool | |
| auto_book | bool | books closest reservation |
| displayed_alerts | text[] | selectable; known: depleted, over_daily_limit; rest unpublished |
| reservation_page_timeout_s | int | |
| package_page_timeout_s | int | |
| confirmation_timeout_s | int | |
| lookup_method | enum | name, membership_number, both |
| deny_without_gate_flag | bool | vaccine passport denial |

Relationships: Location 1-1. Evidence: CHK-06, CHK-17

### AccessPolicy
Purpose: per-location decision rules for entry.

| field | type guess | notes |
|---|---|---|
| location_id | fk Location unique | |
| on_expired, on_cancelled, on_suspended, on_frozen, on_depleted, on_past_due | enum each | allow, deny |
| past_due_days | int | threshold for past-due rule |
| max_visits_rule | enum | allow_multiple, deny_after_one_per_day (visit-limited memberships only; local day) |
| apply_to_check_ins | bool | software enforcement only |
| default_access_mode | enum | allow, deny, rules_based (new clients only) |

Relationships: Location 1-1; Client.access_mode (allow / deny / rules_based) is a client-owned field. Evidence: CHK-08

### AccessSchedule
Purpose: named weekly time-of-day entry windows.

| field | type guess | notes |
|---|---|---|
| location_id | fk Location | |
| name | text | |

Child AccessScheduleRange: schedule_id, weekday (0-6), start_time, end_time (location tz; multiple per day).
Relationships: mapped to membership types via MembershipTypeAccess. Evidence: CHK-09

### MembershipTypeAccess
Purpose: entitlement mapping of a membership type to a schedule and to locations.

| field | type guess | notes |
|---|---|---|
| membership_type_id | fk MembershipType | |
| access_schedule_id | fk AccessSchedule null | null = unrestricted hours (assumed) |
| location_ids | m2m Location | "Location Mappings"; empty = home location only (assumed) |

Relationships: MembershipType 1-1. Evidence: CHK-09, CHK-10

### MemberCredential
Purpose: an identifier that resolves to a client at check-in, POS or door.

| field | type guess | notes |
|---|---|---|
| client_id | fk Client | |
| kind | enum | membership_number, key_fob_barcode, printed_id_card, app_card, wallet_pass, rfid, biometric_ref |
| value | text | alphanumeric; unique per tenant (assumed); their "Membership #" |
| source | enum | generated, scanned, app_registered, imported |
| registered_at | timestamptz | app console filters by created range |
| revoked_at | timestamptz null | admin "clear card" |

Relationships: Client 1-n (source product has exactly one check-in number per client). Evidence: CHK-11, CHK-13, CHK-15

### IdCardTemplate
Purpose: printable card layout.

| field | type guess | notes |
|---|---|---|
| name | text | |
| with_photo | bool | "Photo" tab |
| shown_fields | text[] | "Show Fields" |
| colors | jsonb | |
| is_active | bool | one active/default template per location (assumed) |

Relationships: used to render cards for Client (photo, credential). Evidence: CHK-12

### AccessControllerLink
Purpose: adapter configuration for an external door system (interface only in v1).

| field | type guess | notes |
|---|---|---|
| location_id | fk Location | |
| provider | enum | brivo (only evidenced provider) |
| external_account_ref | text | |
| service_user_ref | text | dedicated integration user in the tenant's door account |
| secret_ref | text | pointer to secret store, never the secret |
| status | enum | active, error, disabled |
| last_sync_at | timestamptz | |

Relationships: Location 1-n. Evidence: CHK-16

### Enumerations (consolidated)
- TenderType: card, card_on_file, cash, check, gift_card, account_credit, pay_later (+ split = multiple SaleTender rows)
- DiscountKind: flat, percent; DiscountScope: sale, lines; DiscountSource: preset, custom, coupon, client_global_pct
- StockAdjustMode: delta ("Make an adjustment (+ or -)"), set ("Set Inventory"); StockAdjustReason: other, discrepancy, bought_new_stock
- ReceiptChannel: print, email
- EquipmentStatus: available, checked_out, needs_restocking
- StationTier: main, secondary; StationMode: staff, self
- KioskView: card, row; KioskLookup: name, membership_number, both
- KioskResultScreen: ok_no_balance, balance_owed, frozen_or_suspended
- MembershipIndicator (check-in): active, visits_depleted, non_member; membership kind: simple, advanced
- AccessMode: allow, deny, rules_based; RuleOutcome: allow, deny
- AccessRuleCondition: expired, cancelled, suspended, frozen, depleted, past_due(days), max_visits_per_day
- CheckInAlert (known): waiver_unsigned, balance_due, card_expired, membership_expired, visits_depleted, over_daily_limit, birthday, staff_note (last two from blog)
- CredentialKind: membership_number, key_fob_barcode, printed_id_card, app_card, wallet_pass, rfid, biometric_ref

## Leagues & Tournaments, Groups & Online Registration

All tables carry `tenant_id` (RLS), `id`, audit timestamps; omitted below. Types are guesses. "(inferred)" = not stated in any source.

## Leagues & Tournaments

### Competition
Purpose: one league or tournament instance (their "League" / "Tournament").

| field | type guess | notes / allowed values |
|---|---|---|
| kind | enum | league, tournament. Immutable once linked to a registration group |
| format | enum | round_robin, single_elimination, double_elimination, pool_play, three_games_guaranteed. League allows round_robin only |
| name | text | |
| sport_id | fk SportConfig | |
| age_group_id | fk AgeGroup | predefined pick-list; mandatory when publishing a group (video), used to match officials |
| season_label | text null | their "Season", optional |
| division_label | text null | free text (recreation, competitive, A, B) |
| starts_on / ends_on | date | generation starts from starts_on |
| game_length_min | int | "Minutes per Game"; default from sport |
| show_roster_public | bool | league-level roster visibility on the public site, default true; a second team-level flag exists (video) |
| max_defaults | int null | per team per season cap |
| max_forfeits | int null | per team per season cap |
| min_sportsmanship | numeric null | rating floor |
| team_fee_text / player_fee_text | text/money | display-only on public site |
| fee_comments / more_info / rules_text | text | display |
| registration_url | text null | auto from linked group or pasted |
| status | enum | values not enumerated publicly ("League Status" filter); assume draft, active, completed (inferred) |
| public_display | jsonb | per-item visibility toggles (items not enumerated) |
| standings_config | jsonb / child rows | snapshot copied from sport at creation |
| source_group_id | fk Group null | set when created by publishing a group |
| location_id | fk | (inferred) |

Relationships: has many CompetitionTeam, Game, ScheduleRun, Bracket; belongs to SportConfig; optional 1-1 with Group.
Evidence: LGE-01, LGE-02, LGE-14, REG-14.

### AgeGroup
Purpose: predefined age bracket list used by competitions and official qualifications.

| field | type guess | notes |
|---|---|---|
| name | text | list contents not published |

Evidence: LGE-01, LGE-15.

### SportConfig
Purpose: per-sport defaults and rule templates.

| field | type guess | notes |
|---|---|---|
| name | text | |
| default_game_length_min | int | |
| default_player_fee / default_team_fee | money | |
| fees_text / more_info / rules_text | text | shown publicly |
| points_per_outcome | jsonb | league points per game status (win/loss/tie/forfeit...; list not enumerated) |
| standings_sort | jsonb | ordered list of (column, asc/desc) |

Relationships: has many StandingsColumn, StatTable; referenced by Competition, Official, PickupListing.
Evidence: LGE-05, LGE-06.

### StandingsColumn
Purpose: ordered display columns of a standings table (sport template and competition snapshot).

| field | type guess | notes |
|---|---|---|
| owner | fk sport or competition | |
| metric | enum | GP, W, L, T, GF, GA, PTS, GD, WP (defaults); further selectable columns not enumerated |
| heading | text | custom heading text |
| position | int | move up / remove |

Evidence: LGE-06.

### StatTable / StatDefinition
Purpose: sport-specific player statistic sheets.

| field | type guess | notes |
|---|---|---|
| StatTable.name | text | |
| StatTable.display_order | int | |
| StatDefinition.name | text | |
| StatDefinition.stat_table_id | fk | |
| StatDefinition.type | enum | user_entry, formula |
| StatDefinition.decimal_places | int | |
| StatDefinition.formula | text null | formula type only; grammar unknown |
| StatDefinition.display_order | int | |

Evidence: LGE-07.

### Team / CompetitionTeam
Purpose: a team identity and its entry (with seed) in a competition.

| field | type guess | notes |
|---|---|---|
| Team.name | text | generic placeholders allowed ("Generate Teams") |
| Team.source_group_id | fk Group null | subgroup that produced the team (inferred) |
| CompetitionTeam.competition_id / team_id | fk | copy-from-existing creates new entries |
| CompetitionTeam.seed | int null | editable ordering |
| CompetitionTeam.pool | text null | (inferred; pool assignment undocumented) |
| CompetitionTeam.calendar_feed_token | text | per-team subscribe URL |

Enumeration: team creation mode = none, generate_n, copy_from_existing.
Evidence: LGE-03, LGE-25.

### Player / RosterEntry
Purpose: person on a team for cards and stats.

| field | type guess | notes |
|---|---|---|
| Player.first_name / last_name | text | required |
| Player.client_id | fk Client null | our design: link to core client (inferred; their player DB appears separate) |
| Player.extra | jsonb | "other optional information" unspecified |
| Player.origin | enum | published_from_group, manual. Their manual add is one-way (no core client is created) (video) |
| RosterEntry.competition_team_id / player_id | fk | (inferred) |

Evidence: LGE-04.

### Official / OfficialQualification / GameOfficial
Purpose: referees, what they may officiate, and per-game assignment.

| field | type guess | notes |
|---|---|---|
| Official.first_name / last_name | text | required |
| Official.staff_user_id | fk null | (inferred link to Staff module) |
| OfficialQualification.sport_id | fk | many |
| OfficialQualification.age_group_id | fk | many |
| GameOfficial.game_id / official_id | fk | role, pay not documented |

Evidence: LGE-15.

### ScheduleRun
Purpose: persisted generator input/output so a run can be resumed, audited and re-run mid-season.

| field | type guess | notes |
|---|---|---|
| kind | enum | round_robin, pool_play, bracket |
| competition_ids | fk[] | multi-competition runs |
| venue_ids | fk[] Resource | |
| start_on / end_on / cutoff_on | date | cutoff optional |
| weekdays | int[] | |
| dates | date[] | incl. moved dates map |
| game_length_min | int | |
| games_per_week / games_total / games_per_team | int | games_total includes byes |
| begin_pairings_at_game | int null | |
| remove_previous_games | bool | |
| avoid_double_booking | bool | we always enforce; keep flag for parity only |
| remove_unschedulable | bool | |
| back_to_back_doubleheaders | bool | |
| bye_mode | enum | no_opponent_no_location (default), no_opponent_use_location, bye_filler, rotate_team |
| rotation_strategy | enum | fewest_time_slots (default); others not enumerated |
| rotation_spots / rotation_axis | int / enum | video: "rotate" N spots left through venues and/or down through time slots; a fewest-locations mode also exists (menu names uncertain) |
| predicted_completion_on | date | derived, shown live on the settings step (video) |
| keep_winners_on_same_field | bool | bracket |
| lower_bracket_mode | enum | ab_ba (default), ab_ab |
| state | enum | draft, previewed, committed (inferred; supports auto-save) |
| result_stats | jsonb | per team: home/away, per venue, per slot, per weekday; unschedulable list |

Relationships: has many ScheduleTimeSlot, TeamSchedulingPreference; produces Game.
Evidence: LGE-08, LGE-09, LGE-11, LGE-12.

### ScheduleTimeSlot
| field | type guess | notes |
|---|---|---|
| schedule_run_id | fk | |
| on_date | date | brackets require slots for every date |
| starts_at | time | auto-increment by game length |
| venue_id | fk Resource null | mapped at finalize |

Evidence: LGE-08, LGE-12.

### TeamSchedulingPreference
| field | type guess | notes |
|---|---|---|
| competition_team_id | fk | |
| type | enum | date, weekday, time_slot, home_venue, visitor_venue |
| target | text/fk | the date, weekday, slot or venue |
| preference | enum | value list not published; assume prefer / avoid (inferred) |
| is_priority | bool | |

Evidence: LGE-10.

### Game
Purpose: a scheduled fixture; also a resource booking.

| field | type guess | notes |
|---|---|---|
| competition_id | fk | |
| home_team_id / away_team_id | fk CompetitionTeam null | null on one side for a bye / undetermined bracket slot |
| booking_id | fk Booking null | holds (resource_id, tstzrange) under the exclusion constraint |
| starts_at | timestamptz null | null = unschedulable |
| status | enum | scheduled, played, postponed, cancelled, unschedulable, bye (postponed and cancelled are named; rest inferred) |
| round_no / week_no | int | |
| is_bye | bool | |
| bracket_slot_id | fk null | |
| doubleheader_of | fk Game null | |
| game_type | enum | regular (default for generated games), post_season (video) |
| round_label | text null | free text for post-season games, e.g. quarterfinals; shown publicly |
| home_label / away_label | text null | free-text placeholder opponent ("first place"); never auto-resolved |
| length_min | int | editable per game (video) |

Evidence: LGE-08, LGE-09, LGE-14.

### GameResult / PlayerGameStat
| field | type guess | notes |
|---|---|---|
| GameResult.game_id / competition_team_id | fk | one row per side |
| GameResult.score | int | |
| GameResult.participation | enum | full, default, forfeit |
| GameResult.sportsmanship | numeric null | |
| GameResult.bonus_points | int | added to league points |
| GameResult.overtime | text/int null | overtime / extra-time entry on the score form; exact shape not shown (video) |
| PlayerGameStat.game_id / player_id / stat_definition_id | fk | user_entry stats only |
| PlayerGameStat.value | numeric | |

Evidence: LGE-14, LGE-07.

### Bracket / BracketRegion / BracketRound / BracketSlot
| field | type guess | notes |
|---|---|---|
| Bracket.competition_id | fk | |
| Bracket.type | enum | single_elimination, double_elimination, three_games_guaranteed |
| BracketRegion.name | text | renamable |
| BracketRound.name | text | renamable |
| BracketSlot.round_id / position | fk / int | feeds_from winner/loser of other slots (inferred) |

Evidence: LGE-12, LGE-13.

### LeagueSite (settings)
| field | type guess | notes |
|---|---|---|
| logo_asset_id | fk | JPG, about 370x60 |
| menu_items | jsonb | visibility toggles |
| colors | jsonb | includes primary and link colour (hex) |
| leagues_page_defaults / tournaments_page_defaults | jsonb | status, sport, season, age group, division, sort |
| allow_indexing | bool | |
| contact | jsonb | facility info fields |
| about_html | text | |
| default_schedule_view | enum | list (default), grid |

Evidence: LGE-18, LGE-19.

### SavedPublicView
| field | type guess | notes |
|---|---|---|
| filters | jsonb | status, sport, season, age group, division, sort |
| token | text | public URL; iframe snippet derived |

Evidence: LGE-17.

### SiteLink / SitePhoto / ClassifiedAd / PickupListing
| field | type guess | notes |
|---|---|---|
| SiteLink.url / description / category / more_info | text | |
| SitePhoto.caption / asset_id / featured_on_home | text / fk / bool | JPG, 200 KB cap |
| ClassifiedAd.category | enum | player_seeking_team, team_seeking_player, team_seeking_coach, coach_seeking_team |
| ClassifiedAd.poster_account_id / body | fk / text | poster accounts self-managed |
| PickupListing.day / sport_id / time / more_info / registration_url | | day+sport+time required |

Evidence: LGE-20, LGE-21, LGE-22, LGE-23.

### League role (enumeration)
super_user, admin (admin cannot manage users). Evidence: LGE-26.

### LeagueEmailAlertSettings
| field | type guess | notes |
|---|---|---|
| scope | tenant or sport | sources disagree on where this is configured (see unknowns) |
| first_reminder_offset / second_reminder_offset | interval null | demo range: 2 days down to 15 minutes before game start |
| game_change_alerts | bool | emails players and captains of affected teams on postpone, cancel, reschedule or venue change |

Evidence: LGE-30.

### SponsorAd
Fields: image_asset_id, target_url, active; shown in the public site's right-hand column, rotating. Evidence: LGE-33.

## Groups & Online Registration

### Group
Purpose: registerable container, self-referencing tree (their "Group" / "Sub Group").

| field | type guess | notes |
|---|---|---|
| parent_id | fk Group null | arbitrary depth (grandchild shown) |
| name / description | text | |
| child_label | text | what children are called: team (default), session, class... |
| session_id / sport_id / age_division_id | fk GroupClassifier null | |
| revenue_category_id | fk | optional inheritance from parent |
| max_individuals | int null | capacity |
| max_subgroups | int null | cap on child nodes, e.g. teams; their UI uses 0 = unlimited for both caps (video) |
| contact_person / contact_email | text null | shown on the client-portal group page only (video) |
| price | money null | |
| status | enum | active, completed, archived (possibly = completed), deleted (soft) |
| auto_archive_after | date null | |
| waitlist_mode | enum | account default overridable; values unknown |
| location_id | fk | |
| competition_id | fk null | link after publish |
| last_accessed (per user) | separate table | drives "recently accessed" (cap 150) |

Relationships: has many GroupRegistration, GroupFee; one GroupRegistrationSettings; optional Competition.
Evidence: REG-01, REG-02, REG-04, REG-05, REG-14.

### GroupClassifier
| field | type guess | notes |
|---|---|---|
| kind | enum | session, sport, age_division |
| title | text | delete blocked while referenced |

Evidence: REG-03.

### GroupRegistration
Purpose: a client's membership of a group node (their "Group Member").

| field | type guess | notes |
|---|---|---|
| group_id | fk | unique (group_id, client_id) |
| client_id | fk Client | |
| status | enum | enrolled, waitlisted |
| fee_id | fk GroupFee or ProgramFee null | |
| revenue_category_id | fk | may be rewritten on move |
| invoice_id | fk null | none while waitlisted or when free |
| registered_by | enum | staff, online |
| payer_client_id | fk null | parent/guardian (inferred) |
| custom_field_values | via client custom fields | shown in roster grid |
| is_captain | bool | registrant who created the team; shown with a star (video) |
| registrant_comment | text null | copied to staff notification email and client profile comments (video) |
| waiver_acknowledged_at | timestamptz null | sets the client-profile waiver flag (video) |

Evidence: REG-07, REG-08, REG-09, REG-12.

### GroupFee
| field | type guess | notes |
|---|---|---|
| group_id | fk | |
| type | enum | individual, join_subgroup ("With a Team"/"With a Choice"), new_subgroup ("New Team"/"Team Fee") |
| description | text | |
| amount | money | |
| deposit_amount | money null | |
| payment_schedule | jsonb | instalment dates/amounts |
| schedule_first_draft_on / schedule_frequency / schedule_payment_count | date / enum / int | video: first auto-draft date, frequency (weekly shown), number of payments; balance after deposit split evenly |
| autopay_remaining | bool/enum | "Auto-Pay options" not enumerated |

Evidence: REG-10.

### GroupRegistrationSettings
| field | type guess | notes |
|---|---|---|
| group_id | fk unique | |
| enabled | bool | implicit when a fee exists (New); explicit checkbox (Classic) |
| opens_on / closes_on | date null | effective at 00:00 location time |
| notification_emails | text[] | semicolon list in their UI |
| payment_requirement | enum | pay_later_allowed, immediate_card_payment, card_required_charge_optional, card_required_no_charge |
| force_store_card | bool | |
| allow_coupons | bool | |
| disallow_partial_card_payment | bool | overrides deposit |
| online_description_html | text | stated limit 800,000 characters (video) |
| public_slug | text | registration link |
| portal_publish_name | text null | portal publishing owned by Engagement |
| closed_message | text null | shown after the close date (video) |
| roster_entry_mode | enum | none, captain_with_payment_assignment, captain_without_payment_assignment (video) |
| document_id | fk null | at most one registration document / waiver (video) |
| display_openings | bool | live count of spots / teams left (video) |
| confirmation_message | text null | (video) |

Evidence: REG-10, REG-11.

### RegistrationDefaults (tenant/location settings)
Fields: default payment_requirement, force_store_card, autopay defaults, default notification email, allow_coupons default, subgroups_inherit_revenue_category, gender_field (hidden / optional / required), waitlist default. Video adds: logo + large-header + alignment, accepted card types, disallow_partial (default on), allow_store_card, include_fee_description_on_billing_item, autopay_for_waitlisted, cvn_required, use_revenue_category_taxes, document_id, display_openings, online_waiver_fulfilment, remember_form_fields, background_colour, confirmation_message, analytics_id + cross_domain, roster_entry_mode. Evidence: REG-11, REG-09.

### ProgramFee (referenced; catalogue under location settings)
Fields: description, amount, location_id. Used for staff-side registration. Evidence: REG-07.

### RosterInvite
Fields: group_id (team node), captain_client_id, token (emailed link, resendable by staff), rows of first_name, last_name, home_phone, date_of_birth, email, assigned_amount. Each row creates a client and a registration. Evidence: REG-26.

### UserGridPreference
Fields: user_id, screen_key, collapsed_sections[], section_order[], column_order[], visible_columns[]. Evidence: REG-06.

### RegistrationForm
Purpose: standalone event form (their form product).

| field | type guess | notes |
|---|---|---|
| public_id | int | auto "Form ID" |
| name / event_name / date_location_text | text | |
| event_starts_on / event_ends_on | date | not the registration window |
| status | enum | draft (inferred), open, closed |
| auto_close_at | timestamptz null | |
| template_id | fk FormTemplate null | |
| copied_from_id | fk null | |
| header_asset_id | fk null | only after publish |
| theme | jsonb | colours, font, table_width_px |
| confirmation_message_html | text null | "Confirmation Messages" edit area; count and format undocumented (inferred single post-registration text) |
| public_slug | text | |

Evidence: REG-15, REG-19, REG-20.

### FormTemplate
Fields: event_type (e.g. triathlon), seed questions/topics/dependencies. Evidence: REG-15.

### FormQuestion
| field | type guess | notes |
|---|---|---|
| form_id | fk | |
| type | enum | text_box, drop_down, radio, checkbox, purchase_amount, purchase_quantity |
| text / hint / help | text | |
| visibility | enum | shown, hidden |
| required | bool | |
| expires_on | date null | |
| position | int | shared ordering with InformationTopic |
| max_length / default_answer | int / text | text_box |
| default_checked / price | bool / money | checkbox |
| unit_price | money | purchase_quantity |
| depends_on_question_id / depends_on_choice_id | fk null | template dependencies |

Evidence: REG-16.

### FormAnswerChoice
Fields: question_id, text, price, audience (all_registrants; member-only variants gated by membership module), position. Evidence: REG-16.

### InventoryControl
| field | type guess | notes |
|---|---|---|
| target | fk question or answer choice | answer for choice/checkbox-yes; question for quantity |
| enabled | bool | |
| limit_qty | int | |
| sold_qty | int | derived / counter |
| sold_out_memo | text null | not configurable for multiple choice |
| show_count_publicly | bool | |

Evidence: REG-17.

### InformationTopic
Fields: form_id, title, body_html, position. Evidence: REG-18.

### FormRegistration / FormRegistrationAnswer
| field | type guess | notes |
|---|---|---|
| form_id | fk | |
| confirmation_no | text | search key |
| account_client_id | fk Client | who registered |
| registrant_client_id | fk Client | self or other |
| status | enum | editable by admin; values not published |
| invoice_id | fk null | none when total is zero |
| total | money | |
| Answer.question_id / choice_id / text_value / quantity / amount | | deleting question/choice cascades in their system; we soft-delete |

Evidence: REG-21, REG-23.

### FormExportFile
Fields: form_id, columns[], filters, generated_at, asset_id, published_search_page (bool). Evidence: REG-21.

### FormPromoCode / FormWaitlistEntry
Stub entities; fields unknown. Evidence: REG-24.

## Staff & Payroll, Marketing, Self-Service Portal, Mobile App

All entities carry `id`, `tenant_id` (RLS), `created_at`, `updated_at` unless noted; omitted from tables. "Their label" = the vendor's UI term, recorded as a fact. Types are guesses.

## Staff / Trainers / Time Clock / Payroll

### Trainer
Bookable staff resource with a default pay profile.

| field | type guess | notes / allowed values |
|---|---|---|
| location_id | fk | trainers are defined per location |
| resource_id | fk | calendar resource created with the trainer (owned by scheduling) |
| user_id | fk nullable | link to login user; link not documented publicly (inferred, needed for own-data report scoping) |
| display_name | text | their label "Trainer Name" |
| pay_basis | enum | `per_attendee`, `per_session` |
| session_commission_pct | numeric | % of consumed package value; ignored when per_session |
| rate_60 / rate_45 / rate_30 | money | "Hourly / 45 Min / 30 Min Session Rate"; per attendee or per session by basis; prorated by length |
| comp_session_rate | money | flat hourly per comp package in session |
| program_instruction_rate | money | flat |
| non_training_rate | money | sessions with no attendees |
| floor_rate | money | flat |
| sales_commission_pct | numeric | "Sales Comm" on package value |
| sales_flat_commission | money | "Flat Comm Rate" per package |
| active | bool | (inferred) |

Relationships: 1-n ServicePayRate, MembershipCommissionRate, HoursBonus, OffHourBonusWindow; 1-1 scheduling Resource; acts as seller on sales.
Evidence: STF-01, STF-02

### Salesperson
Non-scheduled seller used for sale attribution and commission.

| field | type guess | notes / allowed values |
|---|---|---|
| location_id | fk | |
| full_name | text | shown in "Sold By" |
| package_commission_pct / package_flat | numeric / money | "Pkg Comm Rate", "Pkg Flat Comm" |
| session_commission_pct / session_flat | numeric / money | paid on session completion |
| membership_commission_pct / membership_flat | numeric / money | "Mem Comm Rate", "Mem Flat Comm" |
| first_invoice_only | bool | |

Relationships: 1-n ServicePayRate (keyed by program type), MembershipCommissionRate; referenced by sales as seller. Design note: model Trainer and Salesperson as one `StaffPayee` with `is_schedulable` (trainers are automatically salespeople).
Evidence: STF-05

### ServicePayRate
Override of pay/commission for one payee and one service type.

| field | type guess | notes / allowed values |
|---|---|---|
| payee_id | fk | trainer or salesperson |
| service_kind | enum | `reservation_type` (trainer; "Package Pay Rates"), `program_type` (salesperson; "Program Specific Pay Rates") |
| service_type_id | fk | |
| pay_basis | enum nullable | `per_attendee`, `per_session` (trainer only) |
| rate_60 / rate_45 / rate_30 / comp_session_rate | money | trainer only |
| sales_commission_pct / sales_flat_commission | numeric / money | |

Relationships: n-1 payee; n-1 reservation/program type. Unique (payee, service_kind, service_type_id) (inferred).
Evidence: STF-03, STF-05

### MembershipCommissionRate
Commission on sale of a specific membership type.

| field | type guess | notes / allowed values |
|---|---|---|
| payee_id | fk | |
| membership_type_id | fk | |
| commission_pct | numeric | "Sale Commission" |
| flat_commission | money | "Flat Comm." |
| first_invoice_only | bool | their labels "First Invoice Only" / "first time contract sold only" |

Relationships: n-1 payee; n-1 membership type.
Evidence: STF-03, STF-05

### HoursBonus
Threshold bonus on trained hours.

| field | type guess | notes / allowed values |
|---|---|---|
| trainer_id | fk | |
| name | text | |
| min_hours | numeric | |
| amount | money | per-hour vs lump sum not stated (assume per hour) |
| extra_hours_only | bool | "Apply Bonus only to the Extra Hours" |

Relationships: n-1 Trainer.
Evidence: STF-04

### OffHourBonusWindow
Per-weekday premium window.

| field | type guess | notes / allowed values |
|---|---|---|
| trainer_id | fk | |
| weekday | smallint | 0-6 |
| start_time / end_time | time | location-local |
| amount | money | |

Relationships: n-1 Trainer; one row per weekday (inferred).
Evidence: STF-04

### JobClassification
Named job a user can clock into.

| field | type guess | notes / allowed values |
|---|---|---|
| name | text | e.g. front desk, trainer |
| active | bool | (inferred) |

Relationships: 1-n StaffHourlyRate, TimeEntry.
Evidence: STF-06

### StaffHourlyRate
Hourly rate for a user in a classification.

| field | type guess | notes / allowed values |
|---|---|---|
| user_id | fk | |
| job_classification_id | fk | |
| hourly_rate | money | |
| effective_from | date | our addition (source shows no rate history) |

Relationships: n-1 User, JobClassification.
Evidence: STF-06

### TimeEntry
One clock-in/clock-out interval.

| field | type guess | notes / allowed values |
|---|---|---|
| user_id | fk | |
| job_classification_id | fk | |
| location_id | fk | (inferred) |
| clock_in_at / clock_out_at | timestamptz | out null while open |
| source | enum | `self`, `manager_added`, `manager_edited` (our audit addition) |
| source_ip | inet | for allowlist enforcement audit (inferred) |
| edited_by | fk nullable | |

Relationships: n-1 User, JobClassification. Constraint: no overlapping entries per user (exclusion on (user_id, tstzrange), our design).
Evidence: STF-07, STF-08

### TimeClockNetworkPolicy
Where the time clock may be used.

| field | type guess | notes / allowed values |
|---|---|---|
| location_id | fk | scope (account vs location) not stated |
| allow_any_ip | bool | "Allow access from any IP Address" |
| allowed_ips | inet[] | multiple |

Relationships: 1-1 location (assumed).
Evidence: STF-06

### PayStatement (our design, inferred)
Snapshot of a computed payroll/commission run so results are reproducible.

| field | type guess | notes / allowed values |
|---|---|---|
| payee_id / user_id | fk | |
| period_start / period_end | date | |
| commission_basis | enum | `invoiced`, `paid` ("Calculate commission from") |
| additional_income | money | manual add-on |
| lines | jsonb / child rows | kind: `session`, `comp_session`, `flat_activity`, `hours_bonus`, `off_hour_bonus`, `sale_commission`, `membership_commission`, `session_completion_commission`, `hourly` |
| status | enum | `draft`, `locked`, `exported` (our addition) |

Relationships: n-1 payee; lines reference sessions, invoices, time entries.
Evidence: STF-09, STF-10, STF-08

### Shift (brief-driven, inferred)
Planned staff working interval.

| field | type guess | notes / allowed values |
|---|---|---|
| user_id | fk | |
| location_id | fk | |
| job_classification_id | fk | |
| starts_at / ends_at | timestamptz | |
| status | enum | `planned`, `published`, `cancelled` (our design; no source enumeration) |

Relationships: n-1 User; compared with TimeEntry for variance.
Evidence: STF-15

## Email / SMS / Push

### ContactEmail
An email address on a client with verification and consent proof.

| field | type guess | notes / allowed values |
|---|---|---|
| client_id | fk | a client may hold several addresses |
| address | citext | |
| status | enum | `pending`, `verified` |
| verification_method | enum | `client_link`, `staff_manual` |
| verified_at | timestamptz | null for manual (no proof) in source; we store staff id instead |
| opt_in_ip | inet | captured on client verification |
| consent_basis | enum | `express`, `implied_purchase`, `implied_inquiry` (inferred from CASL article) |
| verification_token_hash | text | (our design) |

Relationships: n-1 Client; 1-n CommunicationSubscription.
Evidence: MKT-01, MKT-09

### CommunicationSubscription
Per-address topic opt-in.

| field | type guess | notes / allowed values |
|---|---|---|
| contact_email_id | fk | |
| topic | enum | `session_reminders`, `card_expiration`, `email_campaigns` (their three); add `sms_marketing` for US labelling (inferred from title-only article) |
| subscribed | bool | defaults: reminders true, card_expiration true, campaigns false |
| changed_by | enum | `client`, `staff` |
| changed_at | timestamptz | |

Relationships: n-1 ContactEmail.
Evidence: MKT-02

### EmailCampaign
A bulk email to a resolved audience.

| field | type guess | notes / allowed values |
|---|---|---|
| generation | enum | `basic`, `advanced` (ours; maps to legacy wizard vs 2024 builder) |
| subject | text | |
| sender_user_id / reply_to | fk / text | "Return Email Address" defaults to user email; display name = company |
| audience | jsonb | built-in segment `all_contacts`, `all_members`, `non_members`, `birthdays_this_month`, `birthdays_next_month`; client category ids; filters (`membership_expiration`, `birth_month`, `date_of_birth`, ...); source `group`/`form` ids |
| template_id | fk nullable | |
| body_html / layout_json | text / jsonb | |
| status | enum | `draft`, `scheduled`, `sending`, `sent`, `cancelled` (draft/scheduled/sent evidenced; others ours) |
| scheduled_at / sent_at | timestamptz | |
| counters | jsonb | attempted, duplicates, invalid, suppressed ("blacklisted"), sent; 2024 Sent view adds bounced, clicked, delivered, opened, spam, unsubscribed (video) |

Relationships: 1-n CampaignRecipient; n-1 EmailTemplate.
Evidence: MKT-03, MKT-04, MKT-07, MKT-11, MKT-12

### CampaignRecipient
Per-recipient delivery record.

| field | type guess | notes / allowed values |
|---|---|---|
| campaign_id | fk | |
| client_id / address | fk / citext | |
| status | enum | `delivered`, `opened`, `clicked`, `bounced`, `dropped` (their: Delivered, Open, Click, Bounce, Dropped); 2024 view also names `spam`, `unsubscribed`, `invalid`, `duplicate`, `blacklisted` (video) |
| provider_message_id | text | (our design) |
| last_event_at | timestamptz | |

Relationships: n-1 EmailCampaign, Client.
Evidence: MKT-07

### EmailTemplate
Reusable message.

| field | type guess | notes / allowed values |
|---|---|---|
| name | text | unique per tenant in 2024 builder |
| category | text | "Template Category" |
| type | text | "Type" (values not published) |
| origin | enum | `preset`, `saved` ("My Saved Templates" / "Your Templates"), `basic_layout` |
| subject | text | |
| body_html / layout_json | text / jsonb | |

Relationships: used by EmailCampaign, DirectMessage.
Evidence: MKT-05

### SavedSubject
Reusable subject line for direct emails.

| field | type guess | notes / allowed values |
|---|---|---|
| text | text | "Save Subject To Template" |

Relationships: used by DirectMessage.
Evidence: MKT-10

### MediaAsset
Image for email bodies.

| field | type guess | notes / allowed values |
|---|---|---|
| caption | text | |
| storage_key | text | S3 |
| purpose | enum | `email_image` (also reusable for app/portal assets, our design) |

Relationships: referenced from template/campaign HTML.
Evidence: MKT-06

### SuppressionEntry
Address blocked from sending.

| field | type guess | notes / allowed values |
|---|---|---|
| address | citext | |
| reason | enum | `bounce`, `spam_complaint` (unified 2024-05-23); `manual` (ours) |
| detail | text | provider diagnostic ("Reason" pop-up) |
| last_failed_at | timestamptz | |
| released_at | timestamptz nullable | "Unblock" |
| release_count | int | video: one unblock allowed; a second bounce blocks permanently |

Relationships: matched by address at send time. Trade-off: tenant-scoped vs platform-wide suppression (see unknowns).
Evidence: MKT-08

### DirectMessage
One-off email logged on a client.

| field | type guess | notes / allowed values |
|---|---|---|
| client_id | fk | |
| channel | enum | `email` (their "Type" implies other kinds) |
| sender_user_id | fk | "Assigned To" |
| subject | text | |
| template_id | fk nullable | |
| body_html | text | |
| due_on | date nullable | Classic task-style field |
| sent_at | timestamptz | |

Relationships: n-1 Client; appears in the client email audit.
Evidence: MKT-10, MKT-09

### NotificationRouting
Where operational alerts go.

| field | type guess | notes / allowed values |
|---|---|---|
| location_id | fk | |
| decline_alert_email | text | "Alert Email" |
| portal_alerts_enabled | bool | "Enable Email Alerts" |
| portal_alert_actions | text[] | client action types (list not published) |
| portal_alert_recipients | text[] | "Additional Emails" |
| management_summary_user_ids | fk[] | recipients must be users |
| registration_notice_emails | text[] | account default; group-level override lives on the group |

Relationships: 1-1 location.
Evidence: MKT-14

### ReminderRule
Session reminder schedule.

| field | type guess | notes / allowed values |
|---|---|---|
| location_id | fk | |
| offsets | interval[] | max 2 entries |
| channels | enum[] | `email`, `sms` |
| notify_trainer | bool | |
| scope | enum | `session` (core), `league_game` (league module: two reminders per sport, 15 min to 2 days before start; video) |
| notify_on_change | bool | league 'Game Change Alerts': postpone, cancel, reschedule, matchup change (video) |

Relationships: produces ReminderDispatch rows (booking, offset, sent_at) for idempotency (our design).
Evidence: MKT-13, LGE-30

### SmsProviderLink (adapter)
Tenant binding to an SMS provider.

| field | type guess | notes / allowed values |
|---|---|---|
| provider | enum | `textmunication` (theirs); ours pluggable |
| config | jsonb | credentials reference only |
| automations | jsonb | kinds evidenced: `lead`, `billing_decline`, `collection`, `new_prospect`, `renewal`, `birthday`, `class_reminder`, `promotion`; video adds `special_occasion`, `new_member_sequence`, `prospect_sequence`, `cancellation_confirmation`, `inactivity_winback`; each has enabled, text, delivery time, day offset, target groups |
| keywords | jsonb[] | video: keyword on a shared short code, autoresponder text, opted-in numbers with timestamp |
| groups | jsonb[] | video: synced `current_members`, `former_members`, `prospects`, `no_checkin_members`; auto-purged `opted_out`, `undeliverable`; custom groups |
| monthly_allotment | int | video: plan tier 2,000 / 4,000 / 7,000 / 10,000 texts; campaign sends lock at the cap, automations continue |

Relationships: 1-1 tenant.
Evidence: MKT-15, MKT-23

### PushNotification
Message pushed to app users.

| field | type guess | notes / allowed values |
|---|---|---|
| text | varchar(180) | hard cap 180 |
| url | text nullable | embedded in text in source |
| location_ids | fk[] | |
| filters | jsonb | list of {type, value, negate}; type `age`, `gender`, `last_check_in`, `membership_status`, `app_activity`; video: age = range plus include-unknown-birth-date flag; membership status includes `pending`, `active` |
| status | enum | `scheduled`, `sent`, `deleted` (inferred); video shows `preparing` before send and a recall/delete that removes it from member inboxes |
| scheduled_at / sent_at | timestamptz | |
| stats | jsonb | analytics (metrics not published) |

Relationships: fans out to DeviceRegistration; shown in in-app inbox for 30 days.
Evidence: MKT-16, MKT-17

### DeviceRegistration (our design, inferred)
Push token for a member device.

| field | type guess | notes / allowed values |
|---|---|---|
| client_id | fk | |
| platform | enum | `ios`, `android` |
| push_token | text | |
| location_id | fk | selected location |
| last_active_at | timestamptz | supports `app_activity` filter |

Relationships: n-1 Client.
Evidence: MKT-16, MKT-17, APP-17

### NewsStory
Story on the public league site.

| field | type guess | notes / allowed values |
|---|---|---|
| title | text | |
| body_html | text | |
| on_home_page | bool | |
| league_ids | fk[] | leagues/tournaments |

Relationships: n-n League/Tournament.
Evidence: MKT-18

## Self-Service Portal

### PortalSettings
Per-location portal configuration.

| field | type guess | notes / allowed values |
|---|---|---|
| location_id | fk | |
| enabled | bool | |
| slug | text | vanity URL |
| public_browse | bool | anonymous view |
| landing_page | enum | `login`, `schedule`, ... (list not published) |
| sessions_bookable / rentals_bookable | bool | |
| public_registration | bool | |
| registration_requires_verification | bool | |
| coupons_enabled | bool | |
| sell_past_start_products | bool | |
| card_policy | enum | values not published; assume `optional`, `required_for_recurring`, `always_required` |
| customer_editable | text[] | `profile_picture`, `basic_info`, `contact_info`, `payment_method`, `billing_address`, `relationships` |
| default_calendar_view | enum | `day`, `week`, `month`, `agenda`, `resource` |
| hide_booked_slots | bool | Classic option |
| redirect_after_public_registration / redirect_after_invitation | text | URLs |
| social_links | jsonb | https only |
| menu | jsonb | item key -> enabled; keys evidenced: `book_rental`, `registrations`, `video_library` |

Relationships: 1-1 Location; 1-1 SessionBookingPolicy (default), RentalBookingPolicy, PortalDesign.
Evidence: SSP-01, SSP-05, SSP-07, SSP-10, SSP-11, SSP-12, SSP-13, SSP-15

### SessionBookingPolicy
Booking rules, as location default or reservation-type override (null = inherit).

| field | type guess | notes / allowed values |
|---|---|---|
| location_id | fk | |
| reservation_type_id | fk nullable | null = location default |
| listing_mode | enum | `allow_booking`, `list_only`, `do_not_list` |
| requires_active_membership | bool | paid-to-date |
| requires_paid_package | bool | paid through current invoice date |
| visible_range_days | int | default only; no override |
| hide_full_sessions | bool | app |
| booking_cutoff | interval | |
| self_cancel_allowed / cancel_notice | bool / interval | |
| allow_post_billed_packages | bool | default only |
| adjacency_mode | enum | `none`, `show_but_block`, `hide_non_adjacent` |
| waitlist_enabled | bool | |
| auto_book_waitlist | bool | |
| allowed_package_plan_ids | fk[] | override only; empty = all |
| instant_staff_alert | bool | override only |
| online_description | text | override only |
| max_participants | int | override only |

Relationships: n-1 Location; n-1 ReservationType. Unique (location, reservation_type).
Evidence: SSP-02, SSP-03, SSP-09

### RentalBookingPolicy
Online rental rules, default or per rental type.

| field | type guess | notes / allowed values |
|---|---|---|
| location_id | fk | |
| rental_type_id | fk nullable | |
| online_booking | enum | `allow`, `disallow` |
| visible_range_days | int | |
| customer_sets_search_start | bool | |
| max_search_start_days | int | |
| hold_seconds | int | "hold clock", minutes or seconds |
| start_alignment_minutes | int | 60 (on-the-hour rule) |

Relationships: n-1 Location, RentalType.
Evidence: SSP-04

### BookingHold (our design, inferred)
Temporary reservation of a rental slot during checkout.

| field | type guess | notes / allowed values |
|---|---|---|
| resource_id | fk | |
| period | tstzrange | participates in the booking exclusion constraint |
| client_id | fk | |
| expires_at | timestamptz | now + hold_seconds |
| status | enum | `held`, `converted`, `expired` |

Relationships: converts to a rental booking.
Evidence: SSP-04

### PortalAccount
Client login for portal and app.

| field | type guess | notes / allowed values |
|---|---|---|
| client_id | fk | one login may act for related clients |
| username | citext | |
| password_hash / idp_subject | text | brief: OIDC + magic link |
| status | enum | `invited`, `pending_verification`, `active`, `disabled` |
| origin | enum | `invitation`, `public_registration` |
| last_login_at | timestamptz | |

Relationships: 1-1 Client; acts for clients via Relationship (owned by clients cluster).
Evidence: SSP-05, SSP-06

### PortalInvitation
Invitation to create a login.

| field | type guess | notes / allowed values |
|---|---|---|
| client_id | fk | |
| email | citext | |
| token_hash | text | |
| sent_at | timestamptz | displayed in facility time zone |
| accepted_at | timestamptz nullable | |
| sent_by | fk | |

Relationships: n-1 Client.
Evidence: SSP-06

### PortalDesign
Branding and content.

| field | type guess | notes / allowed values |
|---|---|---|
| location_id | fk | |
| banner_asset_id | fk | 160 x 36 px in source |
| primary_color | text | hex |
| welcome_message_html | text | |
| welcome_message_hidden | bool | |
| term_overrides | jsonb | menu label renames |
| payment_terms_html | text | versioned in our design for acknowledgment proof |
| analytics_id | text | Google Analytics tracking ID |

Relationships: 1-1 Location.
Evidence: SSP-14

### Video
Externally hosted video entry.

| field | type guess | notes / allowed values |
|---|---|---|
| source_type | enum | `url`, `embed_html` |
| source | text | embed HTML must be sanitised/allow-listed (our rule) |
| title | text | |
| reservation_type_id | fk nullable | category and watch-now link |
| enabled | bool | |
| (rule) | - | video: attaches per reservation type only (null = library-only, shown as 'other'); may be a scheduled live-stream URL; no entitlement check |

Relationships: n-1 ReservationType.
Evidence: SSP-16

### ProgramPublication
Portal listing of a group/program.

| field | type guess | notes / allowed values |
|---|---|---|
| group_id | fk | |
| publish_name | text | |
| session_starts / session_ends | date | informational |
| visible_in_portal | bool | "Show in Self Service" |
| published_at | timestamptz | |

Relationships: 1-1 Group (programs cluster).
Evidence: SSP-17

### PackagePlan.online_sale_mode (attribute on another cluster's entity)

| field | type guess | notes / allowed values |
|---|---|---|
| online_sale_mode | enum | `not_sold_online`, `allow_balance`, `paid_in_full` ("Sell Online": Yes - Allow Balances / Yes - Paid in Full) |

Relationships: owned by memberships/packages cluster. Similar per-coupon flag `portal_enabled` + `per_customer_limit`.
Evidence: SSP-08, SSP-11

## Mobile App

### AppConfig
Per-tenant app identity.

| field | type guess | notes / allowed values |
|---|---|---|
| mode | enum | `shared` (MM+ style directory app), `branded` |
| name / logo / color_scheme | text / asset / jsonb | |
| membership_card_mode | enum | `auto_generate`, `manual_entry` |
| features | jsonb | add-on flags e.g. `targeted_push`; video: Branded-only flags also `waitlist`, `location_push`, `custom_home_screen`, `reporting` |

Relationships: 1-n HomeScreen; 1-n per-location content settings.
Evidence: APP-01, APP-02, APP-06

### HomeScreen
A home-screen layout version.

| field | type guess | notes / allowed values |
|---|---|---|
| status | enum | `draft`, `live` |
| tile_padding_pt | smallint | 0-25 |
| background_color | text | |
| background_asset_id | fk nullable | |

Relationships: 1-n Tile.
Evidence: APP-04

### Tile
One tile on the 3-column grid.

| field | type guess | notes / allowed values |
|---|---|---|
| home_screen_id | fk | |
| type | enum | `favorites`, `youtube`, `contact`, `my_schedule_plus`, `pages_cms`, `instagram`, `my_account`, `submit_feedback`, `notifications`, `twitter`, `social_checkin`, `switch_locations`, `logo`, `gallery`, `services`, `announcements`, `image`, `app_link`, `facebook`, `schedule`, `weblink`, `trial_pass`, `membership_card`, `articles` |
| col / row / col_span / row_span | smallint | col 0-2; spans 1-3 |
| icon_asset_id | fk nullable | |
| bg_color / bg_opacity | text / numeric | |
| bg_asset_id | fk nullable | |
| border | jsonb | enabled, color, width, radius |
| target | jsonb | url, article/category id, app link |
| captions | jsonb | keys `top`, `middle`, `bottom`; each: text (may hold the dynamic token), align left/center/right, color, font default/verdana/sans_serif, weight light/normal/medium/bold/condensed/condensed_bold/black, style normal/italic/oblique, size_px 8-30, bg color+opacity, padding, margin |

Relationships: n-1 HomeScreen. Validation: dynamic captions only when col_span >= 2.
Evidence: APP-04, APP-05

### AppArticle / AppArticleCategory
In-app CMS content.

| field | type guess | notes / allowed values |
|---|---|---|
| category.name | text | |
| article.category_id | fk | |
| article.title / body_html | text | |
| article.publish_from / publish_to | timestamptz | publish_to nullable (open-ended) |

Relationships: Category 1-n Article; referenced by `pages_cms`/`articles` tiles.
Evidence: APP-07

### AppLocationContent
Per-location app content blocks.

| field | type guess | notes / allowed values |
|---|---|---|
| location_id | fk | "save to all branches" = copy to every location |
| general_info | jsonb | hours/contact (fields not published); video: name, address, lat/long, client email, vendor-contact email, social URLs, free-text hours, phones |
| department_numbers | jsonb[] | name, number, extension |
| service_contacts | jsonb[] | name, email, phone, website; max 10 |
| feedback_recipients | text[] | |
| referral_message | text | "Tell a friend" |
| trial_terms_html | text | |
| trial_recipient_email | text | |
| announcements | jsonb[] | image, optional url; video: plus text, valid_from, valid_to, cta `share`/`website`/`email`/`phone`; max 11 live |
| gallery_asset_ids | fk[] |; video: each with go-live and take-down dates |

Relationships: 1-1 Location.
Evidence: APP-08, APP-09, APP-10, APP-11, APP-12, APP-14, APP-16

### TrialRequest
Prospect submission from the app.

| field | type guess | notes / allowed values |
|---|---|---|
| first_name / last_name / phone / email | text | |
| location_id | fk | |
| terms_accepted_at | timestamptz | |
| status | enum | `new`, `converted`, `dismissed` (ours; source only emails it) |
| client_id | fk nullable | set on conversion |

Relationships: n-1 Location.
Evidence: APP-12

### FeedbackSubmission (our design, inferred)

| field | type guess | notes / allowed values |
|---|---|---|
| location_id | fk | |
| client_id | fk nullable | reviewers describe it as anonymous |
| body | text | |
| submitted_at | timestamptz | |
| category | enum | video: `classes_events_instructors`, `facility_equipment`, `mobile_app`, `other` |

Relationships: emailed to feedback recipients.
Evidence: APP-10

### Favorite

| field | type guess | notes / allowed values |
|---|---|---|
| client_id | fk | |
| target_kind | enum | `session`, `instructor`, `location` |
| target_id | fk | |

Relationships: n-1 Client.
Evidence: APP-13

### MembershipCardPass

| field | type guess | notes / allowed values |
|---|---|---|
| client_id | fk | |
| barcode_value | text | auto-generated or member-entered |
| wallet_platform | enum nullable | `apple`, `google` |
| wallet_serial | text | |
| revoked_at | timestamptz nullable | (ours; reviews show cards cannot be removed) |
| (rule) | - | video: several passes per app install (vendor: up to 10, for families); barcode value = card number already on the client profile |

Relationships: n-1 Client; scanned by check-in (c6 cluster).
Evidence: APP-06

### ReservationCategory

| field | type guess | notes / allowed values |
|---|---|---|
| location_id | fk | |
| label | text | renameable |

Relationships: 1-n sessions/reservations; used to group the app schedule.
Evidence: APP-18

## Reporting, Integrations & API, Release-note changes

All entities carry `id`, `tenant_id` (RLS), `created_at`, `updated_at` unless noted; `location_id` where the source scopes by location. Money = numeric(12,2) in tenant currency. "Their label" = short UI label seen publicly. Reporting owns catalog, run and read-model entities only; transactional facts (invoices, payments, contracts, attendance, POS orders) are owned by other modules and listed under "Upstream data the reports require".

### ReportDefinition
Purpose: catalog entry for one report (code-defined, seeded; not tenant-editable).

| field | type guess | notes / allowed values |
|---|---|---|
| key | text unique | e.g. `revenue_summary`, `deposits`, `open_invoices` |
| name | text | display name |
| description | text | one-line description shown in the catalog |
| category | enum ReportCategory | financial, marketing, membership, training, pos, check_in, time_clock, lockers, leagues, groups, app_analytics |
| param_schema | jsonb | typed parameter list (date, date range, enum, multi-select, bool, entity ref) incl. "more options" flag |
| supports_detail | bool | their "Show Details" |
| required_permission | text | RBAC permission key |
| required_module | text null | add-on gate, e.g. lockers, advanced_memberships, leagues |
| self_scope_roles | text[] | roles restricted to own rows (trainer on trainer reports) |
| date_basis | enum | revenue_date, payment_date, invoice_date, due_date, as_of, none |
| is_legacy | bool | parity-only reports |

Relationships: has many ReportRun. Evidence: RPT-01, RPT-41

### ReportRun
Purpose: one execution of a report with frozen parameters and a static result.

| field | type guess | notes / allowed values |
|---|---|---|
| report_key | fk ReportDefinition | |
| requested_by | fk User | |
| location_ids | uuid[] | scope; multi-location filter on dashboard |
| params | jsonb | validated against param_schema |
| status | enum | queued, running, succeeded, failed |
| started_at / finished_at | timestamptz | |
| row_count | int | |
| result_ref | text | object-store key of cached result set |
| idempotency_key | text | blocks duplicate runs from double-click |

Relationships: belongs to ReportDefinition, User; has many ReportExport. Evidence: RPT-01, REL-02

### ReportExport
Purpose: a file rendered from a run.

| field | type guess | notes / allowed values |
|---|---|---|
| report_run_id | fk ReportRun | |
| format | enum ExportFormat | theirs: word, excel, powerpoint, pdf, tiff, mhtml, csv, xml, data_feed; ours v1: csv, xlsx, pdf |
| include_details | bool | export expanded rows |
| page_size / orientation | text | print/PDF options |
| file_ref | text | object-store key |

Relationships: belongs to ReportRun. Evidence: RPT-01

### RevenueFact (read model)
Purpose: one row per billing item for revenue-date reporting.

| field | type guess | notes / allowed values |
|---|---|---|
| billing_item_id | fk | source item |
| revenue_date | date | their "Revenue Date"; drives revenue, tax, discount sections |
| revenue_category_id | fk RevenueCategory | filter and grouping |
| rental_type_id | fk null | column added to "Report by Revenue" |
| gross_amount | money | discounts included, taxes excluded in category table |
| discount_amount | money | Discounts by Category |
| tax_amount | money | Taxes Generated; per tax rate |
| invoice_id | fk null | null = still in cart ("not on invoice") |
| amount_paid_to_date | money | for Underpaid Items as-of logic |

Relationships: BillingItem, Invoice, RevenueCategory. Evidence: RPT-02, RPT-03, RPT-09

### PaymentFact (read model)
Purpose: one row per payment/refund for cash reporting.

| field | type guess | notes / allowed values |
|---|---|---|
| payment_id | fk | |
| payment_date | date | drives Payment Breakdown, Deposits |
| client_id | fk | Client Name, Member Number |
| method | enum PaymentMethod | cash, check (UK label cheque), credit_card, bank_transfer (record-only), direct_debit/ACH, other |
| card_type | text null | captured from manual and auto-pay payments |
| kind | enum | payment, refund |
| is_voided | bool | shown flagged in Deposits |
| total_amount | money | "Total Payment" |
| amount_applied | money | |
| amount_unused | money | unapplied / on account |
| collected_by | fk User | "Collected By" |
| comments | text | |
| processor_txn_id | text null | "Transaction ID" for payout matching |

Relationships: Payment, Client, User. Evidence: RPT-03, RPT-04, RPT-07

### ClientBalanceView (derived)
Purpose: per-client liability position.

| field | type guess | notes |
|---|---|---|
| client_id | fk | |
| unapplied_payments | money | not applied and not refunded |
| unpaid_invoices | money | remaining on all invoices regardless of date |
| liability | money | unapplied minus unpaid; positive = credit held |

Relationships: Client. Evidence: RPT-07

### ReceivableRow (derived)
Purpose: as-of open invoice line for receivables reporting.

| field | type guess | notes / allowed values |
|---|---|---|
| invoice_id | fk | |
| client_id | fk | name, home phone |
| basis | enum | due_date (schedule-aware), invoice_date |
| balance_as_of | money | ignores payments on/after end date |
| is_auto_pay | bool | filter: all / auto_pay_only / non_auto_pay |
| days_past_due | int | |
| last_decline_reason | text null | detail for failed auto-pay |
| client_state | enum | active, deleted |
| in_collections | bool | from client billing status |

Relationships: Invoice, Client. Evidence: RPT-06

### DashboardSnapshot (derived)
Purpose: period KPI bundle for the management dashboard.

| field | type guess | notes |
|---|---|---|
| start_date / end_date | date | |
| location_ids | uuid[] | |
| revenue_goal | money null | optional run parameter |
| revenue_generated, discounts, taxes | money | by revenue date |
| payments_applied, net_deposits | money | by payment date; net deposits include unapplied |
| balance_due, in_collections | money | as of end date |
| deposits_by_method | jsonb | received, refunded, net per method |
| membership_counts | jsonb | by status |
| attendance_counts | jsonb | by attendance status |
| rental_count, rental_hours | numeric | |

Relationships: computed from RevenueFact, PaymentFact, contracts, attendance, rentals. Evidence: RPT-02

### AppAnalyticsDaily
Purpose: daily aggregates of branded-app usage per platform and screen.

| field | type guess | notes / allowed values |
|---|---|---|
| organization_id | fk | chain level (above location) |
| day | date | |
| platform | enum | ios, android |
| screen | enum AppScreen null | splash, location_switch, home, schedule, package_select, account, announcements, contact, favorites, notifications, member_card, add_member_card, multi_barcode |
| new_downloads | int | |
| active_users_1d / 7d / 28d | int | distinct users in window ending that day |
| sessions | int | |
| engaged_sessions | int | open longer than 10 s |
| avg_session_seconds | numeric | |
| screen_views / screen_users | int | per screen |

Relationships: Organization. Evidence: RPT-38

### ApiClient
Purpose: machine credential for the public API.

| field | type guess | notes / allowed values |
|---|---|---|
| name | text | |
| client_id | text unique | |
| client_secret_hash | text | shown once |
| realm | enum | back_office (their "TMS"), self_service |
| scopes | text[] | per resource family: clients, memberships, schedule, bookings, invoices, packages, pos, leagues |
| location_ids | uuid[] | accessible locations (cross-location membership-number lookup) |
| status | enum | active, revoked |
| last_used_at | timestamptz | |

Relationships: Tenant; has many ApiAccessToken. Evidence: INT-01 to INT-06

### ApiAccessToken
Purpose: issued bearer token (or its audit record if JWT).

| field | type guess | notes |
|---|---|---|
| api_client_id | fk ApiClient | |
| subject_client_id | fk Client null | member context in self-service realm |
| expires_at | timestamptz | |
| revoked_at | timestamptz null | |

Relationships: ApiClient. Evidence: INT-01, INT-05

### IntegrationConnection
Purpose: generic record of a tenant/location link to an external provider.

| field | type guess | notes / allowed values |
|---|---|---|
| location_id | fk Location null | most are per location |
| provider | enum | quickbooks_online, zoom, smartwaiver, perkville, coachmeplus, trainingym, google_analytics |
| status | enum | pending, active, error, disconnected |
| credential_ref | text | secret-store reference (OAuth tokens or API key); never plaintext |
| external_account_id | text | e.g. QuickBooks company id |
| settings | jsonb | provider-specific, see below |
| connected_by | fk User | |
| last_sync_at / last_error | timestamptz / text | |

Relationships: Location; has many provider child rows. Evidence: INT-07, INT-09, INT-10, INT-11, INT-12, INT-13, INT-15

### AccountingClassMapping
Purpose: maps a revenue category to an accounting-system class.

| field | type guess | notes |
|---|---|---|
| connection_id | fk IntegrationConnection | QuickBooks |
| revenue_category_id | fk RevenueCategory | their field "Quickbooks Online Class" on the category |
| external_class_id | text | |
| external_class_name | text | |

Relationships: IntegrationConnection, RevenueCategory. Settings on the connection: `auto_sync` bool. Evidence: INT-07

### AccountingSyncRecord (inferred)
Purpose: idempotency and status of each pushed object.

| field | type guess | notes / allowed values |
|---|---|---|
| connection_id | fk | |
| object_type | enum | customer, invoice, payment, refund, pos_sale |
| local_id | uuid | |
| external_id | text null | |
| status | enum | pending, synced, failed, skipped |
| attempts / last_error | int / text | |
| synced_at | timestamptz | |

Relationships: IntegrationConnection. Evidence: INT-07 (inferred from one-way push and duplicate-customer warning)

### VideoMeetingSettings
Purpose: per-location access policy for virtual sessions (settings of the Zoom connection).

| field | type guess | notes / allowed values |
|---|---|---|
| connection_id | fk IntegrationConnection | |
| require_portal_login | bool | their "Require Self-Service Log-in" |
| require_booking | bool | their "Require Session Booking" |
| access_mode | enum (derived) | open, logged_in, booked_only |
| launch_window_minutes | int | 10 before start (fixed in theirs) |
| (scope note) | n-a | theirs is per location only, with no per-reservation-type override (2020 webinar); ours could allow one |

Relationships: IntegrationConnection. Evidence: INT-09

### VideoMeeting
Purpose: external meeting attached to a reservation/session.

| field | type guess | notes |
|---|---|---|
| reservation_id | fk Reservation | deleting reservation deletes meeting |
| connection_id | fk | |
| host_external_user_id | text | Zoom user; no overlapping meetings per host |
| external_meeting_id | text | |
| host_start_url / join_url | text | join link issued per client through portal login; in theirs a cancelled client's link keeps working (not revocable) |
| status | enum | scheduled, deleted |

Relationships: Reservation 1-1, IntegrationConnection. Evidence: INT-09

### WaiverProviderLink
Purpose: inbound waiver-provider configuration (settings of the Smartwaiver connection).

| field | type guess | notes |
|---|---|---|
| connection_id | fk IntegrationConnection | API key in secret store |
| webhook_token | text | our replacement for location id in URL |
| is_active | bool | their "Activate" |
| require_email_validation | bool | their "Email validation" Yes / No; a waiver is held back until the signer confirms their email; overridable per waiver on the provider side |

Relationships: IntegrationConnection; has many InboundWebhookEvent. Evidence: INT-10

### InboundWebhookEvent
Purpose: raw provider callback kept for idempotent processing.

| field | type guess | notes / allowed values |
|---|---|---|
| provider | enum | smartwaiver, stripe, zoom |
| location_id | fk null | resolved from URL token |
| external_event_id | text | unique per provider for dedupe |
| payload | jsonb | |
| status | enum | received, processed, failed, ignored |
| processed_at | timestamptz | |

Relationships: IntegrationConnection. Evidence: INT-10

### LoyaltyEvent (inferred)
Purpose: outbound earn event for a loyalty provider.

| field | type guess | notes / allowed values |
|---|---|---|
| client_id | fk | |
| event_type | enum | check_in, session_attended, amount_invoiced |
| amount | money null | for amount_invoiced |
| source_id | uuid | check-in, attendance or invoice id |
| delivered_at | timestamptz null | |

Relationships: Client, IntegrationConnection. Evidence: INT-11

### CalendarFeed
Purpose: per-user read-only calendar subscription.

| field | type guess | notes / allowed values |
|---|---|---|
| user_id | fk User | |
| token | text unique | their UID key; rotated on disable/enable |
| is_enabled | bool | |
| resource_ids | uuid[] null | null = all |
| reservation_type_ids | uuid[] null | null = all |
| days_past / days_future | int | each capped at 90 in theirs (2013 launch webinar) |
| include_unbooked_sessions | bool | |
| include_rentals | bool | |
| include_other_reservations | bool | e.g. program instruction, unavailable |
| include_notes | bool | |
| include_booking_list | bool | PII in feed |
| last_fetched_at | timestamptz | |

Relationships: User. Evidence: INT-08

### ReleaseNote
Purpose: published changelog entry.

| field | type guess | notes |
|---|---|---|
| release_date | date | |
| published_at | timestamptz | can lag release date |
| version | text null | e.g. 53.0, v104.0 |
| title | text | |

Relationships: has many ReleaseNoteItem. Evidence: REL-01

### ReleaseNoteItem
Purpose: one shipped change.

| field | type guess | notes / allowed values |
|---|---|---|
| release_note_id | fk ReleaseNote | |
| kind | enum | feature, improvement, fix, api, api_fix, tech |
| module | text | owning module key |
| ui | enum | classic, new, both, n_a |
| body | text | |

Relationships: ReleaseNote. Evidence: REL-01

### Enumerations found (report parameters and outputs)
| enum | values | evidence |
|---|---|---|
| OpenInvoiceBasis | due_date, invoice_date | RPT-06 |
| InvoiceInclusion | all, auto_pay_only, non_auto_pay | RPT-06 |
| ClientStateFilter | active, deleted, both | RPT-06 |
| OpenInvoiceSort | client_name, invoice_balance, invoice_due_date | RPT-06 |
| MembershipAction | cancelled, frozen, suspended | RPT-13 |
| MembershipActionDateBasis (labels uncertain) | start_date, action_date, end_date, both | RPT-13 (video) |
| MembershipStatus (as counted by the report) | active, cancelled, frozen, pending, suspended | RPT-12 (video) |
| WaiverMatchOutcome | attached_to_existing, client_created, ambiguous_admins_notified | INT-10 (video) |
| LeagueReportKind | games_by_venue, officials, demographics_by_gender, demographics_by_ranking, demographics_by_team | LGE-32 |
| MembershipLossReason (counted) | voluntary_cancel, expired_not_renewed | RPT-14 |
| CancelReason (not counted) | upgrade, downgrade, administrative_error, other_modification | RPT-14 |
| MembershipRevenuePeriod | this_month, this_quarter, this_year, next_month, next_quarter, next_year, rolling_1_year, custom | RPT-11 |
| ActivityType | phone, email, task, other, customer_service_rep | RPT-18 |
| ActivityStatus | not_started, in_progress, completed, waiting, deferred | RPT-18 |
| ReferralGrouping | by_source, by_category | RPT-20 |
| PosSalesOutputMode | normal_for_printing, simplified_for_exporting | RPT-30 |
| EmailEventType | delivered, open, click, bounce, dropped, spam_report | RPT-29 |
| CampaignAudienceCounter | attempted, duplicates, empty, invalid, blacklisted, sent | RPT-29 |
| RentalPlanSaleChannel | staff, self_service | RPT-39 |
| VideoAccessMode | open, logged_in, booked_only | INT-09 |
| ApiRealm | back_office, self_service | INT-01 |
| Gender | male, female, not_specified | REL-04 |

### Upstream data the reports require (owned elsewhere; constraints on other modules)
| requirement | needed by |
|---|---|
| Billing item carries revenue_date, revenue_category, tax, discount separately from invoice date and schedule | RPT-03, RPT-09 |
| Payment keeps applied vs unused amounts, void flag (soft), collector, method, card type, processor transaction id | RPT-04, RPT-07 |
| Payment allocations are dated, so balances can be computed as of a past date | RPT-06, RPT-09 |
| Auto-pay attempts store decline reason | RPT-06 |
| Client billing status includes in-collections; clients are soft-deleted | RPT-06 |
| Membership contract status history with timestamp and reason; renewal-configured flag; contract owner vs sharers | RPT-12 to RPT-15 |
| Membership sale stores referring client and seller | RPT-16 |
| Client has default trainer, category, referral source and referral category | RPT-20, RPT-23, RPT-26 |
| Package has price, session count, expiry, lock-outside-range flag, complimentary flag; session consumption tied to attendance status | RPT-10, RPT-22, RPT-24 |
| POS order stores register, logged-in user, coupon, product brand/supplier/category, unit cost | RPT-30 to RPT-32 |
| Product has reorder level (-1 = exclude) | RPT-33 |
| Email send log keeps per-address events (45-day detail retention in theirs) | RPT-29 |
