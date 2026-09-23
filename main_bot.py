# main_bot.py — ОСНОВНОЙ бот: витрина и продажи (оплата LTC вручную)
import asyncio
from aiogram import Bot, Dispatcher, F
from aiogram.types import Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.filters import CommandStart, Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.storage.memory import MemoryStorage
from config import BOT_TOKEN, ADMIN_IDS, DB_PATH
from db import (get_products, get_product, add_order, attach_proof,
                get_user_orders, get_order, get_setting, init_db)

bot = Bot(token=BOT_TOKEN)
dp = Dispatcher(storage=MemoryStorage())

class PayFlow(StatesGroup):
    waiting_proof = State()  # ждём txid/скрин от клиента

def catalog_kb(products):
    rows = [[InlineKeyboardButton(text=f"{p[1]} — {p[2]}$", callback_data=f"buy_{p[0]}")]
            for p in products]
    return InlineKeyboardMarkup(inline_keyboard=rows)

@dp.message(CommandStart())
async def start(m: Message):
    await m.answer("🛍 Добро пожаловать в магазин! Вот наши товары:",
                   reply_markup=catalog_kb(await get_products(DB_PATH)))

@dp.callback_query(F.data.startswith("buy_"))
async def show_product(c: CallbackQuery):
    p = await get_product(DB_PATH, int(c.data.split("_")[1]))
    if not p:
        return await c.answer("Товар снят с продажи", show_alert=True)
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=f"💰 Купить за {p[2]}$", callback_data=f"pay_{p[0]}")],
        [InlineKeyboardButton(text="◀️ Назад", callback_data="back")]
    ])
    await c.message.edit_text(f"*{p[1]}*\n\n{p[3]}", parse_mode="Markdown", reply_markup=kb)

@dp.callback_query(F.data == "back")
async def back(c: CallbackQuery):
    await c.message.edit_text("🛍 Каталог:",
        reply_markup=catalog_kb(await get_products(DB_PATH)))

@dp.callback_query(F.data.startswith("pay_"))
async def pay(c: CallbackQuery, state: FSMContext):
    p = await get_product(DB_PATH, int(c.data.split("_")[1]))
    wallet = await get_setting(DB_PATH, "ltc_wallet")
    await state.set_state(PayFlow.waiting_proof)
    await state.update_data(order_id=None, product_id=p[0], amount=p[2], name=p[1])
    await c.message.answer(
        f"💰 *Оплата товара «{p[1]}» — {p[2]}$ в LTC*\n\n"
        f"Отправьте эквивалент на адрес:\n`{wallet}`\n\n"
        f"После отправки пришлите сюда *TXID транзакции* или скриншот перевода.",
        parse_mode="Markdown")

@dp.message(PayFlow.waiting_proof, F.text | F.photo)
async def proof(m: Message, state: FSMContext):
    data = await state.get_data()
    username = m.from_user.username or "без username"
    order_id = await add_order(DB_PATH, m.from_user.id, username,
                               data["product_id"], data["amount"])
    proof_txt = m.text if m.text else "[скриншот]"
    await attach_proof(DB_PATH, order_id, proof_txt)

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
    await state.clear()
    await m.answer("⏳ Заявка на оплату создана! Ожидайте подтверждения — пришлю результат сюда.")

@dp.message(PayFlow.waiting_proof)
async def proof_wrong(m: Message):
    await m.answer("Пришлите TXID текстом или скриншотом.")

@dp.message(Command("orders"))
async def my_orders(m: Message):
    orders = await get_user_orders(DB_PATH, m.from_user.id)
    if not orders:
        return await m.answer("У вас пока нет заказов.")
    status = {"waiting": "⏳", "paid": "✅", "rejected": "❌"}
    txt = "\n".join(f"{status.get(o[3],'')} #{o[0]} — {o[1]} — {o[2]}$ ({o[4]})"
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
