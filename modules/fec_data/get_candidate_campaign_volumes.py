"""
Get campaign volumes for candidates from CivicEngine elections.
Uses FEC API to get totals by race, then matches candidates by last name.
"""

from typing import Dict, Any, Optional, List, Tuple
from datetime import date, timedelta
from collections import defaultdict
import sys
import os
import requests
import re
import time

# Add parent directory to path to import from get_civicengine
sys.path.append(os.path.join(os.path.dirname(__file__), '../..'))
from get_civicengine import query_civicengine

# Get FEC token from environment
FEC_TOKEN = os.getenv('FEC_TOKEN')
if not FEC_TOKEN:
    raise ValueError("FEC_TOKEN environment variable is not set. Please set it before running.")

# State name to abbreviation mapping
STATE_NAME_TO_ABBREV = {
    'Alabama': 'AL', 'Alaska': 'AK', 'Arizona': 'AZ', 'Arkansas': 'AR',
    'California': 'CA', 'Colorado': 'CO', 'Connecticut': 'CT', 'Delaware': 'DE',
    'Florida': 'FL', 'Georgia': 'GA', 'Hawaii': 'HI', 'Idaho': 'ID',
    'Illinois': 'IL', 'Indiana': 'IN', 'Iowa': 'IA', 'Kansas': 'KS',
    'Kentucky': 'KY', 'Louisiana': 'LA', 'Maine': 'ME', 'Maryland': 'MD',
    'Massachusetts': 'MA', 'Michigan': 'MI', 'Minnesota': 'MN', 'Mississippi': 'MS',
    'Missouri': 'MO', 'Montana': 'MT', 'Nebraska': 'NE', 'Nevada': 'NV',
    'New Hampshire': 'NH', 'New Jersey': 'NJ', 'New Mexico': 'NM', 'New York': 'NY',
    'North Carolina': 'NC', 'North Dakota': 'ND', 'Ohio': 'OH', 'Oklahoma': 'OK',
    'Oregon': 'OR', 'Pennsylvania': 'PA', 'Rhode Island': 'RI', 'South Carolina': 'SC',
    'South Dakota': 'SD', 'Tennessee': 'TN', 'Texas': 'TX', 'Utah': 'UT',
    'Vermont': 'VT', 'Virginia': 'VA', 'Washington': 'WA', 'West Virginia': 'WV',
    'Wisconsin': 'WI', 'Wyoming': 'WY', 'District of Columbia': 'DC'
}


def parse_race_name(race_name: str) -> Dict[str, Any]:
    """
    Parse a race name to extract office type, state, and district.
    
    Returns:
        dict with keys: 'office' ('S' or 'H'), 'state' (2-letter code), 'district' (int or None)
    """
    result = {'office': None, 'state': None, 'district': None}
    
    # Extract state name (works for all race types)
    for state_name, abbrev in STATE_NAME_TO_ABBREV.items():
        if state_name in race_name:
            result['state'] = abbrev
            break
    
    # Check for Senate race
    if 'U.S. Senate' in race_name or ('Senate' in race_name and 'U.S.' in race_name):
        result['office'] = 'S'
    
    # Check for House race
    elif 'U.S. House' in race_name or ('House of Representatives' in race_name and 'U.S.' in race_name):
        result['office'] = 'H'
        
        # Extract district number
        district_match = re.search(r'(\d+)(?:st|nd|rd|th)?\s+Congressional District', race_name)
        if district_match:
            result['district'] = int(district_match.group(1))
        else:
            # Try alternative pattern
            district_match = re.search(r'District\s+(\d+)', race_name)
            if district_match:
                result['district'] = int(district_match.group(1))
            # Check for At Large districts
            elif 'At Large' in race_name or 'at-large' in race_name.lower():
                result['district'] = None  # At Large district
    
    return result


def get_fec_candidates_for_race(office: str, state: str, district: Optional[int] = None, 
                                cycle: int = 2024, verbose: bool = False) -> List[Dict[str, Any]]:
    """
    Query FEC API to get candidates with their totals for a specific race.
    
    Args:
        office: 'S' for Senate, 'H' for House
        state: Two-letter state code
        district: District number for House races (None for Senate)
        cycle: Election cycle year (default: 2024)
        verbose: Whether to print debug information
    
    Returns:
        List of candidate dictionaries with 'name', 'candidate_id', and 'receipts'
    """
    base_url = "https://api.open.fec.gov/v1/candidates/"
    
    # Check both the current cycle and the previous cycle to get complete data
    cycles_to_check = [cycle]
    if cycle >= 2024:
        cycles_to_check.insert(0, cycle - 2)  # Also check previous cycle
    cycles_to_check = sorted(set(cycles_to_check), reverse=True)
    
    fec_candidates = []
    candidate_ids_seen = set()
    
    for check_cycle in cycles_to_check:
        params = {
            'api_key': FEC_TOKEN,
            'office': office,
            'state': state,
            'cycle': check_cycle,
            'per_page': 100,
            'election_year': check_cycle if check_cycle == cycle else None,
        }
        
        # Remove None values
        params = {k: v for k, v in params.items() if v is not None}
        
        if office == 'H' and district is not None:
            params['district'] = str(district).zfill(2)  # FEC expects 2-digit district
        
        max_retries = 3
        retry_delay = 1
        
        for attempt in range(max_retries):
            try:
                response = requests.get(base_url, params=params, timeout=10)
                
                if response.status_code == 429:
                    if attempt < max_retries - 1:
                        wait_time = retry_delay * (2 ** attempt)
                        if verbose:
                            print(f"  FEC: Rate limited (cycle {check_cycle}), waiting {wait_time}s")
                        time.sleep(wait_time)
                        continue
                    else:
                        response.raise_for_status()
                
                response.raise_for_status()
                data = response.json()
                
                candidates = data.get('results', [])
                
                if verbose and candidates:
                    print(f"  FEC: Found {len(candidates)} candidates for {state} {office}{district or ''} (cycle {check_cycle})")
                
                # Process candidates
                for candidate in candidates:
                    candidate_id = candidate.get('candidate_id')
                    if not candidate_id or candidate_id in candidate_ids_seen:
                        continue
                    
                    candidate_ids_seen.add(candidate_id)
                    
                    # Get totals for this candidate
                    max_receipts = 0.0
                    for total_cycle in cycles_to_check:
                        totals_url = f"https://api.open.fec.gov/v1/candidate/{candidate_id}/totals/"
                        totals_params = {
                            'api_key': FEC_TOKEN,
                            'cycle': total_cycle,
                            'per_page': 100
                        }
                        
                        for totals_attempt in range(max_retries):
                            try:
                                totals_response = requests.get(totals_url, params=totals_params, timeout=10)
                                
                                if totals_response.status_code == 429:
                                    if totals_attempt < max_retries - 1:
                                        wait_time = retry_delay * (2 ** totals_attempt)
                                        time.sleep(wait_time)
                                        continue
                                    else:
                                        totals_response.raise_for_status()
                                
                                totals_response.raise_for_status()
                                totals_data = totals_response.json()
                                
                                totals_list = totals_data.get('results', [])
                                for total in totals_list:
                                    receipts = total.get('receipts', 0) or 0
                                    max_receipts = max(max_receipts, float(receipts))
                                break
                            except requests.RequestException:
                                if totals_attempt < max_retries - 1:
                                    wait_time = retry_delay * (2 ** totals_attempt)
                                    time.sleep(wait_time)
                                continue
                    
                    # Store candidate with receipts
                    fec_candidates.append({
                        'name': candidate.get('name', ''),
                        'candidate_id': candidate_id,
                        'receipts': max_receipts,
                        'party': candidate.get('party_full', '') or candidate.get('party', '')
                    })
                
                break  # Success, exit retry loop
                
            except requests.RequestException as e:
                if attempt < max_retries - 1:
                    wait_time = retry_delay * (2 ** attempt)
                    if verbose:
                        print(f"  FEC: Request error (attempt {attempt + 1}/{max_retries}): {e}")
                    time.sleep(wait_time)
                else:
                    if verbose:
                        print(f"  FEC API error after {max_retries} attempts: {e}")
                    continue
            except (KeyError, ValueError, TypeError) as e:
                if verbose:
                    print(f"  FEC API parsing error: {e}")
                break
    
    return fec_candidates


def extract_last_name(full_name: str) -> str:
    """Extract last name from full name."""
    if not full_name:
        return ''
    name_parts = full_name.split()
    if name_parts:
        return name_parts[-1].lower()
    return ''


def match_candidates_by_last_name(civic_candidates: List[Dict[str, Any]], 
                                  fec_candidates: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """
    Match Civic Engine candidates to FEC candidates by last name.
    
    Args:
        civic_candidates: List of Civic Engine candidate dicts
        fec_candidates: List of FEC candidate dicts with receipts
    
    Returns:
        List of matched candidates with receipts
    """
    matched = []
    
    for civic_cand in civic_candidates:
        civic_name = civic_cand.get('name', '')
        civic_last_name = extract_last_name(civic_name)
        
        if not civic_last_name:
            continue
        
        # Find matching FEC candidate by last name
        best_match = None
        for fec_cand in fec_candidates:
            fec_name = fec_cand.get('name', '')
            fec_last_name = extract_last_name(fec_name)
            
            if fec_last_name == civic_last_name:
                best_match = fec_cand
                break  # Use first match
        
        matched.append({
            **civic_cand,
            'fec_name': best_match.get('name') if best_match else None,
            'fec_candidate_id': best_match.get('candidate_id') if best_match else None,
            'receipts': best_match.get('receipts', 0.0) if best_match else None,
            'fec_party': best_match.get('party') if best_match else None,
            'matched': best_match is not None
        })
    
    return matched


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


def get_candidates_from_elections(
    token: Optional[str] = None,
    max_elections: int = 10,
    max_races_per_election: int = 200,
    levels: List[str] = ["STATE", "FEDERAL"]
) -> Dict[str, List[Dict[str, Any]]]:
    """
    Query elections and extract all candidates, grouped by race.
    
    Args:
        token: Optional API token. If not provided, uses CIVIC_ENGINE_TOKEN from environment
        max_elections: Maximum number of elections to fetch
        max_races_per_election: Maximum number of races to fetch per election
        levels: List of election levels to include
        
    Returns:
        Dictionary mapping race names to lists of candidate dictionaries
    """
    today = (date.today() - timedelta(days=14)).isoformat()
    level_set = set(levels)

    elections_query = """
    query GetStateFederalElections($day: ISO8601Date!, $first: Int!) {
      elections(
        filterBy: { electionDay: { eq: $day } }
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

    start_date = date.fromisoformat(today)
    end_date = date.today()

    elections_by_id: Dict[str, Dict[str, Any]] = {}
    day = start_date
    while day <= end_date:
        election_vars = {
            "day": day.isoformat(),
            "first": max_elections
        }

        election_response = query_civicengine(elections_query, variables=election_vars, token=token)

        if "errors" in election_response:
            raise RuntimeError(f"GraphQL errors: {election_response['errors']}")

        election_nodes = _extract_nodes(election_response.get("data", {}).get("elections"))
        for election in election_nodes:
            elections_by_id[election.get("id")] = {
                "id": election.get("id"),
                "name": election.get("name"),
                "electionDay": election.get("electionDay")
            }
        day += timedelta(days=1)

    races_query = """
    query GetElectionRacesWithCandidates($electionId: ID!, $first: Int!) {
      races(
        filterBy: { electionId: $electionId, level: [FEDERAL, STATE] }
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
          }
        }
      }
    }
    """

    # Group candidates by race (position name)
    candidates_by_race: Dict[str, List[Dict[str, Any]]] = defaultdict(list)

    for election_id in elections_by_id:
        race_vars = {
            "electionId": election_id,
            "first": max_races_per_election,
        }

        race_response = query_civicengine(races_query, variables=race_vars, token=token)

        if "errors" in race_response:
            continue

        races_data = _extract_nodes(race_response.get("data", {}).get("races"))

        for race in races_data:
            position = race.get("position") or {}
            level = position.get("level")
            if level not in level_set:
                continue

            race_name = position.get("name", "")
            if not race_name:
                continue

            candidacies = _extract_nodes(race.get("candidacies"))

            for candidacy in candidacies:
                candidate = candidacy.get("candidate") or {}
                candidate_id = candidate.get("id")

                # Extract candidate name
                candidate_name = candidate.get("fullName") or " ".join(
                    filter(None, [candidate.get("firstName"), candidate.get("lastName")])
                ).strip() or "Unknown"

                if candidate_name and candidate_name != "Unknown":
                    candidates_by_race[race_name].append({
                        "id": candidate_id,
                        "name": candidate_name,
                        "fullName": candidate.get("fullName"),
                        "firstName": candidate.get("firstName"),
                        "lastName": candidate.get("lastName"),
                        "election": elections_by_id[election_id]["name"],
                        "electionDay": elections_by_id[election_id]["electionDay"],
                        "position": race_name,
                        "level": level
                    })

    return dict(candidates_by_race)


def main():
    """Main function to get campaign volumes for all candidates."""
    try:
        print("Fetching candidates from elections...")
        candidates_by_race = get_candidates_from_elections(max_elections=10)
        
        print(f"\nFound {sum(len(cands) for cands in candidates_by_race.values())} candidates across {len(candidates_by_race)} races")
        print("=" * 80)
        
        # Determine election year from current date
        current_year = date.today().year
        # FEC cycles are 2-year periods ending in even years
        if current_year % 2 == 0:
            cycle = current_year
        else:
            cycle = current_year - 1
        
        all_matched_candidates = []
        
        for race_name, civic_candidates in candidates_by_race.items():
            print(f"\nRace: {race_name}")
            print(f"  Candidates from Civic Engine: {len(civic_candidates)}")
            
            # Only process FEDERAL races (FEC API only has federal data)
            if not any(c.get('level') == 'FEDERAL' for c in civic_candidates):
                print(f"  Skipping (not a FEDERAL race)")
                # Still add candidates with None receipts
                for cand in civic_candidates:
                    all_matched_candidates.append({
                        **cand,
                        'fec_name': None,
                        'fec_candidate_id': None,
                        'receipts': None,
                        'fec_party': None,
                        'matched': False
                    })
                continue
            
            # Parse race name to get office, state, district
            race_info = parse_race_name(race_name)
            
            if not race_info.get('office') or not race_info.get('state'):
                print(f"  Could not parse race name (office={race_info.get('office')}, state={race_info.get('state')})")
                # Still add candidates with None receipts
                for cand in civic_candidates:
                    all_matched_candidates.append({
                        **cand,
                        'fec_name': None,
                        'fec_candidate_id': None,
                        'receipts': None,
                        'fec_party': None,
                        'matched': False
                    })
                continue
            
            # Get FEC candidates for this race
            print(f"  Querying FEC for {race_info['office']} race in {race_info['state']}" + 
                  (f" District {race_info.get('district')}" if race_info.get('district') else ""))
            
            fec_candidates = get_fec_candidates_for_race(
                office=race_info['office'],
                state=race_info['state'],
                district=race_info.get('district'),
                cycle=cycle,
                verbose=False
            )
            
            print(f"  FEC candidates found: {len(fec_candidates)}")
            
            # Match by last name
            matched = match_candidates_by_last_name(civic_candidates, fec_candidates)
            all_matched_candidates.extend(matched)
            
            # Print matches for this race
            for cand in matched:
                if cand['matched']:
                    print(f"    ✓ {cand['name']} -> {cand['fec_name']}: ${cand['receipts']:,.2f}")
                else:
                    print(f"    ✗ {cand['name']}: No FEC match found")
        
        # Print summary
        print("\n" + "=" * 80)
        print("SUMMARY")
        print("=" * 80)
        
        matched_count = sum(1 for c in all_matched_candidates if c.get('matched'))
        unmatched_count = len(all_matched_candidates) - matched_count
        
        print(f"\nTotal candidates: {len(all_matched_candidates)}")
        print(f"Matched with FEC: {matched_count}")
        print(f"Unmatched: {unmatched_count}")
        
        # print("\n" + "=" * 80)
        # print("DETAILED RESULTS")
        # print("=" * 80)
        
        # for i, candidate in enumerate(all_matched_candidates, 1):
        #     print(f"\n{i}. {candidate['name']}")
        #     print(f"   Election: {candidate.get('election', 'N/A')}")
        #     print(f"   Position: {candidate.get('position', 'N/A')}")
        #     if candidate.get('matched'):
        #         print(f"   FEC Name: {candidate.get('fec_name', 'N/A')}")
        #         print(f"   FEC Party: {candidate.get('fec_party', 'N/A')}")
        #         print(f"   Campaign Volume: ${candidate.get('receipts', 0):,.2f}")
        #     else:
        #         print(f"   Campaign Volume: None (no FEC match)")
        
    except ValueError as e:
        print(f"Configuration error: {e}")
    except RuntimeError as e:
        print(f"Error: {e}")
    except Exception as e:
        print(f"Unexpected error: {e}")
        import traceback
        traceback.print_exc()


if __name__ == "__main__":
    main()
