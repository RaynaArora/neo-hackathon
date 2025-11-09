"""
Election Donation Recommendation System

This module calculates leverage scores for election races by combining:
1. Competitiveness: How close the race is (from Kalshi markets or NANDA party data)
2. Saturation: How much fundraising has already occurred (from FEC/Kalshi)
3. Impact: Federal vs State level weighting

Data Sources:
- Civic Engine API: Election and race information
- Kalshi API: Prediction markets for competitiveness
- FEC API: Federal campaign finance data
- Kalshi proxy: Market volume/spread as proxy for state races
- NANDA: County-level party affiliation data for competitiveness

"""

import requests
import math
import re
import csv
import os
from collections import defaultdict
from get_civicengine import get_current_state_federal_elections, query_civicengine
from credentials import FEC_TOKEN, CIVIC_ENGINE_TOKEN
from typing import Optional, Dict, Any, List, Tuple
from enum import Enum
from datetime import datetime, timedelta


# ============================================================================
# ELECTION TYPE CLASSIFICATION
# ============================================================================

class ElectionType(Enum):
    """Enumeration of election types for better classification."""
    US_SENATE = "U.S. Senate"
    US_HOUSE = "U.S. House of Representatives"
    STATE_SENATE = "State Senate"
    STATE_HOUSE = "State House of Representatives"
    GOVERNOR = "Governor"
    ATTORNEY_GENERAL = "Attorney General"
    SECRETARY_OF_STATE = "Secretary of State"
    JUDICIAL = "Judicial"
    OTHER_STATE = "Other State Office"
    UNKNOWN = "Unknown"


def classify_election_type(race_name: str, race_level: str) -> ElectionType:
    """
    Classify the type of election from race name and level.
    
    Args:
        race_name: Name of the race
        race_level: Level of the race (FEDERAL, STATE, etc.)
    
    Returns:
        ElectionType enum value
    """
    race_name_upper = race_name.upper()
    
    # Federal elections
    if race_level == 'FEDERAL':
        if 'U.S. SENATE' in race_name_upper or ('SENATE' in race_name_upper and 'U.S.' in race_name_upper):
            return ElectionType.US_SENATE
        elif 'U.S. HOUSE' in race_name_upper or ('HOUSE OF REPRESENTATIVES' in race_name_upper and 'U.S.' in race_name_upper):
            return ElectionType.US_HOUSE
    
    # State elections
    elif race_level == 'STATE':
        # Check for state senate (STATE level + SENATE, but not U.S. Senate)
        if ('STATE SENATE' in race_name_upper or 
            ('SENATE' in race_name_upper and 'U.S.' not in race_name_upper)):
            return ElectionType.STATE_SENATE
        # Check for state house (STATE level + HOUSE, but not U.S. House)
        elif ('STATE HOUSE' in race_name_upper or 
              ('HOUSE OF REPRESENTATIVES' in race_name_upper and 'U.S.' not in race_name_upper) or
              ('HOUSE' in race_name_upper and 'U.S.' not in race_name_upper)):
            return ElectionType.STATE_HOUSE
        elif 'GOVERNOR' in race_name_upper:
            return ElectionType.GOVERNOR
        elif 'ATTORNEY GENERAL' in race_name_upper:
            return ElectionType.ATTORNEY_GENERAL
        elif 'SECRETARY OF STATE' in race_name_upper:
            return ElectionType.SECRETARY_OF_STATE
        elif 'JUDGE' in race_name_upper or 'JUSTICE' in race_name_upper or 'COURT' in race_name_upper:
            return ElectionType.JUDICIAL
        else:
            return ElectionType.OTHER_STATE
    
    return ElectionType.UNKNOWN


def get_election_type_description(election_type: ElectionType) -> str:
    """Get a human-readable description of the election type."""
    return election_type.value


# ============================================================================
# NANDA DATA LOADING AND PROCESSING
# ============================================================================

def load_nanda_data(tsv_path: str = "nanda.tsv", year: Optional[int] = None) -> Dict[str, List[Dict[str, Any]]]:
    """
    Load NANDA dataset and organize by FIPS code.
    
    Args:
        tsv_path: Path to the NANDA TSV file
        year: Optional year to filter data (uses most recent if not specified)
    
    Returns:
        Dictionary mapping FIPS codes to list of records for that FIPS
    """
    if not os.path.exists(tsv_path):
        return {}
    
    nanda_data = defaultdict(list)
    max_year = 0
    
    try:
        with open(tsv_path, 'r', encoding='utf-8') as f:
            reader = csv.DictReader(f, delimiter='\t')
            for row in reader:
                fips = row.get('STCOFIPS10', '').strip()
                year_str = row.get('YEAR', '').strip()
                
                if not fips or not year_str:
                    continue
                
                try:
                    record_year = int(year_str)
                    max_year = max(max_year, record_year)
                    
                    # Filter by year if specified
                    if year and record_year != year:
                        continue
                    
                    nanda_data[fips].append({
                        'year': record_year,
                        'fips': fips,
                        'pres_dem_ratio': _parse_ratio(row.get('PRES_DEM_RATIO', '')),
                        'pres_rep_ratio': _parse_ratio(row.get('PRES_REP_RATIO', '')),
                        'sen_dem_ratio': _parse_ratio(row.get('SEN_DEM_RATIO', '')),
                        'sen_rep_ratio': _parse_ratio(row.get('SEN_REP_RATIO', '')),
                        'partisan_index_dem': _parse_ratio(row.get('PARTISAN_INDEX_DEM', '')),
                        'partisan_index_rep': _parse_ratio(row.get('PARTISAN_INDEX_REP', '')),
                    })
                except (ValueError, TypeError):
                    continue
        
        # If no year specified, use most recent year's data
        if not year and max_year > 0:
            filtered_data = {}
            for fips, records in nanda_data.items():
                latest_record = max(records, key=lambda x: x['year'])
                if latest_record['year'] == max_year:
                    filtered_data[fips] = [latest_record]
            return filtered_data
        
        return dict(nanda_data)
        
    except Exception as e:
        print(f"Error loading NANDA data: {e}")
        return {}


def _parse_ratio(value: str) -> Optional[float]:
    """Parse a ratio value from NANDA data."""
    if not value or value.strip() == '':
        return None
    try:
        return float(value.strip())
    except (ValueError, TypeError):
        return None


# State FIPS codes mapping (shared constant)
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


def calculate_competitiveness_nanda(race_name: str, race_type: ElectionType, 
                                    nanda_data: Dict[str, List[Dict[str, Any]]],
                                    year: Optional[int] = None,
                                    verbose: bool = False) -> float:
    """
    Calculate competitiveness score using NANDA party split data.
    
    Args:
        race_name: Name of the race
        race_type: Type of election
        nanda_data: NANDA data organized by FIPS code
        year: Election year (uses most recent data if not specified)
        verbose: Whether to print debug information
    
    Returns:
        Competitiveness score between 0 and 1 (higher = more competitive)
    """
    # Extract state from race name using parse_race_name
    race_info = parse_race_name(race_name)
    state_abbrev = race_info.get('state')
    if not state_abbrev:
        if verbose:
            print(f"  NANDA: Could not extract state from race name: {race_name}")
        return 0.5  # Default moderate competitiveness
    
    # Get state FIPS code
    state_fips_prefix = STATE_FIPS_MAP.get(state_abbrev)
    if not state_fips_prefix:
        if verbose:
            print(f"  NANDA: Could not find FIPS code for state: {state_abbrev}")
        return 0.5
    
    # Aggregate data for all counties in the state
    state_ratios = []
    
    # Determine which ratio field to use based on race type
    ratio_field = None
    if race_type == ElectionType.US_SENATE or race_type == ElectionType.STATE_SENATE:
        ratio_field = 'sen_dem_ratio'
    elif race_type == ElectionType.US_HOUSE or race_type == ElectionType.STATE_HOUSE:
        ratio_field = 'pres_dem_ratio'  # Use presidential as proxy for House
    else:
        ratio_field = 'pres_dem_ratio'  # Default to presidential
    
    # Collect ratios from all counties in the state
    for fips, records in nanda_data.items():
        if fips.startswith(state_fips_prefix):
            for record in records:
                if year is None or record['year'] == year:
                    ratio = record.get(ratio_field)
                    if ratio is not None:
                        state_ratios.append(ratio)
    
    if not state_ratios:
        if verbose:
            print(f"  NANDA: No data found for {state_abbrev} ({state_fips_prefix}*)")
        return 0.5  # Default moderate competitiveness
    
    # Calculate average party split for the state
    avg_dem_ratio = sum(state_ratios) / len(state_ratios)
    avg_rep_ratio = 1.0 - avg_dem_ratio
    
    # Competitiveness: closer to 50/50 = more competitive
    # Formula: 1 - abs(0.5 - dem_ratio) / 0.5
    # This gives: 50/50 = 1.0, 60/40 = 0.8, 70/30 = 0.6, etc.
    competitiveness = 1.0 - abs(0.5 - avg_dem_ratio) / 0.5
    competitiveness = max(0.0, min(1.0, competitiveness))
    
    if verbose:
        print(f"  NANDA: State {state_abbrev}: Dem {avg_dem_ratio:.1%}, Rep {avg_rep_ratio:.1%}")
        print(f"  NANDA: Competitiveness score: {competitiveness:.3f} (based on {len(state_ratios)} counties)")
    
    return competitiveness


# ============================================================================
# HISTORICAL ELECTION DATA FROM CIVIC ENGINE
# ============================================================================

def get_historical_election_results(race_name: str, position_id: Optional[str] = None, 
                                     years_back: int = 4, verbose: bool = False) -> List[Dict[str, Any]]:
    """
    Get historical election results for a specific race from Civic Engine API.
    
    This function uses a hybrid approach:
    1. Gets past election candidates from GraphQL API
    2. Determines winner by matching to current office holder (for most recent election)
    3. Maps winners to parties using FEC API
    
    Args:
        race_name: Name of the race (e.g., "U.S. House of Representatives - North Carolina 2nd Congressional District")
        position_id: Optional position ID from Civic Engine (not currently used)
        years_back: How many years back to look for historical elections (default: 4)
        verbose: Whether to print debug information
    
    Returns:
        List of historical election results with winner and party information
    """
    # Parse race to get office, state, district
    race_info = parse_race_name(race_name)
    if not race_info['office'] or not race_info['state']:
        if verbose:
            print(f"  Historical: Could not parse race name: {race_name}")
        return []
    
    # Historical data should work for all race types that have positions in Civic Engine
    # No need to restrict to specific office types - let the function try to find the position
    
    # Import the Civic Engine-based historical winners function
    try:
        from get_historical_winners_civicengine import get_historical_winners_civicengine
        
        if verbose:
            print(f"  Historical: Fetching historical winners from Civic Engine API...")
        
        # Get historical winners using Civic Engine API (direct ElectionResult field)
        winners = get_historical_winners_civicengine(race_name, years_back=years_back, verbose=verbose)
        
        if not winners:
            if verbose:
                print(f"  Historical: No winners found from Civic Engine, falling back to NANDA data")
            return []
        
        # Convert to expected format
        results = []
        for winner in winners:
            results.append({
                'year': winner['year'],
                'winner_name': winner['name'],
                'winner_party': winner['party'],
                'method': winner.get('method', 'civicengine_result')
            })
        
        if verbose:
            print(f"  Historical: Found {len(results)} historical winner(s) from Civic Engine")
            for result in results:
                print(f"    - {result['year']}: {result['winner_name']} ({result['winner_party'] or 'Unknown party'})")
        
        return results
        
    except Exception as e:
        if verbose:
            print(f"  Historical: Error fetching historical winners from Civic Engine: {e}")
            print(f"  Historical: Falling back to NANDA data")
        import traceback
        if verbose:
            traceback.print_exc()
        return []


def get_candidate_party_from_fec(candidate_name: str, bioguide_id: Optional[str] = None,
                                  state: Optional[str] = None, district: Optional[int] = None,
                                  cycle: int = 2024, verbose: bool = False) -> Optional[str]:
    """
    Get a candidate's party affiliation from FEC API.
    
    Args:
        candidate_name: Candidate's full name
        bioguide_id: Optional Bioguide ID (not directly used by FEC API, but kept for reference)
        state: State abbreviation
        district: District number (for House races)
        cycle: Election cycle year
        verbose: Whether to print debug information
    
    Returns:
        Party abbreviation (e.g., "DEM", "REP", "IND") or None if not found
    """
    # FEC API search endpoint works better for name-based queries
    search_url = "https://api.open.fec.gov/v1/candidates/search/"
    
    params = {
        'api_key': FEC_TOKEN,
        'per_page': 10,
        'cycle': cycle
    }
    
    # Extract last name from full name (more reliable for FEC search)
    name_parts = candidate_name.split()
    if name_parts:
        last_name = name_parts[-1].upper()
        params['q'] = last_name
    
    # Add state filter if available
    if state:
        params['state'] = state
    
    try:
        response = requests.get(search_url, params=params, timeout=10)
        response.raise_for_status()
        data = response.json()
        
        candidates = data.get('results', [])
        if not candidates:
            # Try previous cycle
            if cycle > 2020:
                return get_candidate_party_from_fec(candidate_name, bioguide_id, state, district, 
                                                     cycle - 2, verbose)
            if verbose:
                print(f"  FEC Party Lookup: No candidates found for {candidate_name}")
            return None
        
        # Try to find best match by name and district
        best_match = None
        for candidate in candidates:
            cand_name = candidate.get('name', '').upper()
            cand_state = candidate.get('state', '')
            cand_district = candidate.get('district', '')
            
            # Check if name matches (last name should match)
            if last_name in cand_name:
                # For House races, check district match
                if district is not None:
                    if cand_district == str(district).zfill(2) and cand_state == state:
                        best_match = candidate
                        break
                elif state and cand_state == state:
                    # For Senate or other races, just match state
                    best_match = candidate
                    break
        
        # If no exact match, use first result
        if not best_match:
            best_match = candidates[0]
            if verbose:
                print(f"  FEC Party Lookup: Using first result for {candidate_name} (may not be exact match)")
        
        # Get party from candidate
        party = best_match.get('party_full', '') or best_match.get('party', '')
        
        if party:
            # Normalize party name
            party_upper = party.upper()
            if 'DEMOCRAT' in party_upper:
                return 'DEM'
            elif 'REPUBLICAN' in party_upper:
                return 'REP'
            elif 'INDEPENDENT' in party_upper or party_upper == 'IND':
                return 'IND'
            elif 'GREEN' in party_upper:
                return 'GRN'
            elif 'LIBERTARIAN' in party_upper:
                return 'LIB'
            else:
                # Return first 3 chars as abbreviation, or full if short
                return party[:3] if len(party) > 3 else party
        
        return None
        
    except Exception as e:
        if verbose:
            print(f"  FEC Party Lookup: Error for {candidate_name}: {e}")
        return None


# Note: get_current_officeholder_winner was removed - we now use get_historical_winners_civicengine
# which directly queries ElectionResult from Civic Engine for more accurate historical data


def calculate_competitiveness_from_historical(race_name: str, race_type: ElectionType,
                                               verbose: bool = False) -> Tuple[float, Dict[str, Any]]:
    """
    Calculate competitiveness score from historical election results.
    
    Uses Civic Engine's ElectionResult field to get historical winners from past elections.
    Calculates competitiveness based on party consistency across multiple election cycles.
    
    Args:
        race_name: Name of the race
        race_type: Type of election
        verbose: Whether to print debug information
    
    Returns:
        Tuple of (competitiveness_score, metadata_dict)
        competitiveness_score: 0-1 score (higher = more competitive)
        metadata_dict: Contains data quality info, historical results, etc.
    """
    metadata = {
        "data_quality": "low",
        "historical_elections_found": 0,
        "method": "civicengine_historical",
        "warnings": [],
        "historical_winners": []
    }
    
    # Get historical election results from Civic Engine
    historical_results = get_historical_election_results(race_name, years_back=6, verbose=verbose)
    
    if not historical_results:
        if verbose:
            print(f"  Historical: No historical results found, falling back to NANDA")
        metadata["warnings"].append("No historical election results available")
        metadata["data_quality"] = "none"
        return 0.5, metadata  # Default moderate competitiveness
    
    metadata["historical_elections_found"] = len(historical_results)
    metadata["historical_winners"] = historical_results
    
    # Calculate competitiveness based on party consistency
    parties = [r.get('winner_party') for r in historical_results if r.get('winner_party')]
    
    if not parties:
        metadata["warnings"].append("No party information in historical results")
        metadata["data_quality"] = "low"
        return 0.5, metadata
    
    # Count unique parties
    unique_parties = set(parties)
    num_elections = len(parties)
    
    if num_elections == 0:
        metadata["data_quality"] = "low"
        return 0.5, metadata
    
    # Competitiveness calculation:
    # - If only one party wins all elections: low competitiveness (0.2-0.4)
    # - If two parties alternate or split: high competitiveness (0.6-0.9)
    # - More elections = more confidence in the score
    
    if len(unique_parties) == 1:
        # Same party wins all elections - safe seat
        competitiveness = 0.3  # Low competitiveness
        if verbose:
            print(f"  Historical: Same party ({parties[0]}) won all {num_elections} election(s) - safe seat")
    elif len(unique_parties) == 2:
        # Two parties - check if they alternate
        # Count transitions (party changes)
        transitions = sum(1 for i in range(1, len(parties)) if parties[i] != parties[i-1])
        transition_ratio = transitions / (len(parties) - 1) if len(parties) > 1 else 0
        
        if transition_ratio > 0.5:
            # Parties alternate frequently - very competitive
            competitiveness = 0.8
            if verbose:
                print(f"  Historical: Party swings detected ({transitions} transitions in {num_elections} elections) - competitive")
        else:
            # Some variation but mostly one party
            competitiveness = 0.5
            if verbose:
                print(f"  Historical: Some party variation ({len(unique_parties)} parties) - moderate competitiveness")
    else:
        # Multiple parties - very competitive
        competitiveness = 0.9
        if verbose:
            print(f"  Historical: Multiple parties ({len(unique_parties)}) - highly competitive")
    
    # Adjust data quality based on number of elections
    if num_elections >= 3:
        metadata["data_quality"] = "high"
    elif num_elections >= 2:
        metadata["data_quality"] = "medium"
    else:
        metadata["data_quality"] = "low"
        metadata["warnings"].append("Limited historical data - only one election cycle")
    
    metadata["num_elections"] = num_elections
    metadata["unique_parties"] = list(unique_parties)
    metadata["competitiveness"] = competitiveness
    
    if verbose:
        print(f"  Historical: Competitiveness score: {competitiveness:.3f} (based on {num_elections} election(s))")
    
    return competitiveness, metadata


# ============================================================================
# KALSHI API INTEGRATION
# ============================================================================

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

def validate_kalshi_market_match(market_series: Dict[str, Any], race_name: str, 
                                  election_year: Optional[int] = None, 
                                  verbose: bool = False) -> Tuple[bool, float, List[str]]:
    """
    Validate that a Kalshi market series matches the race we're looking for.
    
    Args:
        market_series: Market series from Kalshi API
        race_name: Race name we're looking for
        election_year: Expected election year (optional)
        verbose: Whether to print debug info
    
    Returns:
        Tuple of (is_valid, match_score, warnings)
        - is_valid: True if market is a good match
        - match_score: 0-1 score indicating match quality
        - warnings: List of warnings about the match
    """
    warnings = []
    match_score = 0.0
    
    if not market_series:
        return False, 0.0, ["No market series provided"]
    
    # Extract market info (Kalshi uses different field names)
    # Keep ticker in original case for matching (it's usually uppercase like "HOUSETN7S")
    market_title = (market_series.get('series_title', '') or market_series.get('event_title', '') or '').lower()
    market_subtitle = (market_series.get('event_subtitle', '') or '').lower()
    market_ticker_orig = market_series.get('series_ticker', '') or market_series.get('event_ticker', '') or ''
    market_ticker = market_ticker_orig.lower()  # For case-insensitive matching
    market_ticker_upper = market_ticker_orig.upper()  # For uppercase matching (e.g., "HOUSETN7S")
    
    # Parse race info
    race_info = parse_race_name(race_name)
    race_lower = race_name.lower()
    
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
        
        # Check state match - look for state abbreviation or full name
        state_lower = state.lower()
        state_full_lower = state_full.lower()
        state_upper = state.upper()
        if (state_lower in market_title or state_lower in market_ticker or 
            state_full_lower in market_title or state_upper in market_ticker_upper):
            state_match = True
            match_score += 0.3
        else:
            warnings.append(f"State mismatch: looking for {race_info['state']}, market may be for different state")
    
    # Check office type match
    office_match = False
    if race_info.get('office') == 'H':
        # Look for HOUSE in ticker (e.g., HOUSETN7S) or 'house' in title
        if ('house' in market_title or 'HOUSE' in market_ticker_upper or 
            market_ticker_upper.startswith('HOUSE') or 'h-' in market_ticker):
            office_match = True
            match_score += 0.3
        else:
            warnings.append("Office type mismatch: looking for House, market may be for different office")
    elif race_info.get('office') == 'S':
        # Look for SENATE in ticker or 'senate' in title
        if ('senate' in market_title or 'SENATE' in market_ticker_upper or 
            market_ticker_upper.startswith('SENATE') or 's-' in market_ticker):
            office_match = True
            match_score += 0.3
        else:
            warnings.append("Office type mismatch: looking for Senate, market may be for different office")
    
    # Check district match (for House races)
    district_match = False
    if race_info.get('office') == 'H' and race_info.get('district'):
        district = race_info['district']
        # Check if district number appears in market (e.g., HOUSETN7S or TN 7)
        district_str = str(district)
        # Look for district in ticker (e.g., HOUSETN7S has 7) or title (e.g., "TN 7")
        if (district_str in market_title or district_str in market_ticker or 
            f"-{district:02d}" in market_ticker or f"{district:02d}" in market_ticker):
            district_match = True
            match_score += 0.2
        else:
            warnings.append(f"District mismatch: looking for district {district}, market may be for different district")
    
    # Check year match
    year_match = False
    if election_year:
        year_str = str(election_year)
        if year_str in market_title or year_str in market_ticker:
            year_match = True
            match_score += 0.2
        else:
            # Check if it's close (within 2 years)
            year_matches = re.findall(r'\b(20\d{2})\b', market_title + ' ' + market_ticker)
            if year_matches:
                market_year = int(year_matches[0])
                year_diff = abs(market_year - election_year)
                if year_diff <= 2:
                    year_match = True
                    match_score += 0.1
                    warnings.append(f"Year mismatch: looking for {election_year}, market is for {market_year} (using anyway)")
                else:
                    warnings.append(f"Year mismatch: looking for {election_year}, market is for {market_year}")
            else:
                warnings.append(f"Year not found in market: looking for {election_year}")
    
    # Determine if match is valid
    # Need at least state and office match, and district match for House
    is_valid = state_match and office_match
    if race_info.get('office') == 'H' and race_info.get('district'):
        is_valid = is_valid and district_match
    
    # Lower threshold for validity if year is close
    if not is_valid and state_match and office_match:
        if year_match or not election_year:  # If year matches or not specified, be more lenient
            is_valid = True
            warnings.append("Using market despite some mismatches (state and office match)")
    
    if verbose:
        if is_valid:
            print(f"  ✓ Market validation: GOOD MATCH (score: {match_score:.2f})")
        else:
            print(f"  ✗ Market validation: POOR MATCH (score: {match_score:.2f})")
        if warnings:
            for warning in warnings:
                print(f"    ⚠️  {warning}")
    
    return is_valid, match_score, warnings


def get_kalshi_market(race_name, election_year: Optional[int] = None, verbose: bool = False):
    """
    Searches the Kalshi API for a given race and validates the match.
    Returns the best matching series or None.
    
    Args:
        race_name: Race name to search for
        election_year: Expected election year (optional, for validation)
        verbose: Whether to print validation info
    
    Returns:
        Best matching market series or None, along with validation info
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
        
        # Get all search results
        all_series = []
        
        # Handle different possible response structures
        if 'current_page' in data and data['current_page']:
            all_series = data['current_page']
        elif 'series' in data and data['series']:
            all_series = data['series']
        elif isinstance(data, list):
            all_series = data
        
        if not all_series:
            if verbose:
                print(f"  Kalshi: No markets found for '{race_name}'")
            return None
        
        if verbose:
            print(f"  Kalshi: Found {len(all_series)} market series")
        
        # Validate and score each series (without verbose output for each)
        scored_series = []
        for series in all_series:
            if 'markets' not in series or not series.get('markets'):
                continue
            
            # Validate without verbose output (we'll only show final result)
            is_valid, match_score, warnings = validate_kalshi_market_match(
                series, race_name, election_year, verbose=False
            )
            
            scored_series.append({
                'series': series,
                'is_valid': is_valid,
                'match_score': match_score,
                'warnings': warnings
            })
        
        if not scored_series:
            if verbose:
                print(f"  Kalshi: No valid markets found (all lacked market data)")
            return None
        
        # Sort by match score (highest first), prioritize valid matches
        scored_series.sort(key=lambda x: (x['is_valid'], x['match_score']), reverse=True)
        
        # Get best match
        best_match = scored_series[0]
        
        # Only print validation result (good match or not)
        if verbose:
            market_title_display = (best_match['series'].get('series_title') or 
                                   best_match['series'].get('event_title') or 
                                   best_match['series'].get('series_ticker', 'Unknown'))
            if best_match['is_valid']:
                print(f"  ✓ Kalshi: Found good match - {market_title_display} (score: {best_match['match_score']:.2f})")
            else:
                print(f"  ⚠️  Kalshi: Poor match found - {market_title_display} (score: {best_match['match_score']:.2f})")
                # Only show warnings if it's a poor match
                if best_match['warnings']:
                    for warning in best_match['warnings'][:3]:  # Limit to first 3 warnings
                        print(f"    - {warning}")
                    if len(best_match['warnings']) > 3:
                        print(f"    ... and {len(best_match['warnings']) - 3} more warnings")
        
        # Return best match if it's valid or if it's the best we have
        # Include validation info in the series for later use
        best_series = best_match['series']
        best_series['_validation'] = {
            'is_valid': best_match['is_valid'],
            'match_score': best_match['match_score'],
            'warnings': best_match['warnings']
        }
        
        return best_series
        
    except requests.RequestException as e:
        if verbose:
            print(f"  Kalshi API error for '{race_name}': {e}")
    except (KeyError, IndexError, TypeError) as e:
        if verbose:
            print(f"  Kalshi API response parsing error for '{race_name}': {e}")
    except Exception as e:
        if verbose:
            print(f"  Unexpected error querying Kalshi for '{race_name}': {e}")

    return None

def calculate_competitiveness_general(price):
    """Calculates competitiveness for a binary (Rep vs Dem) market."""
    price = max(1, min(99, price)) # Clamp price to 1-99
    return (1 - abs(price - 50) / 50)

def calculate_competitiveness_primary(markets):
    """
    Calculates competitiveness for a multi-candidate primary using entropy-based measure.
    
    Uses entropy: -Σ(p_i * log(p_i)) where p_i is the probability/price of candidate i.
    Higher entropy = more competitive (more evenly distributed probabilities).
    
    Also considers:
    - Number of candidates (more candidates = potentially more competitive due to vote splitting)
    - Gap between top candidates (smaller gap = more competitive)
    
    Args:
        markets: List of market dictionaries for each candidate
    
    Returns:
        Competitiveness score between 0 and 1 (higher = more competitive)
    """
    if not markets or len(markets) < 2:
        return 0.0
    
    # Try to get prices from various possible fields
    prices = []
    for m in markets:
        price = m.get('last_price') or m.get('yes_bid') or m.get('yes_ask')
        if price is not None:
            prices.append(price)
    
    if len(prices) < 2:
        # Not enough price data - estimate from available data
        if len(prices) == 1:
            # Only one candidate has price data - use that to estimate
            # If one candidate is heavily favored (high price), less competitive
            single_price = prices[0]
            if single_price > 100:
                single_price = single_price / 100
            # Inverse relationship: higher price = less competitive
            return max(0.1, min(0.9, 1 - (single_price / 100)))
        else:
            # No price data at all - can't calculate competitiveness
            # Return moderate score instead of arbitrary 0.3
            # This indicates uncertainty rather than a specific competitiveness level
            return 0.5  # Moderate/unknown competitiveness
    
    # Normalize prices to 0-100 range if needed and calculate probabilities
    normalized_prices = []
    for p in prices:
        if p > 100:
            p = p / 100
        normalized_prices.append(max(0.01, min(99, p)))  # Clamp to avoid log(0)
    
    # Calculate entropy-based competitiveness
    # Higher entropy = more evenly distributed = more competitive
    total = sum(normalized_prices)
    if total == 0:
        return 0.5  # Can't determine
    
    # Normalize to probabilities
    probabilities = [p / total for p in normalized_prices]
    
    # Calculate entropy: -Σ(p_i * log(p_i))
    # Maximum entropy occurs when all probabilities are equal
    entropy = 0.0
    for p in probabilities:
        if p > 0:
            entropy -= p * math.log(p)
    
    # Normalize entropy to 0-1 range
    # Maximum entropy for n candidates is log(n)
    max_entropy = math.log(len(probabilities))
    entropy_score = entropy / max_entropy if max_entropy > 0 else 0.0
    
    # Also consider gap between top 2 candidates
    sorted_prices = sorted(normalized_prices, reverse=True)
    p1, p2 = sorted_prices[0], sorted_prices[1]
    gap_score = 1 - ((p1 - p2) / 100)  # Smaller gap = higher score
    gap_score = max(0.0, min(1.0, gap_score))
    
    # Combine entropy and gap scores
    # Weight entropy more heavily (60%) since it considers all candidates
    # Weight gap score less (40%) since it only considers top 2
    competitiveness = 0.6 * entropy_score + 0.4 * gap_score
    
    # Adjust for number of candidates (more candidates = potentially more competitive)
    num_candidates = len(markets)
    if num_candidates > 3:
        # Boost competitiveness slightly for races with many candidates (vote splitting)
        competitiveness = min(1.0, competitiveness * 1.1)
    
    return max(0.0, min(1.0, competitiveness))

# ============================================================================
# FEC API INTEGRATION
# ============================================================================

# State name to abbreviation mapping (shared constant)
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

def parse_race_name(race_name):
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
        
        # Add retry logic for transient failures
        max_retries = 3
        retry_delay = 1  # Start with 1 second
        
        for attempt in range(max_retries):
            try:
                response = requests.get(base_url, params=params, timeout=10)
                
                # Handle rate limiting (429)
                if response.status_code == 429:
                    if attempt < max_retries - 1:
                        wait_time = retry_delay * (2 ** attempt)  # Exponential backoff
                        if verbose:
                            print(f"  FEC: Rate limited (cycle {check_cycle}), waiting {wait_time}s before retry {attempt + 1}/{max_retries}")
                        import time
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
                    
                    # Try to get totals for this candidate across multiple cycles
                    max_receipts = 0.0
                    for total_cycle in cycles_to_check:
                        totals_url = f"https://api.open.fec.gov/v1/candidate/{candidate_id}/totals/"
                        totals_params = {
                            'api_key': FEC_TOKEN,
                            'cycle': total_cycle,
                            'per_page': 100  # Get all totals for this cycle
                        }
                        
                        # Retry logic for totals endpoint too
                        for totals_attempt in range(max_retries):
                            try:
                                totals_response = requests.get(totals_url, params=totals_params, timeout=10)
                                
                                if totals_response.status_code == 429:
                                    if totals_attempt < max_retries - 1:
                                        wait_time = retry_delay * (2 ** totals_attempt)
                                        import time
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
                                break  # Success, exit retry loop
                            except requests.RequestException as totals_e:
                                if totals_attempt < max_retries - 1:
                                    # Retry with exponential backoff
                                    wait_time = retry_delay * (2 ** totals_attempt)
                                    import time
                                    time.sleep(wait_time)
                                else:
                                    # Last attempt failed, skip this cycle
                                    if verbose:
                                        print(f"  FEC: Could not get totals for {candidate_id} cycle {total_cycle} after {max_retries} attempts: {totals_e}")
                                    continue
                    
                    if max_receipts > 0:
                        total_receipts += max_receipts
                        if verbose:
                            print(f"  FEC: Candidate {candidate_id}: ${max_receipts:,.0f}")
                
                # If we got data (even if empty), break out of retry loop
                break
                
            except requests.RequestException as e:
                if attempt < max_retries - 1:
                    # Retry with exponential backoff
                    wait_time = retry_delay * (2 ** attempt)
                    if verbose:
                        print(f"  FEC: Request error for cycle {check_cycle} (attempt {attempt + 1}/{max_retries}), retrying in {wait_time}s: {e}")
                    import time
                    time.sleep(wait_time)
                else:
                    # Last attempt failed
                    if verbose:
                        print(f"  FEC API error for cycle {check_cycle} after {max_retries} attempts: {e}")
                    # Continue to next cycle instead of returning 0
                    continue
            except (KeyError, ValueError, TypeError) as e:
                if verbose:
                    print(f"  FEC API parsing error for cycle {check_cycle}: {e}")
                # Don't retry on parsing errors
                break
    
    if verbose and total_receipts > 0:
        print(f"  FEC: Total receipts: ${total_receipts:,.0f}")
    
    return total_receipts


def calculate_saturation_fec(race_name: str, cycle: int = 2024, verbose: bool = False) -> Tuple[float, Dict[str, Any]]:
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
        Tuple of (saturation_score, metadata_dict)
        saturation_score: 0-1 score (higher = less saturated)
        metadata_dict: Contains data quality info, warnings, error flags, etc.
    """
    metadata = {
        "data_quality": "high",
        "method": "fec",
        "cycle": cycle,
        "warnings": [],
        "error": None,
        "total_receipts": 0.0
    }
    
    # Parse race name to get office, state, district
    race_info = parse_race_name(race_name)
    
    if not race_info['office'] or not race_info['state']:
        # Can't parse race, return default moderate score
        if verbose:
            print(f"  FEC: Could not parse race name: {race_name}")
        metadata["data_quality"] = "low"
        metadata["warnings"].append("Could not parse race name")
        default_score = 1 / math.log(1 + 10_000_000)  # Default to $10M equivalent
        return default_score, metadata
    
    if verbose:
        print(f"  FEC: Querying {race_info['office']} race in {race_info['state']}" + 
              (f" District {race_info['district']}" if race_info['district'] else ""))
    
    # Get total receipts for the race (with retry logic built in)
    try:
        total_receipts = get_fec_candidates_total_receipts(
            office=race_info['office'],
            state=race_info['state'],
            district=race_info.get('district'),
            cycle=cycle,
            verbose=verbose
        )
        metadata["total_receipts"] = total_receipts
    except Exception as e:
        # API error - distinguish from "no data"
        metadata["error"] = str(e)
        metadata["data_quality"] = "none"
        metadata["warnings"].append(f"FEC API error: {e}")
        if verbose:
            print(f"  FEC: Error querying FEC API: {e}")
        # Return conservative default instead of treating as "no fundraising"
        return 0.5, metadata  # Conservative default
    
    if total_receipts == 0:
        # No fundraising data found - could be legitimate (no candidates) or error
        # Check if we're in a valid cycle to distinguish
        from datetime import date
        current_year = date.today().year
        if cycle > current_year:
            metadata["warnings"].append(f"Future cycle {cycle} - data may not exist yet")
            metadata["data_quality"] = "low"
        elif cycle < 2018:
            metadata["warnings"].append(f"Old cycle {cycle} - data may be incomplete")
            metadata["data_quality"] = "low"
        
        # Treat as low saturation (no fundraising yet)
        if verbose:
            print(f"  FEC: No fundraising data found, treating as low saturation")
        metadata["warnings"].append("No fundraising data found - may indicate no candidates or incomplete data")
        return 1.0, metadata
    
    # Calculate saturation score: inverse log relationship
    # Using log ensures diminishing returns and prevents extreme values
    saturation_score = 1 / math.log(1 + total_receipts)
    
    # Normalize to reasonable range (clamp between 0.05 and 1.0)
    saturation_score = max(0.05, min(1.0, saturation_score))
    
    if verbose:
        print(f"  FEC: Saturation score: {saturation_score:.3f} (receipts: ${total_receipts:,.0f})")
    
    return saturation_score, metadata

# ============================================================================
# Note: OCPF (Massachusetts campaign finance) data has been removed.
# All state races now use Kalshi proxy for saturation scoring.


# ============================================================================
# SATURATION CALCULATION HELPERS
# ============================================================================

def calculate_saturation_kalshi(volume, spread, verbose: bool = False) -> Tuple[float, Dict[str, Any]]:
    """
    Uses Kalshi's own metrics as a proxy for saturation/attention.
    
    Args:
        volume: Market volume
        spread: Bid-ask spread
        verbose: Whether to print debug information
    
    Returns:
        Tuple of (saturation_score, metadata_dict)
        saturation_score: 0-1 score (higher = less saturated)
        metadata_dict: Contains data quality info, warnings, etc.
    """
    metadata = {
        "data_quality": "medium",
        "method": "kalshi_proxy",
        "warnings": [],
        "volume": volume,
        "spread": spread
    }
    
    # Use the advanced formula: (log(spread)) / (log(volume))
    # This rewards *inefficient* (high spread) and *low attention* (low volume) markets
    spread = max(1, spread)
    volume = max(2, volume) # Avoid log(1) or log(0)
    
    # We normalize to prevent skewed scores
    spread_score = math.log(1 + spread)
    volume_penalty = math.log(1 + volume)
    
    saturation_score = spread_score / volume_penalty
    
    # Normalize to 0-1 range (clamp between 0.05 and 1.0)
    saturation_score = max(0.05, min(1.0, saturation_score))
    
    # Add warnings for low data quality
    if volume < 10:
        metadata["warnings"].append("Low Kalshi market volume - saturation score may be unreliable")
        metadata["data_quality"] = "low"
    elif volume < 100:
        metadata["warnings"].append("Moderate Kalshi market volume - saturation score may be less reliable")
        metadata["data_quality"] = "medium"
    else:
        metadata["data_quality"] = "high"
    
    if verbose:
        if metadata["warnings"]:
            for warning in metadata["warnings"]:
                print(f"  ⚠️  {warning}")
    
    return saturation_score, metadata

# ============================================================================
# CIVIC ENGINE API INTEGRATION
# ============================================================================

def get_civic_engine_races(max_months_ahead: Optional[int] = 18, filter_past: bool = True):
    """
    Fetches current state and federal elections from Civic Engine API
    and returns a list of individual races with classification.
    
    Args:
        max_months_ahead: Maximum months into the future to include races (default: 18)
                         None = no limit
        filter_past: Whether to filter out past elections (default: True)
    
    Returns:
        List of race dictionaries with classification and metadata
    """
    try:
        # Get elections from Civic Engine API (verbose=False to reduce output)
        elections_dict = get_current_state_federal_elections(max_elections=100, verbose=False)
        
        # Extract individual races from elections
        races = []
        today = datetime.now().date()
        
        for election_id, election_data in elections_dict.items():
            election_day = election_data.get('electionDay', '')
            
            # Parse election date
            try:
                if election_day:
                    election_date = datetime.strptime(election_day, '%Y-%m-%d').date()
                else:
                    election_date = None
            except (ValueError, TypeError):
                election_date = None
            
            # Filter by date if specified
            if filter_past and election_date and election_date < today:
                continue  # Skip past elections
            
            if max_months_ahead and election_date:
                months_ahead = (election_date.year - today.year) * 12 + (election_date.month - today.month)
                if months_ahead > max_months_ahead:
                    continue  # Skip races too far in the future
            
            for race in election_data.get('races', []):
                position = race.get('position', {})
                race_name = position.get('name', '')
                race_level = position.get('level', '')
                
                if race_name and race_level in ['STATE', 'FEDERAL']:
                    # Classify election type
                    election_type = classify_election_type(race_name, race_level)
                    
                    # Calculate days until election for prioritization
                    days_until = None
                    if election_date:
                        days_until = (election_date - today).days
                    
                    races.append({
                        'name': race_name,
                        'level': race_level,
                        'day': election_day,
                        'election_name': election_data.get('name', ''),
                        'race_id': race.get('id', ''),
                        'election_type': election_type,
                        'election_type_desc': get_election_type_description(election_type),
                        'days_until': days_until,
                        'election_date': election_date.isoformat() if election_date else None
                    })
        
        print(f"Fetched {len(races)} state/federal races from Civic Engine API")
        return races
    except Exception as e:
        print(f"Error fetching data from Civic Engine API: {e}")
        print("Falling back to empty list")
        return []

# ============================================================================
# MAIN PROCESSING PIPELINE
# ============================================================================

def process_races(max_races=None, verbose=True, nanda_year: Optional[int] = None,
                  max_months_ahead: Optional[int] = 18, filter_past: bool = True):
    """
    Main function to process all races and generate a ranked list.
    
    Args:
        max_races: Maximum number of races to process (None for all)
        verbose: Whether to print progress during processing
        nanda_year: Year to use for NANDA data (uses most recent if None)
        max_months_ahead: Maximum months into the future to include races (default: 18)
        filter_past: Whether to filter out past elections (default: True)
    """
    # Load NANDA data once for all races
    if verbose:
        print("Loading NANDA dataset...")
    nanda_data = load_nanda_data(year=nanda_year)
    if verbose:
        print(f"Loaded NANDA data: {len(nanda_data)} FIPS codes")
    
    # Get races from Civic Engine API (with date filtering)
    races = get_civic_engine_races(max_months_ahead=max_months_ahead, filter_past=filter_past)
    
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
        election_type = race.get('election_type', ElectionType.UNKNOWN)
        election_type_desc = race.get('election_type_desc', 'Unknown')
        
        if verbose:
            print(f"\n[{i}/{len(races)}] Processing: {race_name} ({race_level})")
            print(f"  Type: {election_type_desc}")
        
        # This will hold the scores
        scores = {
            'name': race_name,
            'level': race_level,
            'day': election_day,
            'election_type': election_type_desc,
            'source': '',
            'comp_score': 0,
            'sat_score': 0,
            'leverage_score': 0
        }
        
        # Determine election year for data matching
        try:
            election_year = int(election_day.split('-')[0]) if election_day else None
        except (ValueError, AttributeError):
            election_year = None

        # --- TIER 1: ATTEMPT KALSHI ---
        market_series = get_kalshi_market(race_name, election_year=election_year, verbose=verbose)

        if market_series and 'markets' in market_series:
            scores['source'] = 'Kalshi'
            markets = market_series.get('markets', [])
            
            # Get validation info if available
            validation_info = market_series.get('_validation', {})
            if validation_info:
                scores['kalshi_validation'] = {
                    'is_valid': validation_info.get('is_valid', True),
                    'match_score': validation_info.get('match_score', 1.0),
                    'warnings': validation_info.get('warnings', [])
                }
                # Add validation warnings to comp_warnings
                if not scores.get('comp_warnings'):
                    scores['comp_warnings'] = []
                scores['comp_warnings'].extend(validation_info.get('warnings', []))
            
            if markets:
                # 1. Calculate Competitiveness
                try:
                    # Get market volume for data quality assessment
                    market_volume = market_series.get('total_series_volume', 0) or 0
                    
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
                    
                    # Set competitiveness data quality based on market volume
                    if market_volume < 10:
                        scores['comp_data_quality'] = 'low'
                        scores['comp_warnings'] = ['Low Kalshi market volume - competitiveness may be unreliable']
                    elif market_volume < 100:
                        scores['comp_data_quality'] = 'medium'
                    else:
                        scores['comp_data_quality'] = 'high'
                    
                    scores.setdefault('comp_warnings', [])

                    # 2. Calculate Saturation
                    if race_level == 'FEDERAL':
                        # Federal races always use FEC data
                        # Determine cycle from election year using improved calculation
                        try:
                            from datetime import date
                            current_year = date.today().year
                            cycle_year = election_year if election_year else current_year
                            
                            # FEC cycles are 2-year periods ending in even years
                            if cycle_year % 2 == 0:
                                cycle = cycle_year  # Even year = cycle year
                            else:
                                cycle = cycle_year - 1  # Odd year = previous even year cycle
                            
                            # Validate cycle is reasonable
                            if cycle > current_year:
                                # Future cycle, use most recent completed cycle
                                if current_year % 2 == 0:
                                    cycle = current_year
                                else:
                                    cycle = current_year - 1
                            
                            if cycle < 2018:
                                cycle = 2024  # Default to 2024 cycle
                                
                        except (ValueError, AttributeError):
                            cycle = 2024
                        
                        sat_score, sat_metadata = calculate_saturation_fec(race_name, cycle=cycle, verbose=verbose)
                        scores['sat_score'] = sat_score
                        scores['source'] += " + FEC"
                        scores['sat_data_quality'] = sat_metadata.get('data_quality', 'high')
                        scores['sat_warnings'] = sat_metadata.get('warnings', [])
                        scores['fec_cycle'] = cycle  # Store cycle for reference
                        if sat_metadata.get('error'):
                            scores['sat_warnings'].append(f"FEC API error: {sat_metadata['error']}")
                        if verbose:
                            print(f"  FEC: Using cycle {cycle} for election year {election_year}")
                    else:
                        # State races: Use Kalshi proxy for all states
                        volume = market_series.get('total_series_volume', 0) or 0
                        sat_score, sat_metadata = calculate_saturation_kalshi(volume, spread, verbose=verbose)
                        scores['sat_score'] = sat_score
                        scores['sat_data_quality'] = sat_metadata.get('data_quality', 'medium')
                        scores['sat_warnings'] = sat_metadata.get('warnings', [])
                        scores['sat_method'] = 'kalshi_proxy'  # Mark as proxy method
                        scores['source'] += " + Kalshi (proxy: using market volume/spread as estimate)"
                        if sat_metadata.get('warnings'):
                            scores['sat_warnings'] = sat_metadata['warnings']
                        # Add explanation to warnings if not already present
                        if 'Kalshi market volume/spread used as proxy' not in str(scores['sat_warnings']):
                            scores['sat_warnings'].insert(0, 'Kalshi market volume/spread used as proxy for campaign finance data (not actual fundraising data)')
                        
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
            
            # 1. Calculate Competitiveness
            # Try historical data first for all race types (more accurate than NANDA when available)
            # Historical data works for any race type that has positions in Civic Engine
            nanda_fallback = False
            try:
                comp_score, comp_metadata = calculate_competitiveness_from_historical(
                    race_name, election_type, verbose=verbose
                )
                
                # Only use historical data if we got actual results (not just default/fallback)
                if comp_metadata.get('historical_elections_found', 0) > 0:
                    scores['comp_score'] = comp_score
                    scores['comp_data_quality'] = comp_metadata.get('data_quality', 'low')
                    scores['comp_warnings'] = comp_metadata.get('warnings', [])
                    scores['source'] += " + Historical"
                    if verbose:
                        print(f"  ✓ Using historical data for competitiveness: {scores['comp_score']:.3f}")
                        if comp_metadata.get('warnings'):
                            for warning in comp_metadata['warnings']:
                                print(f"  ⚠️  {warning}")
                    # Skip fallback to NANDA since we have historical data
                    nanda_fallback = False
                else:
                    # No historical data found, fall back to NANDA
                    nanda_fallback = True
                    if verbose:
                        print(f"  → No historical data available, falling back to NANDA")
            except Exception as e:
                if verbose:
                    print(f"  ✗ Error calculating historical competitiveness: {e}")
                nanda_fallback = True
            
            # Fall back to NANDA if historical data wasn't available
            if nanda_fallback:
                if nanda_data:
                    try:
                        scores['comp_score'] = calculate_competitiveness_nanda(
                            race_name, 
                            election_type, 
                            nanda_data, 
                            year=election_year,
                            verbose=verbose
                        )
                        scores['source'] += " + NANDA"
                        scores['comp_data_quality'] = 'medium'
                        if not scores.get('comp_warnings'):
                            scores['comp_warnings'] = []
                        scores['comp_warnings'].append('Using state-level NANDA data (not district-specific)')
                        if verbose:
                            print(f"  ✓ Using NANDA for competitiveness: {scores['comp_score']:.3f}")
                    except Exception as e2:
                        if verbose:
                            print(f"  ✗ Error calculating NANDA competitiveness: {e2}")
                        scores['comp_score'] = 0.5
                        scores['comp_data_quality'] = 'low'
                        scores['comp_warnings'] = ['No competitiveness data available']
                else:
                    scores['comp_score'] = 0.5
                    scores['comp_data_quality'] = 'low'
                    scores['comp_warnings'] = ['No competitiveness data available']
                    if verbose:
                        print(f"  → No NANDA data available, using default competitiveness")
            
            # 2. Calculate Saturation
            if race_level == 'FEDERAL':
                # Determine cycle from election year using improved calculation
                try:
                    from datetime import date
                    current_year = date.today().year
                    cycle_year = election_year if election_year else current_year
                    
                    # FEC cycles are 2-year periods ending in even years
                    if cycle_year % 2 == 0:
                        cycle = cycle_year  # Even year = cycle year
                    else:
                        cycle = cycle_year - 1  # Odd year = previous even year cycle
                    
                    # Validate cycle is reasonable
                    if cycle > current_year:
                        # Future cycle, use most recent completed cycle
                        if current_year % 2 == 0:
                            cycle = current_year
                        else:
                            cycle = current_year - 1
                    
                    if cycle < 2018:
                        cycle = 2024  # Default to 2024 cycle
                        if verbose:
                            print(f"  FEC: Election year {cycle_year} too old, using default cycle {cycle}")
                            
                except (ValueError, AttributeError):
                    cycle = 2024
                
                sat_score, sat_metadata = calculate_saturation_fec(race_name, cycle=cycle, verbose=verbose)
                scores['sat_score'] = sat_score
                scores['source'] += " + FEC"
                scores['sat_data_quality'] = sat_metadata.get('data_quality', 'high')
                scores['sat_warnings'] = sat_metadata.get('warnings', [])
                scores['fec_cycle'] = cycle  # Store cycle for reference
                if sat_metadata.get('error'):
                    scores['sat_warnings'].append(f"FEC API error: {sat_metadata['error']}")
                if verbose:
                    print(f"  FEC: Using cycle {cycle} for election year {election_year}")
            else:
                # State races: No Kalshi market = no saturation data available
                scores['sat_score'] = None  # Mark as unavailable
                scores['sat_data_quality'] = 'none'
                scores['sat_warnings'] = ['No saturation data available - Kalshi market not found']
                if verbose:
                    print(f"  ⚠️  No saturation data available for state race (no Kalshi market)")
                
            if verbose:
                data_sources = []
                if 'NANDA' in scores['source']:
                    data_sources.append("NANDA (competitiveness)")
                if 'FEC' in scores['source']:
                    data_sources.append(scores['source'].split(' + ')[-1] + " (saturation)")
                if not data_sources:
                    data_sources.append("Defaults")
                print(f"  → Data sources: {', '.join(data_sources)}")

        # --- FINAL LEVERAGE SCORE ---
        # We also add an Impact_Score (Federal/State > Local)
        impact_score = 1.0 if race_level == 'FEDERAL' else 0.8
        
        # Handle missing saturation score (state races without Kalshi)
        sat_score = scores.get('sat_score')
        if sat_score is None:
            # If no saturation data, exclude from ranking or use a default
            # For now, we'll use a moderate default but flag it
            sat_score = 0.5
            if 'sat_warnings' not in scores:
                scores['sat_warnings'] = []
            scores['sat_warnings'].append('Using default saturation (no data available)')
        
        scores['leverage_score'] = (
            scores['comp_score'] * sat_score * impact_score
        )
        
        # Store data quality info
        scores.setdefault('comp_data_quality', 'unknown')
        scores.setdefault('sat_data_quality', 'unknown')
        scores.setdefault('comp_warnings', [])
        scores.setdefault('sat_warnings', [])
        
        # Add days until election for prioritization
        if race.get('days_until') is not None:
            days_until = race['days_until']
            # Adjust leverage score based on time until election (sooner = slightly higher weight)
            # Races within 90 days get 10% boost, races within 180 days get 5% boost
            if days_until >= 0:
                if days_until <= 90:
                    scores['leverage_score'] *= 1.1  # 10% boost for upcoming races
                    scores['time_priority'] = 'immediate'
                elif days_until <= 180:
                    scores['leverage_score'] *= 1.05  # 5% boost for near-term races
                    scores['time_priority'] = 'near-term'
                elif days_until > 730:  # More than 2 years away
                    scores['time_priority'] = 'long-term'
                    # Flag as low confidence due to distant date
                    if 'comp_warnings' not in scores:
                        scores['comp_warnings'] = []
                    scores['comp_warnings'].append(f"Election is {days_until} days away - data may be incomplete")
                    if scores.get('comp_data_quality') == 'high':
                        scores['comp_data_quality'] = 'low'
                else:
                    scores['time_priority'] = 'medium-term'
        
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
        print(f"  Type: {r.get('election_type', 'Unknown')}")
        print(f"  Election Day: {r.get('day', 'N/A')}")
        
        # Show time until election if available
        if r.get('days_until') is not None:
            days_until = r['days_until']
            if days_until < 0:
                print(f"  ⚠️  Election Date: {days_until} days ago (past election)")
            elif days_until <= 90:
                print(f"  🚨 Election in {days_until} days (IMMEDIATE)")
            elif days_until <= 180:
                print(f"  ⏰ Election in {days_until} days (NEAR-TERM)")
            elif days_until <= 365:
                print(f"  📅 Election in {days_until} days")
            else:
                months_away = days_until // 30
                print(f"  📅 Election in ~{months_away} months ({days_until} days)")
        
        print(f"  Leverage Score: {r['leverage_score']:.3f}")
        print(f"  Data Sources: {r['source']}")
        print(f"    > Competitiveness: {r['comp_score']:.3f} (quality: {r.get('comp_data_quality', 'unknown')})")
        
        # Show saturation score with data quality and warnings
        sat_score = r.get('sat_score')
        sat_method = r.get('sat_method', '')
        if sat_score is not None:
            method_note = ""
            if sat_method == 'kalshi_proxy':
                method_note = " [Kalshi proxy - not actual finance data]"
            print(f"    > Saturation: {sat_score:.3f} (quality: {r.get('sat_data_quality', 'unknown')}){method_note}")
        else:
            print(f"    > Saturation: N/A (no data available)")
        
        # Show data source explanation
        source_parts = r.get('source', '').split(' + ')
        if 'Kalshi (proxy' in r.get('source', ''):
            print(f"    📊 Note: State race saturation uses Kalshi market activity (volume/spread) as a proxy")
            print(f"       for actual campaign finance data. This estimates saturation based on market attention,")
            print(f"       not real fundraising amounts.")
        
        # Show Kalshi validation info if available
        kalshi_validation = r.get('kalshi_validation', {})
        if kalshi_validation:
            is_valid = kalshi_validation.get('is_valid', True)
            match_score = kalshi_validation.get('match_score', 1.0)
            validation_warnings = kalshi_validation.get('warnings', [])
            
            if is_valid:
                print(f"    ✓ Kalshi Market Validation: GOOD MATCH (score: {match_score:.2f})")
            else:
                print(f"    ⚠️  Kalshi Market Validation: POOR MATCH (score: {match_score:.2f})")
            
            if validation_warnings:
                print(f"    📋 Market Validation Details:")
                for warning in validation_warnings[:3]:  # Limit to first 3
                    print(f"       - {warning}")
                if len(validation_warnings) > 3:
                    print(f"       ... and {len(validation_warnings) - 3} more")
        
        # Show FEC cycle info if available
        if r.get('fec_cycle'):
            print(f"    📅 FEC Cycle: {r['fec_cycle']}")
        
        # Show warnings
        all_warnings = []
        if r.get('comp_warnings'):
            all_warnings.extend(r['comp_warnings'])
        if r.get('sat_warnings'):
            all_warnings.extend(r['sat_warnings'])
        
        if all_warnings:
            print(f"    ⚠️  Warnings:")
            for warning in all_warnings[:5]:  # Limit to first 5 warnings
                print(f"       - {warning}")
            if len(all_warnings) > 5:
                print(f"       ... and {len(all_warnings) - 5} more warnings")
    
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