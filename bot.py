"""
🤖  Telegram-бот: Калькулятор + Мини ИИ
─────────────────────────────────────────
•  Обычный калькулятор  (кнопки + текст)
•  Калькулятор дробей   (1/2 + 3/4 = 5/4)
•  ИИ-помощник по школьным предметам
─────────────────────────────────────────
Python 3.10+  ·  aiogram 3.x  ·  openai
"""

import asyncio
import logging
import re
from fractions import Fraction
from html import escape

from aiogram import Bot, Dispatcher, Router, F
from aiogram.filters import CommandStart, Command
from aiogram.types import (
    Message,
    CallbackQuery,
    InlineKeyboardMarkup,
    InlineKeyboardButton,
    ReplyKeyboardMarkup,
    KeyboardButton,
)
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.enums import ParseMode
from aiogram.client.default import DefaultBotProperties


# ════════════════════════════════════════════
# ⚙️  НАСТРОЙКИ  —  ЗАМЕНИ НА СВОИ!
# ════════════════════════════════════════════
BOT_TOKEN    = "8634105762:AAGndA8G3rUtGlSM2u0WzFymU9KFmfaBEqc"
OPENAI_KEY   = "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"                     # ключ OpenAI
OPENAI_MODEL = "llama-3.3-70b-versatile"              # или gpt-4o-mini


# ════════════════════════════════════════════
# 🚀  ИНИЦИАЛИЗАЦИЯ
# ════════════════════════════════════════════
logging.basicConfig(level=logging.INFO,
                    format="%(asctime)s  [%(levelname)s]  %(message)s")
log = logging.getLogger(__name__)

bot = Bot(token=BOT_TOKEN,
          default=DefaultBotProperties(parse_mode=ParseMode.HTML))
dp  = Dispatcher(storage=MemoryStorage())
router = Router()
dp.include_router(router)

# --- OpenAI ---
AI_OK = False
try:
    from openai import AsyncOpenAI
    ai = AsyncOpenAI(api_key=OPENAI_KEY, base_url="https://api.groq.com/openai/v1")
    AI_OK = True
except ImportError:
    log.warning("openai не установлен:  pip install openai")

# Хранилище калькулятора   { user_id: {"expr": "...", "mode": "normal"} }
uc: dict[int, dict] = {}


# ════════════════════════════════════════════
# 📋  FSM-СОСТОЯНИЯ  (для ИИ-чата)
# ════════════════════════════════════════════
class AI(StatesGroup):
    choosing = State()      # выбирает предмет
    chatting = State()      # задаёт вопросы


# ════════════════════════════════════════════
# 📚  ПРЕДМЕТЫ ДЛЯ ИИ
# ════════════════════════════════════════════
SUBJ = {
    "math":    ("📐 Математика",
                "Ты — учитель математики. Решай пошагово, объясняй просто. Отвечай на русском."),
    "history": ("📜 История",
                "Ты — учитель истории. Упоминай даты и факты. Отвечай на русском."),
    "russian": ("📝 Русский язык",
                "Ты — учитель русского языка. Объясняй правила, приводи примеры. Отвечай на русском."),
    "geo":     ("🌍 География",
                "Ты — учитель географии. Рассказывай о странах, реках, горах. Отвечай на русском."),
    "physics": ("🔬 Физика",
                "Ты — учитель физики. Объясняй законы и формулы просто. Отвечай на русском."),
    "bio":     ("🧬 Биология",
                "Ты — учитель биологии. Рассказывай о природе и организмах. Отвечай на русском."),
    "lit":     ("📚 Литература",
                "Ты — учитель литературы. Анализируй произведения. Отвечай на русском."),
    "general": ("💡 Любой вопрос",
                "Ты — умный помощник. Отвечай подробно и понятно. Отвечай на русском."),
}


# ════════════════════════════════════════════
# 🎹  КЛАВИАТУРЫ
# ════════════════════════════════════════════

def kb_main():
    """Главное reply-меню."""
    return ReplyKeyboardMarkup(keyboard=[
        [KeyboardButton(text="🧮 Калькулятор"),
         KeyboardButton(text="📊 Дроби")],
        [KeyboardButton(text="🤖 Мини ИИ"),
         KeyboardButton(text="❓ Помощь")],
    ], resize_keyboard=True)


def kb_calc():
    """Inline-клавиатура калькулятора."""
    rows = [
        ["7", "8", "9", "÷"],
        ["4", "5", "6", "×"],
        ["1", "2", "3", "−"],
        ["0", ".", "(", ")"],
        ["C", "⌫", "=", "+"],
    ]
    kb = [[InlineKeyboardButton(text=b, callback_data=f"c:{b}")
           for b in row] for row in rows]
    kb.append([
        InlineKeyboardButton(text="📊 Режим дробей ↔",
                             callback_data="c:mode"),
        InlineKeyboardButton(text="🔙 Меню",
                             callback_data="c:menu"),
    ])
    return InlineKeyboardMarkup(inline_keyboard=kb)


def kb_subj():
    """Inline-клавиатура предметов."""
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📐 Математика",   callback_data="s:math"),
         InlineKeyboardButton(text="📜 История",      callback_data="s:history")],
        [InlineKeyboardButton(text="📝 Русский язык", callback_data="s:russian"),
         InlineKeyboardButton(text="🌍 География",    callback_data="s:geo")],
        [InlineKeyboardButton(text="🔬 Физика",       callback_data="s:physics"),
         InlineKeyboardButton(text="🧬 Биология",     callback_data="s:bio")],
        [InlineKeyboardButton(text="📚 Литература",   callback_data="s:lit"),
         InlineKeyboardButton(text="💡 Любой вопрос", callback_data="s:general")],
        [InlineKeyboardButton(text="🔙 Назад",        callback_data="s:back")],
    ])


def kb_ai_nav():
    """Кнопки навигации внутри ИИ-чата."""
    return InlineKeyboardMarkup(inline_keyboard=[[
        InlineKeyboardButton(text="📚 Сменить предмет",
                             callback_data="s:change"),
        InlineKeyboardButton(text="🔙 Меню",
                             callback_data="s:back"),
    ]])


# ════════════════════════════════════════════
# 🧮  КАЛЬКУЛЯТОР — ЛОГИКА
# ════════════════════════════════════════════
_OK = re.compile(r'^[\d\s+\-*/().]+$')      # допустимые символы


def _norm(e: str) -> str:
    """Приводит визуальные символы к стандартным."""
    return (e .replace("×", "*")
              .replace("÷", "/")
              .replace("−", "-")
              .replace(",", "."))


def calc_normal(raw: str) -> str:
    """Обычный калькулятор.  Возвращает строку-результат."""
    e = _norm(raw).strip()
    if not e:
        return "0"
    if not _OK.match(e):
        return "❌ Недопустимые символы"
    if "**" in e or len(e) > 150:
        return "❌ Слишком сложное выражение"
    try:
        r = eval(e, {"__builtins__": {}}, {})   # безопасный eval
        if isinstance(r, float):
            if r != r or abs(r) == float("inf"):
                return "❌ Ошибка"
            if r == int(r) and abs(r) < 1e15:
                return str(int(r))
            return f"{r:.10g}"
        return str(r)
    except ZeroDivisionError:
        return "❌ Деление на ноль!"
    except Exception:
        return "❌ Ошибка в выражении"


def calc_frac(raw: str) -> str:
    """Калькулятор с дробями — результат в виде дроби."""
    e = _norm(raw).strip()
    if not e:
        return "0"
    if not _OK.match(e):
        return "❌ Недопустимые символы"
    if "**" in e or len(e) > 150:
        return "❌ Слишком сложное выражение"
    try:
        # Каждое число превращаем в Fraction
        fe = re.sub(r'(\d+\.?\d*)', r'Fraction("\1")', e)
        r = eval(fe, {"__builtins__": {}, "Fraction": Fraction}, {})
        if isinstance(r, Fraction):
            if r.denominator == 1:
                return str(r.numerator)
            return f"{r.numerator}/{r.denominator}  (≈ {float(r):.6g})"
        return str(r)
    except ZeroDivisionError:
        return "❌ Деление на ноль!"
    except Exception:
        return "❌ Ошибка!  Пример: 1/2 + 3/4"


# ════════════════════════════════════════════
# 🤖  ИИ — ЛОГИКА
# ════════════════════════════════════════════

async def ask_ai(question: str, key: str,
                 history: list | None = None) -> str:
    """Отправляет вопрос в ChatGPT."""
    if not AI_OK:
        return "❌ ИИ не подключён!\npip install openai  и укажи ключ."

    _, prompt = SUBJ.get(key, SUBJ["general"])
    msgs = [{"role": "system", "content": prompt}]
    if history:
        msgs += history[-10:]                # последние 10 реплик
    msgs.append({"role": "user", "content": question})

    try:
        resp = await ai.chat.completions.create(
            model=OPENAI_MODEL,
            messages=msgs,
            max_tokens=2000,
            temperature=0.7,
        )
        return resp.choices[0].message.content.strip()
    except Exception as e:
        log.error("AI error: %s", e)
        return f"❌ Ошибка ИИ: {e}"


# ════════════════════════════════════════════
# 📨  ОБРАБОТЧИКИ — СТАРТ / ПОМОЩЬ
# ════════════════════════════════════════════

@router.message(CommandStart())
async def cmd_start(msg: Message, state: FSMContext):
    await state.clear()
    await msg.answer(
        "👋 <b>Привет! Я — бот-помощник!</b>\n\n"
        "🧮 <b>Калькулятор</b> — считаю любые примеры\n"
        "📊 <b>Дроби</b> — результат в виде дроби\n"
        "🤖 <b>Мини ИИ</b> — отвечаю по предметам\n\n"
        "Выбери в меню 👇",
        reply_markup=kb_main())


@router.message(Command("help"))
@router.message(F.text == "❓ Помощь")
async def cmd_help(msg: Message, state: FSMContext):
    await state.clear()
    await msg.answer(
        "<b>📖 Справка</b>\n\n"

        "<b>🧮 Калькулятор</b>\n"
        "Жми кнопки или пиши пример:\n"
        "<code>2 + 2</code>  ·  <code>(10+5)/3</code>\n\n"

        "<b>📊 Дроби</b>\n"
        "<code>1/2 + 3/4</code> → 5/4  (≈ 1.25)\n"
        "<code>2/3 * 5/7</code> → 10/21\n\n"

        "<b>🤖 Мини ИИ</b>\n"
        "Выбери предмет и задай вопрос.\n"
        "Математика · История · Русский язык\n"
        "География · Физика · Биология · Литература\n\n"

        "/start · /help · /calc · /frac · /ai",
        reply_markup=kb_main())


# ════════════════════════════════════════════
# 📨  ОБРАБОТЧИКИ — КАЛЬКУЛЯТОР
# ════════════════════════════════════════════

@router.message(F.text == "🧮 Калькулятор")
@router.message(Command("calc"))
async def open_calc(msg: Message, state: FSMContext):
    await state.clear()
    uid = msg.from_user.id
    # Если написали /calc 2+2  — считаем сразу
    parts = msg.text.split(maxsplit=1)
    if len(parts) > 1 and parts[0].startswith("/"):
        result = calc_normal(parts[1])
        await msg.answer(f"🧮 <code>{escape(parts[1])}</code>\n"
                         f"<b>= {escape(result)}</b>")
        return
    uc[uid] = {"expr": "", "mode": "normal"}
    await msg.answer(
        "🧮 <b>Калькулятор</b>  (🔢 обычный)\n\n"
        "Жми кнопки или пиши пример текстом.\n\n"
        "📟 <code>0</code>",
        reply_markup=kb_calc())


@router.message(F.text == "📊 Дроби")
@router.message(Command("frac"))
async def open_frac(msg: Message, state: FSMContext):
    await state.clear()
    uid = msg.from_user.id
    parts = msg.text.split(maxsplit=1)
    if len(parts) > 1 and parts[0].startswith("/"):
        result = calc_frac(parts[1])
        await msg.answer(f"📊 <code>{escape(parts[1])}</code>\n"
                         f"<b>= {escape(result)}</b>")
        return
    uc[uid] = {"expr": "", "mode": "fraction"}
    await msg.answer(
        "📊 <b>Калькулятор дробей</b>\n\n"
        "Жми кнопки или пиши пример:\n"
        "<code>1/2 + 3/4</code>  ·  <code>2/3 * 5/7</code>\n\n"
        "📟 <code>0</code>",
        reply_markup=kb_calc())


# --- Inline-кнопки калькулятора ---
@router.callback_query(F.data.startswith("c:"))
async def cb_calc(call: CallbackQuery):
    uid = call.from_user.id
    btn = call.data[2:]

    if uid not in uc:
        uc[uid] = {"expr": "", "mode": "normal"}
    d = uc[uid]

    expr = d["expr"]
    mode = d["mode"]

    if btn == "C":
        expr = ""
        show = "0"

    elif btn == "⌫":
        expr = expr[:-1]
        show = expr or "0"

    elif btn == "=":
        show = calc_frac(expr) if mode == "fraction" else calc_normal(expr)
        expr = ""

    elif btn == "mode":
        mode = "fraction" if mode == "normal" else "normal"
        d["mode"] = mode
        show = expr or "0"

    elif btn == "menu":
        await call.message.delete()
        await call.message.answer("👋 Главное меню:", reply_markup=kb_main())
        await call.answer()
        return

    else:
        ch = {"÷": "/", "×": "*", "−": "-"}.get(btn, btn)
        if len(expr) < 100:
            expr += ch
        show = expr

    d["expr"] = expr
    lbl = "📊 дроби" if mode == "fraction" else "🔢 обычный"

    try:
        await call.message.edit_text(
            f"🧮 <b>Калькулятор</b>  ({lbl})\n\n"
            f"📟 <code>{escape(show)}</code>",
            reply_markup=kb_calc())
    except Exception:
        pass
    await call.answer()


# ════════════════════════════════════════════
# 📨  ОБРАБОТЧИКИ — МИНИ ИИ
# ════════════════════════════════════════════

@router.message(F.text == "🤖 Мини ИИ")
@router.message(Command("ai"))
async def open_ai_menu(msg: Message, state: FSMContext):
    await state.clear()
    await state.set_state(AI.choosing)
    await msg.answer(
        "🤖 <b>Мини ИИ — Умный помощник</b>\n\n"
        "Выбери предмет и задавай вопросы! 🧠",
        reply_markup=kb_subj())


# --- Inline-кнопки предметов ---
@router.callback_query(F.data.startswith("s:"))
async def cb_subject(call: CallbackQuery, state: FSMContext):
    key = call.data[2:]

    if key == "back":
        await state.clear()
        await call.message.delete()
        await call.message.answer("👋 Главное меню:",
                                  reply_markup=kb_main())
        await call.answer()
        return

    if key == "change":
        await state.set_state(AI.choosing)
        await state.update_data(history=[])
        try:
            await call.message.edit_text(
                "🤖 <b>Выбери предмет:</b>",
                reply_markup=kb_subj())
        except Exception:
            pass
        await call.answer()
        return

    if key not in SUBJ:
        await call.answer("❓ Неизвестный предмет")
        return

    name, _ = SUBJ[key]
    await state.set_state(AI.chatting)
    await state.update_data(subject=key, history=[])

    try:
        await call.message.edit_text(
            f"🤖 Предмет: <b>{name}</b>\n\n"
            f"Задавай вопросы — я помогу! ✍️\n"
            f"<i>Просто напиши свой вопрос…</i>",
            reply_markup=kb_ai_nav())
    except Exception:
        pass
    await call.answer()


# --- Сообщения в AI-чате ---
@router.message(AI.chatting)
async def ai_question(msg: Message, state: FSMContext):
    data  = await state.get_data()
    key   = data.get("subject", "general")
    hist  = data.get("history", [])
    name  = SUBJ.get(key, SUBJ["general"])[0]

    wait = await msg.answer(f"🤔 <i>Думаю… ({name})</i>")

    answer = await ask_ai(msg.text, key, hist)

    # сохраняем историю
    hist.append({"role": "user",      "content": msg.text})
    hist.append({"role": "assistant", "content": answer})
    await state.update_data(history=hist)

    try:
        await wait.delete()
    except Exception:
        pass

    text = f"💬 <b>{name}</b>\n\n{escape(answer)}"
    if len(text) > 4000:
        # разбиваем длинный ответ
        for i in range(0, len(text), 4000):
            chunk = text[i:i+4000]
            if i + 4000 >= len(text):
                await msg.answer(chunk, reply_markup=kb_ai_nav())
            else:
                await msg.answer(chunk)
    else:
        await msg.answer(text, reply_markup=kb_ai_nav())


# --- Если в AI.choosing пишут текст, а не жмут кнопку ---
@router.message(AI.choosing)
async def ai_choosing_hint(msg: Message):
    await msg.answer("👆 Выбери предмет из списка выше!",
                     reply_markup=kb_subj())


# ════════════════════════════════════════════
# 📨  ВСЁ ОСТАЛЬНОЕ  (catch-all)
# ════════════════════════════════════════════

@router.message()
async def fallback(msg: Message):
    """Если пользователь просто прислал текст."""
    text = msg.text
    if not text:
        return

    # Попробуем посчитать, если похоже на пример
    test = _norm(text.strip())
    if _OK.match(test) and any(c.isdigit() for c in test):
        uid  = msg.from_user.id
        mode = uc.get(uid, {}).get("mode", "normal")
        res  = calc_frac(text) if mode == "fraction" else calc_normal(text)
        await msg.answer(
            f"🧮 <code>{escape(text.strip())}</code>\n"
            f"<b>= {escape(res)}</b>")
    else:
        await msg.answer(
            "🤔 Не понял. Выбери действие в меню 👇\n"
            "Или напиши математический пример.",
            reply_markup=kb_main())


# ════════════════════════════════════════════
# 🏁  ЗАПУСК
# ════════════════════════════════════════════

async def main():
    log.info("🚀 Бот запускается…")
    await bot.delete_webhook(drop_pending_updates=True)
    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())