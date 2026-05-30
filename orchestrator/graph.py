from langgraph.graph import StateGraph, END
from langgraph.checkpoint.redis import RedisSaver
from langgraph.types import interrupt, Command
from dotenv import load_dotenv
import os

load_dotenv(os.path.join(os.path.dirname(__file__), '..', '.env'))

from state import AgentState
from agents.monitoring_agent import monitoring_agent, route_after_monitoring
from agents.analysis_agent import analysis_agent
from agents.planning_agent import planning_agent
from agents.security_agent import security_agent
from agents.execution_agent import execution_agent
from agents.audit_agent import audit_agent

REDIS_URL = os.getenv("REDIS_URL", "redis://localhost:6380")


def human_approval_node(state: dict) -> dict:
    print(f"\n[Human Approval] ⏸  Graph paused — waiting for human decision")
    print(f"[Human Approval] Pipeline : {state['pipeline_name']}")
    print(f"[Human Approval] Risk     : {state['risk_level']}")
    print(f"[Human Approval] Reason   : {state['approval_reason']}")
    print(f"[Human Approval] Call POST /approve or /reject with the thread_id to continue")

    human_decision = interrupt({
        "message":       "High-risk recovery plan requires human approval",
        "pipeline":      state["pipeline_name"],
        "failure_type":  state["failure_type"],
        "risk_reason":   state["approval_reason"],
        "recovery_plan": state["recovery_plan"],
    })

    approved = human_decision.get("approved", False)
    notes    = human_decision.get("notes", "")

    print(f"\n[Human Approval] ▶  Resumed — human decision: {'APPROVED' if approved else 'REJECTED'}")
    if notes:
        print(f"[Human Approval] Notes: {notes}")

    return {
        "human_approved": approved,
        "human_notes":    notes,
    }


def route_after_security(state: dict) -> str:
    if state["approved"]:
        print(f"[Router] Auto-approved → routing to execution_agent")
        return "execution_agent"
    else:
        print(f"[Router] High risk → routing to human_approval")
        return "human_approval_node"


def route_after_human(state: dict) -> str:
    if state.get("human_approved"):
        print(f"[Router] Human approved → routing to execution_agent")
        return "execution_agent"
    else:
        print(f"[Router] Human rejected → routing to audit_agent")
        return "audit_agent"


def build_graph(checkpointer=None):
    graph = StateGraph(AgentState)

    graph.add_node("monitoring_agent",  monitoring_agent)
    graph.add_node("analysis_agent",    analysis_agent)
    graph.add_node("planning_agent",    planning_agent)
    graph.add_node("security_agent",    security_agent)
    graph.add_node("human_approval",    human_approval_node)
    graph.add_node("execution_agent",   execution_agent)
    graph.add_node("audit_agent",       audit_agent)

    graph.set_entry_point("monitoring_agent")

    graph.add_conditional_edges(
        "monitoring_agent",
        route_after_monitoring,
        {"analysis_agent": "analysis_agent", "END": END}
    )

    graph.add_edge("analysis_agent", "planning_agent")
    graph.add_edge("planning_agent", "security_agent")

    graph.add_conditional_edges(
        "security_agent",
        route_after_security,
        {
            "execution_agent":   "execution_agent",
            "human_approval_node": "human_approval",
        }
    )

    graph.add_conditional_edges(
        "human_approval",
        route_after_human,
        {
            "execution_agent": "execution_agent",
            "audit_agent":     "audit_agent",
        }
    )

    graph.add_edge("execution_agent", "audit_agent")
    graph.add_edge("audit_agent", END)

    return graph.compile(checkpointer=checkpointer)


# Stateless graph for quick runs from main.py
graph = build_graph()