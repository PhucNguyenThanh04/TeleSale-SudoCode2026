import asyncio
from pathlib import Path
from uuid import uuid4

import asyncpg
from pydantic import Field, SecretStr

from app.auth import password_hash
from app.configs import VoiceSettings
from app.database.demo_users import postgres_url


class SeedSettings(VoiceSettings):
    database_url: str
    demo_user_1_username: str = Field(min_length=1, max_length=100)
    demo_user_1_password: SecretStr = Field(min_length=8, max_length=1024)
    demo_user_1_customer_id: str = Field(min_length=1)
    demo_user_2_username: str = Field(min_length=1, max_length=100)
    demo_user_2_password: SecretStr = Field(min_length=8, max_length=1024)
    demo_user_2_customer_id: str = Field(min_length=1)


async def seed(connection, settings):
    accounts = [(getattr(settings, f'demo_user_{i}_username'),
                 getattr(settings, f'demo_user_{i}_password').get_secret_value(),
                 getattr(settings, f'demo_user_{i}_customer_id')) for i in (1, 2)]
    if len({a[0] for a in accounts}) != 2 or len({a[2] for a in accounts}) != 2:
        raise ValueError('Two distinct usernames and BTC customer IDs are required')
    migration = Path(__file__).resolve().parents[1] / 'migrations' / '0007_demo_users.sql'
    async with connection.transaction():
        await connection.execute(migration.read_text())
        for username, password, customer_id in accounts:
            customer = await connection.fetchrow('''SELECT c.customer_id FROM btc_source.customers c
                WHERE c.customer_id=$1 AND NOT EXISTS (
                    SELECT 1 FROM btc_source.customers other WHERE other.customer_id<>c.customer_id
                    AND (other.phone=c.phone OR (c.fb_id IS NOT NULL AND other.fb_id=c.fb_id)
                         OR (c.zalo_id IS NOT NULL AND other.zalo_id=c.zalo_id)))''', customer_id)
            if not customer:
                raise ValueError('Assigned BTC profile is missing or has shared channel identities')
            existing = await connection.fetchrow(
                'SELECT customer_id FROM runtime.demo_users WHERE username=$1', username)
            if existing:
                if existing['customer_id'] != customer_id:
                    raise ValueError('Existing account has a different assigned BTC profile')
                continue
            await connection.execute('''INSERT INTO runtime.demo_users(id, username, password_hash, customer_id)
                VALUES($1,$2,$3,$4)''', str(uuid4()), username, password_hash.hash(password), customer_id)


async def main():
    settings = SeedSettings()
    connection = await asyncpg.connect(postgres_url(settings.database_url))
    try:
        await seed(connection, settings)
        print('Two demo accounts are ready. Existing passwords and BTC profiles were preserved.')
    finally:
        await connection.close()


if __name__ == '__main__':
    asyncio.run(main())
