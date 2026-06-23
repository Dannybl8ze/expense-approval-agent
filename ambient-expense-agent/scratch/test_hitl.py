import asyncio
import json
from google.genai import types
from google.adk.runners import Runner
from google.adk.sessions.sqlite_session_service import SqliteSessionService
from expense_agent.agent import root_agent

async def main():
    db_path = "expense_agent/.adk/eval_test.db"
    session_service = SqliteSessionService(db_path=db_path)
    runner = Runner(agent=root_agent, session_service=session_service, app_name="expense_agent")
    
    session_id = "test-hitl-session"
    
    session = await session_service.get_session(app_name="expense_agent", user_id="pubsub_user", session_id=session_id)
    if not session:
        session = await session_service.create_session(app_name="expense_agent", user_id="pubsub_user", session_id=session_id)
        
    input_payload = {"amount": 150.0, "submitter": "bob@company.com", "category": "travel", "description": "Hotel conference", "date": "2026-06-20"}
    user_message = types.Content(
        role="user",
        parts=[types.Part.from_text(text=json.dumps(input_payload))]
    )
    
    async for event in runner.run_async(
        new_message=user_message,
        user_id="pubsub_user",
        session_id=session.id
    ):
        print("Event type:", type(event))
        print("Event dir:", dir(event))
        break

if __name__ == "__main__":
    asyncio.run(main())
