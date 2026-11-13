## backend/app/modules/memberships/README.md

- [wording] README:47-48 lists "the card-save modes at sale" as not built without saying the setting exists. `membership_settings.online_card_save_mode` (`always | when_nothing_due | ask`) is stored and exposed (`backend/app/modules/memberships/models.py:244,253`, `schemas.py:171,183`), but nothing in `service.py` reads it. Line 54 already uses a "stored only" note for `freeze_resume_invoice_mode`; this setting needs the same note.
