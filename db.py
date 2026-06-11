import aiosqlite

DB = "bot.db"

async def init():
    async with aiosqlite.connect(DB) as db:
await db.execute("""
CREATE TABLE IF NOT EXISTS guild_config(
    guild_id INTEGER PRIMARY KEY,
    log_channel INTEGER
)
""")
        await db.execute("""
        CREATE TABLE IF NOT EXISTS warns(
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            guild_id INTEGER,
            user_id INTEGER,
            reason TEXT
        )
        """)

        await db.commit()


async def add_warn(guild_id,user_id,reason):
    async with aiosqlite.connect(DB) as db:
        await db.execute(
            "INSERT INTO warns(guild_id,user_id,reason) VALUES(?,?,?)",
            (guild_id,user_id,reason)
        )
        await db.commit()


async def get_warns(guild_id,user_id):
    async with aiosqlite.connect(DB) as db:

        async with db.execute(
            "SELECT reason FROM warns WHERE guild_id=? AND user_id=?",
            (guild_id,user_id)
        ) as cursor:

            return await cursor.fetchall()
async def set_log_channel(guild_id, channel_id):

    async with aiosqlite.connect(DB) as db:

        await db.execute(
            """
            INSERT OR REPLACE INTO guild_config
            (guild_id, log_channel)
            VALUES (?, ?)
            """,
            (guild_id, channel_id)
        )

        await db.commit()


async def get_log_channel(guild_id):

    async with aiosqlite.connect(DB) as db:

        async with db.execute(
            """
            SELECT log_channel
            FROM guild_config
            WHERE guild_id=?
            """,
            (guild_id,)
        ) as cur:

            row = await cur.fetchone()

            if row:
                return row[0]

            return None
