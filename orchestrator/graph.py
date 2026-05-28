from langgraph.graph import StateGraph, END
from dotenv import load_dotenv
import os
# import sys

load_dotenv(os.path.join(os.path.dirname(__file__), '..', '.env'))

# Add project root to path so imports work from orchestrator/
# sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from state import AgentState
from agents.monitoring_agent import monitoring_agent, route_after_monitoring
from agents.analysis_agent import analysis_agent
from agents.planning_agent import planning_agent
from agents.security_agent import security_agent, route_after_security
from agents.execution_agent import execution_agent
from agents.audit_agent import audit_agent


def build_graph():
    """
    Builds and compiles the full LangGraph multi-agent graph.

    This function:
    1. Creates a StateGraph typed to AgentState
    2. Registers all 6 agent functions as nodes
    3. Wires edges between them (regular + conditional)
    4. Compiles and returns the runnable graph
    """

    # ── 1. CREATE THE GRAPH ────────────────────────────────────────────────────
    # StateGraph takes your TypedDict — this tells LangGraph what
    # the state looks like and how to merge partial updates from each node.
    graph = StateGraph(AgentState)


    # ── 2. REGISTER NODES ─────────────────────────────────────────────────────
    # Each node is a name (string) + a function (agent).
    # The name is what edges reference — must match exactly.
    graph.add_node("monitoring_agent", monitoring_agent)
    graph.add_node("analysis_agent",   analysis_agent)
    graph.add_node("planning_agent",   planning_agent)
    graph.add_node("security_agent",   security_agent)
    graph.add_node("execution_agent",  execution_agent)
    graph.add_node("audit_agent",      audit_agent)


    # ── 3. SET ENTRY POINT ────────────────────────────────────────────────────
    # Tells LangGraph which node runs first when you call graph.invoke().
    graph.set_entry_point("monitoring_agent")


    # ── 4. WIRE THE EDGES ─────────────────────────────────────────────────────

    # Conditional edge after monitoring:
    # route_after_monitoring() returns "analysis_agent" or "END"
    graph.add_conditional_edges(
        "monitoring_agent",         # from this node
        route_after_monitoring,     # call this router function
        {
            "analysis_agent": "analysis_agent",   # if router returns "analysis_agent" → go there
            "END": END                             # if router returns "END" → stop the graph
        }
    )

    # Regular edges — no branching, always go to the next node
    graph.add_edge("analysis_agent", "planning_agent")
    graph.add_edge("planning_agent", "security_agent")

    # Conditional edge after security:
    # route_after_security() returns "execution_agent" or "audit_agent"
    graph.add_conditional_edges(
        "security_agent",           # from this node
        route_after_security,       # call this router function
        {
            "execution_agent": "execution_agent",  # approved → execute
            "audit_agent":     "audit_agent"       # rejected → skip to audit
        }
    )

    # Execution always flows into audit (whether execution succeeded or failed)
    graph.add_edge("execution_agent", "audit_agent")

    # Audit is the terminal node — after it runs, the graph ends
    graph.add_edge("audit_agent", END)


    # ── 5. COMPILE ────────────────────────────────────────────────────────────
    # Compiles the graph into a runnable object.
    # After this point the structure is locked — no more adding nodes or edges.
    return graph.compile()


# Export the compiled graph so main.py can import it directly
graph = build_graph()