"""TOTP second factor and recovery codes (ADR 0002 section 6, security-baseline 5.1, chip S2).

RFC 6238 through pyotp: 30-second steps, 6 digits, one step of drift either way. The last accepted step is
stored, so a code (or an earlier one) is never accepted twice. The secret is sealed with core.crypto under the
tenant id and leaves this module only once, as the otpauth URI shown at enrolment. Sign-in, step-up, lockout
and audit live in platform.auth, which calls the functions here.
"""

import hmac
import secrets

import pyotp
from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session

from app.core import clock, crypto
from app.core.auth import CATALOGUE
from app.core.errors import Conflict
from app.core.settings import get_settings
from app.modules.platform import rbac
from app.modules.platform.models import Identity, MfaFactor, MfaPolicy, MfaRecoveryCode, StaffUser, Tenant

_STEP_SEC = 30
_DRIFT = 1
RECOVERY_CODE_COUNT = 10
_ALPHABET = "abcdefghjkmnpqrstuvwxyz23456789"  # no 0/o, 1/l/i: read off paper
_PRIVILEGED_ROLES = ("owner", "admin")  # owner decision 3, plus any holder of a `+` key (ADR 0002 section 6)


def factor(session: Session, identity_id, *, lock: bool = False) -> MfaFactor | None:
    stmt = select(MfaFactor).where(MfaFactor.identity_id == identity_id, MfaFactor.kind == "totp")
    return session.scalar(stmt.with_for_update() if lock else stmt)


def confirmed_factor(session: Session, identity_id, *, lock: bool = False) -> MfaFactor | None:
    row = factor(session, identity_id, lock=lock)
    return row if row is not None and row.confirmed_at is not None else None


def is_required(session: Session, identity: Identity) -> bool:
    """Members may enrol but are never required to (ADR 0002 section 6). Staff follow the tenant policy."""
    if identity.kind != "staff":
        return False
    policy = session.get_one(Tenant, identity.tenant_id).staff_mfa_policy
    if policy == MfaPolicy.ALL:
        return True
    if policy != MfaPolicy.PRIVILEGED:
        return False
    staff = session.scalar(select(StaffUser).where(StaffUser.identity_id == identity.id))
    if staff is None:
        return False
    if staff.role.system_key in _PRIVILEGED_ROLES:
        return True
    # A cloned role or a per-user override can carry `+` keys too: whoever may use them must have a factor.
    held = rbac.effective_permissions(session, staff)
    return any(CATALOGUE[key].needs_step_up for key in held if key in CATALOGUE)


def start_enrolment(session: Session, identity: Identity) -> tuple[str, str]:
    """A fresh unconfirmed secret (replacing an earlier unconfirmed one). Returns (secret, otpauth URI)."""
    row = factor(session, identity.id, lock=True)
    if row is not None and row.confirmed_at is not None:
        raise Conflict("Two-step verification is already on. Turn it off first.", code="mfa-already-enrolled")
    secret = pyotp.random_base32()  # 160 bits, the RFC 4226 recommendation
    sealed = crypto.encrypt(secret, identity.tenant_id)
    if row is None:
        session.add(MfaFactor(identity_id=identity.id, kind="totp", secret_encrypted=sealed))
    else:
        row.secret_encrypted, row.last_used_step = sealed, None
    session.flush()
    issuer = get_settings().app.display_name
    return secret, pyotp.TOTP(secret).provisioning_uri(name=identity.email, issuer_name=issuer)


def match_totp(row: MfaFactor, code: str) -> bool:
    """True, and remembered, when `code` is right for the current step or one either side and newer than the
    last one used. Call with the row locked (factor(lock=True)) so two requests cannot both spend one code."""
    code = code.strip().replace(" ", "")
    if len(code) != 6 or not code.isdigit():
        return False
    totp = pyotp.TOTP(crypto.decrypt(row.secret_encrypted, row.tenant_id))
    now_step = int(clock.now().timestamp()) // _STEP_SEC
    last = row.last_used_step if row.last_used_step is not None else -1
    for step in range(max(now_step - _DRIFT, last + 1), now_step + _DRIFT + 1):
        if hmac.compare_digest(totp.at(step * _STEP_SEC), code):
            row.last_used_step = step
            return True
    return False


def _normalise(code: str) -> str:
    return code.strip().lower().replace("-", "").replace(" ", "")


def _code_hash(identity_id, code: str) -> str:
    """Keyed and bound to the identity: a leaked table cannot be brute-forced offline or matched across users."""
    return crypto.mac(f"mfa-recovery:{identity_id}:{_normalise(code)}")


def use_recovery_code(session: Session, identity_id, code: str) -> bool:
    """Spend one unused recovery code; True when it was one."""
    row = session.scalar(
        select(MfaRecoveryCode)
        .where(
            MfaRecoveryCode.identity_id == identity_id,
            MfaRecoveryCode.code_hash == _code_hash(identity_id, code),
            MfaRecoveryCode.used_at.is_(None),
        )
        .with_for_update()
    )
    if row is None:
        return False
    row.used_at = clock.now()
    return True


def verify(session: Session, row: MfaFactor, code: str) -> str | None:
    """A confirmed factor's TOTP code, or a recovery code in its place: "totp", "recovery" or None."""
    if match_totp(row, code):
        return "totp"
    if use_recovery_code(session, row.identity_id, code):
        return "recovery"
    return None


def new_recovery_codes(session: Session, identity_id) -> list[str]:
    """Ten fresh codes replacing every earlier one. The plain codes exist only in the return value."""
    session.execute(delete(MfaRecoveryCode).where(MfaRecoveryCode.identity_id == identity_id))
    codes = ["".join(secrets.choice(_ALPHABET) for _ in range(10)) for _ in range(RECOVERY_CODE_COUNT)]
    for code in codes:
        session.add(MfaRecoveryCode(identity_id=identity_id, code_hash=_code_hash(identity_id, code)))
    session.flush()
    return [f"{code[:5]}-{code[5:]}" for code in codes]


def remaining_recovery_codes(session: Session, identity_id) -> int:
    count = session.scalar(
        select(func.count())
        .select_from(MfaRecoveryCode)
        .where(MfaRecoveryCode.identity_id == identity_id, MfaRecoveryCode.used_at.is_(None))
    )
    return count or 0


def remove(session: Session, identity_id) -> None:
    session.execute(delete(MfaRecoveryCode).where(MfaRecoveryCode.identity_id == identity_id))
    session.execute(delete(MfaFactor).where(MfaFactor.identity_id == identity_id))
