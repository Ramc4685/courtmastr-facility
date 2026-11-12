"""Files and object storage (security-baseline 8): test_upload_rules of 8.3, removal and purge, the signed local
route, the S3 adapter and the clamd scanner. The last two run against the optional Compose profiles
(`--profile storage`, `--profile scan`) and skip when those services are not running."""

import io
import shutil
import socket
from datetime import timedelta
from uuid import uuid4

import httpx
import pytest
from PIL import Image

from app.adapters.scanner import ClamdScanner, NoopScanner
from app.core import clock
from app.core.db import tenant_session
from app.core.errors import NotFound, PermissionDenied, ValidationFailed
from app.core.settings import REPO_ROOT, get_settings
from app.modules.platform import files
from app.modules.platform.models import StoredFile
from app.ports import scanner, storage
from conftest import make_tenant

EICAR = rb"X5O!P%@AP[4\PZX54(P^)7CC)7}$EICAR-STANDARD-ANTIVIRUS-TEST-FILE!$H+H*"
STAFF = ("staff", None)


def png(width: int = 4, height: int = 4, mode: str = "RGB") -> bytes:
    out = io.BytesIO()
    Image.new(mode, (width, height)).save(out, "PNG")
    return out.getvalue()


def stored(tenant, data: bytes = b"%PDF-1.4 test", *, purpose: str = "test.doc", **kw) -> StoredFile:
    with tenant_session(tenant.id) as session:
        return files.store(session, data, purpose=purpose, content_type=files.PDF, uploaded_by=STAFF, **kw)


def _up(port: int) -> bool:
    with socket.socket() as sock:
        sock.settimeout(0.5)
        return sock.connect_ex(("127.0.0.1", port)) == 0


class _EicarScanner:
    def scan(self, data: bytes) -> str | None:
        return "Eicar-Test-Signature" if EICAR in data else None


@pytest.fixture
def eicar_scanner():
    scanner.configure(_EicarScanner())
    yield
    scanner.configure(NoopScanner())


# --- test_upload_rules (8.3) ----------------------------------------------------------------------------------


def test_type_confusion_html_named_as_an_image_is_refused():
    with pytest.raises(ValidationFailed) as refused:
        files.clean(b"<html><script>alert(1)</script></html>", "image/jpeg", allowed=(files.JPEG,), max_bytes=1024)
    assert refused.value.code == "file-type-mismatch"
    with pytest.raises(ValidationFailed):  # real PNG bytes declared as JPEG
        files.clean(png(), files.JPEG, allowed=(files.JPEG, files.PNG), max_bytes=10_000)


def test_oversize_is_refused():
    with pytest.raises(ValidationFailed) as refused:
        files.clean(b"%PDF-" + b"x" * 2000, files.PDF, allowed=(files.PDF,), max_bytes=1000)
    assert refused.value.code == "file-too-large"


def test_decompression_bomb_image_is_refused():
    bomb = png(10_000, 10_000, mode="1")  # 100 megapixels in a few kilobytes
    assert len(bomb) < 100_000
    with pytest.raises(ValidationFailed) as refused:
        files.clean(bomb, files.PNG, allowed=(files.PNG,), max_bytes=10 * 2**20)
    assert refused.value.code == "file-too-large"


def test_eicar_is_refused_when_the_scanner_is_on(tenant, eicar_scanner):
    with pytest.raises(ValidationFailed) as refused:
        stored(tenant, b"%PDF-1.4 " + EICAR)
    assert refused.value.code == "file-infected"
    assert storage.keys(tenant.id) == []  # nothing written


class _DownScanner:
    def scan(self, data: bytes) -> str | None:
        raise RuntimeError("clamd scan failed: INSTREAM size limit exceeded")  # an outage or StreamMaxLength


def test_system_generated_files_store_with_the_scanner_down_and_user_uploads_do_not(tenant):
    """An export zip above clamd's stream limit, or a clamd outage, must not dead-letter exports and reports:
    bytes the system made from its own data skip the scan. A person's upload is still refused (fail-closed)."""
    from app.core.db.session import tenant_session

    scanner.configure(_DownScanner())
    try:
        with tenant_session(tenant.id) as session:
            row = files.store(
                session, b"PK\x05\x06" + b"\0" * 18, purpose="tenant_export", content_type="application/zip",
                uploaded_by=("system", None), generated=True,
            )  # fmt: skip
            assert row.status == "ready"
        with pytest.raises(RuntimeError, match="clamd"):
            stored(tenant, b"%PDF-1.4 a person's scan")
    finally:
        scanner.configure(NoopScanner())


def test_traversal_filename_is_metadata_only(tenant):
    row = stored(tenant, original_name='../../etc/pass"wd')
    assert row.original_name == "pass_wd"
    assert row.object_key == f"t/{tenant.id}/files/{row.id}"
    assert files.safe_name("..\\..\\boot.ini") == "boot.ini" and files.safe_name("..") is None
    with pytest.raises(ValueError):
        storage.get(tenant.id, f"t/{tenant.id}/../{uuid4()}/files/x")


def test_cross_tenant_file_id_is_not_found(tenant):
    row = stored(tenant)
    other = make_tenant()
    with tenant_session(other.id) as session:
        for call in (
            lambda: files.read(session, row.id),
            lambda: files.load(session, row.id, purpose="test.doc"),
            lambda: files.download_url(session, row.id),
            lambda: files.remove(session, row.id),
        ):
            with pytest.raises(NotFound):
                call()
    with pytest.raises(ValueError):  # and the port refuses the other tenant's key outright
        storage.get(other.id, row.object_key)


def test_wrong_purpose_and_pending_files_cannot_be_referenced(tenant):
    row = stored(tenant)
    with tenant_session(tenant.id) as session:
        assert files.load(session, row.id, purpose="test.doc").id == row.id
        with pytest.raises(NotFound):
            files.load(session, row.id, purpose="client_photo")
        pending = StoredFile(
            id=uuid4(), object_key=f"t/{tenant.id}/files/p", purpose="test.doc", content_type=files.PDF,
            size_bytes=0, status="pending", uploaded_by_type="staff",
        )  # fmt: skip
        session.add(pending)
        session.flush()
        with pytest.raises(NotFound):
            files.load(session, pending.id, purpose="test.doc")


def test_signed_route_serves_once_signed_and_refuses_expired_or_forged(client, tenant):
    row = stored(tenant, original_name="report.pdf")
    with tenant_session(tenant.id) as session:
        url = files.download_url(session, row.id)
    path = url.removeprefix(get_settings().app.web_base_url)
    assert path.startswith(f"/api/v1/files/{tenant.id}/{row.id}?exp=")

    served = client.get(path)
    assert served.status_code == 200 and served.content == b"%PDF-1.4 test"
    assert served.headers["content-disposition"] == 'attachment; filename="report.pdf"'
    assert served.headers["x-content-type-options"] == "nosniff"
    assert served.headers["content-type"] == files.PDF

    assert client.get(path.replace("sig=", "sig=0")).status_code == 404
    assert client.get(path.replace(str(row.id), str(uuid4()))).status_code == 404  # signature binds the id
    with clock.freeze(clock.now() + timedelta(minutes=6)):
        expired = client.get(path)
    assert expired.status_code == 403 and expired.json()["code"] == "link-expired"


def test_image_renditions_are_served_inline(client, tenant):
    data, kind = files.clean(png(), files.PNG, allowed=(files.PNG,), max_bytes=10_000)
    with tenant_session(tenant.id) as session:
        row = files.store(session, data, purpose="tenant_logo", content_type=kind, uploaded_by=STAFF, public=True)
        url = files.download_url(session, row.id)
    assert row.object_key == f"t/{tenant.id}/public/{row.id}"
    served = client.get(url.removeprefix(get_settings().app.web_base_url))
    assert served.status_code == 200 and served.headers["content-disposition"].startswith("inline;")


def test_check_signature_errors():
    tenant_id, file_id, exp = uuid4(), uuid4(), int(clock.now().timestamp()) - 1
    with pytest.raises(NotFound):
        files.check_signature(tenant_id, file_id, exp, "forged")
    with pytest.raises(PermissionDenied):
        files.check_signature(tenant_id, file_id, exp, files._signature(tenant_id, file_id, exp))


# --- removal and purge -----------------------------------------------------------------------------------------


def test_remove_purges_the_row_and_deletes_bytes_after_commit(tenant):
    row = stored(tenant)
    with tenant_session(tenant.id) as session:
        files.remove(session, row.id)
        assert storage.get(tenant.id, row.object_key)  # still there until commit
    assert storage.keys(tenant.id) == []
    with tenant_session(tenant.id) as session:
        assert session.get(StoredFile, row.id).status == "purged"
        files.remove(session, row.id)  # idempotent
        with pytest.raises(NotFound):
            files.read(session, row.id)


def test_remove_rolled_back_keeps_the_file(tenant):
    row = stored(tenant)
    with pytest.raises(RuntimeError), tenant_session(tenant.id) as session:
        files.remove(session, row.id)
        raise RuntimeError("caller failed")
    with tenant_session(tenant.id) as session:
        assert files.read(session, row.id)[1] == b"%PDF-1.4 test"


def test_purge_deletes_purged_bytes_and_reports_orphans(tenant):
    keep, gone = stored(tenant), stored(tenant)
    with tenant_session(tenant.id) as session:
        files.remove(session, gone.id)
    storage.put(tenant.id, gone.object_key, b"left behind by a failed delete")
    orphan = storage.object_key(tenant.id, uuid4())
    storage.put(tenant.id, orphan, b"rolled-back store")

    assert files.purge_files.fn(str(tenant.id)) == {"deleted": 1, "orphans": [orphan]}  # the queued actor, inline
    assert sorted(storage.keys(tenant.id)) == sorted([keep.object_key, orphan])
    assert files.purge_files.fn(str(tenant.id)) == {"deleted": 0, "orphans": [orphan]}  # idempotent


def test_purge_is_on_the_hourly_clock():
    from app.scheduler import EVERY_HOUR

    assert "purge_files" in EVERY_HOUR


# --- configuration ----------------------------------------------------------------------------------------------


def test_production_refuses_the_noop_scanner(tmp_path, monkeypatch, deploy_secrets):
    shutil.copy(REPO_ROOT / "config" / "app.yaml", tmp_path / "app.yaml")
    overlay = tmp_path / "app.production.yaml"
    base = "auth: {cookie_secure: true}\nemail: {log_links: false}\npayments: {provider: none}\napi: {exposed_directly: true}\n"
    monkeypatch.setenv("FH_CONFIG_DIR", str(tmp_path))
    monkeypatch.setenv("FH_ENV", "production")
    overlay.write_text(base)
    with pytest.raises(RuntimeError, match="storage.scanner"):
        get_settings.__wrapped__()
    overlay.write_text(base + "storage: {scanner: clamd}\n")
    assert get_settings.__wrapped__().storage.scanner == "clamd"


# --- adapters against the optional Compose services ---------------------------------------------------------------


@pytest.mark.skipif(not _up(59000), reason="S3 service not running: docker compose --profile storage up -d s3")
def test_s3_adapter_against_the_compose_bucket(monkeypatch):
    from app.adapters.s3_storage import S3Storage

    monkeypatch.setenv("FH_S3_ACCESS_KEY_ID", "dev-minio")
    monkeypatch.setenv("FH_S3_SECRET_ACCESS_KEY", "dev-minio-secret")
    s3 = S3Storage(bucket="fh-test", endpoint_url="http://127.0.0.1:59000", region="us-east-1", path_style=True)
    if "fh-test" not in [b["Name"] for b in s3.client.list_buckets()["Buckets"]]:
        s3.client.create_bucket(Bucket="fh-test")
    prefix = f"t/{uuid4()}/"
    key = f"{prefix}files/{uuid4()}"
    s3.put(key, b"%PDF-1.4 bucket")
    assert s3.get(key) == b"%PDF-1.4 bucket" and list(s3.keys(prefix)) == [key]

    url = s3.url(key, expires_in=300, content_type=files.PDF, disposition='attachment; filename="a.pdf"')
    served = httpx.get(url)
    assert served.status_code == 200 and served.content == b"%PDF-1.4 bucket"
    assert served.headers["content-disposition"] == 'attachment; filename="a.pdf"'
    forged = url.rsplit("X-Amz-Signature=", 1)[0] + "X-Amz-Signature=" + "0" * 64
    assert httpx.get(forged).status_code == 403
    assert httpx.get(url.split("?")[0]).status_code == 403  # unsigned: the bucket is private

    s3.delete(key)
    s3.delete(key)  # a missing key is not an error
    assert list(s3.keys(prefix)) == []


@pytest.mark.skipif(not _up(53310), reason="clamd not running: docker compose --profile scan up -d clamav")
def test_clamd_scanner_finds_eicar():
    clamd = ClamdScanner("127.0.0.1", 53310)
    try:
        hit = clamd.scan(EICAR)
    except (RuntimeError, OSError) as exc:  # the container answers before its signatures have loaded
        pytest.skip(f"clamd not ready: {exc}")
    assert hit and "eicar" in hit.lower()
    assert clamd.scan(b"%PDF-1.4 clean" * 10_000) is None  # several INSTREAM chunks
