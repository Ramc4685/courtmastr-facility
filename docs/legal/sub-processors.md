# Courtmastr Facility Sub-processors

DRAFT, not legal advice, pending attorney review. Last updated: 2026-11-13.

This list names the third parties that process Customer Personal Data for Marvy Labs LLC in providing Courtmastr Facility, as referred to in the Data Processing Agreement. The Service is not live yet, so the list shows the expected setup at launch. [TO CONFIRM: re-check every row against the deployed environment before the first Customer signs.]

## 1. Current list

| Sub-processor | Purpose | Data categories | Location |
|---|---|---|---|
| Amazon Web Services, Inc. | Hosting of the application and database, object storage for uploaded files and exports, backups, and email delivery through Amazon SES | All Customer Data stored in the Service; email addresses and message content for outgoing email | United States [TO CONFIRM: AWS region] |
| Stripe, Inc. | Card and bank payment processing, stored payment methods, refunds, disputes | Payer name and contact details, payment method details entered in Stripe-hosted fields (Stripe receives them directly), amounts, payment status | United States (Stripe may process data in other countries under its own terms) |
| Expo (650 Industries, Inc.) with Apple Push Notification service and Google Firebase Cloud Messaging | Delivery of push notifications to the mobile app | Device push token, a generic notification title and a record identifier. Notification payloads do not carry names or health information | United States (Apple and Google process notifications globally under their terms) |

[TO CONFIRM: confirm the legal entity names and any additional Expo or Google services in use.]

## 2. Connected only if the Customer turns them on

These are not Sub-processors of Marvy Labs for the connection. The Customer directs the transfer, and the provider's terms apply. They are listed for transparency.

| Service | Purpose | Data categories | Location |
|---|---|---|---|
| Intuit QuickBooks | Accounting export of invoices, payments and related totals | Customer and invoice data the Customer chooses to send | United States |
| Zoom | Creating virtual session meetings for programs | Session titles, times and participant names and emails where the Customer sends them | United States |

## 3. To be decided

[TO CONFIRM: door entry and lighting control hardware or controller cloud (vendor, data sent, location), an SMS provider if text messages are offered, an error tracking or monitoring provider, and any customer support tool. Add each to the table above before it receives Personal Data.]

## 4. Notice of changes

4.1 We will give Customers at least [TO CONFIRM: 30] days' notice before adding or replacing a Sub-processor that will process Personal Data.

4.2 Notice will be by email to the Account owner (and any security or privacy contact the Customer has registered) and by updating this page with a new "Last updated" date and the effective date of the change.

4.3 A Customer may object in writing within [TO CONFIRM: 15] days of the notice on reasonable data-protection grounds. We will work with the Customer to address the concern. If we cannot, the options in Section 7.3 of the Data Processing Agreement apply.

4.4 We may replace a Sub-processor with shorter notice in an emergency, for example when a provider fails or a security issue requires it. We will tell Customers as soon as we can and the objection right still applies.

## 5. Our commitments

We have a written agreement with each Sub-processor that requires data protection and security terms in substance no less protective than our Data Processing Agreement. We remain responsible for their performance. We review this list at least [TO CONFIRM: every 6 months].

## 6. Contact

Questions or objections: [TO CONFIRM: privacy contact email].
