import sys
import os
import uuid
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
from langgraph.checkpoint.redis import RedisSaver
from langgraph.errors import GraphInterrupt
from langgraph.types import Command
from langgraph._internal._constants import INTERRUPT
from dotenv import load_dotenv

load_dotenv(os.path.join(os.path.dirname(__file__), '..', '.env'))
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from orchestrator.graph import build_graph
from simulator.failure_sim import generate_failure

REDIS_URL = os.getenv("REDIS_URL", "redis://localhost:6380")
app_state = {}


def verify_redis_json_support(redis_url: str) -> None:
    import redis

    client = redis.from_url(redis_url)
    test_key = "infra_recovery:redis_json_probe"
    try:
        client.execute_command("JSON.SET", test_key, "$", '{"ok": true}')
        client.delete(test_key)
    except redis.exceptions.ResponseError as exc:
        if "unknown command" in str(exc).lower() and "json.set" in str(exc).lower():
            raise RuntimeError(
                f"Redis at {redis_url} does not support JSON.SET. "
                "Port 6379 on Windows is often plain Redis — use Redis Stack on 6380: "
                "docker compose up -d redis"
            ) from exc
        raise

# The 4 endpoints are:
# 1. /run - Start a new recovery run. Returns thread_id for tracking.
# 2. /approve/{thread_id} - Human approves the high-risk plan. Graph resumes into execution.
# 3. /reject/{thread_id} - Human rejects the plan. Graph resumes into audit, nothing executes.
# 4. /status/{thread_id} - Check the current state of any run.
# 5. /health - Check the health of the API.

@asynccontextmanager
async def lifespan(app: FastAPI):
    print("[API] Connecting to Redis...")
    verify_redis_json_support(REDIS_URL)
    with RedisSaver.from_conn_string(REDIS_URL) as checkpointer:
        checkpointer.setup()
        app_state["graph"] = build_graph(checkpointer=checkpointer)
        print("[API] Ready — graph compiled with Redis checkpointer")
        yield   # server runs here, connection stays open
    print("[API] Shutting down")


app = FastAPI(
    title="Infrastructure Recovery API",
    description="Human-in-the-loop approval for high-risk recovery plans",
    lifespan=lifespan
)


class RunRequest(BaseModel):
    scenario: str = None


class ApprovalRequest(BaseModel):
    notes: str = ""


def pending_approval_response(thread_id: str, values: dict) -> dict:
    values = values or {}
    return {
        "status":        "pending_approval",
        "thread_id":     thread_id,
        "pipeline":      values.get("pipeline_name"),
        "failure_type":  values.get("failure_type"),
        "risk_level":    values.get("risk_level"),
        "risk_reason":   values.get("approval_reason"),
        "recovery_plan": values.get("recovery_plan"),
        "message":       "Call POST /approve/{thread_id} or /reject/{thread_id} to continue",
    }


def run_state_values(result, state_snapshot) -> dict:
    if state_snapshot and state_snapshot.values:
        return state_snapshot.values
    if isinstance(result, dict):
        return {key: value for key, value in result.items() if key != INTERRUPT}
    return {}


def graph_is_paused(result, state_snapshot) -> bool:
    if isinstance(result, dict) and result.get(INTERRUPT):
        return True
    return bool(state_snapshot and state_snapshot.next)


# The /run endpoint starts a new recovery run.
# It generates a unique thread_id, configures the graph with it,
# and invokes the initial state. If the graph is paused (waiting for approval),
# it returns a response with the pending status and thread_id.
# Otherwise, it returns a response with the completed status and execution results.
@app.post("/run")
async def run_pipeline(request: RunRequest):
    """Start a new recovery run. Returns thread_id for tracking."""
    graph         = app_state["graph"]
    thread_id     = str(uuid.uuid4())
    config        = {"configurable": {"thread_id": thread_id}}
    initial_state = generate_failure(request.scenario)

    print(f"\n[API] Starting run — thread_id: {thread_id}")

    try:
        result = graph.invoke(initial_state, config=config)
    except GraphInterrupt:
        result = None
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

    try:
        state_snapshot = graph.get_state(config)
    except Exception as e:
        if result is None or not isinstance(result, dict):
            raise HTTPException(status_code=500, detail=str(e))
        state_snapshot = None

    if graph_is_paused(result, state_snapshot):
        return pending_approval_response(
            thread_id,
            run_state_values(result, state_snapshot),
        )

    if not isinstance(result, dict):
        raise HTTPException(status_code=500, detail="Graph finished without a result")

    return {
        "status":           "completed",
        "thread_id":        thread_id,
        "pipeline":         result.get("pipeline_name"),
        "failure_type":     result.get("failure_type"),
        "execution_status": result.get("execution_status"),
        "completed_at":     result.get("completed_at"),
    }


# The /approve/{thread_id} endpoint is used to approve a high-risk recovery plan.
# It checks if the run is waiting for approval, and if so, it resumes the graph
# with the approved flag set to True and the human notes.
@app.post("/approve/{thread_id}")
async def approve_plan(thread_id: str, request: ApprovalRequest):
    """Human approves the high-risk plan. Graph resumes into execution."""
    graph  = app_state["graph"]
    config = {"configurable": {"thread_id": thread_id}}

    try:
        state_snapshot = graph.get_state(config)
    except Exception:
        raise HTTPException(status_code=404, detail=f"Thread {thread_id} not found")

    if not state_snapshot.next:
        raise HTTPException(status_code=400, detail="This run is not waiting for approval")

    print(f"\n[API] ✓ APPROVED — thread: {thread_id}")

    result = graph.invoke(
        Command(resume={"approved": True, "notes": request.notes}),
        config=config
    )

    return {
        "status":           "completed",
        "thread_id":        thread_id,
        "human_decision":   "approved",
        "execution_status": result.get("execution_status"),
        "actions_taken":    result.get("actions_taken"),
        "completed_at":     result.get("completed_at"),
    }


# The /reject/{thread_id} endpoint is used to reject a high-risk recovery plan.
# It checks if the run is waiting for approval, and if so, it resumes the graph
# with the approved flag set to False and the human notes.
@app.post("/reject/{thread_id}")
async def reject_plan(thread_id: str, request: ApprovalRequest):
    """Human rejects the plan. Graph resumes into audit, nothing executes."""
    graph  = app_state["graph"]
    config = {"configurable": {"thread_id": thread_id}}

    try:
        state_snapshot = graph.get_state(config)
    except Exception:
        raise HTTPException(status_code=404, detail=f"Thread {thread_id} not found")

    if not state_snapshot.next:
        raise HTTPException(status_code=400, detail="This run is not waiting for approval")

    print(f"\n[API] ✗ REJECTED — thread: {thread_id}")

    result = graph.invoke(
        Command(resume={"approved": False, "notes": request.notes}),
        config=config
    )

    return {
        "status":         "completed",
        "thread_id":      thread_id,
        "human_decision": "rejected",
        "outcome":        "requires_human",
        "completed_at":   result.get("completed_at"),
    }


# The /status/{thread_id} endpoint is used to check the current state of any run.
# It checks if the run is waiting for approval, and if so, it returns the pending status.
# Otherwise, it returns the completed status and execution results.
@app.get("/status/{thread_id}")
async def get_status(thread_id: str):
    """Check the current state of any run."""
    graph  = app_state["graph"]
    config = {"configurable": {"thread_id": thread_id}}

    try:
        state_snapshot = graph.get_state(config)
    except Exception:
        raise HTTPException(status_code=404, detail=f"Thread {thread_id} not found")

    values    = state_snapshot.values
    is_paused = bool(state_snapshot.next)

    return {
        "thread_id":        thread_id,
        "status":           "pending_approval" if is_paused else "completed",
        "pipeline":         values.get("pipeline_name"),
        "failure_type":     values.get("failure_type"),
        "risk_level":       values.get("risk_level"),
        "execution_status": values.get("execution_status"),
        "next_node":        list(state_snapshot.next) if is_paused else None,
    }


@app.get("/health")
async def health():
    return {"status": "ok", "redis": REDIS_URL}