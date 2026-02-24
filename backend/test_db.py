import asyncio
from app.db.engine import async_session
from sqlalchemy import text, select
from app.db.models import SecretEntry

async def main():
    async with async_session() as db:
        r1 = await db.execute(text("SELECT value_json FROM system_settings WHERE key = 'LLM_API_KEY'"))
        print('SYSTEM SETTINGS LLM_API_KEY:', r1.fetchall())
        r2 = await db.execute(select(SecretEntry.name, SecretEntry.encrypted_value))
        print('SECRETS TABLE:', r2.fetchall())

asyncio.run(main())
