import argparse
import os
import secrets
from pathlib import Path


SECRET_FILES = (
    'postgres_password', 'mcp_catalog_password', 'mcp_order_password',
    'mcp_memory_password', 'mcp_knowledge_password', 'mcp_internal_token',
    'ai_internal_token', 'reviewer_password', 'worker_password', 'backend_password',
    'demo_jwt_secret', 'demo_user_1_password', 'demo_user_2_password',
)


def main():
    parser = argparse.ArgumentParser(description='Generate local submission credentials once')
    parser.add_argument('--dir', type=Path, default=Path('secrets-submission'))
    directory = parser.parse_args().dir
    directory.mkdir(mode=0o700, parents=True, exist_ok=True)
    for field in SECRET_FILES:
        path = directory / field
        try:
            with os.fdopen(os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600), 'w') as handle:
                handle.write(secrets.token_hex(16 if field.startswith('demo_user_') else 32) + '\n')
        except FileExistsError:
            if not path.is_file() or not path.stat().st_size:
                raise ValueError(f'Invalid existing secret file: {path}')
    print(f'Submission credentials are ready in {directory}')


if __name__ == '__main__':
    main()
