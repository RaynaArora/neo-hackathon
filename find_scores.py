import requests
import math
import re
from get_civicengine import get_current_state_federal_elections
from credentials import FEC_TOKEN
from typing import Optional, Dict, Any

def clean_search_query(race_name):
    """Cleans a CivicEngine race name into a good Kalshi search query."""
    if "U.S. Senate" in race_name:
        return race_name.replace("U.S. Senate - ", "") + " Senate"
    if "U.S. House" in race_name:
        name = re.sub(r"U.S. House of Representatives - ", "", race_name)
        name = re.sub(r"(\d+)(st|nd|rd|th) Congressional District", r" \1", name)
        return name
    if "State Senate" in race_name or "SD" in race_name:
        return race_name.replace("State Senate - ", "").replace("SD", "")
    if "House of Representatives" in race_name or "HD" in race_name:
        return race_name.replace("House of Representatives - ", "").replace("HD", "")
    return race_name

def get_kalshi_market(race_name):
    """
    Searches the Kalshi API for a given race.
    Returns the *first matching series* or None.
    """
    query = clean_search_query(race_name)
    url = "https://api.elections.kalshi.com/v1/search/series"
    params = {
        'query': query,
        'embedding_search': 'true',
        'order_by': 'querymatch'
    }
    
    try:
        response = requests.get(url, params=params, timeout=10)
        response.raise_for_status()
        data = response.json()
        
        # Handle different possible response structures
        if 'current_page' in data and data['current_page']:
            # Return the *first and most relevant* search result
            series = data['current_page'][0]
            # Ensure markets exist in the response
            if 'markets' in series:
                return series
        elif 'series' in data and data['series']:
            # Alternative response structure
            series = data['series'][0]
            if 'markets' in series:
                return series
        elif isinstance(data, list) and len(data) > 0:
            # Direct list response
            series = data[0]
            if 'markets' in series:
                return series
    except requests.RequestException as e:
        print(f"Kalshi API error for '{race_name}': {e}")
    except (KeyError, IndexError, TypeError) as e:
        print(f"Kalshi API response parsing error for '{race_name}': {e}")
    except Exception as e:
        print(f"Unexpected error querying Kalshi for '{race_name}': {e}")

    return None

def calculate_competitiveness_general(price):
    """Calculates competitiveness for a binary (Rep vs Dem) market."""
    price = max(1, min(99, price)) # Clamp price to 1-99
    return (1 - abs(price - 50) / 50)

def calculate_competitiveness_primary(markets):
    """Calculates competitiveness for a multi-candidate primary."""
    if not markets or len(markets) < 2:
        return 0
    
    # Try to get prices from various possible fields
    prices = []
    for m in markets:
        price = m.get('last_price') or m.get('yes_bid') or m.get('yes_ask')
        if price:
            prices.append(price)
    
    if len(prices) < 2:
        # If we don't have enough prices, try to estimate from bid/ask
        # This is a fallback for markets without last_price
        return 0.3  # Default moderate competitiveness
        
    prices = sorted(prices, reverse=True)
    p1, p2 = prices[0], prices[1]
    
    # Normalize prices to 0-100 range if needed
    if p1 > 100:
        p1 = p1 / 100
    if p2 > 100:
        p2 = p2 / 100
    
    leader_score = max(0, (1 - (p1 / 100)))
    gap_score = max(0, (1 - ((p1 - p2) / 100)))
    return leader_score * gap_score

def parse_race_name(race_name):
    """
    Parse a race name to extract office type, state, and district.
    
    Returns:
        dict with keys: 'office' ('S' or 'H'), 'state' (2-letter code), 'district' (int or None)
    """
    # State abbreviations mapping
    state_abbrev = {
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
    
    result = {'office': None, 'state': None, 'district': None}
    
    # Check for Senate race
    if 'U.S. Senate' in race_name or 'Senate' in race_name:
        result['office'] = 'S'
        # Extract state name
        for state_name, abbrev in state_abbrev.items():
            if state_name in race_name:
                result['state'] = abbrev
                break
    
    # Check for House race
    elif 'U.S. House' in race_name or 'House of Representatives' in race_name:
        result['office'] = 'H'
        # Extract state name
        for state_name, abbrev in state_abbrev.items():
            if state_name in race_name:
                result['state'] = abbrev
                break
        
        # Extract district number
        district_match = re.search(r'(\d+)(?:st|nd|rd|th)?\s+Congressional District', race_name)
        if district_match:
            result['district'] = int(district_match.group(1))
        else:
            # Try alternative pattern
            district_match = re.search(r'District\s+(\d+)', race_name)
            if district_match:
                result['district'] = int(district_match.group(1))
    
    return result


def get_fec_candidates_total_receipts(office: str, state: str, district: Optional[int] = None, 
                                      cycle: int = 2024, verbose: bool = False) -> float:
    """
    Query FEC API to get total receipts (fundraising) for all candidates in a race.
    
    Args:
        office: 'S' for Senate, 'H' for House
        state: Two-letter state code
        district: District number for House races (None for Senate)
        cycle: Election cycle year (default: 2024)
        verbose: Whether to print debug information
    
    Returns:
        Total receipts in dollars (sum of all candidates)
    """
    base_url = "https://api.open.fec.gov/v1/candidates/"
    
    # Check both the current cycle and the previous cycle to get complete data
    # FEC cycles are 2-year periods, so check current and previous 2-year cycle
    cycles_to_check = [cycle]
    if cycle >= 2024:
        cycles_to_check.insert(0, cycle - 2)  # Also check previous cycle (insert first to prioritize)
    # Remove duplicates and sort (most recent first)
    cycles_to_check = sorted(set(cycles_to_check), reverse=True)
    
    total_receipts = 0.0
    candidate_ids_seen = set()
    
    for check_cycle in cycles_to_check:
        params = {
            'api_key': FEC_TOKEN,
            'office': office,
            'state': state,
            'cycle': check_cycle,
            'per_page': 100,
            'election_year': check_cycle if check_cycle == cycle else None,  # Only set for primary cycle
        }
        
        # Remove None values
        params = {k: v for k, v in params.items() if v is not None}
        
        if office == 'H' and district is not None:
            params['district'] = str(district).zfill(2)  # FEC expects 2-digit district
        
        try:
            response = requests.get(base_url, params=params, timeout=10)
            response.raise_for_status()
            data = response.json()
            
            candidates = data.get('results', [])
            
            if verbose and candidates:
                print(f"  FEC: Found {len(candidates)} candidates for {state} {office}{district or ''} (cycle {check_cycle})")
            
            for candidate in candidates:
                candidate_id = candidate.get('candidate_id')
                if not candidate_id or candidate_id in candidate_ids_seen:
                    continue
                
                candidate_ids_seen.add(candidate_id)
                
                # Try to get totals for this candidate across multiple cycles
                max_receipts = 0.0
                for total_cycle in cycles_to_check:
                    totals_url = f"https://api.open.fec.gov/v1/candidate/{candidate_id}/totals/"
                    totals_params = {
                        'api_key': FEC_TOKEN,
                        'cycle': total_cycle,
                        'per_page': 100  # Get all totals for this cycle
                    }
                    
                    try:
                        totals_response = requests.get(totals_url, params=totals_params, timeout=10)
                        totals_response.raise_for_status()
                        totals_data = totals_response.json()
                        
                        totals_list = totals_data.get('results', [])
                        for total in totals_list:
                            receipts = total.get('receipts', 0) or 0
                            max_receipts = max(max_receipts, float(receipts))
                    except requests.RequestException:
                        # If we can't get totals for this cycle, continue
                        continue
                
                if max_receipts > 0:
                    total_receipts += max_receipts
                    if verbose:
                        print(f"  FEC: Candidate {candidate_id}: ${max_receipts:,.0f}")
            
        except requests.RequestException as e:
            if verbose:
                print(f"  FEC API error for cycle {check_cycle}: {e}")
            continue
        except (KeyError, ValueError, TypeError) as e:
            if verbose:
                print(f"  FEC API parsing error for cycle {check_cycle}: {e}")
            continue
    
    if verbose and total_receipts > 0:
        print(f"  FEC: Total receipts: ${total_receipts:,.0f}")
    
    return total_receipts


def calculate_saturation_fec(race_name: str, cycle: int = 2024, verbose: bool = False) -> float:
    """
    Gets FEC data for Federal races and calculates saturation score.
    
    Saturation is inversely related to total fundraising:
    - Higher fundraising = more saturated = lower score (penalty)
    - Lower fundraising = less saturated = higher score (opportunity)
    
    Formula: 1 / log(1 + total_receipts)
    This means:
    - $0 raised: score = 1.0 (highest, no saturation)
    - $1M raised: score ≈ 0.14
    - $10M raised: score ≈ 0.10
    - $100M raised: score ≈ 0.09
    
    Args:
        race_name: Name of the race (e.g., "U.S. Senate - North Carolina")
        cycle: Election cycle year (default: 2024)
        verbose: Whether to print debug information
    
    Returns:
        Saturation score between 0 and 1 (higher = less saturated)
    """
    # Parse race name to get office, state, district
    race_info = parse_race_name(race_name)
    
    if not race_info['office'] or not race_info['state']:
        # Can't parse race, return default moderate score
        if verbose:
            print(f"  FEC: Could not parse race name: {race_name}")
        return 1 / math.log(1 + 10_000_000)  # Default to $10M equivalent
    
    if verbose:
        print(f"  FEC: Querying {race_info['office']} race in {race_info['state']}" + 
              (f" District {race_info['district']}" if race_info['district'] else ""))
    
    # Get total receipts for the race
    total_receipts = get_fec_candidates_total_receipts(
        office=race_info['office'],
        state=race_info['state'],
        district=race_info.get('district'),
        cycle=cycle,
        verbose=verbose
    )
    
    if total_receipts == 0:
        # No fundraising data found, treat as low saturation
        if verbose:
            print(f"  FEC: No fundraising data found, treating as low saturation")
        return 1.0
    
    # Calculate saturation score: inverse log relationship
    # Using log ensures diminishing returns and prevents extreme values
    saturation_score = 1 / math.log(1 + total_receipts)
    
    # Normalize to reasonable range (clamp between 0.05 and 1.0)
    saturation_score = max(0.05, min(1.0, saturation_score))
    
    if verbose:
        print(f"  FEC: Saturation score: {saturation_score:.3f} (receipts: ${total_receipts:,.0f})")
    
    return saturation_score

def calculate_saturation_kalshi(volume, spread):
    """Uses Kalshi's own metrics as a proxy for saturation/attention."""
    # Use the advanced formula: (log(spread)) / (log(volume))
    # This rewards *inefficient* (high spread) and *low attention* (low volume) markets
    spread = max(1, spread)
    volume = max(2, volume) # Avoid log(1) or log(0)
    
    # We normalize to prevent skewed scores
    spread_score = math.log(1 + spread)
    volume_penalty = math.log(1 + volume)
    
    return spread_score / volume_penalty

def get_civic_engine_races():
    """
    Fetches current state and federal elections from Civic Engine API
    and returns a list of individual races.
    """
    try:
        # Get elections from Civic Engine API (verbose=False to reduce output)
        elections_dict = get_current_state_federal_elections(max_elections=100, verbose=False)
        
        # Extract individual races from elections
        races = []
        for election_id, election_data in elections_dict.items():
            election_day = election_data.get('electionDay', '')
            for race in election_data.get('races', []):
                position = race.get('position', {})
                race_name = position.get('name', '')
                race_level = position.get('level', '')
                
                if race_name and race_level in ['STATE', 'FEDERAL']:
                    races.append({
                        'name': race_name,
                        'level': race_level,
                        'day': election_day,
                        'election_name': election_data.get('name', ''),
                        'race_id': race.get('id', '')
                    })
        
        print(f"Fetched {len(races)} state/federal races from Civic Engine API")
        return races
    except Exception as e:
        print(f"Error fetching data from Civic Engine API: {e}")
        print("Falling back to empty list")
        return []

def process_races(max_races=None, verbose=True):
    """
    Main function to process all races and generate a ranked list.
    
    Args:
        max_races: Maximum number of races to process (None for all)
        verbose: Whether to print progress during processing
    """
    # Get races from Civic Engine API
    races = get_civic_engine_races()
    
    if not races:
        print("No races found. Cannot generate recommendations.")
        return
    
    # Limit number of races if specified
    if max_races:
        races = races[:max_races]
        print(f"Processing limited to first {max_races} races")
    
    recommendations = []
    
    if verbose:
        print(f"\nProcessing {len(races)} races...")
        print("=" * 80)

    for i, race in enumerate(races, 1):
        race_name = race['name']
        race_level = race['level']
        election_day = race.get('day', '')
        
        if verbose:
            print(f"\n[{i}/{len(races)}] Processing: {race_name} ({race_level})")
        
        # This will hold the scores
        scores = {
            'name': race_name,
            'level': race_level,
            'day': election_day,
            'source': '',
            'comp_score': 0,
            'sat_score': 0,
            'leverage_score': 0
        }

        # --- TIER 1: ATTEMPT KALSHI ---
        market_series = get_kalshi_market(race_name)

        if market_series and 'markets' in market_series:
            scores['source'] = 'Kalshi'
            markets = market_series.get('markets', [])
            
            if markets:
                # 1. Calculate Competitiveness
                try:
                    if len(markets) <= 2:  # Binary general election
                        market = markets[0]
                        price = market.get('last_price') or market.get('yes_bid', 50)
                        if price:
                            scores['comp_score'] = calculate_competitiveness_general(price)
                            # Use spread from the main market
                            yes_ask = market.get('yes_ask', 0)
                            yes_bid = market.get('yes_bid', 0)
                            spread = max(1, yes_ask - yes_bid)
                        else:
                            spread = 1
                    else:  # Multi-candidate primary
                        scores['comp_score'] = calculate_competitiveness_primary(markets)
                        # Get spread from the *leading* candidate
                        sorted_markets = sorted(
                            [m for m in markets if m.get('last_price')],
                            key=lambda x: x.get('last_price', 0),
                            reverse=True
                        )
                        if sorted_markets:
                            leader = sorted_markets[0]
                            yes_ask = leader.get('yes_ask', 0)
                            yes_bid = leader.get('yes_bid', 0)
                            spread = max(1, yes_ask - yes_bid)
                        else:
                            spread = 1

                    # 2. Calculate Saturation
                    if race_level == 'FEDERAL':
                        # Federal races always use FEC data
                        # Determine cycle from election year
                        try:
                            election_year = int(election_day.split('-')[0]) if election_day else 2024
                            # FEC cycles are typically even years, use the cycle before the election
                            cycle = election_year - 1 if election_year % 2 == 1 else election_year
                        except (ValueError, AttributeError):
                            cycle = 2024
                        scores['sat_score'] = calculate_saturation_fec(race_name, cycle=cycle, verbose=verbose)
                        scores['source'] += " + FEC"
                    else:
                        # State races must use Kalshi proxy
                        volume = market_series.get('total_series_volume', 0)
                        scores['sat_score'] = calculate_saturation_kalshi(volume, spread)
                        
                    if verbose:
                        print(f"  ✓ Found Kalshi market: {len(markets)} markets, comp={scores['comp_score']:.3f}")
                except (KeyError, TypeError, IndexError) as e:
                    if verbose:
                        print(f"  ✗ Error processing Kalshi market data: {e}")
                    # Fall through to fallback
                    market_series = None
            else:
                if verbose:
                    print(f"  ✗ Kalshi market found but no markets in series")
                market_series = None

        # --- TIER 2: FALLBACK (No Kalshi market found) ---
        if not market_series or 'markets' not in market_series or not market_series.get('markets'):
            scores['source'] = 'Civic Engine'
            
            # 1. Calculate Competitiveness (default to moderate for unknown races)
            # In a real implementation, you might use historical data or polls
            scores['comp_score'] = 0.5  # Default moderate competitiveness
            
            # 2. Calculate Saturation
            if race_level == 'FEDERAL':
                # Determine cycle from election year
                try:
                    election_year = int(election_day.split('-')[0]) if election_day else 2024
                    # FEC cycles are typically even years, use the cycle before the election
                    cycle = election_year - 1 if election_year % 2 == 1 else election_year
                except (ValueError, AttributeError):
                    cycle = 2024
                scores['sat_score'] = calculate_saturation_fec(race_name, cycle=cycle, verbose=verbose)
                scores['source'] += " + FEC"
            else:
                # No Kalshi market = low visibility = HIGH score
                # This is an *un-saturated* race by definition
                scores['sat_score'] = 1.0
                
            if verbose:
                print(f"  → No Kalshi market found, using defaults")

        # --- FINAL LEVERAGE SCORE ---
        # We also add an Impact_Score (Federal/State > Local)
        impact_score = 1.0 if race_level == 'FEDERAL' else 0.8
        
        scores['leverage_score'] = (
            scores['comp_score'] * scores['sat_score'] * impact_score
        )
        
        recommendations.append(scores)

    # --- RANK AND PRINT FINAL LIST ---
    ranked_list = sorted(recommendations, key=lambda x: x['leverage_score'], reverse=True)
    
    print("\n" + "=" * 80)
    print("--- Top Donation Recommendations (Ranked by Leverage) ---")
    print("=" * 80)
    
    # Show top 20 recommendations
    top_n = min(20, len(ranked_list))
    for i, r in enumerate(ranked_list[:top_n], 1):
        print(f"\n#{i}: {r['name']} ({r['level']})")
        print(f"  Election Day: {r.get('day', 'N/A')}")
        print(f"  Leverage Score: {r['leverage_score']:.3f}")
        print(f"  Source: {r['source']}")
        print(f"    > Competitiveness: {r['comp_score']:.3f}")
        print(f"    > Saturation/Penalty: {r['sat_score']:.3f}")
    
    if len(ranked_list) > top_n:
        print(f"\n... and {len(ranked_list) - top_n} more races")


if __name__ == "__main__":
    import sys
    # Allow limiting number of races via command line argument
    max_races = None
    if len(sys.argv) > 1:
        try:
            max_races = int(sys.argv[1])
        except ValueError:
            print(f"Invalid argument: {sys.argv[1]}. Expected a number.")
            sys.exit(1)
    
    process_races(max_races=max_races, verbose=True)