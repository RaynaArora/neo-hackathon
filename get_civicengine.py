import requests
from typing import Dict, Any, Optional
from datetime import date
from credentials import CIVIC_ENGINE_TOKEN


# API endpoint
GRAPHQL_ENDPOINT = "https://bpi.civicengine.com/graphql"


def query_civicengine(
    query: str,
    variables: Optional[Dict[str, Any]] = None,
    token: Optional[str] = None
) -> Dict[str, Any]:
    """
    Query the Civic Engine GraphQL API.
    
    Args:
        query: The GraphQL query string (e.g., "{ issues { nodes { id, name } } }")
        variables: Optional dictionary of variables for the GraphQL query
        token: Optional API token. If not provided, uses CIVIC_ENGINE_TOKEN from credentials
    
    Returns:
        Dictionary containing the API response
        
    Raises:
        requests.exceptions.RequestException: If the API request fails
        ValueError: If the token is not provided and not found in credentials
    
    Example:
        >>> query = "{ issues { nodes { id, name } } }"
        >>> response = query_civicengine(query)
        >>> print(response)
    """
    # Use provided token or fall back to credentials
    api_token = token if token is not None else CIVIC_ENGINE_TOKEN
    
    # Validate token
    if not api_token or api_token == "<INSERT TOKEN>":
        raise ValueError(
            "API token not provided. Please set CIVIC_ENGINE_TOKEN in credentials.py, "
            "set the CIVIC_ENGINE_TOKEN environment variable, or pass the token parameter."
        )
    
    # Prepare headers
    headers = {
        'Content-Type': 'application/json',
        'Accept': 'application/json',
        'Authorization': f'Bearer {api_token}'
    }
    
    # Prepare payload
    payload = {"query": query}
    if variables:
        payload["variables"] = variables
    
    # Make the request
    response = requests.post(
        GRAPHQL_ENDPOINT,
        headers=headers,
        json=payload
    )
    
    # Raise an error for bad status codes
    response.raise_for_status()
    
    # Return the JSON response
    return response.json()


def get_current_state_federal_elections(
    token: Optional[str] = None,
    max_elections: int = 10000
) -> Dict[str, Any]:
    """
    Get all currently ongoing elections filtered to state or federal level.
    
    An election is considered "currently ongoing" if its electionDay is today or in the future.
    An election is included if it has at least one race with a STATE or FEDERAL level position.
    
    Args:
        token: Optional API token. If not provided, uses CIVIC_ENGINE_TOKEN from credentials
        max_elections: Maximum number of elections to fetch (default: 100)
    
    Returns:
        Dictionary with election IDs as keys and election data as values.
        Each election entry contains:
        - id: Election ID
        - name: Election name
        - electionDay: Election date (ISO8601 format)
        - races: List of races with STATE or FEDERAL level positions
        - state_federal_race_count: Number of state/federal races in this election
    
    Raises:
        requests.exceptions.RequestException: If the API request fails
        ValueError: If the token is not provided and not found in credentials
    """
    # Get today's date in ISO8601 format
    today = date.today().isoformat()
    
    # Query to get elections with their races and positions
    # We fetch elections with electionDay >= today, then filter by position level
    query = """
    query GetCurrentElections($today: ISO8601Date!, $first: Int!) {
      elections(
        filterBy: { electionDay: { gte: $today } }
        first: $first
      ) {
        nodes {
          id
          name
          electionDay
          races(first: 100) {
            nodes {
              id
              position {
                id
                name
                level
              }
            }
          }
        }
        pageInfo {
          hasNextPage
          endCursor
        }
      }
    }
    """
    
    variables = {
        "today": today,
        "first": max_elections
    }
    
    # Make the query
    response = query_civicengine(query, variables=variables, token=token)
    
    # Check for errors in response
    if "errors" in response:
        raise RuntimeError(f"GraphQL errors: {response['errors']}")
    
    elections_data = response.get("data", {}).get("elections", {}).get("nodes", [])

    #print ("Total elections: ", len(elections_data))
    
    # Filter elections to only include those with STATE or FEDERAL level positions
    filtered_elections = {}
    all_levels = set()
    
    for election in elections_data:
        election_id = election.get("id")
        election_name = election.get("name")
        election_day = election.get("electionDay")

        if verbose:
            print ("Election data: ", election)
            print ("Election id: ", election_id)
            print ("Election name: ", election_name)
            print ("Election day: ", election_day)
        
        # Get races and filter by STATE or FEDERAL level
        races = election.get("races", {}).get("nodes", [])
        state_federal_races = []
        
        for race in races:
            position = race.get("position")
            if position:
                level = position.get("level")
                all_levels.add(level)
                if level in ["STATE", "FEDERAL"]:
                    state_federal_races.append({
                        "id": race.get("id"),
                        "position": {
                            "id": position.get("id"),
                            "name": position.get("name"),
                            "level": level
                        }
                    })
        
        # Only include elections that have at least one STATE or FEDERAL race
        if state_federal_races:
            filtered_elections[election_id] = {
                "id": election_id,
                "name": election_name,
                "electionDay": election_day,
                "races": state_federal_races,
                "state_federal_race_count": len(state_federal_races),
                "total_race_count": len(races)
            }
    
    if verbose:
        print ("All levels: ", all_levels)
    return filtered_elections


if __name__ == "__main__":
    # Example: Get current state and federal elections
    try:
        elections_dict = get_current_state_federal_elections()
        print(f"Found {len(elections_dict)} current state/federal elections:")
        print("-" * 80)
        
        for election_id, election_data in elections_dict.items():
            print(f"\nElection: {election_data['name']}")
            print(f"  ID: {election_id}")
            print(f"  Election Day: {election_data['electionDay']}")
            print(f"  State/Federal Races: {election_data['state_federal_race_count']}")
            print(f"  Total Races: {election_data['total_race_count']}")
            print(f"  Positions:")
            for race in election_data['races'][:5]:  # Show first 5 races
                print(f"    - {race['position']['name']} ({race['position']['level']})")
            if election_data['state_federal_race_count'] > 5:
                print(f"    ... and {election_data['state_federal_race_count'] - 5} more")
        
        print(f"\n\nFull dictionary with {len(elections_dict)} elections stored.")
        
    except ValueError as e:
        print(f"Configuration error: {e}")
    except requests.exceptions.RequestException as e:
        print(f"API request failed: {e}")
    except RuntimeError as e:
        print(f"Error: {e}")

