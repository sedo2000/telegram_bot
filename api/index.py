import os
import re
from typing import Dict, List, Tuple, Optional

import httpx
from bs4 import BeautifulSoup
from fastapi import FastAPI, Request, HTTPException

BASE = "https://hmomen.com"
BOT_TOKEN = os.getenv("BOT_TOKEN", "").strip()
OWNER_ID = os.getenv("OWNER_ID", "").strip()  # optional

# Telegram limits: 4096 chars per message. Keep a safety margin.
TG_LIMIT = 3500

# =========================
# Content map (list pages)
# =========================
# sub_id is used in callback_data (short & stable)
SECTIONS: Dict[str, Dict[str, Dict[str, str]]] = {
    "الأدعية": {
        "الأدعية العامة": {"id": "dua", "path": "/content/dua"},
        "أدعية الأيام": {"id": "days", "path": "/content/days"},
        "تعقيبات الصلاة": {"id": "taq", "path": "/content/taqeebat"},
        "الصلوات على الحجج الطاهرين": {"id": "sal", "path": "/content/sallats"},
    },
    "الزيارات": {
        "الزيارات العامة": {"id": "zyg", "path": "/content/zyarat"},
        "زيارة الأئمة في أيام الأسبوع": {"id": "dzy", "path": "/content/days_zyarat"},
    },
    "المناجات والتسابيح": {
        "المناجات": {"id": "mon", "path": "/content/monajat"},
        "التسابيح": {"id": "tas", "path": "/content/days_tasbih"},
    },
    "الأعمال": {
        "محرم": {"id": "muh", "path": "/content/muharram"},
        "صفر": {"id": "saf", "path": "/content/safar"},
        "ربيع الأول": {"id": "rab1", "path": "/content/rabiulawal"},
        "رجب": {"id": "raj", "path": "/content/rajab"},
        "شعبان": {"id": "sha", "path": "/content/shaban"},
        "شوال": {"id": "shw", "path": "/content/shawwal"},
        "ذو القعدة": {"id": "dq", "path": "/content/dhulqadah"},
        "ذو الحجة": {"id": "dh", "path": "/content/dhualhijjah"},
    },
}

# quick reverse index for callbacks
SUB_BY_ID: Dict[str, Tuple[str, str, str]] = {}
for cat, subs in SECTIONS.items():
    for sub_name, meta in subs.items():
        SUB_BY_ID[meta["id"]] = (cat, sub_name, meta["path"])


# =========================
# Telegram helpers
# =========================
async def tg_request(method: str, payload: dict) -> dict:
    if not BOT_TOKEN:
        raise RuntimeError("BOT_TOKEN is missing")
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/{method}"
    async with httpx.AsyncClient(timeout=25) as client:
        r = await client.post(url, json=payload)
        r.raise_for_status()
        data = r.json()
        if not data.get("ok"):
            raise RuntimeError(str(data))
        return data


async def send_message(chat_id: int, text: str, reply_markup: Optional[dict] = None) -> None:
    payload = {"chat_id": chat_id, "text": text}
    if reply_markup:
        payload["reply_markup"] = reply_markup
    await tg_request("sendMessage", payload)


async def edit_message(chat_id: int, message_id: int, text: str, reply_markup: Optional[dict] = None) -> None:
    payload = {"chat_id": chat_id, "message_id": message_id, "text": text}
    if reply_markup is not None:
        payload["reply_markup"] = reply_markup
    await tg_request("editMessageText", payload)


def keyboard(buttons: List[Tuple[str, str]], cols: int = 2) -> dict:
    rows = []
    row = []
    for label, cb in buttons:
        row.append({"text": label, "callback_data": cb})
        if len(row) >= cols:
            rows.append(row)
            row = []
    if row:
        rows.append(row)
    return {"inline_keyboard": rows}


def chunk_text(text: str, limit: int = TG_LIMIT) -> List[str]:
    text = text.strip()
    if len(text) <= limit:
        return [text]
    chunks = []
    i = 0
    while i < len(text):
        j = min(i + limit, len(text))
        # try to split on paragraph boundary
        cut = text.rfind("\n\n", i, j)
        if cut == -1 or cut <= i + 200:
            cut = text.rfind("\n", i, j)
        if cut == -1 or cut <= i + 200:
            cut = j
        chunks.append(text[i:cut].strip())
        i = cut
    return [c for c in chunks if c]


# =========================
# hmomen.com parsing
# =========================
async def fetch_html(path_or_url: str) -> str:
    url = path_or_url
    if url.startswith("/"):
        url = BASE + url
    async with httpx.AsyncClient(timeout=25, follow_redirects=True) as client:
        r = await client.get(url)
        r.raise_for_status()
        return r.text


def parse_list(html: str) -> List[Tuple[str, str]]:
    """Return [(title, href_path)] from a list page."""
    soup = BeautifulSoup(html, "html.parser")
    out: List[Tuple[str, str]] = []
    seen = set()

    for a in soup.find_all("a"):
        href = (a.get("href") or "").strip()
        title = a.get_text(" ", strip=True)
        if not href.startswith("/content/"):
            continue
        if not title or len(title) > 120:
            continue
        # ignore section roots like /content/dua itself
        if href.count("/") <= 2:
            continue
        key = (title, href)
        if key in seen:
            continue
        seen.add(key)
        out.append((title, href))

    # simple heuristic: keep order as page order
    return out


def clean_detail_text(html: str) -> Tuple[str, str]:
    """Extract (title, body_text) from a detail page."""
    soup = BeautifulSoup(html, "html.parser")

    # title
    h1 = soup.find("h1")
    title = h1.get_text(" ", strip=True) if h1 else ""

    # remove noise
    for tag in soup(["script", "style", "nav", "footer", "header"]):
        tag.decompose()

    text = soup.get_text("\n", strip=True)

    # drop common UI lines
    bad_starts = {
        "روابط مهمة",
        "المحتوى",
        "القرآن الكريم",
        "الرئيسية",
        "تحميل التطبيق",
        "أنضم إلينا",
        "جميع الحقوق",
    }

    lines = []
    time_like = re.compile(r"^\s*\d{1,2}:\d{2}\s*$")  # مثل 00:00

for line in text.splitlines():
    line = line.strip()
    if not line:
        continue

    # احذف سطور الوقت مثل 00:00
    if time_like.match(line):
        continue

    if any(line.startswith(b) for b in bad_starts):
        continue

    # remove repeated menu headers
    if line in {"الأدعية", "الزيارات"}:
        continue

    lines.append(line)

    # try to start after title occurrence
    body = "\n".join(lines)
    if title and title in body:
        idx = body.find(title)
        body = body[idx + len(title):].strip()

    # compress excessive blank lines
    body = re.sub(r"\n{3,}", "\n\n", body).strip()

    return title.strip(), body


# =========================
# Bot logic
# =========================
async def show_main(chat_id: int) -> None:
    btns = [(cat, f"cat|{cat}") for cat in SECTIONS.keys()]
    await send_message(chat_id, "اختر قسمًا من الأقسام التالية:", keyboard(btns, cols=1))


async def show_subcategories(chat_id: int, message_id: int, category: str) -> None:
    subs = SECTIONS.get(category, {})
    btns = [(name, f"sub|{subs[name]['id']}") for name in subs.keys()]
    btns.append(("⬅️ رجوع", "back|main"))
    await edit_message(chat_id, message_id, f"{category}: اختر قسمًا فرعيًا:", keyboard(btns, cols=1))


async def show_items(chat_id: int, message_id: int, sub_id: str) -> None:
    if sub_id not in SUB_BY_ID:
        await edit_message(chat_id, message_id, "القسم غير موجود.")
        return
    cat, sub_name, path = SUB_BY_ID[sub_id]

    html = await fetch_html(path)
    items = parse_list(html)
    if not items:
        await edit_message(chat_id, message_id, "ماكو محتوى ظاهر بهذا القسم حالياً.")
        return

    # callback_data max 64 bytes: keep it short
    btns = [(t, f"it|{sub_id}|{h}") for (t, h) in items[:90]]
    btns.append(("⬅️ رجوع", f"cat|{cat}"))
    await edit_message(chat_id, message_id, f"{cat} › {sub_name}: اختر عنصرًا:", keyboard(btns, cols=1))


async def show_detail(chat_id: int, message_id: int, sub_id: str, href: str) -> None:
    if sub_id not in SUB_BY_ID:
        await edit_message(chat_id, message_id, "القسم غير موجود.")
        return
    cat, sub_name, _ = SUB_BY_ID[sub_id]

    html = await fetch_html(href)
    title, body = clean_detail_text(html)

    if not body:
        await edit_message(chat_id, message_id, "ما قدرت أستخرج النص من الصفحة.")
        return

    header = f"{title}\n\n" if title else ""
    footer = f"\n\nالمصدر: {BASE}{href}"
    full = (header + body + footer).strip()

    parts = chunk_text(full)

    # edit first message, then send the rest
    await edit_message(chat_id, message_id, parts[0])
    for p in parts[1:]:
        await send_message(chat_id, p)

    # send navigation buttons in a separate message (so we don't fight message length)
    nav = keyboard([
        ("⬅️ رجوع للقائمة", f"sub|{sub_id}"),
        ("⬅️ رجوع للقسم", f"cat|{cat}"),
    ], cols=1)
    await send_message(chat_id, "التنقل:", nav)


# =========================
# Webhook handler
# =========================
app = FastAPI()


@app.post("/")
async def telegram_webhook(request: Request) -> Dict[str, str]:
    if not BOT_TOKEN:
        raise HTTPException(status_code=500, detail="BOT_TOKEN is not configured")

    try:
        update = await request.json()
    except Exception as exc:
        raise HTTPException(status_code=400, detail="Invalid JSON") from exc

    # message
    if "message" in update:
        msg = update["message"]
        text = (msg.get("text") or "").strip()
        chat_id = msg["chat"]["id"]

        if text in {"/start", "start", "ابدأ"}:
            await show_main(chat_id)
        elif text == "/id":
            await send_message(chat_id, f"chat_id: {chat_id}")
        else:
            await show_main(chat_id)

    # callback query
    elif "callback_query" in update:
        cq = update["callback_query"]
        data = cq.get("data") or ""
        message = cq.get("message") or {}
        chat_id = message.get("chat", {}).get("id")
        message_id = message.get("message_id")

        if not (chat_id and message_id):
            return {"status": "ok"}

        parts = data.split("|", 3)
        kind = parts[0] if parts else ""

        if kind == "back" and len(parts) > 1 and parts[1] == "main":
            await edit_message(chat_id, message_id, "اختر قسمًا من الأقسام التالية:", keyboard([(c, f"cat|{c}") for c in SECTIONS.keys()], cols=1))
        elif kind == "cat" and len(parts) > 1:
            await show_subcategories(chat_id, message_id, parts[1])
        elif kind == "sub" and len(parts) > 1:
            await show_items(chat_id, message_id, parts[1])
        elif kind == "it" and len(parts) > 2:
            sub_id = parts[1]
            href = parts[2]
            await show_detail(chat_id, message_id, sub_id, href)

    return {"status": "ok"}
