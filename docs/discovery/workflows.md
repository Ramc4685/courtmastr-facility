# Workflows — end-to-end flows

Phase 0 output 3. Flows are written in our own words from public help material; feature IDs refer to `feature-inventory.md`.

## Platform, Locations & Resources, Import, Onboarding

### First-run account setup
- Actors: owner/admin; vendor onboarding trainer (optional).
- Preconditions: tenant provisioned with one location, the built-in roles and an owner login.
- Steps:
  1. Review the built-in roles; clone and trim one for any special job (e.g. bookkeeper with financial reports only).
  2. Create a login per employee and assign a role; link trainers to their calendar resource.
  3. Complete the location profile: internal label, public name, address, phone, customer-visible email, alert email for card declines, website.
  4. Once a payment processor is connected, tick the accepted card brands.
  5. Upload logos.
  6. Set the daily run times for membership renewal, package renewal and autopay; choose digest vs per-decline staff emails.
  7. Choose time-clock rounding and the schedule drag-and-drop default.
  8. EU only: enable GDPR mode; the system then sends the admin to author the consent document.
  9. Enter weekly facility hours.
  10. Create schedule groups, then trainers, salespeople and venues, placing each resource in a group.
  11. Optional: submit the data import (see "Onboarding data import").
- Rules/edge cases: time-clock users must have a user record; facility hours appear on the calendar only once resources exist; resources without a schedule group are discouraged; card-brand setting is invisible until a processor is integrated.
- Feature IDs involved: ONB-01, PLT-02, PLT-04, PLT-05, PLT-08, PLT-16, RES-01, RES-02, RES-03, RES-04, IMP-02
- Evidence URLs: https://support.ezfacility.com/hc/en-us/articles/4402434192027-How-to-Set-Up-Your-New-Account, https://support.ezfacility.com/hc/en-us/articles/22795613046299-Location-Setup, https://www.ezfacility.com/blog/how-to-succeed-with-ezfacility

### Create a staff user
- Actors: owner/admin.
- Preconditions: target role exists; username not in use.
- Steps:
  1. Open user administration and start a new user.
  2. Pick the role.
  3. Enter first name, last name, email, username and an initial password that satisfies the password policy.
  4. Enter mobile number and carrier for text notifications, or choose no SMS.
  5. Optionally link the user to a schedule resource and opt in to attendance-change emails for it.
  6. Optionally restrict the IP addresses the user may work from (current IP is offered; add more or allow any).
  7. Save; the user appears in the active list and can log in.
- Rules/edge cases: duplicate username rejected; policy is 6+ chars letters and digits in Classic, 12+ chars with a digit and an uppercase letter in New; resource-scoped permissions are inert until step 5 is done; attendance emails fire only when a status change alters class size and never for a salesperson link; the user's email becomes the reply-to on mail they send.
- Feature IDs involved: PLT-02, PLT-05, PLT-07
- Evidence URLs: https://support.ezfacility.com/hc/en-us/articles/29554644710171-Creating-A-New-User, https://support.ezfacility.com/hc/en-us/articles/4402427180315-Creating-A-New-User, https://support.ezfacility.com/hc/en-us/articles/30051822805659-How-to-Use-the-Employee-Time-Clock-in-EZFacility-Classic

### Create a custom role and assign it
- Actors: owner/admin.
- Preconditions: none.
- Steps:
  1. Open role administration and start a new role.
  2. Name it; optionally apply an existing role as the starting template (permissions are copied, the source is untouched).
  3. Walk the permission areas and tick (grant) or untick (deny) each permission; set per-reservation-type access where relevant.
  4. Save; the role is now selectable on the user form.
  5. On a new or existing user, choose the role and save.
  6. Optional: open that user's own permission grid and adjust individual permissions; the user is then flagged as diverging from the role.
- Rules/edge cases: built-in roles are also editable in New (shield icon); only custom roles can be deleted (Classic, inferred); email-campaign level (Publisher/Editor/Viewer/None) can be set at role or user level and only by a Manager; new reservation types inherit permissions by back-fill.
- Feature IDs involved: PLT-04, PLT-05, PLT-06
- Evidence URLs: https://support.ezfacility.com/hc/en-us/articles/29748234477595-Creating-A-Custom-Role, https://support.ezfacility.com/hc/en-us/articles/4402434188187-Creating-a-Custom-User-Role, https://support.ezfacility.com/hc/en-us/articles/22791705622811-Where-to-find-edit-and-create-Roles-on-EZFacility, https://support.ezfacility.com/hc/en-us/articles/4402427179419-Adding-a-Role-to-a-User, https://support.ezfacility.com/hc/en-us/articles/34419227413659-Assigning-A-Role-to-A-User, https://support.ezfacility.com/hc/en-us/articles/27808006885275-Change-Permissions-for-Email-Campaigns-2024, https://support.ezfacility.com/hc/en-us/articles/34155834657819-July-3rd-2024-Release-Notes

### Reset a staff password
- Actors: owner/admin; affected staff user.
- Preconditions: user has a valid email on file (for the emailed path).
- Steps:
  1. Open the user from the active-users list.
  2. Decision: (a) type a new password and save, then tell the user out of band; or (b) trigger the reset action.
  3. For (b) the system emails the user: a temporary password in Classic, a reset link in New.
  4. System confirms the reset to the admin.
  5. User signs in and sets their own password.
- Rules/edge cases: path (a) means the admin knows the password; forced change on next login is not documented.
- Feature IDs involved: PLT-03
- Evidence URLs: https://support.ezfacility.com/hc/en-us/articles/29554698393883-How-to-Change-a-User-s-Password, https://support.ezfacility.com/hc/en-us/articles/4402427178395-How-to-Change-a-User-Password, https://support.ezfacility.com/hc/en-us/articles/20241459046683-November-8th-2023-Release-Notes

### Configure a location's hours and resources
- Actors: owner/admin.
- Preconditions: location exists.
- Steps:
  1. Open the location and set start/end time or "closed" for each weekday; save. The schedule grid now starts and ends at those times.
  2. Create schedule groups for each resource family.
  3. Add each venue with a name and a schedule group.
  4. Reorder venues to the desired left-to-right calendar order.
  5. Where a space subdivides (New, 2026), open the venue, go to its Sub Venues tab and use "create sub venue" for each part; set rates and rental types on the children where they are priced apart from the whole.
  6. Edit or rename later in place.
- Rules/edge cases: hours are year-round with no holiday exceptions; hours only bound the staff schedule and are not published; resource count is limited by plan; overlap rules between parent and sub-venue are unpublished (we assume booking the parent blocks all children and vice versa); the 2026 webinar confirms exactly that, and adds that self-service offers the children or the parent according to which one the rental type is linked to; resource groups are headers only and cannot be booked.
- Feature IDs involved: RES-02, RES-03, RES-04, PLT-14
- Evidence URLs: https://support.ezfacility.com/hc/en-us/articles/4403486971675-How-To-Set-Facility-Hours-in-EZFacility-Classic, https://support.ezfacility.com/hc/en-us/articles/22934947867547-Facility-Hours-Setup, https://support.ezfacility.com/hc/en-us/articles/4403493938843-Adding-or-Editing-a-Venue-in-EZFacility-Classic, https://support.ezfacility.com/hc/en-us/articles/4402434192027-How-to-Set-Up-Your-New-Account, https://www.youtube.com/watch?v=SzgMT6X961A, https://www.youtube.com/watch?v=SzgMT6X961A (t=05:40, t=06:41, t=21:00)

### Book a trainer session that holds venues
- Actors: scheduler (admin or front desk).
- Preconditions: trainer and venues exist on the schedule; reservation types configured; user has permission for that reservation type.
- Steps:
  1. On the schedule, click the trainer's cell at the wanted time.
  2. Choose the reservation type; its defaults populate.
  3. Select one or more venues to hold.
  4. Decision: save and finish, save and add a client, or define recurrence.
  5. System writes the trainer booking and a linked "unavailable" hold on each selected venue for every occurrence.
  6. Later, drag the booking to a new time: all linked holds move with it.
  7. Delete from either the trainer row or a venue row: the whole linked set is released.
- Rules/edge cases: any conflict on the trainer or on any selected venue must reject the save or move as a unit; recurrence fans out to trainer plus venues for every instance; large series (1,500+ linked reservations) must not time out; drop onto an occupied slot is rejected.
- Feature IDs involved: RES-05, RES-03, PLT-04
- Evidence URLs: https://support.ezfacility.com/hc/en-us/articles/4404311244187-Advanced-Multi-Scheduling-in-EZFacility-Classic, https://support.ezfacility.com/hc/en-us/articles/4404311249435-Multi-Scheduling-a-Trainer-and-a-Venue-for-a-Single-Reservation-in-EZFacility-Classic, https://support.ezfacility.com/hc/en-us/articles/36516396025115-April-23rd-2025-Release-Notes

### Map a league venue to facility resources
- Actors: league admin.
- Preconditions: league module linked to the facility account; facility venues exist.
- Steps:
  1. In the league module, add a venue and name it.
  2. Move the matching facility venue(s) from the available list to the mapped list.
  3. Enter the public description.
  4. Save.
  5. From then on, each game scheduled on that league venue also appears on the mapped facility calendars.
- Rules/edge cases: mapping list is hidden when no facility account is linked; whether a facility-side conflict blocks the league scheduler is unpublished (we assume yes, enforced by the same constraint).
- Feature IDs involved: RES-06, RES-03
- Evidence URLs: https://support.ezfacility.com/hc/en-us/articles/4405051095195-How-to-Add-Venues, https://support.ezfacility.com/hc/en-us/articles/26569114691099-How-to-Add-Venues

### Set up lockers
- Actors: owner/admin.
- Preconditions: Lockers module enabled for the tenant.
- Steps:
  1. Add a locker room with name and gender.
  2. In the create-lockers tab, enter a start and end number and a size; repeat per size band.
  3. Define locker terms (name, start, end) and order them.
  4. Register padlocks with number and combination.
  5. Front desk can now rent lockers (Scheduling cluster flow).
- Rules/edge cases: disabled padlocks remain viewable until purged; overlapping number ranges are not addressed publicly (we reject duplicates within a room).
- Feature IDs involved: RES-07, RES-08, RES-09, PLT-14
- Evidence URLs: https://support.ezfacility.com/hc/en-us/articles/4405051209883-How-to-Set-Up-a-Locker-Rentals-in-EZFacility-Classic, https://support.ezfacility.com/hc/en-us/articles/4405044650779-How-to-Set-Up-Terms-for-Locker-Rentals-in-EZFacility-Classic, https://support.ezfacility.com/hc/en-us/articles/4405044678811-How-to-Manage-Lockers-in-EZFacility-Classic

### Onboarding data import (vendor-assisted)
- Actors: owner/admin; vendor support technician.
- Preconditions: account created; correct template chosen (Basic Contact, Advanced Contact or POS).
- Steps:
  1. Download the template for the import type.
  2. Fill it without renaming or adding columns; dates of birth in MM/DD/YYYY or DD/MM/YYYY.
  3. Advanced only: consult a support technician about per-membership-type details before submitting.
  4. Open the in-app support request, set ticket type to Import, attach the file, submit.
  5. Vendor staff validate and load the data; contacts, memberships/contracts, package balances, stored payment methods and (optionally) a first-term invoice are created.
  6. Customer verifies the result.
- Rules/edge cases: historical invoices and payments are never imported; first import free, later ones charged; missing columns need a support call; ambiguous DOB format is a data-quality risk (two accepted formats, no declared flag); schedules cannot be imported and leagues are rebuilt by hand.
- Feature IDs involved: IMP-01, IMP-02, ONB-03
- Evidence URLs: https://support.ezfacility.com/hc/en-us/articles/4404305442587-Submitting-a-Client-Data-Import-in-EZFacility-Classic, https://support.ezfacility.com/hc/en-us/articles/4405372124059-The-Three-Types-of-Imports-Available, https://support.ezfacility.com/hc/en-us/articles/34419970103963-The-Three-Types-of-Imports-Available, https://support.ezfacility.com/hc/en-us/articles/34419979004187-The-Three-Types-of-Imports-Available, https://www.youtube.com/watch?v=j4Rn9joKKpQ (t=28:34)

### Export client demographics
- Actors: owner/admin.
- Preconditions: permission to client administration.
- Steps:
  1. Open the export-clients tool.
  2. Choose which clients to include and whether to add membership information.
  3. Generate the report.
  4. Pick a file type (Excel, CSV, PDF, others) and export.
  5. Open or save the file.
- Rules/edge cases: no column picker; EU tenants need the per-client personal-data export instead for access requests (IMP-04).
- Feature IDs involved: IMP-03, IMP-04
- Evidence URLs: https://support.ezfacility.com/hc/en-us/articles/4405137464603-How-to-Export-Client-Demographic-Information, https://support.ezfacility.com/hc/en-us/articles/4402434192027-How-to-Set-Up-Your-New-Account

### Add a branded-app portal user
- Actors: portal admin; invitee.
- Preconditions: tenant has the branded/MemberMe+ app; at least one app location.
- Steps:
  1. Open user management in the app portal and add a user.
  2. Enter username, first name, last name, email.
  3. Decision: tick the admin flag (all locations) or leave unticked.
  4. Add the primary location; add further locations if needed.
  5. For each location choose "manage location" or "send notifications only".
  6. Save; the invitee receives an email with a link to set a password.
- Rules/edge cases: primary location is mandatory; logins can be deleted from the list.
- Feature IDs involved: PLT-13
- Evidence URLs: https://support.ezfacility.com/hc/en-us/articles/29244338187547-Creating-user-admin-profiles-for-MiGym-admin-portal-MemberMe-Branded-App

### Add a league-module user
- Actors: league Super User.
- Preconditions: signed in as the Super User.
- Steps:
  1. Open accounts and add a user.
  2. Fill all (required) detail fields.
  3. Choose access level: Admin, Scorekeeper or Advertising Manager.
  4. Save.
- Rules/edge cases: Admins cannot create or edit users; Advertising Manager is only offered where the advertising feature exists.
- Feature IDs involved: PLT-11
- Evidence URLs: https://support.ezfacility.com/hc/en-us/articles/26596341240091-How-to-Create-a-User-Account-in-EZLeagues, https://support.ezfacility.com/hc/en-us/articles/4405044353435-How-to-Create-a-User-Account, https://support.ezfacility.com/hc/en-us/articles/22122496577179-January-17th-2024-Release-Notes

### Handle a GDPR access or erasure request
- Actors: owner/admin or staff holding the permanent-delete permission; client.
- Preconditions: GDPR mode on for the location (PLT-16); for erasure, the user has the permanent-delete permission.
- Steps:
  1. Open the client's profile.
  2. Access request: choose "export client data"; an Excel file with the client's personal information downloads; hand it to the client.
  3. Erasure request or refused consent, decision: (a) a legitimate reason to keep the record exists (current member, outstanding invoice): keep it and tell the client; (b) the record should stay intact but inactive: disable the client instead; (c) otherwise continue to permanent delete.
  4. Choose permanent delete and type "delete" to confirm.
  5. System removes the personal information, stops and unmaps renewing memberships and packages, and leaves invoices, revenue and payments in place without a link to the person.
- Rules/edge cases: cannot be undone and the vendor holds no backup; accounting is not a reason to refuse, because financial rows survive deletion anyway; existing clients are kept until staff act; source is the spring 2018 launch demo, so labels may have changed.
- Feature IDs involved: IMP-04, PLT-16, PLT-04
- Evidence URLs: https://www.youtube.com/watch?v=C-7p_z3_Cxs (t=11:05, t=14:00, t=21:21, t=39:20)

## Scheduling, Rentals, Classes

### Configure an activity type and open it for online booking
- Actors: owner/admin
- Preconditions: location exists; revenue categories exist; package plans for the type exist if booking is to be package-gated.
- Steps:
  1. Create a reservation type: name, schedulable and/or sellable flags, revenue category, default capacity, colour, category, default free-booking flag.
  2. Order the list (order drives pickers).
  3. Open the type's online-booking options; either inherit the location default or override: listing mode (listed or unlisted), accepted package types, public description.
  4. Optionally grant staff users permission on the new type (new types inherit from existing permissions by default).
  5. System: type becomes selectable when creating reservations (if schedulable) and when selling packages (if sellable).
- Rules/edge cases: a sell-only type never appears on the calendar; deleting a type cascades to its package plans and strands holders' self-booking rights; capacity default is copied at reservation creation, not referenced live.
- Feature IDs: SCH-02, SCH-03, SCH-04, SCH-05, CLS-05
- Evidence: https://support.ezfacility.com/hc/en-us/articles/29783959046555-How-to-Set-Up-Reservation-Types-in-EZFacility-Classic, https://support.ezfacility.com/hc/en-us/articles/34440874732443-How-to-Set-Up-Reservation-Types-in-EZFacility-Classic, https://support.ezfacility.com/hc/en-us/articles/4402427203355-How-to-Set-Up-Reservation-Types, https://support.ezfacility.com/hc/en-us/articles/30058087582875-Managing-Self-Service-Shared-Bookings-in-EZFacility-Classic, https://support.ezfacility.com/hc/en-us/articles/34155834657819-July-3rd-2024-Release-Notes, https://support.ezfacility.com/hc/en-us/articles/17574439837467-August-2nd-2023-Release-Notes

### Publish bookable availability (single window or split slots)
- Actors: admin, trainer, front desk
- Preconditions: schedulable reservation type; trainer or venue column visible on the calendar.
- Steps:
  1. On the calendar choose date and the trainer/venue column; click an empty cell at the start time.
  2. Choose kind Session and the reservation type; defaults prefill.
  3. Adjust capacity, staff title, public title, self-booking flag, start and end.
  4. Decision: split? If yes pick the slot length; the window becomes N consecutive slots each with the stated capacity; end time is the end of the last slot.
  5. Decision: recurring? If yes go through the recurrence flow below.
  6. Save and finish, or save and go straight to adding clients.
  7. System: occurrences appear on the calendar with an "empty" fill marker and, when self-booking is on and the type is listed, on the client-facing schedule under the public title.
- Rules/edge cases: slot rows are independent reservations linked as one series (inferred); the public API can create sessions but not rentals/special blocks; NSE demo order: click an empty cell or Add Reservation > Add Session, pick type and venue (optionally with an instructor), decide buffer (location default or per-session), then Recurring yes/no and split on the same screen
- Feature IDs: SCH-07, SCH-06, SCH-09, SCH-18
- Evidence: https://support.ezfacility.com/hc/en-us/articles/4404311260571-How-to-Schedule-an-Available-Session-in-EZFacility-Classic, https://support.ezfacility.com/hc/en-us/articles/26498179644187-June-5th-2024-Release-Notes, https://support.ezfacility.com/hc/en-us/articles/4404311237659-How-to-Assign-Custom-Colors-to-Reservation-Types, https://www.youtube.com/watch?v=SzgMT6X961A (t=15:51, t=17:54)

### Generate a recurring series with preview
- Actors: scheduler/admin
- Preconditions: reservation kind and type chosen in the create dialog.
- Steps:
  1. Pick a pattern (daily, weekly, bi-weekly, monthly by date, yearly, nth weekday of month).
  2. Pick weekdays and the range (occurrence count or end date); for overnight operation set explicit start/end date-times.
  3. Generate occurrences; the preview lists them (rentals: each row flagged clear or conflicting).
  4. Optionally repeat generation with a different pattern or resource to stack more rows into the same series.
  5. Tick rows to delete or modify before committing.
  6. Commit; system writes all occurrences as one linked series.
- Rules/edge cases: series of 1,500+ occurrences must commit without timeout; an end at exactly midnight must not roll to the next date; conflicts shown in preview must still be enforced at commit (our DB constraint) because another user may book in between; NSE form asks Recurring = yes, Custom, every N weeks, weekdays, and an end by count or date; the start date's weekday must stay ticked or the pattern errors (restart on the right day)
- Feature IDs: SCH-09, SCH-12, SCH-13
- Evidence: https://support.ezfacility.com/hc/en-us/articles/4404311308571-How-to-Create-Recurring-Sessions-in-EZFacility-Classic, https://support.ezfacility.com/hc/en-us/articles/36516396025115-April-23rd-2025-Release-Notes, https://support.ezfacility.com/hc/en-us/articles/17981009155995-August-16th-2023-Release-Notes, https://support.ezfacility.com/hc/en-us/articles/4407310264475-How-to-Add-Additional-Rentals-to-an-Existing-Rental-in-EZFacility-Classic, https://www.youtube.com/watch?v=SzgMT6X961A (t=17:54), https://www.youtube.com/watch?v=7JVYZ3kxUAo (t=15:34)

### Mass-edit or delete part of a series
- Actors: scheduler/admin
- Preconditions: a linked series exists.
- Steps:
  1. Open any occurrence. For a one-off change edit the field in place and stop.
  2. Otherwise open the linked-occurrences list; filter by date range (typically future only); tick rows or select all.
  3. Decision: delete or modify.
  4. Modify: fill only the fields to change (e.g. capacity, time, type); preview shows affected rows highlighted.
  5. Delete: rows are flagged as pending deletion; confirm.
  6. Finish to commit.
  7. Fast path: enable delete mode on the calendar, click an occurrence, choose scope (this one, all, today's, past, future, custom).
- Rules/edge cases: empty mass-edit fields are ignored; type-level capacity edits never propagate to existing occurrences, so this flow is the only way to change them in bulk; behaviour for occurrences that already have participants or invoices is undocumented; series built from several patterns are edited one pattern at a time; delete mode is offered only in the timeline Day view; NSE does not propagate a rename across the series; two series can first be merged by reservation number so they share one linked list (SCH-21)
- Feature IDs: SCH-10, SCH-11, CLS-04
- Evidence: https://support.ezfacility.com/hc/en-us/articles/4404311272731-How-to-Edit-a-Reservation-in-EZFacility-Classic, https://support.ezfacility.com/hc/en-us/articles/4404311324443-How-to-Edit-Class-Sizes-in-EZFacility-Classic, https://support.ezfacility.com/hc/en-us/articles/4404311287451-Deleting-Reservations-using-Delete-Mode-in-EZFacility-Classic, https://support.ezfacility.com/hc/en-us/articles/4404311326875-How-to-Delete-Reservations-Delete-Mode-in-EZFacility-Classic, https://support.ezfacility.com/hc/en-us/articles/23864931136795-Deleting-or-Removing-a-Booking-or-Session-on-the-Schedule (title only, body not read), https://www.youtube.com/watch?v=Rjy8ZpfIA68 (t=42:04), https://www.youtube.com/watch?v=7JVYZ3kxUAo (t=24:49, t=25:50), https://www.youtube.com/watch?v=SzgMT6X961A (t=44:42)

### Block time on a resource or trainer
- Actors: admin/scheduler
- Preconditions: none.
- Steps:
  1. Click a cell on a trainer or venue column; choose kind Special and a subtype (floor hours, program instruction, unpaid time, unavailable).
  2. Set start/end, optional title, optional recurrence; save.
  3. System: block occupies the resource; no participants can be added; trainer blocks flow to payroll/commission reporting; an "unavailable" venue block removes the venue from online rental search for that span.
- Rules/edge cases: subtypes carry payroll meaning (paid floor/instruction vs unpaid) (inferred from names and payroll report inclusion).
- Feature IDs: SCH-08, SCH-18, RNT-05
- Evidence: https://support.ezfacility.com/hc/en-us/articles/4404311270683-Scheduling-a-Special-Reservation-in-EZFacility-Classic

### Register a client into one or many sessions and run the roster
- Actors: front desk/admin/trainer
- Preconditions: session exists with free capacity; client holds a package of an accepted type, or the session allows free booking.
- Steps:
  1. Click the session on the calendar; choose register client.
  2. Find the client (disabled clients are not offered) or create one.
  3. Decision: no eligible package -> sell a package first, then return.
  4. Decision: exactly one eligible package and speed-register on -> package auto-selected. Otherwise pick the package.
  5. Choose scope: this session only, all linked sessions (full ones skipped), or a custom subset.
  6. System: creates one booking per chosen occurrence, reserves package sessions, recolours fill markers (partial/full), shows the roster.
  7. On the roster: mark attendance, open participant info, view package/invoice/balance and take payment, remove a participant, see next booked session, email all or selected participants.
  8. If the session is full the client may be waitlisted; when a place frees up the system books the first waitlisted client automatically.
- Rules/edge cases: occurrence capacity overrides type capacity (including type capacity 0); virtual-meeting links go only to scheduled/reserved/attended participants; shared-package holders are promoted from waitlist like owners; decision at early cancel: rebook into an alternative date found by search, or return the session to the package; waitlist promotion in the member app is either automatic queue or open first-click
- Feature IDs: CLS-01, CLS-02, CLS-03, CLS-05, CLS-06, SCH-06
- Evidence: https://support.ezfacility.com/hc/en-us/articles/4402427209115-Registering-A-Client-Into-a-Single-Available-Session, https://support.ezfacility.com/hc/en-us/articles/27849876503323-Registering-A-Client-Into-Multiple-Available-Sessions, https://support.ezfacility.com/hc/en-us/articles/24695840840603-April-10th-2024-Release-Notes, https://support.ezfacility.com/hc/en-us/articles/22122496577179-January-17th-2024-Release-Notes, https://support.ezfacility.com/hc/en-us/articles/19132331777307-September-27th-2023-Release-Notes, https://support.ezfacility.com/hc/en-us/articles/34155834657819-July-3rd-2024-Release-Notes, https://www.youtube.com/watch?v=TWNQ4cTiEFs (t=42:16), https://www.youtube.com/watch?v=oNHKhlv39qo (t=55:17)

### Staff books a court/field rental and invoices it
- Actors: front desk/admin; renter
- Preconditions: rental type and at least one rate (or staff will key a custom rate); venue(s) exist.
- Steps:
  1. Click an empty cell; optionally multi-select several venue columns.
  2. Choose kind Rental, set title and start/end; optionally flag for display on the public league site.
  3. Optional recurrence: pattern, weekdays, range; generate occurrences (repeatable); review conflicts.
  4. Find or create the client.
  5. Choose a predefined rate or enter a custom rate. System computes quantity per the rate's basis (hours, occurrences, flat) and multi-resource mode, and builds billing lines per the rate's billing-item mode.
  6. Decision: charge now (add to cart) or no charge (bill later / free).
  7. Decision: single invoice now, or leave in cart to combine with other purchases.
  8. Take payment, print or email the invoice, finish.
  9. System: occurrences appear in the rental colour titled with the client's name.
- Rules/edge cases: taxes deselected at creation must not reappear on the invoice; $0 rental types are valid; autopay flag chosen at payment is stored on the invoice; demo order in the New UI: tick resource(s), choose rental type, set end time by hand (not pre-filled), attach a client (mandatory), pick rate, then decision on invoice option (multiple per occurrence, single, add to open invoice, date-based) before the payment screen; More options holds revenue date, coupon and discount; a second client can be added later; payment-step decision when the client holds a rental plan: use plan, one-time rate, or sell a plan
- Feature IDs: RNT-01, RNT-02, RNT-03, RNT-13, SCH-09, SCH-12, SCH-13
- Evidence: https://support.ezfacility.com/hc/en-us/articles/4404308503195-How-to-Schedule-a-Rental-Reservation-in-EZFacility-Classic, https://support.ezfacility.com/hc/en-us/articles/29859659205787-How-to-Set-Up-Rental-Rates-in-EZFacility-Classic, https://support.ezfacility.com/hc/en-us/articles/29852788198427-How-to-Set-Up-Rental-Types-in-EZFacility-Classic, https://support.ezfacility.com/hc/en-us/articles/18741009680795-September-13th-2023-Release-Notes, https://support.ezfacility.com/hc/en-us/articles/16308423683355-June-12th-2023-Release-Notes, https://www.youtube.com/watch?v=7JVYZ3kxUAo (t=05:18, t=17:35, t=22:46), https://www.youtube.com/watch?v=SzgMT6X961A (t=21:00), https://www.youtube.com/watch?v=ERaBaf5YWHo (t=16:20)

### Extend an existing rental and add it to an open invoice
- Actors: front desk/admin
- Preconditions: a linked rental series with a client.
- Steps:
  1. Open the rental; choose add more.
  2. Define pattern/range, generate; rows show clear vs conflict; fix or drop conflicting rows; repeat the pass for each additional resource.
  3. Finish; reopen the linked list, clear filters, tick the new (unbilled) occurrences.
  4. Bill selected: confirm the client; choose predefined or custom rate; choose one combined line or one line per occurrence.
  5. Route the lines: several new invoices (one per line), a single new invoice, date-based invoices, an existing open invoice, or the cart.
  6. Print/email, take payment, done.
- Rules/edge cases: reservation creation and billing are separate transactions, so unbilled occurrences can exist indefinitely (reporting gap; we should expose an "unbilled rentals" view, inferred need).
- Feature IDs: RNT-04, RNT-02, SCH-10
- Evidence: https://support.ezfacility.com/hc/en-us/articles/4407310264475-How-to-Add-Additional-Rentals-to-an-Existing-Rental-in-EZFacility-Classic

### Enable online rentals and let a client self-book
- Actors: admin; client (member or public)
- Preconditions: rental type and rate exist; portal enabled.
- Steps:
  1. Admin opens the rental type's online settings: enable self-booking, choose allowed venues, bind the rate, set minimum lead time and min/max length, optionally require an active paid-to-date membership.
  2. Client opens rentals on the portal and searches by type, length, venue and weekday(s).
  3. System returns only free slots on allowed venues, on the hour, outside the cut-off, excluding venues blocked unavailable.
  4. Client selects a slot; system checks eligibility (membership requirement) and holds/creates the booking.
  5. Client pays (or defers, where pay-later is allowed; $0 types skip payment; a rental-plan balance may be applied instead).
  6. System confirms, emails confirmation with invoice copy, shows the rental on the staff calendar.
- Rules/edge cases: conflict must be re-checked atomically at confirmation; deposits/capacity are marketed but undocumented; no public description of a hold/timeout during checkout; NSE setup adds Access = self-book, default/min/max length, buffers, optional rental-plan allow-list and client eligibility; a logged-in member is offered the member rate first; a rental type linked to sub-venues exposes only those children online; one court per online transaction
- Feature IDs: RNT-05, RNT-06, RNT-01, RNT-02, RNT-07, RNT-09, SCH-12
- Evidence: https://support.ezfacility.com/hc/en-us/articles/22938731158811-How-to-set-up-Rentals-For-Self-Service, https://www.ezfacility.com/blog/features-and-fixes-online-rentals, https://support.ezfacility.com/hc/en-us/articles/16731304236571-June-28th-2023-Release-Notes, https://support.ezfacility.com/hc/en-us/articles/16308423683355-June-12th-2023-Release-Notes, https://support.ezfacility.com/hc/en-us/articles/4404311270683-Scheduling-a-Special-Reservation-in-EZFacility-Classic, https://support.ezfacility.com/hc/en-us/articles/4404312822811-Online-Webinar-How-to-Set-Up-Online-Rentals-in-EZFacility-Classic, https://www.youtube.com/watch?v=SzgMT6X961A (t=08:43, t=34:24, t=37:27, t=53:00), https://www.youtube.com/watch?v=ERaBaf5YWHo (t=19:25)

### Sell and redeem a prepaid rental plan
- Actors: admin, front desk, client
- Preconditions: rental types exist; plan sales enabled for the portal if clients are to self-purchase.
- Steps:
  1. Admin defines a plan: linked rental type(s), model (hours or occurrences), quantity, member and non-member price, start/expiry, auto-renew.
  2. Sale: from the admin plan list, the client's profile tab, at checkout while booking a rental, or by the client on the portal (terms acknowledgement on first or every purchase if configured).
  3. System records the purchase with an opening balance.
  4. Booking: when a rental of a linked type is booked, the balance is offered as tender; system debits hours or one occurrence.
  5. Cancellation of that booking credits the balance back automatically.
  6. At expiry: auto-renew plans roll into a new term (charging the stored payment method, inferred); others lapse.
  7. Manager can share the plan with another client, or remove and refund it.
  8. Owner runs the plan-sales report for sales and outstanding balance.
- Rules/edge cases: per-hour plans must handle fractional/mixed lengths; treatment of unused balance on renewal and proration on refund are undocumented; demo order: plan settings screen then pricing screen; three sale paths (manager-only admin list, client profile Rental plans tab, schedule payment step); decision for recurring rentals: balance must cover every occurrence, else sell another plan or charge the rate; removal decision: reverse billing and remove (irreversible), delete but keep billing, or open the invoice
- Feature IDs: RNT-09, RNT-10, RNT-11, RNT-12, RNT-06
- Evidence: https://www.ezfacility.com/blog/introducing-rental-plans-prepaid-rentals-made-simple, https://www.youtube.com/watch?v=ERaBaf5YWHo, https://support.ezfacility.com/hc/en-us/articles/57003799901851-How-to-Create-a-New-Rental-Plan (title only, body not read), https://support.ezfacility.com/hc/en-us/articles/57004869280027-How-to-Share-a-Rental-Plan (title only, body not read), https://support.ezfacility.com/hc/en-us/articles/57004883480731-How-to-Remove-and-Refund-a-Rental-Plan (title only, body not read), https://support.ezfacility.com/hc/en-us/articles/57004872733211-How-to-Run-the-Rental-Plan-Sales-Report (title only, body not read), https://www.youtube.com/watch?v=ERaBaf5YWHo (t=06:09, t=09:11, t=13:13, t=14:14, t=17:20)

### Private or shared booking via direct link
- Actors: trainer/coach/admin; clients
- Preconditions: package plan exists and is purchasable online; for auto-sharing, client relationships exist before the sale.
- Steps:
  1. (Private) create a reservation type whose listing overrides the location default to unlisted; set accepted packages and description.
  2. Put the session on the calendar.
  3. Copy the session's direct registration link; email it to one or many clients (profile email, optional saved template).
  4. Client opens the link, signs in, buys the package if needed, and is booked; the session shows under their schedule.
  5. Variant combined cost: session capacity 1; package priced for two and auto-shared with the related person; one session is deducted for both.
  6. Variant team: coach buys (or receives) a team package that auto-shares to related players; each player self-books practices at no charge.
- Rules/edge cases: relationship created after the sale does not trigger auto-share (share manually); the link also works for listed sessions; unlisted sessions are invisible without the link.
- Feature IDs: SCH-16, SCH-17, SCH-03, CLS-09
- Evidence: https://support.ezfacility.com/hc/en-us/articles/30058010593563-How-to-Share-a-Direct-Registration-Link-for-a-Session-in-EZFacility-Classic, https://support.ezfacility.com/hc/en-us/articles/30058087582875-Managing-Self-Service-Shared-Bookings-in-EZFacility-Classic, https://support.ezfacility.com/hc/en-us/articles/4404305610651-Managing-Self-Service-Shared-Bookings-in-EZFacility-Classic

### Equipment rental: checkout at POS and return
- Actors: cashier/front desk
- Preconditions: equipment categories and items exist; a register is open.
- Steps:
  1. Open POS, choose the register (by location).
  2. Switch the item panel to equipment; search or tap the item.
  3. Attach a client (search by at least three leading letters, or create one). Mandatory.
  4. Adjust quantity or price on the cart line; add other products if wanted; complete payment.
  5. System records the loan against the client with due date/time from the item's allowed days and return time (inferred), and marks the unit(s) checked out.
  6. Return: from the client profile's checked-out list or from the equipment tab, find the loan and mark returned; item shows available in POS again.
- Rules/edge cases: late and replacement fees are informational; staff charge them manually; rental sale without a client is rejected.
- Feature IDs: RNT-14, RNT-15, RNT-16
- Evidence: https://support.ezfacility.com/hc/en-us/articles/34418766995099-How-to-Set-Up-Equipment-in-EZFacility-Classic, https://support.ezfacility.com/hc/en-us/articles/34418782382235-How-to-Rent-Equipment-in-EZFacility-Classic, https://support.ezfacility.com/hc/en-us/articles/34418804557467-How-to-Return-Equipment-Rentals-in-EZFacility-Classic, https://support.ezfacility.com/hc/en-us/articles/34418934806171-How-to-Set-Up-Rental-Equipment-in-EZFacility-Classic

### Rent and release a locker
- Actors: front desk/admin
- Preconditions: locker rooms, lockers and terms configured (resources cluster).
- Steps:
  1. Open the locker room, search lockers, choose rent on a free locker.
  2. Find or create the client; choose the contract term (day, week, year or a custom term).
  3. Choose a predefined fee or enter one; add to cart or mark no charge.
  4. Invoice now (single invoice) or leave in cart to combine with membership/package purchases.
  5. Release: clear a single locker, or bulk-clear all expired assignments.
- Rules/edge cases: no automatic release at expiry is described; expiring/assigned locker reports exist in the reporting cluster.
- Feature IDs: RNT-17, RNT-18
- Evidence: https://support.ezfacility.com/hc/en-us/articles/4405044656411-How-to-Rent-a-Locker-in-EZFacility-Classic, https://support.ezfacility.com/hc/en-us/articles/4405044668699-How-to-Clear-an-Expired-Locker-in-EZFacility-Classic

### Advertise a class/clinic on the public league site
- Actors: league-site admin
- Preconditions: league site enabled; optionally a Group with online registration.
- Steps:
  1. Add a class/clinic entry with title, sport, start date, description.
  2. Paste the Group's registration link if sign-up should be offered.
  3. Publish; edit or delete later.
- Rules/edge cases: no capacity or enrolment data is synchronised; it is a static card with an outbound link.
- Feature IDs: CLS-07, CLS-10
- Evidence: https://support.ezfacility.com/hc/en-us/articles/10414727616795-How-to-Manage-your-Classes-Clinics-in-EZLeagues, https://support.ezfacility.com/hc/en-us/articles/4405044308251-How-to-Manage-your-Classes-Clinics

## Clients, Households, Waivers & Documents, Fitness Assessments

### Create a client and grant portal access (staff)
- Actors: front desk, client
- Preconditions: field policy configured (CLI-04); staff has client-create permission.
- Steps:
  1. Staff opens the client list and starts Add Client (side panel in New UI).
  2. System renders the fields for the staff context; required ones are marked; names are always required.
  3. Staff enters data, adds one or more emails, optionally category, referral, default trainer/salesperson, tags, emergency contacts, photo.
  4. On submit the system validates required fields, creates the record (submit is single-fire to avoid double creation), stamps created-by/at, and sends an email-verification message to the address.
  5. Record appears at the top of the user's recents. Decision: if portal access is wanted and an email exists, staff ticks Enabled in the Self-Service block; system sends an invitation and records the invite date; client chooses username and password.
  6. Staff can later trigger a password reset from the same block.
- Rules/edge cases: no email means no portal enablement and no emailed documents; unverified email blocks emailed documents and bulk sends in the New UI; inline creation from membership sale or document wizard follows the same validation.
- Feature IDs: CLI-01, CLI-02, CLI-04, CLI-15, CLI-12
- Evidence: https://support.ezfacility.com/hc/en-us/articles/30146189430171-Adding-a-Client-Profile-to-the-New-EZFacility-Experience, https://support.ezfacility.com/hc/en-us/articles/9061322036635-How-to-Send-a-Self-Service-Invitation-Through-the-Client-Profile, https://support.ezfacility.com/hc/en-us/articles/18408526583067-August-31st-2023-Release-Notes, https://support.ezfacility.com/hc/en-us/articles/4405137459995-Client-Management

### Configure client field policy and custom fields
- Actors: owner/admin
- Preconditions: admin access to client settings.
- Steps:
  1. Open Contact Preferences.
  2. Label up to six custom slots; a slot becomes configurable only after it has a label.
  3. For each field and each context (staff add, group online registration, self-service completion) choose hidden, optional or required; locked system fields cannot be changed.
  4. Set gender visibility/requirement and the default gender.
  5. Save; the three surfaces immediately render and validate against the new policy.
- Rules/edge cases: Classic offers required-only ticks; New offers tri-state plus locked; one article says seven custom fields while listing six.
- Feature IDs: CLI-04, CLI-05
- Evidence: https://support.ezfacility.com/hc/en-us/articles/4402427177115-How-to-Set-Up-Contact-Preferences, https://support.ezfacility.com/hc/en-us/articles/4402434184475-How-to-Set-Up-Required-Fields-for-Self-Service-Registration, https://support.ezfacility.com/hc/en-us/articles/29861551814171-How-to-Set-Up-Contact-Preferences-in-EZFacility-Classic, https://support.ezfacility.com/hc/en-us/articles/25134483797531-April-24th-2024-Release-Notes

### Find and merge duplicate clients
- Actors: admin, front desk
- Preconditions: two or more profiles for the same person.
- Steps:
  1. Open the Possible Duplicates view (heuristic: partial first name + full last name + phone) or search manually.
  2. Tick the candidate rows and choose Merge Duplicates.
  3. Decision (New UI): if losing profiles hold memberships or group registrations, cancel them first.
  4. Pick the profile to retain; system warns if the merge would leave multiple active memberships; confirm Merge.
  5. System re-points invoices, reservations, group memberships and similar children to the survivor; with exactly two records it back-fills blank survivor fields (not stored cards or interests); losers are deleted (Classic) or disabled (New).
  6. Survivor profile is shown.
- Rules/edge cases: irreversible; no un-merge documented; a separate confirm dialog was removed in 2024.
- Feature IDs: CLI-13, CLI-03, CLI-14
- Evidence: https://support.ezfacility.com/hc/en-us/articles/4405144383003-Merging-Duplicate-Clients, https://support.ezfacility.com/hc/en-us/articles/28071987897371-How-to-Merge-Client-Profiles, https://support.ezfacility.com/hc/en-us/articles/25134483797531-April-24th-2024-Release-Notes

### Disable a client
- Actors: admin
- Preconditions: profile open.
- Steps:
  1. Choose Disable Client from the profile action menu and confirm.
  2. System flags the client disabled; the client no longer appears in session-registration search or self check-in; history and invoices remain reportable (active vs deleted split on receivables reporting).
- Rules/edge cases: re-enable path, effect on active memberships/autopay and on portal login are not documented.
- Feature IDs: CLI-14
- Evidence: https://support.ezfacility.com/hc/en-us/articles/27849984397979-How-to-Disable-a-Client, https://support.ezfacility.com/hc/en-us/articles/22122496577179-January-17th-2024-Release-Notes

### Log an interaction or assign a follow-up task
- Actors: staff, assignee
- Preconditions: subject list optionally seeded (CLI-10).
- Steps:
  1. On the client, start Log an Activity (or Add Activity) or Create New Task.
  2. Choose type (Phone, Email, Task, Other) and subject, or create a subject inline.
  3. Choose the staff user (performer for an activity, assignee for a task), optionally attach a file, write the message.
  4. For a task set status, due date and, on completion, completion date.
  5. Save. Activity appears in the client's history; a task appears in the client's active list and increments the assignee's header counter.
  6. Manager runs the Task/Activity report with filters to review workload.
- Rules/edge cases: attachments are internal only and are the documented way to store arbitrary files on a client; task status values are not published.
- Feature IDs: CLI-09, CLI-10, CLI-11
- Evidence: https://support.ezfacility.com/hc/en-us/articles/4405137428507-How-to-Log-Client-Activity-in-EZFacility-Classic, https://support.ezfacility.com/hc/en-us/articles/4405137471643-Creating-a-Task, https://support.ezfacility.com/hc/en-us/articles/4405137446427-How-to-Create-Activity-Subjects-for-Tasks-and-Activities, https://support.ezfacility.com/hc/en-us/articles/15851993226139-How-to-Upload-a-Document-to-a-Client-Profile

### Link a family and share a membership or package (staff)
- Actors: front desk, admin
- Preconditions: every family member has their own profile; the contract/package holder is created last.
- Steps:
  1. On the holder's profile add a relationship per family member: pick type as read from the holder, search the other client, Add, then Save the profile.
  2. System shows the inverse relationship on the other profile.
  3. Sell the membership or package to the holder. Side-effect: if a package (standalone or bundled in the membership) is flagged to allow sharing, it is auto-shared with related clients at sale.
  4. Otherwise open the Membership or Packages tab, choose Share, tick related clients and/or search unrelated clients, save.
  5. Shared clients can now check in / book against the shared entitlement.
- Rules/edge cases: relationships do not chain; a relationship alone conveys no entitlement; relationship not saved until the profile save; API reports client count and billed total for shared contracts; rental plans follow the same pattern from the client's Rental plans tab, with sharing enabled on the plan and shown for related clients only; vendor advice is to sell a child's membership on the child's profile with the parent's billing details and share only genuinely multi-user contracts; the preset staff role cannot share by default.
- Feature IDs: FAM-01, FAM-04, FAM-05, FAM-06
- Evidence: https://support.ezfacility.com/hc/en-us/articles/4401990000411-How-to-Share-a-Membership, https://support.ezfacility.com/hc/en-us/articles/22132354311067-How-to-Share-a-Package-Plan, https://support.ezfacility.com/hc/en-us/articles/27907266866715-How-to-Establish-Relationships-between-Clients-on-their-Profiles, https://support.ezfacility.com/hc/en-us/articles/4405144396955-Establishing-Relationship-Between-Clients, https://www.youtube.com/watch?v=ERaBaf5YWHo (t=14:14), https://www.youtube.com/watch?v=KAN6h9vPUiM (t=09:14)

### Manage a household in self-service and transact on behalf
- Actors: client/parent, related adult
- Preconditions: parent has an enabled portal login.
- Steps:
  1. Parent opens Relationships under their name and chooses Add Relationship with a type (e.g. Child).
  2. Decision: new person: parent enters the person's details (may reuse own email); profile and link are created immediately. Existing account: parent finds the person by name; system emails that person; link stays pending until they confirm.
  3. When buying a membership or package the parent selects which person it is for; payment uses the parent's stored method and billing address.
  4. When booking a session or rental the parent filters/selects the person ("Book For"); for rentals supplies location, rental type, one venue, weekdays, search start date, length and hour-level start time, then completes checkout.
  5. My Schedule can be filtered per person.
- Rules/edge cases: only related people are selectable; purchase works for relatives with no portal registration of their own; one venue per rental booking.
- Feature IDs: FAM-02, FAM-03, FAM-05
- Evidence: https://support.ezfacility.com/hc/en-us/articles/25312556816539-Create-and-Manage-Relationships-in-Self-Service, https://support.ezfacility.com/hc/en-us/articles/22132354311067-How-to-Share-a-Package-Plan, https://support.ezfacility.com/hc/en-us/articles/17574439837467-August-2nd-2023-Release-Notes

### Author a document template and bind it to services
- Actors: owner/admin
- Preconditions: none.
- Steps:
  1. Open Document Templates, choose create (or edit an existing one from the recent list).
  2. Choose type (Client Document; GDPR Consent where enabled), enter name, description (becomes the document subject), body (paste as plain text if needed) and the acceptance statement (max 1,000 chars).
  3. Preview, then save.
  4. Bind: on a membership plan set Default Document; for group registrations pick the single account-wide Document in Online Registration settings; package plans have the same document field at the bottom of the plan's main details page; for groups also switch on Allow Online Waiver Fulfilment or the document is not enforced.
- Rules/edge cases: one document per plan; the group document applies to all groups; no inline initials/signature blocks; editing a template has no documented effect on already-issued documents (no versioning); no binding for rentals or POS items; links are added through the editor's hyperlink manager.
- Feature IDs: DOC-01, DOC-08
- Evidence: https://support.ezfacility.com/hc/en-us/articles/11840312242331-Creating-Document-Templates-in-EZFacility, https://support.ezfacility.com/hc/en-us/articles/27663085801883-Editing-Document-Templates-in-EZFacility, https://support.ezfacility.com/hc/en-us/articles/27662401294875-How-to-Connect-Documents-to-Services, https://support.ezfacility.com/hc/en-us/articles/4411661820955-How-use-Documents-to-Create-Membership-Waivers-for-Self-Service, https://support.ezfacility.com/hc/en-us/articles/4404305716251-Creating-and-Editing-Document-Templates-in-EZFacility-Classic, https://www.youtube.com/watch?v=zzEUXdDPMyU (t=09:21), https://www.youtube.com/watch?v=VuUR1Y9bhjQ (t=10:15)

### Issue a document to a client (digital, email or paper)
- Actors: front desk, client, optional co-signer
- Preconditions: template exists; for email, client has an email (verified in New UI).
- Steps:
  1. Start Generate Document from the client's Documents tab or from the admin Documents area (select or create the client).
  2. Pick the template by search or from recents; choose the acceptance path.
  3. Digital in person: client reads on screen, ticks the acceptance statement or draws a signature (touch, mouse or pad); optional co-signer name; save. Status Signed.
  4. Email: preview, Save and Email, choose recipient addresses. Status Pending; client follows the link and accepts or declines; on acceptance status becomes Signed; expired links must be re-sent.
  5. Paper: system produces a PDF to print; staff uploads the signed PDF scan, which sets the signed flag (can be cleared); save. Status Signed if flagged, else Pending.
  6. Result screen offers finish, email a copy, print, or start another document. The document is listed on the client's Documents tab and in account-wide Document History.
- Rules/edge cases: link lifetime documented as 24h and 48h in different articles; upload must be PDF; history rows support view, email, delete; the acceptance record carries IP address, date/time and generating user; staff are not notified when an emailed document is signed and there are no unsigned-document reminders; a deleted document shows as Deleted and is recoverable for 30 days; the paper path doubles as the upload route for outside paperwork because clients cannot upload in the portal; a minor's document can take a child signature plus a separate guardian signature.
- Feature IDs: DOC-02, DOC-03, DOC-04, DOC-05, DOC-06, DOC-12
- Evidence: https://support.ezfacility.com/hc/en-us/articles/4404308609179-Generating-a-Document-with-Digital-Acceptance-in-EZFacility-Classic, https://support.ezfacility.com/hc/en-us/articles/4404308612891-Generating-a-Document-with-Acceptance-by-Email-in-EZFacility-Classic, https://support.ezfacility.com/hc/en-us/articles/4404314931483-Generating-a-Document-to-Print-Paper-Acceptance-in-EZFacility-Classic, https://support.ezfacility.com/hc/en-us/articles/4402426437275-Generating-a-Document-from-a-Client-s-Account, https://support.ezfacility.com/hc/en-us/articles/4411809532187-How-use-Documents-to-Create-Membership-Waivers-when-selling-a-Membership-in-person, https://support.ezfacility.com/hc/en-us/articles/4404308614811-How-to-View-Document-History-in-EZFacility-Classic, https://www.youtube.com/watch?v=zzEUXdDPMyU (t=06:15), https://www.youtube.com/watch?v=KAN6h9vPUiM (t=28:49), https://www.youtube.com/watch?v=TWNQ4cTiEFs (t=23:38)

### Audit missing documents and bulk send
- Actors: admin
- Preconditions: template exists.
- Steps:
  1. Open Audit Clients > Documents and choose a template.
  2. System lists clients who have never been issued that document.
  3. Select all or some; send. System creates a Pending document per client and emails the link; a summary count is shown.
  4. Later, filter Document History by Pending to find non-responders and re-send individually.
- Rules/edge cases: no category/tag targeting; clients without a verified email are skipped (New); audit shows "not issued", not "not signed".
- Feature IDs: DOC-07, DOC-06, DOC-04
- Evidence: https://support.ezfacility.com/hc/en-us/articles/38072534577307-How-to-send-Documents-in-en-mass, https://support.ezfacility.com/hc/en-us/articles/4404308617115-Using-Client-Audit-with-Documents, https://support.ezfacility.com/hc/en-us/articles/4404312856731-Using-Client-Audit-with-Documents

### Enable GDPR and capture consent
- Actors: owner/admin, front desk, client
- Preconditions: location in a GDPR jurisdiction.
- Steps:
  1. Admin ticks Enable GDPR on the location and saves. Decision: if no GDPR template exists the system prompts and redirects to template creation.
  2. Admin creates the single GDPR Consent template (name, description up to 240 chars, body, acceptance wording; vendor GDPR text is linked automatically).
  3. Profiles without consent show a GDPR banner; from then on, creating a client opens a consent pop-up that the client ticks personally.
  4. Staff generates the GDPR document from the profile: email (verified address, link valid 48h) or on-screen acceptance.
  5. On acceptance the document is stored, the banner clears, and staff can email or print the signed copy.
- Rules/edge cases: only one GDPR template may exist; bulk route is the audit flow; only the GDPR Consent document type logs consent; verbal or paper consent is logged with the paper acceptance type; deleting the consent document brings the banner back; a client who refuses consent is either permanently deleted (IMP-04) or kept only with a business reason.
- Feature IDs: DOC-09, DOC-01, DOC-04, DOC-07
- Evidence: https://support.ezfacility.com/hc/en-us/articles/38068447234331-How-to-Enable-GDPR-on-EZFacility, https://support.ezfacility.com/hc/en-us/articles/38068886342171-How-to-Create-a-GDPR-Document, https://support.ezfacility.com/hc/en-us/articles/38071098727067-How-to-Send-a-GDPR-Document-to-a-client-from-their-profile, https://www.youtube.com/watch?v=C-7p_z3_Cxs (t=13:08)

### Sell a membership with mandatory document acceptance
- Actors: client (online) or front desk + client (in person)
- Preconditions: plan has a Default Document; plan is sellable online for the portal path.
- Steps:
  1. Buyer (or staff) selects the plan and proceeds to checkout.
  2. System inserts an acceptance step for the plan's document.
  3. Online: client must accept to complete the purchase. In person: staff picks paper, digital checkbox, drawn signature, or email (Pending until returned).
  4. Payment completes; signed/pending document is attached to the client's Documents tab and visible in Document History.
- Rules/edge cases: one document per plan; acknowledged once at sale; emailed waiver in this flow is documented with a 24h acceptance window; a defect where the step was skipped on the first attempt was fixed in 2025; whether an unsigned (Pending) document blocks check-in is not stated; package plans differ: at the desk the sale forces acknowledgement, but an online package purchase completes unsigned and leaves a Pending document on the profile; accepting a plan document does not tick the profile waiver checkbox.
- Feature IDs: DOC-08, DOC-02, DOC-03, DOC-04, DOC-05
- Evidence: https://support.ezfacility.com/hc/en-us/articles/4411661820955-How-use-Documents-to-Create-Membership-Waivers-for-Self-Service, https://support.ezfacility.com/hc/en-us/articles/4411809532187-How-use-Documents-to-Create-Membership-Waivers-when-selling-a-Membership-in-person, https://support.ezfacility.com/hc/en-us/articles/36516396025115-April-23rd-2025-Release-Notes, https://www.youtube.com/watch?v=zzEUXdDPMyU (t=09:21)

### Execute a legacy membership agreement (Classic)
- Actors: owner/admin (template), front desk, client
- Preconditions: advanced membership contract sold; agreement template configured.
- Steps:
  1. Admin configures the three sections, included contract fields, and required signer roles per section; optionally allows the agreement online.
  2. After selling a contract, staff clicks Create in the Agreement column of the client's Membership tab; agreement opens in a pop-up.
  3. Export (Word/PDF) or print; client signs on the pad for each required signer role, or staff toggles the signed flag when no pad exists; system warns on missing required signatures.
  4. Later, View/Edit from the same tab.
- Rules/edge cases: pop-up blockers break the flow; print icon is IE-only; replaced by plan-bound documents on New-UI accounts; online purchase (2016): with Allow Online Agreement on, the portal shows the agreement before checkout, the checkbox tick counts as the signature and the client can email themselves a copy; with it off the step is skipped and the contract is signed at the next visit.
- Feature IDs: DOC-10, DOC-11, DOC-12
- Evidence: https://support.ezfacility.com/hc/en-us/articles/29852220977051-Setting-Up-a-Membership-Agreements-in-EZFacility-Classic, https://support.ezfacility.com/hc/en-us/articles/29852081983387-Creating-a-Membership-Contract-Agreement-in-EZFacility-Classic, https://support.ezfacility.com/hc/en-us/articles/4404308371995-Viewing-A-Membership-Contract-Agreement-in-EZFacility-Classic, https://support.ezfacility.com/hc/en-us/articles/29852227776923-Enabling-Membership-Agreements-when-Selling-Memberships-Online-in-EZFacility-Classic, https://www.youtube.com/watch?v=SDO3SkkHTlY (t=08:20)

### Connect an external waiver provider and ingest signed waivers
- Actors: owner/admin, client
- Preconditions: tenant has a Smartwaiver account and a generated API v4 key (shown once by the provider); the vendor has enabled the integration module on the account (request via Support Center partner form or account manager; $10 per month add-on).
- Steps:
  1. Admin enters the API key under the provider settings and activates; choose Email validation Yes or No.
  2. System registers an account-level webhook at the provider that encodes the target location.
  3. Client signs at a kiosk or online; provider calls the webhook; Decision: with Email validation on (and not overridden on that waiver at the provider), nothing syncs until the signer confirms their email.
  4. System matches on first name + last name + email. Decision: one match attaches the waiver to that client; no match creates a client from the fields the waiver collected; several matches email the account admins to resolve or merge manually. Extra participants and minors become their own clients linked to the signer (parent of). The waiver is listed in the provider table on the Documents tab (view PDF, email a copy) and the profile waiver checkbox is ticked until every waiver has expired.
  5. Optional: per-template webhook override at the provider routes specific waivers to another location.
- Rules/edge cases: one provider account may serve several locations; match rules (email? name+DOB?) are not published; location id is obtained from vendor support; no notification to staff from the platform on completion; a waiver never creates a membership or package; photo capture is probably not synced; recommended order for new customers is waiver first, portal invitation second.
- Feature IDs: DOC-13, DOC-15, FAM-01, CLI-13
- Evidence: https://support.ezfacility.com/hc/en-us/articles/4406062265883-Enable-the-Smartwaiver-and-EZFacility-Integration-in-EZFacility-Classic, https://www.ezfacility.com/partners/smartwaiver/, https://www.ezfacility.com/blog/software-release-ezpayments-uk-smartwaiver, https://www.youtube.com/watch?v=jbwkXIo9rY8 (t=04:02), https://www.youtube.com/watch?v=jbwkXIo9rY8 (t=09:10), https://www.youtube.com/watch?v=zzEUXdDPMyU (t=22:45)

### Define, record and report fitness assessments
- Actors: owner/admin, trainer, client
- Preconditions: none.
- Steps:
  1. Admin creates assessment categories, then numeric fields with decimal precision, each assigned to a category.
  2. Trainer opens the client's Assessment tab, enters values for the relevant fields, sets date/time, saves an entry.
  3. Tab shows the latest values; History lists all entries for edit/delete.
  4. Trainer generates the per-client report for a date range and prints or exports it.
  5. Owner runs the Assessment Summary report with start date, end date and maximum value age to compare the cohort at start vs end.
- Rules/edge cases: clients with stale values (older than the max-age window before start) are excluded from the summary; no client-side entry documented.
- Feature IDs: FIT-01, FIT-02, FIT-03, FIT-04, FIT-05
- Evidence: https://support.ezfacility.com/hc/en-us/articles/4404308492315-Setting-Up-Your-Assessment-Categories, https://support.ezfacility.com/hc/en-us/articles/4404314819483-Adding-an-Assessment-in-EZFacility-Classic, https://support.ezfacility.com/hc/en-us/articles/4404308386075-Assessment-Summary-Report

## Memberships, Packages & Sessions

### Configure the membership catalogue
- Actors: owner/admin.
- Preconditions: revenue categories exist (billing cluster); document templates exist if plans should carry one; package plans / pre-defined items exist if they will be add-ons.
- Steps:
  1. Create membership types, each mapped to a revenue category; order them.
  2. Create a plan: pick type, description, cadence and number of billings (their product = contract length), optional fixed start date, visit cap, fees (initiation, per term), due day, default document.
  3. Decide renewal: leave lead time blank (contract just ends) or set lead time and target (same terms as sold, or a named plan whose live terms apply at renewal).
  4. Set billing defaults: discount, revenue category, default invoice option, default autopay, online-sale flag.
  5. Optionally set proration mode and attach add-ons.
  6. Review summary and save; system lists the plan (newest first) and makes it selectable as a renewal target for other plans.
  7. Set tenant preferences: remark requirement, number auto-generation, payment-method capture mode.
- Rules/edge cases: promo-to-full-price is modelled as plan A renewing as plan B; later price changes are plan edits and reach only new sales and renewals that resolve to that plan; contracts renewing as a copy are untouched.
- Feature IDs: MEM-01, MEM-02, MEM-03, MEM-04, MEM-05
- Evidence: https://support.ezfacility.com/hc/en-us/articles/29852362973211-Creating-Membership-Types-in-EZFacility-Classic, https://support.ezfacility.com/hc/en-us/articles/22758625268379-Creating-Membership-Types-in-New-EZFacility-Experience, https://support.ezfacility.com/hc/en-us/articles/29794984963099-Setting-Up-Membership-Plans-in-EZFacility-Classic, https://support.ezfacility.com/hc/en-us/articles/4402058520603-How-to-add-Membership-Plans, https://support.ezfacility.com/hc/en-us/articles/4402427197467-How-to-Edit-Membership-Plans, https://support.ezfacility.com/hc/en-us/articles/29796200065179-Prorating-Membership-Plans-in-EZFacility-Classic, https://support.ezfacility.com/hc/en-us/articles/4402427196571-How-to-Prorate-Membership-Plans, https://support.ezfacility.com/hc/en-us/articles/23397491696795-Adding-a-Package-or-Add-On-to-a-Membership-Plan, https://support.ezfacility.com/hc/en-us/articles/29852095095067-Setting-Up-Membership-Preferences-in-EZFacility-Classic, https://support.ezfacility.com/hc/en-us/articles/20482279207963-Chalk-Talk-November-2023-Updating-Membership-Pricing

### Sell a membership at the desk
- Actors: front desk / sales; member (signs).
- Preconditions: plan exists (or Classic manual terms); client exists or is created inline with tenant-required fields.
- Steps:
  1. Start from the client profile or from the plan list; find or create the client.
  2. Pick the plan; system pre-fills a contract draft from it.
  3. Review and optionally override for this sale only: seller, referrer, start date, duration, fees, visit cap, renewal terms, autopay, proration, add-ons, linked document.
  4. Decision: proration. If plan mode is Custom, seller chooses; otherwise plan rule applies; system computes first-period amount and shifts later due dates to the 1st.
  5. Capture agreement by paper upload, tick-box, drawn signature or emailed link; system files the accepted copy on the client.
  6. Depending on tenant preference, capture card/direct-debit details (hidden, optional or required).
  7. Decision: invoicing. Invoice now (one invoice per billing period, or one for all), invoice later, or leave in cart; then pay now or leave the invoice open.
  8. System side-effects: contract created with a snapshot of terms; billing periods generated for the whole contract (initiation fee on the first); bundled packages granted at zero price; membership number generated if enabled; client becomes an active member from the start date; autopay flag copied to invoices.
- Rules/edge cases: revenue date editable only for single-billing contracts; setting an explicit end date collapses the schedule to one period; a fixed plan start date overrides the sale date; contract sold with a package add-on is active the same day; expired members are simply sold a new contract.
- Video-confirmed detail: one membership per client at a time, so a second sale must be future-dated behind the current one; a fixed-term deal is made at the review step by switching auto-renew and autopay off and entering the duration in days (needs the per-user customize-contract permission, otherwise only plan terms can be sold); on a prorated mid-month sale the payment step asks whether to collect the prorated part only or the prorated part plus the first full month.
- Feature IDs: MEM-07, MEM-08, MEM-03, MEM-04, MEM-05, MEM-19
- Evidence: https://support.ezfacility.com/hc/en-us/articles/4404308093211-Selling-an-Advanced-Membership-Contract-in-EZFacility-Classic, https://support.ezfacility.com/hc/en-us/articles/4401983374619-How-to-Sell-a-Membership-from-the-Client-Profile, https://support.ezfacility.com/hc/en-us/articles/4401990058523-How-to-Sell-a-Membership-from-Administration, https://support.ezfacility.com/hc/en-us/articles/29796200065179-Prorating-Membership-Plans-in-EZFacility-Classic, https://support.ezfacility.com/hc/en-us/articles/23397491696795-Adding-a-Package-or-Add-On-to-a-Membership-Plan, https://support.ezfacility.com/hc/en-us/articles/29852095095067-Setting-Up-Membership-Preferences-in-EZFacility-Classic, https://support.ezfacility.com/hc/en-us/articles/22122496577179-January-17th-2024-Release-Notes, https://support.ezfacility.com/hc/en-us/articles/19847009538203-October-25th-2023-Release-Notes, https://www.youtube.com/watch?v=KAN6h9vPUiM (t=09:14, t=10:16, t=25:00), https://www.youtube.com/watch?v=iR4MVBspNlQ (t=07:10, t=29:53)

### Buy a membership online
- Actors: member or guardian.
- Preconditions: plan flagged for online sale; card processing connected (inferred from package rule); portal account.
- Steps:
  1. Member (or parent acting for a relative) opens the portal and selects a published plan.
  2. Optional coupon; amount due recalculates.
  3. System prompts e-signature of the plan's document.
  4. Payment; system creates contract, billing schedule and member status as in the desk flow.
- Rules/edge cases: the relative need not have their own portal login; items bought online are eligible for member-side renewal opt-out. Detailed screens are not publicly documented in this cluster (see unknowns).
- Video-confirmed detail: observed order in the launch demo: (1) portal Buy menu > Memberships, plans grouped by type with term, quantity, dates, auto-renew flag, price and initiation fee, start date = today unless the plan fixes it; (2) agreement step, ticking the box counts as signing and the client can email themselves a copy; decision: online agreement switched off = skip straight to checkout and sign at the next visit; (3) card checkout; decision: tenant forces card save (always, or only when nothing is due today), otherwise the client is asked whether to save the card, and a client with a stored card picks it or enters another; (4) contract appears on the profile with autopay on when the billing preference says so, and staff on the alert list get an instant email.
- Feature IDs: MEM-09, MEM-08, MEM-18
- Evidence: https://support.ezfacility.com/hc/en-us/articles/29852167415195-Allowing-Memberships-to-be-Sold-Online-in-EZFacility-Classic, https://support.ezfacility.com/hc/en-us/articles/4402058520603-How-to-add-Membership-Plans, https://www.ezfacility.com/blog/software-release-vaccine-passport, https://support.ezfacility.com/hc/en-us/articles/17574439837467-August-2nd-2023-Release-Notes, https://support.ezfacility.com/hc/en-us/articles/18408526583067-August-31st-2023-Release-Notes, https://support.ezfacility.com/hc/en-us/articles/37195623250587-Click-to-Disable-Auto-Renew-Memberships, https://www.youtube.com/watch?v=SDO3SkkHTlY (t=04:40, t=05:30, t=07:10, t=08:20, t=09:10, t=11:00)

### Membership renewal cycle
- Actors: scheduler; admin/front desk; member.
- Preconditions: contract has an auto-renew lead time, or staff trigger a manual renewal.
- Steps:
  1. Lead-time before expiry, the scheduler selects contracts due to renew (not disabled, not frozen).
  2. Resolve target: copy = clone the contract's own sold terms; named plan = read that plan's current terms.
  3. Apply renewal-time discount, description and remark; if the contract is suspended with a suspension fee, use that fee.
  4. Create the successor contract (visible as upcoming) with its billing periods; re-grant bundled packages only if those packages are themselves set to renew.
  5. On the old contract's end date the successor becomes current; with no renewal configured the contract expires and the client stops being a member.
  6. Manual path: staff open the contract, change lead/target, disable renewal, or renew immediately.
  7. Member path: member disables renewal in the portal; contract runs to term end and expires.
- Rules/edge cases: manual renew must be idempotent; staff must look for an already generated successor before freezing, suspending or cancelling; price increases propagate only through named-plan renewals; freeze turns renewal off until staff restore it.
- Video-confirmed detail: changing plan mid-term has no dedicated command; decision: keep the paid term = disable renewal on the current contract and sell the new plan future-dated; switch now = cancel to the start date with reason Upgrade or Downgrade and sell the new plan (backdate to the 1st to keep the billing day). Disabling renewal on a prorated contract ends it at the close of the first full month. A contract that expires without renewal flips the profile to non-member.
- Feature IDs: MEM-11, MEM-10, MEM-18, MEM-04, MEM-14
- Evidence: https://support.ezfacility.com/hc/en-us/articles/22758241119899-Membership-Renewal-Process, https://support.ezfacility.com/hc/en-us/articles/29794984963099-Setting-Up-Membership-Plans-in-EZFacility-Classic, https://support.ezfacility.com/hc/en-us/articles/20482279207963-Chalk-Talk-November-2023-Updating-Membership-Pricing, https://support.ezfacility.com/hc/en-us/articles/22758476497819-How-to-view-and-edit-Memberships-on-a-Client-Profile-in-New-EZFacility-Experience, https://support.ezfacility.com/hc/en-us/articles/4402434194715-How-to-Suspend-a-Membership, https://support.ezfacility.com/hc/en-us/articles/23397491696795-Adding-a-Package-or-Add-On-to-a-Membership-Plan, https://support.ezfacility.com/hc/en-us/articles/37195623250587-Click-to-Disable-Auto-Renew-Memberships, https://support.ezfacility.com/hc/en-us/articles/18408526583067-August-31st-2023-Release-Notes, https://support.ezfacility.com/hc/en-us/articles/16846068050715-July-3rd-2023-Release-Notes, https://www.youtube.com/watch?v=a7-8-cHwB8Y (t=49:15, t=56:22), https://www.youtube.com/watch?v=KAN6h9vPUiM (t=22:33), https://www.youtube.com/watch?v=pYlicKb3lng (t=06:00)

### Freeze and unfreeze a membership
- Actors: admin / front desk.
- Preconditions: active (or upcoming) contract; remark if tenant requires.
- Steps:
  1. Open the correct term (check for a pending renewed term).
  2. Add a freeze: first day, optional last day, remarks.
  3. System: status history row; billing stops; not-yet-due invoices from the sale are withdrawn back to un-invoiced periods; autopay and auto-renew switched off; check-in and profile show frozen.
  4. Decision: end date known? If set, membership resumes the day after; if not, staff set it later.
  5. To change or end early: clear the end date (confirm), set a new one, or clear start to drop the freeze.
  6. After the freeze, staff re-invoice remaining periods: from the client's billing items (all selected into one invoice, or one per period) or via the cart (then add a payment schedule).
  7. Staff re-enable autopay / auto-renew as needed.
- Rules/edge cases: cart route without a schedule makes the whole remainder due on the earliest period date; cart default view shows only the freezing user's items; whether the contract end date shifts by the frozen duration is not documented.
- Video-confirmed detail: the contract end date is pushed out by the frozen duration; when the end date is saved in New the system asks how to invoice the unfrozen items (one invoice each, one combined invoice, or leave un-invoiced), which shortens step 6; billing restarts on the exact freeze end date, not on the 1st or the original sale day; no freeze fee; freezing all members at once is a vendor-support request, not a staff action.
- Feature IDs: MEM-12, MEM-13, MEM-05, MEM-10
- Evidence: https://support.ezfacility.com/hc/en-us/articles/4404314520475-Freezing-a-Membership-in-EZFacility-Classic, https://support.ezfacility.com/hc/en-us/articles/6740429102747-How-to-Freeze-a-Membership-in-EZFacility, https://support.ezfacility.com/hc/en-us/articles/4404308193435-Removing-a-Freeze-in-EZFacility-Classic, https://support.ezfacility.com/hc/en-us/articles/38623038228763-Removing-a-Freeze-in-EZFacility, https://support.ezfacility.com/hc/en-us/articles/4404308380827-How-to-Edit-or-Add-an-End-Date-for-a-Membership-Freeze-in-EZFacility-Classic, https://www.youtube.com/watch?v=a7-8-cHwB8Y (t=20:29, t=21:31, t=26:38, t=33:48), https://www.youtube.com/watch?v=KAN6h9vPUiM (t=21:31)

### Suspend and reinstate a membership
- Actors: admin.
- Preconditions: contract exists; remark if required.
- Steps:
  1. Open the correct term; add a suspension with first day, optional last day, optional fee, remarks.
  2. System: status history row; suspended marker at check-in, profile and lists.
  3. If renewal fires while suspended and a fee is set, the successor is priced at that fee.
  4. To reinstate: set (or change) the suspension end date; contract returns to active after it.
- Rules/edge cases: fee applies to membership contracts only; effect on regular dues during suspension undocumented.
- Video-confirmed detail: dues keep billing during the suspension and the fee is added on top; access is denied at the door and check-in; dates do not move; with an end date the contract resumes the next day, without one staff unsuspend manually. Decision guide given by trainers: member stops attending or card is expiring = freeze or cancel, never suspend, because suspension keeps billing.
- Feature IDs: MEM-14, MEM-11, MEM-05
- Evidence: https://support.ezfacility.com/hc/en-us/articles/4404314524571-Suspending-a-Membership-in-EZFacility-Classic, https://support.ezfacility.com/hc/en-us/articles/4402434194715-How-to-Suspend-a-Membership, https://support.ezfacility.com/hc/en-us/articles/4404314514587-Unsuspending-a-Membership-in-EZFacility-Classic, https://support.ezfacility.com/hc/en-us/articles/4402427184283-How-to-Unsuspend-a-Membership, https://www.youtube.com/watch?v=a7-8-cHwB8Y (t=16:24, t=35:43, t=37:55), https://www.youtube.com/watch?v=KAN6h9vPUiM (t=21:31)

### Cancel a membership and refund
- Actors: admin (refund permission).
- Preconditions: contract active or upcoming; payment processor capable of integrated refunds, else manual.
- Steps:
  1. Open the contract (check for pending renewed term and cancel that too if needed).
  2. Enter cancellation date (within the active period), reason code and remarks.
  3. Decision: date = start date? Yes: system reverses the contract invoice and moves payments to on-account credit (full refund path). No: contract ends on that date; invoices remain.
  4. Partial path: open the invoice(s); discount or reverse specific items to create the agreed credit, which lands on account.
  5. From on-account, issue the refund: issue date, amount, method (original card, different card, or external/manual), memo.
  6. Separately remove bundled packages if they should end too.
  7. System: status cancelled with reason; member status lost after the date; event counted in attrition unless reason is administrative error.
- Rules/edge cases: irreversible for users; direct-debit refunds always manual; non-integrated gateways need an external refund record plus portal refund; can refund a single payment while leaving the item owed.
- Video-confirmed detail: decision before step 1: no refund intended = do not cancel, disable auto-renew and let the paid term run out (reverse the open next-period invoice if it should be waived). In New, step 2 also asks whether to delete the connected add-on package, replacing step 6 for bundled packages. Refund dialog offers the card originally used or another card; card refunds take a few business days.
- Feature IDs: MEM-15, MEM-16, MEM-04, PKG-13
- Evidence: https://support.ezfacility.com/hc/en-us/articles/4404308183707-Canceling-a-Membership-in-EZFacility-Classic, https://support.ezfacility.com/hc/en-us/articles/4402434198555-How-to-Cancel-a-Membership, https://support.ezfacility.com/hc/en-us/articles/4404308377243-Canceling-a-Membership-with-a-Refund-in-EZFacility-Classic, https://support.ezfacility.com/hc/en-us/articles/17764248824987-How-to-Cancel-Membership-and-Refund-the-Client-Full-Partial-in-EZFacility, https://support.ezfacility.com/hc/en-us/articles/23397491696795-Adding-a-Package-or-Add-On-to-a-Membership-Plan, https://www.youtube.com/watch?v=a7-8-cHwB8Y (t=06:13, t=08:16, t=12:20), https://www.youtube.com/watch?v=KAN6h9vPUiM (t=22:33)

### Share a membership or package with related clients
- Actors: front desk; admin (plan presets).
- Preconditions: contract or package exists; relationships exist for the quick-pick list.
- Steps:
  1. Open the owner's contract/package and choose share.
  2. Tick related clients or search any other client; save.
  3. System records covered clients; share count appears on the owner's row; covered clients are treated as members / may book against the package.
  4. Package plans may pre-define sharing so step 1 to 3 happen automatically at sale.
- Rules/edge cases: billing stays with the owner; shared-package waitlist entries auto-book on a free place; API exposes owner contract and covered-client count.
- Feature IDs: MEM-17, PKG-06
- Evidence: https://support.ezfacility.com/hc/en-us/articles/4404308188315-Sharing-a-Membership-in-EZFacility-Classic, https://support.ezfacility.com/hc/en-us/articles/4404308415899-How-to-Share-Packages-Automatically-in-EZFacility-Classic, https://support.ezfacility.com/hc/en-us/articles/4404308418843-How-to-Share-a-Package-Post-Sale-in-EZFacility-Classic, https://support.ezfacility.com/hc/en-us/articles/23807158781211-March-14th-2024-Release-Notes, https://support.ezfacility.com/hc/en-us/articles/19132331777307-September-27th-2023-Release-Notes

### Visit-limited check-in
- Actors: member; check-in system; front desk.
- Preconditions: active contract with a visit cap; optional daily-entry rule and alert enabled.
- Steps:
  1. Member scans in; system resolves the covering contract (own, shared, or simple membership).
  2. Count visits in the current term; if cap reached raise the depleted alert.
  3. If the daily rule is on and a visit was already logged today (location-local day), deny entry; if only the alert is on, show "over daily limit", allow, and log the visit.
  4. Otherwise record the visit against the contract.
- Rules/edge cases: daily-limit alert shows only when no higher-priority membership alert applies; frozen and suspended states also surface here.
- Feature IDs: MEM-20, MEM-12, MEM-14, MEM-06
- Evidence: https://support.ezfacility.com/hc/en-us/articles/23328878237467-February-28th-2024-Release-Notes, https://support.ezfacility.com/hc/en-us/articles/29794984963099-Setting-Up-Membership-Plans-in-EZFacility-Classic, https://support.ezfacility.com/hc/en-us/articles/4404314520475-Freezing-a-Membership-in-EZFacility-Classic, https://support.ezfacility.com/hc/en-us/articles/4404314524571-Suspending-a-Membership-in-EZFacility-Classic, https://support.ezfacility.com/hc/en-us/articles/29852099999259-Setting-Up-a-Simple-Membership-in-EZFacility-Classic

### Configure a package plan
- Actors: owner/admin.
- Preconditions: reservation type exists; revenue category exists.
- Steps:
  1. Choose kind: individual or recurring.
  2. Details: reservation type, description, session mode (single, N, range, unlimited), validity (start rule, length, out-of-range booking), renewal (lead time, target, threshold), sharing preset, document.
  3. Recurring only: pattern, interval, number of occurrences, auto-renew of the series.
  4. Billing: paid or free; fee and basis; default invoice option; default autopay; online-sale policy; members-only; discount; revenue category; descriptions.
  5. Review summary and save.
- Rules/edge cases: single session forces per-session pricing; free hides money fields; auto-renew lead must fit inside the package length.
- Feature IDs: PKG-01, PKG-02, PKG-03, PKG-04, PKG-05, PKG-06, PKG-09, PKG-10
- Evidence: https://support.ezfacility.com/hc/en-us/articles/29784038483867-How-to-Set-Up-Multiple-Session-Package-Plans-in-EZFacility-Classic, https://support.ezfacility.com/hc/en-us/articles/29784117801755-How-to-Set-Up-Single-Session-Package-Plans-in-EZFacility-Classic, https://support.ezfacility.com/hc/en-us/articles/29784160666267-How-to-Set-Up-Unlimited-Package-Plans-in-EZFacility-Classic, https://support.ezfacility.com/hc/en-us/articles/29784623019035-How-to-Set-Up-Package-Recurring-Plans-in-EZFacility-Classic, https://support.ezfacility.com/hc/en-us/articles/4402427214107-Setting-Up-a-Recurring-Package-Plans, https://support.ezfacility.com/hc/en-us/articles/29784674271131-How-to-Set-Up-Complimentary-Sessions-in-EZFacility-Classic, https://support.ezfacility.com/hc/en-us/articles/4402434205851-Setting-up-a-Free-Package-Plan, https://support.ezfacility.com/hc/en-us/articles/34440097348379-Creating-a-Package-with-an-Expiration-Date-in-EZFacility-Classic, https://support.ezfacility.com/hc/en-us/articles/23573413327643-Setting-up-Auto-Renew-for-an-Individual-Package, https://support.ezfacility.com/hc/en-us/articles/4404308407579-How-to-Sell-Package-Plans-Online-in-EZFacility-Classic, https://support.ezfacility.com/hc/en-us/articles/34441361024795-How-to-Create-Member-Only-Package-Plans-in-EZFacility-Classic

### Sell a package (desk or online)
- Actors: front desk; member/guardian online.
- Preconditions: plan exists (or staff build an ad-hoc package); for online: plan published and card processing connected; members-only plans need an active membership.
- Steps:
  1. Staff open the client's package tab or the admin sell screen (or the registration dialog); member opens the portal/app store-front.
  2. Select plan; for range plans choose the quantity; staff may customise terms for this sale, apply a coupon and set the salesperson.
  3. Decision: invoice timing (only asked if the plan has no default): now, or later via cart.
  4. Decision: finish and pay (payment capture opens; on-account credit pre-applied) or finish (open invoice). Online: pay in full, or allowed to leave a balance, per plan policy.
  5. System: package instance created with plan snapshot, session balance, validity window, sharing per preset; invoice(s) created; renewal schedule armed if configured.
- Rules/edge cases: partial on-account credit is consumed first and the rest stays due; recurring plans may create one invoice per occurrence.
- Feature IDs: PKG-07, PKG-09, PKG-10, PKG-06, PKG-08
- Evidence: https://support.ezfacility.com/hc/en-us/articles/4404308405531-How-to-Sell-a-Package-in-EZFacility-Classic, https://support.ezfacility.com/hc/en-us/articles/23607740442011-How-to-Sell-a-Package-to-a-Client-on-their-Profile, https://support.ezfacility.com/hc/en-us/articles/4402434204955-How-to-Sell-a-Package-on-the-admin-side, https://support.ezfacility.com/hc/en-us/articles/4404308407579-How-to-Sell-Package-Plans-Online-in-EZFacility-Classic, https://support.ezfacility.com/hc/en-us/articles/34441361024795-How-to-Create-Member-Only-Package-Plans-in-EZFacility-Classic, https://support.ezfacility.com/hc/en-us/articles/21201707663515-Removing-and-Refunding-Packages, https://support.ezfacility.com/hc/en-us/articles/17574439837467-August-2nd-2023-Release-Notes

### Redeem package sessions (register, attend)
- Actors: front desk / trainer; client.
- Preconditions: a schedulable session with free capacity; client holds (or is sold) a package for that reservation type.
- Steps:
  1. Open the session on the calendar and choose register client; find or create the client.
  2. System shows client summary (age, medical, waiver, balance, membership) and eligible packages; speed-register picks the package automatically when there is exactly one.
  3. Decision: scope = this session, all linked sessions, or a custom subset; if no suitable package, sell one inline.
  4. System books the client, reserves credits from the package, updates capacity state; if full, client can be waitlisted and is auto-booked when a place opens.
  5. At or after the session, staff mark attendance on the roster; roster also gives access to the registrant's package, invoice, balance and payment, removal, and bulk email.
  6. Package ledger shows purchased / remaining / scheduled; renewal marker appears when the threshold is reached and the package is set to renew.
- Rules/edge cases: "all sessions" is best-effort against availability; out-of-range sessions are bookable only if the package allows; the exact moment a credit is consumed (booking vs attendance) and no-show handling are undocumented.
- Video-confirmed detail: credits on a counted package drop only when staff mark the registrant attended (reservation drop-down: scheduled > attended); unlimited packages need no marking; early cancel either rebooks into another open session or returns the session to the package; late cancel and no-show marks need extra permissions and their credit effect is not shown.
- Feature IDs: PKG-12, PKG-14, PKG-05, PKG-04, PKG-07
- Evidence: https://support.ezfacility.com/hc/en-us/articles/4404311276699-How-to-Register-a-Client-into-an-Available-Session-in-EZFacility-Classic, https://support.ezfacility.com/hc/en-us/articles/34440097348379-Creating-a-Package-with-an-Expiration-Date-in-EZFacility-Classic, https://support.ezfacility.com/hc/en-us/articles/34439958272283-How-to-Sell-a-Post-Billed-Package-in-EZFacility-Classic, https://support.ezfacility.com/hc/en-us/articles/19132331777307-September-27th-2023-Release-Notes, https://support.ezfacility.com/hc/en-us/articles/18408526583067-August-31st-2023-Release-Notes, https://support.ezfacility.com/hc/en-us/articles/16308423683355-June-12th-2023-Release-Notes, https://www.youtube.com/watch?v=7JVYZ3kxUAo (t=32:56), https://www.youtube.com/watch?v=Rjy8ZpfIA68 (t=24:35), https://www.youtube.com/watch?v=TWNQ4cTiEFs (t=42:16)

### Post-billed package lifecycle
- Actors: admin; front desk.
- Preconditions: post-billed rate defined for the reservation type.
- Steps:
  1. Admin defines rate rows: reservation type, minimum session count, per-session amount, optional extra billed items.
  2. Staff open a post-billed package on the client: rate, sharing, autopay, renewal threshold, auto-renew.
  3. Client is booked into any number of sessions; no invoice exists while open.
  4. Staff close the package; system bills each used session at the rate plus extras.
  5. If auto-renew is on, a new open package follows (inferred).
- Rules/edge cases: tier selection when several rate rows match is undocumented.
- Feature IDs: PKG-11, PKG-12
- Evidence: https://support.ezfacility.com/hc/en-us/articles/34439589179291-How-to-Create-a-Post-Billed-Package-in-EZFacility-Classic, https://support.ezfacility.com/hc/en-us/articles/34439958272283-How-to-Sell-a-Post-Billed-Package-in-EZFacility-Classic

### Remove and refund a package
- Actors: admin.
- Preconditions: package instance exists; refund permission.
- Steps:
  1. From the client's package list (all packages) choose delete.
  2. Decision if billed: reverse the billing; delete and keep the billing; inspect billing first; or abort.
  3. Reverse: enter reason and revenue date; system posts an offsetting item; payments stay on the invoice and the surplus becomes on-account credit.
  4. Refund from on-account (issue date, negative amount, method) or leave the credit for future purchases, where it is applied by default.
- Rules/edge cases: package bundled with a membership is handled separately from the membership cancel in New.
- Feature IDs: PKG-13, MEM-16
- Evidence: https://support.ezfacility.com/hc/en-us/articles/21201707663515-Removing-and-Refunding-Packages, https://support.ezfacility.com/hc/en-us/articles/23397491696795-Adding-a-Package-or-Add-On-to-a-Membership-Plan, https://support.ezfacility.com/hc/en-us/articles/4404308377243-Canceling-a-Membership-with-a-Refund-in-EZFacility-Classic

## Billing & Invoicing, Payments & Merchant

### Sell an ad-hoc or recurring charge from a client profile
- Actors: Admin (catalog), Front Desk (sale), System.
- Preconditions: pre-defined item exists with fee and revenue category; for autopay, client has stored billing details and the location has a processor.
- Steps:
  1. Admin defines the catalog item: kind (one-off or recurring), start rule, optional length/auto-renew, recurrence (pattern, every N, end after N), fee, default invoice option, autopay default, discount, revenue category, client-visible and internal notes.
  2. Staff opens the client's Billing > Items and starts a generic-item sale; picks the item; optionally overrides details/billing for this sale.
  3. System creates one billing item (one-off) or one per occurrence (recurring), each with revenue date, revenue category and taxes resolved from the category at the revenue date's rate.
  4. Decision by default invoice option: single invoice for all occurrences, one invoice per occurrence, or leave uninvoiced.
  5. Staff chooses pay now (lands on the invoice payment step) or finish (invoice stays open, payable at desk or in Self-Service; autopay collects on due dates if flagged).
  6. At renewal lead time, system creates the successor from the "renews as" target (itself or another catalog item) at that item's current settings.
- Rules/edge cases: preset discount always applies; blank discount may be added at sale; customised sale that renews as the catalog item loses its overrides on renewal; autopay silently does nothing without billing details/processor.
- Feature IDs: BIL-14, BIL-01, BIL-03, BIL-04, BIL-12, BIL-13, BIL-17, PAY-01
- Evidence: https://support.ezfacility.com/hc/en-us/articles/17657710657051-How-to-Create-and-Sell-a-Pre-Defined-Item

### Invoice uninvoiced items (bulk) and send
- Actors: Billing staff, System, Client.
- Preconditions: uninvoiced billing items exist at the location.
- Steps:
  1. Open the location-wide billing-items list.
  2. Tick the items of a single client and create a new invoice.
  3. System numbers the invoice, records creator, sets a default one-line payment schedule (full amount on due date).
  4. Decision: take payment now, leave open, or email the invoice.
  5. For follow-up, switch the list to the open-invoices preset and bulk print/save, email, reverse billing, or attach a catalog item to the selected invoices.
- Rules/edge cases: mixing clients bills everything to the first ticked client; email requires a profile email; emailed invoice has no pay link; Classic performs the same from the location cart with the invoiced/uninvoiced filter; demo order for rentals: at the rental sale staff pick "leave items in cart" (slot stays held, item uninvoiced) or a single new invoice; later the items are ticked one client at a time; an invoiced rental shows a "$" on the calendar; presets seen are Open Invoices and Invoice Lookup; there is no scheduled/automatic send
- Feature IDs: BIL-02, BIL-03, BIL-04, BIL-10, BIL-07, PAY-18
- Evidence: https://support.ezfacility.com/hc/en-us/articles/26114234694043-How-to-Create-an-Invoice-for-Un-invoiced-Items, https://support.ezfacility.com/hc/en-us/articles/26114282998811-How-to-view-all-open-invoices, https://support.ezfacility.com/hc/en-us/articles/4403493341083-How-to-Add-Items-to-Invoices-in-the-Shopping-Cart-in-EZFacility-Classic, https://support.ezfacility.com/hc/en-us/articles/25419259427099-How-to-Email-an-Invoice-to-a-Client, https://www.youtube.com/watch?v=iR4MVBspNlQ (t=25:48-44:13)

### Take a payment and allocate it
- Actors: Front Desk, System, Client.
- Preconditions: client has open billing items (or staff is taking a prepayment); desired method enabled in billing preferences.
- Steps:
  1. Start from the client header, the Payments tab, or the pay icon on a specific invoice.
  2. Pick a suggested total or type an amount; choose method; add memo. If the client's home location differs from the current one, system warns.
  3. Take the payment: processed methods hit the processor/terminal; record-only methods just log.
  4. System proposes an allocation across open items, oldest first; staff edits per-item amounts.
  5. Apply: allocations are stored; fully covered invoices become paid; any unallocated remainder becomes account credit.
  6. Receipt is available to print; optional save of a keyed card per the save-card default.
- Rules/edge cases: partial application allowed; multiple payments per invoice; allocation view pages at 75 items; save-card default ignored if the client already has a stored card; decline triggers PAY-08 notices.
- Feature IDs: PAY-01, PAY-02, PAY-03, PAY-06, BIL-21, PAY-12, PAY-13
- Evidence: https://support.ezfacility.com/hc/en-us/articles/4402433808923-How-to-Take-a-Payment, https://support.ezfacility.com/hc/en-us/articles/4403485806363-How-to-Apply-a-Payment-in-EZFacility-Classic, https://support.ezfacility.com/hc/en-us/articles/4402433808155-How-to-Set-Up-Payment-Options, https://support.ezfacility.com/hc/en-us/articles/16731304236571-June-28th-2023-Release-Notes, https://support.ezfacility.com/hc/en-us/articles/25551222201627-May-8th-2024-Release-Notes

### Put an invoice on an instalment schedule
- Actors: Front Desk / Admin.
- Preconditions: open invoice with a balance.
- Steps:
  1. Open the invoice and edit its payments-due block.
  2. Either generate equal instalments (start date, interval count + unit, number of payments) or clear the schedule and add dated amounts by hand (remaining balance is prefilled each time).
  3. System shows a running cumulative total; payments already received are shown as schedule rows.
  4. Save is accepted only when the cumulative total equals the invoice amount due and no row predates the invoice date.
  5. Invoice shows a compact summary (count and final date); each entry becomes a due date for autopay, AR ageing and reminders.
- Rules/edge cases: regenerating replaces the default single entry; change is written to invoice history.
- Feature IDs: BIL-06, BIL-04, BIL-09, PAY-09
- Evidence: https://support.ezfacility.com/hc/en-us/articles/4402426435739-How-to-Set-Up-a-Payment-Schedule, https://support.ezfacility.com/hc/en-us/articles/4403486115483-How-to-Set-Up-a-Payment-Schedule-on-an-Invoice-in-EZFacility-Classic

### Recurring autopay cycle with decline handling (month-end billing)
- Actors: System (scheduled job), Owner/Admin, Client.
- Preconditions: processor integrated; invoices or schedule entries flagged autopay; client has a stored card or verified direct-debit account.
- Steps:
  1. Upstream modules (memberships, packages, recurring items, rentals, registrations) create billing items and invoices per their billing cadence, with autopay defaulted from plan and account preferences.
  2. Ahead of time, the system emails clients whose stored card expires in 1 and/or 2 months (scope per preference).
  3. On each due date the job selects due autopay entries and charges the stored method; for direct debit it requests the due date and falls back to the processor's next available processing date.
  4. Success: payment recorded with method and card type, allocated to the due items, invoice paid/part-paid.
  5. Failure: invoice stays open with the processor error; client decline notice sent per preference; location alert mailbox receives a digest or per-transaction email.
  6. Staff works the AR report (autopay-only filter), expiring-cards report and direct-debit failures report; updates the stored method or takes payment manually.
  7. Persistent non-payers are tagged for collections and later marked as placed in collections.
- Rules/edge cases: retry cadence is not documented (inferred: manual re-attempt); terminal/network timeouts must not generate failure emails; autopay settings are invisible until a processor exists.
- Feature IDs: PAY-09, BIL-17, PAY-06, PAY-07, PAY-08, PAY-10, BIL-19, BIL-20, BIL-22
- Evidence: https://support.ezfacility.com/hc/en-us/articles/21173246031771-Setting-Up-Billing-Preferences, https://support.ezfacility.com/hc/en-us/articles/4402427195163-Defaulting-New-Membership-Contracts-To-Auto-Pay-In-Self-Service, https://support.ezfacility.com/hc/en-us/articles/22968789591963-February-15th-2024-Release-Notes, https://support.ezfacility.com/hc/en-us/articles/18408526583067-August-31st-2023-Release-Notes, https://support.ezfacility.com/hc/en-us/articles/4403493405851-Accounts-Receivable, https://support.ezfacility.com/hc/en-us/articles/4403486991515-Failed-Transaction-Email, https://support.ezfacility.com/hc/en-us/articles/4403493392539-Expired-Expiring-Credit-Cards, https://support.ezfacility.com/hc/en-us/articles/4403493437211-Direct-Debit-Failures, https://support.ezfacility.com/hc/en-us/articles/4403486270875-Collections

### Full refund of a payment
- Actors: Admin / Front Desk with refund permission, System, Processor.
- Preconditions: recorded payment; for card-back refunds a processor that supports them.
- Steps:
  1. Open the receipt from the client's payments list.
  2. Un-apply the payment from the item(s) it covered, turning it into unapplied money.
  3. Start refund; amount defaults to the full unapplied sum; choose method; add comment.
  4. Decision: integrated processor that supports refunds returns funds to the card; otherwise choose the external method and refund separately in the gateway portal; direct debit is always refunded outside the system.
  5. System records a negative payment row linked to the original and shows refunded amount on the original receipt.
  6. The invoice is now open with a balance: void it, reverse the item, or collect again.
- Rules/edge cases: refunding several payments together locks amounts to full; button disabled when nothing is on account; sensitive tender details hidden without permission.
- Feature IDs: PAY-05, PAY-03, BIL-21, BIL-08, BIL-07, PAY-11
- Evidence: https://support.ezfacility.com/hc/en-us/articles/4403486096667-How-to-Refund-Payments-Full-Partial-in-EZFacility-Classic, https://support.ezfacility.com/hc/en-us/articles/16731304236571-June-28th-2023-Release-Notes, https://support.ezfacility.com/hc/en-us/articles/23807158781211-March-14th-2024-Release-Notes

### Partial refund after a price adjustment
- Actors: Admin / Front Desk.
- Preconditions: paid invoice.
- Steps:
  1. Open the invoice and edit the item: lower the unit price or add a discount; save.
  2. System recalculates the item total and tax; the payment's applied total drops below what was received.
  3. Open the receipt; refund the difference; choose method; optional memo; issue.
  4. Receipt summary shows collected, refunded and still-applied amounts.
- Rules/edge cases: two independent steps (adjust, then refund); if step 3 is skipped the excess sits as account credit.
- Feature IDs: PAY-05, BIL-01, BIL-21, PAY-03
- Evidence: https://support.ezfacility.com/hc/en-us/articles/25737423648923-How-to-Partially-Refund-a-Sale, https://support.ezfacility.com/hc/en-us/articles/4403486096667-How-to-Refund-Payments-Full-Partial-in-EZFacility-Classic

### Void a payment that did not clear
- Actors: Front Desk / Admin.
- Preconditions: recorded payment (e.g. returned check, fraud-flagged charge, wrong tender).
- Steps:
  1. Find the payment in the client's payments list (widen the date range if needed).
  2. Void it and enter a reason.
  3. System marks the payment voided, removes its allocations, and reopens the affected invoice(s).
  4. Voided payments remain retrievable through the voided filter.
- Rules/edge cases: no money moves; use refund when funds must be returned; trainer guidance: void suits external/check payments and account credit added by mistake, not card payments (record lost, nothing refunded); for a chargeback the processor acts first and staff then void the payment
- Feature IDs: PAY-04, PAY-03, BIL-04
- Evidence: https://support.ezfacility.com/hc/en-us/articles/4402426355099-How-to-Void-a-Payment, https://support.ezfacility.com/hc/en-us/articles/4403493305499-How-to-Void-a-Payment-in-EZFacility-Classic, https://www.youtube.com/watch?v=iR4MVBspNlQ (t=45:15), https://www.youtube.com/watch?v=a7-8-cHwB8Y (t=57:23-58:24)

### Correct a wrong charge: reverse an item or void an invoice
- Actors: Admin / Front Desk.
- Preconditions: billing item exists, invoiced or not.
- Steps:
  1. Decision: is the charge itself wrong (reverse) or only the invoice grouping wrong (void invoice)?
  2. Reverse: trigger reversal on the item, give a reason, choose the revenue date for the reversing entry (today, original bill date, custom). If already paid, the paid amount becomes account credit.
  3. Void invoice: detach items from the invoice (they return to uninvoiced), then void the now-empty invoice.
  4. For detached items: re-invoice them, or void the item permanently.
  5. Every step is appended to item/invoice history.
- Rules/edge cases: void invoice does not refund or reverse; item void is irreversible; reversal with original bill date keeps period reports consistent; decision point shown in training: reversal dated today is reported as handled today though tied to the original service start; reversing an uninvoiced rental item only makes it complimentary, the booking must be removed from the schedule as a separate step; when only the grouping is wrong, items can be moved by editing their invoice number and the emptied invoice needs a manager to void it
- Feature IDs: BIL-07, BIL-08, BIL-03, BIL-09, BIL-21
- Evidence: https://support.ezfacility.com/hc/en-us/articles/4402433754267-How-to-Reverse-the-Billing-of-an-Item, https://support.ezfacility.com/hc/en-us/articles/4402433754907-How-to-Reverse-the-Billing-of-an-Item-on-an-Invoice, https://support.ezfacility.com/hc/en-us/articles/4403493306779-How-to-Reverse-the-Billing-of-an-Item-on-an-Invoice-in-EZFacility-Classic, https://support.ezfacility.com/hc/en-us/articles/4402433807515-How-to-Void-an-Invoice, https://support.ezfacility.com/hc/en-us/articles/4403493317275-How-to-Void-an-Invoice-in-EZFacility-Classic, https://support.ezfacility.com/hc/en-us/articles/4403486128283-How-to-Add-Items-to-the-Shopping-Cart-in-EZFacility-Classic, https://www.youtube.com/watch?v=a7-8-cHwB8Y (t=10:17, t=22:33-24:35), https://www.youtube.com/watch?v=iR4MVBspNlQ (t=32:58-44:13), https://www.youtube.com/watch?v=7JVYZ3kxUAo (t=42:17-45:21)

### Remove a registrant from a group and refund
- Actors: Admin / Front Desk.
- Preconditions: client registered in a group with a billed (possibly paid) registration.
- Steps:
  1. Remove the member from the group roster and choose the option that reverses billing.
  2. System reverses the registration charge; if it had been paid, the amount appears as credit on the client account.
  3. Open the client profile and refund the on-account amount (method per processor capability), or leave it as credit.
- Rules/edge cases: refund step only needed when the invoice was paid.
- Feature IDs: BIL-07, BIL-21, PAY-05
- Evidence: https://support.ezfacility.com/hc/en-us/articles/4415441364635-How-to-Process-a-Refund-Remove-a-Client-from-a-Group

### Close and bill post-billed packages
- Actors: Billing staff, System.
- Preconditions: clients hold post-billed packages with sessions in the period.
- Steps:
  1. Open the post-billing close page; set the closing date.
  2. For each listed client, follow the scheduled-count link to give outstanding sessions an attendance status.
  3. Select clients and run close-and-bill.
  4. System creates billing items/invoices for sessions up to the closing date; on auto-renewing packages later sessions move to a fresh package.
  5. Print/save invoices as PDF and/or email them; review past closes on the review page.
- Rules/edge cases: sessions without attendance status block accurate billing; which sessions print on the invoice follows the package-invoice-dates preference.
- Feature IDs: BIL-18, BIL-10, BIL-16
- Evidence: https://support.ezfacility.com/hc/en-us/articles/29784817818907-How-to-Close-and-Review-Post-Billed-Packages-in-EZFacility-Classic, https://support.ezfacility.com/hc/en-us/articles/21173246031771-Setting-Up-Billing-Preferences

### Email billing statements in bulk
- Actors: Manager user, System, Clients.
- Preconditions: user is flagged manager and holds the statements permission; statement email template and footer configured.
- Steps:
  1. Open the statements wizard from the clients area.
  2. Narrow by client category and saved client filter; set date range; choose invoice-date or due-date basis; optionally restrict to clients with an open invoice.
  3. Select all or specific clients.
  4. Send: system renders each statement and emails it using the template.
  5. For a single client, staff can instead view the statement on the profile for a range and export it.
- Rules/edge cases: clients without valid email are skipped (inferred); unbounded range is slow; step 2 also offers client tags; email must be verified and no delivery confirmation is shown; presenter says the date range is capped at one year (conflict logged); single-client statement saves as Word or PDF or prints; nothing can be scheduled
- Feature IDs: BIL-11, BIL-16
- Evidence: https://support.ezfacility.com/hc/en-us/articles/25631630542619-How-to-Send-a-Client-a-Billing-Statement, https://support.ezfacility.com/hc/en-us/articles/23774950594715-How-to-View-a-Billing-Statement-on-a-Client-s-Profile, https://www.youtube.com/watch?v=iR4MVBspNlQ (t=04:06-06:09, t=19:35-24:43)

### Change a tax rate from a future date
- Actors: Owner/Admin.
- Preconditions: tax exists and is linked to revenue categories.
- Steps:
  1. Open the tax's detail and add a new effective date with the new percentage.
  2. From then on, items whose revenue date falls on or after that date use the new rate; earlier-dated items keep the old rate.
  3. To retire a tax, deactivate it; it stops applying from that date.
  4. To exempt a product line, untick the tax on its revenue category; to exempt one sale, untick it on the item.
- Rules/edge cases: several taxes on one item are each computed on the pre-tax amount.
- Feature IDs: BIL-12, BIL-13, BIL-01
- Evidence: https://support.ezfacility.com/hc/en-us/articles/4402426433819-How-to-Set-Up-Taxes-For-Your-Account, https://support.ezfacility.com/hc/en-us/articles/4403485782811-How-to-Set-Up-Taxes-for-your-Account-in-EZFacility-Classic, https://support.ezfacility.com/hc/en-us/articles/4402426434587-How-to-Set-Up-Revenue-Categories, https://support.ezfacility.com/hc/en-us/articles/23969046407579-How-to-Connect-Your-Revenue-Categories

### Onboard a card terminal
- Actors: Location admin, vendor payment services, terminal provider.
- Preconditions: merchant account approved; hardware delivered.
- Steps:
  1. (EZPayments terminal) Cable and provision the device; vendor supplies a terminal code.
  2. Grant the terminal permission to the users who will take card-present payments.
  3. Register the terminal on the location with name + code, set active, then mark one as default.
  4. (Clover, UK) Vendor enables the location flag; admin with account-administration permission opens the connection page, authenticates at Clover, picks the merchant; system stores merchant id and token; pairing completes via Clover's cloud display app.
  5. At payment time staff select the terminal (default pre-selected); result posts back as a processed payment.
- Rules/edge cases: connection page is hidden unless flag + permission; terminal timeouts must be treated as unknown outcome, not as declines; Clover timeline as presented: approval usually under a week, account linked by the vendor in under an hour, terminals shipped to the site; at payment the amount is pushed to the terminal and cannot be changed there
- Feature IDs: PAY-12, PAY-13, PAY-11, PAY-01
- Evidence: https://support.ezfacility.com/hc/en-us/articles/21171478349211-How-to-Setup-your-EZPayments-EMV-Terminal-in-EZFacility, https://support.ezfacility.com/hc/en-us/articles/14101589968923-Clover-Terminal-Set-Up-UK-Clients-Only, https://support.ezfacility.com/hc/en-us/articles/22122496577179-January-17th-2024-Release-Notes, https://www.youtube.com/watch?v=wTcpTun-eyM (t=15:20-19:25, t=29:35-31:37)

### Client pays an open invoice online
- Actors: Client / Parent, System.
- Preconditions: open invoice on the client (or the payer it was reassigned to); Self-Service enabled.
- Steps:
  1. Staff emails the invoice (no pay link) or client is reminded automatically.
  2. Client signs in to Self-Service, opens outstanding invoices, pays with stored or new card (coupon and autopay switches apply to new purchases).
  3. System records the payment, allocates it to the invoice items, sends receipt.
- Rules/edge cases: an invoice reassigned to a parent appears under the parent's login; accounts may be barred from Self-Service booking while a balance is outstanding (2017 capability).
- Feature IDs: PAY-18, BIL-10, BIL-05, PAY-06, BIL-22
- Evidence: https://support.ezfacility.com/hc/en-us/articles/25419259427099-How-to-Email-an-Invoice-to-a-Client, https://support.ezfacility.com/hc/en-us/articles/26114234694043-How-to-Create-an-Invoice-for-Un-invoiced-Items, https://support.ezfacility.com/hc/en-us/articles/26528401455643-How-to-Assign-an-Invoice-to-a-Different-Client, https://www.ezfacility.com/features/billing-payments

## POS & Inventory, Check-in & Access Control

### Counter sale (retail products)
- Actors: cashier; optionally a client.
- Preconditions: user role grants POS access (and passes IP restriction); at least one register, category and product exist; taxes/revenue categories configured in Billing.
- Steps:
  1. Cashier opens the POS app (from the back office or a bookmarked link) and confirms the active register; in multi-location accounts may switch to a register of another connected location.
  2. Builds the cart: taps product tiles (optionally filtered by category or register favourites), types a SKU, or scans barcodes; each action adds one unit.
  3. Optional: attaches a client by name / member ID search, or quick-adds a new client.
  4. Optional: adjusts line quantity; a privileged user may override unit price.
  5. Optional: applies a preset or custom discount to the whole sale or to ticked lines; a client-level global percentage discount applies automatically when a client is attached; coupon applied if used.
  6. Presses Pay and chooses tender: card, cash, check, gift card, money on account, pay later, or split tender across several. With an integrated card terminal (Clover Flex in the UK webinar) the amount is pushed to the terminal, cannot be changed there, and the result posts back to the sale.
  7. Decision: Pay Later -> system creates an open invoice on the client account instead of a completed transaction; Money on Account -> client balance is debited; otherwise payment is captured.
  8. Optional memo on the transaction, then accepts the sale.
  9. System side-effects: transaction and invoice number created, sale attributed to the logged-in user and register, stock decremented (inferred), revenue and tax posted per product/category mapping, sale visible on the client's invoice tab.
  10. Receipt step: print, email (address prefilled from client or typed), or both.
- Rules/edge cases: client mandatory for card on file, money on account, pay later and equipment; an email typed at checkout is not saved to the profile; with auto-print on, also choosing print double-prints; discount allocation across lines must not produce rounding drift; quick-added client is only persisted if "save" is chosen.
- Feature IDs involved: POS-01, POS-02, POS-07, POS-08, POS-09, POS-10, POS-11, POS-12, POS-13, POS-14
- Evidence URLs: https://support.ezfacility.com/hc/en-us/articles/23505052562971-How-to-Add-Products-to-the-Shopping-Cart-and-Finish-Sale, https://support.ezfacility.com/hc/en-us/articles/34418766515099-How-to-Add-Products-to-the-Shopping-Cart-and-Finish-Sale, https://support.ezfacility.com/hc/en-us/articles/23505069345947-How-to-Search-for-a-Client-in-the-POS, https://support.ezfacility.com/hc/en-us/articles/23505046070811-How-to-Edit-Quantity-or-Price-of-items-in-the-Point-of-Sale-Cart, https://support.ezfacility.com/hc/en-us/articles/23505081363227-How-to-Discount-Individual-POS-Products-Equipment, https://support.ezfacility.com/hc/en-us/articles/34418925611803-How-to-Email-P-O-S-Receipts-from-the-Sale-Complete-Page, https://support.ezfacility.com/hc/en-us/articles/23505084116891-How-to-Enable-the-Email-Option-in-Point-of-Sale, https://support.ezfacility.com/hc/en-us/articles/36516560976539-April-9th-2025-Release-Notes, https://support.ezfacility.com/hc/en-us/articles/26498179644187-June-5th-2024-Release-Notes, https://www.youtube.com/watch?v=wTcpTun-eyM (t=15:20)

### Refund / return of a POS sale
- Actors: cashier / front desk.
- Preconditions: a completed POS transaction exists.
- Steps:
  1. Open Transactions in the POS; locate the sale by client name or invoice number, or pick it from the list.
  2. Decision (newer POS): tick the individual items being returned and confirm the return; (older POS): refund applies to the sale.
  3. Choose "refund sale" and pick the tender to refund to.
  4. Process the refund; system confirms completion.
  5. System side-effects (inferred): refund transaction linked to the original, shows on returns/refunds and daily register reports, client account updated.
- Rules/edge cases: line-level partial returns only evidenced in the newer UI; restocking of returned goods and constraints on refund tender are not documented - we must decide (see unknowns); Pay Later sales are open invoices and are handled in billing rather than as completed transactions.
- Feature IDs involved: POS-16, POS-12
- Evidence URLs: https://support.ezfacility.com/hc/en-us/articles/23505037972251-How-to-Refund-in-Point-of-Sale, https://support.ezfacility.com/hc/en-us/articles/34419183605659-Refunding-in-the-Point-of-Sale, https://support.ezfacility.com/hc/en-us/articles/34419017128987-Order-Returns-Refunds, https://support.ezfacility.com/hc/en-us/articles/34419021121051-Daily-Register-Report

### Re-send a receipt for a past transaction
- Actors: cashier / front desk.
- Preconditions: email receipt option enabled in POS preferences (v.2).
- Steps:
  1. POS > Transactions; search by client or invoice number; select the transaction so its details load.
  2. Open receipt options; choose email and/or print.
  3. Send; system emails the receipt (and/or prints via the local print bridge).
- Rules/edge cases: any historical transaction qualifies; same receipt is reachable from the client's invoice tab.
- Feature IDs involved: POS-13, POS-15, POS-16
- Evidence URLs: https://support.ezfacility.com/hc/en-us/articles/23505072579483-How-to-Email-a-P-O-S-Receipt-from-Completed-Transactions, https://support.ezfacility.com/hc/en-us/articles/34418959208987-How-to-Email-a-P-O-S-Receipt-from-Completed-Transactions, https://support.ezfacility.com/hc/en-us/articles/23505084116891-How-to-Enable-the-Email-Option-in-Point-of-Sale

### POS catalogue and register setup
- Actors: owner/admin.
- Preconditions: tax codes and revenue categories defined in Billing administration.
- Steps:
  1. Create cash registers (one per till).
  2. Create brands and suppliers.
  3. Create categories and subcategories; link each to a revenue category and tick tax codes (pre-ticked when the revenue category carries a default tax).
  4. Add products under a category: name (register label), unique product ID, SKU, unit price, buying price, qty per unit, reorder level, brand, supplier; revenue category/tax inherit from the category unless overridden.
  5. Enter opening stock via the adjustment controls (set-inventory mode).
  6. Per register, choose favourite products and enable favourites.
  7. Set POS preferences (email receipt option, auto-print) and the receipt footer; install the print bridge on each till machine if silent printing is wanted.
- Rules/edge cases: reorder level -1 excludes the product from reorder reporting; favourites matter only with multiple registers.
- Feature IDs involved: POS-02, POS-03, POS-04, POS-05, POS-06, POS-13, POS-14, POS-15
- Evidence URLs: https://support.ezfacility.com/hc/en-us/articles/24547185574939-How-to-Setup-Point-of-Sale, https://support.ezfacility.com/hc/en-us/articles/34419191751451-Setting-Up-Product-Categories-Inventory, https://support.ezfacility.com/hc/en-us/articles/34419084373915-Setting-Up-Cash-Registers, https://support.ezfacility.com/hc/en-us/articles/34419081377307-Setting-Up-Product-Brands, https://support.ezfacility.com/hc/en-us/articles/34419162852891-Setting-Up-Product-Suppliers, https://support.ezfacility.com/hc/en-us/articles/34419085151003-How-to-Create-a-Product-Subcategory, https://support.ezfacility.com/hc/en-us/articles/34418941582747-New-Point-of-Sale-Customizing-the-Receipt, https://support.ezfacility.com/hc/en-us/articles/23505035242779-Receipt-Printing-Using-the-QZ-Tray-Application-For-PC

### Stock receipt, count correction and reorder
- Actors: owner/admin or stock keeper.
- Preconditions: product exists with SKU.
- Steps:
  1. Open the quick inventory panel on the category page (or edit the product).
  2. Scan or type the SKU.
  3. Choose mode: delta adjustment (+/-) or absolute set.
  4. Enter quantity, adjustment timestamp (defaults to now), reason (other / discrepancy / bought new stock) and optional comment; submit.
  5. System updates on-hand quantity and records the adjustment.
  6. Periodically run the re-order report listing products at or below their reorder level; reorder from the product's supplier.
- Rules/edge cases: backdated adjustments are allowed via the timestamp field; "automated" alerts beyond the report are claimed in marketing only.
- Feature IDs involved: POS-06, POS-05, POS-22
- Evidence URLs: https://support.ezfacility.com/hc/en-us/articles/34419193012379-How-to-Add-Inventory-to-a-Product, https://support.ezfacility.com/hc/en-us/articles/34419191751451-Setting-Up-Product-Categories-Inventory, https://support.ezfacility.com/hc/en-us/articles/34419009666459-Inventory-Re-order-Report, https://www.ezfacility.com/press-news/press-releases/ezfacility-releases-cutting-edge-fitness-point-of-sale-solution

### Equipment rental and return
- Actors: front desk; client.
- Preconditions: equipment category and item defined with rental fee, rental days, return time, late and replace fees; revenue category linked if taxes are used.
- Steps:
  1. In POS open the Equipment view and pick the register.
  2. Attach the client (mandatory) by search or quick-add.
  3. Tap the equipment item to add it to the cart; adjust quantity/price if permitted.
  4. Pay with any tender and accept the sale; choose receipt delivery.
  5. System marks the item as checked out to the client; it appears on the client's checked-out list and the checked-out equipment report.
  6. On return, staff go to the back-office Equipment page (or the client profile's checked-out section) and mark it returned; the item becomes available in POS again.
  7. Decision: overdue or damaged -> staff bill late or replacement fee (manual; automation not evidenced).
- Rules/edge cases: return is not done in the POS app; sources conflict on whether late/replace fees are charged or merely recorded.
- Feature IDs involved: POS-17, POS-18, POS-08, POS-12
- Evidence URLs: https://support.ezfacility.com/hc/en-us/articles/27444958543003-How-to-Rent-and-Return-Equipment, https://support.ezfacility.com/hc/en-us/articles/27444960685851-How-to-Add-Equipment-to-POS, https://support.ezfacility.com/hc/en-us/articles/34418782382235-How-to-Rent-Equipment-in-EZFacility-Classic, https://support.ezfacility.com/hc/en-us/articles/34418804557467-How-to-Return-Equipment-Rentals-in-EZFacility-Classic, https://support.ezfacility.com/hc/en-us/articles/34418766995099-How-to-Set-Up-Equipment-in-EZFacility-Classic, https://support.ezfacility.com/hc/en-us/articles/34419089287067-View-the-Checked-Out-Equipment-in-EZFacility-Classic

### Front-desk (staff) check-in
- Actors: front desk; client.
- Preconditions: client has a membership number (non-members can); staff check-in settings saved; optionally access rules applied to check-in.
- Steps:
  1. Staff open the check-in window (pop-out) at their station; focus is in the search field.
  2. Identify the client: scan card/fob barcode or the barcode on the member's phone app (2D scanner needed for screens), fingerprint device supplies the number, type the number, or type the name and pick from delayed suggestions.
  3. Decision (if access rules are applied): system evaluates the client's access mode (allow / deny / rules based) and, for rules-based clients, membership-state rules, time-of-day schedule and location mapping. Denied -> alert shown, no visit consumed, stop.
  4. System records the check-in (time, station, location), decrements a visit on visit-limited memberships, and marks attendance for any session of the client within the auto-attendance window.
  5. Window shows identity, membership state (active / visits depleted / non-member), last visit, waiver status, balance due, expired-card alert, relationships, today's sessions and packages (subject to the user's detail-visibility permission).
  6. Optional: staff select a schedulable package and book the client into a session starting soon (the window proposes open slots in the next few hours but never books by itself; staff may add several, e.g. for a parent and child); or follow the link to the full client record to take payment / renew.
  7. Clear the window for the next arrival.
- Rules/edge cases: auto-attendance window -3 h / +5 h around session start; book-in offered for sessions from -1 h to +4 h; shared clients can be checked in at any connected location; one-visit-per-day rule uses the location's local day; alternative entry point is the check-in button on the client profile.
- Feature IDs involved: CHK-01, CHK-02, CHK-03, CHK-04, CHK-08, CHK-09, CHK-10, CHK-11, CHK-14, CHK-21
- Evidence URLs: https://support.ezfacility.com/hc/en-us/articles/4405137521563-Using-the-Check-In-Window-in-EZFacility-Classic, https://support.ezfacility.com/hc/en-us/articles/4402434197147-How-to-use-the-Staff-Check-in-Window, https://support.ezfacility.com/hc/en-us/articles/27914147357339-Staff-Check-in-Station-Settings, https://support.ezfacility.com/hc/en-us/articles/27996895819547-Setting-up-Access-Control, https://support.ezfacility.com/hc/en-us/articles/4405137527067-Using-Check-In-from-Client-s-Page-in-EZFacility-Classic, https://support.ezfacility.com/hc/en-us/articles/23328878237467-February-28th-2024-Release-Notes, https://support.ezfacility.com/hc/en-us/articles/4405137541403-Using-Bluetooth-Scanners, https://www.youtube.com/watch?v=7JVYZ3kxUAo (t=33:00), https://www.youtube.com/watch?v=KAN6h9vPUiM (t=35:00), https://www.youtube.com/watch?v=Zs-8tpgvadk (t=43:02)

### Self check-in at a kiosk
- Actors: client; staff (launch); admin (settings).
- Preconditions: kiosk settings saved (lookup method, windows, auto-book, timeouts, alerts); a staff user opens the kiosk window on a tablet/desktop.
- Steps:
  1. Kiosk shows welcome message; client enters name and/or membership number, or scans a card.
  2. System finds the client (disabled clients excluded); if the vaccine gate is on and the client is unflagged -> deny.
  3. System records the check-in and marks attendance for a matching session.
  4. Decision: auto-book on -> system books the client into the closest eligible reservation; otherwise the reservation page lists sessions within the visible range honouring early/late check-in windows, and the client picks one.
  5. Decision: no usable package -> package page lets the client buy one (purchase flow at kiosk).
  6. Status screen: all clear, balance owed, or frozen/suspended; selected membership alerts shown (e.g. depleted, over daily limit); client is directed to staff where needed.
  7. Confirmation closes after its timeout; search field regains focus for the next client.
- Rules/edge cases: page timeouts return to start; "over daily limit" alert alone does not block or void the check-in; kiosk never controls door hardware.
- Feature IDs involved: CHK-05, CHK-06, CHK-08, CHK-17, CHK-14
- Evidence URLs: https://support.ezfacility.com/hc/en-us/articles/27550762531739-How-to-use-the-Self-Check-in-Station, https://support.ezfacility.com/hc/en-us/articles/27914135025819-Self-Check-in-Station-Settings, https://support.ezfacility.com/hc/en-us/articles/4405137537563-How-to-Set-up-the-Self-Check-In-Settings-in-EZFacility-Classic, https://support.ezfacility.com/hc/en-us/articles/4404311317403-Online-Webinar-Introducing-Self-Check-In-Advanced-Multi-Scheduling, https://support.ezfacility.com/hc/en-us/articles/23328878237467-February-28th-2024-Release-Notes, https://support.ezfacility.com/hc/en-us/articles/19132331777307-September-27th-2023-Release-Notes, https://support.ezfacility.com/hc/en-us/articles/22122496577179-January-17th-2024-Release-Notes, https://support.ezfacility.com/hc/en-us/articles/4411549886107-How-to-use-the-Vaccine-Passport-with-Self-Check-in

### Occupancy tracking and check-out
- Actors: manager; front desk.
- Preconditions: manager grants the check-out permission; checkout preference enabled; stations defined as main or secondary with capacities; location max capacity set.
- Steps:
  1. Check-ins at a main station raise the location head-count; check-ins at a secondary station raise that station's count.
  2. Staff watch the dashboard, filtering by client or station.
  3. Decision: approaching capacity -> tile colour changes; at capacity -> secondary station shows red and a menu alert appears; staff may override and admit anyway.
  4. When a guest leaves, staff check them out (or edit the check-out time, with a "now" shortcut). Main check-out also closes any open secondary check-in; secondary check-out only leaves that zone.
  5. Previous dates can be reviewed.
- Rules/edge cases: no evidence of automatic check-out (e.g. end of day) or of self check-out; capacity is advisory.
- Feature IDs involved: CHK-07, CHK-01
- Evidence URLs: https://support.ezfacility.com/hc/en-us/articles/4404305376795-How-to-Set-Up-the-Check-In-Dashboard-in-EZFacility-Classic, https://support.ezfacility.com/hc/en-us/articles/4405137543835-Online-Webinar-Check-in-Dashboard-in-EZFacility-Classic

### Configure access control
- Actors: owner/admin.
- Preconditions: membership types exist; for location mapping, multiple connected locations share clients.
- Steps:
  1. Open access-control settings for the location.
  2. Set each membership-state rule (expired, cancelled, suspended, frozen, depleted, past due with day threshold, max visits per day) to allow or deny.
  3. Optional: build named weekly schedules with time ranges per day and map membership types to them.
  4. Optional: map each membership type to the locations it may enter.
  5. Choose whether rules also apply in the software check-in windows.
  6. Choose the default access mode for new clients (allow / deny / rules based); adjust individual existing clients on their profiles.
  7. Save.
- Rules/edge cases: default mode is not retroactive; software enforcement toggle does not affect door devices.
- Feature IDs involved: CHK-08, CHK-09, CHK-10, CHK-02
- Evidence URLs: https://support.ezfacility.com/hc/en-us/articles/27996895819547-Setting-up-Access-Control, https://support.ezfacility.com/hc/en-us/articles/23328878237467-February-28th-2024-Release-Notes, https://support.ezfacility.com/hc/en-us/articles/27914147357339-Staff-Check-in-Station-Settings

### Issue a member credential (number, card, app card)
- Actors: front desk; admin; member.
- Preconditions: client record exists; ID card template designed (for printed cards).
- Steps:
  1. On the client's membership details, generate a random membership number or scan a pre-printed key tag / fob into the number field; save.
  2. Optional: capture or upload the client photo and generate/print an ID card from the active template.
  3. Optional: member registers the card number in the mobile app (or adds a wallet pass) and uses the on-phone barcode.
  4. If an app-registered card is wrong or stuck, chain admin finds it by number / created date in the app console and deletes it (or clears all).
- Rules/edge cases: only the membership-number field is used by check-in; alphanumeric numbers allowed; bulk card clearing is chain-wide and irreversible.
- Feature IDs involved: CHK-11, CHK-12, CHK-13, CHK-14
- Evidence URLs: https://support.ezfacility.com/hc/en-us/articles/4405137473947-Assigning-a-Membership-Number, https://support.ezfacility.com/hc/en-us/articles/4416952099611-How-to-Generate-an-ID-Card, https://support.ezfacility.com/hc/en-us/articles/29244336130203-Clear-client-member-card-from-database-MemberMe-Branded-App, https://support.ezfacility.com/hc/en-us/articles/29852099999259-Setting-Up-a-Simple-Membership-in-EZFacility-Classic, https://www.ezfacility.com/features/member-engagement

### Door access synchronisation (hardware partner)
- Actors: admin; access-control vendor cloud; member.
- Preconditions: tenant has an access-control account; a dedicated service user for the integration exists in that account with credentials held by the platform.
- Steps:
  1. Admin (with vendor support) links the account; platform authenticates as the service user.
  2. Platform pushes member identities/credentials and entitlement changes to the door system as memberships change (sell, freeze, expire, arrears).
  3. Door readers admit or refuse locally; door system may apply anti-passback, per-area groups and after-hours notifications.
  4. On vendor platform migration, admin updates the service user's details so the platform can reset its stored password and keep syncing.
- Rules/edge cases: software check-in rule enforcement is independent of door enforcement; outage of the service user breaks sync; event flow back from doors to check-in history is not evidenced.
- Feature IDs involved: CHK-16, CHK-08, CHK-15
- Evidence URLs: https://support.ezfacility.com/hc/en-us/articles/8305870999323-Updating-your-EZFacility-User-in-Brivo-Access, https://www.ezfacility.com/press-news/press-releases/ezfacility-partners-with-brivo-to-offer-24-hour-sports-fitness-access, https://www.ezfacility.com/blog/the-top-5-advantages-of-gun-range-management-software, https://support.ezfacility.com/hc/en-us/articles/27996895819547-Setting-up-Access-Control

## Leagues & Tournaments, Groups & Online Registration

### Run a round-robin league season
- Actors: admin (registration), league admin/scheduler, scorekeeper, officials, players/public.
- Preconditions: sport exists with defaults, standings rules and stat tables; venues exist; classifier values (season, sport, age/division) exist.
- Steps:
  1. Create a registration group for the season; add subgroups as teams (or let captains create them online via a "new team" fee).
  2. Configure online registration: fees (individual / join team / new team), deposit or schedule, window, payment requirement; share the link or publish to the client portal.
  3. Registrations arrive; staff handle walk-ins, waitlist promotion and team moves.
  4. Publish the group to the league system as "League Round Robin" with age group, division, season dates, sport, display fees, minutes per game and discipline caps. Decision: league vs tournament family is locked from here on.
  5. Alternatively create the league directly and add teams by generating placeholders or copying from an earlier competition; adjust seeds.
  6. Add players and officials.
  7. Run the schedule generator (next flow); commit games.
  8. Games appear on the public site, TV board and team calendar feeds.
  9. Each game night: print game cards (batch by sport/date), assign officials, enter results, participation, sportsmanship, bonus points and player stats. System recomputes standings and leaders.
  10. Handle postponements (reschedule prompt) and cancellations (excluded from standings); mid-season, re-run the generator from pairing N if teams change.
  11. Season end: mark the registration group Completed (or let auto-archive do it).
- Rules / edge cases: discipline caps (max defaults, max forfeits, min sportsmanship) are stored per competition, enforcement is manual as far as documented; sport defaults are copied at creation and never back-propagate; pickup games cannot follow this path.
- Video-observed order and decision points: vendor's demo order is register teams first, publish only when all teams are in (clearing the registration link at publish), then map venues, then generate. Age group is required at publish. The publish form ends with two switches (subgroups as teams, members as players); players must be published for stats and email alerts. Decision after publish when a team joins late: push the new subgroup to the league (New UI), then either hand-add its games or re-run the wizard (which overwrites existing games). Playoffs: either hand-add post-season games with a round label (LGE-31), or copy the top teams into a new group and publish it as an elimination tournament; nothing rolls over automatically. Next season: copy the group, publish, run the wizard again.
- Feature IDs: REG-01, REG-02, REG-10, REG-12, REG-14, LGE-01, LGE-03, LGE-04, LGE-05, LGE-06, LGE-08, LGE-14, LGE-15, LGE-16, LGE-18, LGE-24, LGE-25, REG-05.
- Evidence: https://support.ezfacility.com/hc/en-us/articles/4405044226587-How-to-Publish-a-Group-to-EZLeagues-from-EZFacility, https://support.ezfacility.com/hc/en-us/articles/11453271338523-How-to-Create-a-League, https://support.ezfacility.com/hc/en-us/articles/10414795167387-How-to-Generate-a-League-Schedule-Even-Number-of-Team, https://support.ezfacility.com/hc/en-us/articles/10414799252763-How-to-Manage-Scores-in-EZLeagues, https://support.ezfacility.com/hc/en-us/articles/4405044313371-How-to-Manage-your-Sports, https://support.ezfacility.com/hc/en-us/articles/17323515477659-How-to-Allow-Clients-to-Register-for-a-Group-Online, https://support.ezfacility.com/hc/en-us/articles/23929852504219-How-to-Mark-a-Group-as-Completed, https://www.youtube.com/watch?v=VuUR1Y9bhjQ, https://www.youtube.com/watch?v=bHzYz6ZzMSE (t=03:00), https://www.youtube.com/watch?v=j4Rn9joKKpQ (t=10:14), https://www.youtube.com/watch?v=j4Rn9joKKpQ (t=20:24), https://www.youtube.com/watch?v=okhjK-XBid4 (t=51:06)

### Generate a round-robin or pool-play schedule
- Actors: league scheduler.
- Preconditions: competition has teams; venues defined; optional team preferences.
- Steps:
  1. From the competition's edit page start schedule generation; pick one or several competitions to schedule together.
  2. Select venues.
  3. Set start/end, weekdays, optional cut-off date; pick the dates; build time slots from a first start time and game length (subsequent slots auto-increment).
  4. Set games per week and total games (leagues) or games per team (pool play). Choose options: start pairings at game N, wipe previously scheduled games, avoid venue double-booking, drop unschedulable games, back-to-back doubleheaders, moved dates (holidays/closures). Odd team count: choose a bye strategy.
  5. Enter per-team preferences (date, weekday, slot, home venue, visitor venue; each optionally priority).
  6. Finalize screen: read the status bar (slot shortage/excess, byes, games scheduled); choose rotation strategy; hand-edit the grid and refresh. Decision: if infeasible go back and add slots/venues or relax the cut-off.
  7. Review balance statistics (home/away, per venue, per slot, per weekday per team).
  8. Commit: games are created; anything that did not fit is listed as unschedulable.
- Rules / edge cases: preferences are soft; priority > preference > none; total games must include byes; "rotate team" bye mode gives uneven game counts on an incomplete round robin; progress is auto-saved so a run can be resumed; double-booking avoidance is an option, not a hard constraint, in their system.
- Video-observed order and decision points: wizard opens in a new window with the launching league pre-ticked; "Minutes per game" entered at publish (including turnaround) drives slot spacing; individual slots can be deleted for breaks; leave cut-off blank and tune games per week while watching the predicted completion date; set total games to the regular season only; all dates must share one set of start times; rotation (left through venues, down through slots) is chosen to spread teams across fields and days; a balancing step lists conflicts with date and cause and allows pushing games to the end of the league; re-entry on a scheduled league offers to resume the previous session.
- Feature IDs: LGE-08, LGE-09, LGE-10, LGE-11.
- Evidence: https://support.ezfacility.com/hc/en-us/articles/26753867674011-How-to-Generate-a-League-Schedule-Even-Number-of-Team, https://support.ezfacility.com/hc/en-us/articles/26754181794331-How-to-Generate-a-League-Schedule-Odd-Number-of-Teams-Bye, https://support.ezfacility.com/hc/en-us/articles/26754163075099-How-to-Generate-a-Pool-Play-Schedule-in-EZLeagues, https://support.ezfacility.com/hc/en-us/articles/26720911427099-Picking-Team-Preferences-in-EZLeagues, https://www.ezfacility.com/press-news/press-releases/ezfacility-updates-ezleagues-scheduling-wizard, https://www.youtube.com/watch?v=bHzYz6ZzMSE (t=10:19), https://www.youtube.com/watch?v=okhjK-XBid4 (t=42:56), https://www.youtube.com/watch?v=j4Rn9joKKpQ (t=29:36), https://www.youtube.com/watch?v=j0cg9SW8Npo (t=04:20)

### Run an elimination tournament
- Actors: tournament director, scorekeeper.
- Preconditions: tournament created (single elimination, double elimination or three-games-guaranteed) with seeded teams; exactly 8 teams for three-games-guaranteed.
- Steps:
  1. Optionally run pool play first (previous flow) on the same tournament.
  2. Start bracket generation from the tournament edit page.
  3. Select venues.
  4. Select dates; define time slots for every date (start time + game length).
  5. Set bracket preferences: keep winners on the same field or optimise for time; lower-bracket crossing mode (double elimination / 3GG); rename regions and rounds.
  6. Preview pairings; go back to adjust if needed.
  7. Create the bracket; it is immediately visible on the public site.
  8. Enter results as games finish; winners advance (advancement mechanics inferred).
- Rules / edge cases: every chosen date needs slots; AB/BA is the normal lower-bracket mode; how pool results seed the bracket is undocumented.
- Video-observed order and decision points: pool play covers a single pool per published group, so multi-pool events are run as separate groups with winners moved by hand into the bracket group; brackets accept any time slots per date; a 13-team field is placed in a 16-slot bracket with byes for the top three seeds, shown in the preview.
- Feature IDs: LGE-02, LGE-03, LGE-11, LGE-12, LGE-13, LGE-14, LGE-18.
- Evidence: https://support.ezfacility.com/hc/en-us/articles/10414682862235-How-to-Create-a-Tournament-in-EZLeagues, https://support.ezfacility.com/hc/en-us/articles/26753390899995-How-to-Create-a-Tournament-Schedule-Single-Elimination-Bracket, https://support.ezfacility.com/hc/en-us/articles/26753407797019-How-To-Create-a-Tournament-Schedule-Double-Elimination-Bracket, https://support.ezfacility.com/hc/en-us/articles/26753410817051-How-To-Create-a-Three-Games-Guaranteed-Schedule-8-Team-Tournament, https://www.youtube.com/watch?v=j4Rn9joKKpQ (t=17:21), https://www.youtube.com/watch?v=j0cg9SW8Npo (t=13:00)

### Record a result and update standings
- Actors: scorekeeper.
- Preconditions: scheduled game exists.
- Steps:
  1. Open score management; filter by league and game status; choose the date.
  2. Optionally attach officials and print the game card.
  3. Add result: score per side, participation per side (full / default / forfeit), optional sportsmanship rating, bonus points, per-player stats.
  4. Save. System shows the score in place of the entry link and recomputes standings columns, points and leaders.
  5. Alternative: mark postponed -> system asks for new date/time; mark cancelled -> game drops out of standings.
- Rules / edge cases: sportsmanship only when tracked; points per outcome and sort order come from the sport's standings config as copied to the competition.
- Video-observed order and decision points: the score form has a confirm-both-scores step and an overtime / extra-time entry; no live scoring; changing a published game's time, venue or status triggers the game-change email to both teams when alerts are on (LGE-30).
- Feature IDs: LGE-14, LGE-06, LGE-07, LGE-15, LGE-16.
- Evidence: https://support.ezfacility.com/hc/en-us/articles/26754230417819-How-to-Manage-Scores-in-EZLeagues, https://support.ezfacility.com/hc/en-us/articles/4405044313371-How-to-Manage-your-Sports, https://www.youtube.com/watch?v=j4Rn9joKKpQ (t=37:47), https://www.youtube.com/watch?v=edzJ6kuAvMQ (t=17:29)

### Set up the public league site and lobby board
- Actors: league admin.
- Preconditions: league admin account.
- Steps:
  1. Enter facility contact info and About text; upload logo/banner (JPG).
  2. Choose menu items, colours (incl. link colour), search-indexing flag.
  3. Add links, photos (optionally featured), pickup-game listings.
  4. Per competition choose what is displayed publicly.
  5. Build a filtered list, generate a public URL, optionally the iframe snippet, and embed on the facility website.
  6. Open the TV display on a lobby screen.
  7. Players copy their team's calendar-subscription link from the standings section.
- Rules / edge cases: iframe snippet requires a generated URL first; classifieds are user-generated and can only be deleted by the admin.
- Feature IDs: LGE-17, LGE-18, LGE-19, LGE-20, LGE-21, LGE-22, LGE-23, LGE-24, LGE-25.
- Evidence: https://support.ezfacility.com/hc/en-us/articles/4405044374171-How-to-Configure-your-Site-Options, https://support.ezfacility.com/hc/en-us/articles/4405044330523-How-to-Filter-your-Leagues-and-Tournaments, https://support.ezfacility.com/hc/en-us/articles/4405044351259-How-to-Utilize-the-TV-Display, https://support.ezfacility.com/hc/en-us/articles/4404311560475-EZLeagues-Team-Schedule-Calendar-Sync-Google-Calendar, https://support.ezfacility.com/hc/en-us/articles/4405044372123-How-to-Manage-your-Classifieds

### Configure online registration for a group and register online
- Actors: admin; client / parent / captain.
- Preconditions: group (and subgroups if choice is offered) exists; account defaults set; card processing active.
- Steps:
  1. Admin opens the group's online-registration tab and adds at least one fee: individual, join-an-existing-subgroup, or create-a-new-team; sets amount, optional deposit, optional instalment schedule and auto-pay.
  2. Admin sets open/close dates, notification recipients, payment requirement, force-store-card, coupon acceptance, disallow-partial, and the description.
  3. Admin copies the link and/or publishes to the client portal.
  4. Registrant opens the page inside the window, picks the fee/subgroup (or names a new team), may add further subgroups/participants to the cart, applies a coupon if allowed.
  5. Decision by payment requirement: pay in full, pay deposit, store card without charge, or defer. System creates the registration(s), invoice(s), any scheduled instalments, and stores the card when forced.
  6. If the node is at capacity and waitlisting is on, the registration is created as waitlisted and not billed (inferred from staff-side behaviour).
  7. Confirmation/receipt email to registrant; notification email to staff recipients.
- Rules / edge cases: no fee = registration not live; dates switch at midnight; disallow-partial overrides deposit; Classic re-requires ticking "enable" after a fee edit; one registration per client per node.
- Video-observed order and decision points: account defaults are set first under Administration > Online Registration; a fee must exist before registration can be switched on; "Disallow partial" must be off before a deposit or schedule works. Registrant side: choose New Team / Individual / With a Team, enter details (fields from Contact Preferences), optional comment, accept the single attached document if any, then pay per the payment requirement (only the deposit is taken at pay-now).
- Feature IDs: REG-10, REG-11, REG-12, REG-09, REG-02.
- Evidence: https://support.ezfacility.com/hc/en-us/articles/17323515477659-How-to-Allow-Clients-to-Register-for-a-Group-Online, https://support.ezfacility.com/hc/en-us/articles/31149286284187-How-to-Set-Up-Online-Registration-for-a-Group-in-the-Classic-EZFacility-Experience, https://support.ezfacility.com/hc/en-us/articles/16846068050715-July-3rd-2023-Release-Notes, https://support.ezfacility.com/hc/en-us/articles/4415441369883-How-to-Set-Online-Registration-Default-Settings, https://www.youtube.com/watch?v=VuUR1Y9bhjQ (t=10:15), https://www.youtube.com/watch?v=VuUR1Y9bhjQ (t=24:31), https://www.youtube.com/watch?v=VuUR1Y9bhjQ (t=31:44)

### Staff registers a client into a group
- Actors: front desk.
- Preconditions: a program fee exists for the group; group active.
- Steps:
  1. Open the group (or a subgroup via related groups) and start member registration.
  2. Search an existing client or create one.
  3. Select the program fee; continue to review.
  4. Decision: take payment now (any tender incl. bank transfer) or pay later -> invoice is issued/sent.
  5. Member appears in the group roster; invoice on the client ledger.
- Rules / edge cases: duplicates in the same node are rejected; open group invoices can later be settled from the client's Groups tab.
- Video-observed order and decision points: removal path: trash icon on the member row, then choose reverse billing and delete (needs reason and original bill date; result is account credit, not a card refund), delete but keep billing, show invoice only, or cancel.
- Feature IDs: REG-07.
- Evidence: https://support.ezfacility.com/hc/en-us/articles/4415441342235-How-to-Manually-Register-a-Client-into-a-Group-or-a-Sub-group, https://support.ezfacility.com/hc/en-us/articles/16731304236571-June-28th-2023-Release-Notes, https://www.youtube.com/watch?v=VuUR1Y9bhjQ (t=50:10)

### Promote from waitlist
- Actors: front desk / admin.
- Preconditions: member in waitlisted state.
- Steps:
  1. Open group roster; waitlisted rows are visually flagged.
  2. Select rows; apply "set as enrolled".
  3. Use "bill now" to create the charge and finalise enrolment.
  4. Reverse path: select enrolled rows and set as waitlisted.
- Rules / edge cases: billing happens at enrolment; no automatic promotion or notification is documented for groups.
- Feature IDs: REG-09.
- Evidence: https://support.ezfacility.com/hc/en-us/articles/4415445455771-How-to-Remove-or-Add-a-Client-using-Waitlist, https://support.ezfacility.com/hc/en-us/articles/4404931880219-How-to-Remove-Client-from-Waitlist

### Move members or re-parent a subgroup
- Actors: admin.
- Preconditions: destination is active.
- Steps:
  1. Select members (or subgroups) in the source group; choose the move action.
  2. In the target picker filter by session/sport/age-division/name, expand the tree, pick the destination node.
  3. Decide whether revenue category is rewritten to the destination's.
  4. Confirm; system reports attempted / succeeded / failed.
- Rules / edge cases: members already in the destination fail individually (partial success); billing is not re-priced (inferred).
- Feature IDs: REG-08, REG-02.
- Evidence: https://support.ezfacility.com/hc/en-us/articles/4404924790939-How-to-Move-a-Client-Between-Groups-Sub-Groups, https://support.ezfacility.com/hc/en-us/articles/4415441379483-How-to-Move-a-Client-Between-Groups-or-Sub-Groups, https://support.ezfacility.com/hc/en-us/articles/4404931863963-How-to-Move-a-Sub-Group-Between-Groups

### Close out, archive and restore a group
- Actors: admin.
- Steps:
  1. Set status to completed, or rely on the auto-archive date set at creation.
  2. Group leaves active views; remains under completed views and searchable when the active-only box is cleared.
  3. Delete moves it to a deleted view; undelete restores it to active.
- Rules / edge cases: completed/archived groups cannot receive moved members.
- Feature IDs: REG-05, REG-04.
- Evidence: https://support.ezfacility.com/hc/en-us/articles/23929852504219-How-to-Mark-a-Group-as-Completed, https://support.ezfacility.com/hc/en-us/articles/4404924800539-How-to-Undelete-a-Deleted-Group, https://support.ezfacility.com/hc/en-us/articles/4404931875227-How-to-Find-Search-Groups

### Build and publish an event registration form
- Actors: organiser (owner/admin).
- Steps:
  1. Create a form from an event-type template (or copy a previous form of the same format) and enter event name, date/location, start/end.
  2. Edit information topics and questions; add priced choices, checkbox add-ons, quantity items, amount-entry items; set shown/hidden, mandatory, hint/help, expiry.
  3. Add inventory caps and sold-out messages where stock is limited.
  4. Publish; then upload the header image and tune colours/width/font.
  5. Preview in admin mode as a registrant.
  6. Copy the link and post it; set auto-close date/time.
  7. During registration: monitor summaries (registrants, revenue, demographics, answers), look up/edit registrations, export files, optionally publish a searchable entrant page.
- Rules / edge cases: deleting questions/answers after go-live destroys captured answers (hide or expire instead); template dependencies break if the parent question is deleted; summary data may lag about five minutes.
- Feature IDs: REG-15, REG-16, REG-17, REG-18, REG-19, REG-20, REG-21, REG-22, REG-24.
- Evidence: https://support.ezfacility.com/hc/en-us/articles/4414746736155-How-to-Create-New-Form-1st-Time-Set-Up-Event, https://support.ezfacility.com/hc/en-us/articles/4414758416539-How-to-COPY-an-Existing-Form, https://support.ezfacility.com/hc/en-us/articles/4414758842523-How-to-Add-Edit-Multiple-Choice-Questions, https://support.ezfacility.com/hc/en-us/articles/4414758916251-How-to-Add-Inventory-Control-Multiple-Choice-Questions, https://support.ezfacility.com/hc/en-us/articles/4414739101339-Form-Menu-Features-Overview, https://support.ezfacility.com/hc/en-us/articles/4414782814363-How-to-add-edit-a-Form-Header-Graphic

### Register for an event through a form
- Actors: client / parent.
- Preconditions: form open; registrant has or creates a portal account.
- Steps:
  1. Open the link; sign in or create an account (bot check, verification email, then complete contact details).
  2. Choose who is being registered (self or another person).
  3. Answer questions; priced selections accumulate.
  4. Review; optionally clear charges or loop back to add another registrant; proceed.
  5. Pay; receipt on screen and by email.
  6. System writes an invoice to the client's billing record (skipped when total is zero) and lists the registration on the client profile.
- Rules / edge cases: unverified accounts cannot sign in; sold-out options are removed or disabled at render time.
- Feature IDs: REG-23, REG-17.
- Evidence: https://support.ezfacility.com/hc/en-us/articles/4505589011227-Registering-for-an-Event-in-EZSignUp

### Captain registers a team, enters the roster and splits the fee
- Actors: captain / coach, players, admin.
- Preconditions: group has a new-team fee; roster-entry mode allows captain entry (with or without payment assignment).
- Steps:
  1. Captain opens the registration link, chooses New Team, names the team and enters own details; pays or defers per the payment requirement.
  2. System emails the captain a roster link (staff can resend it).
  3. Captain adds players (first name, last name, home phone, date of birth, email); each player is created as a client and emailed.
  4. Decision: if payment assignment is allowed, the captain assigns shares of the team fee to players, who pay their own share online; otherwise the whole balance stays on the captain.
  5. Staff see the team with the captain starred, each player's waiver status and balances.
- Rules / edge cases: unassigned balance remains with the captain; how a player receives the payment link is not shown; mode "No" means staff build teams.
- Feature IDs: REG-26, REG-10, REG-11, REG-12.
- Evidence: https://www.youtube.com/watch?v=VuUR1Y9bhjQ (t=18:24), https://www.youtube.com/watch?v=VuUR1Y9bhjQ (t=41:36), https://www.youtube.com/watch?v=edzJ6kuAvMQ (t=15:25)

## Staff & Payroll, Marketing, Self-Service Portal, Mobile App

### Configure trainer compensation
- Actors: administrator.
- Preconditions: location exists; reservation types and membership types defined (for overrides).
- Steps:
  1. Open the location's resource setup and add a trainer by name; the system creates a schedule calendar for the trainer and makes the trainer selectable as seller on sales.
  2. Choose pay basis (per attendee or per session) and enter duration rates (60/45/30 min), comp-session rate, and flat rates for program instruction, non-training time and floor time.
  3. Enter default sales commission (percent of package value and/or flat per package).
  4. Optionally add per-reservation-type overrides (basis, rates, sales commission).
  5. Optionally add per-membership-type sale commission (percent or flat) and tick first-invoice-only where renewals must not pay commission.
  6. Optionally add trained-hour bonuses (threshold, amount, extra-hours-only) and off-hour bonus windows per weekday.
- Rules/edge cases: session commission percentage is ignored on per-session basis; no default membership commission at trainer level; override resolution order (specific beats default) is implied, not stated; rate changes appear to apply retroactively to any report range (no effective dating evidenced).
- Feature IDs: STF-01, STF-02, STF-03, STF-04
- Evidence: https://support.ezfacility.com/hc/en-us/articles/4403486979739-Adding-or-Editing-a-Trainer-in-EZFacility-Classic, https://support.ezfacility.com/hc/en-us/articles/4402427211163-Adding-or-Editing-a-Trainer, https://support.ezfacility.com/hc/en-us/articles/28333307842971-How-to-Set-Up-Trainer-Commission

### Configure salesperson commission and attribute a sale
- Actors: administrator, front desk.
- Preconditions: location exists.
- Steps:
  1. Add a salesperson (name) with default package, session and membership commission (percent and/or flat) and the first-invoice-only flag.
  2. Optionally add overrides per program type and per membership type.
  3. At sale of a package or membership, staff select the seller ("Sold By"); trainers are selectable too.
  4. System stores the seller on the sale; commission accrues from invoices (or payments) and from later session completions.
- Rules/edge cases: missing seller = no commission; first-invoice-only suppresses commission on renewals and later instalments.
- Feature IDs: STF-05, STF-10
- Evidence: https://support.ezfacility.com/hc/en-us/articles/4403486981915-Adding-or-Editing-a-Salesperson-in-EZFacility-Classic, https://support.ezfacility.com/hc/en-us/articles/4403493414683-Salesperson-Commission-Report

### Time clock: set up, punch, correct
- Actors: administrator, employee, manager.
- Preconditions: each employee has a user account with a role.
- Steps:
  1. Admin defines job classifications.
  2. Admin assigns each user one or more hourly rates, each tied to a classification.
  3. Admin sets the IP policy: allow any, or list permitted addresses (current address offered by default).
  4. Employee opens the time clock, authenticates with own credentials, picks a classification (auto-selected when only one) and clocks in; system records the start.
  5. Employee repeats to clock out; system closes the entry.
  6. Manager searches for a staff member, then adds, edits or deletes entries (missed punches).
  7. Manager runs the time clock report by date range, staff and classification and exports it.
- Rules/edge cases: request from a non-allowed IP is refused; staff cannot edit entries or reach another user's clock; handling of an open entry at day end, overlapping entries, rounding, breaks and overtime is undocumented.
- Feature IDs: STF-06, STF-07, STF-08
- Evidence: https://support.ezfacility.com/hc/en-us/articles/27882337605915-How-to-Setup-the-Employee-Time-Clock, https://support.ezfacility.com/hc/en-us/articles/27882374264603-How-to-Use-the-Employee-Time-Clock-as-Staff, https://support.ezfacility.com/hc/en-us/articles/4406988987803-How-to-Use-the-Employee-Time-Clock-as-a-Manager, https://support.ezfacility.com/hc/en-us/articles/30051822805659-How-to-Use-the-Employee-Time-Clock-in-EZFacility-Classic, https://support.ezfacility.com/hc/en-us/articles/14655161654811-April-18th-2023-Release-Notes

### Payroll / commission run
- Actors: owner or payroll administrator; trainer (own statement).
- Preconditions: sessions marked completed with attendance; sales carry a seller; time entries closed.
- Steps:
  1. Pick the pay period (start/end dates).
  2. Run the trainer payroll/commission report per trainer; choose whether commission is computed from invoiced or paid amounts; optionally add a manual additional-income amount; choose detail grouping.
  3. System computes session pay from completed sessions using the trainer's basis and rates (service-specific overrides where present), comp-session pay, flat-rate activities, bonuses, and sales/membership commission.
  4. Run the salesperson commission report for the same period (one or all salespeople) with the same invoiced/paid choice.
  5. Run the time clock report for hourly staff.
  6. Export each report and hand off to external payroll.
- Rules/edge cases: only completed sessions pay; session-completion commission for salespeople always uses billed package value and is dated by session; trainers see only their own data; no evidence of a locked/approved payroll period, so reruns can change after late edits — we should add period locking.
- Feature IDs: STF-08, STF-09, STF-10, STF-11
- Evidence: https://support.ezfacility.com/hc/en-us/articles/4403486264219-Trainer-Payroll-Commission-Report, https://support.ezfacility.com/hc/en-us/articles/4403493414683-Salesperson-Commission-Report, https://support.ezfacility.com/hc/en-us/articles/30051822805659-How-to-Use-the-Employee-Time-Clock-in-EZFacility-Classic, https://support.ezfacility.com/hc/en-us/articles/22122496577179-January-17th-2024-Release-Notes

### Email address verification and subscription choice
- Actors: staff, client.
- Preconditions: client record exists.
- Steps:
  1. An email address is added or changed (by staff, by self-registration or via the portal); status becomes Pending and a verification message is sent immediately.
  2. Client follows the verification link; system records IP and timestamp.
  3. Client is shown subscription topics: session reminders and card-expiry notices pre-selected, marketing campaigns as an explicit opt-in; submits.
  4. Status becomes Verified; a confirmation message with a manage-subscriptions link is sent.
  5. Later, client (via link) or staff (profile toggles) change topics per address.
  6. If the client never verifies, staff may resend or manually verify.
- Rules/edge cases: manual verification leaves no consent proof; one verification per address per client; unverified or unsubscribed addresses are excluded from campaigns.
- Feature IDs: MKT-01, MKT-02, MKT-09
- Evidence: https://support.ezfacility.com/hc/en-us/articles/4405137478299-Email-Verification-and-Subscriptions-For-Clients, https://support.ezfacility.com/hc/en-us/articles/24856876239771-Email-Verification-and-Subscriptions-For-Clients, https://support.ezfacility.com/hc/en-us/articles/4405144414875-Managing-Email-Subscriptions-on-a-Client-s-Profile, https://support.ezfacility.com/hc/en-us/articles/4405144438939-Benefits-of-Email-Verification

### Send an email campaign
- Actors: marketing staff (publish permission in the 2024 generation).
- Preconditions: sender address/user; audience categories defined; recipients verified and subscribed.
- Steps:
  1. Start a campaign; enter subject and sender.
  2. Choose audience: a built-in segment (all contacts, members, non-members, birthdays this/next month) or saved client categories; optionally add filters (e.g. membership expiration, birth month).
  3. Choose a saved template or base layout; compose (rich text in the legacy wizard, row/column drag-and-drop in the 2024 builder); insert links and library images.
  4. Optionally save as draft and/or as a named template.
  5. Send a test (legacy: to the return address; 2024: to any comma-separated addresses).
  6. Dispatch: legacy sends immediately; 2024 allows now or a scheduled date/time.
  7. System resolves recipients, removes duplicates, invalid, suppressed and non-consenting addresses, appends the mandatory unsubscribe link, queues delivery.
  8. Review history/sent view: counters and per-recipient status; export CSV.
- Rules/edge cases: legacy blast cannot be recalled; decision point at step 7 produces the "attempted / duplicates / invalid / blacklisted / sent" counters; hard bounces feed the suppression list. Video (2024 builder): order shown is permission check, new campaign, subject and sender, category/filters/tags, layout or saved template, edit rows and columns (AI image, Smart Text), device preview, test send, then send now or schedule; scheduled items sit in a Scheduled tab until sent; an account uses either the legacy tools or the builder, not both.
- Feature IDs: MKT-03, MKT-04, MKT-05, MKT-06, MKT-07, MKT-08, MKT-09
- Evidence: https://support.ezfacility.com/hc/en-us/articles/4405137490843-How-to-Send-an-Email-Campaign-in-EZFacility-Classic, https://support.ezfacility.com/hc/en-us/articles/5776809698075-How-to-create-an-Email-Campaign-in-the-New-EZFacility-Experience, https://support.ezfacility.com/hc/en-us/articles/27808005266843-Create-a-New-Email-Campaign-2024, https://support.ezfacility.com/hc/en-us/articles/27808007575195-How-to-Edit-an-Email-Campaign-Draft-2024, https://support.ezfacility.com/hc/en-us/articles/27808030170267-Sent-Email-Campaign-2024, https://support.ezfacility.com/hc/en-us/articles/5777441102235-How-to-view-your-Campaign-History-in-the-New-EZFacility-Experience, https://www.youtube.com/watch?v=bxCUg7Y5PsI (t=02:09, t=10:22), https://www.youtube.com/watch?v=TWNQ4cTiEFs (t=20:34)

### Bounce and suppression handling
- Actors: system, administrator.
- Preconditions: outbound email in flight.
- Steps:
  1. Provider reports a hard bounce or spam complaint; system adds the address to the suppression list with reason and date.
  2. Future sends skip the address and count it as blacklisted/dropped.
  3. Admin reviews the list, inspects the reason, and either corrects the address or unblocks it.
  4. If it fails again it is re-suppressed.
- Rules/edge cases: persistent invalid addresses are purged; excessive failures can trigger account-level email suspension by the vendor (we need an equivalent tenant-level reputation breaker).
- Feature IDs: MKT-08
- Evidence: https://support.ezfacility.com/hc/en-us/articles/4405137505179-Manage-Failed-Email-in-in-EZFacility-Classic, https://support.ezfacility.com/hc/en-us/articles/25985296561179-May-23rd-2024-Release-Note, https://support.ezfacility.com/hc/en-us/articles/4405137514267-Canada-Anti-Spam-Law

### Email a client, group or form audience ad hoc
- Actors: front desk, coordinator.
- Preconditions: target has at least one email on file.
- Steps:
  1. From a client profile choose send-email; select sender user, subject (saved or new), template or free text; send. The message is logged against the client.
  2. From the groups list use the envelope on a group/subgroup/registrant, or select several groups and email them; the campaign composer opens with recipients resolved from registrants (including subgroups).
  3. For form registrants, choose one or more forms, enter from/subject/body, preview, submit to the queue.
- Rules/edge cases: envelope hidden if nobody has an email; form broadcasts have no tracking and may be delayed for hours.
- Feature IDs: MKT-10, MKT-11, MKT-12
- Evidence: https://support.ezfacility.com/hc/en-us/articles/33119920006427-How-to-direct-email-a-client-through-their-profile-in-EZFacility-Classic, https://support.ezfacility.com/hc/en-us/articles/33122944575899-How-to-direct-email-a-client-through-their-profile, https://support.ezfacility.com/hc/en-us/articles/4404931886235-How-to-Send-an-Email-Campaign-to-Groups, https://support.ezfacility.com/hc/en-us/articles/4404931926939-How-to-Email-Group-Subgroup-Registrants, https://support.ezfacility.com/hc/en-us/articles/4415441383707-How-to-Send-an-Email-Campaign-to-Groups, https://support.ezfacility.com/hc/en-us/articles/5777638736027-How-To-Send-email-broadcasts-message-to-FORM-registrants

### Send a push notification (broadcast, targeted, scheduled)
- Actors: app administrator with notification permission.
- Preconditions: members have the app installed with notifications allowed; targeted mode needs the extra subscription and a branded app.
- Steps:
  1. Create a message (up to 180 characters, optional URL).
  2. Optionally add audience filters (age, gender, last check-in, membership status, app activity), inverting any of them.
  3. For multi-location apps choose receiving locations.
  4. Post now, or tick schedule and set date/time.
  5. System delivers to matching devices; the message is listed in history and in members' in-app notification list (30 days).
  6. Admin inspects analytics, copies the message for reuse, or deletes it.
- Rules/edge cases: no filters = everyone at the chosen locations; whether a scheduled message can be edited before send is not stated. Video: after posting, the message shows 'preparing for sending' and can be recalled for a few seconds; later a trash icon in history removes it from members' notification lists; the shared app's composer has no targets; no limit on the number of sends.
- Feature IDs: MKT-16, MKT-17, APP-16, APP-17
- Evidence: https://support.ezfacility.com/hc/en-us/articles/29244337277083-Sending-Push-Notifications-MemberMe-Branded-App, https://support.ezfacility.com/hc/en-us/articles/29194752348827-Sending-Targeted-Push-Notifications-Branded-App-Only-Additional-subscription-required, https://support.ezfacility.com/hc/en-us/articles/29244296451355-Sending-Targeted-Push-Notifications-Branded-App-Only-Additional-subscription-required, https://www.youtube.com/watch?v=uLNIb7JsjkM (t=12:18, t=42:04)

### Session reminder dispatch
- Actors: system, client, trainer.
- Preconditions: reminders configured (one or two offsets); client subscribed to session reminders on a verified address/number.
- Steps:
  1. Scheduler finds sessions falling inside a reminder offset.
  2. For each attendee with the subscription on, send by the configured channel(s); send the trainer copy when enabled.
  3. Record the send so each offset fires once per booking.
- Rules/edge cases: at most two reminders per session; behaviour for bookings made inside the offset window is unspecified (assume: skip the elapsed reminder).
- Feature IDs: MKT-13, MKT-02, STF-12
- Evidence: https://support.ezfacility.com/hc/en-us/articles/18308941711899-How-to-Enable-Disable-Email-Notifications, https://support.ezfacility.com/hc/en-us/articles/4405137478299-Email-Verification-and-Subscriptions-For-Clients

### Enable and configure the portal
- Actors: owner/administrator.
- Preconditions: location, reservation types, rental types, package plans exist.
- Steps:
  1. Enable the portal for the location; set the vanity URL; decide whether anonymous visitors may browse and which page they land on.
  2. Turn on session booking and set the nine defaults (availability, requirements, visible range, hide full, cutoffs, post-billed, adjacency, waitlist, auto-book).
  3. Turn on rental booking and set visible range, search-start limit and checkout hold time; override per rental type.
  4. Decide public registration and whether verification is required.
  5. Enable coupons; mark package plans as sold online (balances allowed or paid in full); allow sale of fixed-start products after start if seasonal.
  6. Configure staff email alerts for client actions; card-storage policy; customer-editable profile areas; default calendar view; menu items; social links; redirects.
  7. Set design: banner, colour, welcome message, menu wording, payment terms, analytics tag.
  8. Override per reservation type where needed (listing, cutoffs, requirements, allowed package plans, alerts, auto-book, description).
- Rules/edge cases: changes need re-login to be seen by active sessions; visible range cannot be overridden per type; menu items auto-hide when empty.
- Feature IDs: SSP-01, SSP-02, SSP-03, SSP-04, SSP-05, SSP-07, SSP-10, SSP-11, SSP-12, SSP-13, SSP-14, SSP-15, MKT-14
- Evidence: https://support.ezfacility.com/hc/en-us/articles/4404305577755-How-to-Set-Up-Self-Service-Preferences-in-EZFacility-Classic, https://support.ezfacility.com/hc/en-us/articles/4402427176219-How-to-Set-Up-Self-Service-Preferences, https://support.ezfacility.com/hc/en-us/articles/4402427175195-How-to-Set-Up-Self-Service-Design, https://support.ezfacility.com/hc/en-us/articles/23181863135387-How-to-Change-Self-Service-Settings-for-Packages, https://support.ezfacility.com/hc/en-us/articles/4404305596827-How-to-Configure-Available-Tabs-in-the-Self-Service-Menu-using-EZFacility-Classic, https://support.ezfacility.com/hc/en-us/articles/4402427212571-How-to-Mark-Package-Plans-as-Sold-Online

### Onboard a client to the portal (invite, self-register, recover)
- Actors: front desk, client, prospect.
- Preconditions: portal enabled.
- Steps:
  1. Invitation path: staff tick Enabled on a profile or bulk-invite selected clients; each needs an email (verification is triggered on save; an admin may verify manually).
  2. Client receives the invitation, accepts, creates username and password, and is optionally redirected to a configured page.
  3. Public path: prospect chooses create-account, enters name, email, username, password; a client record is created at once.
  4. If verification is required, the prospect confirms by email and completes required profile fields before first login; otherwise logs in directly.
  5. Recovery: client uses the trouble-logging-in link with username and email; staff can see whether an account is active and its username on the profile; unticking Enabled disables access.
- Rules/edge cases: bulk selection is per page (max 100); duplicate emails across clients are discouraged; self-registration can create duplicates of existing clients (no merge step described here).
- Feature IDs: SSP-05, SSP-06, SSP-07, MKT-01
- Evidence: https://support.ezfacility.com/hc/en-us/articles/4404314764827-How-to-Invite-Your-Clients-to-Use-Self-Service, https://support.ezfacility.com/hc/en-us/articles/4402427133851-Self-Service-How-to-invite-existing-contacts, https://support.ezfacility.com/hc/en-us/articles/15942682403227-How-to-Assist-Clients-who-Cannot-Log-into-Self-Service, https://support.ezfacility.com/hc/en-us/articles/26528305868699-How-to-Create-an-Account-on-Self-Service, https://support.ezfacility.com/hc/en-us/articles/4404312815771-Setting-Up-a-Self-Service-Registration-Redirect-in-EZFacility-Classic

### Book a session on the portal with inline package purchase
- Actors: client (optionally acting for a related client).
- Preconditions: reservation type resolves to "allow booking"; session inside visible range and before booking cutoff.
- Steps:
  1. Client opens the calendar (default or chosen view) and selects a session; chooses Book.
  2. If not authenticated, logs in or creates an account.
  3. System checks requirements: active paid-to-date membership if required; a usable, paid-to-date package of an allowed plan.
  4. No qualifying package and one is sold online: client is offered the package, enters or confirms payment method, accepts payment terms if configured, completes checkout.
  5. System books the spot, decrements the package, shows it in My Schedule and on the staff calendar, and notifies staff/trainer per alert settings.
  6. Session full and waitlist enabled: client joins the waitlist; on a cancellation the first waitlisted client is auto-booked and emailed (if auto-book is on).
  7. Cancellation: allowed only if self-cancel is enabled and the notice period is met.
- Rules/edge cases: "list only" tells the client to call; adjacency restriction can block or hide non-adjacent slots; post-billed packages bypass prepayment until billing closes; shared package = one deduction for a couple; hidden types remain bookable by direct link.
- Feature IDs: SSP-02, SSP-03, SSP-08, SSP-09, SSP-10, SSP-11
- Evidence: https://support.ezfacility.com/hc/en-us/articles/26528293115547-Book-into-a-Session-and-Buy-a-Package-on-Self-Service, https://support.ezfacility.com/hc/en-us/articles/4402427176219-How-to-Set-Up-Self-Service-Preferences, https://support.ezfacility.com/hc/en-us/articles/23181863135387-How-to-Change-Self-Service-Settings-for-Packages, https://support.ezfacility.com/hc/en-us/articles/4404314743067-Managing-Self-Service-Shared-Bookings-in-EZFacility-Classic

### Book a rental on the portal
- Actors: client.
- Preconditions: rental booking enabled; at least one rental type allows online booking.
- Steps:
  1. Client opens book-rentals; picks the person (if relationships), location (if several), rental type and venue.
  2. Sets weekday toggles, search start date (within the allowed horizon), rental length and start hour; runs the search.
  3. Picks an offered slot; system places a timed hold on it.
  4. Client pays (or confirms a $0 rental) and completes checkout before the hold expires; booking appears on the staff calendar.
  5. Hold expiry releases the slot.
- Rules/edge cases: hour-aligned start/end only; slot conflicts must be prevented while held (in our design the hold row participates in the exclusion constraint); rental-plan (prepaid) redemption is owned by the rentals cluster.
- Feature IDs: SSP-04, SSP-13
- Evidence: https://support.ezfacility.com/hc/en-us/articles/25312602916763-How-to-Book-a-Rental-on-Self-Service, https://support.ezfacility.com/hc/en-us/articles/4402427176219-How-to-Set-Up-Self-Service-Preferences, https://support.ezfacility.com/hc/en-us/articles/16731304236571-June-28th-2023-Release-Notes, https://support.ezfacility.com/hc/en-us/articles/16308423683355-June-12th-2023-Release-Notes

### Publish a program for online registration
- Actors: administrator, client.
- Preconditions: group exists with registration window and fees (owned by programs cluster).
- Steps:
  1. Open the group's publish tab; enter public name and informational session start/end; tick show-in-portal; publish.
  2. Group appears under the portal Registrations menu; clients register there.
  3. Staff receive registration notices at the account-default and group-specific addresses.
  4. Later edits use update.
- Rules/edge cases: registration dates are separate from session dates.
- Feature IDs: SSP-17, MKT-14
- Evidence: https://support.ezfacility.com/hc/en-us/articles/28746953502875-How-to-Publish-a-Group-to-Self-Service, https://support.ezfacility.com/hc/en-us/articles/18308941711899-How-to-Enable-Disable-Email-Notifications

### Publish and share on-demand video
- Actors: administrator/trainer, client.
- Preconditions: video hosted on an external service.
- Steps:
  1. Add a video: type (URL or embed HTML), title, optional reservation type; preview; save.
  2. Clients see the library grouped by reservation type; linked classes show a watch-now action on the calendar.
  3. Staff copy a direct video URL and email it to a client or group, optionally via a saved template.
  4. Disable a video to withdraw it without deleting.
- Rules/edge cases: no access control beyond portal login is described (pay-walled video is not evidenced). Video: decision point at step 1 - leave the reservation type empty for a library-only video or pick one to show 'Watch now' on every session of that type; for a live class paste a scheduled YouTube live URL ahead of time (a Facebook live URL must be replaced per broadcast); set the host video to Public/Unlisted; optionally set the type to list-only so only the video is offered; watching records no attendance.
- Feature IDs: SSP-16, MKT-10, MKT-11
- Evidence: https://support.ezfacility.com/hc/en-us/articles/4402427173019-Using-the-Self-Service-Video-Library, https://support.ezfacility.com/hc/en-us/articles/4404312817947-How-to-Create-a-Video-Library-for-Customers-in-EZFacility-Classic, https://support.ezfacility.com/hc/en-us/articles/4404312820763-How-to-Share-a-Link-to-a-Specific-Video-in-the-EZFacility-Classic-Video-Library, https://support.ezfacility.com/hc/en-us/articles/4402434185883-How-to-Create-a-Video-Library-for-Customers, https://www.youtube.com/watch?v=qUf6jPISK_8 (t=08:16, t=11:19, t=16:29), https://www.youtube.com/watch?v=IM8m1sUsMdw (t=13:26, t=16:29)

### Design the branded app home screen
- Actors: app administrator, vendor designer.
- Preconditions: branded app provisioned with a colour scheme.
- Steps:
  1. Switch the editor to the draft home screen; optionally import the default tile set.
  2. Add tiles from the catalogue; drag to position (others are pushed), resize from the corner, remove unwanted.
  3. Style each tile: icon, background colour/opacity or image, border.
  4. Edit top/middle/bottom captions, using the dynamic-text token on tiles that support it.
  5. Set global padding and background colour/image.
  6. Promote draft to live (step not documented publicly).
- Rules/edge cases: 3-column grid; dynamic captions require width of at least 2 columns; custom artwork must follow the sizing rules.
- Feature IDs: APP-04, APP-05
- Evidence: https://support.ezfacility.com/hc/en-us/articles/29244419129627-Branded-App-Home-Screen-Layout-Configuration, https://support.ezfacility.com/hc/en-us/articles/29244435018395-Branded-App-Home-Screen-Layout-Icons-Background, https://support.ezfacility.com/hc/en-us/articles/29244421350555-Branded-App-Home-Screen-Labels-Captions-Dynamic-Text-and-Caption-Customizing, https://support.ezfacility.com/hc/en-us/articles/29194635092123-Branded-App-Home-Screen-Additional-App-Design-Settings, https://support.ezfacility.com/hc/en-us/articles/29244450573339-Branded-App-Home-Screen-Tiles-info

### Trial pass request from the app
- Actors: prospect, administrator.
- Preconditions: trial terms and recipient email configured; trial tile on the home screen.
- Steps:
  1. Prospect opens the trial form, enters name, phone, email, preferred location, accepts terms, submits.
  2. System emails the submission to the configured address.
  3. Staff create the client in the back office and add the free membership/session manually.
- Rules/edge cases: no automatic client creation or entitlement — an obvious improvement point for us (create a lead + grant a trial product).
- Feature IDs: APP-12, MKT-20
- Evidence: https://support.ezfacility.com/hc/en-us/articles/29194634692123-Try-us-feature-MemberMe-Branded-App

### Link related clients and act on their behalf
- Actors: client (parent/partner), related client.
- Preconditions: admin allows customers to add relationships.
- Steps:
  1. Client adds a relationship: link an existing client by email or create a new client, choosing the relationship type.
  2. The other party receives a confirmation email.
  3. Thereafter one login can pick the person when booking sessions/rentals and buying products; packages can auto-share to related clients.
- Rules/edge cases: relationship must precede a sale for auto-share; coupon per-person limits apply when buying for a relative; a parent can buy for a relative with no portal account.
- Feature IDs: SSP-10, SSP-09, SSP-11
- Evidence: https://support.ezfacility.com/hc/en-us/articles/4402427176219-How-to-Set-Up-Self-Service-Preferences, https://support.ezfacility.com/hc/en-us/articles/4404314743067-Managing-Self-Service-Shared-Bookings-in-EZFacility-Classic, https://support.ezfacility.com/hc/en-us/articles/18408526583067-August-31st-2023-Release-Notes, https://support.ezfacility.com/hc/en-us/articles/17574439837467-August-2nd-2023-Release-Notes

### Launch a branded app and migrate from the shared app
- Actors: owner, vendor designer/developer, member.
- Preconditions: branded-app subscription; brand assets (logo, colours, preferably vector); for iOS the facility's own Apple developer account (D-U-N-S number needed).
- Steps:
  1. Facility submits an enrolment form with logos and brand colours.
  2. Vendor designers produce a proof of the app icon, splash/load screen and home screen.
  3. Facility approves or requests changes.
  4. Vendor builds native iOS and Android apps and uploads them to both stores (store review up to about 5 business days).
  5. Onboarding call walks the facility through the admin console; the facility then edits the home screen itself.
  6. If the shared app was in use: announce the new app by push from the old one, add download links, and run both apps in parallel until members have moved.
  7. Members download the new app and log in with their existing self-service credentials; cards are added again in the new app.
- Rules/edge cases: quoted lead time 4-6 weeks (shorter when assets are ready); members are not migrated automatically; one app covers all locations with a home-club picker; the vendor ships later OS-version updates.
- Feature IDs: APP-02, APP-03, APP-04, APP-16, MKT-16
- Evidence: https://www.youtube.com/watch?v=Zs-8tpgvadk (t=24:42), https://www.youtube.com/watch?v=uLNIb7JsjkM (t=32:46, t=48:17), https://www.youtube.com/watch?v=t85Pe_jL_h4 (t=26:38), https://www.youtube.com/watch?v=7yHNga6cY0g (t=13:24)

### SMS opt-in, automation and campaign (partner tool)
- Actors: administrator, prospect, client.
- Preconditions: SMS partner subscription linked to the account; clients carry a mobile (or primary) number.
- Steps:
  1. Facility claims a keyword on the shared short code and writes the autoresponder.
  2. A prospect texts the keyword: the system sends the mandatory disclaimer, then the autoresponder, stores the number under the keyword and emails the facility.
  3. Administrator switches on the automations wanted (birthday, new member, prospect, billing decline, cancellation, inactivity) and sets text, day offset and delivery time for each step.
  4. Each night the tool syncs clients and groups from the core system and queues messages for anyone newly qualifying; they go out the next day at the set time.
  5. To mass-text existing clients, first send the permission/disclaimer text; 24 hours later the groups that did not opt out become selectable.
  6. Compose a campaign (name, text, shortened URL, groups), preview on own phone, send now or schedule.
  7. Replies arrive in the inbox thread; staff answer one-to-one. STOP replies and undeliverable numbers are removed from all groups.
- Rules/edge cases: decline sequence stops when payment is fixed, steps run out, or the account is cancelled/in collections; at the monthly cap campaigns lock but automations continue; keyword leads are not created as core clients; facilities with prior documented consent may skip step 5.
- Feature IDs: MKT-15, MKT-23
- Evidence: https://www.youtube.com/watch?v=eISJe5bhK3Y (t=07:47, t=21:03, t=30:16, t=43:31, t=46:40, t=66:10)

## Reporting, Integrations & API, Release-note changes

### Run, drill into and export a report
- Actors: any staff user with report permission (trainers see only their own data on trainer reports).
- Preconditions: user's role grants the report group; add-on-gated groups (e.g. Lockers, Advanced Memberships reports) require the module on the account.
- Steps:
  1. Open Reports; pick a report group (Financial, Marketing, Membership, Training, POS, Check-in, Time Clock, ...) and open a report from its description row.
  2. Fill the parameter form: date range where applicable, then report-specific filters (some hidden behind "More Options"); a few reports (Contact, Group Waitlists, All Inventory, Re-order) run immediately with no form.
  3. Generate. The system runs the query in the caller's permission and location scope and renders a static result; the Generate control is locked while it runs to prevent duplicate executions.
  4. Decision: need row-level evidence? Expand "Show Details" on a section or group to see underlying invoices, payments, orders or clients.
  5. Decision: change filters or pick up new data? Re-generate; nothing refreshes on its own.
  6. Export to a file format (CSV recommended for finance work; Excel, PDF, Word, XML and others available) or print with page size and orientation.
- Rules / edge cases: results are point-in-time; CSV exports must carry real column names (a past defect emitted generic names); PDF output must scale the tenant logo so it does not cover data; multi-select filters need sane defaults; date semantics differ per report (revenue date vs payment date vs invoice date vs due date) and must be shown to the user.
- Feature IDs: RPT-01, RPT-02 to RPT-41
- Evidence: https://support.ezfacility.com/hc/en-us/articles/27902451074715-How-to-Access-and-Download-a-Report, https://support.ezfacility.com/hc/en-us/articles/18408526583067-August-31st-2023-Release-Notes, https://support.ezfacility.com/hc/en-us/articles/19132331777307-September-27th-2023-Release-Notes, https://support.ezfacility.com/hc/en-us/articles/22122496577179-January-17th-2024-Release-Notes, https://support.ezfacility.com/hc/en-us/articles/36516560976539-April-9th-2025-Release-Notes

### Period-end financial review and bank reconciliation
- Actors: owner, bookkeeper/accountant.
- Preconditions: revenue categories and tax rates configured; payments recorded with method and collector; (optional) processor payouts available.
- Steps:
  1. Run the Revenue Report for the period with an optional revenue goal; read revenue by category, taxes, discounts (all by item revenue date) against payments applied (by payment date).
  2. Run the Deposits Report for the same dates; for each payment method take deposits, subtract refunds, and compare the net with the bank statement; expand details to see each payment with client, collector, applied and unused amounts; voided payments are shown flagged.
  3. Decision: card deposits do not match? Run the processor disbursement report (max one month per run, data may lag 1-5 business days) and match its transaction ids to the Deposits Report transaction ids.
  4. Run Unapplied Payments by Customer; for each positive liability apply the money to open invoices or refund it; negative liability means the client owes.
  5. Run Open Invoices by Customer by due date through today; chase or write off (see next flow).
  6. Run the Invoices Report for the audit trail of invoices raised in the period; optionally Underpaid Items as of period end and Unused Session Value / Accrued Session Revenue for prepaid-session liability and earned training revenue.
  7. Export each report to CSV for the accounting file, or rely on the QuickBooks sync for postings.
- Rules / edge cases: Revenue Report ignores invoice dates and payment schedules; a payment outside the range applied to in-range revenue is absent from Payment Breakdown, so revenue and payments will not tie within one period by design; Net Deposits on the dashboard include unapplied money; Bank Transfer is a recording-only method.
- Feature IDs: RPT-03, RPT-04, RPT-05, RPT-06, RPT-07, RPT-09, RPT-10, RPT-22, RPT-41, INT-07
- Evidence: https://support.ezfacility.com/hc/en-us/articles/20993523042587-Chalk-Talk-December-2023-Top-5-Financial-Reports-in-EZFacility, https://support.ezfacility.com/hc/en-us/articles/34200838065179-Using-the-Revenue-Report-in-EZFacility, https://support.ezfacility.com/hc/en-us/articles/34200840681499-Deposits-Report, https://support.ezfacility.com/hc/en-us/articles/23474559304859-Unapplied-Payments-by-Customer, https://support.ezfacility.com/hc/en-us/articles/34200876269083-Open-Invoices-By-Customer-Report, https://support.ezfacility.com/hc/en-us/articles/23474580662555-Invoices-Report, https://support.ezfacility.com/hc/en-us/articles/4403486278939-Underpaid-Items, https://support.ezfacility.com/hc/en-us/articles/24225032928027-March-27th-2024-Release-Notes, https://support.ezfacility.com/hc/en-us/articles/24695840840603-April-10th-2024-Release-Notes, https://support.ezfacility.com/hc/en-us/articles/16731304236571-June-28th-2023-Release-Notes

### Receivables follow-up
- Actors: billing staff, owner.
- Preconditions: invoices with payment schedules; auto-pay attempts logged with decline reasons; client billing status maintained.
- Steps:
  1. Open Open Invoices by Customer; set Report By = Due Date, leave start blank, end = today.
  2. Choose scope: all invoices, auto-pay only (failed charges) or non-auto-pay (manual payers); decide whether to include clients already reported for collections and deleted clients; exclude fully paid invoices.
  3. Sort by balance or due date; generate.
  4. Expand a client to see each invoice and, for auto-pay, the decline reason.
  5. Decision: declined card -> contact client to update the card and retry; manual payer -> send statement or take payment; long overdue -> tag for collections in billing (other cluster).
  6. Re-run after action; an empty report through today is the target state.
- Rules / edge cases: payments dated on or after the end date are ignored, so back-dated runs give an as-of receivables position; "Invoice Date" mode ignores schedules and overstates lateness for instalment invoices.
- Feature IDs: RPT-06, RPT-07
- Evidence: https://support.ezfacility.com/hc/en-us/articles/4403486300315-Open-Invoices-By-Customer-Report, https://support.ezfacility.com/hc/en-us/articles/23474526075419-Open-Invoices-By-Customer-Report, https://support.ezfacility.com/hc/en-us/articles/34200876269083-Open-Invoices-By-Customer-Report, https://support.ezfacility.com/hc/en-us/articles/20993523042587-Chalk-Talk-December-2023-Top-5-Financial-Reports-in-EZFacility

### Membership health review (status, attrition, renewals, low usage)
- Actors: owner, membership manager, marketing staff.
- Preconditions: contract status history with reasons; check-ins recorded; Advanced Memberships add-on for freeze/suspend actions.
- Steps:
  1. Run Memberships by Status for the head-count (decide whether to count each person sharing a contract and whether to include expired).
  2. Run Membership Attrition for the last N months with a fixed N; decide whether frozen and suspended count as active; read lost contracts and the period percentage.
  3. Run Membership Actions for the same months per action (cancelled / frozen / suspended) to see what drove the change.
  4. Run Expiring Memberships for the coming weeks excluding auto-renewing contracts and contracts already superseded by a newer one; hand the list to the email tool using its membership-expiration filter.
  5. Run Low Usage Check-In with a max visit count to find at-risk members; target them with a re-engagement campaign.
  6. Run Membership Revenue by Month (next quarter / rolling year) to see the revenue effect; Membership Referrals to credit referrers.
- Rules / edge cases: only Voluntary Cancel and non-renewed expiry count as lost; attrition percentages are comparable only between equal-length periods; a contract shared with, but owned by, another client never hides an expiring contract.
- Feature IDs: RPT-11, RPT-12, RPT-13, RPT-14, RPT-15, RPT-16, RPT-17
- Evidence: https://support.ezfacility.com/hc/en-us/articles/4404308209819-Membership-By-Status-Report-in-EZFacility-Classic, https://support.ezfacility.com/hc/en-us/articles/4404308366619-Membership-Attrition-Report-in-EZFacility-Classic, https://support.ezfacility.com/hc/en-us/articles/4404308201243-Membership-Actions, https://support.ezfacility.com/hc/en-us/articles/4404314535195-View-the-Expiring-Memberships-Report-in-EZFacility-Classic, https://support.ezfacility.com/hc/en-us/articles/4404308202907-View-the-Low-Usage-Check-In-Report-in-EZFacility-Classic, https://support.ezfacility.com/hc/en-us/articles/4404308369179-Viewing-Membership-Revenue-by-Month-Report-in-EZFacility-Classic, https://support.ezfacility.com/hc/en-us/articles/4404314692507-Using-the-Membership-Referral-Report-in-EZFacility-Classic, https://support.ezfacility.com/hc/en-us/articles/36516560976539-April-9th-2025-Release-Notes

### Training retention and renewal outreach
- Actors: trainer, manager.
- Preconditions: packages sold with session counts; clients have a default trainer (several filters depend on it).
- Steps:
  1. Run Renewal Candidates with min/max sessions remaining for a trainer; optionally drop clients whose last booking is older than a date.
  2. Run Expiring Packages for the next weeks.
  3. Run Non-training Clients ("not scheduled after" a date) to list lapsed clients, choosing whether to include never-scheduled clients and those without packages.
  4. Contact the lists; later run Trial Conversions and Client Retention (period 1 vs period 2) to measure the result per trainer.
- Rules / edge cases: trainer filters match the client's default trainer, not the delivering trainer; retention counts scheduled sessions and excludes complimentary ones unless opted in; package types with zero remaining are excluded from candidates.
- Feature IDs: RPT-23, RPT-24, RPT-25, RPT-26
- Evidence: https://support.ezfacility.com/hc/en-us/articles/4404314851355-Renewal-Candidates, https://support.ezfacility.com/hc/en-us/articles/4404308572827-Expiring-Packages, https://support.ezfacility.com/hc/en-us/articles/4404308531099-Non-training-Clients, https://support.ezfacility.com/hc/en-us/articles/4404308559771-Trial-Conversions, https://support.ezfacility.com/hc/en-us/articles/4404308575643-Client-Retention-Report

### Group roster and waitlist reporting
- Actors: program coordinator, front desk.
- Preconditions: active group with registrants.
- Steps:
  1. Open Groups and the target group; choose Generate Report from the group's action menu; the report opens in a new tab.
  2. (New) choose sort order and the fields to include; (Classic) optionally expand details.
  3. Export in the chosen format and print for the instructor.
  4. For capacity planning open Reports > Marketing > Group Waitlists (no parameters) to see every waitlisted registrant by group; optionally show medical conditions; export.
- Rules / edge cases: only active groups are listed; waitlist report spans groups and sub-groups; medical data visibility should follow permissions.
- Feature IDs: RPT-27, RPT-28
- Evidence: https://support.ezfacility.com/hc/en-us/articles/4404924765339-How-to-Generate-a-Report-for-Groups, https://support.ezfacility.com/hc/en-us/articles/4415445452059-How-to-Generate-a-Report-for-Groups, https://support.ezfacility.com/hc/en-us/articles/4404314883483-Group-Waitlists, https://support.ezfacility.com/hc/en-us/articles/23857919227035-How-to-Run-a-Waitlist-Report-for-Groups

### Till reconciliation and retail review
- Actors: cashier supervisor, retail manager.
- Preconditions: POS registers defined; sales attributed to logged-in user.
- Steps:
  1. At close, run the Daily Register Report for the register and day; compare sales, money collected and refunds with the drawer count; expand details for individual orders and refunds.
  2. Decision: variance -> run Order Returns/Refunds and Sales By Employee for the same period to locate it.
  3. Weekly: run All Sales (simplified mode for export), Sales By Category (unit cost and margin), by Supplier/Brand and by Coupon.
  4. Run Inventory Re-order to raise purchase orders; All Inventory for a stock list; Checked-Out Equipment to chase unreturned rental gear.
- Rules / edge cases: products with reorder level -1 never appear on the re-order list; employee attribution follows the session user, so shared logins break the report.
- Feature IDs: RPT-30, RPT-31, RPT-32, RPT-33, RPT-34
- Evidence: https://support.ezfacility.com/hc/en-us/articles/34419021121051-Daily-Register-Report, https://support.ezfacility.com/hc/en-us/articles/34419017128987-Order-Returns-Refunds, https://support.ezfacility.com/hc/en-us/articles/34419051390875-Sales-By-Employee, https://support.ezfacility.com/hc/en-us/articles/34418979987611-All-Sales-Report, https://support.ezfacility.com/hc/en-us/articles/34419055387547-Sales-By-Category, https://support.ezfacility.com/hc/en-us/articles/34419009666459-Inventory-Re-order-Report, https://support.ezfacility.com/hc/en-us/articles/34419089287067-View-the-Checked-Out-Equipment-in-EZFacility-Classic

### Print league game cards
- Actors: league admin, scorekeeper.
- Preconditions: league games scheduled (batch mode) or teams defined (manual mode).
- Steps:
  1. Open Reports > Game Cards.
  2. Decision: one-off game -> Manual Game Cards, choose home team, away team, date and time; whole match day -> Game Cards by Sport, choose sport and date range.
  3. Run; batch mode produces one card per scheduled game (page count = game count).
  4. Print directly or export to PDF/Excel.
- Rules / edge cases: manual cards can pair teams from any league and need no scheduled game. The same Reports tile in the league app also offers Games by Venue, an Officials report and participant demographic reports (LGE-32, video).
- Feature IDs: RPT-36, LGE-32
- Evidence: https://support.ezfacility.com/hc/en-us/articles/4405044263835-How-to-Print-Manual-Game-Cards, https://support.ezfacility.com/hc/en-us/articles/4405044293147-How-to-Print-Multiple-Game-Cards, https://www.youtube.com/watch?v=bHzYz6ZzMSE (t=31:50)

### Connect QuickBooks Online and post financials
- Actors: owner/admin, bookkeeper.
- Preconditions: US account with the QuickBooks sync add-on; a QuickBooks Online company (ideally new) configured for class tracking per transaction row, categories on, item table on expense forms off, purchase orders off; revenue categories defined.
- Steps:
  1. In administration open the QuickBooks section for the location and start authorisation.
  2. Sign in to QuickBooks in the pop-up, pass the verification code if asked, choose the company, connect; the platform stores the connection for that location.
  3. For every revenue category choose the QuickBooks Class it maps to and save.
  4. Decision: turn on automatic sync, or leave it off and trigger sync manually.
  5. The system pushes financial activity (invoices, membership and POS sales, payments) to QuickBooks tagged with the mapped class.
- Rules / edge cases: one-way only, edits made in QuickBooks are not read back; connecting to an existing company risks duplicate customers; unmapped categories behaviour is unpublished (we should block or route to a default); token expiry/re-authorisation is not described.
- Feature IDs: INT-07
- Evidence: https://support.ezfacility.com/hc/en-us/articles/5393406604315-How-to-connect-your-QuickBooks-Online-account-with-EZFacility, https://support.ezfacility.com/hc/en-us/articles/4406053980955-How-to-connect-your-QuickBooks-Online-account-with-EZFacility-Classic, https://support.ezfacility.com/hc/en-us/articles/4405044167835-EZFacility-Open-Webinar-QuickBooks-Online-Integration, https://www.ezfacility.com/partners/quickbooks-online-sync/

### Run a virtual session over Zoom
- Actors: admin, trainer (host), client.
- Preconditions: Zoom account (owner credentials recommended); enough Zoom users for concurrent sessions; for paid access a package linked to the reservation type.
- Steps:
  1. Admin authenticates the location with Zoom (OAuth) and chooses the access mode via two switches: require portal login; require a booking.
  2. Staff create a reservation and tick "create Zoom meeting", choosing the hosting Zoom user; or add a meeting to an existing reservation. System creates the meeting and stores id and join link; if added later, booked clients are emailed.
  3. Client finds the session on the portal schedule. Decision by mode: open -> can launch directly; login required -> must sign in; booking required -> must buy/hold an allowed package and book, then launch from their schedule.
  4. Reminder emails include a unique link that routes through portal login.
  5. From 10 minutes before start the client can launch; on join the system deducts a session from the package and marks attendance; the trainer starts the meeting from the reservation.
  6. If the meeting or reservation is deleted, the Zoom meeting is removed and booked clients are notified.
  7. To disconnect, uninstall in administration and remove the app in Zoom's marketplace.
- Rules / edge cases: a Zoom user cannot host overlapping meetings; waitlisted clients never receive links; Zoom plan duration and attendee caps apply. From the 2020 webinar: step 2 is repeated for every occurrence, because a recurring or multi-day series does not create meetings in bulk; a client who cancels after receiving the link can still join, so the host checks the attendance list and removes them in Zoom; the access mode is one setting for the whole location; clients on the shared mobile app must use the portal in a browser.
- Feature IDs: INT-09
- Evidence: https://support.ezfacility.com/hc/en-us/articles/4405051261339-Zoom-Integration-with-EZFacility-Classic, https://support.ezfacility.com/hc/en-us/articles/34441456779163-Online-Webinar-Zoom-Integration-in-EZFacility-Classic, https://support.ezfacility.com/hc/en-us/articles/34155834657819-July-3rd-2024-Release-Notes, https://www.ezfacility.com/blog/new-ezfacility-business-features, https://www.youtube.com/watch?v=hlGAZlxFHWg (t=15:41), https://www.youtube.com/watch?v=hlGAZlxFHWg (t=27:03), https://www.youtube.com/watch?v=hlGAZlxFHWg (t=36:14)

### Publish the schedule to an external calendar
- Actors: staff member or trainer.
- Preconditions: user can view the schedule.
- Steps:
  1. From the schedule open the calendar-sync dialog and enable the feed; the system generates a URL containing a secret key.
  2. Choose scope: resources, reservation types, days back and forward, and whether to include sessions without bookings, rentals, other reservation kinds, notes and the list of booked clients; save.
  3. Subscribe to the URL in Outlook, iOS Calendar or Google Calendar (Android via Google).
  4. The external calendar polls the URL; changes flow one way.
  5. To revoke, disable then re-enable to rotate the key and re-subscribe.
- Limit (video): the window can reach at most 90 days back and 90 days ahead.
- Rules / edge cases: refresh delay is controlled by the calendar client; including booking lists exposes client names to a third-party calendar provider.
- Feature IDs: INT-08
- Evidence: https://support.ezfacility.com/hc/en-us/articles/10867559563547-Syncing-your-EZFacility-Calendar-to-an-External-Calendar, https://support.ezfacility.com/hc/en-us/articles/4404311517339-Syncing-your-EZFacility-Classic-Calendar-to-an-External-Calendar, https://support.ezfacility.com/hc/en-us/articles/4404311542427-Syncing-your-EZFacility-Calendar-to-your-iOS-iPod-iPad-and-iPhone-Calendar, https://support.ezfacility.com/hc/en-us/articles/4404311548059-Syncing-your-EZFacility-Calendar-to-your-Outlook-Calendar, https://support.ezfacility.com/hc/en-us/articles/4404311551899-Syncing-your-EZFacility-Calendar-to-your-Google-Android-device-Calendar

### Connect a third-party waiver provider (Smartwaiver)
- Actors: owner/admin; client as signer.
- Preconditions: Smartwaiver account with an API key (displayed once).
- Steps:
  1. In location settings open the Smartwaiver section, paste the API key and activate.
  2. The system registers an account-level webhook in Smartwaiver whose URL carries the location id; all templates now report to that location.
  3. Optional: for a template that belongs to another location set a per-template webhook URL with that location's id.
  4. Client signs online or on a kiosk; the provider calls the webhook; the system matches or creates the client and attaches the signed waiver.
  5. (video) Decision: email validation on -> the waiver is held until the signer confirms their email, unless that waiver's own provider setting skips validation (e.g. kiosk).
  6. (video) Decision on matching: exactly one existing client -> attach; none -> create a client; several -> email the account admins, who resolve or merge by hand.
  7. (video) Extra participants and minors on the waiver become linked clients with a parent-of relationship; the client's waiver-signed checkbox is ticked, and cleared automatically once every waiver has expired.
- Rules / edge cases: section is hidden until the account exists; matching rules for existing clients and minors are not published; duplicate deliveries must be idempotent in our adapter. Video update: outcomes of matching and the handling of minors are now known (steps 5 to 7), the fields used as the match key are still not stated; the module must first be enabled by the account manager.
- Feature IDs: INT-10
- Evidence: https://support.ezfacility.com/hc/en-us/articles/9917964474011-Enable-the-Smartwaiver-and-EZFacility-Integration-in-EZFacility, https://www.ezfacility.com/partners/smartwaiver/, https://www.youtube.com/watch?v=jbwkXIo9rY8 (t=06:05), https://www.youtube.com/watch?v=jbwkXIo9rY8 (t=09:10), https://www.youtube.com/watch?v=jbwkXIo9rY8 (t=12:14)

### Loyalty points earn and redeem (Perkville)
- Actors: owner, client, front desk, loyalty provider.
- Preconditions: facility has a provider account (30-day trial then paid) linked to the platform; point values and rewards defined in the provider.
- Steps:
  1. Client checks in, attends a session or is invoiced; the platform reports the event to the provider.
  2. Provider awards points and emails the client.
  3. Client creates a free provider account to view points and claim a reward.
  4. Front desk applies the reward manually as a coupon/discount on the next sale.
- Rules / edge cases: POS purchases earn nothing; there is no redeem-points tender, so redemption is not reconciled automatically.
- Feature IDs: INT-11
- Evidence: https://support.ezfacility.com/hc/en-us/articles/5325270760731-How-are-points-earned, https://support.ezfacility.com/hc/en-us/articles/5325205707931-Who-notifies-the-customers-they-earned-points, https://support.ezfacility.com/hc/en-us/articles/5325162944539-How-do-customers-redeem-their-points, https://support.ezfacility.com/hc/en-us/articles/5325163359131-How-does-a-facility-redeem-Perks, https://support.ezfacility.com/hc/en-us/articles/5325289162907-How-does-a-facility-register-for-Perkville

### Onboard an API consumer
- Actors: admin (credential holder), developer.
- Preconditions: plan includes API access; credentials issued (issuing process not public).
- Steps:
  1. Developer obtains Client ID and Client Secret and reads the Swagger sandbox.
  2. Exchange the credentials for a bearer token (OAuth 2.0), choosing the back-office or member (self-service) realm.
  3. Call resources: clients and memberships, sessions/reservations and bookings, invoices with payments and allocations, package plans, POS, leagues.
  4. Write paths: update client, create session reservations (not rentals), mark invoices paid, update stored card (member realm).
  5. Render live schedules/availability on the facility website or app; keep the external system in sync by polling.
- Rules / edge cases: no outbound webhooks are evidenced, so consumers poll; member-realm update exposes fewer fields; lookups by membership number span all locations the credential can access.
- Feature IDs: INT-01, INT-02, INT-03, INT-04, INT-05, INT-06
- Evidence: https://www.ezfacility.com/ez-api-services, https://www.ezfacility.com/blog/client-highlight-c2tactical-utilizes-ezfacility-digital-api, https://support.ezfacility.com/hc/en-us/articles/20241459046683-November-8th-2023-Release-Notes, https://support.ezfacility.com/hc/en-us/articles/22529640450203-January-31-2024-Release-Notes, https://support.ezfacility.com/hc/en-us/articles/25134483797531-April-24th-2024-Release-Notes, https://support.ezfacility.com/hc/en-us/articles/26498179644187-June-5th-2024-Release-Notes, https://support.ezfacility.com/hc/en-us/articles/26750732215835-June-19th-2024-Release-Notes, https://support.ezfacility.com/hc/en-us/articles/36516560976539-April-9th-2025-Release-Notes
