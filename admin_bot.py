# admin_bot.py — АДМИН-БОТ: управление всей системой
import asyncio
from aiogram import Bot, Dispatcher, F
from aiogram.types import Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.storage.memory import MemoryStorage
from config import ADMIN_BOT_TOKEN, ADMIN_IDS, DB_PATH, LTC_WALLET
from db import (init_db, add_product, del_product, get_products, get_orders,
                get_stats, get_setting, set_setting, get_order, set_order_status)

bot = Bot(token=ADMIN_BOT_TOKEN)
dp = Dispatcher(storage=MemoryStorage())

main_bot_link = None  # для уведомлений клиентам (см. main() — берём из конфига)

class NewProduct(StatesGroup):
    name = State(); price = State(); desc = State()

class NewWallet(StatesGroup):
    address = State()

def is_admin(uid: int) -> bool:
    return uid in ADMIN_IDS

def main_kb():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="➕ Опубликовать товар", callback_data="add")],
        [InlineKeyboardButton(text="📦 Товары", callback_data="list"),
         InlineKeyboardButton(text="🧾 Заказы", callback_data="orders")],
        [InlineKeyboardButton(text="📊 Статистика", callback_data="stats")],
        [InlineKeyboardButton(text="💼 Сменить LTC-кошелёк", callback_data="wallet")]
    ])

@dp.message(Command("start", "admin"))
async def admin_panel(m: Message):
    if not is_admin(m.from_user.id):
        return await m.answer("⛔ Доступ запрещён.")
    wallet = await get_setting(DB_PATH, "ltc_wallet")
    await m.answer(f"🎛 Админ-панель магазина\n💼 Текущий кошелёк: `{wallet}`",
                   parse_mode="Markdown", reply_markup=main_kb())

# --- публикация товара ---
@dp.callback_query(F.data == "add")
async def add_start(c: CallbackQuery, state: FSMContext):
    await state.set_state(NewProduct.name)
    await c.message.answer("Введите название товара:")

@dp.message(NewProduct.name)
async def add_name(m: Message, state: FSMContext):
    await state.update_data(name=m.text)
    await state.set_state(NewProduct.price)
    await m.answer("Введите цену в долларах (число):")

@dp.message(NewProduct.price)
async def add_price(m: Message, state: FSMContext):
    try:
        price = float(m.text.replace(",", "."))
    except ValueError:
        return await m.answer("Нужно число, например 25 или 19.99. Попробуйте ещё раз:")
    await state.update_data(price=price)
    await state.set_state(NewProduct.desc)
    await m.answer("Введите описание товара:")

@dp.message(NewProduct.desc)
async def add_desc(m: Message, state: FSMContext):
    data = await state.get_data()
    pid = await add_product(DB_PATH, data["name"], data["price"], m.text)
    await state.clear()
    await m.answer(f"✅ Товар #{pid} «{data['name']}» опубликован — уже виден в основном боте!",
                   reply_markup=main_kb())

# --- товары ---
@dp.callback_query(F.data == "list")
async def list_products(c: CallbackQuery):
    products = await get_products(DB_PATH)
    if not products:
        return await c.answer("Товаров нет.", show_alert=True)
    for p in products:
        kb = InlineKeyboardMarkup(inline_keyboard=[[
            InlineKeyboardButton(text="🗑 Снять с продажи", callback_data=f"del_{p[0]}")]])
        await c.message.answer(f"#{p[0]} {p[1]} — {p[2]}$\n{p[3][:200]}", reply_markup=kb)
    await c.answer()

@dp.callback_query(F.data.startswith("del_"))
async def del_p(c: CallbackQuery):
    await del_product(DB_PATH, int(c.data.split("_")[1]))
    await c.message.edit_text(c.message.text + "\n\n❌ Снят с продажи")

# --- кошелёк ---
@dp.callback_query(F.data == "wallet")
async def wallet_start(c: CallbackQuery, state: FSMContext):
    cur = await get_setting(DB_PATH, "ltc_wallet")
    await state.set_state(NewWallet.address)
    await c.message.answer(f"Текущий адрес: `{cur}`\n\nВведите новый LTC-адрес:",
                           parse_mode="Markdown")

@dp.message(NewWallet.address)
async def wallet_set(m: Message, state: FSMContext):
    addr = m.text.strip()
    if not (addr.startswith("ltc1") or addr.startswith("L") or addr.startswith("M")):
        await m.answer("⚠️ Это не похоже на LTC-адрес. Проверьте и введите ещё раз:")
        return
    await set_setting(DB_PATH, "ltc_wallet", addr)
    await state.clear()
    await m.answer(f"✅ Кошелёк обновлён: `{addr}`", parse_mode="Markdown",
                   reply_markup=main_kb())

# --- заказы и подтверждение оплат ---
@dp.callback_query(F.data == "orders")
async def orders(c: CallbackQuery):
    ords = await get_orders(DB_PATH)
    if not ords:
        return await c.answer("Заказов пока нет.", show_alert=True)
    ic = {"waiting": "⏳", "paid": "✅", "rejected": "❌"}
    txt = "\n".join(f"{ic.get(o[4],'')} #{o[0]} | {o[1]} | {o[3]}$ | {o[5]}"
                     for o in ords[:30])
    await c.message.answer("🧾 Последние заказы:\n" + txt)
    await c.answer()

@dp.callback_query(F.data.startswith("ok_"))
async def confirm(c: CallbackQuery):
    oid = int(c.data.split("_")[1])
    await set_order_status(DB_PATH, oid, "paid")
    o = await get_order(DB_PATH, oid)
    await c.message.edit_text(c.message.text + "\n\n✅ ОПЛАТА ПОДТВЕРЖДЕНА")
    from main_bot import bot as client_bot
    await client_bot.send_message(o[2], f"✅ Заказ #{oid} «{o[1]}» оплачен! Свяжемся для выдачи.")
    await c.answer("Подтверждено")

@dp.callback_query(F.data.startswith("no_"))
async def reject(c: CallbackQuery):
    oid = int(c.data.split("_")[1])
    await set_order_status(DB_PATH, oid, "rejected")
    o = await get_order(DB_PATH, oid)
    await c.message.edit_text(c.message.text + "\n\n❌ ОТКЛОНЁН")
    from main_bot import bot as client_bot
    await client_bot.send_message(o[2], f"❌ Заказ #{oid} отклонён. Если вы оплатили — напишите менеджеру.")
    await c.answer("Отклонён")

# --- статистика ---
@dp.callback_query(F.data == "stats")
async def stats(c: CallbackQuery):
    s = await get_stats(DB_PATH)
    await c.message.answer(
        f"📊 Статистика\n├ Товаров в продаже: {s['products']}\n"
        f"├ Заказов всего: {s['orders']}\n├ Оплачено: {s['paid']}\n"
        f"└ Выручка: {s['revenue']}$", reply_markup=main_kb())
    await c.answer()

async def main():
    await init_db(DB_PATH)
    if not await get_setting(DB_PATH, "ltc_wallet"):
        await set_setting(DB_PATH, "ltc_wallet", LTC_WALLET)
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
