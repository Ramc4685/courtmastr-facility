# Building control hardware: door access and court lighting (web research, 2026-11-13)

Scope: four-court unmanned indoor facility, one entrance, about 80 members. Public web material only; prices are approximate and marked with the date seen (2026-11-13). Vendor pages are marketing and several search snippets were secondhand. Anything marked UNVERIFIED needs a quote or a datasheet.

## Recommendation

| | Primary | Budget |
|---|---|---|
| Door | UniFi Access (local controller, Door Hub plus electric strike) | Seam over a keypad lock (Schlage or Yale commercial) or igloohome offline codes |
| Lights | ControlByWeb 4-relay module driving UL-listed lighting contactors | Shelly Pro 4PM driving the same contactors |

Door: UniFi Access runs on a local controller, so entry keeps working if the internet drops, and has documented PIN and QR visitor credentials plus webhooks. Cost UNVERIFIED (no price found). Rough all-in guess: $1,000 to $2,500 hardware and install, no per-door fee seen. The API reference I found is community-maintained, so confirm against Ubiquiti's own docs first.

Door, budget: Seam is one API over many lock brands, and its pricing pages disagree (see table). Rough all-in: lock $300 to $900 plus install, plus $0 to $5 per device per month. igloohome is the cheapest to retrofit: no wiring and no internet needed.

Lights: ControlByWeb is industrial, local REST, and the relay board only drives a contactor coil, so the electrician sizes the contactor for the 277 V / high-amp load. Module about $200 to $330 (seen today) plus 4 contactors plus labour. Rough all-in guess $1,500 to $4,000 (contactor and labour figures are my estimate, UNVERIFIED).

Lights, budget: Shelly Pro 4PM is cheaper and has a local RPC API, but retailer sheets show no UL listing (UL option "No"). An inspector may refuse it. Treat it as acceptable only for low-voltage coil switching inside a listed enclosure, if the AHJ allows.

## Door access comparison

| Option | Time-bound code by API | Offline? | Entry events | Cost seen | Notes |
|---|---|---|---|---|---|
| [Seam](https://docs.seam.co/capability-guides/smart-locks/access-codes) | Yes: access code with starts_at and ends_at | Depends on the lock; native scheduling on [many brands](https://docs.seam.co/capability-guides/smart-locks/access-codes) | Webhook lock.unlocked with access_code_id for listed brands (Schlage, Yale, Salto KS, TTLock and others) | [Pricing page](https://www.seam.co/pricing): free to 3 devices, $5 or $50 per device per month; [preview page](https://www.seam.co/pricing/preview) shows credit tiers from $1.40. Conflicting. | Reads, events, webhooks do not burn credits on the credit model |
| [igloohome](https://www.igloohome.co/solutions/sports-facilities) | API issues PIN valid only for the booking window | Yes, locks work without Wi-Fi | Not confirmed for offline codes | No prices published | Offline codes via Seam also supported ([hour or day granularity](https://docs.seam.co/capability-guides/smart-locks/access-codes)); lists CourtReserve and Playbypoint partners |
| [UniFi Access](https://unifi-access-api-openapi.pages.dev/USAGE) | Visitor with PIN or QR; QR is [visitor-only](https://help.ui.com/hc/en-us/articles/17459303874327) and [auto-revokes at visit end](https://help.ui.com/hc/en-us/articles/29026995210775) | Local controller (expected; UNVERIFIED for an outage test) | [Webhooks](https://pypi.org/project/aiounifiaccess/); credential unlock events are webhook-only | No price found | Wired Door Hub plus strike or mag lock |
| [RemoteLock](https://remotelock.com/plans/) | Guest codes by REST API, OAuth, webhooks (secondhand) | Lock dependent | Webhooks | About $6 per lock per month annual, $12 Enterprise; Premium caps at 150 guest codes ([review](https://strspecialist.com/reviews/remotelock-access-control-review)) | Partner of CourtReserve and PicklePlanner |
| [Brivo](https://intercom.help/courtreserve/en/articles/10126640-brivo-integration-access-control) | API tier needed; separate API fees reported ([Acre](https://www.acresecurity.com/blog/brivo-access-control-cost)) | UNVERIFIED | UNVERIFIED | Base plans $10 to $545 per month (third party) | Heavier, commercial |
| [Kisi](https://getkisi.com/pricing/fitness) | API listed; tier unconfirmed | UNVERIFIED | UNVERIFIED | About $25 to $80 per door per month ([Vendr](https://www.vendr.com/marketplace/kisi), estimate) | Likely too pricey for one door |

Not researched: Openpath/Avigilon Alta, ButterflyMX, Salto KS direct, ProdataKey (named only as a [Playbypoint partner](https://www.prodatakey.com/single-post/pdk-and-playbypoint)).

## Lighting comparison

| Option | API | Electrical | Failure behaviour | Cost seen |
|---|---|---|---|---|
| [ControlByWeb](https://controlbyweb.com/product-tag/relays/) (X-410, WebRelay-Quad) | Open REST, MQTT, Modbus; local | Relays are 15 A class ([10-relay board](https://controlbyweb.com/?p=31813)); use contactors for high-bay circuits | Relay type and power-loss state: check datasheet (UNVERIFIED) | X-410 about $330 to $430; Quad about $200 to $230 |
| [Shelly Pro 4PM](https://us.shelly.com/blogs/documentation/shelly-pro-4pm) | Local RPC (Switch.Set, Switch.GetStatus), MQTT | 16 A per channel, 110 to 240 V; no UL found ([retailer sheet](https://shellyparts.de/en/products/shelly-pro-4pm)) | Configurable power-on state (UNVERIFIED) | Not captured |
| [Lutron](https://support.lutron.com/us/en/product/radiora3/article/networking/Lutron-s-LEAP-API-Integration-Protocol) | LIP (documented, Pro bridge) or LEAP (unpublished, can change) | Residential Caseta is not for 277 V high-bay; commercial relay panels not verified | UNVERIFIED | Not researched |
| Anolla, PodPlay | [Anolla](https://anolla.com/en/pickleball-software) advertises booking-linked lighting add-on, hardware unnamed | Reference only | Reference only | Not published |

Not researched: Leviton, Z-Wave via hub, Kasa/Tapo (consumer, low amperage), Brainboxes, DMX and 0-10 V.

## Integration shape

Door (UniFi): create visitor with start and end time; create and assign PIN (or QR); delete visitor to revoke; remote unlock endpoint on the door; webhook endpoint for entry events. Door (Seam): POST access_codes/create with device_id, code, starts_at, ends_at; delete to revoke; locks/unlock_door where supported; webhook lock.unlocked. Adapter should store the vendor code id and treat revoke as best effort with a short end time.

Lights: relay on and off per zone by local REST (ControlByWeb) or RPC (Shelly); read relay state by GET. A local device needs a reachable gateway (small always-on box or VPN); cloud access is not offered by these modules by default (UNVERIFIED for ControlByWeb cloud). Scheduling should live on the device as a fallback, pushed ahead of time, so a network drop does not leave courts dark mid-booking.

## Safety and legal checks with a licensed installer and the fire authority

1. Egress: the entrance must open from inside without a key, special knowledge or effort. Ask which code Illinois and the local fire authority enforce (IBC or NFPA 101); I could not confirm. Sources say delayed egress is restricted by occupancy ([locksmith ledger](https://www.locksmithledger.com/electronics-access-control/article/11514575/the-ins-and-outs-of-delayed-egress)).
2. Fire alarm release: electrically locked egress doors must release on alarm and power loss; electric strikes on fire-rated doors must be listed for the assembly and fail-secure ([source](https://constructionspecifier.com/code-requirements-for-doors-with-access-control/print)). Mag locks need special approvals.
3. ADA: reader height, clear opening, and operable hardware; glass storefront doors may need a strike with a panic device rather than a keypad deadbolt.
4. Emergency and exit lighting must never be on the software-controlled circuit; keep it on its own always-on circuit.
5. Lighting: use UL-listed contactors, rated enclosures, and a permit; lights should fail on, with a manual override switch, if the controller loses power or network (design intent, confirm with electrician).
6. Unmanned: ask the insurer and AHJ about occupancy, cameras, and an after-hours emergency contact.

## Open questions for the owner

Door type and material (glass storefront, steel)? Existing panic hardware and fire alarm panel? Lighting voltage, circuit count and amps per court? Is internet stable, and is a local gateway acceptable? Budget ceiling and monthly fee tolerance? Should lights stay on after the booking ends for a grace period? Who handles after-hours failures?

## Could not verify

UniFi hardware and Door Hub prices; Kisi and Brivo API and webhook details; lighting-control power-loss behaviour for any product; ControlByWeb and Shelly cloud options; Shelly UL status beyond retailer sheets; Seam's current price (sources conflict); Illinois code edition; what Anolla and PodPlay use underneath.
