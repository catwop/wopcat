# db.py — общая база данных для обоих ботов
import aiosqlite

SCHEMA = """
CREATE TABLE IF NOT EXISTS products(
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    price INTEGER NOT NULL,
    description TEXT DEFAULT '',
    active INTEGER DEFAULT 1
);
CREATE TABLE IF NOT EXISTS orders(
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL,
    username TEXT DEFAULT '',
    product_id INTEGER NOT NULL,
    amount INTEGER NOT NULL,
    status TEXT DEFAULT 'waiting',  -- waiting / paid / rejected
    proof TEXT DEFAULT '',
    created_at TEXT DEFAULT (datetime('now'))
);
CREATE TABLE IF NOT EXISTS settings(
    key TEXT PRIMARY KEY,
    value TEXT
);
"""

async def init_db(path):
    async with aiosqlite.connect(path) as db:
        await db.executescript(SCHEMA)
        await db.commit()

async def get_products(path):
    async with aiosqlite.connect(path) as db:
        cur = await db.execute(
            "SELECT id,name,price,description FROM products WHERE active=1")
        return await cur.fetchall()

async def get_product(path, pid):
    async with aiosqlite.connect(path) as db:
        cur = await db.execute(
            "SELECT id,name,price,description FROM products WHERE id=? AND active=1", (pid,))
        return await cur.fetchone()

async def add_product(path, name, price, desc):
    async with aiosqlite.connect(path) as db:
        cur = await db.execute(
            "INSERT INTO products(name,price,description) VALUES(?,?,?)",
            (name, price, desc))
        await db.commit()
        return cur.lastrowid

async def del_product(path, pid):
    async with aiosqlite.connect(path) as db:
        await db.execute("UPDATE products SET active=0 WHERE id=?", (pid,))
        await db.commit()

# --- настройки (адрес LTC и т.п.) ---
async def get_setting(path, key):
    async with aiosqlite.connect(path) as db:
        cur = await db.execute("SELECT value FROM settings WHERE key=?", (key,))
        row = await cur.fetchone()
        return row[0] if row else None

async def set_setting(path, key, value):
    async with aiosqlite.connect(path) as db:
        await db.execute(
            "INSERT INTO settings(key,value) VALUES(?,?) "
            "ON CONFLICT(key) DO UPDATE SET value=excluded.value", (key, value))
        await db.commit()

# --- заказы ---
async def add_order(path, user_id, username, product_id, amount):
    async with aiosqlite.connect(path) as db:
        cur = await db.execute(
            "INSERT INTO orders(user_id,username,product_id,amount) VALUES(?,?,?,?)",
            (user_id, username, product_id, amount))
        await db.commit()
        return cur.lastrowid

async def attach_proof(path, order_id, proof):
    async with aiosqlite.connect(path) as db:
        await db.execute("UPDATE orders SET proof=? WHERE id=?", (proof, order_id))
        await db.commit()

async def get_order(path, oid):
    async with aiosqlite.connect(path) as db:
        cur = await db.execute(
            """SELECT o.id, p.name, o.user_id, o.username, o.amount, o.status, o.proof
               FROM orders o JOIN products p ON p.id=o.product_id WHERE o.id=?""", (oid,))
        return await cur.fetchone()

async def set_order_status(path, oid, status):
    async with aiosqlite.connect(path) as db:
        await db.execute("UPDATE orders SET status=? WHERE id=?", (status, oid))
        await db.commit()

async def get_user_orders(path, user_id):
    async with aiosqlite.connect(path) as db:
        cur = await db.execute(
            """SELECT o.id, p.name, o.amount, o.status, o.created_at
               FROM orders o JOIN products p ON p.id=o.product_id
               WHERE o.user_id=? ORDER BY o.id DESC""", (user_id,))
        return await cur.fetchall()

async def get_orders(path):
    async with aiosqlite.connect(path) as db:
        cur = await db.execute(
            """SELECT o.id, p.name, o.user_id, o.amount, o.status, o.created_at
               FROM orders o JOIN products p ON p.id=o.product_id
               ORDER BY o.id DESC""")
        return await cur.fetchall()

async def get_stats(path):
    async with aiosqlite.connect(path) as db:
        p = (await (await db.execute(
            "SELECT COUNT(*) FROM products WHERE active=1")).fetchone())[0]
        o = (await (await db.execute("SELECT COUNT(*) FROM orders")).fetchone())[0]
        paid = (await (await db.execute(
            "SELECT COUNT(*) FROM orders WHERE status='paid'")).fetchone())[0]
        r = (await (await db.execute(
            "SELECT COALESCE(SUM(amount),0) FROM orders WHERE status='paid'")).fetchone())[0]
        return {"products": p, "orders": o, "paid": paid, "revenue": r}
