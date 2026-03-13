import os
import logging
import io
import re
import asyncio
from aiogram import Bot, Dispatcher, types, F
from aiogram.filters import CommandStart
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

bot = Bot(token=BOT_TOKEN, parse_mode="HTML")
dp = Dispatcher(storage=MemoryStorage())
anthropic_client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)

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

<i>Этот разбор сделан в боте «Мадам Селезнёва разбирает» — проекте Кристины Селезнёвой.</i>"""


class Dialog(StatesGroup):
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


@dp.message(CommandStart())
async def cmd_start(message: types.Message, state: FSMContext):
    await state.clear()
    await state.set_state(Dialog.start)
    await message.answer(
        "Здравствуйте.\n"
        "Я — Мадам Селезнёва.\n\n"
        "Я задам вам несколько точных вопросов и попробую собрать картину вашей ситуации.\n\n"
        "Это не терапия и не диагноз.\n"
        "Но иногда уже по ответам становится видно, где именно всё запуталось.\n\n"
        "Если готовы — начнём.",
        reply_markup=btn(["Разобрать ситуацию"])
    )


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
        "content": "Предложи ровно 3 варианта темы — каждый на отдельной строке, коротко (до 60 символов), без нумерации."
    })
    response = await ask_claude(history)
    history.append({"role": "assistant", "content": response})

    lines = [l.strip() for l in response.strip().split("\n") if l.strip()]
    # Фильтруем вводные фразы и оставляем только короткие темы
    skip_words = ["вот", "варианта", "варианты", "предлагаю", "можно разобрать", "три", "рассмотрим"]
    themes = []
    for l in lines:
        l_lower = l.lower()
        if any(w in l_lower for w in skip_words):
            continue
        if len(l) < 80:
            themes.append(l)
        if len(themes) == 3:
            break
    if len(themes) < 3:
        themes = (themes + ["Вариант 1", "Вариант 2", "Вариант 3"])[:3]

    text = (
        "Похоже, что здесь может идти речь о:\n"
        f"1. {themes[0]}\n"
        f"2. {themes[1]}\n"
        f"3. {themes[2]}\n"
        "4. Другое — можете уточнить своими словами\n\n"
        "Я правильно понимаю направление вашей ситуации?"
    )
    await state.update_data(history=history, themes=themes, question_count=0)
    await state.set_state(Dialog.questions)
    await message.answer(text, reply_markup=btn([themes[0], themes[1], themes[2], "Другое"]))


@dp.message(Dialog.questions)
async def handle_questions(message: types.Message, state: FSMContext):
    data = await state.get_data()
    history = data.get("history", [])
    q_count = data.get("question_count", 0)
    user_input = message.text

    if q_count == 0:
        history.append({"role": "user", "content": f"Выбранная тема: {user_input}"})
        history.append({"role": "assistant", "content": "Хорошо, буду отталкиваться от этого."})
        history.append({"role": "user", "content": "Задай первый уточняющий вопрос — один, коротко, 1-2 предложения."})
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
        [InlineKeyboardButton(text="📎 Сохранить разбор (PDF)", callback_data="save")],
        [InlineKeyboardButton(
            text="📨 Отправить другу",
            switch_inline_query="Я прошла разбор ситуации у бота «Мадам Селезнёва разбирает». Он задаёт несколько вопросов и точно собирает картину. Попробуй: @madame_seleznyova_bot"
        )],
    ])
    await message.answer(final_text, reply_markup=keyboard)


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


async def main():
    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())
