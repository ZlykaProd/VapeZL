import asyncio
import logging
import sqlite3
from datetime import datetime

from aiogram import Bot, Dispatcher, F
from aiogram.filters import Command, CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.types import Message, CallbackQuery
from aiogram.utils.keyboard import InlineKeyboardBuilder

# ================== НАСТРОЙКИ ==================
BOT_TOKEN = "8869442349:AAHiDPLfOy0YGSvD0QXfvZuuvMoJ75KebL4"
ADMINS = {"yazlyka", "miii69_54"}  # username без @, в нижнем регистре
DB_PATH = "reviews.db"
# ================================================

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
)
logger = logging.getLogger("VapeZL")

bot = Bot(token=BOT_TOKEN)
dp = Dispatcher(storage=MemoryStorage())


# ================== БАЗА ДАННЫХ ==================
def db_connect():
    return sqlite3.connect(DB_PATH, timeout=10)


def db_init():
    with db_connect() as con:
        cur = con.cursor()
        cur.execute("""
            CREATE TABLE IF NOT EXISTS allowed_users (
                username TEXT PRIMARY KEY
            )
        """)
        cur.execute("""
            CREATE TABLE IF NOT EXISTS reviews (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                seller TEXT NOT NULL,
                username TEXT NOT NULL,
                stars INTEGER NOT NULL CHECK(stars BETWEEN 1 AND 5),
                info TEXT NOT NULL,
                price TEXT NOT NULL DEFAULT '',
                date TEXT NOT NULL,
                UNIQUE(username, seller)
            )
        """)
        # Совместимость с reviews.db, созданной старой версией:
        # добавляем уникальный индекс, только если старых дублей нет.
        cur.execute("""
            CREATE INDEX IF NOT EXISTS idx_reviews_seller_id
            ON reviews(seller, id DESC)
        """)
        con.commit()


def normalize_username(username: str) -> str:
    return username.strip().lstrip("@").lower()


def is_allowed(username: str) -> bool:
    if not username:
        return False
    with db_connect() as con:
        row = con.execute(
            "SELECT 1 FROM allowed_users WHERE username = ?",
            (normalize_username(username),),
        ).fetchone()
    return row is not None


def add_allowed(username: str):
    with db_connect() as con:
        con.execute(
            "INSERT OR IGNORE INTO allowed_users (username) VALUES (?)",
            (normalize_username(username),),
        )


def del_allowed(username: str):
    with db_connect() as con:
        con.execute(
            "DELETE FROM allowed_users WHERE username = ?",
            (normalize_username(username),),
        )


def user_has_review(username: str, seller: str) -> bool:
    if not username:
        return False
    with db_connect() as con:
        row = con.execute(
            "SELECT 1 FROM reviews WHERE lower(username) = ? AND seller = ?",
            (normalize_username(username), seller),
        ).fetchone()
    return row is not None


def add_review(seller, username, stars, info, price):
    if not username:
        return False
    try:
        with db_connect() as con:
            con.execute(
                """INSERT INTO reviews
                   (seller, username, stars, info, price, date)
                   VALUES (?, ?, ?, ?, ?, ?)""",
                (
                    seller,
                    normalize_username(username),
                    int(stars),
                    info,
                    str(price),
                    datetime.now().strftime("%d.%m.%Y %H:%M"),
                ),
            )
        return True
    except sqlite3.IntegrityError:
        return False


def get_reviews(seller: str):
    with db_connect() as con:
        rows = con.execute(
            """SELECT id, username, stars, info, price, date
               FROM reviews WHERE seller = ? ORDER BY id DESC""",
            (seller,),
        ).fetchall()
    return rows


def get_allowed_users():
    with db_connect() as con:
        return [
            row[0]
            for row in con.execute(
                "SELECT username FROM allowed_users ORDER BY username"
            ).fetchall()
        ]


def delete_review(review_id: int):
    with db_connect() as con:
        con.execute("DELETE FROM reviews WHERE id = ?", (review_id,))


def get_review(review_id: int):
    with db_connect() as con:
        return con.execute(
            "SELECT id, seller, username, stars, info, price, date "
            "FROM reviews WHERE id = ?",
            (review_id,),
        ).fetchone()


# ================== FSM ==================
class AddUser(StatesGroup):
    waiting_username = State()


# ================== КЛАВИАТУРЫ ==================
def main_menu(admin_user=False):
    kb = InlineKeyboardBuilder()
    kb.button(text="✍️  Оставить отзыв", callback_data="leave")
    kb.button(text="📋  Смотреть отзывы", callback_data="view")
    if admin_user:
        kb.button(text="⚙️  Панель администратора", callback_data="admin")
    kb.adjust(1)
    return kb.as_markup()


def sellers_kb():
    kb = InlineKeyboardBuilder()
    kb.button(text="🟣  Zlyka", callback_data="seller_zlyka")
    kb.button(text="🔵  Пар№1 НК", callback_data="seller_park")
    kb.button(text="◀️  Главное меню", callback_data="back_main")
    kb.adjust(1)
    return kb.as_markup()


def zlyka_products_kb():
    kb = InlineKeyboardBuilder()
    kb.button(text="📦 Фулл бак · 100₽", callback_data="z|Фулл бак|100")
    kb.button(text="📦 Пол бака · 80₽", callback_data="z|Пол бака|80")
    kb.button(text="⚡ Фулл бак пасик · 150₽", callback_data="z|Фулл бак пасик|150")
    kb.button(text="⚡ Пол бака пасик · 100₽", callback_data="z|Пол бака пасик|100")
    kb.button(text="◀️  Назад", callback_data="leave")
    kb.adjust(1)
    return kb.as_markup()


def park_products_kb():
    kb = InlineKeyboardBuilder()
    products = [
        ("📦 Кт", "Кт"),
        ("📦 Подик", "Подик"),
        ("📦 Снюс", "Снюс"),
        ("📦 Одноразка", "Одноразка"),
        ("📦 Испарик", "Испарик"),
        ("📦 Жижа", "Жижа"),
    ]
    for label, product in products:
        kb.button(text=label, callback_data=f"p|{product}")
    kb.button(text="◀️  Назад", callback_data="leave")
    kb.adjust(2, 2, 2, 1)
    return kb.as_markup()


def stars_kb(prefix: str):
    kb = InlineKeyboardBuilder()
    for i in range(1, 6):
        kb.button(text=f"{'⭐' * i}  {i}/5", callback_data=f"{prefix}|{i}")
    kb.button(text="◀️  Назад", callback_data="leave")
    kb.adjust(3, 2, 1)
    return kb.as_markup()


def reviews_menu_kb():
    kb = InlineKeyboardBuilder()
    kb.button(text="🟣  Отзывы о Zlyka", callback_data="view_zlyka")
    kb.button(text="🔵  Отзывы о Пар№1 НК", callback_data="view_park")
    kb.button(text="◀️  Главное меню", callback_data="back_main")
    kb.adjust(1)
    return kb.as_markup()


def admin_menu_kb():
    kb = InlineKeyboardBuilder()
    kb.button(text="➕  Добавить пользователя", callback_data="admin_add")
    kb.button(text="➖  Удалить пользователя", callback_data="admin_del_user")
    kb.button(text="🗑️  Удалить отзыв", callback_data="admin_del_review")
    kb.button(text="◀️  Главное меню", callback_data="back_main")
    kb.adjust(1)
    return kb.as_markup()


def admin_del_review_kb():
    kb = InlineKeyboardBuilder()
    kb.button(text="🟣  Отзывы о Zlyka", callback_data="adelrev|zlyka")
    kb.button(text="🔵  Отзывы о Пар№1 НК", callback_data="adelrev|park")
    kb.button(text="◀️  В админ-панель", callback_data="admin")
    kb.adjust(1)
    return kb.as_markup()


# ================== ХЕЛПЕРЫ ==================
def is_admin(username):
    return bool(username) and normalize_username(username) in ADMINS


def fmt_reviews(rows, with_price=True):
    if not rows:
        return "📭 Отзывов пока нет."

    output = []
    for _, username, stars, info, price, date in rows:
        text = (
            f"👤 @{username}\n"
            f"⭐ {'⭐' * stars} ({stars}/5)\n"
            f"📦 {info}\n"
        )
        if with_price and price:
            text += f"💰 {price}₽\n"
        text += f"🕐 {date}"
        output.append(text)

    return "\n\n➖➖➖➖➖\n\n".join(output)


async def safe_edit(message: Message, text: str, reply_markup=None):
    """Изменяет сообщение; если текст тот же, не роняет обработчик."""
    try:
        await message.edit_text(text, reply_markup=reply_markup)
    except Exception as exc:
        # Telegram выдаёт ошибку, если текст и клавиатура не изменились.
        if "message is not modified" not in str(exc).lower():
            raise


async def show_reviews_page(
    cb: CallbackQuery,
    seller: str,
    page: int = 0,
    delete_mode: bool = False,
):
    rows = get_reviews(seller)
    page_size = 5
    total_pages = max(1, (len(rows) + page_size - 1) // page_size)
    page = max(0, min(page, total_pages - 1))
    current = rows[page * page_size:(page + 1) * page_size]

    seller_name = "Zlyka" if seller == "zlyka" else "Пар№1 НК"
    if delete_mode:
        text = f"🗑️ Удаление отзывов: {seller_name}\n\nВыбери отзыв:"
        kb = InlineKeyboardBuilder()
        for rid, username, stars, info, price, date in current:
            label = f"#{rid} @{username} | {'⭐' * stars} | {info}"
            kb.button(text=label[:60], callback_data=f"dorev|{rid}|{seller}|{page}")
        if page > 0:
            kb.button(text="⬅️ Предыдущая", callback_data=f"adelpage|{seller}|{page - 1}")
        if page < total_pages - 1:
            kb.button(text="Следующая ➡️", callback_data=f"adelpage|{seller}|{page + 1}")
        kb.button(text="◀️ Назад", callback_data="admin_del_review")
        kb.adjust(1)
        await safe_edit(cb.message, text, kb.as_markup())
    else:
        text = f"📋 Отзывы о {seller_name}\n\n{fmt_reviews(current, with_price=(seller == 'zlyka'))}"
        kb = InlineKeyboardBuilder()
        if page > 0:
            kb.button(text="⬅️ Предыдущая", callback_data=f"revpage|{seller}|{page - 1}")
        if page < total_pages - 1:
            kb.button(text="Следующая ➡️", callback_data=f"revpage|{seller}|{page + 1}")
        kb.button(text="◀️ К выбору продавца", callback_data="view")
        kb.adjust(2, 1)
        await safe_edit(cb.message, text[:4000], kb.as_markup())


# ================== ОСНОВНЫЕ ХЕНДЛЕРЫ ==================
@dp.message(CommandStart())
async def cmd_start(msg: Message, state: FSMContext):
    await state.clear()
    await msg.answer(
        "👋 Добро пожаловать в VapeZL!\n\n"
        "⭐ Здесь ты можешь оставить отзыв "
        "или ознакомиться с отзывами других пользователей.\n\n"
        "👇 Выбери нужное действие:",
        reply_markup=main_menu(is_admin(msg.from_user.username)),
    )


@dp.message(Command("cancel"))
async def cancel_command(msg: Message, state: FSMContext):
    await state.clear()
    await msg.answer(
        "↩️ Действие отменено.\n\nГлавное меню VapeZL:",
        reply_markup=main_menu(is_admin(msg.from_user.username)),
    )


@dp.callback_query(F.data == "back_main")
async def back_main(cb: CallbackQuery, state: FSMContext):
    await state.clear()
    await safe_edit(
        cb.message,
        "👋 Главное меню VapeZL:\n\nВыбери нужное действие:",
        reply_markup=main_menu(is_admin(cb.from_user.username)),
    )
    await cb.answer()


# ---------- ОСТАВИТЬ ОТЗЫВ ----------
@dp.callback_query(F.data == "leave")
async def leave(cb: CallbackQuery):
    username = cb.from_user.username
    if not username or not is_allowed(username):
        await cb.answer(
            "❌ Тебя нет в списке разрешённых. Попроси админа добавить тебя.",
            show_alert=True,
        )
        return
    await safe_edit(cb.message, "📝 Выбери продавца:", reply_markup=sellers_kb())
    await cb.answer()


@dp.callback_query(F.data == "seller_zlyka")
async def seller_zlyka(cb: CallbackQuery):
    username = cb.from_user.username
    if not username or not is_allowed(username):
        await cb.answer("❌ Нет доступа. Попроси админа добавить тебя.", show_alert=True)
        return
    if user_has_review(username, "zlyka"):
        await cb.answer("❌ Ты уже оставлял отзыв про Zlyka!", show_alert=True)
        return
    await safe_edit(cb.message, "🟣 Zlyka\n\nВыбери, что брал:", reply_markup=zlyka_products_kb())
    await cb.answer()


@dp.callback_query(F.data == "seller_park")
async def seller_park(cb: CallbackQuery):
    username = cb.from_user.username
    if not username or not is_allowed(username):
        await cb.answer("❌ Нет доступа. Попроси админа добавить тебя.", show_alert=True)
        return
    if user_has_review(username, "park"):
        await cb.answer("❌ Ты уже оставлял отзыв про Пар№1 НК!", show_alert=True)
        return
    await safe_edit(cb.message, "🔵 Пар№1 НК\n\nВыбери, что купил:", reply_markup=park_products_kb())
    await cb.answer()


@dp.callback_query(F.data.startswith("z|"))
async def z_product(cb: CallbackQuery):
    username = cb.from_user.username
    if not username or not is_allowed(username):
        await cb.answer("❌ Нет доступа.", show_alert=True)
        return
    if user_has_review(username, "zlyka"):
        await cb.answer("❌ Ты уже оставлял отзыв про Zlyka!", show_alert=True)
        return
    try:
        _, name, price = cb.data.split("|", 2)
    except ValueError:
        await cb.answer("❌ Некорректный товар.", show_alert=True)
        return
    await safe_edit(
        cb.message,
        f"🛍️ Выбрано: {name} · {price}₽\n\n⭐ Оцени продавца:",
        reply_markup=stars_kb(f"zstar|{name}|{price}"),
    )
    await cb.answer()


@dp.callback_query(F.data.startswith("p|"))
async def p_product(cb: CallbackQuery):
    username = cb.from_user.username
    if not username or not is_allowed(username):
        await cb.answer("❌ Нет доступа.", show_alert=True)
        return
    if user_has_review(username, "park"):
        await cb.answer("❌ Ты уже оставлял отзыв про Пар№1 НК!", show_alert=True)
        return
    _, name = cb.data.split("|", 1)
    await safe_edit(
        cb.message,
        f"🛍️ Выбрано: {name}\n\n⭐ Оцени продавца:",
        reply_markup=stars_kb(f"pstar|{name}"),
    )
    await cb.answer()


@dp.callback_query(F.data.startswith("zstar|"))
async def z_star(cb: CallbackQuery):
    username = cb.from_user.username
    if not username or not is_allowed(username):
        await cb.answer("❌ Нет доступа.", show_alert=True)
        return
    if user_has_review(username, "zlyka"):
        await cb.answer("❌ Ты уже оставлял отзыв про Zlyka!", show_alert=True)
        return

    try:
        _, name, price, stars = cb.data.split("|", 3)
        stars = int(stars)
        if not 1 <= stars <= 5:
            raise ValueError
    except ValueError:
        await cb.answer("❌ Некорректная оценка.", show_alert=True)
        return

    if not add_review("zlyka", username, stars, name, price):
        await cb.answer("❌ Отзыв уже существует или не удалось сохранить.", show_alert=True)
        return

    await safe_edit(
        cb.message,
        "✅ Отзыв оставлен!\n\n"
        "🟣 Продавец: Zlyka\n"
        f"📦 Товар: {name}\n"
        f"💰 Цена: {price}₽\n"
        f"⭐ Оценка: {'⭐' * stars} ({stars}/5)",
        reply_markup=main_menu(is_admin(username)),
    )
    await cb.answer("Спасибо за отзыв!")


@dp.callback_query(F.data.startswith("pstar|"))
async def p_star(cb: CallbackQuery):
    username = cb.from_user.username
    if not username or not is_allowed(username):
        await cb.answer("❌ Нет доступа.", show_alert=True)
        return
    if user_has_review(username, "park"):
        await cb.answer("❌ Ты уже оставлял отзыв про Пар№1 НК!", show_alert=True)
        return

    try:
        _, name, stars = cb.data.split("|", 2)
        stars = int(stars)
        if not 1 <= stars <= 5:
            raise ValueError
    except ValueError:
        await cb.answer("❌ Некорректная оценка.", show_alert=True)
        return

    if not add_review("park", username, stars, name, ""):
        await cb.answer("❌ Отзыв уже существует или не удалось сохранить.", show_alert=True)
        return

    await safe_edit(
        cb.message,
        "✅ Отзыв оставлен!\n\n"
        "🔵 Продавец: Пар№1 НК\n"
        f"📦 Товар: {name}\n"
        f"⭐ Оценка: {'⭐' * stars} ({stars}/5)",
        reply_markup=main_menu(is_admin(username)),
    )
    await cb.answer("Спасибо за отзыв!")


# ---------- СМОТРЕТЬ ОТЗЫВЫ ----------
@dp.callback_query(F.data == "view")
async def view(cb: CallbackQuery):
    await safe_edit(cb.message, "📋 Чьи отзывы смотреть?", reply_markup=reviews_menu_kb())
    await cb.answer()


@dp.callback_query(F.data == "view_zlyka")
async def view_zlyka(cb: CallbackQuery):
    await show_reviews_page(cb, "zlyka", 0)
    await cb.answer()


@dp.callback_query(F.data == "view_park")
async def view_park(cb: CallbackQuery):
    await show_reviews_page(cb, "park", 0)
    await cb.answer()


@dp.callback_query(F.data.startswith("revpage|"))
async def reviews_page(cb: CallbackQuery):
    try:
        _, seller, page = cb.data.split("|", 2)
        page = int(page)
        if seller not in {"zlyka", "park"}:
            raise ValueError
    except ValueError:
        await cb.answer("Некорректная страница.", show_alert=True)
        return
    await show_reviews_page(cb, seller, page)
    await cb.answer()


# ---------- АДМИН-ПАНЕЛЬ ----------
@dp.callback_query(F.data == "admin")
async def admin(cb: CallbackQuery):
    if not is_admin(cb.from_user.username):
        await cb.answer("⛔ Нет доступа", show_alert=True)
        return
    await safe_edit(cb.message, "⚙️ Панель администратора VapeZL:", reply_markup=admin_menu_kb())
    await cb.answer()


@dp.callback_query(F.data == "admin_add")
async def admin_add(cb: CallbackQuery, state: FSMContext):
    if not is_admin(cb.from_user.username):
        await cb.answer("⛔ Нет доступа", show_alert=True)
        return
    await state.set_state(AddUser.waiting_username)
    await safe_edit(
        cb.message,
        "➕ Добавление пользователя\n\n"
        "Отправь username пользователя с @ или без @.\n"
        "Для отмены отправь /cancel.",
    )
    await cb.answer()


@dp.message(AddUser.waiting_username)
async def process_add_user(msg: Message, state: FSMContext):
    if not is_admin(msg.from_user.username):
        await state.clear()
        await msg.answer("⛔ Нет доступа.")
        return
    if not msg.text:
        await msg.answer("❌ Отправь username текстом или /cancel.")
        return
    if msg.text.strip().lower() == "/cancel":
        await state.clear()
        await msg.answer("↩️ Отменено.", reply_markup=main_menu(True))
        return

    username = normalize_username(msg.text)
    if (
        not username
        or " " in username
        or len(username) > 32
        or not username.replace("_", "").isalnum()
    ):
        await msg.answer("❌ Неверный username. Попробуй снова или отправь /cancel.")
        return

    add_allowed(username)
    await state.clear()
    await msg.answer(
        f"✅ @{username} добавлен в список разрешённых.",
        reply_markup=main_menu(True),
    )


@dp.callback_query(F.data == "admin_del_user")
async def admin_del_user(cb: CallbackQuery):
    if not is_admin(cb.from_user.username):
        await cb.answer("⛔ Нет доступа", show_alert=True)
        return

    users = get_allowed_users()
    if not users:
        await safe_edit(cb.message, "📭 Список разрешённых пользователей пуст.", reply_markup=admin_menu_kb())
        await cb.answer()
        return

    kb = InlineKeyboardBuilder()
    for username in users:
        kb.button(text=f"❌ @{username}", callback_data=f"deluser|{username}")
    kb.button(text="◀️  В админ-панель", callback_data="admin")
    kb.adjust(1)
    await safe_edit(cb.message, "➖ Кого удалить из списка?", reply_markup=kb.as_markup())
    await cb.answer()


@dp.callback_query(F.data.startswith("deluser|"))
async def del_user(cb: CallbackQuery):
    if not is_admin(cb.from_user.username):
        await cb.answer("⛔ Нет доступа", show_alert=True)
        return

    username = cb.data.split("|", 1)[1]
    del_allowed(username)
    await cb.answer(f"Пользователь @{username} удалён.")
    # Не вызываем другой callback-хендлер: он повторно отвечал бы на callback.
    users = get_allowed_users()
    if not users:
        await safe_edit(cb.message, "📭 Список разрешённых пользователей пуст.", reply_markup=admin_menu_kb())
        return

    kb = InlineKeyboardBuilder()
    for user in users:
        kb.button(text=f"❌ @{user}", callback_data=f"deluser|{user}")
    kb.button(text="◀️  В админ-панель", callback_data="admin")
    kb.adjust(1)
    await safe_edit(cb.message, "➖ Кого удалить из списка?", reply_markup=kb.as_markup())


@dp.callback_query(F.data == "admin_del_review")
async def admin_del_review(cb: CallbackQuery):
    if not is_admin(cb.from_user.username):
        await cb.answer("⛔ Нет доступа", show_alert=True)
        return
    await safe_edit(cb.message, "🗑️ Отзывы какого продавца удалить?", reply_markup=admin_del_review_kb())
    await cb.answer()


@dp.callback_query(F.data.startswith("adelrev|"))
async def admin_del_review_list(cb: CallbackQuery):
    if not is_admin(cb.from_user.username):
        await cb.answer("⛔ Нет доступа", show_alert=True)
        return
    seller = cb.data.split("|", 1)[1]
    if seller not in {"zlyka", "park"}:
        await cb.answer("Некорректный продавец.", show_alert=True)
        return
    await show_reviews_page(cb, seller, 0, delete_mode=True)
    await cb.answer()


@dp.callback_query(F.data.startswith("adelpage|"))
async def admin_delete_page(cb: CallbackQuery):
    if not is_admin(cb.from_user.username):
        await cb.answer("⛔ Нет доступа", show_alert=True)
        return
    try:
        _, seller, page = cb.data.split("|", 2)
        page = int(page)
        if seller not in {"zlyka", "park"}:
            raise ValueError
    except ValueError:
        await cb.answer("Некорректная страница.", show_alert=True)
        return
    await show_reviews_page(cb, seller, page, delete_mode=True)
    await cb.answer()


@dp.callback_query(F.data.startswith("dorev|"))
async def do_del_review(cb: CallbackQuery):
    if not is_admin(cb.from_user.username):
        await cb.answer("⛔ Нет доступа", show_alert=True)
        return
    try:
        parts = cb.data.split("|")
        rid = int(parts[1])
        seller = parts[2] if len(parts) > 2 else "zlyka"
        page = int(parts[3]) if len(parts) > 3 else 0
        if seller not in {"zlyka", "park"}:
            raise ValueError
    except (ValueError, IndexError):
        await cb.answer("Некорректный отзыв.", show_alert=True)
        return

    review = get_review(rid)
    if not review:
        await cb.answer("Этот отзыв уже удалён.", show_alert=True)
        await show_reviews_page(cb, seller, page, delete_mode=True)
        return

    delete_review(rid)
    await cb.answer(f"Отзыв #{rid} удалён ✅")
    await show_reviews_page(cb, seller, page, delete_mode=True)


# ================== ЗАПУСК ==================
async def main():
    if BOT_TOKEN == "ТОКЕН_СЮДА" or not BOT_TOKEN.strip():
        raise RuntimeError("Укажи настоящий BOT_TOKEN в настройках файла.")

    db_init()
    logger.info("VapeZL запускается...")
    try:
        await dp.start_polling(bot)
    finally:
        await bot.session.close()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except (KeyboardInterrupt, SystemExit):
        logger.info("VapeZL остановлен.")
