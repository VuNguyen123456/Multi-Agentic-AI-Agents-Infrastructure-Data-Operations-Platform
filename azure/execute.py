"""
azure/execute.py

Calls the Azure Function after human approves a high-risk recovery plan.
This is the "real cloud action" that fires post-approval.
"""
import json
import os

import requests
from dotenv import load_dotenv
load_dotenv(os.path.join(os.path.dirname(__file__), '..', '.env'))

FUNCTION_URL = os.getenv("AZURE_FUNCTION_URL")
FUNCTION_KEY = os.getenv("AZURE_FUNCTION_KEY")


def _function_request_url() -> str | None:
    if not FUNCTION_URL:
        return None
    if "code=" in FUNCTION_URL:
        return FUNCTION_URL
    if FUNCTION_KEY:
        sep = "&" if "?" in FUNCTION_URL else "?"
        return f"{FUNCTION_URL}{sep}code={FUNCTION_KEY}"
    return FUNCTION_URL


def _parse_function_response(response: requests.Response) -> dict:
    text = (response.text or "").strip()
    if not text:
        return {"status": "executed", "message": "Function returned empty body"}
    try:
        return response.json()
    except ValueError:
        return {"status": "executed", "message": text, "raw_text": True}


def trigger_remediation(state: dict, thread_id: str, notes: str = "") -> dict:
    """
    Calls the Azure Function with the approved recovery plan details.
    Returns the Function's response, or a fallback if the call fails.
    """
    url = _function_request_url()
    if not url:
        print("[Azure Execute] AZURE_FUNCTION_URL not set — skipping cloud execute")
        return {"status": "skipped", "reason": "AZURE_FUNCTION_URL not configured"}

    payload = {
        "thread_id":      thread_id,
        "pipeline_name":  state.get("pipeline_name"),
        "failure_type":   state.get("failure_type"),
        "recovery_plan":  state.get("recovery_plan", []),
        "risk_level":     state.get("risk_level"),
        "root_cause":     state.get("root_cause"),
        "approved_by":    "human",
        "notes":          notes,
    }

    print(f"[Azure Execute] Triggering remediation Function for {state.get('pipeline_name')}...")

    try:
        response = requests.post(url, json=payload, timeout=15)
        response.raise_for_status()
        result = _parse_function_response(response)
        print(f"[Azure Execute] OK Function responded: {result.get('status', 'ok')}")
        if result.get("message"):
            print(f"[Azure Execute] Message: {result.get('message')}")
        return result
    except requests.exceptions.Timeout:
        print("[Azure Execute] Function timed out")
        return {"status": "timeout", "error": "Function did not respond within 15s"}
    except Exception as e:
        print(f"[Azure Execute] Function call failed: {e}")
        return {"status": "error", "error": str(e)}


if __name__ == "__main__":
    # Quick test
    test_state = {
        "pipeline_name": "etl_payments_pipeline",
        "failure_type":  "pipeline_crash",
        "risk_level":    "high",
        "root_cause":    "PostgreSQL server unreachable on port 5432",
        "recovery_plan": [
            "Step 1: Check PostgreSQL service status",
            "Step 2: Verify network connectivity",
            "Step 3: Re-run pipeline",
        ],
    }
    result = trigger_remediation(test_state, thread_id="test-123", notes="test run")
    print(f"\nResult: {result}")