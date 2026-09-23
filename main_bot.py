# main_bot.py — ОСНОВНОЙ бот: витрина и продажи (оплата LTC вручную)
import asyncio
from aiogram import Bot, Dispatcher, F
from aiogram.types import Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.filters import CommandStart, Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.storage.memory import MemoryStorage
from config import BOT_TOKEN, ADMIN_IDS, DB_PATH, SUPPORT_USERNAME
from db import (get_products, get_product, add_order, attach_proof,
                get_user_orders, get_setting, init_db)

bot = Bot(token=BOT_TOKEN)
dp = Dispatcher(storage=MemoryStorage())

class PayFlow(StatesGroup):
    waiting_proof = State()  # ждём txid/скрин от клиента

# ---------- клавиатуры ----------
def menu_kb():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🛍 Каталог", callback_data="menu_catalog")],
        [InlineKeyboardButton(text="🆘 Поддержка", callback_data="menu_support"),
         InlineKeyboardButton(text="📦 Мои заказы", callback_data="menu_orders")]
    ])

def catalog_kb(products):
    rows = [[InlineKeyboardButton(text=f"{p[1]} — {p[2]}$", callback_data=f"buy_{p[0]}")]
            for p in products]
    rows.append([InlineKeyboardButton(text="◀️ В меню", callback_data="menu")])
    return InlineKeyboardMarkup(inline_keyboard=rows)

def back_kb(where="menu_catalog", label="◀️ Назад"):
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=label, callback_data=where)]])

STATUS_ICONS = {"waiting": "⏳", "paid": "✅", "rejected": "❌"}

# ---------- главное меню ----------
@dp.message(CommandStart())
async def start(m: Message):
    await m.answer("🛍 *Добро пожаловать в магазин!*\nВыберите раздел:",
                   parse_mode="Markdown", reply_markup=menu_kb())

@dp.callback_query(F.data == "menu")
async def to_menu(c: CallbackQuery):
    await c.message.edit_text("🛍 *Главное меню*\nВыберите раздел:",
                              parse_mode="Markdown", reply_markup=menu_kb())

@dp.callback_query(F.data == "menu_support")
async def support(c: CallbackQuery):
    await c.message.edit_text(
        f"🆘 *Поддержка*\n\nПо любым вопросам пишите: {SUPPORT_USERNAME}",
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text=f"✍️ Написать {SUPPORT_USERNAME}",
                                  url=f"https://t.me/{SUPPORT_USERNAME.lstrip('@')}")],
            [InlineKeyboardButton(text="◀️ В меню", callback_data="menu")]
        ]))

@dp.callback_query(F.data == "menu_orders")
async def my_orders(c: CallbackQuery):
    orders = await get_user_orders(DB_PATH, c.from_user.id)
    if not orders:
        txt = "У вас пока нет заказов."
    else:
        txt = "\n".join(f"{STATUS_ICONS.get(o[3],'')} #{o[0]} — {o[1]} — {o[2]}$ ({o[4]})"
                         for o in orders)
    await c.message.edit_text(f"📦 *Ваши заказы:*\n{txt}", parse_mode="Markdown",
                              reply_markup=back_kb("menu", "◀️ В меню"))

@dp.callback_query(F.data == "menu_catalog")
async def catalog(c: CallbackQuery):
    await c.message.edit_text("🛍 *Каталог:*", parse_mode="Markdown",
                              reply_markup=catalog_kb(await get_products(DB_PATH)))

# ---------- товар и оплата ----------
@dp.callback_query(F.data.startswith("buy_"))
async def show_product(c: CallbackQuery):
    p = await get_product(DB_PATH, int(c.data.split("_")[1]))
    if not p:
        return await c.answer("Товар снят с продажи", show_alert=True)
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=f"💰 Купить за {p[2]}$", callback_data=f"pay_{p[0]}")],
        [InlineKeyboardButton(text="◀️ Назад к каталогу", callback_data="menu_catalog")]
    ])
    await c.message.edit_text(f"*{p[1]}*\n\n{p[3]}", parse_mode="Markdown", reply_markup=kb)

@dp.callback_query(F.data.startswith("pay_"))
async def pay(c: CallbackQuery, state: FSMContext):
    p = await get_product(DB_PATH, int(c.data.split("_")[1]))
    wallet = await get_setting(DB_PATH, "ltc_wallet")
    await state.set_state(PayFlow.waiting_proof)
    await state.update_data(product_id=p[0], amount=p[2], name=p[1],
                            chat_id=c.message.chat.id, msg_id=c.message.message_id)
    await c.message.edit_text(
        f"💰 *Оплата: «{p[1]}» — {p[2]}$ в LTC*\n\n"
        f"Отправьте эквивалент на адрес:\n`{wallet}`\n\n"
        f"После отправки пришлите сюда *TXID транзакции* или скриншот перевода.",
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="❌ Отмена", callback_data="cancel_pay")]]))

@dp.callback_query(F.data == "cancel_pay")
async def cancel_pay(c: CallbackQuery, state: FSMContext):
    await state.clear()
    await c.message.edit_text("❌ Оплата отменена.", reply_markup=back_kb("menu_catalog"))

async def close_window(bot_msg, text, kb=None):
    """Сворачиваем текущее окно: редактируем его в финальный текст."""
    try:
        await bot_msg.edit_text(text, parse_mode="Markdown", reply_markup=kb)
    except Exception:
        await bot_msg.answer(text, parse_mode="Markdown", reply_markup=kb)

@dp.message(PayFlow.waiting_proof, F.text | F.photo)
async def proof(m: Message, state: FSMContext):
    data = await state.get_data()
    await state.clear()
    username = m.from_user.username or "без username"
    order_id = await add_order(DB_PATH, m.from_user.id, username,
                               data["product_id"], data["amount"])
    proof_txt = m.text if m.text else "[скриншот]"
    await attach_proof(DB_PATH, order_id, proof_txt)

    # Сворачиваем окно оплаты в подтверждение
    from aiogram.types import Message as TgMessage
    fake = TgMessage(message_id=data["msg_id"], chat=data["chat_id"])
    await close_window(fake, f"⏳ *Заявка #{order_id} на проверке.*\nРезультат пришлю сюда.")

    # Уведомляем админов с кнопками подтверждения
    kb = InlineKeyboardMarkup(inline_keyboard=[[
        InlineKeyboardButton(text="✅ Подтвердить", callback_data=f"ok_{order_id}"),
        InlineKeyboardButton(text="❌ Отклонить", callback_data=f"no_{order_id}")]])
    for aid in ADMIN_IDS:
        await bot.send_message(
            aid,
            f"🆕 Заказ #{order_id}\nТовар: {data['name']}\n"
            f"Сумма: {data['amount']}$\nКлиент: @{username} (id {m.from_user.id})\n"
            f"Подтверждение: {proof_txt}",
            reply_markup=kb)
        if m.photo:
            await bot.send_photo(aid, m.photo[-1].file_id,
                                 caption=f"Скриншот к заказу #{order_id}")

@dp.message(PayFlow.waiting_proof)
async def proof_wrong(m: Message):
    await m.answer("Пришлите TXID текстом или скриншотом. Или нажмите «❌ Отмена».")

@dp.message(Command("orders"))
async def my_orders_cmd(m: Message):
    orders = await get_user_orders(DB_PATH, m.from_user.id)
    if not orders:
        return await m.answer("У вас пока нет заказов.")
    txt = "\n".join(f"{STATUS_ICONS.get(o[3],'')} #{o[0]} — {o[1]} — {o[2]}$ ({o[4]})"
                     for o in orders)
    await m.answer(f"📦 Ваши заказы:\n{txt}")

async def main():
    await init_db(DB_PATH)
    from config import LTC_WALLET
    from db import set_setting
    if not await get_setting(DB_PATH, "ltc_wallet"):
        await set_setting(DB_PATH, "ltc_wallet", LTC_WALLET)
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
