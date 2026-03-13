import os
import logging
import io
import re
import asyncio
import json
from datetime import datetime, date
from aiogram import Bot, Dispatcher, types, F
from aiogram.filters import CommandStart, Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.types import (
    ReplyKeyboardMarkup, KeyboardButton, ReplyKeyboardRemove,
    InlineKeyboardMarkup, InlineKeyboardButton, BufferedInputFile
)
import anthropic
from docx import Document
from docx.shared import Pt, RGBColor
from docx.enum.text import WD_ALIGN_PARAGRAPH

logging.basicConfig(level=logging.INFO)

BOT_TOKEN = os.environ.get("BOT_TOKEN")
ANTHROPIC_API_KEY = os.environ.get("ANTHROPIC_API_KEY")
CHANNEL_URL = "https://t.me/seleznyovaochemzadymalas"
SESSION_URL = os.environ.get("SESSION_URL", "https://t.me/")
ADMIN_ID = int(os.environ.get("ADMIN_ID", "0"))

STATS_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "stats.json")

bot = Bot(token=BOT_TOKEN, parse_mode="HTML")
dp = Dispatcher(storage=MemoryStorage())
anthropic_client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)


def load_stats() -> dict:
    try:
        with open(STATS_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {"users": {}}


def save_stats(stats: dict):
    try:
        with open(STATS_FILE, "w", encoding="utf-8") as f:
            json.dump(stats, f, ensure_ascii=False, indent=2)
    except Exception as e:
        logging.error(f"Stats save error: {e}")


def record_session(user_id: int, username: str):
    stats = load_stats()
    uid = str(user_id)
    today = str(date.today())
    now = datetime.now().isoformat(timespec="seconds")
    if uid not in stats["users"]:
        stats["users"][uid] = {"username": username, "sessions": 0, "first": now, "last": now, "dates": []}
    stats["users"][uid]["sessions"] += 1
    stats["users"][uid]["last"] = now
    stats["users"][uid]["username"] = username or stats["users"][uid].get("username", "")
    if today not in stats["users"][uid]["dates"]:
        stats["users"][uid]["dates"].append(today)
    save_stats(stats)



SYSTEM_PROMPT = """Ты — ИИ-ассистент Кристины Селезнёвой, коуча ICF.

Бот работает как персонаж «Мадам Селезнёва» и помогает людям коротко разобрать их жизненную ситуацию.

Твоя задача — через несколько точных вопросов собрать картину происходящего и дать короткий, ясный разбор.

СТИЛЬ ОБЩЕНИЯ:
- коротко и по делу
- без воды
- поддерживающе, но прямо
- как умный внимательный собеседник, а не психолог из сериала
- тон — спокойный, немного ироничный

Никогда не используй слова: «однозначно», «безусловно», «конечно».
Не давай банальных советов.

ФОРМАТ ДИАЛОГА:
- один вопрос = одно сообщение
- не задавай несколько вопросов одновременно
- вопросы: 1-2 предложения

УТОЧНЯЮЩИЕ ВОПРОСЫ:
Задавай 4-6 вопросов. Если после 6 картина ясна — переходи к разбору.
Если есть 70-80% понимания — переходи к разбору.

КОГДА ПЕРЕХОДИШЬ К РАЗБОРУ — НЕ пиши никакой вводной фразы типа «Я внимательно посмотрю на ваши ответы». Сразу начинай с первого раздела разбора.

СТРУКТУРА ФИНАЛЬНОГО РАЗБОРА (до 1500 символов):
СТРОГО используй HTML-теги <b>...</b> для заголовков разделов. Никаких звёздочек **текст** — только <b>текст</b>.

Пример правильного форматирования:
<b>Что происходит</b>
Тут текст раздела.

<b>Почему это происходит</b>
Тут текст раздела.

<b>Что происходит</b>
[текст]

<b>Почему это происходит</b>
[текст]

<b>Эмоциональный маркер</b>
[текст]

<b>На что стоит обратить внимание</b>
[текст]

Затем:
Оставлю вам один вопрос, который может быть полезно спокойно обдумать:

[вопрос]

Иногда именно с него начинает постепенно распутываться вся ситуация.

<i>Этот вопрос — не для ответа в чате, а для себя.</i>

<i>Этот разбор сделан в боте «Мадам Селезнёва разбирает» — проекте Кристины Селезнёвой.</i>"""


class Dialog(StatesGroup):
    consent = State()
    start = State()
    describe = State()
    questions = State()
    final = State()
    post_final = State()


def btn(labels: list[str]) -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        keyboard=[[KeyboardButton(text=t)] for t in labels],
        resize_keyboard=True,
        one_time_keyboard=True
    )


async def ask_claude(messages: list[dict]) -> str:
    response = anthropic_client.messages.create(
        model="claude-sonnet-4-6",
        max_tokens=1500,
        system=SYSTEM_PROMPT,
        messages=messages
    )
    return response.content[0].text


def html_to_plain(text: str) -> str:
    text = re.sub(r'<b>(.*?)</b>', r'\1', text)
    text = re.sub(r'<i>(.*?)</i>', r'\1', text)
    text = re.sub(r'<[^>]+>', '', text)
    return text


def create_docx(final_text: str) -> bytes:
    doc = Document()

    # Заголовок
    title = doc.add_heading('Мадам Селезнёва разбирает', level=1)
    if title.runs:
        title.runs[0].font.color.rgb = RGBColor(0x6B, 0x3F, 0xA0)

    sub = doc.add_paragraph('Разбор вашей ситуации')
    if sub.runs:
        sub.runs[0].font.color.rgb = RGBColor(0x88, 0x88, 0x88)
        sub.runs[0].font.size = Pt(11)

    doc.add_paragraph()

    # Убираем все HTML теги и пишем чистый текст
    # Сначала заменяем <b>текст</b> → "▶ текст" чтобы выделить заголовки
    text = re.sub(r'<b>(.*?)</b>', r'\n▶ \1\n', final_text)
    text = re.sub(r'<i>(.*?)</i>', r'\1', text)
    text = re.sub(r'<[^>]+>', '', text)

    for line in text.split('\n'):
        line = line.strip()
        if not line:
            continue
        if line.startswith('▶ '):
            # Заголовок раздела
            heading_text = line[2:]
            h = doc.add_heading(heading_text, level=2)
            if h.runs:
                h.runs[0].font.color.rgb = RGBColor(0x3D, 0x20, 0x60)
        else:
            p = doc.add_paragraph(line)
            if p.runs:
                p.runs[0].font.size = Pt(11)

    buffer = io.BytesIO()
    doc.save(buffer)
    buffer.seek(0)
    return buffer.read()


WELCOME_PHOTO = os.environ.get("WELCOME_PHOTO_ID", "")
WELCOME_PHOTO_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "ChatGPT Image 13 мар. 2026 г., 16_00_51.png")
PRIVACY_URL = "https://telegra.ph/Politika-konfidencialnosti-03-13-46"


@dp.message(CommandStart())
async def cmd_start(message: types.Message, state: FSMContext):
    await state.clear()
    await state.set_state(Dialog.consent)
    user = message.from_user
    record_session(user.id, user.username or user.full_name or "")
    await message.answer(
        "Прежде чем начать — один момент.\n\n"
        "В ходе разбора вы будете делиться личными переживаниями. "
        "Ваши ответы не сохраняются и не передаются третьим лицам после завершения сессии.\n\n"
        "Нажимая «Принимаю условия», вы подтверждаете согласие на обработку текста ваших сообщений в рамках этого разбора.",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="📄 Политика конфиденциальности", url=PRIVACY_URL)],
            [InlineKeyboardButton(text="✅ Принимаю условия", callback_data="consent_accept")],
        ])
    )


@dp.callback_query(F.data == "consent_accept")
async def consent_handler(callback: types.CallbackQuery, state: FSMContext):
    await callback.answer()
    await state.set_state(Dialog.start)

    caption = (
        "Здравствуйте.\n"
        "Я — Мадам Селезнёва.\n\n"
        "Задам несколько точных вопросов и попробую собрать картину вашей ситуации.\n\n"
        "Это не терапия и не диагноз.\n"
        "Но иногда уже по ответам становится видно, где именно всё запуталось.\n\n"
        "Если готовы — начнём."
    )

    if WELCOME_PHOTO:
        await callback.message.answer_photo(
            photo=WELCOME_PHOTO,
            caption=caption,
            reply_markup=btn(["Разобрать ситуацию"])
        )
    elif os.path.exists(WELCOME_PHOTO_PATH):
        photo_file = types.FSInputFile(WELCOME_PHOTO_PATH)
        await callback.message.answer_photo(
            photo=photo_file,
            caption=caption,
            reply_markup=btn(["Разобрать ситуацию"])
        )
    else:
        await callback.message.answer(caption, reply_markup=btn(["Разобрать ситуацию"]))


@dp.message(Dialog.start, F.text == "Разобрать ситуацию")
async def screen_describe(message: types.Message, state: FSMContext):
    await state.set_state(Dialog.describe)
    await message.answer(
        "Расскажите немного о том, что сейчас происходит в вашей жизни.\n"
        "Что вас беспокоит или с чем вы хотели бы разобраться?\n\n"
        "Можно коротко — до 500 символов.",
        reply_markup=ReplyKeyboardRemove()
    )


@dp.message(Dialog.describe)
async def screen_themes(message: types.Message, state: FSMContext):
    user_text = message.text[:500]
    history = [{"role": "user", "content": f"Моя ситуация: {user_text}"}]
    await state.update_data(situation=user_text, history=history)
    await message.answer("Анализирую...", reply_markup=ReplyKeyboardRemove())

    history.append({
        "role": "user",
        "content": (
            "Назови 2-3 темы для разбора — каждая на отдельной строке. "
            "Формат: короткая назывная фраза, без вопросов, без нумерации, до 50 символов. "
            "Пример: 'Страх после пережитого', 'Возвращение к нормальной жизни'. "
            "Если видишь только 2 реальные темы — дай 2, не выдумывай третью. "
            "Только темы, ничего лишнего."
        )
    })
    response = await ask_claude(history)
    history.append({"role": "assistant", "content": response})

    lines = [l.strip() for l in response.strip().split("\n") if l.strip()]
    skip_words = ["вот", "варианта", "варианты", "предлагаю", "можно разобрать", "три", "рассмотрим", "тем"]
    themes = []
    for l in lines:
        l_lower = l.lower()
        if any(w in l_lower for w in skip_words):
            continue
        if len(l) < 80:
            themes.append(l)
        if len(themes) == 3:
            break

    # Минимум 2 темы — если меньше, берём что есть
    if len(themes) < 2:
        themes = lines[:2] if len(lines) >= 2 else (lines + ["Другое"])[:2]

    # Формируем текст и кнопки динамически
    numbered = "\n".join(f"{i+1}. {t}" for i, t in enumerate(themes))
    next_num = len(themes) + 1
    text = (
        f"Похоже, что здесь может идти речь о:\n{numbered}\n"
        f"{next_num}. Другое — можете уточнить своими словами\n\n"
        "Я правильно понимаю направление вашей ситуации?"
    )
    await state.update_data(history=history, themes=themes, question_count=0)
    await state.set_state(Dialog.questions)
    await message.answer(text, reply_markup=btn([*themes, "Другое"]))


@dp.message(Dialog.questions)
async def handle_questions(message: types.Message, state: FSMContext):
    data = await state.get_data()
    history = data.get("history", [])
    q_count = data.get("question_count", 0)
    user_input = message.text

    if q_count == 0:
        history.append({"role": "user", "content": f"Пользователь выбрал направление: {user_input}. Задай первый уточняющий вопрос по этой теме — один вопрос, коротко, 1-2 предложения. Не повторяй формулировку темы."})
        question = await ask_claude(history)
        history.append({"role": "assistant", "content": question})
        await state.update_data(history=history, question_count=1)
        await message.answer(question, reply_markup=ReplyKeyboardRemove())
        return

    history.append({"role": "user", "content": user_input})

    if q_count >= 6:
        await state.update_data(history=history)
        await do_final(message, state)
        return

    history.append({
        "role": "user",
        "content": (
            f"Это был ответ на вопрос №{q_count}. "
            "Если уже есть 70-80% понимания — напиши ТОЛЬКО слово РАЗБОР. "
            "Если нужен ещё вопрос — задай один, коротко."
        )
    })
    response = await ask_claude(history)

    if "РАЗБОР" in response.upper() or q_count >= 5:
        await state.update_data(history=history)
        await do_final(message, state)
        return

    history.append({"role": "assistant", "content": response})
    await state.update_data(history=history, question_count=q_count + 1)
    await message.answer(response, reply_markup=ReplyKeyboardRemove())


async def do_final(message: types.Message, state: FSMContext):
    data = await state.get_data()
    history = data.get("history", [])

    await message.answer("Собираю разбор...", reply_markup=ReplyKeyboardRemove())

    history.append({
        "role": "user",
        "content": (
            "Сделай финальный разбор. "
            "ВАЖНО: используй ТОЛЬКО HTML-теги <b>заголовок</b> для разделов. "
            "Никаких **звёздочек**, никаких вводных фраз типа 'Я внимательно посмотрю'.\n\n"
            "Начни сразу с:\n"
            "<b>Что происходит</b>\n[текст]\n\n"
            "<b>Почему это происходит</b>\n[текст]\n\n"
            "<b>Эмоциональный маркер</b>\n[текст]\n\n"
            "<b>На что стоит обратить внимание</b>\n[текст]\n\n"
            "Затем:\nОставлю вам один вопрос, который может быть полезно спокойно обдумать:\n\n[вопрос]\n\n"
            "Иногда именно с него начинает постепенно распутываться вся ситуация.\n\n"
            "<i>Этот разбор сделан в боте «Мадам Селезнёва разбирает» — проекте Кристины Селезнёвой.</i>\n\n"
            "Весь текст — до 1500 символов. Никаких --- разделителей."
        )
    })

    final_text = await ask_claude(history)
    history.append({"role": "assistant", "content": final_text})
    await state.update_data(history=history, final_text=final_text)
    await state.set_state(Dialog.final)

    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📎 Сохранить разбор (Word)", callback_data="save")],
    ])
    await message.answer(final_text, reply_markup=keyboard)


@dp.callback_query(F.data == "share")
async def share_handler(callback: types.CallbackQuery, state: FSMContext):
    await callback.answer()
    share_text = (
        "Я прошла разбор ситуации у бота «Мадам Селезнёва разбирает».\n"
        "Он задаёт несколько вопросов и довольно точно собирает картину происходящего.\n\n"
        "Попробуй: @madame_seleznyova_bot"
    )
    await callback.message.answer(
        f"Скопируйте и отправьте другу:\n\n{share_text}"
    )


@dp.callback_query(F.data == "save")
async def save_handler(callback: types.CallbackQuery, state: FSMContext):
    data = await state.get_data()
    final_text = data.get("final_text", "")
    await callback.answer("Генерирую файл...")
    try:
        logging.info(f"Final text preview: {final_text[:200]}")
        docx_bytes = create_docx(final_text)
        docx_file = BufferedInputFile(docx_bytes, filename="razбор_madame_seleznyova.docx")
        await callback.message.answer_document(docx_file, caption="Ваш разбор сохранён 📎")
    except Exception as e:
        logging.error(f"PDF error: {e}")
        await callback.message.answer("Не удалось создать PDF. Разбор сохранён выше в чате.")
    await after_final(callback.message, state)


async def after_final(message: types.Message, state: FSMContext):
    await state.set_state(Dialog.post_final)
    await message.answer(
        "Если вам близок такой способ разбираться в сложных ситуациях —\n"
        "в моём канале я регулярно публикую похожие разборы и наблюдения.",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="Перейти в канал", url=CHANNEL_URL)]
        ])
    )
    await asyncio.sleep(1)
    await message.answer(
        "Иногда одного разбора достаточно, чтобы увидеть ситуацию яснее.\n\n"
        "Но если вы чувствуете, что хотите разобраться глубже, на сессии мы обычно делаем две вещи:\n"
        "разбираем, где именно застряла ситуация\n"
        "и находим точки выхода и ресурсы, на которые можно опереться.",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="Записаться на сессию", url=SESSION_URL)],
            [InlineKeyboardButton(text="Второй разбор — 300 ₽", callback_data="second")]
        ])
    )


@dp.callback_query(F.data == "second")
async def second_handler(callback: types.CallbackQuery, state: FSMContext):
    await callback.answer()
    await state.clear()
    await callback.message.answer(
        "Хорошо, начнём новый разбор.\n\nРасскажите — что на этот раз?",
        reply_markup=ReplyKeyboardRemove()
    )
    await state.set_state(Dialog.describe)


@dp.message(Command("stats"))
async def stats_handler(message: types.Message):
    if ADMIN_ID and message.from_user.id != ADMIN_ID:
        return
    stats = load_stats()
    users = stats.get("users", {})
    total_users = len(users)
    total_sessions = sum(u["sessions"] for u in users.values())
    today = str(date.today())
    today_sessions = sum(1 for u in users.values() if today in u.get("dates", []))
    multi = [(uid, u) for uid, u in users.items() if u["sessions"] > 1]
    multi.sort(key=lambda x: x[1]["sessions"], reverse=True)

    text = (
        f"📊 <b>Статистика бота</b>\n\n"
        f"👥 Уникальных пользователей: <b>{total_users}</b>\n"
        f"🔄 Всего сессий: <b>{total_sessions}</b>\n"
        f"📅 Сегодня: <b>{today_sessions}</b>\n"
    )
    if multi:
        text += f"\n🔁 <b>Возвращались больше 1 раза:</b>\n"
        for uid, u in multi[:10]:
            name = u.get("username") or uid
            text += f"  @{name} — {u['sessions']} раз\n"

    await message.answer(text)


async def main():
    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())
