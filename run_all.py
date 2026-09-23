# run_all.py — запускает ОБОИХ ботов одним процессом (нужно для хостинга)
import asyncio
from config import DB_PATH, LTC_WALLET
from db import init_db, get_setting, set_setting

async def run_both():
    await init_db(DB_PATH)
    if not await get_setting(DB_PATH, "ltc_wallet"):
        await set_setting(DB_PATH, "ltc_wallet", LTC_WALLET)

    import main_bot, admin_bot
    await asyncio.gather(
        main_bot.dp.start_polling(main_bot.bot),
        admin_bot.dp.start_polling(admin_bot.bot),
    )

if __name__ == "__main__":
    asyncio.run(run_both())
