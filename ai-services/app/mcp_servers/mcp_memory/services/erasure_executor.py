"""Internal, retry-safe erasure of memory-owned customer rows."""

from uuid import UUID


async def execute_erasure(repo, request_key: str) -> dict:
    """Purge the authorized memory slice; other stores remain explicitly pending."""
    try:
        UUID(request_key)
    except (TypeError, ValueError):
        return {"error": "invalid_request_key"}
    async with repo.transaction() as conn:
        request = await repo.erasure_request(conn, request_key)
        if request is None:
            return {"error": "request_not_found"}
        customer_id = request["customer_id"]
        await repo.lock_key(conn, f"erasure:{customer_id}")
        request = await repo.erasure_request(conn, request_key, for_update=True)
        if "ai_memory" not in request["scope"]:
            return {"error": "memory_not_in_scope"}
        if request["status"] == "completed":
            return {"request_key": request_key, "status": "completed",
                    "store_results": request["store_results"]}
        memory_result = await repo.purge_customer_memory(conn, customer_id)
        other_stores = [store for store in request["scope"] if store != "ai_memory"]
        results = {"ai_memory": memory_result,
                   **{store: {"status": "pending"} for store in other_stores}}
        status = ("completed" if not other_stores
                  and memory_result["status"] == "completed" else "partial")
        await repo.finish_erasure_request(conn, request_key, status, results)
        return {"request_key": request_key, "status": status,
                "store_results": results}
