"""Run LangGraph while recording per-agent Prometheus metrics."""

import time
from typing import Any

from langgraph.errors import GraphInterrupt

from observability.metrics import AGENT_STEPS_TOTAL, GRAPH_RUN_DURATION


def tracked_invoke(graph, input, config, *, endpoint: str) -> Any:
    """
    Stream graph updates to count agent steps, then return the same payload
    that graph.invoke(..., stream_mode='values') would return.
    """
    start = time.perf_counter()
    latest: Any = None

    try:
        for chunk in graph.stream(
            input,
            config,
            stream_mode=["updates", "values"],
        ):
            if len(chunk) == 2:
                mode, payload = chunk
            else:
                _, mode, payload = chunk

            if mode == "updates" and isinstance(payload, dict):
                for node_name in payload:
                    AGENT_STEPS_TOTAL.labels(agent=node_name).inc()
            elif mode == "values":
                latest = payload
    finally:
        GRAPH_RUN_DURATION.labels(endpoint=endpoint).observe(time.perf_counter() - start)

    return latest
