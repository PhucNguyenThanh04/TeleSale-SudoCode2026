"""Read auth accounts together with their assigned BTC customer profile."""
SELECT = '''SELECT u.id, u.username, u.password_hash, u.active,
                   c.customer_id, c.name, c.phone, c.fb_id, c.zalo_id
            FROM runtime.demo_users u JOIN btc_source.customers c USING (customer_id)'''


def postgres_url(url):
    return url.replace('postgresql+asyncpg://', 'postgresql://', 1)


class DemoUsers:
    def __init__(self, pool):
        self.pool = pool

    async def by_username(self, username):
        return await self.pool.fetchrow(SELECT + ' WHERE u.username=$1', username)

    async def by_id(self, user_id):
        return await self.pool.fetchrow(SELECT + ' WHERE u.id=$1', user_id)
