import asyncio
import os
import json
from dotenv import load_dotenv
load_dotenv()

import vertexai
from vertexai.resources.preview import reasoning_engines

def main():
    vertexai.init(project="project-3ba8b553-324f-445f-b23", location="us-east1")
    
    engine_id = "projects/626689579306/locations/us-east1/reasoningEngines/1811115553272627200"
    print(f"Loading reasoning engine {engine_id}...")
    remote_agent = reasoning_engines.ReasoningEngine(engine_id)
    
    print("\nRemote agent properties and methods:")
    print(dir(remote_agent))
    
    # Let's inspect the underlying object or call query if it exists
    # Normally, reasoning_engines.ReasoningEngine has a .query() method or similar
    # Let's see if we can call remote_agent.query
    if hasattr(remote_agent, "query"):
        print("remote_agent has query() method")
    else:
        print("remote_agent does NOT have query() method")

if __name__ == "__main__":
    main()
