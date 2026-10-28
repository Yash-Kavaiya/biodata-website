"""
Telegram bot tests against a fake Telegram Bot API. Handlers run on the app's
event loop (via the TestClient portal) so they share the real queue and database.
"""
import json

import httpx
import pytest

from backend.services.telegram_bot import TelegramBot
from tests.conftest import PDF_BYTES, PNG_BYTES, uploaded_files

OWNER = 111
STRANGER = 999


class FakeTelegram:
    """Records Bot API calls and serves files for getFile downloads."""

    def __init__(self, files):
        self.files = files  # file_id -> bytes
        self.calls = []

    def handler(self, request: httpx.Request) -> httpx.Response:
        path = request.url.path
        if "/file/bot" in path:
            file_id = path.rsplit("/", 1)[-1]
            return httpx.Response(200, content=self.files[file_id])
        method = path.rsplit("/", 1)[-1]
        params = json.loads(request.content or b"{}")
        self.calls.append((method, params))
        if method == "getFile":
            return httpx.Response(200, json={"ok": True, "result": {"file_path": f"documents/{params['file_id']}"}})
        if method == "sendMessage":
            return httpx.Response(200, json={"ok": True, "result": {"message_id": len(self.calls)}})
        return httpx.Response(200, json={"ok": True, "result": True})

    def last(self, method):
        return [p for m, p in self.calls if m == method][-1]


@pytest.fixture
def telegram(client):
    fake = FakeTelegram({"pdf1": PDF_BYTES, "png1": PNG_BYTES, "bad": b"not a pdf"})
    bot = TelegramBot("TOKEN", {OWNER}, transport=httpx.MockTransport(fake.handler))

    def handle(update):
        client.portal.call(bot.handle_update, update)

    yield fake, handle
    client.portal.call(bot.close)


def document_update(chat_id, file_id, name, mime="application/pdf"):
    return {"update_id": 1, "message": {
        "message_id": 10, "chat": {"id": chat_id},
        "document": {"file_id": file_id, "file_unique_id": file_id, "file_name": name,
                     "mime_type": mime, "file_size": 100},
    }}


def test_stranger_gets_chat_id_and_nothing_is_processed(client, telegram, provider):
    fake, handle = telegram
    handle(document_update(STRANGER, "pdf1", "b.pdf"))

    assert [m for m, _ in fake.calls] == ["sendMessage"]
    reply = fake.last("sendMessage")
    assert reply["chat_id"] == STRANGER
    assert str(STRANGER) in reply["text"] and "private" in reply["text"]
    assert provider.calls == 0
    assert client.get("/api/biodata").json()["total"] == 0


def test_pdf_is_ocrd_added_and_approved_from_button(client, telegram, provider):
    fake, handle = telegram
    handle(document_update(OWNER, "pdf1", "rahul.pdf"))

    assert provider.calls == 1
    items = client.get("/api/biodata").json()["items"]
    assert len(items) == 1 and items[0]["original_filename"] == "rahul.pdf"
    assert items[0]["ocr_status"] == "completed"
    assert len(uploaded_files()) == 1

    result = fake.last("editMessageText")
    assert "Rahul Sharma" in result["text"] and "Added for review" in result["text"]
    buttons = result["reply_markup"]["inline_keyboard"][0]
    assert [b["callback_data"] for b in buttons] == [f"approve:{items[0]['id']}", f"reject:{items[0]['id']}"]

    handle({"update_id": 2, "callback_query": {
        "id": "cb1", "data": buttons[0]["callback_data"],
        "message": {"message_id": 5, "chat": {"id": OWNER}},
    }})
    assert client.get(f"/api/biodata/{items[0]['id']}").json()["ocr_status"] == "approved"
    final = fake.last("editMessageText")
    assert "Approved" in final["text"] and final["reply_markup"] == {"inline_keyboard": []}


def test_photo_uses_largest_size(client, telegram, provider):
    fake, handle = telegram
    handle({"update_id": 3, "message": {
        "message_id": 11, "chat": {"id": OWNER},
        "photo": [{"file_id": "small", "file_unique_id": "s", "file_size": 10},
                  {"file_id": "png1", "file_unique_id": "big", "file_size": 100}],
    }})
    assert fake.last("getFile")["file_id"] == "png1"
    # PNG bytes under a .jpg name are rejected by the signature check, so nothing is stored
    assert "does not look like a valid JPG" in fake.last("editMessageText")["text"]
    assert provider.calls == 0


def test_invalid_file_and_ocr_failure_are_reported(client, telegram, provider):
    fake, handle = telegram
    handle(document_update(OWNER, "bad", "fake.pdf"))
    assert "valid PDF" in fake.last("editMessageText")["text"]

    provider.responses = [ValueError("unreadable scan")]
    handle(document_update(OWNER, "pdf1", "scan.pdf"))
    assert "unreadable scan" in fake.last("editMessageText")["text"]
    assert uploaded_files() == []
    assert client.get("/api/biodata").json()["total"] == 0


def test_oversized_file_rejected_before_download(client, telegram, provider):
    fake, handle = telegram
    update = document_update(OWNER, "pdf1", "huge.pdf")
    update["message"]["document"]["file_size"] = 50 * 1024 * 1024
    handle(update)
    assert "too large" in fake.last("sendMessage")["text"]
    assert not any(m == "getFile" for m, _ in fake.calls)


def test_stats_and_help(client, telegram):
    fake, handle = telegram
    client.post("/api/biodata", json={"name": "Priya", "gender": "female"})
    handle({"update_id": 4, "message": {"message_id": 12, "chat": {"id": OWNER}, "text": "/stats"}})
    assert "Approved: 1" in fake.last("sendMessage")["text"]

    handle({"update_id": 5, "message": {"message_id": 13, "chat": {"id": OWNER}, "text": "hello"}})
    assert "Send a biodata" in fake.last("sendMessage")["text"]


def test_callback_from_stranger_is_refused(client, telegram):
    fake, handle = telegram
    biodata_id = client.post("/api/biodata", json={"name": "X"}).json()["id"]
    client.post(f"/api/validation/reject/{biodata_id}")
    handle({"update_id": 6, "callback_query": {
        "id": "cb2", "data": f"approve:{biodata_id}",
        "message": {"message_id": 7, "chat": {"id": STRANGER}},
    }})
    assert fake.last("answerCallbackQuery")["text"] == "Not allowed"
    assert client.get(f"/api/biodata/{biodata_id}").json()["ocr_status"] == "rejected"
