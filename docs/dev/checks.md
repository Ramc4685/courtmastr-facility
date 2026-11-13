# Contract and static checks

Five checks beyond lint and the test suite, added in Phase 8 chip K3. Each one has a make target, a CI step and a
single place to record an exception. The rule for every exception list: shrink it, never grow it, and give every
line a reason.

| Check | Run | Catches | Exceptions live in |
|---|---|---|---|
| mypy | `make typecheck` | type errors in `backend/app` (tests excluded) | `backend/pyproject.toml` `[[tool.mypy.overrides]]` |
| import-linter | `make boundaries` | a context importing one it may not call (overview section 2) | `ignore_imports` per contract, `backend/pyproject.toml` |
| API breaking-change diff | `make api-diff` | removed or narrowed API surface against the merge base with `main` | `docs/api/breaking-allow.txt` |
| Schemathesis (small) | inside `make test` | 5xx and responses that break their own schema | `KNOWN_FAILURES` in `backend/tests/test_contract_schemathesis.py` |
| Secret scan (gitleaks 8.30.1) | CI job `secrets`; locally `gitleaks git --redact .` | a credential anywhere in the history | `.gitleaksignore` (one fingerprint per reviewed example value or false positive) |
| Schemathesis (long) | `make contract` | the same, over every operation with more examples | same list |

## mypy

Lenient by default, strict (`disallow_untyped_defs`, `disallow_any_generics`, `warn_return_any` and friends) for
`app.core.*` and `app.ports.*`. Two override blocks hold the debt: core files that do not yet pass the strict
flags (they keep the other checks), and files that report errors even leniently (`ignore_errors`; mostly Optional
narrowing and `Literal` values read from SQLAlchemy rows). To tighten a file, delete its line and fix what mypy
then says. To add an exception, add the module to the right list; never put `# type: ignore` in domain code.
Pytest modules under `app/modules/*/tests` are not checked.

## import-linter

One `forbidden` contract per context, generated from the "May call" column of the overview's context table: it
lists the contexts that column omits. `integrations` may import any service, so it has no context contract. Two
extra contracts: `core` and `ports` import no module or adapter, and modules import no adapter (they use ports).
Contracts check direct imports only (`allow_indirect_imports`), and pytest modules are ignored. To allow a new
import, change the "May call" column in the overview first, then the contract; to record a known breach add an
`ignore_imports` line with a trailing `# reason`. Not enforced: "other contexts' top-level package only"
(import-linter cannot express it); nine deep imports exist, listed in the K3 status note.

## API diff

`oasdiff breaking` between `backend/openapi.json` at the merge base with `main` (`API_DIFF_BASE` overrides the
ref) and the working copy, failing on errors. Install oasdiff 1.37.0 locally (`brew install oasdiff`); CI pins
the same release and checks its SHA-256. To allow a breaking change, add the line oasdiff printed, in the form `METHOD /path message`,
to `docs/api/breaking-allow.txt` with a reason comment, and have it reviewed.

**What the diff cannot see.** Cookies, CSRF headers and rate limits are not in the OpenAPI document. S1's session
contract change (one `__Host-fh_session` cookie, the `__Host-fh_pre` login-CSRF cookie, `X-CSRF-Token` on browser
writes) shows up in the diff only as added endpoints, so it needs no allow line; it is recorded in
`docs/status/phase8-s1-signin.md`.
The diff also rates a removed request property as a warning, not an error. Our request schemas reject unknown
fields, so a client that still sends the property gets a 422: treat that warning as a breaking change and say so in
`CHANGELOG.md` (the `currency` removal from `PATCH /tenant` is the example).

## Schemathesis

`backend/tests/test_contract_schemathesis.py` drives the live schema in process as a fresh tenant's owner and
asserts no 5xx and schema-conforming bodies. Sign-in, refresh and password routes are skipped because they would
end the session the run uses. The default run covers a fixed 1-in-8 sample of operations with one example each
(stable hash, derandomised); a full sweep is about 12 CPU-minutes per example, so it lives behind `make contract`
(`FH_CONTRACT_EXAMPLES`, default 25, sample 1). Random path ids mean most calls end in 404: the test finds crashes
on malformed input, not workflow bugs. A found 500 is fixed in the same change; if it is in a context you may
not touch, add `"METHOD /path": "reason"` to `KNOWN_FAILURES` (the test then xfails that operation).

## Supply chain in CI

Every action in `.github/workflows/ci.yml` is pinned to a full commit SHA with its tag in a comment; to upgrade,
resolve the new tag with `gh api repos/<owner>/<repo>/git/ref/tags/<tag>` (an annotated tag needs a second
`git/tags/<sha>` call for its commit). Downloaded tools (oasdiff, gitleaks) are pinned releases whose SHA-256 is
checked before use (the digest is on the release asset: `gh api repos/<owner>/<repo>/releases/tags/<tag>`). The
`mobile` job runs the app's lint, typecheck and Jest suite. No job needs a repository secret.
