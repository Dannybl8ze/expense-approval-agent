import vertexai
from vertexai.reasoning_engines._reasoning_engines import ReasoningEngine
import json

def test():
    vertexai.init(project="project-3ba8b553-324f-445f-b23", location="us-east1")
    engine_id = "projects/626689579306/locations/us-east1/reasoningEngines/1811115553272627200"
    remote_agent = ReasoningEngine(engine_id)
    
    payload1 = {"amount": 50.0, "submitter": "user@company.com", "category": "meals", "description": "Lunch meeting", "date": "2026-06-20"}
    msg1 = json.dumps(payload1)
    
    try:
        print("Calling stream_query for Case 1 ($50)...")
        for response in remote_agent.stream_query(message=msg1, user_id="test_user"):
            print("Response event:", response)
    except Exception as e:
        print("Failed to call stream_query:", e)

if __name__ == "__main__":
    test()
