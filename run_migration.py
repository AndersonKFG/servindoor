import asyncio
from sqlmodel import text
from app.db.session import engine

async def migrate():
    async with engine.begin() as conn:
        # Add admin_geral to enum if not exists
        try:
            await conn.execute(text("ALTER TYPE userrole ADD VALUE IF NOT EXISTS 'admin_geral';"))
            print("Enum userrole updated with admin_geral")
        except Exception as e:
            print("Enum note:", e)

        # Add column roles to usuarios
        await conn.execute(text("ALTER TABLE usuarios ADD COLUMN IF NOT EXISTS roles VARCHAR;"))
        print("Column roles added to usuarios table")

if __name__ == "__main__":
    asyncio.run(migrate())
