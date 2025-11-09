"""
Calculate importance/relevance scores for races using leverage scoring.

This stage of the pipeline calculates leverage scores (competitiveness × saturation)
for each race and updates the relevance_score field.
"""

import os
import sys
import math
import re
import requests
import time
from typing import Dict, Any, Optional, List, Tuple
from datetime import date, datetime
from collections import defaultdict

# Get FEC token from environment
FEC_TOKEN = os.getenv('FEC_TOKEN')
if not FEC_TOKEN:
    try:
        sys.path.append(os.path.join(os.path.dirname(__file__), '..'))
        from credentials import FEC_TOKEN
    except ImportError:
        pass

if not FEC_TOKEN:
    print("Warning: FEC_TOKEN not set. FEC-based saturation scoring will be unavailable.")


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

# State FIPS codes mapping
STATE_FIPS_MAP = {
    'AL': '01', 'AK': '02', 'AZ': '04', 'AR': '05', 'CA': '06', 'CO': '08', 'CT': '09',
    'DE': '10', 'FL': '12', 'GA': '13', 'HI': '15', 'ID': '16', 'IL': '17', 'IN': '18',
    'IA': '19', 'KS': '20', 'KY': '21', 'LA': '22', 'ME': '23', 'MD': '24', 'MA': '25',
    'MI': '26', 'MN': '27', 'MS': '28', 'MO': '29', 'MT': '30', 'NE': '31', 'NV': '32',
    'NH': '33', 'NJ': '34', 'NM': '35', 'NY': '36', 'NC': '37', 'ND': '38', 'OH': '39',
    'OK': '40', 'OR': '41', 'PA': '42', 'RI': '44', 'SC': '45', 'SD': '46', 'TN': '47',
    'TX': '48', 'UT': '49', 'VT': '50', 'VA': '51', 'WA': '53', 'WV': '54', 'WI': '55',
    'WY': '56', 'DC': '11'
}


def parse_race_name(race_name: str) -> Dict[str, Any]:
    """
    Parse a race name to extract office type, state, and district.
    
    Returns:
        dict with keys: 'office' ('S' or 'H'), 'state' (2-letter code), 'district' (int or None)
    """
    result = {'office': None, 'state': None, 'district': None}
    
    # Extract state name
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
            district_match = re.search(r'District\s+(\d+)', race_name)
            if district_match:
                result['district'] = int(district_match.group(1))
            elif 'At Large' in race_name or 'at-large' in race_name.lower():
                result['district'] = None
    
    return result


def clean_search_query(race_name: str) -> str:
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


def validate_kalshi_market_match(market_series: Dict[str, Any], race_name: str, 
                                  election_year: Optional[int] = None) -> Tuple[bool, float, List[str]]:
    """
    Validate that a Kalshi market series matches the race we're looking for.
    
    Returns:
        Tuple of (is_valid, match_score, warnings)
    """
    warnings = []
    match_score = 0.0
    
    if not market_series:
        return False, 0.0, ["No market series provided"]
    
    market_title = (market_series.get('series_title', '') or market_series.get('event_title', '') or '').lower()
    market_ticker_orig = market_series.get('series_ticker', '') or market_series.get('event_ticker', '') or ''
    market_ticker = market_ticker_orig.lower()
    market_ticker_upper = market_ticker_orig.upper()
    
    race_info = parse_race_name(race_name)
    
    # Check state match
    state_match = False
    if race_info.get('state'):
        state = race_info['state'].lower()
        state_names = {
            'al': 'alabama', 'ak': 'alaska', 'az': 'arizona', 'ar': 'arkansas',
            'ca': 'california', 'co': 'colorado', 'ct': 'connecticut', 'de': 'delaware',
            'fl': 'florida', 'ga': 'georgia', 'hi': 'hawaii', 'id': 'idaho',
            'il': 'illinois', 'in': 'indiana', 'ia': 'iowa', 'ks': 'kansas',
            'ky': 'kentucky', 'la': 'louisiana', 'me': 'maine', 'md': 'maryland',
            'ma': 'massachusetts', 'mi': 'michigan', 'mn': 'minnesota', 'ms': 'mississippi',
            'mo': 'missouri', 'mt': 'montana', 'ne': 'nebraska', 'nv': 'nevada',
            'nh': 'new hampshire', 'nj': 'new jersey', 'nm': 'new mexico', 'ny': 'new york',
            'nc': 'north carolina', 'nd': 'north dakota', 'oh': 'ohio', 'ok': 'oklahoma',
            'or': 'oregon', 'pa': 'pennsylvania', 'ri': 'rhode island', 'sc': 'south carolina',
            'sd': 'south dakota', 'tn': 'tennessee', 'tx': 'texas', 'ut': 'utah',
            'vt': 'vermont', 'va': 'virginia', 'wa': 'washington', 'wv': 'west virginia',
            'wi': 'wisconsin', 'wy': 'wyoming', 'dc': 'district of columbia'
        }
        state_full = state_names.get(state, state)
        state_lower = state.lower()
        state_full_lower = state_full.lower()
        state_upper = state.upper()
        if (state_lower in market_title or state_lower in market_ticker or 
            state_full_lower in market_title or state_upper in market_ticker_upper):
            state_match = True
            match_score += 0.3
    
    # Check office type match
    office_match = False
    if race_info.get('office') == 'H':
        if ('house' in market_title or 'HOUSE' in market_ticker_upper or 
            market_ticker_upper.startswith('HOUSE') or 'h-' in market_ticker):
            office_match = True
            match_score += 0.3
    elif race_info.get('office') == 'S':
        if ('senate' in market_title or 'SENATE' in market_ticker_upper or 
            market_ticker_upper.startswith('SENATE') or 's-' in market_ticker):
            office_match = True
            match_score += 0.3
    
    # Check district match (for House races)
    district_match = False
    if race_info.get('office') == 'H' and race_info.get('district'):
        district = race_info['district']
        district_str = str(district)
        if (district_str in market_title or district_str in market_ticker or 
            f"-{district:02d}" in market_ticker or f"{district:02d}" in market_ticker):
            district_match = True
            match_score += 0.2
    
    # Check year match
    year_match = False
    if election_year:
        year_str = str(election_year)
        if year_str in market_title or year_str in market_ticker:
            year_match = True
            match_score += 0.2
    
    # Determine if match is valid
    is_valid = state_match and office_match
    if race_info.get('office') == 'H' and race_info.get('district'):
        is_valid = is_valid and district_match
    
    if not is_valid and state_match and office_match:
        if year_match or not election_year:
            is_valid = True
            warnings.append("Using market despite some mismatches (state and office match)")
    
    return is_valid, match_score, warnings


def get_kalshi_market(race_name: str, election_year: Optional[int] = None) -> Optional[Dict[str, Any]]:
    """
    Searches the Kalshi API for a given race and validates the match.
    
    Returns:
        Best matching market series or None
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
        
        all_series = []
        if 'current_page' in data and data['current_page']:
            all_series = data['current_page']
        elif 'series' in data and data['series']:
            all_series = data['series']
        elif isinstance(data, list):
            all_series = data
        
        if not all_series:
            return None
        
        # Validate and score each series
        scored_series = []
        for series in all_series:
            if 'markets' not in series or not series.get('markets'):
                continue
            
            is_valid, match_score, warnings = validate_kalshi_market_match(
                series, race_name, election_year
            )
            
            scored_series.append({
                'series': series,
                'is_valid': is_valid,
                'match_score': match_score,
                'warnings': warnings
            })
        
        if not scored_series:
            return None
        
        # Sort by match score (highest first), prioritize valid matches
        scored_series.sort(key=lambda x: (x['is_valid'], x['match_score']), reverse=True)
        
        # Get best match
        best_match = scored_series[0]
        best_series = best_match['series']
        best_series['_validation'] = {
            'is_valid': best_match['is_valid'],
            'match_score': best_match['match_score'],
            'warnings': best_match['warnings']
        }
        
        return best_series
        
    except Exception:
        return None


def calculate_competitiveness_general(price: float) -> float:
    """Calculates competitiveness for a binary (Rep vs Dem) market."""
    price = max(1, min(99, price))
    return (1 - abs(price - 50) / 50)


def calculate_competitiveness_primary(markets: List[Dict[str, Any]]) -> float:
    """
    Calculates competitiveness for a multi-candidate primary using entropy-based measure.
    """
    if not markets or len(markets) < 2:
        return 0.0
    
    prices = []
    for m in markets:
        price = m.get('last_price') or m.get('yes_bid') or m.get('yes_ask')
        if price is not None:
            prices.append(price)
    
    if len(prices) < 2:
        if len(prices) == 1:
            single_price = prices[0]
            if single_price > 100:
                single_price = single_price / 100
            return max(0.1, min(0.9, 1 - (single_price / 100)))
        else:
            return 0.5
    
    # Normalize prices to 0-100 range
    normalized_prices = []
    for p in prices:
        if p > 100:
            p = p / 100
        normalized_prices.append(max(0.01, min(99, p)))
    
    # Calculate entropy-based competitiveness
    total = sum(normalized_prices)
    if total == 0:
        return 0.5
    
    probabilities = [p / total for p in normalized_prices]
    
    # Calculate entropy: -Σ(p_i * log(p_i))
    entropy = 0.0
    for p in probabilities:
        if p > 0:
            entropy -= p * math.log(p)
    
    # Normalize entropy to 0-1 range
    max_entropy = math.log(len(probabilities))
    entropy_score = entropy / max_entropy if max_entropy > 0 else 0.0
    
    # Consider gap between top 2 candidates
    sorted_prices = sorted(normalized_prices, reverse=True)
    p1, p2 = sorted_prices[0], sorted_prices[1]
    gap_score = 1 - ((p1 - p2) / 100)
    gap_score = max(0.0, min(1.0, gap_score))
    
    # Combine entropy and gap scores
    competitiveness = 0.6 * entropy_score + 0.4 * gap_score
    
    # Adjust for number of candidates
    num_candidates = len(markets)
    if num_candidates > 3:
        competitiveness = min(1.0, competitiveness * 1.1)
    
    return max(0.0, min(1.0, competitiveness))


def get_fec_candidates_total_receipts(office: str, state: str, district: Optional[int] = None, 
                                      cycle: int = 2024) -> float:
    """
    Query FEC API to get total receipts (fundraising) for all candidates in a race.
    """
    base_url = "https://api.open.fec.gov/v1/candidates/"
    
    if not FEC_TOKEN:
        return 0.0
    
    cycles_to_check = [cycle]
    if cycle >= 2024:
        cycles_to_check.insert(0, cycle - 2)
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
            'election_year': check_cycle if check_cycle == cycle else None,
        }
        
        params = {k: v for k, v in params.items() if v is not None}
        
        if office == 'H' and district is not None:
            params['district'] = str(district).zfill(2)
        
        max_retries = 3
        retry_delay = 1
        
        for attempt in range(max_retries):
            try:
                response = requests.get(base_url, params=params, timeout=10)
                
                if response.status_code == 429:
                    if attempt < max_retries - 1:
                        wait_time = retry_delay * (2 ** attempt)
                        time.sleep(wait_time)
                        continue
                    else:
                        response.raise_for_status()
                
                response.raise_for_status()
                data = response.json()
                
                candidates = data.get('results', [])
                
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
                    
                    if max_receipts > 0:
                        total_receipts += max_receipts
                
                break
                
            except requests.RequestException:
                if attempt < max_retries - 1:
                    wait_time = retry_delay * (2 ** attempt)
                    time.sleep(wait_time)
                else:
                    continue
            except (KeyError, ValueError, TypeError):
                break
    
    return total_receipts


def calculate_saturation_fec(race_name: str, cycle: int = 2024) -> Tuple[float, Dict[str, Any]]:
    """
    Gets FEC data for Federal races and calculates saturation score.
    
    Returns:
        Tuple of (saturation_score, metadata_dict)
    """
    metadata = {
        "data_quality": "high",
        "method": "fec",
        "cycle": cycle,
        "warnings": [],
        "error": None,
        "total_receipts": 0.0
    }
    
    race_info = parse_race_name(race_name)
    
    if not race_info['office'] or not race_info['state']:
        metadata["data_quality"] = "low"
        metadata["warnings"].append("Could not parse race name")
        default_score = 1 / math.log(1 + 10_000_000)
        return default_score, metadata
    
    try:
        total_receipts = get_fec_candidates_total_receipts(
            office=race_info['office'],
            state=race_info['state'],
            district=race_info.get('district'),
            cycle=cycle
        )
        metadata["total_receipts"] = total_receipts
    except Exception as e:
        metadata["error"] = str(e)
        metadata["data_quality"] = "none"
        metadata["warnings"].append(f"FEC API error: {e}")
        return 0.5, metadata
    
    if total_receipts == 0:
        current_year = date.today().year
        if cycle > current_year:
            metadata["warnings"].append(f"Future cycle {cycle} - data may not exist yet")
            metadata["data_quality"] = "low"
        elif cycle < 2018:
            metadata["warnings"].append(f"Old cycle {cycle} - data may be incomplete")
            metadata["data_quality"] = "low"
        
        metadata["warnings"].append("No fundraising data found")
        return 1.0, metadata
    
    # Calculate saturation score: inverse log relationship
    saturation_score = 1 / math.log(1 + total_receipts)
    saturation_score = max(0.05, min(1.0, saturation_score))
    
    return saturation_score, metadata


def calculate_saturation_kalshi(volume: float, spread: float) -> Tuple[float, Dict[str, Any]]:
    """
    Uses Kalshi's own metrics as a proxy for saturation/attention.
    
    Returns:
        Tuple of (saturation_score, metadata_dict)
    """
    metadata = {
        "data_quality": "medium",
        "method": "kalshi_proxy",
        "warnings": [],
        "volume": volume,
        "spread": spread
    }
    
    spread = max(1, spread)
    volume = max(2, volume)
    
    spread_score = math.log(1 + spread)
    volume_penalty = math.log(1 + volume)
    
    saturation_score = spread_score / volume_penalty
    saturation_score = max(0.05, min(1.0, saturation_score))
    
    if volume < 10:
        metadata["warnings"].append("Low Kalshi market volume")
        metadata["data_quality"] = "low"
    elif volume < 100:
        metadata["warnings"].append("Moderate Kalshi market volume")
        metadata["data_quality"] = "medium"
    else:
        metadata["data_quality"] = "high"
    
    return saturation_score, metadata


def calculate_race_leverage_score(race: Dict[str, Any], verbose: bool = False) -> Dict[str, Any]:
    """
    Calculate leverage score for a single race.
    
    Leverage Score = Competitiveness × Saturation
    
    Args:
        race: Race dictionary from get_races.py
        verbose: Whether to print debug information
    
    Returns:
        Dictionary with leverage score and metadata
    """
    race_name = race['position']['name']
    race_level = race['position']['level']
    election_day = race['election']['electionDay']
    
    # Determine election year
    try:
        election_year = int(election_day.split('-')[0]) if election_day else None
    except (ValueError, AttributeError):
        election_year = None
    
    # Initialize scores
    comp_score = 0.5  # Default moderate competitiveness
    sat_score = 1.0   # Default neutral saturation (no penalty)
    comp_sources = []
    sat_method = None
    
    # --- COMPETITIVENESS: Try Kalshi first ---
    market_series = get_kalshi_market(race_name, election_year=election_year)
    
    if market_series and 'markets' in market_series:
        markets = market_series.get('markets', [])
        validation_info = market_series.get('_validation', {})
        
        if markets:
            try:
                match_score = validation_info.get('match_score', 1.0)
                is_valid_match = validation_info.get('is_valid', True)
                
                # Calculate competitiveness from market
                if len(markets) <= 2:  # Binary general election
                    market = markets[0]
                    price = market.get('last_price') or market.get('yes_bid', 50)
                    if price:
                        kalshi_comp = calculate_competitiveness_general(price)
                    else:
                        kalshi_comp = 0.5
                else:  # Multi-candidate primary
                    kalshi_comp = calculate_competitiveness_primary(markets)
                
                # Weight based on match quality
                kalshi_weight = match_score if is_valid_match else match_score * 0.5
                comp_score = kalshi_comp
                comp_sources.append('Kalshi')
                
                # Calculate saturation for state/local races using Kalshi proxy
                if race_level != 'FEDERAL' and is_valid_match and match_score >= 0.6:
                    volume = market_series.get('total_series_volume', 0) or 0
                    # Get spread from leading candidate
                    if len(markets) <= 2:
                        market = markets[0]
                        yes_ask = market.get('yes_ask', 0)
                        yes_bid = market.get('yes_bid', 0)
                        spread = max(1, yes_ask - yes_bid)
                    else:
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
                    
                    sat_score, sat_metadata = calculate_saturation_kalshi(volume, spread)
                    sat_method = 'kalshi_proxy'
                
            except Exception as e:
                if verbose:
                    print(f"  Error processing Kalshi market: {e}")
    
    # --- SATURATION: For FEDERAL races, use FEC ---
    if race_level == 'FEDERAL' and sat_method is None:
        try:
            current_year = date.today().year
            cycle_year = election_year if election_year else current_year
            
            # FEC cycles are 2-year periods ending in even years
            if cycle_year % 2 == 0:
                cycle = cycle_year
            else:
                cycle = cycle_year - 1
            
            if cycle > current_year:
                if current_year % 2 == 0:
                    cycle = current_year
                else:
                    cycle = current_year - 1
            
            if cycle < 2018:
                cycle = 2024
            
            sat_score, sat_metadata = calculate_saturation_fec(race_name, cycle=cycle)
            sat_method = 'fec'
        except Exception as e:
            if verbose:
                print(f"  Error calculating FEC saturation: {e}")
            sat_score = 1.0  # Default neutral
    
    # --- CALCULATE LEVERAGE SCORE ---
    leverage_score = comp_score * sat_score
    
    # Apply time-based boost
    try:
        if election_day:
            election_date = datetime.strptime(election_day, '%Y-%m-%d').date()
            days_until = (election_date - date.today()).days
            
            if days_until >= 0:
                if days_until <= 90:
                    leverage_score *= 1.1  # 10% boost
                elif days_until <= 180:
                    leverage_score *= 1.05  # 5% boost
        else:
            days_until = None
    except (ValueError, AttributeError):
        days_until = None
    
    return {
        'leverage_score': leverage_score,
        'competitiveness': comp_score,
        'saturation': sat_score,
        'comp_sources': comp_sources,
        'sat_method': sat_method,
        'days_until': days_until
    }


def get_importance_scores(races: List[Dict[str, Any]], verbose: bool = False) -> List[Dict[str, Any]]:
    """
    Calculate importance/relevance scores for a list of races.
    
    This function updates the relevance_score field in each race dictionary
    based on leverage scoring (competitiveness × saturation).
    
    Args:
        races: List of race dictionaries from get_races.py
        verbose: Whether to print progress information
    
    Returns:
        Updated list of race dictionaries with relevance_score populated
    """
    if verbose:
        print(f"Calculating importance scores for {len(races)} races...")
    
    for i, race in enumerate(races, 1):
        if verbose and i % 10 == 0:
            print(f"  Processing race {i}/{len(races)}...")
        
        try:
            score_data = calculate_race_leverage_score(race, verbose=verbose)
            
            # Update race with scores
            race['relevance_score'] = score_data['leverage_score']
            race['metadata']['leverage_score'] = score_data['leverage_score']
            race['metadata']['competitiveness'] = score_data['competitiveness']
            race['metadata']['saturation'] = score_data['saturation']
            race['metadata']['comp_sources'] = score_data['comp_sources']
            race['metadata']['sat_method'] = score_data['sat_method']
            race['metadata']['days_until'] = score_data['days_until']
            race['metadata']['stage'] = 'get_importance_scores'
        
        except Exception as e:
            if verbose:
                print(f"  Error calculating score for race {race.get('race_id', 'unknown')}: {e}")
            # Keep default score of 0.0 on error
            race['metadata']['error'] = str(e)
    
    if verbose:
        print(f"Completed calculating importance scores")
    
    return races


if __name__ == "__main__":
    # Test with sample race data
    test_races = [
        {
            "race_id": "test-1",
            "position": {
                "id": "pos-1",
                "name": "U.S. Senate - North Carolina",
                "level": "FEDERAL"
            },
            "election": {
                "id": "election-1",
                "name": "2024 General Election",
                "electionDay": "2024-11-05"
            },
            "candidates": [
                {
                    "id": "cand-1",
                    "name": "John Smith",
                    "issues": [{"id": "6", "name": "Education"}]
                }
            ],
            "candidate_count": 1,
            "relevance_score": 0.0,
            "metadata": {}
        }
    ]
    
    print("Testing get_importance_scores...")
    print("=" * 80)
    
    updated_races = get_importance_scores(test_races, verbose=True)
    
    for race in updated_races:
        print(f"\nRace: {race['position']['name']}")
        print(f"  Relevance Score: {race['relevance_score']:.3f}")
        print(f"  Competitiveness: {race['metadata'].get('competitiveness', 'N/A')}")
        print(f"  Saturation: {race['metadata'].get('saturation', 'N/A')}")
        print(f"  Sources: {race['metadata'].get('comp_sources', [])}")

