import asyncio
import os
import json
import re
import uuid
from pathlib import Path
from dotenv import load_dotenv
load_dotenv()
from google.genai import types
from google.adk.runners import Runner
from google.adk.sessions.sqlite_session_service import SqliteSessionService
from expense_agent.agent import root_agent


# Detection of prompt injection to automate the HITL decision
def is_prompt_injection(description: str) -> bool:
    injection_patterns = [
        r"ignore previous instructions",
        r"bypass rules",
        r"override system",
        r"force auto-approval",
        r"auto-approve this",
        r"system instruction override"
    ]
    for pat in injection_patterns:
        if re.search(pat, description, re.IGNORECASE):
            return True
    return False

# Convert types.Content or types.Part to dictionary safely
def content_to_dict(content) -> dict:
    if not content:
        return None
    
    parts_list = []
    for part in content.parts:
        part_dict = {}
        if hasattr(part, "text") and part.text is not None:
            part_dict["text"] = part.text
        elif hasattr(part, "function_call") and part.function_call:
            fc = part.function_call
            part_dict["function_call"] = {
                "name": fc.name,
                "id": fc.id,
                "args": fc.args
            }
        elif hasattr(part, "function_response") and part.function_response:
            fr = part.function_response
            part_dict["function_response"] = {
                "name": fr.name,
                "id": fr.id,
                "response": fr.response
            }
        if part_dict:
            parts_list.append(part_dict)
            
    return {
        "role": content.role or "model",
        "parts": parts_list
    }

async def run_scenario(runner, session_service, case_id, prompt_text):
    session_id = f"eval-session-{case_id}-{uuid.uuid4()}"
    
    # Clean up any existing session
    try:
        await session_service.delete_session(app_name="expense_agent", session_id=session_id)
    except Exception:
        pass
        
    session = await session_service.create_session(app_name="expense_agent", user_id="eval_user", session_id=session_id)
    
    parsed_prompt = json.loads(prompt_text)
    description = parsed_prompt.get("description", "")
    
    user_message = types.Content(
        role="user",
        parts=[types.Part.from_text(text=prompt_text)]
    )
    
    events_list = []
    
    # Event 0: The initial user prompt
    events_list.append({
        "author": "user",
        "content": {
            "role": "user",
            "parts": [{"text": prompt_text}]
        }
    })
    
    paused = False
    interrupt_id = None
    
    async for event in runner.run_async(
        new_message=user_message,
        user_id="eval_user",
        session_id=session.id
    ):
        # Check for pause
        if event.content and event.content.parts:
            for part in event.content.parts:
                if hasattr(part, "function_call") and part.function_call and part.function_call.name == "adk_request_input":
                    paused = True
                    interrupt_id = part.function_call.id
                    
        if event.content:
            event_dict = {
                "author": event.author or "expense_approval_workflow",
                "content": content_to_dict(event.content)
            }
            events_list.append(event_dict)
                    
    if paused:
        # Determine human decision
        if is_prompt_injection(description):
            decision = "reject"
        else:
            decision = "approve"
            
        # Event representing user's resumption input
        events_list.append({
            "author": "user",
            "content": {
                "role": "user",
                "parts": [
                    {
                        "function_response": {
                            "name": "adk_request_input",
                            "id": interrupt_id,
                            "response": {"response": decision}
                        }
                    }
                ]
            }
        })
        
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
        
        async for event in runner.run_async(
            new_message=resume_message,
            user_id="eval_user",
            session_id=session.id
        ):
            if event.content:
                event_dict = {
                    "author": event.author or "expense_approval_workflow",
                    "content": content_to_dict(event.content)
                }
                events_list.append(event_dict)
            
    # Extract final text response
    final_text = ""
    for ev in reversed(events_list):
        if "content" in ev and ev["content"]:
            parts = ev["content"].get("parts", [])
            for p in parts:
                if "text" in p and p["text"]:
                    final_text = p["text"]
                    break
            if final_text:
                break
                
    responses = []
    if final_text:
        responses.append({
            "response": {
                "role": "model",
                "parts": [{"text": final_text}]
            }
        })
        
    return events_list, responses

async def main():
    print("Initializing ADK runner...")
    db_path = "expense_agent/.adk/eval_temp.db"
    session_service = SqliteSessionService(db_path=db_path)
    runner = Runner(agent=root_agent, session_service=session_service, app_name="expense_agent")
    
    dataset_path = Path("tests/eval/datasets/basic-dataset.json")
    output_path = Path("artifacts/traces/generated_traces.json")
    
    print(f"Reading dataset from {dataset_path}...")
    with open(dataset_path, "r", encoding="utf-8") as f:
        dataset = json.load(f)
        
    cases = dataset.get("eval_cases", [])
    n_cases = len(cases)
    print(f"Loaded {n_cases} eval cases.")
    
    output_cases = []
    
    for i, case in enumerate(cases):
        case_id = case["eval_case_id"]
        prompt_text = case["prompt"]["parts"][0]["text"]
        print(f"[{i+1}/{n_cases}] Running case {case_id}...")
        
        events_list, responses = await run_scenario(runner, session_service, case_id, prompt_text)
        
        output_case = {
            "eval_case_id": case_id,
            "prompt": case["prompt"],
            "responses": responses,
            "agent_data": {
                "agents": {
                    "expense_approval_workflow": {
                        "agent_id": "expense_approval_workflow",
                        "agent_type": "Workflow",
                        "description": "",
                        "tools": [],
                        "sub_agents": []
                    }
                },
                "turns": [
                    {
                        "turn_index": 0,
                        "turn_id": "turn_0",
                        "events": events_list
                    }
                ]
            }
        }
        output_cases.append(output_case)
        print(f"[{i+1}/{n_cases}] Case {case_id} completed. Responses count: {len(responses)}")
        
    result = {"eval_cases": output_cases}
    
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(result, f, indent=2)
        
    print(f"Wrote generated traces to {output_path}")
    
    # Cleanup database files
    try:
        if os.path.exists(db_path):
            os.remove(db_path)
        # Also remove temp journal/wal files if any
        for f in os.listdir("expense_agent/.adk"):
            if f.startswith("eval_temp.db-"):
                os.remove(os.path.join("expense_agent/.adk", f))
    except Exception as e:
        print(f"Cleanup warning: {e}")

if __name__ == "__main__":
    asyncio.run(main())
