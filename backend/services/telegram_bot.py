"""
Telegram Bot - send a biodata PDF/photo to the bot and it is OCR'd and added,
exactly like an upload from the web UI. Replies with the extracted summary and
Approve / Reject buttons.

Runs as a long-polling background task inside the app (no public URL needed).
Only chat IDs listed in TELEGRAM_ALLOWED_CHAT_IDS may use it; anyone else is
told their chat ID so the owner can allow it.
"""
import asyncio
import html
import logging
from pathlib import Path
from typing import Any, Dict, Optional, Set

import httpx

from backend.config import settings
from backend.models import OCRStatus

logger = logging.getLogger(__name__)

API_ROOT = "https://api.telegram.org"
# Telegram bots can only download files up to 20 MB
TELEGRAM_DOWNLOAD_LIMIT = 20 * 1024 * 1024
_MIME_EXTENSIONS = {"application/pdf": ".pdf", "image/png": ".png", "image/jpeg": ".jpg"}

HELP_TEXT = (
    "<b>Biodata Manager bot</b>\n\n"
    "Send a biodata <b>PDF</b> or <b>photo</b> and I'll read it with AI and add it for review.\n"
    "Tip: send photos as a <i>file</i> (📎 → File) to keep full quality for better OCR.\n\n"
    "/stats – profile counts\n"
    "/help – this message"
)

SUMMARY_FIELDS = [
    ("age", "Age"), ("gender", "Gender"), ("date_of_birth", "DOB"), ("education", "Education"),
    ("occupation", "Occupation"), ("current_city", "City"), ("religion", "Religion"),
    ("caste", "Caste"), ("contact_number", "Contact"),
]


class TelegramBot:
    """Minimal Telegram Bot API client + update handler."""

    def __init__(
        self,
        token: str,
        allowed_chat_ids: Set[int],
        transport: Optional[httpx.AsyncBaseTransport] = None,
    ):
        self.token = token
        self.allowed_chat_ids = allowed_chat_ids
        self._client = httpx.AsyncClient(timeout=60.0, transport=transport)
        self._offset: Optional[int] = None
        self._tasks: Set[asyncio.Task] = set()

    # ------------------------------------------------------------- API calls
    async def call(self, method: str, **params) -> Any:
        response = await self._client.post(f"{API_ROOT}/bot{self.token}/{method}", json=params)
        data = response.json()
        if not data.get("ok"):
            raise RuntimeError(f"Telegram {method} failed: {data.get('description')}")
        return data["result"]

    async def send(self, chat_id: int, text: str, **extra) -> Dict[str, Any]:
        return await self.call("sendMessage", chat_id=chat_id, text=text, parse_mode="HTML",
                               disable_web_page_preview=True, **extra)

    async def edit(self, chat_id: int, message_id: int, text: str, **extra):
        await self.call("editMessageText", chat_id=chat_id, message_id=message_id, text=text,
                        parse_mode="HTML", disable_web_page_preview=True, **extra)

    async def download(self, file_id: str) -> bytes:
        info = await self.call("getFile", file_id=file_id)
        response = await self._client.get(f"{API_ROOT}/file/bot{self.token}/{info['file_path']}")
        response.raise_for_status()
        return response.content

    # --------------------------------------------------------------- polling
    async def run(self):
        """Long-poll for updates until cancelled."""
        me = await self.call("getMe")
        logger.info(f"Telegram bot @{me['username']} is polling for messages")
        if not self.allowed_chat_ids:
            logger.warning("TELEGRAM_ALLOWED_CHAT_IDS is empty: the bot will only reply with chat IDs")

        while True:
            try:
                params = {"timeout": 30, "allowed_updates": ["message", "callback_query"]}
                if self._offset is not None:
                    params["offset"] = self._offset
                response = await self._client.post(
                    f"{API_ROOT}/bot{self.token}/getUpdates", json=params, timeout=45.0
                )
                data = response.json()
                if not data.get("ok"):
                    raise RuntimeError(data.get("description"))
                for update in data["result"]:
                    self._offset = update["update_id"] + 1
                    task = asyncio.create_task(self._safe_handle(update))
                    self._tasks.add(task)
                    task.add_done_callback(self._tasks.discard)
            except asyncio.CancelledError:
                raise
            except Exception as e:
                logger.error(f"Telegram polling error: {e}")
                await asyncio.sleep(5)

    async def close(self):
        for task in list(self._tasks):
            task.cancel()
        await self._client.aclose()

    async def _safe_handle(self, update: Dict[str, Any]):
        try:
            await self.handle_update(update)
        except Exception:
            logger.exception("Failed to handle Telegram update")

    # --------------------------------------------------------------- handlers
    async def handle_update(self, update: Dict[str, Any]):
        if "callback_query" in update:
            await self._handle_callback(update["callback_query"])
            return

        message = update.get("message")
        if not message:
            return
        chat_id = message["chat"]["id"]

        if chat_id not in self.allowed_chat_ids:
            logger.warning(f"Telegram message from unauthorized chat {chat_id}")
            await self.send(chat_id, (
                "⛔ This bot is private.\n\n"
                f"Your chat ID is <code>{chat_id}</code>. To get access, the owner must add it to "
                "<code>TELEGRAM_ALLOWED_CHAT_IDS</code> and restart the app."
            ))
            return

        text = (message.get("text") or "").strip()
        if text.startswith("/stats"):
            await self._send_stats(chat_id)
        elif message.get("document") or message.get("photo"):
            await self._handle_file(message)
        else:
            await self.send(chat_id, HELP_TEXT)

    async def _send_stats(self, chat_id: int):
        from backend.services import db

        counts = await db.status_counts()
        to_review = sum(counts.get(s, 0) for s in ("completed", "pending", "failed"))
        await self.send(chat_id, (
            "<b>Profiles</b>\n"
            f"Total: {counts.get('total', 0)}\n"
            f"Approved: {counts.get('approved', 0)}\n"
            f"To review: {to_review}\n"
            f"Rejected: {counts.get('rejected', 0)}"
        ))

    async def _handle_file(self, message: Dict[str, Any]):
        from backend.routers.upload import ingest_file, validate_upload_content
        from backend.services import storage_service

        chat_id = message["chat"]["id"]
        if message.get("document"):
            doc = message["document"]
            file_id, size = doc["file_id"], doc.get("file_size") or 0
            filename = doc.get("file_name") or f"telegram_{doc['file_unique_id']}"
            if not Path(filename).suffix:
                filename += _MIME_EXTENSIONS.get(doc.get("mime_type", ""), "")
        else:
            photo = message["photo"][-1]  # largest size
            file_id, size = photo["file_id"], photo.get("file_size") or 0
            filename = f"telegram_photo_{photo['file_unique_id']}.jpg"

        limit = min(settings.max_file_bytes, TELEGRAM_DOWNLOAD_LIMIT)
        if size > limit:
            await self.send(chat_id, f"⚠️ <b>{html.escape(filename)}</b> is too large (max {limit // (1024 * 1024)} MB).")
            return

        status = await self.send(chat_id, f"⏳ Reading <b>{html.escape(filename)}</b> with AI…",
                                 reply_to_message_id=message["message_id"])
        try:
            content = await self.download(file_id)
            validate_upload_content(filename, content)
        except ValueError as e:
            await self.edit(chat_id, status["message_id"], f"⚠️ {html.escape(str(e))}")
            return

        file_path = await storage_service.save_file_content(content, filename)
        result = await ingest_file(file_path, filename)
        if result.status == OCRStatus.FAILED:
            await self.edit(chat_id, status["message_id"], f"❌ {html.escape(result.message)}")
            return

        await self._show_biodata(chat_id, status["message_id"], result.id, header="✅ Added for review")

    async def _show_biodata(self, chat_id: int, message_id: int, biodata_id: str, header: str,
                            buttons: bool = True):
        from backend.services import db

        biodata = await db.get_by_id(biodata_id)
        if not biodata:
            await self.edit(chat_id, message_id, "This biodata no longer exists.")
            return
        lines = [f"{header}", "", f"<b>{html.escape(biodata.name or 'Unnamed profile')}</b>"]
        for key, label in SUMMARY_FIELDS:
            value = getattr(biodata, key)
            if value is not None:
                value = value.value if hasattr(value, "value") else value
                lines.append(f"{label}: {html.escape(str(value))}")
        lines.append(f"\nConfidence: {round((biodata.ocr_confidence or 0) * 100)}%")
        markup = {"inline_keyboard": [[
            {"text": "✅ Approve", "callback_data": f"approve:{biodata.id}"},
            {"text": "❌ Reject", "callback_data": f"reject:{biodata.id}"},
        ]]} if buttons else {"inline_keyboard": []}
        await self.edit(chat_id, message_id, "\n".join(lines), reply_markup=markup)

    async def _handle_callback(self, query: Dict[str, Any]):
        from backend.services import db, graph_service

        message = query.get("message") or {}
        chat_id = (message.get("chat") or {}).get("id")
        if chat_id not in self.allowed_chat_ids:
            await self.call("answerCallbackQuery", callback_query_id=query["id"], text="Not allowed")
            return

        action, _, biodata_id = (query.get("data") or "").partition(":")
        updates = {
            "approve": {"ocr_status": OCRStatus.APPROVED.value, "is_approved": True},
            "reject": {"ocr_status": OCRStatus.REJECTED.value, "is_approved": False},
        }.get(action)
        if not updates:
            await self.call("answerCallbackQuery", callback_query_id=query["id"])
            return

        updated = await db.update(biodata_id, updates)
        if not updated:
            await self.call("answerCallbackQuery", callback_query_id=query["id"], text="Biodata not found")
            return
        await graph_service.sync(updated)
        label = "Approved" if action == "approve" else "Rejected"
        await self.call("answerCallbackQuery", callback_query_id=query["id"], text=label)
        await self._show_biodata(chat_id, message["message_id"], biodata_id,
                                 header=("✅ " if action == "approve" else "❌ ") + label, buttons=False)


def create_bot() -> Optional[TelegramBot]:
    """Build the bot from settings, or None when no token is configured."""
    if not settings.TELEGRAM_BOT_TOKEN:
        return None
    return TelegramBot(settings.TELEGRAM_BOT_TOKEN, settings.telegram_allowed_chat_ids)
