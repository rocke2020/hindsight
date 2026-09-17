# Hindsight Retain Inputs: Text, Images, Files, and Documents

## Overview

Hindsight's regular retain endpoint accepts one or more memory items. Each item's `content` is either a plain string or an ordered list of `text`, `image`, and `file` blocks. Images use the `image` block; PDFs, DOCX files, spreadsheets, and other non-image attachments use the `file` block. There is no `document` content-block type: a Hindsight document is created by assigning the item a stable `document_id`.

Use inline blocks when the position of an image or file relative to surrounding text matters to extraction. Use the separate file-retain endpoint when a whole PDF or office file should be parsed into Markdown and retained as its own document.

The authoritative request models are `hindsight-api-slim/hindsight_api/api/http.py` (`MemoryItem`, `TextContentBlock`, `ImageContentBlock`, and `FileContentBlock`).

## 1. Retain API

The REST endpoint is:

```http
POST /v1/default/banks/{bank_id}/memories
Content-Type: application/json
```

The top-level request contains `items` and an optional asynchronous-processing flag:

```json
{
  "items": [
    {
      "content": "Alice prefers morning appointments.",
      "document_id": "alice-profile",
      "context": "User profile",
      "timestamp": "unset",
      "metadata": {"source": "profile-service", "revision": "42"},
      "tags": ["user:alice"],
      "update_mode": "replace"
    }
  ],
  "async": false
}
```

The maintained Python client exposes the same operation as `client.retain(...)` for one item and `client.retain_batch(...)` for multiple items.

## 2. Types Accepted Inside `content`

| Input | Representation | Meaning |
| --- | --- | --- |
| Plain text | `"content": "..."` | Ordinary prose, Markdown, a transcript, or serialized JSON/JSONL |
| Inline text | `{"type": "text", "text": "..."}` | Text positioned before, between, or after attachments |
| Inline image | `{"type": "image", "source": {...}}` | An image passed to the multimodal retain model |
| Inline PDF or other non-image file | `{"type": "file", "source": {...}, "filename": "..."}` | A file passed directly to the multimodal retain model |

An attachment source currently has this shape:

```json
{
  "type": "base64",
  "media_type": "image/png",
  "data": "BASE64_ENCODED_BYTES_WITHOUT_A_DATA_URI_PREFIX"
}
```

Only `base64` is supported as the attachment source type. `data` must contain the Base64 payload alone, not a string beginning with `data:image/png;base64,`.

Common media types include:

| File | Block type | `media_type` |
| --- | --- | --- |
| PNG | `image` | `image/png` |
| JPEG | `image` | `image/jpeg` |
| PDF | `file` | `application/pdf` |
| DOCX | `file` | `application/vnd.openxmlformats-officedocument.wordprocessingml.document` |
| XLSX | `file` | `application/vnd.openxmlformats-officedocument.spreadsheetml.sheet` |

Hindsight accepts any syntactically valid MIME type at ingress, but the configured model provider decides whether it can interpret that format.

## 3. Real Example: Retain an Ordinary Text Document

A document is ordinary string content plus a stable `document_id`; it is not a block inside `content`.

```python
from pathlib import Path

from hindsight_client import Hindsight


profile_path = Path("./alice-medical-profile.md")
if not profile_path.is_file():
    raise FileNotFoundError(profile_path)

client = Hindsight(base_url="http://localhost:8888")

response = client.retain(
    bank_id="alice",
    document_id="user-medical-profile",
    content=profile_path.read_text(encoding="utf-8"),
    context="Medical profile copied from the authoritative profile service",
    metadata={"source": "profile-service", "revision": "42"},
    tags=["user:alice", "source:medical-profile"],
    update_mode="replace",
)

print(response.success)
```

Reusing `user-medical-profile` with `update_mode="replace"` makes the new body the current document version. Use `append` only when the document is intentionally growing and the server retains document text.

## 4. Real Example: Interleave Text, an Image, and a PDF

This example reads real local files, Base64-encodes their bytes, and places them beside the prose that explains them.

```python
import base64
from pathlib import Path

from hindsight_client import Hindsight


def encode_file(path: Path) -> str:
    if not path.is_file():
        raise FileNotFoundError(path)
    return base64.b64encode(path.read_bytes()).decode("ascii")


screenshot_path = Path("./vpn-error.png")
policy_path = Path("./vpn-policy.pdf")

client = Hindsight(base_url="http://localhost:8888")

response = client.retain(
    bank_id="alice",
    document_id="vpn-support-case-123",
    context="Support case containing a VPN error screenshot and the applicable policy",
    update_mode="replace",
    content=[
        {
            "type": "text",
            "text": "The user sees this error after clicking Connect:",
        },
        {
            "type": "image",
            "source": {
                "type": "base64",
                "media_type": "image/png",
                "data": encode_file(screenshot_path),
            },
        },
        {
            "type": "text",
            "text": "Use the following policy document to determine the correct remediation:",
        },
        {
            "type": "file",
            "source": {
                "type": "base64",
                "media_type": "application/pdf",
                "data": encode_file(policy_path),
            },
            "filename": policy_path.name,
        },
    ],
)

print(response.success)
```

The order is meaningful: the extraction model receives the screenshot after the sentence that introduces it and the PDF after the sentence that explains its role.

## 5. Real Example: Retain a DOCX Inline

DOCX uses the same `file` block as PDF; only its MIME type and filename differ.

```python
import base64
from pathlib import Path

from hindsight_client import Hindsight


document_path = Path("./employee-handbook.docx")
document_bytes = document_path.read_bytes()

client = Hindsight(base_url="http://localhost:8888")

response = client.retain(
    bank_id="company-knowledge",
    document_id="employee-handbook-inline",
    context="The attached file is the employee handbook",
    content=[
        {
            "type": "text",
            "text": "Extract the policies stated in this handbook:",
        },
        {
            "type": "file",
            "source": {
                "type": "base64",
                "media_type": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
                "data": base64.b64encode(document_bytes).decode("ascii"),
            },
            "filename": document_path.name,
        },
    ],
)

print(response.success)
```

Whether this succeeds depends on whether the configured provider can consume DOCX as a model input. Hindsight validates the MIME syntax, stores the bytes, and lets the provider accept or reject the actual format.

## 6. Whole-File Parsing Is a Separate Path

Inline `file` means that the attachment stays in position and is presented directly to the multimodal extraction model. It is different from `retain_files`, which uploads a whole file, converts it to Markdown through a configured parser, and retains the converted result as its own document.

Use whole-file parsing for a standalone PDF, DOCX, spreadsheet, image requiring OCR, or audio file requiring transcription:

```python
from pathlib import Path

from hindsight_client import Hindsight


client = Hindsight(base_url="http://localhost:8888")

response = client.retain_files(
    bank_id="company-knowledge",
    files=[Path("./employee-handbook.pdf")],
    files_metadata=[
        {
            "document_id": "employee-handbook",
            "context": "Current employee handbook",
            "metadata": {"source": "people-operations"},
            "tags": ["policy", "people-operations"],
        }
    ],
)

print(response.operation_ids)
```

File conversion always runs asynchronously. Poll the returned operation ID before treating the document as available for recall.

## 7. Conversation Turns

Conversation turns are not another content-block type. Serialize the turns as a string and retain the full conversation as one document. Hindsight recognizes JSON arrays and JSONL during chunking and preserves complete turn or line boundaries when they fit the configured structured-chunk limit.

```python
import json

from hindsight_client import Hindsight


turns = [
    {"role": "user", "content": "I prefer morning medical appointments."},
    {"role": "assistant", "content": "I will remember that preference."},
]

client = Hindsight(base_url="http://localhost:8888")

response = client.retain(
    bank_id="alice",
    document_id="conversation-2026-09-18",
    context="Conversation between Alice and her assistant",
    content=json.dumps(turns, ensure_ascii=False),
    update_mode="replace",
)

print(response.success)
```

Do not pass `turns` directly as `content`: a Python list there is interpreted as a list of `text`, `image`, or `file` content blocks. Serialize the conversation with `json.dumps` first.

For incremental conversations, either resend the complete transcript with `replace` or send a new serialized tail with `append`. Multiple items with the same `document_id` can be folded in order by synchronous batch retain, but asynchronous batches reject duplicate document IDs to prevent concurrent document-update races.

## 8. Operational Constraints

- Inline `image` and `file` blocks require a retain model that Hindsight recognizes as vision-capable; otherwise retain returns HTTP 422 instead of silently dropping attachments.
- Inline attachments are incompatible with `HINDSIGHT_API_RETAIN_BATCH_ENABLED=true`; that configuration also returns HTTP 422 for such a request.
- The default limit is 20 MiB of decoded bytes per attachment, 50 attachments per retain item, and 8 attachments per extraction chunk. These are server configuration values and may differ in a deployment.
- `filename` is optional for a `file` block but should be supplied because providers may expose it to the model.
- Re-retaining the same `document_id` with `replace` replaces that document's prior content and derived memories; choose stable document IDs deliberately.
- Active formats such as SVG or HTML are served under their declared media type when fetched later. Treat write access to a bank as permission to host content on the dataplane origin.

## 9. Selection Guide

| Goal | Use |
| --- | --- |
| Retain prose or Markdown | Plain string `content` |
| Preserve an image's position beside explanatory prose | Inline `image` block |
| Preserve a PDF or DOCX beside explanatory prose | Inline `file` block |
| Parse a standalone PDF or office file into Markdown | `client.retain_files(...)` / `POST /files/retain` |
| Create or update a logical Hindsight document | Stable `document_id` plus `replace` or `append` |
| Retain a conversation | Serialized transcript in string `content` |

The shortest rule is: `text`, `image`, and `file` are types inside `content`; `document_id` turns the retained item into a managed Hindsight document.
