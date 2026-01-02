"""
Telegram Bot FastAPI handler for serverless deployment on Vercel.

This module implements a FastAPI application that receives webhook updates
from Telegram and responds with structured religious content. The bot uses
a dictionary to represent the content hierarchy (categories, sub‑categories
and items) and encodes navigation in the callback_data of inline keyboard
buttons so that no persistent state is required.  The bot does not run
long‑lived processes; instead, it responds to each webhook invocation
independently, which makes it suitable for serverless environments such
as Vercel.  The Telegram bot token should be provided as an environment
variable named ``BOT_TOKEN`` at deploy time.

Note: Do not commit your actual bot token to version control. Configure
the environment on Vercel with ``BOT_TOKEN``.  For local testing you can
export the variable in your shell before running.
"""

import os
import asyncio
from typing import Dict, Any

import httpx
from fastapi import FastAPI, Request, HTTPException


def _build_content() -> Dict[str, Dict[str, Dict[str, Dict[str, str]]]]:
    """Return the hierarchical content structure for the bot.

    The structure is a nested dictionary: top‑level keys are categories,
    second‑level keys are sub‑categories, third‑level keys are item names.
    Each item value is a mapping with optional ``text`` and ``url`` fields.

    This function encapsulates the content definition so that it can be
    extended or modified without altering the rest of the code.  The
    religious content here is intentionally brief and primarily links to
    external resources, respecting copyright and attribution requirements.
    """

    return {
        "الأدعية": {
            "الأدعية العامة": {
                "دعاء كميل": {
                    "text": "دعاء كميل هو دعاء معروف ينسب للإمام علي بن أبي طالب عليه السلام.",
                    "url": "https://hmomen.com/duaa/general/duaa-kumail"
                },
                "دعاء الجوشن الكبير": {
                    "text": "دعاء الجوشن الكبير يُقرأ في ليالي شهر رمضان المبارك.",
                    "url": "https://hmomen.com/duaa/general/duaa-jawshan-kabir"
                },
                "دعاء الندبة": {
                    "text": "دعاء الندبة يُقرأ في الأعياد الأربعة ويُظهر الشوق للإمام المنتظر.",
                    "url": "https://hmomen.com/duaa/general/duaa-nudba"
                },
                "دعاء الافتتاح": {
                    "text": "دعاء الافتتاح يُقرأ في ليالي شهر رمضان ويتضمن الثناء على الله والدعاء للنبي وأهل بيته.",
                    "url": "https://hmomen.com/duaa/general/duaa-iftitah"
                }
            },
            "أدعية الأيام": {
                "دعاء يوم السبت": {
                    "text": "دعاء مخصوص يُقرأ يوم السبت يطلب فيه من الله الفرج والتوفيق.",
                    "url": "https://hmomen.com/duaa/days/saturday"
                },
                "دعاء يوم الأحد": {
                    "text": "دعاء يوم الأحد، يبتدئ بالحمد لله ويطلب الستر والمغفرة.",
                    "url": "https://hmomen.com/duaa/days/sunday"
                },
                "دعاء يوم الاثنين": {
                    "text": "دعاء يوم الاثنين يطلب العفو والرزق الحلال.",
                    "url": "https://hmomen.com/duaa/days/monday"
                },
                "دعاء يوم الثلاثاء": {
                    "text": "دعاء يوم الثلاثاء يتوسل إلى الله بأسماء الأنبياء عليهم السلام.",
                    "url": "https://hmomen.com/duaa/days/tuesday"
                },
                "دعاء يوم الأربعاء": {
                    "text": "دعاء يوم الأربعاء يدعو للتوفيق والبركة.",
                    "url": "https://hmomen.com/duaa/days/wednesday"
                },
                "دعاء يوم الخميس": {
                    "text": "دعاء يوم الخميس يطلب المغفرة والتسديد.",
                    "url": "https://hmomen.com/duaa/days/thursday"
                },
                "دعاء يوم الجمعة": {
                    "text": "دعاء يوم الجمعة يُكثر فيه الثناء على الله والصلاة على محمد وآله.",
                    "url": "https://hmomen.com/duaa/days/friday"
                }
            },
            "تعقيبات الصلاة": {
                "أذكار بعد الصلاة": {
                    "text": "مجموعة من الأذكار والتسبيحات تقال بعد الصلوات الخمس.",
                    "url": "https://hmomen.com/duaa/after-prayers"
                }
            },
            "الصلوات على الحجج الطاهرين": {
                "الصلاة على النبي وأهل بيته": {
                    "text": "صلوات خاصة على النبي صلى الله عليه وآله والأئمة الأطهار.",
                    "url": "https://hmomen.com/duaa/salawat"
                }
            }
        },
        "الزيارات": {
            "الزيارات العامة": {
                "زيارة عاشوراء": {
                    "text": "زيارة عاشوراء تُقرأ لإحياء ذكرى الإمام الحسين عليه السلام.",
                    "url": "https://hmomen.com/ziyarat/general/ziyarat-ashura"
                },
                "الزيارة الجامعة الكبيرة": {
                    "text": "زيارة الجامعة الكبيرة نصٌ جامع لزيارة الأئمة الأطهار.",
                    "url": "https://hmomen.com/ziyarat/general/universial"
                }
            },
            "زيارة الأئمة في أيام الأسبوع": {
                "زيارة الإمام أمير المؤمنين يوم الاثنين": {
                    "text": "زيارة قصيرة تُقرأ للإمام علي بن أبي طالب يوم الاثنين.",
                    "url": "https://hmomen.com/ziyarat/week/imam-ali-monday"
                },
                "زيارة الإمام الحسين يوم الثلاثاء": {
                    "text": "زيارة قصيرة تُقرأ للإمام الحسين يوم الثلاثاء.",
                    "url": "https://hmomen.com/ziyarat/week/imam-husayn-tuesday"
                },
                "زيارة الإمام الكاظم والجواد يوم الأربعاء": {
                    "text": "زيارة تُقرأ للإمامين موسى الكاظم ومحمد الجواد يوم الأربعاء.",
                    "url": "https://hmomen.com/ziyarat/week/imam-kadhim-jawad-wednesday"
                },
                "زيارة الإمام الرضا والإمام الهادي يوم الخميس": {
                    "text": "زيارة تُقرأ للإمامين علي الرضا وعلي الهادي يوم الخميس.",
                    "url": "https://hmomen.com/ziyarat/week/imam-redha-hadi-thursday"
                },
                "زيارة النبي الأكرم يوم الجمعة": {
                    "text": "زيارة قصيرة تُقرأ للنبي محمد صلى الله عليه وآله يوم الجمعة.",
                    "url": "https://hmomen.com/ziyarat/week/prophet-friday"
                }
            }
        },
        "المناجات والتسابيح": {
            "المناجات": {
                "مناجاة التائبين": {
                    "text": "مناجاة التائبين مناجاة توبة وندم.",
                    "url": "https://hmomen.com/munajat/repentant"
                },
                "مناجاة الشاكرين": {
                    "text": "مناجاة الشاكرين تشكر الله على نعمه.",
                    "url": "https://hmomen.com/munajat/grateful"
                },
                "مناجاة المحبين": {
                    "text": "مناجاة المحبين تعبّر عن حب الله.",
                    "url": "https://hmomen.com/munajat/lovers"
                }
            },
            "التسابيح": {
                "تسبيح يوم السبت": {
                    "text": "تسبيح يقال يوم السبت يتضمن ذكر الله والتضرع.",
                    "url": "https://hmomen.com/tasbih/saturday"
                },
                "تسبيح يوم الأحد": {
                    "text": "تسبيح يوم الأحد يحوي تمجيدًا لله عز وجل.",
                    "url": "https://hmomen.com/tasbih/sunday"
                },
                "تسبيح يوم الاثنين": {
                    "text": "تسبيح يوم الاثنين يدعو لله بالرحمة.",
                    "url": "https://hmomen.com/tasbih/monday"
                },
                "تسبيح يوم الثلاثاء": {
                    "text": "تسبيح يوم الثلاثاء يتضمن الحمد والشكر.",
                    "url": "https://hmomen.com/tasbih/tuesday"
                },
                "تسبيح يوم الأربعاء": {
                    "text": "تسبيح يوم الأربعاء يكثر فيه الاستغفار.",
                    "url": "https://hmomen.com/tasbih/wednesday"
                },
                "تسبيح يوم الخميس": {
                    "text": "تسبيح يوم الخميس يشتمل على الثناء والتقديس.",
                    "url": "https://hmomen.com/tasbih/thursday"
                },
                "تسبيح يوم الجمعة": {
                    "text": "تسبيح يوم الجمعة يُستحب إكثاره، ويشمل الصلاة على محمد وآله.",
                    "url": "https://hmomen.com/tasbih/friday"
                }
            }
        },
        "الأعمال": {
            "محرم": {
                "أعمال الليلة الأولى": {
                    "text": "أعمال عبادة لليلة الأولى من شهر محرم.",
                    "url": "https://hmomen.com/amal/muharram/night1"
                },
                "أعمال اليوم الأول": {
                    "text": "أعمال اليوم الأول تشمل الصيام والدعاء.",
                    "url": "https://hmomen.com/amal/muharram/day1"
                },
                "أعمال يوم التاسع": {
                    "text": "أعمال يوم التاسع من محرم تتضمن زيارة الإمام الحسين.",
                    "url": "https://hmomen.com/amal/muharram/day9"
                },
                "أعمال يوم العاشر": {
                    "text": "أعمال عاشوراء تتضمن الدعاء والبكاء على الإمام الحسين.",
                    "url": "https://hmomen.com/amal/muharram/day10"
                }
            },
            "صفر": {
                "أعمال اليوم الأول": {
                    "text": "أعمال اليوم الأول من شهر صفر تتضمن الصدقة والصلاة.",
                    "url": "https://hmomen.com/amal/safar/day1"
                },
                "أعمال اليوم الثالث والعشرين": {
                    "text": "أعمال اليوم الثالث والعشرين من صفر تشمل زيارة الإمام الحسين.",
                    "url": "https://hmomen.com/amal/safar/day23"
                }
            },
            "ربيع الأول": {
                "أعمال اليوم الأول": {
                    "text": "أعمال اليوم الأول من ربيع الأول.",
                    "url": "https://hmomen.com/amal/rabee1/day1"
                },
                "أعمال اليوم الثاني عشر": {
                    "text": "أعمال اليوم الثاني عشر تشمل الاحتفال بمولد النبي.",
                    "url": "https://hmomen.com/amal/rabee1/day12"
                },
                "أعمال الليلة التاسعة عشرة": {
                    "text": "أعمال الليلة التاسعة عشرة من ربيع الأول.",
                    "url": "https://hmomen.com/amal/rabee1/night19"
                }
            },
            "رجب": {
                "أعمال الليلة الثالثة": {
                    "text": "أعمال الليلة الثالثة من شهر رجب.",
                    "url": "https://hmomen.com/amal/rajab/night3"
                },
                "أعمال الليلة الرابعة": {
                    "text": "أعمال الليلة الرابعة من رجب.",
                    "url": "https://hmomen.com/amal/rajab/night4"
                },
                "أعمال الليلة الخامسة": {
                    "text": "أعمال الليلة الخامسة من رجب.",
                    "url": "https://hmomen.com/amal/rajab/night5"
                },
                "أعمال الليلة التاسعة": {
                    "text": "أعمال الليلة التاسعة من رجب.",
                    "url": "https://hmomen.com/amal/rajab/night9"
                },
                "أعمال الليلة الرابعة والعشرين": {
                    "text": "أعمال الليلة الرابعة والعشرين من رجب.",
                    "url": "https://hmomen.com/amal/rajab/night24"
                }
            },
            "شعبان": {
                "أعمال اليوم الأول": {
                    "text": "أعمال اليوم الأول من شعبان.",
                    "url": "https://hmomen.com/amal/shaban/day1"
                },
                "أعمال اليوم الثاني": {
                    "text": "أعمال اليوم الثاني من شعبان.",
                    "url": "https://hmomen.com/amal/shaban/day2"
                },
                "أعمال اليوم الثالث": {
                    "text": "أعمال اليوم الثالث من شعبان.",
                    "url": "https://hmomen.com/amal/shaban/day3"
                }
            },
            "شوال": {
                "أعمال الليلة الأولى": {
                    "text": "أعمال الليلة الأولى من شوال.",
                    "url": "https://hmomen.com/amal/shawwal/night1"
                },
                "أعمال اليوم الأول": {
                    "text": "أعمال اليوم الأول من شوال وتشمل صلاة العيد.",
                    "url": "https://hmomen.com/amal/shawwal/day1"
                }
            },
            "ذو القعدة": {
                "أعمال عامة": {
                    "text": "أعمال عامة لشهر ذو القعدة.",
                    "url": "https://hmomen.com/amal/zulqadah/general"
                },
                "أعمال اليوم الخامس": {
                    "text": "أعمال اليوم الخامس من ذو القعدة.",
                    "url": "https://hmomen.com/amal/zulqadah/day5"
                },
                "أعمال اليوم الحادي عشر": {
                    "text": "أعمال اليوم الحادي عشر من ذو القعدة.",
                    "url": "https://hmomen.com/amal/zulqadah/day11"
                },
                "أعمال اليوم الثالث والعشرون": {
                    "text": "أعمال اليوم الثالث والعشرون من ذو القعدة.",
                    "url": "https://hmomen.com/amal/zulqadah/day23"
                },
                "أعمال الليلة الخامسة عشر": {
                    "text": "أعمال الليلة الخامسة عشر من ذو القعدة.",
                    "url": "https://hmomen.com/amal/zulqadah/night15"
                },
                "أعمال من الثامن عشر إلى نهاية الشهر": {
                    "text": "أعمال الثلث الأخير من شهر ذو القعدة.",
                    "url": "https://hmomen.com/amal/zulqadah/after18"
                }
            },
            "ذو الحجة": {
                "أعمال اليوم الأول حتى اليوم العاشر": {
                    "text": "أعمال الأيام العشرة الأولى من ذو الحجة تتضمن أعمال الحج والتقرب.",
                    "url": "https://hmomen.com/amal/zulhijjah/day1-10"
                },
                "أعمال اليوم الثامن عشر": {
                    "text": "أعمال اليوم الثامن عشر من ذو الحجة، يوم الغدير.",
                    "url": "https://hmomen.com/amal/zulhijjah/day18"
                },
                "أعمال اليوم الرابع والعشرين": {
                    "text": "أعمال اليوم الرابع والعشرين من ذو الحجة.",
                    "url": "https://hmomen.com/amal/zulhijjah/day24"
                },
                "أعمال اليوم الثلاثون": {
                    "text": "أعمال اليوم الثلاثون من ذو الحجة.",
                    "url": "https://hmomen.com/amal/zulhijjah/day30"
                }
            }
        }
    }


CONTENT = _build_content()

BOT_TOKEN = os.getenv("BOT_TOKEN", "")
if not BOT_TOKEN:
    # If the token is missing, raise an exception on startup so that the
    # deployment fails early.  The user must provide the token in the
    # environment on Vercel.  For local testing, set it manually.
    raise RuntimeError(
        "BOT_TOKEN environment variable is not set. Please configure your bot token"
    )


async def send_message(chat_id: int, text: str, reply_markup: Dict[str, Any] | None = None) -> None:
    """Send a message to a Telegram chat using the Bot API.

    Args:
        chat_id: The recipient chat ID.
        text: The message text.
        reply_markup: Optional inline keyboard markup structure.
    """
    async with httpx.AsyncClient() as client:
        await client.post(
            f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage",
            json={"chat_id": chat_id, "text": text, "reply_markup": reply_markup},
            timeout=15,
        )


async def edit_message(chat_id: int, message_id: int, text: str, reply_markup: Dict[str, Any] | None = None) -> None:
    """Edit a previously sent message.

    Args:
        chat_id: The chat identifier.
        message_id: The message identifier to edit.
        text: The new text.
        reply_markup: Optional updated inline keyboard markup.
    """
    async with httpx.AsyncClient() as client:
        await client.post(
            f"https://api.telegram.org/bot{BOT_TOKEN}/editMessageText",
            json={
                "chat_id": chat_id,
                "message_id": message_id,
                "text": text,
                "reply_markup": reply_markup,
            },
            timeout=15,
        )


def build_keyboard(options: Dict[str, Any], prefix: str) -> Dict[str, Any]:
    """Build an inline keyboard for a list of options.

    Args:
        options: A mapping of option names to nested dicts or values.
        prefix: A prefix string used to build callback_data identifiers.

    Returns:
        A dict representing the inline keyboard markup.
    """
    keyboard: list[list[Dict[str, str]]] = []
    for key in options.keys():
        keyboard.append([
            {
                "text": key,
                "callback_data": f"{prefix}|{key}"
            }
        ])
    return {"inline_keyboard": keyboard}


async def handle_message(message: Dict[str, Any]) -> None:
    """Handle incoming standard text messages.

    When a user sends any message, the bot responds by presenting the top‑level
    categories for navigation.
    """
    chat_id = message["chat"]["id"]
    text = "اختر قسمًا من الأقسام التالية:"  # "Choose a category from the following:"
    reply_markup = build_keyboard(CONTENT, "cat")
    await send_message(chat_id, text, reply_markup)


async def handle_callback_query(callback_query: Dict[str, Any]) -> None:
    """Handle callback queries from inline keyboard buttons.

    The callback_data is expected to contain pipe‑separated identifiers
    describing the path in the content structure.  For example:
    - "cat|الأدعية"
    - "sub|الأدعية|الأدعية العامة"
    - "item|الأدعية|الأدعية العامة|دعاء كميل"
    """
    data = callback_query.get("data", "")
    message = callback_query.get("message")
    chat_id = message["chat"]["id"]
    message_id = message["message_id"]

    parts = data.split("|")
    if not parts:
        return

    kind = parts[0]
    if kind == "cat" and len(parts) == 2:
        category = parts[1]
        sub_options = CONTENT.get(category, {})
        text = f"اختر قسمًا فرعيًا من {category}:"
        reply_markup = build_keyboard(sub_options, f"sub|{category}")
        await edit_message(chat_id, message_id, text, reply_markup)
    elif kind == "sub" and len(parts) == 3:
        category = parts[1]
        subcategory = parts[2]
        items = CONTENT.get(category, {}).get(subcategory, {})
        text = f"اختر موضوعًا من {subcategory}:"
        reply_markup = build_keyboard(items, f"item|{category}|{subcategory}")
        await edit_message(chat_id, message_id, text, reply_markup)
    elif kind == "item" and len(parts) == 4:
        category = parts[1]
        subcategory = parts[2]
        item_name = parts[3]
        entry = CONTENT.get(category, {}).get(subcategory, {}).get(item_name, {})
        text = entry.get("text", "")
        url = entry.get("url")
        if url:
            text += f"\n\n📎 رابط: {url}"
        await edit_message(chat_id, message_id, text)
    else:
        # Unrecognized callback; simply ignore
        pass


app = FastAPI()


@app.post("/")
async def telegram_webhook(request: Request) -> Dict[str, str]:
    """Endpoint to receive Telegram webhook updates.

    This route receives both standard messages and callback queries.  It
    processes them asynchronously and acknowledges receipt by returning
    immediately with a simple JSON payload.
    """
    try:
        update = await request.json()
    except Exception as exc:
        raise HTTPException(status_code=400, detail="Invalid JSON") from exc

    # Handle message (text or command)
    if "message" in update:
        # Only react to text messages; ignore other types (stickers, photos, etc.)
        if update["message"].get("text"):
            await handle_message(update["message"])
    # Handle callback query from inline buttons
    elif "callback_query" in update:
        await handle_callback_query(update["callback_query"])

    # Always respond with OK to acknowledge receipt
    return {"status": "ok"}
