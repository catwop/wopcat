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

def menu_btn():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="◀️ В меню", callback_data="panel")]])

async def render_panel(msg, user_id):
    wallet = await get_setting(DB_PATH, "ltc_wallet")
    await msg.edit_text(
        f"🎛 *Админ-панель магазина*\n💼 Кошелёк: `{wallet}`",
        parse_mode="Markdown", reply_markup=main_kb())

@dp.message(Command("start", "admin"))
async def admin_panel(m: Message):
    if not is_admin(m.from_user.id):
        return await m.answer("⛔ Доступ запрещён.")
    wallet = await get_setting(DB_PATH, "ltc_wallet")
    await m.answer(f"🎛 *Админ-панель магазина*\n💼 Кошелёк: `{wallet}`",
                   parse_mode="Markdown", reply_markup=main_kb())

@dp.callback_query(F.data == "panel")
async def panel(c: CallbackQuery):
    await render_panel(c.message, c.from_user.id)

# --- публикация товара (всё в одном окне) ---
@dp.callback_query(F.data == "add")
async def add_start(c: CallbackQuery, state: FSMContext):
    await state.set_state(NewProduct.name)
    msg = await c.message.edit_text("➕ *Новый товар*\n\nВведите название товара:",
                                    parse_mode="Markdown", reply_markup=menu_btn())
    await state.update_data(mid=msg.message_id)

async def edit_step(m: Message, state: FSMContext, text):
    data = await state.get_data()
    try:
        await m.bot.edit_message_text(text, chat_id=m.chat.id,
                                      message_id=data["mid"],
                                      parse_mode="Markdown", reply_markup=menu_btn())
    except Exception:
        pass
    await m.delete()  # убираем сообщение пользователя, чтобы окно не плодилось

@dp.message(NewProduct.name)
async def add_name(m: Message, state: FSMContext):
    await state.update_data(name=m.text)
    await state.set_state(NewProduct.price)
    await edit_step(m, state, f"➕ *Новый товар*\n\nНазвание: *{m.text}*\n\nТеперь введите цену в долларах (число):")

@dp.message(NewProduct.price)
async def add_price(m: Message, state: FSMContext):
    try:
        price = float(m.text.replace(",", "."))
    except ValueError:
        await m.delete()
        return await m.bot.send_message(m.chat.id, "⚠️ Нужно число, например 25 или 19.99. Введите ещё раз:")
    await state.update_data(price=price)
    await state.set_state(NewProduct.desc)
    await edit_step(m, state, f"➕ *Новый товар*\n\nНазвание: *{(await state.get_data())['name']}*\nЦена: *{price}$*\n\nТеперь введите описание:")

@dp.message(NewProduct.desc)
async def add_desc(m: Message, state: FSMContext):
    data = await state.get_data()
    pid = await add_product(DB_PATH, data["name"], data["price"], m.text)
    await state.clear()
    await m.delete()
    try:
        await m.bot.edit_message_text(
            f"✅ Товар #{pid} «{data['name']}» опубликован — уже виден в основном боте!",
            chat_id=m.chat.id, message_id=data["mid"], reply_markup=main_kb())
    except Exception:
        await m.answer(f"✅ Товар #{pid} «{data['name']}» опубликован!",
                       reply_markup=main_kb())

# --- товары (одно окно) ---
@dp.callback_query(F.data == "list")
async def list_products(c: CallbackQuery):
    products = await get_products(DB_PATH)
    if not products:
        return await c.message.edit_text("📦 Товаров нет.", reply_markup=menu_btn())
    rows = [[InlineKeyboardButton(text=f"🗑 #{p[0]} {p[1]} — {p[2]}$",
                                  callback_data=f"del_{p[0]}")] for p in products]
    rows.append([InlineKeyboardButton(text="◀️ В меню", callback_data="panel")])
    txt = "📦 *Товары в продаже:*\n\n" + "\n".join(
        f"#{p[0]} {p[1]} — {p[2]}$\n{p[3][:150]}" for p in products)
    await c.message.edit_text(txt, parse_mode="Markdown",
                              reply_markup=InlineKeyboardMarkup(inline_keyboard=rows))

@dp.callback_query(F.data.startswith("del_"))
async def del_p(c: CallbackQuery):
    await del_product(DB_PATH, int(c.data.split("_")[1]))
    await c.answer("Снят с продажи ✅")
    await list_products(c)

# --- кошелёк (одно окно) ---
@dp.callback_query(F.data == "wallet")
async def wallet_start(c: CallbackQuery, state: FSMContext):
    cur = await get_setting(DB_PATH, "ltc_wallet")
    await state.set_state(NewWallet.address)
    msg = await c.message.edit_text(f"💼 *Смена кошелька*\n\nТекущий: `{cur}`\n\nВведите новый LTC-адрес:",
                                    parse_mode="Markdown", reply_markup=menu_btn())
    await state.update_data(mid=msg.message_id)

@dp.message(NewWallet.address)
async def wallet_set(m: Message, state: FSMContext):
    addr = m.text.strip()
    if not (addr.startswith("ltc1") or addr.startswith("L") or addr.startswith("M")):
        await m.delete()
        return await m.bot.send_message(m.chat.id, "⚠️ Это не похоже на LTC-адрес. Проверьте и введите ещё раз:")
    await set_setting(DB_PATH, "ltc_wallet", addr)
    data = await state.get_data()
    await state.clear()
    await m.delete()
    try:
        await m.bot.edit_message_text(f"✅ Кошелёк обновлён: `{addr}`",
                                      chat_id=m.chat.id, message_id=data["mid"],
                                      parse_mode="Markdown", reply_markup=main_kb())
    except Exception:
        await m.answer(f"✅ Кошелёк обновлён: `{addr}`", reply_markup=main_kb())

# --- заказы и подтверждение оплат ---
@dp.callback_query(F.data == "orders")
async def orders(c: CallbackQuery):
    ords = await get_orders(DB_PATH)
    if not ords:
        return await c.message.edit_text("🧾 Заказов пока нет.", reply_markup=menu_btn())
    ic = {"waiting": "⏳", "paid": "✅", "rejected": "❌"}
    txt = "🧾 *Последние заказы:*\n\n" + "\n".join(
        f"{ic.get(o[4],'')} #{o[0]} | {o[1]} | {o[3]}$ | {o[5]}" for o in ords[:30])
    await c.message.edit_text(txt, parse_mode="Markdown", reply_markup=menu_btn())

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
    await client_bot.send_message(o[2], f"❌ Заказ #{oid} отклонён. Если вы оплатили — напишите в поддержку.")
    await c.answer("Отклонён")

# --- статистика ---
@dp.callback_query(F.data == "stats")
async def stats(c: CallbackQuery):
    s = await get_stats(DB_PATH)
    await c.message.edit_text(
        f"📊 *Статистика*\n├ Товаров в продаже: {s['products']}\n"
        f"├ Заказов всего: {s['orders']}\n├ Оплачено: {s['paid']}\n"
        f"└ Выручка: {s['revenue']}$",
        parse_mode="Markdown", reply_markup=main_kb())

async def main():
    await init_db(DB_PATH)
    if not await get_setting(DB_PATH, "ltc_wallet"):
        await set_setting(DB_PATH, "ltc_wallet", LTC_WALLET)
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
