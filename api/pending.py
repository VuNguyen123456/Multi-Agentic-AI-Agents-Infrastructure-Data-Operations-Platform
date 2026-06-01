"""Track thread_ids waiting for human approval so the dashboard can discover them."""

import redis

PENDING_SET_KEY = "infra_recovery:pending_threads"


def _client(redis_url: str) -> redis.Redis:
    return redis.from_url(redis_url)


def track_pending(redis_url: str, thread_id: str) -> None:
    _client(redis_url).sadd(PENDING_SET_KEY, thread_id)


def untrack_pending(redis_url: str, thread_id: str) -> None:
    _client(redis_url).srem(PENDING_SET_KEY, thread_id)


def list_pending_approvals(redis_url: str, graph) -> list[dict]:
    """
    Return runs still paused at human_approval. Prune stale ids from the set.
    """
    client = _client(redis_url)
    thread_ids = client.smembers(PENDING_SET_KEY)
    if not thread_ids:
        return []

    pending = []
    for raw in thread_ids:
        thread_id = raw.decode() if isinstance(raw, bytes) else str(raw)
        config = {"configurable": {"thread_id": thread_id}}
        try:
            snap = graph.get_state(config)
        except Exception:
            client.srem(PENDING_SET_KEY, thread_id)
            continue

        if not snap or not snap.next:
            client.srem(PENDING_SET_KEY, thread_id)
            continue

        values = snap.values or {}
        pending.append({
            "status": "pending_approval",
            "thread_id": thread_id,
            "pipeline": values.get("pipeline_name"),
            "failure_type": values.get("failure_type"),
            "risk_level": values.get("risk_level"),
            "risk_reason": values.get("approval_reason"),
            "recovery_plan": values.get("recovery_plan"),
        })

    return pending
