#!/usr/bin/env python3
"""
Get historical election winners using Civic Engine GraphQL API.

This approach uses the ElectionResult field on Candidacy objects to directly
determine winners from past elections.
"""

from get_civicengine import query_civicengine
from credentials import CIVIC_ENGINE_TOKEN
from find_scores import parse_race_name, get_candidate_party_from_fec
from typing import List, Dict, Any, Optional
from datetime import date, timedelta
import re

def get_historical_winners_from_position(race_name: str, election_name: Optional[str] = None, verbose: bool = False) -> List[Dict[str, Any]]:
    """
    Get historical winners for a position by querying all past races for that position.
    
    Approach:
    1. Parse race name to get position identifier
    2. Query positions by name/level
    3. Get all races for that position
    4. Filter for past elections
    5. Extract winners from candidacies with result = "WON"
    
    Args:
        race_name: Name of the race (e.g., "U.S. House of Representatives - Alabama 1st Congressional District" or "Mount Vernon City Council")
        election_name: Optional election name (used to extract state for local races)
        verbose: Whether to print debug info
    
    Returns:
        List of winner dictionaries with year, name, party, and election info
    """
    # Parse race name to extract office type, state, and level (FEDERAL vs STATE vs CITY)
    # Try to determine if it's a federal, state, or city race
    is_city_race = 'City' in race_name or 'Mayor' in race_name or 'Council' in race_name
    is_federal = 'U.S.' in race_name or 'United States' in race_name
    
    if is_city_race:
        race_level = 'CITY'
    elif is_federal:
        race_level = 'FEDERAL'
    else:
        race_level = 'STATE'
    
    # For local races, state may be in election_name
    race_info = parse_race_name(race_name, election_name=election_name)
    
    # For city races, we may not have state in race_name, but we need it for filtering
    # For federal/state races, we need state
    if not race_info.get('state') and race_level != 'CITY':
        if verbose:
            print(f"  Could not parse state from race: {race_name}")
        return []
    
    state = race_info.get('state')
    
    # Determine district (only for House races and some state races)
    district = race_info.get('district')
    
    # Extract office type from race name for better matching
    office_type = None
    if 'U.S. Senate' in race_name or (race_level == 'FEDERAL' and 'Senate' in race_name):
        office_type = 'S'
        district = None
    elif 'U.S. House' in race_name or (race_level == 'FEDERAL' and 'House' in race_name):
        office_type = 'H'
    elif 'State Senate' in race_name or (race_level == 'STATE' and 'Senate' in race_name and 'U.S.' not in race_name):
        office_type = 'STATE_SENATE'
        district = race_info.get('district')  # State Senate may have districts
    elif 'State House' in race_name or (race_level == 'STATE' and 'House' in race_name and 'U.S.' not in race_name):
        office_type = 'STATE_HOUSE'
        district = race_info.get('district')
    elif 'Governor' in race_name:
        office_type = 'GOVERNOR'
        district = None
    elif is_city_race:
        # City/local race - extract city name and office type from race_name
        # Examples: "Mount Vernon City Council", "New York City Mayor", "Albany City Mayor"
        if 'Mayor' in race_name:
            office_type = 'MAYOR'
        elif 'Council' in race_name:
            office_type = 'COUNCIL'
        else:
            office_type = 'CITY'
        # Extract city name (everything before "City" or at the start)
        city_match = re.search(r'^([^C]+?)\s+City', race_name)
        if city_match:
            city_name = city_match.group(1).strip()
        else:
            # Fallback: use race_name as search pattern
            city_name = race_name
    else:
        # Try to use parsed office type
        office_type = race_info.get('office')
    
    # Build position name pattern to search for
    # Try to match the position name from the race name
    # Example: "U.S. House of Representatives - Alabama 1st Congressional District"
    state_names = {
        'AL': 'Alabama', 'AK': 'Alaska', 'AZ': 'Arizona', 'AR': 'Arkansas',
        'CA': 'California', 'CO': 'Colorado', 'CT': 'Connecticut', 'DE': 'Delaware',
        'FL': 'Florida', 'GA': 'Georgia', 'HI': 'Hawaii', 'ID': 'Idaho',
        'IL': 'Illinois', 'IN': 'Indiana', 'IA': 'Iowa', 'KS': 'Kansas',
        'KY': 'Kentucky', 'LA': 'Louisiana', 'ME': 'Maine', 'MD': 'Maryland',
        'MA': 'Massachusetts', 'MI': 'Michigan', 'MN': 'Minnesota', 'MS': 'Mississippi',
        'MO': 'Missouri', 'MT': 'Montana', 'NE': 'Nebraska', 'NV': 'Nevada',
        'NH': 'New Hampshire', 'NJ': 'New Jersey', 'NM': 'New Mexico', 'NY': 'New York',
        'NC': 'North Carolina', 'ND': 'North Dakota', 'OH': 'Ohio', 'OK': 'Oklahoma',
        'OR': 'Oregon', 'PA': 'Pennsylvania', 'RI': 'Rhode Island', 'SC': 'South Carolina',
        'SD': 'South Dakota', 'TN': 'Tennessee', 'TX': 'Texas', 'UT': 'Utah',
        'VT': 'Vermont', 'VA': 'Virginia', 'WA': 'Washington', 'WV': 'West Virginia',
        'WI': 'Wisconsin', 'WY': 'Wyoming', 'DC': 'District of Columbia'
    }
    state_full = state_names.get(state, state) if state else None
    
    # Build search pattern based on office type and level
    # For federal races: "U.S. House/Senate - State"
    # For state races: "State Office - State" or "State Office - State District X"
    # For city races: "City Name City Council" or "City Name Mayor"
    if office_type == 'H':
        # Federal House
        if district is not None:
            search_pattern = f"{state_full} {district}"
        else:
            search_pattern = f"{state_full} At Large"
    elif office_type == 'S':
        # Federal Senate - position name is "U.S. Senate - State"
        search_pattern = f"U.S. Senate - {state_full}"
    elif office_type == 'STATE_SENATE':
        # State Senate
        if district is not None:
            search_pattern = f"{state_full} State Senate {district}"
        else:
            search_pattern = f"{state_full} State Senate"
    elif office_type == 'STATE_HOUSE':
        # State House
        if district is not None:
            search_pattern = f"{state_full} State House {district}"
        else:
            search_pattern = f"{state_full} State House"
    elif office_type == 'GOVERNOR':
        # Governor
        search_pattern = f"{state_full} Governor"
    elif is_city_race:
        # City race - use the race_name directly or city name
        # Civic Engine position names for city races are typically like:
        # "Mount Vernon City Council", "New York City Mayor", etc.
        search_pattern = race_name  # Use full race name for city positions
    else:
        # Try to use state and parts of race name
        search_pattern = state_full if state_full else race_name
    
    # Build query based on level - GraphQL needs the enum value directly in the query
    # Civic Engine supports FEDERAL, STATE, COUNTY, and CITY levels
    if race_level == 'FEDERAL':
        query = '''
        query GetPositionAndRaces($positionName: String!) {
          positions(
            filterBy: {
              name: { contains: $positionName }
              level: FEDERAL
            }
            first: 20
          ) {
            nodes {
              id
              name
              level
              races(first: 100, orderBy: {field: ELECTION_DAY, direction: DESC}) {
                nodes {
                  id
                  election {
                    id
                    name
                    electionDay
                  }
                  candidacies {
                    id
                    candidate {
                      id
                      fullName
                      bioguideId
                    }
                    result
                  }
                }
              }
            }
          }
        }
        '''
    elif race_level == 'CITY':
        query = '''
        query GetPositionAndRaces($positionName: String!) {
          positions(
            filterBy: {
              name: { contains: $positionName }
              level: CITY
            }
            first: 20
          ) {
            nodes {
              id
              name
              level
              races(first: 100, orderBy: {field: ELECTION_DAY, direction: DESC}) {
                nodes {
                  id
                  election {
                    id
                    name
                    electionDay
                  }
                  candidacies {
                    id
                    candidate {
                      id
                      fullName
                      bioguideId
                    }
                    result
                  }
                }
              }
            }
          }
        }
        '''
    else:
        # STATE level (or default)
        query = '''
        query GetPositionAndRaces($positionName: String!) {
          positions(
            filterBy: {
              name: { contains: $positionName }
              level: STATE
            }
            first: 20
          ) {
            nodes {
              id
              name
              level
              races(first: 100, orderBy: {field: ELECTION_DAY, direction: DESC}) {
                nodes {
                  id
                  election {
                    id
                    name
                    electionDay
                  }
                  candidacies {
                    id
                    candidate {
                      id
                      fullName
                      bioguideId
                    }
                    result
                  }
                }
              }
            }
          }
        }
        '''
    
    try:
        result = query_civicengine(query, {'positionName': search_pattern}, CIVIC_ENGINE_TOKEN)
        
        if 'errors' in result:
            if verbose:
                print(f"  GraphQL errors: {result['errors']}")
            return []
        
        positions = result.get('data', {}).get('positions', {}).get('nodes', [])
        
        if verbose:
            print(f"  Found {len(positions)} positions matching '{search_pattern}'")
        
        # Find the exact matching position
        matching_position = None
        for position in positions:
            pos_name = position.get('name', '')
            is_match = False
            
            # Match based on office type
            if office_type == 'H':
                # Federal House: "U.S. House of Representatives - State Xth Congressional District"
                if state_full in pos_name and 'House of Representatives' in pos_name:
                    if district is not None:
                        # Check district match
                        district_match = re.search(r'(\d+)(?:st|nd|rd|th)?\s+Congressional', pos_name, re.IGNORECASE)
                        if district_match:
                            found_district = int(district_match.group(1))
                            if found_district == district:
                                is_match = True
                        else:
                            # Try "District X" pattern
                            district_match = re.search(r'District\s+(\d+)', pos_name, re.IGNORECASE)
                            if district_match:
                                found_district = int(district_match.group(1))
                                if found_district == district:
                                    is_match = True
                    else:
                        # At Large district
                        if 'At Large' in pos_name or 'at-large' in pos_name.lower():
                            is_match = True
            elif office_type == 'S':
                # Federal Senate: "U.S. Senate - State"
                if state_full in pos_name and 'U.S. Senate' in pos_name:
                    is_match = True
            elif office_type == 'STATE_SENATE':
                # State Senate: "State Senate - State District X" or "State Senate - State"
                if state_full in pos_name and 'State Senate' in pos_name and 'U.S.' not in pos_name:
                    if district is not None:
                        # Check district match
                        district_match = re.search(r'District\s+(\d+)', pos_name, re.IGNORECASE)
                        if district_match:
                            found_district = int(district_match.group(1))
                            if found_district == district:
                                is_match = True
                        elif str(district) in pos_name:
                            is_match = True
                    else:
                        # No district specified, match any state senate for this state
                        is_match = True
            elif office_type == 'STATE_HOUSE':
                # State House: "State House of Representatives - State District X"
                if state_full in pos_name and ('State House' in pos_name or 'House of Representatives' in pos_name) and 'U.S.' not in pos_name:
                    if district is not None:
                        # Check district match
                        district_match = re.search(r'District\s+(\d+)', pos_name, re.IGNORECASE)
                        if district_match:
                            found_district = int(district_match.group(1))
                            if found_district == district:
                                is_match = True
                        elif str(district) in pos_name:
                            is_match = True
                    else:
                        # No district specified
                        is_match = True
            elif office_type == 'GOVERNOR':
                # Governor: "State Governor"
                if state_full in pos_name and 'Governor' in pos_name:
                    is_match = True
            else:
                # Generic match: check if state and key terms from race name are in position name
                if state_full in pos_name:
                    # Try to match key terms from original race name
                    key_terms = [word for word in race_name.split() if word.lower() not in ['-', 'of', 'the', 'and']]
                    if any(term.lower() in pos_name.lower() for term in key_terms[:3]):  # Check first few key terms
                        is_match = True
            
            if is_match:
                matching_position = position
                break
        
        if not matching_position:
            if verbose:
                print(f"  No matching position found for {race_name}")
            return []
        
        if verbose:
            print(f"  Found matching position: {matching_position.get('name')}")
        
        # Get all races for this position
        races = matching_position.get('races', {}).get('nodes', [])
        
        if verbose:
            print(f"  Found {len(races)} total races for this position")
        
        # Filter for past races and focus on general elections (typically in November)
        today = date.today().isoformat()
        past_races = []
        for race in races:
            election = race.get('election', {})
            election_day = election.get('electionDay', '')
            election_name = election.get('name', '').lower()
            
            # Only include past elections
            if not election_day or election_day >= today:
                continue
            
            # Prefer general elections (typically in November, or named "General")
            # Filter out primaries and special elections if we can identify them
            election_month = int(election_day[5:7]) if len(election_day) >= 7 else None
            
            # General elections are typically in November (month 11)
            # Also check if election name contains "general"
            is_general = False
            if election_month == 11:
                is_general = True
            elif 'general' in election_name:
                is_general = True
            elif 'primary' not in election_name and 'special' not in election_name:
                # If it's not clearly a primary or special, assume it might be a general
                # We'll prioritize November elections later
                is_general = True
            
            past_races.append({
                'race': race,
                'election_day': election_day,
                'election_year': int(election_day[:4]) if election_day else None,
                'election_month': election_month,
                'is_general': is_general,
                'election_name': election_name
            })
        
        if verbose:
            print(f"  Found {len(past_races)} past races")
        
        # Extract winners from past races
        winners_by_year = {}  # year -> winner dict (to deduplicate)
        
        for race_info in past_races:
            race = race_info['race']
            election_year = race_info['election_year']
            election_day = race_info['election_day']
            is_general = race_info['is_general']
            
            if not election_year:
                continue
            
            candidacies = race.get('candidacies', [])
            
            # Find winners (result = "WON" or "WIN")
            for cand in candidacies:
                result = cand.get('result')
                if result and result.upper() in ['WON', 'WIN']:
                    person = cand.get('candidate', {})
                    winner_name = person.get('fullName', '')
                    bioguide_id = person.get('bioguideId')
                    
                    if winner_name:
                        # If we already have a winner for this year, prefer general election
                        if election_year in winners_by_year:
                            existing = winners_by_year[election_year]
                            # Keep existing if it's already from a general election
                            if existing.get('is_general'):
                                continue
                            # Replace with general election if this is one
                            if not is_general:
                                continue
                        
                        # Get party from FEC
                        party = get_candidate_party_from_fec(
                            winner_name,
                            bioguide_id,
                            state,
                            district,
                            cycle=election_year,
                            verbose=False
                        )
                        
                        winner_data = {
                            'year': election_year,
                            'name': winner_name,
                            'party': party,
                            'bioguide_id': bioguide_id,
                            'election_date': election_day,
                            'result': result,
                            'method': 'civicengine_result',
                            'is_general': is_general
                        }
                        
                        winners_by_year[election_year] = winner_data
                        
                        if verbose:
                            election_type = "General" if is_general else "Other"
                            print(f"    ✓ {election_year} ({election_type}): {winner_name} ({party or 'Unknown party'})")
        
        # Convert to list and sort by year (descending - most recent first)
        winners = list(winners_by_year.values())
        winners.sort(key=lambda x: x['year'], reverse=True)
        
        return winners
        
    except Exception as e:
        if verbose:
            print(f"  Error: {e}")
        import traceback
        if verbose:
            traceback.print_exc()
        return []


def get_historical_winners_civicengine(race_name: str, years_back: int = 6, election_name: Optional[str] = None, verbose: bool = False) -> List[Dict[str, Any]]:
    """
    Get historical winners for a race using Civic Engine GraphQL API.
    
    This function queries the Position, then gets all past Races for that position,
    and extracts winners from Candidacies with result = "WON".
    Works for federal, state, and city/local races.
    
    Args:
        race_name: Name of the race
        years_back: How many years back to filter (not used directly - gets all past races)
        election_name: Optional election name (used to extract state for local races)
        verbose: Whether to print debug info
    
    Returns:
        List of winners with year, name, and party
    """
    if verbose:
        print(f"  CivicEngine Historical: Getting historical winners for {race_name}")
    
    # Get all historical winners from the position
    # Pass election_name to help extract state for local races
    winners = get_historical_winners_from_position(race_name, election_name=election_name, verbose=verbose)
    
    if verbose:
        if winners:
            print(f"  CivicEngine Historical: Found {len(winners)} historical winner(s)")
        else:
            print(f"  CivicEngine Historical: No winners found")
    
    # Filter by years_back if needed (optional - can return all)
    if years_back and winners:
        current_year = date.today().year
        cutoff_year = current_year - years_back
        winners = [w for w in winners if w.get('year', 0) >= cutoff_year]
        if verbose and len(winners) < len([w for w in winners if w.get('year', 0) >= cutoff_year]):
            print(f"  CivicEngine Historical: Filtered to {len(winners)} winners within {years_back} years")
    
    return winners


def test_civicengine_historical_winners():
    """Test the Civic Engine historical winners functionality"""
    print("=" * 80)
    print("TEST: Getting Historical Winners from Civic Engine API")
    print("=" * 80)
    
    test_races = [
        "U.S. House of Representatives - Alabama 1st Congressional District",
        "U.S. House of Representatives - Massachusetts 7th Congressional District",
        "U.S. House of Representatives - New York 10th Congressional District",
    ]
    
    for race_name in test_races:
        print(f"\n{'='*80}")
        print(f"Testing: {race_name}")
        print(f"{'='*80}")
        
        winners = get_historical_winners_civicengine(race_name, years_back=6, verbose=True)
        
        if winners:
            print(f"\n✓ Found {len(winners)} historical winner(s):")
            for winner in winners:
                print(f"  - {winner['year']}: {winner['name']} ({winner['party'] or 'Unknown party'})")
        else:
            print("\n⚠️  No winners found")


if __name__ == "__main__":
    test_civicengine_historical_winners()

