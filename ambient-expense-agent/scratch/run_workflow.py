import asyncio
import json
from dotenv import load_dotenv
load_dotenv()
from google.adk.runners import Runner
from google.adk.sessions import InMemorySessionService
from google.genai import types
from google.adk.events.request_input import RequestInput
from google.adk.events.event import Event

# Set path and import agent
import sys
sys.path.append("c:\\Users\\User\\OneDrive\\Dokumenti\\Google Antigravity\\Projects\\Kaggle-google-5days-my-first-project\\ambient-expense-agent")
from expense_agent.agent import root_agent

async def run_verification():
    print("Initializing Session Service and Runner...")
    session_service = InMemorySessionService()
    session = await session_service.create_session(user_id="alice_user", app_name="expense_app")
    
    runner = Runner(agent=root_agent, session_service=session_service, app_name="expense_app")
    
    # Test Payload
    payload = {
        "amount": 150.0,
        "submitter": "alice@company.com",
        "category": "software",
        "description": "IDE License",
        "date": "2026-06-06"
    }
    
    message = types.Content(
        role="user",
        parts=[types.Part.from_text(text=json.dumps(payload))]
    )
    
    print("\n--- Starting Workflow (Step 1) ---")
    interrupt_id = None
    
    async for event in runner.run_async(
        new_message=message,
        user_id="alice_user",
        session_id=session.id
    ):
        print(f"DEBUG Event type: {type(event)}, representation: {repr(event)}")
        if hasattr(event, "content") and event.content:
            text = "".join(p.text for p in event.content.parts if p.text)
            print(f"[UI Content]: {text}")
            
        if hasattr(event, "output") and event.output:
            print(f"[Output]: {event.output}")
            
        # Check if execution paused for human input
        is_request_input = False
        if hasattr(event, "content") and event.content and event.content.parts:
            for part in event.content.parts:
                if hasattr(part, "function_call") and part.function_call and part.function_call.name == "adk_request_input":
                    is_request_input = True
                    interrupt_id = part.function_call.id or part.function_call.args.get("interruptId")
                    message = part.function_call.args.get("message")
                    print(f"\n[PAUSED - Human Input Required (Interrupt ID: {interrupt_id})]")
                    print(f"Message:\n{message}")
                    break
        if is_request_input:
            break


            
    if interrupt_id:
        print("\nSimulating Human Input: replying 'approve'...")
        resume_message = types.Content(
            role="user",
            parts=[
                types.Part(
                    function_response=types.FunctionResponse(
                        name="adk_request_input",
                        id=interrupt_id,
                        response={"response": "approve"}
                    )
                )
            ]
        )
        
        print("\n--- Resuming Workflow (Step 2) ---")
        async for event in runner.run_async(
            new_message=resume_message,
            user_id="alice_user",
            session_id=session.id
        ):
            if hasattr(event, "content") and event.content:
                text = "".join(p.text for p in event.content.parts if p.text)
                print(f"[UI Content]: {text}")
                
            if hasattr(event, "output") and event.output:
                print(f"[Output]: {event.output}")


if __name__ == "__main__":
    asyncio.run(run_verification())
