"""Stable command entrypoint for the knowledge feedback worker."""
import asyncio
from app.knowledge.events.worker import main


if __name__ == '__main__':
    asyncio.run(main())
