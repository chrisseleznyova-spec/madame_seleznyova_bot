import os
import logging
from aiogram import Bot, Dispatcher, types, F
from aiogram.filters import CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.types import ReplyKeyboardMarkup, KeyboardButton, ReplyKeyboardRemove, InlineKeyboardMarkup, InlineKeyboardButton
import anthropic
import asyncio

logging.basicConfig(level=logging.INFO)

BOT_TOKEN = os.environ.get("BOT_TOKEN")
ANTHROPIC_API_KEY = os.environ.get("ANTHROPIC_API_KEY")
CHANNEL_URL = os.environ.get("CHANNEL_URL", "https://t.me/")
SESSION_URL = os.environ.get("SESSION_URL", "https://t.me/")

bot = Bot(token=BOT_TOKEN)
dp = Dispatcher(storage=MemoryStorage())
anthropic_client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)

SYSTEM_PROMPT = """Ты — ИИ-ассистент Кристины Селезнёвой, коуча ICF.

Бот работает как персонаж «Мадам Селезнёва» и помогает людям коротко разобрать их жизненную ситуацию.

Твоя задача — через несколько точных вопросов собрать картину происходящего и дать короткий, ясный разбор.

Твоя цель — помочь человеку понять суть ситуации, увидеть основное напряжение и возможную точку выхода.

СТИЛЬ ОБЩЕНИЯ:
- коротко и по делу
- без воды
- без дежурных фраз вроде «я понимаю как вам тяжело»
- поддерживающе, но прямо
- как умный внимательный собеседник, а не психолог из сериала

Тон — спокойный, внимательный, немного ироничный.

Никогда не используй слова: «однозначно», «безусловно», «конечно».
Не давай банальных советов вроде «вам нужно больше отдыхать».

ФОРМАТ ДИАЛОГА:
- один вопрос = одно сообщение
- не задавай несколько вопросов одновременно
- после каждого вопроса жди ответ пользователя
- вопросы: 1-2 предложения, без длинных объяснений

УТОЧНЯЮЩИЕ ВОПРОСЫ (после выбора темы):
Цель: уточнить контекст, выявить внутренний конфликт, отделить факты от интерпретаций, увидеть паттерны, определить зону контроля.
Задавай 4-6 вопросов (максимум 8). Если после 6 картина ясна — переходи к разбору.
Если есть 70-80% понимания — переходи к разбору. Не тяни бесконечно.

Основная часть вопросов — открытые (развёрнутый ответ).
Закрытые (Да/Нет) — только для коротких уточнений фактов, редко.

При анализе разделяй: факты / интерпретации / эмоции.
Обращай внимание на: попытки контролировать чужие решения, приписывание мотивов, повторяющиеся сценарии, внутренние противоречия, напряжение между желаниями и реальностью.

Если прослеживается — используй в разборе: скрытый вопрос (что человек на самом деле пытается решить), точку выбора (между чем фактически находится), зону контроля (что зависит от него, что нет). Не придумывай эти элементы, если их нет.

КОГДА ПЕРЕХОДИШЬ К РАЗБОРУ — напиши сначала:
«Я внимательно посмотрю на ваши ответы и попробую сформулировать, что здесь может происходить.»

СТРУКТУРА ФИНАЛЬНОГО РАЗБОРА (до 1500 символов):
1. Что происходит — коротко своими словами, можно использовать яркие формулировки пользователя как якоря, не копировать полностью
2. Почему это происходит — один основной психологический механизм
3. Эмоциональный маркер — аккуратно обозначь эмоциональный фон
4. На что стоит обратить внимание — одна мысль или вопрос, иной взгляд на ситуацию. Не говори что человек должен делать.

В конце разбора обязательно:
«Оставлю вам один вопрос, который может быть полезно спокойно обдумать:

[вопрос]

Иногда именно с него начинает постепенно распутываться вся ситуация.»

В самом конце добавь строку:
«Этот разбор сделан в боте «Мадам Селезнёва разбирает» — проекте Кристины Селезнёвой.»"""


class Dialog(StatesGroup):
    start = State()
    describe = State()
    themes = State()
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
        max_tokens=1024,
        system=SYSTEM_PROMPT,
        messages=messages
    )
    return response.content[0].text


@dp.message(CommandStart())
async def cmd_start(message: types.Message, state: FSMContext):
    await state.clear()
    await state.set_state(Dialog.start)
    await message.answer(
        "Здравствуйте.\n"
        "Я — бот «Мадам Селезнёва разбирает».\n\n"
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
    await state.update_data(situation=user_text, history=[
        {"role": "user", "content": f"Моя ситуация: {user_text}"}
    ])

    await message.answer("Продолжить", reply_markup=btn(["Продолжить"]))
    await state.set_state(Dialog.themes)


@dp.message(Dialog.themes, F.text == "Продолжить")
async def generate_themes(message: types.Message, state: FSMContext):
    data = await state.get_data()
    history = data["history"]

    history.append({
        "role": "user",
        "content": "Проанализируй мою ситуацию и предложи 3 варианта темы (каждый в одну строку, без нумерации, коротко). Затем спроси: «Я правильно понимаю направление вашей ситуации?». Формат ответа: только три темы с новой строки, без лишних слов."
    })

    response = await ask_claude(history)
    history.append({"role": "assistant", "content": response})

    # Парсим темы из ответа
    lines = [l.strip() for l in response.strip().split("\n") if l.strip()]
    themes = [l for l in lines if len(l) < 80][:3]
    if len(themes) < 3:
        themes = ["Вариант 1", "Вариант 2", "Вариант 3"]

    await state.update_data(history=history, themes=themes)

    text = (
        "Я попробую сформулировать, какая тема может быть в центре вашей ситуации.\n\n"
        "Похоже, что здесь может идти речь о:\n"
        f"1. {themes[0]}\n"
        f"2. {themes[1]}\n"
        f"3. {themes[2]}\n"
        "4. Другое — можете уточнить своими словами\n\n"
        "Я правильно понимаю направление вашей ситуации?"
    )
    await message.answer(text, reply_markup=btn([themes[0], themes[1], themes[2], "Другое"]))
    await state.set_state(Dialog.questions)
    await state.update_data(question_count=0)


@dp.message(Dialog.questions)
async def handle_questions(message: types.Message, state: FSMContext):
    data = await state.get_data()
    history = data.get("history", [])
    q_count = data.get("question_count", 0)
    user_input = message.text

    # Если только что выбрали тему (первое сообщение в этом состоянии)
    if q_count == 0:
        history.append({"role": "user", "content": f"Выбранная тема: {user_input}"})
        history.append({
            "role": "assistant",
            "content": "Хорошо, буду отталкиваться от этого."
        })
        await state.update_data(history=history, question_count=1)
        # Задаём первый вопрос
        history.append({
            "role": "user",
            "content": "Задай мне первый уточняющий вопрос — один, коротко, 1-2 предложения."
        })
        question = await ask_claude(history)
        history.append({"role": "assistant", "content": question})
        await state.update_data(history=history)
        await message.answer(question, reply_markup=btn(["Поделиться ответом"]))
        return

    # Обрабатываем ответ пользователя на предыдущий вопрос
    if user_input == "Поделиться ответом":
        return  # Ждём реального ответа

    history.append({"role": "user", "content": user_input})

    # Проверяем — достаточно ли данных для разбора
    if q_count >= 6:
        # Переходим к финальному разбору
        await state.update_data(history=history)
        await do_final(message, state)
        return

    # Просим следующий вопрос или разбор
    history.append({
        "role": "user",
        "content": (
            f"Это был ответ на вопрос №{q_count}. "
            "Если уже есть 70-80% понимания ситуации — напиши ТОЛЬКО слово РАЗБОР. "
            "Если нужен ещё один вопрос — задай его, один, коротко."
        )
    })
    response = await ask_claude(history)

    if "РАЗБОР" in response.upper() or q_count >= 5:
        await state.update_data(history=history)
        await do_final(message, state)
        return

    history.append({"role": "assistant", "content": response})
    await state.update_data(history=history, question_count=q_count + 1)
    await message.answer(response, reply_markup=btn(["Поделиться ответом"]))


async def do_final(message: types.Message, state: FSMContext):
    data = await state.get_data()
    history = data.get("history", [])

    await message.answer(
        "Я внимательно посмотрю на ваши ответы и попробую сформулировать, что здесь может происходить.",
        reply_markup=ReplyKeyboardRemove()
    )

    history.append({
        "role": "user",
        "content": (
            "Сделай финальный разбор по структуре:\n"
            "1. Что происходит\n"
            "2. Почему это происходит\n"
            "3. Эмоциональный маркер\n"
            "4. На что стоит обратить внимание\n\n"
            "Затем финальный вопрос в формате:\n"
            "«Оставлю вам один вопрос, который может быть полезно спокойно обдумать:\n[вопрос]\nИногда именно с него начинает постепенно распутываться вся ситуация.»\n\n"
            "В конце строка: «Этот разбор сделан в боте «Мадам Селезнёва разбирает» — проекте Кристины Селезнёвой.»\n\n"
            "Весь текст — до 1500 символов."
        )
    })

    final_text = await ask_claude(history)
    history.append({"role": "assistant", "content": final_text})
    await state.update_data(history=history, final_text=final_text)
    await state.set_state(Dialog.final)

    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📎 Сохранить разбор", callback_data="save")],
        [InlineKeyboardButton(text="🔁 Отправить разбор другу", callback_data="share")]
    ])
    await message.answer(final_text, reply_markup=keyboard)


@dp.callback_query(F.data == "save")
async def save_handler(callback: types.CallbackQuery, state: FSMContext):
    data = await state.get_data()
    final_text = data.get("final_text", "")
    await callback.answer("Разбор сохранён в этом чате — можете вернуться к нему в любой момент.", show_alert=True)
    await after_final(callback.message, state)


@dp.callback_query(F.data == "share")
async def share_handler(callback: types.CallbackQuery, state: FSMContext):
    share_text = (
        "Я прошёл разбор ситуации у бота «Мадам Селезнёва разбирает».\n"
        "Он задаёт несколько вопросов и довольно точно собирает картину происходящего.\n"
        "Если интересно — можно попробовать: @madame_seleznyova_bot"
    )
    await callback.answer()
    await callback.message.answer(f"Скопируйте и отправьте другу:\n\n{share_text}")
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
    await state.set_state(Dialog.start)
    await callback.message.answer(
        "Хорошо, начнём новый разбор.\n\nРасскажите — что на этот раз?",
        reply_markup=ReplyKeyboardRemove()
    )
    await state.set_state(Dialog.describe)


async def main():
    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())
