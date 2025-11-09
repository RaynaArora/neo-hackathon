"""
Get current races with candidates and their issues for the search pipeline.

This is the first stage of the pipeline that fetches races and initializes
the data structure that will be updated by subsequent stages.
"""

import os
import sys
from typing import Dict, Any, Optional, List
from datetime import date, timedelta

# Add parent directory to path to import from get_civicengine
sys.path.append(os.path.join(os.path.dirname(__file__), '..'))
from get_civicengine import query_civicengine


def _extract_nodes(payload: Any) -> List[Dict[str, Any]]:
    """Normalize GraphQL connection responses to a list of nodes."""
    if payload is None:
        return []
    if isinstance(payload, list):
        return [item for item in payload if item]
    if isinstance(payload, dict):
        if payload.get("nodes") is not None:
            return [item for item in payload.get("nodes", []) if item]
        edges = payload.get("edges")
        if edges:
            return [edge.get("node") for edge in edges if edge and edge.get("node")]
    return []


def get_races(
    token: Optional[str] = None,
    max_elections: int = 100,
    days_back: int = 14,
    levels: List[str] = ["STATE", "FEDERAL", "LOCAL", "CITY"]
) -> List[Dict[str, Any]]:
    """
    Get current races with candidates and their issues.
    
    This function:
    1. Fetches elections from (today - days_back) to today
    2. Gets races for those elections
    3. Gets candidates and their issues/stances for each race
    4. Returns a list of race dictionaries with initial relevance scores
    
    Args:
        token: Optional API token. If not provided, uses CIVIC_ENGINE_TOKEN from credentials
        max_elections: Maximum number of elections to fetch (default: 100)
        days_back: Number of days back to start fetching elections (default: 14)
        levels: List of race levels to include (default: STATE, FEDERAL, LOCAL, CITY)
    
    Returns:
        List of race dictionaries, each containing:
        - race_id: Race ID
        - position: Position information (id, name, level)
        - election: Election information (id, name, electionDay)
        - candidates: List of candidates with their issues
        - relevance_score: Initial heuristic relevance score (0.0, will be updated by later stages)
        - metadata: Dictionary for later stages to populate
    """
    start_date = date.today() - timedelta(days=days_back)
    end_date = date.today()
    level_set = set(levels)
    
    # Query to get elections
    elections_query = """
    query GetElections($day: ISO8601Date!, $first: Int!) {
      elections(
        filterBy: { electionDay: { eq: $day } }
        first: $first
      ) {
        nodes {
          id
          name
          electionDay
        }
      }
    }
    """
    
    # Collect elections from date range
    elections_by_id: Dict[str, Dict[str, Any]] = {}
    day = start_date
    election_count = 0
    
    while day <= end_date and election_count < max_elections:
        election_vars = {
            "day": day.isoformat(),
            "first": max_elections - election_count
        }
        
        try:
            election_response = query_civicengine(elections_query, variables=election_vars, token=token)
            
            if "errors" in election_response:
                print(f"Warning: GraphQL errors for {day.isoformat()}: {election_response['errors']}")
                day += timedelta(days=1)
                continue
            
            election_nodes = _extract_nodes(election_response.get("data", {}).get("elections"))
            
            for election in election_nodes:
                if election_count >= max_elections:
                    break
                election_id = election.get("id")
                if election_id and election_id not in elections_by_id:
                    elections_by_id[election_id] = {
                        "id": election_id,
                        "name": election.get("name", ""),
                        "electionDay": election.get("electionDay", "")
                    }
                    election_count += 1
            
            day += timedelta(days=1)
        except Exception as e:
            print(f"Error fetching elections for {day.isoformat()}: {e}")
            day += timedelta(days=1)
            continue
    
    if not elections_by_id:
        return []
    
    # Query to get races with candidates and their stances/issues
    races_query = """
    query GetRacesWithCandidates($electionId: ID!, $first: Int!) {
      races(
        filterBy: { electionId: $electionId }
        first: $first
      ) {
        nodes {
          id
          position {
            id
            name
            level
          }
          candidacies {
            id
            candidate {
              id
              fullName
              firstName
              lastName
            }
            stances {
              id
              issue {
                id
                name
                key
              }
              statement
            }
          }
        }
      }
    }
    """
    
    all_races = []
    
    for election_id, election_info in elections_by_id.items():
        race_vars = {
            "electionId": election_id,
            "first": 200  # Max races per election
        }
        
        try:
            race_response = query_civicengine(races_query, variables=race_vars, token=token)
            
            if "errors" in race_response:
                print(f"Warning: GraphQL errors for election {election_id}: {race_response['errors']}")
                continue
            
            races_data = _extract_nodes(race_response.get("data", {}).get("races"))
            
            for race in races_data:
                position = race.get("position") or {}
                level = position.get("level", "")
                
                # Filter by level
                if level not in level_set:
                    continue
                
                # Extract candidates with their issues
                candidacies = _extract_nodes(race.get("candidacies"))
                candidates = []
                
                for candidacy in candidacies:
                    candidate = candidacy.get("candidate") or {}
                    candidate_name = candidate.get("fullName") or " ".join(
                        filter(None, [candidate.get("firstName"), candidate.get("lastName")])
                    ).strip() or "Unknown"
                    
                    # Extract unique issues from stances
                    stances = _extract_nodes(candidacy.get("stances"))
                    issues = []
                    issue_ids_seen = set()
                    
                    for stance in stances:
                        issue = stance.get("issue", {})
                        issue_id = issue.get("id")
                        issue_name = issue.get("name", "")
                        
                        # Only add unique issues
                        if issue_id and issue_id not in issue_ids_seen:
                            issues.append({
                                "id": issue_id,
                                "name": issue_name,
                                "key": issue.get("key", "")
                            })
                            issue_ids_seen.add(issue_id)
                    
                    candidates.append({
                        "id": candidate.get("id", ""),
                        "name": candidate_name,
                        "fullName": candidate.get("fullName"),
                        "firstName": candidate.get("firstName"),
                        "lastName": candidate.get("lastName"),
                        "issues": issues,
                        "issue_count": len(issues),
                        "stance_count": len(stances)
                    })
                
                # Only include races with at least one candidate
                if candidates:
                    race_dict = {
                        "race_id": race.get("id", ""),
                        "position": {
                            "id": position.get("id", ""),
                            "name": position.get("name", ""),
                            "level": level
                        },
                        "election": {
                            "id": election_info["id"],
                            "name": election_info["name"],
                            "electionDay": election_info["electionDay"]
                        },
                        "candidates": candidates,
                        "candidate_count": len(candidates),
                        "relevance_score": 0.0,  # Initial score, will be updated by later stages
                        "metadata": {
                            "stage": "get_races",
                            "total_issues": sum(c["issue_count"] for c in candidates),
                            "avg_issues_per_candidate": sum(c["issue_count"] for c in candidates) / len(candidates) if candidates else 0
                        }
                    }
                    all_races.append(race_dict)
        
        except Exception as e:
            print(f"Error processing election {election_id}: {e}")
            continue
    
    return all_races


if __name__ == "__main__":
    # Test the function
    print("Fetching races...")
    print("=" * 80)
    
    try:
        races = get_races(max_elections=100, days_back=14)
        
        print(f"\nFound {len(races)} races")
        print("=" * 80)
        
        # Show summary statistics
        total_candidates = sum(r["candidate_count"] for r in races)
        total_issues = sum(r["metadata"]["total_issues"] for r in races)
        
        print(f"\nSummary:")
        print(f"  Total races: {len(races)}")
        print(f"  Total candidates: {total_candidates}")
        print(f"  Total unique issues: {total_issues}")
        print(f"  Average candidates per race: {total_candidates / len(races) if races else 0:.2f}")
        
        # Show first few races as examples
        print(f"\n" + "=" * 80)
        print("Sample races (first 5):")
        print("=" * 80)
        
        for i, race in enumerate(races[:5], 1):
            print(f"\n{i}. {race['position']['name']} ({race['position']['level']})")
            print(f"   Election: {race['election']['name']} ({race['election']['electionDay']})")
            print(f"   Candidates: {race['candidate_count']}")
            print(f"   Relevance Score: {race['relevance_score']}")
            
            # Show first candidate as example
            if race['candidates']:
                candidate = race['candidates'][0]
                print(f"   Example candidate: {candidate['name']}")
                print(f"     Issues: {candidate['issue_count']}")
                if candidate['issues']:
                    issue_names = [issue['name'] for issue in candidate['issues'][:3]]
                    print(f"     Sample issues: {', '.join(issue_names)}")
                    if candidate['issue_count'] > 3:
                        print(f"     ... and {candidate['issue_count'] - 3} more")
        
        if len(races) > 5:
            print(f"\n... and {len(races) - 5} more races")
    
    except Exception as e:
        print(f"Error: {e}")
        import traceback
        traceback.print_exc()

