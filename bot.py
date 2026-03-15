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


def record_session(user_id: int, username: str, source: str = ""):
    stats = load_stats()
    uid = str(user_id)
    today = str(date.today())
    now = datetime.now().isoformat(timespec="seconds")
    if uid not in stats["users"]:
        stats["users"][uid] = {"username": username, "sessions": 0, "first": now, "last": now, "dates": [], "completed": 0, "source": source}
    stats["users"][uid]["sessions"] += 1
    stats["users"][uid]["last"] = now
    stats["users"][uid]["username"] = username or stats["users"][uid].get("username", "")
    if today not in stats["users"][uid]["dates"]:
        stats["users"][uid]["dates"].append(today)
    if source and not stats["users"][uid].get("source"):
        stats["users"][uid]["source"] = source
    save_stats(stats)


def record_theme(user_id: int, theme: str):
    stats = load_stats()
    if "themes" not in stats:
        stats["themes"] = []
    stats["themes"].append({"uid": str(user_id), "theme": theme, "date": str(date.today())})
    save_stats(stats)


def record_completion(user_id: int):
    stats = load_stats()
    uid = str(user_id)
    if uid in stats["users"]:
        stats["users"][uid]["completed"] = stats["users"][uid].get("completed", 0) + 1
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
    mini_age = State()
    mini_sphere = State()
    mini_work = State()
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
WELCOME_PHOTO_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "ChatGPT Image 14 мар. 2026 г., 21_30_47.png")
PRIVACY_URL = "https://telegra.ph/Politika-konfidencialnosti-03-13-46"


@dp.message(CommandStart())
async def cmd_start(message: types.Message, state: FSMContext):
    await state.clear()
    await state.set_state(Dialog.consent)
    user = message.from_user

    # Реферальный источник из deep link (?start=instagram)
    args = message.text.split()
    source = args[1] if len(args) > 1 else "direct"
    record_session(user.id, user.username or user.full_name or "", source=source)
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
    await state.set_state(Dialog.mini_sphere)

    caption = (
        "Здравствуйте.\n"
        "Я — Мадам Селезнёва.\n\n"
        "Задам несколько точных вопросов и попробую собрать картину вашей ситуации.\n\n"
        "Это не терапия и не диагноз.\n"
        "Но иногда уже по ответам становится видно, где именно всё запуталось."
    )

    if WELCOME_PHOTO:
        await callback.message.answer_photo(photo=WELCOME_PHOTO, caption=caption)
    elif os.path.exists(WELCOME_PHOTO_PATH):
        photo_file = types.FSInputFile(WELCOME_PHOTO_PATH)
        await callback.message.answer_photo(photo=photo_file, caption=caption)
    else:
        await callback.message.answer(caption)

    await asyncio.sleep(1)
    await callback.message.answer(
        "Один вопрос перед началом — чтобы я лучше понимала контекст.\n\n"
        "Какая сфера жизни сейчас занимает больше всего мыслей?\n"
        "<i>Выберите до двух вариантов, затем нажмите «Готово»</i>",
        reply_markup=sphere_keyboard([])
    )


def sphere_keyboard(selected: list) -> InlineKeyboardMarkup:
    options = ["Отношения", "Работа и карьера", "Семья", "Я сама / внутреннее состояние"]
    buttons = []
    for opt in options:
        mark = "✅ " if opt in selected else ""
        buttons.append([InlineKeyboardButton(text=f"{mark}{opt}", callback_data=f"sphere_{opt}")])
    buttons.append([InlineKeyboardButton(text="Готово →", callback_data="sphere_done")])
    return InlineKeyboardMarkup(inline_keyboard=buttons)


@dp.callback_query(Dialog.mini_sphere, F.data.startswith("sphere_") & ~F.data.endswith("done"))
async def sphere_toggle(callback: types.CallbackQuery, state: FSMContext):
    chosen = callback.data[7:]  # убираем "sphere_"
    data = await state.get_data()
    selected = data.get("selected_spheres", [])
    if chosen in selected:
        selected.remove(chosen)
    elif len(selected) < 2:
        selected.append(chosen)
    await state.update_data(selected_spheres=selected)
    await callback.message.edit_reply_markup(reply_markup=sphere_keyboard(selected))
    await callback.answer()


@dp.callback_query(Dialog.mini_sphere, F.data == "sphere_done")
async def sphere_done(callback: types.CallbackQuery, state: FSMContext):
    await callback.answer()
    data = await state.get_data()
    selected = data.get("selected_spheres", [])
    if not selected:
        await callback.answer("Выберите хотя бы один вариант", show_alert=True)
        return

    # Сохраняем в статистику
    stats = load_stats()
    uid = str(callback.from_user.id)
    sphere_str = ", ".join(selected)
    if uid in stats["users"]:
        stats["users"][uid]["sphere"] = sphere_str
        if "spheres" not in stats:
            stats["spheres"] = []
        stats["spheres"].append({"sphere": sphere_str, "date": str(date.today())})
        save_stats(stats)

    await state.set_state(Dialog.start)
    await callback.message.edit_reply_markup(reply_markup=None)
    await callback.message.answer("Хорошо. Если готовы — начнём.", reply_markup=btn(["Разобрать ситуацию"]))


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
        record_theme(message.from_user.id, user_input)
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
    record_completion(message.from_user.id)

    # Сохраняем тему для напоминания
    data = await state.get_data()
    themes = data.get("themes", [])
    chosen_theme = themes[0] if themes else ""
    stats = load_stats()
    uid = str(message.from_user.id)
    if uid in stats["users"]:
        stats["users"][uid]["last_theme"] = chosen_theme
        stats["users"][uid]["remind_at"] = (datetime.now().replace(hour=11, minute=0, second=0, microsecond=0)
                                             .isoformat() if True else "")
        # Напоминание через 3 дня
        from datetime import timedelta
        remind_dt = datetime.now() + timedelta(days=3)
        stats["users"][uid]["remind_at"] = remind_dt.isoformat(timespec="seconds")
        stats["users"][uid]["reminded"] = False
        save_stats(stats)

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

    # Сначала опрос про полезность
    await asyncio.sleep(1)
    await message.answer(
        "Скажите — этот разбор был для вас полезным?",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [
                InlineKeyboardButton(text="✅ Да, попал в точку", callback_data="fb_yes"),
                InlineKeyboardButton(text="🤔 Частично", callback_data="fb_partly"),
            ],
            [InlineKeyboardButton(text="❌ Не очень", callback_data="fb_no")],
        ])
    )


@dp.callback_query(F.data.startswith("fb_"))
async def feedback_handler(callback: types.CallbackQuery, state: FSMContext):
    await callback.answer()
    fb_map = {"fb_yes": "да", "fb_partly": "частично", "fb_no": "нет"}
    fb_value = fb_map.get(callback.data, "")

    # Сохраняем в статистику
    stats = load_stats()
    if "feedback" not in stats:
        stats["feedback"] = []
    stats["feedback"].append({"uid": str(callback.from_user.id), "value": fb_value, "date": str(date.today())})
    save_stats(stats)

    if callback.data == "fb_yes":
        reply = "Рада слышать. Значит, картина сложилась."
    elif callback.data == "fb_partly":
        reply = "Понятно. Иногда одного разбора недостаточно — ситуация многослойная."
    else:
        reply = "Жаль. Возможно, тема оказалась сложнее или вопросы не попали в нужное место."

    await callback.message.answer(reply)
    await asyncio.sleep(1)

    await callback.message.answer(
        "Если вам близок такой способ разбираться в сложных ситуациях —\n"
        "в моём канале я регулярно публикую похожие разборы и наблюдения.",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="Перейти в канал", url=CHANNEL_URL)]
        ])
    )
    await asyncio.sleep(1)
    await callback.message.answer(
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
    themes_log = stats.get("themes", [])

    total_users = len(users)
    total_sessions = sum(u["sessions"] for u in users.values())
    total_completed = sum(u.get("completed", 0) for u in users.values())
    today = str(date.today())
    today_sessions = sum(1 for u in users.values() if today in u.get("dates", []))
    multi = [(uid, u) for uid, u in users.items() if u["sessions"] > 1]
    multi.sort(key=lambda x: x[1]["sessions"], reverse=True)

    # Конверсия
    conversion = round(total_completed / total_sessions * 100) if total_sessions else 0

    # Топ тем
    from collections import Counter
    theme_counts = Counter(t["theme"] for t in themes_log)
    top_themes = theme_counts.most_common(8)

    text = (
        f"📊 <b>Статистика бота</b>\n\n"
        f"👥 Уникальных пользователей: <b>{total_users}</b>\n"
        f"🔄 Всего сессий: <b>{total_sessions}</b>\n"
        f"✅ Дошли до разбора: <b>{total_completed}</b> ({conversion}%)\n"
        f"📅 Сегодня: <b>{today_sessions}</b>\n"
    )

    if top_themes:
        text += f"\n🔥 <b>Популярные темы:</b>\n"
        for i, (theme, count) in enumerate(top_themes, 1):
            text += f"  {i}. {theme} — {count}\n"

    # Фидбек
    feedback = stats.get("feedback", [])
    if feedback:
        from collections import Counter
        fb_counts = Counter(f["value"] for f in feedback)
        text += f"\n💬 <b>Отзывы ({len(feedback)}):</b>\n"
        text += f"  ✅ Да — {fb_counts.get('да', 0)}\n"
        text += f"  🤔 Частично — {fb_counts.get('частично', 0)}\n"
        text += f"  ❌ Нет — {fb_counts.get('нет', 0)}\n"

    if multi:
        text += f"\n🔁 <b>Возвращались:</b>\n"
        for uid, u in multi[:5]:
            name = u.get("username") or uid
            text += f"  @{name} — {u['sessions']} раз\n"

    await message.answer(text)

    # Анализ тем через Claude если их достаточно
    if len(themes_log) >= 5:
        all_themes = [t["theme"] for t in themes_log]
        analysis_prompt = (
            f"Вот список тем которые выбирали пользователи бота психологического разбора: {all_themes}. "
            f"Кратко (3-5 предложений): какие паттерны видны? Что чаще всего беспокоит аудиторию? "
            f"Какую тему стоит раскрыть в контенте коучу?"
        )
        response = anthropic_client.messages.create(
            model="claude-sonnet-4-6",
            max_tokens=400,
            messages=[{"role": "user", "content": analysis_prompt}]
        )
        analysis = response.content[0].text
        await message.answer(f"🧠 <b>Анализ тем:</b>\n\n{analysis}")


async def send_reminders():
    """Проверяем и отправляем напоминания через 3 дня"""
    while True:
        try:
            stats = load_stats()
            now = datetime.now()
            changed = False
            for uid, u in stats["users"].items():
                if u.get("reminded") is False and u.get("remind_at"):
                    remind_dt = datetime.fromisoformat(u["remind_at"])
                    if now >= remind_dt:
                        theme = u.get("last_theme", "")
                        # Генерируем контекстное напоминание через Claude
                        prompt = (
                            f"Пользователь 3 дня назад прошёл разбор ситуации на тему: «{theme}». "
                            f"Напиши короткое тёплое сообщение от Мадам Селезнёвой (2-3 предложения): "
                            f"спроси как они, упомни тему разбора, задай один мягкий вопрос о том, "
                            f"что изменилось или что удалось обдумать. "
                            f"Затем предложи новый разбор если появилась другая ситуация. "
                            f"Тон — тёплый, без навязчивости."
                        )
                        response = anthropic_client.messages.create(
                            model="claude-sonnet-4-6",
                            max_tokens=300,
                            messages=[{"role": "user", "content": prompt}]
                        )
                        reminder_text = response.content[0].text
                        reminder_text += "\n\nЕсли хотите разобрать новую ситуацию — просто напишите /start"
                        try:
                            await bot.send_message(int(uid), reminder_text)
                            stats["users"][uid]["reminded"] = True
                            changed = True
                        except Exception as e:
                            logging.error(f"Reminder error for {uid}: {e}")
                            stats["users"][uid]["reminded"] = True
                            changed = True
            if changed:
                save_stats(stats)
        except Exception as e:
            logging.error(f"Reminder loop error: {e}")
        await asyncio.sleep(3600)  # Проверяем каждый час


async def send_weekly_report():
    """Еженедельный отчёт каждый понедельник в 11:00 МСК"""
    while True:
        try:
            now = datetime.now()
            # Понедельник = 0, 11:00
            days_until_monday = (7 - now.weekday()) % 7 or 7
            next_monday = now.replace(hour=8, minute=0, second=0, microsecond=0)  # 11:00 МСК = 08:00 UTC
            next_monday = next_monday.replace(day=now.day) + __import__('datetime').timedelta(days=days_until_monday)
            wait_seconds = (next_monday - now).total_seconds()
            if wait_seconds < 0:
                wait_seconds += 7 * 86400
            await asyncio.sleep(max(wait_seconds, 60))

            if not ADMIN_ID:
                continue

            stats = load_stats()
            users = stats.get("users", {})
            themes_log = stats.get("themes", [])
            spheres_log = stats.get("spheres", [])

            from collections import Counter
            total_users = len(users)
            total_sessions = sum(u["sessions"] for u in users.values())
            total_completed = sum(u.get("completed", 0) for u in users.values())
            conversion = round(total_completed / total_sessions * 100) if total_sessions else 0
            top_themes = Counter(t["theme"] for t in themes_log).most_common(5)
            top_spheres = Counter(s["sphere"] for s in spheres_log).most_common(4)

            text = (
                f"📊 <b>Еженедельный отчёт</b>\n\n"
                f"👥 Всего пользователей: <b>{total_users}</b>\n"
                f"🔄 Всего сессий: <b>{total_sessions}</b>\n"
                f"✅ Конверсия до разбора: <b>{conversion}%</b>\n"
            )
            if top_themes:
                text += "\n🔥 <b>Топ тем за всё время:</b>\n"
                for theme, count in top_themes:
                    text += f"  • {theme} — {count}\n"
            if top_spheres:
                text += "\n🌀 <b>Сферы жизни:</b>\n"
                for sphere, count in top_spheres:
                    text += f"  • {sphere} — {count}\n"

            await bot.send_message(ADMIN_ID, text)

            # Анализ профессий через Claude
            works = [u.get("work", "") for u in stats["users"].values() if u.get("work")]
            if len(works) >= 3:
                work_prompt = (
                    f"Вот список профессий/занятий пользователей бота психологического разбора: {works}. "
                    f"Разбей по категориям (например: предприниматели, наёмные сотрудники, фрилансеры, в декрете и т.д.). "
                    f"Напиши кратко какие категории преобладают и что это говорит об аудитории. "
                    f"3-4 предложения, без лишнего."
                )
                work_response = anthropic_client.messages.create(
                    model="claude-sonnet-4-6",
                    max_tokens=300,
                    messages=[{"role": "user", "content": work_prompt}]
                )
                await bot.send_message(ADMIN_ID, f"👩‍💼 <b>Анализ аудитории по профессиям:</b>\n\n{work_response.content[0].text}")

        except Exception as e:
            logging.error(f"Weekly report error: {e}")
            await asyncio.sleep(3600)


async def main():
    asyncio.create_task(send_reminders())
    asyncio.create_task(send_weekly_report())
    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())
