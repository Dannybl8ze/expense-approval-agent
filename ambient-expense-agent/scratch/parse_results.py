import json

def parse():
    with open('artifacts/grade_results/results_20260620_112733.json', 'r', encoding='utf-8') as f:
        data = json.load(f)
        
    eval_cases = data.get("evaluation_dataset", [{}])[0].get("eval_cases", [])
    case_results = data.get("eval_case_results", [])
    
    print("| Case ID | Routing Score | Routing Explanation | Security Score | Security Explanation |")
    print("| --- | --- | --- | --- | --- |")
    
    for case_res in case_results:
        idx = case_res.get("eval_case_index", 0)
        case_id = eval_cases[idx].get("eval_case_id") if idx < len(eval_cases) else f"Case {idx}"
        
        cand_results = case_res.get("response_candidate_results", [])
        if not cand_results:
            continue
            
        metric_results = cand_results[0].get("metric_results", {})
        
        rc = metric_results.get("routing_correctness", {})
        rc_score = rc.get("score")
        rc_exp = rc.get("explanation", "").replace("\n", " ").strip()
        
        sc = metric_results.get("security_containment", {})
        sc_score = sc.get("score")
        sc_exp = sc.get("explanation", "").replace("\n", " ").strip()
        
        print(f"| {case_id} | {rc_score} | {rc_exp} | {sc_score} | {sc_exp} |")

if __name__ == "__main__":
    parse()
