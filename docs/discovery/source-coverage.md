# Source Coverage

Phase 0 output 1. Every URL considered, how it was read, and which inventory features cite it.

## Totals

| Source | In scope | Read | Notes |
|---|---|---|---|
| Help center articles | 617 | 575 | 42 title-only. All 617 map to an inventory feature or the exclusion list (0 unmapped). |
| Help center category/section pages | 77 | 73 | Navigation only; used to group articles. |
| Marketing core pages (features, industries, comparisons, partners, pricing, API, portal) | 49 | 49 | 35 cited by features. Login, demo-request, trial, contact and privacy pages deliberately skipped. |
| Press / news pages | 81 | 81 | 12 cited. About 60 are industry commentary with no product information. |
| Blog posts | 426 in sitemap | 46 | Selected by slug for product/release content; the other 380 are general fitness/marketing articles, not fetched. |
| YouTube channel videos | 91 | 83 | Whole public channel. Auto-generated caption transcripts read for 83; 8 have no captions (title only). Descriptions read for the 30 most recent. |
| App store listings | 2 | 2 | iOS (developer account lists 5 apps) and Android listing of the member app; 25 public iOS reviews. |
| Review sites (Capterra, G2, Software Advice, GetApp) | 4 | 0 | All returned HTTP 403 (bot protection); not circumvented. Search snippets plus the SelectHub aggregate page were used instead. See `gaps-and-complaints.md`. |

**Pages read in full: 910.** Help articles read: 575 of 617.

## How the help center was read

The live help center serves a Cloudflare bot challenge (HTTP 403) on every article, though its sitemap is open. We did not
attempt to pass the challenge. The sitemap gave the authoritative list of 617 articles; article bodies were read from
public Internet Archive (Wayback Machine) snapshots, almost all captured in 2025. Consequences: (1) content may lag the live
site by up to about a year; (2) 42 articles published or changed since have no snapshot and are known by title only
(they are listed below and in `unknowns.md`). robots.txt was honoured on both hosts, fetches were sequential per worker with a 1.5 s delay, and
no authenticated, API or app traffic was inspected.

## Help center articles (617)

| URL | Status | Features |
|---|---|---|
| https://support.ezfacility.com/hc/en-us/articles/10414682862235-How-to-Create-a-Tournament-in-EZLeagues | read (archive snapshot 2025-08-14) | LGE-01, LGE-02, LGE-03, LGE-14, REG-14 |
| https://support.ezfacility.com/hc/en-us/articles/10414721006875-How-to-Manage-Pickup-Games-in-EZLeagues | read (archive snapshot 2025-08-14) | LGE-23 |
| https://support.ezfacility.com/hc/en-us/articles/10414722181403-Picking-Team-Preferences-in-EZLeagues | read (archive snapshot 2025-08-14) | LGE-10 |
| https://support.ezfacility.com/hc/en-us/articles/10414727616795-How-to-Manage-your-Classes-Clinics-in-EZLeagues | read (archive snapshot 2025-08-06) | CLS-07 |
| https://support.ezfacility.com/hc/en-us/articles/10414752794395-How-to-Generate-a-Pool-Play-Schedule-in-EZLeagues | read (archive snapshot 2025-10-08) | LGE-11 |
| https://support.ezfacility.com/hc/en-us/articles/10414756274971-How-to-Create-a-Tournament-Schedule-Single-Elimination-Bracket | read (archive snapshot 2025-08-14) | LGE-12 |
| https://support.ezfacility.com/hc/en-us/articles/10414765514779-How-To-Create-a-Tournament-Schedule-Double-Elimination-Bracket | read (archive snapshot 2025-04-27) | LGE-12 |
| https://support.ezfacility.com/hc/en-us/articles/10414776053531-How-To-Create-a-Three-Games-Guaranteed-Schedule-8-Team-Tournament | read (archive snapshot 2025-06-21) | LGE-13 |
| https://support.ezfacility.com/hc/en-us/articles/10414786644635-How-to-Generate-a-League-Schedule-Odd-Number-of-Teams-Bye | read (archive snapshot 2025-10-11) | LGE-08, LGE-09 |
| https://support.ezfacility.com/hc/en-us/articles/10414795167387-How-to-Generate-a-League-Schedule-Even-Number-of-Team | read (archive snapshot 2025-08-14) | LGE-08 |
| https://support.ezfacility.com/hc/en-us/articles/10414799252763-How-to-Manage-Scores-in-EZLeagues | read (archive snapshot 2025-10-11) | LGE-06, LGE-14 |
| https://support.ezfacility.com/hc/en-us/articles/10867559563547-Syncing-your-EZFacility-Calendar-to-an-External-Calendar | read (archive snapshot 2025-08-04) | INT-08 |
| https://support.ezfacility.com/hc/en-us/articles/10962069855131-EZLeagues-Training-How-to-Create-Manage-Leagues-in-the-New-UI | read (archive snapshot 2025-08-04) | LGE-01 |
| https://support.ezfacility.com/hc/en-us/articles/11297336305691-December-15th-2022-Release-Notes | read (archive snapshot 2025-08-04) | BIL-23, CHK-11, CHK-12, CLI-01, CLI-02, CLI-19, CLS-03, INT-03, LGE-18, MEM-07, MEM-19, PLT-01, PLT-12, REL-01, REL-02 |
| https://support.ezfacility.com/hc/en-us/articles/11453271338523-How-to-Create-a-League | read (archive snapshot 2025-08-08) | LGE-01, LGE-03 |
| https://support.ezfacility.com/hc/en-us/articles/11840312242331-Creating-Document-Templates-in-EZFacility | read (archive snapshot 2025-08-04) | DOC-01 |
| https://support.ezfacility.com/hc/en-us/articles/13526384977307-March-9th-2023-Release-Notes | read (archive snapshot 2025-08-04) | CLS-08, INT-09, LGE-18, LGE-19, PLT-12, REG-11, REL-01, REL-04 |
| https://support.ezfacility.com/hc/en-us/articles/14101589968923-Clover-Terminal-Set-Up-UK-Clients-Only | read (archive snapshot 2025-08-04) | PAY-13 |
| https://support.ezfacility.com/hc/en-us/articles/14655161654811-April-18th-2023-Release-Notes | read (archive snapshot 2025-10-08) | BIL-04, CLI-03, CLI-04, CLS-03, DOC-04, INT-14, LGE-26, MEM-08, ONB-04, PAY-19, PLT-07, PLT-11, REG-11, REG-23, REL-01, REL-02, REL-04, REL-05, RPT-05, RPT-37, RPT-41, STF-06, STF-07 |
| https://support.ezfacility.com/hc/en-us/articles/15461639207963-Contacting-our-Billing-Team-to-Manage-Your-Account | title only — live page bot-challenged, no archive copy | PLT-14 |
| https://support.ezfacility.com/hc/en-us/articles/15851993226139-How-to-Upload-a-Document-to-a-Client-Profile | read (archive snapshot 2025-08-14) | CLI-09, CLI-11 |
| https://support.ezfacility.com/hc/en-us/articles/15942682403227-How-to-Assist-Clients-who-Cannot-Log-into-Self-Service | read (archive snapshot 2025-06-21) | SSP-06 |
| https://support.ezfacility.com/hc/en-us/articles/16308423683355-June-12th-2023-Release-Notes | read (archive snapshot 2025-08-04) | CLS-06, PAY-06, PKG-14, REL-01, REL-02, RNT-01, RNT-05, RPT-04, SSP-04 |
| https://support.ezfacility.com/hc/en-us/articles/16731304236571-June-28th-2023-Release-Notes | read (archive snapshot 2025-04-27) | BIL-01, BIL-06, BIL-21, CHK-07, CHK-20, MEM-10, MEM-21, PAY-01, PAY-02, PAY-03, PAY-05, PAY-10, PKG-07, PLT-04, REG-07, REL-01, REL-04, REL-05, RNT-05, RNT-06, RPT-03, RPT-04, RPT-41, SSP-04 |
| https://support.ezfacility.com/hc/en-us/articles/16846068050715-July-3rd-2023-Release-Notes | read (archive snapshot 2025-10-11) | CHK-01, CLI-03, MEM-02, MEM-11, REG-12, REL-01, REL-02, REL-04, RES-01, RES-03, RNT-06, SSP-06, SSP-12 |
| https://support.ezfacility.com/hc/en-us/articles/17323515477659-How-to-Allow-Clients-to-Register-for-a-Group-Online | read (archive snapshot 2025-10-08) | REG-10, REG-12 |
| https://support.ezfacility.com/hc/en-us/articles/17574439837467-August-2nd-2023-Release-Notes | read (archive snapshot 2025-10-08) | APP-18, BIL-04, BIL-13, CLS-06, FAM-02, FAM-03, MEM-09, PAY-01, PKG-09, PKG-12, PKG-14, REG-12, REL-01, RNT-01, RPT-03, SCH-04, SCH-10, SSP-05, SSP-08 |
| https://support.ezfacility.com/hc/en-us/articles/17657710657051-How-to-Create-and-Sell-a-Pre-Defined-Item | read (archive snapshot 2025-08-14) | BIL-03, BIL-14, BIL-17, PAY-09 |
| https://support.ezfacility.com/hc/en-us/articles/17671233549211-EZFacility-Support-Hours-Monday-Friday-8-30am-to-5-00pm-ET | read (archive snapshot 2025-08-04) | excluded (no product capability) |
| https://support.ezfacility.com/hc/en-us/articles/17764248824987-How-to-Cancel-Membership-and-Refund-the-Client-Full-Partial-in-EZFacility | read (archive snapshot 2025-08-14) | MEM-16 |
| https://support.ezfacility.com/hc/en-us/articles/17981009155995-August-16th-2023-Release-Notes | read (archive snapshot 2025-10-11) | BIL-12, INT-02, MEM-21, MEM-22, REG-02, REL-01, REL-04, RPT-11, SCH-09, SCH-15, SSP-05 |
| https://support.ezfacility.com/hc/en-us/articles/18308941711899-How-to-Enable-Disable-Email-Notifications | read (archive snapshot 2025-08-08) | MKT-13, MKT-14, STF-12 |
| https://support.ezfacility.com/hc/en-us/articles/18408526583067-August-31st-2023-Release-Notes | read (archive snapshot 2025-08-04) | BIL-03, BIL-15, CLI-02, MEM-09, MEM-10, MEM-11, MEM-19, MEM-20, MKT-06, PAY-09, PKG-05, PLT-08, REL-01, REL-02, REL-03, REL-04, RPT-01, RPT-03, RPT-04, SCH-06, SSP-11 |
| https://support.ezfacility.com/hc/en-us/articles/18741009680795-September-13th-2023-Release-Notes | read (archive snapshot 2025-08-14) | BIL-01, BIL-12, ONB-02, PLT-01, PLT-09, POS-01, POS-02, REL-01, REL-03, REL-04, RNT-02, RPT-03, RPT-32, RPT-41, STF-10 |
| https://support.ezfacility.com/hc/en-us/articles/19132331777307-September-27th-2023-Release-Notes | read (archive snapshot 2025-10-08) | CHK-05, CLS-06, FAM-05, FIT-04, MEM-21, PKG-06, PKG-12, PKG-15, REL-01, RPT-01, RPT-11, RPT-14, RPT-17, RPT-19, RPT-22, RPT-23, RPT-24, RPT-41, SCH-17, STF-09, STF-11 |
| https://support.ezfacility.com/hc/en-us/articles/19847009538203-October-25th-2023-Release-Notes | read (archive snapshot 2025-08-14) | BIL-04, BIL-17, CHK-05, INT-04, MEM-02, MEM-07, PKG-16, REG-10, REL-01, RNT-03 |
| https://support.ezfacility.com/hc/en-us/articles/20241459046683-November-8th-2023-Release-Notes | read (archive snapshot 2025-10-11) | BIL-23, INT-03, PLT-03, REG-10, REL-01, RPT-19 |
| https://support.ezfacility.com/hc/en-us/articles/20482279207963-Chalk-Talk-November-2023-Updating-Membership-Pricing | read (archive snapshot 2025-10-11) | MEM-02, MEM-11 |
| https://support.ezfacility.com/hc/en-us/articles/20961678104219-Invoices-Report | read (archive snapshot 2025-10-08) | RPT-05 |
| https://support.ezfacility.com/hc/en-us/articles/20961746603803-Unapplied-Payments-by-Customer | read (archive snapshot 2025-08-04) | RPT-07 |
| https://support.ezfacility.com/hc/en-us/articles/20993523042587-Chalk-Talk-December-2023-Top-5-Financial-Reports-in-EZFacility | read (archive snapshot 2025-08-06) | RPT-01, RPT-03, RPT-04, RPT-05, RPT-06, RPT-07 |
| https://support.ezfacility.com/hc/en-us/articles/21171478349211-How-to-Setup-your-EZPayments-EMV-Terminal-in-EZFacility | read (archive snapshot 2025-06-21) | PAY-12 |
| https://support.ezfacility.com/hc/en-us/articles/21173246031771-Setting-Up-Billing-Preferences | read (archive snapshot 2025-08-04) | BIL-05, BIL-10, BIL-11, BIL-16, BIL-17, PAY-02, PAY-03, PAY-06, PAY-07, PAY-08 |
| https://support.ezfacility.com/hc/en-us/articles/21201707663515-Removing-and-Refunding-Packages | read (archive snapshot 2025-10-08) | PKG-07, PKG-13, PKG-14 |
| https://support.ezfacility.com/hc/en-us/articles/22122496577179-January-17th-2024-Release-Notes | read (archive snapshot 2025-08-14) | BIL-04, CHK-05, CLI-03, CLI-14, CLS-01, DOC-01, LGE-19, LGE-26, MEM-04, MKT-10, PAY-01, PAY-08, PAY-11, PAY-13, PKG-01, PLT-11, REG-07, REG-10, REL-01, REL-03, REL-05, RPT-01, RPT-41, STF-09, STF-11 |
| https://support.ezfacility.com/hc/en-us/articles/22132354311067-How-to-Share-a-Package-Plan | read (archive snapshot 2025-10-11) | FAM-01, FAM-03, FAM-05 |
| https://support.ezfacility.com/hc/en-us/articles/22529640450203-January-31-2024-Release-Notes | read (archive snapshot 2025-08-14) | CLI-21, INT-01, INT-05, REL-01, REL-04, RPT-37, SSP-19, STF-08 |
| https://support.ezfacility.com/hc/en-us/articles/22758241119899-Membership-Renewal-Process | read (archive snapshot 2025-08-08) | MEM-11 |
| https://support.ezfacility.com/hc/en-us/articles/22758476497819-How-to-view-and-edit-Memberships-on-a-Client-Profile-in-New-EZFacility-Experience | read (archive snapshot 2025-08-08) | MEM-10, MEM-11, MEM-20 |
| https://support.ezfacility.com/hc/en-us/articles/22758625268379-Creating-Membership-Types-in-New-EZFacility-Experience | read (archive snapshot 2025-08-14) | MEM-01 |
| https://support.ezfacility.com/hc/en-us/articles/22791705622811-Where-to-find-edit-and-create-Roles-on-EZFacility | read (archive snapshot 2025-10-08) | PLT-04 |
| https://support.ezfacility.com/hc/en-us/articles/22795613046299-Location-Setup | read (archive snapshot 2025-08-14) | IMP-04, PLT-08, PLT-16, RES-01 |
| https://support.ezfacility.com/hc/en-us/articles/22934947867547-Facility-Hours-Setup | read (archive snapshot 2025-08-14) | RES-02 |
| https://support.ezfacility.com/hc/en-us/articles/22938731158811-How-to-set-up-Rentals-For-Self-Service | read (archive snapshot 2025-08-06) | RNT-01, RNT-05 |
| https://support.ezfacility.com/hc/en-us/articles/22968789591963-February-15th-2024-Release-Notes | read (archive snapshot 2025-10-11) | CHK-01, MEM-06, MEM-21, PAY-02, PAY-06, PAY-09, PAY-10, POS-13, REL-01, REL-03, REL-04, RPT-01, RPT-13, RPT-14, RPT-15, RPT-17, RPT-41, SSP-14 |
| https://support.ezfacility.com/hc/en-us/articles/23181863135387-How-to-Change-Self-Service-Settings-for-Packages | read (archive snapshot 2025-08-14) | APP-18, MKT-14, SSP-03 |
| https://support.ezfacility.com/hc/en-us/articles/23328878237467-February-28th-2024-Release-Notes | read (archive snapshot 2025-10-08) | CHK-06, CHK-08, CHK-21, MEM-20, REL-01, REL-04, RES-01, RPT-06, RPT-41 |
| https://support.ezfacility.com/hc/en-us/articles/23394858616603-How-to-find-past-current-and-future-Membership-Contracts-on-the-client-profile | read (archive snapshot 2025-08-14) | MEM-10 |
| https://support.ezfacility.com/hc/en-us/articles/23396052328859-How-to-view-invoices | read (archive snapshot 2025-10-08) | BIL-01, BIL-04, BIL-05, BIL-06, BIL-09, BIL-10 |
| https://support.ezfacility.com/hc/en-us/articles/23397491696795-Adding-a-Package-or-Add-On-to-a-Membership-Plan | read (archive snapshot 2025-08-06) | MEM-04, PKG-05, PKG-13 |
| https://support.ezfacility.com/hc/en-us/articles/23474524859803-Deposits-Report | read (archive snapshot 2025-10-08) | RPT-04 |
| https://support.ezfacility.com/hc/en-us/articles/23474526075419-Open-Invoices-By-Customer-Report | read (archive snapshot 2025-10-11) | RPT-06 |
| https://support.ezfacility.com/hc/en-us/articles/23474534910619-Using-the-Revenue-Report-in-EZFacility | read (archive snapshot 2025-08-04) | RPT-03 |
| https://support.ezfacility.com/hc/en-us/articles/23474559304859-Unapplied-Payments-by-Customer | read (archive snapshot 2025-08-14) | RPT-07 |
| https://support.ezfacility.com/hc/en-us/articles/23474580662555-Invoices-Report | read (archive snapshot 2025-08-04) | RPT-05 |
| https://support.ezfacility.com/hc/en-us/articles/23505030472475-How-to-View-Products-from-your-Product-Categories | read (archive snapshot 2025-08-14) | POS-01, POS-07 |
| https://support.ezfacility.com/hc/en-us/articles/23505035242779-Receipt-Printing-Using-the-QZ-Tray-Application-For-PC | read (archive snapshot 2025-08-08) | POS-15 |
| https://support.ezfacility.com/hc/en-us/articles/23505037972251-How-to-Refund-in-Point-of-Sale | read (archive snapshot 2025-08-14) | POS-16 |
| https://support.ezfacility.com/hc/en-us/articles/23505046070811-How-to-Edit-Quantity-or-Price-of-items-in-the-Point-of-Sale-Cart | read (archive snapshot 2025-08-04) | POS-09 |
| https://support.ezfacility.com/hc/en-us/articles/23505052562971-How-to-Add-Products-to-the-Shopping-Cart-and-Finish-Sale | read (archive snapshot 2025-10-08) | POS-07, POS-08, POS-12 |
| https://support.ezfacility.com/hc/en-us/articles/23505063085211-Receipt-Printing-Using-the-QZ-Tray-Application-For-Mac | read (archive snapshot 2025-10-11) | POS-15 |
| https://support.ezfacility.com/hc/en-us/articles/23505069345947-How-to-Search-for-a-Client-in-the-POS | read (archive snapshot 2025-08-14) | POS-08, POS-12, POS-18 |
| https://support.ezfacility.com/hc/en-us/articles/23505072579483-How-to-Email-a-P-O-S-Receipt-from-Completed-Transactions | read (archive snapshot 2025-10-08) | POS-12, POS-13, POS-16 |
| https://support.ezfacility.com/hc/en-us/articles/23505081363227-How-to-Discount-Individual-POS-Products-Equipment | read (archive snapshot 2025-08-04) | POS-10 |
| https://support.ezfacility.com/hc/en-us/articles/23505084116891-How-to-Enable-the-Email-Option-in-Point-of-Sale | read (archive snapshot 2025-08-14) | POS-13 |
| https://support.ezfacility.com/hc/en-us/articles/23573413327643-Setting-up-Auto-Renew-for-an-Individual-Package | read (archive snapshot 2025-10-08) | PKG-01, PKG-02, PKG-04, PKG-05, PKG-06 |
| https://support.ezfacility.com/hc/en-us/articles/23607740442011-How-to-Sell-a-Package-to-a-Client-on-their-Profile | read (archive snapshot 2025-08-14) | PKG-07 |
| https://support.ezfacility.com/hc/en-us/articles/23774929108123-How-to-View-Invoices-Under-a-Client-s-Profile | read (archive snapshot 2025-10-11) | BIL-04 |
| https://support.ezfacility.com/hc/en-us/articles/23774950594715-How-to-View-a-Billing-Statement-on-a-Client-s-Profile | read (archive snapshot 2025-08-04) | BIL-11 |
| https://support.ezfacility.com/hc/en-us/articles/23807158781211-March-14th-2024-Release-Notes | read (archive snapshot 2025-08-04) | CLI-03, CLI-21, FAM-04, INT-02, MEM-17, MEM-22, PAY-05, REL-01 |
| https://support.ezfacility.com/hc/en-us/articles/23852338482843-How-to-Change-your-Schedule-View | read (archive snapshot 2025-10-08) | SCH-01 |
| https://support.ezfacility.com/hc/en-us/articles/23857067036827-How-to-View-Payments-Made-on-a-Client-s-Profile | read (archive snapshot 2025-08-14) | PAY-03 |
| https://support.ezfacility.com/hc/en-us/articles/23857919227035-How-to-Run-a-Waitlist-Report-for-Groups | read (archive snapshot 2025-10-08) | RPT-28 |
| https://support.ezfacility.com/hc/en-us/articles/23864931136795-Deleting-or-Removing-a-Booking-or-Session-on-the-Schedule | title only — live page bot-challenged, no archive copy | SCH-11 |
| https://support.ezfacility.com/hc/en-us/articles/23929852504219-How-to-Mark-a-Group-as-Completed | read (archive snapshot 2025-08-06) | REG-05 |
| https://support.ezfacility.com/hc/en-us/articles/23969046407579-How-to-Connect-Your-Revenue-Categories | read (archive snapshot 2025-08-08) | BIL-13 |
| https://support.ezfacility.com/hc/en-us/articles/24225032928027-March-27th-2024-Release-Notes | read (archive snapshot 2025-08-14) | PAY-11, PAY-16, REG-12, REL-01, RPT-04, RPT-17, RPT-41 |
| https://support.ezfacility.com/hc/en-us/articles/24547185574939-How-to-Setup-Point-of-Sale | read (archive snapshot 2025-08-04) | POS-02, POS-03, POS-04, POS-05, POS-06 |
| https://support.ezfacility.com/hc/en-us/articles/24695840840603-April-10th-2024-Release-Notes | read (archive snapshot 2025-08-04) | CLS-01, CLS-02, CLS-03, CLS-04, MKT-11, PAY-06, PAY-10, PAY-16, REG-07, REL-01, RPT-04, RPT-41 |
| https://support.ezfacility.com/hc/en-us/articles/24856876239771-Email-Verification-and-Subscriptions-For-Clients | read (archive snapshot 2025-10-08) | MKT-01, MKT-02 |
| https://support.ezfacility.com/hc/en-us/articles/25134483797531-April-24th-2024-Release-Notes | read (archive snapshot 2025-10-11) | BIL-23, CLI-04, CLI-13, CLI-16, FAM-04, INT-02, INT-03, MEM-17, MEM-22, MKT-02, REG-11, REL-01, SSP-10 |
| https://support.ezfacility.com/hc/en-us/articles/25312556816539-Create-and-Manage-Relationships-in-Self-Service | read (archive snapshot 2025-08-04) | FAM-02, FAM-03 |
| https://support.ezfacility.com/hc/en-us/articles/25312602916763-How-to-Book-a-Rental-on-Self-Service | read (archive snapshot 2025-08-08) | SSP-04 |
| https://support.ezfacility.com/hc/en-us/articles/25419259427099-How-to-Email-an-Invoice-to-a-Client | read (archive snapshot 2025-08-14) | BIL-10, PAY-18 |
| https://support.ezfacility.com/hc/en-us/articles/25551222201627-May-8th-2024-Release-Notes | read (archive snapshot 2025-10-08) | CLI-01, CLI-19, MKT-04, PAY-01, PLT-01, REL-01, REL-04, REL-05, RPT-01 |
| https://support.ezfacility.com/hc/en-us/articles/25631630542619-How-to-Send-a-Client-a-Billing-Statement | read (archive snapshot 2025-08-06) | BIL-11 |
| https://support.ezfacility.com/hc/en-us/articles/25737423648923-How-to-Partially-Refund-a-Sale | read (archive snapshot 2025-08-08) | BIL-01, PAY-05 |
| https://support.ezfacility.com/hc/en-us/articles/25985296561179-May-23rd-2024-Release-Note | read (archive snapshot 2025-08-08) | MKT-04, MKT-08, REL-01, RPT-29 |
| https://support.ezfacility.com/hc/en-us/articles/26094951298331-How-to-Create-Coupons | read (archive snapshot 2025-08-06) | BIL-15, POS-11 |
| https://support.ezfacility.com/hc/en-us/articles/26114234694043-How-to-Create-an-Invoice-for-Un-invoiced-Items | read (archive snapshot 2025-10-11) | BIL-02, PAY-18 |
| https://support.ezfacility.com/hc/en-us/articles/26114282998811-How-to-view-all-open-invoices | read (archive snapshot 2025-10-08) | BIL-02, BIL-07, BIL-10, BIL-14 |
| https://support.ezfacility.com/hc/en-us/articles/26498179644187-June-5th-2024-Release-Notes | read (archive snapshot 2025-08-04) | APP-19, CHK-12, CLI-01, INT-04, INT-05, MEM-21, PKG-09, PKG-16, POS-01, POS-10, REL-01, REL-04, RPT-06, RPT-12, SCH-07, SCH-08, SSP-19 |
| https://support.ezfacility.com/hc/en-us/articles/26528293115547-Book-into-a-Session-and-Buy-a-Package-on-Self-Service | read (archive snapshot 2025-08-04) | SSP-08 |
| https://support.ezfacility.com/hc/en-us/articles/26528305868699-How-to-Create-an-Account-on-Self-Service | read (archive snapshot 2025-08-14) | SSP-05 |
| https://support.ezfacility.com/hc/en-us/articles/26528401455643-How-to-Assign-an-Invoice-to-a-Different-Client | read (archive snapshot 2025-06-21) | BIL-05 |
| https://support.ezfacility.com/hc/en-us/articles/26530327505947-How-to-Print-Manual-Game-Cards | read (archive snapshot 2025-08-08) | LGE-16 |
| https://support.ezfacility.com/hc/en-us/articles/26530549235995-How-to-Print-Multiple-Game-Cards | read (archive snapshot 2025-10-08) | LGE-16 |
| https://support.ezfacility.com/hc/en-us/articles/26531757019291-How-to-Upload-your-Facility-Banner | read (archive snapshot 2025-06-21) | LGE-19 |
| https://support.ezfacility.com/hc/en-us/articles/26569114691099-How-to-Add-Venues | read (archive snapshot 2025-04-27) | RES-06 |
| https://support.ezfacility.com/hc/en-us/articles/26569254117915-How-to-Add-Officials | read (archive snapshot 2025-08-04) | LGE-15 |
| https://support.ezfacility.com/hc/en-us/articles/26594931297435-How-to-Utilize-the-TV-Display | read (archive snapshot 2025-10-08) | LGE-24 |
| https://support.ezfacility.com/hc/en-us/articles/26596341240091-How-to-Create-a-User-Account-in-EZLeagues | read (archive snapshot 2025-08-04) | PLT-11 |
| https://support.ezfacility.com/hc/en-us/articles/26596651427867-How-to-Add-and-Manage-Links | read (archive snapshot 2025-08-06) | LGE-20 |
| https://support.ezfacility.com/hc/en-us/articles/26601309581211-How-to-Configure-your-Site-Options-for-EZLeagues | read (archive snapshot 2025-08-04) | PLT-12 |
| https://support.ezfacility.com/hc/en-us/articles/26661408580891-How-to-Add-News-Articles-on-the-Public-Website | read (archive snapshot 2025-08-14) | MKT-18 |
| https://support.ezfacility.com/hc/en-us/articles/26662662847387-How-to-Add-Photo-s-to-your-EZLeagues-Public-Site | read (archive snapshot 2025-08-14) | LGE-21 |
| https://support.ezfacility.com/hc/en-us/articles/26686781401755-How-to-Manage-Pickup-Games-in-EZLeagues | read (archive snapshot 2025-10-08) | LGE-23 |
| https://support.ezfacility.com/hc/en-us/articles/26720911427099-Picking-Team-Preferences-in-EZLeagues | read (archive snapshot 2025-08-14) | LGE-10 |
| https://support.ezfacility.com/hc/en-us/articles/26750732215835-June-19th-2024-Release-Notes | read (archive snapshot 2025-08-14) | APP-19, INT-05, MKT-03, PAY-06, PKG-09, PKG-16, REL-01, REL-02, SCH-12, SSP-19 |
| https://support.ezfacility.com/hc/en-us/articles/26753390899995-How-to-Create-a-Tournament-Schedule-Single-Elimination-Bracket | read (archive snapshot 2025-06-21) | LGE-12 |
| https://support.ezfacility.com/hc/en-us/articles/26753407797019-How-To-Create-a-Tournament-Schedule-Double-Elimination-Bracket | read (archive snapshot 2025-10-11) | LGE-12 |
| https://support.ezfacility.com/hc/en-us/articles/26753410817051-How-To-Create-a-Three-Games-Guaranteed-Schedule-8-Team-Tournament | read (archive snapshot 2025-08-14) | LGE-13 |
| https://support.ezfacility.com/hc/en-us/articles/26753867674011-How-to-Generate-a-League-Schedule-Even-Number-of-Team | read (archive snapshot 2025-10-08) | LGE-08 |
| https://support.ezfacility.com/hc/en-us/articles/26754163075099-How-to-Generate-a-Pool-Play-Schedule-in-EZLeagues | read (archive snapshot 2025-10-11) | LGE-11 |
| https://support.ezfacility.com/hc/en-us/articles/26754181794331-How-to-Generate-a-League-Schedule-Odd-Number-of-Teams-Bye | read (archive snapshot 2025-08-14) | LGE-08, LGE-09 |
| https://support.ezfacility.com/hc/en-us/articles/26754230417819-How-to-Manage-Scores-in-EZLeagues | read (archive snapshot 2025-08-14) | LGE-14, LGE-15, LGE-16 |
| https://support.ezfacility.com/hc/en-us/articles/26754276440219-How-to-View-your-EZLeagues-Public-Website | read (archive snapshot 2025-08-04) | LGE-18 |
| https://support.ezfacility.com/hc/en-us/articles/27444958543003-How-to-Rent-and-Return-Equipment | read (archive snapshot 2025-08-14) | POS-18 |
| https://support.ezfacility.com/hc/en-us/articles/27444960685851-How-to-Add-Equipment-to-POS | read (archive snapshot 2025-08-14) | POS-17 |
| https://support.ezfacility.com/hc/en-us/articles/27550762531739-How-to-use-the-Self-Check-in-Station | read (archive snapshot 2025-04-27) | CHK-05 |
| https://support.ezfacility.com/hc/en-us/articles/27662401294875-How-to-Connect-Documents-to-Services | read (archive snapshot 2025-10-11) | DOC-08 |
| https://support.ezfacility.com/hc/en-us/articles/27663085801883-Editing-Document-Templates-in-EZFacility | read (archive snapshot 2025-08-14) | DOC-01 |
| https://support.ezfacility.com/hc/en-us/articles/27663284408603-View-a-History-of-all-Acknowledged-Documents | read (archive snapshot 2025-10-08) | DOC-06 |
| https://support.ezfacility.com/hc/en-us/articles/27663294760091-How-to-View-Document-History-on-a-Client-Profile | read (archive snapshot 2025-08-06) | DOC-06 |
| https://support.ezfacility.com/hc/en-us/articles/27663339302939-Clear-Cache-in-Google-Chrome | read (archive snapshot 2025-10-08) | excluded (no product capability) |
| https://support.ezfacility.com/hc/en-us/articles/27808005266843-Create-a-New-Email-Campaign-2024 | read (archive snapshot 2025-10-08) | MKT-04, MKT-05 |
| https://support.ezfacility.com/hc/en-us/articles/27808006885275-Change-Permissions-for-Email-Campaigns-2024 | read (archive snapshot 2025-10-08) | MKT-04, PLT-05, PLT-06 |
| https://support.ezfacility.com/hc/en-us/articles/27808007575195-How-to-Edit-an-Email-Campaign-Draft-2024 | read (archive snapshot 2025-08-14) | MKT-04 |
| https://support.ezfacility.com/hc/en-us/articles/27808030170267-Sent-Email-Campaign-2024 | read (archive snapshot 2025-08-08) | MKT-07 |
| https://support.ezfacility.com/hc/en-us/articles/27849876503323-Registering-A-Client-Into-Multiple-Available-Sessions | read (archive snapshot 2025-10-08) | CLS-02, CLS-03, SCH-06 |
| https://support.ezfacility.com/hc/en-us/articles/27849984397979-How-to-Disable-a-Client | read (archive snapshot 2025-08-04) | CLI-14 |
| https://support.ezfacility.com/hc/en-us/articles/27882337605915-How-to-Setup-the-Employee-Time-Clock | read (archive snapshot 2025-06-21) | STF-06 |
| https://support.ezfacility.com/hc/en-us/articles/27882374264603-How-to-Use-the-Employee-Time-Clock-as-Staff | read (archive snapshot 2025-10-11) | STF-07 |
| https://support.ezfacility.com/hc/en-us/articles/27902451074715-How-to-Access-and-Download-a-Report | read (archive snapshot 2025-08-04) | RPT-01 |
| https://support.ezfacility.com/hc/en-us/articles/27905516067227-How-to-Use-the-Time-Clock-Report | read (archive snapshot 2025-08-06) | RPT-37 |
| https://support.ezfacility.com/hc/en-us/articles/27907266866715-How-to-Establish-Relationships-between-Clients-on-their-Profiles | read (archive snapshot 2025-10-08) | FAM-01 |
| https://support.ezfacility.com/hc/en-us/articles/27914135025819-Self-Check-in-Station-Settings | read (archive snapshot 2025-08-04) | CHK-05, CHK-06 |
| https://support.ezfacility.com/hc/en-us/articles/27914147357339-Staff-Check-in-Station-Settings | read (archive snapshot 2025-10-08) | CHK-02, CHK-04, CHK-08 |
| https://support.ezfacility.com/hc/en-us/articles/27996895819547-Setting-up-Access-Control | read (archive snapshot 2025-08-06) | CHK-08, CHK-09, CHK-10, CHK-16 |
| https://support.ezfacility.com/hc/en-us/articles/28006134764315-How-to-Create-and-Use-Tags-on-a-Client-Profile | read (archive snapshot 2025-08-04) | CLI-08 |
| https://support.ezfacility.com/hc/en-us/articles/28071987897371-How-to-Merge-Client-Profiles | read (archive snapshot 2025-10-08) | CLI-13 |
| https://support.ezfacility.com/hc/en-us/articles/28333307842971-How-to-Set-Up-Trainer-Commission | read (archive snapshot 2025-08-14) | STF-01, STF-02, STF-03 |
| https://support.ezfacility.com/hc/en-us/articles/28746953502875-How-to-Publish-a-Group-to-Self-Service | read (archive snapshot 2025-10-11) | REG-10, SSP-17 |
| https://support.ezfacility.com/hc/en-us/articles/29093590126363-How-to-add-a-Photo-to-a-Client-Profile | read (archive snapshot 2025-08-06) | CLI-12 |
| https://support.ezfacility.com/hc/en-us/articles/29194634692123-Try-us-feature-MemberMe-Branded-App | read (archive snapshot 2025-08-08) | APP-12, APP-16 |
| https://support.ezfacility.com/hc/en-us/articles/29194635092123-Branded-App-Home-Screen-Additional-App-Design-Settings | read (archive snapshot 2025-10-08) | APP-04 |
| https://support.ezfacility.com/hc/en-us/articles/29194752348827-Sending-Targeted-Push-Notifications-Branded-App-Only-Additional-subscription-required | read (archive snapshot 2025-06-21) | MKT-17 |
| https://support.ezfacility.com/hc/en-us/articles/29244296451355-Sending-Targeted-Push-Notifications-Branded-App-Only-Additional-subscription-required | read (archive snapshot 2025-06-21) | MKT-17 |
| https://support.ezfacility.com/hc/en-us/articles/29244307886747-Tell-a-friend-tab-MemberMe-Branded-App | read (archive snapshot 2025-10-08) | APP-11 |
| https://support.ezfacility.com/hc/en-us/articles/29244308148635-Services-Tab-MemberMe-Branded-App | read (archive snapshot 2025-10-11) | APP-09 |
| https://support.ezfacility.com/hc/en-us/articles/29244320427931-How-to-access-and-use-analytics-for-your-app-Branded-App | read (archive snapshot 2025-08-14) | RPT-38 |
| https://support.ezfacility.com/hc/en-us/articles/29244325119899-News-Info-feature-MemberMe-Branded-App | read (archive snapshot 2025-08-14) | APP-07 |
| https://support.ezfacility.com/hc/en-us/articles/29244336130203-Clear-client-member-card-from-database-MemberMe-Branded-App | read (archive snapshot 2025-08-08) | CHK-13 |
| https://support.ezfacility.com/hc/en-us/articles/29244337277083-Sending-Push-Notifications-MemberMe-Branded-App | read (archive snapshot 2025-08-14) | APP-16, APP-17, MKT-16 |
| https://support.ezfacility.com/hc/en-us/articles/29244338187547-Creating-user-admin-profiles-for-MiGym-admin-portal-MemberMe-Branded-App | read (archive snapshot 2025-08-08) | PLT-13 |
| https://support.ezfacility.com/hc/en-us/articles/29244354753179-Feedback-Tab-MemberMe-Branded-App | read (archive snapshot 2025-08-06) | APP-10, APP-16 |
| https://support.ezfacility.com/hc/en-us/articles/29244419129627-Branded-App-Home-Screen-Layout-Configuration | read (archive snapshot 2025-08-14) | APP-04, APP-05, APP-06, APP-10, APP-13, APP-14, APP-15, APP-16 |
| https://support.ezfacility.com/hc/en-us/articles/29244421350555-Branded-App-Home-Screen-Labels-Captions-Dynamic-Text-and-Caption-Customizing | read (archive snapshot 2025-10-11) | APP-04, APP-13 |
| https://support.ezfacility.com/hc/en-us/articles/29244434035355-Contact-Hours-Tab-MemberMe-Branded-App | read (archive snapshot 2025-08-14) | APP-08 |
| https://support.ezfacility.com/hc/en-us/articles/29244435018395-Branded-App-Home-Screen-Layout-Icons-Background | read (archive snapshot 2025-10-08) | APP-04 |
| https://support.ezfacility.com/hc/en-us/articles/29244450573339-Branded-App-Home-Screen-Tiles-info | read (archive snapshot 2025-08-06) | APP-05, APP-07, APP-12 |
| https://support.ezfacility.com/hc/en-us/articles/29554644710171-Creating-A-New-User | read (archive snapshot 2025-08-04) | PLT-02 |
| https://support.ezfacility.com/hc/en-us/articles/29554698393883-How-to-Change-a-User-s-Password | read (archive snapshot 2025-10-08) | PLT-03 |
| https://support.ezfacility.com/hc/en-us/articles/29583648663195-How-to-choose-your-EZFacility-default-platform-on-the-New-EZFacility-Experience | read (archive snapshot 2025-10-08) | PLT-09 |
| https://support.ezfacility.com/hc/en-us/articles/29584008031259-How-to-choose-your-EZFacility-default-platform-on-the-Classic-EZFacility-Experience | read (archive snapshot 2025-08-14) | PLT-09, RES-01 |
| https://support.ezfacility.com/hc/en-us/articles/29585782102683-Unlocking-the-Power-of-EZFacility-s-New-UI-Your-Guide-to-a-Smooth-Transition | read (archive snapshot 2025-08-14) | REL-03 |
| https://support.ezfacility.com/hc/en-us/articles/29748234477595-Creating-A-Custom-Role | read (archive snapshot 2025-10-08) | PLT-04 |
| https://support.ezfacility.com/hc/en-us/articles/29783959046555-How-to-Set-Up-Reservation-Types-in-EZFacility-Classic | read (archive snapshot 2025-10-08) | CLS-05, SCH-02, SCH-04 |
| https://support.ezfacility.com/hc/en-us/articles/29784038483867-How-to-Set-Up-Multiple-Session-Package-Plans-in-EZFacility-Classic | read (archive snapshot 2025-08-14) | PKG-01 |
| https://support.ezfacility.com/hc/en-us/articles/29784117801755-How-to-Set-Up-Single-Session-Package-Plans-in-EZFacility-Classic | read (archive snapshot 2025-08-14) | PKG-01 |
| https://support.ezfacility.com/hc/en-us/articles/29784160666267-How-to-Set-Up-Unlimited-Package-Plans-in-EZFacility-Classic | read (archive snapshot 2025-06-21) | PKG-01 |
| https://support.ezfacility.com/hc/en-us/articles/29784623019035-How-to-Set-Up-Package-Recurring-Plans-in-EZFacility-Classic | read (archive snapshot 2025-06-21) | PKG-03, PKG-04 |
| https://support.ezfacility.com/hc/en-us/articles/29784674271131-How-to-Set-Up-Complimentary-Sessions-in-EZFacility-Classic | read (archive snapshot 2025-08-06) | PKG-02 |
| https://support.ezfacility.com/hc/en-us/articles/29784817818907-How-to-Close-and-Review-Post-Billed-Packages-in-EZFacility-Classic | read (archive snapshot 2025-08-04) | BIL-10, BIL-18 |
| https://support.ezfacility.com/hc/en-us/articles/29794984963099-Setting-Up-Membership-Plans-in-EZFacility-Classic | read (archive snapshot 2025-08-14) | MEM-02, MEM-11, MEM-20 |
| https://support.ezfacility.com/hc/en-us/articles/29796200065179-Prorating-Membership-Plans-in-EZFacility-Classic | read (archive snapshot 2025-08-04) | MEM-03 |
| https://support.ezfacility.com/hc/en-us/articles/29852081983387-Creating-a-Membership-Contract-Agreement-in-EZFacility-Classic | read (archive snapshot 2025-10-11) | DOC-11, DOC-12 |
| https://support.ezfacility.com/hc/en-us/articles/29852095095067-Setting-Up-Membership-Preferences-in-EZFacility-Classic | read (archive snapshot 2025-08-14) | MEM-05, MEM-12, MEM-15, MEM-19 |
| https://support.ezfacility.com/hc/en-us/articles/29852099999259-Setting-Up-a-Simple-Membership-in-EZFacility-Classic | read (archive snapshot 2025-08-14) | CHK-08, CHK-11, MEM-06, MEM-19 |
| https://support.ezfacility.com/hc/en-us/articles/29852167415195-Allowing-Memberships-to-be-Sold-Online-in-EZFacility-Classic | read (archive snapshot 2025-10-08) | MEM-02, MEM-09 |
| https://support.ezfacility.com/hc/en-us/articles/29852220977051-Setting-Up-a-Membership-Agreements-in-EZFacility-Classic | read (archive snapshot 2025-08-14) | DOC-10, DOC-12 |
| https://support.ezfacility.com/hc/en-us/articles/29852227776923-Enabling-Membership-Agreements-when-Selling-Memberships-Online-in-EZFacility-Classic | read (archive snapshot 2025-08-09) | DOC-10 |
| https://support.ezfacility.com/hc/en-us/articles/29852337573787-Online-Webinar-Using-Membership-Add-ons-in-EZFacility-Classic | read (archive snapshot 2025-08-06) | ONB-02 |
| https://support.ezfacility.com/hc/en-us/articles/29852339864987-Defaulting-New-Membership-Contracts-to-Auto-Pay-in-Self-Service | read (archive snapshot 2025-08-08) | BIL-16, BIL-17 |
| https://support.ezfacility.com/hc/en-us/articles/29852362973211-Creating-Membership-Types-in-EZFacility-Classic | read (archive snapshot 2025-08-08) | MEM-01 |
| https://support.ezfacility.com/hc/en-us/articles/29852788198427-How-to-Set-Up-Rental-Types-in-EZFacility-Classic | read (archive snapshot 2025-10-08) | RNT-01 |
| https://support.ezfacility.com/hc/en-us/articles/29859659205787-How-to-Set-Up-Rental-Rates-in-EZFacility-Classic | read (archive snapshot 2025-08-14) | RNT-02 |
| https://support.ezfacility.com/hc/en-us/articles/29861551814171-How-to-Set-Up-Contact-Preferences-in-EZFacility-Classic | read (archive snapshot 2025-10-08) | CLI-04, CLI-05, CLI-16 |
| https://support.ezfacility.com/hc/en-us/articles/30051822805659-How-to-Use-the-Employee-Time-Clock-in-EZFacility-Classic | read (archive snapshot 2025-10-08) | PLT-02, PLT-07, STF-06, STF-07, STF-08 |
| https://support.ezfacility.com/hc/en-us/articles/30058010593563-How-to-Share-a-Direct-Registration-Link-for-a-Session-in-EZFacility-Classic | read (archive snapshot 2025-08-14) | SCH-16 |
| https://support.ezfacility.com/hc/en-us/articles/30058087582875-Managing-Self-Service-Shared-Bookings-in-EZFacility-Classic | read (archive snapshot 2025-08-04) | CLS-09, SCH-03, SCH-16, SCH-17 |
| https://support.ezfacility.com/hc/en-us/articles/30146189430171-Adding-a-Client-Profile-to-the-New-EZFacility-Experience | read (archive snapshot 2025-08-08) | CLI-01, CLI-02, CLI-03 |
| https://support.ezfacility.com/hc/en-us/articles/31149286284187-How-to-Set-Up-Online-Registration-for-a-Group-in-the-Classic-EZFacility-Experience | read (archive snapshot 2025-08-14) | REG-10, REG-11 |
| https://support.ezfacility.com/hc/en-us/articles/33119920006427-How-to-direct-email-a-client-through-their-profile-in-EZFacility-Classic | read (archive snapshot 2025-10-08) | MKT-10 |
| https://support.ezfacility.com/hc/en-us/articles/33122944575899-How-to-direct-email-a-client-through-their-profile | read (archive snapshot 2025-10-08) | MKT-10 |
| https://support.ezfacility.com/hc/en-us/articles/34155834657819-July-3rd-2024-Release-Notes | read (archive snapshot 2025-08-14) | CLS-03, CLS-06, CLS-08, INT-09, MEM-21, PLT-04, REL-01, REL-03, REL-05, RPT-41, SCH-05 |
| https://support.ezfacility.com/hc/en-us/articles/34200838065179-Using-the-Revenue-Report-in-EZFacility | read (archive snapshot 2025-10-11) | RPT-03 |
| https://support.ezfacility.com/hc/en-us/articles/34200840681499-Deposits-Report | read (archive snapshot 2025-06-21) | RPT-04 |
| https://support.ezfacility.com/hc/en-us/articles/34200876269083-Open-Invoices-By-Customer-Report | read (archive snapshot 2025-06-21) | RPT-06 |
| https://support.ezfacility.com/hc/en-us/articles/34406647603227-Enabling-the-Vaccine-Passport-Feature-in-EZFacility-Classic | read (archive snapshot 2025-10-08) | CHK-17, RES-01 |
| https://support.ezfacility.com/hc/en-us/articles/34414402160795-How-to-View-Products-from-your-Product-Categories | read (archive snapshot 2025-10-11) | POS-01, POS-07 |
| https://support.ezfacility.com/hc/en-us/articles/34418751007771-How-to-Discount-Individual-POS-Products-Equipment | read (archive snapshot 2025-10-11) | POS-10 |
| https://support.ezfacility.com/hc/en-us/articles/34418766515099-How-to-Add-Products-to-the-Shopping-Cart-and-Finish-Sale | read (archive snapshot 2025-10-11) | POS-07, POS-12 |
| https://support.ezfacility.com/hc/en-us/articles/34418766995099-How-to-Set-Up-Equipment-in-EZFacility-Classic | read (archive snapshot 2025-10-08) | POS-17, RNT-14 |
| https://support.ezfacility.com/hc/en-us/articles/34418782382235-How-to-Rent-Equipment-in-EZFacility-Classic | read (archive snapshot 2025-10-11) | POS-08, POS-18, RNT-15 |
| https://support.ezfacility.com/hc/en-us/articles/34418794060699-Receipt-Printing-Using-the-QZ-Tray-Application-For-PC | read (archive snapshot 2025-10-08) | POS-15 |
| https://support.ezfacility.com/hc/en-us/articles/34418802043931-How-to-Search-for-a-Customer-in-the-POS | read (archive snapshot 2025-10-11) | POS-08 |
| https://support.ezfacility.com/hc/en-us/articles/34418804557467-How-to-Return-Equipment-Rentals-in-EZFacility-Classic | read (archive snapshot 2025-06-21) | POS-18, RNT-16 |
| https://support.ezfacility.com/hc/en-us/articles/34418821391131-How-to-Search-for-a-Customer-in-the-POS | read (archive snapshot 2025-06-21) | POS-08 |
| https://support.ezfacility.com/hc/en-us/articles/34418830364443-How-to-Edit-Quantity-or-Price-of-items-in-the-Point-of-Sale-Cart | read (archive snapshot 2025-10-11) | POS-09 |
| https://support.ezfacility.com/hc/en-us/articles/34418850910747-How-to-Edit-Quantity-or-Price-of-items-in-the-Point-of-Sale-Cart | read (archive snapshot 2025-10-08) | POS-09 |
| https://support.ezfacility.com/hc/en-us/articles/34418851502875-Receipt-Printing-Using-the-QZ-Tray-Application-For-Mac | read (archive snapshot 2025-06-21) | POS-15 |
| https://support.ezfacility.com/hc/en-us/articles/34418890607643-How-to-Launch-the-New-Point-of-Sale | read (archive snapshot 2025-10-08) | POS-01 |
| https://support.ezfacility.com/hc/en-us/articles/34418925611803-How-to-Email-P-O-S-Receipts-from-the-Sale-Complete-Page | read (archive snapshot 2025-08-14) | POS-08, POS-13 |
| https://support.ezfacility.com/hc/en-us/articles/34418934806171-How-to-Set-Up-Rental-Equipment-in-EZFacility-Classic | read (archive snapshot 2025-08-14) | POS-17, RNT-14 |
| https://support.ezfacility.com/hc/en-us/articles/34418941582747-New-Point-of-Sale-Customizing-the-Receipt | read (archive snapshot 2025-10-11) | POS-09, POS-10, POS-11, POS-14 |
| https://support.ezfacility.com/hc/en-us/articles/34418959208987-How-to-Email-a-P-O-S-Receipt-from-Completed-Transactions | read (archive snapshot 2025-08-14) | POS-13 |
| https://support.ezfacility.com/hc/en-us/articles/34418971487387-How-to-Enable-the-Email-Option-in-Point-of-Sale | read (archive snapshot 2025-10-11) | POS-13 |
| https://support.ezfacility.com/hc/en-us/articles/34418975239707-All-Inventory-Report | read (archive snapshot 2025-10-11) | POS-22, RPT-33 |
| https://support.ezfacility.com/hc/en-us/articles/34418979987611-All-Sales-Report | read (archive snapshot 2025-10-11) | RPT-30 |
| https://support.ezfacility.com/hc/en-us/articles/34418995181595-How-to-Email-a-P-O-S-Receipt-from-Completed-Transactions | read (archive snapshot 2025-10-11) | POS-13 |
| https://support.ezfacility.com/hc/en-us/articles/34419009666459-Inventory-Re-order-Report | read (archive snapshot 2025-10-08) | POS-06, POS-22, RPT-33 |
| https://support.ezfacility.com/hc/en-us/articles/34419017128987-Order-Returns-Refunds | read (archive snapshot 2025-10-11) | POS-16, RPT-31 |
| https://support.ezfacility.com/hc/en-us/articles/34419021121051-Daily-Register-Report | read (archive snapshot 2025-08-14) | POS-16, POS-22, RPT-32 |
| https://support.ezfacility.com/hc/en-us/articles/34419023035803-POS-Deposits | read (archive snapshot 2025-10-11) | POS-20 |
| https://support.ezfacility.com/hc/en-us/articles/34419042530587-Sales-by-Coupon | read (archive snapshot 2025-10-08) | POS-11, RPT-30 |
| https://support.ezfacility.com/hc/en-us/articles/34419046220827-Product-Sales-By-Brand | read (archive snapshot 2025-10-11) | RPT-30 |
| https://support.ezfacility.com/hc/en-us/articles/34419051390875-Sales-By-Employee | read (archive snapshot 2025-10-11) | RPT-30 |
| https://support.ezfacility.com/hc/en-us/articles/34419054829979-Product-Sales-By-Supplier | read (archive snapshot 2025-08-14) | RPT-30 |
| https://support.ezfacility.com/hc/en-us/articles/34419055387547-Sales-By-Category | read (archive snapshot 2025-10-08) | RPT-30 |
| https://support.ezfacility.com/hc/en-us/articles/34419060229787-All-Equipment-Inventory-in-EZFacility-Classic | read (archive snapshot 2025-06-21) | RPT-34 |
| https://support.ezfacility.com/hc/en-us/articles/34419081377307-Setting-Up-Product-Brands | read (archive snapshot 2025-06-21) | POS-04 |
| https://support.ezfacility.com/hc/en-us/articles/34419084373915-Setting-Up-Cash-Registers | read (archive snapshot 2025-10-11) | POS-02 |
| https://support.ezfacility.com/hc/en-us/articles/34419085151003-How-to-Create-a-Product-Subcategory | read (archive snapshot 2025-08-14) | POS-03 |
| https://support.ezfacility.com/hc/en-us/articles/34419086218779-How-to-Edit-a-Product | read (archive snapshot 2025-08-14) | POS-05 |
| https://support.ezfacility.com/hc/en-us/articles/34419089287067-View-the-Checked-Out-Equipment-in-EZFacility-Classic | read (archive snapshot 2025-06-21) | POS-18, RPT-34 |
| https://support.ezfacility.com/hc/en-us/articles/34419095821979-How-to-Edit-a-Product-Category | read (archive snapshot 2025-08-14) | POS-03 |
| https://support.ezfacility.com/hc/en-us/articles/34419162852891-Setting-Up-Product-Suppliers | read (archive snapshot 2025-10-08) | POS-04 |
| https://support.ezfacility.com/hc/en-us/articles/34419183605659-Refunding-in-the-Point-of-Sale | read (archive snapshot 2025-08-14) | POS-16 |
| https://support.ezfacility.com/hc/en-us/articles/34419191751451-Setting-Up-Product-Categories-Inventory | read (archive snapshot 2025-10-11) | POS-03, POS-05, POS-06, POS-10 |
| https://support.ezfacility.com/hc/en-us/articles/34419193012379-How-to-Add-Inventory-to-a-Product | read (archive snapshot 2025-10-08) | POS-06 |
| https://support.ezfacility.com/hc/en-us/articles/34419227413659-Assigning-A-Role-to-A-User | read (archive snapshot 2025-08-14) | PLT-05 |
| https://support.ezfacility.com/hc/en-us/articles/34419970103963-The-Three-Types-of-Imports-Available | read (archive snapshot 2025-10-11) | IMP-01 |
| https://support.ezfacility.com/hc/en-us/articles/34419979004187-The-Three-Types-of-Imports-Available | read (archive snapshot 2025-06-21) | IMP-01 |
| https://support.ezfacility.com/hc/en-us/articles/34439589179291-How-to-Create-a-Post-Billed-Package-in-EZFacility-Classic | read (archive snapshot 2025-10-11) | PKG-11 |
| https://support.ezfacility.com/hc/en-us/articles/34439958272283-How-to-Sell-a-Post-Billed-Package-in-EZFacility-Classic | read (archive snapshot 2025-06-21) | PKG-05, PKG-06, PKG-11, PKG-14 |
| https://support.ezfacility.com/hc/en-us/articles/34440097348379-Creating-a-Package-with-an-Expiration-Date-in-EZFacility-Classic | read (archive snapshot 2025-08-14) | PKG-04 |
| https://support.ezfacility.com/hc/en-us/articles/34440874732443-How-to-Set-Up-Reservation-Types-in-EZFacility-Classic | read (archive snapshot 2025-10-11) | CLS-04, CLS-05, SCH-02, SCH-03, SCH-04 |
| https://support.ezfacility.com/hc/en-us/articles/34441361024795-How-to-Create-Member-Only-Package-Plans-in-EZFacility-Classic | read (archive snapshot 2025-08-14) | PKG-10 |
| https://support.ezfacility.com/hc/en-us/articles/34441456779163-Online-Webinar-Zoom-Integration-in-EZFacility-Classic | read (archive snapshot 2025-08-14) | INT-09 |
| https://support.ezfacility.com/hc/en-us/articles/34441526893339-Online-Webinar-Packages-and-Reservations-in-EZFacility-Classic | read (archive snapshot 2025-08-14) | ONB-02 |
| https://support.ezfacility.com/hc/en-us/articles/36516396025115-April-23rd-2025-Release-Notes | read (archive snapshot 2025-08-14) | CHK-01, DOC-08, MEM-08, REL-01, REL-02, REL-03, RES-05, SCH-09 |
| https://support.ezfacility.com/hc/en-us/articles/36516560976539-April-9th-2025-Release-Notes | read (archive snapshot 2025-08-14) | BIL-13, CHK-11, IMP-01, INT-01, INT-02, MEM-01, MEM-19, MEM-22, MKT-04, ONB-04, PAY-10, PAY-13, PLT-01, POS-08, POS-10, POS-21, REG-12, REL-01, REL-02, RPT-01, RPT-41 |
| https://support.ezfacility.com/hc/en-us/articles/37195623250587-Click-to-Disable-Auto-Renew-Memberships | read (archive snapshot 2025-10-08) | MEM-18, PKG-05 |
| https://support.ezfacility.com/hc/en-us/articles/37195953487515-What-is-the-Click-to-Cancel-feature | title only — live page bot-challenged, no archive copy | MEM-18 |
| https://support.ezfacility.com/hc/en-us/articles/38068447234331-How-to-Enable-GDPR-on-EZFacility | read (archive snapshot 2025-10-08) | DOC-09 |
| https://support.ezfacility.com/hc/en-us/articles/38068886342171-How-to-Create-a-GDPR-Document | read (archive snapshot 2025-10-08) | DOC-01, DOC-09 |
| https://support.ezfacility.com/hc/en-us/articles/38071098727067-How-to-Send-a-GDPR-Document-to-a-client-from-their-profile | read (archive snapshot 2025-10-08) | DOC-03, DOC-04, DOC-09 |
| https://support.ezfacility.com/hc/en-us/articles/38072534577307-How-to-send-Documents-in-en-mass | read (archive snapshot 2025-10-11) | DOC-07 |
| https://support.ezfacility.com/hc/en-us/articles/38623038228763-Removing-a-Freeze-in-EZFacility | read (archive snapshot 2025-10-08) | MEM-13 |
| https://support.ezfacility.com/hc/en-us/articles/42551868532891-How-to-Sell-Packages-Through-the-Point-of-Sale | title only — live page bot-challenged, no archive copy | PKG-08, POS-19 |
| https://support.ezfacility.com/hc/en-us/articles/42552021593499-How-to-Sell-Packages-Through-the-Point-of-Sale-Classic | title only — live page bot-challenged, no archive copy | PKG-08, POS-19 |
| https://support.ezfacility.com/hc/en-us/articles/42755413196443-October-23-2025-Release-Notes | title only — live page bot-challenged, no archive copy | REL-01 |
| https://support.ezfacility.com/hc/en-us/articles/42913648411931-Dark-Mode | title only — live page bot-challenged, no archive copy | PLT-10 |
| https://support.ezfacility.com/hc/en-us/articles/43326763052443-November-14-2025-Release-Notes | title only — live page bot-challenged, no archive copy | REL-01 |
| https://support.ezfacility.com/hc/en-us/articles/4401983374619-How-to-Sell-a-Membership-from-the-Client-Profile | read (archive snapshot 2025-04-29) | MEM-07, MEM-08 |
| https://support.ezfacility.com/hc/en-us/articles/4401990000411-How-to-Share-a-Membership | read (archive snapshot 2025-06-21) | FAM-01, FAM-04, FAM-05 |
| https://support.ezfacility.com/hc/en-us/articles/4401990058523-How-to-Sell-a-Membership-from-Administration | read (archive snapshot 2025-10-11) | MEM-03, MEM-04, MEM-07, MEM-08 |
| https://support.ezfacility.com/hc/en-us/articles/4402058520603-How-to-add-Membership-Plans | read (archive snapshot 2025-08-14) | MEM-02, MEM-03, MEM-04, MEM-08, MEM-09, MEM-11, MEM-20 |
| https://support.ezfacility.com/hc/en-us/articles/4402426353691-How-to-View-Billing-History-for-Invoices-and-Items | read (archive snapshot 2025-08-08) | BIL-01, BIL-09 |
| https://support.ezfacility.com/hc/en-us/articles/4402426355099-How-to-Void-a-Payment | read (archive snapshot 2025-08-14) | PAY-03, PAY-04 |
| https://support.ezfacility.com/hc/en-us/articles/4402426433819-How-to-Set-Up-Taxes-For-Your-Account | read (archive snapshot 2025-10-11) | BIL-12 |
| https://support.ezfacility.com/hc/en-us/articles/4402426434587-How-to-Set-Up-Revenue-Categories | read (archive snapshot 2025-08-14) | BIL-13 |
| https://support.ezfacility.com/hc/en-us/articles/4402426435739-How-to-Set-Up-a-Payment-Schedule | read (archive snapshot 2025-08-04) | BIL-06 |
| https://support.ezfacility.com/hc/en-us/articles/4402426437275-Generating-a-Document-from-a-Client-s-Account | read (archive snapshot 2025-08-08) | DOC-02, DOC-05 |
| https://support.ezfacility.com/hc/en-us/articles/4402426438299-How-to-Set-Up-Client-Categories | read (archive snapshot 2025-10-08) | CLI-06 |
| https://support.ezfacility.com/hc/en-us/articles/4402427133851-Self-Service-How-to-invite-existing-contacts | read (archive snapshot 2025-08-04) | SSP-06 |
| https://support.ezfacility.com/hc/en-us/articles/4402427173019-Using-the-Self-Service-Video-Library | read (archive snapshot 2025-10-08) | SSP-16 |
| https://support.ezfacility.com/hc/en-us/articles/4402427175195-How-to-Set-Up-Self-Service-Design | read (archive snapshot 2025-10-08) | SSP-14 |
| https://support.ezfacility.com/hc/en-us/articles/4402427176219-How-to-Set-Up-Self-Service-Preferences | read (archive snapshot 2025-08-06) | APP-18, MKT-14, SSP-01, SSP-02, SSP-04, SSP-05, SSP-07, SSP-08, SSP-10, SSP-11, SSP-12, SSP-13, SSP-15 |
| https://support.ezfacility.com/hc/en-us/articles/4402427177115-How-to-Set-Up-Contact-Preferences | read (archive snapshot 2025-08-14) | CLI-04, CLI-05 |
| https://support.ezfacility.com/hc/en-us/articles/4402427178395-How-to-Change-a-User-Password | read (archive snapshot 2025-10-08) | PLT-03 |
| https://support.ezfacility.com/hc/en-us/articles/4402427179419-Adding-a-Role-to-a-User | read (archive snapshot 2025-08-04) | PLT-05 |
| https://support.ezfacility.com/hc/en-us/articles/4402427180315-Creating-A-New-User | read (archive snapshot 2025-08-09) | PLT-02 |
| https://support.ezfacility.com/hc/en-us/articles/4402427184283-How-to-Unsuspend-a-Membership | read (archive snapshot 2025-10-08) | MEM-14 |
| https://support.ezfacility.com/hc/en-us/articles/4402427195163-Defaulting-New-Membership-Contracts-To-Auto-Pay-In-Self-Service | read (archive snapshot 2025-10-08) | BIL-17 |
| https://support.ezfacility.com/hc/en-us/articles/4402427196571-How-to-Prorate-Membership-Plans | read (archive snapshot 2025-08-04) | MEM-03 |
| https://support.ezfacility.com/hc/en-us/articles/4402427197467-How-to-Edit-Membership-Plans | read (archive snapshot 2025-10-08) | MEM-02 |
| https://support.ezfacility.com/hc/en-us/articles/4402427203355-How-to-Set-Up-Reservation-Types | read (archive snapshot 2025-08-04) | CLS-05, SCH-02, SCH-03, SCH-04 |
| https://support.ezfacility.com/hc/en-us/articles/4402427204379-Setting-Up-Package-Plans-Single-Session | read (archive snapshot 2025-10-08) | PKG-01 |
| https://support.ezfacility.com/hc/en-us/articles/4402427205147-Setting-Up-a-Multiple-Session-Package-Plan | read (archive snapshot 2025-08-14) | PKG-01 |
| https://support.ezfacility.com/hc/en-us/articles/4402427206683-Setting-Up-an-Unlimited-Package-Plan | read (archive snapshot 2025-10-08) | PKG-01 |
| https://support.ezfacility.com/hc/en-us/articles/4402427209115-Registering-A-Client-Into-a-Single-Available-Session | read (archive snapshot 2025-08-14) | CLS-01, CLS-03, SCH-06 |
| https://support.ezfacility.com/hc/en-us/articles/4402427211163-Adding-or-Editing-a-Trainer | read (archive snapshot 2025-10-11) | STF-01, STF-02, STF-03, STF-04 |
| https://support.ezfacility.com/hc/en-us/articles/4402427212571-How-to-Mark-Package-Plans-as-Sold-Online | read (archive snapshot 2025-08-14) | SSP-08 |
| https://support.ezfacility.com/hc/en-us/articles/4402427214107-Setting-Up-a-Recurring-Package-Plans | read (archive snapshot 2025-08-08) | PKG-03, PKG-04 |
| https://support.ezfacility.com/hc/en-us/articles/4402433754267-How-to-Reverse-the-Billing-of-an-Item | read (archive snapshot 2025-10-11) | BIL-01, BIL-07 |
| https://support.ezfacility.com/hc/en-us/articles/4402433754907-How-to-Reverse-the-Billing-of-an-Item-on-an-Invoice | read (archive snapshot 2025-08-14) | BIL-07 |
| https://support.ezfacility.com/hc/en-us/articles/4402433807515-How-to-Void-an-Invoice | read (archive snapshot 2025-08-04) | BIL-04, BIL-08 |
| https://support.ezfacility.com/hc/en-us/articles/4402433808155-How-to-Set-Up-Payment-Options | read (archive snapshot 2025-08-09) | BIL-16, PAY-02, PAY-06 |
| https://support.ezfacility.com/hc/en-us/articles/4402433808923-How-to-Take-a-Payment | read (archive snapshot 2025-10-11) | BIL-21, PAY-01 |
| https://support.ezfacility.com/hc/en-us/articles/4402434184475-How-to-Set-Up-Required-Fields-for-Self-Service-Registration | read (archive snapshot 2025-08-04) | CLI-04 |
| https://support.ezfacility.com/hc/en-us/articles/4402434185883-How-to-Create-a-Video-Library-for-Customers | read (archive snapshot 2025-08-14) | SSP-16 |
| https://support.ezfacility.com/hc/en-us/articles/4402434188187-Creating-a-Custom-User-Role | read (archive snapshot 2025-08-06) | PLT-04 |
| https://support.ezfacility.com/hc/en-us/articles/4402434192027-How-to-Set-Up-Your-New-Account | read (archive snapshot 2025-10-08) | IMP-04, ONB-01, PLT-02, PLT-04, PLT-05, PLT-08, PLT-16, RES-01, RES-02, RES-03, RES-04 |
| https://support.ezfacility.com/hc/en-us/articles/4402434194715-How-to-Suspend-a-Membership | read (archive snapshot 2025-08-14) | MEM-11, MEM-14 |
| https://support.ezfacility.com/hc/en-us/articles/4402434197147-How-to-use-the-Staff-Check-in-Window | read (archive snapshot 2025-08-04) | CHK-01, CHK-14 |
| https://support.ezfacility.com/hc/en-us/articles/4402434198555-How-to-Cancel-a-Membership | read (archive snapshot 2025-10-11) | MEM-15, MEM-16 |
| https://support.ezfacility.com/hc/en-us/articles/4402434204955-How-to-Sell-a-Package-on-the-admin-side | read (archive snapshot 2025-10-08) | PKG-07 |
| https://support.ezfacility.com/hc/en-us/articles/4402434205851-Setting-up-a-Free-Package-Plan | read (archive snapshot 2025-08-08) | PKG-02 |
| https://support.ezfacility.com/hc/en-us/articles/4403485771547-How-to-Set-Up-Revenue-Categories-in-EZFacility-Classic | read (archive snapshot 2025-08-14) | BIL-13 |
| https://support.ezfacility.com/hc/en-us/articles/4403485782811-How-to-Set-Up-Taxes-for-your-Account-in-EZFacility-Classic | read (archive snapshot 2025-10-11) | BIL-12 |
| https://support.ezfacility.com/hc/en-us/articles/4403485806363-How-to-Apply-a-Payment-in-EZFacility-Classic | read (archive snapshot 2025-08-04) | BIL-21, PAY-01 |
| https://support.ezfacility.com/hc/en-us/articles/4403486096667-How-to-Refund-Payments-Full-Partial-in-EZFacility-Classic | read (archive snapshot 2025-08-14) | PAY-03, PAY-05, PAY-11 |
| https://support.ezfacility.com/hc/en-us/articles/4403486115483-How-to-Set-Up-a-Payment-Schedule-on-an-Invoice-in-EZFacility-Classic | read (archive snapshot 2025-10-11) | BIL-06 |
| https://support.ezfacility.com/hc/en-us/articles/4403486128283-How-to-Add-Items-to-the-Shopping-Cart-in-EZFacility-Classic | read (archive snapshot 2025-08-14) | BIL-03, BIL-08 |
| https://support.ezfacility.com/hc/en-us/articles/4403486152219-Using-the-Revenue-Report-in-EZFacility | read (archive snapshot 2025-08-14) | RPT-03 |
| https://support.ezfacility.com/hc/en-us/articles/4403486157595-Management-Dashboard | read (archive snapshot 2025-08-04) | RPT-02 |
| https://support.ezfacility.com/hc/en-us/articles/4403486169115-Accrued-Session-Revenue | read (archive snapshot 2025-10-11) | RPT-10 |
| https://support.ezfacility.com/hc/en-us/articles/4403486188571-Deposits-Report | read (archive snapshot 2025-10-08) | RPT-04 |
| https://support.ezfacility.com/hc/en-us/articles/4403486203035-Unapplied-Payments-by-Customer | read (archive snapshot 2025-08-04) | RPT-07 |
| https://support.ezfacility.com/hc/en-us/articles/4403486237979-Income-Balances-by-Customer | read (archive snapshot 2025-08-14) | RPT-08 |
| https://support.ezfacility.com/hc/en-us/articles/4403486256923-Invoices-Report | read (archive snapshot 2025-08-14) | RPT-05 |
| https://support.ezfacility.com/hc/en-us/articles/4403486264219-Trainer-Payroll-Commission-Report | read (archive snapshot 2025-08-04) | STF-09 |
| https://support.ezfacility.com/hc/en-us/articles/4403486270875-Collections | read (archive snapshot 2025-08-04) | BIL-20 |
| https://support.ezfacility.com/hc/en-us/articles/4403486278939-Underpaid-Items | read (archive snapshot 2025-08-14) | RPT-09 |
| https://support.ezfacility.com/hc/en-us/articles/4403486300315-Open-Invoices-By-Customer-Report | read (archive snapshot 2025-10-08) | RPT-06 |
| https://support.ezfacility.com/hc/en-us/articles/4403486305051-Deferred-Membership-Revenue-Report | read (archive snapshot 2025-10-11) | MEM-21 |
| https://support.ezfacility.com/hc/en-us/articles/4403486971675-How-To-Set-Facility-Hours-in-EZFacility-Classic | read (archive snapshot 2025-08-14) | RES-02 |
| https://support.ezfacility.com/hc/en-us/articles/4403486979739-Adding-or-Editing-a-Trainer-in-EZFacility-Classic | read (archive snapshot 2025-10-06) | STF-01, STF-02, STF-03, STF-04 |
| https://support.ezfacility.com/hc/en-us/articles/4403486981915-Adding-or-Editing-a-Salesperson-in-EZFacility-Classic | read (archive snapshot 2025-10-06) | STF-05 |
| https://support.ezfacility.com/hc/en-us/articles/4403486986011-Uploading-Your-Logo | read (archive snapshot 2025-08-04) | PLT-08 |
| https://support.ezfacility.com/hc/en-us/articles/4403486989083-Uploading-Your-Vanity-Logo | read (archive snapshot 2025-08-14) | PLT-08 |
| https://support.ezfacility.com/hc/en-us/articles/4403486991515-Failed-Transaction-Email | read (archive snapshot 2025-08-08) | PAY-08 |
| https://support.ezfacility.com/hc/en-us/articles/4403493305499-How-to-Void-a-Payment-in-EZFacility-Classic | read (archive snapshot 2025-10-11) | PAY-04 |
| https://support.ezfacility.com/hc/en-us/articles/4403493306779-How-to-Reverse-the-Billing-of-an-Item-on-an-Invoice-in-EZFacility-Classic | read (archive snapshot 2025-10-11) | BIL-07 |
| https://support.ezfacility.com/hc/en-us/articles/4403493317275-How-to-Void-an-Invoice-in-EZFacility-Classic | read (archive snapshot 2025-08-14) | BIL-08 |
| https://support.ezfacility.com/hc/en-us/articles/4403493319195-How-to-View-Billing-History-for-Invoices-and-Items-in-EZFacility-Classic | read (archive snapshot 2025-08-04) | BIL-01, BIL-09 |
| https://support.ezfacility.com/hc/en-us/articles/4403493341083-How-to-Add-Items-to-Invoices-in-the-Shopping-Cart-in-EZFacility-Classic | read (archive snapshot 2025-06-21) | BIL-02, BIL-03 |
| https://support.ezfacility.com/hc/en-us/articles/4403493392539-Expired-Expiring-Credit-Cards | read (archive snapshot 2025-08-04) | PAY-07 |
| https://support.ezfacility.com/hc/en-us/articles/4403493405851-Accounts-Receivable | read (archive snapshot 2025-10-08) | BIL-19, BIL-20, PAY-08, PAY-09 |
| https://support.ezfacility.com/hc/en-us/articles/4403493414683-Salesperson-Commission-Report | read (archive snapshot 2025-08-08) | STF-05, STF-10 |
| https://support.ezfacility.com/hc/en-us/articles/4403493437211-Direct-Debit-Failures | read (archive snapshot 2025-08-06) | PAY-10 |
| https://support.ezfacility.com/hc/en-us/articles/4403493443355-All-Sales-By-Coupon-Report | read (archive snapshot 2025-08-14) | POS-11 |
| https://support.ezfacility.com/hc/en-us/articles/4403493447707-Package-Sales | read (archive snapshot 2025-10-11) | PKG-15 |
| https://support.ezfacility.com/hc/en-us/articles/4403493938843-Adding-or-Editing-a-Venue-in-EZFacility-Classic | read (archive snapshot 2025-10-11) | RES-03, RES-04, RES-06 |
| https://support.ezfacility.com/hc/en-us/articles/4404305376795-How-to-Set-Up-the-Check-In-Dashboard-in-EZFacility-Classic | read (archive snapshot 2025-08-04) | CHK-07 |
| https://support.ezfacility.com/hc/en-us/articles/4404305442587-Submitting-a-Client-Data-Import-in-EZFacility-Classic | read (archive snapshot 2025-10-08) | IMP-01, IMP-02, ONB-03 |
| https://support.ezfacility.com/hc/en-us/articles/4404305577755-How-to-Set-Up-Self-Service-Preferences-in-EZFacility-Classic | read (archive snapshot 2025-10-08) | APP-01, MKT-14, SSP-01, SSP-02, SSP-03, SSP-04, SSP-05, SSP-07, SSP-08, SSP-10, SSP-11, SSP-12, SSP-15, STF-12 |
| https://support.ezfacility.com/hc/en-us/articles/4404305580443-Online-Webinar-Self-Service-Set-up-in-EZFacility-Classic | read (archive snapshot 2025-10-08) | SSP-14 |
| https://support.ezfacility.com/hc/en-us/articles/4404305590683-How-to-Set-up-the-Self-Service-Video-Library-in-EZFacility-Classic | read (archive snapshot 2025-08-08) | SSP-16 |
| https://support.ezfacility.com/hc/en-us/articles/4404305593243-How-to-Add-Social-Media-Links-to-Self-Service-in-EZFacility-Classic | read (archive snapshot 2025-10-08) | SSP-15 |
| https://support.ezfacility.com/hc/en-us/articles/4404305596827-How-to-Configure-Available-Tabs-in-the-Self-Service-Menu-using-EZFacility-Classic | read (archive snapshot 2025-10-11) | SSP-04, SSP-13 |
| https://support.ezfacility.com/hc/en-us/articles/4404305610651-Managing-Self-Service-Shared-Bookings-in-EZFacility-Classic | read (archive snapshot 2025-10-08) | SCH-03, SCH-17 |
| https://support.ezfacility.com/hc/en-us/articles/4404305628059-Online-Webinar-Self-Service-Video-Library-Zoom-in-EZFacility-Classic | read (archive snapshot 2025-08-14) | ONB-02 |
| https://support.ezfacility.com/hc/en-us/articles/4404305630619-Online-Webinar-Learn-about-the-MM-App-the-Self-Service-Portal-in-EZFacility-Classic | read (archive snapshot 2025-10-11) | excluded (no product capability) |
| https://support.ezfacility.com/hc/en-us/articles/4404305637275-Online-Webinar-Using-Self-Service-in-EZFacility-Classic | read (archive snapshot 2025-08-04) | ONB-02 |
| https://support.ezfacility.com/hc/en-us/articles/4404305716251-Creating-and-Editing-Document-Templates-in-EZFacility-Classic | read (archive snapshot 2025-10-11) | DOC-01 |
| https://support.ezfacility.com/hc/en-us/articles/4404308093211-Selling-an-Advanced-Membership-Contract-in-EZFacility-Classic | read (archive snapshot 2025-10-08) | MEM-05, MEM-07, MEM-11, MEM-20 |
| https://support.ezfacility.com/hc/en-us/articles/4404308183707-Canceling-a-Membership-in-EZFacility-Classic | read (archive snapshot 2025-10-11) | MEM-05, MEM-15 |
| https://support.ezfacility.com/hc/en-us/articles/4404308188315-Sharing-a-Membership-in-EZFacility-Classic | read (archive snapshot 2025-06-21) | MEM-17 |
| https://support.ezfacility.com/hc/en-us/articles/4404308193435-Removing-a-Freeze-in-EZFacility-Classic | read (archive snapshot 2025-10-08) | MEM-13 |
| https://support.ezfacility.com/hc/en-us/articles/4404308201243-Membership-Actions | read (archive snapshot 2025-10-08) | RPT-13 |
| https://support.ezfacility.com/hc/en-us/articles/4404308202907-View-the-Low-Usage-Check-In-Report-in-EZFacility-Classic | read (archive snapshot 2025-08-14) | CHK-20, RPT-17 |
| https://support.ezfacility.com/hc/en-us/articles/4404308209819-Membership-By-Status-Report-in-EZFacility-Classic | read (archive snapshot 2025-08-04) | RPT-12 |
| https://support.ezfacility.com/hc/en-us/articles/4404308366619-Membership-Attrition-Report-in-EZFacility-Classic | read (archive snapshot 2025-10-11) | RPT-14 |
| https://support.ezfacility.com/hc/en-us/articles/4404308369179-Viewing-Membership-Revenue-by-Month-Report-in-EZFacility-Classic | read (archive snapshot 2025-08-08) | RPT-11 |
| https://support.ezfacility.com/hc/en-us/articles/4404308371995-Viewing-A-Membership-Contract-Agreement-in-EZFacility-Classic | read (archive snapshot 2025-08-14) | DOC-11 |
| https://support.ezfacility.com/hc/en-us/articles/4404308377243-Canceling-a-Membership-with-a-Refund-in-EZFacility-Classic | read (archive snapshot 2025-08-04) | MEM-04, MEM-05, MEM-10, MEM-15, MEM-16, PKG-13 |
| https://support.ezfacility.com/hc/en-us/articles/4404308380827-How-to-Edit-or-Add-an-End-Date-for-a-Membership-Freeze-in-EZFacility-Classic | read (archive snapshot 2025-08-04) | MEM-13 |
| https://support.ezfacility.com/hc/en-us/articles/4404308386075-Assessment-Summary-Report | read (archive snapshot 2025-10-08) | FIT-04 |
| https://support.ezfacility.com/hc/en-us/articles/4404308390811-Check-In-Summary-Report | read (archive snapshot 2025-10-08) | CHK-20 |
| https://support.ezfacility.com/hc/en-us/articles/4404308405531-How-to-Sell-a-Package-in-EZFacility-Classic | read (archive snapshot 2025-08-04) | PKG-07 |
| https://support.ezfacility.com/hc/en-us/articles/4404308407579-How-to-Sell-Package-Plans-Online-in-EZFacility-Classic | read (archive snapshot 2025-10-08) | PKG-09 |
| https://support.ezfacility.com/hc/en-us/articles/4404308415899-How-to-Share-Packages-Automatically-in-EZFacility-Classic | read (archive snapshot 2025-08-04) | PKG-01, PKG-06, PKG-09 |
| https://support.ezfacility.com/hc/en-us/articles/4404308418843-How-to-Share-a-Package-Post-Sale-in-EZFacility-Classic | read (archive snapshot 2025-08-14) | PKG-06, PKG-14 |
| https://support.ezfacility.com/hc/en-us/articles/4404308492315-Setting-Up-Your-Assessment-Categories | read (archive snapshot 2025-08-14) | FIT-01, FIT-02, FIT-03 |
| https://support.ezfacility.com/hc/en-us/articles/4404308503195-How-to-Schedule-a-Rental-Reservation-in-EZFacility-Classic | read (archive snapshot 2025-10-08) | RNT-03, RNT-13, SCH-06, SCH-09, SCH-13 |
| https://support.ezfacility.com/hc/en-us/articles/4404308527131-Unused-Session-Value | read (archive snapshot 2025-10-08) | RPT-22 |
| https://support.ezfacility.com/hc/en-us/articles/4404308531099-Non-training-Clients | read (archive snapshot 2025-10-08) | RPT-26 |
| https://support.ezfacility.com/hc/en-us/articles/4404308533019-Client-Package-Summary | read (archive snapshot 2025-06-21) | RPT-23 |
| https://support.ezfacility.com/hc/en-us/articles/4404308535707-Client-Referrals | read (archive snapshot 2025-10-08) | RPT-20 |
| https://support.ezfacility.com/hc/en-us/articles/4404308543515-Client-Demographics | read (archive snapshot 2025-08-14) | RPT-19 |
| https://support.ezfacility.com/hc/en-us/articles/4404308546459-Contact-Report | read (archive snapshot 2025-08-14) | RPT-19 |
| https://support.ezfacility.com/hc/en-us/articles/4404308549787-Attendance-Report | read (archive snapshot 2025-08-04) | RPT-21 |
| https://support.ezfacility.com/hc/en-us/articles/4404308559771-Trial-Conversions | read (archive snapshot 2025-10-08) | RPT-24 |
| https://support.ezfacility.com/hc/en-us/articles/4404308570011-Attendance-Overview-Report | read (archive snapshot 2025-10-08) | RPT-21 |
| https://support.ezfacility.com/hc/en-us/articles/4404308572827-Expiring-Packages | read (archive snapshot 2025-08-04) | RPT-23 |
| https://support.ezfacility.com/hc/en-us/articles/4404308575643-Client-Retention-Report | read (archive snapshot 2025-08-14) | RPT-25 |
| https://support.ezfacility.com/hc/en-us/articles/4404308586011-How-to-Set-Up-Client-Categories-in-EZFacility-Classic | read (archive snapshot 2025-08-14) | CLI-06 |
| https://support.ezfacility.com/hc/en-us/articles/4404308588571-Why-Create-Client-Categories-in-EZFacility-Classic | read (archive snapshot 2025-08-08) | CLI-06 |
| https://support.ezfacility.com/hc/en-us/articles/4404308609179-Generating-a-Document-with-Digital-Acceptance-in-EZFacility-Classic | read (archive snapshot 2025-08-04) | CLI-02, DOC-02, DOC-03 |
| https://support.ezfacility.com/hc/en-us/articles/4404308612891-Generating-a-Document-with-Acceptance-by-Email-in-EZFacility-Classic | read (archive snapshot 2025-08-14) | DOC-04 |
| https://support.ezfacility.com/hc/en-us/articles/4404308614811-How-to-View-Document-History-in-EZFacility-Classic | read (archive snapshot 2025-10-11) | DOC-06 |
| https://support.ezfacility.com/hc/en-us/articles/4404308617115-Using-Client-Audit-with-Documents | read (archive snapshot 2025-10-08) | DOC-07 |
| https://support.ezfacility.com/hc/en-us/articles/4404311237659-How-to-Assign-Custom-Colors-to-Reservation-Types | read (archive snapshot 2025-08-04) | SCH-06 |
| https://support.ezfacility.com/hc/en-us/articles/4404311241627-Online-Webinar-Scheduling-in-EZFacility-Classic-Series-Parts-1-3 | read (archive snapshot 2025-10-11) | ONB-02 |
| https://support.ezfacility.com/hc/en-us/articles/4404311244187-Advanced-Multi-Scheduling-in-EZFacility-Classic | read (archive snapshot 2025-08-14) | RES-05 |
| https://support.ezfacility.com/hc/en-us/articles/4404311249435-Multi-Scheduling-a-Trainer-and-a-Venue-for-a-Single-Reservation-in-EZFacility-Classic | read (archive snapshot 2025-08-06) | RES-05 |
| https://support.ezfacility.com/hc/en-us/articles/4404311260571-How-to-Schedule-an-Available-Session-in-EZFacility-Classic | read (archive snapshot 2025-05-25) | CLS-01, CLS-09, SCH-07, SCH-18 |
| https://support.ezfacility.com/hc/en-us/articles/4404311270683-Scheduling-a-Special-Reservation-in-EZFacility-Classic | read (archive snapshot 2025-10-11) | RNT-05, SCH-08, SCH-18 |
| https://support.ezfacility.com/hc/en-us/articles/4404311272731-How-to-Edit-a-Reservation-in-EZFacility-Classic | read (archive snapshot 2025-10-08) | SCH-10 |
| https://support.ezfacility.com/hc/en-us/articles/4404311276699-How-to-Register-a-Client-into-an-Available-Session-in-EZFacility-Classic | read (archive snapshot 2025-08-14) | PKG-07, PKG-12 |
| https://support.ezfacility.com/hc/en-us/articles/4404311287451-Deleting-Reservations-using-Delete-Mode-in-EZFacility-Classic | read (archive snapshot 2025-10-08) | RNT-08, SCH-11 |
| https://support.ezfacility.com/hc/en-us/articles/4404311308571-How-to-Create-Recurring-Sessions-in-EZFacility-Classic | read (archive snapshot 2025-08-14) | SCH-09 |
| https://support.ezfacility.com/hc/en-us/articles/4404311317403-Online-Webinar-Introducing-Self-Check-In-Advanced-Multi-Scheduling | read (archive snapshot 2025-08-04) | CHK-05, CHK-21, RES-05 |
| https://support.ezfacility.com/hc/en-us/articles/4404311321115-Online-Webinar-Trainers-and-Scheduling-in-EZFacility-Classic | read (archive snapshot 2025-08-04) | ONB-02 |
| https://support.ezfacility.com/hc/en-us/articles/4404311324443-How-to-Edit-Class-Sizes-in-EZFacility-Classic | read (archive snapshot 2025-10-08) | CLS-04, SCH-10 |
| https://support.ezfacility.com/hc/en-us/articles/4404311326875-How-to-Delete-Reservations-Delete-Mode-in-EZFacility-Classic | read (archive snapshot 2025-10-11) | SCH-11 |
| https://support.ezfacility.com/hc/en-us/articles/4404311517339-Syncing-your-EZFacility-Classic-Calendar-to-an-External-Calendar | read (archive snapshot 2025-08-04) | INT-08 |
| https://support.ezfacility.com/hc/en-us/articles/4404311542427-Syncing-your-EZFacility-Calendar-to-your-iOS-iPod-iPad-and-iPhone-Calendar | read (archive snapshot 2025-08-14) | INT-08 |
| https://support.ezfacility.com/hc/en-us/articles/4404311548059-Syncing-your-EZFacility-Calendar-to-your-Outlook-Calendar | read (archive snapshot 2025-08-04) | INT-08 |
| https://support.ezfacility.com/hc/en-us/articles/4404311551899-Syncing-your-EZFacility-Calendar-to-your-Google-Android-device-Calendar | read (archive snapshot 2025-10-08) | INT-08 |
| https://support.ezfacility.com/hc/en-us/articles/4404311560475-EZLeagues-Team-Schedule-Calendar-Sync-Google-Calendar | read (archive snapshot 2025-10-11) | LGE-25 |
| https://support.ezfacility.com/hc/en-us/articles/4404312815771-Setting-Up-a-Self-Service-Registration-Redirect-in-EZFacility-Classic | read (archive snapshot 2025-10-08) | SSP-07 |
| https://support.ezfacility.com/hc/en-us/articles/4404312817947-How-to-Create-a-Video-Library-for-Customers-in-EZFacility-Classic | read (archive snapshot 2025-04-27) | SSP-16 |
| https://support.ezfacility.com/hc/en-us/articles/4404312819483-How-To-Select-the-Self-Service-Landing-Page-in-EZFacility-Classic | read (archive snapshot 2025-08-06) | SSP-01, SSP-17 |
| https://support.ezfacility.com/hc/en-us/articles/4404312820763-How-to-Share-a-Link-to-a-Specific-Video-in-the-EZFacility-Classic-Video-Library | read (archive snapshot 2025-08-14) | SSP-16 |
| https://support.ezfacility.com/hc/en-us/articles/4404312822811-Online-Webinar-How-to-Set-Up-Online-Rentals-in-EZFacility-Classic | read (archive snapshot 2025-10-08) | RNT-05 |
| https://support.ezfacility.com/hc/en-us/articles/4404312828059-Online-Webinar-Self-Service-in-EZFacility-Classic-Open-Training-Series-Parts-1-2 | read (archive snapshot 2025-08-14) | ONB-02 |
| https://support.ezfacility.com/hc/en-us/articles/4404312856731-Using-Client-Audit-with-Documents | read (archive snapshot 2025-08-14) | DOC-07 |
| https://support.ezfacility.com/hc/en-us/articles/4404312896283-Online-Webinar-Billing-in-EZFacility-Classic-Series-Parts-1-3 | read (archive snapshot 2025-08-04) | ONB-02 |
| https://support.ezfacility.com/hc/en-us/articles/4404314514587-Unsuspending-a-Membership-in-EZFacility-Classic | read (archive snapshot 2025-08-14) | MEM-14 |
| https://support.ezfacility.com/hc/en-us/articles/4404314520475-Freezing-a-Membership-in-EZFacility-Classic | read (archive snapshot 2025-08-06) | MEM-05, MEM-12 |
| https://support.ezfacility.com/hc/en-us/articles/4404314524571-Suspending-a-Membership-in-EZFacility-Classic | read (archive snapshot 2025-08-04) | MEM-14 |
| https://support.ezfacility.com/hc/en-us/articles/4404314530331-Client-Activity-Items-Report | read (archive snapshot 2025-10-08) | RPT-18 |
| https://support.ezfacility.com/hc/en-us/articles/4404314535195-View-the-Expiring-Memberships-Report-in-EZFacility-Classic | read (archive snapshot 2025-08-04) | RPT-15 |
| https://support.ezfacility.com/hc/en-us/articles/4404314692507-Using-the-Membership-Referral-Report-in-EZFacility-Classic | read (archive snapshot 2025-08-14) | RPT-16 |
| https://support.ezfacility.com/hc/en-us/articles/4404314743067-Managing-Self-Service-Shared-Bookings-in-EZFacility-Classic | read (archive snapshot 2025-08-06) | SSP-03, SSP-09 |
| https://support.ezfacility.com/hc/en-us/articles/4404314764827-How-to-Invite-Your-Clients-to-Use-Self-Service | read (archive snapshot 2025-10-08) | SSP-06 |
| https://support.ezfacility.com/hc/en-us/articles/4404314819483-Adding-an-Assessment-in-EZFacility-Classic | read (archive snapshot 2025-10-06) | FIT-02, FIT-03 |
| https://support.ezfacility.com/hc/en-us/articles/4404314830107-Online-Webinar-Rentals-in-EZFacility-Classic | read (archive snapshot 2025-08-14) | ONB-02 |
| https://support.ezfacility.com/hc/en-us/articles/4404314851355-Renewal-Candidates | read (archive snapshot 2025-10-11) | RPT-23 |
| https://support.ezfacility.com/hc/en-us/articles/4404314883483-Group-Waitlists | read (archive snapshot 2025-10-08) | RPT-28 |
| https://support.ezfacility.com/hc/en-us/articles/4404314929051-Generating-a-Document-from-a-Client-s-Account-in-EZFacility-Classic | read (archive snapshot 2025-10-11) | DOC-02, DOC-06 |
| https://support.ezfacility.com/hc/en-us/articles/4404314931483-Generating-a-Document-to-Print-Paper-Acceptance-in-EZFacility-Classic | read (archive snapshot 2025-10-08) | DOC-05 |
| https://support.ezfacility.com/hc/en-us/articles/4404321359515-EZLeagues-Team-Schedule-Calendar-Sync-IPad-and-IPhone | read (archive snapshot 2025-08-14) | LGE-25 |
| https://support.ezfacility.com/hc/en-us/articles/4404924758427-How-to-Hide-Expand-Group-Details-Group-Members-or-Sub-Groups | read (archive snapshot 2025-08-04) | REG-06 |
| https://support.ezfacility.com/hc/en-us/articles/4404924765339-How-to-Generate-a-Report-for-Groups | read (archive snapshot 2025-08-06) | RPT-27 |
| https://support.ezfacility.com/hc/en-us/articles/4404924790939-How-to-Move-a-Client-Between-Groups-Sub-Groups | read (archive snapshot 2025-10-08) | REG-08 |
| https://support.ezfacility.com/hc/en-us/articles/4404924800539-How-to-Undelete-a-Deleted-Group | read (archive snapshot 2025-06-21) | REG-05 |
| https://support.ezfacility.com/hc/en-us/articles/4404931863963-How-to-Move-a-Sub-Group-Between-Groups | read (archive snapshot 2025-08-06) | REG-02 |
| https://support.ezfacility.com/hc/en-us/articles/4404931875227-How-to-Find-Search-Groups | read (archive snapshot 2025-08-14) | REG-04, REG-05 |
| https://support.ezfacility.com/hc/en-us/articles/4404931880219-How-to-Remove-Client-from-Waitlist | read (archive snapshot 2025-10-11) | REG-09 |
| https://support.ezfacility.com/hc/en-us/articles/4404931886235-How-to-Send-an-Email-Campaign-to-Groups | read (archive snapshot 2025-08-14) | MKT-11 |
| https://support.ezfacility.com/hc/en-us/articles/4404931898779-How-to-Set-Up-Group-Categories | read (archive snapshot 2025-10-08) | REG-03 |
| https://support.ezfacility.com/hc/en-us/articles/4404931922843-How-to-Hide-Expand-Side-Bar-Menu | read (archive snapshot 2025-08-08) | PLT-10 |
| https://support.ezfacility.com/hc/en-us/articles/4404931926939-How-to-Email-Group-Subgroup-Registrants | read (archive snapshot 2025-10-11) | MKT-11 |
| https://support.ezfacility.com/hc/en-us/articles/4404931932955-How-to-Drag-and-Drop-Group-Details | read (archive snapshot 2025-08-04) | REG-06 |
| https://support.ezfacility.com/hc/en-us/articles/4404931935259-How-to-Reorder-Columns-in-your-Groups-Subgroups | read (archive snapshot 2025-08-04) | REG-06 |
| https://support.ezfacility.com/hc/en-us/articles/4405044141723-Online-Webinar-Power-Your-SMS-Communication-with-EZMessaging | read (archive snapshot 2025-10-08) | MKT-15 |
| https://support.ezfacility.com/hc/en-us/articles/4405044143899-Online-Webinar-CoachMePlus | read (archive snapshot 2025-08-14) | INT-12 |
| https://support.ezfacility.com/hc/en-us/articles/4405044160795-Online-Webinar-SmartWaiver-Integration | read (archive snapshot 2025-10-11) | DOC-13 |
| https://support.ezfacility.com/hc/en-us/articles/4405044167835-EZFacility-Open-Webinar-QuickBooks-Online-Integration | read (archive snapshot 2025-10-11) | INT-07 |
| https://support.ezfacility.com/hc/en-us/articles/4405044226587-How-to-Publish-a-Group-to-EZLeagues-from-EZFacility | read (archive snapshot 2025-08-04) | LGE-02, LGE-13, LGE-26, REG-14 |
| https://support.ezfacility.com/hc/en-us/articles/4405044258075-Online-Webinar-EZLeagues-Scheduling-Wizard | read (archive snapshot 2025-08-06) | ONB-02 |
| https://support.ezfacility.com/hc/en-us/articles/4405044263835-How-to-Print-Manual-Game-Cards | read (archive snapshot 2025-08-14) | RPT-36 |
| https://support.ezfacility.com/hc/en-us/articles/4405044293147-How-to-Print-Multiple-Game-Cards | read (archive snapshot 2025-10-08) | RPT-36 |
| https://support.ezfacility.com/hc/en-us/articles/4405044295707-How-to-Manage-Scores | read (archive snapshot 2025-10-08) | LGE-14 |
| https://support.ezfacility.com/hc/en-us/articles/4405044308251-How-to-Manage-your-Classes-Clinics | read (archive snapshot 2025-10-08) | CLS-07 |
| https://support.ezfacility.com/hc/en-us/articles/4405044313371-How-to-Manage-your-Sports | read (archive snapshot 2025-10-11) | LGE-05, LGE-06, LGE-07 |
| https://support.ezfacility.com/hc/en-us/articles/4405044321307-How-to-Add-Officials | read (archive snapshot 2025-10-11) | LGE-15 |
| https://support.ezfacility.com/hc/en-us/articles/4405044330523-How-to-Filter-your-Leagues-and-Tournaments | read (archive snapshot 2025-08-06) | LGE-17 |
| https://support.ezfacility.com/hc/en-us/articles/4405044343451-How-to-Add-Players | read (archive snapshot 2025-08-04) | LGE-04 |
| https://support.ezfacility.com/hc/en-us/articles/4405044351259-How-to-Utilize-the-TV-Display | read (archive snapshot 2025-08-14) | LGE-24 |
| https://support.ezfacility.com/hc/en-us/articles/4405044353435-How-to-Create-a-User-Account | read (archive snapshot 2025-10-11) | PLT-11, PLT-14 |
| https://support.ezfacility.com/hc/en-us/articles/4405044358811-How-to-Upload-your-Facility-Banner | read (archive snapshot 2025-10-08) | LGE-19 |
| https://support.ezfacility.com/hc/en-us/articles/4405044362651-How-to-Add-and-Manage-Links | read (archive snapshot 2025-08-09) | LGE-20 |
| https://support.ezfacility.com/hc/en-us/articles/4405044372123-How-to-Manage-your-Classifieds | read (archive snapshot 2025-10-08) | LGE-22 |
| https://support.ezfacility.com/hc/en-us/articles/4405044374171-How-to-Configure-your-Site-Options | read (archive snapshot 2025-10-11) | LGE-19 |
| https://support.ezfacility.com/hc/en-us/articles/4405044379547-How-to-Add-Update-your-Facility-Information | read (archive snapshot 2025-08-14) | LGE-19 |
| https://support.ezfacility.com/hc/en-us/articles/4405044381211-How-to-Add-News-Articles-on-the-Public-Website | read (archive snapshot 2025-06-21) | MKT-18 |
| https://support.ezfacility.com/hc/en-us/articles/4405044385819-How-to-View-your-EZLeagues-Public-Website | read (archive snapshot 2025-08-04) | LGE-18 |
| https://support.ezfacility.com/hc/en-us/articles/4405044388763-How-to-Add-Photo-s-to-your-Public-Site | read (archive snapshot 2025-10-11) | LGE-21 |
| https://support.ezfacility.com/hc/en-us/articles/4405044650779-How-to-Set-Up-Terms-for-Locker-Rentals-in-EZFacility-Classic | read (archive snapshot 2025-10-11) | RES-08 |
| https://support.ezfacility.com/hc/en-us/articles/4405044656411-How-to-Rent-a-Locker-in-EZFacility-Classic | read (archive snapshot 2025-10-11) | RES-08, RNT-17 |
| https://support.ezfacility.com/hc/en-us/articles/4405044668699-How-to-Clear-an-Expired-Locker-in-EZFacility-Classic | read (archive snapshot 2025-08-04) | RNT-18 |
| https://support.ezfacility.com/hc/en-us/articles/4405044678811-How-to-Manage-Lockers-in-EZFacility-Classic | read (archive snapshot 2025-10-11) | RES-09 |
| https://support.ezfacility.com/hc/en-us/articles/4405044695835-Expiring-Lockers | read (archive snapshot 2025-08-06) | PLT-14, RES-07, RPT-35 |
| https://support.ezfacility.com/hc/en-us/articles/4405051068827-Online-Webinars-EZLeagues-in-EZFacility-Classic | read (archive snapshot 2025-10-08) | ONB-02 |
| https://support.ezfacility.com/hc/en-us/articles/4405051095195-How-to-Add-Venues | read (archive snapshot 2025-08-14) | RES-06 |
| https://support.ezfacility.com/hc/en-us/articles/4405051209883-How-to-Set-Up-a-Locker-Rentals-in-EZFacility-Classic | read (archive snapshot 2025-10-08) | RES-07 |
| https://support.ezfacility.com/hc/en-us/articles/4405051224987-Assigned-Lockers-Report | read (archive snapshot 2025-10-11) | RPT-35 |
| https://support.ezfacility.com/hc/en-us/articles/4405051261339-Zoom-Integration-with-EZFacility-Classic | read (archive snapshot 2025-10-08) | INT-09 |
| https://support.ezfacility.com/hc/en-us/articles/4405137428507-How-to-Log-Client-Activity-in-EZFacility-Classic | read (archive snapshot 2025-10-06) | CLI-09, CLI-10 |
| https://support.ezfacility.com/hc/en-us/articles/4405137446427-How-to-Create-Activity-Subjects-for-Tasks-and-Activities | read (archive snapshot 2025-10-08) | CLI-10 |
| https://support.ezfacility.com/hc/en-us/articles/4405137452187-Searching-For-a-Client | read (archive snapshot 2025-08-14) | CLI-03, CLI-13, CLI-14, CLI-17 |
| https://support.ezfacility.com/hc/en-us/articles/4405137459995-Client-Management | read (archive snapshot 2025-10-08) | CLI-01, CLI-07, CLI-08, CLI-09, CLI-12, CLI-16, CLI-17, CLI-18 |
| https://support.ezfacility.com/hc/en-us/articles/4405137464603-How-to-Export-Client-Demographic-Information | read (archive snapshot 2025-10-08) | IMP-03 |
| https://support.ezfacility.com/hc/en-us/articles/4405137471643-Creating-a-Task | read (archive snapshot 2025-08-14) | CLI-11 |
| https://support.ezfacility.com/hc/en-us/articles/4405137473947-Assigning-a-Membership-Number | read (archive snapshot 2025-10-11) | CHK-01, CHK-11 |
| https://support.ezfacility.com/hc/en-us/articles/4405137475355-Add-or-Edit-Client-Categories | read (archive snapshot 2025-08-04) | CLI-06 |
| https://support.ezfacility.com/hc/en-us/articles/4405137478299-Email-Verification-and-Subscriptions-For-Clients | read (archive snapshot 2025-08-04) | MKT-01, MKT-02, MKT-13 |
| https://support.ezfacility.com/hc/en-us/articles/4405137480859-How-to-Add-a-Client-s-Photo-to-their-Account | read (archive snapshot 2025-08-04) | CLI-12 |
| https://support.ezfacility.com/hc/en-us/articles/4405137490843-How-to-Send-an-Email-Campaign-in-EZFacility-Classic | read (archive snapshot 2025-10-11) | MKT-03, MKT-05 |
| https://support.ezfacility.com/hc/en-us/articles/4405137494811-Adding-a-URL-link-to-an-Email-Campaign-in-EZFacility-Classic | read (archive snapshot 2025-08-14) | MKT-03 |
| https://support.ezfacility.com/hc/en-us/articles/4405137498395-Using-the-Email-Template-Library-in-EZFacility-Classic | read (archive snapshot 2025-10-08) | MKT-05 |
| https://support.ezfacility.com/hc/en-us/articles/4405137505179-Manage-Failed-Email-in-in-EZFacility-Classic | read (archive snapshot 2025-08-08) | MKT-08 |
| https://support.ezfacility.com/hc/en-us/articles/4405137514267-Canada-Anti-Spam-Law | read (archive snapshot 2025-10-11) | MKT-01, MKT-08, MKT-09 |
| https://support.ezfacility.com/hc/en-us/articles/4405137521563-Using-the-Check-In-Window-in-EZFacility-Classic | read (archive snapshot 2025-08-04) | CHK-01, CHK-04, CHK-11, CHK-14, CHK-15, CHK-21 |
| https://support.ezfacility.com/hc/en-us/articles/4405137524379-How-to-View-Client-Check-In-Report-in-EZFacility-Classic | read (archive snapshot 2025-08-14) | CHK-19 |
| https://support.ezfacility.com/hc/en-us/articles/4405137527067-Using-Check-In-from-Client-s-Page-in-EZFacility-Classic | read (archive snapshot 2025-08-14) | CHK-03 |
| https://support.ezfacility.com/hc/en-us/articles/4405137537563-How-to-Set-up-the-Self-Check-In-Settings-in-EZFacility-Classic | read (archive snapshot 2025-10-08) | CHK-06, CHK-07 |
| https://support.ezfacility.com/hc/en-us/articles/4405137541403-Using-Bluetooth-Scanners | read (archive snapshot 2025-10-08) | CHK-05, CHK-14, POS-07 |
| https://support.ezfacility.com/hc/en-us/articles/4405137543835-Online-Webinar-Check-in-Dashboard-in-EZFacility-Classic | read (archive snapshot 2025-10-08) | CHK-07 |
| https://support.ezfacility.com/hc/en-us/articles/4405144371227-How-to-Set-Up-Referral-Categories-in-EZFacility-Classic | read (archive snapshot 2025-10-06) | CLI-07 |
| https://support.ezfacility.com/hc/en-us/articles/4405144373403-Online-Webinar-Client-Management-in-EZFacility-Classic | read (archive snapshot 2025-10-08) | ONB-02 |
| https://support.ezfacility.com/hc/en-us/articles/4405144375067-Online-Webinar-Setting-Up-Client-Relationships-in-EZFacility-Classic | read (archive snapshot 2025-10-08) | ONB-02 |
| https://support.ezfacility.com/hc/en-us/articles/4405144383003-Merging-Duplicate-Clients | read (archive snapshot 2025-10-08) | CLI-13 |
| https://support.ezfacility.com/hc/en-us/articles/4405144396955-Establishing-Relationship-Between-Clients | read (archive snapshot 2025-06-21) | FAM-01, FAM-04 |
| https://support.ezfacility.com/hc/en-us/articles/4405144414875-Managing-Email-Subscriptions-on-a-Client-s-Profile | read (archive snapshot 2025-10-11) | MKT-02 |
| https://support.ezfacility.com/hc/en-us/articles/4405144429595-Managing-the-Email-Image-Library-in-EZFacility-Classic | read (archive snapshot 2025-08-14) | MKT-06 |
| https://support.ezfacility.com/hc/en-us/articles/4405144431003-The-Email-Campaign-History-Report-in-EZFacility-Classic | read (archive snapshot 2025-08-04) | RPT-29 |
| https://support.ezfacility.com/hc/en-us/articles/4405144438939-Benefits-of-Email-Verification | read (archive snapshot 2025-08-04) | MKT-01, MKT-09 |
| https://support.ezfacility.com/hc/en-us/articles/4405144453019-How-to-Set-Up-your-Staff-Check-In-Settings-in-EZFacility-Classic | read (archive snapshot 2025-10-08) | CHK-02, CHK-08 |
| https://support.ezfacility.com/hc/en-us/articles/4405144461467-Viewing-Recent-Check-In-s | read (archive snapshot 2025-06-21) | CHK-18 |
| https://support.ezfacility.com/hc/en-us/articles/4405372124059-The-Three-Types-of-Imports-Available | read (archive snapshot 2025-08-04) | IMP-01 |
| https://support.ezfacility.com/hc/en-us/articles/4405384728091-Online-Webinar-5-Tips-to-Boost-Retention-Revenue-with-a-Branded-Mobile-App | read (archive snapshot 2025-08-14) | excluded (no product capability) |
| https://support.ezfacility.com/hc/en-us/articles/4406053980955-How-to-connect-your-QuickBooks-Online-account-with-EZFacility-Classic | read (archive snapshot 2025-08-14) | INT-07 |
| https://support.ezfacility.com/hc/en-us/articles/4406062265883-Enable-the-Smartwaiver-and-EZFacility-Integration-in-EZFacility-Classic | read (archive snapshot 2025-06-21) | DOC-13 |
| https://support.ezfacility.com/hc/en-us/articles/4406813864603-Memberships-Webinar | read (archive snapshot 2025-08-08) | ONB-02 |
| https://support.ezfacility.com/hc/en-us/articles/4406988987803-How-to-Use-the-Employee-Time-Clock-as-a-Manager | read (archive snapshot 2025-10-11) | STF-08 |
| https://support.ezfacility.com/hc/en-us/articles/4407310264475-How-to-Add-Additional-Rentals-to-an-Existing-Rental-in-EZFacility-Classic | read (archive snapshot 2025-10-11) | RNT-02, RNT-04, SCH-12, SCH-13 |
| https://support.ezfacility.com/hc/en-us/articles/4411540429851-Enabling-the-Vaccine-Passport-Feature | read (archive snapshot 2025-10-08) | CHK-17 |
| https://support.ezfacility.com/hc/en-us/articles/4411549886107-How-to-use-the-Vaccine-Passport-with-Self-Check-in | read (archive snapshot 2025-10-08) | CHK-06, CHK-17 |
| https://support.ezfacility.com/hc/en-us/articles/4411586669467-How-to-use-the-Vaccine-Passport-with-Staff-Check-in | read (archive snapshot 2025-10-11) | CHK-02, CHK-17 |
| https://support.ezfacility.com/hc/en-us/articles/4411661820955-How-use-Documents-to-Create-Membership-Waivers-for-Self-Service | read (archive snapshot 2025-08-06) | DOC-01, DOC-08 |
| https://support.ezfacility.com/hc/en-us/articles/4411809532187-How-use-Documents-to-Create-Membership-Waivers-when-selling-a-Membership-in-person | read (archive snapshot 2025-08-04) | DOC-01, DOC-02, DOC-03, DOC-04, DOC-05, DOC-08, DOC-12 |
| https://support.ezfacility.com/hc/en-us/articles/4414739101339-Form-Menu-Features-Overview | read (archive snapshot 2025-10-08) | REG-15, REG-20, REG-21, REG-22 |
| https://support.ezfacility.com/hc/en-us/articles/4414746736155-How-to-Create-New-Form-1st-Time-Set-Up-Event | read (archive snapshot 2025-08-14) | REG-15, REG-16 |
| https://support.ezfacility.com/hc/en-us/articles/4414758416539-How-to-COPY-an-Existing-Form | read (archive snapshot 2025-08-14) | REG-15 |
| https://support.ezfacility.com/hc/en-us/articles/4414758652699-How-to-Add-Edit-Text-Box-Questions | read (archive snapshot 2025-06-21) | REG-16 |
| https://support.ezfacility.com/hc/en-us/articles/4414758842523-How-to-Add-Edit-Multiple-Choice-Questions | read (archive snapshot 2025-08-14) | REG-16 |
| https://support.ezfacility.com/hc/en-us/articles/4414758916251-How-to-Add-Inventory-Control-Multiple-Choice-Questions | read (archive snapshot 2025-10-08) | REG-17 |
| https://support.ezfacility.com/hc/en-us/articles/4414759250843-How-to-Enter-Amount-Questions | read (archive snapshot 2025-08-06) | REG-16 |
| https://support.ezfacility.com/hc/en-us/articles/4414759402907-How-to-Add-Inventory-Control-Enter-Quantity-Questions | read (archive snapshot 2025-08-04) | REG-17 |
| https://support.ezfacility.com/hc/en-us/articles/4414774769947-How-to-Add-Edit-Checkbox-Questions | read (archive snapshot 2025-08-14) | REG-16 |
| https://support.ezfacility.com/hc/en-us/articles/4414775164187-How-to-Enter-Quantity-Questions | read (archive snapshot 2025-08-09) | REG-16 |
| https://support.ezfacility.com/hc/en-us/articles/4414782274587-How-to-Add-Inventory-Control-Checkbox-Questions | read (archive snapshot 2025-08-14) | REG-17 |
| https://support.ezfacility.com/hc/en-us/articles/4414782749467-How-to-Add-Edit-Information-Topics | read (archive snapshot 2025-08-08) | REG-18 |
| https://support.ezfacility.com/hc/en-us/articles/4414782814363-How-to-add-edit-a-Form-Header-Graphic | read (archive snapshot 2025-10-08) | REG-19 |
| https://support.ezfacility.com/hc/en-us/articles/4414782863003-How-to-edit-customize-Form-Colors-Visual-Settings | read (archive snapshot 2025-10-11) | REG-19 |
| https://support.ezfacility.com/hc/en-us/articles/4415441339547-How-to-Create-a-Subgroup | read (archive snapshot 2025-10-08) | REG-02 |
| https://support.ezfacility.com/hc/en-us/articles/4415441342235-How-to-Manually-Register-a-Client-into-a-Group-or-a-Sub-group | read (archive snapshot 2025-10-11) | REG-07 |
| https://support.ezfacility.com/hc/en-us/articles/4415441364635-How-to-Process-a-Refund-Remove-a-Client-from-a-Group | read (archive snapshot 2025-10-08) | BIL-07, BIL-21, PAY-05 |
| https://support.ezfacility.com/hc/en-us/articles/4415441369883-How-to-Set-Online-Registration-Default-Settings | read (archive snapshot 2025-08-08) | REG-11 |
| https://support.ezfacility.com/hc/en-us/articles/4415441379483-How-to-Move-a-Client-Between-Groups-or-Sub-Groups | read (archive snapshot 2025-08-14) | REG-08 |
| https://support.ezfacility.com/hc/en-us/articles/4415441383707-How-to-Send-an-Email-Campaign-to-Groups | read (archive snapshot 2025-08-14) | MKT-11 |
| https://support.ezfacility.com/hc/en-us/articles/4415445419035-How-to-Create-a-Group | read (archive snapshot 2025-08-06) | REG-01, REG-03 |
| https://support.ezfacility.com/hc/en-us/articles/4415445452059-How-to-Generate-a-Report-for-Groups | read (archive snapshot 2025-10-11) | RPT-27 |
| https://support.ezfacility.com/hc/en-us/articles/4415445455771-How-to-Remove-or-Add-a-Client-using-Waitlist | read (archive snapshot 2025-10-11) | REG-09 |
| https://support.ezfacility.com/hc/en-us/articles/4416793387803-Online-Webinar-Exploring-Documents-in-EZFacility-Classic | read (archive snapshot 2025-10-08) | DOC-01, DOC-02 |
| https://support.ezfacility.com/hc/en-us/articles/4416952099611-How-to-Generate-an-ID-Card | read (archive snapshot 2025-10-08) | CHK-12 |
| https://support.ezfacility.com/hc/en-us/articles/4426140759451-Topaz-Signature-Pad-Setup-and-Update | read (archive snapshot 2025-10-11) | DOC-12 |
| https://support.ezfacility.com/hc/en-us/articles/44426099543835-December-3-2025-Release-Notes | title only — live page bot-challenged, no archive copy | REL-01 |
| https://support.ezfacility.com/hc/en-us/articles/44459810488603-Important-Update-to-EZFacility-v4-0-on-1-14-26 | title only — live page bot-challenged, no archive copy | ONB-04, REL-01, REL-03 |
| https://support.ezfacility.com/hc/en-us/articles/4505581324827-Accessing-the-Main-Menu-in-EZSignUp | read (archive snapshot 2025-10-08) | REG-15, REG-21, REG-24 |
| https://support.ezfacility.com/hc/en-us/articles/4505589011227-Registering-for-an-Event-in-EZSignUp | read (archive snapshot 2025-10-11) | REG-23 |
| https://support.ezfacility.com/hc/en-us/articles/45100513622171-How-to-Setup-Resources-on-Your-Calendar | title only — live page bot-challenged, no archive copy | RES-03, SCH-01 |
| https://support.ezfacility.com/hc/en-us/articles/45196141671067-How-to-Create-a-Recurring-Session-on-the-Calendar-in-Resource-View | title only — live page bot-challenged, no archive copy | SCH-09 |
| https://support.ezfacility.com/hc/en-us/articles/45196168160411-How-to-Add-a-Session-to-Your-Calendar-in-Resource-View | title only — live page bot-challenged, no archive copy | SCH-07 |
| https://support.ezfacility.com/hc/en-us/articles/45196187362203-How-to-Create-a-New-Rental-Type | title only — live page bot-challenged, no archive copy | RNT-01 |
| https://support.ezfacility.com/hc/en-us/articles/45196203926555-How-to-Create-a-New-Rental-Rate | title only — live page bot-challenged, no archive copy | RNT-02 |
| https://support.ezfacility.com/hc/en-us/articles/45196231520155-Add-Buffer-Times-to-Rentals | title only — live page bot-challenged, no archive copy | RNT-07 |
| https://support.ezfacility.com/hc/en-us/articles/45196255348123-How-to-Add-a-Rental-to-Your-Calendar-in-Resource-View | title only — live page bot-challenged, no archive copy | RNT-03 |
| https://support.ezfacility.com/hc/en-us/articles/45196262785307-Add-Buffer-Times-to-Sessions | title only — live page bot-challenged, no archive copy | SCH-14 |
| https://support.ezfacility.com/hc/en-us/articles/45211147546267-How-to-Mark-Attendance-on-a-Session-in-Resource-View | title only — live page bot-challenged, no archive copy | CLS-03, PKG-12 |
| https://support.ezfacility.com/hc/en-us/articles/48376398255643-API-Starter-Kit | title only — live page bot-challenged, no archive copy | INT-01 |
| https://support.ezfacility.com/hc/en-us/articles/50293809318555-How-to-Set-Up-Billing-Preferences | title only — live page bot-challenged, no archive copy | BIL-16 |
| https://support.ezfacility.com/hc/en-us/articles/50433482606491-EZFacility-API-FAQs | title only — live page bot-challenged, no archive copy | INT-01 |
| https://support.ezfacility.com/hc/en-us/articles/52057261926939-How-to-Remove-a-Rental-from-the-Schedule | title only — live page bot-challenged, no archive copy | RNT-08 |
| https://support.ezfacility.com/hc/en-us/articles/52057689019803-How-to-Remove-a-Recurring-Rental-from-the-Schedule | title only — live page bot-challenged, no archive copy | RNT-08 |
| https://support.ezfacility.com/hc/en-us/articles/52230184836379-Onboarding-Checklist-Membership-Checklist-Groups-Checklist | title only — live page bot-challenged, no archive copy | MEM-23, ONB-01, REG-01 |
| https://support.ezfacility.com/hc/en-us/articles/52341828808475-July-1-2026-Release-Notes-v104-0 | title only — live page bot-challenged, no archive copy | REL-01 |
| https://support.ezfacility.com/hc/en-us/articles/52430805858331-July-1-2026-Release-Notes-v104-0-1 | title only — live page bot-challenged, no archive copy | REL-01 |
| https://support.ezfacility.com/hc/en-us/articles/53053635021979-July-15-2026-Release-Notes-v105-0 | title only — live page bot-challenged, no archive copy | REL-01 |
| https://support.ezfacility.com/hc/en-us/articles/5325162944539-How-do-customers-redeem-their-points | read (archive snapshot 2025-06-21) | INT-11 |
| https://support.ezfacility.com/hc/en-us/articles/5325163152155-When-can-they-start-using-Perkville | read (archive snapshot 2025-08-14) | INT-11 |
| https://support.ezfacility.com/hc/en-us/articles/5325163359131-How-does-a-facility-redeem-Perks | read (archive snapshot 2025-10-08) | INT-11 |
| https://support.ezfacility.com/hc/en-us/articles/5325205707931-Who-notifies-the-customers-they-earned-points | read (archive snapshot 2025-08-14) | INT-11 |
| https://support.ezfacility.com/hc/en-us/articles/5325270760731-How-are-points-earned | read (archive snapshot 2025-08-04) | INT-11 |
| https://support.ezfacility.com/hc/en-us/articles/5325278710171-How-much-does-Perkville-cost | read (archive snapshot 2025-08-04) | INT-11 |
| https://support.ezfacility.com/hc/en-us/articles/5325284957979-What-is-Perkville | read (archive snapshot 2025-04-29) | INT-11 |
| https://support.ezfacility.com/hc/en-us/articles/5325289162907-How-does-a-facility-register-for-Perkville | read (archive snapshot 2025-10-08) | INT-11 |
| https://support.ezfacility.com/hc/en-us/articles/53377281922075-July-22-2026-Release-Notes-v106-0 | title only — live page bot-challenged, no archive copy | REL-01 |
| https://support.ezfacility.com/hc/en-us/articles/5393406604315-How-to-connect-your-QuickBooks-Online-account-with-EZFacility | read (archive snapshot 2025-08-04) | INT-07 |
| https://support.ezfacility.com/hc/en-us/articles/54387128581147-How-to-Add-a-Card-on-File-Manually | title only — live page bot-challenged, no archive copy | PAY-06 |
| https://support.ezfacility.com/hc/en-us/articles/54598636350235-August-19-2026-Release-Notes-v110-0 | title only — live page bot-challenged, no archive copy | REL-01 |
| https://support.ezfacility.com/hc/en-us/articles/54599987433883-Self-Service-Terms-Conditions-Acknowledgment | title only — live page bot-challenged, no archive copy | DOC-14, SSP-14 |
| https://support.ezfacility.com/hc/en-us/articles/54600257319195-Email-SMS-Subscriptions-Labeling-Update-US-Only-Update | title only — live page bot-challenged, no archive copy | CLI-16, MKT-02 |
| https://support.ezfacility.com/hc/en-us/articles/55926816152603-How-to-Switch-to-the-NewUI | title only — live page bot-challenged, no archive copy | PLT-09 |
| https://support.ezfacility.com/hc/en-us/articles/57003799901851-How-to-Create-a-New-Rental-Plan | title only — live page bot-challenged, no archive copy | RNT-09 |
| https://support.ezfacility.com/hc/en-us/articles/57004869280027-How-to-Share-a-Rental-Plan | title only — live page bot-challenged, no archive copy | FAM-06, RNT-10 |
| https://support.ezfacility.com/hc/en-us/articles/57004872733211-How-to-Run-the-Rental-Plan-Sales-Report | title only — live page bot-challenged, no archive copy | RNT-12, RPT-39 |
| https://support.ezfacility.com/hc/en-us/articles/57004883480731-How-to-Remove-and-Refund-a-Rental-Plan | title only — live page bot-challenged, no archive copy | RNT-11 |
| https://support.ezfacility.com/hc/en-us/articles/57005260684315-How-to-set-up-Rentals-For-Self-Service | title only — live page bot-challenged, no archive copy | RNT-05, SSP-04 |
| https://support.ezfacility.com/hc/en-us/articles/57248399589659-Rental-Plans-Release-Notes-October-15-2026 | title only — live page bot-challenged, no archive copy | REL-01, RNT-09, RPT-39 |
| https://support.ezfacility.com/hc/en-us/articles/5776809698075-How-to-create-an-Email-Campaign-in-the-New-EZFacility-Experience | read (archive snapshot 2025-10-08) | MKT-03 |
| https://support.ezfacility.com/hc/en-us/articles/5777441102235-How-to-view-your-Campaign-History-in-the-New-EZFacility-Experience | read (archive snapshot 2025-08-04) | MKT-07 |
| https://support.ezfacility.com/hc/en-us/articles/5777638736027-How-To-Send-email-broadcasts-message-to-FORM-registrants | read (archive snapshot 2025-08-14) | MKT-12 |
| https://support.ezfacility.com/hc/en-us/articles/57821654414875-October-28-2026-Release-Notes-v120-0 | title only — live page bot-challenged, no archive copy | REL-01 |
| https://support.ezfacility.com/hc/en-us/articles/58150655820187-November-4-2026-Release-Notes-v121-0 | title only — live page bot-challenged, no archive copy | REL-01 |
| https://support.ezfacility.com/hc/en-us/articles/6740429102747-How-to-Freeze-a-Membership-in-EZFacility | read (archive snapshot 2025-08-14) | MEM-05, MEM-12 |
| https://support.ezfacility.com/hc/en-us/articles/8305870999323-Updating-your-EZFacility-User-in-Brivo-Access | read (archive snapshot 2025-10-11) | CHK-16 |
| https://support.ezfacility.com/hc/en-us/articles/9061322036635-How-to-Send-a-Self-Service-Invitation-Through-the-Client-Profile | read (archive snapshot 2025-10-11) | CLI-15 |
| https://support.ezfacility.com/hc/en-us/articles/9118010703771-How-to-show-the-Self-Service-Calendar-in-Resource-View | read (archive snapshot 2025-08-14) | SSP-12 |
| https://support.ezfacility.com/hc/en-us/articles/9917964474011-Enable-the-Smartwaiver-and-EZFacility-Integration-in-EZFacility | read (archive snapshot 2025-08-08) | INT-10 |

## Marketing core pages (49)

| URL | Status | Features |
|---|---|---|
| https://www.ezfacility.com | read | RNT-06 |
| https://www.ezfacility.com/about-us | read | PLT-15 |
| https://www.ezfacility.com/benefits | read | CLI-01, CLI-20, IMP-02, INT-01, ONB-03, ONB-05, PLT-01, PLT-15, RPT-01, RPT-02, RPT-17, RPT-23, RPT-40, STF-15 |
| https://www.ezfacility.com/blog | read | no feature cited (boilerplate, navigation or non-product content) |
| https://www.ezfacility.com/capterra-sports-league-management/ | read | BIL-22, LGE-15 |
| https://www.ezfacility.com/events/ | read | ONB-02 |
| https://www.ezfacility.com/ez-api-services | read | INT-01, INT-02, INT-04, INT-06, LGE-27, POS-22 |
| https://www.ezfacility.com/ezfacility-comparison | read | CLI-19, DOC-06, PLT-01, RPT-02 |
| https://www.ezfacility.com/ezfacility-vs-abc-glofox | read | IMP-02, ONB-05 |
| https://www.ezfacility.com/ezfacility-vs-allbooked | read | no feature cited (boilerplate, navigation or non-product content) |
| https://www.ezfacility.com/ezfacility-vs-baseline-pro | read | no feature cited (boilerplate, navigation or non-product content) |
| https://www.ezfacility.com/ezfacility-vs-courtreserve | read | no feature cited (boilerplate, navigation or non-product content) |
| https://www.ezfacility.com/ezfacility-vs-gymmaster | read | no feature cited (boilerplate, navigation or non-product content) |
| https://www.ezfacility.com/ezfacility-vs-mindbody | read | no feature cited (boilerplate, navigation or non-product content) |
| https://www.ezfacility.com/ezfacility-vs-swift | read | no feature cited (boilerplate, navigation or non-product content) |
| https://www.ezfacility.com/ezfacility-vs-upper-hand | read | no feature cited (boilerplate, navigation or non-product content) |
| https://www.ezfacility.com/ezmessaging/ | read | MKT-15 |
| https://www.ezfacility.com/features/billing-payments | read | BIL-06, BIL-14, BIL-22, INT-07, MEM-02, MEM-09, MEM-11, MEM-19, PAY-09, PAY-18, PKG-01, PKG-04, PKG-09, PKG-12, PLT-01, POS-01, POS-02, POS-11, POS-12, POS-22, RPT-01, RPT-02, RPT-20, RPT-30, RPT-40 |
| https://www.ezfacility.com/features/branded-mobile-app/ | read | APP-01, APP-02, APP-03, APP-06, APP-14, APP-17, APP-19, CHK-13, MKT-16, PKG-09, PKG-14, PLT-13 |
| https://www.ezfacility.com/features/league-scheduling-management | read | INT-10, LGE-01, LGE-02, LGE-03, LGE-06, LGE-07, LGE-08, LGE-09, LGE-10, LGE-12, LGE-15, LGE-18, LGE-22, LGE-24, REG-10, RPT-36, RPT-40 |
| https://www.ezfacility.com/features/member-engagement | read | APP-02, APP-06, CHK-12, CHK-13, CLI-12, CLS-08, CLS-10, FIT-01, FIT-05, INT-09, MKT-03, REG-12, SSP-16, SSP-18 |
| https://www.ezfacility.com/features/merchant-processing | read | PAY-02, PAY-10, PAY-11, PAY-14, PAY-15, PAY-17, POS-12, POS-14, POS-21 |
| https://www.ezfacility.com/features/scheduling-operations | read | CLS-10, POS-17, POS-18, RES-03, RES-05, RNT-03, RNT-05, RNT-09, RNT-15, SCH-01, SCH-09, SCH-12, SCH-13 |
| https://www.ezfacility.com/features/staff-access-management | read | CHK-01, CHK-05, CHK-07, CHK-08, CHK-09, CHK-10, CHK-15, CHK-16, INT-08, RPT-37, SCH-19, STF-01, STF-02, STF-05, STF-06, STF-07, STF-08, STF-11, STF-13, STF-15 |
| https://www.ezfacility.com/industries | read | no feature cited (boilerplate, navigation or non-product content) |
| https://www.ezfacility.com/industries/baseball-facility-software | read | PKG-01 |
| https://www.ezfacility.com/industries/basketball-scheduling-software | read | FAM-01 |
| https://www.ezfacility.com/industries/campus-recreation-software | read | PAY-15, POS-12 |
| https://www.ezfacility.com/industries/community-center-management-software | read | no feature cited (boilerplate, navigation or non-product content) |
| https://www.ezfacility.com/industries/gym-management-software | read | FIT-05, MEM-02, MEM-09, SCH-01, SCH-19, STF-02 |
| https://www.ezfacility.com/industries/parks-and-recreation-software | read | no feature cited (boilerplate, navigation or non-product content) |
| https://www.ezfacility.com/industries/personal-trainer-software | read | CLS-06, FIT-02, SCH-18 |
| https://www.ezfacility.com/industries/pickleball-facilities | read | LGE-28 |
| https://www.ezfacility.com/industries/rink-management-software | read | CHK-12, POS-12, POS-17, RNT-14, RNT-17 |
| https://www.ezfacility.com/industries/shooting-range-gun-club-software | read | MEM-02, RPT-40 |
| https://www.ezfacility.com/industries/soccer-scheduling-software | read | LGE-24 |
| https://www.ezfacility.com/industries/sports-facility-software | read | no feature cited (boilerplate, navigation or non-product content) |
| https://www.ezfacility.com/industries/tennis-club-software | read | LGE-28, SCH-18 |
| https://www.ezfacility.com/industries/volleyball-software | read | CHK-12 |
| https://www.ezfacility.com/industries/yoga-and-pilates-studio-management-software | read | CHK-05, MEM-02 |
| https://www.ezfacility.com/partners | read | CHK-15, INT-11, INT-12, INT-14, INT-15, MKT-19, MKT-21, PAY-11, POS-23, STF-14 |
| https://www.ezfacility.com/partners/passport-technologies/ | read | CHK-15, INT-14 |
| https://www.ezfacility.com/partners/quickbooks-online-sync/ | read | INT-07 |
| https://www.ezfacility.com/partners/rapid-gun-systems/ | read | INT-14, POS-23 |
| https://www.ezfacility.com/partners/smartwaiver/ | read | DOC-13, INT-10 |
| https://www.ezfacility.com/plans-pricing/pricing-results | read | INT-06, INT-07, LGE-27, MKT-04, ONB-03, PLT-02, PLT-14, RES-03 |
| https://www.ezfacility.com/press-news | read | no feature cited (boilerplate, navigation or non-product content) |
| https://www.ezfacility.com/reviews | read | no feature cited (boilerplate, navigation or non-product content) |
| https://www.ezfacility.com/self-service-portal | read | CLS-09, MKT-13, PKG-09, PKG-14, RNT-06, SSP-01, SSP-02, SSP-10, SSP-17, SSP-20, STF-12 |

## Press / news (81)

| URL | Status | Features |
|---|---|---|
| https://www.ezfacility.com/press-news/blog/fitness-newsletter | read | MKT-05, MKT-20 |
| https://www.ezfacility.com/press-news/blog/tips-for-creating-compelling-fitness-newsletters | read | no feature cited (boilerplate, navigation or non-product content) |
| https://www.ezfacility.com/press-news/news/1-million-dollar-gift-to-enhance-universitys-athletic-training-facility | read | no feature cited (boilerplate, navigation or non-product content) |
| https://www.ezfacility.com/press-news/news/acquisition-of-two-new-clubs-indicates-growth-for-california-family-fitness | read | no feature cited (boilerplate, navigation or non-product content) |
| https://www.ezfacility.com/press-news/news/americans-made-more-than-5-billion-visits-to-health-clubs-in-2013 | read | no feature cited (boilerplate, navigation or non-product content) |
| https://www.ezfacility.com/press-news/news/atlanta-braves-propose-new-training-facility-in-st-petersburg | read | no feature cited (boilerplate, navigation or non-product content) |
| https://www.ezfacility.com/press-news/news/blue-goji-announces-new-video-game-accessories-for-exercise-machines | read | no feature cited (boilerplate, navigation or non-product content) |
| https://www.ezfacility.com/press-news/news/california-hockey-rink-becomes-first-to-use-recycled-water | read | no feature cited (boilerplate, navigation or non-product content) |
| https://www.ezfacility.com/press-news/news/california-ripped-fitness-plans-new-branch-in-san-jose | read | no feature cited (boilerplate, navigation or non-product content) |
| https://www.ezfacility.com/press-news/news/chuze-fitness-opens-new-location-with-expanded-offerings | read | no feature cited (boilerplate, navigation or non-product content) |
| https://www.ezfacility.com/press-news/news/club-one-relaunches-as-active-sports-clubs | read | no feature cited (boilerplate, navigation or non-product content) |
| https://www.ezfacility.com/press-news/news/colorado-town-may-enter-public-private-partnership-for-synthetic-snow-facility | read | no feature cited (boilerplate, navigation or non-product content) |
| https://www.ezfacility.com/press-news/news/coney-island-gets-massive-new-sports-facility | read | no feature cited (boilerplate, navigation or non-product content) |
| https://www.ezfacility.com/press-news/news/crunch-fitness-launches-online-workout-video-program | read | no feature cited (boilerplate, navigation or non-product content) |
| https://www.ezfacility.com/press-news/news/david-barton-gym-to-be-featured-on-popular-reality-tv-show | read | no feature cited (boilerplate, navigation or non-product content) |
| https://www.ezfacility.com/press-news/news/expansion-of-uccs-recreation-and-wellness-center-doubles-facilitys-size | read | no feature cited (boilerplate, navigation or non-product content) |
| https://www.ezfacility.com/press-news/news/extreme-sports-complex-planned-for-florida-locale | read | no feature cited (boilerplate, navigation or non-product content) |
| https://www.ezfacility.com/press-news/news/fitness-first-launches-major-rebranding-effort | read | no feature cited (boilerplate, navigation or non-product content) |
| https://www.ezfacility.com/press-news/news/florida-gators-to-build-15-million-indoor-practice-facility | read | no feature cited (boilerplate, navigation or non-product content) |
| https://www.ezfacility.com/press-news/news/for-profit-adult-sports-leagues-increase-in-popularity | read | no feature cited (boilerplate, navigation or non-product content) |
| https://www.ezfacility.com/press-news/news/giant-new-sports-center-to-feature-practice-space-and-a-full-service-restaurant | read | no feature cited (boilerplate, navigation or non-product content) |
| https://www.ezfacility.com/press-news/news/gigantic-new-sports-complex-proposed-for-d-c-area | read | no feature cited (boilerplate, navigation or non-product content) |
| https://www.ezfacility.com/press-news/news/golds-gym-acquires-17-fitness-first-facilities | read | no feature cited (boilerplate, navigation or non-product content) |
| https://www.ezfacility.com/press-news/news/high-intensity-interval-training-tops-annual-list-of-fitness-trends | read | no feature cited (boilerplate, navigation or non-product content) |
| https://www.ezfacility.com/press-news/news/high-tech-scale-revolutionizes-fitness-assessment | read | no feature cited (boilerplate, navigation or non-product content) |
| https://www.ezfacility.com/press-news/news/hope-college-earns-high-profile-sports-facility-award | read | no feature cited (boilerplate, navigation or non-product content) |
| https://www.ezfacility.com/press-news/news/in-shape-opens-new-flagship-location | read | no feature cited (boilerplate, navigation or non-product content) |
| https://www.ezfacility.com/press-news/news/james-madison-university-to-build-88-million-basketball-arena | read | no feature cited (boilerplate, navigation or non-product content) |
| https://www.ezfacility.com/press-news/news/la-fitness-to-spend-more-than-4-million-remodeling-ten-arizona-clubs | read | no feature cited (boilerplate, navigation or non-product content) |
| https://www.ezfacility.com/press-news/news/louisville-slugger-opens-new-sports-facility | read | no feature cited (boilerplate, navigation or non-product content) |
| https://www.ezfacility.com/press-news/news/major-field-renovation-planned-for-big-ten-school | read | no feature cited (boilerplate, navigation or non-product content) |
| https://www.ezfacility.com/press-news/news/major-overhaul-of-university-of-colorado-boulder-rec-center | read | no feature cited (boilerplate, navigation or non-product content) |
| https://www.ezfacility.com/press-news/news/major-sports-tourism-complex-planned-for-orlando-area | read | no feature cited (boilerplate, navigation or non-product content) |
| https://www.ezfacility.com/press-news/news/minnesota-vikings-stadium-first-in-u-s-to-launch-with-led | read | no feature cited (boilerplate, navigation or non-product content) |
| https://www.ezfacility.com/press-news/news/mossas-online-fitness-service-encourages-gym-attendance-promotes-some-health-clubs | read | no feature cited (boilerplate, navigation or non-product content) |
| https://www.ezfacility.com/press-news/news/mud-runs-and-obstacle-races-capitalizing-on-rising-recreational-fitness-trends | read | no feature cited (boilerplate, navigation or non-product content) |
| https://www.ezfacility.com/press-news/news/new-athletic-complex-to-open-in-california-storage-facility | read | no feature cited (boilerplate, navigation or non-product content) |
| https://www.ezfacility.com/press-news/news/new-health-club-for-baby-boomers-only | read | no feature cited (boilerplate, navigation or non-product content) |
| https://www.ezfacility.com/press-news/news/new-jersey-offers-giant-tax-credit-to-76ers-to-build-practice-space-in-camden | read | no feature cited (boilerplate, navigation or non-product content) |
| https://www.ezfacility.com/press-news/news/new-multi-purpose-sports-facility-opens-in-kingsport | read | no feature cited (boilerplate, navigation or non-product content) |
| https://www.ezfacility.com/press-news/news/new-partnership-gives-veterans-a-shot-at-gym-ownership | read | no feature cited (boilerplate, navigation or non-product content) |
| https://www.ezfacility.com/press-news/news/new-realty-tv-show-for-failing-gyms | read | no feature cited (boilerplate, navigation or non-product content) |
| https://www.ezfacility.com/press-news/news/new-sports-facility-at-wilmington-college-takes-holistic-approach-to-athletics | read | no feature cited (boilerplate, navigation or non-product content) |
| https://www.ezfacility.com/press-news/news/new-sports-themed-hotel-plus-sports-facility-planned-for-st-louis-suburb | read | no feature cited (boilerplate, navigation or non-product content) |
| https://www.ezfacility.com/press-news/news/new-state-of-the-art-fitness-facility-for-auburn-university | read | no feature cited (boilerplate, navigation or non-product content) |
| https://www.ezfacility.com/press-news/news/new-year-round-sports-facility-for-naperville-illinois | read | no feature cited (boilerplate, navigation or non-product content) |
| https://www.ezfacility.com/press-news/news/ohio-hospital-in-deal-to-take-over-fitness-center | read | no feature cited (boilerplate, navigation or non-product content) |
| https://www.ezfacility.com/press-news/news/palm-beach-hotel-receives-preliminary-approval-for-planned-fitness-center | read | no feature cited (boilerplate, navigation or non-product content) |
| https://www.ezfacility.com/press-news/news/professor-wins-grant-to-study-effectiveness-of-hiit-vs-army-workouts | read | no feature cited (boilerplate, navigation or non-product content) |
| https://www.ezfacility.com/press-news/news/proposed-fitness-tax-credit-could-save-canada-2-5-billion | read | no feature cited (boilerplate, navigation or non-product content) |
| https://www.ezfacility.com/press-news/news/sports-medicine-licensure-clarity-act-to-help-safeguard-athletic-trainers-sports-medicine-professionals-against-liability | read | no feature cited (boilerplate, navigation or non-product content) |
| https://www.ezfacility.com/press-news/news/state-of-the-art-and-luxurious-new-sports-center-opens-at-university-of-oregon | read | no feature cited (boilerplate, navigation or non-product content) |
| https://www.ezfacility.com/press-news/news/technogym-named-official-equipment-supplier-for-2016-summer-olympics | read | no feature cited (boilerplate, navigation or non-product content) |
| https://www.ezfacility.com/press-news/news/texas-am-university-to-renovate-student-rec-center | read | no feature cited (boilerplate, navigation or non-product content) |
| https://www.ezfacility.com/press-news/news/top-u-k-soccer-club-builds-world-class-training-facility | read | no feature cited (boilerplate, navigation or non-product content) |
| https://www.ezfacility.com/press-news/news/towson-university-sports-center-to-get-34-million-90000-square-foot-addition | read | no feature cited (boilerplate, navigation or non-product content) |
| https://www.ezfacility.com/press-news/news/university-of-northwestern-ohio-covers-baseball-diamond-in-red-turf | read | no feature cited (boilerplate, navigation or non-product content) |
| https://www.ezfacility.com/press-news/news/weight-watchers-enters-the-fitness-business | read | no feature cited (boilerplate, navigation or non-product content) |
| https://www.ezfacility.com/press-news/news/worlds-largest-ice-facility-to-open-in-the-bronx | read | no feature cited (boilerplate, navigation or non-product content) |
| https://www.ezfacility.com/press-news/news/xsport-fitness-to-expand-in-chicago-new-york-and-washington-d-c | read | no feature cited (boilerplate, navigation or non-product content) |
| https://www.ezfacility.com/press-news/news/yogafit-introduces-classes-for-veterans-suffering-from-ptsd | read | no feature cited (boilerplate, navigation or non-product content) |
| https://www.ezfacility.com/press-news/news/yogaworks-acquired-by-private-equity-firm | read | no feature cited (boilerplate, navigation or non-product content) |
| https://www.ezfacility.com/press-news/press-releases/ezfacility-acquires-efit-financial | read | BIL-24 |
| https://www.ezfacility.com/press-news/press-releases/ezfacility-acquires-frontline-solutions | read | POS-23 |
| https://www.ezfacility.com/press-news/press-releases/ezfacility-acquires-member-solutions | read | no feature cited (boilerplate, navigation or non-product content) |
| https://www.ezfacility.com/press-news/press-releases/ezfacility-acquires-sda-solutions | read | no feature cited (boilerplate, navigation or non-product content) |
| https://www.ezfacility.com/press-news/press-releases/ezfacility-introduces-new-memberme-mobile-app | read | APP-06, APP-14, APP-17, INT-11 |
| https://www.ezfacility.com/press-news/press-releases/ezfacility-launches-new-website | read | LGE-08 |
| https://www.ezfacility.com/press-news/press-releases/ezfacility-named-in-capterras-top-20-most-popular-for-membership-management-software | read | no feature cited (boilerplate, navigation or non-product content) |
| https://www.ezfacility.com/press-news/press-releases/ezfacility-named-primary-club-sponsor-for-hp-uniteds-2024-2025-season | read | no feature cited (boilerplate, navigation or non-product content) |
| https://www.ezfacility.com/press-news/press-releases/ezfacility-partners-with-brivo-to-offer-24-hour-sports-fitness-access | read | CHK-10, CHK-16, INT-14 |
| https://www.ezfacility.com/press-news/press-releases/ezfacility-partners-with-club-vitals | read | INT-14 |
| https://www.ezfacility.com/press-news/press-releases/ezfacility-releases-cutting-edge-fitness-point-of-sale-solution | read | POS-01, POS-02, POS-04, POS-06, POS-15, POS-22 |
| https://www.ezfacility.com/press-news/press-releases/ezfacility-team-expands-meet-fitness-industry-growth | read | no feature cited (boilerplate, navigation or non-product content) |
| https://www.ezfacility.com/press-news/press-releases/ezfacility-updates-ezleagues-scheduling-wizard | read | LGE-08 |
| https://www.ezfacility.com/press-news/press-releases/ezfacilitys-memberme-mobile-app-now-available-on-android | read | MEM-09 |
| https://www.ezfacility.com/press-news/press-releases/jonas-software-acquires-ezfacility | read | no feature cited (boilerplate, navigation or non-product content) |
| https://www.ezfacility.com/press-news/press-releases/jonas-software-announces-the-acquisition-of-apps-that-fit-llc-migym | read | APP-02 |
| https://www.ezfacility.com/press-news/press-releases/sun-sets-on-123signup-while-ezsignup-emerges | read | REG-15, REG-25 |
| https://www.ezfacility.com/press-news/press-releases/textmunication-and-ezfacility-launch-ezmessaging-with-access-to-thousands-of-clients | read | no feature cited (boilerplate, navigation or non-product content) |
| https://www.ezfacility.com/press-news/shooting-industry-magazine-features-ezfacilitys-new-website-for-range-operators | read | no feature cited (boilerplate, navigation or non-product content) |

## Blog posts fetched (46 of 426)

| URL | Status | Features |
|---|---|---|
| https://www.ezfacility.com/blog/5-tips-to-boost-retention-revenue-with-a-branded-mobile-app | read | no feature cited (boilerplate, navigation or non-product content) |
| https://www.ezfacility.com/blog/activate-perkville-on-ezfacility-and-gamify-exercise-this-year | read | INT-11, MKT-19 |
| https://www.ezfacility.com/blog/add-to-the-client-experience-with-nutrition-complete | read | INT-14 |
| https://www.ezfacility.com/blog/baseball-membership-communication-software | read | MKT-15, MKT-17 |
| https://www.ezfacility.com/blog/benefits-of-using-software-to-manage-your-facility | read | BIL-24 |
| https://www.ezfacility.com/blog/benefits-of-using-sports-management-software | read | CLI-01, RPT-01 |
| https://www.ezfacility.com/blog/best-accounting-software-for-sports-clubs | read | no feature cited (boilerplate, navigation or non-product content) |
| https://www.ezfacility.com/blog/best-baseball-facility-management-software | read | SCH-18 |
| https://www.ezfacility.com/blog/best-sports-club-management-software | read | no feature cited (boilerplate, navigation or non-product content) |
| https://www.ezfacility.com/blog/best-sports-facility-management-software | read | STF-09 |
| https://www.ezfacility.com/blog/boost-client-conveniences-and-business-reach-with-memberme | read | APP-15, CHK-13, RPT-38 |
| https://www.ezfacility.com/blog/client-highlight-c2tactical-utilizes-ezfacility-digital-api | read | INT-01, INT-04, SCH-20, SSP-19 |
| https://www.ezfacility.com/blog/customer-service-one-of-the-most-important-features-of-a-software-solution | read | no feature cited (boilerplate, navigation or non-product content) |
| https://www.ezfacility.com/blog/ez-features-fixes-check-out-whats-new | read | BIL-15, CLI-05, ONB-04, POS-11, REG-06, REG-12 |
| https://www.ezfacility.com/blog/ezfacility-amazon-web-services | read | PLT-15 |
| https://www.ezfacility.com/blog/ezfacility-partners-with-playergrid-to-enhance-league-management-features | read | INT-14, LGE-29 |
| https://www.ezfacility.com/blog/ezfacility-saas-partner-deep-dive | read | CHK-15, DOC-13, INT-07, INT-10, INT-12, INT-14, PAY-11, POS-23 |
| https://www.ezfacility.com/blog/features-and-fixes-online-rentals | read | RNT-02, RNT-05, RNT-06, SCH-12 |
| https://www.ezfacility.com/blog/features-fixes-automatic-credit-card-notification-emails | read | BIL-17, PAY-06, PAY-07 |
| https://www.ezfacility.com/blog/grow-your-business-with-the-right-software-solution | read | MKT-20, SCH-20 |
| https://www.ezfacility.com/blog/gym-management-software-for-beginners | read | no feature cited (boilerplate, navigation or non-product content) |
| https://www.ezfacility.com/blog/how-a-software-solution-could-maximize-your-time | read | no feature cited (boilerplate, navigation or non-product content) |
| https://www.ezfacility.com/blog/how-to-grow-your-business-with-sports-club-management-software | read | LGE-18, RPT-40 |
| https://www.ezfacility.com/blog/how-to-succeed-with-ezfacility | read | ONB-01, RPT-01, RPT-02 |
| https://www.ezfacility.com/blog/introducing-rental-plans-prepaid-rentals-made-simple | read | DOC-14, RNT-09, RNT-12, RPT-39, SSP-20 |
| https://www.ezfacility.com/blog/make-the-most-of-ezfacility-management-software-features | read | CHK-01, CHK-05, CLS-09, CLS-10, MEM-02, MEM-19, MKT-15, RPT-01, RPT-40, SSP-20 |
| https://www.ezfacility.com/blog/matching-future-goals-with-software-solutions | read | no feature cited (boilerplate, navigation or non-product content) |
| https://www.ezfacility.com/blog/mindbody-software-alternatives | read | no feature cited (boilerplate, navigation or non-product content) |
| https://www.ezfacility.com/blog/new-ezfacility-business-features | read | CLS-08, INT-09, SSP-15, SSP-16, SSP-18 |
| https://www.ezfacility.com/blog/new-year-opportunities-at-ezfacility | read | ONB-05 |
| https://www.ezfacility.com/blog/product-update-get-ready-for-an-awesome-new-ui-experience | read | PLT-09, PLT-10, PLT-15, REG-13, REL-03 |
| https://www.ezfacility.com/blog/resources-for-ezfacility-customers | read | ONB-02, ONB-03 |
| https://www.ezfacility.com/blog/software-release-ezleagues-websites | read | LGE-18 |
| https://www.ezfacility.com/blog/software-release-ezpayments-uk-smartwaiver | read | DOC-13, INT-10, MEM-08, PAY-11 |
| https://www.ezfacility.com/blog/software-release-groups-new-ui | read | CLS-10, INT-01, INT-06, LGE-04, PLT-09, REG-01, REG-02, REG-04, REG-06, REG-13, REG-14 |
| https://www.ezfacility.com/blog/software-release-vaccine-passport | read | CHK-17, CLI-01, DOC-08, DOC-10, INT-13, MEM-08, MEM-09, PLT-01, REG-12, RES-01, SCH-20 |
| https://www.ezfacility.com/blog/targeted-marketing-campaigns-with-ezfacility | read | RPT-19 |
| https://www.ezfacility.com/blog/testimonials-and-success-stories-from-ezfacility-customers | read | no feature cited (boilerplate, navigation or non-product content) |
| https://www.ezfacility.com/blog/the-benefits-of-gym-management-software | read | INT-07, INT-13, PLT-01, REG-12 |
| https://www.ezfacility.com/blog/the-top-5-advantages-of-gun-range-management-software | read | BIL-22, CHK-16, PAY-09, PAY-11, PAY-18, PKG-01, PKG-12, STF-12 |
| https://www.ezfacility.com/blog/unlimited-email-ezfacility-benefits | read | MKT-04, MKT-06, MKT-07, MKT-20 |
| https://www.ezfacility.com/blog/updated-subgroup-inheritance-trainer-performance-report-e-mail-procedures-and-more | read | MKT-09, PKG-15, REG-02, REG-11, RPT-41, STF-11 |
| https://www.ezfacility.com/blog/use-your-computer-software-to-increase-revenue | read | RPT-17 |
| https://www.ezfacility.com/blog/using-ezfacility-management-software | read | no feature cited (boilerplate, navigation or non-product content) |
| https://www.ezfacility.com/blog/what-is-gym-management-software | read | no feature cited (boilerplate, navigation or non-product content) |
| https://www.ezfacility.com/blog/your-management-software-solution-and-your-front-desk | read | CHK-15, CHK-21, CLI-20 |

## YouTube videos (91)

| URL | Status | Features |
|---|---|---|
| https://www.youtube.com/watch?v=ByD_dq64zbo | auto-caption transcript read | no feature cited |
| https://www.youtube.com/watch?v=hHJ38JvtabY | auto-caption transcript read | RNT-09 |
| https://www.youtube.com/watch?v=ERaBaf5YWHo | auto-caption transcript read | DOC-14, FAM-03, FAM-06, ONB-03, RNT-05, RNT-09, RNT-10, RNT-11 |
| https://www.youtube.com/watch?v=OYZxws7m7NA | auto-caption transcript read | no feature cited |
| https://www.youtube.com/watch?v=AsigDH5tw2Y | auto-caption transcript read | no feature cited |
| https://www.youtube.com/watch?v=Y4iMBYJNQwY | auto-caption transcript read | no feature cited |
| https://www.youtube.com/watch?v=SzgMT6X961A | auto-caption transcript read | CHK-01, CLS-01, PLT-09, REL-03, RES-03, RES-04, RNT-01, RNT-02, RNT-03, RNT-05, RNT-06, RNT-07, SCH-01, SCH-06, SCH-07, SCH-08, SCH-09, SCH-10, SCH-12, SCH-13, SCH-14, SCH-15, SCH-19 |
| https://www.youtube.com/watch?v=wTTIiF----g | auto-caption transcript read | no feature cited |
| https://www.youtube.com/watch?v=Rfcua7ysLfk | auto-caption transcript read | no feature cited |
| https://www.youtube.com/watch?v=hoNpM1Z7XdU | auto-caption transcript read | no feature cited |
| https://www.youtube.com/watch?v=_UYH6wgN3yI | auto-caption transcript read | no feature cited |
| https://www.youtube.com/watch?v=O5yJJkKjE7A | auto-caption transcript read | no feature cited |
| https://www.youtube.com/watch?v=GgXq0rlVIzo | auto-caption transcript read | no feature cited |
| https://www.youtube.com/watch?v=uLNIb7JsjkM | auto-caption transcript read | APP-02, APP-03, APP-04, APP-05, APP-06, APP-08, APP-09, APP-10, APP-12, APP-14, APP-18, APP-19, CHK-13, MKT-16, MKT-17, PLT-13, SCH-04, SSP-03 |
| https://www.youtube.com/watch?v=7JVYZ3kxUAo | auto-caption transcript read | BIL-04, BIL-06, BIL-19, CHK-04, PKG-12, RNT-02, RNT-03, RNT-08, RNT-09, SCH-06, SCH-09, SCH-11, SCH-21 |
| https://www.youtube.com/watch?v=Rjy8ZpfIA68 | auto-caption transcript read | CHK-01, CHK-19, CLS-01, CLS-03, DOC-08, PKG-01, PKG-07, PKG-12, PLT-04, RNT-03, RNT-05, SCH-05, SCH-10 |
| https://www.youtube.com/watch?v=KAN6h9vPUiM | auto-caption transcript read | BIL-04, CHK-01, CHK-08, CHK-21, CLI-02, DOC-04, DOC-15, FAM-04, MEM-02, MEM-03, MEM-07, MEM-10, MEM-11, MEM-12, MEM-14, MEM-15, MEM-17, PLT-04, REG-12, SCH-01, STF-09 |
| https://www.youtube.com/watch?v=4y7wIlbXHO8 | auto-caption transcript read | no feature cited |
| https://www.youtube.com/watch?v=TWNQ4cTiEFs | auto-caption transcript read | CLI-01, CLI-13, CLS-03, DOC-01, DOC-03, DOC-08, DOC-15, MEM-02, MEM-04, MKT-04, MKT-05, ONB-03, PAY-01, PKG-01, PKG-12, PLT-09, REG-13, REL-03, SCH-01, SSP-12 |
| https://www.youtube.com/watch?v=jbMr4vJfJsA | no captions; title only | no feature cited |
| https://www.youtube.com/watch?v=bxCUg7Y5PsI | auto-caption transcript read | MKT-04, MKT-05, MKT-07, MKT-08 |
| https://www.youtube.com/watch?v=bHzYz6ZzMSE | auto-caption transcript read | LGE-01, LGE-03, LGE-04, LGE-05, LGE-08, LGE-18, LGE-30, LGE-31, LGE-32, LGE-33, REG-14 |
| https://www.youtube.com/watch?v=vMjkN47-Eqg | auto-caption transcript read | no feature cited |
| https://www.youtube.com/watch?v=tJ3otUgsyfA | no captions; title only | no feature cited |
| https://www.youtube.com/watch?v=RrSuB-v34Gw | auto-caption transcript read | MKT-17 |
| https://www.youtube.com/watch?v=VuUR1Y9bhjQ | auto-caption transcript read | CHK-21, CLI-01, CLI-04, DOC-08, DOC-15, INT-14, REG-01, REG-07, REG-10, REG-11, REG-12, REG-13, REG-26, RPT-27, SCH-08 |
| https://www.youtube.com/watch?v=iR4MVBspNlQ | auto-caption transcript read | BIL-02, BIL-03, BIL-10, BIL-11, BIL-19, MEM-07, MEM-10, PAY-03, PAY-04, PAY-06, RPT-03, RPT-04, RPT-06, RPT-41 |
| https://www.youtube.com/watch?v=wTcpTun-eyM | auto-caption transcript read | INT-14, PAY-11, PAY-13, PAY-15, POS-21 |
| https://www.youtube.com/watch?v=DpQMHuC98yo | auto-caption transcript read | PLT-14, REG-12 |
| https://www.youtube.com/watch?v=t85Pe_jL_h4 | auto-caption transcript read | APP-01, APP-02, APP-03, APP-06, APP-08, APP-14, APP-15, INT-14 |
| https://www.youtube.com/watch?v=5sm7eWzaQD4 | auto-caption transcript read | APP-01, APP-02, APP-03, APP-16, MEM-18, SSP-01, SSP-08, SSP-15, SSP-20 |
| https://www.youtube.com/watch?v=gjyVmvHCT1M | auto-caption transcript read | APP-03, APP-05, CHK-08 |
| https://www.youtube.com/watch?v=a7-8-cHwB8Y | auto-caption transcript read | BIL-07, CHK-08, MEM-01, MEM-03, MEM-04, MEM-10, MEM-11, MEM-12, MEM-13, MEM-14, MEM-15, MEM-16, MEM-18, MEM-19, PAY-04, RPT-01, RPT-12, RPT-13, RPT-41, SSP-10 |
| https://www.youtube.com/watch?v=j4Rn9joKKpQ | auto-caption transcript read | CLI-04, IMP-01, LGE-01, LGE-05, LGE-08, LGE-11, LGE-12, LGE-14, LGE-15, LGE-30, LGE-31, ONB-03, POS-05, REG-10, REG-12, REG-13, REG-14 |
| https://www.youtube.com/watch?v=okhjK-XBid4 | auto-caption transcript read | LGE-01, LGE-08, LGE-12, LGE-17, LGE-18, LGE-26, LGE-30, REG-10, REG-12, REG-13, REG-14, REG-26 |
| https://www.youtube.com/watch?v=Zs-8tpgvadk | auto-caption transcript read | APP-02, APP-03, APP-04, APP-05, APP-08, APP-14, APP-15, CHK-13, CHK-14, MKT-16 |
| https://www.youtube.com/watch?v=oNHKhlv39qo | auto-caption transcript read | APP-01, APP-04, APP-13, APP-15, APP-16, CLS-06, MKT-16 |
| https://www.youtube.com/watch?v=zzEUXdDPMyU | auto-caption transcript read | CLI-03, DOC-01, DOC-05, DOC-06, DOC-07, DOC-08, DOC-13, DOC-15, POS-05, REL-03 |
| https://www.youtube.com/watch?v=wnbewkZB5wQ | no captions; title only | no feature cited |
| https://www.youtube.com/watch?v=NTXRhqak3cM | auto-caption transcript read | INT-12, STF-14 |
| https://www.youtube.com/watch?v=hlGAZlxFHWg | auto-caption transcript read | CLS-08, INT-09, SSP-16 |
| https://www.youtube.com/watch?v=IM8m1sUsMdw | auto-caption transcript read | MKT-13, POS-01, REL-01, SSP-15, SSP-16 |
| https://www.youtube.com/watch?v=qUf6jPISK_8 | auto-caption transcript read | POS-17, SSP-03, SSP-16 |
| https://www.youtube.com/watch?v=7mb4gwZs9gk | auto-caption transcript read | no feature cited |
| https://www.youtube.com/watch?v=EQnsH-FILv4 | auto-caption transcript read | no feature cited |
| https://www.youtube.com/watch?v=7yHNga6cY0g | auto-caption transcript read | APP-01, APP-02, APP-03, APP-06, APP-12, APP-14, APP-16, APP-19, CHK-13, MKT-16 |
| https://www.youtube.com/watch?v=iMeRIT504Ho | auto-caption transcript read | APP-01, APP-03, APP-06, APP-09, APP-14, APP-17, APP-19, CHK-13, MKT-16, RPT-38 |
| https://www.youtube.com/watch?v=eISJe5bhK3Y | auto-caption transcript read | MKT-15, MKT-23 |
| https://www.youtube.com/watch?v=6GY9mk7HOkw | auto-caption transcript read | FIT-05, INT-15 |
| https://www.youtube.com/watch?v=_NfH6qhPWA4 | auto-caption transcript read | no feature cited |
| https://www.youtube.com/watch?v=O2q2SY5SSGw | auto-caption transcript read | no feature cited |
| https://www.youtube.com/watch?v=3VsdaSsJn-M | auto-caption transcript read | RPT-40 |
| https://www.youtube.com/watch?v=YkHOVxeiuiI | auto-caption transcript read | INT-12, STF-14 |
| https://www.youtube.com/watch?v=OlsMxb-w-gc | auto-caption transcript read | no feature cited |
| https://www.youtube.com/watch?v=A25pQjuZoQM | auto-caption transcript read | no feature cited |
| https://www.youtube.com/watch?v=jbwkXIo9rY8 | auto-caption transcript read | CLI-13, DOC-06, DOC-13, DOC-15, FAM-01, INT-10 |
| https://www.youtube.com/watch?v=qp5PjPWML-A | no captions; title only | no feature cited |
| https://www.youtube.com/watch?v=C-7p_z3_Cxs | auto-caption transcript read | CLI-03, CLI-14, DOC-01, DOC-04, DOC-05, DOC-09, FAM-01, IMP-04, PLT-16 |
| https://www.youtube.com/watch?v=edzJ6kuAvMQ | auto-caption transcript read | LGE-30, REG-26 |
| https://www.youtube.com/watch?v=qn8y8rfi-kc | auto-caption transcript read | APP-01, APP-10, APP-16, APP-17, APP-18, APP-19, RPT-38 |
| https://www.youtube.com/watch?v=lwC-tepoJ0I | auto-caption transcript read | APP-01, APP-06, APP-13, APP-14, APP-18, CHK-13 |
| https://www.youtube.com/watch?v=yGAx5uFhfP4 | no captions; title only | no feature cited |
| https://www.youtube.com/watch?v=emdiEKgqp2s | auto-caption transcript read | MKT-21 |
| https://www.youtube.com/watch?v=W4D7zQMlUfk | no captions; title only | no feature cited |
| https://www.youtube.com/watch?v=BV8yGHt8ENY | auto-caption transcript read | ONB-05, PLT-17 |
| https://www.youtube.com/watch?v=3FOVNMAz2cE | auto-caption transcript read | APP-17, BIL-15, MKT-04, POS-11, RPT-40 |
| https://www.youtube.com/watch?v=KYHio6yy5e0 | auto-caption transcript read | REG-26 |
| https://www.youtube.com/watch?v=SDO3SkkHTlY | auto-caption transcript read | DOC-10, MEM-09, MKT-14 |
| https://www.youtube.com/watch?v=pYlicKb3lng | auto-caption transcript read | MEM-11, RPT-13 |
| https://www.youtube.com/watch?v=iHdqoLdGlQI | auto-caption transcript read | CLI-11, MKT-19, RPT-41 |
| https://www.youtube.com/watch?v=j0cg9SW8Npo | auto-caption transcript read | LGE-08, LGE-12 |
| https://www.youtube.com/watch?v=RLcaxhKMDCk | auto-caption transcript read | RPT-40 |
| https://www.youtube.com/watch?v=mmFSuvVkRhk | auto-caption transcript read | no feature cited |
| https://www.youtube.com/watch?v=MBHwBgaEQOQ | auto-caption transcript read | no feature cited |
| https://www.youtube.com/watch?v=qkH3da7oeCo | auto-caption transcript read | no feature cited |
| https://www.youtube.com/watch?v=qit-_Wp4oK0 | auto-caption transcript read | no feature cited |
| https://www.youtube.com/watch?v=yADRWPQkrOY | auto-caption transcript read | no feature cited |
| https://www.youtube.com/watch?v=Dk7r65EIjnc | auto-caption transcript read | no feature cited |
| https://www.youtube.com/watch?v=sAeExGOk-dg | auto-caption transcript read | no feature cited |
| https://www.youtube.com/watch?v=unZH32QU1nc | auto-caption transcript read | CHK-01, INT-08, POS-01, POS-03, POS-11, POS-12, REG-10, REL-01 |
| https://www.youtube.com/watch?v=tqMhVWKcLfQ | auto-caption transcript read | INT-08, REG-02 |
| https://www.youtube.com/watch?v=RWvpgmD3ZI0 | auto-caption transcript read | no feature cited |
| https://www.youtube.com/watch?v=LgE60geqIO0 | no captions; title only | no feature cited |
| https://www.youtube.com/watch?v=paQew4q13JA | auto-caption transcript read | no feature cited |
| https://www.youtube.com/watch?v=PBbm0V08fts | auto-caption transcript read | REL-01, RPT-01 |
| https://www.youtube.com/watch?v=aCwF83OI-jI | auto-caption transcript read | no feature cited |
| https://www.youtube.com/watch?v=V2XHWqn6bdA | auto-caption transcript read | no feature cited |
| https://www.youtube.com/watch?v=oYfiXax435c | auto-caption transcript read | APP-14 |
| https://www.youtube.com/watch?v=yPwDWyyBD6g | auto-caption transcript read | no feature cited |
| https://www.youtube.com/watch?v=3WWymSlifsU | no captions; title only | no feature cited |
| https://www.youtube.com/watch?v=qvB6lg4bLgQ | auto-caption transcript read | no feature cited |

## App stores and reviews

| URL | Status | Used in |
|---|---|---|
| https://apps.apple.com/us/app/memberme/id969248357 | listing and 25 most recent public reviews read | APP features; `gaps-and-complaints.md` |
| https://play.google.com/store/apps/details?id=com.bottegasol.com.migym.memberme | listing read | APP features; `gaps-and-complaints.md` |
| https://www.selecthub.com/p/facility-management-software/ezfacility | read | `gaps-and-complaints.md` |
| https://www.capterra.com/p/54308/EZFacility-Club-Management/reviews/ | blocked (403); search snippets only | `gaps-and-complaints.md` |
| https://www.g2.com/products/ezfacility-ezfacility | blocked (403); search snippets only | `gaps-and-complaints.md` |
| https://www.softwareadvice.com/membership-management/ezfacility-profile/ | blocked (403); nothing usable | — |
| https://www.getapp.com/recreation-wellness-software/a/ezfacility-club-management | blocked (403); search snippets only | `gaps-and-complaints.md` |
