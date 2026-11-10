# Feature Inventory — EZFacility parity target

Phase 0 output 2. Module → feature → sub-features → settings → rules → user story → actors → priority, each with evidence URLs.
Built only from public material (see `source-coverage.md`). "Classic" / "New" are the reference product's two UI generations.
"(inferred)" marks our inference; "(title only, body not read)" marks a help article known only by its title.

**Totals:** 453 features across 26 modules — P0: 202, P1: 195, P2: 35, v2-adapter: 21.
Priority: P0 = needed for MVP of the matching brief module; P1 = parity, post-MVP; P2 = minor or legacy; v2-adapter = hardware/partner item kept as an interface only.

Feature ID prefixes: PLT platform, RES resources, IMP import, ONB onboarding, SCH scheduling, RNT rentals, CLS classes, CLI clients, FAM households,
DOC waivers/documents, FIT assessments, MEM memberships, PKG packages, BIL billing, PAY payments, POS point of sale, CHK check-in/access,
LGE leagues, REG groups/registration, STF staff, MKT marketing, SSP self-service portal, APP mobile app, RPT reporting, INT integrations, REL cross-cutting release changes.

Naming used by the source: "Classic" / "TMS" = older UI; "New Experience" / "New UI" / "EZUI" = redesign (2021 onward); "EZLeagues" = league module with its own user table and public site; "MiGym" = admin portal behind the MemberMe+ / branded mobile app. "(inferred)" marks our deductions.

## Platform & Admin

### PLT-01 Tenant account and multi-location organization
- Sub-features: one customer account owning one or more locations; client records shared across locations; bookings visible across locations; cross-location reporting; signed waivers honoured across locations; each client has a home location; staff can act on clients from another location (sell membership, email session/group members); POS user can view and switch to another connected location's cash registers; API lookups by membership number span all locations the caller can access.
- Settings / options: per-location settings exist (see RES-01); client home location (one per client); "connected locations" relationship between locations of one account (inferred: all locations of the tenant, possibly a subset).
- Rules / limits: staff taking payment for a client whose home location differs gets a warning, not a block (shipped 2024-05-08); several cross-location defects were fixed over 2022-2024, i.e. location is a filter on shared data, not a hard partition.
- User story: As an owner of several sites, I want one account with shared clients and consolidated reporting, so that members can use any site and I manage the business centrally.
- Actors: owner/admin, multi-site operator, front desk.
- UI generation: both
- Priority: P0
- Evidence: https://www.ezfacility.com/ezfacility-comparison, https://www.ezfacility.com/features/billing-payments, https://www.ezfacility.com/benefits, https://www.ezfacility.com/blog/the-benefits-of-gym-management-software, https://www.ezfacility.com/blog/software-release-vaccine-passport, https://support.ezfacility.com/hc/en-us/articles/25551222201627-May-8th-2024-Release-Notes, https://support.ezfacility.com/hc/en-us/articles/18741009680795-September-13th-2023-Release-Notes, https://support.ezfacility.com/hc/en-us/articles/36516560976539-April-9th-2025-Release-Notes, https://support.ezfacility.com/hc/en-us/articles/11297336305691-December-15th-2022-Release-Notes

### PLT-02 Staff user accounts
- Sub-features: create staff login; list of active users; edit user; link a user to a schedule resource (trainer/venue calendar) to unlock resource-scoped permissions and reporting; opt a linked user into attendance-change emails; SMS notification target (cell number + carrier); user email doubles as reply-to for emails and campaigns sent by that user; every Time Clock or POS operator needs an individual login; hourly rates per job set on the user (owned by Staff cluster).
- Settings / options: Role (required); First name; Last name; Email; Username; Password; Cellular phone; Cell provider (carrier list) or "Don't use SMS"; linked resource; "Send Email Notifications For" (resource link, Classic label); user status Active vs inactive (inferred from "Active Users" list); IP restriction (PLT-07).
- Rules / limits: username unique; password policy differs by UI generation: Classic min 6 chars with letters and digits, New min 12 chars with at least one digit and one uppercase; scheduling, reporting and attendance permissions only take effect when the user is linked to a resource; attendance-change emails fire when a status change alters class size (e.g. Scheduled to Reschedule, Waitlist to Scheduled) and do nothing if the user is linked to a salesperson; employee users are unlimited on every plan.
- User story: As an admin, I want to create individual staff logins tied to a role and optionally to a calendar resource, so that each employee sees and does only what their job needs.
- Actors: owner/admin (Manager role).
- UI generation: both (Classic: Administration > User Administration; New: Administration > Location Settings > Users)
- Priority: P0
- Evidence: https://support.ezfacility.com/hc/en-us/articles/29554644710171-Creating-A-New-User, https://support.ezfacility.com/hc/en-us/articles/4402427180315-Creating-A-New-User, https://support.ezfacility.com/hc/en-us/articles/4402434192027-How-to-Set-Up-Your-New-Account, https://support.ezfacility.com/hc/en-us/articles/30051822805659-How-to-Use-the-Employee-Time-Clock-in-EZFacility-Classic, https://www.ezfacility.com/plans-pricing/pricing-results

### PLT-03 Staff password administration
- Sub-features: admin types a new password for another user; admin triggers a reset that emails the user; confirmation dialog after a reset (shipped 2023-11-08, Classic).
- Settings / options: manual password field; "Reset Password" (Classic: emails a temporary password) / "Password Reset" (New: emails a reset link).
- Rules / limits: reset goes to the email on the user record; no self-service forgot-password flow is described in the public articles for staff (unknown).
- User story: As an admin, I want to set or reset a colleague's password, so that locked-out staff regain access without contacting the vendor.
- Actors: owner/admin.
- UI generation: both (delivery differs: temporary password vs link)
- Priority: P0
- Evidence: https://support.ezfacility.com/hc/en-us/articles/29554698393883-How-to-Change-a-User-s-Password, https://support.ezfacility.com/hc/en-us/articles/4402427178395-How-to-Change-a-User-Password, https://support.ezfacility.com/hc/en-us/articles/20241459046683-November-8th-2023-Release-Notes

### PLT-04 Roles and permission catalogue
- Sub-features: built-in roles; custom roles created blank or cloned from an existing role; per-permission allow/deny checkboxes grouped by area; edit and delete custom roles; reservation-type-scoped permissions (one grant per reservation type, back-filled from the former single permission, shipped 2024-07-03); refund permission also masks card type and bank account data; trainers restricted to their own data in reports (inferred from release notes); individual permissions named in training demos: membership area (create contracts, edit contracts, edit Sold By, membership administration i.e. create plans, cancel, share), reservation attendance statuses (early cancel, late cancel, no-show) grantable separately from the default manual scheduled-to-attended change, and refund / reverse / void.
- Settings / options: built-in roles (New): Manager (everything), Staff (most areas, not Administration or Reporting), Trainer (Staff variant for trainers), View Only (schedule read-only). Permission areas (New): Hidden, General, Administration, Report, Billing, POS, Document, Membership, Reservation, Package, Pre-Defined Items, Client, Group/Subgroup. Role fields: name, "Apply an existing role" / base role template. Each permission: granted or denied. Extra section on the user permission page: Reservation Type Permissions.
- Rules / limits: cloning copies permissions and never alters the source role; only custom roles show edit/delete controls (Classic, inferred); individual permission names are not published (only the 13 area names); an accountant-style role limited to financial reports is the vendor's own example; preset Staff role as demonstrated (New): may create contracts but not cancel or share memberships, may not run billing or training reports, may not refund, reverse or void, and may not set early-cancel, late-cancel or no-show unless granted (a manager does it otherwise); there is no on-the-spot supervisor override, so a blocked action needs an authorised user to log in or the permission to be changed first.
- User story: As an owner, I want to define roles with fine-grained permissions, so that bookkeepers, trainers and front-desk staff each get a least-privilege workspace.
- Actors: owner/admin.
- UI generation: both (Classic: User Administration > Role Administration; New: Location Settings > Roles)
- Priority: P0
- Evidence: https://support.ezfacility.com/hc/en-us/articles/29748234477595-Creating-A-Custom-Role, https://support.ezfacility.com/hc/en-us/articles/4402434188187-Creating-a-Custom-User-Role, https://support.ezfacility.com/hc/en-us/articles/22791705622811-Where-to-find-edit-and-create-Roles-on-EZFacility, https://support.ezfacility.com/hc/en-us/articles/4402434192027-How-to-Set-Up-Your-New-Account, https://support.ezfacility.com/hc/en-us/articles/34155834657819-July-3rd-2024-Release-Notes, https://support.ezfacility.com/hc/en-us/articles/16731304236571-June-28th-2023-Release-Notes, https://www.youtube.com/watch?v=KAN6h9vPUiM (t=08:14), https://www.youtube.com/watch?v=Rjy8ZpfIA68 (t=24:35)

### PLT-05 Role assignment and per-user permission overrides
- Sub-features: choose a default or custom role when creating a user; change the role of an existing user; edit one user's permissions away from the role template (shield icon on the user row); marker on users whose permissions diverge from their role.
- Settings / options: Role drop-down on the user form; per-user permission grid (same catalogue as PLT-04); asterisk shown next to the role name when the user's permissions were edited from the template.
- Rules / limits: one role per user (inferred: single-select drop-down); override semantics on later role edits are not documented (see unknowns).
- User story: As an admin, I want to assign a role and then tweak one person's permissions, so that exceptions do not force me to create a new role.
- Actors: owner/admin.
- UI generation: both
- Priority: P0
- Evidence: https://support.ezfacility.com/hc/en-us/articles/34419227413659-Assigning-A-Role-to-A-User, https://support.ezfacility.com/hc/en-us/articles/4402427179419-Adding-a-Role-to-a-User, https://support.ezfacility.com/hc/en-us/articles/4402434192027-How-to-Set-Up-Your-New-Account, https://support.ezfacility.com/hc/en-us/articles/27808006885275-Change-Permissions-for-Email-Campaigns-2024

### PLT-06 Email-campaign permission levels
- Sub-features: graded access to the email-campaign tool, set on a role or on an individual user.
- Settings / options: level enum: Publisher (create, edit, view, send), Editor (view and edit; no create, no send), Viewer (view only), None (no access).
- Rules / limits: only users holding the Manager role can change these levels.
- User story: As a manager, I want to let staff draft campaigns without being able to send them, so that outbound email is reviewed before it goes out.
- Actors: Manager role.
- UI generation: New
- Priority: P1
- Evidence: https://support.ezfacility.com/hc/en-us/articles/27808006885275-Change-Permissions-for-Email-Campaigns-2024

### PLT-07 IP address restriction for staff access
- Sub-features: allow-list of IP addresses from which a staff user may use the system (documented in the time-clock context to stop off-site clock-ins); current IP pre-filled; multiple addresses; remove an address.
- Settings / options: IP Address Restriction list; "Allow access from any IP Address" checkbox (a.k.a. "Allow from any IP Address").
- Rules / limits: scope (per user vs per location, whole login vs time clock only) is not stated; a 2023-04-18 fix says error messages now show when the allow-any option is on, which implies the check runs at login.
- User story: As an owner, I want staff logins limited to the facility's network, so that employees cannot clock in or open the back office from home.
- Actors: owner/admin; staff.
- UI generation: Classic documented; New unknown
- Priority: P1
- Evidence: https://support.ezfacility.com/hc/en-us/articles/30051822805659-How-to-Use-the-Employee-Time-Clock-in-EZFacility-Classic, https://support.ezfacility.com/hc/en-us/articles/14655161654811-April-18th-2023-Release-Notes

### PLT-08 Location branding assets (logos)
- Sub-features: per-location logo used in the app header, receipts, invoices, reports and email campaigns; separate "vanity" logo shown top-left inside the back office; further distinct slots for the public logo, the online-registration (OLR) logo and the self-service logo; upload with progress indicator; remove vanity logo; PDF reports scale the logo so it does not overlap data (fix 2023-08-31); support staff can upload on the customer's behalf.
- Settings / options: logo slots enum: location logo, vanity logo, public logo, OLR logo, self-service logo. Classic logo constraints: max 80 px high, max 240 px wide, .gif, lowercase filename without punctuation. New "Location Public Logo": ideal 240 px wide, square 240 x 240.
- Rules / limits: Classic and New constraints conflict (GIF 240x80 vs 240x240, format unstated); slots are independent (changing one does not change the others).
- User story: As an admin, I want my logo on every customer-facing document and screen, so that the system looks like my brand.
- Actors: account administrators; vendor support.
- UI generation: both
- Priority: P1
- Evidence: https://support.ezfacility.com/hc/en-us/articles/4403486986011-Uploading-Your-Logo, https://support.ezfacility.com/hc/en-us/articles/4403486989083-Uploading-Your-Vanity-Logo, https://support.ezfacility.com/hc/en-us/articles/22795613046299-Location-Setup, https://support.ezfacility.com/hc/en-us/articles/4402434192027-How-to-Set-Up-Your-New-Account, https://support.ezfacility.com/hc/en-us/articles/18408526583067-August-31st-2023-Release-Notes

### PLT-09 UI generation switch and default platform
- Sub-features: per-location choice of which UI generation opens after login; in-session link to switch between Classic and New Experience (moved to the mobile footer bar 2023-09-13); account-level opt-in to the New UI, with some accounts fully transitioned and unable to go back.
- Settings / options: Default Platform drop-down on Location Details (values not published; inferred: Classic, New Experience); session switch "switch to classic" / "new experience".
- Rules / limits: the system always opens in the chosen platform; some features exist only in New (e.g. vaccine passport, email-campaign permission levels) or only for fully transitioned accounts; new features ship only in the New UI; reports and report permissions are the same in both UIs (a customer-retention report is missing in New per webinar Q&A); after the 2026 scheduling release an account may still switch back to Classic, but rental rules and types lose the new options, and the vendor advises moving the whole facility at once instead of individual staff.
- User story: As an admin, I want to choose which interface my staff land in, so that we can migrate to the new UI at our own pace.
- Actors: owner/admin; any staff user (session switch).
- UI generation: both
- Priority: P2 (legacy coexistence; we ship one UI. Dates: New UI announced 2021-10-12, Classic still live 2024-09-20)
- Evidence: https://support.ezfacility.com/hc/en-us/articles/29584008031259-How-to-choose-your-EZFacility-default-platform-on-the-Classic-EZFacility-Experience, https://support.ezfacility.com/hc/en-us/articles/29583648663195-How-to-choose-your-EZFacility-default-platform-on-the-New-EZFacility-Experience, https://support.ezfacility.com/hc/en-us/articles/18741009680795-September-13th-2023-Release-Notes, https://www.ezfacility.com/blog/product-update-get-ready-for-an-awesome-new-ui-experience, https://www.ezfacility.com/blog/software-release-groups-new-ui, https://www.youtube.com/watch?v=TWNQ4cTiEFs, https://support.ezfacility.com/hc/en-us/articles/55926816152603-How-to-Switch-to-the-NewUI (title only, body not read), https://www.youtube.com/watch?v=TWNQ4cTiEFs (t=01:07, t=32:57), https://www.youtube.com/watch?v=SzgMT6X961A (t=47:45)

### PLT-10 Per-user UI preferences (sidebar, dark mode)
- Sub-features: collapse/expand the sidebar on the group page with the state remembered; slide-out navigation that can be hidden (New UI); dark mode (title-only evidence).
- Settings / options: sidebar collapsed yes/no (remembered); theme light/dark (inferred from title).
- Rules / limits: persistence scope (per user vs per browser) unknown.
- User story: As a staff user, I want the layout to stay how I left it, so that I get more working space on small screens.
- Actors: any staff user.
- UI generation: Classic (sidebar article); New (slide-out nav, dark mode inferred)
- Priority: P2
- Evidence: https://support.ezfacility.com/hc/en-us/articles/4404931922843-How-to-Hide-Expand-Side-Bar-Menu, https://www.ezfacility.com/blog/product-update-get-ready-for-an-awesome-new-ui-experience, https://support.ezfacility.com/hc/en-us/articles/42913648411931-Dark-Mode (title only, body not read)

### PLT-11 League-module staff users and access levels
- Sub-features: separate user list inside the league module; fixed access levels; single sign-on from the main product into the league module; SSO users can edit their own profile (fix 2023-04-18).
- Settings / options: access level enum: Super User (account owner; only one who can add users), Admin (full access except user management), Scorekeeper (Manage Scores only), Advertising Manager (Advertising only; not present in every account). User details: all fields required (names not published).
- Rules / limits: only the Super User may add users; until 2024-01-17 a defect let Admins modify the Super User or add users, now blocked for both create and edit.
- User story: As a league owner, I want scorekeepers to enter results without seeing the rest of the admin, so that volunteers can help safely.
- Actors: Super User; Admin; Scorekeeper; Advertising Manager.
- UI generation: n-a (league module UI)
- Priority: P1
- Evidence: https://support.ezfacility.com/hc/en-us/articles/4405044353435-How-to-Create-a-User-Account, https://support.ezfacility.com/hc/en-us/articles/26596341240091-How-to-Create-a-User-Account-in-EZLeagues, https://support.ezfacility.com/hc/en-us/articles/22122496577179-January-17th-2024-Release-Notes, https://support.ezfacility.com/hc/en-us/articles/14655161654811-April-18th-2023-Release-Notes

### PLT-12 League public-site options
- Sub-features: facility logo for the public league site; show/hide each public menu item; colour scheme by colour code including a custom link colour (shipped 2023-03-09); default filters and sort for the public Leagues page and the Tournaments page; default schedule view list with visitor toggle to grid; logos and banners auto-resize on mobile.
- Settings / options: Facility Logo (JPG only); Menu Options (checkbox per item); Site Colors (hex per slot, incl. primary and "Link Color"); Leagues Page Options and Tournament Page Options, each with filters Status, Sport, Season, Age Group, Division plus Sorting; schedule view default list / grid.
- Rules / limits: page filters only preset the initial list and visitors can change them; white as primary colour can make text invisible (no contrast validation, although release notes mention later "site color validation").
- User story: As a league admin, I want to brand the public league site and choose what visitors see first, so that players find current leagues quickly.
- Actors: league admin.
- UI generation: n-a (league module UI)
- Priority: P1
- Evidence: https://support.ezfacility.com/hc/en-us/articles/26601309581211-How-to-Configure-your-Site-Options-for-EZLeagues, https://support.ezfacility.com/hc/en-us/articles/13526384977307-March-9th-2023-Release-Notes, https://support.ezfacility.com/hc/en-us/articles/11297336305691-December-15th-2022-Release-Notes

### PLT-13 Branded-app portal users
- Sub-features: user management inside the mobile-app admin portal; global admin flag for multi-location apps; location-scoped permissions; invitation email with set-password link; edit and delete logins; portal opened from the back office via Administration > Location Settings > MemberMe (new browser tab, separate portal credentials); "What's New" screen in the portal listing recent and in-progress features.
- Settings / options: username, first name, last name, email; "is this user an admin?" (manages all locations); location assignments with one primary/base location; per-location permission enum: "Manage location in app" (all portal changes) or "Send notifications for this location" (push only).
- Rules / limits: primary location mandatory; password is set by the invitee, never by the admin; this user table is separate from back-office users (PLT-02); no stated cap on the number of portal users (meant for managers who send pushes or edit announcements and news).
- User story: As an app admin, I want a marketing assistant who can only send push notifications for their own club, so that app content stays controlled.
- Actors: portal admin.
- UI generation: n-a (MiGym portal)
- Priority: P1
- Evidence: https://support.ezfacility.com/hc/en-us/articles/29244338187547-Creating-user-admin-profiles-for-MiGym-admin-portal-MemberMe-Branded-App, https://www.ezfacility.com/features/branded-mobile-app/, https://www.youtube.com/watch?v=uLNIb7JsjkM (t=07:10, t=20:32)

### PLT-14 Subscription plans, metered limits and add-on entitlements
- Sub-features: tiered plans metered on member count and resource count; feature tiers; purchasable or bundled add-ons; module gating in the UI (e.g. locker reports only appear when the Lockers module is purchased; Advertising Manager level only in some league accounts); one-time activation fee; annual discount; billing-team contact route for account changes; time-limited promotional offers made to webinar attendees (e.g. free software for the summer, valid until Sept 1).
- Settings / options: plans: Starter (500 members, 5 resources, chat+email support, limited features), Basic (1,500 / 15, phone+chat+email, basic features), Premium (3,000 / 30, all features, basic add-ons included), Ultimate (unlimited / unlimited, all add-ons). Add-ons named: Branded Mobile App, Advanced Email Marketing, EZLeagues, QuickBooks Online Sync; separately sold modules evidenced elsewhere: Locker Rentals. Billing cycle monthly / annual (15% saving). Activation fee 300-500 USD.
- Rules / limits: staff users and contacts are never metered; the pricing page carries two conflicting price blocks (144/203/280/509 USD per month vs an older garbled block starting 99); enforcement behaviour at the limit is not published.
- User story: As the platform operator, I want plan limits and add-on flags per tenant, so that features and capacity follow what the customer bought.
- Actors: platform operator; owner (buyer).
- UI generation: n-a
- Priority: P1
- Evidence: https://www.ezfacility.com/plans-pricing/pricing-results, https://support.ezfacility.com/hc/en-us/articles/4405044695835-Expiring-Lockers, https://support.ezfacility.com/hc/en-us/articles/4405044353435-How-to-Create-a-User-Account, https://support.ezfacility.com/hc/en-us/articles/15461639207963-Contacting-our-Billing-Team-to-Manage-Your-Account (title only, body not read), https://www.youtube.com/watch?v=DpQMHuC98yo (t=05:10)

### PLT-15 Cloud delivery and availability commitments
- Sub-features: browser-based back office with no install; responsive on any device; automatic updates; AWS hosting; PCI DSS Level 1; "unlimited storage" claim.
- Settings / options: none (non-functional).
- Rules / limits: uptime claim 99.99% (current site and 2022 post) vs 99% (2021 post); AWS migration announced 2021-10, executed 2022-10.
- User story: As an owner, I want a hosted system I never have to install or patch, so that I can run the facility from any device.
- Actors: all.
- UI generation: both
- Priority: P0 (non-functional baseline)
- Evidence: https://www.ezfacility.com/benefits, https://www.ezfacility.com/about-us, https://www.ezfacility.com/blog/ezfacility-amazon-web-services, https://www.ezfacility.com/blog/product-update-get-ready-for-an-awesome-new-ui-experience

### PLT-16 GDPR mode
- Sub-features: location-level switch for EU operators that turns on a GDPR consent document, permanent client deletion and personal-data export (the last two detailed in IMP-04); enabling shows the admin a prompt with a "take me there" shortcut to the document setup; with GDPR on and a consent template present, creating a client raises a consent pop-up and the profile carries a red no-consent banner until consent is recorded (detail owned by the Documents cluster).
- Settings / options: GDPR toggle on Location Setup.
- Rules / limits: intended for EU locations only; saving with the toggle on redirects the admin to Documents to author the GDPR document; vendor guidance at launch (spring 2018): applies to EU facilities and to non-EU facilities with EU customers, UK included after leaving the EU; data may be kept where a legitimate reason exists (e.g. an outstanding invoice), and accounting alone is not such a reason because invoices are retained anyway.
- User story: As an EU operator, I want a compliance mode, so that I can collect consent and honour erasure and access requests.
- Actors: owner/admin.
- UI generation: New (documented); Classic unknown; Classic (shown in the 2018 launch webinar)
- Priority: P1
- Evidence: https://support.ezfacility.com/hc/en-us/articles/22795613046299-Location-Setup, https://support.ezfacility.com/hc/en-us/articles/4402434192027-How-to-Set-Up-Your-New-Account, https://www.youtube.com/watch?v=C-7p_z3_Cxs (t=04:24, t=05:26, t=13:08, t=20:20)

### PLT-17 Account activity report (staff audit trail)
- Sub-features: report listing which staff user changed or deleted a record (example given: a schedule item) and the exact time of the action.
- Settings / options: none published (filters, date range and columns not shown).
- Rules / limits: only useful when every employee has an individual login, which is the vendor's stated reason against shared usernames; covered events, retention period and menu location are not published (see unknowns).
- User story: As an owner, I want to see who changed or deleted something and when, so that I can resolve disputes and hold staff accountable.
- Actors: owner/admin (Manager role).
- UI generation: unknown (mentioned verbally in a staff-training webinar, no screen shown)
- Priority: P1
- Evidence: https://www.youtube.com/watch?v=BV8yGHt8ENY (t=15:34)

## Locations & Resources

### RES-01 Location profile and operational settings
- Sub-features: edit identity and contact details of a location; choose accepted card brands; set daily run times for renewals and autopay; decline-notification behaviour; time-clock rounding; schedule drag-and-drop default; compliance toggles; default UI platform; location time zone used for timestamps and "day" boundaries.
- Settings / options: Location Label (internal name); Public Name (customer-facing); Address; Phone; Email (visible to customers); Alert Email (receives failed-card notices only; billing mailbox advised); Website; Integrated Credit Card Types Allowed (only visible once a merchant processor is integrated); Location Public Logo (PLT-08); Membership Renewal run time; Package Renewal run time (replenishes package quantity and takes payment); Auto Pay Run Time; Send One Failed Transaction Email (yes = one daily digest of declines, no = one email per decline); Time Clock Rounding (round up / round down; increments not published); Drag & Drop Default enum: Reschedule, Move Booking, No Default; GDPR toggle (PLT-16); Vaccine Passport toggle (default off; owned by Check-in cluster); Default Platform (PLT-09); time zone (inferred field; referenced as "facility/location time zone").
- Rules / limits: the client always receives an immediate decline email regardless of the digest setting; picking a drag-and-drop default hides the other choice at move time; a day for access rules runs midnight to midnight in the location time zone; facility hours are edited from this screen (RES-02).
- User story: As an owner, I want each location to carry its own identity and batch-job timings, so that billing and scheduling behave correctly for that site.
- Actors: owner/admin.
- UI generation: both (Classic: Administration > Account Setup > Location & Trainer Setup; New: Administration > Location Settings > Location Setup)
- Priority: P0
- Evidence: https://support.ezfacility.com/hc/en-us/articles/22795613046299-Location-Setup, https://support.ezfacility.com/hc/en-us/articles/4402434192027-How-to-Set-Up-Your-New-Account, https://support.ezfacility.com/hc/en-us/articles/29584008031259-How-to-choose-your-EZFacility-default-platform-on-the-Classic-EZFacility-Experience, https://support.ezfacility.com/hc/en-us/articles/34406647603227-Enabling-the-Vaccine-Passport-Feature-in-EZFacility-Classic, https://support.ezfacility.com/hc/en-us/articles/16846068050715-July-3rd-2023-Release-Notes, https://support.ezfacility.com/hc/en-us/articles/23328878237467-February-28th-2024-Release-Notes, https://www.ezfacility.com/blog/software-release-vaccine-passport

### RES-02 Facility hours
- Sub-features: weekly opening hours per location that set the visible start and end of the schedule grid; per-day closed flag.
- Settings / options: per weekday: start time, end time, closed checkbox.
- Rules / limits: applies year-round; holidays and one-off closures cannot be expressed here; hours are not published to customers, they only bound the schedule display; in New the hours show on the schedule only after resources have been added to it.
- User story: As an admin, I want the calendar to show only our operating hours, so that staff do not scroll through dead time.
- Actors: owner/admin.
- UI generation: both (Classic: Administration > Facility Hours; New: link inside Location Setup)
- Priority: P0
- Evidence: https://support.ezfacility.com/hc/en-us/articles/4403486971675-How-To-Set-Facility-Hours-in-EZFacility-Classic, https://support.ezfacility.com/hc/en-us/articles/22934947867547-Facility-Hours-Setup, https://support.ezfacility.com/hc/en-us/articles/4402434192027-How-to-Set-Up-Your-New-Account

### RES-03 Venues (bookable resources) and sub-venues
- Sub-features: define the physical spaces or equipment that get a calendar column: fields, courts, studios, batting cages, tunnels, ice sheets, lanes, rooms, pools, equipment; assign each to a schedule group; manual display order; edit in place; rentable by clients, blockable by trainers, usable for league games; sub-venues as child spaces of a venue (New Scheduling Experience, 2026-06); resource admin settings relocated in the 2026 scheduling refresh; resources ordered naturally when names contain numbers (self-service fix 2023-07-03); resource count is a plan-metered unit (PLT-14); sub-venues are created from a Sub Venues tab inside the venue ("create sub venue"), and each child can carry its own rental rates and types (e.g. full turf priced apart from quarters).
- Settings / options: Venue Name; Schedule Group; sort order (up/down arrows); parent venue (sub-venues); resource kind (venue vs trainer; trainers and salespeople are configured in sibling tabs of the same location screen and belong to the Staff cluster).
- Rules / limits: every resource should sit in a schedule group; conflict semantics between a parent venue and its sub-venues are not published; delete behaviour for venues with history is not published; parent/child conflict rule as demonstrated (2026 webinar): renting a sub-venue blocks the parent and renting the parent blocks every sub-venue; self-service lists only the sub-venues when the rental type is linked to them, and only the full venue when it is linked to the parent.
- User story: As an admin, I want to model every rentable space once, so that scheduling, rentals, leagues and self-service all book against the same calendar.
- Actors: account administrators.
- UI generation: both (Classic: Location & Trainer Setup > Venues tab; New: resource setup on the calendar)
- Priority: P0
- Evidence: https://support.ezfacility.com/hc/en-us/articles/4403493938843-Adding-or-Editing-a-Venue-in-EZFacility-Classic, https://support.ezfacility.com/hc/en-us/articles/4402434192027-How-to-Set-Up-Your-New-Account, https://www.ezfacility.com/features/scheduling-operations, https://www.ezfacility.com/plans-pricing/pricing-results, https://www.youtube.com/watch?v=SzgMT6X961A, https://support.ezfacility.com/hc/en-us/articles/16846068050715-July-3rd-2023-Release-Notes, https://support.ezfacility.com/hc/en-us/articles/45100513622171-How-to-Setup-Resources-on-Your-Calendar (title only, body not read), https://www.youtube.com/watch?v=SzgMT6X961A (t=06:41, t=21:00, t=31:19)

### RES-04 Schedule groups
- Sub-features: named categories that partition the schedule (e.g. courts, cages); grouping lets a client or staff member rent several resources of the group in one action; renamed "Resource Groups" in the New Scheduling Experience, where they appear as header rows on the resource view.
- Settings / options: schedule group name; membership of venues and trainers in a group.
- Rules / limits: each resource belongs to exactly one group (inferred: single-select drop-down); groups are per location (inferred); a group is only a header: nothing can be scheduled on the group itself.
- User story: As an admin, I want to group similar resources, so that staff can filter the calendar and book several courts at once.
- Actors: owner/admin.
- UI generation: both
- Priority: P0
- Evidence: https://support.ezfacility.com/hc/en-us/articles/4402434192027-How-to-Set-Up-Your-New-Account, https://support.ezfacility.com/hc/en-us/articles/4403493938843-Adding-or-Editing-a-Venue-in-EZFacility-Classic, https://www.youtube.com/watch?v=SzgMT6X961A (t=05:40)

### RES-05 Linked multi-resource reservations (trainer plus venues)
- Sub-features: while booking a trainer session, select one or many venues to hold; held venues show as unavailable (grey) on their own rows; the holds follow the reservation on drag-and-drop; recurrence applies to trainer and venue holds together; opening either entry opens the same reservation; deleting any entry releases all linked resources; marketing describes the same as allocating multiple venues to one event.
- Settings / options: venue multi-select on the reservation form (Ctrl-click, select all); save actions: Save and Finish, Save and Add a Client, set recurrence; display states: full/partial session colour on trainer row, grey "Unavailable" on venue row; account-level enable/disable of the Advanced Multi-Scheduling mode.
- Rules / limits: Advanced Multi-Scheduling and the older Multi-Scheduling mode are mutually exclusive, and the legacy mode is switched off automatically while the advanced mode is enabled; replaces manual blocking bookings; creating more than 300 linked reservations in one action used to time out, fixed 2025-04-23 with 1,500+ supported; dragging onto an overlapping slot on the same resource was a defect fixed 2024-06-19 (overlap must be rejected).
- User story: As a scheduler, I want a class to reserve its instructor and its room in one step, so that neither can be double-booked.
- Actors: admin, front desk scheduler.
- UI generation: Classic (documented); New (inferred equivalent via resource view)
- Priority: P0
- Evidence: https://support.ezfacility.com/hc/en-us/articles/4404311244187-Advanced-Multi-Scheduling-in-EZFacility-Classic, https://support.ezfacility.com/hc/en-us/articles/4404311249435-Multi-Scheduling-a-Trainer-and-a-Venue-for-a-Single-Reservation-in-EZFacility-Classic, https://www.ezfacility.com/features/scheduling-operations, https://support.ezfacility.com/hc/en-us/articles/36516396025115-April-23rd-2025-Release-Notes, https://support.ezfacility.com/hc/en-us/articles/4404311317403-Online-Webinar-Introducing-Self-Check-In-Advanced-Multi-Scheduling

### RES-06 League venues and facility-resource mapping
- Sub-features: league module keeps its own venue list for game scheduling; each league venue can map to one or more facility resources so scheduled games appear on (and occupy) the facility calendar; public description per venue.
- Settings / options: Venue name; Description (public site); mapped facility venues (dual list, available to mapped).
- Rules / limits: the mapping control only appears when the league account is linked to a facility account ("EZF 4.0" or "TMS/TCMS"); one league venue may map to several facility resources.
- User story: As a league admin, I want league games to block the real field on the facility calendar, so that rentals and games never collide.
- Actors: league admin.
- UI generation: n-a (league module UI)
- Priority: P1
- Evidence: https://support.ezfacility.com/hc/en-us/articles/4405051095195-How-to-Add-Venues, https://support.ezfacility.com/hc/en-us/articles/26569114691099-How-to-Add-Venues, https://support.ezfacility.com/hc/en-us/articles/4403493938843-Adding-or-Editing-a-Venue-in-EZFacility-Classic

### RES-07 Locker rooms and bulk locker creation
- Sub-features: define locker rooms; generate lockers in bulk by number range and size; several ranges per room to mirror physical layout; delete a room. Renting, clearing and locker reports belong to other clusters.
- Settings / options: locker room name; gender; range start; range end; locker size (size list not published); locker status (inferred: available, rented, expired).
- Rules / limits: sold as a separate Lockers module; numbering uniqueness scope (per room vs per location) not published.
- User story: As an admin, I want to load my locker bank quickly, so that front desk can rent lockers by number.
- Actors: owner/admin.
- UI generation: Classic
- Priority: P1
- Evidence: https://support.ezfacility.com/hc/en-us/articles/4405051209883-How-to-Set-Up-a-Locker-Rentals-in-EZFacility-Classic, https://support.ezfacility.com/hc/en-us/articles/4405044695835-Expiring-Lockers

### RES-08 Locker terms
- Sub-features: named date ranges offered as rental periods for lockers; add, edit, delete, reorder.
- Settings / options: Term Name; Starts; End; sort order.
- Rules / limits: the rental flow also offers default terms Day, Week, etc. (see Scheduling cluster); how custom terms combine with those defaults is not published.
- User story: As an admin, I want season-length locker terms, so that all seasonal rentals expire on the same day.
- Actors: owner/admin.
- UI generation: Classic
- Priority: P1
- Evidence: https://support.ezfacility.com/hc/en-us/articles/4405044650779-How-to-Set-Up-Terms-for-Locker-Rentals-in-EZFacility-Classic, https://support.ezfacility.com/hc/en-us/articles/4405044656411-How-to-Rent-a-Locker-in-EZFacility-Classic

### RES-09 Padlock inventory
- Sub-features: register padlocks with number and combination; edit; soft delete/disable; view disabled or deleted locks and purge them permanently.
- Settings / options: Lock number; Combination; status enum: active, disabled/deleted (soft), purged.
- Rules / limits: combinations are held as plain data (our note: treat as a secret, encrypt and permission-gate); the lock-to-locker assignment step is not described.
- User story: As front desk, I want to look up a lock's combination, so that I can open or reissue a locker.
- Actors: owner/admin; front desk.
- UI generation: Classic
- Priority: P2
- Evidence: https://support.ezfacility.com/hc/en-us/articles/4405044678811-How-to-Manage-Lockers-in-EZFacility-Classic

## Data Import/Export

### IMP-01 Onboarding import templates (contacts, contracts, POS products)
- Sub-features: three fixed spreadsheet layouts: (1) Basic Contact: names, address, demographics, basic membership info, remaining sessions on a package, card or bank account on file; (2) Advanced Contact: everything in Basic plus full membership contracts with billing terms, optional first-term invoice and stored payment details; (3) POS product list; support describes the importable data as clients, basic location/contact info, memberships and POS inventory (items, brands and similar).
- Settings / options: import type enum: Basic Contact, Advanced Contact, POS; template files Basic_Contact_Import_-_Updated.xls, TMS_Master_Import_Template.xls, POS_Products_Template_Updated.xls; DOB format MM/DD/YYYY or DD/MM/YYYY.
- Rules / limits: past invoices and payment history cannot be imported; columns may not be renamed or added; the Advanced layout needs per-membership-type details and a vendor review before submission; the Basic template is sent at account creation; a 2025-04-09 fix restored the state field after client import; schedules cannot be imported from a file and leagues must be built by hand (support statement in a New-UI leagues webinar).
- User story: As a new customer, I want to load my members, their plans, balances and products from spreadsheets, so that I can go live without re-keying data.
- Actors: owner/admin; vendor support technician.
- UI generation: Classic (templates apply to the account regardless of UI)
- Priority: P1
- Evidence: https://support.ezfacility.com/hc/en-us/articles/34419970103963-The-Three-Types-of-Imports-Available, https://support.ezfacility.com/hc/en-us/articles/34419979004187-The-Three-Types-of-Imports-Available, https://support.ezfacility.com/hc/en-us/articles/4405372124059-The-Three-Types-of-Imports-Available, https://support.ezfacility.com/hc/en-us/articles/4404305442587-Submitting-a-Client-Data-Import-in-EZFacility-Classic, https://support.ezfacility.com/hc/en-us/articles/36516560976539-April-9th-2025-Release-Notes, https://www.youtube.com/watch?v=j4Rn9joKKpQ (t=28:34, t=34:43)

### IMP-02 Assisted import submission and migration service
- Sub-features: imports are executed by vendor staff, not self-serve; customer attaches the filled template to a support ticket of type Import; vendor markets migration of members, schedules, packages and balances from competitor systems with a dedicated onboarding trainer.
- Settings / options: Ticket Type = Import; file upload (Browse, Begin upload); other required ticket fields not published.
- Rules / limits: first import free, later imports chargeable; missing columns require a call to support; no public evidence of validation reports, dry runs or rollback.
- User story: As a new customer, I want the vendor to load my data for me, so that I do not risk corrupting my account.
- Actors: owner/admin; vendor support.
- UI generation: Classic (Help/Support > Request Support)
- Priority: P1 (we replace with self-serve import; keep an operator-assisted path)
- Evidence: https://support.ezfacility.com/hc/en-us/articles/4404305442587-Submitting-a-Client-Data-Import-in-EZFacility-Classic, https://www.ezfacility.com/benefits, https://www.ezfacility.com/ezfacility-vs-abc-glofox

### IMP-03 Client demographic export
- Sub-features: export a chosen set of clients, optionally with membership data, as a generated report that can be downloaded in several formats; typical use is mail merge.
- Settings / options: client-set selector (values not published); include membership information yes/no; output format drop-down: Excel, CSV, PDF and others.
- Rules / limits: two-step (Generate Report, then pick format and Export); column selection is not offered (users are told to delete unwanted columns in the file).
- User story: As an admin, I want my client list in Excel, so that I can run mail merges and external analysis.
- Actors: owner/admin.
- UI generation: Classic (Administration > Client Administration > Export Clients)
- Priority: P1
- Evidence: https://support.ezfacility.com/hc/en-us/articles/4405137464603-How-to-Export-Client-Demographic-Information

### IMP-04 Personal-data export and permanent deletion (GDPR)
- Sub-features: with GDPR mode on (PLT-16), staff can export one client's personal data and permanently delete a client; "export client data" downloads an Excel file of that client's personal information; permanent delete makes the user type "delete" to confirm.
- Settings / options: enabled only by the location GDPR toggle; a dedicated user permission controls permanent delete (PLT-04).
- Rules / limits: export format, scope of deletion (financial records, signed documents) and retention exceptions are not published; as demonstrated at launch (spring 2018): permanent delete cannot be undone and the vendor keeps no backup; only personal information is removed, while invoicing, revenue and payment history stay but are no longer linked to the person; renewing memberships and packages stop and are unmapped from the client; disabling the client is the alternative that keeps all data; existing data stays until staff delete it; guidance is to delete a client who refuses consent unless a business reason (current member, open invoice) justifies keeping the record.
- User story: As an EU operator, I want to fulfil access and erasure requests from inside the product, so that I stay compliant without vendor tickets.
- Actors: owner/admin.
- UI generation: New (documented); Classic (shown in the 2018 launch webinar)
- Priority: P1
- Evidence: https://support.ezfacility.com/hc/en-us/articles/4402434192027-How-to-Set-Up-Your-New-Account, https://support.ezfacility.com/hc/en-us/articles/22795613046299-Location-Setup, https://www.youtube.com/watch?v=C-7p_z3_Cxs (t=11:05, t=14:00, t=21:21, t=39:20, t=53:42)

## Support/Onboarding

### ONB-01 Account setup sequence and onboarding checklist
- Sub-features: recommended first-run order: review roles, create users, complete location details, upload logos, set renewal/autopay run times, time-clock rounding, schedule defaults, GDPR, facility hours, then resources (schedule groups, trainers, salespeople, venues); onboarding checklists for membership and group businesses (title-only evidence); vendor guidance to add venues and trainers, build schedules and memberships, then sell contracts.
- Settings / options: none of its own (sequence over PLT and RES settings).
- Rules / limits: anyone using the time clock needs a user profile; every resource should be in a schedule group.
- User story: As a new owner, I want a guided order of setup tasks, so that nothing blocks my first booking or sale.
- Actors: owner/admin; onboarding trainer.
- UI generation: both (article screenshots predate the New UI)
- Priority: P1
- Evidence: https://support.ezfacility.com/hc/en-us/articles/4402434192027-How-to-Set-Up-Your-New-Account, https://www.ezfacility.com/blog/how-to-succeed-with-ezfacility, https://support.ezfacility.com/hc/en-us/articles/52230184836379-Onboarding-Checklist-Membership-Checklist-Groups-Checklist (title only, body not read)

### ONB-02 Training library (webinars, videos, knowledge base)
- Sub-features: recorded "EZ Essentials" short webinars embedded in help articles, grouped by topic: league scheduling wizard (even/odd team leagues, double elimination), leagues in Classic (publishing groups to leagues, player stats), membership add-ons, packages and reservations, client management, client relationships, rentals, memberships, billing series (payment schedules, refunds, carts and invoices), self-service series (incl. video library and Zoom), scheduling series, trainers and scheduling; public knowledge base; in-app "Help & Training" link; knowledge-base link in the mobile footer; live webinar events.
- Settings / options: none.
- Rules / limits: video content only; articles carry agendas, not steps.
- User story: As a new staff member, I want short topic videos linked from the product, so that I can learn a task without a trainer.
- Actors: admin and staff learners.
- UI generation: Classic content mostly; n-a
- Priority: P2
- Evidence: https://support.ezfacility.com/hc/en-us/articles/4405044258075-Online-Webinar-EZLeagues-Scheduling-Wizard, https://support.ezfacility.com/hc/en-us/articles/4405051068827-Online-Webinars-EZLeagues-in-EZFacility-Classic, https://support.ezfacility.com/hc/en-us/articles/29852337573787-Online-Webinar-Using-Membership-Add-ons-in-EZFacility-Classic, https://support.ezfacility.com/hc/en-us/articles/34441526893339-Online-Webinar-Packages-and-Reservations-in-EZFacility-Classic, https://support.ezfacility.com/hc/en-us/articles/4405144373403-Online-Webinar-Client-Management-in-EZFacility-Classic, https://support.ezfacility.com/hc/en-us/articles/4405144375067-Online-Webinar-Setting-Up-Client-Relationships-in-EZFacility-Classic, https://support.ezfacility.com/hc/en-us/articles/4404314830107-Online-Webinar-Rentals-in-EZFacility-Classic, https://support.ezfacility.com/hc/en-us/articles/4406813864603-Memberships-Webinar, https://support.ezfacility.com/hc/en-us/articles/4404312896283-Online-Webinar-Billing-in-EZFacility-Classic-Series-Parts-1-3, https://support.ezfacility.com/hc/en-us/articles/4404305628059-Online-Webinar-Self-Service-Video-Library-Zoom-in-EZFacility-Classic, https://support.ezfacility.com/hc/en-us/articles/4404305637275-Online-Webinar-Using-Self-Service-in-EZFacility-Classic, https://support.ezfacility.com/hc/en-us/articles/4404312828059-Online-Webinar-Self-Service-in-EZFacility-Classic-Open-Training-Series-Parts-1-2, https://support.ezfacility.com/hc/en-us/articles/4404311241627-Online-Webinar-Scheduling-in-EZFacility-Classic-Series-Parts-1-3, https://support.ezfacility.com/hc/en-us/articles/4404311321115-Online-Webinar-Trainers-and-Scheduling-in-EZFacility-Classic, https://www.ezfacility.com/blog/resources-for-ezfacility-customers, https://www.ezfacility.com/events/, https://support.ezfacility.com/hc/en-us/articles/18741009680795-September-13th-2023-Release-Notes

### ONB-03 In-app support requests and support channels
- Sub-features: support ticket form inside the back office with ticket type and file attachment; channels phone, live chat, email; phone lines and mailboxes for US/Canada and UK; plan-gated channel availability; New UI "Give Feedback" button at the bottom of the screen (rating, then general feedback or bug report; goes to the developers, and support or development may reply; a development request is routed to product); chat-bubble bot that creates support tickets; "?" menu at top right with Events and Webinars recordings (also present in the league module); a feedback specialist on training webinars funnels requests to development.
- Settings / options: Ticket Type (only "Import" is published); attachment; plan gating: Starter chat+email, Basic and above add live phone.
- Rules / limits: published hours Monday-Friday 08:30-17:00 Eastern; out-of-hours contacts roll to the next business day.
- User story: As an admin, I want to raise a ticket with attachments from inside the product, so that support has my account context.
- Actors: owner/admin; vendor support.
- UI generation: Classic (Help/Support > Request Support); New unknown for the ticket form; New has the Give Feedback button, chat bot and "?" menu (video)
- Priority: P1
- Evidence: https://support.ezfacility.com/hc/en-us/articles/4404305442587-Submitting-a-Client-Data-Import-in-EZFacility-Classic, https://www.ezfacility.com/benefits, https://www.ezfacility.com/plans-pricing/pricing-results, https://www.ezfacility.com/blog/resources-for-ezfacility-customers, https://www.youtube.com/watch?v=j4Rn9joKKpQ (t=02:01, t=23:27, t=41:51), https://www.youtube.com/watch?v=TWNQ4cTiEFs (t=05:13), https://www.youtube.com/watch?v=ERaBaf5YWHo (t=28:36)

### ONB-04 Release notes and product-update notices
- Sub-features: dated release notes published in the help center roughly every two weeks, listing features and fixes per release; versioned notes (v104.0 onward) in 2026; one-off "important update" notices; smaller "features and fixes" blog posts with ticket keys.
- Settings / options: none.
- Rules / limits: users are advised to clear the browser cache after a release.
- User story: As an admin, I want to see what changed in each release, so that I can brief staff and spot fixes I was waiting for.
- Actors: all customers.
- UI generation: n-a
- Priority: P2
- Evidence: https://www.ezfacility.com/blog/ez-features-fixes-check-out-whats-new, https://support.ezfacility.com/hc/en-us/articles/14655161654811-April-18th-2023-Release-Notes, https://support.ezfacility.com/hc/en-us/articles/36516560976539-April-9th-2025-Release-Notes, https://support.ezfacility.com/hc/en-us/articles/44459810488603-Important-Update-to-EZFacility-v4-0-on-1-14-26 (title only, body not read)

### ONB-05 Customer-success services (onboarding trainer, account manager)
- Sub-features: dedicated onboarding trainer for each new customer; hands-on help through launch and first season; named account manager with periodic structured account reviews (announced for 2026); customers are encouraged to appoint several in-house "EZ experts"; the trainer makes follow-up calls at six months and annually.
- Settings / options: none (service, not software).
- Rules / limits: not a product capability; recorded because it shapes expectations for assisted setup and import.
- User story: As a new customer, I want a named person guiding my rollout, so that I reach go-live quickly.
- Actors: owner; vendor staff.
- UI generation: n-a
- Priority: P2
- Evidence: https://www.ezfacility.com/benefits, https://www.ezfacility.com/blog/new-year-opportunities-at-ezfacility, https://www.ezfacility.com/ezfacility-vs-abc-glofox, https://www.youtube.com/watch?v=BV8yGHt8ENY (t=02:18, t=15:34)

Conventions: "Classic" / "New" = the two UI generations of the reference product; "NSE" = the "New Scheduling Experience" calendar rolled out 2026-06-22 (evidence is webinar description + title-only articles, so NSE detail is thin). "(inferred)" marks our inference. Their term "venue" = our Resource; "reservation" = one calendar occurrence; "linked reservations" = a series. Resource/venue master data, locker master data, Groups/online registration, packages, self-service portal and reports are owned by other clusters and only cross-referenced here.

## Scheduling

### SCH-01 Schedule calendar views and navigation
- Sub-features: vertical single-day grid with resources as columns ("Datebook"); horizontal timeline ("EZ-View") in Day, Week (Mon-Sun) and Month modes; Month mode can be filtered to one weekday (e.g. every Monday); previous/today/next and date-picker navigation; NSE adds Resource view, Day, Week, Month views, hover details on a booking, calendar filtering, and a "setup resources on your calendar" admin step; one calendar shared by sessions, classes, rentals, league games, special blocks; marketed staff search for open dates/trainers/rooms; NSE view detail (video): Resource view is the landing page with resource columns under resource-group headers; Day view is an agenda-style list with a book-a-client button per slot; Week view stacks all seven days as columns without sideways scrolling and shades hours outside business hours darker; Month view is a classic grid whose cells show an overflow marker ("5+" style) when bookings do not fit; NSE search bar filters the visible bookings by reservation-type or rental-type name (everything else on the day is hidden), next to a colour-legend panel; NSE hover card is interactive (pointer can move into it) and lists date, time, venue, booked clients, spots left and who still owes a balance (paid-in-full clients flagged as paid), with three buttons: Open Clients (roster), Book a Client (jumps to registration for that session), Open Reservation Details
- Settings / options: view = Datebook | EZ-View; EZ-View range = Day | Week | Month; Month weekday filter (Mon..Sun); NSE view = Resource | Day | Week | Month; date/trainer/venue selectors on the schedule page.
- Rules / limits: Week runs Monday to Sunday; Datebook shows exactly one day; empty (grey) cells are the click target for creating a reservation; the Groups module is not connected to the calendar (group activity never shows as bookings; raised as customer feedback); the calendar date picker reaches back to 2015; the calendar's time increment is not customer-editable; only vendor support can change it on the back end
- User story: As a front-desk scheduler, I want to flip between a per-resource day grid and week/month timelines, so that I can see utilisation and find free slots quickly.
- Actors: staff (admin, front desk, trainer)
- UI generation: both (Datebook/EZ-View in New; NSE supersedes from 2026-06)
- Priority: P0
- Evidence: https://support.ezfacility.com/hc/en-us/articles/23852338482843-How-to-Change-your-Schedule-View, https://www.ezfacility.com/features/scheduling-operations, https://www.ezfacility.com/industries/gym-management-software, https://www.youtube.com/watch?v=SzgMT6X961A, https://support.ezfacility.com/hc/en-us/articles/45100513622171-How-to-Setup-Resources-on-Your-Calendar (title only, body not read), https://www.youtube.com/watch?v=SzgMT6X961A (t=02:36), https://www.youtube.com/watch?v=SzgMT6X961A (t=24:02), https://www.youtube.com/watch?v=SzgMT6X961A (t=13:48, t=35:25), https://www.youtube.com/watch?v=SzgMT6X961A (t=41:36), https://www.youtube.com/watch?v=KAN6h9vPUiM (t=40:11), https://www.youtube.com/watch?v=TWNQ4cTiEFs (t=37:08)

### SCH-02 Reservation types (activity-type master data)
- Sub-features: per-location list of activity types that drive both what can be put on the calendar and which packages can be sold/consumed; add, edit, reorder, delete; per-type defaults copied onto each new reservation (capacity, colour, revenue category, free-booking flag, session length); link to per-type online-booking options (SCH-03).
- Settings / options: Reservation Type (name); Can Schedule (appears in the type picker when creating a reservation); Can Sell (packages of this type can be sold; a type may be sell-only, used just to attach a package to a profile); Revenue Category (default for packages/rentals of the type); Class Size (default capacity; not applicable to rentals); Color; Reservation Category and Sub-category (grouping/tile in the member app, see SCH-04); Session Length (default duration, listed in one Classic article only); Default Allow Free Booking(s) (if off, a per-reservation "Allow Free Bookings" toggle still exists); sort order.
- Rules / limits: deleting a type also deletes its package plans, and clients still holding such packages can no longer self-book sessions restricted to them (New UI article); changing a type's Class Size affects only reservations created afterwards (see CLS-04); menu path differs by generation (Administration > Packages > Reservation Types vs Administration > Reservation Types).
- User story: As an owner, I want to define the kinds of sessions we run with their defaults, so that scheduling and package sales stay consistent and report to the right revenue category.
- Actors: owner/admin
- UI generation: both (same model; icon set differs: wrench in Classic vs gear in New for online options)
- Priority: P0
- Evidence: https://support.ezfacility.com/hc/en-us/articles/29783959046555-How-to-Set-Up-Reservation-Types-in-EZFacility-Classic, https://support.ezfacility.com/hc/en-us/articles/34440874732443-How-to-Set-Up-Reservation-Types-in-EZFacility-Classic, https://support.ezfacility.com/hc/en-us/articles/4402427203355-How-to-Set-Up-Reservation-Types

### SCH-03 Reservation-type online-booking options
- Sub-features: per-type self-service policy reached from the type row (wrench/gear); restrict which package types may be used to book; public description shown to the client at booking/payment; listing visibility including a private "Do Not List" mode; inherit-from-location default with per-type override; per-reservation Self-Booking flag and Public Title (SCH-07).
- Settings / options: Allowed Packages (package types accepted); Online Description; Use Location Default (checkbox; uncheck to override); listing option incl. Do Not List (other listing values not enumerated in the material); Total allowed participants (set on the reservation/type).
- Rules / limits: payment during self-booking is only possible when the required package is itself offered on self-service; unlisted sessions are reachable only by direct link (SCH-16); booking cut-off times and descriptions are shown to clients in the app/portal (cut-off setting location not documented for sessions).
- User story: As an admin, I want to control per activity type whether and how clients can book online, so that only eligible package holders can reserve and private sessions stay hidden.
- Actors: admin; client (affected)
- UI generation: both
- Priority: P0
- Evidence: https://support.ezfacility.com/hc/en-us/articles/30058087582875-Managing-Self-Service-Shared-Bookings-in-EZFacility-Classic, https://support.ezfacility.com/hc/en-us/articles/4404305610651-Managing-Self-Service-Shared-Bookings-in-EZFacility-Classic, https://support.ezfacility.com/hc/en-us/articles/34440874732443-How-to-Set-Up-Reservation-Types-in-EZFacility-Classic, https://support.ezfacility.com/hc/en-us/articles/4402427203355-How-to-Set-Up-Reservation-Types, https://apps.apple.com/us/app/memberme/id969248357

### SCH-04 Reservation categories
- Sub-features: location-level category list; assign reservation types/sessions to a category (and sub-category); rename category labels; categories group sessions into tiles on the member mobile app schedule.
- Settings / options: Category label; Sub-category label; path Administration > Location Settings > Reservation Categories; "Res. Category" selector on the reservation type.
- Rules / limits: shipped 2023-08-02; one Classic article lists Sub-category, the other two do not; only reservation types attached to a category are shown in the member app; the categories themselves are created by the vendor during app sign-up/training and the facility then attaches types to them
- User story: As an admin, I want to group activity types into member-facing categories, so that the app schedule is browsable.
- Actors: admin; member (app)
- UI generation: both
- Priority: P1
- Evidence: https://support.ezfacility.com/hc/en-us/articles/17574439837467-August-2nd-2023-Release-Notes, https://support.ezfacility.com/hc/en-us/articles/29783959046555-How-to-Set-Up-Reservation-Types-in-EZFacility-Classic, https://support.ezfacility.com/hc/en-us/articles/34440874732443-How-to-Set-Up-Reservation-Types-in-EZFacility-Classic, https://support.ezfacility.com/hc/en-us/articles/4402427203355-How-to-Set-Up-Reservation-Types, https://www.youtube.com/watch?v=uLNIb7JsjkM (t=23:36)

### SCH-05 Reservation-type permissions (per staff user)
- Sub-features: a section on the user-permissions page granting access per reservation type; replaces an older single reservation-types permission; newly created types are back-populated from existing permissions.
- Settings / options: per user x reservation type access flag (granularity view/create/edit not documented).
- Rules / limits: shipped 2024-07-03, applies in Classic as well; the default (non-manager) staff role can view and even create reservation types, but cannot create package plans
- User story: As an owner, I want to restrict which staff can schedule which activity types, so that trainers cannot alter programmes they do not run.
- Actors: owner/admin; staff (subject)
- UI generation: both
- Priority: P1
- Evidence: https://support.ezfacility.com/hc/en-us/articles/34155834657819-July-3rd-2024-Release-Notes, https://www.youtube.com/watch?v=Rjy8ZpfIA68 (t=05:09)

### SCH-06 Calendar colour coding, fill indicators and legend
- Sub-features: custom colour per reservation type; corner fill indicator on each session tile; colour legend opened from the schedule; recurring-series glyph next to the title; rentals drawn in a fixed rental colour with title plus client name; renewal marker ("R") on a session when the booked package is set to renew; dollar-sign icon on a rental tile flags an unpaid balance (New UI calendar before NSE; in NSE the owed/paid indicator sits only in the hover card, see unknowns)
- Settings / options: Color (per type); fill states Empty | Partially Full | Full (Classic wording); New UI corner colours yellow = no registrants, green = partially full, red = full.
- Rules / limits: built-in default colours cannot be changed; in Classic the corner indicator shows only on types given a custom colour; picking red for a capacity-1 type masks the red "full" marker.
- User story: As a scheduler, I want colour and fill cues on the calendar, so that I can spot open and full sessions at a glance.
- Actors: admin (configure); all staff (read)
- UI generation: both (state vocabulary differs)
- Priority: P1
- Evidence: https://support.ezfacility.com/hc/en-us/articles/4404311237659-How-to-Assign-Custom-Colors-to-Reservation-Types, https://support.ezfacility.com/hc/en-us/articles/27849876503323-Registering-A-Client-Into-Multiple-Available-Sessions, https://support.ezfacility.com/hc/en-us/articles/4402427209115-Registering-A-Client-Into-a-Single-Available-Session, https://support.ezfacility.com/hc/en-us/articles/4404308503195-How-to-Schedule-a-Rental-Reservation-in-EZFacility-Classic, https://support.ezfacility.com/hc/en-us/articles/18408526583067-August-31st-2023-Release-Notes, https://www.youtube.com/watch?v=7JVYZ3kxUAo (t=20:41), https://www.youtube.com/watch?v=SzgMT6X961A (t=35:25)

### SCH-07 Create an available (bookable) session, optionally split into slots
- Sub-features: click an empty cell on a trainer or venue column; choose kind "Session" then a reservation type; type defaults prefill and are editable per event; internal vs public title; per-reservation self-booking flag; split a long window into equal bookable slots; finish, or finish and immediately add clients; optional recurrence (SCH-09); NSE "add a session in Resource view" flow; API creation of session reservations; NSE has two entry points: click an empty time cell, or use the "Add Reservation" button whose drop-down offers Add Session | Add Rental; a venue and an instructor can be booked on the same session; reservation types created before NSE carry over unchanged
- Settings / options: reservation kind = Session | Rental | Special; Reservation Type; Class Size (max participants; when split, per slot); Title (staff calendar); Public Title (self-service schedule); Self-Booking (yes/no); Start Time; End Time (end of last slot when split); Split interval (15 / 30 / 45 / 60 ... minutes); Allow Free Bookings (per reservation); save actions "Save and Finish" | "Save and Add Clients".
- Rules / limits: a session can be booked by staff immediately or left open; public API (2024-06-05) can create session reservations but not rentals or special types, and can list reservation types (id + name) per location.
- User story: As a trainer, I want to publish a block of availability chopped into fixed slots, so that clients can book individual appointments themselves.
- Actors: admin, trainer, front desk; API client
- UI generation: both (Classic article; NSE flow title-only)
- Priority: P0
- Evidence: https://support.ezfacility.com/hc/en-us/articles/4404311260571-How-to-Schedule-an-Available-Session-in-EZFacility-Classic, https://support.ezfacility.com/hc/en-us/articles/26498179644187-June-5th-2024-Release-Notes, https://support.ezfacility.com/hc/en-us/articles/45196168160411-How-to-Add-a-Session-to-Your-Calendar-in-Resource-View (title only, body not read), https://www.youtube.com/watch?v=SzgMT6X961A (t=15:51)

### SCH-08 Special (non-client) reservations / time blocks
- Sub-features: block time on a trainer or venue with a typed, optionally titled, optionally recurring non-bookable reservation; payroll visibility for trainer blocks; blocking a venue removes it from online rental search.
- Settings / options: Special subtype = Floor Hours | Program Instruction | Unpaid Time | Unavailable; Start Time; End Time; Title (optional); recurrence.
- Rules / limits: clients cannot be booked into a special reservation; special blocks on a trainer column are reported in the Trainer Payroll/Commission report; "Unavailable" on a venue hides it from self-service rental availability for that span; API cannot create special types; Groups (leagues, programmes) do not appear on the calendar, so the documented workaround is a Special reservation retitled e.g. "League" to hold the space
- User story: As a scheduler, I want to mark blackout, floor and admin time on resources and staff, so that nobody books over it and paid non-client time reaches payroll.
- Actors: admin/scheduler
- UI generation: Classic documented (NSE webinar lists special reservations as a Q&A topic)
- Priority: P0
- Evidence: https://support.ezfacility.com/hc/en-us/articles/4404311270683-Scheduling-a-Special-Reservation-in-EZFacility-Classic, https://support.ezfacility.com/hc/en-us/articles/26498179644187-June-5th-2024-Release-Notes, https://www.youtube.com/watch?v=SzgMT6X961A, https://www.youtube.com/watch?v=VuUR1Y9bhjQ (t=37:56)

### SCH-09 Recurrence engine with pre-commit preview
- Sub-features: pattern picker; weekday multi-select; end by count or by date; "add occurrences" is repeatable so several patterns/resources can be stacked into one linked series; preview grid of generated occurrences with per-row delete/modify before commit; overnight spans via full start/end date-times; rentals reuse the same engine and add conflict colouring (SCH-12).
- Settings / options: Pattern = Single Entry | Daily | Weekly | Bi-Weekly | Monthly (same calendar date) | Yearly | Of the Month (nth weekday, e.g. every 4th Thursday); On These Days (weekday set); Range = total number of sessions | end date; preview row state "to be added" (green); NSE form: Recurring = yes, then Custom, "repeat every N weeks", weekday ticks, and a mandatory end (after N occurrences | on a date); the split-into-slots option sits on the same screen
- Rules / limits: generation previously timed out above ~300 linked occurrences; fixed 2025-04-23 to support 1,500+ per series; a pattern ending exactly at midnight must not roll the end date to the next day (fix 2023-08-16); rental articles list patterns without "Of the Month" and "Single Entry"; in a weekly pattern the weekday of the start date must stay ticked (unticking it errors); if the series was started on the wrong day staff cancel and start again on the right day
- User story: As a scheduler, I want to generate a whole season of sessions from a pattern and prune exceptions before saving, so that bulk scheduling takes minutes.
- Actors: scheduler/admin
- UI generation: both (Classic article; NSE flow title-only)
- Priority: P0
- Evidence: https://support.ezfacility.com/hc/en-us/articles/4404311308571-How-to-Create-Recurring-Sessions-in-EZFacility-Classic, https://support.ezfacility.com/hc/en-us/articles/36516396025115-April-23rd-2025-Release-Notes, https://support.ezfacility.com/hc/en-us/articles/17981009155995-August-16th-2023-Release-Notes, https://support.ezfacility.com/hc/en-us/articles/4404308503195-How-to-Schedule-a-Rental-Reservation-in-EZFacility-Classic, https://www.ezfacility.com/features/scheduling-operations, https://support.ezfacility.com/hc/en-us/articles/45196141671067-How-to-Create-a-Recurring-Session-on-the-Calendar-in-Resource-View (title only, body not read), https://www.youtube.com/watch?v=SzgMT6X961A (t=17:54), https://www.youtube.com/watch?v=7JVYZ3kxUAo (t=15:34)

### SCH-10 Edit a reservation and mass-edit its linked series
- Sub-features: per-field change on a single occurrence; "Linked Reservations" tab listing the whole series with checkboxes and date-range filter; mass modify (only fields filled in are applied); mass delete; preview of pending changes (changed rows highlighted, deleted rows red with action "Deleted") before commit; "TBD" (unassigned) occurrence can be created from the linked tab and later given a type; "Add More" occurrences to an existing series (see RNT-04).
- Settings / options: Modify Checked; Delete Checked; Mass Edit Options (field set not enumerated; includes class size, type); Preview Changes; Finish; filter by date range.
- Rules / limits: deletions need explicit confirmation; blank mass-edit fields leave values untouched; series edits are staged then committed atomically (inferred); NSE (2026-06): renaming a session changes only that occurrence, not the series, so each occurrence must be renamed (logged as feedback; differs from Classic mass-modify); a schedule built from several stacked patterns (e.g. a year of lessons) must be edited pattern by pattern from Linked Reservations (clear the filter, tick rows, Delete Checked / Modify Checked); drag-and-drop moves one occurrence at a time
- User story: As a scheduler, I want to change time, room or capacity on selected future occurrences of a series in one pass, so that I do not edit dozens of sessions by hand.
- Actors: admin/scheduler
- UI generation: Classic documented (New equivalent implied by "Linked Reservation tab" release-note fix)
- Priority: P0
- Evidence: https://support.ezfacility.com/hc/en-us/articles/4404311272731-How-to-Edit-a-Reservation-in-EZFacility-Classic, https://support.ezfacility.com/hc/en-us/articles/4404311324443-How-to-Edit-Class-Sizes-in-EZFacility-Classic, https://support.ezfacility.com/hc/en-us/articles/17574439837467-August-2nd-2023-Release-Notes, https://www.youtube.com/watch?v=SzgMT6X961A (t=44:42), https://www.youtube.com/watch?v=Rjy8ZpfIA68 (t=42:04)

### SCH-11 Delete reservations (delete mode and series scopes)
- Sub-features: calendar toggle that turns clicks into deletes; scope chooser relative to the clicked occurrence; custom picker page for arbitrary occurrences; NSE articles for deleting/removing a booking or session.
- Settings / options: delete scope = Just this One | Delete All (whole linked series) | Today's | Past | Future | Custom.
- Rules / limits: scopes apply only to occurrences linked to the clicked one; treatment of registered clients, consumed package sessions and invoices on delete is not documented; Delete Mode (calendar turns pink while active) exists only in the Day view of EZ-View, not in the other views
- User story: As a scheduler, I want to remove one occurrence or the remaining run of a series in two clicks, so that cancellations are quick.
- Actors: admin/scheduler
- UI generation: both (Classic documented; New title-only)
- Priority: P0
- Evidence: https://support.ezfacility.com/hc/en-us/articles/4404311287451-Deleting-Reservations-using-Delete-Mode-in-EZFacility-Classic, https://support.ezfacility.com/hc/en-us/articles/4404311326875-How-to-Delete-Reservations-Delete-Mode-in-EZFacility-Classic, https://support.ezfacility.com/hc/en-us/articles/23864931136795-Deleting-or-Removing-a-Booking-or-Session-on-the-Schedule (title only, body not read), https://www.youtube.com/watch?v=7JVYZ3kxUAo (t=25:50)

### SCH-12 Conflict detection and drag-and-drop rescheduling
- Sub-features: real-time double-booking prevention across sessions, rentals, classes and league games on the same resource; drag a tile to another time/resource; recurrence/add-more preview flags each generated occurrence as clear or conflicting; online rental search only offers conflict-free slots.
- Settings / options: preview state green = no conflict, orange = conflict; marketed "booking rules" (not enumerated).
- Rules / limits: a 2024-06-19 fix addressed dragging sessions onto overlapping times on the same resource, i.e. overlap is expected to be rejected; whether staff can force an overlap (override) is not documented; NSE drag-and-drop can move a booking to another time or to another resource inside the same resource group, but not across resource groups (2026-06)
- User story: As a facility manager, I want the system to refuse overlapping bookings on a court, so that customers never turn up to an occupied space.
- Actors: staff; client (online)
- UI generation: both
- Priority: P0
- Evidence: https://www.ezfacility.com/features/scheduling-operations, https://support.ezfacility.com/hc/en-us/articles/26750732215835-June-19th-2024-Release-Notes, https://support.ezfacility.com/hc/en-us/articles/4407310264475-How-to-Add-Additional-Rentals-to-an-Existing-Rental-in-EZFacility-Classic, https://www.ezfacility.com/blog/features-and-fixes-online-rentals, https://www.youtube.com/watch?v=SzgMT6X961A (t=45:42)

### SCH-13 Multi-resource reservations
- Sub-features: select several venue columns (multi-schedule icons) and create one reservation spanning them; marketed allocation of multiple venues to one event and pairing equipment/officials/coaches with a booking; trainer + venue pairing on one reservation (documented in the resources cluster); in NSE several venues can still be ticked at once in the venue drop-down of the booking form
- Settings / options: resource multi-select at creation; per-rate multi-resource quantity/billing modes (RNT-02).
- Rules / limits: adding another resource to an existing rental series requires a separate "Add More" pass per resource (RNT-04).
- User story: As a scheduler, I want one booking to hold a court plus the adjoining room, so that an event blocks everything it needs.
- Actors: staff
- UI generation: both
- Priority: P0
- Evidence: https://support.ezfacility.com/hc/en-us/articles/4404308503195-How-to-Schedule-a-Rental-Reservation-in-EZFacility-Classic, https://support.ezfacility.com/hc/en-us/articles/4407310264475-How-to-Add-Additional-Rentals-to-an-Existing-Rental-in-EZFacility-Classic, https://www.ezfacility.com/features/scheduling-operations, https://www.youtube.com/watch?v=SzgMT6X961A (t=44:42)

### SCH-14 Buffer times on sessions (per reservation type)
- Sub-features: configurable padding around sessions of a reservation type so back-to-back bookings leave turnaround time; introduced with NSE.
- Settings / options: buffer per reservation type (before/after split and units not documented); video detail: buffer settings live on the reservation type and a location-level default exists; the session form has a "use location default" checkbox which, when unticked, lets staff set a buffer for that session; choices run from 5 minutes to 1 hour
- Rules / limits: described as all-new in June 2026; interaction with conflict checks and with client-visible duration unknown; buffers render as dashed strips before and after the tile and are part of the conflict range (another booking, including a rental, cannot start inside a buffer); marketed uses are prep/clean-up, trainer gaps and ice resurfacing
- User story: As an operator, I want automatic turnaround gaps after sessions, so that staff can reset the space.
- Actors: admin
- UI generation: New (NSE)
- Priority: P1
- Evidence: https://www.youtube.com/watch?v=SzgMT6X961A, https://support.ezfacility.com/hc/en-us/articles/45196262785307-Add-Buffer-Times-to-Sessions (title only, body not read), https://www.youtube.com/watch?v=SzgMT6X961A (t=09:44, t=17:54), https://www.youtube.com/watch?v=SzgMT6X961A (t=24:02)

### SCH-15 Sub-venues (parent/child resources)
- Sub-features: child spaces defined under a venue (e.g. half-courts under a full court) on the new calendar; resource ordering follows subgroup order in the league resource view.
- Settings / options: parent venue -> sub venue hierarchy (depth not documented); a venue has a Sub Venues tab with a "create sub venue" action; rental types and rates can be attached per child, so a whole field can be priced separately from its quarters
- Rules / limits: introduced with NSE (June 2026); whether booking a parent blocks children and vice versa is not stated (inferred: yes). Master data belongs to the Locations & Resources cluster; listed here because it changes conflict semantics; confirmed by the NSE webinar: booking a child blocks the parent and booking the parent blocks every child; on self-service a rental type linked to the sub-venues shows only the sub-venues, while one linked to the parent shows only the whole venue; half-court hire to two parties is the stated use case
- User story: As an operator, I want to book either a whole field or one of its halves, so that I can sell divisible space without double-booking.
- Actors: admin; scheduler
- UI generation: New (NSE)
- Priority: P1
- Evidence: https://www.youtube.com/watch?v=SzgMT6X961A, https://support.ezfacility.com/hc/en-us/articles/17981009155995-August-16th-2023-Release-Notes, https://www.youtube.com/watch?v=SzgMT6X961A (t=06:41, t=21:00), https://www.youtube.com/watch?v=SzgMT6X961A (t=31:19, t=39:31, t=53:00)

### SCH-16 Direct registration link for a reservation
- Sub-features: copy a per-reservation deep link that lands the client on self-service booking for exactly that session; share to one or many clients, typically by emailing from the client profile with a saved template; works for one-to-one and group sessions and for unlisted sessions.
- Settings / options: reservation action "Copy Direct Registration URL"; email template (example name "Personal Training Invitation").
- Rules / limits: client can pay and register only if the required package is sold on self-service; link is not single-use and can be forwarded (inferred, since one link is sent to many).
- User story: As a trainer, I want to send a client a link to a specific session, so that they can pay and book without browsing the schedule.
- Actors: admin/front desk/trainer; client
- UI generation: Classic documented
- Priority: P1
- Evidence: https://support.ezfacility.com/hc/en-us/articles/30058010593563-How-to-Share-a-Direct-Registration-Link-for-a-Session-in-EZFacility-Classic, https://support.ezfacility.com/hc/en-us/articles/30058087582875-Managing-Self-Service-Shared-Bookings-in-EZFacility-Classic

### SCH-17 Shared bookings for related clients
- Sub-features: three supported patterns distinct from an ordinary multi-registrant class: (a) combined-cost booking where a capacity-1 session is paid once by a package that is auto-shared with a spouse/related person and only one session is deducted; (b) private session via unlisted type plus direct link; (c) team booking where a coach's package (free via team membership or priced for the team) auto-shares to related players who then self-book at no extra cost.
- Settings / options: package auto-share with spouse / related people (or share after sale); client Relationships; reservation capacity = 1 for combined cost; Allowed Packages on the type; BUY button on self-service; post-purchase landing on "My Schedule".
- Rules / limits: the relationship must exist before the package is sold for auto-sharing to apply; direct links also work for listed sessions; team booking differs from a rental because each player is individually booked while the coach pays; waitlisted clients on a shared package are auto-booked when a spot opens (fix 2023-09-27).
- User story: As a coach, I want my players to book team practices against a package I paid for, so that each player is on the roster without paying separately.
- Actors: admin/trainer/coach; clients (couples, team players, invitees)
- UI generation: Classic documented (two near-identical articles)
- Priority: P1
- Evidence: https://support.ezfacility.com/hc/en-us/articles/30058087582875-Managing-Self-Service-Shared-Bookings-in-EZFacility-Classic, https://support.ezfacility.com/hc/en-us/articles/4404305610651-Managing-Self-Service-Shared-Bookings-in-EZFacility-Classic, https://support.ezfacility.com/hc/en-us/articles/19132331777307-September-27th-2023-Release-Notes

### SCH-18 Trainer/coach availability scheduling
- Sub-features: trainers appear as schedulable columns alongside venues; set instructor/lesson availability; private lessons bookable on combined coach and court availability; assign studio space; recurring or single lessons; staff search for available dates, trainers and rooms.
- Settings / options: availability expressed as available sessions (SCH-07) and special blocks (SCH-08) on the trainer column; no separate working-hours template is documented in this cluster.
- Rules / limits: trainer master data, pay and commissions belong to the Staff cluster.
- User story: As a coach, I want my bookable hours published on my own column, so that clients only book when I am available.
- Actors: trainer/coach, admin, member
- UI generation: both
- Priority: P0
- Evidence: https://www.ezfacility.com/industries/personal-trainer-software, https://www.ezfacility.com/industries/tennis-club-software, https://www.ezfacility.com/blog/best-baseball-facility-management-software, https://support.ezfacility.com/hc/en-us/articles/4404311260571-How-to-Schedule-an-Available-Session-in-EZFacility-Classic, https://support.ezfacility.com/hc/en-us/articles/4404311270683-Scheduling-a-Special-Reservation-in-EZFacility-Classic

### SCH-19 Staff calendar sync (Google / Outlook)
- Sub-features: push staff schedules to personal Google or Outlook calendars; calendar sync is a Q&A topic of the NSE webinar.
- Settings / options: provider = Google | Outlook (direction, per-user opt-in, feed vs OAuth not documented).
- Rules / limits: none documented.
- User story: As an instructor, I want my sessions on my phone calendar, so that I do not miss them.
- Actors: trainer, instructor, staff
- UI generation: both (assumed)
- Priority: P1
- Evidence: https://www.ezfacility.com/features/staff-access-management, https://www.ezfacility.com/industries/gym-management-software, https://www.youtube.com/watch?v=SzgMT6X961A

### SCH-20 Embedded public schedule / schedule data for external sites
- Sub-features: class schedule embedded in the tenant's own website; API-fed custom calendars showing open seats and lane reservations; Google Analytics cross-domain tracking between marketing site and booking pages.
- Settings / options: none documented.
- Rules / limits: a customer asked for stable class IDs in the API (enhancement request, 2020).
- User story: As a marketer, I want the live class timetable on our website, so that visitors can see openings and click through to book.
- Actors: admin; public visitor
- UI generation: n-a
- Priority: P1
- Evidence: https://www.ezfacility.com/blog/grow-your-business-with-the-right-software-solution, https://www.ezfacility.com/blog/client-highlight-c2tactical-utilizes-ezfacility-digital-api, https://www.ezfacility.com/blog/software-release-vaccine-passport

### SCH-21 Merge two reservations into one linked series
- Sub-features: from inside one reservation, staff key in the number of another reservation and merge; the two series (e.g. a baseball rental and a softball rental for the same customer) then show together under Linked Reservations and can be mass-edited, deleted and billed as one set.
- Settings / options: Merge action on a reservation; input = the other reservation's number.
- Rules / limits: demo merged two recurring rentals into a 10-occurrence linked list; whether merge is reversible, restricted to the same client or kind, or changes invoices is not stated.
- User story: As a front-desk agent, I want to join two separately created bookings into one series, so that I manage and bill a customer's whole block together.
- Actors: front desk/admin
- UI generation: New (pre-NSE calendar demo; NSE not confirmed)
- Priority: P2
- Evidence: https://www.youtube.com/watch?v=7JVYZ3kxUAo (t=24:49)

## Rentals

### RNT-01 Rental types
- Sub-features: per-location master list of facility-rental kinds, separate from reservation types and from equipment; each carries a default revenue category and colour; reorder/edit/delete; rental type appears as a column in the revenue report; zero-price rental types.
- Settings / options: Rental Type (name); Revenue Category (default); Color; sort order; price/value may be 0; Access (NSE) = admin-only (never on self-service) | self-book (also offered on self-service)
- Rules / limits: revenue category is bound to the type, so types should be modelled around reporting granularity; $0 rental types allowed since 2023-06-12 (staff can sell at no charge, clients can self-book, history retained), intended for membership-included rentals; menu path Classic: Administration > Rental Types, New: Administration > Location Settings > Rental Types.
- User story: As an admin, I want rental categories such as "Court hire" and "Party room" with their own revenue mapping, so that rental income reports cleanly.
- Actors: owner/admin
- UI generation: both
- Priority: P0
- Evidence: https://support.ezfacility.com/hc/en-us/articles/29852788198427-How-to-Set-Up-Rental-Types-in-EZFacility-Classic, https://support.ezfacility.com/hc/en-us/articles/16308423683355-June-12th-2023-Release-Notes, https://support.ezfacility.com/hc/en-us/articles/17574439837467-August-2nd-2023-Release-Notes, https://support.ezfacility.com/hc/en-us/articles/22938731158811-How-to-set-up-Rentals-For-Self-Service, https://support.ezfacility.com/hc/en-us/articles/45196187362203-How-to-Create-a-New-Rental-Type (title only, body not read), https://www.youtube.com/watch?v=SzgMT6X961A (t=08:43)

### RNT-02 Rental rates (rate templates per rental type)
- Sub-features: multiple named rates per rental type (e.g. seasonal); three calculation bases; rule for how quantity is counted when several resources are booked; rule for how many billing lines are produced; label reused as the invoice line description; NSE adds peak / off-peak (time-of-day) rate options; tax rates applied to rentals.
- Settings / options: Label; Rate (amount); calculation = Per Hour (total hours x rate) | Per Occurrence (occurrences x rate) | Custom (single flat amount); multi-resource quantity = "Calculate quantity once only" | "Calculate quantity separately for each"; billing-item creation = Combined | Per Resource | Per Occurrence | Separate (one per resource x occurrence); peak / off-peak tiers (NSE, structure not documented); taxes selectable at rental creation; NSE rate holds member price and non-member price side by side (previously two separate rates) plus an internal-only description never shown to clients; NSE rate rules, each scoped by any of time-of-day range (peak/off-peak) | date range (season, holiday) | days of week | membership type; a rule is created either as a "rate" (replaces the price) or as a "discount" (price unchanged, shown as an explicit discount line)
- Rules / limits: at booking time staff may pick a predefined rate or key a custom rate; with no predefined rate the default is a single combined billing item; taxes unticked at rental creation must stay off the invoice (fix 2023-09-13); which invoice options staff see at booking (multiple invoices one per occurrence | single invoice | date-based periodic invoices such as weekly or monthly for long lets) depends on how the admin configured the rate's billing items (per resource vs per occurrence); before NSE (c. 2025) there was a single "members only" rate with no tiering by membership level; the suggested workaround was one coupon code per tier, with nothing to stop codes being shared (superseded by NSE membership-type rules)
- User story: As an admin, I want hourly, per-booking and flat rates per rental type, so that staff price rentals consistently without a calculator.
- Actors: owner/admin; front desk (apply)
- UI generation: both
- Priority: P0
- Evidence: https://support.ezfacility.com/hc/en-us/articles/29859659205787-How-to-Set-Up-Rental-Rates-in-EZFacility-Classic, https://support.ezfacility.com/hc/en-us/articles/4407310264475-How-to-Add-Additional-Rentals-to-an-Existing-Rental-in-EZFacility-Classic, https://support.ezfacility.com/hc/en-us/articles/18741009680795-September-13th-2023-Release-Notes, https://www.ezfacility.com/blog/features-and-fixes-online-rentals, https://www.youtube.com/watch?v=SzgMT6X961A, https://support.ezfacility.com/hc/en-us/articles/45196203926555-How-to-Create-a-New-Rental-Rate (title only, body not read), https://www.youtube.com/watch?v=SzgMT6X961A (t=10:45), https://www.youtube.com/watch?v=SzgMT6X961A (t=15:00), https://www.youtube.com/watch?v=7JVYZ3kxUAo (t=22:46), https://www.youtube.com/watch?v=7JVYZ3kxUAo (t=46:23)

### RNT-03 Staff-booked rental reservation (single or recurring, one or many resources)
- Sub-features: create a rental from the calendar on one or several venues; recurrence with repeatable "add occurrences"; attach an existing or newly created client; price by predefined or custom rate; charge now or mark no-charge and bill later; invoice immediately or park in the client's cart to combine with other items; take payment, print/email invoice; optionally publish on the public league site; NSE "add a rental in Resource view" flow; a second client can be added to an existing rental, either charged or at no charge
- Settings / options: Reservation kind = Rental; Title; Start/End; Show On EZLeagues (checkbox, only with the leagues module); Pattern = Daily | Weekly | Bi-Weekly | Monthly | Yearly; extra weekdays; range = total days | end date; client; rate = predefined | custom; charge = Add to Cart | No Charge; invoicing = Single Invoice now | Invoice Later; NSE: after the client is picked and before the payment screen, invoice option = recurring pattern of multiple invoices | single invoice | add to an open invoice | date-based invoice; cart step "More options": Revenue date (defaults to today; set it to the rental date so the first payment falls due then), coupon code, discount
- Rules / limits: client name is appended to the calendar title after save; rental tiles use a fixed rental colour; billing is a step after the occurrences exist (reservation and charge are decoupled); class size does not apply to rentals; autopay on/off chosen at payment must be reflected on the rental invoice (fix 2023-10-25); rentals have no attendance tracking, and there is no built-in split of one rental charge between co-renters (workaround: bill each client their share separately); unlike sessions the end time is not pre-filled from a default length, staff must pick it; a rental cannot be saved without a client; a waiver/document cannot be attached to a rental type or rate; for bookings that need waivers (e.g. birthday parties) the vendor points to a Group with online registration instead
- User story: As a front-desk agent, I want to book a team's weekly field slot for a season and invoice it in one flow, so that the space is held and the customer is billed correctly.
- Actors: front desk/admin; renter (client)
- UI generation: both (Classic documented in detail; New via webinar and title-only)
- Priority: P0
- Evidence: https://support.ezfacility.com/hc/en-us/articles/4404308503195-How-to-Schedule-a-Rental-Reservation-in-EZFacility-Classic, https://www.youtube.com/watch?v=7JVYZ3kxUAo, https://support.ezfacility.com/hc/en-us/articles/19847009538203-October-25th-2023-Release-Notes, https://www.ezfacility.com/features/scheduling-operations, https://support.ezfacility.com/hc/en-us/articles/45196255348123-How-to-Add-a-Rental-to-Your-Calendar-in-Resource-View (title only, body not read), https://www.youtube.com/watch?v=SzgMT6X961A (t=21:00), https://www.youtube.com/watch?v=SzgMT6X961A (t=22:00), https://www.youtube.com/watch?v=SzgMT6X961A (t=22:00, t=34:24), https://www.youtube.com/watch?v=7JVYZ3kxUAo (t=06:20), https://www.youtube.com/watch?v=7JVYZ3kxUAo (t=17:35), https://www.youtube.com/watch?v=Rjy8ZpfIA68 (t=37:58), https://www.youtube.com/watch?v=SzgMT6X961A (t=25:03)

### RNT-04 Extend an existing rental and bill selected occurrences
- Sub-features: "Add More" on a linked rental to append dates and (by repeating) other resources; conflict-coloured preview; select unbilled occurrences and "Bill Selected" to an existing client; choose rate and number of billing items; route the charges to new invoice(s), an existing open invoice, or the cart.
- Settings / options: Actions > Add More; pattern and range as RNT-03; Modify Checked / Delete Checked; Bill Selected; rate = predefined | custom; "Bill how many items?" = Just one (combined) | One for each occurrence; invoice routing = Multiple New Invoices (one per line item) | Single New Invoice | Date-based Invoices | Choose an Open Invoice | Invoice Later (leave in cart); invoice actions print / email / take payment.
- Rules / limits: each additional resource needs its own Add More pass; default is one combined item when no predefined rate; occurrences carry a billed/unbilled state (inferred from Bill Selected).
- User story: As a front-desk agent, I want to add extra dates to a customer's rental and put them on their open invoice, so that they receive one bill.
- Actors: front desk/admin
- UI generation: Classic documented
- Priority: P1
- Evidence: https://support.ezfacility.com/hc/en-us/articles/4407310264475-How-to-Add-Additional-Rentals-to-an-Existing-Rental-in-EZFacility-Classic

### RNT-05 Online rental policy per rental type (self-service setup)
- Sub-features: per-rental-type switch and constraints for client self-booking; restrict to specific venues; bind the rate used online; lead-time and length limits; eligibility requirement; paid-in-full versus pay-later choice; $0 online rentals; acknowledgement of terms.
- Settings / options: Available for Self-Booking; Allowed Venues; Rental Rate; Rental Cutoff Times (minimum lead time before start); minimum rent length; maximum rent length; Default Requirements = active, paid-to-date membership; payment option paid-in-full | pay-later (2016 blog); revenue category and tax rates (2016 blog); rental type carries a "rental plans" multi-select (left empty = any plan may be bought/used for this rental type) and client eligibility = all clients | members only; a rental rate remains mandatory for one-off online rentals
- Rules / limits: rental type and rate must exist first; self-service start and end times snap to the hour (since 2023-06-28); venues blocked "Unavailable" are excluded from results; marketing additionally claims deposits and capacity management for online rentals (no help-centre detail); NSE: default, minimum and maximum length sit on the rental type (demo 1 h to 8 h); fixed start/end times cannot be imposed the way they can with sessions; min = max = 1 h restricts clients to one-hour blocks; facility opening hours still bound the bookable times; when rentals are modelled as package sessions instead (pre-rental-plan workaround) nothing stops a client from buying several sessions and booking consecutive hours; only manual monitoring
- User story: As an admin, I want to decide which spaces members can rent online, at what rate, how far ahead and for how long, so that online rentals follow house rules.
- Actors: admin
- UI generation: both (New article; Classic webinar; newer article title-only)
- Priority: P0
- Evidence: https://support.ezfacility.com/hc/en-us/articles/22938731158811-How-to-set-up-Rentals-For-Self-Service, https://support.ezfacility.com/hc/en-us/articles/4404312822811-Online-Webinar-How-to-Set-Up-Online-Rentals-in-EZFacility-Classic, https://support.ezfacility.com/hc/en-us/articles/16731304236571-June-28th-2023-Release-Notes, https://support.ezfacility.com/hc/en-us/articles/16308423683355-June-12th-2023-Release-Notes, https://support.ezfacility.com/hc/en-us/articles/4404311270683-Scheduling-a-Special-Reservation-in-EZFacility-Classic, https://www.ezfacility.com/blog/features-and-fixes-online-rentals, https://www.ezfacility.com/features/scheduling-operations, https://support.ezfacility.com/hc/en-us/articles/57005260684315-How-to-set-up-Rentals-For-Self-Service (title only, body not read), https://www.youtube.com/watch?v=SzgMT6X961A (t=37:27, t=46:43), https://www.youtube.com/watch?v=Rjy8ZpfIA68 (t=35:54), https://www.youtube.com/watch?v=ERaBaf5YWHo (t=19:25)

### RNT-06 Client online rental search and booking
- Sub-features: client searches availability by rental type, length, venue and days of week; only conflict-free slots are offered; books and pays (or pays later per policy); confirmation email with invoice copy; resources listed in natural ascending order; member and non-member (public) renters; single or recurring.
- Settings / options: search filters = type | length | venue | days of week; times on the hour only.
- Rules / limits: double-booking prevented at confirmation; behaves like session self-booking; natural sort for resource names containing numbers (fix 2023-07-03); self-service recognises a logged-in member and offers the member rate first while other rates remain selectable; booking several courts in one online transaction is not possible (staff multi-venue booking is)
- User story: As a member, I want to find a free cage for an hour on Saturday and pay online, so that I do not need to phone the desk.
- Actors: client/renter (member or public)
- UI generation: both
- Priority: P0
- Evidence: https://www.ezfacility.com/blog/features-and-fixes-online-rentals, https://support.ezfacility.com/hc/en-us/articles/16731304236571-June-28th-2023-Release-Notes, https://support.ezfacility.com/hc/en-us/articles/16846068050715-July-3rd-2023-Release-Notes, https://www.ezfacility.com, https://www.ezfacility.com/self-service-portal, https://www.youtube.com/watch?v=SzgMT6X961A (t=34:24)

### RNT-07 Buffer times on rentals
- Sub-features: padding added around rental bookings (turnover/cleaning) on the new calendar.
- Settings / options: buffer per rental type (inferred; before/after and units not documented); video detail: buffer set per rental type with the same 5 minutes to 1 hour choices as sessions; the staff rental form shows pre- and post-buffer fields
- Rules / limits: introduced June 2026; whether buffers are billed or shown to the renter is unknown; a buffer can be added to rentals that already exist, including ones open to online booking, by editing them (no delete and rebook)
- User story: As an operator, I want an automatic gap between rentals, so that one party can clear out before the next arrives.
- Actors: admin
- UI generation: New (NSE)
- Priority: P1
- Evidence: https://www.youtube.com/watch?v=SzgMT6X961A, https://support.ezfacility.com/hc/en-us/articles/45196231520155-Add-Buffer-Times-to-Rentals (title only, body not read), https://www.youtube.com/watch?v=SzgMT6X961A (t=13:00), https://www.youtube.com/watch?v=SzgMT6X961A (t=33:22)

### RNT-08 Remove a rental or a recurring rental from the schedule
- Sub-features: remove a single rental; remove a recurring rental series (new-calendar articles); Classic uses delete mode scopes (SCH-11).
- Settings / options: not documented (title only).
- Rules / limits: effect on invoices, payments and rental-plan balance not documented, except that cancelling a plan-funded booking returns the balance (RNT-09); video: removing a rental that was already paid leaves the money on the client as account credit usable on any later purchase, or a manager refunds it; the default staff role has no card-refund permission; removing one occurrence does not rebalance an invoice payment schedule
- User story: As a front-desk agent, I want to cancel a customer's rental or the rest of their series, so that the space frees up.
- Actors: front desk/admin
- UI generation: New (title only); Classic via SCH-11
- Priority: P0
- Evidence: https://support.ezfacility.com/hc/en-us/articles/52057261926939-How-to-Remove-a-Rental-from-the-Schedule (title only, body not read), https://support.ezfacility.com/hc/en-us/articles/52057689019803-How-to-Remove-a-Recurring-Rental-from-the-Schedule (title only, body not read), https://support.ezfacility.com/hc/en-us/articles/4404311287451-Deleting-Reservations-using-Delete-Mode-in-EZFacility-Classic, https://www.youtube.com/watch?v=7JVYZ3kxUAo (t=27:52, t=19:38)

### RNT-09 Rental plans (prepaid rental balance)
- Sub-features: sell prepaid rental time before any booking exists; built on existing rental types; two balance models; member vs non-member price; validity window; rolling auto-renew; sold from the admin plan list, a client-profile tab, or at checkout while booking a rental; consumed when booking (staff or client); automatic balance return on cancellation; balance visible to staff and client; self-service browse/buy/apply; optional terms acknowledgement; plan list actions: pencil edit (settings then pricing), archive (reversible) and trash (permanent); client profile has a "Rental plans" tab with New rental plan; a manager may alter plan details or price for that single sale before the payment screen; a new client can be created inline; in the rental booking dialog the payment step lets staff filter by rental plan, choose a one-time rental rate instead, or sell a new plan when the client has none; the reservation's billing then reads as covered by the plan and paid in full, and remaining hours show on the client; staff can click the used-hours figure to list the bookings behind it; self-service: payment drop-down offers plan or rental rate; the confirmation shows hours used and left; clients may chain back-to-back bookings until the plan is empty; a "Rental plans" page under the profile shows used and remaining hours; a client can buy a plan for themselves or put one in the cart on behalf of a spouse
- Settings / options: plan name; linked rental type(s); model = Per Hour (balance in hours, any mix of lengths) | Per Occurrence (balance in bookings regardless of length); quantity; member price; non-member price; start date; expiration date; auto-renew (rolling); self-service enable flag "Rental Plans" under Self-Service Preferences; terms acknowledgement = first purchase | every purchase (Self-Service > Design); plan form, screen 1 (video): name; rental type (required); internal-only description; selling status (on = purchasable on self-service, off = staff sale only); members-only checkbox; start date with "default to sale date" checkbox (otherwise a future start); expiration date; auto renew (until cancelled); sharing across relationships; plan form, screen 2 pricing (video): quantity as a number or an Unlimited checkbox; Flat rate checkbox (ticked = price is for the whole plan, unticked = price x quantity, e.g. 50 x 10 = 500); discount section; revenue category; default invoice option (defaults to single invoice); auto pay (relevant when the plan has a payment schedule, mostly with auto renew); additional client-visible description for notes/terms
- Rules / limits: live 2026-10-15; positioned as replacing the workaround of using package plans for rentals; cancelled booking credits hours/occurrences back automatically; the Administration plan list with its direct Sell button is manager-only; other staff sell from the client profile or from the schedule; a recurring rental is checked against the remaining balance as a whole: if the plan cannot cover every occurrence staff must sell another plan that covers all the hours or charge the rental rate instead (no part-plan, part-rate mix shown); expiry applies regardless of unused balance; with Per Occurrence a long booking costs the same one unit as a short one; limits stated in Q&A (2026-10): no per-week usage cap; a plan may auto-renew weekly but does not recur the way a package plan does; plans are standalone and cannot be attached to a membership as an add-on; before rental plans (c. 2025) the only way to bundle a fixed amount of rental time into a membership was pre-placed sessions on the calendar plus a package ("rentals as packages"), which also suits rentals limited to fixed windows
- User story: As an operator, I want to sell a 10-hour court pack that customers draw down as they book, so that I collect revenue up front and regulars book faster.
- Actors: admin (create/sell), front desk (sell/apply), client (buy/apply)
- UI generation: New
- Priority: P1
- Evidence: https://www.ezfacility.com/blog/introducing-rental-plans-prepaid-rentals-made-simple, https://www.youtube.com/watch?v=hHJ38JvtabY, https://www.youtube.com/watch?v=ERaBaf5YWHo, https://www.ezfacility.com/features/scheduling-operations, https://support.ezfacility.com/hc/en-us/articles/57003799901851-How-to-Create-a-New-Rental-Plan (title only, body not read), https://support.ezfacility.com/hc/en-us/articles/57248399589659-Rental-Plans-Release-Notes-October-15-2026 (title only, body not read), https://www.youtube.com/watch?v=ERaBaf5YWHo (t=06:09), https://www.youtube.com/watch?v=ERaBaf5YWHo (t=09:11), https://www.youtube.com/watch?v=ERaBaf5YWHo (t=11:12), https://www.youtube.com/watch?v=ERaBaf5YWHo (t=12:13), https://www.youtube.com/watch?v=ERaBaf5YWHo (t=13:13), https://www.youtube.com/watch?v=ERaBaf5YWHo (t=16:20, t=25:34), https://www.youtube.com/watch?v=ERaBaf5YWHo (t=17:20, t=04:06), https://www.youtube.com/watch?v=ERaBaf5YWHo (t=21:27), https://www.youtube.com/watch?v=ERaBaf5YWHo (t=23:29), https://www.youtube.com/watch?v=7JVYZ3kxUAo (t=01:09)

### RNT-10 Share a rental plan
- Sub-features: share a purchased rental plan with another client (by analogy with shared packages, inferred); confirmed by video: a sold plan is shared with related clients (siblings, parents, spouse) from the owner's Rental plans tab, and the plan definition has a "sharing across relationships" setting
- Settings / options: not documented.
- Rules / limits: unknown (who may consume, whether relationship is required).
- User story: As a parent, I want my family to draw on one prepaid rental plan, so that we do not buy separate plans.
- Actors: front desk/admin; clients
- UI generation: New
- Priority: P1
- Evidence: https://support.ezfacility.com/hc/en-us/articles/57004869280027-How-to-Share-a-Rental-Plan (title only, body not read), https://www.youtube.com/watch?v=ERaBaf5YWHo (t=14:14, t=06:09)

### RNT-11 Remove and refund a rental plan
- Sub-features: remove a sold plan from a client and refund it.
- Settings / options: not documented; video: trash on a sold plan offers three choices: reverse billing and remove the plan | delete the plan but keep the billing | go to the invoice
- Rules / limits: proration of consumed balance unknown; reversing the billing cannot be undone
- User story: As a manager, I want to cancel a customer's rental plan and refund the unused part, so that disputes are settled cleanly.
- Actors: admin/manager
- UI generation: New
- Priority: P1
- Evidence: https://support.ezfacility.com/hc/en-us/articles/57004883480731-How-to-Remove-and-Refund-a-Rental-Plan (title only, body not read), https://www.youtube.com/watch?v=ERaBaf5YWHo (t=14:14)

### RNT-12 Rental Plan Sales report
- Sub-features: financial report over a date range listing plan name, sale price, outstanding balance and sales channel.
- Settings / options: date range; columns plan name | sale price | outstanding balance | sold by (staff vs self-service); path Reports > Financial > Rental Plan Sales.
- Rules / limits: none documented.
- User story: As an owner, I want to see prepaid rental sales and the unredeemed balance, so that I know my liability.
- Actors: owner/admin
- UI generation: New
- Priority: P1
- Evidence: https://www.ezfacility.com/blog/introducing-rental-plans-prepaid-rentals-made-simple, https://support.ezfacility.com/hc/en-us/articles/57004872733211-How-to-Run-the-Rental-Plan-Sales-Report (title only, body not read)

### RNT-13 Publish a rental on the public league site
- Sub-features: per-rental flag that shows the booking on the public league/schedule website.
- Settings / options: Show On EZLeagues (checkbox).
- Rules / limits: only available when the leagues module is purchased.
- User story: As a league admin, I want hired-out field time visible on the public schedule, so that visitors see when fields are in use.
- Actors: front desk/admin; public visitor
- UI generation: Classic documented
- Priority: P2
- Evidence: https://support.ezfacility.com/hc/en-us/articles/4404308503195-How-to-Schedule-a-Rental-Reservation-in-EZFacility-Classic

### RNT-14 Rental equipment catalogue
- Sub-features: equipment categories; equipment items with rental fee, loan period, due time and informational late/replacement fees; soft delete with show-deleted toggle; reorder; items surface on a dedicated Equipment panel in POS with their own search.
- Settings / options: category name; Equipment Name; Equipment ID (unique); Description; Rental Fee (pre-tax); Rental Days (allowed loan length); Late Fee; Return Time (time of day due back); Replace Fee; Tax Code(s) (newer article) or Tax % (older article); Show Deleted Categories toggle; sort order.
- Rules / limits: Equipment ID must be unique; Late Fee and Replace Fee are record-only and not auto-charged (article wording is internally inconsistent); deleting is soft; rink marketing says late fees/replacement costs are tracked via inventory reports.
- User story: As an admin, I want a catalogue of rentable gear with fees and due rules, so that the desk can hire it out and track what is outstanding.
- Actors: owner/admin; cashier (view)
- UI generation: Classic
- Priority: P0
- Evidence: https://support.ezfacility.com/hc/en-us/articles/34418766995099-How-to-Set-Up-Equipment-in-EZFacility-Classic, https://support.ezfacility.com/hc/en-us/articles/34418934806171-How-to-Set-Up-Rental-Equipment-in-EZFacility-Classic, https://www.ezfacility.com/industries/rink-management-software

### RNT-15 Rent equipment to a client through POS
- Sub-features: choose register (per location); switch POS panel from Products to Equipment; search equipment; attach or create a client; add items to the cart; adjust quantity and price; complete the sale; marketed real-time available / checked-out status.
- Settings / options: register selection; client search (minimum 3 leading characters); cart quantity; price override.
- Rules / limits: a client must be attached to any sale containing equipment; a client created mid-sale persists in the client database; each add starts at quantity 1.
- User story: As a cashier, I want to hire out skates against a customer record at the till, so that we know who has what.
- Actors: cashier/front desk
- UI generation: Classic
- Priority: P0
- Evidence: https://support.ezfacility.com/hc/en-us/articles/34418782382235-How-to-Rent-Equipment-in-EZFacility-Classic, https://www.ezfacility.com/features/scheduling-operations

### RNT-16 Return rented equipment
- Sub-features: return from the client profile's checked-out-items list or from the Equipment tab; search by client or equipment; item becomes available again in POS.
- Settings / options: Return action (two entry points).
- Rules / limits: returns are done in the main app, not in POS; no automatic late-fee assessment is documented.
- User story: As a front-desk agent, I want to check gear back in from the customer's profile, so that stock availability is correct.
- Actors: front desk/admin
- UI generation: Classic
- Priority: P0
- Evidence: https://support.ezfacility.com/hc/en-us/articles/34418804557467-How-to-Return-Equipment-Rentals-in-EZFacility-Classic

### RNT-17 Locker rental to a client
- Sub-features: find a locker in a locker room; assign to an existing or new client for a contract term; price by predefined fee or manual amount, or no charge; invoice now or leave in cart to combine with other purchases.
- Settings / options: Contract Term = Day | Week | Year | custom Locker Terms; Fee = predefined | manual; charge = Add to Cart | No Charge; invoicing = Invoice Now (single invoice) | Invoice Later.
- Rules / limits: locker rooms, lockers and locker terms are master data owned by the platform/resources cluster; expiry derives from term (inferred).
- User story: As a front-desk agent, I want to assign a locker for a year and bill it with the membership, so that the member gets one invoice.
- Actors: front desk/admin
- UI generation: Classic
- Priority: P1
- Evidence: https://support.ezfacility.com/hc/en-us/articles/4405044656411-How-to-Rent-a-Locker-in-EZFacility-Classic, https://www.ezfacility.com/industries/rink-management-software

### RNT-18 Clear locker assignments
- Sub-features: clear one locker's assignment; bulk "Clear Expired" for all lapsed assignments.
- Settings / options: Clear (per locker); Clear Expired (bulk).
- Rules / limits: none documented (no auto-release job is described).
- User story: As a front-desk agent, I want to release all expired lockers at once, so that they can be re-let.
- Actors: front desk/admin
- UI generation: Classic
- Priority: P1
- Evidence: https://support.ezfacility.com/hc/en-us/articles/4405044668699-How-to-Clear-an-Expired-Locker-in-EZFacility-Classic

## Classes/Clinics/Camps

### CLS-01 Register a client into a single session
- Sub-features: open a session from the calendar; search or create the client; choose which of the client's packages pays for the booking; speed-register shortcut; success confirmation leading to the roster; also reachable straight after creating a session ("save and add clients").
- Settings / options: Register Client; Create New Client; Enable Speed Register (auto-selects the package after the client is picked); package option "This Package" (book only the clicked session); Finish.
- Rules / limits: speed register only fires when the client holds exactly one eligible package; a client without a suitable package must be sold one first (or the session must allow free booking, CLS-05); disabled clients are excluded from the register search (fix 2024-01-17); class size 0 on the type with a positive size on the session must still allow booking (fix 2024-04-10); a waiver cannot be required per session or per rental (asked for in the NSE webinar; not available as of 2026-06)
- User story: As a front-desk agent, I want to drop a client into a class against their package in a couple of clicks, so that walk-ups are handled fast.
- Actors: front desk/admin/trainer
- UI generation: New (Classic equivalent via "Save and Add Clients")
- Priority: P0
- Evidence: https://support.ezfacility.com/hc/en-us/articles/4402427209115-Registering-A-Client-Into-a-Single-Available-Session, https://support.ezfacility.com/hc/en-us/articles/4404311260571-How-to-Schedule-an-Available-Session-in-EZFacility-Classic, https://support.ezfacility.com/hc/en-us/articles/22122496577179-January-17th-2024-Release-Notes, https://support.ezfacility.com/hc/en-us/articles/24695840840603-April-10th-2024-Release-Notes, https://www.youtube.com/watch?v=Rjy8ZpfIA68, https://www.youtube.com/watch?v=SzgMT6X961A (t=25:03)

### CLS-02 Register a client into multiple linked sessions (multi-enrolment)
- Sub-features: from one occurrence of a series, book the client into all remaining linked sessions or a hand-picked subset in one action, drawing on one package.
- Settings / options: "Book Using" = All Sessions (n) (every linked occurrence, subject to availability) | Custom (choose occurrences) | This Package (single).
- Rules / limits: occurrences that are full are skipped under "All Sessions" (wording "subject to availability"); package must be of an allowed type and (inferred) have enough remaining sessions.
- User story: As a front-desk agent, I want to enrol a child in every Tuesday class of the term at once, so that I do not repeat the booking twelve times.
- Actors: front desk/admin
- UI generation: New
- Priority: P0
- Evidence: https://support.ezfacility.com/hc/en-us/articles/27849876503323-Registering-A-Client-Into-Multiple-Available-Sessions, https://support.ezfacility.com/hc/en-us/articles/24695840840603-April-10th-2024-Release-Notes

### CLS-03 Session roster, attendance and participant actions
- Sub-features: per-session roster ("Reservation Details"); mark attendance; filter roster by name; view participant info (DOB, phones); view the package used, its invoice and balance, and take payment; remove a participant; see each participant's next booked session; email all or selected participants; client-profile schedule tab with "List and Edit All Sessions"; attendance marking from the new calendar; marking an attendee as early-cancelled prompts staff to pick an alternative date, searches open sessions and rebooks the client, or simply returns the session to the package
- Settings / options: attendance states seen across sources: scheduled | reserved | attended | waitlisted (full enumeration incl. no-show/cancelled not documented); Email All Clients | Email Checked Clients; attendance state "early cancelled" seen in the New UI demo
- Rules / limits: removing a participant's effect on the package balance is not stated here (press notes mention used-session refunds on cancel); emailing participants works across locations (fix 2024-04-10).
- User story: As an instructor, I want a roster where I tick attendance and message the class, so that usage and no-shows are recorded and people are informed.
- Actors: front desk/admin/trainer
- UI generation: both
- Priority: P0
- Evidence: https://support.ezfacility.com/hc/en-us/articles/4402427209115-Registering-A-Client-Into-a-Single-Available-Session, https://support.ezfacility.com/hc/en-us/articles/27849876503323-Registering-A-Client-Into-Multiple-Available-Sessions, https://support.ezfacility.com/hc/en-us/articles/11297336305691-December-15th-2022-Release-Notes, https://support.ezfacility.com/hc/en-us/articles/14655161654811-April-18th-2023-Release-Notes, https://support.ezfacility.com/hc/en-us/articles/24695840840603-April-10th-2024-Release-Notes, https://support.ezfacility.com/hc/en-us/articles/34155834657819-July-3rd-2024-Release-Notes, https://www.youtube.com/watch?v=Rjy8ZpfIA68, https://support.ezfacility.com/hc/en-us/articles/45211147546267-How-to-Mark-Attendance-on-a-Session-in-Resource-View (title only, body not read), https://www.youtube.com/watch?v=TWNQ4cTiEFs (t=42:16)

### CLS-04 Class capacity and bulk capacity change
- Sub-features: default capacity on the reservation type; per-occurrence capacity override; bulk change of capacity on selected future occurrences of a series via the linked-reservations editor with preview.
- Settings / options: Class Size (type default); Class Size (per reservation; per slot when split); date-range filter; select all; Preview Changes; Finish.
- Rules / limits: editing the type default does not touch already scheduled occurrences; occurrence value overrides type value (including type = 0); capacity is not applicable to rentals.
- User story: As an admin, I want to cut the capacity of all remaining classes in a term, so that we can respond to distancing or staffing limits.
- Actors: admin
- UI generation: Classic documented (model shared)
- Priority: P0
- Evidence: https://support.ezfacility.com/hc/en-us/articles/4404311324443-How-to-Edit-Class-Sizes-in-EZFacility-Classic, https://support.ezfacility.com/hc/en-us/articles/24695840840603-April-10th-2024-Release-Notes, https://support.ezfacility.com/hc/en-us/articles/34440874732443-How-to-Set-Up-Reservation-Types-in-EZFacility-Classic

### CLS-05 Free booking (register without a package)
- Sub-features: allow registration into a session without consuming a package; default at type level, override per session.
- Settings / options: Default Allow Free Booking(s) (type); Allow Free Bookings (per session).
- Rules / limits: when off, a package of an allowed type is mandatory.
- User story: As an admin, I want open-gym sessions that anyone can join without a pass, so that free programmes still have rosters.
- Actors: admin; client
- UI generation: both
- Priority: P0
- Evidence: https://support.ezfacility.com/hc/en-us/articles/29783959046555-How-to-Set-Up-Reservation-Types-in-EZFacility-Classic, https://support.ezfacility.com/hc/en-us/articles/34440874732443-How-to-Set-Up-Reservation-Types-in-EZFacility-Classic, https://support.ezfacility.com/hc/en-us/articles/4402427203355-How-to-Set-Up-Reservation-Types

### CLS-06 Session waitlist with auto-promotion
- Sub-features: clients can be waitlisted on a full session; promotion to a booking when a spot opens (confirmed for shared packages); client-profile package tab shows Reserved and Waitlist counts with drill-down to an attendance-update list; waitlisted clients are excluded from virtual-meeting link distribution.
- Settings / options: booking state waitlisted; Package tab views Reserved | Waitlist; member-app waitlist mode (configured in the app) = automatic priority queue (next person in line is moved into the freed spot) | open waitlist (everyone waiting is emailed and the first to click the link gets the spot); vendor recommends the automatic queue
- Rules / limits: auto-booking on vacancy (fix 2023-09-27); ordering, notification, cut-off and whether a package session is held while waitlisted are not documented in this cluster (Group waitlists are a separate mechanism in the registration cluster).
- User story: As a member, I want to join a waitlist and be booked automatically if someone drops out, so that I do not have to keep checking.
- Actors: client; front desk
- UI generation: both
- Priority: P0
- Evidence: https://support.ezfacility.com/hc/en-us/articles/19132331777307-September-27th-2023-Release-Notes, https://support.ezfacility.com/hc/en-us/articles/16308423683355-June-12th-2023-Release-Notes, https://support.ezfacility.com/hc/en-us/articles/17574439837467-August-2nd-2023-Release-Notes, https://support.ezfacility.com/hc/en-us/articles/34155834657819-July-3rd-2024-Release-Notes, https://www.ezfacility.com/industries/personal-trainer-software, https://www.youtube.com/watch?v=oNHKhlv39qo (t=55:17, t=56:17)

### CLS-07 Public class/clinic listing on the league website
- Sub-features: add, edit, delete class/clinic cards on the public league site; optional outbound registration link pasted from a Group's registration page.
- Settings / options: Title; Sport; Start Date; Description (all four required); registration link (optional).
- Rules / limits: listing only; enrolment, capacity and payment live in the linked Group; two near-duplicate articles (2021 and later).
- User story: As a league admin, I want to advertise clinics on our public site with a sign-up link, so that visitors can find and register for them.
- Actors: league-site admin; public visitor
- UI generation: n-a (league site admin)
- Priority: P2
- Evidence: https://support.ezfacility.com/hc/en-us/articles/10414727616795-How-to-Manage-your-Classes-Clinics-in-EZLeagues, https://support.ezfacility.com/hc/en-us/articles/4405044308251-How-to-Manage-your-Classes-Clinics

### CLS-08 Virtual sessions (Zoom link on a session)
- Sub-features: run paid or free one-to-one or group sessions online; join link distributed to booked participants from the portal; works with a basic Zoom account; integration reworked for compliance in March 2023.
- Settings / options: none documented in this cluster.
- Rules / limits: link is sent only to participants in scheduled / reserved / attended state, never to waitlisted (fix 2024-07-03); per the 2020 integration demo (details owned by INT-09) meetings are created one reservation at a time, recurring occurrences do not get meetings automatically, and the access settings are per location rather than per reservation type
- User story: As an instructor, I want booked clients to receive the meeting link automatically, so that only paying participants can join the stream.
- Actors: admin/instructor; client
- UI generation: both
- Priority: P1
- Evidence: https://www.ezfacility.com/features/member-engagement, https://www.ezfacility.com/blog/new-ezfacility-business-features, https://support.ezfacility.com/hc/en-us/articles/13526384977307-March-9th-2023-Release-Notes, https://support.ezfacility.com/hc/en-us/articles/34155834657819-July-3rd-2024-Release-Notes, https://www.youtube.com/watch?v=hlGAZlxFHWg (t=15:41, t=36:14)

### CLS-09 Client self-booking and cancellation of sessions
- Sub-features: clients view the schedule in portal or app, see openings, descriptions and cut-off times, book and cancel sessions/classes, and see remaining package sessions; booking requirements by package type; purchase-then-auto-book via BUY; "My Schedule" page.
- Settings / options: per-reservation Self-Booking flag; per-type online options (SCH-03); cut-off times (location of setting not documented).
- Rules / limits: portal mechanics are owned by the Self-Service cluster; listed here for the booking rules that the scheduling engine must enforce.
- User story: As a member, I want to book and cancel classes from my phone, so that I manage my own schedule.
- Actors: client/member; parent
- UI generation: both
- Priority: P0
- Evidence: https://www.ezfacility.com/blog/make-the-most-of-ezfacility-management-software-features, https://apps.apple.com/us/app/memberme/id969248357, https://www.ezfacility.com/self-service-portal, https://support.ezfacility.com/hc/en-us/articles/4404311260571-How-to-Schedule-an-Available-Session-in-EZFacility-Classic, https://support.ezfacility.com/hc/en-us/articles/30058087582875-Managing-Self-Service-Shared-Bookings-in-EZFacility-Classic

### CLS-10 Camp / clinic / program registration (delivered through Groups)
- Sub-features: camps, clinics, workshops and multi-week programmes are sold as Groups with online registration rather than as calendar sessions: multi-enrolment in one transaction, guest checkout, discount/coupon codes, registration deposits, waivers in flow, confirmation emails, real-time availability; parents register children from the portal.
- Settings / options: see the Groups & Online Registration cluster (not repeated here).
- Rules / limits: this cluster only records that "class" (package-consuming calendar session) and "camp/clinic" (fee-based group registration) are two different mechanisms in the reference product.
- User story: As a parent, I want to enrol two children in a summer camp in one checkout, so that registration is quick.
- Actors: parent/member/guest; admin
- UI generation: both
- Priority: P0
- Evidence: https://www.ezfacility.com/features/member-engagement, https://www.ezfacility.com/features/scheduling-operations, https://www.ezfacility.com/blog/make-the-most-of-ezfacility-management-software-features, https://www.ezfacility.com/blog/software-release-groups-new-ui

## Clients

### CLI-01 Client profile record
- Sub-features: one record per individual (never one per family); basic contact block; multiple email addresses per client; custom fields (CLI-05); category (CLI-06); referral category + source (CLI-07); default trainer / default salesperson (CLI-17); SMS + email subscription state (CLI-16); created-by/at and modified-by/at stamps; "simple membership" block on the profile (membership number, type, start, expiry; read at check-in); client-level global percentage discount that carries into POS; profile tabs: Profile, Membership, Packages, Schedule, Billing, Documents, Activity, Additional (sports/seasons/tags), Emergency, Assessment, Relationships; email the client from the profile (New UI); organization/company and phone captured from POS; New UI profile header leads with photo, balance, overdue amount and account credit (Classic showed the photo at the bottom); per-client Schedule report on the profile (date range, Generate) listing every booking and its attendance; free-text Comments and Medical Conditions sections for staff notes; notes typed by a registrant during group online registration are copied into Additional Information > Comments, tagged with the group name; a "waiver" checkbox on the profile (DOC-15).
- Settings / options: Gender (label was "Sex" until 2024-05-08); Default Gender (account setting); home location (payment taken at a non-home location raises a warning); global discount percent; simple-membership fields (Membership Number may contain letters, Membership Type, Start date, Expiration date); email list is add-then-save (Classic: Add then Update; New: plus icon).
- Rules / limits: first and last name always required and locked; an email entered but not committed with Add + Update is lost (Classic); marketing claims the profile aggregates visit history, purchases, payment history, communications, league participation, skills assessments and alerts.
- User story: As front-desk staff, I want one authoritative profile per person with contact, membership, billing, document and history tabs, so that every interaction starts from the same record.
- Actors: front desk, owner/admin, trainer, salesperson
- UI generation: both (Classic tab names differ slightly; New UI uses a side/edit panel)
- Priority: P0
- Evidence: https://support.ezfacility.com/hc/en-us/articles/4405137459995-Client-Management, https://support.ezfacility.com/hc/en-us/articles/30146189430171-Adding-a-Client-Profile-to-the-New-EZFacility-Experience, https://support.ezfacility.com/hc/en-us/articles/25551222201627-May-8th-2024-Release-Notes, https://support.ezfacility.com/hc/en-us/articles/26498179644187-June-5th-2024-Release-Notes, https://support.ezfacility.com/hc/en-us/articles/11297336305691-December-15th-2022-Release-Notes, https://www.ezfacility.com/benefits, https://www.ezfacility.com/blog/software-release-vaccine-passport, https://www.ezfacility.com/blog/benefits-of-using-sports-management-software, https://www.youtube.com/watch?v=TWNQ4cTiEFs (t=08:17), https://www.youtube.com/watch?v=TWNQ4cTiEFs (t=29:52), https://www.youtube.com/watch?v=TWNQ4cTiEFs (t=41:14), https://www.youtube.com/watch?v=VuUR1Y9bhjQ (t=31:44)

### CLI-02 Manual client creation
- Sub-features: Add Client from client list (New UI: side panel; Classic: client page); required fields marked bold with asterisk; inline creation of a client from inside other flows (membership sale, document generation wizard, POS); automatic verification email to the client's address on save.
- Settings / options: required-field set comes from the "Client Options / Client Profiles" column of the field policy (CLI-04); email entry via plus icon.
- Rules / limits: submit button is single-click (2023-08-31 fix to stop duplicate profiles); on save a verification email is sent; later features (emailed documents, bulk document send) require the address to be verified; new record surfaces at top of Recently Accessed; New UI as well: an email typed into the add-client form is dropped unless it is committed with the plus button before saving (webinar, early 2025).
- User story: As front-desk staff, I want to create a client in a few required fields without leaving my current task, so that walk-ins can be sold to immediately.
- Actors: front desk, admin
- UI generation: both
- Priority: P0
- Evidence: https://support.ezfacility.com/hc/en-us/articles/30146189430171-Adding-a-Client-Profile-to-the-New-EZFacility-Experience, https://support.ezfacility.com/hc/en-us/articles/18408526583067-August-31st-2023-Release-Notes, https://support.ezfacility.com/hc/en-us/articles/11297336305691-December-15th-2022-Release-Notes, https://support.ezfacility.com/hc/en-us/articles/4404308609179-Generating-a-Document-with-Digital-Acceptance-in-EZFacility-Classic, https://www.youtube.com/watch?v=KAN6h9vPUiM (t=05:08)

### CLI-03 Client list, search and saved views
- Sub-features: free-text search over first name, last name, phone, email (partial matches); View selector; trainer filter; salesperson filter; page-size selector (New); bulk action dropdown on checked rows ("For Checked": Merge Duplicates); Last Session column; status drop-down in client search (active, disabled, or both); waiver column in the client list showing a green check for clients whose waiver flag is set (DOC-15).
- Settings / options: View values: Recently Accessed (default), Recently Created, Birthdays This Month, Birthdays Next Month, All Members, All Contacts, Search Results, Deleted Contacts, Possible Duplicates, No Category, plus one view per client category; Filter By Trainer; Filter By Salesperson; New UI filter toggle + name search + page size.
- Rules / limits: Recently Accessed = last 25 contacts the current user touched (Classic) vs 20 most recently accessed (New); Recently Created and Deleted Contacts cap at 25; All Members = clients whose membership start/expiry window contains today; All Contacts paged by last-name initial with a Show All link; Possible Duplicates = partial first name + full last name + phone; trainer/salesperson filters match only the profile's default trainer/salesperson; type-ahead fires after 3 characters (2023-04-18); search accepts partial email (2024-01-17) and two-word first names (2023-07-03).
- User story: As front-desk staff, I want fast recents plus named views and search, so that I can reach a client in one or two keystrokes without loading the whole database.
- Actors: front desk, trainer, salesperson
- UI generation: both
- Priority: P0
- Evidence: https://support.ezfacility.com/hc/en-us/articles/4405137452187-Searching-For-a-Client, https://support.ezfacility.com/hc/en-us/articles/30146189430171-Adding-a-Client-Profile-to-the-New-EZFacility-Experience, https://support.ezfacility.com/hc/en-us/articles/14655161654811-April-18th-2023-Release-Notes, https://support.ezfacility.com/hc/en-us/articles/16846068050715-July-3rd-2023-Release-Notes, https://support.ezfacility.com/hc/en-us/articles/22122496577179-January-17th-2024-Release-Notes, https://support.ezfacility.com/hc/en-us/articles/23807158781211-March-14th-2024-Release-Notes, https://www.youtube.com/watch?v=C-7p_z3_Cxs (t=36:37), https://www.youtube.com/watch?v=zzEUXdDPMyU (t=18:38)

### CLI-04 Per-context field requirement policy (Contact Preferences)
- Sub-features: matrix of client fields x three capture contexts; each cell independently set; Gender visibility/requirement and Default Gender; applies to staff add-client, group online-registration form, and the "Complete Registration" step after self-service signup.
- Settings / options: contexts: Client Options / Client Profiles (staff side), Online Registration Options (Groups registration form), Self-Service Options (post-signup completion email); cell states (New UI colour-coded): not included (blue), included/optional (green), required (red), system default/locked (gray, e.g. names); Classic exposes only a required tick per context; Gender required toggle; Default Gender; Update Preferences.
- Rules / limits: locked fields cannot be changed; vendor recommends requiring email (invoices, receipts, marketing) and cell phone (SMS reminders; carrier needed for SMS); gender made configurable across the grid, self-service, online registration and Clients page on 2024-04-24; UK forms label the field "Mobile Phone"; the Online Registration column is account-wide and applies to every group, so per-group or per-subgroup form fields are not possible; for group sign-up, email and date of birth are locked as required while zip stays configurable; custom fields sit at the bottom of the grid and are the only way to ask a group-specific question (e.g. team name).
- User story: As an owner, I want to decide per channel which profile fields are hidden, optional or required, so that online signup stays short while staff-entered records stay complete.
- Actors: owner/admin
- UI generation: both (Classic: required-only ticks; New: tri-state + locked)
- Priority: P0
- Evidence: https://support.ezfacility.com/hc/en-us/articles/29861551814171-How-to-Set-Up-Contact-Preferences-in-EZFacility-Classic, https://support.ezfacility.com/hc/en-us/articles/4402427177115-How-to-Set-Up-Contact-Preferences, https://support.ezfacility.com/hc/en-us/articles/4402434184475-How-to-Set-Up-Required-Fields-for-Self-Service-Registration, https://support.ezfacility.com/hc/en-us/articles/25134483797531-April-24th-2024-Release-Notes, https://support.ezfacility.com/hc/en-us/articles/14655161654811-April-18th-2023-Release-Notes, https://www.youtube.com/watch?v=j4Rn9joKKpQ (t=31:41), https://www.youtube.com/watch?v=VuUR1Y9bhjQ (t=31:44)

### CLI-05 Custom client fields
- Sub-features: fixed slots with tenant-defined labels; participate in the field policy matrix once labelled; shown in two columns on the profile; shown (and hide/show-able) in group member views and group registration.
- Settings / options: Custom 1-6 labels (1-3 left column, 4-6 right column).
- Rules / limits: maximum six slots (one New-UI article intro says seven, its own list shows six); a slot's policy options enable only after a label is entered; no typed fields or option lists described (free text, inferred).
- User story: As an owner, I want a handful of extra labelled fields on every client, so that I can capture facility-specific data (school, jersey size) without custom development.
- Actors: owner/admin, front desk
- UI generation: both
- Priority: P1
- Evidence: https://support.ezfacility.com/hc/en-us/articles/29861551814171-How-to-Set-Up-Contact-Preferences-in-EZFacility-Classic, https://support.ezfacility.com/hc/en-us/articles/4402427177115-How-to-Set-Up-Contact-Preferences, https://www.ezfacility.com/blog/ez-features-fixes-check-out-whats-new

### CLI-06 Client categories
- Sub-features: admin-managed category list (add, rename, delete, view members with count); single category per client chosen on the profile (existing or "Add New" inline); each category is a client-list view; category is a filter for email campaigns and billing statements; some reports require categories (Silver Sneakers membership reports).
- Settings / options: Category name; client Category dropdown; "No Category" view.
- Rules / limits: single-valued per client (inferred from dropdown); behaviour on deleting an in-use category not described.
- User story: As a marketer, I want to bucket clients into one primary category, so that lists, statements and campaigns can target the bucket.
- Actors: owner/admin, front desk, marketing
- UI generation: both
- Priority: P0
- Evidence: https://support.ezfacility.com/hc/en-us/articles/4404308586011-How-to-Set-Up-Client-Categories-in-EZFacility-Classic, https://support.ezfacility.com/hc/en-us/articles/4404308588571-Why-Create-Client-Categories-in-EZFacility-Classic, https://support.ezfacility.com/hc/en-us/articles/4405137475355-Add-or-Edit-Client-Categories, https://support.ezfacility.com/hc/en-us/articles/4402426438299-How-to-Set-Up-Client-Categories

### CLI-07 Referral categories and source
- Sub-features: admin list of referral categories with per-category client count drill-down, edit, delete; referral category + free-text referral source on the client.
- Settings / options: Referral Category name; client Referral Category; client Referral Source.
- Rules / limits: none stated; marketing mentions referral-source reporting.
- User story: As an owner, I want each client's acquisition channel recorded, so that I can report which sources convert.
- Actors: owner/admin, front desk, sales
- UI generation: Classic (field present on profile in both, inferred)
- Priority: P1
- Evidence: https://support.ezfacility.com/hc/en-us/articles/4405144371227-How-to-Set-Up-Referral-Categories-in-EZFacility-Classic, https://support.ezfacility.com/hc/en-us/articles/4405137459995-Client-Management

### CLI-08 Tags (sports, seasons, custom)
- Sub-features: three tag families on the profile "Additional" tab; Available vs Active pick-lists; custom tags created inline and immediately available tenant-wide; all three usable as email-campaign filters.
- Settings / options: Sports (preset list, alphabetical Baseball..Wrestling); Seasons (Fall, Spring, Summer, Winter); Tags (custom, type + Add Tag).
- Rules / limits: a newly typed tag persists only if the profile is saved, even when not assigned; no admin screen for tag rename/delete described.
- User story: As staff, I want to tag clients with sports, seasons and ad-hoc labels, so that campaigns can target any combination.
- Actors: staff, marketing
- UI generation: both
- Priority: P0
- Evidence: https://support.ezfacility.com/hc/en-us/articles/28006134764315-How-to-Create-and-Use-Tags-on-a-Client-Profile, https://support.ezfacility.com/hc/en-us/articles/4405137459995-Client-Management

### CLI-09 Activity log with attachments (CRM history)
- Sub-features: log an interaction against a client; reusable subject or inline new subject; attribute to a staff user; attach a file; history list with click-to-edit; the only documented way to store an arbitrary external file on a client (internal-only, not client-visible).
- Settings / options: Activity Type: Phone, Email, Task, Other; Subject (list + "--Other--"); User; Attachment; Message.
- Rules / limits: attachments are staff-only; New UI labels the user field as the user who completed the activity; New UI lists entries under "Activity Tasks" on the Activity tab.
- User story: As a salesperson, I want to log calls, emails and files against a client, so that anyone can see the contact history.
- Actors: front desk, sales, admin
- UI generation: both
- Priority: P1
- Evidence: https://support.ezfacility.com/hc/en-us/articles/4405137428507-How-to-Log-Client-Activity-in-EZFacility-Classic, https://support.ezfacility.com/hc/en-us/articles/15851993226139-How-to-Upload-a-Document-to-a-Client-Profile, https://support.ezfacility.com/hc/en-us/articles/4405137459995-Client-Management

### CLI-10 Activity/task subject list
- Sub-features: tenant-level reusable subject vocabulary shared by activities and tasks; add, edit, delete; inline creation from the activity/task form.
- Settings / options: Subject text.
- Rules / limits: none stated.
- User story: As an admin, I want a controlled list of subjects, so that activity and task reporting is consistent.
- Actors: owner/admin
- UI generation: Classic (reused by New UI activity form, inferred)
- Priority: P1
- Evidence: https://support.ezfacility.com/hc/en-us/articles/4405137446427-How-to-Create-Activity-Subjects-for-Tasks-and-Activities, https://support.ezfacility.com/hc/en-us/articles/4405137428507-How-to-Log-Client-Activity-in-EZFacility-Classic

### CLI-11 Client tasks and task/activity report
- Sub-features: task tied to a client and assigned to a staff user; due and completion dates; attachment; active-task list on the client; per-user open-task counter badge in the global header; Task/Activity report with filters; optional email reminder to the assigned employee (legacy-era webinar, early 2010s; New-UI presence unverified).
- Settings / options: Subject; User (assignee); Attachment; Status (value list not published); Due date; Completion date; Message.
- Rules / limits: counter shows tasks for the signed-in user; subject link opens the task in a new window.
- User story: As a manager, I want to assign dated follow-ups on a client to a colleague, so that leads and issues are not dropped.
- Actors: staff, admin
- UI generation: Classic (New UI "Activity Tasks" area suggests parity, inferred)
- Priority: P1
- Evidence: https://support.ezfacility.com/hc/en-us/articles/4405137471643-Creating-a-Task, https://support.ezfacility.com/hc/en-us/articles/15851993226139-How-to-Upload-a-Document-to-a-Client-Profile, https://www.youtube.com/watch?v=iHdqoLdGlQI (t=16:28)

### CLI-12 Client photo
- Sub-features: capture by webcam, file picker, or drag-and-drop (New); client can change their own picture in the self-service portal and it syncs to the staff profile; photo is surfaced at check-in.
- Settings / options: location-level setting allowing clients to edit their photo (setting name not published); browser camera permission with remember option.
- Rules / limits: Classic capture was rebuilt for modern browsers (no plugin).
- User story: As front-desk staff, I want a photo on every profile, so that I can verify identity at check-in.
- Actors: front desk, client
- UI generation: both (Classic: webcam only; New: webcam/upload/drag-drop + self-service)
- Priority: P0
- Evidence: https://support.ezfacility.com/hc/en-us/articles/4405137480859-How-to-Add-a-Client-s-Photo-to-their-Account, https://support.ezfacility.com/hc/en-us/articles/29093590126363-How-to-add-a-Photo-to-a-Client-Profile, https://support.ezfacility.com/hc/en-us/articles/4405137459995-Client-Management, https://www.ezfacility.com/features/member-engagement

### CLI-13 Duplicate detection and merge
- Sub-features: Possible Duplicates view; multi-select and Merge Duplicates bulk action; choose survivor; two or more records per merge.
- Settings / options: none beyond survivor selection.
- Rules / limits: Classic: non-survivors are deleted, and invoices, reservations, group memberships etc. are re-pointed to the survivor; with exactly two records, blank survivor fields are back-filled from the other, excluding stored card data and interests. New: memberships and group registrations on the losing profiles must be cancelled first; losers end up disabled. 2024-04-24: confirmation pop-up removed and warning reworded for the multiple-active-memberships case; no self-serve bulk delete of clients or bulk duplicate clean-up; the vendor's answer is to ask support; when a Smartwaiver submission matches several existing clients the system does not merge, it emails account admins to resolve or merge by hand (DOC-13).
- User story: As an admin, I want to collapse duplicate profiles into one, so that history and balances are not split.
- Actors: admin, front desk
- UI generation: both (different post-conditions, see rules)
- Priority: P1
- Evidence: https://support.ezfacility.com/hc/en-us/articles/4405144383003-Merging-Duplicate-Clients, https://support.ezfacility.com/hc/en-us/articles/28071987897371-How-to-Merge-Client-Profiles, https://support.ezfacility.com/hc/en-us/articles/25134483797531-April-24th-2024-Release-Notes, https://support.ezfacility.com/hc/en-us/articles/4405137452187-Searching-For-a-Client, https://www.youtube.com/watch?v=TWNQ4cTiEFs (t=27:45), https://www.youtube.com/watch?v=jbwkXIo9rY8 (t=09:10)

### CLI-14 Disable (soft-delete) a client
- Sub-features: Disable Client action with confirmation from the profile; disabled clients drop out of operational pickers; Classic "Deleted Contacts" view lists the last 25 deleted; "disabled clients" filter view (top 25 by default) and a search status drop-down (active / disabled / both) to find disabled records.
- Settings / options: client state active / disabled (Classic wording: deleted).
- Rules / limits: disabled clients are excluded from session-registration search and from the self check-in window (2024-01-17); re-enable path not documented; Open Invoices report distinguishes active vs deleted clients; disable keeps all of the client's data; the destructive alternative is the permanent delete owned by the import/data cluster (IMP-04), which strips personal information only.
- User story: As an admin, I want to retire a profile without losing its financial history, so that lists stay clean and audits stay intact.
- Actors: admin
- UI generation: both
- Priority: P0
- Evidence: https://support.ezfacility.com/hc/en-us/articles/27849984397979-How-to-Disable-a-Client, https://support.ezfacility.com/hc/en-us/articles/22122496577179-January-17th-2024-Release-Notes, https://support.ezfacility.com/hc/en-us/articles/4405137452187-Searching-For-a-Client, https://www.youtube.com/watch?v=C-7p_z3_Cxs (t=36:37), https://www.youtube.com/watch?v=C-7p_z3_Cxs (t=21:21)

### CLI-15 Self-service portal access provisioning
- Sub-features: per-client Self-Service block on the profile: Enabled checkbox, invite-sent date, portal username, staff-triggered password reset; enabling sends an invitation email from which the client sets username and password; re-send by toggling.
- Settings / options: Enabled (bool); invite sent date (read-only); username (read-only to staff).
- Rules / limits: an email on file is required to enable.
- User story: As front-desk staff, I want to grant or re-send portal access from the profile, so that members can self-serve without a support ticket.
- Actors: front desk, client
- UI generation: New
- Priority: P0
- Evidence: https://support.ezfacility.com/hc/en-us/articles/9061322036635-How-to-Send-a-Self-Service-Invitation-Through-the-Client-Profile

### CLI-16 Communication subscriptions (email and SMS consent)
- Sub-features: per-email-address subscription management on the profile; SMS subscription flag with mobile carrier ("Service Provider") selection, used for session reminders by text; public "Manage your subscriptions" link in campaign emails.
- Settings / options: SMS subscribed (bool); SMS Service Provider (carrier list); per-email subscription flags (list of subscription types not published).
- Rules / limits: Classic SMS requires a carrier on the profile (email-to-SMS gateway, inferred); a 2026 help article signals relabelled email/SMS subscription options for US accounts only (title only, body not read).
- User story: As a client, I want to control which emails and texts I receive, so that the facility stays compliant and I am not spammed.
- Actors: front desk, client, marketing
- UI generation: both
- Priority: P0
- Evidence: https://support.ezfacility.com/hc/en-us/articles/4405137459995-Client-Management, https://support.ezfacility.com/hc/en-us/articles/29861551814171-How-to-Set-Up-Contact-Preferences-in-EZFacility-Classic, https://support.ezfacility.com/hc/en-us/articles/25134483797531-April-24th-2024-Release-Notes, https://support.ezfacility.com/hc/en-us/articles/54600257319195-Email-SMS-Subscriptions-Labeling-Update-US-Only-Update (title only, body not read)

### CLI-17 Default trainer / salesperson ownership
- Sub-features: Default Trainer and Default Salesperson on the profile; client-list filters by each; used to restrict which clients an employee can see.
- Settings / options: Default Trainer (user); Default Salesperson (user).
- Rules / limits: filters match on these defaults only; the permission that enforces own-clients-only is referenced, not described.
- User story: As an owner, I want each client owned by a trainer and a salesperson, so that lists, commissions and access can be scoped per employee.
- Actors: owner/admin, trainer, salesperson
- UI generation: Classic (New UI parity inferred)
- Priority: P1
- Evidence: https://support.ezfacility.com/hc/en-us/articles/4405137452187-Searching-For-a-Client, https://support.ezfacility.com/hc/en-us/articles/4405137459995-Client-Management

### CLI-18 Emergency contacts
- Sub-features: Emergency tab on the profile.
- Settings / options: Emergency Contact 1, Emergency Contact 2 (sub-fields not listed).
- Rules / limits: maximum two.
- User story: As staff, I want emergency contacts on the profile, so that I can reach someone if a member is injured.
- Actors: front desk
- UI generation: Classic (New UI parity inferred)
- Priority: P0
- Evidence: https://support.ezfacility.com/hc/en-us/articles/4405137459995-Client-Management

### CLI-19 Cross-location shared client record
- Sub-features: one client database shared by all locations of an account; client has a home location; clients of another location are selectable in sales flows; signed waivers visible across sites.
- Settings / options: home location.
- Rules / limits: warning when taking a payment for a client outside their home location (2024-05-08).
- User story: As a multi-site operator, I want a member known at every site, so that they can buy and check in anywhere without re-registration.
- Actors: owner/admin, front desk
- UI generation: both
- Priority: P0
- Evidence: https://www.ezfacility.com/ezfacility-comparison, https://support.ezfacility.com/hc/en-us/articles/25551222201627-May-8th-2024-Release-Notes, https://support.ezfacility.com/hc/en-us/articles/11297336305691-December-15th-2022-Release-Notes

### CLI-20 Staff-facing client alerts and notes
- Sub-features: pop-up alerts tied to a member shown to staff at check-in (photo, birthday message, injury note, past-due or expired membership).
- Settings / options: not published in the help-center articles of this cluster.
- Rules / limits: evidence is blog-level only; alert authoring UI unknown.
- User story: As front-desk staff, I want member-specific alerts when I open or check in a client, so that I act on balances, injuries or birthdays.
- Actors: front desk
- UI generation: unknown
- Priority: P1
- Evidence: https://www.ezfacility.com/blog/your-management-software-solution-and-your-front-desk, https://www.ezfacility.com/benefits

### CLI-21 Client API surface
- Sub-features: staff-scope client endpoints; a self-service-scope update-client endpoint with a reduced field set (2024-01-31); client payloads expose the current membership contract id, the contract-owning client id, the number of clients on the contract and its total billed amount (2024-03-14).
- Settings / options: OAuth-style scopes "TMS" (staff) vs "Self-Service".
- Rules / limits: self-service scope cannot update every field.
- User story: As an integrator, I want to read and update clients through the API, so that my website or app can keep profiles in sync.
- Actors: integrator
- UI generation: n-a
- Priority: P1
- Evidence: https://support.ezfacility.com/hc/en-us/articles/22529640450203-January-31-2024-Release-Notes, https://support.ezfacility.com/hc/en-us/articles/23807158781211-March-14th-2024-Release-Notes

## Households & Family

### FAM-01 Typed client-to-client relationships (staff side)
- Sub-features: link two existing client profiles with a relationship type read from the current profile toward the other; reciprocal display on the other profile with the inverse label; click-through to the related profile; remove link; drives membership/package sharing candidates and on-behalf booking in the portal; relationships can also be created by the system: extra participants and minors on a Smartwaiver waiver become linked clients with the relationship ("parent of") set automatically (DOC-13).
- Settings / options: Relationship Type list (only "Child of"/"Child", parent and spouse are evidenced; full list not published); related client (type-ahead).
- Rules / limits: both profiles must exist first; link is not persisted until the profile is saved (Update/Save); relationships are pairwise and non-transitive (the other person's relationships are not inherited); a relationship alone grants no entitlement to use a membership or package; vendor GDPR guidance (2018) is to track parental consent for under-16s through client relationships, with no enforcement in the product.
- User story: As front-desk staff, I want to link parents, children and spouses, so that sharing, on-behalf booking and family context work.
- Actors: front desk, admin
- UI generation: both
- Priority: P0
- Evidence: https://support.ezfacility.com/hc/en-us/articles/4405144396955-Establishing-Relationship-Between-Clients, https://support.ezfacility.com/hc/en-us/articles/27907266866715-How-to-Establish-Relationships-between-Clients-on-their-Profiles, https://support.ezfacility.com/hc/en-us/articles/4401990000411-How-to-Share-a-Membership, https://support.ezfacility.com/hc/en-us/articles/22132354311067-How-to-Share-a-Package-Plan, https://www.ezfacility.com/industries/basketball-scheduling-software, https://www.youtube.com/watch?v=jbwkXIo9rY8 (t=12:14), https://www.youtube.com/watch?v=C-7p_z3_Cxs (t=43:28)

### FAM-02 Self-service relationship management
- Sub-features: portal user adds a relationship by creating a new person (dependent) or by finding an existing account holder by name; existing-account links require the other party to confirm by email; one login then manages all linked people.
- Settings / options: "I want to add a/an" relationship type (example: Child); new-person details (email may duplicate the parent's).
- Rules / limits: existing-account link is pending until the other person verifies; a parent can buy for a relative who has no portal registration (2023-08-02 fix); duplicate emails across related profiles are allowed.
- User story: As a parent, I want to add my children to my login, so that I can manage the whole family from one account.
- Actors: client/parent, related adult
- UI generation: New
- Priority: P0
- Evidence: https://support.ezfacility.com/hc/en-us/articles/25312556816539-Create-and-Manage-Relationships-in-Self-Service, https://support.ezfacility.com/hc/en-us/articles/17574439837467-August-2nd-2023-Release-Notes

### FAM-03 Act on behalf of a related person in self-service
- Sub-features: person selector when buying memberships ("Memberships" dropdown), packages ("Packages For"), booking sessions (Filter by person / "Book For"), booking rentals, and viewing My Schedule; payment uses the logged-in user's payment info and billing address; rental plans can be bought or added to the cart on behalf of a related person (demo: spouse).
- Settings / options: rental search inputs when booking for a person: person, location (if multiple), rental type, single venue, days of week, Start Search On, Rental Length, Start Time (hour granularity).
- Rules / limits: one venue per rental booking; start time adjustable by hour only; on-behalf options list only related people.
- User story: As a parent, I want to buy and book for my child from my own login, so that the child needs no account.
- Actors: client/parent
- UI generation: New
- Priority: P0
- Evidence: https://support.ezfacility.com/hc/en-us/articles/25312556816539-Create-and-Manage-Relationships-in-Self-Service, https://support.ezfacility.com/hc/en-us/articles/22132354311067-How-to-Share-a-Package-Plan, https://support.ezfacility.com/hc/en-us/articles/17574439837467-August-2nd-2023-Release-Notes, https://www.youtube.com/watch?v=ERaBaf5YWHo (t=21:27)

### FAM-04 Membership sharing
- Sub-features: Share action on a sold membership contract; tick related clients or search and add unrelated clients; API exposes owner client, client count and total billed amount for a shared contract.
- Settings / options: share list per contract.
- Rules / limits: related profiles should exist before the contract holder is sold to; relationship does not imply sharing; merge warns when it would leave multiple active memberships; vendor best practice: sell a child's membership on the child's own profile with the parent's billing details, and use sharing only when several people really use one contract; sharing a membership is a permission the preset staff role lacks by default.
- User story: As front-desk staff, I want one paid contract to cover several family members, so that a family plan bills once but admits everyone.
- Actors: admin, front desk
- UI generation: New (Classic relationship article also cites sharing)
- Priority: P0
- Evidence: https://support.ezfacility.com/hc/en-us/articles/4401990000411-How-to-Share-a-Membership, https://support.ezfacility.com/hc/en-us/articles/4405144396955-Establishing-Relationship-Between-Clients, https://support.ezfacility.com/hc/en-us/articles/23807158781211-March-14th-2024-Release-Notes, https://support.ezfacility.com/hc/en-us/articles/25134483797531-April-24th-2024-Release-Notes, https://www.youtube.com/watch?v=KAN6h9vPUiM (t=09:14), https://www.youtube.com/watch?v=KAN6h9vPUiM (t=08:14)

### FAM-05 Package sharing
- Sub-features: Share action on a sold package (Packages tab); related clients listed, unrelated searchable; package plans can be flagged to allow sharing so that a package bundled in a membership auto-shares with related clients at sale; shared users book against the same balance; waitlist auto-booking works for sharers.
- Settings / options: package plan "allow sharing"/auto-share flag (exact label not in this cluster); share list per sold package.
- Rules / limits: auto-share only if the package plan allows it; relationship alone is not authorization; waitlisted sharers are auto-booked when a spot opens (2023-09-27).
- User story: As a parent, I want my session pack usable by my kids, so that one purchase covers the household.
- Actors: admin, front desk, client/parent
- UI generation: New
- Priority: P0
- Evidence: https://support.ezfacility.com/hc/en-us/articles/22132354311067-How-to-Share-a-Package-Plan, https://support.ezfacility.com/hc/en-us/articles/4401990000411-How-to-Share-a-Membership, https://support.ezfacility.com/hc/en-us/articles/19132331777307-September-27th-2023-Release-Notes

### FAM-06 Rental plan sharing
- Sub-features: a sold rental plan is shared with related clients from the Rental plans tab on the owner's profile; the plan definition carries a sharing option scoped to relationships (demo names siblings and parents); sharers book against the same prepaid hours/occurrences, in the portal as well as at the desk.
- Settings / options: rental plan: sharing across relationships (plan-level option); share list per sold plan on the client's Rental plans tab.
- Rules / limits: sharing shown only between related clients (unrelated-client search, as offered for memberships/packages, not demonstrated); balance is one pool (used/remaining hours shown on the plan); plan mechanics belong to the rentals cluster (RNT-09/RNT-10).
- User story: As a team organiser, I want my prepaid rental hours usable by another client, so that either of us can book against the balance.
- Actors: admin, client
- UI generation: New
- Priority: P1
- Evidence: https://support.ezfacility.com/hc/en-us/articles/57004869280027-How-to-Share-a-Rental-Plan (title only, body not read), https://www.youtube.com/watch?v=ERaBaf5YWHo (t=06:09), https://www.youtube.com/watch?v=ERaBaf5YWHo (t=14:14)

## Waivers & Documents

### DOC-01 Document templates
- Sub-features: create, edit, delete, preview; plain-text paste helper; recent list (most recently used/created) for edit and selection; template name appears in service-binding dropdowns; description doubles as the subject line of the generated document; configurable acceptance statement; hyperlink manager in the template editor (URL, link text, anchor and email-link options), aimed at emailed documents that point signers to another page or file on the facility's site.
- Settings / options: Document Type: Client Document, GDPR Consent (second value only for GDPR-enabled accounts); Template Name; Description; Template Body; Template Acceptance text; Acceptance Preview; actions Save / Cancel / Preview / Paste Plain Text.
- Rules / limits: acceptance text max 1,000 characters (2024-01-17); description max 240 characters (stated on the GDPR article); no in-body initials or signature fields, one acknowledgement per document; no template versioning described; the Documents module is switched on per account by support or the account manager (stated 2018); the vendor supplies no template library, all wording comes from the facility.
- User story: As an owner, I want to author my own waivers and policies, so that clients accept current terms without a third-party tool.
- Actors: owner/admin
- UI generation: both
- Priority: P0
- Evidence: https://support.ezfacility.com/hc/en-us/articles/4404305716251-Creating-and-Editing-Document-Templates-in-EZFacility-Classic, https://support.ezfacility.com/hc/en-us/articles/11840312242331-Creating-Document-Templates-in-EZFacility, https://support.ezfacility.com/hc/en-us/articles/27663085801883-Editing-Document-Templates-in-EZFacility, https://support.ezfacility.com/hc/en-us/articles/4411661820955-How-use-Documents-to-Create-Membership-Waivers-for-Self-Service, https://support.ezfacility.com/hc/en-us/articles/4411809532187-How-use-Documents-to-Create-Membership-Waivers-when-selling-a-Membership-in-person, https://support.ezfacility.com/hc/en-us/articles/38068886342171-How-to-Create-a-GDPR-Document, https://support.ezfacility.com/hc/en-us/articles/4416793387803-Online-Webinar-Exploring-Documents-in-EZFacility-Classic, https://support.ezfacility.com/hc/en-us/articles/22122496577179-January-17th-2024-Release-Notes, https://www.youtube.com/watch?v=zzEUXdDPMyU (t=30:09), https://www.youtube.com/watch?v=TWNQ4cTiEFs (t=15:29), https://www.youtube.com/watch?v=C-7p_z3_Cxs (t=13:08)

### DOC-02 Generate a document for a client
- Sub-features: wizard entry points: Administration > Documents > Generate Document (pick or create client) and the client's Documents tab; template search or recent list; choose acceptance path; result screen with new document / email copy / print.
- Settings / options: Acceptance Type: Paper Copy, Digital Copy, Digital Signature, Email Document; finish actions: Finish, Email, Print.
- Rules / limits: status Pending until accepted, then Signed; pop-up/PDF handled by the browser.
- User story: As front-desk staff, I want to issue any template to a client on demand, so that walk-ins sign before participating.
- Actors: front desk, client
- UI generation: both
- Priority: P0
- Evidence: https://support.ezfacility.com/hc/en-us/articles/4404308609179-Generating-a-Document-with-Digital-Acceptance-in-EZFacility-Classic, https://support.ezfacility.com/hc/en-us/articles/4404314929051-Generating-a-Document-from-a-Client-s-Account-in-EZFacility-Classic, https://support.ezfacility.com/hc/en-us/articles/4402426437275-Generating-a-Document-from-a-Client-s-Account, https://support.ezfacility.com/hc/en-us/articles/4411809532187-How-use-Documents-to-Create-Membership-Waivers-when-selling-a-Membership-in-person, https://support.ezfacility.com/hc/en-us/articles/4416793387803-Online-Webinar-Exploring-Documents-in-EZFacility-Classic

### DOC-03 In-person digital acceptance (checkbox, co-signer, drawn signature)
- Sub-features: client ticks the acceptance statement on the staff device; optional co-signer name (guardian); drawn signature by touch screen, mouse or signature pen/pad; email or print the accepted copy; New UI signature view captures the child's signature and then a separate guardian signature; co-signer is offered on both Digital Copy and Digital Signature in the New UI.
- Settings / options: accept checkbox; Co-Signer name (free text); method Digital Copy vs Digital Signature.
- Rules / limits: co-signer is a typed name, not a linked client; no explicit minor/age rule described.
- User story: As a client at the desk, I want to accept a waiver on screen, so that there is no paper.
- Actors: front desk, client, guardian
- UI generation: both (drawn signature evidenced in New)
- Priority: P0
- Evidence: https://support.ezfacility.com/hc/en-us/articles/4404308609179-Generating-a-Document-with-Digital-Acceptance-in-EZFacility-Classic, https://support.ezfacility.com/hc/en-us/articles/4411809532187-How-use-Documents-to-Create-Membership-Waivers-when-selling-a-Membership-in-person, https://support.ezfacility.com/hc/en-us/articles/38071098727067-How-to-Send-a-GDPR-Document-to-a-client-from-their-profile, https://www.youtube.com/watch?v=TWNQ4cTiEFs (t=23:38)

### DOC-04 Remote acceptance by email
- Sub-features: preview then Save and Email; choose which of the client's stored email addresses receive it; client opens a link and accepts on any device; re-send from results screen, document history or audit; client can decline from the email; acceptance record shows IP address, date/time and the staff user who generated the document, viewable from the client's Membership tab; on the emailed path the name the client types is stored as the signature text.
- Settings / options: recipient address selection; Re-send Email.
- Rules / limits: stays Pending until returned; link lifetime stated as 48 hours (GDPR article) and 24 hours (membership waiver article); New UI requires a verified client email; a declined document re-enables a "View Text" link on the membership grid (2023-04-18); an emailed document reads as sent/delivered (Pending) rather than signed until the client acts; staff get no notification when a client signs (logged as feedback, early 2025).
- User story: As a client, I want to sign from my phone before I arrive, so that check-in is not delayed.
- Actors: front desk, client
- UI generation: both
- Priority: P0
- Evidence: https://support.ezfacility.com/hc/en-us/articles/4404308612891-Generating-a-Document-with-Acceptance-by-Email-in-EZFacility-Classic, https://support.ezfacility.com/hc/en-us/articles/38071098727067-How-to-Send-a-GDPR-Document-to-a-client-from-their-profile, https://support.ezfacility.com/hc/en-us/articles/4411809532187-How-use-Documents-to-Create-Membership-Waivers-when-selling-a-Membership-in-person, https://support.ezfacility.com/hc/en-us/articles/14655161654811-April-18th-2023-Release-Notes, https://www.youtube.com/watch?v=KAN6h9vPUiM (t=28:49), https://www.youtube.com/watch?v=KAN6h9vPUiM (t=47:21), https://www.youtube.com/watch?v=C-7p_z3_Cxs (t=27:22)

### DOC-05 Paper acceptance with scan upload
- Sub-features: produce PDF to print; upload the signed scan; signed flag set automatically on upload and manually clearable; remove uploaded file; save valid in either state; used as the staff workaround for outside paperwork (e.g. a child's physical): generate with Paper Copy and upload the file the client already signed; also the way to log consent given verbally or on paper.
- Settings / options: Uploaded document (PDF only); Paper Copy Signed (bool).
- Rules / limits: upload must be PDF; Signed if flag set, else Pending; clients cannot upload a document themselves in self-service.
- User story: As front-desk staff, I want to file a wet-ink waiver against the client, so that paper signers are still tracked.
- Actors: front desk
- UI generation: both
- Priority: P1
- Evidence: https://support.ezfacility.com/hc/en-us/articles/4404314931483-Generating-a-Document-to-Print-Paper-Acceptance-in-EZFacility-Classic, https://support.ezfacility.com/hc/en-us/articles/4411809532187-How-use-Documents-to-Create-Membership-Waivers-when-selling-a-Membership-in-person, https://support.ezfacility.com/hc/en-us/articles/4402426437275-Generating-a-Document-from-a-Client-s-Account, https://www.youtube.com/watch?v=zzEUXdDPMyU (t=13:26), https://www.youtube.com/watch?v=C-7p_z3_Cxs (t=31:32)

### DOC-06 Document history (account-wide and per client)
- Sub-features: account-level searchable log with location and date-range filters; per-client Documents tab; row actions view, email copy, delete; used to chase Pending documents.
- Settings / options: filters: Location, Date Range, First Name, Last Name, Document Name, Description, Status; statuses Pending, Signed; statuses shown in the New UI history: Signed, Pending, Declined, Deleted; row columns: description, name, created date/time, acceptance type, document type.
- Rules / limits: email action only for digital documents (Classic); multi-site accounts see signed waivers across sites (marketing claim); a deleted document stays listed as Deleted and can be recovered within 30 days; Smartwaiver waivers appear on the client's Documents tab in a separate table from native documents (DOC-13).
- User story: As an admin, I want to find any issued document and its state, so that I can prove acceptance or chase stragglers.
- Actors: admin, front desk
- UI generation: both
- Priority: P0
- Evidence: https://support.ezfacility.com/hc/en-us/articles/4404308614811-How-to-View-Document-History-in-EZFacility-Classic, https://support.ezfacility.com/hc/en-us/articles/27663284408603-View-a-History-of-all-Acknowledged-Documents, https://support.ezfacility.com/hc/en-us/articles/27663294760091-How-to-View-Document-History-on-a-Client-Profile, https://support.ezfacility.com/hc/en-us/articles/4404314929051-Generating-a-Document-from-a-Client-s-Account-in-EZFacility-Classic, https://www.ezfacility.com/ezfacility-comparison, https://www.youtube.com/watch?v=zzEUXdDPMyU (t=06:15), https://www.youtube.com/watch?v=jbwkXIo9rY8 (t=10:11)

### DOC-07 Missing-document audit and bulk email
- Sub-features: Clients > Audit Clients > Documents: pick a template, list clients who have never received it, select all or some, email the document; post-send summary count (New).
- Settings / options: document selector; client selection.
- Rules / limits: cannot filter by client category; acceptance is tracked in Document History, not here; New UI sends only to clients with a verified email; also the route to push a new document to everyone; no automatic emailing of a waiver when a client is created and no reminders for unsigned documents (reminders exist only for scheduled items); this audit-and-send screen is the stated substitute.
- User story: As an admin, I want to see who lacks the current waiver and send it in bulk, so that coverage reaches 100%.
- Actors: admin
- UI generation: both
- Priority: P1
- Evidence: https://support.ezfacility.com/hc/en-us/articles/4404308617115-Using-Client-Audit-with-Documents, https://support.ezfacility.com/hc/en-us/articles/4404312856731-Using-Client-Audit-with-Documents, https://support.ezfacility.com/hc/en-us/articles/38072534577307-How-to-send-Documents-in-en-mass, https://www.youtube.com/watch?v=zzEUXdDPMyU (t=16:31), https://www.youtube.com/watch?v=zzEUXdDPMyU (t=19:41)

### DOC-08 Documents bound to services (membership plans, group registration)
- Sub-features: default document on a membership plan; one account-wide document for all group online registrations; acceptance step enforced at self-service checkout and prompted in staff sale; accepted copy lands on the client's Documents tab; replaces Classic membership agreements for accounts fully on the New UI; package plans can carry their own document too (field at the bottom of the plan's main details page, like membership plans).
- Settings / options: Membership plan: Default Document; Online Registration settings: Document; Package plan: document; Online Registration settings: Allow Online Waiver Fulfilment (must be on, otherwise the registration document is not enforced).
- Rules / limits: one document per membership plan; group document is global, not per group; document acknowledged once, at sale; a 2025-04-23 fix addressed the acceptance step being skipped on the first sale attempt; bindable to membership plans, package plans and group registration only, not to rentals, rental types or POS items (rental permit workaround: generate from the client's Documents tab before or after booking; birthday-party workaround: run it as a Group with online registration); a package-plan document is acknowledged only on the staff side: an online package purchase completes without signing and leaves the document Pending on the profile, whereas membership documents are signed both in person and online; accepting a membership document does not set the profile waiver checkbox (DOC-15).
- User story: As an owner, I want buying a membership or registering for a program to force waiver acceptance, so that nobody participates unsigned.
- Actors: owner/admin, front desk, client
- UI generation: New
- Priority: P0
- Evidence: https://support.ezfacility.com/hc/en-us/articles/27662401294875-How-to-Connect-Documents-to-Services, https://support.ezfacility.com/hc/en-us/articles/4411661820955-How-use-Documents-to-Create-Membership-Waivers-for-Self-Service, https://support.ezfacility.com/hc/en-us/articles/4411809532187-How-use-Documents-to-Create-Membership-Waivers-when-selling-a-Membership-in-person, https://support.ezfacility.com/hc/en-us/articles/36516396025115-April-23rd-2025-Release-Notes, https://www.ezfacility.com/blog/software-release-vaccine-passport, https://www.youtube.com/watch?v=zzEUXdDPMyU (t=09:21), https://www.youtube.com/watch?v=zzEUXdDPMyU (t=11:24), https://www.youtube.com/watch?v=Rjy8ZpfIA68 (t=16:26), https://www.youtube.com/watch?v=Rjy8ZpfIA68 (t=37:58), https://www.youtube.com/watch?v=VuUR1Y9bhjQ (t=10:15), https://www.youtube.com/watch?v=TWNQ4cTiEFs (t=16:30)

### DOC-09 GDPR consent document
- Sub-features: location-level Enable GDPR switch; dedicated GDPR Consent template type embedding a vendor-supplied GDPR text link; profile banner until the client has accepted; send from profile by email or accept on screen; print/email signed copy; consent pop-up when staff create a client while GDPR is on and a GDPR template exists (names the facility and the vendor as processor; the client ticks the box personally); the GDPR document can be chosen as the online-registration agreement, the portal carries consent wording, and clients created through the league product can consent as well.
- Settings / options: Location: Enable GDPR; template Document Type = GDPR Consent; EZFacility GDPR Text link; Template Acceptance wording.
- Rules / limits: exactly one GDPR template at a time; enabling without one prompts and redirects to create it; email path needs a verified address and the link expires after 48 hours; banner clears on acceptance; consent is logged only by documents of type GDPR Consent, never by an ordinary client document; the vendor appends its own processor text and privacy-policy link to the facility-written body; the red no-consent banner comes back if the consent document is deleted; phone or in-person consent is logged with the paper acceptance type; a companion per-client data export (Excel) and permanent delete exist in the import/data cluster (IMP-04).
- User story: As a UK/EU operator, I want explicit, recorded data-processing consent per client, so that I can evidence GDPR compliance.
- Actors: owner/admin, front desk, client
- UI generation: New
- Priority: P1
- Evidence: https://support.ezfacility.com/hc/en-us/articles/38068447234331-How-to-Enable-GDPR-on-EZFacility, https://support.ezfacility.com/hc/en-us/articles/38068886342171-How-to-Create-a-GDPR-Document, https://support.ezfacility.com/hc/en-us/articles/38071098727067-How-to-Send-a-GDPR-Document-to-a-client-from-their-profile, https://www.youtube.com/watch?v=C-7p_z3_Cxs (t=13:08), https://www.youtube.com/watch?v=C-7p_z3_Cxs (t=16:14), https://www.youtube.com/watch?v=C-7p_z3_Cxs (t=27:22), https://www.youtube.com/watch?v=C-7p_z3_Cxs (t=54:43)

### DOC-10 Legacy membership agreement template (Classic, advanced memberships)
- Sub-features: single account-level agreement with three sections (Contract, Auto-Pay Agreement, Terms and Conditions); contract section built from includable/relabelable contract fields; required signers per section; missing-signature warning; preview and export; option to present the agreement during online membership purchase.
- Settings / options: section texts; contract field include/exclude + label; signer roles per section: Contract Owner, Other Contract Users, Invoice Holder; warn on missing required signature; Allow Online Agreement; Save / Save and Preview; export Word, PDF and others.
- Rules / limits: advanced (recurring-billing) contracts only; superseded by DOC-08 for fully transitioned New-UI accounts (announced 2021-11-29); with Allow Online Agreement on, ticking the checkbox at the portal agreement step counts as signing and the client can email a copy to the address on file; with it off the portal skips the agreement step and goes straight to checkout, and the contract can be signed at the next visit (March 2016 release webinar).
- User story: As an owner, I want a contract with autopay authorization and terms signed by the right parties, so that recurring billing is enforceable.
- Actors: owner/admin
- UI generation: Classic
- Priority: P2 (legacy; superseded 2021-11-29)
- Evidence: https://support.ezfacility.com/hc/en-us/articles/29852220977051-Setting-Up-a-Membership-Agreements-in-EZFacility-Classic, https://support.ezfacility.com/hc/en-us/articles/29852227776923-Enabling-Membership-Agreements-when-Selling-Memberships-Online-in-EZFacility-Classic, https://www.ezfacility.com/blog/software-release-vaccine-passport, https://www.youtube.com/watch?v=SDO3SkkHTlY (t=08:20), https://www.youtube.com/watch?v=SDO3SkkHTlY (t=10:30)

### DOC-11 Membership agreement instance (create, view, export, print, sign)
- Sub-features: per-contract agreement created from the client's Membership tab; view agreement or captured signature; edit; export Word/PDF; print; capture signature on a pad, or toggle a signed flag when no pad is present.
- Settings / options: Agreement column actions Create / View / Edit; Select a Format (Word, PDF); signed toggle.
- Rules / limits: opens in a pop-up (blocked by pop-up blockers); print icon works in Internet Explorer only.
- User story: As front-desk staff, I want to produce and sign the contract at point of sale, so that the member leaves with an executed agreement.
- Actors: front desk, client
- UI generation: Classic
- Priority: P2 (legacy; superseded 2021-11-29)
- Evidence: https://support.ezfacility.com/hc/en-us/articles/29852081983387-Creating-a-Membership-Contract-Agreement-in-EZFacility-Classic, https://support.ezfacility.com/hc/en-us/articles/4404308371995-Viewing-A-Membership-Contract-Agreement-in-EZFacility-Classic

### DOC-12 Signature capture hardware (Topaz pad/pen)
- Sub-features: USB signature pad driven through a locally installed vendor bridge (SigWeb) for agreements and documents; touch screen or mouse as fallbacks.
- Settings / options: workstation driver install with default presets.
- Rules / limits: per-workstation install; without a pad the staff member toggles signed status.
- User story: As front-desk staff, I want members to sign on a pad, so that the signature image is stored with the document.
- Actors: admin, front desk
- UI generation: both
- Priority: v2-adapter
- Evidence: https://support.ezfacility.com/hc/en-us/articles/4426140759451-Topaz-Signature-Pad-Setup-and-Update, https://support.ezfacility.com/hc/en-us/articles/29852081983387-Creating-a-Membership-Contract-Agreement-in-EZFacility-Classic, https://support.ezfacility.com/hc/en-us/articles/29852220977051-Setting-Up-a-Membership-Agreements-in-EZFacility-Classic, https://support.ezfacility.com/hc/en-us/articles/4411809532187-How-use-Documents-to-Create-Membership-Waivers-when-selling-a-Membership-in-person

### DOC-13 Smartwaiver integration
- Sub-features: connect an external waiver account by API key; provider webhook pushes signed waivers into the platform; signing creates or updates the client record; signed waivers stored on the client; provider kiosk apps (iPad/Android) and online signing; per-template routing of webhooks to a different location; client matching on each submission (existing match receives the waiver; no match creates a client; several matches email the account admins, never an auto-merge); extra participants and minors on one waiver become their own linked clients with the relationship set automatically; Documents tab lists provider waivers in their own table (title, signed date, expiry, signer/participant, participant count, minors flag) with View as PDF and email-a-copy; drives the profile waiver checkbox (DOC-15); a branded mobile app can link to the waiver through a web tile.
- Settings / options: Administration > Smartwaiver (visible only once a provider account exists): API Key, Activate; provider-side account webhook URL carrying the location id; per-template "Send Webhook for this waiver" + URL override; Email validation Yes/No (Yes holds a signed waiver out of the platform until the signer confirms their email; a per-waiver setting on the provider side overrides it, e.g. validate online but not at the kiosk).
- Rules / limits: one provider account can feed several locations; default routes all templates to the activating location; location id must be requested from vendor support; managed from the New UI since 2022-02-17; the admin item is hidden until the vendor enables the module (requested through the Support Center partner form or the account manager; connection said to be possible same day); add-on fee of $10 per month on the platform side on top of the provider's own plan; needs a provider API v4 key, which the provider shows once; match key stated as first name + last name + email; synced profile fields are whatever the waiver collects; a waiver never creates a membership or package; the platform sends no notification on completion; no advanced waiver reporting; positioned for forms needing per-field initials or many distinct waivers.
- User story: As an owner already using Smartwaiver, I want signed waivers to create and update client profiles automatically, so that I do not retype participants.
- Actors: owner/admin, client
- UI generation: both
- Priority: v2-adapter
- Evidence: https://support.ezfacility.com/hc/en-us/articles/4406062265883-Enable-the-Smartwaiver-and-EZFacility-Integration-in-EZFacility-Classic, https://support.ezfacility.com/hc/en-us/articles/4405044160795-Online-Webinar-SmartWaiver-Integration, https://www.ezfacility.com/partners/smartwaiver/, https://www.ezfacility.com/blog/software-release-ezpayments-uk-smartwaiver, https://www.ezfacility.com/blog/ezfacility-saas-partner-deep-dive, https://www.youtube.com/watch?v=jbwkXIo9rY8 (t=04:02), https://www.youtube.com/watch?v=jbwkXIo9rY8 (t=06:05), https://www.youtube.com/watch?v=jbwkXIo9rY8 (t=09:10), https://www.youtube.com/watch?v=jbwkXIo9rY8 (t=12:14), https://www.youtube.com/watch?v=zzEUXdDPMyU (t=22:45), https://www.youtube.com/watch?v=zzEUXdDPMyU (t=27:53)

### DOC-14 Self-service terms and conditions acknowledgment
- Sub-features: force a portal user to accept terms or a rental agreement at purchase; evidenced for rental plans with first-purchase vs every-purchase frequency; the acknowledgment text is either an existing document template or custom text; it is the vendor's answer to "no document on a rental".
- Settings / options: acknowledgment frequency: first purchase, every purchase (rental plans); wider scope unknown; configured under Administration > Self-Service > Design; source: existing document or custom text.
- Rules / limits: help-article body still not read; the rental-plans training video confirms first-purchase vs every-purchase frequency and the document-or-custom-text source; scope beyond rental plans not demonstrated.
- User story: As an owner, I want portal buyers to acknowledge terms before paying, so that policies are accepted without a full waiver.
- Actors: owner/admin, client
- UI generation: New
- Priority: P1
- Evidence: https://support.ezfacility.com/hc/en-us/articles/54599987433883-Self-Service-Terms-Conditions-Acknowledgment (title only, body not read), https://www.ezfacility.com/blog/introducing-rental-plans-prepaid-rentals-made-simple, https://www.youtube.com/watch?v=ERaBaf5YWHo (t=26:35)

### DOC-15 Client waiver-signed indicator
- Sub-features: single waiver checkbox on the client profile; set automatically when the client accepts the group document during online group registration; set automatically by an active Smartwaiver waiver and cleared automatically once every such waiver has expired; staff can tick it by hand; surfaced as a green check in the client-list waiver column, on the check-in card, and as a quick check in schedule, reservation and group-registration views.
- Settings / options: waiver (bool) on the client; no configuration described.
- Rules / limits: one flag per client, not per document or per activity; stays set while any provider waiver is active; accepting a membership or package document never sets it; native documents carry no expiry, so only provider waivers ever clear it automatically.
- User story: As front-desk staff, I want an at-a-glance signal that a client has a waiver on file, so that I can stop unsigned participants at check-in or booking.
- Actors: front desk, coach/trainer, client (indirectly, by signing)
- UI generation: both
- Priority: P0
- Evidence: https://www.youtube.com/watch?v=jbwkXIo9rY8 (t=13:14), https://www.youtube.com/watch?v=VuUR1Y9bhjQ (t=38:58), https://www.youtube.com/watch?v=KAN6h9vPUiM (t=35:00), https://www.youtube.com/watch?v=TWNQ4cTiEFs (t=16:30), https://www.youtube.com/watch?v=zzEUXdDPMyU (t=18:38)

## Fitness Assessments

### FIT-01 Assessment categories and fields (configuration)
- Sub-features: tenant-defined categories; numeric fields assigned to a category; rename and delete for both.
- Settings / options: Category name; Field name; decimal places; owning Category.
- Rules / limits: a field belongs to exactly one category (inferred); numeric only, no units, formulas, or text/choice fields described; effect of deleting a field on history not described.
- User story: As a head trainer, I want to define what we measure, so that every trainer records the same metrics.
- Actors: owner/admin
- UI generation: Classic (no New-UI article found)
- Priority: P0
- Evidence: https://support.ezfacility.com/hc/en-us/articles/4404308492315-Setting-Up-Your-Assessment-Categories, https://www.ezfacility.com/features/member-engagement

### FIT-02 Record assessment values on a client
- Sub-features: Assessment tab on the profile; one entry = a date/time plus values for any subset of fields; latest values shown by default.
- Settings / options: Assessment Date and Time; value per field.
- Rules / limits: entries are editable and deletable; no recording-trainer attribution described.
- User story: As a trainer, I want to log a client's measurements at each review, so that progress is tracked over time.
- Actors: trainer, front desk
- UI generation: Classic
- Priority: P0
- Evidence: https://support.ezfacility.com/hc/en-us/articles/4404314819483-Adding-an-Assessment-in-EZFacility-Classic, https://support.ezfacility.com/hc/en-us/articles/4404308492315-Setting-Up-Your-Assessment-Categories, https://www.ezfacility.com/industries/personal-trainer-software

### FIT-03 Assessment history and per-client report
- Sub-features: History list of all entries with edit/delete; Report view filtered by date range; print and export.
- Settings / options: report date range; Generate Report.
- Rules / limits: none stated.
- User story: As a trainer, I want a printable progress report for a client, so that I can review results with them.
- Actors: trainer, client (recipient)
- UI generation: Classic
- Priority: P0
- Evidence: https://support.ezfacility.com/hc/en-us/articles/4404314819483-Adding-an-Assessment-in-EZFacility-Classic, https://support.ezfacility.com/hc/en-us/articles/4404308492315-Setting-Up-Your-Assessment-Categories

### FIT-04 Assessment Summary report (cohort change between two dates)
- Sub-features: compares assessment values at a start and end date across clients; per-field Client Count, At Start, At End; export (CSV headers fixed 2023-09-27).
- Settings / options: Compare values on this date; to this date; Maximum age of values (days).
- Rules / limits: a client whose latest value before the start date is older than the max-age window is excluded; aggregation function (sum vs mean) not stated.
- User story: As an owner, I want to see how the membership base changed on each metric over a period, so that I can demonstrate programme outcomes.
- Actors: owner/admin, trainer
- UI generation: Classic (listed among membership reports in both)
- Priority: P1
- Evidence: https://support.ezfacility.com/hc/en-us/articles/4404308386075-Assessment-Summary-Report, https://support.ezfacility.com/hc/en-us/articles/19132331777307-September-27th-2023-Release-Notes

### FIT-05 Client-facing progress sharing
- Sub-features: marketing states that stats and personal bests can be shared via reports and the client portal; the only demonstrated member-facing fitness data comes from a partner product (Trainingym): body-composition results, fitness tests and progress history in the partner's member app, with fitness reports printable to PDF or emailed to the member; the platform's part is passing new contract-signing clients to the partner.
- Settings / options: unknown.
- Rules / limits: no help-center article shows assessments in self-service; treat as claim.
- User story: As a member, I want to see my own results and bests, so that I stay motivated.
- Actors: client, trainer
- UI generation: unknown
- Priority: P1
- Evidence: https://www.ezfacility.com/features/member-engagement, https://www.ezfacility.com/industries/gym-management-software, https://www.youtube.com/watch?v=6GY9mk7HOkw (t=35:44), https://www.youtube.com/watch?v=6GY9mk7HOkw (t=08:09)

Conventions: "Classic" / "New" = the two UI generations of the reference product. "(inferred)" = not stated outright in a source. Billing, invoices, refunds, coupons, documents/e-sign, check-in and self-service are owned by other clusters; they appear here only where a membership/package rule depends on them.

## Memberships

### MEM-01 Membership type catalogue
- Sub-features: create / rename / delete types; manual ordering (arrow buttons in Classic, drag handle in New); "save and add another" (New); inline creation of a missing type from the plan wizard (New).
- Settings / options: name; revenue category (single pick in the articles; a 2025 fix note speaks of "revenue categories" on a type, plural); sort order.
- Rules / limits: a type must exist before any plan, simple membership, or client import carrying memberships; type is the grouping dimension exposed to membership reports; revenue category is expected even for tenants that do not tax; new entries land at the top of the list (New). Vendor training advises modelling day, week, month and year passes as membership plans, not packages, so the pass history stays on the membership tab.
- User story: As an admin, I want a short list of membership types mapped to revenue categories, so that plans and reports group consistently and revenue posts to the right ledger bucket.
- Actors: owner/admin.
- UI generation: both (same capability; only list controls differ).
- Priority: P0
- Evidence: https://support.ezfacility.com/hc/en-us/articles/29852362973211-Creating-Membership-Types-in-EZFacility-Classic, https://support.ezfacility.com/hc/en-us/articles/22758625268379-Creating-Membership-Types-in-New-EZFacility-Experience, https://support.ezfacility.com/hc/en-us/articles/36516560976539-April-9th-2025-Release-Notes, https://www.youtube.com/watch?v=a7-8-cHwB8Y (t=47:06)

### MEM-02 Membership plan templates ("advanced" plans)
- Sub-features: create plan (New: tabbed wizard Plan Details > Billing > Prorate > Add-Ons > Summary; Classic: single form plus later Prorate tab); edit; duplicate (copy icon, or "save and add new" with a keep-copy checkbox); delete; reorder; plan-chaining for promos (intro plan renews into full-price plan); annual price update procedure; tiered plans by audience (individual, family, student, corporate are marketing examples, modelled as ordinary plans).
- Settings / options: Type (MEM-01); Description; Start Date (optional fixed calendar date); billing cadence "Bill Every"/"Billed" (monthly, yearly named; other units implied by "etc."); number of billings "Bill How Many Times"/"Duration"; Auto-Renew lead time (number + unit, e.g. 1 day; blank = never renews); "Contracts renew as" = copy of itself (default) or a named plan (may be the same plan by name); Default Document (New only); Max Visits; Initiation Fee; Fee Billed Each Term; Payments Due On (day); Discount (New); Revenue Category (New); Default Invoice Option = No Default / Multiple Invoices / Single Invoice (New); Auto-Pay default Yes/No (New); Additional Description (New); Sell Online Yes/No; sort order. Additional Description is capped at 100 characters and prints on the client invoice (video).
- Rules / limits: contract length = cadence x count (yearly x1 = one year paid in full; monthly x12 = one year monthly); a fixed Start Date forces every contract sold from the plan to start that day; initiation fee is added to the first invoice only; Payments Due On doubles as the auto-pay charge day; plan edits affect only purchases and renewals made afterwards; contracts set to renew as a copy keep their originally sold price, so a plan price change does not reach them; the renews-as picker only lists a plan after it has been saved and the screen re-entered (their quirk, not a rule to copy); newest plan listed first by default. On a price increase the operator chooses between leaving existing contracts at the old price and repricing them; the system sends clients no notice of a price change, and reports keep showing what was actually paid at the time (video).
- User story: As an admin, I want reusable plan templates that fix cadence, term count, fees, renewal target and visit limits, so that staff and the portal sell consistent contracts without re-keying terms.
- Actors: owner/admin.
- UI generation: both (New adds Default Document, Discount, Revenue Category, Default Invoice Option, Auto-Pay default, Additional Description, copy action; Classic exposes the core fields only).
- Priority: P0
- Evidence: https://support.ezfacility.com/hc/en-us/articles/29794984963099-Setting-Up-Membership-Plans-in-EZFacility-Classic, https://support.ezfacility.com/hc/en-us/articles/4402058520603-How-to-add-Membership-Plans, https://support.ezfacility.com/hc/en-us/articles/4402427197467-How-to-Edit-Membership-Plans, https://support.ezfacility.com/hc/en-us/articles/20482279207963-Chalk-Talk-November-2023-Updating-Membership-Pricing, https://support.ezfacility.com/hc/en-us/articles/29852167415195-Allowing-Memberships-to-be-Sold-Online-in-EZFacility-Classic, https://support.ezfacility.com/hc/en-us/articles/16846068050715-July-3rd-2023-Release-Notes, https://support.ezfacility.com/hc/en-us/articles/19847009538203-October-25th-2023-Release-Notes, https://www.ezfacility.com/features/billing-payments, https://www.ezfacility.com/industries/gym-management-software, https://www.ezfacility.com/industries/yoga-and-pilates-studio-management-software, https://www.ezfacility.com/industries/shooting-range-gun-club-software, https://www.ezfacility.com/blog/make-the-most-of-ezfacility-management-software-features, https://www.youtube.com/watch?v=TWNQ4cTiEFs (t=14:27), https://www.youtube.com/watch?v=KAN6h9vPUiM (t=49:24)

### MEM-03 Plan proration rules
- Sub-features: plan-level proration mode; per-sale proration choice when the plan delegates it; per-sale override of the plan's proration from the admin-side sale.
- Settings / options: mode = None (default) / Prorate-to-first-of-next-month, with tail behaviour one of {extend last term until a full billing month exists; drop the last term that is not a full billing month; prorate the final term too} / Custom (seller decides at sale; Classic shows a "prorate this membership" checkbox on the contract). At the payment step of a prorated mid-month sale staff pick what to collect now: the prorated part only (labelled "amount due") or the prorated part plus the first full month (labelled "client total") (video).
- Rules / limits: every prorated contract moves subsequent billing to the 1st of the following month at the full periodic rate; plan must be saved before proration can be configured (Classic); under Custom, nothing is prorated unless the seller ticks it on each contract. Proration arithmetic (day basis, rounding) is not documented. Proration exists for memberships only: groups never prorate and any other item is prorated by hand; a plan without proration bills on the same day of each month as the sale (video).
- User story: As an admin, I want mid-month joiners billed a partial first period and then aligned to the 1st, so that all dues run on one billing day.
- Actors: owner/admin (configure); front desk/sales (choose at sale).
- UI generation: both (identical option set).
- Priority: P1
- Evidence: https://support.ezfacility.com/hc/en-us/articles/29796200065179-Prorating-Membership-Plans-in-EZFacility-Classic, https://support.ezfacility.com/hc/en-us/articles/4402427196571-How-to-Prorate-Membership-Plans, https://support.ezfacility.com/hc/en-us/articles/4401990058523-How-to-Sell-a-Membership-from-Administration, https://support.ezfacility.com/hc/en-us/articles/4402058520603-How-to-add-Membership-Plans, https://www.youtube.com/watch?v=a7-8-cHwB8Y (t=34:50), https://www.youtube.com/watch?v=KAN6h9vPUiM (t=10:16, t=30:52)

### MEM-04 Plan add-ons (bundled packages and pre-defined items)
- Sub-features: attach one or more package plans and/or pre-defined billable items to a membership plan; add/remove add-ons per sale; listing of attached add-ons on the plan.
- Settings / options: add-on reference (package plan or pre-defined item); no quantity or price override documented.
- Rules / limits: the package plan / item must pre-exist; a bundled package is granted at no charge when the contract is first created; on membership auto-renewal the package is only re-granted if the package plan itself auto-renews with matching lead time, and a priced package is then invoiced at its own price (free only at first sale); cancelling the membership does not cancel the bundled package in New (Classic's cancel dialog offers to cancel attached package plans on the same date); a contract sold with a package add-on must show active the same day (2024 fix). A New-UI training demo contradicts the New article: cancelling a membership with a connected add-on package asks whether to delete that package too, and only the package tied to the contract is affected, never packages bought separately (see unknowns, conflict). Package plans themselves cannot carry add-ons.
- User story: As an admin, I want a membership to include session packs or fixed extras, so that a single sale grants both access and credits.
- Actors: owner/admin; front desk (per-sale edit).
- UI generation: New (Add-Ons tab); Classic evidence limited to the cancel dialog.
- Priority: P1
- Evidence: https://support.ezfacility.com/hc/en-us/articles/23397491696795-Adding-a-Package-or-Add-On-to-a-Membership-Plan, https://support.ezfacility.com/hc/en-us/articles/4402058520603-How-to-add-Membership-Plans, https://support.ezfacility.com/hc/en-us/articles/4401990058523-How-to-Sell-a-Membership-from-Administration, https://support.ezfacility.com/hc/en-us/articles/4404308377243-Canceling-a-Membership-with-a-Refund-in-EZFacility-Classic, https://support.ezfacility.com/hc/en-us/articles/22122496577179-January-17th-2024-Release-Notes, https://www.youtube.com/watch?v=a7-8-cHwB8Y (t=06:13, t=11:18), https://www.youtube.com/watch?v=TWNQ4cTiEFs (t=35:04)

### MEM-05 Membership preferences (tenant-level switches)
- Sub-features: mandatory-remark policy for status changes; membership-number auto-generation switch; payment-method capture policy during contract creation.
- Settings / options: "require remark" for Freeze / Suspend / Cancel (described as one requirement covering the three actions; per-action granularity not confirmed); auto-generate membership numbers on/off; payment-method section mode, mutually exclusive = hidden / shown-optional / shown-required (card or direct debit).
- Rules / limits: number auto-generation fires at client creation and/or membership purchase and should be off when numbers are assigned by hand (pre-printed tags); the remark policy is what makes the Remarks field compulsory in the freeze, suspend and cancel dialogs.
- User story: As an owner, I want to force a reason on every freeze, suspension and cancellation and to require a payment method at sign-up, so that retention data and autopay coverage are complete.
- Actors: owner/admin.
- UI generation: Classic article; the same policies are referenced by New-UI freeze/cancel articles.
- Priority: P0
- Evidence: https://support.ezfacility.com/hc/en-us/articles/29852095095067-Setting-Up-Membership-Preferences-in-EZFacility-Classic, https://support.ezfacility.com/hc/en-us/articles/4404308183707-Canceling-a-Membership-in-EZFacility-Classic, https://support.ezfacility.com/hc/en-us/articles/4404308377243-Canceling-a-Membership-with-a-Refund-in-EZFacility-Classic, https://support.ezfacility.com/hc/en-us/articles/4404314520475-Freezing-a-Membership-in-EZFacility-Classic, https://support.ezfacility.com/hc/en-us/articles/6740429102747-How-to-Freeze-a-Membership-in-EZFacility, https://support.ezfacility.com/hc/en-us/articles/4404308093211-Selling-an-Advanced-Membership-Contract-in-EZFacility-Classic

### MEM-06 Simple (record-only) membership
- Sub-features: mark a client as a member directly on the profile with type, dates and a number, without contract or billing; generate or scan the number; coexists with advanced contracts.
- Settings / options: Membership #; Membership Type; Start; Expiration; Membership Fee (memo); Initiation Fee (memo); payment details (memo); Notes.
- Rules / limits: produces no billing items or invoices and cannot be charged through the system; intended for free memberships or dues tracked elsewhere; a membership number can exist without any membership; door/check-in access rules still key off it; a client with an expired simple membership but an active advanced contract must count as a member (2024 fix), i.e. member status = OR across both kinds.
- User story: As a front-desk user, I want to flag someone as a member with an expiry date and card number without billing them, so that check-in recognises comp or externally billed members.
- Actors: front desk/staff.
- UI generation: Classic (simple vs advanced distinction still present in 2024 release notes).
- Priority: P2
- Evidence: https://support.ezfacility.com/hc/en-us/articles/29852099999259-Setting-Up-a-Simple-Membership-in-EZFacility-Classic, https://support.ezfacility.com/hc/en-us/articles/22968789591963-February-15th-2024-Release-Notes

### MEM-07 Staff sale of a membership contract
- Sub-features: entry points = client profile (Classic "New Contract"; New "Sell Membership") and Administration > plans > sell; client search / recently viewed / inline new client (tenant-required fields enforced; clients from another location selectable); start from a plan or key terms manually (Classic); per-sale overrides that do not alter the plan; optional payment-method capture; invoice-option choice; pay now or leave an open invoice; sale to an expired/non-renewing member. Fixed-term (non-renewing) contract sold from an ordinary plan by editing details at sale: auto-renew off, duration entered in days, autopay off, so no extra plan or type is needed (video).
- Settings / options: Sold By (salesperson); Referred by (existing client); plan ("Use Plan"); Membership Type; fee per term; Initiation Fee; Bill Every; How Many Times; Start Date; Revenue Date; End Date; Max Visits (blank = unlimited); Payments Due On; Auto-Renew lead (blank = none); renews-as; Discount for Renewals (percent or flat amount, with description and internal remarks); Autopay Yes/No; proration; add-ons; linked waiver/document; "more options" = coupon, additional discount, internal notes, revenue category. Invoice option = Invoice Now {one invoice per billed item / one invoice for everything} / Invoice Later / leave items in cart (Classic); New = pay now / Pay Later. Admin-side review step lists editable: client, sold by, referrals, plan type, description, start date, duration, auto-renew terms, linked waiver, max visits, billing options, cost, auto-pay, pro-rate, add-ons.
- Rules / limits: overrides are a per-contract snapshot (enables one-off concessions such as waiving the initiation fee); Revenue Date defaults to start/due date and is editable only when the term count is 1; editing End Date rewrites cadence to the day count between start and end and sets count to 1; revenue date must be validated, never saved empty (2022 fix); payment-method section visibility follows MEM-05; plan auto-pay default must carry to the payment step and to the resulting invoices (2023 fix); captured card/direct-debit lands in the client's billing profile. A client holds at most one membership at a time (packages are unlimited); a future-dated contract can be sold behind the current one. Editing plan details at sale is gated by a "customize contract" permission that is set per user, not per role; a user without it sees a banner saying contracts can only be created from existing plans (video).
- User story: As a front-desk user, I want to sell a plan to a client in a few steps with optional one-off adjustments, so that the contract, its billing schedule and first payment are created together.
- Actors: front desk, sales, trainer, admin.
- UI generation: both (Classic: two-step contract form + invoice choice; New: guided flow with review, document acceptance and payment steps).
- Priority: P0
- Evidence: https://support.ezfacility.com/hc/en-us/articles/4404308093211-Selling-an-Advanced-Membership-Contract-in-EZFacility-Classic, https://support.ezfacility.com/hc/en-us/articles/4401983374619-How-to-Sell-a-Membership-from-the-Client-Profile, https://support.ezfacility.com/hc/en-us/articles/4401990058523-How-to-Sell-a-Membership-from-Administration, https://support.ezfacility.com/hc/en-us/articles/11297336305691-December-15th-2022-Release-Notes, https://support.ezfacility.com/hc/en-us/articles/19847009538203-October-25th-2023-Release-Notes, https://www.youtube.com/watch?v=KAN6h9vPUiM (t=09:14, t=25:00), https://www.youtube.com/watch?v=iR4MVBspNlQ (t=07:10, t=29:53)

### MEM-08 Contract document acceptance at sale
- Sub-features: default document template per plan; acceptance captured during the sale; signed/accepted copy filed on the client's documents; e-sign prompt when bought online; decline path when sent by email; view accepted text from the client's membership grid.
- Settings / options: acceptance method = Paper Copy (sign on paper, upload) / Digital Copy (tick-box consent) / Digital Signature (drawn with pen or mouse) / Email Document (client completes on own device, can keep or email a copy); plan field Default Document; per-sale "linked waiver" override; Classic counterpart is a single tenant-wide Membership Agreement (other cluster).
- Rules / limits: email method needs a valid email on file; a declined emailed document must still leave the document reachable from the membership grid (2023 fix); the acceptance step must not be skippable on first attempt (2025 fix); per-plan Membership Documents exist only for accounts fully on New.
- User story: As a facility owner, I want every contract sale to capture agreement to the plan's terms by one of several methods, so that I hold enforceable proof per member.
- Actors: front desk; member (signer).
- UI generation: New (Classic uses the Membership Agreement feature documented in the documents cluster).
- Priority: P1
- Evidence: https://support.ezfacility.com/hc/en-us/articles/4401990058523-How-to-Sell-a-Membership-from-Administration, https://support.ezfacility.com/hc/en-us/articles/4401983374619-How-to-Sell-a-Membership-from-the-Client-Profile, https://support.ezfacility.com/hc/en-us/articles/4402058520603-How-to-add-Membership-Plans, https://support.ezfacility.com/hc/en-us/articles/14655161654811-April-18th-2023-Release-Notes, https://support.ezfacility.com/hc/en-us/articles/36516396025115-April-23rd-2025-Release-Notes, https://www.ezfacility.com/blog/software-release-vaccine-passport, https://www.ezfacility.com/blog/software-release-ezpayments-uk-smartwaiver

### MEM-09 Online (self-service) membership sales
- Sub-features: publish selected plans to the member portal; member purchase with document e-sign; guardian purchasing for a related client who has no portal login; coupon applied to the purchase; marketing positions it as website-embedded sign-up. Portal "Buy" menu > Memberships lists only plans flagged for online sale, grouped by membership type in collapsible sections, each row showing term length, quantity, start and end date, auto-renew flag, price and initiation fee; card-on-file capture during checkout; instant email alert to staff when a membership is sold online (alert owned by the notifications cluster) (video).
- Settings / options: plan flag Sell Online Yes/No (the only documented control); plan Default Document drives the e-sign prompt. Self-service card storage for online membership sales: (1) always require and save the card; (2) save the card only when nothing is due at purchase (e.g. plan with a future default start date); option 1 overrides option 2; with neither set the buyer gets a yes/no "save this card for future payments" choice, and a buyer with a stored card chooses between it and a new one. Billing preference "default new membership contracts to autopay" makes every online sale autopay (owned by billing). Agreement step can be switched off, in which case checkout follows plan selection directly (owned by documents) (video).
- Rules / limits: a coupon on an annual plan must update the amount due in the portal checkout (2023 fix); a parent account may buy for a relative lacking a portal registration (2023 fix). Step-by-step portal flow is not in the public articles of this cluster. Start date defaults to the purchase date unless the plan has a fixed start date. Online membership sales shipped on 22 March 2016 and were limited to accounts holding the advanced membership module (video, legacy Classic).
- User story: As a prospective member, I want to buy a plan online and sign its agreement, so that I can join without visiting the desk.
- Actors: member, parent/guardian; admin (publishes plans).
- UI generation: both (flag in both; e-sign prompt New only).
- Priority: P1
- Evidence: https://support.ezfacility.com/hc/en-us/articles/29852167415195-Allowing-Memberships-to-be-Sold-Online-in-EZFacility-Classic, https://support.ezfacility.com/hc/en-us/articles/4402058520603-How-to-add-Membership-Plans, https://support.ezfacility.com/hc/en-us/articles/17574439837467-August-2nd-2023-Release-Notes, https://support.ezfacility.com/hc/en-us/articles/18408526583067-August-31st-2023-Release-Notes, https://www.ezfacility.com/blog/software-release-vaccine-passport, https://www.ezfacility.com/press-news/press-releases/ezfacilitys-memberme-mobile-app-now-available-on-android, https://www.ezfacility.com/features/billing-payments, https://www.ezfacility.com/industries/gym-management-software, https://www.youtube.com/watch?v=SDO3SkkHTlY (t=01:10, t=05:30, t=09:10, t=11:00)

### MEM-10 Contract list, status views and in-place edit on the client profile
- Sub-features: membership tab defaults to the current contract; status filter; side-panel editor (New); status-change history per contract; visit summary per contract; entry point to freeze, suspend, cancel, share, renew.
- Settings / options: filter values across sources = Active/current, Upcoming (already renewed, not yet started), Past/Expired, Cancelled, Frozen, Suspended, All Contracts. Editable post-sale: Sold By; Referred by (must be an existing client); auto-renew timing / disable / renew now; discount applied at auto-renewal; additional description applied at auto-renewal; internal remark applied at auto-renewal; Auto-Pay on/off; Max Visits on an active contract.
- Rules / limits: the eight field edits require an explicit save; freeze/suspend/cancel are separate commands; before any status change staff must check whether the next term has already been generated by auto-renew and act on that pending term too; timestamps (created, visits) are stored in UTC and shown in facility local time without DST drift (2023 fixes). When a contract runs out with auto-renew off the profile reverts to non-member. Future-dated contracts appear only under the "all" filter. There is no bulk edit of a contract's monthly price: each remaining month is edited by hand (video).
- User story: As a front-desk user, I want to see a member's current, future and past contracts and adjust renewal, autopay and visit settings, so that I can service account requests without re-selling.
- Actors: front desk, admin.
- UI generation: both (Classic "View" drop-down; New filter toggle + side panel).
- Priority: P0
- Evidence: https://support.ezfacility.com/hc/en-us/articles/22758476497819-How-to-view-and-edit-Memberships-on-a-Client-Profile-in-New-EZFacility-Experience, https://support.ezfacility.com/hc/en-us/articles/23394858616603-How-to-find-past-current-and-future-Membership-Contracts-on-the-client-profile, https://support.ezfacility.com/hc/en-us/articles/4404308377243-Canceling-a-Membership-with-a-Refund-in-EZFacility-Classic, https://support.ezfacility.com/hc/en-us/articles/16731304236571-June-28th-2023-Release-Notes, https://support.ezfacility.com/hc/en-us/articles/18408526583067-August-31st-2023-Release-Notes, https://www.youtube.com/watch?v=a7-8-cHwB8Y (t=56:22), https://www.youtube.com/watch?v=KAN6h9vPUiM (t=24:37), https://www.youtube.com/watch?v=iR4MVBspNlQ (t=29:53)

### MEM-11 Contract renewal (automatic, manual, plan-switching)
- Sub-features: scheduled auto-renew a configurable lead time before expiry; renewal target = same terms as sold ("copy") or current terms of a named plan; per-contract override of lead time and target; disable auto-renew on one contract; immediate manual renew; renewal-time discount, description and internal remark; contract simply expires when no renewal is set; price-increase procedure via plan edit.
- Settings / options: plan and contract: auto-renew lead (number + unit; blank/disabled = none), renews-as (copy / plan id); contract: renewal discount (percent or flat), renewal additional description, renewal internal remark.
- Rules / limits: renewal creates a new successor contract ("Upcoming") rather than extending the old one (inferred from Upcoming view and pending-term warnings); "copy" freezes price and terms until cancelled or re-pointed manually; a named plan is read at renewal time, so plan price edits flow through; a "copy" selection must persist on the plan (2023 fix); manual renew must be idempotent, a double click once produced duplicate contracts (2023 fix); a suspension fee, if set, becomes the fee when a suspended contract renews (MEM-14); freeze switches auto-renew off (MEM-13); add-on packages renew only under their own auto-renew settings (MEM-04). No upgrade/downgrade command exists: a mid-term plan change is either (a) disable renewal and sell a future-dated contract on the new plan, or (b) cancel to the start date with reason Upgrade/Downgrade and sell a new contract, backdated to the 1st when the billing day should stay there; earlier payments are neither refunded nor deleted by this. Two active contracts cannot coexist, but a pending future-dated one can be queued behind the active one. Disabling auto-renew on a prorated contract leaves it expiring at the end of the first full month (video).
- User story: As an owner, I want contracts to roll over automatically on terms I control, so that dues continue without staff action and price rises reach the right members.
- Actors: system scheduler; admin; front desk.
- UI generation: both.
- Priority: P0
- Evidence: https://support.ezfacility.com/hc/en-us/articles/22758241119899-Membership-Renewal-Process, https://support.ezfacility.com/hc/en-us/articles/29794984963099-Setting-Up-Membership-Plans-in-EZFacility-Classic, https://support.ezfacility.com/hc/en-us/articles/4402058520603-How-to-add-Membership-Plans, https://support.ezfacility.com/hc/en-us/articles/20482279207963-Chalk-Talk-November-2023-Updating-Membership-Pricing, https://support.ezfacility.com/hc/en-us/articles/4404308093211-Selling-an-Advanced-Membership-Contract-in-EZFacility-Classic, https://support.ezfacility.com/hc/en-us/articles/22758476497819-How-to-view-and-edit-Memberships-on-a-Client-Profile-in-New-EZFacility-Experience, https://support.ezfacility.com/hc/en-us/articles/4402434194715-How-to-Suspend-a-Membership, https://support.ezfacility.com/hc/en-us/articles/16846068050715-July-3rd-2023-Release-Notes, https://support.ezfacility.com/hc/en-us/articles/18408526583067-August-31st-2023-Release-Notes, https://www.ezfacility.com/features/billing-payments, https://www.youtube.com/watch?v=a7-8-cHwB8Y (t=49:15), https://www.youtube.com/watch?v=pYlicKb3lng (t=06:00), https://www.youtube.com/watch?v=KAN6h9vPUiM (t=22:33)

### MEM-12 Freeze a contract
- Sub-features: add a freeze with start and optional end; history row per freeze; frozen flag surfaced at check-in and on the client page.
- Settings / options: first day; last day (optional, may be set later, any future date); remarks (optional unless MEM-05 requires).
- Rules / limits: freeze halts all billing for the contract; membership resumes automatically the day after the end date; open-ended freezes allowed; check for an already generated renewal term before freezing; freeze disables Auto-Pay and Auto-Renew on the contract and removes not-yet-due invoices created at sale (see MEM-13). A freeze pushes the contract end date out by the frozen duration (video, stated twice); the invoices the frozen months would have produced stay visible as history but are not billed; no freeze fee exists; there is no bulk "freeze every membership" action, operators are sent to vendor support for that.
- User story: As a front-desk user, I want to pause a member's dues and access for a period, so that they keep their contract through an injury or absence.
- Actors: admin, front desk.
- UI generation: both.
- Priority: P0
- Evidence: https://support.ezfacility.com/hc/en-us/articles/4404314520475-Freezing-a-Membership-in-EZFacility-Classic, https://support.ezfacility.com/hc/en-us/articles/6740429102747-How-to-Freeze-a-Membership-in-EZFacility, https://support.ezfacility.com/hc/en-us/articles/29852095095067-Setting-Up-Membership-Preferences-in-EZFacility-Classic, https://www.youtube.com/watch?v=a7-8-cHwB8Y (t=26:38, t=30:44, t=32:48, t=33:48), https://www.youtube.com/watch?v=KAN6h9vPUiM (t=21:31)

### MEM-13 Edit or remove a freeze and re-bill the remaining term
- Sub-features: set, change or clear the freeze end date; delete the freeze (clear start); re-invoice un-invoiced billing periods after the freeze, either as one invoice or one per period.
- Settings / options: end date set / remove (with confirmation); start remove; remarks; re-billing route A = client billing items list (select periods, "invoice checked" into one invoice, or per-row create for separate invoices); route B = shopping cart (own items vs all users' items; new invoice). New-UI demo: saving a freeze end date prompts for the treatment of the unfrozen items = each item on its own new invoice / all items on one new invoice (one line per month) / leave un-invoiced for now.
- Rules / limits: changing an end date is remove-then-set; after a freeze the remaining periods exist only as un-invoiced billing items and Auto-Pay/Auto-Renew stay off until staff re-invoice and re-enable; the cart route yields a single lump sum due on the earliest period date unless a payment schedule is added by hand, the items route with a single invoice avoids that; for separate invoices, periods are invoiced one at a time; cart "mine" view only shows items owned by the user who created the freeze. Billing restarts on the exact freeze end date: it is not realigned to the 1st even when the contract was prorated to the 1st, nor to the original sale day (video).
- User story: As an admin, I want to end a freeze early and restore the member's remaining billing, so that dues restart on the right dates.
- Actors: admin.
- UI generation: both (same procedure in both).
- Priority: P1
- Evidence: https://support.ezfacility.com/hc/en-us/articles/4404308193435-Removing-a-Freeze-in-EZFacility-Classic, https://support.ezfacility.com/hc/en-us/articles/38623038228763-Removing-a-Freeze-in-EZFacility, https://support.ezfacility.com/hc/en-us/articles/4404308380827-How-to-Edit-or-Add-an-End-Date-for-a-Membership-Freeze-in-EZFacility-Classic, https://www.youtube.com/watch?v=a7-8-cHwB8Y (t=20:29, t=21:31)

### MEM-14 Suspend and unsuspend a contract
- Sub-features: add a suspension with start, optional end and optional fee; set/change the end date later; status-change history; suspended marker at check-in, on the client page and as an icon in member lists.
- Settings / options: first day; last day (optional); suspension fee (optional, membership contracts only); remarks (subject to MEM-05).
- Rules / limits: if the contract is still suspended when it renews, the successor is priced at the suspension fee; target the pending renewed term if one exists; whether normal dues continue during suspension is not stated (contrast with freeze). Video training (two sessions) fills the gap: suspension does not pause billing, normal dues keep running and the suspension fee is charged on top (example: 10 extra); door and check-in access is blocked; end and renewal dates do not move; the contract resumes the day after the suspension end date, or on manual unsuspend when open-ended. This contradicts the fee-as-renewal-price reading above (see unknowns, conflict).
- User story: As an admin, I want to suspend a member (e.g. non-payment or conduct) and optionally charge a reduced holding fee, so that access is blocked without ending the contract.
- Actors: admin.
- UI generation: both.
- Priority: P1
- Evidence: https://support.ezfacility.com/hc/en-us/articles/4404314524571-Suspending-a-Membership-in-EZFacility-Classic, https://support.ezfacility.com/hc/en-us/articles/4402434194715-How-to-Suspend-a-Membership, https://support.ezfacility.com/hc/en-us/articles/4404314514587-Unsuspending-a-Membership-in-EZFacility-Classic, https://support.ezfacility.com/hc/en-us/articles/4402427184283-How-to-Unsuspend-a-Membership, https://www.youtube.com/watch?v=a7-8-cHwB8Y (t=16:24, t=30:44, t=35:43), https://www.youtube.com/watch?v=KAN6h9vPUiM (t=21:31)

### MEM-15 Cancel a contract (reason-coded)
- Sub-features: cancel with effective date, reason and remarks; cancelled view; optional same-date cancel of attached package plans (Classic dialog).
- Settings / options: cancellation date; remarks (MEM-05); reason = Voluntary Cancel / Upgrade / Downgrade / Administrative Error / Other Modification.
- Rules / limits: date must fall inside the contract's active period; cancelling to the start date auto-reverses the contract invoice and moves any payment to the client's on-account credit; Administrative Error excludes the event from membership (attrition) reporting; cancellation is terminal for users (re-sell to reactivate; vendor support can undo); a contract cancelled on its sale date may still read active until the next day; check for a pending renewed term first. Cancelling to any date after the start date ends the contract with no automatic partial refund (video confirms).
- User story: As an admin, I want to end a contract on a chosen date with a coded reason, so that billing stops and churn reporting is accurate.
- Actors: admin.
- UI generation: both.
- Priority: P0
- Evidence: https://support.ezfacility.com/hc/en-us/articles/4404308183707-Canceling-a-Membership-in-EZFacility-Classic, https://support.ezfacility.com/hc/en-us/articles/4402434198555-How-to-Cancel-a-Membership, https://support.ezfacility.com/hc/en-us/articles/4404308377243-Canceling-a-Membership-with-a-Refund-in-EZFacility-Classic, https://support.ezfacility.com/hc/en-us/articles/29852095095067-Setting-Up-Membership-Preferences-in-EZFacility-Classic, https://www.youtube.com/watch?v=KAN6h9vPUiM (t=22:33), https://www.youtube.com/watch?v=a7-8-cHwB8Y (t=05:12)

### MEM-16 Cancel with full or partial refund
- Sub-features: full refund = cancel back to start date, auto-reversal, refund from on-account balance; partial refund = cancel to a later date, then discount or reverse specific invoice items to create on-account credit, then refund; refund a specific payment while leaving the item owed (via its receipt); external (bookkeeping-only) refund for non-integrated gateways; statement print option. Trainer-recommended "cancel without refund" path: do not cancel, set auto-renew to disabled so the contract runs to the end of its paid term; an already open next-period invoice stays owed unless staff reverse it (video).
- Settings / options: refund form = client to refund; issue date (editable for reporting); amount; original payment method (display); refund method; original card vs different card (on file or keyed); memo; print statement. Classic: "refund all" with prefilled amount, partial by entering a smaller negative amount, method must match original.
- Rules / limits: integrated card refunds only on the vendor's supported processors, otherwise record an external refund and refund in the gateway portal; direct-debit (ACH/EFT) refunds are always manual; if cancelled to any date other than start, the invoice stays and must be adjusted by hand; settlement time quoted as about 5 business days (New) vs 7 to 10 (Classic); fall back to a different card if the original fails.
- User story: As an admin, I want cancelling a membership to produce the correct credit and let me refund all or part of it to the member, so that I don't have to rebuild invoices manually.
- Actors: admin, front desk (with refund permission).
- UI generation: both (New has explicit full vs partial procedures and original/different card choice).
- Priority: P1
- Evidence: https://support.ezfacility.com/hc/en-us/articles/4404308377243-Canceling-a-Membership-with-a-Refund-in-EZFacility-Classic, https://support.ezfacility.com/hc/en-us/articles/17764248824987-How-to-Cancel-Membership-and-Refund-the-Client-Full-Partial-in-EZFacility, https://support.ezfacility.com/hc/en-us/articles/4402434198555-How-to-Cancel-a-Membership, https://www.youtube.com/watch?v=a7-8-cHwB8Y (t=08:16, t=12:20)

### MEM-17 Shared membership (one contract, several clients)
- Sub-features: share a contract with clients linked by a preset relationship (tick list) or with any other client found by search; share count shown on the owner's contract; API exposure of the owning contract, owner and member count.
- Settings / options: per-contract list of additional covered clients; no per-person price or role documented.
- Rules / limits: one billed owner, N covered clients (inferred from API fields: current contract id, owning client id, total client count, total billed amount); contract status endpoints include shared contracts; merging clients can leave one person with multiple active memberships (warning on merge). The person added must already have a client profile (and relationship); vendor guidance is to sell a child's membership on the child's own profile with the parent's billing details and to share only when several people really use one contract (video).
- User story: As a front-desk user, I want to extend one contract to family members, so that a household is billed once and everyone checks in as a member.
- Actors: front desk, admin.
- UI generation: Classic article; behaviour confirmed current by 2024 API release notes.
- Priority: P1
- Evidence: https://support.ezfacility.com/hc/en-us/articles/4404308188315-Sharing-a-Membership-in-EZFacility-Classic, https://support.ezfacility.com/hc/en-us/articles/23807158781211-March-14th-2024-Release-Notes, https://support.ezfacility.com/hc/en-us/articles/25134483797531-April-24th-2024-Release-Notes, https://www.youtube.com/watch?v=KAN6h9vPUiM (t=09:14-17:24)

### MEM-18 Member-initiated auto-renew opt-out ("click to cancel")
- Sub-features: portal button to switch off renewals on a membership, package or prepaid item; visible "auto-renew disabled" state; success confirmation.
- Settings / options: none documented tenant-side; per-subscription auto-renew flag.
- Rules / limits: applies to eligible items bought online; access continues to the end of the paid term, nothing is refunded or terminated early; one-way from the member's side as documented. Members cannot cancel, freeze, suspend or manually renew a contract in the portal; portal membership actions are purchase, viewing the membership number and (since the click-to-cancel release) switching off auto-renew; buying again after expiry is an ordinary new purchase (video; see unknowns).
- User story: As a member, I want to stop future renewals myself in one click, so that I am not billed again but keep what I paid for.
- Actors: member.
- UI generation: New (self-service).
- Priority: P1
- Evidence: https://support.ezfacility.com/hc/en-us/articles/37195623250587-Click-to-Disable-Auto-Renew-Memberships, https://support.ezfacility.com/hc/en-us/articles/37195953487515-What-is-the-Click-to-Cancel-feature (title only, body not read), https://www.youtube.com/watch?v=a7-8-cHwB8Y (t=45:04), https://www.youtube.com/watch?v=5sm7eWzaQD4 (t=63:33)

### MEM-19 Membership number and member card identity
- Sub-features: membership number per client; auto-generate or manual entry; generate/save control on the profile; scan a pre-printed key tag barcode into the field; alphanumeric values; ID card generation from the number; lookup by number across locations via API; physical plastic/RFID cards (hardware).
- Settings / options: auto-generate on/off (MEM-05); number value (free text, letters allowed).
- Rules / limits: a number may exist without a membership; letters must not break ID-card generation (2022 fix); API search by membership number spans all locations the key can access (2025). Reported gap: the number is cut off on the New profile at some widths and is not a column in the client list (video, request logged with the vendor).
- User story: As a front-desk user, I want each member to carry a unique number that a scanner can read, so that check-in is one scan.
- Actors: front desk, admin; system.
- UI generation: both.
- Priority: P0 (number, QR/barcode); RFID and card-printer integration v2-adapter
- Evidence: https://support.ezfacility.com/hc/en-us/articles/29852095095067-Setting-Up-Membership-Preferences-in-EZFacility-Classic, https://support.ezfacility.com/hc/en-us/articles/29852099999259-Setting-Up-a-Simple-Membership-in-EZFacility-Classic, https://support.ezfacility.com/hc/en-us/articles/11297336305691-December-15th-2022-Release-Notes, https://support.ezfacility.com/hc/en-us/articles/18408526583067-August-31st-2023-Release-Notes, https://support.ezfacility.com/hc/en-us/articles/36516560976539-April-9th-2025-Release-Notes, https://www.ezfacility.com/features/billing-payments, https://www.ezfacility.com/blog/make-the-most-of-ezfacility-management-software-features, https://www.youtube.com/watch?v=a7-8-cHwB8Y (t=55:22)

### MEM-20 Visit limits and visit counting
- Sub-features: per-term visit cap on plan and contract; visit summary on the contract; "depleted" alert at check-in; optional one-entry-per-day access rule for visit-limited memberships; "Over Daily Limit" self-check-in alert.
- Settings / options: Max Visits (integer; blank = unlimited), editable on an active contract; access-control rule "deny if today's entry already used" on/off; self-check-in alert "Over Daily Limit" on/off.
- Rules / limits: cap counts check-ins within the term; the daily rule applies only to visit-limited, active contracts and a day is midnight to midnight in the location's time zone; alert and rule are independent, with the alert alone the check-in still succeeds and consumes a visit; Over Daily Limit has the lowest priority among membership alerts (shown only if no other applies, including depleted).
- User story: As an owner, I want to sell limited-visit memberships (e.g. 8 visits a month) and have check-in enforce them, so that members cannot exceed what they bought.
- Actors: admin (configure); check-in system; front desk.
- UI generation: both (daily rule added Feb 2024).
- Priority: P0 (cap + counter); P1 for the daily rule and alert priority
- Evidence: https://support.ezfacility.com/hc/en-us/articles/29794984963099-Setting-Up-Membership-Plans-in-EZFacility-Classic, https://support.ezfacility.com/hc/en-us/articles/4402058520603-How-to-add-Membership-Plans, https://support.ezfacility.com/hc/en-us/articles/4404308093211-Selling-an-Advanced-Membership-Contract-in-EZFacility-Classic, https://support.ezfacility.com/hc/en-us/articles/22758476497819-How-to-view-and-edit-Memberships-on-a-Client-Profile-in-New-EZFacility-Experience, https://support.ezfacility.com/hc/en-us/articles/23328878237467-February-28th-2024-Release-Notes, https://support.ezfacility.com/hc/en-us/articles/18408526583067-August-31st-2023-Release-Notes

### MEM-21 Membership revenue and lifecycle reports
- Sub-features: deferred (unearned) membership revenue by contract; report names referenced by release notes for this module: Membership Revenue by Month, Un-accrued Membership Revenue, Membership Attrition, Membership Overview, Memberships by Status, Membership Actions, Membership Ending Actions, Expiring Memberships, New Memberships, Low-usage check-in (bodies of those belong to the reporting cluster).
- Settings / options: deferred report inputs = liable contracts only Yes/No; contract start date range; include deleted clients. Columns = member id, name, start date, contract length, total billed (initiation + term items), total paid, recognized, remaining, recognized this month. Other reports: multi-select membership-type filter; CSV export.
- Rules / limits: recognized = payments applied to items whose revenue date is today or earlier; remaining = total paid minus recognized; "liable" = contracts holding payments applied to future-dated items; with the filter off both liable and non-liable contracts are returned (2023 fix).
- User story: As an owner, I want to see how much prepaid dues are still unearned per contract, so that my books carry the right liability.
- Actors: owner, bookkeeper.
- UI generation: both.
- Priority: P1
- Evidence: https://support.ezfacility.com/hc/en-us/articles/4403486305051-Deferred-Membership-Revenue-Report, https://support.ezfacility.com/hc/en-us/articles/16731304236571-June-28th-2023-Release-Notes, https://support.ezfacility.com/hc/en-us/articles/17981009155995-August-16th-2023-Release-Notes, https://support.ezfacility.com/hc/en-us/articles/19132331777307-September-27th-2023-Release-Notes, https://support.ezfacility.com/hc/en-us/articles/22968789591963-February-15th-2024-Release-Notes, https://support.ezfacility.com/hc/en-us/articles/26498179644187-June-5th-2024-Release-Notes, https://support.ezfacility.com/hc/en-us/articles/34155834657819-July-3rd-2024-Release-Notes

### MEM-22 Membership data in the public API
- Sub-features: client resource carries earliest membership start and latest membership end; current contract id, owning client id, covered-client count and total billed amount; endpoints returning status and dates for one contract and for all contracts of a client (shared included); search by membership number across locations.
- Settings / options: read-only fields named above.
- Rules / limits: membership date fields populate only for clients with a membership; shared contracts resolve to the owner's contract.
- User story: As an integrator, I want to read a client's membership status and dates, so that external systems (apps, access devices) can gate on membership.
- Actors: API consumer.
- UI generation: n/a (API).
- Priority: P1
- Evidence: https://support.ezfacility.com/hc/en-us/articles/17981009155995-August-16th-2023-Release-Notes, https://support.ezfacility.com/hc/en-us/articles/23807158781211-March-14th-2024-Release-Notes, https://support.ezfacility.com/hc/en-us/articles/25134483797531-April-24th-2024-Release-Notes, https://support.ezfacility.com/hc/en-us/articles/36516560976539-April-9th-2025-Release-Notes

### MEM-23 Membership onboarding checklist
- Sub-features: a setup checklist for the membership area (and one for groups), known from an article title only.
- Settings / options: unknown.
- Rules / limits: unknown; see unknowns file.
- User story: As a new tenant admin, I want a guided checklist of membership setup steps, so that I configure types, plans and preferences in a workable order (inferred).
- Actors: owner/admin (inferred).
- UI generation: unknown (article dated 2026, likely New).
- Priority: P2
- Evidence: https://support.ezfacility.com/hc/en-us/articles/52230184836379-Onboarding-Checklist-Membership-Checklist-Groups-Checklist (title only, body not read)

## Packages & Sessions

### PKG-01 Package plan definition (individual, session-counted)
- Sub-features: wizard (details > billing > summary); bound to one reservation type; session mode single / fixed multiple / buyer-chosen quantity within a range / unlimited; per-session or per-package pricing; default invoice behaviour; default auto-pay; discount; internal vs customer-facing descriptions; edit, list all plans.
- Settings / options: Package Type = Individual (vs Recurring, PKG-03); Reservation Type; Description; Sessions = Single / Multiple (count) / Multiple with Min and Max / Unlimited; Category = Paid / Free; Fee; fee basis = Per Session / Per Package; Default Invoice Option = No Default / Single Invoice / Leave items in cart; Auto-Pay default Yes/No; Sell Online; Discount; Revenue Category; Additional Description; Internal Remarks; Default Document (New); Renewal Threshold, validity, auto-renew and Share With covered in PKG-04/05/06.
- Rules / limits: reservation type must pre-exist; single-session mode forces per-session pricing; for buyer-chosen quantity Min should be 1 and Max is free; the range variant does not show a default invoice option in the Classic text (inferred not offered); all plans must be reachable from the plan list regardless of count (2024 fix). Package plans cannot carry add-ons in New; add-ons exist only on membership plans (video).
- User story: As an admin, I want to define session packs (1, N, pick-your-quantity, unlimited) per service type with a price rule, so that staff and members buy credits that the schedule can redeem.
- Actors: owner/admin.
- UI generation: both (same wizard; New adds Default Document and Is Comp flag).
- Priority: P0
- Evidence: https://support.ezfacility.com/hc/en-us/articles/29784117801755-How-to-Set-Up-Single-Session-Package-Plans-in-EZFacility-Classic, https://support.ezfacility.com/hc/en-us/articles/29784038483867-How-to-Set-Up-Multiple-Session-Package-Plans-in-EZFacility-Classic, https://support.ezfacility.com/hc/en-us/articles/29784160666267-How-to-Set-Up-Unlimited-Package-Plans-in-EZFacility-Classic, https://support.ezfacility.com/hc/en-us/articles/4402427204379-Setting-Up-Package-Plans-Single-Session, https://support.ezfacility.com/hc/en-us/articles/4402427205147-Setting-Up-a-Multiple-Session-Package-Plan, https://support.ezfacility.com/hc/en-us/articles/4402427206683-Setting-Up-an-Unlimited-Package-Plan, https://support.ezfacility.com/hc/en-us/articles/23573413327643-Setting-up-Auto-Renew-for-an-Individual-Package, https://support.ezfacility.com/hc/en-us/articles/4404308415899-How-to-Share-Packages-Automatically-in-EZFacility-Classic, https://support.ezfacility.com/hc/en-us/articles/22122496577179-January-17th-2024-Release-Notes, https://www.ezfacility.com/blog/the-top-5-advantages-of-gun-range-management-software, https://www.youtube.com/watch?v=Rjy8ZpfIA68, https://www.ezfacility.com/features/billing-payments, https://www.ezfacility.com/industries/baseball-facility-software, https://www.youtube.com/watch?v=TWNQ4cTiEFs (t=35:04)

### PKG-02 Free and complimentary package plans
- Sub-features: zero-price plans via Category = Free (any session mode); separate "comp" marker for reporting.
- Settings / options: Category = Free; under Free the billing step shows only Sell Online, Additional Description, Internal Remarks; Is Comp Package flag (New; reporting only, no billing effect).
- Rules / limits: Free removes fee, invoice-option, auto-pay, discount and revenue-category inputs (inferred from the reduced field list); a paid plan can still be flagged comp.
- User story: As an admin, I want free trial or comp session plans that create credits without an invoice, so that trials are tracked like any other package.
- Actors: owner/admin.
- UI generation: both.
- Priority: P1
- Evidence: https://support.ezfacility.com/hc/en-us/articles/29784674271131-How-to-Set-Up-Complimentary-Sessions-in-EZFacility-Classic, https://support.ezfacility.com/hc/en-us/articles/4402434205851-Setting-up-a-Free-Package-Plan, https://support.ezfacility.com/hc/en-us/articles/23573413327643-Setting-up-Auto-Renew-for-an-Individual-Package

### PKG-03 Recurring package plans
- Sub-features: package that repeats on a calendar pattern (e.g. N sessions every month); four-step wizard adding a recurrence step; fixed number of occurrences; auto-renew of the series; renew as itself or another plan; one-invoice-per-occurrence option.
- Settings / options: Package Type = Recurring; Sessions = Single / Multiple / Unlimited (per occurrence); Booking Out of Range = Allow / Disallow; Recurrence Pattern = Daily / Weekly / Monthly / Yearly; every N units (N x unit = length of each package period); End After N Occurrences; Auto-Renew Yes/No; renews as = copy of itself / existing plan; Default Invoice Option = No Default / Single Invoice / Multiple Invoices / Leave items in cart; remaining billing fields as PKG-01.
- Rules / limits: occurrences setting creates that many consecutive package periods; Booking Out of Range decides whether sessions dated after a period's end may still be booked against it.
- User story: As an admin, I want a "4 sessions per month for 6 months" product, so that credits refresh each period and are billed per period.
- Actors: owner/admin.
- UI generation: both (identical options).
- Priority: P1
- Evidence: https://support.ezfacility.com/hc/en-us/articles/29784623019035-How-to-Set-Up-Package-Recurring-Plans-in-EZFacility-Classic, https://support.ezfacility.com/hc/en-us/articles/4402427214107-Setting-Up-a-Recurring-Package-Plans

### PKG-04 Package validity window and expiry
- Sub-features: start date fixed or defaulted to sale date; length from start; computed end date; policy for booking beyond the end date; expiry tracking surfaced to staff and members.
- Settings / options: Start Date (fixed) or "default to the sale date" checkbox; Package Length (duration); End Date (derived); Booking Out of Range = Allow / Disallow.
- Rules / limits: Disallow blocks using/booking sessions after the end date; Allow lets leftover sessions be consumed after expiry; for recurring plans the period length comes from the recurrence step.
- User story: As an admin, I want a 10-pack that expires six months after purchase, so that unused credits do not remain a liability forever.
- Actors: owner/admin.
- UI generation: both.
- Priority: P0
- Evidence: https://support.ezfacility.com/hc/en-us/articles/34440097348379-Creating-a-Package-with-an-Expiration-Date-in-EZFacility-Classic, https://support.ezfacility.com/hc/en-us/articles/23573413327643-Setting-up-Auto-Renew-for-an-Individual-Package, https://support.ezfacility.com/hc/en-us/articles/29784623019035-How-to-Set-Up-Package-Recurring-Plans-in-EZFacility-Classic, https://support.ezfacility.com/hc/en-us/articles/4402427214107-Setting-Up-a-Recurring-Package-Plans, https://www.ezfacility.com/features/billing-payments

### PKG-05 Package auto-renewal and renewal prompts
- Sub-features: time-based auto-renew a lead time before expiry; renewal target selection; sessions-remaining threshold that flags a package for renewal; renewal icon on the client's package rows and on booked sessions; member opt-out (MEM-18).
- Settings / options: Auto-renew lead (period before expiration; must be within the package length, or 0 days); renews as = copy of itself / another plan / this plan by name (available after first save; follows later plan edits); Renewal Threshold (sessions remaining); post-billed sale: Auto Renew Yes/No.
- Rules / limits: the renewal marker on a session shows only when the package is actually set to renew (2023 fix); threshold-driven auto-renew is mentioned but not specified; when bundled into a membership the package needs its own auto-renew with matching lead time (MEM-04).
- User story: As an owner, I want session packs to re-purchase themselves when they run out or expire, so that regular clients never lapse.
- Actors: system scheduler; admin; front desk.
- UI generation: New article; threshold/icon behaviour also in Classic.
- Priority: P1
- Evidence: https://support.ezfacility.com/hc/en-us/articles/23573413327643-Setting-up-Auto-Renew-for-an-Individual-Package, https://support.ezfacility.com/hc/en-us/articles/34439958272283-How-to-Sell-a-Post-Billed-Package-in-EZFacility-Classic, https://support.ezfacility.com/hc/en-us/articles/18408526583067-August-31st-2023-Release-Notes, https://support.ezfacility.com/hc/en-us/articles/23397491696795-Adding-a-Package-or-Add-On-to-a-Membership-Plan, https://support.ezfacility.com/hc/en-us/articles/37195623250587-Click-to-Disable-Auto-Renew-Memberships

### PKG-06 Package sharing
- Sub-features: plan-level automatic sharing with related clients at sale; post-sale sharing with related clients or any searched client as authorised users; share count on the owner's package; shared-package waitlist handling.
- Settings / options: plan: Share With (relationship-based preset); sale (post-billed form): Share With = No One / All Related Clients; post-sale: explicit list of authorised clients.
- Rules / limits: plan summary states the package will be shared with all related clients; clients waitlisted on a shared package are auto-booked when a seat opens and show the package info marker (2023 fixes); all sharers draw from the owner's balance (inferred).
- User story: As a parent, I want one pack of lessons usable by any of my children, so that I buy once and whoever attends consumes a credit.
- Actors: admin (plan), front desk (post-sale), guardian/member (beneficiary).
- UI generation: both.
- Priority: P1
- Evidence: https://support.ezfacility.com/hc/en-us/articles/4404308415899-How-to-Share-Packages-Automatically-in-EZFacility-Classic, https://support.ezfacility.com/hc/en-us/articles/4404308418843-How-to-Share-a-Package-Post-Sale-in-EZFacility-Classic, https://support.ezfacility.com/hc/en-us/articles/23573413327643-Setting-up-Auto-Renew-for-an-Individual-Package, https://support.ezfacility.com/hc/en-us/articles/34439958272283-How-to-Sell-a-Post-Billed-Package-in-EZFacility-Classic, https://support.ezfacility.com/hc/en-us/articles/19132331777307-September-27th-2023-Release-Notes

### PKG-07 Staff sale of a package
- Sub-features: entry points = client's package tab, Administration > packages > sell, and inline from the session registration dialog; pick a plan or build an ad-hoc package from scratch; customise details and billing for this sale only; apply coupon; attribute salesperson; choose invoice timing; finish-and-pay vs finish; bank transfer among payment methods; on-account credit pre-applied.
- Settings / options: plan (or ad-hoc terms); Customize (per-sale snapshot of details and billing); coupon; Sold By; invoice option Invoice Now / Invoice Later (to cart), shown only when the plan has no default; finish and pay (opens payment capture) / finish (opens invoice, pay later via add payment). New package picker on the profile filters by reservation type and by description text (video).
- Rules / limits: customisations never change the plan; new sales default the client's on-account balance as payment, a partial balance is consumed and the rest of the invoice stays open; payment method list includes Bank Transfer in the package sale flow (2023). The picker filter persists from the previous sale and then hides other plans (their quirk; reset the filter per sale in our build).
- User story: As a front-desk user, I want to sell a session pack from the client's profile and take payment immediately, so that the client can book straight away.
- Actors: front desk, sales, admin.
- UI generation: both (same options; New flow documented from profile and admin side).
- Priority: P0
- Evidence: https://support.ezfacility.com/hc/en-us/articles/4404308405531-How-to-Sell-a-Package-in-EZFacility-Classic, https://support.ezfacility.com/hc/en-us/articles/23607740442011-How-to-Sell-a-Package-to-a-Client-on-their-Profile, https://support.ezfacility.com/hc/en-us/articles/4402434204955-How-to-Sell-a-Package-on-the-admin-side, https://support.ezfacility.com/hc/en-us/articles/4404311276699-How-to-Register-a-Client-into-an-Available-Session-in-EZFacility-Classic, https://support.ezfacility.com/hc/en-us/articles/21201707663515-Removing-and-Refunding-Packages, https://support.ezfacility.com/hc/en-us/articles/16731304236571-June-28th-2023-Release-Notes, https://www.youtube.com/watch?v=Rjy8ZpfIA68 (t=14:24)

### PKG-08 Package sale through point of sale
- Sub-features: selling package plans from the POS screen (Classic and New variants exist); known from article titles only.
- Settings / options: unknown.
- Rules / limits: unknown; see unknowns file.
- User story: As a cashier, I want to add a session pack to a POS basket with retail items, so that one transaction covers both (inferred).
- Actors: front desk/cashier (inferred).
- UI generation: both (one title per UI).
- Priority: P1
- Evidence: https://support.ezfacility.com/hc/en-us/articles/42551868532891-How-to-Sell-Packages-Through-the-Point-of-Sale (title only, body not read), https://support.ezfacility.com/hc/en-us/articles/42552021593499-How-to-Sell-Packages-Through-the-Point-of-Sale-Classic (title only, body not read)

### PKG-09 Online (self-service and app) package sales
- Sub-features: publish plans to the portal; pay-in-full vs allow-balance purchase policy; guardian purchase for a relative without a login; API listing of plans for sale and checkout line items for the mobile app cart; members see remaining sessions in the app.
- Settings / options: Sell Online = No / Yes, allow balances (partial or no payment at purchase) / Yes, paid in full; members-only restriction (PKG-10).
- Rules / limits: both Yes values require integrated card processing; one wizard text describes Sell Online as making the plan sold only through self-service (ambiguous, see unknowns).
- User story: As a client, I want to buy a class pack on my phone and book with it immediately, so that I do not need the front desk.
- Actors: member, guardian; admin (publishes).
- UI generation: both.
- Priority: P1
- Evidence: https://support.ezfacility.com/hc/en-us/articles/4404308407579-How-to-Sell-Package-Plans-Online-in-EZFacility-Classic, https://support.ezfacility.com/hc/en-us/articles/4404308415899-How-to-Share-Packages-Automatically-in-EZFacility-Classic, https://support.ezfacility.com/hc/en-us/articles/17574439837467-August-2nd-2023-Release-Notes, https://support.ezfacility.com/hc/en-us/articles/26498179644187-June-5th-2024-Release-Notes, https://support.ezfacility.com/hc/en-us/articles/26750732215835-June-19th-2024-Release-Notes, https://www.ezfacility.com/features/billing-payments, https://www.ezfacility.com/self-service-portal, https://www.ezfacility.com/features/branded-mobile-app/

### PKG-10 Member-only package plans
- Sub-features: restrict online purchase of a plan to clients holding an active membership.
- Settings / options: members-only checkbox on the plan's billing step.
- Rules / limits: enforced for online purchase; staff-side enforcement not stated.
- User story: As an owner, I want discounted packs that only current members can buy online, so that membership carries a tangible perk.
- Actors: admin; member.
- UI generation: Classic article (setting lives on the shared plan billing tab).
- Priority: P1
- Evidence: https://support.ezfacility.com/hc/en-us/articles/34441361024795-How-to-Create-Member-Only-Package-Plans-in-EZFacility-Classic

### PKG-11 Post-billed packages (bill after use)
- Sub-features: rate table per reservation type with volume threshold; optional extra billed items attached to every billed session; open a post-billed package for a client without upfront charge; unlimited scheduling while open; close to bill; sharing, auto-pay, renewal threshold and auto-renew on the instance.
- Settings / options: rate: Reservation Type, "with at least N sessions", per-session amount, extra billed items (pre-defined items). Sale: Package Type = Post-Billed; Sold By; Reservation Type; Share With (No One / All Related Clients); Auto-Pay Yes/No; Renewal Threshold; Package Rate; Auto Renew Yes/No. Instance shows "POST" in purchased/remaining columns.
- Rules / limits: no billing data exists until the package is closed; on close each used session is billed at the per-session rate (plus extra items); multiple rate rows per reservation type imply volume tiers (inferred).
- User story: As a facility running lessons on account, I want to let a client book freely and invoice the sessions actually taken at period end, so that I bill usage rather than prepayment.
- Actors: admin (rates); front desk (open/close).
- UI generation: Classic.
- Priority: P2
- Evidence: https://support.ezfacility.com/hc/en-us/articles/34439589179291-How-to-Create-a-Post-Billed-Package-in-EZFacility-Classic, https://support.ezfacility.com/hc/en-us/articles/34439958272283-How-to-Sell-a-Post-Billed-Package-in-EZFacility-Classic

### PKG-12 Session registration against a package, roster and attendance
- Sub-features: register a client into a schedulable session and choose which package pays; book this session, all linked sessions, or a custom subset; speed-register; sell a package inline; roster with attendance marking, per-registrant package/invoice/balance/payment access, removal, next-booked-session view, bulk email to all or checked registrants; capacity colour state on the calendar; waitlist with auto-promotion; client summary panel during registration.
- Settings / options: Book Into = This Package / All Sessions (n) / Custom; Enable Speed Register toggle; capacity state = empty / partially full / full; roster attendance mark; client summary shows DOB, phones, age, medical note, waiver signed, balance, membership. Attendance values seen in New: scheduled (default), attended, early cancel, late cancel, no-show; the last three need extra staff permissions (video).
- Rules / limits: speed-register only applies when the client has exactly one package; "all sessions" books every linked reservation subject to availability; package must match the session's reservation type (inferred from plan binding); booking requirements for a class can depend on package type (marketing); waitlisted sharers of a shared package are auto-booked when a place frees (2023); used sessions may be refunded on cancel (marketing, mechanics unspecified). A counted package only decrements when attendance is marked (unlimited packages need no marking); marking an early cancel offers to rebook into another available session or simply returns the session to the package (video).
- User story: As a trainer or front-desk user, I want to add a client to a session and have one credit drawn from the right package, so that attendance and balances stay in step.
- Actors: front desk, trainer; member (self-service booking is owned by the scheduling/portal clusters).
- UI generation: Classic article; New resource-view attendance article exists by title.
- Priority: P0
- Evidence: https://support.ezfacility.com/hc/en-us/articles/4404311276699-How-to-Register-a-Client-into-an-Available-Session-in-EZFacility-Classic, https://support.ezfacility.com/hc/en-us/articles/19132331777307-September-27th-2023-Release-Notes, https://support.ezfacility.com/hc/en-us/articles/17574439837467-August-2nd-2023-Release-Notes, https://support.ezfacility.com/hc/en-us/articles/45211147546267-How-to-Mark-Attendance-on-a-Session-in-Resource-View (title only, body not read), https://www.ezfacility.com/features/billing-payments, https://www.ezfacility.com/blog/the-top-5-advantages-of-gun-range-management-software, https://www.youtube.com/watch?v=Rjy8ZpfIA68 (t=24:35), https://www.youtube.com/watch?v=7JVYZ3kxUAo (t=32:56), https://www.youtube.com/watch?v=TWNQ4cTiEFs (t=42:16)

### PKG-13 Remove a sold package and reverse or refund its billing
- Sub-features: delete a client's package with a four-way decision when it has billing; reversal item with reason and revenue date; unapplied payments move to on-account credit; refund from on-account; same-date cancel of package plans attached to a membership (Classic cancel dialog).
- Settings / options: delete prompt = reverse the billing / delete but keep the billing / show the billing (no delete) / abort. Reversal: reason, revenue date. Refund form: client, issue date, amount (negative), original method, refund method.
- Rules / limits: reversal posts an equal and opposite item; payments stay recorded on the invoice and the surplus becomes on-account credit, which later sales consume by default; this is the documented way to fully un-bill a package; a membership's bundled package must be removed separately in New (MEM-04).
- User story: As an admin, I want to remove a wrongly sold or unused pack and return the money, so that the client's ledger and credits are both corrected.
- Actors: admin.
- UI generation: New (Classic evidence limited to the membership cancel dialog).
- Priority: P1
- Evidence: https://support.ezfacility.com/hc/en-us/articles/21201707663515-Removing-and-Refunding-Packages, https://support.ezfacility.com/hc/en-us/articles/4404308377243-Canceling-a-Membership-with-a-Refund-in-EZFacility-Classic, https://support.ezfacility.com/hc/en-us/articles/23397491696795-Adding-a-Package-or-Add-On-to-a-Membership-Plan

### PKG-14 Client package ledger and balance views
- Sub-features: per-client package list with purchased and remaining counts; view filter (all packages, reserved, waitlist, combinable); schedule count drill-down to an attendance update list; share count; renewal icon; member-facing remaining-sessions display in portal and app.
- Settings / options: view filter values = All Packages / Reserved / Waitlist (others not enumerated); columns purchased, remaining ("POST" for post-billed), schedule count.
- Rules / limits: reserved and waitlist views must be viewable together (2023 fix); the waitlist-row drill-down lists only the selected clients (2023 fix).
- User story: As a member or front-desk user, I want to see how many sessions remain on each pack and what is already booked, so that I know when to rebook or renew.
- Actors: front desk, trainer, member.
- UI generation: both.
- Priority: P0
- Evidence: https://support.ezfacility.com/hc/en-us/articles/21201707663515-Removing-and-Refunding-Packages, https://support.ezfacility.com/hc/en-us/articles/34439958272283-How-to-Sell-a-Post-Billed-Package-in-EZFacility-Classic, https://support.ezfacility.com/hc/en-us/articles/4404308418843-How-to-Share-a-Package-Post-Sale-in-EZFacility-Classic, https://support.ezfacility.com/hc/en-us/articles/16308423683355-June-12th-2023-Release-Notes, https://support.ezfacility.com/hc/en-us/articles/17574439837467-August-2nd-2023-Release-Notes, https://www.ezfacility.com/features/branded-mobile-app/, https://www.ezfacility.com/self-service-portal

### PKG-15 Package sales and usage reports
- Sub-features: Package Sales report for a date range, summary or detail; related report names from release notes: Client Package Summary, Unused Session Value; trainer performance report shows the package type used per session.
- Settings / options: Package Sales inputs = location (multi-location tenants), start/end date, show details; columns = date sold, client, reservation type, salesperson, sessions purchased, total cost, amount paid, balance due; export (CSV).
- Rules / limits: none stated beyond the inputs.
- User story: As an owner, I want to see packs sold by date, service and salesperson with paid vs owed, so that I can track sales and commissions.
- Actors: owner, manager.
- UI generation: both.
- Priority: P1
- Evidence: https://support.ezfacility.com/hc/en-us/articles/4403493447707-Package-Sales, https://support.ezfacility.com/hc/en-us/articles/19132331777307-September-27th-2023-Release-Notes, https://www.ezfacility.com/blog/updated-subgroup-inheritance-trainer-performance-report-e-mail-procedures-and-more

### PKG-16 Package data in the public and self-service APIs
- Sub-features: sessions scheduled and sessions completed per package (active and all); list of package plans available for sale; checkout line items for package plans (mobile cart).
- Settings / options: read fields and cart line type as named.
- Rules / limits: none stated.
- User story: As an app developer, I want package balances and purchasable plans over an API, so that a branded app can sell and display packs.
- Actors: API consumer, mobile app.
- UI generation: n/a (API).
- Priority: P1
- Evidence: https://support.ezfacility.com/hc/en-us/articles/19847009538203-October-25th-2023-Release-Notes, https://support.ezfacility.com/hc/en-us/articles/26498179644187-June-5th-2024-Release-Notes, https://support.ezfacility.com/hc/en-us/articles/26750732215835-June-19th-2024-Release-Notes

## Billing & Invoicing

### BIL-01 Billing item ledger and item-level edits
- Sub-features: per-client "Items" tab listing every billed charge (invoiced or not); open item (pencil) to edit; item reachable from the invoice it sits on; item fields editable after sale: price per session, discount, revenue date, revenue category, taxes on/off per tax, additional (client-visible) remarks, internal (staff-only) remarks; item can carry or lack an invoice; simplified apply-payment view of billed items with paging.
- Settings / options: item state: uninvoiced / on open invoice / on paid invoice / reversed / voided (voided = removed from the books, irreversible); per-item tax toggles; per-item revenue category override; discount as amount or percent (inferred from pre-defined item and coupon forms); revenue date distinct from bill date and invoice date; item "invoice number" shown as an editable item attribute (see unknowns).
- Rules / limits: taxes apply automatically from the item's revenue category and can be removed per item; unchecked taxes at rental creation must stay unchecked on the resulting invoice (fix 2023-09-13); billed-items list pages at 75 per page (2023-06-28); price change on an item does not itself move money (refund is a separate step).
- User story: As a front-desk user, I want to see and correct every charge on a client account, so that invoices reflect what was actually agreed.
- Actors: Owner/Admin, Front Desk, billing staff.
- UI generation: both (Items tab in Classic and New; edit detail documented for New)
- Priority: P0
- Evidence: https://support.ezfacility.com/hc/en-us/articles/23396052328859-How-to-view-invoices, https://support.ezfacility.com/hc/en-us/articles/25737423648923-How-to-Partially-Refund-a-Sale, https://support.ezfacility.com/hc/en-us/articles/4402433754267-How-to-Reverse-the-Billing-of-an-Item, https://support.ezfacility.com/hc/en-us/articles/4402426353691-How-to-View-Billing-History-for-Invoices-and-Items, https://support.ezfacility.com/hc/en-us/articles/4403493319195-How-to-View-Billing-History-for-Invoices-and-Items-in-EZFacility-Classic, https://support.ezfacility.com/hc/en-us/articles/16731304236571-June-28th-2023-Release-Notes, https://support.ezfacility.com/hc/en-us/articles/18741009680795-September-13th-2023-Release-Notes

### BIL-02 Global billing-items workbench and bulk invoicing
- Sub-features: location-wide list "All Un-invoiced Items" reached from the top-right menu; tick items and create a "New Invoice"; post-create choices: apply payment, leave open (Done), email invoice; filter editor with presets (e.g. "Open Invoices"); bulk actions on the filtered set: Reverse Billing, Print/Save Invoices, Email Invoices, Add Item to Invoices (attach a pre-defined item to many invoices); Classic equivalent: choose items via "Add..." dropdown then "Add Billed Items To Invoices"; select all / individual invoices.
- Settings / options: filter "Invoiced/Uninvoiced" (values include "Item IS on an invoice"); Preset dropdown (Open Invoices; others not enumerated); Edit Filters / Apply Filters; second preset "Invoice Lookup" (find by invoice number), shown in a billing Q&A webinar
- Rules / limits: a bulk-created invoice is for ONE client; if items from several clients are ticked, everything is billed to the first client ticked (documented footgun); bulk email needs a valid client email; bulk Reverse Billing undoes the charge but leaves the invoice record on the profile; open invoices created here are payable by the client in Self-Service.
- User story: As billing staff, I want one screen to find uninvoiced charges and open invoices across the location and act on them in bulk, so that month-end clean-up is fast.
- Actors: Admin, billing staff.
- UI generation: both (New: All Un-invoiced Items + presets; Classic: location cart with filters)
- Priority: P0 (invoice-from-items); bulk actions P1
- Evidence: https://support.ezfacility.com/hc/en-us/articles/26114234694043-How-to-Create-an-Invoice-for-Un-invoiced-Items, https://support.ezfacility.com/hc/en-us/articles/26114282998811-How-to-view-all-open-invoices, https://support.ezfacility.com/hc/en-us/articles/4403493341083-How-to-Add-Items-to-Invoices-in-the-Shopping-Cart-in-EZFacility-Classic, https://www.youtube.com/watch?v=iR4MVBspNlQ (t=25:48)

### BIL-03 Uninvoiced-item carts (per-user and per-location)
- Sub-features: "shopping cart" holding billed-but-uninvoiced items; two scopes in Classic: globe cart = all users' uninvoiced items at the location (red count badge), plain cart = current user's items; items removed from an invoice (cart icon on the invoice line) fall back into the cart; sale flows can deliberately "Leave items in cart" (Default Invoice Option on plans/pre-defined items); rental sale offers "Leave items in cart" as the alternative to a single new invoice, which is how uninvoiced rental items arise; an invoiced rental shows a "$" marker on the calendar; "More Options" at invoicing lets staff forward-date the revenue date
- Settings / options: Default Invoice Option value "Leave items in cart" (vs Single Invoice / Multiple Invoices); cart scope user vs location.
- Rules / limits: removing an item from an invoice neither voids nor reverses it; invoice "Created By" must record the creator when the invoice is built from a client's cart items (fix 2023-08-31); leaving a rental uninvoiced still holds the time slot; every rental needs a client attached; reversing an uninvoiced item turns it complimentary but the item and its booking stay (the booking is removed from the schedule separately); bulk invoicing is ticked one client at a time
- User story: As a front-desk user, I want charges I have rung up but not yet invoiced kept in a holding area, so that I can group them onto one invoice later.
- Actors: Front Desk, Admin.
- UI generation: Classic (cart metaphor); New keeps the concept as "un-invoiced items"
- Priority: P1
- Evidence: https://support.ezfacility.com/hc/en-us/articles/4403486128283-How-to-Add-Items-to-the-Shopping-Cart-in-EZFacility-Classic, https://support.ezfacility.com/hc/en-us/articles/4403493341083-How-to-Add-Items-to-Invoices-in-the-Shopping-Cart-in-EZFacility-Classic, https://support.ezfacility.com/hc/en-us/articles/17657710657051-How-to-Create-and-Sell-a-Pre-Defined-Item, https://support.ezfacility.com/hc/en-us/articles/18408526583067-August-31st-2023-Release-Notes, https://www.youtube.com/watch?v=iR4MVBspNlQ (t=32:58-44:13)

### BIL-04 Client invoice list and invoice editing
- Sub-features: client Billing > Invoices list; "Show" filter (default = currently payable invoices; "All Invoices"; "Voided Invoices"); paid invoices rendered struck through; open invoice (pencil); edit invoice date; edit Payments Due; change Bill To; edit items; add Comments; view Payment Receipt; view Invoice History; print receipt; download PDF; email copy; "$" / gold-dollar shortcut on a row to take payment; "Pay Now" on open invoices in the Groups tab; combine invoices by moving an item: pencil on the item, Change next to its invoice number, type the target invoice number (or pick "add to invoice" while creating a rental); add a pre-defined/generic item to an already paid membership invoice (e.g. an annual service fee)
- Settings / options: invoice status (inferred enumeration): open / partially paid / paid / voided; Show filter values: payable (default), All Invoices, Voided Invoices; invoice-level autopay on/off; "Created By"; optional "Organization" on invoice reporting.
- Rules / limits: invoice may hold several payments (allocation order bug fixed 2023-08-02: larger second payment must apply correctly); autopay switch on the payment page must mirror the plan default and persist to the invoice for memberships, rentals and groups (fix 2023-10-25); after items are moved off it the source invoice stays behind empty and only a manager can void it; adding a generic item to a paid membership invoice needs the manager role
- User story: As a front-desk user, I want to open any client invoice and adjust or act on it, so that I can resolve billing questions at the counter.
- Actors: Owner/Admin, Front Desk.
- UI generation: both
- Priority: P0
- Evidence: https://support.ezfacility.com/hc/en-us/articles/23774929108123-How-to-View-Invoices-Under-a-Client-s-Profile, https://support.ezfacility.com/hc/en-us/articles/23396052328859-How-to-view-invoices, https://support.ezfacility.com/hc/en-us/articles/4402433807515-How-to-Void-an-Invoice, https://support.ezfacility.com/hc/en-us/articles/22122496577179-January-17th-2024-Release-Notes, https://support.ezfacility.com/hc/en-us/articles/17574439837467-August-2nd-2023-Release-Notes, https://support.ezfacility.com/hc/en-us/articles/19847009538203-October-25th-2023-Release-Notes, https://support.ezfacility.com/hc/en-us/articles/14655161654811-April-18th-2023-Release-Notes, https://www.youtube.com/watch?v=7JVYZ3kxUAo (t=42:17-45:21), https://www.youtube.com/watch?v=KAN6h9vPUiM (t=42:16-44:17)

### BIL-05 Invoice payer reassignment (Bill To)
- Sub-features: "Change" on the invoice Bill To block; search another client; submit; invoice moves to the new payer's profile while the purchased item stays with the beneficiary.
- Settings / options: Invoice "Bill To" Preferences (what the Bill To block prints); default payer = client the product was sold to; agreement signer role "Invoice Holder" exists on membership contracts (other cluster).
- Rules / limits: typical use is parent paying a child's invoice; no documented restriction to related clients (see unknowns).
- User story: As an admin, I want to move an invoice to a different payer, so that a parent or sponsor can be billed for someone else's purchase.
- Actors: Admin, Front Desk.
- UI generation: New (documented); Classic not documented
- Priority: P1
- Evidence: https://support.ezfacility.com/hc/en-us/articles/26528401455643-How-to-Assign-an-Invoice-to-a-Different-Client, https://support.ezfacility.com/hc/en-us/articles/23396052328859-How-to-view-invoices, https://support.ezfacility.com/hc/en-us/articles/21173246031771-Setting-Up-Billing-Preferences

### BIL-06 Payment schedules (instalments on an invoice)
- Sub-features: "Payments Due" block on an invoice with Change; generator: start date, every N units, for N payments, Generate Schedule; manual builder: new due date + amount, Add to schedule (remaining balance prefilled); Clear Schedule; running "Due To Date" column; Save; schedule summarised on the invoice as "Nx by <date>"; can also be set at time of sale; history logs schedule creation.
- Settings / options: interval unit: days, weeks, half months, months, years (New article omits months; assumed present); default schedule = one entry for the full amount on the invoice due date; generator vs manual mode.
- Rules / limits: sum of entries must equal invoice amount due (cannot save otherwise); last running total must equal invoice total; no entry dated before the invoice date; payments already received appear on the schedule automatically; regenerating overwrites the default single entry; Save/Cancel visibility fix 2023-06-28; removing one occurrence from a recurring rental series does not rebalance the payment schedule, staff adjust it by hand
- User story: As a front-desk user, I want to split an invoice into dated instalments, so that the client can pay over time and autopay/AR follow the agreed dates.
- Actors: Owner/Admin, Front Desk.
- UI generation: both
- Priority: P0
- Evidence: https://support.ezfacility.com/hc/en-us/articles/4403486115483-How-to-Set-Up-a-Payment-Schedule-on-an-Invoice-in-EZFacility-Classic, https://support.ezfacility.com/hc/en-us/articles/4402426435739-How-to-Set-Up-a-Payment-Schedule, https://support.ezfacility.com/hc/en-us/articles/23396052328859-How-to-view-invoices, https://support.ezfacility.com/hc/en-us/articles/16731304236571-June-28th-2023-Release-Notes, https://www.ezfacility.com/features/billing-payments, https://www.youtube.com/watch?v=7JVYZ3kxUAo (t=19:38)

### BIL-07 Billing reversal (item-level credit)
- Sub-features: U-turn action on an item from the Items tab or inside an invoice; mandatory reason; choice of revenue date for the reversing entry; bulk "Reverse Billing" from the workbench; reversal offered when removing a member from a group and when cancelling a membership (other clusters).
- Settings / options: reversal revenue date: Today's Date / Original Billed Date (recommended for reporting) / Custom Date.
- Rules / limits: reversal zeroes the charge (used e.g. to make an item free); if the item was already paid the money becomes credit On Account; revenue-date choice is optional and the default is not stated; reversal is recorded in history; trainer guidance: pick Original Billed Date so everything between the original sale and today is unwound in the right period; Today's Date also works but the revenue report then shows the reversal as done today while still tied to the original service start date
- User story: As an admin, I want to cancel a charge with a reason and control which period the negative revenue lands in, so that reports stay correct.
- Actors: Owner/Admin, Front Desk.
- UI generation: both
- Priority: P0
- Evidence: https://support.ezfacility.com/hc/en-us/articles/4403493306779-How-to-Reverse-the-Billing-of-an-Item-on-an-Invoice-in-EZFacility-Classic, https://support.ezfacility.com/hc/en-us/articles/4402433754267-How-to-Reverse-the-Billing-of-an-Item, https://support.ezfacility.com/hc/en-us/articles/4402433754907-How-to-Reverse-the-Billing-of-an-Item-on-an-Invoice, https://support.ezfacility.com/hc/en-us/articles/26114282998811-How-to-view-all-open-invoices, https://support.ezfacility.com/hc/en-us/articles/4415441364635-How-to-Process-a-Refund-Remove-a-Client-from-a-Group, https://www.youtube.com/watch?v=a7-8-cHwB8Y (t=10:17, t=22:33-24:35)

### BIL-08 Invoice void and item void
- Sub-features: detach items from an invoice (cart icon per line); "Void Invoice" button; "Voided Invoices" filter; afterwards the detached item can be re-invoiced or voided outright from the Items tab.
- Settings / options: invoice status voided; item status voided.
- Rules / limits: voiding an invoice is not a refund and does not reverse the items (they return to uninvoiced); Void Invoice is only offered once the invoice is down to its last/zero items (Classic: button hidden while multiple items remain); item void removes the charge from the books and cannot be undone.
- User story: As an admin, I want to cancel an incorrectly issued invoice without losing the underlying charges, so that I can re-bill them properly.
- Actors: Owner/Admin, Front Desk.
- UI generation: both
- Priority: P0
- Evidence: https://support.ezfacility.com/hc/en-us/articles/4403493317275-How-to-Void-an-Invoice-in-EZFacility-Classic, https://support.ezfacility.com/hc/en-us/articles/4402433807515-How-to-Void-an-Invoice, https://support.ezfacility.com/hc/en-us/articles/4403486128283-How-to-Add-Items-to-the-Shopping-Cart-in-EZFacility-Classic

### BIL-09 Billing audit history
- Sub-features: "View History" on any billing item and any invoice; shows who created the invoice, took payment, reversed an item, applied a discount, built a payment schedule, plus original sale steps.
- Settings / options: none found.
- Rules / limits: read-only; reachable from Items tab, Invoices tab and from an item inside an invoice.
- User story: As an owner, I want a tamper-evident trail of every billing action and actor, so that disputes and staff errors can be traced.
- Actors: Owner/Admin, Front Desk.
- UI generation: both
- Priority: P0
- Evidence: https://support.ezfacility.com/hc/en-us/articles/4403493319195-How-to-View-Billing-History-for-Invoices-and-Items-in-EZFacility-Classic, https://support.ezfacility.com/hc/en-us/articles/4402426353691-How-to-View-Billing-History-for-Invoices-and-Items, https://support.ezfacility.com/hc/en-us/articles/23396052328859-How-to-view-invoices

### BIL-10 Invoice delivery (email, print, PDF)
- Sub-features: envelope action on an invoice sends it to the client's profile email with confirmation; print receipt; download PDF; bulk Print/Save and Email from the workbench and from post-billing close; configurable email subject with merge token; invoice footer and receipt footer text; optional group description on invoice.
- Settings / options: Invoice Email subject template (token {InvoiceNumber}); Invoice Footer; Receipt Footer; Invoice Preferences: include Groups description, sourced from parent group or subgroup; Invoice "Bill To" Preferences.
- Rules / limits: client must have a valid email; the emailed invoice has no pay link, client must log in to Self-Service to pay; no scheduled or automatic sending of invoices or statements (e.g. monthly), every send is started by staff; one facility reported spending a full day a month on it (webinar Q&A, date not stated)
- User story: As a front-desk user, I want to send or print an invoice in one click, so that clients have a record of what they owe.
- Actors: Admin, Front Desk, Client (recipient).
- UI generation: both (email article is New; print/PDF in both)
- Priority: P0
- Evidence: https://support.ezfacility.com/hc/en-us/articles/25419259427099-How-to-Email-an-Invoice-to-a-Client, https://support.ezfacility.com/hc/en-us/articles/21173246031771-Setting-Up-Billing-Preferences, https://support.ezfacility.com/hc/en-us/articles/26114282998811-How-to-view-all-open-invoices, https://support.ezfacility.com/hc/en-us/articles/29784817818907-How-to-Close-and-Review-Post-Billed-Packages-in-EZFacility-Classic, https://support.ezfacility.com/hc/en-us/articles/23396052328859-How-to-view-invoices, https://www.youtube.com/watch?v=iR4MVBspNlQ (t=19:35-24:43)

### BIL-11 Billing statements
- Sub-features: per-client statement for a date range (View Statement) with export for sending outside the system; bulk statement emailing wizard (Clients > Billing Statements): Client Category filter, client Filter, date range, basis invoice date or due date, "only clients with an open invoice", pick clients or select all, Email; statement email subject/body template; statement footer (e.g. tax ID); refund form offers "print a statement" (other cluster); wizard can also filter by client tags; the per-client statement can be saved as Word or PDF or printed
- Settings / options: Search By: invoice date / due date (one required); only-open-invoices checkbox; Billing Statement Email subject + body; Billing Statement Footer; user permission "Billing Statements" (under Billing Permissions).
- Rules / limits: permission can only be granted to users flagged as manager; clients need valid email; open-ended date range returns all invoices and can be slow; bulk email needs a verified client email and the tool gives no delivery confirmation (a customer reported a statement never arriving); a webinar presenter says the date picker allows at most one year (conflicts with the open-ended note, see unknowns)
- User story: As a manager, I want to email account statements to a filtered set of clients, so that outstanding balances are communicated without opening each profile.
- Actors: Manager users, Admin, Front Desk (single view), Client (recipient).
- UI generation: New (documented); Classic not documented
- Priority: P1
- Evidence: https://support.ezfacility.com/hc/en-us/articles/23774950594715-How-to-View-a-Billing-Statement-on-a-Client-s-Profile, https://support.ezfacility.com/hc/en-us/articles/25631630542619-How-to-Send-a-Client-a-Billing-Statement, https://support.ezfacility.com/hc/en-us/articles/21173246031771-Setting-Up-Billing-Preferences, https://www.youtube.com/watch?v=iR4MVBspNlQ (t=04:06-06:09, t=22:38, t=47:19)

### BIL-12 Taxes (effective-dated rates)
- Sub-features: tax definitions with code, label, remarks, percentage and first effective date; add future-dated rate changes; Change; Deactivate; automatic application to memberships, packages, rentals, registrations, POS transactions and (Classic text) locker rentals; per-item opt-out on an invoice; exclusion via revenue category mapping; reports split "Taxes Generated" from revenue.
- Settings / options: Tax Code (free text e.g. HST, PST, GST, VAT); Tax Label; Remarks; Tax percentage; effective-from date; active/deactivated.
- Rules / limits: multiple taxes are each computed on the pre-tax revenue amount (no compounding); the applicable rate is selected by the item's revenue date; deactivation stops application from the deactivation date; deactivation in New UI fixed 2023-08-16; revenue report shows revenue with discounts included and taxes excluded.
- User story: As an owner, I want tax rates that change on a known date and apply automatically, so that invoices are correct without manual edits.
- Actors: Owner/Admin.
- UI generation: both
- Priority: P0
- Evidence: https://support.ezfacility.com/hc/en-us/articles/4403485782811-How-to-Set-Up-Taxes-for-your-Account-in-EZFacility-Classic, https://support.ezfacility.com/hc/en-us/articles/4402426433819-How-to-Set-Up-Taxes-For-Your-Account, https://support.ezfacility.com/hc/en-us/articles/17981009155995-August-16th-2023-Release-Notes, https://support.ezfacility.com/hc/en-us/articles/18741009680795-September-13th-2023-Release-Notes

### BIL-13 Revenue categories (GL-style chart with tax mapping)
- Sub-features: category code + label + remarks; hierarchical sub-categories (parent chosen via picker or by typing parent code); tax checkboxes per category; Update; Deactivate; Show Deactivated / reactivate; attach to Membership Types, Package Plans, Rental/Reservation Types, Groups (optionally cascade to subgroups), POS items, pre-defined items, or override per billed item; revenue reports group by category.
- Settings / options: Code (unique, alphanumeric, may mirror accounting GL code); Label; Remarks; Subcategory of; Taxes[]; active flag; Groups checkbox "Update Revenue Category in Subgroups".
- Rules / limits: items inherit the category's taxes automatically; category with no taxes ticked = untaxed; membership revenue category lives on the Membership Type, not the Plan; saving on new membership types fixed 2025-04-09.
- User story: As an owner, I want every charge classified to an accounting code with default taxes, so that revenue reports and accounting exports reconcile.
- Actors: Owner/Admin.
- UI generation: both
- Priority: P0
- Evidence: https://support.ezfacility.com/hc/en-us/articles/4403485771547-How-to-Set-Up-Revenue-Categories-in-EZFacility-Classic, https://support.ezfacility.com/hc/en-us/articles/4402426434587-How-to-Set-Up-Revenue-Categories, https://support.ezfacility.com/hc/en-us/articles/23969046407579-How-to-Connect-Your-Revenue-Categories, https://support.ezfacility.com/hc/en-us/articles/36516560976539-April-9th-2025-Release-Notes, https://support.ezfacility.com/hc/en-us/articles/17574439837467-August-2nd-2023-Release-Notes

### BIL-14 Pre-defined items (generic charge catalog, one-off and recurring)
- Sub-features: catalog under Location Settings; kinds Individual (one-off, optionally renewing) and Recurring (repeats over a period, optionally renewing); creation wizard (Details, [Recurrence], Billing, Summary); sell from client profile via "Sell Generic Item" side panel with per-sale overrides; Finish & Pay (jump to invoice) or Finish (pay later); attach to many invoices in bulk; bundle into membership plans.
- Settings / options: Description; Start Date: specific date / sale date; Item Length (Individual only, optional); Auto-Renew Yes/No + renew lead time before go-live; "renews as": copy of itself / any other pre-defined item; Recurrence Pattern Daily / Weekly / Monthly / Yearly; Every N; End After N occurrences; Fee; Default Invoice Option: Single Invoice / Multiple Invoices (one per occurrence) / Leave items in cart; Auto-Pay; Discount (% or amount); Revenue Category; Additional Description (on invoice); Internal Remarks.
- Rules / limits: Auto-Pay only charges if the client has billing details on file and a processor is integrated; a discount preset on the item always applies, a blank one can be added at sale; renewing "as" a named item picks up that item's current price, so a per-sale customised item should renew as a copy of itself or it reverts to catalog settings.
- User story: As a front-desk user, I want to sell a predefined fee (once or on a recurring cadence) from a client profile, so that ad-hoc and maintenance charges are billed consistently.
- Actors: Admin (catalog), Front Desk (sale).
- UI generation: New
- Priority: P0 (one-off charge); recurring/renewal P1
- Evidence: https://support.ezfacility.com/hc/en-us/articles/17657710657051-How-to-Create-and-Sell-a-Pre-Defined-Item, https://support.ezfacility.com/hc/en-us/articles/26114282998811-How-to-view-all-open-invoices, https://www.ezfacility.com/features/billing-payments

### BIL-15 Coupons
- Sub-features: coupon list under Billing admin; add / edit / permanent delete; amount-off or percent-off; validity window; per-person redemption cap or unlimited; flag making the code usable in Self-Service checkout; historic: start/end time to the minute enforced at POS (2016); older navigation shown in a video: Point of Sale > Coupons; coupon sales reportable by date range
- Settings / options: Coupon Name; Coupon Code; Start Date; End Date; type Amount / Percent; Coupon Limit: Unlimited or N per person; Self Service Enabled.
- Rules / limits: limit is per person and also applies when a client buys for a relative in Self-Service (fix 2023-08-31); applying a coupon to an annual membership must update payment due in Self-Service (fix 2023-08-31); delete is permanent; product scope and stacking rules not documented; a vendor webinar shows coupons applying to memberships and packages as well as POS items (stacking still not documented)
- User story: As an admin, I want promo codes with dates and per-person limits, so that I can run offers online and at the desk without manual discounts.
- Actors: Admin, Client (redeems in Self-Service), Front Desk.
- UI generation: New (documented); coupons pre-date New UI
- Priority: P0
- Evidence: https://support.ezfacility.com/hc/en-us/articles/26094951298331-How-to-Create-Coupons, https://support.ezfacility.com/hc/en-us/articles/18408526583067-August-31st-2023-Release-Notes, https://www.ezfacility.com/blog/ez-features-fixes-check-out-whats-new, https://www.youtube.com/watch?v=3FOVNMAz2cE (t=25:35-31:44)

### BIL-16 Billing preferences (account-level defaults)
- Sub-features: single settings page with explicit Save covering payment-method visibility, package invoice content, package booking range default, membership autopay default, invoice content, Bill To block, save-card default, card expiry notices, card decline notices, email templates, document footers.
- Settings / options: Optional Payment Methods (checkbox list, "Ext" = external/record-only); Package Invoice Dates (which sessions list on a package invoice); Package Preferences "Booking Out of Range" Allow / Disallow (overridable per package); Membership AutoPay Option (internal sale and/or Self-Service); Invoice Preferences (include group description; from parent group or subgroup); Invoice "Bill To" Preferences; Save Credit Card Info For Manual Payments (values include "Yes", "Always Save"); Expired Credit Card Notifications (1 month, 2 months, or both; all cards or autopay cards only); Credit Card Decline Notifications (all cards or autopay cards only); Invoice Email subject ({InvoiceNumber}); Billing Statement Email subject + body; Invoice Footer; Receipt Footer; Billing Statement Footer.
- Rules / limits: nothing persists until Save; Package Invoice Dates applies on next edit-and-save of a package invoice, not retroactively; vendor advice is to disable all optional external methods and to Disallow out-of-range booking.
- User story: As an owner, I want one place for billing defaults and document wording, so that every invoice, receipt and notice follows house policy.
- Actors: Owner/Admin.
- UI generation: both (New documented in detail; Classic path Administration > Billing Administration > Billing Preferences)
- Priority: P0
- Evidence: https://support.ezfacility.com/hc/en-us/articles/21173246031771-Setting-Up-Billing-Preferences, https://support.ezfacility.com/hc/en-us/articles/4402433808155-How-to-Set-Up-Payment-Options, https://support.ezfacility.com/hc/en-us/articles/29852339864987-Defaulting-New-Membership-Contracts-to-Auto-Pay-in-Self-Service, https://support.ezfacility.com/hc/en-us/articles/50293809318555-How-to-Set-Up-Billing-Preferences (title only, body not read)

### BIL-17 Autopay defaults and per-invoice autopay flag
- Sub-features: account default forcing autopay on new membership contracts, separately for in-facility sales and Self-Service sales; autopay default on membership plans, package plans and pre-defined items; autopay switch at payment time; resulting flag stored on the invoice and visible on the billing tab; membership agreement has a dedicated Auto-Pay section (other cluster).
- Settings / options: Membership Auto-Pay Option: purchased online in Self-Service / purchased in the facility (either or both); plan-level Auto-Pay Yes/No; invoice-level autopay on/off.
- Rules / limits: the account option is only shown once a merchant processor is integrated; Classic article documents only the Self-Service default; plan default must propagate to the payment page and then to the invoice (fix 2023-10-25); 2014 note: stored cards default to "use for autopay" and that could only be changed on accounts using direct debit.
- User story: As an owner, I want new recurring contracts to default to automatic collection, so that dues are not chased manually.
- Actors: Owner/Admin, Front Desk, Client (Self-Service purchase).
- UI generation: both
- Priority: P0
- Evidence: https://support.ezfacility.com/hc/en-us/articles/29852339864987-Defaulting-New-Membership-Contracts-to-Auto-Pay-in-Self-Service, https://support.ezfacility.com/hc/en-us/articles/4402427195163-Defaulting-New-Membership-Contracts-To-Auto-Pay-In-Self-Service, https://support.ezfacility.com/hc/en-us/articles/21173246031771-Setting-Up-Billing-Preferences, https://support.ezfacility.com/hc/en-us/articles/19847009538203-October-25th-2023-Release-Notes, https://support.ezfacility.com/hc/en-us/articles/17657710657051-How-to-Create-and-Sell-a-Pre-Defined-Item, https://www.ezfacility.com/blog/features-fixes-automatic-credit-card-notification-emails

### BIL-18 Post-billed package period close
- Sub-features: "Close Post Billing" batch page: closing date, client checklist, per-client scheduled-session count linking to attendance update, "Close and Bill Selected Packages", then Print/Save Invoices (PDF) and Email Invoices; "Review Post Billing" page for past closes.
- Settings / options: closing date; client selection; package type Post-Billed (other cluster).
- Rules / limits: sessions need an attendance status before they can be billed; on auto-renewing packages, sessions booked after the closing date roll into a new package automatically.
- User story: As billing staff, I want to bill usage-based packages in arrears at period end, so that clients are invoiced for sessions actually consumed.
- Actors: Admin, billing staff.
- UI generation: Classic (New equivalent not documented)
- Priority: P1
- Evidence: https://support.ezfacility.com/hc/en-us/articles/29784817818907-How-to-Close-and-Review-Post-Billed-Packages-in-EZFacility-Classic

### BIL-19 Accounts receivable report
- Sub-features: open invoices as of a date with filters, sorting, detail toggle and export; shows the card-charge error for failed autopay invoices; email-invoice link on report rows
- Settings / options: Report By: Due Dates / Invoice Date; earliest due date (optional); latest due date; include payments up to (blank = all); Invoices: All / Auto Pay Only / Non-Auto Pay; include clients reported for collections; clients: deleted / active / both; sort: Client Name / Invoice Balance / Invoice Due Date; Show Details; export.
- Rules / limits: as-of balance is computed by cutting payments at the "payments up to" date; a deposit shows in receivables on the day it was paid and the remaining balance on the day that is paid (webinar Q&A); a customer reported the email-invoice link in this report not working (date and fix status unknown)
- User story: As an owner, I want an aged list of what is owed and why autopay failed, so that I can chase receivables.
- Actors: Owner/Admin, billing staff.
- UI generation: both (report; UI not stated)
- Priority: P1
- Evidence: https://support.ezfacility.com/hc/en-us/articles/4403493405851-Accounts-Receivable, https://www.youtube.com/watch?v=7JVYZ3kxUAo (t=20:41-21:43), https://www.youtube.com/watch?v=iR4MVBspNlQ (t=48:20)

### BIL-20 Collections tagging and reports
- Sub-features: client billing status flag for collections; five report variants (reported for collections; reported with invoices older than X days; tagged/eligible; tagged with invoices older than X days; not tagged with invoices older than X days); report-time action to mark clients as placed in collections or to tag them.
- Settings / options: client billing status: normal / tagged (eligible) for collections / in collections (reported); days-overdue threshold X; mark placed in collections Yes/No; flag for collections Yes/No.
- Rules / limits: list-only, nothing is transmitted to an agency (facility hires its own); marking only moves the client to the reported list; AR report can include or exclude reported clients.
- User story: As an owner, I want to flag and list delinquent clients by age of debt, so that I can hand them to a collections process.
- Actors: Owner/Admin.
- UI generation: both (report; UI not stated)
- Priority: P1
- Evidence: https://support.ezfacility.com/hc/en-us/articles/4403486270875-Collections, https://support.ezfacility.com/hc/en-us/articles/4403493405851-Accounts-Receivable

### BIL-21 Client account credit ("On Account" balance)
- Sub-features: unapplied portion of a payment remains as money on the client account ("Remaining"); credit also arises when a paid item is reversed, a membership is cancelled, or a member is removed from a group with billing reversal; credit can be applied to items later, spent at POS as "Money on Account" (other cluster) or refunded via the On Account "Refund" button.
- Settings / options: none found (balance is derived).
- Rules / limits: a payment need not be fully applied; refund button is disabled when nothing is on account (2023-06-28).
- User story: As a front-desk user, I want overpayments and reversed charges held as client credit, so that they can be reused or refunded later.
- Actors: Front Desk, Admin, Client.
- UI generation: both
- Priority: P0
- Evidence: https://support.ezfacility.com/hc/en-us/articles/4403485806363-How-to-Apply-a-Payment-in-EZFacility-Classic, https://support.ezfacility.com/hc/en-us/articles/4402433808923-How-to-Take-a-Payment, https://support.ezfacility.com/hc/en-us/articles/4415441364635-How-to-Process-a-Refund-Remove-a-Client-from-a-Group, https://support.ezfacility.com/hc/en-us/articles/16731304236571-June-28th-2023-Release-Notes

### BIL-22 Billing reminders and past-due enforcement
- Sub-features: automated email and text reminders before and after a payment due date; past-due tracking; SMS billing-decline and collection reminders (messaging add-on); option to block clients with outstanding balances from using Self-Service (2017).
- Settings / options: not documented in public help (offsets, channels, templates unknown).
- Rules / limits: marketing-level evidence only.
- User story: As an owner, I want clients nudged automatically before and after an invoice falls due, so that delinquency drops without staff effort.
- Actors: System, Client, Owner/Admin.
- UI generation: both (not stated)
- Priority: P0 (email dunning); SMS and Self-Service lockout P1
- Evidence: https://www.ezfacility.com/features/billing-payments, https://www.ezfacility.com/capterra-sports-league-management/, https://www.ezfacility.com/blog/the-top-5-advantages-of-gun-range-management-software

### BIL-23 Invoice API endpoints
- Sub-features: read invoices by id, by invoice number, by client, by location + invoice number; each invoice carries a Payments array (2022-12-15) and Disbursements linking payments to billed items (2024-04-24); write endpoint to set Paid status on one or many invoices (2023-11-08).
- Settings / options: invoice status includes Paid.
- Rules / limits: paths as published: GET /v2/invoices/{invoiceID}, /v2/invoices/invoiceNumber={invoiceNumber}, /v2/invoices/clientId={clientID}, /v2/invoices/locationID/{locationID}/invoiceNumber={invoiceNumber}; semantics of "mark Paid" (does it create a payment record?) not stated.
- User story: As an integrator, I want invoices with their payments and allocations over an API, so that external accounting or portals stay in sync.
- Actors: API client / integrator.
- UI generation: n-a (API)
- Priority: P1
- Evidence: https://support.ezfacility.com/hc/en-us/articles/11297336305691-December-15th-2022-Release-Notes, https://support.ezfacility.com/hc/en-us/articles/20241459046683-November-8th-2023-Release-Notes, https://support.ezfacility.com/hc/en-us/articles/25134483797531-April-24th-2024-Release-Notes

### BIL-24 Outsourced billing and collections service (legacy)
- Sub-features: vendor-run billing, collections and delinquent-account follow-up offered alongside the software (from the eFit Financial 2010 and Member Solutions 2011 acquisitions).
- Settings / options: none (service, not software).
- Rules / limits: only referenced 2010-2011; no current help-center coverage.
- User story: As an owner, I want the vendor to chase delinquent members for me, so that I do not staff a collections function.
- Actors: Vendor billing team, Owner.
- UI generation: n-a
- Priority: P2 (legacy, 2010-2011 references)
- Evidence: https://www.ezfacility.com/press-news/press-releases/ezfacility-acquires-efit-financial, https://www.ezfacility.com/blog/benefits-of-using-software-to-manage-your-facility

## Payments & Merchant

### PAY-01 Take payment and allocate to billed items
- Sub-features: entry points: "Make Payment" on client detail, Billing > Payments > "Add a Payment", "$" icon on an invoice row, "Pay Now" on group invoices, Finish & Pay at sale; choose a predefined total or type an amount; method; memo; "Take Payment" then allocation screen; auto-split across open items oldest first with manual per-item override; "Apply Payment"; simplified allocation view listing open invoices and billed items.
- Settings / options: payment amount presets (inferred: invoice balance / total due); payment method dropdown (see PAY-02); memo; per-item applied amount.
- Rules / limits: partial application allowed, remainder stays as account credit; allocation list pages at 75 items (2023-06-28); warning when taking payment for a client outside their home location (2024-05-08); several payments per invoice supported; the cash payment screen does not work out change due (confirmed gap in a Q&A, would need a development request)
- User story: As a front-desk user, I want to take money once and spread it over specific charges, so that partial and multi-invoice payments are recorded accurately.
- Actors: Front Desk, Admin.
- UI generation: both
- Priority: P0
- Evidence: https://support.ezfacility.com/hc/en-us/articles/4403485806363-How-to-Apply-a-Payment-in-EZFacility-Classic, https://support.ezfacility.com/hc/en-us/articles/4402433808923-How-to-Take-a-Payment, https://support.ezfacility.com/hc/en-us/articles/16731304236571-June-28th-2023-Release-Notes, https://support.ezfacility.com/hc/en-us/articles/25551222201627-May-8th-2024-Release-Notes, https://support.ezfacility.com/hc/en-us/articles/22122496577179-January-17th-2024-Release-Notes, https://support.ezfacility.com/hc/en-us/articles/17574439837467-August-2nd-2023-Release-Notes, https://www.youtube.com/watch?v=TWNQ4cTiEFs (t=40:12)

### PAY-02 Payment method configuration
- Sub-features: account-level checklist of optional payment methods; external ("Ext") methods record money taken outside the system and never charge a card; Bank Transfer method (2023-06-28) selectable in client payments, package sale and group registration and reportable in deposit/revenue reports; processed methods (card, direct debit) available when a processor is integrated.
- Settings / options: Optional Payment Methods checkboxes; known method kinds: credit/debit card (processed), direct debit EFT/ACH (processed), cash, check ("cheque" in UK locale), Bank Transfer (record-only), external card/wallet methods such as PayPal or CashApp (record-only), gift card and Money on Account at POS (other cluster).
- Rules / limits: unchecked methods disappear from the take-payment dropdown; Bank Transfer is non-electronic, true ACH/direct debit must go through the processor; vendor recommends disabling external methods.
- User story: As an owner, I want to control which tender types staff can record, so that reconciliation matches how we actually take money.
- Actors: Owner/Admin.
- UI generation: both
- Priority: P0
- Evidence: https://support.ezfacility.com/hc/en-us/articles/4402433808155-How-to-Set-Up-Payment-Options, https://support.ezfacility.com/hc/en-us/articles/21173246031771-Setting-Up-Billing-Preferences, https://support.ezfacility.com/hc/en-us/articles/16731304236571-June-28th-2023-Release-Notes, https://support.ezfacility.com/hc/en-us/articles/22968789591963-February-15th-2024-Release-Notes, https://www.ezfacility.com/features/merchant-processing

### PAY-03 Client payment ledger and receipts
- Sub-features: client Billing > Payments list with time-range dropdown; open a receipt by number; receipt shows Total Received vs Total Applied, refunded amount and remaining applied amount; filter voided / not voided / both; print receipt with configurable footer; receipt reachable from the invoice's Receipt column.
- Settings / options: range selector (default range hides older payments); voided filter (voided / not voided / both); Receipt Footer; Payments list range goes up to "past 90 days" or a custom range
- Rules / limits: refunds appear as separate negative payment rows (amount in parentheses); card type and bank details hidden from users lacking the refund permission (2023-06-28).
- User story: As a front-desk user, I want a client's payment history with receipts, so that I can answer "did you get my payment" immediately.
- Actors: Front Desk, Admin.
- UI generation: both
- Priority: P0
- Evidence: https://support.ezfacility.com/hc/en-us/articles/23857067036827-How-to-View-Payments-Made-on-a-Client-s-Profile, https://support.ezfacility.com/hc/en-us/articles/4402426355099-How-to-Void-a-Payment, https://support.ezfacility.com/hc/en-us/articles/4403486096667-How-to-Refund-Payments-Full-Partial-in-EZFacility-Classic, https://support.ezfacility.com/hc/en-us/articles/21173246031771-Setting-Up-Billing-Preferences, https://support.ezfacility.com/hc/en-us/articles/16731304236571-June-28th-2023-Release-Notes, https://www.youtube.com/watch?v=iR4MVBspNlQ (t=25:48-26:50)

### PAY-04 Void payment
- Sub-features: X action on a payment row; reason prompt; Submit/Cancel; voided payments hidden by default and retrievable via filter.
- Settings / options: void reason (free text, required); voided filter.
- Rules / limits: invoice(s) the payment covered revert to open; intended for bounced checks, processor fraud flags and wrong tender recorded; not a refund (no money returned); trainer guidance: use void for external/check-type payments and for account credit added by mistake (Billing > Payments > Void); avoid voiding card payments because the record is lost and no refund is issued; for a chargeback, let the processor handle it and then void the payment
- User story: As a front-desk user, I want to cancel a payment that never really cleared, so that the invoice shows as owed again.
- Actors: Owner/Admin, Front Desk.
- UI generation: both
- Priority: P0
- Evidence: https://support.ezfacility.com/hc/en-us/articles/4403493305499-How-to-Void-a-Payment-in-EZFacility-Classic, https://support.ezfacility.com/hc/en-us/articles/4402426355099-How-to-Void-a-Payment, https://www.youtube.com/watch?v=iR4MVBspNlQ (t=45:15), https://www.youtube.com/watch?v=a7-8-cHwB8Y (t=57:23-58:24)

### PAY-05 Refunds (full, partial, external, on-account)
- Sub-features: Refund action on a receipt and on the client's On Account balance; full refund = un-apply ("Unpay") the payment from its item(s), then refund; partial refund = lower item price / add discount / reverse an item so Total Applied < Total Received, then refund the difference; refund amount editable; refund method chooser; comments/memo; refund recorded as a separate negative payment; "External" refund for non-integrated gateways; multi-payment refund in one action; refund permission.
- Settings / options: refund method: original card (processed), different card (on file or keyed), External, cash/other tender (inferred); user permission "billing refund" (hides card type and bank data, gates the button); refund issue date editable for reporting (other cluster article).
- Rules / limits: processed card refunds only on EZPayments, Constellation Payments (CSI Pay) and Global Payments; other gateways need an External refund here plus a manual refund in the gateway portal; direct debit (EFT/ACH) refunds are always manual; refund leaves the invoice open with a balance (void or re-collect separately); refunding two or more payments at once makes amounts read-only (full amounts only, 2024-03-14); button disabled with zero on account; price adjustment and refund are two separate steps.
- User story: As an admin, I want to return all or part of a payment to the payer with a recorded reason, so that the ledger and the processor agree.
- Actors: Owner/Admin, Front Desk with refund permission.
- UI generation: both
- Priority: P0
- Evidence: https://support.ezfacility.com/hc/en-us/articles/4403486096667-How-to-Refund-Payments-Full-Partial-in-EZFacility-Classic, https://support.ezfacility.com/hc/en-us/articles/25737423648923-How-to-Partially-Refund-a-Sale, https://support.ezfacility.com/hc/en-us/articles/4415441364635-How-to-Process-a-Refund-Remove-a-Client-from-a-Group, https://support.ezfacility.com/hc/en-us/articles/16731304236571-June-28th-2023-Release-Notes, https://support.ezfacility.com/hc/en-us/articles/23807158781211-March-14th-2024-Release-Notes

### PAY-06 Stored payment methods (card on file, bank account)
- Sub-features: client "Billing Details" holding stored card and/or direct-debit bank account; default for saving a manually keyed card; add a card on file manually; stored card flagged for autopay; Self-Service API returns redacted stored card + expiry and accepts updates (2024-06-19); clients update payment info in the portal/app; direct-debit account has Verify action and suspended status/date (L&Z); "Auto Pay Errors" record of failed autopay attempts that can be cleared (where it is shown and who clears it are not documented; presumably a staff-facing list).
- Settings / options: Save Credit Card Info For Manual Payments default (values include "Yes", "Always Save"; others not named); card "use for Auto Pay" flag; direct-debit account status active / suspended (+ suspension date); verified flag.
- Rules / limits: save-card default applies to manual staff payments only, not Online Registration, Self-Service or POS; default is not applied when the client already has a saved card and staff key a new one; adding bank details to profiles with multiple emails fixed 2024-02-15; re-verify must not duplicate the processor-side account (fix 2024-04-10); clearing Auto Pay Errors failed until the 2023-06-12 fix; staff can edit the stored card in the client's billing info; in Self-Service a client can replace a stored card but never fully remove it
- User story: As a member, I want my card or bank account kept on file securely, so that dues and future purchases are collected without re-entering details.
- Actors: Client, Front Desk, Admin, System.
- UI generation: both
- Priority: P0
- Evidence: https://support.ezfacility.com/hc/en-us/articles/4402433808155-How-to-Set-Up-Payment-Options, https://support.ezfacility.com/hc/en-us/articles/21173246031771-Setting-Up-Billing-Preferences, https://support.ezfacility.com/hc/en-us/articles/54387128581147-How-to-Add-a-Card-on-File-Manually (title only, body not read), https://support.ezfacility.com/hc/en-us/articles/26750732215835-June-19th-2024-Release-Notes, https://support.ezfacility.com/hc/en-us/articles/22968789591963-February-15th-2024-Release-Notes, https://support.ezfacility.com/hc/en-us/articles/24695840840603-April-10th-2024-Release-Notes, https://support.ezfacility.com/hc/en-us/articles/16308423683355-June-12th-2023-Release-Notes, https://www.ezfacility.com/blog/features-fixes-automatic-credit-card-notification-emails, https://www.youtube.com/watch?v=iR4MVBspNlQ (t=27:51)

### PAY-07 Card expiry notifications and expiring-cards report
- Sub-features: automatic email to the client's profile address ahead of stored-card expiry; report of expired cards and cards expiring within 60 days with export.
- Settings / options: Expired Credit Card Notifications lead time: 1 month, 2 months, or both; scope: all stored cards / autopay cards only; report option "Report on Only Clients with Open Auto-Pay Invoices" Yes/No.
- Rules / limits: 2014 blog describes the same choices as 60 days / 30 days / both; report window fixed at 60 days; meaningful only with an integrated merchant account.
- User story: As an owner, I want clients warned before their card expires and a list to chase, so that autopay does not fail for avoidable reasons.
- Actors: System, Client, Owner/Admin.
- UI generation: both
- Priority: P1
- Evidence: https://support.ezfacility.com/hc/en-us/articles/4403493392539-Expired-Expiring-Credit-Cards, https://support.ezfacility.com/hc/en-us/articles/21173246031771-Setting-Up-Billing-Preferences, https://www.ezfacility.com/blog/features-fixes-automatic-credit-card-notification-emails

### PAY-08 Decline notifications (staff alert and client notice)
- Sub-features: location-level alert email address notified of card declines; frequency choice between one digest email and one email per failed transaction; client-facing decline notification email; AR report surfaces the decline message per invoice.
- Settings / options: Alert email; failed-transaction email mode: single summary ("One Failed Transaction Email") / per transaction; Credit Card Decline Notifications scope: all cards / autopay cards only.
- Rules / limits: only relevant when payments are processed through the platform; terminal timeouts/network errors must not raise a failed-payment email (Clover fix 2024-01-17).
- User story: As an owner, I want to know immediately when a charge fails and have the client told too, so that failed dues are recovered quickly.
- Actors: System, Owner/Admin, Client.
- UI generation: both (staff alert documented in Classic; client notice in New Billing Preferences)
- Priority: P0
- Evidence: https://support.ezfacility.com/hc/en-us/articles/4403486991515-Failed-Transaction-Email, https://support.ezfacility.com/hc/en-us/articles/21173246031771-Setting-Up-Billing-Preferences, https://support.ezfacility.com/hc/en-us/articles/4403493405851-Accounts-Receivable, https://support.ezfacility.com/hc/en-us/articles/22122496577179-January-17th-2024-Release-Notes

### PAY-09 Autopay collection run (scheduled charging of due invoices)
- Sub-features: background "auto payment jobs" that charge the stored card or direct-debit account for autopay-flagged invoices/schedule entries on their due dates; card type captured on resulting payments for revenue reporting; failures feed decline notices, AR and direct-debit failure reports; for the L&Z direct-debit processor the run targets the invoice due date and otherwise the processor's next available processing date.
- Settings / options: invoice autopay flag (BIL-17); stored method autopay flag (PAY-06); retry policy not documented.
- Rules / limits: requires billing details on the client and an integrated processor; L&Z lead-time and bank-holiday constraints shift the collection date (2024-02-15); auto-pay job payments must carry card type (fix 2023-08-31).
- User story: As an owner, I want due instalments charged automatically on their due dates, so that recurring revenue arrives without staff action.
- Actors: System, Owner/Admin, Client.
- UI generation: both (back-end)
- Priority: P0
- Evidence: https://support.ezfacility.com/hc/en-us/articles/18408526583067-August-31st-2023-Release-Notes, https://support.ezfacility.com/hc/en-us/articles/22968789591963-February-15th-2024-Release-Notes, https://support.ezfacility.com/hc/en-us/articles/4403493405851-Accounts-Receivable, https://support.ezfacility.com/hc/en-us/articles/17657710657051-How-to-Create-and-Sell-a-Pre-Defined-Item, https://www.ezfacility.com/features/billing-payments, https://www.ezfacility.com/blog/the-top-5-advantages-of-gun-range-management-software

### PAY-10 ACH / direct debit processing
- Sub-features: bank-account autopay via an ACH/EFT processor; "Direct Debit Batch" screen; report of failed/declined direct debits by date range with export; account Verify and suspension handling (L&Z); NACHA-file style processor with optional per-routing-number bypass of ABA validation (2025-04-09).
- Settings / options: processors named: L&Z (DD/ACH), NACHA ACH; direct-debit account status active / suspended; report Start/End Date; NACHA property: ABA-validation bypass list.
- Rules / limits: failures report only exists with ACH integrated; refunds of direct debits are manual; Direct Debit Batch was missing from New UI until 2025-04-09; autopay date follows processor availability.
- User story: As an owner, I want to collect dues from bank accounts in batches and see what bounced, so that I pay lower fees than cards and can chase failures.
- Actors: System, Owner/Admin, Client.
- UI generation: both
- Priority: P0 (ACH via our processor); batch-file/NACHA and third-party DD processors v2-adapter
- Evidence: https://support.ezfacility.com/hc/en-us/articles/4403493437211-Direct-Debit-Failures, https://support.ezfacility.com/hc/en-us/articles/22968789591963-February-15th-2024-Release-Notes, https://support.ezfacility.com/hc/en-us/articles/24695840840603-April-10th-2024-Release-Notes, https://support.ezfacility.com/hc/en-us/articles/36516560976539-April-9th-2025-Release-Notes, https://support.ezfacility.com/hc/en-us/articles/16731304236571-June-28th-2023-Release-Notes, https://www.ezfacility.com/features/merchant-processing

### PAY-11 Merchant processor integration (native processing and gateways)
- Sub-features: built-in processing brand (EZPayments) so no separate gateway; one-time and recurring payments in one place; tokenisation / encryption; supported legacy processors and gateways with differing capability (refund-to-card only on some); UK variant built for Strong Customer Authentication with 3-D Secure logging; processor presence unlocks autopay settings, expiry reports and processed refunds.
- Settings / options: processors named over time: EZPayments (Pyxis back end referenced), Constellation Payments / CSI Pay / CSI-CC Secure, Global Payments, Clover (card-present), L&Z and NACHA (ACH), "other gateways" (external refunds only); per-location processor (reports refer to locations with a current or past EZPayments processor).
- Rules / limits: features gated on "merchant processor integrated"; PCI DSS Level 1 claimed; merchant underwriting and rate quoting are a vendor service; UK webinar quoted a typical e-commerce rate of 1.8% plus 20p per transaction with preferential rates for the vendor's customers and final rates set after application (informational, not a product rule)
- User story: As an owner, I want card processing built into the platform, so that payments, refunds and reconciliation happen in one system.
- Actors: Owner/Admin, vendor payment services, System.
- UI generation: both
- Priority: P0 (single processor: Stripe Connect onboarding); additional gateways and underwriting v2-adapter
- Evidence: https://www.ezfacility.com/features/merchant-processing, https://www.ezfacility.com/partners, https://support.ezfacility.com/hc/en-us/articles/4403486096667-How-to-Refund-Payments-Full-Partial-in-EZFacility-Classic, https://support.ezfacility.com/hc/en-us/articles/22122496577179-January-17th-2024-Release-Notes, https://support.ezfacility.com/hc/en-us/articles/24225032928027-March-27th-2024-Release-Notes, https://www.ezfacility.com/blog/software-release-ezpayments-uk-smartwaiver, https://www.ezfacility.com/blog/the-top-5-advantages-of-gun-range-management-software, https://www.ezfacility.com/blog/ezfacility-saas-partner-deep-dive, https://www.youtube.com/watch?v=wTcpTun-eyM (t=20:27)

### PAY-12 EMV card terminals (EZPayments, Lane 3000)
- Sub-features: register a countertop EMV terminal against a location (Location Settings > EMV-Terminals > Add Terminal); mark active; mark one terminal default so it pre-selects for EMV payments; per-user permission to use terminals; device provisioning (network, application download, date/time) done on the device.
- Settings / options: Terminal name; Terminal Code (issued by vendor payment services); Active; Default; user "EMV Permission".
- Rules / limits: EZPayments accounts only; other device models follow a different provisioning guide; users without the permission cannot connect/use a terminal; terminals are sold/supplied by the vendor.
- User story: As a front-desk user, I want to push a charge to a chip-and-PIN terminal at my desk, so that card-present payments are recorded automatically.
- Actors: Account admin, Front Desk, vendor payment services.
- UI generation: both (not stated)
- Priority: v2-adapter
- Evidence: https://support.ezfacility.com/hc/en-us/articles/21171478349211-How-to-Setup-your-EZPayments-EMV-Terminal-in-EZFacility

### PAY-13 Clover terminal integration (UK)
- Sub-features: per-location OAuth connection to a Clover merchant ("Clover Authentication" page with Connect); merchant picker when the login has several merchants; stores merchant id and API token; terminals paired through Clover's cloud display app; terminal receipt printing; covers both online (e-commerce) payments and Clover Flex terminals (chip and PIN, contactless, Apple Pay, Google Pay; portable, on Wi-Fi); the sale amount is pushed from the platform to the terminal and the result posts back automatically
- Settings / options: location flag "Clover EMV" (enabled by vendor staff only); user permission "Account Administration"; Merchant ID; API Token.
- Rules / limits: UK clients only; page hidden unless the flag is on and the user holds the permission; terminal set-up completes in Clover's portal; timeouts after an EMV transaction must not send failed-payment emails (2024-01-17); receipt printing fix 2025-04-09; staff cannot edit the amount on the terminal; onboarding as presented: Clover approval usually under a week, vendor links the account in under an hour, terminals shipped with a user guide; Clover contract has an initial 18-month term while the vendor gateway layer follows the platform contract term
- User story: As a UK facility admin, I want to link my Clover account once, so that desk payments run on Clover terminals and post back automatically.
- Actors: Location admin, vendor staff, Clover.
- UI generation: New
- Priority: v2-adapter
- Evidence: https://support.ezfacility.com/hc/en-us/articles/14101589968923-Clover-Terminal-Set-Up-UK-Clients-Only, https://support.ezfacility.com/hc/en-us/articles/22122496577179-January-17th-2024-Release-Notes, https://support.ezfacility.com/hc/en-us/articles/36516560976539-April-9th-2025-Release-Notes, https://www.youtube.com/watch?v=wTcpTun-eyM (t=15:20-19:25, t=24:32, t=29:35-31:37)

### PAY-14 Credit card surcharging
- Sub-features: pass processing cost to the payer on credit transactions; credit-only detection by card BIN; disclosure at point of sale and on receipts; onboarding help and signage templates.
- Settings / options: surcharge rate (marketed as up to about 3%); enablement per merchant (inferred).
- Rules / limits: credit cards only (not debit); only where state law permits; card-brand rules apply.
- User story: As an owner, I want to recover card fees on credit transactions lawfully, so that margins are protected.
- Actors: Owner/Admin, Client, System.
- UI generation: not stated
- Priority: P1
- Evidence: https://www.ezfacility.com/features/merchant-processing

### PAY-15 Digital wallets and tap-to-pay
- Sub-features: Apple Pay, Google Pay and contactless/tap-to-pay acceptance alongside card, debit, ACH/EFT and card on file; ID-card scan to charge to account (campus pages).
- Settings / options: not documented.
- Rules / limits: marketing-level evidence only; channel (online vs terminal) not specified; one channel is now evidenced: Clover Flex terminals (UK) take contactless, Apple Pay and Google Pay
- User story: As a client, I want to pay with my phone wallet, so that checkout is faster.
- Actors: Client, Front Desk.
- UI generation: not stated
- Priority: P1
- Evidence: https://www.ezfacility.com/features/merchant-processing, https://www.ezfacility.com/industries/campus-recreation-software, https://www.youtube.com/watch?v=wTcpTun-eyM (t=15:20-19:25)

### PAY-16 Processor disbursement reconciliation report
- Sub-features: report of processor payouts ("Pyxis Disbursements") for a date range with optional transaction detail, used to match bank deposits to the deposit report by transaction id.
- Settings / options: date range (max 1 month since 2024-04-10); Show Details; detail columns: Transaction Date, Card Holder, Client, Card Number, Card Type, Txn ID.
- Rules / limits: only for locations with a current or past EZPayments processor; data can lag 1-5 business days.
- User story: As an owner, I want each bank deposit broken down into the payments it contains, so that I can reconcile my bank statement.
- Actors: Owner/Admin, bookkeeper.
- UI generation: both (report)
- Priority: P1
- Evidence: https://support.ezfacility.com/hc/en-us/articles/24225032928027-March-27th-2024-Release-Notes, https://support.ezfacility.com/hc/en-us/articles/24695840840603-April-10th-2024-Release-Notes

### PAY-17 Chargeback and transaction sync
- Sub-features: processor-side transactions, refunds and chargebacks flow back into the platform automatically.
- Settings / options: not documented.
- Rules / limits: marketing claim only; no help article describes how a chargeback is represented on the client ledger.
- User story: As an owner, I want disputes to show up against the original payment, so that my books reflect money clawed back.
- Actors: System, Owner/Admin.
- UI generation: not stated
- Priority: P1
- Evidence: https://www.ezfacility.com/features/merchant-processing

### PAY-18 Self-service payment of open invoices
- Sub-features: clients see and pay open invoices in the Self-Service portal/app; update stored payment info; staff-created invoices become payable there immediately.
- Settings / options: none found in this cluster (portal settings live in the engagement cluster).
- Rules / limits: invoice emails carry no pay link; clients must sign in to Self-Service; 2017 option to bar clients with outstanding balances from Self-Service.
- User story: As a client, I want to pay what I owe online, so that I do not have to call or visit the desk.
- Actors: Client, Parent/Guardian.
- UI generation: both
- Priority: P0
- Evidence: https://support.ezfacility.com/hc/en-us/articles/25419259427099-How-to-Email-an-Invoice-to-a-Client, https://support.ezfacility.com/hc/en-us/articles/26114234694043-How-to-Create-an-Invoice-for-Un-invoiced-Items, https://www.ezfacility.com/features/billing-payments, https://www.ezfacility.com/blog/the-top-5-advantages-of-gun-range-management-software

### PAY-19 Magnetic card swipe entry (legacy)
- Sub-features: "Credit Card Swipe" input row in the online sign-up/payment form.
- Settings / options: none.
- Rules / limits: removed from EZSignup on 2023-04-18.
- User story: As a front-desk user, I want to swipe a card into the payment form, so that I do not key the number.
- Actors: Front Desk.
- UI generation: Classic-era
- Priority: P2 (removed 2023-04-18)
- Evidence: https://support.ezfacility.com/hc/en-us/articles/14655161654811-April-18th-2023-Release-Notes

## POS & Inventory

### POS-01 POS application launch, access and register selection
- Sub-features: POS runs as a separate browser app opened from the admin product ("Launch Now", new tab) or from a bookmarkable direct link with the same staff credentials; register picker at top of the register screen; multi-location accounts can list and switch to registers of other connected locations; works on desktop or tablet (responsive).
- Settings / options: role privilege granting POS access; account-level IP allow-list restricting logins; per-role IP-restriction bypass; active Cash Register (per POS session, inferred); POS generation "v1" vs "v.2 / New Point of Sale" (some features v.2 only).
- Rules / limits: access depends on user role; IP restriction blocks logins from non-approved IPs unless role bypasses; a fix dated 2023-09-13 restored viewing/switching other connected locations' registers; POS transaction dates follow the user's culture/locale (fix 2024-06-05); legacy (2013-03-17 release): the POS was rebuilt as a standalone desktop window (Adobe AIR) needing its own sign-in, with large touchscreen-friendly icons, and had a check-in function built in (see CHK-01); the browser "New Point of Sale" was introduced around April 2020 with an open training on April 8.
- User story: As a cashier, I want to open the register app directly and pick my till, so that I can start selling without navigating the back office.
- Actors: admin (grants access), cashier / front desk.
- UI generation: both (the "New Point of Sale" is launched from Classic and from the New UI)
- Priority: P0
- Evidence: https://support.ezfacility.com/hc/en-us/articles/34418890607643-How-to-Launch-the-New-Point-of-Sale, https://support.ezfacility.com/hc/en-us/articles/34414402160795-How-to-View-Products-from-your-Product-Categories, https://support.ezfacility.com/hc/en-us/articles/23505030472475-How-to-View-Products-from-your-Product-Categories, https://support.ezfacility.com/hc/en-us/articles/18741009680795-September-13th-2023-Release-Notes, https://support.ezfacility.com/hc/en-us/articles/26498179644187-June-5th-2024-Release-Notes, https://www.ezfacility.com/press-news/press-releases/ezfacility-releases-cutting-edge-fitness-point-of-sale-solution, https://www.ezfacility.com/features/billing-payments, https://www.youtube.com/watch?v=unZH32QU1nc (t=08:20), https://www.youtube.com/watch?v=IM8m1sUsMdw (t=36:50)

### POS-02 Cash registers and register favourites
- Sub-features: CRUD of named registers; per-register "favourites" (pinned products shown for that register).
- Settings / options: Register Name; Cash Register Favorites tab with per-register product selection and "Enable Favorite" toggle.
- Rules / limits: favourites are only meaningful with more than one register; registers belong to a location (inferred from multi-location register switching); marketing calls register layouts "customizable".
- User story: As an owner, I want each till to show the products it actually sells, so that the snack bar and pro shop each get a short, relevant grid.
- Actors: owner/admin.
- UI generation: both (favourites documented in New only)
- Priority: P0 (registers); favourites P1
- Evidence: https://support.ezfacility.com/hc/en-us/articles/34419084373915-Setting-Up-Cash-Registers, https://support.ezfacility.com/hc/en-us/articles/24547185574939-How-to-Setup-Point-of-Sale, https://support.ezfacility.com/hc/en-us/articles/18741009680795-September-13th-2023-Release-Notes, https://www.ezfacility.com/press-news/press-releases/ezfacility-releases-cutting-edge-fitness-point-of-sale-solution, https://www.ezfacility.com/features/billing-payments

### POS-03 Product categories and subcategories
- Sub-features: hierarchical categories (parent > subcategory); category carries default revenue category and tax codes; edit/delete.
- Settings / options: Category name; Revenue Category (optional); Tax Code(s) (multi-select checkboxes); parent category.
- Rules / limits: if the chosen revenue category has a default tax rate, the matching tax codes are pre-ticked; tax codes are defined in billing administration and should exist before products; Classic auto-saves a new category name on blur; nesting depth not stated; legacy 2013 demo: categories are reordered by drag and drop, and dropping one category onto another makes it a subcategory.
- User story: As an admin, I want products grouped with inherited tax and revenue mapping, so that sales post to the right ledger lines without per-product setup.
- Actors: owner/admin.
- UI generation: both
- Priority: P0
- Evidence: https://support.ezfacility.com/hc/en-us/articles/34419191751451-Setting-Up-Product-Categories-Inventory, https://support.ezfacility.com/hc/en-us/articles/34419085151003-How-to-Create-a-Product-Subcategory, https://support.ezfacility.com/hc/en-us/articles/34419095821979-How-to-Edit-a-Product-Category, https://support.ezfacility.com/hc/en-us/articles/24547185574939-How-to-Setup-Point-of-Sale, https://www.youtube.com/watch?v=unZH32QU1nc (t=06:50, t=07:30)

### POS-04 Product brands and suppliers
- Sub-features: brand lookup list; supplier list with contact information; both selectable on a product; sales reports by brand and by supplier exist (reporting cluster).
- Settings / options: Brand name; Supplier info (fields not enumerated publicly).
- Rules / limits: press material additionally claims "supplier contract tracking" (no help-centre detail).
- User story: As a buyer, I want products tied to brand and supplier, so that I can analyse sales and reorder from the right vendor.
- Actors: owner/admin.
- UI generation: both
- Priority: P1
- Evidence: https://support.ezfacility.com/hc/en-us/articles/34419081377307-Setting-Up-Product-Brands, https://support.ezfacility.com/hc/en-us/articles/34419162852891-Setting-Up-Product-Suppliers, https://support.ezfacility.com/hc/en-us/articles/24547185574939-How-to-Setup-Point-of-Sale, https://www.ezfacility.com/press-news/press-releases/ezfacility-releases-cutting-edge-fitness-point-of-sale-solution

### POS-05 Product master data
- Sub-features: create/edit/delete sellable products inside a category; product name doubles as the register button label; barcode-scannable SKU.
- Settings / options: Brand; Supplier; Revenue Category (or "Inherit from product category"); Tax Code(s); Product Name; Product ID (unique); Description (admin-facing, e.g. size); SKU; Unit Price (pre-tax, pre-discount); Qty per Unit; Buying Price (cost); Units in Stock; Discount %; Reorder Level (-1 = never appears on reorder report).
- Rules / limits: Product ID must be unique; Qty per Unit is described as record-keeping that affects the stock count on sale (ambiguous, see unknowns); tax auto-attaches when the revenue category already has a tax code; POS inventory (items, brands and similar lookups) can be bulk-imported during onboarding; documents/waivers cannot be attached to POS items (only memberships, packages and groups).
- User story: As an admin, I want a product record with price, cost, SKU and tax mapping, so that the register, inventory and margin reports all draw from one source.
- Actors: owner/admin.
- UI generation: both
- Priority: P0
- Evidence: https://support.ezfacility.com/hc/en-us/articles/34419191751451-Setting-Up-Product-Categories-Inventory, https://support.ezfacility.com/hc/en-us/articles/34419086218779-How-to-Edit-a-Product, https://support.ezfacility.com/hc/en-us/articles/24547185574939-How-to-Setup-Point-of-Sale, https://www.youtube.com/watch?v=j4Rn9joKKpQ (t=28:34), https://www.youtube.com/watch?v=zzEUXdDPMyU (t=11:24)

### POS-06 Inventory adjustments and stock tracking
- Sub-features: stock quantity per product; adjustment from product edit form; "Quick Inventory Update" panel driven by SKU entry or barcode scan; stock decremented by sales (inferred from Units in Stock + reorder reporting).
- Settings / options: adjustment mode = "Make an adjustment (+ or -)" (delta) | "Set Inventory" (absolute overwrite); Quantity; Date/Time of Adjustment (default now); Adjustment Reason = Other (default) | Discrepancy | Bought New Stock (New UI text lists only bought new stock / other); Comment (optional).
- Rules / limits: adjustments are timestamped and reasoned (implies a ledger); Reorder Level drives the reorder report and marketed "automated low-stock / reorder alerts".
- User story: As a stock keeper, I want to scan an item and post a received quantity or a count correction with a reason, so that on-hand stock stays trustworthy.
- Actors: owner/admin, stock keeper.
- UI generation: both
- Priority: P0
- Evidence: https://support.ezfacility.com/hc/en-us/articles/34419193012379-How-to-Add-Inventory-to-a-Product, https://support.ezfacility.com/hc/en-us/articles/34419191751451-Setting-Up-Product-Categories-Inventory, https://support.ezfacility.com/hc/en-us/articles/24547185574939-How-to-Setup-Point-of-Sale, https://support.ezfacility.com/hc/en-us/articles/34419009666459-Inventory-Re-order-Report, https://www.ezfacility.com/press-news/press-releases/ezfacility-releases-cutting-edge-fitness-point-of-sale-solution

### POS-07 Register product browsing and cart building
- Sub-features: product grid filtered by category (Classic: category tiles + Home; New: category filter with "All"); Classic splits a "Products & Equipment" tab with Products / Equipment toggles; add to cart by tile click (qty 1), typed SKU + Enter, or barcode scan into the search field; scanner input auto-adds and refocuses, with a failed-scan notification; POS distinguishes typed from scanned input.
- Settings / options: Search SKU / Search Products field; category filter; register favourites (POS-02).
- Rules / limits: each click/scan adds one unit; a scan only works with focus in the search field (Classic), newer POS refocuses automatically.
- User story: As a cashier, I want to scan or tap items into a cart, so that I can ring up a customer in seconds.
- Actors: cashier.
- UI generation: both
- Priority: P0
- Evidence: https://support.ezfacility.com/hc/en-us/articles/34414402160795-How-to-View-Products-from-your-Product-Categories, https://support.ezfacility.com/hc/en-us/articles/23505030472475-How-to-View-Products-from-your-Product-Categories, https://support.ezfacility.com/hc/en-us/articles/34418766515099-How-to-Add-Products-to-the-Shopping-Cart-and-Finish-Sale, https://support.ezfacility.com/hc/en-us/articles/23505052562971-How-to-Add-Products-to-the-Shopping-Cart-and-Finish-Sale, https://support.ezfacility.com/hc/en-us/articles/4405137541403-Using-Bluetooth-Scanners

### POS-08 Attach client to sale
- Sub-features: client search by name or Member ID with dropdown results; inline quick-add of a new client (name + email) from the register or the sale-complete screen; anonymous (walk-in) sales allowed.
- Settings / options: "Add Client to Transaction" (default on) and "Save Client" (persist to client database) on the quick-add form.
- Rules / limits: client is optional, but required for card on file, Money on Account, Pay Later and equipment rentals; Classic equipment search needs 3+ letters; quick-added client is only persisted when Save Client is chosen (sale-complete flow) whereas a client created during an equipment rental stays in the database; fix 2025-04-09: POS quick-add now saves organization and phone.
- User story: As a cashier, I want to link the sale to a member, so that it lands on their account and can use their stored payment methods.
- Actors: cashier.
- UI generation: both
- Priority: P0
- Evidence: https://support.ezfacility.com/hc/en-us/articles/34418802043931-How-to-Search-for-a-Customer-in-the-POS, https://support.ezfacility.com/hc/en-us/articles/34418821391131-How-to-Search-for-a-Customer-in-the-POS, https://support.ezfacility.com/hc/en-us/articles/23505069345947-How-to-Search-for-a-Client-in-the-POS, https://support.ezfacility.com/hc/en-us/articles/23505052562971-How-to-Add-Products-to-the-Shopping-Cart-and-Finish-Sale, https://support.ezfacility.com/hc/en-us/articles/34418925611803-How-to-Email-P-O-S-Receipts-from-the-Sale-Complete-Page, https://support.ezfacility.com/hc/en-us/articles/34418782382235-How-to-Rent-Equipment-in-EZFacility-Classic, https://support.ezfacility.com/hc/en-us/articles/36516560976539-April-9th-2025-Release-Notes

### POS-09 Cart line quantity and price override
- Sub-features: expand a cart line to step quantity and unit price up/down; totals recalc live.
- Settings / options: Classic: enabling setting in POS General Preferences (name not published); New: a dedicated user permission for price changes.
- Rules / limits: items always enter the cart at qty 1; price override is restricted (most users lack it per New article); manual price edits are itemised on the receipt as a discount.
- User story: As a supervisor, I want to correct a quantity or override a price on the spot, so that I can handle bundles and goodwill adjustments without voiding the sale.
- Actors: cashier (quantity), privileged user (price).
- UI generation: both (gating differs: preference in Classic, permission in New)
- Priority: P0 (quantity); price override P1
- Evidence: https://support.ezfacility.com/hc/en-us/articles/34418830364443-How-to-Edit-Quantity-or-Price-of-items-in-the-Point-of-Sale-Cart, https://support.ezfacility.com/hc/en-us/articles/34418850910747-How-to-Edit-Quantity-or-Price-of-items-in-the-Point-of-Sale-Cart, https://support.ezfacility.com/hc/en-us/articles/23505046070811-How-to-Edit-Quantity-or-Price-of-items-in-the-Point-of-Sale-Cart, https://support.ezfacility.com/hc/en-us/articles/34418941582747-New-Point-of-Sale-Customizing-the-Receipt

### POS-10 POS discounts (preset, custom, client-level)
- Sub-features: "Add Discounts" in cart; facility-defined preset Flat Discounts and Percentage Discounts; ad-hoc Custom Discount (amount + Percent/Flat); scope "Apply to Sale" (whole cart) or "Apply To Selected" (ticked lines); a client-profile global percentage discount carries into POS sales; product-level Discount % field.
- Settings / options: preset discount list (name, type flat|percent, value) - configuration screen not documented; custom amount; Percent/Flat toggle; scope.
- Rules / limits: discounts are shown on receipts; multi-item discount rounding errors were fixed 2025-04-09 (allocation across lines must be penny-exact); client global % discount carry-over fixed 2024-06-05.
- User story: As a cashier, I want to apply a staff or promo discount to one item or the whole basket, so that pricing exceptions are recorded rather than hidden in price edits.
- Actors: cashier; admin defines presets.
- UI generation: both
- Priority: P0 (custom + preset); client-level discount P1
- Evidence: https://support.ezfacility.com/hc/en-us/articles/34418751007771-How-to-Discount-Individual-POS-Products-Equipment, https://support.ezfacility.com/hc/en-us/articles/23505081363227-How-to-Discount-Individual-POS-Products-Equipment, https://support.ezfacility.com/hc/en-us/articles/34418941582747-New-Point-of-Sale-Customizing-the-Receipt, https://support.ezfacility.com/hc/en-us/articles/36516560976539-April-9th-2025-Release-Notes, https://support.ezfacility.com/hc/en-us/articles/26498179644187-June-5th-2024-Release-Notes, https://support.ezfacility.com/hc/en-us/articles/34419191751451-Setting-Up-Product-Categories-Inventory

### POS-11 Coupons at POS and coupon sales reporting
- Sub-features: coupon codes usable in-house (POS) as well as online; coupon discount itemised on receipt; "All Sales By Coupon" report with include/exclude POS coupon sales; POS-side "Sales by Coupon" report (reporting cluster).
- Settings / options: report Start/End Date; include/exclude POS coupon sales; coupon definition (name, code, start/end, amount or percent, per-person limit or unlimited, self-service enabled) lives in Billing; coupons are managed under Point of Sale > Coupons with an expiry date (video; example 15% off for returning customers); legacy POS discount dialog listed available coupon codes to pick from.
- Rules / limits: coupon validity window is enforced at POS down to hour and minute (2016-01-20 release); how a coupon is entered in the POS cart is not documented; one coupon definition applies to memberships and packages as well as POS items; coupon sales are reportable by date range.
- User story: As a marketer, I want coupon redemptions at the counter tracked alongside online ones, so that I can measure a promotion end to end.
- Actors: cashier, owner/admin.
- UI generation: both
- Priority: P1
- Evidence: https://support.ezfacility.com/hc/en-us/articles/4403493443355-All-Sales-By-Coupon-Report, https://support.ezfacility.com/hc/en-us/articles/34418941582747-New-Point-of-Sale-Customizing-the-Receipt, https://www.ezfacility.com/blog/ez-features-fixes-check-out-whats-new, https://support.ezfacility.com/hc/en-us/articles/26094951298331-How-to-Create-Coupons, https://support.ezfacility.com/hc/en-us/articles/34419042530587-Sales-by-Coupon, https://www.ezfacility.com/features/billing-payments, https://www.youtube.com/watch?v=3FOVNMAz2cE (t=25:35), https://www.youtube.com/watch?v=unZH32QU1nc (t=10:00)

### POS-12 Tender and sale completion
- Sub-features: Pay step with tender choice; split tender across several payment types; transaction note; ACCEPT SALE finalises; sale posts to the client's account/invoice history when a client is attached; sales attributed to the logged-in user (Sales By Employee report); every POS transaction creates an invoice plus a payment (same model as package and membership sales); "exact change" shortcut on the cash amount entry (legacy 2013 demo).
- Settings / options: payment types = Debit/Credit | Cash | Check | Gift Card | Money on Account | Pay Later | Split Tender; NOTE memo; card on file (client required); marketing adds tap, Apple Pay, Google Pay, "scan ID card to pay", "charge to player account".
- Rules / limits: Money on Account draws on the client's account balance and needs a client; Pay Later places the items on an open invoice and needs a client; completed POS sales are searched as completed transactions unless Pay Later was used (then an open invoice); cash change/rounding, tips and drawer handling are not documented; a sale without a client posts to a system client record named "Point of Sale Customer" (2013); when POS moved to invoices, historical POS data was bulk-converted to invoices.
- User story: As a cashier, I want to take any mix of cash, card, gift card or account credit, so that the customer can pay how they like and the sale is closed correctly.
- Actors: cashier, client.
- UI generation: both
- Priority: P0
- Evidence: https://support.ezfacility.com/hc/en-us/articles/34418766515099-How-to-Add-Products-to-the-Shopping-Cart-and-Finish-Sale, https://support.ezfacility.com/hc/en-us/articles/23505052562971-How-to-Add-Products-to-the-Shopping-Cart-and-Finish-Sale, https://support.ezfacility.com/hc/en-us/articles/23505072579483-How-to-Email-a-P-O-S-Receipt-from-Completed-Transactions, https://support.ezfacility.com/hc/en-us/articles/23505069345947-How-to-Search-for-a-Client-in-the-POS, https://www.ezfacility.com/features/merchant-processing, https://www.ezfacility.com/industries/campus-recreation-software, https://www.ezfacility.com/industries/rink-management-software, https://www.ezfacility.com/features/billing-payments, https://www.youtube.com/watch?v=unZH32QU1nc (t=07:45, t=10:45, t=11:20)

### POS-13 Receipt delivery at sale and re-send from history
- Sub-features: "Receipt and Delivery Options" after payment: Print, Email, or both; email prefilled from client profile or typed ad hoc; re-print / re-email any past transaction from the Transactions tab (search by client or invoice number > Receipt Options > Send Email Receipt); immediate Print button.
- Settings / options: POS Preferences > General Preferences > "Enable Email Receipt Option"; Printer tab > "Auto-Print Receipts"; Delivery (email) field.
- Rules / limits: email receipts exist only in POS v.2; with Auto-Print on, Email is the preselected delivery and also ticking print yields two printouts; an email typed at checkout is not written back to the client profile; POS receipts are also visible on the client's invoice tab; fix 2024-02-15 for emailing receipt after a POS transaction.
- User story: As a cashier, I want to print or email the receipt now or later, so that customers get proof of purchase in the form they prefer.
- Actors: cashier; admin sets preferences.
- UI generation: both
- Priority: P0
- Evidence: https://support.ezfacility.com/hc/en-us/articles/34418925611803-How-to-Email-P-O-S-Receipts-from-the-Sale-Complete-Page, https://support.ezfacility.com/hc/en-us/articles/34418959208987-How-to-Email-a-P-O-S-Receipt-from-Completed-Transactions, https://support.ezfacility.com/hc/en-us/articles/34418995181595-How-to-Email-a-P-O-S-Receipt-from-Completed-Transactions, https://support.ezfacility.com/hc/en-us/articles/23505072579483-How-to-Email-a-P-O-S-Receipt-from-Completed-Transactions, https://support.ezfacility.com/hc/en-us/articles/34418971487387-How-to-Enable-the-Email-Option-in-Point-of-Sale, https://support.ezfacility.com/hc/en-us/articles/23505084116891-How-to-Enable-the-Email-Option-in-Point-of-Sale, https://support.ezfacility.com/hc/en-us/articles/22968789591963-February-15th-2024-Release-Notes

### POS-14 Receipt content customisation
- Sub-features: receipt header from location address, phone and website; free-text receipt footer; automatic itemisation of coupon, manual price edit and manual amount/percent discounts.
- Settings / options: Receipt Footer (Billing Preferences); location address / phone / website (location setup).
- Rules / limits: footer prints on every receipt above the location URL; card-surcharge disclosures are also said to print on receipts (billing cluster).
- User story: As an owner, I want my contact details and a return-policy line on every receipt, so that receipts look like mine and answer common questions.
- Actors: owner/admin.
- UI generation: both (documented under New Point of Sale in the Classic guide set)
- Priority: P1
- Evidence: https://support.ezfacility.com/hc/en-us/articles/34418941582747-New-Point-of-Sale-Customizing-the-Receipt, https://www.ezfacility.com/features/merchant-processing

### POS-15 Local receipt-printer bridge (QZ Tray)
- Sub-features: third-party desktop agent that lets the browser POS print to a locally attached receipt printer; Windows and macOS installers; must run continuously / auto-start on the POS machine.
- Settings / options: optional JDK (OpenJDK 11 HotSpot) prerequisite; install folder; tray icon menu (options, off); macOS admin password, Java enable prompt, Dock, auto-start.
- Rules / limits: Java may be required depending on OS and agent version; press says POS "integrates with printer hardware of choice"; Clover terminal receipt printing is a separate path (POS-21).
- User story: As the person setting up the till, I want browser-initiated silent printing to my receipt printer, so that cashiers are not stuck in print dialogs.
- Actors: admin / POS workstation installer.
- UI generation: both
- Priority: v2-adapter (v1: browser print + PDF/email; define a PrinterBridge interface)
- Evidence: https://support.ezfacility.com/hc/en-us/articles/34418794060699-Receipt-Printing-Using-the-QZ-Tray-Application-For-PC, https://support.ezfacility.com/hc/en-us/articles/34418851502875-Receipt-Printing-Using-the-QZ-Tray-Application-For-Mac, https://support.ezfacility.com/hc/en-us/articles/23505035242779-Receipt-Printing-Using-the-QZ-Tray-Application-For-PC, https://support.ezfacility.com/hc/en-us/articles/23505063085211-Receipt-Printing-Using-the-QZ-Tray-Application-For-Mac, https://www.ezfacility.com/press-news/press-releases/ezfacility-releases-cutting-edge-fitness-point-of-sale-solution

### POS-16 Transaction history, refunds and returns
- Sub-features: Transactions tab listing completed sales; search by client name or invoice number; open a transaction for detail; Classic: "Refund Sale" for the sale; New: tick individual items > Return > Refund Sale; choose refund payment method; Process Refund with confirmation; refund/return and daily register reports (reporting cluster).
- Settings / options: refund payment method/form selector; per-item selection (New).
- Rules / limits: partial (line-level) refund is implied in New by per-item checkboxes, Classic text describes whole-sale refund only; whether refund restocks inventory and whether refund tender is constrained to the original tender are not stated; a separate billing refund permission exists (2023-06-28 notes) - applicability to POS not stated.
- User story: As a cashier, I want to find a past sale and refund some or all of it to a chosen tender, so that returns are quick and auditable.
- Actors: cashier / front desk.
- UI generation: both (line-level return in New)
- Priority: P0
- Evidence: https://support.ezfacility.com/hc/en-us/articles/34419183605659-Refunding-in-the-Point-of-Sale, https://support.ezfacility.com/hc/en-us/articles/23505037972251-How-to-Refund-in-Point-of-Sale, https://support.ezfacility.com/hc/en-us/articles/23505072579483-How-to-Email-a-P-O-S-Receipt-from-Completed-Transactions, https://support.ezfacility.com/hc/en-us/articles/34419017128987-Order-Returns-Refunds, https://support.ezfacility.com/hc/en-us/articles/34419021121051-Daily-Register-Report

### POS-17 Rental equipment catalogue
- Sub-features: equipment categories and rentable equipment items with rental, late and replacement fees; shown on the POS Equipment tab; soft-delete with "Show Deleted Categories"; manual ordering (Classic arrows); marketing extends to locker and hockey-equipment rentals with availability states (available / checked out / needs restocking).
- Settings / options: Category name + Revenue Category; Equipment Name (POS label); Equipment ID (unique, searchable); Description (shown on invoice); Rental Fee (pre-tax); Rental Days (allowed duration); Late Fee; Return Time (time of day due); Replace Fee; Revenue Category or "Inherit from equipment category"; Classic: Tax Code(s) (older variant: free-text Tax %).
- Rules / limits: if the account uses taxes, equipment must be linked to a revenue category (New); Classic articles say late and replace fees are informational only, New describes them as charged when overdue / not returned or damaged (conflict); item appears to be a single trackable asset (one item, one checkout state) with quantity editable in the cart (ambiguous); vendor suggested (2020) using the Equipment module to loan out weights to members during closures, i.e. multi-day off-site loans are an intended use.
- User story: As an admin, I want rentable gear defined with its fee, due time and penalty amounts, so that the desk can rent it out consistently.
- Actors: admin.
- UI generation: both
- Priority: P0
- Evidence: https://support.ezfacility.com/hc/en-us/articles/27444960685851-How-to-Add-Equipment-to-POS, https://support.ezfacility.com/hc/en-us/articles/34418766995099-How-to-Set-Up-Equipment-in-EZFacility-Classic, https://support.ezfacility.com/hc/en-us/articles/34418934806171-How-to-Set-Up-Rental-Equipment-in-EZFacility-Classic, https://www.ezfacility.com/features/scheduling-operations, https://www.ezfacility.com/industries/rink-management-software, https://www.youtube.com/watch?v=qUf6jPISK_8 (t=17:30)

### POS-18 Equipment rent-out and return
- Sub-features: rent through POS Equipment tab as a normal sale line (client mandatory); return processed outside POS in the back office, from the Equipment page or the client profile's checked-out items list; item becomes available in POS again after return; checked-out and all-equipment reports (reporting cluster).
- Settings / options: Search Equipment; client search / Add Client; quantity and price editable in cart (Classic); Return action.
- Rules / limits: every rental must have a client; due date/time derives from Rental Days + Return Time (inferred); automatic late-fee or replacement billing is not evidenced.
- User story: As front desk, I want to check gear out to a named client and check it back in, so that I always know who holds what.
- Actors: front desk.
- UI generation: both
- Priority: P0
- Evidence: https://support.ezfacility.com/hc/en-us/articles/27444958543003-How-to-Rent-and-Return-Equipment, https://support.ezfacility.com/hc/en-us/articles/34418782382235-How-to-Rent-Equipment-in-EZFacility-Classic, https://support.ezfacility.com/hc/en-us/articles/34418804557467-How-to-Return-Equipment-Rentals-in-EZFacility-Classic, https://support.ezfacility.com/hc/en-us/articles/34419089287067-View-the-Checked-Out-Equipment-in-EZFacility-Classic, https://support.ezfacility.com/hc/en-us/articles/23505069345947-How-to-Search-for-a-Client-in-the-POS, https://www.ezfacility.com/features/scheduling-operations

### POS-19 Sell packages through POS
- Sub-features: selling session packages (service products) from the register in addition to retail goods (inferred from title).
- Settings / options: unknown (body not retrieved).
- Rules / limits: presumably needs a client on the sale (inferred); see unknowns.
- User story: As a cashier, I want to sell a class pack at the till with the customer's drink, so that one payment covers both.
- Actors: cashier.
- UI generation: both (separate New and Classic articles)
- Priority: P1
- Evidence: https://support.ezfacility.com/hc/en-us/articles/42551868532891-How-to-Sell-Packages-Through-the-Point-of-Sale (title only, body not read), https://support.ezfacility.com/hc/en-us/articles/42552021593499-How-to-Sell-Packages-Through-the-Point-of-Sale-Classic (title only, body not read)

### POS-20 POS deposits (undocumented)
- Sub-features: a help article titled "POS Deposits" exists in the Classic POS guide set with an empty body; scope unknown (bank/cash deposit reconciliation of register takings, or deposits taken against an item).
- Settings / options: none published.
- Rules / limits: none published.
- User story: As an owner, I want register takings reconciled to deposits, so that cash and card totals match the bank (inferred intent).
- Actors: owner/admin (inferred).
- UI generation: Classic
- Priority: P2 (capability not confirmed; revisit if body becomes available)
- Evidence: https://support.ezfacility.com/hc/en-us/articles/34419023035803-POS-Deposits

### POS-21 Card-present terminal and contactless payments (Clover)
- Sub-features: Clover payment-terminal integration for card-present sales, including receipt printing from the terminal; tap-to-pay, Apple Pay, Google Pay advertised as accepted in person; Clover Flex handheld terminal (Wi-Fi, portable): chip and PIN, contactless, Apple Pay, Google Pay; the sale amount is pushed from the software to the terminal and the payment result posts back automatically; Clover also used for online (e-commerce) payments.
- Settings / options: none published.
- Rules / limits: described as PCI compliant (2023-11 webinar); Clover receipt printing fixed 2025-04-09; pairing model (register to terminal) not documented; semi-integrated: staff cannot edit the pushed amount on the terminal; UK-focused webinar (2023-2024 inferred): Clover approval typically under a week, account linking under an hour, terminals shipped with a user guide, initial 18-month Clover term (commercial terms owned by the payments cluster).
- User story: As a cashier, I want the total pushed to a card reader, so that the customer taps or inserts and the sale closes itself.
- Actors: cashier, client.
- UI generation: both (inferred)
- Priority: v2-adapter (v1 uses Stripe Terminal behind a CardPresentTerminal interface or keyed/hosted card entry; Clover is partner-specific)
- Evidence: https://www.youtube.com/watch?v=wTcpTun-eyM, https://support.ezfacility.com/hc/en-us/articles/36516560976539-April-9th-2025-Release-Notes, https://www.ezfacility.com/features/merchant-processing, https://www.youtube.com/watch?v=wTcpTun-eyM (t=15:20, t=24:32, t=29:35)

### POS-22 Reorder alerts and POS reporting hooks
- Sub-features: automated low-stock / reorder alerts; product profitability (buying price vs sale price, profit margin); revenue-source tracking; POS reports: all sales, daily register, returns/refunds, sales by coupon / brand / supplier / category / employee, all inventory, re-order, equipment inventory, checked-out equipment (owned by the reporting cluster; listed here for data-model coverage); POS sales sync to QuickBooks Online; public API exposes POS endpoints.
- Settings / options: Reorder Level per product (-1 disables); report date ranges and register/employee selectors.
- Rules / limits: what "automated" alerting means beyond the on-demand re-order report is not documented.
- User story: As an owner, I want to be told when stock runs low and see margin by product, so that I reorder in time and stock what earns.
- Actors: owner/admin.
- UI generation: both
- Priority: P1
- Evidence: https://www.ezfacility.com/press-news/press-releases/ezfacility-releases-cutting-edge-fitness-point-of-sale-solution, https://www.ezfacility.com/features/billing-payments, https://support.ezfacility.com/hc/en-us/articles/34419009666459-Inventory-Re-order-Report, https://support.ezfacility.com/hc/en-us/articles/34419021121051-Daily-Register-Report, https://support.ezfacility.com/hc/en-us/articles/34418975239707-All-Inventory-Report, https://www.ezfacility.com/ez-api-services

### POS-23 Vertical / partner and legacy POS lines
- Sub-features: Rapid Gun Systems partner POS (NCR Counterpoint reseller) for gun retail and ranges: ATF compliance, electronic bound book, 2D ID scanning, vendor catalogues, range manager; Plastic Printers supplies POS hardware and card printers; Frontline Solutions rink/FEC POS + ticketing line acquired 2012-04-20 (legacy, status unknown).
- Settings / options: none published.
- Rules / limits: partner products are separate systems, not features of the core POS.
- User story: As a range owner, I want regulated-goods sales handled by a compliant system that still shares members with my facility software, so that I do not double-enter customers.
- Actors: owner, partner system.
- UI generation: n-a
- Priority: v2-adapter (Frontline line: P2 legacy, 2012-04-20)
- Evidence: https://www.ezfacility.com/partners/rapid-gun-systems/, https://www.ezfacility.com/partners, https://www.ezfacility.com/blog/ezfacility-saas-partner-deep-dive, https://www.ezfacility.com/press-news/press-releases/ezfacility-acquires-frontline-solutions

## Check-in & Access Control

### CHK-01 Staff check-in window
- Sub-features: dedicated pop-out window; look up by membership number (typed, barcode-scanned, or supplied by a fingerprint device) or by name with delayed autocomplete; Check-In action; Clear Window; link to full client record; result panel with identity, membership state, today's sessions, current packages, relationships and alerts; automatic attendance marking for a matching scheduled session; non-member check-in; cross-location check-in for shared clients; accepted identifiers shown in New UI demos: name, member ID, phone (app) barcode or key tag; result card also lists package plans and upcoming sessions in the next few hours; check-in is also reachable inside the POS so a client can be signed in mid-sale without disturbing the cart (2013 demo; a 2026 webinar still refers to "native or POS" check-in stations).
- Settings / options: displayed fields: name, DOB, Membership Type, Membership Number ("0" if none), Membership Start, Membership Expires / renewal, Check-In Time, Last Visit, Waiver (not signed), Balance Due (items due today or earlier), expired-card alert, relationships, today's sessions, current packages; membership status indicators: Membership Active | "Membership Visits Depleted" | Non-Member; membership kinds Simple | Advanced.
- Rules / limits: attendance auto-marked when check-in falls from 3 h before to 5 h after a scheduled session; name lookup shows matches after roughly 10 s; non-members only need a membership number; a visit-limited membership consumes a visit on successful check-in; "Share Clients" lets any connected location check the client in; fixes: non-member no longer shows membership info (2023-07-03), client with active advanced but expired simple membership no longer shown as non-member (2024-02-15), check-in modals open from collapsed menu (2025-04-23); a client without a membership shows as "invalid member / non-member", yet attendance against a package session is still recorded and remaining sessions are displayed; the staff window does not auto-book (it only proposes sessions).
- User story: As front desk, I want to scan a member and instantly see whether they are good to enter and what they are booked for, so that I can greet them and resolve issues at the door.
- Actors: front desk.
- UI generation: both
- Priority: P0
- Evidence: https://support.ezfacility.com/hc/en-us/articles/4405137521563-Using-the-Check-In-Window-in-EZFacility-Classic, https://support.ezfacility.com/hc/en-us/articles/4402434197147-How-to-use-the-Staff-Check-in-Window, https://support.ezfacility.com/hc/en-us/articles/4405137473947-Assigning-a-Membership-Number, https://support.ezfacility.com/hc/en-us/articles/16846068050715-July-3rd-2023-Release-Notes, https://support.ezfacility.com/hc/en-us/articles/22968789591963-February-15th-2024-Release-Notes, https://support.ezfacility.com/hc/en-us/articles/36516396025115-April-23rd-2025-Release-Notes, https://www.ezfacility.com/features/staff-access-management, https://www.ezfacility.com/blog/make-the-most-of-ezfacility-management-software-features, https://www.youtube.com/watch?v=Rjy8ZpfIA68 (t=22:33), https://www.youtube.com/watch?v=KAN6h9vPUiM (t=35:00), https://www.youtube.com/watch?v=unZH32QU1nc (t=11:40), https://www.youtube.com/watch?v=SzgMT6X961A

### CHK-02 Staff check-in settings and detail visibility
- Sub-features: admin page controlling what the staff check-in window reveals and whether access rules are enforced there.
- Settings / options: Classic: "Show Date of Birth" (default Yes); New: per-field "Client Details" visibility toggles; "Apply Access Control Rules To Check In"; "Free Booking" (show free-booking reservations at check-in); option to show vaccine status (CHK-17); permission 'Full Details on Check-in'.
- Rules / limits: visibility toggles apply only to users lacking the Full Details permission; with access rules applied, a denied client triggers an alert and does not consume a membership visit; setting never changes behaviour of physical door devices.
- User story: As an admin, I want junior desk staff to see only what they need at check-in, so that sensitive client data stays restricted.
- Actors: admin.
- UI generation: both (New has granular field toggles and Free Booking)
- Priority: P1
- Evidence: https://support.ezfacility.com/hc/en-us/articles/4405144453019-How-to-Set-Up-your-Staff-Check-In-Settings-in-EZFacility-Classic, https://support.ezfacility.com/hc/en-us/articles/27914147357339-Staff-Check-in-Station-Settings, https://support.ezfacility.com/hc/en-us/articles/4411586669467-How-to-use-the-Vaccine-Passport-with-Staff-Check-in

### CHK-03 Check-in from client profile
- Sub-features: Check-In button on the client record as an alternative to the window.
- Settings / options: none.
- Rules / limits: button only shown when the client has a membership number.
- User story: As staff already viewing a client, I want to check them in from there, so that I do not need to re-search.
- Actors: staff.
- UI generation: Classic (New equivalent not documented)
- Priority: P0
- Evidence: https://support.ezfacility.com/hc/en-us/articles/4405137527067-Using-Check-In-from-Client-s-Page-in-EZFacility-Classic

### CHK-04 Session / package booking from check-in
- Sub-features: from the check-in result, pick one of the client's schedulable packages ("Select") and book into an available session; package list filterable by column; optional display of free-booking reservations; New UI demo: after check-in the window proposes other open bookable slots in the next 3-4 hours, so staff can add further bookings on the spot (example: two batting cages for a parent and child).
- Settings / options: "Free Booking" toggle (CHK-02).
- Rules / limits: book-in options are offered only for sessions starting from 1 h before to 4 h after the check-in time, otherwise N/A.
- User story: As front desk, I want to drop a walk-in member into the class that is about to start using their package, so that attendance and credit usage are captured without opening the schedule.
- Actors: front desk.
- UI generation: both (detailed in Classic)
- Priority: P1
- Evidence: https://support.ezfacility.com/hc/en-us/articles/4405137521563-Using-the-Check-In-Window-in-EZFacility-Classic, https://support.ezfacility.com/hc/en-us/articles/27914147357339-Staff-Check-in-Station-Settings, https://www.youtube.com/watch?v=7JVYZ3kxUAo (t=33:00)

### CHK-05 Self check-in kiosk
- Sub-features: staff opens a kiosk window on a tablet/desktop; client identifies by name and/or membership number (or scans a card); system records the check-in, marks attendance, and shows a status screen; optional auto-booking into the nearest reservation; reservation page listing bookable sessions; package page allowing package purchase at the kiosk; confirmation screen with timeout; search field stays focused between users.
- Settings / options: see CHK-06; result screens: active membership with no balance | balance owed | frozen or suspended membership (client told to see staff for inactive membership or balance).
- Rules / limits: attendance auto-marked for sessions from 3 h before to 5 h after check-in; disabled clients are excluded from kiosk search (fix 2024-01-17); cursor persistence added 2023-09-27; confirmation window closing fixed 2023-10-25; launch webinar adds that staff can collect an overdue balance or re-sell an expired membership at check-in.
- User story: As a member, I want to check myself in on a tablet, so that I do not queue at the desk.
- Actors: client/member; staff launches the kiosk.
- UI generation: both
- Priority: P0
- Evidence: https://support.ezfacility.com/hc/en-us/articles/27550762531739-How-to-use-the-Self-Check-in-Station, https://support.ezfacility.com/hc/en-us/articles/4404311317403-Online-Webinar-Introducing-Self-Check-In-Advanced-Multi-Scheduling, https://support.ezfacility.com/hc/en-us/articles/27914135025819-Self-Check-in-Station-Settings, https://support.ezfacility.com/hc/en-us/articles/4405137541403-Using-Bluetooth-Scanners, https://support.ezfacility.com/hc/en-us/articles/19132331777307-September-27th-2023-Release-Notes, https://support.ezfacility.com/hc/en-us/articles/19847009538203-October-25th-2023-Release-Notes, https://support.ezfacility.com/hc/en-us/articles/22122496577179-January-17th-2024-Release-Notes, https://www.ezfacility.com/features/staff-access-management, https://www.ezfacility.com/industries/yoga-and-pilates-studio-management-software, https://www.ezfacility.com/blog/make-the-most-of-ezfacility-management-software-features

### CHK-06 Self check-in kiosk settings
- Sub-features: configuration of kiosk look, lookup, booking windows, timeouts and alerts.
- Settings / options: Visible Range (sessions starting within N minutes/hours are listed); Early Check-In Window; Late Check-In Window (after start); Welcome Message; Colors; Default View = Card (grid) | Row; Client Photo show | hide; Auto-Book on | off (books closest reservation); selectable "criteria" / membership alerts shown at check-in (list not fully published; includes depleted and "Over Daily Limit"); Reservation Page Timeout; Select Package Page Timeout; Confirmation Timeout; Client Lookup Method = Client Name | Membership Number | Both; Classic also manages Check-in Stations (Staff or Self) on this page; vaccine-passport denial Yes | No (CHK-17).
- Rules / limits: "Over Daily Limit" alert (2024-02-28) fires when the client already has one contract visit today on an active visit-limited membership; it has the lowest alert priority and is independent of the access rule (alert alone still records a successful check-in and logs a visit).
- User story: As an admin, I want to brand the kiosk and decide how members identify and what they may book, so that self check-in matches my front-desk policy.
- Actors: admin.
- UI generation: both
- Priority: P0 (lookup method, windows, auto-book, timeouts); branding and alert selection P1
- Evidence: https://support.ezfacility.com/hc/en-us/articles/4405137537563-How-to-Set-up-the-Self-Check-In-Settings-in-EZFacility-Classic, https://support.ezfacility.com/hc/en-us/articles/27914135025819-Self-Check-in-Station-Settings, https://support.ezfacility.com/hc/en-us/articles/23328878237467-February-28th-2024-Release-Notes, https://support.ezfacility.com/hc/en-us/articles/4411549886107-How-to-use-the-Vaccine-Passport-with-Self-Check-in

### CHK-07 Check-in stations, check-out and occupancy dashboard
- Sub-features: named check-in stations; main vs secondary stations (e.g. facility entrance vs a zone); optional check-out; live occupancy counts per location and per secondary station; capacity thresholds with colour warnings and a menu alert; manual check-out and check-out time editing ("Now" shortcut); filter by client name or station; browse previous dates; station filter on check-in reports.
- Settings / options: permission "Check-Out" (granted by a Manager-level user); "Enable Checkout Preference"; Station name; Station type = Main | Secondary (Classic self-check-in page also classifies stations Staff | Self); Max Capacity (location, and per secondary station); check-out time.
- Rules / limits: main check-in +1 location count, main check-out -1 and also closes any open secondary check-in; secondary check-out only leaves that station; near capacity the tile changes colour, at capacity a secondary station turns red and a menu alert shows; staff may override the capacity warning and admit over the maximum; only Manager-permission users can enable; station filter on Check-in Detail/Summary reports fixed 2023-06-28.
- User story: As a duty manager, I want to see how many people are in the building and in each zone, so that I can enforce capacity limits.
- Actors: manager, front desk.
- UI generation: Classic (no New UI article; marketing claims live occupancy generally)
- Priority: P1
- Evidence: https://support.ezfacility.com/hc/en-us/articles/4404305376795-How-to-Set-Up-the-Check-In-Dashboard-in-EZFacility-Classic, https://support.ezfacility.com/hc/en-us/articles/4405137543835-Online-Webinar-Check-in-Dashboard-in-EZFacility-Classic, https://support.ezfacility.com/hc/en-us/articles/4405137537563-How-to-Set-up-the-Self-Check-In-Settings-in-EZFacility-Classic, https://support.ezfacility.com/hc/en-us/articles/16731304236571-June-28th-2023-Release-Notes, https://www.ezfacility.com/features/staff-access-management

### CHK-08 Access-control membership rules and access mode
- Sub-features: per-location rule set mapping membership conditions to Allow Entry / Deny Entry; per-client access mode; option to enforce the same rules in the software check-in windows.
- Settings / options: rules (each Allow Entry | Deny Entry): Expired, Cancelled, Suspended, Frozen, Depleted (visit allowance used), Past Due (+ days-overdue threshold), Max Visits (allow multiple entries per day | deny more than 1 visit/day); "Apply To Check-Ins" toggle; Default Access Mode = Allow Entry | Deny Entry | Rules Based; per-client access mode editable on the profile; menu path Administration > Client Settings > Access Control (video).
- Rules / limits: Default Access Mode applies only to newly created clients; one-visit-per-day rule (2024-02-28) applies to active visit-limited (not unlimited) memberships, day = midnight to midnight in the location time zone; a denied client consumes no visit and staff are alerted; "Apply To Check-Ins" affects only software check-in, not door devices; simple (non-billed) memberships also rely on these rules for door access; "Expired" means a non-auto-renewing contract has run its full term (auto-renewing members only expire if auto-renew is switched off); a suspended membership keeps billing but is blocked at door/check-in, a frozen one pauses billing; the past-due day threshold is facility-chosen so a failed autopay can block entry from the next day; with the default "Allowed Entry" mode everyone gets in, rules only bite in Rules Based mode; trainer states cancelled, suspended and frozen members are refused by integrated door hardware (Brivo named).
- User story: As an owner, I want lapsed, frozen or overdue members automatically refused, so that staff do not have to police entitlement manually.
- Actors: owner/admin; front desk.
- UI generation: New (Classic exposes only the "Apply Access Control Rules To Check In" switch)
- Priority: P1
- Evidence: https://support.ezfacility.com/hc/en-us/articles/27996895819547-Setting-up-Access-Control, https://support.ezfacility.com/hc/en-us/articles/23328878237467-February-28th-2024-Release-Notes, https://support.ezfacility.com/hc/en-us/articles/4405144453019-How-to-Set-Up-your-Staff-Check-In-Settings-in-EZFacility-Classic, https://support.ezfacility.com/hc/en-us/articles/27914147357339-Staff-Check-in-Station-Settings, https://support.ezfacility.com/hc/en-us/articles/29852099999259-Setting-Up-a-Simple-Membership-in-EZFacility-Classic, https://www.ezfacility.com/features/staff-access-management, https://www.youtube.com/watch?v=a7-8-cHwB8Y (t=18:27, t=35:53, t=38:56), https://www.youtube.com/watch?v=KAN6h9vPUiM (t=21:31), https://www.youtube.com/watch?v=gjyVmvHCT1M (t=27:40)

### CHK-09 Time-of-day access schedules
- Sub-features: named weekly schedules made of one or more time ranges per weekday; mapping of membership types to a schedule (off-peak style memberships).
- Settings / options: Schedule Name; per-day "+Add Range" (start, end); Current Schedules list; Membership Type Mappings (tick types, choose schedule, Apply Selected Mapping).
- Rules / limits: a membership type maps to one schedule (inferred); behaviour for unmapped types (assumed unrestricted) and for midnight-spanning ranges not stated.
- User story: As an owner, I want off-peak memberships admitted only in defined hours, so that I can price by time of day.
- Actors: owner/admin.
- UI generation: New
- Priority: P1
- Evidence: https://support.ezfacility.com/hc/en-us/articles/27996895819547-Setting-up-Access-Control, https://www.ezfacility.com/features/staff-access-management

### CHK-10 Location access mappings
- Sub-features: per membership type, choose which connected locations the type grants entry to.
- Settings / options: per-type location multi-select; Save Mappings.
- Rules / limits: relevant only when several connected locations share clients; marketing describes finer "zone-based" restriction (pools, daycare, spa) which the help centre only evidences via the Brivo integration.
- User story: As a multi-site operator, I want single-club and all-club memberships, so that entry rights follow what was sold.
- Actors: owner/admin.
- UI generation: New
- Priority: P1
- Evidence: https://support.ezfacility.com/hc/en-us/articles/27996895819547-Setting-up-Access-Control, https://www.ezfacility.com/features/staff-access-management, https://www.ezfacility.com/press-news/press-releases/ezfacility-partners-with-brivo-to-offer-24-hour-sports-fitness-access

### CHK-11 Membership number / credential assignment
- Sub-features: a per-client membership number acts as the check-in lookup key; auto-generate a random number; enter a key-fob / key-tag barcode number by scanning into the field; non-members can hold a number.
- Settings / options: Membership # field; Generate; separate client/account number field (not used for check-in).
- Rules / limits: only the Membership # field resolves at check-in; numbers may contain letters (ID card generation bug fixed 2022-12-15); "0" displayed when absent; several API endpoints search by membership number across accessible locations (2025-04-09); uniqueness scope (location vs account) not stated.
- User story: As front desk, I want to bind a fob or card number to a client, so that one scan identifies them.
- Actors: front desk.
- UI generation: both
- Priority: P0
- Evidence: https://support.ezfacility.com/hc/en-us/articles/4405137473947-Assigning-a-Membership-Number, https://support.ezfacility.com/hc/en-us/articles/29852099999259-Setting-Up-a-Simple-Membership-in-EZFacility-Classic, https://support.ezfacility.com/hc/en-us/articles/4405137521563-Using-the-Check-In-Window-in-EZFacility-Classic, https://support.ezfacility.com/hc/en-us/articles/11297336305691-December-15th-2022-Release-Notes, https://support.ezfacility.com/hc/en-us/articles/36516560976539-April-9th-2025-Release-Notes

### CHK-12 ID card templates and generation
- Sub-features: configurable printable ID card / player pass; template designer with tabs Photo (with or without photo), Show Fields, Colors, Summary; preview; default/active template; generate a card from a client record; client photo capture by camera, upload or drag-and-drop; cards scanned at check-in or door, and (marketing) scanned to pay at POS.
- Settings / options: Default ID / Active ID Card; with-photo | without-photo; shown fields list; colours.
- Rules / limits: image size/format requirements exist but are not published; vendor also builds bespoke per-company templates (2024-06-05 note); used for league player verification.
- User story: As an admin, I want to print branded photo cards carrying the member's scan code, so that identity and entitlement can be verified at the door or pitch.
- Actors: admin (design), front desk (generate/print).
- UI generation: Classic article (feature marketed generally)
- Priority: P1
- Evidence: https://support.ezfacility.com/hc/en-us/articles/4416952099611-How-to-Generate-an-ID-Card, https://support.ezfacility.com/hc/en-us/articles/11297336305691-December-15th-2022-Release-Notes, https://support.ezfacility.com/hc/en-us/articles/26498179644187-June-5th-2024-Release-Notes, https://www.ezfacility.com/features/member-engagement, https://www.ezfacility.com/industries/volleyball-software, https://www.ezfacility.com/industries/rink-management-software

### CHK-13 App member cards, wallet pass and mobile check-in
- Sub-features: members register their member-card (barcode) number in the consumer app (shared app or branded app) and present a digital card; Apple Wallet / Google Wallet membership pass; chain-level admin console listing registered cards with search by number and created-date range, delete one or delete all; legacy GPS check-in via Facebook (2017); card is created in the app by logging in / entering name and membership number, after which the app renders a barcode tied to the profile that scans like a key tag and opens the client (with photo) at check-in; available in both the shared and branded app; the app's "Check-in" tile is a social check-in (member shares a "checked in at" post with a facility-set link), not an attendance check-in (owned by the app cluster).
- Settings / options: Membercards tab filters: card number, created range; bulk "delete Member Cards"; per-row delete.
- Rules / limits: bulk delete removes every registered card in the chain database; app-store reviews report a card cannot be added on multiple devices/for family or removed by the user (2023-2024), which is what the admin clear function works around; the membership number must already exist on the client profile; the phone barcode does not replace door fobs; branded app can hold several cards (2018 demo: up to ten; spring 2025 webinar: an "add" control for one key tag per family member), which conflicts with the review-based note above (see unknowns).
- User story: As a member, I want my card on my phone, so that I can scan in without a plastic card.
- Actors: member; chain admin.
- UI generation: n-a (mobile app + app admin console)
- Priority: P0 (in-app QR/barcode card); wallet pass P1; GPS/Facebook check-in P2 (legacy, 2017)
- Evidence: https://support.ezfacility.com/hc/en-us/articles/29244336130203-Clear-client-member-card-from-database-MemberMe-Branded-App, https://www.ezfacility.com/features/member-engagement, https://www.ezfacility.com/features/branded-mobile-app/, https://www.ezfacility.com/blog/boost-client-conveniences-and-business-reach-with-memberme, https://apps.apple.com/us/app/memberme/id969248357, https://www.youtube.com/watch?v=Zs-8tpgvadk (t=43:02), https://www.youtube.com/watch?v=iMeRIT504Ho (t=08:06, t=15:17, t=23:28), https://www.youtube.com/watch?v=uLNIb7JsjkM (t=27:41, t=30:44), https://www.youtube.com/watch?v=7yHNga6cY0g (t=06:10), https://www.youtube.com/watch?v=lwC-tepoJ0I (t=27:39)

### CHK-14 Barcode scanner input (Bluetooth HID / USB)
- Sub-features: keyboard-emulating scanners for check-in and POS on tablets and desktops; scan in check-in auto-submits the check-in; client search is focused when check-in opens; on-screen keyboard toggle gestures per device; stand/continuous mode.
- Settings / options: none in product; device pairing in OS Bluetooth settings, HID mode.
- Rules / limits: named devices: SocketScan S700, Tera wireless 1D/2D/QR, Newland Piranha BS8060; USB on desktop; 2D/QR capable; reading a barcode off a phone screen needs a 2D scanner (glare defeats 1D laser scanners); the vendor sells 2D scanners through its own hardware store.
- User story: As front desk on an iPad, I want a wireless scanner that just types the code, so that check-in and sales need no special drivers.
- Actors: front desk, cashier.
- UI generation: both
- Priority: P0 (no adapter needed: treat scanner as keyboard input with scan detection)
- Evidence: https://support.ezfacility.com/hc/en-us/articles/4405137541403-Using-Bluetooth-Scanners, https://support.ezfacility.com/hc/en-us/articles/4405137521563-Using-the-Check-In-Window-in-EZFacility-Classic, https://support.ezfacility.com/hc/en-us/articles/4402434197147-How-to-use-the-Staff-Check-in-Window, https://www.youtube.com/watch?v=Zs-8tpgvadk (t=43:02)

### CHK-15 Biometric, RFID and cardless credentials (partners)
- Sub-features: fingerprint reader that resolves to the membership number in the check-in window; RFID cards, key fobs, wristbands and barcode media (Authentic8); cardless check-in (Identity One IDlink); client-access solutions (Passport Technologies); card/ID printers (Plastic Printers).
- Settings / options: none published.
- Rules / limits: partner hardware; enrolment flow and template storage not documented.
- User story: As an owner, I want members identified by fingerprint or wristband, so that card sharing is reduced.
- Actors: member, front desk, hardware partner.
- UI generation: both (inferred)
- Priority: v2-adapter
- Evidence: https://support.ezfacility.com/hc/en-us/articles/4405137521563-Using-the-Check-In-Window-in-EZFacility-Classic, https://www.ezfacility.com/features/staff-access-management, https://www.ezfacility.com/partners, https://www.ezfacility.com/partners/passport-technologies/, https://www.ezfacility.com/blog/ezfacility-saas-partner-deep-dive, https://www.ezfacility.com/blog/your-management-software-solution-and-your-front-desk

### CHK-16 Door access hardware integration (Brivo)
- Sub-features: cloud-to-cloud sync of member data to a Brivo access-control account so doors admit valid members 24/7; facility software is the single point of data entry; per-area access (pool, daycare, spa); anti-passback; email/SMS notification rules for after-hours access; staff alerts on invalid attempts; video via DVR/hosted video (Brivo side); integration authenticates as a dedicated service user in the tenant's Brivo account.
- Settings / options: Brivo service-user identity (first/last name, support email) and vendor-held password; migration from Brivo OnAir to Brivo Access.
- Rules / limits: the service user must exist and match or the sync is interrupted; software-side "Apply To Check-Ins" and vaccine gating explicitly do not alter door behaviour; which rule outcomes are pushed to doors is not documented.
- User story: As an owner of an unstaffed gym, I want door readers to honour membership status automatically, so that I can open 24 hours safely.
- Actors: owner/admin, member, access-control vendor.
- UI generation: n-a
- Priority: v2-adapter (define AccessController port: upsert credential, set entitlement, receive door events)
- Evidence: https://support.ezfacility.com/hc/en-us/articles/8305870999323-Updating-your-EZFacility-User-in-Brivo-Access, https://www.ezfacility.com/press-news/press-releases/ezfacility-partners-with-brivo-to-offer-24-hour-sports-fitness-access, https://www.ezfacility.com/blog/the-top-5-advantages-of-gun-range-management-software, https://support.ezfacility.com/hc/en-us/articles/27996895819547-Setting-up-Access-Control, https://www.ezfacility.com/features/staff-access-management

### CHK-17 Vaccine passport flag and check-in gating
- Sub-features: per-location opt-in adding a vaccination checkbox on client profiles; optional display in the staff check-in window; optional denial of self check-in for unflagged clients.
- Settings / options: location "Enable Vaccine Passport" (default off); client checkbox (default unchecked); staff check-in "show vaccine status"; self check-in deny Yes | No.
- Rules / limits: set one client at a time (no bulk); never affects door hardware; released 2021-11-29 (COVID era).
- User story: As an operator under a public-health mandate, I want to record and enforce vaccination status at entry, so that I comply locally.
- Actors: admin, front desk, client at kiosk.
- UI generation: both (blog says New only; a Classic enablement article exists)
- Priority: P2 (legacy, 2021-11-29) - if ever built, generalise as a custom boolean client attribute usable as a check-in gate
- Evidence: https://support.ezfacility.com/hc/en-us/articles/34406647603227-Enabling-the-Vaccine-Passport-Feature-in-EZFacility-Classic, https://support.ezfacility.com/hc/en-us/articles/4411540429851-Enabling-the-Vaccine-Passport-Feature, https://support.ezfacility.com/hc/en-us/articles/4411549886107-How-to-use-the-Vaccine-Passport-with-Self-Check-in, https://support.ezfacility.com/hc/en-us/articles/4411586669467-How-to-use-the-Vaccine-Passport-with-Staff-Check-in, https://www.ezfacility.com/blog/software-release-vaccine-passport

### CHK-18 Recent check-ins list
- Sub-features: list of check-ins within a chosen recent time span with a link to each client's detail view.
- Settings / options: time-span drop-down; Show Check-Ins.
- Rules / limits: span options not enumerated.
- User story: As front desk, I want to see who just came in, so that I can answer "is X here?" and fix mistakes.
- Actors: front desk.
- UI generation: both (inferred; article not UI-specific)
- Priority: P0
- Evidence: https://support.ezfacility.com/hc/en-us/articles/4405144461467-Viewing-Recent-Check-In-s

### CHK-19 Client check-in history report
- Sub-features: per-client check-in history for a date range from the client record; New UI: the client profile has a Check-in tab (and a Schedule tab) that run date-range reports.
- Settings / options: start date, end date, Generate Report.
- Rules / limits: none stated.
- User story: As staff, I want a member's visit history, so that I can settle usage disputes.
- Actors: staff.
- UI generation: both (Classic article; New UI Check-in tab shown in video)
- Priority: P0
- Evidence: https://support.ezfacility.com/hc/en-us/articles/4405137524379-How-to-View-Client-Check-In-Report-in-EZFacility-Classic, https://www.youtube.com/watch?v=Rjy8ZpfIA68 (t=25:35)

### CHK-20 Check-in summary analytics report
- Sub-features: aggregate check-in report with sections By Day Of Week, By Gender (distinct clients and total check-ins for Male / Female / Unknown), By Hour of Day, Total By Category, Total By Type (membership type, counting repeats), Unique By Type; sibling Check-in Detail and Low Usage reports (reporting cluster).
- Settings / options: start/end date; Client Category; Check-In Station; custom contact field filter.
- Rules / limits: clients without a value for the chosen custom field are excluded; clients without a category are grouped in a blank row; station filter fixed 2023-06-28.
- User story: As an owner, I want visits by hour, weekday and membership type, so that I can staff and price to demand.
- Actors: owner/admin.
- UI generation: Classic (inferred); New has report equivalents per release notes
- Priority: P1
- Evidence: https://support.ezfacility.com/hc/en-us/articles/4404308390811-Check-In-Summary-Report, https://support.ezfacility.com/hc/en-us/articles/16731304236571-June-28th-2023-Release-Notes, https://support.ezfacility.com/hc/en-us/articles/4404308202907-View-the-Low-Usage-Check-In-Report-in-EZFacility-Classic

### CHK-21 Front-desk alerts and at-check-in remediation
- Sub-features: check-in surfaces actionable alerts (unsigned waiver, balance due, expired card on file, expired/depleted membership, birthday, injury or custom notes, photo for identity); staff can take an overdue payment or re-sell an expired membership directly from the check-in context.
- Settings / options: alert types are partly configurable via kiosk "criteria" (CHK-06) and detail visibility (CHK-02).
- Rules / limits: Balance Due counts items with due date today or earlier; exact alert catalogue and priority order are not published except that "Over Daily Limit" is lowest; the waiver indicator is a checkbox on the client profile that is ticked automatically only when the client acknowledges a document during group online registration; in every other case staff tick it by hand.
- User story: As front desk, I want problems flagged and fixable at the moment the member arrives, so that arrears and renewals are handled face to face.
- Actors: front desk.
- UI generation: both
- Priority: P1
- Evidence: https://support.ezfacility.com/hc/en-us/articles/4404311317403-Online-Webinar-Introducing-Self-Check-In-Advanced-Multi-Scheduling, https://support.ezfacility.com/hc/en-us/articles/4405137521563-Using-the-Check-In-Window-in-EZFacility-Classic, https://www.ezfacility.com/blog/your-management-software-solution-and-your-front-desk, https://support.ezfacility.com/hc/en-us/articles/23328878237467-February-28th-2024-Release-Notes, https://www.youtube.com/watch?v=VuUR1Y9bhjQ (t=38:58), https://www.youtube.com/watch?v=KAN6h9vPUiM (t=35:00)

Scope note: their league product ("EZLeagues") is a separately-signed-in admin app plus a per-facility public website, fed from the core product's Groups via a one-way publish. Their event-form product ("EZSignUp", successor of 123SignUp) is a third admin surface. We document capability, not that product split. Help articles for the league app exist in two near-identical generations (2021-22 and 2024 re-issue); both are cited and merged.

## Leagues & Tournaments

### LGE-01 League (round-robin competition) setup
- Sub-features: create league; edit league info; attach teams (see LGE-03); per-league choice of which items show on the public site; league list with edit entry point; New-UI league management (training webinar only); New UI (video): left side menu that expands in place so any page is reachable without returning to the admin home; layout and navigation only, functions unchanged; pushed to every league-app customer on Monday 14 Nov (2022 inferred) with no interruption.
- Settings / options: Type = Round Robin (only value for leagues); Name; Age Group (pick-list of predefined values); Season (optional label); Division (free label, e.g. recreation / competitive / A / B); Starts; Ends; Sport (pick-list); Teams mode = Don't Create Teams | Generate Teams (+ count of generic placeholder teams) | Choose teams from Existing; Maximum Defaults; Maximum Forfeits; Minimum Sportsmanship; Registration Link; public-display checkboxes (individual items not enumerated); League Status (filter value set not enumerated, see LGE-17).
- Rules / limits: Max Defaults / Max Forfeits are per-team per-season caps; Min Sportsmanship is the rating floor a team needs to keep playing; schedule generation starts from Starts date; sport-level defaults (LGE-05) are copied at creation only; Age Group is mandatory when a group is published as a league; its stated purpose is matching officials qualified for that age group.
- User story: As a league admin, I want to define a competition with its sport, age group, division, dates and discipline thresholds, so that I can attach teams and generate a schedule.
- Actors: league admin.
- UI generation: both (league app has its own Classic and New UI; only the classic screens are documented in text)
- Priority: P0
- Evidence: https://support.ezfacility.com/hc/en-us/articles/11453271338523-How-to-Create-a-League, https://support.ezfacility.com/hc/en-us/articles/10962069855131-EZLeagues-Training-How-to-Create-Manage-Leagues-in-the-New-UI, https://support.ezfacility.com/hc/en-us/articles/10414682862235-How-to-Create-a-Tournament-in-EZLeagues, https://www.ezfacility.com/features/league-scheduling-management, https://www.youtube.com/watch?v=okhjK-XBid4 (t=38:00), https://www.youtube.com/watch?v=bHzYz6ZzMSE (t=04:05), https://www.youtube.com/watch?v=j4Rn9joKKpQ (t=15:18)

### LGE-02 Tournament setup and format types
- Sub-features: create tournament; edit tournament info; public-display toggles; alternative creation path by publishing a registration group (REG-14).
- Settings / options: Type (direct create) = Round Robin | Single Elimination | Double Elimination; Type (via group publish) additionally PoolPlay | Three Games Guaranteed; Name; Age Group; Season (optional); Division; Starts; Ends; Sport; Teams mode (as LGE-01); Maximum Defaults; Maximum Forfeits; Minimum Sportsmanship; Registration Link.
- Rules / limits: same discipline caps as leagues; games scheduled from Starts forward; Three Games Guaranteed requires exactly 8 teams; a published round-robin league cannot later be switched to a tournament or vice versa.
- User story: As a tournament director, I want to create a tournament in a chosen format, so that the matching scheduler (pool play or bracket) can be run for it.
- Actors: league admin.
- UI generation: both
- Priority: P0
- Evidence: https://support.ezfacility.com/hc/en-us/articles/10414682862235-How-to-Create-a-Tournament-in-EZLeagues, https://support.ezfacility.com/hc/en-us/articles/4405044226587-How-to-Publish-a-Group-to-EZLeagues-from-EZFacility, https://www.ezfacility.com/features/league-scheduling-management

### LGE-03 Teams, team copy and seeding
- Sub-features: no teams at creation (add later); bulk-generate N generic placeholder teams; copy teams from one or more earlier leagues/tournaments (switch source mid-selection); reorder seeds; remove a picked team; teams arriving from published groups (subgroups-as-teams, inferred from REG-14); marketing claims seed entry or blind draw for brackets and grouping by age range/division; "Add/Edit Teams" screen to add a team by hand before the schedule is generated.
- Settings / options: Teams mode (3 values, LGE-01); source competition picker; per-team seed; team name.
- Rules / limits: seeding is editable in the picker before finishing; blind-draw mechanics not documented; a player must already exist in the league app before being put on a hand-added team's roster.
- User story: As a league admin, I want to reuse last season's teams and set their seeds, so that I do not re-key teams every season.
- Actors: league admin.
- UI generation: both
- Priority: P0
- Evidence: https://support.ezfacility.com/hc/en-us/articles/10414682862235-How-to-Create-a-Tournament-in-EZLeagues, https://support.ezfacility.com/hc/en-us/articles/11453271338523-How-to-Create-a-League, https://www.ezfacility.com/features/league-scheduling-management, https://www.youtube.com/watch?v=bHzYz6ZzMSE (t=22:37)

### LGE-04 Player database and rosters
- Sub-features: add player (rapid repeat-entry form with success banner); players used for team rosters, game cards and stat tracking; rosters described as syncing from groups (blog); Players tile lists players carried over from the core product (arrive when a group's members are published as players, REG-14); public roster display toggles.
- Settings / options: First name (required), Last name (required), further optional attributes (not enumerated); public roster visibility = two checkboxes under Public Site > Edit (league level, team level), both ticked by default.
- Rules / limits: roster assignment UI is not documented in any body text (see unknowns); "Add Player" is one-way and does not create a client in the core product; a roster exists only if published from the core group or typed in by hand.
- User story: As a league admin, I want a player list tied to teams, so that game cards and player statistics have someone to attach to.
- Actors: league admin, scorekeeper.
- UI generation: both
- Priority: P0
- Evidence: https://support.ezfacility.com/hc/en-us/articles/4405044343451-How-to-Add-Players, https://www.ezfacility.com/blog/software-release-groups-new-ui, https://www.youtube.com/watch?v=bHzYz6ZzMSE (t=21:35), https://www.youtube.com/watch?v=bHzYz6ZzMSE (t=30:50)

### LGE-05 Per-sport defaults
- Sub-features: sport list; per sport: Settings, Standings Options (LGE-06), Player Stat Tables (LGE-07).
- Settings / options: Game Length; Player Fee; Team Fee; League Fees Text; League More Info; Rules & Regulations (all rendered on the public site).
- Rules / limits: defaults apply only to competitions created after the change (copy-on-create, no retroactive propagation); the sport list (e.g. ice hockey, inline hockey, laser tag, kickball) is vendor-maintained: tenants cannot add, rename or relabel a sport and must ask support.
- User story: As a league admin, I want sport-level defaults, so that new competitions start with correct game length, fees and rules text.
- Actors: league admin.
- UI generation: both
- Priority: P1
- Evidence: https://support.ezfacility.com/hc/en-us/articles/4405044313371-How-to-Manage-your-Sports, https://www.youtube.com/watch?v=bHzYz6ZzMSE (t=42:00), https://www.youtube.com/watch?v=j4Rn9joKKpQ (t=22:27)

### LGE-06 Standings configuration and computation
- Sub-features: league points awarded per game status/outcome; multi-column sort with direction; custom column set (choose column, custom heading, add, move up, remove); standings shown on public site and TV display in real time.
- Settings / options: default columns GP, W, L, T, GF, GA, PTS, GD, WP; points-per-status table (status list not enumerated); sort columns each Ascending | Descending; custom column heading text; bonus points per game (LGE-14) feed PTS.
- Rules / limits: default columns always show unless a custom set is defined; cancelled games are excluded from standings; config is per sport and copied to new competitions only.
- User story: As a league admin, I want to define how points and tie-break ordering work per sport, so that standings compute automatically from entered results.
- Actors: league admin; public viewers.
- UI generation: both
- Priority: P0
- Evidence: https://support.ezfacility.com/hc/en-us/articles/4405044313371-How-to-Manage-your-Sports, https://support.ezfacility.com/hc/en-us/articles/10414799252763-How-to-Manage-Scores-in-EZLeagues, https://www.ezfacility.com/features/league-scheduling-management

### LGE-07 Player stat tables and formula stats
- Sub-features: multiple stat tables per sport (name + display order); stats within a table; edit/delete table; per-game player stat entry (LGE-14); league leaders on public site (marketing).
- Settings / options: Stat Name; Stat Table; Stat Type = User Entry | Formula; Decimal Places; Formula (formula type only; e.g. save percentage, goals-against average); Display Order.
- Rules / limits: formula syntax/operators not documented.
- User story: As a league admin, I want sport-specific stat sheets with computed stats, so that leader boards are produced from scorekeeper entries.
- Actors: league admin, scorekeeper.
- UI generation: both
- Priority: P1
- Evidence: https://support.ezfacility.com/hc/en-us/articles/4405044313371-How-to-Manage-your-Sports, https://www.ezfacility.com/features/league-scheduling-management

### LGE-08 Round-robin schedule generator (7-step wizard)
- Sub-features: steps = select competition(s) -> locations/venues -> dates & times -> settings -> team preferences (LGE-10) -> map time slots / finalize -> balancing review -> commit games; multi-league scheduling in one run (colour per league); time-slot builder that auto-increments by game length; games grid with manual slot edits and "Update Grid"; feasibility status bar; balancing statistics (home/away per team, games per team per venue, per time slot, per weekday); unschedulable/conflict list; wizard progress auto-save and resume (2014); marketing "AI-assisted" scheduling (2026) incl. blackout dates and automatic venue-conflict resolution; re-entering the wizard on an already scheduled league offers to resume the earlier session (used to run a mid-season team through it); live "predicted completion" date on the settings step that moves as games-per-week / total games change; single time slots removable (X) to leave meal breaks.
- Settings / options: League Start Date; End Date; weekdays; League Cut Off Date (optional); dates to schedule; game start times; "It Will Be a [n] Minute Game"; Games per week; Games in Total; "Begin Current Pairings at Game [n]"; "Remove Previously Scheduled Games"; "Avoid Double Booking Facilities"; "Remove Unschedulable Games"; "All Games Back-to-Back Double Headers"; "Move Scheduled Date"; Game Rotation menu (default "Efficient Use of Times (Completes in Fewest Times)"; other values not enumerated, aimed at multi-league runs); finalize summary fields: total teams, spots available, byes, games scheduled, status, league colour; rotation option "rotate": after each game shift N spots left through the venue columns and/or down through the time rows, so games spread over fields, early/late slots and days; a fewest-locations style mode keeps a social league on few venues (exact menu names uncertain from captions); "Minutes per game" should include turnaround (60 min game + 10 min gap = 70) because it sets slot spacing.
- Rules / limits: games needing slots after the cut-off stay Unschedulable; back-to-back doubleheader = second game swaps home/away, same venue, starts at first game's end; "Begin Current Pairings at Game" regenerates mid-season without repeating matchups; status flags slot shortage or excess; balancing is best effort, not guaranteed; default rotation packs games into fewest time slots (leaves other venues free); regenerating on a live league overwrites its games (vendor advises against it); a schedule cannot be copied from an earlier league nor imported by CSV; vendor advises leaving the cut-off date blank and steering the end date through games per week; "Games in Total" should cover the regular season only, otherwise the public site shows playoff dates with unknowable matchups; all selected dates must share the same start times (different times per day require hand edits after generation; brackets are exempt); a team joining after generation needs hand-made games or a full re-run; time-slot preferences stop making sense once slots rotate; "Move Scheduled Date" can park a blackout date's games after season end; practices are booked in the core scheduler, not here.
- User story: As a league scheduler, I want to generate a balanced round-robin across chosen venues, dates and time slots, so that a full season is scheduled in minutes and can be re-run mid-season.
- Actors: league scheduler/admin.
- UI generation: both
- Priority: P0
- Evidence: https://support.ezfacility.com/hc/en-us/articles/10414795167387-How-to-Generate-a-League-Schedule-Even-Number-of-Team, https://support.ezfacility.com/hc/en-us/articles/26753867674011-How-to-Generate-a-League-Schedule-Even-Number-of-Team, https://support.ezfacility.com/hc/en-us/articles/10414786644635-How-to-Generate-a-League-Schedule-Odd-Number-of-Teams-Bye, https://support.ezfacility.com/hc/en-us/articles/26754181794331-How-to-Generate-a-League-Schedule-Odd-Number-of-Teams-Bye, https://www.ezfacility.com/press-news/press-releases/ezfacility-updates-ezleagues-scheduling-wizard, https://www.ezfacility.com/press-news/press-releases/ezfacility-launches-new-website, https://www.ezfacility.com/features/league-scheduling-management, https://www.youtube.com/watch?v=bHzYz6ZzMSE, https://www.youtube.com/watch?v=okhjK-XBid4 (t=42:56), https://www.youtube.com/watch?v=okhjK-XBid4 (t=70:30), https://www.youtube.com/watch?v=bHzYz6ZzMSE (t=11:19), https://www.youtube.com/watch?v=j4Rn9joKKpQ (t=29:36), https://www.youtube.com/watch?v=j0cg9SW8Npo (t=04:20)

### LGE-09 Bye handling for odd team counts
- Sub-features: four bye strategies selectable in wizard settings.
- Settings / options: Bye Game Scheduling Options = "No Opponent, No Location" (default; bye not shown) | "No Opponent, Use Location" (bye shown and consumes a venue/time slot) | "Bye Filler" (season one week shorter; the last round's games are redistributed as doubleheaders, e.g. 7 teams: week-7 games placed in weeks 1, 3, 5) | "Rotate League Team" (bye team gets an extra game against a team already playing that day).
- Rules / limits: Games in Total must count byes; Rotate League Team yields uneven games per team if the round robin is not completed.
- User story: As a league scheduler, I want to choose how the idle team is treated each round, so that odd-sized divisions still get a fair season.
- Actors: league scheduler.
- UI generation: both
- Priority: P0
- Evidence: https://support.ezfacility.com/hc/en-us/articles/10414786644635-How-to-Generate-a-League-Schedule-Odd-Number-of-Teams-Bye, https://support.ezfacility.com/hc/en-us/articles/26754181794331-How-to-Generate-a-League-Schedule-Odd-Number-of-Teams-Bye, https://www.ezfacility.com/features/league-scheduling-management

### LGE-10 Per-team scheduling preferences
- Sub-features: per team: date preferences (repeatable rows), weekday preferences, time-slot preferences, home-venue preference, visitor-venue preference; save per team; consumed by round-robin and pool-play generators.
- Settings / options: preference type = Date | Days of the Week | Time Slots | Home Location | Visitor Location; Preference value (value list not enumerated); Priority checkbox per preference.
- Rules / limits: soft constraints only; a team with a preference outranks a team without; Priority outranks non-priority; selectable weekdays/slots/venues are limited to those chosen earlier in the same wizard run.
- User story: As a league scheduler, I want to record each team's availability and venue wishes, so that the generator honours them where possible.
- Actors: league scheduler.
- UI generation: both
- Priority: P1
- Evidence: https://support.ezfacility.com/hc/en-us/articles/10414722181403-Picking-Team-Preferences-in-EZLeagues, https://support.ezfacility.com/hc/en-us/articles/26720911427099-Picking-Team-Preferences-in-EZLeagues, https://www.ezfacility.com/features/league-scheduling-management

### LGE-11 Pool-play schedule generation (tournaments)
- Sub-features: same 7-step generator applied to a tournament; games-per-team total; multi-tournament colouring; conflicts/unschedulable list under final step.
- Settings / options: start date; dates to schedule; time slots; game length; games per team in total; League Cut Off Date; Remove Previously Scheduled Games; Avoid Double Booking Facilities; Remove Unschedulable Games; All Games Back-to-Back Double Headers; Begin Current Pairings at Game; Game Rotation menu.
- Rules / limits: cut-off stops the generator consuming more time than needed; overflow games remain Unschedulable; pool definition (how teams are split into pools) is not described; video: one published group is one pool; a multi-pool event (pools A-F, winners advance) is not supported, each pool is published separately and winners are moved into a new group by hand; support names pool play as the format raising most questions.
- User story: As a tournament director, I want pool-play games generated before bracket play, so that every team gets a fixed number of games.
- Actors: tournament scheduler.
- UI generation: both
- Priority: P1
- Evidence: https://support.ezfacility.com/hc/en-us/articles/10414752794395-How-to-Generate-a-Pool-Play-Schedule-in-EZLeagues, https://support.ezfacility.com/hc/en-us/articles/26754163075099-How-to-Generate-a-Pool-Play-Schedule-in-EZLeagues, https://www.youtube.com/watch?v=j4Rn9joKKpQ (t=17:21)

### LGE-12 Elimination bracket generation (single and double)
- Sub-features: 5-step wizard = tournament(s) -> locations -> dates + time slots per date -> bracket preferences -> preview pairings -> create bracket; rename regions and rounds; back-navigation; bracket published to the public site on creation.
- Settings / options: "Keep Winning Teams On The Same Field" (on = winners stay on home field when possible; off = optimise time use); Region Settings (names); Round Settings (names); Lower Bracket Scheduling (double elimination) = AB/BA (loser crosses to the opposite half; common) | AB/AB (keeps position; rare); earliest start + Add Time Slot; game length minutes; multi-select dates.
- Rules / limits: time slots must be defined for every selected date; pairings come from seeds (LGE-03); advancement of winners after score entry is not described; non-power-of-two fields are supported (a 13-team double elimination fills a 16-slot bracket with byes for seeds 1-3, visible in the preview); no automatic league-to-playoff rollover: staff move or duplicate the top teams into a new parent group, publish it as an elimination tournament and run this wizard.
- User story: As a tournament director, I want a seeded bracket placed onto venues and time slots, so that the knockout stage is published without manual drawing.
- Actors: tournament scheduler.
- UI generation: both
- Priority: P0
- Evidence: https://support.ezfacility.com/hc/en-us/articles/10414756274971-How-to-Create-a-Tournament-Schedule-Single-Elimination-Bracket, https://support.ezfacility.com/hc/en-us/articles/26753390899995-How-to-Create-a-Tournament-Schedule-Single-Elimination-Bracket, https://support.ezfacility.com/hc/en-us/articles/10414765514779-How-To-Create-a-Tournament-Schedule-Double-Elimination-Bracket, https://support.ezfacility.com/hc/en-us/articles/26753407797019-How-To-Create-a-Tournament-Schedule-Double-Elimination-Bracket, https://www.ezfacility.com/features/league-scheduling-management, https://www.youtube.com/watch?v=j0cg9SW8Npo (t=13:00), https://www.youtube.com/watch?v=j4Rn9joKKpQ (t=24:29), https://www.youtube.com/watch?v=okhjK-XBid4 (t=71:35)

### LGE-13 Three-games-guaranteed format (8 teams)
- Sub-features: consolation-style format through the same 5-step bracket wizard.
- Settings / options: same bracket preferences as double elimination (Lower Bracket Scheduling AB/BA | AB/AB; Keep Winning Teams On The Same Field; region/round names).
- Rules / limits: exactly 8 teams, no other size supported.
- User story: As a tournament director, I want a format where no team goes home after one loss, so that entry fees feel justified.
- Actors: tournament scheduler.
- UI generation: both
- Priority: P1
- Evidence: https://support.ezfacility.com/hc/en-us/articles/10414776053531-How-To-Create-a-Three-Games-Guaranteed-Schedule-8-Team-Tournament, https://support.ezfacility.com/hc/en-us/articles/26753410817051-How-To-Create-a-Three-Games-Guaranteed-Schedule-8-Team-Tournament, https://support.ezfacility.com/hc/en-us/articles/4405044226587-How-to-Publish-a-Group-to-EZLeagues-from-EZFacility

### LGE-14 Result entry, game status and discipline tracking
- Sub-features: score-management list filtered by League and Game Status; pick date; add/update result per game; participation per team; sportsmanship rating; bonus points; per-player stat entry; postpone (prompts new date/time); cancel; links from each game to officials and game card; confirm-both-scores step and an overtime / extra-time entry on the score form; saved score shows on the public schedule.
- Settings / options: Participation = Full | Default | Forfeit; game status values named: Postponed, Cancelled (plus scheduled/played implied); Score; Sportsmanship Rating (optional, only if tracked); Bonus Points (extra league points); discipline caps on the competition (Maximum Defaults, Maximum Forfeits, Minimum Sportsmanship).
- Rules / limits: cancelled games ignored by standings; after save the score replaces the add-result link; enforcement action when a team exceeds caps is not described; no live or auto-updating scoring, every score is keyed by hand; known issue (late 2023): home team listed above the away team leads to entry mistakes.
- User story: As a scorekeeper, I want to enter results with forfeits, sportsmanship and player stats, so that standings and leaders update immediately.
- Actors: scorekeeper, league admin.
- UI generation: both
- Priority: P0
- Evidence: https://support.ezfacility.com/hc/en-us/articles/10414799252763-How-to-Manage-Scores-in-EZLeagues, https://support.ezfacility.com/hc/en-us/articles/26754230417819-How-to-Manage-Scores-in-EZLeagues, https://support.ezfacility.com/hc/en-us/articles/4405044295707-How-to-Manage-Scores, https://support.ezfacility.com/hc/en-us/articles/10414682862235-How-to-Create-a-Tournament-in-EZLeagues, https://www.youtube.com/watch?v=j4Rn9joKKpQ (t=37:47), https://www.youtube.com/watch?v=j4Rn9joKKpQ (t=25:31)

### LGE-15 Officials roster and game assignment
- Sub-features: add/edit/delete official; qualification by sport and by age group (dual-list pickers, move one / move all); associate officials to a game from score management; marketing adds availability tracking, schedules, game reminders and communications to referees.
- Settings / options: First name, Last name (required); Sports qualified; Age Groups qualified; other attributes unspecified.
- Rules / limits: whether assignment is restricted to qualified officials, pay rates and availability data are not documented; no bulk assignment: officials are attached one game at a time, from the game edit form or score management.
- User story: As a league admin, I want to assign qualified referees to games, so that every game is covered and officials know their schedule.
- Actors: league admin, official.
- UI generation: both
- Priority: P0
- Evidence: https://support.ezfacility.com/hc/en-us/articles/4405044321307-How-to-Add-Officials, https://support.ezfacility.com/hc/en-us/articles/26569254117915-How-to-Add-Officials, https://support.ezfacility.com/hc/en-us/articles/26754230417819-How-to-Manage-Scores-in-EZLeagues, https://www.ezfacility.com/features/league-scheduling-management, https://www.ezfacility.com/capterra-sports-league-management/, https://www.youtube.com/watch?v=j4Rn9joKKpQ (t=26:32)

### LGE-16 Game cards (scoresheets)
- Sub-features: per-game card from score management; "Manual Game Cards" report (any two teams, even from different leagues, plus date/time; no scheduled game needed (inferred)); "Game Cards by Sport" batch report (one page per scheduled game in a date range); export Excel or PDF; direct print; page count.
- Settings / options: manual: Home team, Away team, date, time; batch: Sport, start date, end date.
- Rules / limits: batch cards populate from scheduled games of that sport; card layout/contents (roster lines, stat columns) not described.
- User story: As a league admin, I want to print scoresheets for a night's games in one run, so that officials have pre-filled cards.
- Actors: league admin.
- UI generation: both
- Priority: P1
- Evidence: https://support.ezfacility.com/hc/en-us/articles/26530327505947-How-to-Print-Manual-Game-Cards, https://support.ezfacility.com/hc/en-us/articles/26530549235995-How-to-Print-Multiple-Game-Cards, https://support.ezfacility.com/hc/en-us/articles/26754230417819-How-to-Manage-Scores-in-EZLeagues

### LGE-17 Competition list filters, shareable public URL and embed
- Sub-features: filter and sort league/tournament lists; generate a public URL reflecting the filter; embed code (iframe) for the same view; default admin-list filters per page (LGE-19).
- Settings / options: filters League Status, Sport, Season, Age Group, Division; Sort By; sort order; "Generate Public URL"; "Use as iFrame" checkbox; embed URL parameter `styled=1` opts the iframe into the redesigned look (omit it to keep the old look).
- Rules / limits: embed code is only produced after a public URL was generated; requires a signed-in admin; the embed shows the league-list part of the page, from which visitors click through to a league; code can be pasted into any CMS.
- User story: As a league admin, I want a link showing only, say, this season's adult leagues, so that I can embed it on my own website.
- Actors: league admin; public viewers.
- UI generation: both
- Priority: P1
- Evidence: https://support.ezfacility.com/hc/en-us/articles/4405044330523-How-to-Filter-your-Leagues-and-Tournaments, https://www.youtube.com/watch?v=okhjK-XBid4 (t=59:17)

### LGE-18 Public league website
- Sub-features: per-facility public site with schedules, standings, scores, leagues/tournaments, brackets, fees and rules text, registration links; menu; linkable and iframe-embeddable sections; mobile-optimised tables; Table vs Card view toggle; schedule default list view with grid toggle (2023-03); date picker open by default and collapsible; print / save-PDF of a day's schedule; auto-resized logo/banner; league leaders and player stats (marketing); standings, stats and schedules surfaced in the branded mobile app (marketing); redesign (late 2022) is mobile-first with a hamburger menu; quick stats (league leaders, top offences and defences); home page with today's games, news and a rotating picture / advert area; calendar date pick on the schedule page; league page with a "Register online" link and tabs standings / schedule / news / details / player stats; click a team to see only its schedule; stat-abbreviation legend popup; feedback form, About Us, Contact Us; player-facing public sign-up account.
- Settings / options: view mode Table | Card; schedule view List (default since 2023-03-09) | Grid; per-competition display checkboxes (LGE-01/02).
- Rules / limits: only competitions in the league system appear; fee and info text come from sport defaults or the publish form; the "Register online" link is filled automatically for a competition published from a group, otherwise a registration URL can be pasted; the public sign-up account is separate from the core client-portal account (two logins).
- User story: As a player or parent, I want a public page with my schedule and standings on my phone, so that I do not have to call the facility.
- Actors: public visitors, players, league admin.
- UI generation: both
- Priority: P1
- Evidence: https://support.ezfacility.com/hc/en-us/articles/4405044385819-How-to-View-your-EZLeagues-Public-Website, https://support.ezfacility.com/hc/en-us/articles/26754276440219-How-to-View-your-EZLeagues-Public-Website, https://support.ezfacility.com/hc/en-us/articles/11297336305691-December-15th-2022-Release-Notes, https://support.ezfacility.com/hc/en-us/articles/13526384977307-March-9th-2023-Release-Notes, https://www.ezfacility.com/blog/software-release-ezleagues-websites, https://www.ezfacility.com/features/league-scheduling-management, https://www.ezfacility.com/blog/how-to-grow-your-business-with-sports-club-management-software, https://www.youtube.com/watch?v=okhjK-XBid4 (t=56:13), https://www.youtube.com/watch?v=bHzYz6ZzMSE (t=44:01)

### LGE-19 Public-site options, branding and facility info
- Sub-features: menu item visibility; colour scheme; link colour (2023-03); default filters/sort for the admin leagues page and tournaments page; search-engine indexing switch; logo/banner upload; facility contact details and About Us text.
- Settings / options: Menu Options checkboxes (items not enumerated); Site Colors (colour code per element; includes primary colour and Link Color; picker or hex, validated since 2024-01); Leagues Page Options and Tournament Page Options (Status, Sport, Season, Age Group, Division, sort); Search Engine Indexing checkbox; Facility Logo file; contact fields (names not listed; some required); About Us.
- Rules / limits: banner JPG only, suggested 370 x 60 px, may need a refresh to appear; a white primary colour can hide text; page options affect only the admin's initial list.
- User story: As a league admin, I want to brand the public site and control its menu, so that it matches my facility.
- Actors: league admin.
- UI generation: both
- Priority: P1
- Evidence: https://support.ezfacility.com/hc/en-us/articles/4405044374171-How-to-Configure-your-Site-Options, https://support.ezfacility.com/hc/en-us/articles/4405044358811-How-to-Upload-your-Facility-Banner, https://support.ezfacility.com/hc/en-us/articles/26531757019291-How-to-Upload-your-Facility-Banner, https://support.ezfacility.com/hc/en-us/articles/4405044379547-How-to-Add-Update-your-Facility-Information, https://support.ezfacility.com/hc/en-us/articles/13526384977307-March-9th-2023-Release-Notes, https://support.ezfacility.com/hc/en-us/articles/22122496577179-January-17th-2024-Release-Notes

### LGE-20 Public-site links directory
- Sub-features: add / edit / delete external links; grouped by category on a public Links page; click-through.
- Settings / options: Website address (entered without scheme, from "www" or first subdomain); Description; Category; More Information.
- Rules / limits: none stated.
- User story: As a league admin, I want a curated links page (governing bodies, sponsors), so that players find related resources.
- Actors: league admin; public visitors.
- UI generation: both
- Priority: P2
- Evidence: https://support.ezfacility.com/hc/en-us/articles/4405044362651-How-to-Add-and-Manage-Links, https://support.ezfacility.com/hc/en-us/articles/26596651427867-How-to-Add-and-Manage-Links

### LGE-21 Public-site photo gallery
- Sub-features: upload photo with caption; feature on home page; delete.
- Settings / options: Title caption; image file; featured flag.
- Rules / limits: JPG only; 200 KB cap (larger images auto-shrunk).
- User story: As a league admin, I want to post game photos, so that the public site feels alive.
- Actors: league admin; public visitors.
- UI generation: both
- Priority: P2
- Evidence: https://support.ezfacility.com/hc/en-us/articles/4405044388763-How-to-Add-Photo-s-to-your-Public-Site, https://support.ezfacility.com/hc/en-us/articles/26662662847387-How-to-Add-Photo-s-to-your-EZLeagues-Public-Site

### LGE-22 Classifieds board (player/team/coach matching)
- Sub-features: visitors self-register an account and post ads; category filter; admin can only delete ads.
- Settings / options: categories Player Seeking Team | Team Seeking Player | Team Seeking Coach | Coach Seeking Team; Show Ads filter.
- Rules / limits: poster accounts are separate from facility clients and invisible to the admin; no pre-moderation.
- User story: As a free agent, I want to advertise that I need a team, so that captains can recruit me.
- Actors: public visitors (posters), league admin (moderation).
- UI generation: both
- Priority: P2
- Evidence: https://support.ezfacility.com/hc/en-us/articles/4405044372123-How-to-Manage-your-Classifieds, https://www.ezfacility.com/features/league-scheduling-management

### LGE-23 Pickup-game listings
- Sub-features: add / edit / delete informational listings for one-off games on the public site, each carrying a pasted registration link.
- Settings / options: Day; Sport; Time (these three are the minimum); More Info (fees etc.); Registration link.
- Rules / limits: cannot be published from a registration group like leagues/tournaments; link is pasted manually; no schedule or standings behind it.
- User story: As a league admin, I want to advertise drop-in games with a sign-up link, so that casual players can find and pay for them.
- Actors: league admin; public visitors.
- UI generation: both
- Priority: P2
- Evidence: https://support.ezfacility.com/hc/en-us/articles/10414721006875-How-to-Manage-Pickup-Games-in-EZLeagues, https://support.ezfacility.com/hc/en-us/articles/26686781401755-How-to-Manage-Pickup-Games-in-EZLeagues

### LGE-24 TV display board
- Sub-features: full-screen page for a lobby TV / cast screen: facility name, current date-time, today's games (time, status, event), auto-rotating; marketing adds standings, upcoming games and player stats.
- Settings / options: none documented (4 games per page, 5-second rotation are fixed).
- Rules / limits: runs only while the browser window is open; needs a dedicated screen/computer or casting.
- User story: As facility staff, I want a lobby board that cycles today's games, so that teams find their field without asking.
- Actors: facility staff; spectators.
- UI generation: both
- Priority: P1
- Evidence: https://support.ezfacility.com/hc/en-us/articles/4405044351259-How-to-Utilize-the-TV-Display, https://support.ezfacility.com/hc/en-us/articles/26594931297435-How-to-Utilize-the-TV-Display, https://www.ezfacility.com/industries/soccer-scheduling-software, https://www.ezfacility.com/features/league-scheduling-management

### LGE-25 Team schedule calendar subscription
- Sub-features: per-team subscribe URL exposed next to each team in the public standings section; one-click copy; works with Google Calendar and iOS/iPadOS subscribed calendars; games appear as events.
- Settings / options: none.
- Rules / limits: competition must be published to the league site; one URL per team.
- User story: As a player, I want my team's games in my phone calendar, so that reschedules reach me automatically.
- Actors: players, parents, coaches.
- UI generation: both
- Priority: P1
- Evidence: https://support.ezfacility.com/hc/en-us/articles/4404311560475-EZLeagues-Team-Schedule-Calendar-Sync-Google-Calendar, https://support.ezfacility.com/hc/en-us/articles/4404321359515-EZLeagues-Team-Schedule-Calendar-Sync-IPad-and-IPhone

### LGE-26 League-admin users, roles and SSO
- Sub-features: separate admin sign-in to the league app; single sign-on from the core product ("Admin Edit" link); SSO users can edit their own profile; role tiers; two-way SSO (late 2022): at the first core-product login after the update the user is prompted to link the two accounts, after which moving in either direction signs in automatically.
- Settings / options: roles SuperUser | Admin.
- Rules / limits: since 2024-01-17 Admins cannot create or edit other users nor modify a SuperUser; before linking, the two products needed separate usernames and passwords.
- User story: As an owner, I want league staff limited to league tasks, so that they cannot manage users.
- Actors: owner (SuperUser), league admin.
- UI generation: both
- Priority: P1
- Evidence: https://support.ezfacility.com/hc/en-us/articles/14655161654811-April-18th-2023-Release-Notes, https://support.ezfacility.com/hc/en-us/articles/22122496577179-January-17th-2024-Release-Notes, https://support.ezfacility.com/hc/en-us/articles/4405044226587-How-to-Publish-a-Group-to-EZLeagues-from-EZFacility, https://www.youtube.com/watch?v=okhjK-XBid4 (t=65:26)

### LGE-27 League data in the public API; add-on packaging
- Sub-features: league endpoints listed among public REST API resource groups (OAuth2 client-credentials, Swagger sandbox); league module sold as an add-on bundled into the top plan.
- Settings / options: plan gating (add-on vs included in Premium).
- Rules / limits: endpoint list not public in the notes.
- User story: As an integrator, I want schedules and standings via API, so that I can render them on the club's own site.
- Actors: developer, owner.
- UI generation: both
- Priority: P1
- Evidence: https://www.ezfacility.com/ez-api-services, https://www.ezfacility.com/plans-pricing/pricing-results

### LGE-28 Ladder standings (racquet sports)
- Sub-features: ladder standings published online for tennis and pickleball (marketing only).
- Settings / options: none documented.
- Rules / limits: no help-center coverage; challenge rules unknown.
- User story: As a tennis director, I want a published ladder, so that members can see rankings.
- Actors: league admin; members.
- UI generation: both
- Priority: P2
- Evidence: https://www.ezfacility.com/industries/tennis-club-software, https://www.ezfacility.com/industries/pickleball-facilities

### LGE-29 Third-party team-communication sync (PlayerGrid, legacy)
- Sub-features: rosters and schedules pushed to an external team-messaging service; postponement notifications by email/text/push.
- Settings / options: none documented.
- Rules / limits: announced 2012-12-06; partner probably defunct.
- User story: As a coach, I want my roster and schedule in a team-chat tool, so that I can message players.
- Actors: coach, players.
- UI generation: Classic
- Priority: v2-adapter
- Evidence: https://www.ezfacility.com/blog/ezfacility-partners-with-playergrid-to-enhance-league-management-features

### LGE-30 League email alerts (game reminders and game-change notices)
- Sub-features: automatic first and second game-reminder emails to rostered players; game-change alert that emails the players and captains of the affected teams when a published game is postponed, cancelled, rescheduled or moved to another venue; independent of the core product's session reminders.
- Settings / options: First reminder; Second reminder (lead time each; one demo gives a range from 2 days down to 15 minutes before game start); Game Change Alerts checkbox (vendor recommends leaving it on).
- Rules / limits: email only, no text / SMS; reaches only players with a valid email who were published from the group into the league app; where the settings live differs by source (an Email Alerts section under Administration vs per-sport settings, see unknowns).
- User story: As a player, I want a reminder before my game and a notice when it moves, so that I turn up at the right field at the right time.
- Actors: league admin; players, captains.
- UI generation: both
- Priority: P1
- Evidence: https://www.youtube.com/watch?v=okhjK-XBid4 (t=60:18), https://www.youtube.com/watch?v=bHzYz6ZzMSE (t=34:53), https://www.youtube.com/watch?v=j4Rn9joKKpQ (t=35:45), https://www.youtube.com/watch?v=edzJ6kuAvMQ (t=17:29), https://www.youtube.com/watch?v=edzJ6kuAvMQ (t=21:33)

### LGE-31 Manual game add / edit and post-season games
- Sub-features: "Add/Edit Games" screen to add games by hand (playoffs after a generated regular season, games for a late team); edit a game (pencil): date, time, length, venue, officials, scores; a date change lists other games on that venue around that time; swap teams between games; public site shows "postseason" plus the round label.
- Settings / options: Game Type = regular (default for generated games) | post season; round label (free text, e.g. quarterfinals); placeholder opponent labels (free text such as "first place").
- Rules / limits: placeholder labels never resolve from standings; a league cannot spawn a bracket (see LGE-12); a post-season game can be re-dated later.
- User story: As a league admin, I want to add and label playoff games by hand after the regular season, so that the public schedule shows the post-season without a separate tournament.
- Actors: league admin.
- UI generation: both
- Priority: P0
- Evidence: https://www.youtube.com/watch?v=j4Rn9joKKpQ (t=20:24), https://www.youtube.com/watch?v=bHzYz6ZzMSE (t=23:40), https://www.youtube.com/watch?v=bHzYz6ZzMSE (t=24:43)

### LGE-32 League operational reports
- Sub-features: Reports tile in the league app: Games by Venue; Officials report (every venue and match per official, to hand out); participant demographic reports (by gender, ranking, team); game-card reports (LGE-16).
- Settings / options: Games by Venue: all venues or one, date range.
- Rules / limits: export formats and further filters not shown.
- User story: As a league admin, I want a per-venue game list and a per-official assignment sheet, so that staff and referees know the day's plan.
- Actors: league admin, officials.
- UI generation: both
- Priority: P1
- Evidence: https://www.youtube.com/watch?v=bHzYz6ZzMSE (t=31:50)

### LGE-33 Public-site sponsor advertising
- Sub-features: Advertising tile; sponsor adverts shown in the right-hand column of the public site; several adverts rotate.
- Settings / options: image; click-through URL.
- Rules / limits: adverts must be an image with a link; rotation interval not stated.
- User story: As a league admin, I want sponsor banners on the public site, so that I can sell sponsorship.
- Actors: league admin; public visitors.
- UI generation: both
- Priority: P2
- Evidence: https://www.youtube.com/watch?v=bHzYz6ZzMSE (t=40:58)

## Groups & Online Registration

### REG-01 Group (registerable program container) creation
- Sub-features: create group; used for leagues, tournaments, camps, clinics, workshops, parties, fundraisers; in-group tabs for online registration, self-service publishing and league publishing; group list columns (Group Name, Description, Registration Balance, Invoice Balance, Total Subgroups) with quick icons (email, edit, delete); onboarding checklist for groups (title only).
- Settings / options: Name (required set not specified); Session, Sport, Age/Division (optional classifiers, REG-03); Revenue Category; Maximum individuals; price; Auto-Archive after (date); waitlist behaviour default (REG-09); Group Status (REG-05); Contact person and Contact email (shown on the client-portal group page, not on the registration page); Max Subgroups (e.g. number of teams); Allow Wait List with a "use default" checkbox; subgroup label (default "Team", editable).
- Rules / limits: classifiers double as filters in staff list and in the client portal; 0 in Max Individuals or Max Subgroups means unlimited; Price is mainly what staff-side registration uses and is also shown in the client portal; classifier values can be created inline and reused.
- User story: As an admin, I want one container per program or league season with capacity and price, so that people can be registered and billed against it.
- Actors: admin, front desk.
- UI generation: both
- Priority: P0
- Evidence: https://support.ezfacility.com/hc/en-us/articles/4415445419035-How-to-Create-a-Group, https://www.ezfacility.com/blog/software-release-groups-new-ui, https://www.youtube.com/watch?v=VuUR1Y9bhjQ, https://support.ezfacility.com/hc/en-us/articles/52230184836379-Onboarding-Checklist-Membership-Checklist-Groups-Checklist (title only, body not read), https://www.youtube.com/watch?v=VuUR1Y9bhjQ (t=05:08)

### REG-02 Subgroup hierarchy (teams, sessions, divisions)
- Sub-features: add subgroup under any group (multi-level: parent / grandparent / child / grandchild grid, current node bolded); copy-from-parent; subgroup label configurable (team by default, e.g. session, class); re-parent a subgroup to another group; side navigation between related groups; optional revenue-category inheritance from parent with prompt on parent edit; alphanumeric ordering of subgroups.
- Settings / options: Name; Revenue Category; Maximum individuals; price; "Copy from parent group"; Save & Close | Save & Continue; account setting "Subgroups Inherit Revenue Category from Parent Group".
- Rules / limits: copy also copies the name, so it must be renamed; Classic re-parent reuses the "Move Selected Members" bulk action and ends with "Move Subgroup"; ordering fixed 2023-08-16; the 2013 launch of nested groups states unlimited levels (team in division in conference in league).
- User story: As an admin, I want teams or sessions as children of a league or camp, so that registrants choose one and capacity is tracked per child.
- Actors: admin.
- UI generation: both (re-parent documented for Classic only)
- Priority: P0
- Evidence: https://support.ezfacility.com/hc/en-us/articles/4415441339547-How-to-Create-a-Subgroup, https://support.ezfacility.com/hc/en-us/articles/4404931863963-How-to-Move-a-Sub-Group-Between-Groups, https://support.ezfacility.com/hc/en-us/articles/17981009155995-August-16th-2023-Release-Notes, https://www.ezfacility.com/blog/updated-subgroup-inheritance-trainer-performance-report-e-mail-procedures-and-more, https://www.ezfacility.com/blog/software-release-groups-new-ui, https://www.youtube.com/watch?v=tqMhVWKcLfQ (t=00:50)

### REG-03 Group classifiers (Session / Sport / Age-Division lists)
- Sub-features: three admin-maintained lists; add, rename, delete-if-unused; usage count drilling to the groups using a value; used for group-list filters, move-target filters, portal filters and email-campaign targeting.
- Settings / options: list kind = Sessions | Sports | Age/Divisions; Title.
- Rules / limits: values in use cannot be removed; values can also be created inline while creating a group.
- User story: As an admin, I want consistent season/sport/age labels, so that groups can be filtered and marketed to.
- Actors: admin.
- UI generation: both (admin screen documented for Classic)
- Priority: P1
- Evidence: https://support.ezfacility.com/hc/en-us/articles/4404931898779-How-to-Set-Up-Group-Categories, https://support.ezfacility.com/hc/en-us/articles/4415445419035-How-to-Create-a-Group

### REG-04 Group search, views and filters
- Sub-features: name search (full or partial) limited to active by default with opt-in to completed; saved views; classifier filters; status colouring.
- Settings / options: View = Recently Accessed (default) | Recently Created | All Groups | All Completed | Deleted Groups | Search Results; filters Session, Sport, Age/Division; New UI filter active / upcoming / completed; colour: Classic completed = yellow, New completed = blue.
- Rules / limits: Recently Accessed holds the last 150 active groups accessed.
- User story: As front-desk staff, I want to find a group quickly among hundreds, so that I can register a walk-in.
- Actors: admin, front desk.
- UI generation: both (views documented for Classic)
- Priority: P1
- Evidence: https://support.ezfacility.com/hc/en-us/articles/4404931875227-How-to-Find-Search-Groups, https://www.ezfacility.com/blog/software-release-groups-new-ui

### REG-05 Group lifecycle: complete, auto-archive, delete and restore
- Sub-features: manual status change to Completed; scheduled auto-archive date; soft delete; undelete from the Deleted view.
- Settings / options: Group Status = Active | Completed | Archived (last two possibly the same state); "Auto-Archive after" date; action "Undelete Group".
- Rules / limits: completed groups leave the active list; non-active groups cannot be a move destination (REG-08); deleted groups are recoverable (retention period unknown).
- User story: As an admin, I want finished seasons to drop out of working lists but stay reportable and restorable, so that the list stays usable.
- Actors: admin.
- UI generation: both (undelete documented for Classic; status/auto-archive for New)
- Priority: P0
- Evidence: https://support.ezfacility.com/hc/en-us/articles/23929852504219-How-to-Mark-a-Group-as-Completed, https://support.ezfacility.com/hc/en-us/articles/4404924800539-How-to-Undelete-a-Deleted-Group, https://support.ezfacility.com/hc/en-us/articles/4404931875227-How-to-Find-Search-Groups

### REG-06 Group page personalisation and member-grid columns
- Sub-features: collapse/expand panels (Group Details, Group Members, Sub Groups); drag panels to reorder; drag column headers to reorder member grid; column customisation (New UI); custom client fields and comments shown as member-grid columns, hide/show per group.
- Settings / options: per-user remembered layout (collapsed state, panel order, column order).
- Rules / limits: persistence is per user; custom-field columns date from 2016-01-20.
- User story: As a staff user, I want the roster grid arranged my way, so that the fields I check most are visible.
- Actors: staff user.
- UI generation: both (drag/collapse documented for Classic; column picker for New)
- Priority: P2
- Evidence: https://support.ezfacility.com/hc/en-us/articles/4404924758427-How-to-Hide-Expand-Group-Details-Group-Members-or-Sub-Groups, https://support.ezfacility.com/hc/en-us/articles/4404931932955-How-to-Drag-and-Drop-Group-Details, https://support.ezfacility.com/hc/en-us/articles/4404931935259-How-to-Reorder-Columns-in-your-Groups-Subgroups, https://www.ezfacility.com/blog/ez-features-fixes-check-out-whats-new, https://www.ezfacility.com/blog/software-release-groups-new-ui

### REG-07 Staff-side registration into a group or subgroup
- Sub-features: register an existing or newly created client; choose a program fee; review step; take payment now or defer (invoice issued); register into a subgroup via the related-groups grid; pay open group invoices from the client's Groups tab ("Pay Now"); email group members (cross-location fix 2024-04); remove a member (trash icon) with a four-way choice: reverse billing and delete | delete but keep billing | show invoice only | cancel; pickup games can be run as a group with a New Team-style fee.
- Settings / options: Program Fees catalogue under location settings (description, amount); payment method list includes Bank Transfer (2023-06-28) alongside card/cash etc.; pay now | pay later.
- Rules / limits: a client can hold at most one registration per subgroup and one at parent level; fee description should mirror the group name (convention, not enforced); a billing reversal needs a reason and the original bill date and becomes account credit (the card is not refunded automatically, even with integrated processing); no photo player ID card (name, date of birth and custom fields only).
- User story: As front-desk staff, I want to enrol a walk-in into a team and take payment or invoice them, so that the roster and ledger stay in sync.
- Actors: front desk, admin.
- UI generation: both (flow documented for New)
- Priority: P0
- Evidence: https://support.ezfacility.com/hc/en-us/articles/4415441342235-How-to-Manually-Register-a-Client-into-a-Group-or-a-Sub-group, https://support.ezfacility.com/hc/en-us/articles/16731304236571-June-28th-2023-Release-Notes, https://support.ezfacility.com/hc/en-us/articles/22122496577179-January-17th-2024-Release-Notes, https://support.ezfacility.com/hc/en-us/articles/24695840840603-April-10th-2024-Release-Notes, https://www.youtube.com/watch?v=VuUR1Y9bhjQ (t=50:10), https://www.youtube.com/watch?v=VuUR1Y9bhjQ (t=36:54)

### REG-08 Move members between groups / subgroups
- Sub-features: bulk-select members and move to another group or subgroup; target picker tree with classifier and name filters (matches highlighted); optional revenue-category rewrite; result summary with attempted / succeeded / failed counts.
- Settings / options: "Update Revenue Category" checkbox (on = take destination's category; off = keep original); filters Session, Sport, Age/Division, group name.
- Rules / limits: move fails for members already registered in the destination node; destination must be Active; all selected members go to one destination.
- User story: As an admin, I want to shift players between teams after evaluations, so that I do not refund and re-register them.
- Actors: admin, front desk.
- UI generation: both
- Priority: P1
- Evidence: https://support.ezfacility.com/hc/en-us/articles/4404924790939-How-to-Move-a-Client-Between-Groups-Sub-Groups, https://support.ezfacility.com/hc/en-us/articles/4415441379483-How-to-Move-a-Client-Between-Groups-or-Sub-Groups

### REG-09 Group waitlist and enrolment promotion
- Sub-features: mark members waitlisted; promote to enrolled (bulk); "Bill Now" on promotion; visual flag for waitlisted rows.
- Settings / options: member status Enrolled | Waitlisted; actions "Set as Waitlisted", "Set as Enrolled", "Bill Now"; waitlist behaviour is an account default overridable per group; display: Classic pink highlight, New italics.
- Rules / limits: billing happens at enrolment, not at waitlisting; automatic promotion when a spot opens is not described for groups.
- User story: As an admin, I want overflow registrants parked without charge and promoted when space opens, so that I never oversell a team.
- Actors: admin, front desk.
- UI generation: both
- Priority: P0
- Evidence: https://support.ezfacility.com/hc/en-us/articles/4404931880219-How-to-Remove-Client-from-Waitlist, https://support.ezfacility.com/hc/en-us/articles/4415445455771-How-to-Remove-or-Add-a-Client-using-Waitlist

### REG-10 Per-group online registration configuration
- Sub-features: online-registration tab per group; one or more fees; registration window; staff notification recipients; payment-collection policy; deposits and instalment schedule with auto-pay of the remainder; coupon acceptance; rich-text online description with link editor; shareable registration link (copy); publish to the client portal with a publish name (owned by the portal module); registration deposits and team-or-individual registration (marketing).
- Settings / options: fee type = Individual | With a Team (join existing subgroup; label customisable, Classic calls it "With a Choice") | New Team (creates a subgroup; Classic "Team Fee"); fee description; amount; deposit; custom payment schedule; Auto-Pay options; Open Date; Close Date; Notification Emails (semicolon-separated); Payment requirement = allow pay later | require immediate online card payment | require card details but allow no charge or pay later | require card details, do not charge; "Force storing of CC info"; "Allow coupon codes"; "Disallow partial credit card payments"; "Enable Online Registration" checkbox (Classic); Online description; Registration link; Publish Name / Publish Group; payment schedule fields = first auto-draft date, frequency (weekly in the demo), number of payments; Registration closed message (shown after the close date); per-group overrides of the account default payment / store-card / coupon settings.
- Rules / limits: registration is inactive until at least one fee exists; no open date = opens immediately; open/close take effect at 00:00 of the date (no time of day); Classic: editing a saved fee un-ticks the enable box; "Disallow partial" forces full payment and overrides the deposit; force-store saves the card on the client profile; payment requirement and force-store default from account settings (REG-11); the balance after the deposit is divided as evenly as possible over the scheduled payments; online description limit stated as 800,000 characters; no member vs non-member pricing online (fees may be titled that way but membership is not detected; workarounds are two groups or a member coupon code); capacity (max individuals / max teams) lives on the group, the league app has no size limit; legacy 2013 behaviour: every nesting level has its own registration form and a registrant joins the chosen level plus the level directly below.
- User story: As an admin, I want each program to have its own fees, window and payment rules online, so that families can self-register and pay the way I require.
- Actors: admin; registrants.
- UI generation: both
- Priority: P0
- Evidence: https://support.ezfacility.com/hc/en-us/articles/17323515477659-How-to-Allow-Clients-to-Register-for-a-Group-Online, https://support.ezfacility.com/hc/en-us/articles/31149286284187-How-to-Set-Up-Online-Registration-for-a-Group-in-the-Classic-EZFacility-Experience, https://support.ezfacility.com/hc/en-us/articles/28746953502875-How-to-Publish-a-Group-to-Self-Service, https://support.ezfacility.com/hc/en-us/articles/19847009538203-October-25th-2023-Release-Notes, https://support.ezfacility.com/hc/en-us/articles/20241459046683-November-8th-2023-Release-Notes, https://support.ezfacility.com/hc/en-us/articles/22122496577179-January-17th-2024-Release-Notes, https://www.ezfacility.com/features/league-scheduling-management, https://www.youtube.com/watch?v=VuUR1Y9bhjQ (t=24:31), https://www.youtube.com/watch?v=VuUR1Y9bhjQ (t=29:38), https://www.youtube.com/watch?v=VuUR1Y9bhjQ (t=34:51), https://www.youtube.com/watch?v=j4Rn9joKKpQ (t=34:43), https://www.youtube.com/watch?v=okhjK-XBid4 (t=49:04), https://www.youtube.com/watch?v=unZH32QU1nc (t=05:30)

### REG-11 Account-wide online-registration defaults
- Sub-features: defaults applied to every new group registration setup and overridable per group; form-field configuration; roster-entry mode for captains (REG-26).
- Settings / options: default payment requirement; default force-store-card; default auto-pay settings; default notification recipient; default coupon acceptance; "Subgroups Inherit Revenue Category from Parent Group"; Gender field visible / required (2024-04-24); phone label "Mobile" (2023); video list (Administration > Online Registration): banner logo with Show Large Header and header alignment; accepted card types (Visa / Mastercard default, Amex / Discover optional); Disallow Partial Credit Card Payments; Allow Storing of Card; Force Storing; Include fee description on billing item; Enable Autopay with payment schedule (optionally also for wait-listed clients); CVN required; Allow coupon codes; Use revenue-category taxes; one registration Document; Display Number of Openings (live count of spots / teams left); Allow Wait List; Allow Online Waiver Fulfilment; Remember Form Fields; page background colour; confirmation message; default notification emails (semicolon-separated); Google Analytics tracking ID plus cross-domain; "Allow clients to enter rosters for subgroups" = No | captain enters roster and may assign payments | captain enters roster without assigning payments.
- Rules / limits: the full settings list is not published (article body is a pointer only); video supplies the list the article omits: Disallow Partial is on by default and must be off for deposits or payment plans; Online Waiver Fulfilment must be on or the attached document is not required; logo max 790 px wide; CVN advised when Amex / Discover are accepted.
- User story: As an owner, I want house rules for online registration set once, so that staff do not misconfigure individual groups.
- Actors: owner, admin.
- UI generation: both
- Priority: P1
- Evidence: https://support.ezfacility.com/hc/en-us/articles/4415441369883-How-to-Set-Online-Registration-Default-Settings, https://support.ezfacility.com/hc/en-us/articles/31149286284187-How-to-Set-Up-Online-Registration-for-a-Group-in-the-Classic-EZFacility-Experience, https://support.ezfacility.com/hc/en-us/articles/25134483797531-April-24th-2024-Release-Notes, https://support.ezfacility.com/hc/en-us/articles/13526384977307-March-9th-2023-Release-Notes, https://support.ezfacility.com/hc/en-us/articles/14655161654811-April-18th-2023-Release-Notes, https://www.ezfacility.com/blog/updated-subgroup-inheritance-trainer-performance-report-e-mail-procedures-and-more, https://www.youtube.com/watch?v=VuUR1Y9bhjQ (t=10:15), https://www.youtube.com/watch?v=VuUR1Y9bhjQ (t=18:24)

### REG-12 Registrant online checkout for groups
- Sub-features: public registration page per group from link, portal or embed; choose individual / join team / create team; multi-enrolment cart (several subgroups or participants paid together); guest checkout; coupon/discount codes; deposit or full payment; captcha at payment; waiver signing in flow (partner waiver product); confirmation and receipt emails; real-time availability; analytics cross-domain tracking (2021-11-29); video flow: registrant picks New Team / Individual / With a Team, a captain names the team then enters own details; free-text notes / comments; "Remember my information" checkbox; registration agreement step appears only when a document is attached; accepting it sets the waiver flag on the client profile; also used to collect waivers and create client profiles for a team renting space.
- Settings / options: driven by REG-10/REG-11; coupon codes with validity windows (2016); personal fields shown / required come from Administration > Client Settings > Contact Preferences (online-registration column, including custom fields such as team name).
- Rules / limits: multi-subgroup cart fixed 2023-07-03; captcha fix 2023-08-02; UK portal payment fix 2024-03-27; step-by-step registrant flow for groups is not documented in help bodies; only one document can attach to a group's online registration (no sport-specific waiver per group); field configuration is account-wide, never per group or subgroup; first and last name are locked, email and date of birth are locked as required; registrant comments go into the staff confirmation email and the client profile comments tagged with the group name; a presenter says the plain public link registers one individual at a time and points to the client portal for related people (uncertain, see unknowns); marketing webinar claims a shared link lands in the cart with the item already added.
- User story: As a parent, I want to register two children into different sessions and pay once, so that sign-up takes minutes.
- Actors: client, parent/guardian, team captain, guest.
- UI generation: both
- Priority: P0
- Evidence: https://support.ezfacility.com/hc/en-us/articles/17323515477659-How-to-Allow-Clients-to-Register-for-a-Group-Online, https://support.ezfacility.com/hc/en-us/articles/16846068050715-July-3rd-2023-Release-Notes, https://support.ezfacility.com/hc/en-us/articles/17574439837467-August-2nd-2023-Release-Notes, https://support.ezfacility.com/hc/en-us/articles/24225032928027-March-27th-2024-Release-Notes, https://support.ezfacility.com/hc/en-us/articles/36516560976539-April-9th-2025-Release-Notes, https://www.ezfacility.com/features/member-engagement, https://www.ezfacility.com/blog/ez-features-fixes-check-out-whats-new, https://www.ezfacility.com/blog/the-benefits-of-gym-management-software, https://www.ezfacility.com/blog/software-release-vaccine-passport, https://www.youtube.com/watch?v=VuUR1Y9bhjQ (t=31:44), https://www.youtube.com/watch?v=VuUR1Y9bhjQ (t=22:28), https://www.youtube.com/watch?v=j4Rn9joKKpQ (t=31:41), https://www.youtube.com/watch?v=okhjK-XBid4 (t=30:45), https://www.youtube.com/watch?v=DpQMHuC98yo (t=44:03), https://www.youtube.com/watch?v=KAN6h9vPUiM (t=48:24)

### REG-13 Group tools: copy, export, generate
- Sub-features: copy a group, export groups, bulk-generate groups from a global tools menu (New UI); video: "Copy Group" from the dropdown arrow on the group page (subgroups copied from the subgroup page); parent-group "Generate Report" (each team's members with amount paid and balance, sortable, column filters, export, print); "Generate score sheet" (PDF of the selected teams' players, plus player stats when tracked); copy-then-publish is the vendor's way to repeat a league each season.
- Settings / options: not documented in help; video shows the copy dialog: new name, "copy group members" checkbox, "copy subgroup members" checkbox; report default sort = last name.
- Rules / limits: blog mention only; what is copied (fees, subgroups, registration settings) is unknown; leave both member checkboxes unticked or every member lands in the copy; score sheet needs at least two teams selected; a league schedule is never copied, each season needs a fresh wizard run.
- User story: As an admin, I want next season's groups cloned from this season's, so that setup is not repeated.
- Actors: admin.
- UI generation: New
- Priority: P1
- Evidence: https://www.ezfacility.com/blog/software-release-groups-new-ui, https://www.ezfacility.com/blog/product-update-get-ready-for-an-awesome-new-ui-experience, https://www.youtube.com/watch?v=VuUR1Y9bhjQ (t=46:04), https://www.youtube.com/watch?v=TWNQ4cTiEFs (t=43:16), https://www.youtube.com/watch?v=j4Rn9joKKpQ (t=13:18), https://www.youtube.com/watch?v=okhjK-XBid4 (t=51:06)

### REG-14 Publish a group as a league or tournament
- Sub-features: push a parent group (button) or a subgroup (tab) into the league system; after publishing: public preview link and admin-edit deep link (SSO); registration link auto-filled from the group's online registration; rosters, schedules and standings then live on the league side; New UI: push further subgroups (and optionally their players) into an already published league via "publish these subgroups to EZLeagues as teams"; remove a team, or the whole league, published by mistake from the group page.
- Settings / options: Type = League Round Robin | Tournament Single Elimination | Tournament Double Elimination | Tournament Round Robin | PoolPlay | Three Games Guaranteed; Name (from group title); Age Group; Division; Season Starts; Season Ends; Sport; Team Fee; Player Fee; Fee Comments; More info; Registration Link; Minutes per Game; Maximum Defaults; Maximum Forfeits; Minimum Sportsmanship; two switches closing the publish form: "publish all subgroups as teams", "publish all members as players".
- Rules / limits: league vs tournament family is immutable after publish; Three Games Guaranteed needs exactly 8 teams; fees are display-only text on the public site; pickup games cannot be published this way; teams that register after publishing do not sync on their own (staff push them, and an existing schedule is not updated); players must be published for player stats and email alerts (LGE-30); before the New UI adding teams meant deleting and republishing; vendor advice: clear the Registration Link and publish only once all teams have joined; the type chosen at publish decides which scheduler runs; "Minutes per Game" should include turnaround time.
- User story: As an admin, I want the registration container to become the league with its teams, so that I do not maintain two rosters.
- Actors: admin.
- UI generation: both (documented on Classic "4.0"; tab also present in New UI per blog)
- Priority: P1
- Evidence: https://support.ezfacility.com/hc/en-us/articles/4405044226587-How-to-Publish-a-Group-to-EZLeagues-from-EZFacility, https://www.ezfacility.com/blog/software-release-groups-new-ui, https://support.ezfacility.com/hc/en-us/articles/10414682862235-How-to-Create-a-Tournament-in-EZLeagues, https://www.youtube.com/watch?v=j4Rn9joKKpQ (t=10:14), https://www.youtube.com/watch?v=bHzYz6ZzMSE (t=07:11), https://www.youtube.com/watch?v=bHzYz6ZzMSE (t=06:10), https://www.youtube.com/watch?v=okhjK-XBid4 (t=49:04)

### REG-15 Event form builder: create, copy, publish, list
- Sub-features: main menu with published-forms list, create-form tab, email broadcasts and upload tools; build from an event-type template (templates may carry dependent questions); copy an existing form; publish; admin-mode preview as a registrant; copy public link; per-form menu; per-form Edit Form tool with six editable areas: Overall Form Settings, Questions and Answers (REG-16), Information Topics (REG-18), Confirmation Messages (inferred: editable text shown to a registrant after registering; contents not documented), Form Header Graphic and Form Colors/Visual Settings (REG-19).
- Settings / options: Form ID (auto); Form Name; Event Name; Date/Location; Form Start Date / End Date (event dates, not the registration window); list filter Open | Closed | All; sort by Start Date | Form ID | Form Name; columns incl. Registrations count.
- Rules / limits: single-day event uses identical start and end; copy is meant for same-format repeats; header image and colours editable only after publish.
- User story: As an event organiser, I want a registration form up from a template in minutes, so that I can post a link for a race or camp.
- Actors: owner, admin.
- UI generation: New (separate form product)
- Priority: P1
- Evidence: https://support.ezfacility.com/hc/en-us/articles/4505581324827-Accessing-the-Main-Menu-in-EZSignUp, https://support.ezfacility.com/hc/en-us/articles/4414746736155-How-to-Create-New-Form-1st-Time-Set-Up-Event, https://support.ezfacility.com/hc/en-us/articles/4414758416539-How-to-COPY-an-Existing-Form, https://support.ezfacility.com/hc/en-us/articles/4414739101339-Form-Menu-Features-Overview, https://www.ezfacility.com/press-news/press-releases/sun-sets-on-123signup-while-ezsignup-emerges

### REG-16 Form question types and attributes
- Sub-features: add / edit / place questions; types: Text Box, Drop Down List, Radio Button List, Checkbox, Purchase Amount (registrant-entered money amount (inferred: donations)), Purchase Quantity (quantity x unit price); priced answer choices; conditional (dependent) questions and answers from templates; answer visibility by audience.
- Settings / options: common: Question Text; Status Shown | Hidden; Mandatory | Optional; Hint Text; Help Text; Expiration Date; position. Text Box: Maximum Answer Length; Default Answer. Multiple choice: answer text; per-answer price; visibility = All Registrants (other audiences only with the membership module). Checkbox: default Checked | Unchecked; price when checked; answers fixed to No/Yes. Purchase Quantity: unit price.
- Rules / limits: deleting a question or answer choice after registrations exist destroys the captured data; deleting a question another depends on breaks the dependency; expiry removes the item before the form closes; an opt-out (default-checked) box only works if Optional.
- User story: As an organiser, I want priced options (shirt, donation, add-ons) and custom questions on the form, so that one checkout captures everything.
- Actors: owner, admin.
- UI generation: New
- Priority: P1
- Evidence: https://support.ezfacility.com/hc/en-us/articles/4414758652699-How-to-Add-Edit-Text-Box-Questions, https://support.ezfacility.com/hc/en-us/articles/4414758842523-How-to-Add-Edit-Multiple-Choice-Questions, https://support.ezfacility.com/hc/en-us/articles/4414774769947-How-to-Add-Edit-Checkbox-Questions, https://support.ezfacility.com/hc/en-us/articles/4414759250843-How-to-Enter-Amount-Questions, https://support.ezfacility.com/hc/en-us/articles/4414775164187-How-to-Enter-Quantity-Questions, https://support.ezfacility.com/hc/en-us/articles/4414746736155-How-to-Create-New-Form-1st-Time-Set-Up-Event

### REG-17 Inventory caps on form options
- Sub-features: cap the number of selections of an answer choice (multiple choice), of a checkbox "Yes", or the total quantity of a Purchase Quantity question; optional public remaining-count; sold-out messaging.
- Settings / options: Inventory status Enabled | disabled; limit count; sold-out memo text (checkbox and quantity types; fixed system text for multiple choice); "Display Inventory Counts publicly".
- Rules / limits: sold-out multiple-choice option disappears with a generic notice; sold-out checkbox/quantity input is disabled and shows the custom memo.
- User story: As an organiser, I want only 50 VIP slots sellable, so that I never oversell limited items.
- Actors: owner, admin; registrants.
- UI generation: New
- Priority: P1
- Evidence: https://support.ezfacility.com/hc/en-us/articles/4414758916251-How-to-Add-Inventory-Control-Multiple-Choice-Questions, https://support.ezfacility.com/hc/en-us/articles/4414759402907-How-to-Add-Inventory-Control-Enter-Quantity-Questions, https://support.ezfacility.com/hc/en-us/articles/4414782274587-How-to-Add-Inventory-Control-Checkbox-Questions

### REG-18 Form information topics
- Sub-features: static headed text blocks placed anywhere on the form.
- Settings / options: Information Topic Title; Body; position.
- Rules / limits: body formatting requires raw HTML.
- User story: As an organiser, I want explanatory sections between questions, so that registrants understand what they are buying.
- Actors: owner, admin.
- UI generation: New
- Priority: P1
- Evidence: https://support.ezfacility.com/hc/en-us/articles/4414782749467-How-to-Add-Edit-Information-Topics

### REG-19 Form branding (header image, colours, width, font)
- Sub-features: header/logo image upload; colour, font and table-width settings.
- Settings / options: Header Image; Form Table Width (px); colours; font.
- Rules / limits: header suggested max 300 px high and 700-900 px wide; header width must not exceed table width; only editable after publish.
- User story: As an organiser, I want the form to carry my event branding, so that it looks like part of my site.
- Actors: owner, admin.
- UI generation: New
- Priority: P1
- Evidence: https://support.ezfacility.com/hc/en-us/articles/4414782814363-How-to-add-edit-a-Form-Header-Graphic, https://support.ezfacility.com/hc/en-us/articles/4414782863003-How-to-edit-customize-Form-Colors-Visual-Settings

### REG-20 Form open / close and auto-close
- Sub-features: manual open and close; scheduled auto-close.
- Settings / options: status Open | Closed; Auto-Close date and time.
- Rules / limits: independent of the event start/end dates.
- User story: As an organiser, I want registration to shut automatically at the deadline, so that late sign-ups cannot slip in.
- Actors: owner, admin.
- UI generation: New
- Priority: P1
- Evidence: https://support.ezfacility.com/hc/en-us/articles/4414739101339-Form-Menu-Features-Overview

### REG-21 Registration lookup, edit and export
- Sub-features: find a registration by name, email or confirmation number; edit it and its status; standard full export; custom export (choose columns and filters); generate-then-download files with an archive of past files; turn an exported file into a searchable public web page; upload tools for images/files.
- Settings / options: export mode Download All | custom; file archive.
- Rules / limits: none stated on retention.
- User story: As an organiser, I want to pull a filtered participant list and publish a searchable entrant list, so that check-in and results are easy.
- Actors: owner, admin.
- UI generation: New
- Priority: P1
- Evidence: https://support.ezfacility.com/hc/en-us/articles/4414739101339-Form-Menu-Features-Overview, https://support.ezfacility.com/hc/en-us/articles/4505581324827-Accessing-the-Main-Menu-in-EZSignUp

### REG-22 Form summaries (registrant, revenue, demographic, answers)
- Sub-features: Registrant Summary (alphabetical, opens full confirmation, editable); Revenue Summary (Excel export); Demographic Summary (age, gender, weekday, date, state, city, country); Question Answer Summary (count per answer choice).
- Settings / options: none.
- Rules / limits: registrant summary can lag about 5 minutes (cached); revenue summary excludes refunds; demographics limited to what the form asks.
- User story: As an organiser, I want live counts of sizes and options sold, so that I can place supplier orders.
- Actors: owner, admin.
- UI generation: New
- Priority: P1
- Evidence: https://support.ezfacility.com/hc/en-us/articles/4414739101339-Form-Menu-Features-Overview

### REG-23 Event-form registrant flow
- Sub-features: open form link; sign in with client-portal credentials or create an account with email verification and bot check; complete contact profile; register self or another person; answer questions; review with clear-all and add-another-registrant loop; pay; on-screen and emailed receipt; invoice on the client's billing record; registration listed on a dedicated tab of the client profile.
- Settings / options: account fields first name, last name, email, unique username, password; registrant selector (self | other).
- Rules / limits: zero-priced registration creates no invoice; the account must be email-verified before first login; card-swipe option removed from this flow (2023-04-18).
- User story: As a parent, I want to register several family members through one account and get a receipt, so that I have proof and one payment.
- Actors: client, parent/guardian; admin.
- UI generation: New
- Priority: P1
- Evidence: https://support.ezfacility.com/hc/en-us/articles/4505589011227-Registering-for-an-Event-in-EZSignUp, https://support.ezfacility.com/hc/en-us/articles/14655161654811-April-18th-2023-Release-Notes

### REG-24 Form wait list and promo codes
- Sub-features: per-form wait list and coupon/promo codes under a "More Tools" entry.
- Settings / options: not documented.
- Rules / limits: named only.
- User story: As an organiser, I want early-bird codes and a wait list when the event fills, so that I maximise attendance.
- Actors: owner, admin.
- UI generation: New
- Priority: P1
- Evidence: https://support.ezfacility.com/hc/en-us/articles/4505581324827-Accessing-the-Main-Menu-in-EZSignUp

### REG-25 Legacy event-registration product (123SignUp)
- Sub-features: predecessor event/association registration software replaced by the form builder above.
- Settings / options: n/a.
- Rules / limits: wind-down from late 2021; discontinuation announced 2022-10-13.
- User story: As a legacy customer, I want my event forms on the successor product, so that I keep registering attendees.
- Actors: owner.
- UI generation: Classic
- Priority: P2
- Evidence: https://www.ezfacility.com/press-news/press-releases/sun-sets-on-123signup-while-ezsignup-emerges

### REG-26 Captain roster entry and team-fee split
- Sub-features: after a new-team registration the captain / coach receives an emailed link to enter the roster; each added player is created as a client and emailed; the captain may assign shares of the team fee to players, who then pay their own share online; staff can resend the roster link; captain flagged with a star in the team list; per-player waiver status visible.
- Settings / options: "Allow clients to enter rosters for subgroups" = No (staff build teams) | captain enters roster and may assign payments | captain enters roster but cannot assign payments (account default, REG-11); roster row fields: first name, last name, home phone, date of birth, email.
- Rules / limits: any unassigned balance stays on the captain; demo example: a $3,600 team fee split into $360 per player; how each player receives a payment link is not shown; one webinar's captions name this "Leader's roster" (uncertain).
- User story: As a team captain, I want to enter my roster and split the team fee among players, so that nobody has to chase me for money.
- Actors: captain / coach, players, admin.
- UI generation: both (demonstrated in the New UI)
- Priority: P1
- Evidence: https://www.youtube.com/watch?v=VuUR1Y9bhjQ (t=18:24), https://www.youtube.com/watch?v=VuUR1Y9bhjQ (t=41:36), https://www.youtube.com/watch?v=okhjK-XBid4 (t=34:49), https://www.youtube.com/watch?v=edzJ6kuAvMQ (t=15:25), https://www.youtube.com/watch?v=KYHio6yy5e0 (t=14:00)

Conventions: "Classic"/"New" = the two admin UI generations. "TMS" = their name for the core back-office system. "MM+" = MemberMe+ (shared multi-tenant member app). "Branded App" = per-facility white-label app (MiGym lineage). "(inferred)" marks our inference. Dates are release/publication dates from public sources.

## Staff / Trainers / Time Clock / Payroll

### STF-01 Trainer records as schedulable resources
- Sub-features: create/edit/delete trainer under a location; each trainer gets a calendar column on the schedule; trainer is implicitly a salesperson (no second record); trainer name is the schedule label.
- Settings / options: Trainer Name; location scope (trainers are defined per location under "Location & Trainer Setup" in Classic, "Location Settings > Resources Setup > Trainers tab" in New); row actions edit / save / delete.
- Rules / limits: trainer count appears licence-bound because each consumes a calendar (inferred from the contrast "salespeople have no calendar so unlimited"); a trainer is distinct from a login user (time clock uses User records, pay uses Trainer records; link between the two is not documented).
- User story: As an administrator, I want trainers to exist as bookable calendar resources with pay attributes, so that sessions can be scheduled against them and paid correctly.
- Actors: account administrator.
- UI generation: both (same model; navigation differs).
- Priority: P0
- Evidence: https://support.ezfacility.com/hc/en-us/articles/4403486979739-Adding-or-Editing-a-Trainer-in-EZFacility-Classic, https://support.ezfacility.com/hc/en-us/articles/4402427211163-Adding-or-Editing-a-Trainer, https://support.ezfacility.com/hc/en-us/articles/28333307842971-How-to-Set-Up-Trainer-Commission, https://www.ezfacility.com/features/staff-access-management

### STF-02 Trainer session pay model
- Sub-features: default pay profile per trainer covering session pay, comp sessions, flat-rate activities and sales commission.
- Settings / options: Pay basis = Per Attendee | Per Session. Session Commission (% of the value of the client package used to book). Hourly Session Rate, 45 Min Session Rate, 30 Min Session Rate. Comp Session Rate. Program Instruction rate. Non-Training Time rate. Floor Rate. Sales Comm (% of package value). Flat Comm Rate (per package sold).
- Rules / limits: Per Attendee — duration rates are money per attended client, prorated by class length; Session Commission pays % of consumed package value; Comp Session Rate is flat hourly per complimentary package present in the session. Per Session — duration rates are a flat amount per session prorated by length; Comp rate as above; Session Commission is ignored. Program Instruction, Non-Training Time (sessions with no attendees) and Floor Rate are flat regardless of attendance. A default membership-sale commission cannot be set at this level (must use STF-03 membership rates).
- User story: As an administrator, I want to define how each trainer earns per session and per sale, so that payroll can be computed from completed schedule activity.
- Actors: administrator.
- UI generation: both (New "How to Set Up Trainer Commission" lists the same fields minus Program Instruction/Non-Training/Floor, which the New "Adding or Editing a Trainer" article does list).
- Priority: P0
- Evidence: https://support.ezfacility.com/hc/en-us/articles/4403486979739-Adding-or-Editing-a-Trainer-in-EZFacility-Classic, https://support.ezfacility.com/hc/en-us/articles/4402427211163-Adding-or-Editing-a-Trainer, https://support.ezfacility.com/hc/en-us/articles/28333307842971-How-to-Set-Up-Trainer-Commission, https://www.ezfacility.com/features/staff-access-management, https://www.ezfacility.com/industries/gym-management-software

### STF-03 Service-specific and membership-specific trainer pay rates
- Sub-features: per-Reservation-Type override of pay basis, rates and sales commission ("Package Pay Rates" / "Service Specific"); per-Membership-Type sale commission ("Membership Pay Rates"); add/edit/delete rate rows.
- Settings / options: Reservation Type; pay basis Per Attendee | Per Session; rate; sales comm %; flat comm. Membership Type; Sale Commission %; Flat Comm.; "First Invoice Only" (New commission article labels it "first time contract sold only").
- Rules / limits: unlimited override rows per trainer; multiple membership rates allowed; First Invoice Only pays commission on the first bill only, suppressing commission on auto-renewals and on contracts billed more than once.
- User story: As an administrator, I want different pay for different services and membership types, so that specialised sessions and membership sales are compensated per policy.
- Actors: administrator.
- UI generation: both.
- Priority: P1
- Evidence: https://support.ezfacility.com/hc/en-us/articles/4403486979739-Adding-or-Editing-a-Trainer-in-EZFacility-Classic, https://support.ezfacility.com/hc/en-us/articles/4402427211163-Adding-or-Editing-a-Trainer, https://support.ezfacility.com/hc/en-us/articles/28333307842971-How-to-Set-Up-Trainer-Commission

### STF-04 Trainer bonuses (trained-hour and off-hour)
- Sub-features: threshold bonus on hours trained; time-of-day premium per weekday.
- Settings / options: Trained Hour Bonus — Bonus Name, Min Hours, Bonus amount, "Apply Bonus only to the Extra Hours" checkbox. Off Hour Bonus — for each weekday: Start Time, End Time, Bonus Amount.
- Rules / limits: once Min Hours is reached the bonus applies to all hours unless the extra-hours-only flag is set; evaluation period for the threshold (per report range vs per pay period) is not stated.
- User story: As an administrator, I want volume and unsociable-hour bonuses, so that trainer incentives are calculated automatically.
- Actors: administrator.
- UI generation: both.
- Priority: P1
- Evidence: https://support.ezfacility.com/hc/en-us/articles/4403486979739-Adding-or-Editing-a-Trainer-in-EZFacility-Classic, https://support.ezfacility.com/hc/en-us/articles/4402427211163-Adding-or-Editing-a-Trainer

### STF-05 Salesperson records and sales commission rates
- Sub-features: non-scheduled staff used for "Sold By" attribution on package and membership sales; default rates plus per-Program-Type and per-Membership-Type overrides.
- Settings / options: Full Name; Pkg Comm Rate (%); Pkg Flat Comm; Session Comm Rate (%); Session Flat Comm; Mem Comm Rate (%); Mem Flat Comm; First Invoice Only; Service Specific rows keyed by Program Type ("Program Specific Pay Rates"); Membership Pay Rates rows keyed by Membership Type.
- Rules / limits: salespeople have no calendar, so quantity is unlimited; trainers already act as salespeople; "Sold By" must be captured at sale time for commission to accrue.
- User story: As an administrator, I want to attribute sales to staff and define their commission, so that commission statements can be produced.
- Actors: administrator; front desk (chooses Sold By at sale).
- UI generation: Classic article only; New navigation not documented (assumed equivalent under Resources Setup).
- Priority: P0
- Evidence: https://support.ezfacility.com/hc/en-us/articles/4403486981915-Adding-or-Editing-a-Salesperson-in-EZFacility-Classic, https://support.ezfacility.com/hc/en-us/articles/4403493414683-Salesperson-Commission-Report, https://www.ezfacility.com/features/staff-access-management

### STF-06 Time clock setup (job classifications, hourly rates, IP restriction)
- Sub-features: user account per employee; job classification catalogue; hourly rate per user per classification; network restriction for the time clock.
- Settings / options: User required fields Role, First Name, Last Name, Email, Username, Password. Job Classification (name). Hourly Rate rows (user, classification, rate; multiple per user). IP Address Restriction: current IP pre-filled, "Allow access from any IP Address" checkbox, multiple addresses, remove row.
- Rules / limits: every employee needs their own login; role governs access; a rate must exist for a classification before the employee can clock into it.
- User story: As an administrator, I want to define what jobs staff clock into, at what rate and from which networks, so that timekeeping is accurate and on-premises.
- Actors: administrator.
- UI generation: both (Classic: Administration > User Administration / Time Clock; New: Location Settings > User, Time Clock > Job Classifications / Hourly Rate).
- Priority: P0
- Evidence: https://support.ezfacility.com/hc/en-us/articles/27882337605915-How-to-Setup-the-Employee-Time-Clock, https://support.ezfacility.com/hc/en-us/articles/30051822805659-How-to-Use-the-Employee-Time-Clock-in-EZFacility-Classic, https://support.ezfacility.com/hc/en-us/articles/14655161654811-April-18th-2023-Release-Notes, https://www.ezfacility.com/features/staff-access-management

### STF-07 Employee clock in / clock out
- Sub-features: dedicated time clock screen; re-authentication with own credentials; choose job classification; clock in; same path to clock out.
- Settings / options: classification picker shows only classifications for which the user has a rate (single one when only one rate exists).
- Rules / limits: staff-level users cannot edit their own entries; a defect fix (2023-04-18) confirms a user must only reach their own clock.
- User story: As an hourly employee, I want to clock in and out against the job I am doing, so that I am paid for the right hours at the right rate.
- Actors: staff, trainers, front desk.
- UI generation: both.
- Priority: P0
- Evidence: https://support.ezfacility.com/hc/en-us/articles/27882374264603-How-to-Use-the-Employee-Time-Clock-as-Staff, https://support.ezfacility.com/hc/en-us/articles/30051822805659-How-to-Use-the-Employee-Time-Clock-in-EZFacility-Classic, https://support.ezfacility.com/hc/en-us/articles/14655161654811-April-18th-2023-Release-Notes, https://www.ezfacility.com/features/staff-access-management

### STF-08 Manager time-entry management and time clock reporting
- Sub-features: search staff; view, add, edit, delete entries; time clock report by date range, staff and job type; multi-format export.
- Settings / options: report filters date range / staff / job classification; export formats (not enumerated).
- Rules / limits: requires a manager-level permission; audit of edits is not described; a 2024-01-31 fix restored entry editing.
- User story: As a manager, I want to correct missed punches and report hours, so that payroll is right.
- Actors: manager, owner.
- UI generation: both.
- Priority: P0
- Evidence: https://support.ezfacility.com/hc/en-us/articles/4406988987803-How-to-Use-the-Employee-Time-Clock-as-a-Manager, https://support.ezfacility.com/hc/en-us/articles/30051822805659-How-to-Use-the-Employee-Time-Clock-in-EZFacility-Classic, https://support.ezfacility.com/hc/en-us/articles/22529640450203-January-31-2024-Release-Notes, https://www.ezfacility.com/features/staff-access-management

### STF-09 Trainer Payroll/Commission report
- Sub-features: per-trainer earnings for a date range from completed sessions and attributed sales.
- Settings / options: trainer selector; Start/End Date; session detail organisation (a "by client" grouping only applies to per-attendee trainers); additional income amount (manual add-on); "Calculate commission from" = Invoiced amount | Paid amount; export.
- Rules / limits: only completed sessions count; rates read from the trainer record at run time (no evidence of rate history/effective dating); special reservation types on a trainer calendar appear here; trainers running it see only their own data (fix 2024-01-17). Video (webinar Q&A): the product does not disburse pay; it only reports amounts, and staff are paid outside it.
- User story: As a payroll administrator, I want a per-trainer pay statement, so that I can pay session fees and commissions.
- Actors: owner, payroll admin, trainer (own data).
- UI generation: both (New UI generation fixed 2023-09-27).
- Priority: P0
- Evidence: https://support.ezfacility.com/hc/en-us/articles/4403486264219-Trainer-Payroll-Commission-Report, https://support.ezfacility.com/hc/en-us/articles/19132331777307-September-27th-2023-Release-Notes, https://support.ezfacility.com/hc/en-us/articles/22122496577179-January-17th-2024-Release-Notes, https://www.ezfacility.com/blog/best-sports-facility-management-software, https://www.youtube.com/watch?v=KAN6h9vPUiM (t=44:17)

### STF-10 Salesperson Commission report
- Sub-features: commission by salesperson across packages, memberships and session completions.
- Settings / options: Salesperson (single or all); Start/End Date; "Calculate Commission from" (invoiced vs paid; applies to package/membership only); "Filter Results by" (applies to package/membership only; option values not listed); export.
- Rules / limits: session-completion commission is always based on billed package value and is included by session date regardless of package dates; depends on Sold By being set.
- User story: As an owner, I want commission totals per salesperson, so that I can pay sales incentives.
- Actors: owner, payroll admin.
- UI generation: both (all-salespeople run fixed 2023-09-13).
- Priority: P0
- Evidence: https://support.ezfacility.com/hc/en-us/articles/4403493414683-Salesperson-Commission-Report, https://support.ezfacility.com/hc/en-us/articles/18741009680795-September-13th-2023-Release-Notes

### STF-11 Trainer Performance report and trainer-scoped report access
- Sub-features: Trainer Performance report (sort by date or Reservation Type, Package Type column); trainers limited to their own rows in Trainer Performance, Trainer Schedule, Session Notes and Trainer Payroll/Commission reports.
- Settings / options: sort key date | reservation type.
- Rules / limits: row-level scoping by the trainer linked to the logged-in user (link mechanism undocumented).
- User story: As a trainer, I want to see my own performance and pay without seeing colleagues', so that earnings are transparent but private.
- Actors: trainer, manager.
- UI generation: both.
- Priority: P1
- Evidence: https://www.ezfacility.com/blog/updated-subgroup-inheritance-trainer-performance-report-e-mail-procedures-and-more, https://support.ezfacility.com/hc/en-us/articles/19132331777307-September-27th-2023-Release-Notes, https://support.ezfacility.com/hc/en-us/articles/22122496577179-January-17th-2024-Release-Notes, https://www.ezfacility.com/features/staff-access-management

### STF-12 Trainer booking alerts and reminders
- Sub-features: automatic email (and text) to a trainer when a client books or cancels; trainer copy of session reminders.
- Settings / options: user-level flag "Attendance Status Changes" in User Administration opts a trainer into booking notifications; trainer reminders toggle on the Email Alerts page.
- Rules / limits: notification is sent on self-service bookings; text channel depends on the SMS add-on (inferred).
- User story: As a trainer, I want to be told when my sessions change, so that I do not miss clients.
- Actors: trainer, administrator.
- UI generation: both.
- Priority: P1
- Evidence: https://support.ezfacility.com/hc/en-us/articles/4404305577755-How-to-Set-Up-Self-Service-Preferences-in-EZFacility-Classic, https://support.ezfacility.com/hc/en-us/articles/18308941711899-How-to-Enable-Disable-Email-Notifications, https://www.ezfacility.com/blog/the-top-5-advantages-of-gun-range-management-software, https://www.ezfacility.com/self-service-portal

### STF-13 Staff schedule sync to personal calendars
- Sub-features: push a staff member's schedule to Google Calendar or Outlook.
- Settings / options: none documented.
- Rules / limits: direction (one-way vs two-way) and mechanism (ICS feed vs OAuth) unknown.
- User story: As a trainer, I want my sessions in my own calendar, so that I see work and personal commitments together.
- Actors: staff.
- UI generation: n-a (marketing claim).
- Priority: P1
- Evidence: https://www.ezfacility.com/features/staff-access-management

### STF-14 Coaching/athlete performance partner integration (CoachMePlus)
- Sub-features: partner listing only. Video (partner webinars, c. 2020): every client record is mirrored automatically into a partner account with basic contact data (phone, contacts, email), so clients are maintained once in the core system; a client who is no longer an active profile/member is set inactive on the partner side; the partner tool then supplies an exercise library (about 1,000-1,200 exercises, roughly a third with video), reusable circuits and dated programs assignable to one client or a group and adjustable per client, one-way alerts with read tracking plus two-way staff-client messaging, per-client dashboards/testing/notes/files, and a client workout-logging app with health-platform sync.
- Settings / options: none documented. Video: nothing to configure on the core side; partner 'Activate' package is priced by trainer count with unlimited clients (about $80/month for 5 trainers, tiers at 10/15/20, custom above 20, no activation fee); 30-day trial via a referral landing page; onboarding quoted at 1-2 days.
- Rules / limits: no integration detail public. Video: sync appears one-way (core to partner); the partner tool takes no payments and sells nothing (products, sessions, packages stay in the core system).
- User story: As a performance coach, I want athlete goals tracked in a specialist tool linked to client records, so that training is measurable.
- Actors: coach.
- UI generation: n-a.
- Priority: v2-adapter
- Evidence: https://www.ezfacility.com/partners, https://www.youtube.com/watch?v=NTXRhqak3cM (t=02:03, t=08:10, t=20:28), https://www.youtube.com/watch?v=YkHOVxeiuiI (t=20:36, t=23:38, t=27:43)

### STF-15 Shift assignment
- Sub-features: marketing states staff shift assignment is automated; no help-center article describes a shift entity or screen.
- Settings / options: none documented.
- Rules / limits: evidence is a single benefits-page phrase; treat the capability as brief-driven (module 12 "Shifts") rather than parity-driven.
- User story: As a manager, I want to assign staff to shifts, so that the front desk and floor are covered.
- Actors: manager, staff.
- UI generation: n-a.
- Priority: P0
- Evidence: https://www.ezfacility.com/benefits, https://www.ezfacility.com/features/staff-access-management

## Email / SMS / Push Marketing

### MKT-01 Email verification (double opt-in)
- Sub-features: verification email on add/change of an address; staff resend; staff manual verify; client verify button/link; confirmation page; consent proof capture.
- Settings / options: status Pending | Verified; actions "Resend email verification to this address", "Manually verify email address" (+ Confirm); captured opt-in IP and confirmation date.
- Rules / limits: every new address triggers a verification message immediately; an address can be verified once per client; manual verification stores no IP/date and shifts spam liability to the facility; unverified addresses receive neither campaigns nor other email (per the rationale article); repeated failures can lead the vendor to disable the account's email capability.
- User story: As a facility, I want provable consent for each address, so that deliverability and anti-spam compliance are protected.
- Actors: client, front desk, administrator.
- UI generation: both.
- Priority: P0
- Evidence: https://support.ezfacility.com/hc/en-us/articles/4405137478299-Email-Verification-and-Subscriptions-For-Clients, https://support.ezfacility.com/hc/en-us/articles/24856876239771-Email-Verification-and-Subscriptions-For-Clients, https://support.ezfacility.com/hc/en-us/articles/4405144438939-Benefits-of-Email-Verification, https://support.ezfacility.com/hc/en-us/articles/4405137514267-Canada-Anti-Spam-Law

### MKT-02 Communication subscriptions per email address
- Sub-features: three subscription topics per address; client self-management link; staff toggles on the profile; subscription choice step during verification.
- Settings / options: topics Session Reminders (email or text), Credit Card Expiration, Email Campaigns; defaults on = Session Reminders + Credit Card Expiration, Email Campaigns = explicit opt-in; "Manage your subscriptions" link in campaign emails.
- Rules / limits: each address on a client carries its own toggles; staff may change toggles only after verification (New article); staff must not opt a client in without consent; a 2026 title-only article indicates US-only relabelling of Email/SMS subscriptions (body not read).
- User story: As a client, I want to choose which messages I receive, so that I only get what I agreed to.
- Actors: client, staff.
- UI generation: both.
- Priority: P0
- Evidence: https://support.ezfacility.com/hc/en-us/articles/4405137478299-Email-Verification-and-Subscriptions-For-Clients, https://support.ezfacility.com/hc/en-us/articles/24856876239771-Email-Verification-and-Subscriptions-For-Clients, https://support.ezfacility.com/hc/en-us/articles/4405144414875-Managing-Email-Subscriptions-on-a-Client-s-Profile, https://support.ezfacility.com/hc/en-us/articles/25134483797531-April-24th-2024-Release-Notes, https://support.ezfacility.com/hc/en-us/articles/54600257319195-Email-SMS-Subscriptions-Labeling-Update-US-Only-Update (title only, body not read)

### MKT-03 Email campaign wizard (legacy blast)
- Sub-features: five-step wizard: audience category, extra filter, envelope (template, return address, subject), content editor, preview/test/send; rich-text editor with hyperlink dialog and paste-from-Word dialog.
- Settings / options: default audiences All Contacts, All Members, Non-Members, Birthdays this month, Birthdays next month, plus saved Client Categories; "New Filter"; Email Template (default or My Saved Templates); Return Email Address (defaults to the logged-in user's email, per-send editable, permanent change in user admin); Email Subject; "Save as New Template" + Template Name; Send Test (to the return address only); Send Blast. Link dialog: Link URL, Target = new window | same window.
- Rules / limits: blast is immediate and irreversible (no scheduling in this generation); only verified addresses subscribed to Email Campaigns receive it; sender accepts the vendor's blast policy on send; inline image upload in the New-2022 flow required contacting support; opt-out link cannot be removed.
- User story: As a marketer, I want to email a filtered set of clients from in-platform data, so that I can promote without exporting lists.
- Actors: owner, administrator, marketing staff.
- UI generation: both (Classic, and a 2022 New-UI port of the same wizard).
- Priority: P0
- Evidence: https://support.ezfacility.com/hc/en-us/articles/4405137490843-How-to-Send-an-Email-Campaign-in-EZFacility-Classic, https://support.ezfacility.com/hc/en-us/articles/5776809698075-How-to-create-an-Email-Campaign-in-the-New-EZFacility-Experience, https://support.ezfacility.com/hc/en-us/articles/4405137494811-Adding-a-URL-link-to-an-Email-Campaign-in-EZFacility-Classic, https://support.ezfacility.com/hc/en-us/articles/26750732215835-June-19th-2024-Release-Notes, https://www.ezfacility.com/features/member-engagement

### MKT-04 Advanced Email Campaigns (2024 builder)
- Sub-features: drag-and-drop row/column layout editor; basic layouts and own templates; device preview; drafts; save as template; multi-recipient test send; send now or schedule; drafts list with edit; per-user/role permission levels; segmentation filters; marketed AI writing assistant and AI image library; marketed triggered/automated sequences.
- Settings / options: Subject; Sender; client category multi-select with refresh; template source Your Templates | Basic Layouts; preview device computer | tablet | phone; Save Draft; Save as a template (unique name); Send Test To (comma-separated); Schedule = Send Now | Schedule (date, time); campaign states Draft | Scheduled | Sent (inferred); permission levels Publisher (create/edit/view/send), Editor (view/edit), Viewer, None; filters include membership expiration (date fields + contract-type checkboxes), Birth Month, Date of Birth. Video (builder demo): permissions are set per user (shield icon) under Location settings > Users > Email campaign permissions; 'Send from' may be another user's address and defaults to the facility email from location settings; AI image generation from a text prompt; 'Smart Text' rewrites a text block (e.g. more professional or more personal); background colour per row and per column; images auto-resize with manual resize possible; client category is the top-level audience sort, with client tags as a further targeting key.
- Rules / limits: menu hidden without permission; sold as paid add-on "Advanced Email Marketing", bundled in upper plan tiers; marketed as unlimited sends; sending runs on AWS SES with company name as sender display (2024-05). Video: Editor can view and edit an existing draft but cannot create a draft or send, and Viewer is read-only; recipients come only from in-platform contacts (no external list import); switching the advanced builder on switches the legacy campaign tools off for the account (staff can flip between the Classic and New-UI wizards, but not between those and the builder); a 30-day free builder trial is offered on moving to the New UI, during which legacy campaigns are unavailable.
- User story: As a marketer, I want designed, scheduled, segmented campaigns with analytics, so that communication looks professional and is measurable.
- Actors: staff with Publisher/Editor permission.
- UI generation: New.
- Priority: P1
- Evidence: https://support.ezfacility.com/hc/en-us/articles/27808005266843-Create-a-New-Email-Campaign-2024, https://support.ezfacility.com/hc/en-us/articles/27808007575195-How-to-Edit-an-Email-Campaign-Draft-2024, https://support.ezfacility.com/hc/en-us/articles/27808006885275-Change-Permissions-for-Email-Campaigns-2024, https://support.ezfacility.com/hc/en-us/articles/36516560976539-April-9th-2025-Release-Notes, https://support.ezfacility.com/hc/en-us/articles/25551222201627-May-8th-2024-Release-Notes, https://support.ezfacility.com/hc/en-us/articles/25985296561179-May-23rd-2024-Release-Note, https://www.ezfacility.com/blog/unlimited-email-ezfacility-benefits, https://www.ezfacility.com/plans-pricing/pricing-results, https://www.youtube.com/watch?v=bxCUg7Y5PsI (t=02:09, t=04:13, t=07:15), https://www.youtube.com/watch?v=TWNQ4cTiEFs (t=20:34, t=25:44), https://www.youtube.com/watch?v=3FOVNMAz2cE (t=23:33)

### MKT-05 Email template library
- Sub-features: create template; edit existing (saved as a new copy); preset vs own templates; templates reusable in campaigns, direct emails and group emails.
- Settings / options: Select Action = create new | edit existing; Template Category; Type; Template; Template Name; Email Subject; Message; buttons Save / Save as New; "My Saved Templates" vs preset templates.
- Rules / limits: editing never overwrites (always "Save as New"); legacy EZSignUp broadcasts cannot use templates; marketing cites 500+ stock templates. Video: templates saved in Classic appear in the New-UI wizard but never in the advanced builder, which uses separate tooling; users rebuild them there (no migration path stated).
- User story: As a marketer, I want reusable templates, so that recurring messages are consistent and quick.
- Actors: administrator, marketing staff.
- UI generation: Classic (New equivalent lives inside MKT-04 as "Your Templates").
- Priority: P0
- Evidence: https://support.ezfacility.com/hc/en-us/articles/4405137498395-Using-the-Email-Template-Library-in-EZFacility-Classic, https://support.ezfacility.com/hc/en-us/articles/4405137490843-How-to-Send-an-Email-Campaign-in-EZFacility-Classic, https://support.ezfacility.com/hc/en-us/articles/27808005266843-Create-a-New-Email-Campaign-2024, https://www.ezfacility.com/press-news/blog/fitness-newsletter, https://www.youtube.com/watch?v=TWNQ4cTiEFs (t=21:34), https://www.youtube.com/watch?v=bxCUg7Y5PsI (t=06:14)

### MKT-06 Email image library
- Sub-features: upload, list, delete images for use in email bodies.
- Settings / options: Caption; Photo (file).
- Rules / limits: size/format limits not stated; a 2023-08-31 fix covered broken template images in profile emails.
- User story: As a marketer, I want hosted images, so that emails render pictures reliably.
- Actors: administrator, marketing staff.
- UI generation: Classic (New builder has its own asset handling, including a marketed AI image library).
- Priority: P1
- Evidence: https://support.ezfacility.com/hc/en-us/articles/4405144429595-Managing-the-Email-Image-Library-in-EZFacility-Classic, https://support.ezfacility.com/hc/en-us/articles/18408526583067-August-31st-2023-Release-Notes, https://www.ezfacility.com/blog/unlimited-email-ezfacility-benefits

### MKT-07 Campaign history and analytics
- Sub-features: history list; per-campaign detail; per-recipient search (proof of sending); sent list with "More Info" analytics; CSV export; column filters.
- Settings / options: summary counters clients attempted, duplicates, invalid emails, blacklisted emails, sent emails; per-recipient statuses Delivered, Open, Click, Bounce, Dropped; export CSV. Video (2024 Sent view): per-campaign breakdown blacklisted, bounced, clicked, delivered, duplicates, opened, invalid, spam, unsubscribed; a Scheduled tab lists future sends, still editable before they go.
- Rules / limits: message body is not retained in the legacy history; Delivered means accepted by the receiving server; Bounce = refused by receiving server; Dropped = suppressed on the sending side; analytics columns of the 2024 Sent view are not enumerated; marketing claims real-time open/click analytics.
- User story: As a marketer, I want delivery and engagement results, so that I can prove sends and improve content.
- Actors: administrator, marketing staff.
- UI generation: both (2022 history page; 2024 Sent view).
- Priority: P0
- Evidence: https://support.ezfacility.com/hc/en-us/articles/5777441102235-How-to-view-your-Campaign-History-in-the-New-EZFacility-Experience, https://support.ezfacility.com/hc/en-us/articles/27808030170267-Sent-Email-Campaign-2024, https://www.ezfacility.com/blog/unlimited-email-ezfacility-benefits, https://www.youtube.com/watch?v=bxCUg7Y5PsI (t=10:22)

### MKT-08 Failed-email suppression list
- Sub-features: automatic suppression of hard bounces; list with reason and last failure; correct the address in place; unblock; unified spam-complaint + bounce handling.
- Settings / options: columns Email, Reason (detail pop-up), Last Fail Date; actions edit address, Unblock; suppression reason bounce | spam (2024-05-23).
- Rules / limits: a re-failing address is re-added; chronic invalid addresses are eventually purged; high failure volume risks account-level email shutdown. Video (2024 builder demo): an address can be unblocked only once; if it bounces again the block is permanent.
- User story: As an administrator, I want bad addresses quarantined and fixable, so that sender reputation is preserved.
- Actors: administrator.
- UI generation: Classic article; behaviour applies platform-wide.
- Priority: P0
- Evidence: https://support.ezfacility.com/hc/en-us/articles/4405137505179-Manage-Failed-Email-in-in-EZFacility-Classic, https://support.ezfacility.com/hc/en-us/articles/25985296561179-May-23rd-2024-Release-Note, https://support.ezfacility.com/hc/en-us/articles/4405137514267-Canada-Anti-Spam-Law, https://www.youtube.com/watch?v=bxCUg7Y5PsI (t=13:27)

### MKT-09 Anti-spam compliance guardrails
- Sub-features: non-removable unsubscribe link in every campaign; verification request on every address; client audit view of all emails sent; consent-type concepts (express vs implied).
- Settings / options: none configurable (guardrails are enforced); consent windows referenced: implied consent 24 months after purchase/contract, 6 months after inquiry (Canadian law).
- Rules / limits: opt-out cannot be disabled by the facility (since 2014).
- User story: As a facility, I want the platform to enforce anti-spam law mechanics, so that I am not exposed to penalties.
- Actors: administrator, client.
- UI generation: both.
- Priority: P0
- Evidence: https://support.ezfacility.com/hc/en-us/articles/4405137514267-Canada-Anti-Spam-Law, https://support.ezfacility.com/hc/en-us/articles/4405144438939-Benefits-of-Email-Verification, https://www.ezfacility.com/blog/updated-subgroup-inheritance-trainer-performance-report-e-mail-procedures-and-more

### MKT-10 Direct email to one client from the profile
- Sub-features: compose a one-off email logged against the client; pick sender user; reuse saved subjects and templates.
- Settings / options: Classic form fields Type, Contact, Due On, Subject (list with "other" and "Save Subject To Template"), Email Template (My Saved Templates | Preset), Assigned To (sender), body, Send Email. New: action menu > Send Email, sending user, subject (new or existing), template or free text.
- Rules / limits: client must have an email on file; New UI additionally requires the email-campaign permission; Classic form is task-shaped (Type/Due On), implying a shared communication/task log (inferred).
- User story: As front-desk staff, I want to email a client from their record, so that the message is quick and traceable.
- Actors: staff.
- UI generation: both.
- Priority: P0
- Evidence: https://support.ezfacility.com/hc/en-us/articles/33119920006427-How-to-direct-email-a-client-through-their-profile-in-EZFacility-Classic, https://support.ezfacility.com/hc/en-us/articles/33122944575899-How-to-direct-email-a-client-through-their-profile, https://support.ezfacility.com/hc/en-us/articles/22122496577179-January-17th-2024-Release-Notes

### MKT-11 Email groups, subgroups, registrants and session attendees
- Sub-features: email one group, several selected groups, a subgroup, or a single registrant; opens the campaign composer pre-addressed; email attendees of a session.
- Settings / options: per-row envelope action; multi-select + "Email Selected Groups"; My Saved Templates available in the composer.
- Rules / limits: recipients include registrants of the group and all its subgroups; action hidden when no registrant has an email; cross-location group/session emailing fixed 2024-04-10.
- User story: As a program coordinator, I want to message everyone in a program at once, so that schedule changes reach participants.
- Actors: administrator, front desk, coach.
- UI generation: both.
- Priority: P1
- Evidence: https://support.ezfacility.com/hc/en-us/articles/4404931886235-How-to-Send-an-Email-Campaign-to-Groups, https://support.ezfacility.com/hc/en-us/articles/4404931926939-How-to-Email-Group-Subgroup-Registrants, https://support.ezfacility.com/hc/en-us/articles/4415441383707-How-to-Send-an-Email-Campaign-to-Groups, https://support.ezfacility.com/hc/en-us/articles/24695840840603-April-10th-2024-Release-Notes

### MKT-12 Broadcast email to registration-form registrants (EZSignUp)
- Sub-features: select one or more forms; compose From/Subject/Body; preview; submit to queue.
- Settings / options: Form multi-select; From email; Subject; Body.
- Rules / limits: no open/click/bounce tracking; no templates; queued delivery can lag by hours (time-critical links should go out a day early).
- User story: As an event organiser, I want to message everyone who filled in a form, so that I can send logistics.
- Actors: owner, administrator.
- UI generation: New (EZSignUp sub-product).
- Priority: P1
- Evidence: https://support.ezfacility.com/hc/en-us/articles/5777638736027-How-To-Send-email-broadcasts-message-to-FORM-registrants

### MKT-13 Session/appointment reminders
- Sub-features: automated reminders to clients before a session, by email or text; trainer/staff copies; governed by the client's Session Reminders subscription.
- Settings / options: Session Reminder — one or two reminders before a session (offsets configurable; exact units not stated); trainer reminders on/off; channel email | text.
- Rules / limits: maximum two reminders per session; text channel requires SMS capability; reminders honour subscription toggles (MKT-02). Video (2020 Q&A): the reminder email carries no link to the session or to its video.
- User story: As a client, I want a reminder before my session, so that I do not no-show.
- Actors: client, trainer, administrator.
- UI generation: both (configured under Client Settings > Email Alerts in New).
- Priority: P0
- Evidence: https://support.ezfacility.com/hc/en-us/articles/18308941711899-How-to-Enable-Disable-Email-Notifications, https://www.ezfacility.com/self-service-portal, https://support.ezfacility.com/hc/en-us/articles/4405137478299-Email-Verification-and-Subscriptions-For-Clients, https://www.youtube.com/watch?v=IM8m1sUsMdw (t=29:44)

### MKT-14 Operational notification routing (staff-facing alerts)
- Sub-features: location alert mailbox for card-decline notices; staff alerts on client self-service actions; daily management summary; online-registration notices (account default + per group); credit-card expiry notices to clients.
- Settings / options: Alert Email (per location); Self-Service "Enable Email Alerts" + selectable client action types + Additional Emails (multiple recipients); Management Email Reminder (previous-day activity summary) recipients; "Send notification of all online registrations to the following emails"; per-group notification address on the group's Online Registration tab; per-reservation-type "Instant Email Alerts". Video (March 2016 release walkthrough): 'Instant alerts' cover reservation bookings, package sales and memberships sold online, emailed to the listed addresses.
- Rules / limits: management summary recipients must be user accounts; action-type list not enumerated.
- User story: As a manager, I want operational events routed to the right inbox, so that declines, bookings and registrations are acted on.
- Actors: owner, administrator.
- UI generation: both.
- Priority: P0
- Evidence: https://support.ezfacility.com/hc/en-us/articles/18308941711899-How-to-Enable-Disable-Email-Notifications, https://support.ezfacility.com/hc/en-us/articles/4404305577755-How-to-Set-Up-Self-Service-Preferences-in-EZFacility-Classic, https://support.ezfacility.com/hc/en-us/articles/4402427176219-How-to-Set-Up-Self-Service-Preferences, https://support.ezfacility.com/hc/en-us/articles/23181863135387-How-to-Change-Self-Service-Settings-for-Packages, https://www.youtube.com/watch?v=SDO3SkkHTlY (t=07:10)

### MKT-15 SMS automation (EZMessaging, partner-powered)
- Sub-features: white-labelled automated texting driven by in-platform member data: lead generation, billing-decline and collection alerts, new-prospect alerts, renewal and birthday messages, class/session reminders, promotions; scheduled single or multiple future campaigns; short-code keywords. Video (partner demo webinar): separate partner web app with its own login and sections Keywords, Auto SMS, Subscribers, Campaign Center, Reporting, fed through the core API rather than embedded in the core UI; keyword opt-in on a shared short code: a mandatory disclaimer text, then a customisable autoresponder (may carry a link or phone number), a per-keyword folder of opted-in numbers with timestamps and a running count, and an email to the facility on every new inquiry; Auto SMS automations, each switched on or off separately: birthday messages (any number, each with its own text, delivery time and target groups), annual special-occasion messages, new-member sequence (unlimited steps at N days after the client is created, first step = welcome plus disclaimer), prospect follow-up sequence, billing-decline sequence (unlimited steps with day offsets, for recurring and invoice payment declines alike), cancellation confirmation text (can ask for a reason or offer a rejoin incentive), and a 'we miss you' text after a set number of days without a check-in; campaign centre, groups and inbox are MKT-23.
- Settings / options: not publicly documented (configured in the partner tool). Video: in the partner tool - keyword; autoresponder text; per automation: on/off, message text (URL or phone number allowed), delivery time, day offset, target groups; inactivity threshold in days (example 15); monthly plan tier.
- Rules / limits: delivered by partner Textmunication (launched Sept 2018); separate subscription (inferred). Video: a keyword belongs to one customer on the short code (availability is shown); nobody is texted before receiving the disclaimer; a nightly job syncs clients and evaluates triggers, so messages leave the next day at the configured time; a client leaves the decline sequence when the payment is fixed, the steps run out, or the account is cancelled or sent to collections; the number used is the Mobile field, else the primary/home number (10 digits, any formatting); opt-outs (STOP) and undeliverable numbers (landline, invalid) are purged automatically and delivery reports show line type and failure reason; texting an existing database starts with a consent disclaimer and groups become usable 24 hours later, unless the facility holds prior documented consent; a previous provider's opt-out list can be loaded; the core 'session reminders' subscription is not valid consent for this tool; opt-in/opt-out state lives only in the partner tool; keyword leads do not create core client records (link a web form or key them in); month-to-month plans sized by monthly text allotment (quoted $49.99 for 2,000, $99 for 4,000, $149 for 7,000, top tier 10,000) plus a one-time setup fee; at the cap the campaign centre locks until the 1st while automations keep sending, with no overage fee; Canada runs on a different short code with smaller allotments.
- User story: As a facility, I want automatic texts for reminders and collections, so that members act quickly.
- Actors: administrator, client.
- UI generation: n-a.
- Priority: v2-adapter
- Evidence: https://support.ezfacility.com/hc/en-us/articles/4405044141723-Online-Webinar-Power-Your-SMS-Communication-with-EZMessaging, https://www.ezfacility.com/ezmessaging/, https://www.ezfacility.com/blog/make-the-most-of-ezfacility-management-software-features, https://www.ezfacility.com/blog/baseball-membership-communication-software, https://www.youtube.com/watch?v=eISJe5bhK3Y (t=06:45, t=09:51, t=21:03, t=24:07, t=30:16, t=49:43, t=54:54, t=57:59, t=66:10)

### MKT-16 Push notifications (broadcast)
- Sub-features: compose and post to all app users of chosen locations; schedule; history; per-notification analytics; copy; delete.
- Settings / options: message text (max 180 chars, may contain a URL); "post message" (immediate); "schedule it" + date/time; location multi-select for multi-location apps; history columns message, locations, sent date/time; "i" analytics; copy; delete. Video: history shows a 'preparing for sending' status; a just-posted message can be recalled for a few seconds (Settings > remove notification, confirm) and a trash icon in the sending/sent history later removes it from members' in-app notification lists; emoji are accepted (vendor demos 2017-18).
- Rules / limits: 180-character cap; no audience filters in this tier; available in both MM+ and Branded App; requires "Send notifications for this location" or full permission. Video: no cap on how many notifications are sent and no per-message fee; the in-app notification list is kept per location and lets members with push switched off still read messages; with the app open the member is asked whether to show the notification; the shared app's composer has only message and schedule; the admin portal had two access tiers, full admin and notification-only, granted per location (2017); a multi-location admin sends to one or all locations from one console.
- User story: As a facility, I want to push announcements to members' phones, so that news and openings are seen immediately.
- Actors: administrator (app admin portal user).
- UI generation: n-a (separate app admin portal).
- Priority: P0
- Evidence: https://support.ezfacility.com/hc/en-us/articles/29244337277083-Sending-Push-Notifications-MemberMe-Branded-App, https://www.ezfacility.com/features/branded-mobile-app/, https://apps.apple.com/us/app/memberme/id969248357, https://www.youtube.com/watch?v=uLNIb7JsjkM (t=12:18, t=42:04, t=45:09), https://www.youtube.com/watch?v=oNHKhlv39qo (t=52:14), https://www.youtube.com/watch?v=Zs-8tpgvadk (t=14:28), https://www.youtube.com/watch?v=iMeRIT504Ho (t=20:24, t=40:52), https://www.youtube.com/watch?v=7yHNga6cY0g (t=04:07, t=17:30)

### MKT-17 Targeted push notifications
- Sub-features: audience filters on top of MKT-16, stackable and individually invertible.
- Settings / options: "notification targets" filter types age, gender, last check in, membership status, application activity; "reverse conditions" per filter; confirm/cancel per filter; otherwise as MKT-16. Video (spring 2025 demo): the age target takes a range (captions say 'date range') with an option to include people with no date of birth; member status values include pending and active.
- Rules / limits: Branded App only; extra paid subscription; 180-character cap; filter operators/value shapes not documented.
- User story: As a marketer, I want to push to a segment (e.g. lapsed visitors), so that messages are relevant.
- Actors: administrator.
- UI generation: n-a.
- Priority: P1
- Evidence: https://support.ezfacility.com/hc/en-us/articles/29194752348827-Sending-Targeted-Push-Notifications-Branded-App-Only-Additional-subscription-required, https://support.ezfacility.com/hc/en-us/articles/29244296451355-Sending-Targeted-Push-Notifications-Branded-App-Only-Additional-subscription-required, https://www.youtube.com/watch?v=RrSuB-v34Gw, https://www.ezfacility.com/blog/baseball-membership-communication-software, https://www.youtube.com/watch?v=uLNIb7JsjkM (t=22:33, t=39:01)

### MKT-18 News stories on the public league site
- Sub-features: add/edit/delete stories; rich text; publish to home page and/or specific leagues/tournaments.
- Settings / options: Title; body; home-page flag; dual-list assignment of leagues/tournaments.
- Rules / limits: home-page stories render below the schedule; assigned stories surface on the league/tournament page (as a link at top or a "news" tab, depending on site generation).
- User story: As a league administrator, I want to post news to the public site, so that teams see announcements.
- Actors: league administrator.
- UI generation: n-a (EZLeagues site).
- Priority: P1
- Evidence: https://support.ezfacility.com/hc/en-us/articles/4405044381211-How-to-Add-News-Articles-on-the-Public-Website, https://support.ezfacility.com/hc/en-us/articles/26661408580891-How-to-Add-News-Articles-on-the-Public-Website

### MKT-19 Loyalty/rewards partner integration (Perkville)
- Sub-features: points for check-ins, referrals, birthdays, class attendance, PT; staff edit point-earning activities. Video: three earning metrics named - money spent, number of check-ins, class attendance - with the facility choosing the reward per points level.
- Settings / options: point rules live in the partner product.
- Rules / limits: partner-specific. Video: a separate platform the facility signs up to itself.
- User story: As a facility, I want to reward attendance and referrals, so that retention improves.
- Actors: administrator, member.
- UI generation: n-a.
- Priority: v2-adapter
- Evidence: https://www.ezfacility.com/blog/activate-perkville-on-ezfacility-and-gamify-exercise-this-year, https://www.ezfacility.com/partners, https://www.youtube.com/watch?v=iHdqoLdGlQI (t=19:32)

### MKT-20 Automated/triggered marketing sequences and lead follow-up
- Sub-features (marketing claims only): triggered sequences and auto-responses; follow-up of trial sign-ups who did not join and of "request more information" enquiries; reports on referrals, lead conversions, promotion engagement, bounces.
- Settings / options: none documented.
- Rules / limits: no help article describes triggers, delays or exit conditions.
- User story: As a marketer, I want messages sent automatically on lifecycle events, so that leads and lapsing members are followed up without manual work.
- Actors: marketing staff.
- UI generation: New (inferred, part of the advanced add-on).
- Priority: P1
- Evidence: https://www.ezfacility.com/blog/unlimited-email-ezfacility-benefits, https://www.ezfacility.com/blog/grow-your-business-with-the-right-software-solution, https://www.ezfacility.com/press-news/blog/fitness-newsletter

### MKT-21 Website/digital-marketing partner (97Display)
- Sub-features: partner listing for websites and digital marketing. Video (c. 2014-16 webinar): partner-built sites pass captured leads into the core system (no field-level detail).
- Settings / options: none. Video: commercial terms quoted then - discounted $97 site setup via coupon and a free site review through a partner landing page.
- Rules / limits: partner-specific.
- User story: As an owner, I want a marketing website that links to booking, so that prospects convert.
- Actors: owner.
- UI generation: n-a.
- Priority: v2-adapter
- Evidence: https://www.ezfacility.com/partners, https://www.youtube.com/watch?v=emdiEKgqp2s (t=37:59, t=38:59)


### MKT-23 SMS campaign centre, audience groups and two-way inbox (partner tool)
- Sub-features: mass text to chosen groups, sent now or scheduled; audience groups synced nightly from core data (current members, former/cancelled, prospects/guests/leads, paying members with no check-ins) plus facility-built custom groups (including staff groups for internal texts); one-to-one text to any client found by name or number; campaign history with reuse; scheduled list editable and cancellable before sending; inbound replies tab with the full conversation thread and a reply box.
- Settings / options: internal campaign name (never shown to recipients); message box with live character counter; URL shortener checkbox; group checkboxes (the no-check-in group can be included or excluded); "review campaign" phone preview; "send me a preview" to the user's own number; send now | schedule.
- Rules / limits: a STOP instruction is added to every text; the replies tab refreshes manually; locked once the monthly allotment is used (MKT-15); only disclaimed/consented numbers can be campaigned.
- User story: As a marketer, I want to text a segment and answer the replies in one place, so that promotions and conversations run from one number.
- Actors: administrator, marketing staff, client.
- UI generation: n-a (partner web app).
- Priority: v2-adapter
- Evidence: https://www.youtube.com/watch?v=eISJe5bhK3Y (t=38:27, t=40:27, t=43:31, t=45:39, t=46:40)

## Self-Service Portal

### SSP-01 Portal enablement, public visibility, vanity URL and landing page
- Sub-features: master on/off per location; anonymous browsing; custom URL slug with copy; choose landing page.
- Settings / options: Enable Self-Service Site; Allow public to view self-service site (no login; lands on configured landing page); vanity URL rename + Copy; landing page choice (e.g. schedule/calendar or the login screen; full option list not published).
- Rules / limits: settings are per location; changes are seen by other logged-in users only after re-login; groups published from the back office appear under the Registrations tab. Video: the portal is stated to be included in every plan at no extra charge.
- User story: As an owner, I want a branded portal address that prospects can browse without logging in, so that booking starts from my marketing.
- Actors: owner, administrator, public visitor.
- UI generation: both.
- Priority: P0
- Evidence: https://support.ezfacility.com/hc/en-us/articles/4404305577755-How-to-Set-Up-Self-Service-Preferences-in-EZFacility-Classic, https://support.ezfacility.com/hc/en-us/articles/4402427176219-How-to-Set-Up-Self-Service-Preferences, https://support.ezfacility.com/hc/en-us/articles/4404312819483-How-To-Select-the-Self-Service-Landing-Page-in-EZFacility-Classic, https://www.ezfacility.com/self-service-portal, https://www.youtube.com/watch?v=5sm7eWzaQD4 (t=25:43)

### SSP-02 Session booking defaults (location level)
- Sub-features: nine default policies governing client self-booking of sessions/classes.
- Settings / options: Default Availability = Allow booking | List only, do not book (prompt to call) | Do not list. Default Requirements = active paid-to-date membership and/or package paid to date (through current invoice date). Visible Range (shared with MM+; ceiling depends on services). Hide Full Sessions (MM+). Default Cutoff Times = booking cutoff before start; allow client cancellation + notice required. Allow Post-Billed Packages. Default Adjacent Booking Restriction = none | show and count non-adjacent slots but block self-booking | hide non-adjacent slots. Waitlist = Enable | Disable. Auto-Book Next Client = Enabled | Disabled.
- Rules / limits: Allow booking needs a qualifying package; if that package is sold online the client is prompted to buy and the booking completes; bookings appear on the staff calendar immediately; Visible Range has no per-reservation-type override; post-billed packages are usable until billing is closed, must be unlimited and account-linked, and cannot be sold online; auto-book promotes in waitlist order and emails the client; a cutoff value must exist for self-cancellation to be allowed.
- User story: As an administrator, I want one place to set who can book what and how late, so that online booking follows house rules.
- Actors: administrator.
- UI generation: both.
- Priority: P0
- Evidence: https://support.ezfacility.com/hc/en-us/articles/4404305577755-How-to-Set-Up-Self-Service-Preferences-in-EZFacility-Classic, https://support.ezfacility.com/hc/en-us/articles/4402427176219-How-to-Set-Up-Self-Service-Preferences, https://www.ezfacility.com/self-service-portal

### SSP-03 Per-reservation-type self-service overrides
- Sub-features: override location defaults per reservation type; restrict which package plans may book; public description; private direct links.
- Settings / options: each setting has "Use location default". Listing = Do not list | List only, do not book | Allow booking. Cutoff times (booking; cancellation). Requirements: "Client must have an active, paid-to-date membership"; "The package used to book must be paid-to-date". Allowed Package Types (default all; once any are added only those may book). Instant Email Alerts. Autobook Waitlist = use location default | disabled. Online Description (portal and app). Total participants allowed.
- Rules / limits: a "Do not list" type is still bookable via its direct URL (used for private events). Video: no per-client cap on bookings per day or on booked duration (e.g. three court hours) exists in the portal or app - the only lever is limiting a client to one package at a time (2025 Q&A); switching Listing to 'List only, do not book' is the suggested way to hide the Book button while a type offers only videos.
- User story: As an administrator, I want exceptions per service, so that premium or private sessions follow different rules.
- Actors: administrator.
- UI generation: both (Classic wrench icon; New cog on Packages > Reservation Types).
- Priority: P0
- Evidence: https://support.ezfacility.com/hc/en-us/articles/23181863135387-How-to-Change-Self-Service-Settings-for-Packages, https://support.ezfacility.com/hc/en-us/articles/4404314743067-Managing-Self-Service-Shared-Bookings-in-EZFacility-Classic, https://support.ezfacility.com/hc/en-us/articles/4404305577755-How-to-Set-Up-Self-Service-Preferences-in-EZFacility-Classic, https://www.youtube.com/watch?v=uLNIb7JsjkM (t=38:56), https://www.youtube.com/watch?v=qUf6jPISK_8 (t=11:19)

### SSP-04 Online rental booking (defaults and client flow)
- Sub-features: location rental defaults; per-rental-type overrides; client search-and-book flow with payment; hold timer during checkout; zero-priced rentals.
- Settings / options: Allow users to book rentals online; visible range; allow customer to set search start date + maximum future limit; hold clock (minutes or seconds); per Rental Type online booking Allow booking | Do not allow booking. Client search inputs: person (if relationships exist), location (if multiple), rental type, venue, weekday toggles, Start Search On, Rental Length (e.g. 1 h, 1.5 h), Start Time.
- Rules / limits: self-service start/end times only on the hour (2023-06-28); $0 rental types are bookable online (2023-06-12); the Book Rental menu tab auto-hides when no rental type allows booking (SSP-13); a 2026 title-only article covers rental self-service setup (body not read).
- User story: As a client, I want to find and pay for a free court slot online, so that I do not have to phone.
- Actors: client, administrator.
- UI generation: both.
- Priority: P0
- Evidence: https://support.ezfacility.com/hc/en-us/articles/25312602916763-How-to-Book-a-Rental-on-Self-Service, https://support.ezfacility.com/hc/en-us/articles/4404305577755-How-to-Set-Up-Self-Service-Preferences-in-EZFacility-Classic, https://support.ezfacility.com/hc/en-us/articles/4402427176219-How-to-Set-Up-Self-Service-Preferences, https://support.ezfacility.com/hc/en-us/articles/4404305596827-How-to-Configure-Available-Tabs-in-the-Self-Service-Menu-using-EZFacility-Classic, https://support.ezfacility.com/hc/en-us/articles/16731304236571-June-28th-2023-Release-Notes, https://support.ezfacility.com/hc/en-us/articles/16308423683355-June-12th-2023-Release-Notes, https://support.ezfacility.com/hc/en-us/articles/57005260684315-How-to-set-up-Rentals-For-Self-Service (title only, body not read)

### SSP-05 Public self-registration and account creation
- Sub-features: Register/Create Account on the login page; optional email verification gate; completion of required profile fields; immediate creation of a client record.
- Settings / options: Allow public registrations; "Configure public registrations settings" = require email verification and required contact info before first login | allow login without verification. Minimum fields First Name, Last Name, Email, Username, Password; further required fields flagged per facility configuration.
- Rules / limits: self-registered person becomes a client instantly; with verification on, a "Registration Confirmation" email carries a Complete Registration link; login immediately after sign-up works since 2023-08-16; captcha present on sign-up (2023-08-02 note).
- User story: As a prospect, I want to create my own account, so that I can book and buy without staff help.
- Actors: prospect, client.
- UI generation: both.
- Priority: P0
- Evidence: https://support.ezfacility.com/hc/en-us/articles/26528305868699-How-to-Create-an-Account-on-Self-Service, https://support.ezfacility.com/hc/en-us/articles/4404305577755-How-to-Set-Up-Self-Service-Preferences-in-EZFacility-Classic, https://support.ezfacility.com/hc/en-us/articles/4402427176219-How-to-Set-Up-Self-Service-Preferences, https://support.ezfacility.com/hc/en-us/articles/17981009155995-August-16th-2023-Release-Notes, https://support.ezfacility.com/hc/en-us/articles/17574439837467-August-2nd-2023-Release-Notes

### SSP-06 Invitations, account status and access recovery
- Sub-features: invite one client (profile checkbox) or many (list bulk action); accept-invitation link to create username/password; disable an account; staff view of account state and username; self-service password recovery.
- Settings / options: per-client Self-Service "Enabled" checkbox; list action "Invite for Self-Service" (For Checked); list page size 20 default up to 100, page-level select-all; portal "Having Trouble?" link (username + email).
- Rules / limits: invitation requires a valid (verifiable) email; unique emails recommended; bulk selection is per page; unticking Enabled disables the account; invitation timestamps follow facility time zone (2023-07-03).
- User story: As front-desk staff, I want to onboard existing clients to the portal in bulk, so that adoption does not need individual set-up.
- Actors: administrator, front desk, client.
- UI generation: both.
- Priority: P0
- Evidence: https://support.ezfacility.com/hc/en-us/articles/4404314764827-How-to-Invite-Your-Clients-to-Use-Self-Service, https://support.ezfacility.com/hc/en-us/articles/4402427133851-Self-Service-How-to-invite-existing-contacts, https://support.ezfacility.com/hc/en-us/articles/15942682403227-How-to-Assist-Clients-who-Cannot-Log-into-Self-Service, https://support.ezfacility.com/hc/en-us/articles/16846068050715-July-3rd-2023-Release-Notes

### SSP-07 Post-registration redirects
- Sub-features: separate destination after public registration and after invitation acceptance; shareable registration link.
- Settings / options: Redirect after Public Registration (URL); Redirect after Registration via Invitation (URL); Copy link.
- Rules / limits: existing account holders should keep using the original portal link.
- User story: As a marketer, I want new registrants to land on a specific page (e.g. Book Rental), so that sign-up converts to a booking.
- Actors: administrator.
- UI generation: both.
- Priority: P2
- Evidence: https://support.ezfacility.com/hc/en-us/articles/4404312815771-Setting-Up-a-Self-Service-Registration-Redirect-in-EZFacility-Classic, https://support.ezfacility.com/hc/en-us/articles/4404305577755-How-to-Set-Up-Self-Service-Preferences-in-EZFacility-Classic, https://support.ezfacility.com/hc/en-us/articles/4402427176219-How-to-Set-Up-Self-Service-Preferences

### SSP-08 Book a session with inline package purchase; online sale flags
- Sub-features: click session > Book > authenticate/register > buy required package > pay > accept payment terms > booking auto-completes and shows in My Schedule; package plans flagged for online sale; sale of fixed-start-date products after start. Video: prices shown follow the viewer's membership status (member vs non-member rate, e.g. cheaper PT for a top-tier member); each membership plan has its own purchase-page link, listing the plan's benefits, that can be placed on the facility website.
- Settings / options: Package plan "Sell Online" = No (implied) | Yes - Allow Balances | Yes - Paid in Full; "include memberships and/or packages that start in the past" toggle; Payment Terms & Conditions text (SSP-14).
- Rules / limits: terms step appears only when configured; purchase and booking are a single flow; parent can buy for a relative who has no portal account (2023-08-02 fix).
- User story: As a client, I want to buy what I need at the moment of booking, so that I am not bounced to the front desk.
- Actors: client.
- UI generation: both.
- Priority: P0
- Evidence: https://support.ezfacility.com/hc/en-us/articles/26528293115547-Book-into-a-Session-and-Buy-a-Package-on-Self-Service, https://support.ezfacility.com/hc/en-us/articles/4402427212571-How-to-Mark-Package-Plans-as-Sold-Online, https://support.ezfacility.com/hc/en-us/articles/4404305577755-How-to-Set-Up-Self-Service-Preferences-in-EZFacility-Classic, https://support.ezfacility.com/hc/en-us/articles/4402427176219-How-to-Set-Up-Self-Service-Preferences, https://support.ezfacility.com/hc/en-us/articles/17574439837467-August-2nd-2023-Release-Notes, https://www.youtube.com/watch?v=5sm7eWzaQD4 (t=34:56, t=35:58)

### SSP-09 Shared-booking patterns (couples, private links, teams)
- Sub-features: (a) combined-cost booking where one package covers two related people and one session is deducted; (b) private session reachable only by direct URL; (c) team package shared to players who then book at no cost.
- Settings / options: reservation type participants allowed = 1; package auto-share to related clients; Online Description; Listing "Do Not List" with Use Location Default unticked; BUY button auto-books and redirects to My Schedule.
- Rules / limits: relationships must exist before the sale for auto-share to apply; direct URLs also work for normally listed sessions.
- User story: As a coach, I want a private or shared booking that only invited clients can take, so that bespoke sessions do not appear on the public calendar.
- Actors: client, coach, trainer, administrator.
- UI generation: Classic.
- Priority: P1
- Evidence: https://support.ezfacility.com/hc/en-us/articles/4404314743067-Managing-Self-Service-Shared-Bookings-in-EZFacility-Classic

### SSP-10 Customer profile self-management, stored payment method and relationships
- Sub-features: admin chooses which profile areas customers may edit; customers add relationships and act for related clients with one login; card-on-file policy.
- Settings / options: editable areas Profile Picture, Basic Profile Information, Contact Information, Payment Method (card), Billing Address, Add relationships; Self-Service Credit Card Settings (options not enumerated; can force card storage when memberships/auto-renew packages are sold); gender field visibility/requirement configurable on self-service (2024-04-24). Video (membership sell-online demo): the card setting either forces or makes optional the saving of the card at an online membership purchase.
- Rules / limits: adding a relationship emails the other party for confirmation; link an existing client by email or create a new client with a relationship type; one login books and shops for all linked clients.
- User story: As a parent, I want to manage my children's bookings and my card from one login, so that the household is handled together.
- Actors: client, parent/guardian, administrator.
- UI generation: both.
- Priority: P0
- Evidence: https://support.ezfacility.com/hc/en-us/articles/4404305577755-How-to-Set-Up-Self-Service-Preferences-in-EZFacility-Classic, https://support.ezfacility.com/hc/en-us/articles/4402427176219-How-to-Set-Up-Self-Service-Preferences, https://support.ezfacility.com/hc/en-us/articles/25134483797531-April-24th-2024-Release-Notes, https://www.ezfacility.com/self-service-portal, https://www.youtube.com/watch?v=a7-8-cHwB8Y (t=39:57)

### SSP-11 Coupons at portal checkout
- Sub-features: enable coupon entry at checkout; per-coupon online eligibility; usage limits.
- Settings / options: Allow Coupons; per-coupon "enabled for Self-Service"; usage limit (e.g. once per customer).
- Rules / limits: per-person limit also applies when buying for a relative (2023-08-31 fix).
- User story: As a marketer, I want promo codes redeemable online, so that campaigns convert.
- Actors: client, administrator.
- UI generation: both.
- Priority: P1
- Evidence: https://support.ezfacility.com/hc/en-us/articles/4404305577755-How-to-Set-Up-Self-Service-Preferences-in-EZFacility-Classic, https://support.ezfacility.com/hc/en-us/articles/4402427176219-How-to-Set-Up-Self-Service-Preferences, https://support.ezfacility.com/hc/en-us/articles/18408526583067-August-31st-2023-Release-Notes

### SSP-12 Portal calendar views
- Sub-features: client-switchable calendar views; admin default; hide booked slots.
- Settings / options: views Day, Week, Month, Agenda, Resource (resource day view); default view setting; option to make booked spots invisible (Classic).
- Rules / limits: client changes are temporary; resources with numeric names sort ascending (2023-07-03 fix). Video: staff cannot email a client their schedule from the product; the client uses My Schedule, or staff export/print it.
- User story: As a client, I want to see availability by resource for a day, so that I can pick a free lane/court.
- Actors: client, administrator.
- UI generation: both (Agenda/Resource documented for New).
- Priority: P0
- Evidence: https://support.ezfacility.com/hc/en-us/articles/9118010703771-How-to-show-the-Self-Service-Calendar-in-Resource-View, https://support.ezfacility.com/hc/en-us/articles/4404305577755-How-to-Set-Up-Self-Service-Preferences-in-EZFacility-Classic, https://support.ezfacility.com/hc/en-us/articles/4402427176219-How-to-Set-Up-Self-Service-Preferences, https://support.ezfacility.com/hc/en-us/articles/16846068050715-July-3rd-2023-Release-Notes, https://www.youtube.com/watch?v=TWNQ4cTiEFs (t=44:17)

### SSP-13 Portal menu configuration
- Sub-features: toggle left-menu tabs; automatic hiding of tabs with nothing to offer.
- Settings / options: menu items include Book Rental, Registrations, Video Library (full list not published); custom wording for menu terms (SSP-14).
- Rules / limits: Book Rental hides when every rental type disallows online booking and returns when one allows it; it stays visible when booking is allowed but no dates fall in the visible range; needs "Allow users to book rentals online".
- User story: As an administrator, I want the menu to show only what we sell, so that clients are not led to empty pages.
- Actors: administrator.
- UI generation: both.
- Priority: P1
- Evidence: https://support.ezfacility.com/hc/en-us/articles/4404305596827-How-to-Configure-Available-Tabs-in-the-Self-Service-Menu-using-EZFacility-Classic, https://support.ezfacility.com/hc/en-us/articles/4402427176219-How-to-Set-Up-Self-Service-Preferences

### SSP-14 Portal design, content and legal text
- Sub-features: logo/banner; primary colour; welcome message; menu-term renaming; payment terms & conditions shown at checkout; web analytics tag.
- Settings / options: Branding banner image 160 x 36 px; Self-Service Colors (primary colour); Welcome Message (rich text, hideable); Custom Text (rename menu terms); Payment Terms & Conditions; Google Analytics tracking ID.
- Rules / limits: must save before leaving the page; a 2026 title-only article indicates an explicit T&C acknowledgment step (body not read).
- User story: As an owner, I want the portal to look like my brand and state my policies, so that clients trust it and accept terms.
- Actors: owner, administrator.
- UI generation: both.
- Priority: P0
- Evidence: https://support.ezfacility.com/hc/en-us/articles/4402427175195-How-to-Set-Up-Self-Service-Design, https://support.ezfacility.com/hc/en-us/articles/4404305580443-Online-Webinar-Self-Service-Set-up-in-EZFacility-Classic, https://support.ezfacility.com/hc/en-us/articles/22968789591963-February-15th-2024-Release-Notes, https://support.ezfacility.com/hc/en-us/articles/54599987433883-Self-Service-Terms-Conditions-Acknowledgment (title only, body not read)

### SSP-15 Social media links on the portal
- Sub-features: icon links on the landing page. Video (presenter claim, not demonstrated): a facility's Instagram videos can be pulled into the portal video library automatically.
- Settings / options: one URL per social account; blank ones are hidden. Video: a website URL field sits beside the social links (each icon appears only once its URL is entered); platforms named: Twitter, Facebook, Instagram.
- Rules / limits: https only; not shown when the login screen is the landing page; platform list not published.
- User story: As a marketer, I want social links on the portal, so that clients follow us.
- Actors: administrator.
- UI generation: both.
- Priority: P2
- Evidence: https://support.ezfacility.com/hc/en-us/articles/4404305593243-How-to-Add-Social-Media-Links-to-Self-Service-in-EZFacility-Classic, https://support.ezfacility.com/hc/en-us/articles/4404305577755-How-to-Set-Up-Self-Service-Preferences-in-EZFacility-Classic, https://support.ezfacility.com/hc/en-us/articles/4402427176219-How-to-Set-Up-Self-Service-Preferences, https://www.ezfacility.com/blog/new-ezfacility-business-features, https://www.youtube.com/watch?v=IM8m1sUsMdw (t=10:19), https://www.youtube.com/watch?v=5sm7eWzaQD4 (t=48:13, t=49:14)

### SSP-16 Video library
- Sub-features: catalogue of externally hosted videos; optional link to a reservation type (category/filter and "Watch Now" on the class); enable/disable; copy a direct video URL and share by email. Video (2020 launch webinars): reservation type 'N/A' keeps a video in the library only (shown under 'other'); every video on a type is listed on each of its sessions; live streams work by pasting a scheduled YouTube live URL or iframe; Facebook video via iframe.
- Settings / options: Video Type = URL | HTML (embed code); Title; URL or HTML; Reservation Type (optional); Preview; disabled flag (+ list filter include/exclude disabled); "Copy Direct Video URL".
- Rules / limits: hosting is third-party (YouTube/Facebook named); URL and HTML render identically; unlinked videos remain in the library; a dedicated reservation type can serve as a pure content category. Video: a video attaches to a reservation type, never to one dated session; no restriction by membership, package or session capacity - anyone with a portal login can watch; YouTube items must be Public or Unlisted (Private cannot be embedded); a Facebook live URL changes with each broadcast and must be re-entered; watching neither deducts a package session nor records attendance; no view metrics in the product (use the host's analytics); Zoom recordings do not flow in and are added as ordinary URL entries; previews may not render for some hosts; playlist URLs untested.
- User story: As a client, I want on-demand videos grouped by class type, so that I can train remotely or preview a class.
- Actors: administrator, trainer, client.
- UI generation: both.
- Priority: P0
- Evidence: https://support.ezfacility.com/hc/en-us/articles/4404305590683-How-to-Set-up-the-Self-Service-Video-Library-in-EZFacility-Classic, https://support.ezfacility.com/hc/en-us/articles/4404312817947-How-to-Create-a-Video-Library-for-Customers-in-EZFacility-Classic, https://support.ezfacility.com/hc/en-us/articles/4404312820763-How-to-Share-a-Link-to-a-Specific-Video-in-the-EZFacility-Classic-Video-Library, https://support.ezfacility.com/hc/en-us/articles/4402434185883-How-to-Create-a-Video-Library-for-Customers, https://support.ezfacility.com/hc/en-us/articles/4402427173019-Using-the-Self-Service-Video-Library, https://www.ezfacility.com/blog/new-ezfacility-business-features, https://www.ezfacility.com/features/member-engagement, https://www.youtube.com/watch?v=qUf6jPISK_8 (t=08:16, t=10:16, t=16:29), https://www.youtube.com/watch?v=IM8m1sUsMdw (t=12:26, t=13:26, t=16:29, t=21:36, t=31:46), https://www.youtube.com/watch?v=hlGAZlxFHWg (t=05:19, t=23:57)

### SSP-17 Publish a group (program) for online registration
- Sub-features: publish/update a group to the portal Registrations menu with its own public name and informational dates.
- Settings / options: Publish Name; Session Starts; Session Ends; Show in Self Service; button Publish Group / Update Group; read-only summary of Group Name, Sport, Session, Age Group/Division, Registration Starts/Ends.
- Rules / limits: session dates are informational and distinct from the registration window; not visible unless Show in Self Service is ticked.
- User story: As a program coordinator, I want to expose a camp/league for online sign-up, so that parents register themselves.
- Actors: administrator, client.
- UI generation: New.
- Priority: P0
- Evidence: https://support.ezfacility.com/hc/en-us/articles/28746953502875-How-to-Publish-a-Group-to-Self-Service, https://support.ezfacility.com/hc/en-us/articles/4404312819483-How-To-Select-the-Self-Service-Landing-Page-in-EZFacility-Classic, https://www.ezfacility.com/self-service-portal

### SSP-18 Virtual sessions (Zoom) through the portal
- Sub-features: schedule paid or free virtual sessions, group or one-to-one; clients join from the portal.
- Settings / options: none documented in this cluster.
- Rules / limits: works with a basic Zoom account (marketing claim).
- User story: As a client, I want to join a live class from my bookings, so that I can attend remotely.
- Actors: client, trainer.
- UI generation: both (inferred).
- Priority: P0
- Evidence: https://www.ezfacility.com/blog/new-ezfacility-business-features, https://www.ezfacility.com/features/member-engagement

### SSP-19 Self-service-scope API for portal/app clients
- Sub-features: API realm separate from the back-office realm: update client (reduced field set), list package plans for sale, checkout line items for package plans, read (redacted) and update stored card.
- Settings / options: scopes TMS vs Self-Service.
- Rules / limits: used by the mobile app cart (2024-06-19).
- User story: As a facility with a custom website/app, I want member-scoped endpoints, so that I can build my own front end.
- Actors: integrator, mobile app.
- UI generation: n-a.
- Priority: P1
- Evidence: https://support.ezfacility.com/hc/en-us/articles/22529640450203-January-31-2024-Release-Notes, https://support.ezfacility.com/hc/en-us/articles/26498179644187-June-5th-2024-Release-Notes, https://support.ezfacility.com/hc/en-us/articles/26750732215835-June-19th-2024-Release-Notes, https://www.ezfacility.com/blog/client-highlight-c2tactical-utilizes-ezfacility-digital-api

### SSP-20 Account self-service: balances, invoices, documents
- Sub-features: pay outstanding balances; view invoices; access forms/waivers; buy memberships, packages and rental plans.
- Settings / options: none documented in this cluster.
- Rules / limits: marketing-level evidence only for the invoice/document views. Video: paying open invoices and viewing closed invoices/history are confirmed in presenter narration; a client cannot cancel their own membership in the portal (request passed to development, no date).
- User story: As a member, I want to settle my balance and see my paperwork online, so that I do not need the front desk.
- Actors: member, parent.
- UI generation: both (inferred).
- Priority: P0
- Evidence: https://www.ezfacility.com/self-service-portal, https://www.ezfacility.com/blog/make-the-most-of-ezfacility-management-software-features, https://www.ezfacility.com/blog/introducing-rental-plans-prepaid-rentals-made-simple, https://www.youtube.com/watch?v=5sm7eWzaQD4 (t=38:00, t=63:33)

## Mobile App

### APP-01 Member app core (shared multi-tenant app)
- Sub-features: find a facility by name/city/state/zip; live schedules for classes, trainers, rooms, fields, courts with open-slot counts, descriptions and cut-offs; book/cancel; buy/book packages; see own bookings; waitlist; remaining package count; trainer profiles. Video: launch without login (browse offerings; portal credentials needed only to book); after finding the facility the member saves it as home club; users without an account can still add classes to the phone calendar, see promotions and receive push; the facility chooses whether all sessions or only selected ones show; league fixtures, results, standings and group registration are reached by link to the public league site/registration pages.
- Settings / options: driven by portal settings (visible range, hide full sessions, online descriptions, listing modes).
- Rules / limits: iOS and Android; staff-side schedule management is not offered in the app; public reviews are dominated by load/crash failures after updates. Video: login uses the self-service credentials; availability shows open spots only, never other attendees; no user switching - a parent logs out and in as the child to book for them (2022 Q&A, no change planned); booking needs a package (sessions without one are view-only) and rentals cannot be booked in the app (2017 statement; a 2025 demo shows rentals listed as 'unavailable'); private one-to-one lessons need instructors with fixed schedules (2017); Zoom meetings cannot be launched from the shared app; the shared app may need enabling on request and its directory can surface similarly named or nearby businesses; 2022-2025 webinars describe the waitlist as Branded-only (see unknowns).
- User story: As a member, I want to book and manage sessions from my phone, so that I do not need to call.
- Actors: member.
- UI generation: n-a.
- Priority: P0
- Evidence: https://apps.apple.com/us/app/memberme/id969248357, https://play.google.com/store/apps/details?id=com.bottegasol.com.migym.memberme, https://www.ezfacility.com/features/branded-mobile-app/, https://support.ezfacility.com/hc/en-us/articles/4404305577755-How-to-Set-Up-Self-Service-Preferences-in-EZFacility-Classic, https://www.youtube.com/watch?v=7yHNga6cY0g (t=20:32, t=21:34), https://www.youtube.com/watch?v=lwC-tepoJ0I (t=20:31), https://www.youtube.com/watch?v=t85Pe_jL_h4 (t=37:52, t=51:05), https://www.youtube.com/watch?v=oNHKhlv39qo (t=43:01, t=44:05, t=49:11), https://www.youtube.com/watch?v=iMeRIT504Ho (t=18:22, t=37:49), https://www.youtube.com/watch?v=qn8y8rfi-kc (t=21:28), https://www.youtube.com/watch?v=5sm7eWzaQD4 (t=57:24)

### APP-02 White-label branded app (per-tenant theme)
- Sub-features: facility-specific app identity (logo, colours, layout); same member features as APP-01 plus targeted push and custom home screen. Video: Branded-only list given in webinars - custom icon, splash and load screens, own name in the stores, unlimited tiles with multiple web-link tiles, waitlist, targeted and location-specific push, reporting suite, earlier access to new app features.
- Settings / options: colour scheme agreed at onboarding; default icon recolour by hex via vendor support. Video: list price quoted as $99/month (GBP 75) per location plus a one-time setup fee; optional custom home-screen design about $200 one-off; recurring webinar promotions (not product facts).
- Rules / limits: paid add-on, bundled in upper plan tiers. Video: a separate download - members do not move over automatically from the shared app, though credentials are the same and both apps can run side by side during migration; embedding third-party tool links is reviewed case by case.
- User story: As an owner, I want my own app identity, so that members see my brand rather than the vendor's.
- Actors: owner, member.
- UI generation: n-a.
- Priority: P0
- Evidence: https://www.ezfacility.com/features/branded-mobile-app/, https://www.ezfacility.com/features/member-engagement, https://www.youtube.com/watch?v=uLNIb7JsjkM, https://www.ezfacility.com/press-news/press-releases/jonas-software-announces-the-acquisition-of-apps-that-fit-llc-migym, https://www.youtube.com/watch?v=t85Pe_jL_h4 (t=28:39, t=38:52), https://www.youtube.com/watch?v=Zs-8tpgvadk (t=29:47), https://www.youtube.com/watch?v=uLNIb7JsjkM (t=04:05, t=32:46, t=48:17), https://www.youtube.com/watch?v=7yHNga6cY0g (t=19:32, t=23:37), https://www.youtube.com/watch?v=5sm7eWzaQD4 (t=56:21)

### APP-03 App-store publishing and launch service
- Sub-features: vendor publishes the facility's own listing on both stores; three-step launch (design, layout with a designer, launch + adoption guidance). Video: real order - enrolment form, customer supplies logos and brand colours, vendor designers mock up icon/home screen/splash, approval round with change requests, developers build native iOS and Android apps, vendor uploads to both stores, onboarding call on the admin tools; afterwards the vendor monitors the app and ships OS-version updates.
- Settings / options: none.
- Rules / limits: service-delivered, not self-serve. Video: lead time quoted 4-6 weeks (1.5-3 weeks minimum when assets are ready; store review up to 5 business days); from 2022 the iOS app is published under the facility's own Apple developer account ($99/year), which by 2025 also needs a D-U-N-S number (about 30 days); released in the US, Canada, UK and Australia; moving from the shared app means members download the new one (announce by push from the old app).
- User story: As an owner, I want the app listed under my name, so that members can find it.
- Actors: owner, vendor designer.
- UI generation: n-a.
- Priority: v2-adapter
- Evidence: https://www.ezfacility.com/features/branded-mobile-app/, https://www.youtube.com/watch?v=Zs-8tpgvadk (t=24:42, t=49:08), https://www.youtube.com/watch?v=t85Pe_jL_h4 (t=26:38, t=28:39), https://www.youtube.com/watch?v=uLNIb7JsjkM (t=32:46, t=48:17), https://www.youtube.com/watch?v=7yHNga6cY0g (t=13:24), https://www.youtube.com/watch?v=iMeRIT504Ho (t=14:14), https://www.youtube.com/watch?v=5sm7eWzaQD4 (t=56:21), https://www.youtube.com/watch?v=gjyVmvHCT1M (t=46:07)

### APP-04 Home-screen designer (layout, styling, captions, global design)
- Sub-features: draft vs live home screen; import tiles / reset to default set; add, drag, resize, remove tiles; per-tile icon, background, border; three caption areas with dynamic text; global padding and background.
- Settings / options: active home screen selector incl. "Draft Home Screen"; "import tiles"; "add new tile". Tile: icon file, background colour + transparency, background image, border enable/colour/width/rounded corners. Caption areas Top | Middle | Bottom, each: Text (may contain a dynamic-text token), Alignment left|centre|right, Font Color, Font Default|Verdana|Sans Serif, Text Style Light|normal|medium|bold|condensed|condensed bold|black, Additional Styles Oblique|italic|normal, Text Size 8-30 px, Background colour + opacity (default transparent), Padding (vertical), Margin. Global: Tile Padding 0-25 pt, Background Color, Background Image.
- Rules / limits: 3-column grid, unlimited rows (scrolls); tile shapes 1:1 (also 2:2, 3:3), 1:2, 1:3; moving a tile pushes overlapped tiles; background images are centred, aspect-preserving fill; dynamic captions need a tile at least 2 columns wide; middle caption width = tile width minus one column; icons on dynamic-text tiles anchor bottom-right; design basis 375 pt width, 120 pt tile + 5 pt gutter (or 125 pt, no gutter). How a draft is promoted to live is not described. Video: shared-app admins cannot edit the home screen (changes go through vendor support), while Branded admins edit it themselves at any time; app chrome is English-only (date, instructor and activity labels), with captions free text and session names shown as entered.
- User story: As an owner, I want to compose my app's home screen, so that the most important actions are one tap away.
- Actors: administrator, vendor designer.
- UI generation: n-a (app admin portal).
- Priority: P1
- Evidence: https://support.ezfacility.com/hc/en-us/articles/29244419129627-Branded-App-Home-Screen-Layout-Configuration, https://support.ezfacility.com/hc/en-us/articles/29244435018395-Branded-App-Home-Screen-Layout-Icons-Background, https://support.ezfacility.com/hc/en-us/articles/29244421350555-Branded-App-Home-Screen-Labels-Captions-Dynamic-Text-and-Caption-Customizing, https://support.ezfacility.com/hc/en-us/articles/29194635092123-Branded-App-Home-Screen-Additional-App-Design-Settings, https://www.youtube.com/watch?v=uLNIb7JsjkM (t=08:11), https://www.youtube.com/watch?v=Zs-8tpgvadk (t=45:04), https://www.youtube.com/watch?v=oNHKhlv39qo (t=34:50)

### APP-05 Home-screen tile catalogue
- Sub-features: 24 tile types — Favorites, YouTube, Contact, My Schedule+, Pages CMS, Instagram, Self Service/My Account, Submit Feedback, Notifications, Twitter, Social Checkin, Switch Locations, Logo, Homescreen Gallery, Services, Announcements, Image, App Link, Facebook, Schedule, New Weblink, Trial Pass, Membership Card, Articles.
- Settings / options: per-type link target where applicable (social URL, web URL, app link, article set); default width 3 columns for Favorites, My Schedule+, Notifications, Announcements, Schedule.
- Rules / limits: dynamic-text tiles are Announcements, Schedule, My Schedule+, Favorites, Notifications; Notifications tile lists the last 30 days; Image tile cannot link; Gallery takes uploaded images only (recommended 3x2 tile, ~900x600 px); Trial Pass tile only opens the form (entitlement handled in the back office); My Account tile opens the web portal in an in-app browser. Video: the shared app is limited to the preset home screen with a single web-link tile, the Branded app has unlimited web-link tiles (add new tile > web link, editable text and URL) for groups, leagues, tournaments, camps, portal pages or team registration/payment pages; a web-link tile cannot restrict a purchase to members; app sessions and booking rules are the portal's own.
- User story: As an owner, I want a palette of ready-made tiles, so that I can assemble a home screen without development.
- Actors: administrator.
- UI generation: n-a.
- Priority: P1
- Evidence: https://support.ezfacility.com/hc/en-us/articles/29244450573339-Branded-App-Home-Screen-Tiles-info, https://support.ezfacility.com/hc/en-us/articles/29244419129627-Branded-App-Home-Screen-Layout-Configuration, https://www.youtube.com/watch?v=Zs-8tpgvadk (t=26:45, t=38:56), https://www.youtube.com/watch?v=uLNIb7JsjkM (t=21:32, t=43:06), https://www.youtube.com/watch?v=gjyVmvHCT1M (t=48:07)

### APP-06 Digital membership card (barcode, wallet)
- Sub-features: in-app card showing a scannable barcode for check-in; register a member ID; Apple/Google Wallet pass. Video: several cards/barcodes can sit in one app for a family (vendor quoted up to ten in 2017-18; a 2025 demo shows an 'add' control on the card).
- Settings / options: barcode auto-generate vs manual entry (app setting, values not detailed).
- Rules / limits: reviews report inability to add one card on several devices/family members or to delete a card. Video: the card number must already exist on the client profile; scanning the phone barcode opens the client's profile and photo at check-in exactly like a key tag; it cannot stand in for door fobs (2017).
- User story: As a member, I want my card on my phone, so that I can check in without plastic.
- Actors: member, front desk.
- UI generation: n-a.
- Priority: P0
- Evidence: https://support.ezfacility.com/hc/en-us/articles/29244419129627-Branded-App-Home-Screen-Layout-Configuration, https://www.ezfacility.com/features/member-engagement, https://www.ezfacility.com/features/branded-mobile-app/, https://www.ezfacility.com/press-news/press-releases/ezfacility-introduces-new-memberme-mobile-app, https://apps.apple.com/us/app/memberme/id969248357, https://www.youtube.com/watch?v=7yHNga6cY0g (t=06:10), https://www.youtube.com/watch?v=uLNIb7JsjkM (t=30:44), https://www.youtube.com/watch?v=iMeRIT504Ho (t=08:06, t=15:17), https://www.youtube.com/watch?v=lwC-tepoJ0I (t=27:39), https://www.youtube.com/watch?v=t85Pe_jL_h4 (t=21:31)

### APP-07 In-app News & Info CMS
- Sub-features: categories (create/rename/delete); articles (create/edit/delete) with rich text and a publish window; surfaced by Pages CMS and Articles tiles.
- Settings / options: category name; article title, body, publish start, publish end (optional/open-ended); publish.
- Rules / limits: expired articles leave the app but remain in the admin portal.
- User story: As a facility, I want to publish articles in the app, so that members read news and tips.
- Actors: administrator, member.
- UI generation: n-a.
- Priority: P1
- Evidence: https://support.ezfacility.com/hc/en-us/articles/29244325119899-News-Info-feature-MemberMe-Branded-App, https://support.ezfacility.com/hc/en-us/articles/29244450573339-Branded-App-Home-Screen-Tiles-info, https://apps.apple.com/us/app/memberme/id969248357

### APP-08 Contact & hours page
- Sub-features: general facility information and hours; list of department phone numbers. Video: tapping the address opens the platform's map app for directions.
- Settings / options: general info block (fields not listed in text); department rows name, number, extension (optional). Video (2025 demo): general info = location name, address, latitude/longitude (used to find the location when a member first logs in), client-facing email, a separate email the vendor uses about app issues, social links (full https URL), free-text hours/description, multiple phone numbers.
- Rules / limits: none stated.
- User story: As a member, I want hours and the right phone number in the app, so that I can reach the facility.
- Actors: administrator, member.
- UI generation: n-a.
- Priority: P1
- Evidence: https://support.ezfacility.com/hc/en-us/articles/29244434035355-Contact-Hours-Tab-MemberMe-Branded-App, https://apps.apple.com/us/app/memberme/id969248357, https://www.youtube.com/watch?v=uLNIb7JsjkM (t=19:31), https://www.youtube.com/watch?v=t85Pe_jL_h4 (t=25:37), https://www.youtube.com/watch?v=Zs-8tpgvadk (t=22:41)

### APP-09 Services contact list
- Sub-features: list of third-party/partner contacts shown in the app. Video: also used as a link list for programs and online registration (opens the browser); each entry offers website, email or call actions.
- Settings / options: contact name, email, phone, website URL; "save items across the branches".
- Rules / limits: maximum 10 contacts.
- User story: As a facility, I want to list partners and trainers with contact details, so that members can reach related services.
- Actors: administrator, member.
- UI generation: n-a.
- Priority: P2
- Evidence: https://support.ezfacility.com/hc/en-us/articles/29244308148635-Services-Tab-MemberMe-Branded-App, https://www.youtube.com/watch?v=iMeRIT504Ho (t=17:20), https://www.youtube.com/watch?v=uLNIb7JsjkM (t=13:20)

### APP-10 In-app feedback
- Sub-features: member submits opinions/suggestions/support requests (reported as anonymous by reviewers); emailed to configured recipients.
- Settings / options: recipient emails (comma-separated); "save to all branches". Video: the member picks one of four feedback types - classes/events/instructors; facility and equipment; the mobile app; anything else.
- Rules / limits: delivery is by email only; no in-product inbox described.
- User story: As a member, I want to send feedback from the app, so that the facility hears issues quickly.
- Actors: member, administrator.
- UI generation: n-a.
- Priority: P2
- Evidence: https://support.ezfacility.com/hc/en-us/articles/29244354753179-Feedback-Tab-MemberMe-Branded-App, https://support.ezfacility.com/hc/en-us/articles/29244419129627-Branded-App-Home-Screen-Layout-Configuration, https://apps.apple.com/us/app/memberme/id969248357, https://www.youtube.com/watch?v=uLNIb7JsjkM (t=17:27), https://www.youtube.com/watch?v=qn8y8rfi-kc (t=13:15)

### APP-11 Tell a friend (referral share)
- Sub-features: member shares the app with a pre-written message.
- Settings / options: message text; "save to all branches".
- Rules / limits: message is per location unless saved to all; no referral attribution described.
- User story: As a member, I want to invite a friend from the app, so that they can join.
- Actors: member, administrator.
- UI generation: n-a.
- Priority: P2
- Evidence: https://support.ezfacility.com/hc/en-us/articles/29244307886747-Tell-a-friend-tab-MemberMe-Branded-App, https://apps.apple.com/us/app/memberme/id969248357

### APP-12 Trial pass request form ("Try us")
- Sub-features: prospect form in the app; submission emailed to the facility.
- Settings / options: admin: trial terms & conditions text, registration recipient email, "save to all branches". Prospect fields: first name, last name, phone, email, preferred location, T&C acceptance.
- Rules / limits: the form grants nothing: staff must create the client and add the free membership/session manually. Video: on some shared-app installs the Try us and Tell a friend tiles are missing until vendor support switches them on.
- User story: As a prospect, I want to request a free trial from the app, so that I can try the facility.
- Actors: prospect, administrator.
- UI generation: n-a.
- Priority: P1
- Evidence: https://support.ezfacility.com/hc/en-us/articles/29194634692123-Try-us-feature-MemberMe-Branded-App, https://support.ezfacility.com/hc/en-us/articles/29244450573339-Branded-App-Home-Screen-Tiles-info, https://www.youtube.com/watch?v=uLNIb7JsjkM (t=43:06), https://www.youtube.com/watch?v=7yHNga6cY0g (t=16:29)

### APP-13 Favorites and personalised schedule
- Sub-features: favourite sessions, instructors and locations; tile showing next upcoming favourite class; "My Schedule+" which shows the general schedule until favourites exist. Video: schedule sortable by date/time, activity or instructor; a member can change or switch off favourites at any time.
- Settings / options: none admin-side beyond tile captions.
- Rules / limits: caption and tap target switch from schedule to favourites once favourites are set.
- User story: As a member, I want my usual classes surfaced first, so that rebooking is quick.
- Actors: member.
- UI generation: n-a.
- Priority: P1
- Evidence: https://support.ezfacility.com/hc/en-us/articles/29244419129627-Branded-App-Home-Screen-Layout-Configuration, https://support.ezfacility.com/hc/en-us/articles/29244421350555-Branded-App-Home-Screen-Labels-Captions-Dynamic-Text-and-Caption-Customizing, https://www.youtube.com/watch?v=oNHKhlv39qo (t=22:40), https://www.youtube.com/watch?v=lwC-tepoJ0I (t=26:36)

### APP-14 Announcements, promotions and gallery
- Sub-features: rotating announcement images optionally linked to a URL; home-screen image gallery; promotions/virtual coupons and offers delivered via push; photo/video galleries (2012 lineage). Video: staff bios with photos and a club info page (launch-era tour).
- Settings / options: announcement image + optional URL; gallery images. Video: announcement = image, free text beneath, optional link, optional valid-from/valid-to dates; its button reads 'Share' without a link and 'Open website' with one (2017 demos also show email and phone actions); gallery images have go-live and take-down dates and are per location.
- Rules / limits: promotion redemption/accept-and-schedule mechanics are only described in press material. Video: at most 11 announcements run at once (2025 demo); expired ones leave the app; members can share an announcement; league and program schedules are not part of the class schedule and are surfaced through pasted links in announcements, services or news.
- User story: As a marketer, I want visual promotions in the app, so that offers are noticed.
- Actors: administrator, member.
- UI generation: n-a.
- Priority: P1
- Evidence: https://support.ezfacility.com/hc/en-us/articles/29244419129627-Branded-App-Home-Screen-Layout-Configuration, https://www.ezfacility.com/features/branded-mobile-app/, https://www.ezfacility.com/press-news/press-releases/ezfacility-introduces-new-memberme-mobile-app, https://apps.apple.com/us/app/memberme/id969248357, https://www.youtube.com/watch?v=uLNIb7JsjkM (t=09:13), https://www.youtube.com/watch?v=7yHNga6cY0g (t=02:02, t=18:31), https://www.youtube.com/watch?v=iMeRIT504Ho (t=10:10, t=40:52), https://www.youtube.com/watch?v=t85Pe_jL_h4 (t=17:25), https://www.youtube.com/watch?v=Zs-8tpgvadk (t=16:31), https://www.youtube.com/watch?v=lwC-tepoJ0I (t=19:29), https://www.youtube.com/watch?v=oYfiXax435c (t=00:40)

### APP-15 Social and device integrations
- Sub-features: social check-in/share via the member's own accounts; share a booking by email/Facebook; add booking to phone calendar; links to facility social pages; open another app or its store page.
- Settings / options: social URLs on the relevant tiles. Video: the social check-in post text and its link are set by the facility (e.g. pointing at a sign-up or booking page).
- Rules / limits: reviews report unreliable calendar sync and a Facebook button opening the user's own feed.
- User story: As a member, I want my booking in my phone calendar and shareable, so that I remember and bring friends.
- Actors: member.
- UI generation: n-a.
- Priority: P2
- Evidence: https://support.ezfacility.com/hc/en-us/articles/29244419129627-Branded-App-Home-Screen-Layout-Configuration, https://apps.apple.com/us/app/memberme/id969248357, https://www.ezfacility.com/blog/boost-client-conveniences-and-business-reach-with-memberme, https://www.youtube.com/watch?v=t85Pe_jL_h4 (t=23:34), https://www.youtube.com/watch?v=oNHKhlv39qo (t=29:46), https://www.youtube.com/watch?v=Zs-8tpgvadk (t=21:40)

### APP-16 Multi-location apps
- Sub-features: member switches location in one app; admin applies content settings to one or all locations; notifications addressed per location. Video: member picks a home club from a location drop-down; one super-admin console covers every location.
- Settings / options: Switch Locations tile; "save to all branches" on Try us, Tell a friend, Feedback, Services; location multi-select on notifications.
- Rules / limits: content is location-scoped by default. Video: one branded app per brand, with locations added to match the account's location count; the monthly fee is per location.
- User story: As a multi-site operator, I want one app covering all branches, so that members move between sites.
- Actors: administrator, member.
- UI generation: n-a.
- Priority: P1
- Evidence: https://support.ezfacility.com/hc/en-us/articles/29244419129627-Branded-App-Home-Screen-Layout-Configuration, https://support.ezfacility.com/hc/en-us/articles/29244337277083-Sending-Push-Notifications-MemberMe-Branded-App, https://support.ezfacility.com/hc/en-us/articles/29194634692123-Try-us-feature-MemberMe-Branded-App, https://support.ezfacility.com/hc/en-us/articles/29244354753179-Feedback-Tab-MemberMe-Branded-App, https://www.youtube.com/watch?v=oNHKhlv39qo (t=57:18), https://www.youtube.com/watch?v=5sm7eWzaQD4 (t=53:18), https://www.youtube.com/watch?v=qn8y8rfi-kc (t=23:31), https://www.youtube.com/watch?v=7yHNga6cY0g (t=25:40)

### APP-17 App engagement analytics
- Sub-features: dashboard of downloads, engagement, booking rates, in-app promotion results; per-notification analytics; reports on popular features.
- Settings / options: none documented. Video: in 2017-18 the analytics came from a third-party mobile analytics service (Flurry) - dashboards, time-range slicing, scheduled emailed reports, iOS vs Android split; metrics named in later talks: downloads, clicks per page, active users, concurrent sessions, session length.
- Rules / limits: metric definitions not published.
- User story: As an owner, I want to know whether members use the app, so that I can justify and tune it.
- Actors: owner.
- UI generation: n-a.
- Priority: P1
- Evidence: https://www.ezfacility.com/features/branded-mobile-app/, https://support.ezfacility.com/hc/en-us/articles/29244337277083-Sending-Push-Notifications-MemberMe-Branded-App, https://www.ezfacility.com/press-news/press-releases/ezfacility-introduces-new-memberme-mobile-app, https://www.youtube.com/watch?v=iMeRIT504Ho (t=12:12, t=34:43), https://www.youtube.com/watch?v=qn8y8rfi-kc (t=14:15), https://www.youtube.com/watch?v=3FOVNMAz2cE (t=34:47)

### APP-18 App schedule presentation controls
- Sub-features: reservation categories that group sessions in the app; hide full sessions; shared visible range; online description.
- Settings / options: Reservation Categories (create, assign sessions, rename labels) under Location Settings; Hide Full Sessions; Visible Range. Video: member-side schedule filters activity, resource, instructor and date; in 2017 the vendor configured the breakdown (by date, studio, instructor or discipline) with the customer.
- Rules / limits: categories shipped 2023-08-02. Video: rentals appear in the app schedule marked 'unavailable' when notice settings apply; a free calendar event shows when its reservation type has a category enabled and class size is at least 1; the schedule is read live from the core system, so cancellation and booking-range rules are the core ones.
- User story: As a member, I want the schedule grouped and uncluttered, so that I find a bookable class fast.
- Actors: administrator, member.
- UI generation: New (admin side).
- Priority: P1
- Evidence: https://support.ezfacility.com/hc/en-us/articles/17574439837467-August-2nd-2023-Release-Notes, https://support.ezfacility.com/hc/en-us/articles/4402427176219-How-to-Set-Up-Self-Service-Preferences, https://support.ezfacility.com/hc/en-us/articles/23181863135387-How-to-Change-Self-Service-Settings-for-Packages, https://www.youtube.com/watch?v=uLNIb7JsjkM (t=25:38, t=47:17), https://www.youtube.com/watch?v=qn8y8rfi-kc (t=06:06), https://www.youtube.com/watch?v=lwC-tepoJ0I (t=18:29)

### APP-19 In-app purchase and payment
- Sub-features: package-plan cart/checkout; stored card view (redacted) and update; pay balances.
- Settings / options: follows portal sale flags and card settings.
- Rules / limits: implemented over the self-service API realm (2024-06). Video: the spring-2025 demo says purchases (packages, memberships, anything else) open the self-service site in a browser inside the app; 2017-18 demos state no native payment at all (see unknowns conflict).
- User story: As a member, I want to buy a package and pay in the app, so that booking is not blocked.
- Actors: member.
- UI generation: n-a.
- Priority: P0
- Evidence: https://support.ezfacility.com/hc/en-us/articles/26750732215835-June-19th-2024-Release-Notes, https://support.ezfacility.com/hc/en-us/articles/26498179644187-June-5th-2024-Release-Notes, https://www.ezfacility.com/features/branded-mobile-app/, https://www.youtube.com/watch?v=uLNIb7JsjkM (t=44:08), https://www.youtube.com/watch?v=7yHNga6cY0g (t=21:34), https://www.youtube.com/watch?v=qn8y8rfi-kc (t=22:30), https://www.youtube.com/watch?v=iMeRIT504Ho (t=39:50)

## Reporting

Conventions: "Classic" = legacy admin UI (also called TMS), "New" = New EZFacility Experience (also called EZUI). Unless stated, every report has Generate, optional "Show Details" drill-down, export and print through the shared viewer (RPT-01). Cross-references such as BIL-19 point at features owned by other clusters.

### RPT-01 Report center (catalog, parameters, generate, drill-down, export, print)
- Sub-features: Reports menu grouped by report type with a one-line description and a View button per report; parameter form (date range on most, extra filters behind "More Options"); Generate Report; per-section/per-row "Show Details" expanders; export; print; Classic keeps a left navigation sidebar to jump between reports and a format selector plus export button; some reports open in a new tab; some run with no parameter form. Legacy 2012 interface refresh (video): hovering the Reports module shows recently opened reports, and the reports page gained a sidebar to jump to a section or open a report directly, with reports and admin pages made usable on tablets and phones.
- Settings / options: report groups observed: Financial, Marketing, Membership, Training, Point of Sale, Check-in, Time Clock, Lockers, Game Cards (leagues), per-group (Groups); export formats (New): Word, Excel, PowerPoint, PDF, TIFF, MHTML (web archive), CSV (comma delimited), XML file with report data, Data Feed; marketing names .csv, .pdf, .xlsx (a blog adds XML and Word); CSV is the vendor-recommended format for finance reports; print options: Page size, Page orientation; multi-select dropdown parameters (membership types etc.); period presets on some reports.
- Rules / limits: output is a static snapshot, the user must regenerate after data or filter changes; Reports menu visibility is permission-controlled per user; trainers running Trainer Performance, Trainer Schedule, Session Notes and Trainer Payroll/Commission see only their own data (fix 2024-01-17); the Generate button is disabled after click to stop duplicate runs (2025-04-09); report sections for add-on modules (e.g. Lockers) appear only when the module is purchased; shipped fixes: CSV column headers showed generic "textbox#" names on Revenue/Deposit (2023-08-31) and on a list of marketing and membership reports (2023-09-27), PDF logo overlapped data (2023-08-31), multi-select defaults in New (2024-02-15), start/end date display in New (2025-04-09), label "Sex" renamed "Gender" across reports (2024-05-08). Export list and "textbox#" artefact imply an SSRS-style viewer (inferred). Reports are not tailored per account: a request for a custom report goes to support and is treated as a product-development suggestion (training webinar).
- User story: As an owner, I want one place to pick any report, set filters, drill into rows and export, so that I can answer operational and financial questions without a data team.
- Actors: owner/admin, billing staff, managers, trainers (scoped), any user with report permission.
- UI generation: both (Classic: sidebar + format selector; New: type menu + icons)
- Priority: P0
- Evidence: https://support.ezfacility.com/hc/en-us/articles/27902451074715-How-to-Access-and-Download-a-Report, https://support.ezfacility.com/hc/en-us/articles/20993523042587-Chalk-Talk-December-2023-Top-5-Financial-Reports-in-EZFacility, https://support.ezfacility.com/hc/en-us/articles/18408526583067-August-31st-2023-Release-Notes, https://support.ezfacility.com/hc/en-us/articles/19132331777307-September-27th-2023-Release-Notes, https://support.ezfacility.com/hc/en-us/articles/22122496577179-January-17th-2024-Release-Notes, https://support.ezfacility.com/hc/en-us/articles/22968789591963-February-15th-2024-Release-Notes, https://support.ezfacility.com/hc/en-us/articles/25551222201627-May-8th-2024-Release-Notes, https://support.ezfacility.com/hc/en-us/articles/36516560976539-April-9th-2025-Release-Notes, https://www.ezfacility.com/features/billing-payments, https://www.ezfacility.com/benefits, https://www.ezfacility.com/blog/make-the-most-of-ezfacility-management-software-features, https://www.ezfacility.com/blog/benefits-of-using-sports-management-software, https://www.ezfacility.com/blog/how-to-succeed-with-ezfacility, https://www.youtube.com/watch?v=PBbm0V08fts (t=01:10), https://www.youtube.com/watch?v=PBbm0V08fts (t=02:40), https://www.youtube.com/watch?v=a7-8-cHwB8Y (t=52:20)

### RPT-02 Management Dashboard
- Sub-features: single-page summary with five sections: Billing Summary, Deposits Summary, Membership Count Summary, Attendance Summary, Rental Summary; export with format select; sidebar to other reports.
- Settings / options: Start Date; End Date; Revenue Goal (optional); Location (shown only to multi-location accounts). Billing Summary lines: Revenue Generated, Discounts, Taxes, Payments Applied, Net Deposits, Balance Due (as of end date), In Collections (as of end date). Deposits Summary per payment method: Received, Refunded, Net. Attendance Summary by attendance status (attended, rescheduled, etc.). Rental Summary: total rentals, rental hours.
- Rules / limits: Revenue/Discounts/Taxes keyed to billing-item Revenue Date; Payments Applied and Net Deposits keyed to Payment Date; Net Deposits include unapplied payments; Balance Due counts invoices due on or before end date. Marketing also claims real-time dashboards and a central cross-location dashboard (no help-center detail beyond the Location filter).
- User story: As an owner, I want a period snapshot of revenue, cash, members, attendance and rentals against a goal, so that I can review the business weekly.
- Actors: owner/admin, multi-site operator.
- UI generation: both (article not UI-specific)
- Priority: P1
- Evidence: https://support.ezfacility.com/hc/en-us/articles/4403486157595-Management-Dashboard, https://www.ezfacility.com/features/billing-payments, https://www.ezfacility.com/benefits, https://www.ezfacility.com/ezfacility-comparison, https://www.ezfacility.com/blog/how-to-succeed-with-ezfacility

### RPT-03 Revenue Report (revenue summary vs goal)
- Sub-features: bar graph Revenue vs Payments Applied; Revenue by Category; Taxes Generated; Payment Breakdown (applied / not applied / refunded); Discounts by Category; Show Details per section; export; print. A related "Report by Revenue" gained Revenue Category and Rental Type columns (2023-08-02).
- Settings / options: Start Date; End Date; Revenue Goal (optional); Filter by Revenue Category; More Options; table title "Revenue By Category (Discounts are included. Taxes are excluded)".
- Rules / limits: revenue, tax and discount sections use each billing item's Revenue Date; Payment Breakdown uses Payment Date; invoice dates and payment schedules are ignored; a payment received outside the range but applied to in-range revenue is not listed; Taxes Generated is empty unless a tax rate is configured; the two bars are equal when all revenue is collected; payment method Bank Transfer is reportable (2023-06-28); credit card type captured from manual payments and auto-pay jobs (fix 2023-08-31); category filter totals corrected (2023-09-13). Payment remarks are printed in the payments section (second page) of the revenue report, which is where staff review recorded cancellation reasons (billing webinar).
- User story: As an owner, I want earned revenue by category for a period compared with a target and with cash applied, so that I can see whether we are on plan.
- Actors: owner/admin with report access.
- UI generation: both (same parameters; New adds disc/print icons)
- Priority: P0
- Evidence: https://support.ezfacility.com/hc/en-us/articles/4403486152219-Using-the-Revenue-Report-in-EZFacility, https://support.ezfacility.com/hc/en-us/articles/23474534910619-Using-the-Revenue-Report-in-EZFacility, https://support.ezfacility.com/hc/en-us/articles/34200838065179-Using-the-Revenue-Report-in-EZFacility, https://support.ezfacility.com/hc/en-us/articles/20993523042587-Chalk-Talk-December-2023-Top-5-Financial-Reports-in-EZFacility, https://support.ezfacility.com/hc/en-us/articles/16731304236571-June-28th-2023-Release-Notes, https://support.ezfacility.com/hc/en-us/articles/17574439837467-August-2nd-2023-Release-Notes, https://support.ezfacility.com/hc/en-us/articles/18408526583067-August-31st-2023-Release-Notes, https://support.ezfacility.com/hc/en-us/articles/18741009680795-September-13th-2023-Release-Notes, https://www.youtube.com/watch?v=iR4MVBspNlQ (t=50:26)

### RPT-04 Deposits Report (cash by payment method)
- Sub-features: totals per payment method (deposits, refunds, net); Show Details per method group; voided payments listed and flagged; export. Companion processor-payout report (Pyxis Disbursements, see PAY-16) is matched to this report by transaction id.
- Settings / options: date range; More Options; detail columns: Payment Date, Client Name, Member Number, Payment Type, Comments, Collected By, Total Payment, Amount Applied, Amount Unused; Transaction ID (referenced 2024-03-27).
- Rules / limits: net = deposits minus refunds, and one article says the user must do that subtraction (conflict with the "net" column, see unknowns); voided = payments a user removed; Bank Transfer appears as a method (2023-06-28); duplicate payment-method rows fixed 2023-06-12; CSV headers fixed 2023-08-31. Trainer guidance (video): the Unused amount column is the way to spot money sitting on account.
- User story: As a bookkeeper, I want money received and refunded per payment method per day range, so that I can reconcile the bank statement.
- Actors: owner/admin, bookkeeper.
- UI generation: both
- Priority: P0
- Evidence: https://support.ezfacility.com/hc/en-us/articles/4403486188571-Deposits-Report, https://support.ezfacility.com/hc/en-us/articles/23474524859803-Deposits-Report, https://support.ezfacility.com/hc/en-us/articles/34200840681499-Deposits-Report, https://support.ezfacility.com/hc/en-us/articles/20993523042587-Chalk-Talk-December-2023-Top-5-Financial-Reports-in-EZFacility, https://support.ezfacility.com/hc/en-us/articles/16308423683355-June-12th-2023-Release-Notes, https://support.ezfacility.com/hc/en-us/articles/16731304236571-June-28th-2023-Release-Notes, https://support.ezfacility.com/hc/en-us/articles/18408526583067-August-31st-2023-Release-Notes, https://support.ezfacility.com/hc/en-us/articles/24225032928027-March-27th-2024-Release-Notes, https://support.ezfacility.com/hc/en-us/articles/24695840840603-April-10th-2024-Release-Notes, https://www.youtube.com/watch?v=iR4MVBspNlQ (t=19:35)

### RPT-05 Invoices Report
- Sub-features: list of every invoice (open and paid) created in a date range; export.
- Settings / options: Start Date; End Date; column "Organization" (company/business of the client) added 2023-04-18; other columns not published.
- Rules / limits: selection is by invoice creation date, not due date.
- User story: As billing staff, I want all invoices raised in a period, so that I can audit billing activity.
- Actors: admin, billing staff.
- UI generation: both
- Priority: P0
- Evidence: https://support.ezfacility.com/hc/en-us/articles/20961678104219-Invoices-Report, https://support.ezfacility.com/hc/en-us/articles/4403486256923-Invoices-Report, https://support.ezfacility.com/hc/en-us/articles/23474580662555-Invoices-Report, https://support.ezfacility.com/hc/en-us/articles/20993523042587-Chalk-Talk-December-2023-Top-5-Financial-Reports-in-EZFacility, https://support.ezfacility.com/hc/en-us/articles/14655161654811-April-18th-2023-Release-Notes

### RPT-06 Open Invoices by Customer (receivables)
- Sub-features: per-client outstanding invoices with days past due; Show Details lists the invoices and, for failed auto-pay, the decline reason; export.
- Settings / options: Report By: Due Date (uses payment schedule; recommended) / Invoice Date; start date (blank recommended); end date (today recommended); Invoices to Include: All Invoices / Auto Pay Only / Non-Auto Pay; Include clients reported for collections: Yes / No; Include fully paid invoices: Yes / No (No recommended); Include clients that are: Active / Deleted / Both; Sort by: Client Name / Invoice Balance / Invoice Due Date. Output columns: client name, home phone, total payment to date, amount paid, balance, on auto-pay, days past due.
- Rules / limits: payments made on or after the end date are ignored (as-of balance); "reported for collections" derives from client billing status In Collections; run to today with nothing owed returns empty. Release notes separately name an "Accounts Receivable" report in New (fix 2024-02-28; email link fix 2024-06-05), documented as BIL-19 with near-identical parameters; relationship between the two is unconfirmed. Payment remarks also show in this report's payments section (billing webinar).
- User story: As an owner, I want everyone who owes money, how late, and why auto-pay failed, so that I can collect.
- Actors: owner/admin, billing staff.
- UI generation: both
- Priority: P0
- Evidence: https://support.ezfacility.com/hc/en-us/articles/4403486300315-Open-Invoices-By-Customer-Report, https://support.ezfacility.com/hc/en-us/articles/23474526075419-Open-Invoices-By-Customer-Report, https://support.ezfacility.com/hc/en-us/articles/34200876269083-Open-Invoices-By-Customer-Report, https://support.ezfacility.com/hc/en-us/articles/20993523042587-Chalk-Talk-December-2023-Top-5-Financial-Reports-in-EZFacility, https://support.ezfacility.com/hc/en-us/articles/23328878237467-February-28th-2024-Release-Notes, https://support.ezfacility.com/hc/en-us/articles/26498179644187-June-5th-2024-Release-Notes, https://www.youtube.com/watch?v=iR4MVBspNlQ (t=50:26)

### RPT-07 Unapplied Payments by Customer (client liability)
- Sub-features: per-client money on account versus unpaid invoices; export.
- Settings / options: columns Unapplied Payments, Unpaid Invoices, Liability; no date filter documented.
- Rules / limits: Unapplied = payments neither applied to invoices nor refunded; Unpaid Invoices = remaining amount on all invoices regardless of invoice date or schedule; Liability = Unapplied minus Unpaid (positive = facility holds client money, negative = client owes). Follow-up action is manual (apply or refund).
- User story: As an accountant, I want each client's credit-on-account netted against what they owe, so that I can clear balances and state liabilities.
- Actors: admin, accountant.
- UI generation: both
- Priority: P1
- Evidence: https://support.ezfacility.com/hc/en-us/articles/20961746603803-Unapplied-Payments-by-Customer, https://support.ezfacility.com/hc/en-us/articles/4403486203035-Unapplied-Payments-by-Customer, https://support.ezfacility.com/hc/en-us/articles/23474559304859-Unapplied-Payments-by-Customer, https://support.ezfacility.com/hc/en-us/articles/20993523042587-Chalk-Talk-December-2023-Top-5-Financial-Reports-in-EZFacility

### RPT-08 Income/Balances by Customer
- Sub-features: invoices dated in range grouped by client with total paid and remaining balance; Show Details expands the invoices.
- Settings / options: Start Date; End Date (either blank = open-ended).
- Rules / limits: keyed to invoice date (contrast RPT-03 which ignores invoice dates).
- User story: As an owner, I want income and balance per client for a period, so that I can see my largest and most indebted accounts.
- Actors: admin.
- UI generation: both (article not UI-specific; only an older-style article exists)
- Priority: P1
- Evidence: https://support.ezfacility.com/hc/en-us/articles/4403486237979-Income-Balances-by-Customer

### RPT-09 Underpaid Items
- Sub-features: billing items not fully paid as of a date; Show Details; export.
- Settings / options: "Show items that were not fully paid as of" (date); "Include items not on invoice?" (i.e. still in the cart); "Include items on paid-to-date invoices?"; "Include items on future invoices?".
- Rules / limits: items with a revenue date after the as-of date are excluded; payments after the as-of date are not counted; paid-to-date = No drops a whole invoice that is current against its schedule even if individual items are underpaid; future = No drops invoices dated after the as-of date.
- User story: As billing staff, I want item-level shortfalls as of a date, so that I can find revenue recognised but not collected.
- Actors: admin, billing staff.
- UI generation: both (article not UI-specific)
- Priority: P1
- Evidence: https://support.ezfacility.com/hc/en-us/articles/4403486278939-Underpaid-Items

### RPT-10 Accrued Session Revenue
- Sub-features: value of completed training sessions in a range.
- Settings / options: Start Date; End Date; Trainer.
- Rules / limits: session value = package price / number of sessions (e.g. 100 for 10 sessions gives 10 per completed session).
- User story: As an owner, I want earned training revenue by delivered sessions, so that prepaid packages are recognised as they are used.
- Actors: owner/admin.
- UI generation: both (article not UI-specific)
- Priority: P1
- Evidence: https://support.ezfacility.com/hc/en-us/articles/4403486169115-Accrued-Session-Revenue

### RPT-11 Membership Revenue by Month
- Sub-features: membership revenue across a chosen time frame, including future periods (scheduled dues).
- Settings / options: period dropdown: current month (default), This Quarter, This Year, Next Month, Next Quarter, Next Year, Rolling 1 Year, Custom; sits in the "Membership Reports" group.
- Rules / limits: failed to generate in one of the two UIs until 2023-08-16; CSV headers fixed 2023-09-27. Related revenue-recognition reports (Deferred Membership Revenue, Un-accrued Membership Revenue) are owned by the Memberships cluster.
- User story: As an owner, I want membership revenue per month looking back and forward, so that I can forecast recurring income.
- Actors: owner/admin.
- UI generation: both (documented in Classic; generation fixed for both)
- Priority: P1
- Evidence: https://support.ezfacility.com/hc/en-us/articles/4404308369179-Viewing-Membership-Revenue-by-Month-Report-in-EZFacility-Classic, https://support.ezfacility.com/hc/en-us/articles/17981009155995-August-16th-2023-Release-Notes, https://support.ezfacility.com/hc/en-us/articles/19132331777307-September-27th-2023-Release-Notes

### RPT-12 Memberships by Status
- Sub-features: contracts grouped by current status; Show Details; export.
- Settings / options: "Include each member who shares another's contract?" Yes / No; "Include expired contracts?" Yes / No; Membership Mode; Membership Type(s) (multi-select). Video adds: an option to include billing details and a way to show the membership contract; statuses counted: Active, Cancelled, Frozen, Pending, Suspended.
- Rules / limits: New UI ignored selected membership types until 2024-06-05; status and mode value lists are not published in this cluster's material. Trainer calls it the best report for exporting or printing the active-member list; cancelled counts are historical and do not change (video).
- User story: As a manager, I want a head-count of contracts by status, so that I know active, frozen and lapsed numbers.
- Actors: owner/admin.
- UI generation: both
- Priority: P0
- Evidence: https://support.ezfacility.com/hc/en-us/articles/4404308209819-Membership-By-Status-Report-in-EZFacility-Classic, https://support.ezfacility.com/hc/en-us/articles/26498179644187-June-5th-2024-Release-Notes, https://www.youtube.com/watch?v=a7-8-cHwB8Y (t=41:59)

### RPT-13 Membership Actions
- Sub-features: count of contracts cancelled, frozen or suspended in a date range; export.
- Settings / options: Start Date; End Date; membership action: Cancelled / Frozen / Suspended; membership type; "Include which cancellations" (shown only when action = Cancelled; option values not published). Video adds: a "run by" basis (start date / action date / end date / both; exact labels uncertain from captions) and a cancellation-reason filter when the action is Cancelled.
- Rules / limits: only meaningful with the Advanced Memberships add-on module. Shows actions that fell inside the range, not a full history; used to follow up frozen members; in one demo the Suspended option appeared to return cancellation numbers (flagged by the presenter as a possible defect).
- User story: As a manager, I want to see how many members froze, suspended or cancelled in a period, so that I can track churn drivers.
- Actors: owner/admin.
- UI generation: both (documented Classic; New multi-select fix 2024-02-15)
- Priority: P1
- Evidence: https://support.ezfacility.com/hc/en-us/articles/4404308201243-Membership-Actions, https://support.ezfacility.com/hc/en-us/articles/22968789591963-February-15th-2024-Release-Notes, https://www.youtube.com/watch?v=a7-8-cHwB8Y (t=43:01), https://www.youtube.com/watch?v=pYlicKb3lng (t=06:50)

### RPT-14 Membership Attrition
- Sub-features: month-by-month attrition table with period average and total.
- Settings / options: last month; number of months; "Count Frozen members as Active?"; "Count Suspended members as Active?"; "Include Deleted Clients?"; membership type(s). Output columns: Memberships At Start, Memberships Lost, Attrition, Average, Total For Period.
- Rules / limits: At Start = contracts whose latest status before month start was Active (plus Frozen/Suspended if opted in); Lost = status changed in the month to Canceled with reason Voluntary Cancel, or to Expired without a renewal set up; Average = total losses / sum of start counts; Total For Period = losses as a percentage of the average start count, comparable only across equal-length periods; cancel reasons Upgrade, Downgrade, Administrative Error, Other Modification are not losses (inferred from the definition). Requires status history with reasons.
- User story: As an owner, I want a consistent monthly churn rate, so that I can compare retention across periods.
- Actors: owner/admin.
- UI generation: both (documented Classic; New fix 2024-02-15; CSV fix 2023-09-27)
- Priority: P1
- Evidence: https://support.ezfacility.com/hc/en-us/articles/4404308366619-Membership-Attrition-Report-in-EZFacility-Classic, https://support.ezfacility.com/hc/en-us/articles/19132331777307-September-27th-2023-Release-Notes, https://support.ezfacility.com/hc/en-us/articles/22968789591963-February-15th-2024-Release-Notes

### RPT-15 Expiring Memberships
- Sub-features: contracts expiring in a date range, usable as a renewal call/email list.
- Settings / options: Start Date; End Date; Membership Type; "Include Auto-Renewing contracts"; "Include contracts even if a newer contract exists".
- Rules / limits: by default an expiring contract is hidden when its owner holds a contract with a later expiration; if types are selected only newer contracts of those types suppress it; newer contracts owned by someone else and merely shared with the owner never suppress it. Vendor tip: send renewal notices through Email with the membership filter rather than from the report.
- User story: As front-desk staff, I want members whose contract ends soon and who have not already renewed, so that I can prompt renewal.
- Actors: owner/admin, front desk.
- UI generation: both (documented Classic; New fix 2024-02-15)
- Priority: P1
- Evidence: https://support.ezfacility.com/hc/en-us/articles/4404314535195-View-the-Expiring-Memberships-Report-in-EZFacility-Classic, https://support.ezfacility.com/hc/en-us/articles/22968789591963-February-15th-2024-Release-Notes

### RPT-16 Membership Referrals
- Sub-features: membership sales attributed to a referring client, with total revenue per referrer; Show Details lists plans sold.
- Settings / options: date range; capture fields on contract sale: "Referred by" (client search + Add) and Sold By.
- Rules / limits: tracks client referrals only; staff sales attribution belongs to the Trainer Payroll/Commission and Salesperson Commission reports (STF-09, STF-10).
- User story: As an owner, I want revenue generated by each referring member, so that I can reward referrals.
- Actors: owner/admin.
- UI generation: Classic (documented); New not confirmed
- Priority: P1
- Evidence: https://support.ezfacility.com/hc/en-us/articles/4404314692507-Using-the-Membership-Referral-Report-in-EZFacility-Classic

### RPT-17 Low Usage Check-In
- Sub-features: clients whose check-in count in a range falls between a minimum and a maximum (at-risk list). Named "Client Low Usage Check-in History" in release notes.
- Settings / options: Start Date; End Date; minimum check-ins; maximum check-ins; Client Category; Membership Status; Membership Type(s).
- Rules / limits: date range and other filters were ignored until fixed 2024-03-27; marketing positions this style of report as churn early-warning.
- User story: As a manager, I want members who barely visit, so that I can re-engage them before they cancel.
- Actors: owner/admin, marketing staff.
- UI generation: both
- Priority: P1
- Evidence: https://support.ezfacility.com/hc/en-us/articles/4404308202907-View-the-Low-Usage-Check-In-Report-in-EZFacility-Classic, https://support.ezfacility.com/hc/en-us/articles/19132331777307-September-27th-2023-Release-Notes, https://support.ezfacility.com/hc/en-us/articles/22968789591963-February-15th-2024-Release-Notes, https://support.ezfacility.com/hc/en-us/articles/24225032928027-March-27th-2024-Release-Notes, https://www.ezfacility.com/benefits, https://www.ezfacility.com/blog/use-your-computer-software-to-increase-revenue

### RPT-18 Client Activity Items report
- Sub-features: CRM-style list of client activities and staff tasks; also opened from the "You have (x) Active Tasks" indicator in the header. Underlying task feature is CLI-11.
- Settings / options: activity type: Phone / Email / Task / Other / Customer Service Rep.; activity subject (configured list); status: Not Started / In Progress / Completed / Waiting / Deferred; latest due date (blank = all); user; Location; sort order ascending / descending.
- Rules / limits: none published.
- User story: As a manager, I want open follow-ups by staff member and due date, so that nothing owed to a client is dropped.
- Actors: admin, sales/front-desk staff.
- UI generation: Classic (inferred)
- Priority: P1
- Evidence: https://support.ezfacility.com/hc/en-us/articles/4404314530331-Client-Activity-Items-Report

### RPT-19 Contact Report and Client Demographics
- Sub-features: (a) Contact Report: contact details for all clients, no parameters; (b) Client Demographics: demographic breakdown (age/gender per marketing).
- Settings / options: Client Demographics: "Last session after" date (blank = all clients).
- Rules / limits: "Last session after" considers only package-based bookings, not rentals or reserved slots; clearing the date wrongly triggered validation until 2023-11-08; CSV headers fixed 2023-09-27.
- User story: As a marketer, I want a contact export and a demographic profile of active clients, so that I can target campaigns.
- Actors: admin, marketing staff.
- UI generation: both (documented Classic-style; CSV fixes apply to both)
- Priority: P1
- Evidence: https://support.ezfacility.com/hc/en-us/articles/4404308546459-Contact-Report, https://support.ezfacility.com/hc/en-us/articles/4404308543515-Client-Demographics, https://support.ezfacility.com/hc/en-us/articles/19132331777307-September-27th-2023-Release-Notes, https://support.ezfacility.com/hc/en-us/articles/20241459046683-November-8th-2023-Release-Notes, https://www.ezfacility.com/blog/targeted-marketing-campaigns-with-ezfacility

### RPT-20 Client Referrals (lead source)
- Sub-features: how new clients heard of the facility in a date range; Show Details.
- Settings / options: Start Date; End Date; grouping toggle: by referral source (default) / "Don't group by source" which switches to referral category.
- Rules / limits: source and category are two distinct client attributes (inferred).
- User story: As an owner, I want sign-ups by marketing source, so that I can judge channel spend.
- Actors: admin, marketing staff.
- UI generation: both (documented Classic-style)
- Priority: P1
- Evidence: https://support.ezfacility.com/hc/en-us/articles/4404308535707-Client-Referrals, https://www.ezfacility.com/features/billing-payments

### RPT-21 Attendance Report and Attendance Overview
- Sub-features: (a) Attendance Report: session attendance rows; (b) Attendance Overview: attendance by class and instructor, with attendee names appended (can run to several pages).
- Settings / options: Attendance Report: Start Date; End Date; attendance status(es) to include; package type to include (described as reservation type). Attendance Overview: Start Date; End Date; Time Range; trainer; class type (reservation type).
- Rules / limits: attendance status list is tenant data owned by scheduling; the package-type vs reservation-type wording is inconsistent in the source.
- User story: As a program manager, I want attendance by class, instructor and status, so that I can spot under-performing classes and no-show patterns.
- Actors: admin, program manager.
- UI generation: both (documented Classic-style)
- Priority: P0
- Evidence: https://support.ezfacility.com/hc/en-us/articles/4404308549787-Attendance-Report, https://support.ezfacility.com/hc/en-us/articles/4404308570011-Attendance-Overview-Report

### RPT-22 Unused Session Value (prepaid session liability)
- Sub-features: monetary value of purchased-but-unused package sessions; Show Details.
- Settings / options: "Ignore Sessions Booked After" (date; later sessions count as unused whatever their attendance, for back-dated reporting); "Which Sessions Are Used?" (choice of attendance statuses that consume a session); "Ignore Expired Packages?" (date, or today).
- Rules / limits: without the ignore-expired option only packages set to "Lock" outside their date range are excluded, since other expired packages remain usable; CSV headers fixed 2023-09-27.
- User story: As an accountant, I want the value of sessions still owed to clients as of a date, so that I can state deferred revenue.
- Actors: admin, accountant.
- UI generation: both (documented Classic-style)
- Priority: P1
- Evidence: https://support.ezfacility.com/hc/en-us/articles/4404308527131-Unused-Session-Value, https://support.ezfacility.com/hc/en-us/articles/19132331777307-September-27th-2023-Release-Notes

### RPT-23 Package pipeline reports (Client Package Summary, Expiring Packages, Renewal Candidates)
- Sub-features: (a) Client Package Summary: all open packages per client; (b) Expiring Packages: packages whose expiration falls in a window; (c) Renewal Candidates: clients whose remaining sessions fall in a range.
- Settings / options: Package Summary: filter by client's default trainer(s) (only matches clients that have one), "Include Deleted Resources". Expiring Packages: Earliest Expiration Date, Latest Expiration Date, trainer, reservation type. Renewal Candidates: Maximum and Minimum sessions remaining, trainer, reservation type, "Exclude clients whose most recent booked session is before" (date, optional), Filter by Client Category.
- Rules / limits: Renewal Candidates excludes package types whose total remaining is 0; CSV headers for Package Summary fixed 2023-09-27.
- User story: As a trainer or manager, I want clients about to run out of sessions or time, so that I can sell the renewal before they lapse.
- Actors: admin, trainers.
- UI generation: both (documented Classic-style)
- Priority: P1
- Evidence: https://support.ezfacility.com/hc/en-us/articles/4404308533019-Client-Package-Summary, https://support.ezfacility.com/hc/en-us/articles/4404308572827-Expiring-Packages, https://support.ezfacility.com/hc/en-us/articles/4404314851355-Renewal-Candidates, https://support.ezfacility.com/hc/en-us/articles/19132331777307-September-27th-2023-Release-Notes, https://www.ezfacility.com/benefits

### RPT-24 Trial Conversions
- Sub-features: conversion of complimentary (trial) packages into paid packages.
- Settings / options: Start Date; End Date; trainer; reservation type.
- Rules / limits: definition of "converted" (window, same reservation type or any paid package) is not published.
- User story: As an owner, I want the trial-to-paid rate per trainer, so that I can coach sales follow-up.
- Actors: owner/admin.
- UI generation: both (documented Classic-style; CSV fix 2023-09-27)
- Priority: P1
- Evidence: https://support.ezfacility.com/hc/en-us/articles/4404308559771-Trial-Conversions, https://support.ezfacility.com/hc/en-us/articles/19132331777307-September-27th-2023-Release-Notes

### RPT-25 Client Retention (two-period comparison)
- Sub-features: per trainer, distinct clients with at least one scheduled session in each of two periods and the percentage present in both; "Show clients" expander.
- Settings / options: Earlier Time Period (Period 1); Later Time Period (Period 2); reservation type; "Include complimentary sessions?" Yes / No (default No).
- Rules / limits: counts scheduled sessions, not attended ones.
- User story: As an owner, I want each trainer's client carry-over between two periods, so that I can measure retention by coach.
- Actors: owner/admin.
- UI generation: both (documented Classic-style)
- Priority: P1
- Evidence: https://support.ezfacility.com/hc/en-us/articles/4404308575643-Client-Retention-Report

### RPT-26 Non-training Clients (lapsed list)
- Sub-features: clients with nothing scheduled after a date.
- Settings / options: "Show clients not scheduled after" (date); "Show clients for this trainer" (matches the client's default trainer only); "Show clients in this category"; "Show clients who have never been scheduled?" Yes / No; "Show clients who have no packages?" Yes / No; "Ignore packages with no remaining sessions?" Yes / No.
- Rules / limits: trainer filter does not look at who actually delivered sessions.
- User story: As a trainer, I want clients who stopped booking, so that I can win them back.
- Actors: admin, trainers.
- UI generation: both (documented Classic-style)
- Priority: P1
- Evidence: https://support.ezfacility.com/hc/en-us/articles/4404308531099-Non-training-Clients

### RPT-27 Per-group roster report
- Sub-features: report launched from a group's page listing its registrants; New lets the user pick the fields and sort order before export; Classic offers Show Details. New-UI demo (video): the parent group's Generate Report lists each team's members with amount paid and balance remaining, sortable (default last name), with column filters, export and print.
- Settings / options: Classic: action dropdown "Generate Report" + Go; New: group menu > Generate Report, Sort Order, field picker, export format.
- Rules / limits: opens in a new tab/window; only active groups are listed by default; export format list not published.
- User story: As a program coordinator, I want a roster for one class/camp with the columns I choose, so that I can hand instructors an attendance sheet.
- Actors: admin, front desk.
- UI generation: both (New adds field/sort selection)
- Priority: P1
- Evidence: https://support.ezfacility.com/hc/en-us/articles/4404924765339-How-to-Generate-a-Report-for-Groups, https://support.ezfacility.com/hc/en-us/articles/4415445452059-How-to-Generate-a-Report-for-Groups, https://www.youtube.com/watch?v=VuUR1Y9bhjQ (t=46:04)

### RPT-28 Group Waitlists
- Sub-features: everyone waitlisted across all active groups and sub-groups with their group; no parameters; export.
- Settings / options: "Show/Hide Medical Conditions" toggle (Classic); New path Reports > Marketing > Group Waitlists.
- Rules / limits: exposes client medical conditions, so needs permission care in our design (inferred).
- User story: As a coordinator, I want all waitlists in one list, so that I can decide where to add capacity.
- Actors: admin, program coordinator.
- UI generation: both
- Priority: P1
- Evidence: https://support.ezfacility.com/hc/en-us/articles/4404314883483-Group-Waitlists, https://support.ezfacility.com/hc/en-us/articles/23857919227035-How-to-Run-a-Waitlist-Report-for-Groups

### RPT-29 Email Campaign History (delivery analytics)
- Sub-features: list of sent campaigns with audience counts; per-campaign detail with chart (hide/show) and per-address event log filterable by event type.
- Settings / options: search by From Address, Subject, Date Sent. List columns: Clients Attempted, Duplicates, Empty, Invalid, Blacklisted, Sent. Detail metrics and event types: Delivered, Open, Click, Bounce, Dropped, Spam Report.
- Rules / limits: detail retained only for campaigns sent in the last 45 days; one message can carry several events; Dropped means the address was already on the blacklist; spam and bounce suppression lists were unified 2024-05-23 so spam-reported addresses are treated like bounces. Marketing claims real-time open/click analytics for the newer email platform.
- User story: As a marketer, I want delivery, open and click results per campaign and per address, so that I can clean lists and judge content.
- Actors: admin, marketing staff.
- UI generation: Classic (documented); New/Advanced Email Campaigns analytics not documented here
- Priority: P1
- Evidence: https://support.ezfacility.com/hc/en-us/articles/4405144431003-The-Email-Campaign-History-Report-in-EZFacility-Classic, https://support.ezfacility.com/hc/en-us/articles/25985296561179-May-23rd-2024-Release-Note

### RPT-30 POS sales reports (all sales, by employee, category, supplier, brand, coupon)
- Sub-features: All Sales; Sales By Employee; Sales By Category; Product Sales By Supplier; Product Sales By Brand; Sales by Coupon; each with a details expander ("Show Order Details" / "Show Details") and export.
- Settings / options: Start Date; End Date (all); All Sales output mode: "Normal, for printing" / "Simplified, for exporting"; employee selector (By Employee); Sales By Category columns include Buying Price (per unit) and Profit Margin (total across units of the item).
- Rules / limits: employee attribution = the user logged in when the transaction was processed; the supplier article describes one supplier but lists no supplier selector; the brand article has no body (grouping inferred from title); Perkville points and similar loyalty rules exclude POS. See POS-11 and POS-22 for the sales-side features.
- User story: As a retail manager, I want sales and margin by product dimension and by cashier, so that I can manage stock, staff and promotions.
- Actors: owner/admin.
- UI generation: Classic (documented); New POS reporting not documented in this bundle
- Priority: P0
- Evidence: https://support.ezfacility.com/hc/en-us/articles/34418979987611-All-Sales-Report, https://support.ezfacility.com/hc/en-us/articles/34419051390875-Sales-By-Employee, https://support.ezfacility.com/hc/en-us/articles/34419055387547-Sales-By-Category, https://support.ezfacility.com/hc/en-us/articles/34419054829979-Product-Sales-By-Supplier, https://support.ezfacility.com/hc/en-us/articles/34419046220827-Product-Sales-By-Brand, https://support.ezfacility.com/hc/en-us/articles/34419042530587-Sales-by-Coupon, https://www.ezfacility.com/features/billing-payments

### RPT-31 Order Returns/Refunds report
- Sub-features: POS returns and refunds in a date range; "Show Refund Details".
- Settings / options: Start Date; End Date.
- Rules / limits: none published.
- User story: As an owner, I want every POS refund in a period, so that I can audit shrinkage and staff behaviour.
- Actors: owner/admin.
- UI generation: Classic (documented)
- Priority: P1
- Evidence: https://support.ezfacility.com/hc/en-us/articles/34419017128987-Order-Returns-Refunds

### RPT-32 Daily Register Report (till reconciliation)
- Sub-features: per-register totals of sales, money collected and refunds; "Show Details" and "Show Refund Details".
- Settings / options: register selector; Start Date; End Date.
- Rules / limits: scoped to one register per run; registers of connected locations became switchable in POS on 2023-09-13.
- User story: As a cashier supervisor, I want what a till should contain for a shift or day, so that I can count the drawer against it.
- Actors: owner/admin, supervisor.
- UI generation: Classic (documented)
- Priority: P0
- Evidence: https://support.ezfacility.com/hc/en-us/articles/34419021121051-Daily-Register-Report, https://support.ezfacility.com/hc/en-us/articles/18741009680795-September-13th-2023-Release-Notes

### RPT-33 Inventory reports (All Inventory, Re-order)
- Sub-features: (a) All Inventory: every product with stock; (b) Inventory Re-order: products at or below their reorder level.
- Settings / options: none (both run without filters).
- Rules / limits: depends on product Reorder Level; a level of -1 excludes the product from the re-order report.
- User story: As a retail manager, I want current stock and what to reorder, so that shelves do not run empty.
- Actors: owner/admin.
- UI generation: Classic (documented)
- Priority: P1
- Evidence: https://support.ezfacility.com/hc/en-us/articles/34418975239707-All-Inventory-Report, https://support.ezfacility.com/hc/en-us/articles/34419009666459-Inventory-Re-order-Report

### RPT-34 Equipment rental reports (All Equipment Inventory, Checked-Out Equipment)
- Sub-features: (a) all equipment set up for rental; (b) equipment currently checked out.
- Settings / options: none published.
- Rules / limits: marketing mentions late fees and replacement costs tracked through inventory reports (no help-center detail).
- User story: As front-desk staff, I want to know what rental gear exists and what is still out, so that I can chase returns.
- Actors: admin, front desk.
- UI generation: Classic (documented)
- Priority: P1
- Evidence: https://support.ezfacility.com/hc/en-us/articles/34419060229787-All-Equipment-Inventory-in-EZFacility-Classic, https://support.ezfacility.com/hc/en-us/articles/34419089287067-View-the-Checked-Out-Equipment-in-EZFacility-Classic

### RPT-35 Locker reports (Expiring Lockers, Assigned Lockers)
- Sub-features: (a) Expiring Lockers in a date range; (b) Assigned Lockers: open, rented and expiring lockers with contract expiration and renter contact details.
- Settings / options: Expiring: Start Date, End Date. Assigned: locker room dropdown (all or one room).
- Rules / limits: "Lockers Reports" group is visible only when the Lockers add-on module is purchased.
- User story: As an attendant, I want which lockers are free, rented or about to lapse, so that I can assign and renew them.
- Actors: admin, front desk.
- UI generation: both (article not UI-specific)
- Priority: P2
- Evidence: https://support.ezfacility.com/hc/en-us/articles/4405044695835-Expiring-Lockers, https://support.ezfacility.com/hc/en-us/articles/4405051224987-Assigned-Lockers-Report

### RPT-36 League game cards (Manual Game Cards, Game Cards by Sport)
- Sub-features: printable score sheets: (a) ad-hoc card for any two teams from any league; (b) batch of cards for every scheduled game of a sport in a date range, one card per page with a page count.
- Settings / options: Manual: Home team, Away team, game date, game time. By Sport: Sport, start date, end date. Export Excel or PDF; direct print.
- Rules / limits: batch mode auto-fills from existing games.
- User story: As a scorekeeper, I want pre-filled game cards for tonight's games, so that officials can record results on paper.
- Actors: league admin, scorekeeper.
- UI generation: n-a (EZLeagues admin)
- Priority: P1
- Evidence: https://support.ezfacility.com/hc/en-us/articles/4405044263835-How-to-Print-Manual-Game-Cards, https://support.ezfacility.com/hc/en-us/articles/4405044293147-How-to-Print-Multiple-Game-Cards, https://www.ezfacility.com/features/league-scheduling-management

### RPT-37 Time Clock report
- Sub-features: staff clock-in/out entries for a date range; export or print. Manager-side entry editing is STF-08.
- Settings / options: start date; end date; path Reports > Time Clock.
- Rules / limits: a defect let some users open other employees' time clocks in New (fixed 2023-04-18); entries editable again from 2024-01-31; marketing calls these time-based payroll reports.
- User story: As a payroll admin, I want hours worked per employee for a pay period, so that I can run payroll.
- Actors: owner/admin, payroll.
- UI generation: New (documented); Classic equivalent not in this bundle
- Priority: P0
- Evidence: https://support.ezfacility.com/hc/en-us/articles/27905516067227-How-to-Use-the-Time-Clock-Report, https://support.ezfacility.com/hc/en-us/articles/14655161654811-April-18th-2023-Release-Notes, https://support.ezfacility.com/hc/en-us/articles/22529640450203-January-31-2024-Release-Notes, https://www.ezfacility.com/features/staff-access-management

### RPT-38 Branded-app analytics
- Sub-features: "Application Analytics" dashboard for the white-label app across iOS and Android: Application Downloads; Users Activity over time (Active 1-day, 7-day, 28-day users); Total User Sessions (all vs engaged); Session Duration (daily average); Total Active Users per page; Total Views per page; per-platform screen lists.
- Settings / options: date range by calendar or presets plus an update button. Tracked screens (our names): splash, location switch, home, schedule, package selection, account, promotions/announcements, contact, favourites, notifications, member card (auto barcode), add member card (manual barcode), multiple barcodes.
- Rules / limits: available at chain level only (above an individual gym page); engaged session = app open longer than 10 seconds; each active-user metric counts distinct users in the window ending on the range's last day. Earlier MemberMe+ material mentions admin reports on downloads and popular features. Vendor webinars name the analytics provider as Flurry Analytics, with time-range slices, an iOS vs Android split and scheduled emailed reports.
- User story: As a multi-site operator, I want downloads, active users and most-used screens of my app, so that I can justify and tune it.
- Actors: chain-level admin.
- UI generation: n-a (separate branded-app admin)
- Priority: P1
- Evidence: https://support.ezfacility.com/hc/en-us/articles/29244320427931-How-to-access-and-use-analytics-for-your-app-Branded-App, https://www.ezfacility.com/blog/boost-client-conveniences-and-business-reach-with-memberme, https://www.youtube.com/watch?v=iMeRIT504Ho (t=12:12), https://www.youtube.com/watch?v=iMeRIT504Ho (t=34:43), https://www.youtube.com/watch?v=qn8y8rfi-kc (t=14:15)

### RPT-39 Rental Plan Sales report
- Sub-features: sales of prepaid rental plans over a date range (plan name, sale price, outstanding balance, sold by staff vs self-service), under Reports > Financial. Owned functionally by RNT-12.
- Settings / options: date range; sales channel dimension: staff / self-service.
- Rules / limits: shipped with Rental Plans on 2026-10-15; help article body not read.
- User story: As an owner, I want prepaid rental plan sales and unpaid balances, so that I can track this revenue line.
- Actors: owner/admin.
- UI generation: New (inferred from release timing)
- Priority: P1
- Evidence: https://support.ezfacility.com/hc/en-us/articles/57004872733211-How-to-Run-the-Rental-Plan-Sales-Report (title only, body not read), https://support.ezfacility.com/hc/en-us/articles/57248399589659-Rental-Plans-Release-Notes-October-15-2026 (title only, body not read), https://www.ezfacility.com/blog/introducing-rental-plans-prepaid-rentals-made-simple

### RPT-40 Operational analytics claimed in marketing (utilization, peak times, class popularity, trainer productivity)
- Sub-features: resource/venue utilization, employee venue utilization, busiest times and day-of-week/seasonal trends, class popularity and under-performing classes, trainer productivity, member behaviour, league participation / venue utilization / staff hours / snack-counter sales, range usage and member visits, product profitability.
- Settings / options: none published.
- Rules / limits: appear only in marketing and blog copy; no help-center article in this bundle defines parameters or formulas (see unknowns). Partly satisfied by RPT-21, RPT-30, RPT-37 and other clusters' reports. Video corroboration: customers say finance, utilization and occupancy reports are their day-to-day reports and give "how often is the gym rented on Saturdays" as a question a report answers; a vendor webinar cites attendance by day of week, by hour and by resource (trainer) for comparing attendance and drop-out. Parameters and formulas are still not shown.
- User story: As an owner, I want utilization and demand trends per resource, class and trainer, so that I can schedule and price better.
- Actors: owner/admin.
- UI generation: n-a (not documented)
- Priority: P1
- Evidence: https://www.ezfacility.com/features/billing-payments, https://www.ezfacility.com/benefits, https://www.ezfacility.com/features/league-scheduling-management, https://www.ezfacility.com/industries/shooting-range-gun-club-software, https://www.ezfacility.com/blog/make-the-most-of-ezfacility-management-software-features, https://www.ezfacility.com/blog/how-to-grow-your-business-with-sports-club-management-software, https://www.youtube.com/watch?v=3VsdaSsJn-M (t=01:30), https://www.youtube.com/watch?v=RLcaxhKMDCk (t=02:00), https://www.youtube.com/watch?v=3FOVNMAz2cE (t=21:30)

### RPT-41 Reports known by name only in this cluster (catalog completeness)
- Sub-features: names surfaced by release notes or cross-references, defined elsewhere or nowhere: Silver Sneakers report; Check-in Detail(s) and Check-in Summary (station filter; CHK-19, CHK-20); Deferred Membership Revenue (filter "Include liable membership contracts only"); Un-accrued Membership Revenue; Membership Overview; Membership Ending Actions; New Memberships; Assessment Summary (FIT-04); Trainer Performance (STF-11; Package Type column, sort by date or reservation type); Trainer Schedule; Session Notes; Trainer Payroll/Commission (STF-09); Salesperson Commission (STF-10); Accounts Receivable (BIL-19); Pyxis Disbursements (PAY-16; max one-month range, Show Details, columns Transaction Date, Card Holder, Client, Card Number, Card Type, Txn ID); Direct Debit Batch. Added from videos: Silver&Fit report (alongside Silver Sneakers); Resource Schedule report under venue booking (lists bookings with their cost, zero-cost bookings show 0).
- Settings / options: as listed per name; nothing further in this bundle. From videos: Membership Ending Actions takes a date range, a reason (frozen or suspended) and membership type; Silver Sneakers / Silver&Fit need only the participating clients to be flagged.
- Rules / limits: these must exist in our report catalog for parity even though their parameter sets come from other clusters; Silver Sneakers, Membership Overview, Membership Ending Actions, New Memberships, Trainer Schedule and Session Notes have no definition in this cluster's sources. Video detail: the Silver Sneakers and Silver&Fit reports exist so visit data can be exported and sent to the insurers for reimbursement; there is no report dedicated to no-charge bookings (the Resource Schedule report is the workaround).
- User story: As a migrating customer, I want every report I used before to have an equivalent, so that I do not lose visibility.
- Actors: owner/admin.
- UI generation: both
- Priority: P1
- Evidence: https://support.ezfacility.com/hc/en-us/articles/14655161654811-April-18th-2023-Release-Notes, https://support.ezfacility.com/hc/en-us/articles/16731304236571-June-28th-2023-Release-Notes, https://support.ezfacility.com/hc/en-us/articles/18741009680795-September-13th-2023-Release-Notes, https://support.ezfacility.com/hc/en-us/articles/19132331777307-September-27th-2023-Release-Notes, https://support.ezfacility.com/hc/en-us/articles/22122496577179-January-17th-2024-Release-Notes, https://support.ezfacility.com/hc/en-us/articles/22968789591963-February-15th-2024-Release-Notes, https://support.ezfacility.com/hc/en-us/articles/23328878237467-February-28th-2024-Release-Notes, https://support.ezfacility.com/hc/en-us/articles/24225032928027-March-27th-2024-Release-Notes, https://support.ezfacility.com/hc/en-us/articles/24695840840603-April-10th-2024-Release-Notes, https://support.ezfacility.com/hc/en-us/articles/34155834657819-July-3rd-2024-Release-Notes, https://support.ezfacility.com/hc/en-us/articles/36516560976539-April-9th-2025-Release-Notes, https://www.ezfacility.com/blog/updated-subgroup-inheritance-trainer-performance-report-e-mail-procedures-and-more, https://www.youtube.com/watch?v=iHdqoLdGlQI (t=20:34), https://www.youtube.com/watch?v=a7-8-cHwB8Y (t=43:01), https://www.youtube.com/watch?v=iR4MVBspNlQ (t=39:08)


## Integrations & API

### INT-01 Public REST API platform (auth, docs, realms)
- Sub-features: REST API for third-party sites and apps; OAuth 2.0 with Client ID and Client Secret exchanged for a bearer token; Swagger sandbox documentation; resource families: Clients, Sessions & Reservations, Bookings, POS, EZLeagues; two realms/scopes: back-office ("TMS") and Self-Service (member context); versioned paths (v2); product name "EZTMS.API"; help-center "API Starter Kit" and "API FAQs" exist (bodies not read).
- Settings / options: credentials: Client ID, Client Secret; scope/realm: TMS / Self-Service; lookups by client id, invoice id, invoice number, location id + invoice number, membership number across all accessible locations (2025-04-09).
- Rules / limits: use cases published: live schedules on own website, real-time bookings and registrations, surfacing account data, keeping POS/leagues/sessions in sync, groups published to a website; no public evidence of outbound webhooks, rate limits, pagination or key self-service UI (see unknowns); plan gating of API access is implied but not itemised.
- User story: As a facility's web developer, I want authenticated programmatic access to schedules, clients and billing, so that I can embed live data in our own site and app.
- Actors: developer/integrator, admin (credential holder), partner apps.
- UI generation: n-a
- Priority: P0
- Evidence: https://www.ezfacility.com/ez-api-services, https://www.ezfacility.com/benefits, https://www.ezfacility.com/blog/client-highlight-c2tactical-utilizes-ezfacility-digital-api, https://www.ezfacility.com/blog/software-release-groups-new-ui, https://support.ezfacility.com/hc/en-us/articles/48376398255643-API-Starter-Kit (title only, body not read), https://support.ezfacility.com/hc/en-us/articles/50433482606491-EZFacility-API-FAQs (title only, body not read), https://support.ezfacility.com/hc/en-us/articles/22529640450203-January-31-2024-Release-Notes, https://support.ezfacility.com/hc/en-us/articles/36516560976539-April-9th-2025-Release-Notes

### INT-02 Client and membership API resources
- Sub-features: client read/update endpoints; client fields EarliestMembershipStartDate and LatestMembershipEndDate (populated from 2023-08-16); four shared-membership fields on all back-office client endpoints: CurrentMembershipContractID, CurrentMembershipClientID, CurrentMembershipTotalClientCount, CurrentMembershipTotalBilledAmount (2024-03-14); two endpoints returning membership contract statuses and dates (one contract; all contracts of a client including shared ones) (2024-04-24); search by membership number across accessible locations (2025-04-09). Also covered from the owning modules' side as CLI-21 and MEM-22.
- Settings / options: none.
- Rules / limits: shared contracts expose the owning client id and the count of clients on the contract.
- User story: As an integrator, I want a client's membership standing and dates, so that an external system can gate access or pricing.
- Actors: developer/integrator.
- UI generation: n-a
- Priority: P0
- Evidence: https://support.ezfacility.com/hc/en-us/articles/17981009155995-August-16th-2023-Release-Notes, https://support.ezfacility.com/hc/en-us/articles/23807158781211-March-14th-2024-Release-Notes, https://support.ezfacility.com/hc/en-us/articles/25134483797531-April-24th-2024-Release-Notes, https://support.ezfacility.com/hc/en-us/articles/36516560976539-April-9th-2025-Release-Notes, https://www.ezfacility.com/ez-api-services

### INT-03 Invoice and payment API resources
- Sub-features: invoice reads: GET /v2/invoices/{invoiceID}, /v2/invoices/invoiceNumber={invoiceNumber}, /v2/invoices/clientId={clientID}, /v2/invoices/locationID/{locationID}/invoiceNumber={invoiceNumber}; "Payments" array on the by-client read (2022-12-15); "Disbursements" section linking payments to billed items on all four (2024-04-24); write to set status Paid on one or many existing invoices (2023-11-08). See BIL-23.
- Settings / options: invoice status value Paid settable externally.
- Rules / limits: marking Paid via API implies payment recorded outside the platform (inferred); no public statement of what ledger entry it creates.
- User story: As an integrator, I want invoices with their payments and allocations, and to mark them paid from an external system, so that accounting stays consistent.
- Actors: developer/integrator.
- UI generation: n-a
- Priority: P1
- Evidence: https://support.ezfacility.com/hc/en-us/articles/11297336305691-December-15th-2022-Release-Notes, https://support.ezfacility.com/hc/en-us/articles/20241459046683-November-8th-2023-Release-Notes, https://support.ezfacility.com/hc/en-us/articles/25134483797531-April-24th-2024-Release-Notes

### INT-04 Schedule, reservation and package API resources
- Sub-features: sessions/reservations and bookings reads (marketing list); create session reservations on the schedule, excluding rentals and special types (2024-06-05); list reservation types (id, name) for a location (2024-06-05); sessions scheduled and sessions completed counts for active packages and for all packages (2023-10-25). See PKG-16.
- Settings / options: none.
- Rules / limits: rentals cannot be created through the API as of 2024-06; a customer asked for class IDs as an enhancement (2020), so identifiers in schedule payloads were then incomplete.
- User story: As an integrator, I want to read the schedule with open seats and create bookings, so that our website shows and sells live availability.
- Actors: developer/integrator.
- UI generation: n-a
- Priority: P0
- Evidence: https://support.ezfacility.com/hc/en-us/articles/19847009538203-October-25th-2023-Release-Notes, https://support.ezfacility.com/hc/en-us/articles/26498179644187-June-5th-2024-Release-Notes, https://www.ezfacility.com/ez-api-services, https://www.ezfacility.com/blog/client-highlight-c2tactical-utilizes-ezfacility-digital-api

### INT-05 Self-Service-scope (member context) API
- Sub-features: update client with a reduced field set (2024-01-31); list package plans available for sale (2024-06-05); checkout line items for package plans, built for the branded-app cart (2024-06-19); read stored card (redacted number, expiration) and update stored card (2024-06-19). Portal-side view is SSP-19.
- Settings / options: realm Self-Service vs TMS.
- Rules / limits: card data is returned redacted only; endpoints are driven by the branded mobile app.
- User story: As a mobile-app developer, I want member-scoped endpoints for profile, purchase and card on file, so that members can self-serve in our app.
- Actors: mobile app, integrator, member (indirect).
- UI generation: n-a
- Priority: P1
- Evidence: https://support.ezfacility.com/hc/en-us/articles/22529640450203-January-31-2024-Release-Notes, https://support.ezfacility.com/hc/en-us/articles/26498179644187-June-5th-2024-Release-Notes, https://support.ezfacility.com/hc/en-us/articles/26750732215835-June-19th-2024-Release-Notes

### INT-06 POS and league API surfaces
- Sub-features: POS endpoints and EZLeagues endpoints (schedules, rosters, standings) listed on the public API page; league API tied to the EZLeagues add-on. See LGE-27.
- Settings / options: none published.
- Rules / limits: endpoint detail is behind the Swagger sandbox and not public; EZLeagues is a plan-gated add-on (included from Premium).
- User story: As a league operator, I want schedules and standings via API, so that my club site stays current.
- Actors: developer/integrator.
- UI generation: n-a
- Priority: P1
- Evidence: https://www.ezfacility.com/ez-api-services, https://www.ezfacility.com/plans-pricing/pricing-results, https://www.ezfacility.com/blog/software-release-groups-new-ui

### INT-07 QuickBooks Online sync
- Sub-features: OAuth connection per location; optional automatic sync; mapping of each Revenue Category to a QuickBooks Class; pushes financials (memberships, invoices, POS sales) to avoid double entry.
- Settings / options: Authorize (Classic: Administration > QuickBooks Online; newer: Administration > Location Settings > QBO); QuickBooks sign-in with optional 6-digit verification and company picker; auto-sync toggle; per Revenue Category field "Quickbooks Online Class". Required QuickBooks-side configuration: class tracking on, class assignment "one to each row in transaction", categories enabled, "Show Items table on expense and purchase forms" off, "Use purchase orders" off.
- Rules / limits: US customers only; one-way (platform to QuickBooks), manual QuickBooks entries are never read back; vendor recommends a brand-new QuickBooks company to avoid duplicate customers; sold as an add-on, bundled from the Premium plan; what document types are created in QuickBooks is not published.
- User story: As a bookkeeper, I want sales and payments to post to QuickBooks by class automatically, so that I do not re-key them.
- Actors: owner/admin, bookkeeper.
- UI generation: both (different menu paths)
- Priority: P0
- Evidence: https://support.ezfacility.com/hc/en-us/articles/5393406604315-How-to-connect-your-QuickBooks-Online-account-with-EZFacility, https://support.ezfacility.com/hc/en-us/articles/4406053980955-How-to-connect-your-QuickBooks-Online-account-with-EZFacility-Classic, https://support.ezfacility.com/hc/en-us/articles/4405044167835-EZFacility-Open-Webinar-QuickBooks-Online-Integration, https://www.ezfacility.com/partners/quickbooks-online-sync/, https://www.ezfacility.com/features/billing-payments, https://www.ezfacility.com/plans-pricing/pricing-results, https://www.ezfacility.com/blog/the-benefits-of-gym-management-software, https://www.ezfacility.com/blog/ezfacility-saas-partner-deep-dive

### INT-08 Calendar subscription feed (iCal-style sync URL)
- Sub-features: per-user subscription URL publishing the schedule one-way to Outlook/Office 365, Apple iOS Calendar and Google Calendar (and on to Android).
- Settings / options: feature Enable / Disable; Sync URL (contains a UID key); Sync these resources: All / selected; Sync these reservation types: All / selected; days in the past; days in the future; "Sync sessions with no bookings?"; "Sync rentals?"; "Sync all other reservations?" (e.g. Program Instruction, Unavailable); "Include Notes?"; "Include list of bookings?"; Save Preferences. Limit stated at launch: days in the past and days in the future are each capped at 90.
- Rules / limits: read-only for the external calendar; disabling and re-enabling issues a new UID key, which invalidates old subscriptions (revocation mechanism); refresh cadence is set by the subscribing calendar; booking lists and notes in the feed are personal data leaving the platform. Marketing describes it as Google/Outlook sync of staff schedules. Scheduling-side view is SCH-19. First shipped in the 17 March 2013 release (legacy webinar), pitched for Android, iPhone, iPad and Outlook.
- User story: As a trainer, I want my sessions on my phone calendar, so that I see work bookings next to personal events.
- Actors: staff, trainers, admin.
- UI generation: both (same options; button above the schedule)
- Priority: P1
- Evidence: https://support.ezfacility.com/hc/en-us/articles/10867559563547-Syncing-your-EZFacility-Calendar-to-an-External-Calendar, https://support.ezfacility.com/hc/en-us/articles/4404311517339-Syncing-your-EZFacility-Classic-Calendar-to-an-External-Calendar, https://support.ezfacility.com/hc/en-us/articles/4404311542427-Syncing-your-EZFacility-Calendar-to-your-iOS-iPod-iPad-and-iPhone-Calendar, https://support.ezfacility.com/hc/en-us/articles/4404311548059-Syncing-your-EZFacility-Calendar-to-your-Outlook-Calendar, https://support.ezfacility.com/hc/en-us/articles/4404311551899-Syncing-your-EZFacility-Calendar-to-your-Google-Android-device-Calendar, https://www.ezfacility.com/features/staff-access-management, https://www.youtube.com/watch?v=unZH32QU1nc (t=02:15), https://www.youtube.com/watch?v=tqMhVWKcLfQ (t=00:35)

### INT-09 Zoom integration for virtual sessions
- Sub-features: per-location OAuth link to a Zoom account; create a Zoom meeting when creating a reservation or add one to an existing reservation; delete meeting; staff "Start Zoom Meeting" link; client "Launch Session" from the portal schedule/My Sessions with countdown; join link in reminder emails; notification emails; uninstall. Session-side views: CLS-08, SSP-18.
- Settings / options: Administration > Zoom > Authenticate; location checkboxes "Require Self-Service Log-in" and "Require Session Booking" yielding three access modes: anyone with portal access / logged-in clients / logged-in and booked clients; per reservation: "Create Zoom meeting" checkbox and Zoom user (host) dropdown; Un-install.
- Rules / limits: paid access needs both checkboxes plus Allowed Packages on the reservation type; clients can launch from 10 minutes before start; one Zoom user cannot host two overlapping meetings, so concurrent classes need several Zoom users; the emailed link is unique and routes through portal login; a session is deducted from the package when the client joins; emails go to booked clients when a meeting is added, on booking (booked-only mode) and when the meeting or reservation is deleted; deleting the reservation deletes the meeting; links go only to scheduled/reserved/attended clients, not waitlisted (fix 2024-07-03); uninstall also requires removing the app in the Zoom marketplace; vendor recommends authenticating as the Zoom account owner; Zoom plan limits apply (free tier 40 minutes); integration reworked for Zoom compliance 2023-03-09; launched 2020-07-28. Pre-launch webinar detail (2020): access settings exist per location only, not per reservation type, so free and paid classes cannot differ within a location; meetings are created one reservation at a time and recurring or multi-day occurrences do not get meetings automatically; there is no preference for when the link is sent; a client who cancels keeps a working unique link (it cannot be revoked), so staff check attendance and remove people inside Zoom; launching is not possible from the shared MemberMe app (branded-app owners add a web tile to the portal; mobile web works); clients need no Zoom account unless the meeting is set to require sign-in; meeting passwords follow the Zoom account defaults; a host can also start from the Zoom app or browser; one Zoom account per location with several users is the advised setup.
- User story: As a studio owner, I want paid or free live-streamed classes whose links only entitled clients can open, so that I can sell virtual training.
- Actors: owner/admin, trainer (host), client.
- UI generation: Classic (documented); New not documented in this bundle
- Priority: P1
- Evidence: https://support.ezfacility.com/hc/en-us/articles/4405051261339-Zoom-Integration-with-EZFacility-Classic, https://support.ezfacility.com/hc/en-us/articles/34441456779163-Online-Webinar-Zoom-Integration-in-EZFacility-Classic, https://support.ezfacility.com/hc/en-us/articles/13526384977307-March-9th-2023-Release-Notes, https://support.ezfacility.com/hc/en-us/articles/34155834657819-July-3rd-2024-Release-Notes, https://www.ezfacility.com/features/member-engagement, https://www.ezfacility.com/blog/new-ezfacility-business-features, https://www.youtube.com/watch?v=hlGAZlxFHWg (t=36:14), https://www.youtube.com/watch?v=hlGAZlxFHWg (t=15:41), https://www.youtube.com/watch?v=hlGAZlxFHWg (t=20:53), https://www.youtube.com/watch?v=hlGAZlxFHWg (t=27:03), https://www.youtube.com/watch?v=hlGAZlxFHWg (t=18:51)

### INT-10 Smartwaiver integration (third-party waivers)
- Sub-features: link a Smartwaiver account to a location by API key; signed waivers flow in by webhook and create or update the client record; waiver/document stored on the client; Smartwaiver's free kiosk apps for on-site signing; also used for contracts. Document-side view is DOC-13. Video adds: client matching on each submission (one match attaches the waiver, no match creates a client, several matches email the account admins to resolve or merge by hand, never auto-merge); extra participants and minors on a waiver become linked clients with the parent-of relationship set automatically; the client's waiver-signed checkbox is ticked automatically while any synced waiver is active and cleared when all have expired.
- Settings / options: Location Settings > Smartwaiver: API Key, Activate; account-level webhook URL auto-populated with the platform location id; per-template webhook override ("Send Webhook for this waiver" + URL carrying another location id). "Email validation" Yes / No in the integration admin (Yes holds a signed waiver out of the platform until the signer confirms their email; a per-waiver setting on the Smartwaiver side overrides it, e.g. validate online but not at the kiosk).
- Rules / limits: menu hidden until a Smartwaiver account exists; all templates route to the linked location unless overridden; one Smartwaiver account can serve several locations; location id is obtained from vendor support; API key is shown once by Smartwaiver; available in New from 2022-02-17. Webinar: the module is switched on by the account manager and carries an extra monthly integration fee; a waiver never creates a membership or package; no waiver-specific reporting inside the platform (details under DOC-13).
- User story: As an owner, I want signed waivers to appear on the right client automatically, so that front desk can verify them at check-in.
- Actors: owner/admin, client (signer).
- UI generation: New (documented)
- Priority: v2-adapter (brief: build own waivers; keep an inbound waiver-provider interface)
- Evidence: https://support.ezfacility.com/hc/en-us/articles/9917964474011-Enable-the-Smartwaiver-and-EZFacility-Integration-in-EZFacility, https://www.ezfacility.com/partners/smartwaiver/, https://www.ezfacility.com/features/league-scheduling-management, https://www.ezfacility.com/blog/software-release-ezpayments-uk-smartwaiver, https://www.ezfacility.com/blog/ezfacility-saas-partner-deep-dive, https://www.youtube.com/watch?v=jbwkXIo9rY8 (t=06:05), https://www.youtube.com/watch?v=jbwkXIo9rY8 (t=09:10), https://www.youtube.com/watch?v=jbwkXIo9rY8 (t=12:14), https://www.youtube.com/watch?v=jbwkXIo9rY8 (t=13:14)

### INT-11 Perkville loyalty/rewards integration
- Sub-features: third-party points program: platform activity earns points in Perkville; customers redeem points for Perks (discounts, free sessions) through a free Perkville account; Perkville emails customers when points are earned.
- Settings / options: earning triggers fed by the platform: check-in, attending a session, each dollar invoiced; point values and Perks are configured by the facility inside Perkville; multiple locations per Perkville account.
- Rules / limits: POS sales do not earn points; redemption is not automated, staff apply the Perk manually like a coupon and there is no "redeem perk" payment type; no integration fee, Perkville bills monthly after a 30-day trial by account size and expected transactions; the article describing how the two systems are linked is referenced but not in the corpus; partnership dates from 2012.
- User story: As an owner, I want visits and spend to earn reward points automatically, so that members are nudged to come back.
- Actors: owner/admin, client, Perkville (external).
- UI generation: n-a
- Priority: v2-adapter (outbound loyalty-event interface only)
- Evidence: https://support.ezfacility.com/hc/en-us/articles/5325284957979-What-is-Perkville, https://support.ezfacility.com/hc/en-us/articles/5325270760731-How-are-points-earned, https://support.ezfacility.com/hc/en-us/articles/5325162944539-How-do-customers-redeem-their-points, https://support.ezfacility.com/hc/en-us/articles/5325163359131-How-does-a-facility-redeem-Perks, https://support.ezfacility.com/hc/en-us/articles/5325205707931-Who-notifies-the-customers-they-earned-points, https://support.ezfacility.com/hc/en-us/articles/5325163152155-When-can-they-start-using-Perkville, https://support.ezfacility.com/hc/en-us/articles/5325278710171-How-much-does-Perkville-cost, https://support.ezfacility.com/hc/en-us/articles/5325289162907-How-does-a-facility-register-for-Perkville, https://www.ezfacility.com/partners, https://www.ezfacility.com/blog/activate-perkville-on-ezfacility-and-gamify-exercise-this-year, https://www.ezfacility.com/press-news/press-releases/ezfacility-introduces-new-memberme-mobile-app

### INT-12 CoachMePlus ("Activate") integration
- Sub-features: partner coaching product: client mobile app, goal tracking, client and trainer dashboards, workout builder with exercise library, wellness questionnaires. Partner webinars add: exercise library of roughly 1,000 to 1,200 exercises (about a third with video) plus custom exercises with default sets/reps, coach note, tags, a measured property and attachments; reusable circuits with supersets, set progressions and loads as a percentage of a stored one-rep max; dated programs built on a calendar and assigned to one client or a group, then adjusted per client; one-way alerts with read tracking and two-way messaging; "Athlete Central" client groups; per-client dashboards, notes, file library, testing and printable reports; client app logging with readiness and exertion questionnaires; hydration station; Apple Health and Google Fit feeds.
- Settings / options: none published. Partner-side only (video): metric / imperial toggle; report export to Excel or print; one account with a training group per location for multi-site operators.
- Rules / limits: only a webinar listing and the partner page exist; data exchanged between the systems is not described. Video detail on the data exchange: platform clients get a CoachMePlus account automatically with basic contact data, and become inactive there when no longer active in the platform; the flow appears one-way from the platform; the partner app takes no payments, sales stay in the platform (pricing and trial terms under STF-14).
- User story: As a performance coach, I want athlete programs and goals alongside bookings, so that training delivery is tracked.
- Actors: trainer, client.
- UI generation: n-a
- Priority: v2-adapter
- Evidence: https://support.ezfacility.com/hc/en-us/articles/4405044143899-Online-Webinar-CoachMePlus, https://www.ezfacility.com/partners, https://www.ezfacility.com/blog/ezfacility-saas-partner-deep-dive, https://www.youtube.com/watch?v=NTXRhqak3cM (t=02:03), https://www.youtube.com/watch?v=NTXRhqak3cM (t=08:10), https://www.youtube.com/watch?v=NTXRhqak3cM (t=24:35), https://www.youtube.com/watch?v=YkHOVxeiuiI (t=05:07), https://www.youtube.com/watch?v=YkHOVxeiuiI (t=27:43)

### INT-13 Google Analytics cross-domain tracking for registration pages
- Sub-features: analytics continuity between the facility's marketing site and hosted online-registration pages (funnel tracking).
- Settings / options: not published (presumably a tracking id per account, inferred).
- Rules / limits: announced 2021-11-29; no help-center article in this bundle.
- User story: As a marketer, I want registrations attributed to the campaign that drove the visit, so that I can measure conversion.
- Actors: admin, marketing staff.
- UI generation: n-a
- Priority: P2
- Evidence: https://www.ezfacility.com/blog/software-release-vaccine-passport, https://www.ezfacility.com/blog/the-benefits-of-gym-management-software

### INT-14 Partner and hardware network (catalog)
- Sub-features: named partners beyond those above: access control (Brivo cloud access with member data sync, anti-passback, per-area access, alerts; Passport Technologies; Identity One cardless check-in), credentials and hardware (Authentic8 RFID cards/fobs/wristbands; Plastic Printers cards, ID printers, POS hardware), payments (Constellation Payments, Clover terminals, in-house EZPayments), retail (Rapid Gun Systems / NCR Counterpoint), messaging (Textmunication SMS), websites (97Display), training content (Trainingym), SportsLife X (no description), senior-fitness reporting (Silver Sneakers report), legacy: PlayerGrid team messaging (2012), Club Vitals maintenance SSO (2011), Nutrition Complete (2015).
- Settings / options: none in this cluster; owning clusters document access control, payments and SMS.
- Rules / limits: several are resale/referral relationships with no data integration described; legacy items (PlayerGrid 2012-12-06, Club Vitals 2011-09-19, Nutrition Complete 2015-05-22) are probably discontinued. Video: card processing is either in-house EZPayments or the facility's own processor reached through a gateway such as Authorize.net; Trainingym has a built client sync (now INT-15); no HubSpot or Zapier connector exists.
- User story: As an owner, I want the platform to work with my door hardware, card printer and processor, so that I do not maintain separate systems.
- Actors: owner/admin, partner vendors.
- UI generation: n-a
- Priority: v2-adapter (legacy items P2)
- Evidence: https://www.ezfacility.com/partners, https://www.ezfacility.com/partners/passport-technologies/, https://www.ezfacility.com/partners/rapid-gun-systems/, https://www.ezfacility.com/blog/ezfacility-saas-partner-deep-dive, https://www.ezfacility.com/press-news/press-releases/ezfacility-partners-with-brivo-to-offer-24-hour-sports-fitness-access, https://www.ezfacility.com/blog/ezfacility-partners-with-playergrid-to-enhance-league-management-features, https://www.ezfacility.com/press-news/press-releases/ezfacility-partners-with-club-vitals, https://www.ezfacility.com/blog/add-to-the-client-experience-with-nutrition-complete, https://www.youtube.com/watch?v=wTcpTun-eyM, https://support.ezfacility.com/hc/en-us/articles/14655161654811-April-18th-2023-Release-Notes, https://www.youtube.com/watch?v=VuUR1Y9bhjQ (t=39:58), https://www.youtube.com/watch?v=t85Pe_jL_h4 (t=55:12)

### INT-15 Trainingym member-engagement integration
- Sub-features: built client sync to the Trainingym partner platform: when a client is created and signs a contract in the platform the record passes to Trainingym, which sends a welcome message inviting the member to download its app. Partner-side capabilities shown: onboarding interview storing goals and motivators for all staff (also as an in-club kiosk self-interview); workout programs from a 2,000+ exercise video library (generated from the interview, written by a trainer, or self-assigned templates); attendance calendar, email, push and automatic reminders; segments and target audiences; automatic satisfaction surveys after interactions plus custom surveys; staff app with communications log and engagement overview; member app with workouts, activity log, health area and Apple Health / Google Fit sync; body-composition scale results in the app (device name unclear).
- Settings / options: none on the platform side were shown; partner side: one licence per location, member login via app, web page or in-club kiosk.
- Rules / limits: the trigger is client creation plus a signed contract; direction shown is platform to partner only; partner reports are online and Excel, fitness reports go to PDF or email; commercial terms (monthly licence plus one-off configuration fee, 30 to 60 days onboarding, members pay nothing) are the partner's; no platform screens were demonstrated, so setup steps are unknown.
- User story: As a gym owner, I want new members to land in my engagement and workout app automatically, so that onboarding starts without re-entering them.
- Actors: owner/admin, trainer, member, Trainingym (external).
- UI generation: n-a
- Priority: v2-adapter
- Evidence: https://www.youtube.com/watch?v=6GY9mk7HOkw (t=26:34), https://www.youtube.com/watch?v=6GY9mk7HOkw (t=33:42), https://www.youtube.com/watch?v=6GY9mk7HOkw (t=06:06), https://www.youtube.com/watch?v=6GY9mk7HOkw (t=12:13), https://www.ezfacility.com/partners

## Release Notes

Only cross-cutting platform changes are kept here; module-specific shipped changes are folded into RPT/INT features above or belong to the owning clusters (memberships, rentals, check-in, billing, leagues, email).

### REL-01 Published release notes (dated, versioned changelog)
- Sub-features: public help-center section with one article per release listing new features, improvements, fixes and API changes; occasional vendor Q&A in comments; separate feature-specific notes (e.g. Rental Plans) and advance notices of major versions.
- Settings / options: item kinds observed: feature, improvement, fix, API, API fix, tech update; version labels (Version 53.0 on 2024-01-17; v104.0 to v121.0 during 2026; "v4.0" notice for 2026-01-14).
- Rules / limits: roughly fortnightly cadence in 2023-2024; articles are sometimes dated later than the release they describe; items name the UI they affect (TMS/Classic, New UI/EZUI) inconsistently; twelve later notes are known by title only. Older cadence statements from videos: after the August 2012 interface release the vendor promised updates every 3 to 4 weeks (and dropped Internet Explorer 6); the 17 March 2013 release ran on a Sunday evening with about two hours of downtime from 8pm Eastern; in 2020 the vendor said it aimed for weekly releases.
- User story: As an admin, I want a dated list of what changed, so that I can brief staff and spot fixes to issues I reported.
- Actors: owner/admin, integrators.
- UI generation: n-a
- Priority: P1
- Evidence: https://support.ezfacility.com/hc/en-us/articles/11297336305691-December-15th-2022-Release-Notes, https://support.ezfacility.com/hc/en-us/articles/13526384977307-March-9th-2023-Release-Notes, https://support.ezfacility.com/hc/en-us/articles/14655161654811-April-18th-2023-Release-Notes, https://support.ezfacility.com/hc/en-us/articles/16308423683355-June-12th-2023-Release-Notes, https://support.ezfacility.com/hc/en-us/articles/16731304236571-June-28th-2023-Release-Notes, https://support.ezfacility.com/hc/en-us/articles/16846068050715-July-3rd-2023-Release-Notes, https://support.ezfacility.com/hc/en-us/articles/17574439837467-August-2nd-2023-Release-Notes, https://support.ezfacility.com/hc/en-us/articles/17981009155995-August-16th-2023-Release-Notes, https://support.ezfacility.com/hc/en-us/articles/18408526583067-August-31st-2023-Release-Notes, https://support.ezfacility.com/hc/en-us/articles/18741009680795-September-13th-2023-Release-Notes, https://support.ezfacility.com/hc/en-us/articles/19132331777307-September-27th-2023-Release-Notes, https://support.ezfacility.com/hc/en-us/articles/19847009538203-October-25th-2023-Release-Notes, https://support.ezfacility.com/hc/en-us/articles/20241459046683-November-8th-2023-Release-Notes, https://support.ezfacility.com/hc/en-us/articles/22122496577179-January-17th-2024-Release-Notes, https://support.ezfacility.com/hc/en-us/articles/22529640450203-January-31-2024-Release-Notes, https://support.ezfacility.com/hc/en-us/articles/22968789591963-February-15th-2024-Release-Notes, https://support.ezfacility.com/hc/en-us/articles/23328878237467-February-28th-2024-Release-Notes, https://support.ezfacility.com/hc/en-us/articles/23807158781211-March-14th-2024-Release-Notes, https://support.ezfacility.com/hc/en-us/articles/24225032928027-March-27th-2024-Release-Notes, https://support.ezfacility.com/hc/en-us/articles/24695840840603-April-10th-2024-Release-Notes, https://support.ezfacility.com/hc/en-us/articles/25134483797531-April-24th-2024-Release-Notes, https://support.ezfacility.com/hc/en-us/articles/25551222201627-May-8th-2024-Release-Notes, https://support.ezfacility.com/hc/en-us/articles/25985296561179-May-23rd-2024-Release-Note, https://support.ezfacility.com/hc/en-us/articles/26498179644187-June-5th-2024-Release-Notes, https://support.ezfacility.com/hc/en-us/articles/26750732215835-June-19th-2024-Release-Notes, https://support.ezfacility.com/hc/en-us/articles/34155834657819-July-3rd-2024-Release-Notes, https://support.ezfacility.com/hc/en-us/articles/36516396025115-April-23rd-2025-Release-Notes, https://support.ezfacility.com/hc/en-us/articles/36516560976539-April-9th-2025-Release-Notes, https://support.ezfacility.com/hc/en-us/articles/42755413196443-October-23-2025-Release-Notes (title only, body not read), https://support.ezfacility.com/hc/en-us/articles/43326763052443-November-14-2025-Release-Notes (title only, body not read), https://support.ezfacility.com/hc/en-us/articles/44426099543835-December-3-2025-Release-Notes (title only, body not read), https://support.ezfacility.com/hc/en-us/articles/44459810488603-Important-Update-to-EZFacility-v4-0-on-1-14-26 (title only, body not read), https://support.ezfacility.com/hc/en-us/articles/52341828808475-July-1-2026-Release-Notes-v104-0 (title only, body not read), https://support.ezfacility.com/hc/en-us/articles/52430805858331-July-1-2026-Release-Notes-v104-0-1 (title only, body not read), https://support.ezfacility.com/hc/en-us/articles/53053635021979-July-15-2026-Release-Notes-v105-0 (title only, body not read), https://support.ezfacility.com/hc/en-us/articles/53377281922075-July-22-2026-Release-Notes-v106-0 (title only, body not read), https://support.ezfacility.com/hc/en-us/articles/54598636350235-August-19-2026-Release-Notes-v110-0 (title only, body not read), https://support.ezfacility.com/hc/en-us/articles/57248399589659-Rental-Plans-Release-Notes-October-15-2026 (title only, body not read), https://support.ezfacility.com/hc/en-us/articles/57821654414875-October-28-2026-Release-Notes-v120-0 (title only, body not read), https://support.ezfacility.com/hc/en-us/articles/58150655820187-November-4-2026-Release-Notes-v121-0 (title only, body not read), https://www.youtube.com/watch?v=PBbm0V08fts (t=03:50), https://www.youtube.com/watch?v=unZH32QU1nc (t=00:00), https://www.youtube.com/watch?v=IM8m1sUsMdw (t=30:45)

### REL-02 Platform performance and resilience changes
- Sub-features: client auto-reconnect after connection loss (2022-12-15); query optimisation for client search/filter, database stability work and extra monitoring (2023-04-18, 2023-06-12); advanced diagnostics (2023-07-03); fewer repeated lookups for reservation details and permission labels/codes (2024-06-19); schedule no longer times out creating more than 300 linked reservations, supports 1500+ (2025-04-23); single-click guards on "Add Client" and "Renew Now" to stop duplicates (2023-08-31); report Generate button disabled after click (2025-04-09).
- Settings / options: type-ahead search fires only after three characters.
- Rules / limits: implied non-functional targets for us: bulk recurring creation of 1500+ sessions in one request; idempotent create actions; debounce/min-length on global search.
- User story: As front-desk staff, I want the app to stay responsive and not create duplicates when I double-click or lose wifi, so that data stays clean.
- Actors: all staff users.
- UI generation: both
- Priority: P1
- Evidence: https://support.ezfacility.com/hc/en-us/articles/11297336305691-December-15th-2022-Release-Notes, https://support.ezfacility.com/hc/en-us/articles/14655161654811-April-18th-2023-Release-Notes, https://support.ezfacility.com/hc/en-us/articles/16308423683355-June-12th-2023-Release-Notes, https://support.ezfacility.com/hc/en-us/articles/16846068050715-July-3rd-2023-Release-Notes, https://support.ezfacility.com/hc/en-us/articles/18408526583067-August-31st-2023-Release-Notes, https://support.ezfacility.com/hc/en-us/articles/26750732215835-June-19th-2024-Release-Notes, https://support.ezfacility.com/hc/en-us/articles/36516396025115-April-23rd-2025-Release-Notes, https://support.ezfacility.com/hc/en-us/articles/36516560976539-April-9th-2025-Release-Notes

### REL-03 New-UI shell, responsive navigation and Classic-to-New transition
- Sub-features: sidebar defaults by device (tablet collapsed to icons, desktop expanded) (2023-08-31); on mobile the quick options, knowledge-base link, logout and UI switch move to a footer bar (2023-09-13); controls restyled to the New look (2024-01-17); mobile inputs no longer trigger browser auto-zoom (2024-07-03); device-specific layout fixes; check-in modals reachable from the collapsed menu (2025-04-23); per-user switch between Classic and New, with a configurable default platform; transition Q&A (2024-09-27).
- Settings / options: "switch to classic" / "new experience" toggle; default platform Classic vs New.
- Rules / limits: users of one account can migrate at different times; schedule behaviour and billing are identical across UIs; gaps stated for New at the time: no colour theming, SMS campaigns planned without date, membership "notes" section removed (client "Comments" and "Medical Conditions" remain), classic email templates unavailable once Advanced Email Campaigns is used, no bulk delete or bulk merge of clients. From webinars: moving an account from Classic to New has no extra cost and is switched on by support, and the vendor said it was not forcing Classic customers across (no sunset date given); the New Scheduling Experience reached only accounts with New on or set as default, automatically on its release date (June 22), while Classic-only accounts had to ask account management; going back to Classic afterwards loses the new rental rule and rental type options; the vendor advises moving a whole facility at once and allows deferring until staff are trained (paid training offered).
- User story: As an owner, I want staff to move to the new interface at their own pace, so that retraining does not disrupt operations.
- Actors: all staff users, owner/admin.
- UI generation: both
- Priority: P2 (we ship one UI; keep responsive shell requirements)
- Evidence: https://support.ezfacility.com/hc/en-us/articles/29585782102683-Unlocking-the-Power-of-EZFacility-s-New-UI-Your-Guide-to-a-Smooth-Transition, https://support.ezfacility.com/hc/en-us/articles/18408526583067-August-31st-2023-Release-Notes, https://support.ezfacility.com/hc/en-us/articles/18741009680795-September-13th-2023-Release-Notes, https://support.ezfacility.com/hc/en-us/articles/22122496577179-January-17th-2024-Release-Notes, https://support.ezfacility.com/hc/en-us/articles/22968789591963-February-15th-2024-Release-Notes, https://support.ezfacility.com/hc/en-us/articles/34155834657819-July-3rd-2024-Release-Notes, https://support.ezfacility.com/hc/en-us/articles/36516396025115-April-23rd-2025-Release-Notes, https://support.ezfacility.com/hc/en-us/articles/44459810488603-Important-Update-to-EZFacility-v4-0-on-1-14-26 (title only, body not read), https://www.ezfacility.com/blog/product-update-get-ready-for-an-awesome-new-ui-experience, https://www.youtube.com/watch?v=SzgMT6X961A (t=26:06), https://www.youtube.com/watch?v=SzgMT6X961A (t=47:45), https://www.youtube.com/watch?v=zzEUXdDPMyU (t=17:36), https://www.youtube.com/watch?v=TWNQ4cTiEFs (t=01:07)

### REL-04 Locale, terminology and time-zone corrections
- Sub-features: region-specific labels (UK "cheque"; "Mobile"/"Mobile Phone" replacing "Cell" on registration forms, UK variant); "Sex" renamed "Gender" everywhere including reports (2024-05-08), stored values Male / Female / Not Specified (2024-01-31); time-zone data correction for Europe/Athens (2023-09-13); membership created timestamp stored in UTC so dates do not shift with daylight saving (2023-06-28); portal invitation timestamps and contract visit summaries shown in facility local time (2023-07-03, 2023-08-31); POS transaction dates follow the user's culture setting (2024-06-05); recurring session ending at midnight no longer rolls to the next day (2023-08-16).
- Settings / options: per-user culture/locale; per-location time zone; region US / UK.
- Rules / limits: day boundaries for business rules are midnight-to-midnight in the location's time zone (stated for the one-visit-per-day rule, 2024-02-28).
- User story: As a UK operator, I want local wording, dates and times, so that staff and members are not confused by US defaults.
- Actors: all users.
- UI generation: both
- Priority: P1
- Evidence: https://support.ezfacility.com/hc/en-us/articles/13526384977307-March-9th-2023-Release-Notes, https://support.ezfacility.com/hc/en-us/articles/14655161654811-April-18th-2023-Release-Notes, https://support.ezfacility.com/hc/en-us/articles/16731304236571-June-28th-2023-Release-Notes, https://support.ezfacility.com/hc/en-us/articles/16846068050715-July-3rd-2023-Release-Notes, https://support.ezfacility.com/hc/en-us/articles/17981009155995-August-16th-2023-Release-Notes, https://support.ezfacility.com/hc/en-us/articles/18408526583067-August-31st-2023-Release-Notes, https://support.ezfacility.com/hc/en-us/articles/18741009680795-September-13th-2023-Release-Notes, https://support.ezfacility.com/hc/en-us/articles/22529640450203-January-31-2024-Release-Notes, https://support.ezfacility.com/hc/en-us/articles/22968789591963-February-15th-2024-Release-Notes, https://support.ezfacility.com/hc/en-us/articles/23328878237467-February-28th-2024-Release-Notes, https://support.ezfacility.com/hc/en-us/articles/25551222201627-May-8th-2024-Release-Notes, https://support.ezfacility.com/hc/en-us/articles/26498179644187-June-5th-2024-Release-Notes

### REL-05 Permission and data-exposure hardening shipped as fixes
- Sub-features: employees could open other employees' time clocks (2023-04-18); refund permission now hides card type and bank details from users without it, refund disabled when nothing is on account (2023-06-28); league Admin role can no longer create or edit other users or modify the SuperUser (2024-01-17); trainers limited to their own data in trainer reports (2024-01-17); error messages shown when "Allow from any IP Address" is enabled (2023-04-18); "Reservation Type Permissions" section on the user permissions page replacing the older reservation-type permission, with back-population for new types (2024-07-03); warning when taking payment for a client outside their home location (2024-05-08).
- Settings / options: "Allow from any IP Address"; billing refund permission; Reservation Type Permissions (per user, per reservation type); league roles Admin / SuperUser.
- Rules / limits: these are regression classes we must test for: row-level scoping of self-only resources, field-level masking tied to permissions, role-escalation prevention.
- User story: As an owner, I want staff to see and do only what their role allows, so that payroll, payment and client data stay protected.
- Actors: owner/admin, all staff roles.
- UI generation: both
- Priority: P0
- Evidence: https://support.ezfacility.com/hc/en-us/articles/14655161654811-April-18th-2023-Release-Notes, https://support.ezfacility.com/hc/en-us/articles/16731304236571-June-28th-2023-Release-Notes, https://support.ezfacility.com/hc/en-us/articles/22122496577179-January-17th-2024-Release-Notes, https://support.ezfacility.com/hc/en-us/articles/25551222201627-May-8th-2024-Release-Notes, https://support.ezfacility.com/hc/en-us/articles/34155834657819-July-3rd-2024-Release-Notes

## Excluded articles

Help articles that document no product capability.

| URL | Reason |
|---|---|
| https://support.ezfacility.com/hc/en-us/articles/17671233549211-EZFacility-Support-Hours-Monday-Friday-8-30am-to-5-00pm-ET | States vendor support opening hours only; no product capability (hours noted under ONB-03 rules). |
| https://support.ezfacility.com/hc/en-us/articles/27663339302939-Clear-Cache-in-Google-Chrome | Generic Chrome cache-clearing steps; browser procedure, not a product feature. |
| https://support.ezfacility.com/hc/en-us/articles/4405384728091-Online-Webinar-5-Tips-to-Boost-Retention-Revenue-with-a-Branded-Mobile-App | Webinar pointer about the branded app; article text carries no capability detail (the product itself is covered by APP-02). |
| https://support.ezfacility.com/hc/en-us/articles/4404305630619-Online-Webinar-Learn-about-the-MM-App-the-Self-Service-Portal-in-EZFacility-Classic | Webinar pointer about MM+ and the portal; no capability detail in text (covered by APP-01 / SSP-01). |
