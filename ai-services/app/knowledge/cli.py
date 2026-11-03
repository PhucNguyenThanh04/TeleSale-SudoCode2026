"""Administrative provisioning and masked lifecycle export. No model calls."""
from app.knowledge.config import configured_url
import argparse
import asyncio
import json
import os
from pathlib import Path
from app.knowledge.repo import KnowledgeRepo
from app.knowledge.schemas import TABLES, KnowledgeError, timestamp
from app.knowledge.permissions import require_permission


async def execute(args):
    env = 'KNOWLEDGE_ADMIN_DATABASE_URL' if args.action in {'grant', 'revoke'} else 'KNOWLEDGE_DATABASE_URL'
    dsn = configured_url(env)
    if not dsn:
        raise SystemExit(env+' required')
    repo = KnowledgeRepo(dsn)
    try:
        async with repo.transaction() as tx:
            if args.action in {'grant', 'revoke'}:
                if not args.actor or args.actor.startswith('web-visitor:'):
                    raise KnowledgeError('Internal actor required')
                await tx.put('permissions', args.actor, {'id': args.actor,
                    'permissions': ['knowledge_review'] if args.action == 'grant' else [], 'updated_at': timestamp()})
                return {'actor_id': args.actor, 'permission': args.action}
            await require_permission(tx, args.actor)
            if args.action == 'export':
                if not args.out:
                    raise KnowledgeError('--out required')
                export = {table: await tx.rows(table) for table in sorted(TABLES-{'permissions', 'erasures', 'backend_outbox'})}
                # Evidence and test drafts have already passed field-path masking.
                args.out.parent.mkdir(parents=True, exist_ok=True)
                with args.out.open('x', encoding='utf-8') as stream:
                    json.dump(export, stream, ensure_ascii=False, indent=2)
                return {'exported': str(args.out)}
    finally:
        await repo.close()


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('action', choices=['grant', 'revoke', 'export'])
    p.add_argument('--actor', required=True)
    p.add_argument('--out', type=Path)
    args = p.parse_args()
    print(json.dumps(asyncio.run(execute(args)), ensure_ascii=False))


if __name__ == '__main__':
    main()
