import azure.functions as func
import json
import logging
from datetime import datetime, timezone

app = func.FunctionApp(http_auth_level=func.AuthLevel.FUNCTION)

@app.route(route="remediate")
def remediate(req: func.HttpRequest) -> func.HttpResponse:
    """
    HTTP-triggered Azure Function.
    Called by /approve after human approves a high-risk recovery plan.
    Logs the remediation action and returns a confirmation.
    """
    logging.info("Remediation request received")

    try:
        body = req.get_json()
    except Exception:
        body = {}

    thread_id     = body.get("thread_id", "unknown")
    pipeline_name = body.get("pipeline_name", "unknown")
    failure_type  = body.get("failure_type", "unknown")
    recovery_plan = body.get("recovery_plan", [])
    approved_by   = body.get("approved_by", "human")
    executed_at   = datetime.now(timezone.utc).isoformat()

    # Log the remediation — visible in App Insights / Function logs
    logging.warning(
        f"REMEDIATION_EXECUTED | pipeline={pipeline_name} | "
        f"failure={failure_type} | thread={thread_id} | "
        f"steps={len(recovery_plan)} | approved_by={approved_by}"
    )

    result = {
        "status":         "remediation_triggered",
        "thread_id":      thread_id,
        "pipeline_name":  pipeline_name,
        "failure_type":   failure_type,
        "steps_count":    len(recovery_plan),
        "approved_by":    approved_by,
        "executed_at":    executed_at,
        "message":        f"Remediation logged for {pipeline_name} — {len(recovery_plan)} steps acknowledged",
        "function":       "infra-recovery-executor/remediate",
    }

    logging.info(f"Remediation result: {json.dumps(result)}")
    return func.HttpResponse(
        json.dumps(result),
        status_code=200,
        mimetype="application/json"
    )