import json
from contextlib import asynccontextmanager
from sqlalchemy import text
from app.mcp_servers.mcp_shared.database import Database
from app.knowledge.schemas import TABLES


class UnitOfWork:
    def __init__(self, session):
        self.session = session

    def table(self, table):
        if table not in TABLES:
            raise ValueError('Unknown knowledge table')
        return 'knowledge.' + table

    async def get(self, table, key):
        row = (await self.session.execute(text(f'SELECT data FROM {self.table(table)} WHERE id=:id'),
                                          {'id': key})).scalar_one_or_none()
        return row

    async def put(self, table, key, value):
        await self.session.execute(text(f'''INSERT INTO {self.table(table)} (id,data)
            VALUES (:id,CAST(:data AS jsonb)) ON CONFLICT (id) DO UPDATE SET data=EXCLUDED.data'''),
            {'id': key, 'data': json.dumps(value, ensure_ascii=False)})

    async def rows(self, table):
        return list((await self.session.execute(text(f'SELECT data FROM {self.table(table)} ORDER BY id'))).scalars())

    async def sources(self, ids=None):
        rows = list((await self.session.execute(text('''SELECT chunk_id,document_id,title,body,
            access_level,date_basis,effective_from,effective_until,source_hash
            FROM btc_source.policy_chunks'''))).mappings())
        return [{k: v.isoformat() if hasattr(v, 'isoformat') else v for k, v in r.items()}
                for r in rows if ids is None or r['chunk_id'] in ids]


class KnowledgeRepo(Database):
    @asynccontextmanager
    async def transaction(self):
        async with super().transaction() as session:
            await session.execute(text("SELECT pg_advisory_xact_lock(714221, 1)"))
            yield UnitOfWork(session)


class AsyncpgUnitOfWork:
    def __init__(self, conn):
        self.conn = conn

    def table(self, name):
        if name not in TABLES:
            raise ValueError('Unknown knowledge table')
        return 'knowledge.'+name

    async def get(self, table, key):
        value = await self.conn.fetchval(f'SELECT data FROM {self.table(table)} WHERE id=$1', key)
        return json.loads(value) if isinstance(value, str) else value

    async def put(self, table, key, value):
        await self.conn.execute(f'''INSERT INTO {self.table(table)}(id,data) VALUES($1,$2::jsonb)
            ON CONFLICT(id) DO UPDATE SET data=EXCLUDED.data''', key, json.dumps(value, ensure_ascii=False))

    async def rows(self, table):
        rows = await self.conn.fetch(f'SELECT data FROM {self.table(table)} ORDER BY id')
        return [json.loads(r['data']) if isinstance(r['data'], str) else r['data'] for r in rows]
