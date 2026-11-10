"""PDF of an issued document: exactly the presented snapshot, then each signer's decision and the evidence
(security-baseline 8.4). The body is already sanitised to tags the renderer understands and holds no image, so
the renderer reads no file and no URL; every other value is plain text we place ourselves.
"""

import io
from collections.abc import Sequence
from dataclasses import dataclass

from fpdf import FPDF

_LABELS = {"client": "Client", "guardian": "Parent or guardian", "co_signer": "Co-signer"}
# shortcut: the built-in PDF fonts cover Latin-1 only; other characters print as "?". Embed a Unicode TTF font
# when a tenant needs non-Latin scripts.
_ASCII = str.maketrans({"‘": "'", "’": "'", "“": '"', "”": '"', "–": "-", "—": "-",
                        "…": "...", "•": "*", " ": " "})  # fmt: skip


def _latin(text: str) -> str:
    return text.translate(_ASCII).encode("latin-1", "replace").decode("latin-1")


@dataclass(frozen=True)
class Signer:
    role: str
    decision: str
    name: str
    method: str
    decided_at: str
    typed_signature: str | None = None
    signature_png: bytes | None = None
    ip: str | None = None
    user_agent: str | None = None
    witnessed_by: str | None = None


@dataclass(frozen=True)
class Snapshot:
    title: str
    organization: str
    client_name: str
    body_html: str
    acceptance_text: str
    blocks: Sequence[dict]
    document_id: str
    issued_at: str
    status: str
    content_sha256: str
    version_label: str | None = None
    version_sha256: str | None = None


def render(doc: Snapshot, signers: Sequence[Signer]) -> bytes:
    pdf = FPDF(format="Letter")
    pdf.set_title(_latin(doc.title))
    pdf.set_creator(_latin(doc.organization))
    pdf.set_auto_page_break(auto=True, margin=18)
    pdf.add_page()
    pdf.set_font("Helvetica", "B", 16)
    pdf.multi_cell(0, 8, _latin(doc.title), new_x="LMARGIN", new_y="NEXT")
    pdf.set_font("Helvetica", "", 10)
    pdf.multi_cell(0, 5, _latin(f"{doc.organization} - for {doc.client_name}"), new_x="LMARGIN", new_y="NEXT")
    pdf.ln(4)
    pdf.set_font("Helvetica", "", 11)
    pdf.write_html(_latin(doc.body_html))
    pdf.ln(4)
    pdf.set_font("Helvetica", "B", 11)
    pdf.multi_cell(0, 6, _latin(doc.acceptance_text), new_x="LMARGIN", new_y="NEXT")
    by_role = {s.role: s for s in signers}
    roles = [b["role"] for b in doc.blocks] + [r for r in by_role if r not in {b["role"] for b in doc.blocks}]
    labels = {b["role"]: b.get("label") or _LABELS[b["role"]] for b in doc.blocks}
    for role in roles:
        pdf.ln(5)
        pdf.set_font("Helvetica", "B", 11)
        pdf.cell(0, 6, _latin(labels.get(role, _LABELS[role])), new_x="LMARGIN", new_y="NEXT")
        pdf.set_font("Helvetica", "", 10)
        signer = by_role.get(role)
        if signer is None:
            pdf.cell(
                0,
                10,
                "Signature: _______________________________   Date: ______________",
                new_x="LMARGIN",
                new_y="NEXT",
            )
            continue
        if signer.signature_png:
            pdf.image(io.BytesIO(signer.signature_png), h=18)
        elif signer.typed_signature:
            pdf.set_font("Times", "I", 18)
            pdf.cell(0, 10, _latin(signer.typed_signature), new_x="LMARGIN", new_y="NEXT")
            pdf.set_font("Helvetica", "", 10)
        lines = [
            f"{signer.decision.capitalize()} by {signer.name} ({signer.method.replace('_', ' ')}) at {signer.decided_at}",
            f"IP {signer.ip or '-'}; device {(signer.user_agent or '-')[:110]}",
        ]
        if signer.witnessed_by:
            lines.append(f"Witnessed by {signer.witnessed_by}")
        for line in lines:
            pdf.multi_cell(0, 5, _latin(line), new_x="LMARGIN", new_y="NEXT")
    pdf.ln(6)
    pdf.set_font("Helvetica", "", 8)
    evidence = [
        f"Document {doc.document_id}; status {doc.status}; issued {doc.issued_at}",
        f"Content SHA-256 {doc.content_sha256}",
    ]
    if doc.version_label:
        evidence.append(f"Template {doc.version_label}; version SHA-256 {doc.version_sha256}")
    for line in evidence:
        pdf.multi_cell(0, 4, _latin(line), new_x="LMARGIN", new_y="NEXT")
    return bytes(pdf.output())
