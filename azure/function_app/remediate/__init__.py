import json
import logging

import azure.functions as func


def main(req: func.HttpRequest) -> func.HttpResponse:
    try:
        body = req.get_json()
    except ValueError:
        body = {}

    logging.info("Remediation approved: %s", json.dumps(body))

    return func.HttpResponse(
        json.dumps({
            "status": "executed",
            "thread_id": body.get("thread_id"),
            "pipeline_name": body.get("pipeline_name"),
            "failure_type": body.get("failure_type"),
            "message": "Azure executor received post-approval remediation request",
        }),
        mimetype="application/json",
        status_code=200,
    )
