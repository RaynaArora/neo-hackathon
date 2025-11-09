"""
Civic Engine Stances Query

This module queries state and federal elections and retrieves candidates' stances on issues.
"""

from typing import Dict, Any, Optional, List
from datetime import date
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


def get_elections_with_candidate_stances(
    token: Optional[str] = None,
    max_elections: int = 100,
    max_stances_per_candidate: int = 5,
    max_races_per_election: int = 200,
    require_stances: bool = True
) -> Dict[str, Any]:
    """
    Query upcoming state and federal elections, then fetch candidate stances per election.
    
    Args:
        token: Optional API token. If not provided, uses CIVIC_ENGINE_TOKEN from credentials
        max_elections: Maximum number of elections to fetch (default: 100)
        max_stances_per_candidate: Maximum number of stances to return per candidate (default: 5)
        max_races_per_election: Maximum number of races to fetch per election (default: 200)
    
    Returns:
        Dictionary keyed by election ID containing races, candidates, and stances.
    """
    today = date.today().isoformat()

    elections_query = """
    query GetStateFederalElections($today: ISO8601Date!, $first: Int!) {
      elections(
        filterBy: { electionDay: { gte: $today } }
        first: $first
      ) {
        nodes {
          id
          name
          electionDay
          races(first: 50) {
            nodes {
              position {
                level
              }
            }
          }
        }
      }
    }
    """

    election_vars = {
        "today": today,
        "first": max_elections
    }

    election_response = query_civicengine(elections_query, variables=election_vars, token=token)

    if "errors" in election_response:
        raise RuntimeError(f"GraphQL errors: {election_response['errors']}")

    election_nodes = _extract_nodes(election_response.get("data", {}).get("elections"))

    # Filter to elections that have at least one state or federal race
    eligible_elections = []
    for election in election_nodes:
        races_preview = _extract_nodes(election.get("races"))
        has_state_federal = any(
            (race.get("position") or {}).get("level") in ("STATE", "FEDERAL")
            for race in races_preview
        )
        if has_state_federal:
            eligible_elections.append({
                "id": election.get("id"),
                "name": election.get("name"),
                "electionDay": election.get("electionDay")
            })

    races_query = """
    query GetElectionRacesWithStances($electionId: ID!, $first: Int!) {
      races(
        filterBy: { electionId: $electionId, level: [STATE, FEDERAL] }
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
                expandedText
              }
              statement
              referenceUrl
              locale
            }
          }
        }
      }
    }
    """

    result: Dict[str, Any] = {}

    for election in eligible_elections:
        election_id = election["id"]
        race_vars = {
            "electionId": election_id,
            "first": max_races_per_election
        }

        race_response = query_civicengine(races_query, variables=race_vars, token=token)

        if "errors" in race_response:
            result[election_id] = {
                **election,
                "races": [],
                "race_count": 0,
                "error": race_response["errors"]
            }
            continue

        races_data = _extract_nodes(race_response.get("data", {}).get("races"))

        election_entry = {
            **election,
            "races": [],
            "race_count": 0
        }

        for race in races_data:
            position = race.get("position") or {}
            level = position.get("level")
            if level not in ("STATE", "FEDERAL"):
                continue

            candidacies = _extract_nodes(race.get("candidacies"))
            processed_candidacies = []

            for candidacy in candidacies:
                candidate = candidacy.get("candidate") or {}

                stances = _extract_nodes(candidacy.get("stances"))
                processed_stances = []
                for stance in stances[:max_stances_per_candidate]:
                    issue = stance.get("issue", {})
                    processed_stances.append({
                        "id": stance.get("id"),
                        "issue": {
                            "id": issue.get("id"),
                            "name": issue.get("name"),
                            "key": issue.get("key"),
                            "expandedText": issue.get("expandedText")
                        },
                        "statement": stance.get("statement"),
                        "referenceUrl": stance.get("referenceUrl"),
                        "locale": stance.get("locale")
                    })

                if processed_stances:
                    candidate_name = candidate.get("fullName") or " ".join(
                        filter(None, [candidate.get("firstName"), candidate.get("lastName")])
                    ).strip() or "Unknown"

                    processed_candidacies.append({
                        "id": candidacy.get("id"),
                        "candidate": {
                            "id": candidate.get("id"),
                            "name": candidate_name,
                            "fullName": candidate.get("fullName"),
                            "firstName": candidate.get("firstName"),
                            "lastName": candidate.get("lastName")
                        },
                        "stances": processed_stances,
                        "stance_count": len(processed_stances)
                    })

            if len(processed_candidacies) < 2:
                continue

            race_entry = {
                "id": race.get("id"),
                "position": {
                    "id": position.get("id"),
                    "name": position.get("name"),
                    "level": level
                },
                "candidacies": processed_candidacies,
                "candidate_count": len(processed_candidacies)
            }

            if not processed_candidacies and not require_stances:
                race_entry["note"] = "No candidacies with stance data for this race"

            election_entry["races"].append(race_entry)

        election_entry["race_count"] = len(election_entry["races"])
        if election_entry["race_count"]:
            result[election_id] = election_entry

    return result


if __name__ == "__main__":
    try:
        print("Fetching state and federal elections with candidate stances...")
        elections = get_elections_with_candidate_stances(max_elections=50)
        
        print(f"\nFound {len(elections)} state/federal elections with candidate stances:")
        print("=" * 80)
        
        for election_id, election_data in elections.items():
            print(f"\n{'='*80}")
            print(f"Election: {election_data['name']}")
            print(f"Election Day: {election_data['electionDay']}")
            print(f"Races: {election_data['race_count']}")
            print(f"{'-'*80}")
            
            for race in election_data['races']:
                print(f"\n  Race: {race['position']['name']} ({race['position']['level']})")
                print(f"  Candidates: {race['candidate_count']}")
                if race.get('note'):
                    print(f"  Note: {race['note']}")
                
                for candidacy in race['candidacies']:
                    candidate = candidacy['candidate']
                    print(f"\n    Candidate: {candidate['name']}")
                    print(f"    Stances ({candidacy['stance_count']} total, showing top {len(candidacy['stances'])}):")
                    
                    for i, stance in enumerate(candidacy['stances'], 1):
                        issue = stance['issue']
                        print(f"      {i}. {issue['name']}")
                        if issue.get('expandedText'):
                            print(f"         Issue: {issue['expandedText']}")
                        if stance.get('statement'):
                            print(f"         Statement: {stance['statement']}")
                        if stance.get('referenceUrl'):
                            print(f"         Reference: {stance['referenceUrl']}")
                        if stance.get('locale'):
                            print(f"         Locale: {stance['locale']}")
        
        print(f"\n\nTotal: {len(elections)} elections processed")
        
    except ValueError as e:
        print(f"Configuration error: {e}")
    except RuntimeError as e:
        print(f"Error: {e}")
    except Exception as e:
        print(f"Unexpected error: {e}")

