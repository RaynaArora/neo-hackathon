from flask import Flask, request, jsonify
from flask_cors import CORS
import math
import os
import sys
import json
from datetime import datetime, timedelta
from typing import Optional

# Add server directory to path for imports
sys.path.append(os.path.dirname(__file__))

from get_races import get_races
from get_importance_scores import get_importance_scores
from get_monetary_estimate_value import get_monetary_estimate_value

app = Flask(__name__)
CORS(app)  # Enable CORS for all routes

# Cache configuration
CACHE_DIR = os.path.join(os.path.dirname(__file__), 'database')
RACES_CACHE_FILE = os.path.join(CACHE_DIR, 'races_cache.json')
SCORES_CACHE_FILE = os.path.join(CACHE_DIR, 'scores_cache.json')
CACHE_DURATION_HOURS = 24

def generate_relevant_viewpoints(user_policies, candidate_name):
    """Generate relevant policy viewpoints based on user's policies."""
    if not user_policies or len(user_policies) == 0:
        return [
            'Supports comprehensive healthcare reform',
            'Advocates for climate action and renewable energy',
            'Focuses on economic growth and job creation'
        ]
    
    # Sort user policies by importance (highest first)
    sorted_policies = sorted(user_policies, key=lambda x: x.get('importance', 0), reverse=True)
    
    # Generate viewpoints that relate to top 3 user policies
    viewpoints = []
    for policy in sorted_policies[:3]:
        policy_text = policy.get('text', '').lower()
        
        # Generate candidate-specific viewpoints based on policy text
        if any(keyword in policy_text for keyword in ['health', 'healthcare', 'medical']):
            viewpoints.append(f"Strong advocate for {policy.get('text', '').lower()} with comprehensive healthcare reform proposals")
        elif any(keyword in policy_text for keyword in ['climate', 'environment', 'green']):
            viewpoints.append(f"Committed to {policy.get('text', '').lower()} through aggressive environmental policies")
        elif any(keyword in policy_text for keyword in ['education', 'school']):
            viewpoints.append(f"Prioritizes {policy.get('text', '').lower()} with innovative education funding plans")
        elif any(keyword in policy_text for keyword in ['economy', 'economic', 'jobs']):
            viewpoints.append(f"Focuses on {policy.get('text', '').lower()} to drive economic growth and job creation")
        elif 'immigration' in policy_text:
            viewpoints.append(f"Supports {policy.get('text', '').lower()} with comprehensive immigration reform")
        elif any(keyword in policy_text for keyword in ['gun', 'firearm']):
            viewpoints.append(f"Advocates for {policy.get('text', '').lower()} through responsible gun safety measures")
        else:
            viewpoints.append(f"Champions {policy.get('text', '').lower()} as a key policy priority")
    
    # Fill remaining slots if user has fewer than 3 policies
    default_viewpoints = [
        'Supports comprehensive healthcare reform',
        'Advocates for climate action and renewable energy',
        'Focuses on economic growth and job creation'
    ]
    
    while len(viewpoints) < 3:
        viewpoints.append(default_viewpoints[len(viewpoints)])
    
    return viewpoints[:3]

def calculate_win_probability_increase(donation_amount, candidate_funding, race_type):
    """Calculate win probability increase based on donation amount and candidate's current funding."""
    donation = float(donation_amount) if donation_amount else 0
    if donation <= 0:
        return 0
    
    # Base impact multiplier varies by race type (local races are more sensitive to donations)
    base_multiplier = 0.15 if race_type == 'Local' else (0.08 if race_type == 'State' else 0.05)
    
    # Impact is inversely proportional to current funding (smaller campaigns benefit more)
    # Use logarithmic scaling to make it more realistic
    funding_factor = math.log10(max(candidate_funding, 1000)) / 10
    impact_multiplier = base_multiplier / (1 + funding_factor)
    
    # Calculate percentage increase based on donation relative to funding
    # Use a formula that gives meaningful results: donation impact scales with log of funding
    # For small donations relative to large funding, still show some impact
    donation_ratio = donation / max(candidate_funding, donation)
    
    # Scale the impact: smaller campaigns get more impact per dollar
    # Use a formula that ensures even small donations show some effect
    percentage_increase = (donation_ratio * impact_multiplier * 100) + (donation / 10000) * impact_multiplier
    
    # Cap at reasonable maximums
    max_increase = 12 if race_type == 'Local' else (8 if race_type == 'State' else 5)
    percentage_increase = min(percentage_increase, max_increase)
    
    # Ensure minimum display value for any donation > 0
    if percentage_increase < 0.1 and donation > 0:
        percentage_increase = max(0.1, (donation / 1000) * 0.01)
    
    return round(percentage_increase * 10) / 10  # Round to 1 decimal place

def generate_dummy_results(donation_amount, user_data, result_limit=10):
    """Generate dummy race and candidate data."""
    races = [
        {
            'name': '2024 Presidential Race',
            'type': 'Federal',
            'date': 'November 5, 2024',
            'location': 'United States',
            'candidates': [
                {
                    'name': 'John Smith',
                    'party': 'Democratic Party',
                    'alignment': 92,
                    'funding': 125000000,
                    'viewpoints': []
                },
                {
                    'name': 'Jane Doe',
                    'party': 'Republican Party',
                    'alignment': 45,
                    'funding': 98000000,
                    'viewpoints': []
                },
                {
                    'name': 'Alex Johnson',
                    'party': 'Independent',
                    'alignment': 78,
                    'funding': 45000000,
                    'viewpoints': []
                }
            ]
        },
        {
            'name': '2024 Senate Race - California',
            'type': 'State',
            'date': 'November 5, 2024',
            'location': 'California',
            'candidates': [
                {
                    'name': 'Sarah Williams',
                    'party': 'Democratic Party',
                    'alignment': 88,
                    'funding': 28000000,
                    'viewpoints': []
                },
                {
                    'name': 'Michael Brown',
                    'party': 'Republican Party',
                    'alignment': 52,
                    'funding': 19500000,
                    'viewpoints': []
                },
                {
                    'name': 'Emily Chen',
                    'party': 'Green Party',
                    'alignment': 85,
                    'funding': 8500000,
                    'viewpoints': []
                }
            ]
        },
        {
            'name': '2024 House of Representatives - District 12',
            'type': 'Federal',
            'date': 'November 5, 2024',
            'location': 'San Francisco, CA',
            'candidates': [
                {
                    'name': 'David Lee',
                    'party': 'Democratic Party',
                    'alignment': 95,
                    'funding': 5200000,
                    'viewpoints': []
                },
                {
                    'name': 'Robert Taylor',
                    'party': 'Republican Party',
                    'alignment': 38,
                    'funding': 3100000,
                    'viewpoints': []
                }
            ]
        },
        {
            'name': '2024 Mayoral Race',
            'type': 'Local',
            'date': 'November 5, 2024',
            'location': 'San Francisco, CA',
            'candidates': [
                {
                    'name': 'Maria Garcia',
                    'party': 'Democratic Party',
                    'alignment': 90,
                    'funding': 1800000,
                    'viewpoints': []
                },
                {
                    'name': 'James Wilson',
                    'party': 'Independent',
                    'alignment': 72,
                    'funding': 950000,
                    'viewpoints': []
                },
                {
                    'name': 'Patricia Martinez',
                    'party': 'Republican Party',
                    'alignment': 48,
                    'funding': 1200000,
                    'viewpoints': []
                }
            ]
        }
    ]
    
    # Add relevant viewpoints and win probability increase to each candidate
    user_policies = user_data.get('policies', []) if user_data else []
    for race in races:
        for candidate in race['candidates']:
            candidate['viewpoints'] = generate_relevant_viewpoints(user_policies, candidate['name'])
            candidate['winProbabilityIncrease'] = calculate_win_probability_increase(
                donation_amount,
                candidate['funding'],
                race['type']
            )
    
    # Sort candidates within each race by alignment (highest first)
    for race in races:
        race['candidates'].sort(key=lambda x: x['alignment'], reverse=True)
    
    # Sort races by highest candidate alignment
    races.sort(key=lambda x: max(c['alignment'] for c in x['candidates']), reverse=True)
    
    # Apply result limit
    return races[:result_limit]

def get_cached_data(cache_file: str, data_key: str) -> tuple[Optional[list], bool]:
    """
    Get data from cache if available and fresh.
    
    Args:
        cache_file: Path to cache file
        data_key: Key in cache JSON to retrieve data
    
    Returns:
        Tuple of (data_list, is_fresh)
        - data_list: List of data if cache is valid, None otherwise
        - is_fresh: True if cache exists and is less than 1 hour old
    """
    if not os.path.exists(cache_file):
        return None, False
    
    try:
        with open(cache_file, 'r') as f:
            cache_data = json.load(f)
        
        # Check timestamp
        cache_timestamp_str = cache_data.get('timestamp', '')
        if not cache_timestamp_str:
            return None, False
        
        cache_timestamp = datetime.fromisoformat(cache_timestamp_str)
        age = datetime.now() - cache_timestamp
        
        # Check if cache is less than 1 hour old
        if age < timedelta(hours=CACHE_DURATION_HOURS):
            data = cache_data.get(data_key, [])
            if data:
                print(f"Using cached {data_key} (age: {age.total_seconds() / 60:.1f} minutes)")
                return data, True
        
        print(f"Cache expired (age: {age.total_seconds() / 3600:.2f} hours)")
        return None, False
    
    except (json.JSONDecodeError, ValueError, KeyError, IOError) as e:
        print(f"Error reading cache: {e}")
        return None, False


def get_cached_races() -> tuple[Optional[list], bool]:
    """Get races from cache if available and fresh."""
    return get_cached_data(RACES_CACHE_FILE, 'races')


def get_cached_scores() -> tuple[Optional[list], bool]:
    """Get scored races from cache if available and fresh."""
    return get_cached_data(SCORES_CACHE_FILE, 'scored_races')


def save_data_to_cache(data: list, cache_file: str, data_key: str) -> None:
    """
    Save data to cache file.
    
    Args:
        data: List of data dictionaries to cache
        cache_file: Path to cache file
        data_key: Key in cache JSON to store data
    """
    # Ensure cache directory exists
    os.makedirs(CACHE_DIR, exist_ok=True)
    
    cache_data = {
        'timestamp': datetime.now().isoformat(),
        data_key: data
    }
    
    try:
        with open(cache_file, 'w') as f:
            json.dump(cache_data, f, indent=2)
        print(f"Cached {len(data)} items to {cache_file}")
    except IOError as e:
        print(f"Error saving cache: {e}")


def save_races_to_cache(races: list) -> None:
    """Save races to cache file."""
    save_data_to_cache(races, RACES_CACHE_FILE, 'races')


def save_scores_to_cache(scored_races: list) -> None:
    """Save scored races to cache file."""
    save_data_to_cache(scored_races, SCORES_CACHE_FILE, 'scored_races')


def get_races_with_cache() -> list:
    """
    Get races, using cache if available and fresh, otherwise fetching new data.
    
    Returns:
        List of race dictionaries
    """
    # Try to get from cache
    cached_races, is_fresh = get_cached_races()
    if is_fresh and cached_races:
        return cached_races
    
    # Cache miss or expired - fetch new data
    print("Fetching fresh races data...")
    races = get_races(max_elections=100, days_back=14)
    
    # Save to cache
    if races:
        save_races_to_cache(races)
    
    return races


def get_scored_races_with_cache(races: list) -> list:
    """
    Get scored races, using cache if available and fresh, otherwise calculating scores.
    
    Args:
        races: List of race dictionaries (from step 1)
    
    Returns:
        List of race dictionaries with relevance scores
    """
    # Try to get from cache
    cached_scored_races, is_fresh = get_cached_scores()
    if is_fresh and cached_scored_races:
        return cached_scored_races
    
    # Cache miss or expired - calculate scores
    print(f"Calculating importance scores for {len(races)} races...")
    scored_races = get_importance_scores(races, verbose=True)
    
    # Save to cache
    if scored_races:
        save_scores_to_cache(scored_races)
    
    return scored_races


def transform_race_for_frontend(race: dict) -> dict:
    """
    Transform race from pipeline format to frontend format.
    
    Args:
        race: Race dictionary from pipeline with relevance_score
        
    Returns:
        Race dictionary in frontend format
    """
    position = race.get('position', {})
    election = race.get('election', {})
    
    # Map level to type
    level = position.get('level', '')
    type_mapping = {
        'FEDERAL': 'Federal',
        'STATE': 'State',
        'LOCAL': 'Local',
        'CITY': 'Local'
    }
    race_type = type_mapping.get(level, 'Unknown')
    
    # Extract location from race name (state name)
    race_name = position.get('name', '')
    location = 'United States'  # Default
    for state_name in ['Alabama', 'Alaska', 'Arizona', 'Arkansas', 'California', 
                       'Colorado', 'Connecticut', 'Delaware', 'Florida', 'Georgia',
                       'Hawaii', 'Idaho', 'Illinois', 'Indiana', 'Iowa', 'Kansas',
                       'Kentucky', 'Louisiana', 'Maine', 'Maryland', 'Massachusetts',
                       'Michigan', 'Minnesota', 'Mississippi', 'Missouri', 'Montana',
                       'Nebraska', 'Nevada', 'New Hampshire', 'New Jersey', 'New Mexico',
                       'New York', 'North Carolina', 'North Dakota', 'Ohio', 'Oklahoma',
                       'Oregon', 'Pennsylvania', 'Rhode Island', 'South Carolina',
                       'South Dakota', 'Tennessee', 'Texas', 'Utah', 'Vermont',
                       'Virginia', 'Washington', 'West Virginia', 'Wisconsin', 'Wyoming']:
        if state_name in race_name:
            location = state_name
            break
    
    # Transform candidates to frontend format (minimal info for now)
    candidates = []
    for candidate in race.get('candidates', []):
        candidates.append({
            'name': candidate.get('name', 'Unknown'),
            'party': '',  # Empty for now
            'alignment': None,  # Empty match percentage
            'funding': None,  # Empty total funding
            'viewpoints': [],  # Empty relevant policies
            'winProbabilityIncrease': None  # Empty win increase
        })
    
    return {
        'name': race_name,
        'type': race_type,
        'date': election.get('electionDay', ''),
        'location': location,
        'relevanceScore': race.get('relevance_score', 0.0),
        'candidates': candidates
    }


@app.route('/run_search', methods=['POST'])
def run_search():
    """Endpoint to run a search and return matching races and candidates."""
    try:
        data = request.get_json()
        
        # Extract request parameters
        donation_amount = data.get('donationAmount', 0)
        user_data = data.get('userData', {})
        result_limit = data.get('resultLimit', 10)
        
        # Validate donation amount (optional for now, but keep validation)
        try:
            donation_amount = float(donation_amount) if donation_amount else 0
        except (ValueError, TypeError):
            donation_amount = 0
        
        # Validate result limit
        try:
            result_limit = int(result_limit)
            if result_limit < 1:
                return jsonify({'error': 'Result limit must be at least 1'}), 400
        except (ValueError, TypeError):
            return jsonify({'error': 'Invalid result limit'}), 400
        
        # --- PIPELINE STAGE 1: Get Races (with caching) ---
        print("Stage 1: Getting races...")
        races = get_races_with_cache()
        
        if not races:
            return jsonify({
                'success': True,
                'results': [],
                'message': 'No races found'
            }), 200
        
        # --- PIPELINE STAGE 2: Calculate Importance Scores (with caching) ---
        print("Stage 2: Getting importance scores...")
        races_with_scores = get_scored_races_with_cache(races)
        
        # --- PIPELINE STAGE 3: Calculate Monetary Estimate Value ---
        if donation_amount > 0:
            print(f"Stage 3: Calculating monetary estimate values with donation ${donation_amount:,.2f}...")
            races_with_scores = get_monetary_estimate_value(races_with_scores, donation_amount, verbose=True)
        else:
            print("Stage 3: Skipping monetary estimate (no donation amount provided)")
        
        # Sort by relevance score (highest first)
        races_with_scores.sort(key=lambda x: x.get('relevance_score', 0.0), reverse=True)
        
        # Transform to frontend format
        results = []
        for race in races_with_scores[:result_limit]:
            transformed_race = transform_race_for_frontend(race)
            results.append(transformed_race)
        
        return jsonify({
            'success': True,
            'results': results
        }), 200
        
    except Exception as e:
        import traceback
        traceback.print_exc()
        return jsonify({'error': str(e)}), 500

@app.route('/health', methods=['GET'])
def health():
    """Health check endpoint."""
    return jsonify({'status': 'healthy'}), 200

if __name__ == '__main__':
    app.run(debug=True, host='0.0.0.0', port=5000)

