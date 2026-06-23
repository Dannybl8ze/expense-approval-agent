import base64
import json
import logging
from typing import Any, Dict
from dotenv import load_dotenv
load_dotenv()

from fastapi import FastAPI, Request, HTTPException
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from google.genai import types
from google.adk.runners import Runner
from google.adk.sessions.sqlite_session_service import SqliteSessionService
from expense_agent.agent import root_agent

# Initialize logging: Use standard Python logging for console logs
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger("expense_agent.web_service")

# Telemetry: Set otel_to_cloud=False
# We ensure trace/OTel data is not exported to GCP Trace/Logging by not initializing the OTel CloudTraceSpanExporter.

app = FastAPI(title="Ambient Expense Approval Pub/Sub Service")

# Setup SQLite session service and runner using local DB
db_path = "expense_agent/.adk/session.db"
session_service = SqliteSessionService(db_path=db_path)
runner = Runner(agent=root_agent, session_service=session_service, app_name="expense_agent")

class ResumeRequest(BaseModel):
    session_id: str
    interrupt_id: str
    decision: str

@app.post("/")
@app.post("/pubsub")
async def trigger_pubsub(request: Request) -> Dict[str, Any]:
    try:
        body = await request.json()
    except Exception as e:
        logger.error(f"Failed to parse JSON body: {e}")
        raise HTTPException(status_code=400, detail="Invalid JSON body")

    # 1. Normalize Pub/Sub subscription name to a short name
    subscription = body.get("subscription")
    if subscription:
        # e.g., projects/my-project/subscriptions/expense-trigger -> expense-trigger
        short_sub_name = subscription.split("/")[-1]
    else:
        short_sub_name = "expense-trigger"

    # 2. Extract Pub/Sub message data
    message = body.get("message")
    if not message or not isinstance(message, dict):
        logger.error("Missing 'message' object in Pub/Sub payload")
        raise HTTPException(status_code=400, detail="Missing 'message' object")

    message_id = message.get("messageId", "default-id")
    raw_data = message.get("data")
    
    # 3. Decode base64 message data if present
    data_payload = {}
    if raw_data:
        try:
            # Check if it is base64 encoded
            decoded_bytes = base64.b64decode(raw_data)
            decoded_str = decoded_bytes.decode("utf-8")
            try:
                data_payload = json.loads(decoded_str)
            except json.JSONDecodeError:
                data_payload = decoded_str
        except Exception:
            # Fall back to raw_data if base64 decoding fails or is not base64
            data_payload = raw_data

    # Assemble the input text as JSON string
    input_text = json.dumps(data_payload)
    message_content = types.Content(
        role="user",
        parts=[types.Part.from_text(text=input_text)]
    )

    # 4. Generate readable session ID using short sub name
    session_id = f"{short_sub_name}-{message_id}"
    logger.info(f"Triggering workflow for subscription: {short_sub_name}, message ID: {message_id}, session: {session_id}")

    try:
        # Create session if it doesn't exist
        session = await session_service.get_session(app_name="expense_agent", user_id="pubsub_user", session_id=session_id)
        if not session:
            session = await session_service.create_session(app_name="expense_agent", user_id="pubsub_user", session_id=session_id)

        # Run the workflow
        events = []
        async for event in runner.run_async(
            new_message=message_content,
            user_id="pubsub_user",
            session_id=session.id
        ):
            events.append(event)
            # Check for interrupt/HITL pause
            if event.content and event.content.parts:
                for part in event.content.parts:
                    if hasattr(part, "function_call") and part.function_call and part.function_call.name == "adk_request_input":
                        logger.info(f"Workflow paused for human input (session: {session_id})")
                        return {
                            "status": "paused",
                            "session_id": session_id,
                            "interrupt_id": part.function_call.id,
                            "message": part.function_call.args.get("message")
                        }

        # Retrieve the final output or state of the workflow
        final_output = None
        for event in reversed(events):
            if event.output:
                final_output = event.output
                break

        logger.info(f"Workflow completed successfully (session: {session_id}, output: {final_output})")
        return {
            "status": "success",
            "session_id": session_id,
            "output": final_output
        }

    except Exception as e:
        logger.exception(f"Error processing workflow for session {session_id}: {e}")
        raise HTTPException(status_code=500, detail=f"Internal agent processing error: {e}")

@app.post("/resume")
async def resume_workflow(req: ResumeRequest) -> Dict[str, Any]:
    session_id = req.session_id
    interrupt_id = req.interrupt_id
    decision = req.decision

    logger.info(f"Resuming workflow for session: {session_id}, decision: {decision}")

    # Build the resumption message
    resume_message = types.Content(
        role="user",
        parts=[
            types.Part(
                function_response=types.FunctionResponse(
                    name="adk_request_input",
                    id=interrupt_id,
                    response={"response": decision}
                )
            )
        ]
    )

    try:
        session = await session_service.get_session(app_name="expense_agent", user_id="pubsub_user", session_id=session_id)
        if not session:
            raise HTTPException(status_code=404, detail=f"Session {session_id} not found")

        events = []
        async for event in runner.run_async(
            new_message=resume_message,
            user_id="pubsub_user",
            session_id=session.id
        ):
            events.append(event)

        final_output = None
        for event in reversed(events):
            if event.output:
                final_output = event.output
                break

        logger.info(f"Workflow completed successfully after resumption (session: {session_id}, output: {final_output})")
        return {
            "status": "success",
            "session_id": session_id,
            "output": final_output
        }

    except Exception as e:
        logger.exception(f"Error resuming workflow for session {session_id}: {e}")
        raise HTTPException(status_code=500, detail=f"Internal agent processing error: {e}")
