# Bundled auth data

`common-passwords.txt`: the 10,000 most common passwords, one per line, refused by
`passwords.check_policy` (compared case-insensitively). Copied unchanged on 2026-11-11 from SecLists,
`Passwords/Common-Credentials/10k-most-common.txt`
(https://github.com/danielmiessler/SecLists, commit on `master` at that date), MIT licence (see
the LICENSE file in that repository). Loaded from disk once per process; nothing is fetched at runtime.
