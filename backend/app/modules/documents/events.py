"""Events the documents context emits (overview section 2). Ids only, no PII."""

from typing import ClassVar, Literal
from uuid import UUID

from app.core.events import Event


class _DocumentEvent(Event):
    aggregate_type: ClassVar[str] = "client_document"
    client_document_id: UUID
    client_id: UUID


class DocumentSent(_DocumentEvent):
    type: Literal["documents.document.sent"] = "documents.document.sent"


class DocumentAccepted(_DocumentEvent):
    type: Literal["documents.document.accepted"] = "documents.document.accepted"


class DocumentDeclined(_DocumentEvent):
    type: Literal["documents.document.declined"] = "documents.document.declined"


class DocumentExpired(_DocumentEvent):
    type: Literal["documents.document.expired"] = "documents.document.expired"
