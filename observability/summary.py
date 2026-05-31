"""Read current Prometheus metric values for the ops dashboard."""


def counter_by_label(counter, label: str) -> dict[str, float]:
    """Return {label_value: count} for a labeled Counter."""
    grouped: dict[str, float] = {}
    for metric in counter.collect():
        for sample in metric.samples:
            if not sample.name.endswith("_total"):
                continue
            key = sample.labels.get(label, "unknown")
            grouped[key] = grouped.get(key, 0.0) + float(sample.value)
    return dict(sorted(grouped.items(), key=lambda x: (-x[1], x[0])))


def gauge_value(gauge) -> float:
    for metric in gauge.collect():
        for sample in metric.samples:
            if sample.name == gauge._name:
                return float(sample.value)
    return 0.0


def build_metrics_summary() -> dict:
    from observability.metrics import (
        AGENT_STEPS_TOTAL,
        HUMAN_DECISIONS_TOTAL,
        PENDING_APPROVALS,
        RUNS_TOTAL,
    )

    agent_steps = counter_by_label(AGENT_STEPS_TOTAL, "agent")
    agent_steps.pop("__interrupt__", None)

    return {
        "pending_approvals": int(gauge_value(PENDING_APPROVALS)),
        "runs_by_status": counter_by_label(RUNS_TOTAL, "status"),
        "human_decisions": counter_by_label(HUMAN_DECISIONS_TOTAL, "decision"),
        "agent_steps": agent_steps,
    }
