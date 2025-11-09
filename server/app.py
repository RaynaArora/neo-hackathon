from flask import Flask, request, jsonify
from flask_cors import CORS
import math

app = Flask(__name__)
CORS(app)  # Enable CORS for all routes

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

def calculate_win_probability_increase(donation_amount, candidate_funding, election_type):
    """Calculate win probability increase based on donation amount and candidate's current funding."""
    donation = float(donation_amount) if donation_amount else 0
    if donation <= 0:
        return 0
    
    # Base impact multiplier varies by election type (local elections are more sensitive to donations)
    base_multiplier = 0.15 if election_type == 'Local' else (0.08 if election_type == 'State' else 0.05)
    
    # Impact is inversely proportional to current funding (smaller campaigns benefit more)
    # Use logarithmic scaling to make it more realistic
    funding_factor = math.log10(max(candidate_funding, 1000)) / 10
    impact_multiplier = base_multiplier / (1 + funding_factor)
    
    # Calculate percentage increase (capped at reasonable maximums)
    max_increase = 12 if election_type == 'Local' else (8 if election_type == 'State' else 5)
    percentage_increase = min(
        (donation / max(candidate_funding, donation)) * impact_multiplier * 100,
        max_increase
    )
    
    return round(percentage_increase * 10) / 10  # Round to 1 decimal place

def generate_dummy_results(donation_amount, user_data, result_limit=10):
    """Generate dummy election and candidate data."""
    elections = [
        {
            'name': '2024 Presidential Election',
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
            'name': '2024 Mayoral Election',
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
    for election in elections:
        for candidate in election['candidates']:
            candidate['viewpoints'] = generate_relevant_viewpoints(user_policies, candidate['name'])
            candidate['winProbabilityIncrease'] = calculate_win_probability_increase(
                donation_amount,
                candidate['funding'],
                election['type']
            )
    
    # Sort candidates within each election by alignment (highest first)
    for election in elections:
        election['candidates'].sort(key=lambda x: x['alignment'], reverse=True)
    
    # Sort elections by highest candidate alignment
    elections.sort(key=lambda x: max(c['alignment'] for c in x['candidates']), reverse=True)
    
    # Apply result limit
    return elections[:result_limit]

@app.route('/run_search', methods=['POST'])
def run_search():
    """Endpoint to run a search and return matching elections and candidates."""
    try:
        data = request.get_json()
        
        # Extract request parameters
        donation_amount = data.get('donationAmount', 0)
        user_data = data.get('userData', {})
        result_limit = data.get('resultLimit', 10)
        
        # Validate donation amount
        try:
            donation_amount = float(donation_amount)
            if donation_amount <= 0:
                return jsonify({'error': 'Donation amount must be greater than 0'}), 400
        except (ValueError, TypeError):
            return jsonify({'error': 'Invalid donation amount'}), 400
        
        # Validate result limit
        try:
            result_limit = int(result_limit)
            if result_limit < 1:
                return jsonify({'error': 'Result limit must be at least 1'}), 400
        except (ValueError, TypeError):
            return jsonify({'error': 'Invalid result limit'}), 400
        
        # Generate results
        results = generate_dummy_results(donation_amount, user_data, result_limit)
        
        return jsonify({
            'success': True,
            'results': results
        }), 200
        
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/health', methods=['GET'])
def health():
    """Health check endpoint."""
    return jsonify({'status': 'healthy'}), 200

if __name__ == '__main__':
    app.run(debug=True, host='0.0.0.0', port=5000)

