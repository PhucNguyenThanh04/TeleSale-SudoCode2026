"""Explicit PostgreSQL integration, all writes rolled back; no AI calls."""
import os
from uuid import uuid4

import asyncpg
import pytest

from app.auth import password_hash
from app.database.demo_users import DemoUsers, postgres_url
from app.seed_demo_users import SeedSettings, seed

pytestmark = pytest.mark.skipif(not os.environ.get('DEMO_TEST_DATABASE_URL'), reason='Set an isolated test PostgreSQL URL')


@pytest.mark.asyncio
async def test_seed_hashes_passwords_preserves_existing_accounts_and_enforces_profile_ownership():
    connection = await asyncpg.connect(postgres_url(os.environ['DEMO_TEST_DATABASE_URL']))
    transaction = connection.transaction()
    await transaction.start()
    try:
        # Fixture customers live only within the rolled-back transaction.
        prefix = 'auth-test-' + uuid4().hex
        for number in (1, 2):
            await connection.execute('''INSERT INTO btc_source.customers
                (customer_id,name,phone,fb_id,zalo_id,data,source_hash)
                VALUES($1,$2,$3,$4,$5,'{}','offline-test')''', f'{prefix}-{number}',
                'Offline Customer', f'{prefix}-phone-{number}', f'{prefix}-fb-{number}', f'{prefix}-zalo-{number}')
        settings = SeedSettings(_env_file=None, database_url='postgresql://unused',
            demo_user_1_username=prefix+'-one', demo_user_1_password='password-one',
            demo_user_1_customer_id=prefix+'-1', demo_user_2_username=prefix+'-two',
            demo_user_2_password='password-two', demo_user_2_customer_id=prefix+'-2')
        await seed(connection, settings)
        store = DemoUsers(connection)
        first = await store.by_username(prefix+'-one')
        assert first['customer_id'] == prefix+'-1'
        assert first['password_hash'] != 'password-one'
        assert password_hash.verify('password-one', first['password_hash'])
        assert (await store.by_id(first['id']))['username'] == prefix+'-one'
        changed = settings.model_copy(update={'demo_user_1_password': settings.demo_user_2_password})
        await seed(connection, changed)
        assert (await store.by_id(first['id']))['password_hash'] == first['password_hash']
        with pytest.raises(ValueError, match='distinct'):
            await seed(connection, settings.model_copy(update={'demo_user_2_customer_id': prefix+'-1'}))
        with pytest.raises(ValueError, match='missing or has shared'):
            await seed(connection, settings.model_copy(update={'demo_user_2_customer_id': 'no-such-customer'}))
        with pytest.raises(asyncpg.UniqueViolationError):
            async with connection.transaction():
                await connection.execute('''INSERT INTO runtime.demo_users(id,username,password_hash,customer_id)
                    VALUES($1,$2,$3,$4)''', prefix, prefix+'-other', first['password_hash'], prefix+'-1')
    finally:
        await transaction.rollback()
        await connection.close()
