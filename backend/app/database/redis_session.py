
from fastapi import Request
from redis.asyncio import Redis


def create_redis_client(redis_url: str) -> Redis:
    return Redis.from_url(
        redis_url,
        decode_responses=True,
        socket_connect_timeout=5,
        socket_timeout=5,
    )


async def check_redis(client: Redis) -> None:
    await client.ping()


def get_redis(request: Request) -> Redis:
    return request.app.state.redis
