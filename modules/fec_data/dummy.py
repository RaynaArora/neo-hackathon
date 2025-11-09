"""
Script to get candidate campaign volume using the OpenFEC API.
"""
import os
import requests

FEC_TOKEN = os.getenv('FEC_TOKEN')
if not FEC_TOKEN:
    raise ValueError("FEC_TOKEN environment variable is not set. Please set it before running.")

def search_candidate(name: str):
    """
    Search for a candidate by name and return candidate information.
    
    Args:
        name: Candidate name to search for
        
    Returns:
        List of candidate dictionaries
    """
    url = "https://api.open.fec.gov/v1/candidates/search/"
    params = {
        'api_key': FEC_TOKEN,
        'q': name,
    }
    
    try:
        response = requests.get(url, params=params, timeout=10)
        response.raise_for_status()
        data = response.json()
        return data.get('results', [])
    except requests.RequestException as e:
        print(f"Error searching for candidate: {e}")
        return []


def get_candidate_info(candidate_id: str):
    """Get candidate information including cycles."""
    url = f"https://api.open.fec.gov/v1/candidate/{candidate_id}/"
    params = {'api_key': FEC_TOKEN}
    
    try:
        response = requests.get(url, params=params, timeout=10)
        response.raise_for_status()
        data = response.json()
        # The endpoint returns a single candidate object, not a list
        if isinstance(data, dict) and 'results' in data:
            return data.get('results', [])
        elif isinstance(data, dict):
            return [data]  # Single candidate object
        return []
    except requests.RequestException:
        return []


def filter_candidates_by_name(candidates: list, full_name: str):
    """
    Filter candidates to only include those whose lowercase name contains all words from full_name.
    
    Args:
        candidates: List of candidate dictionaries
        full_name: Full name string to match (e.g., "Andrew Parrot")
        
    Returns:
        Filtered list of candidates
    """

    if not full_name or not candidates:
        return candidates
    
    # Split full_name into words and convert to lowercase
    name_words = [word.lower() for word in [full_name.split()[0], full_name.split()[-1]]]
    
    if not name_words:
        return candidates
    
    filtered = []
    for candidate in candidates:
        candidate_name = candidate.get('name', '').lower()
        # Check if candidate name contains all words from the input
        if all(word in candidate_name for word in name_words):
            filtered.append(candidate)
    
    return filtered


def get_candidate_campaign_volume(candidate_name: str):
    """
    Get the total amount of money a candidate raised across all cycles.
    Uses the by_size/by_candidate endpoint for all cycles associated with the candidate.
    
    Args:
        candidate_name: Full name of the candidate to search for (e.g., "Andrew Parrot")
        
    Returns:
        Total amount raised (float), or None if no data found
    """
    # Split the full name to get last name (last item)
    name_parts = candidate_name.split()
    if not name_parts:
        return None
    
    last_name = name_parts[-1]  # Last name is the last item
    
    # Search for the candidate using only the last name
    candidates = search_candidate(candidate_name)
    print("candidates: ", candidates, len(candidates))
    
    # Filter to only candidates whose name contains all words from the full name
    candidates = filter_candidates_by_name(candidates, candidate_name)
    print("filtered candidates: ", candidates)
    
    if not candidates:
        return None
    
    # Try each candidate until we find one with nonzero data
    for candidate in candidates:
        candidate_id = candidate.get('candidate_id')
        if not candidate_id:
            continue
        
        # Get candidate info to extract cycles
        candidate_info_list = get_candidate_info(candidate_id)
        if not candidate_info_list:
            continue
        
        candidate_info = candidate_info_list[0]
        cycles = candidate_info.get('cycles', [])
        
        if not cycles:
            continue
        
        # Query by_size/by_candidate for each cycle
        url = "https://api.open.fec.gov/v1/schedules/schedule_a/by_size/by_candidate/"
        total_amount = 0
        
        for cycle in cycles:
            # Try both election_full values
            for election_full in [False, True]:
                params = {
                    'api_key': FEC_TOKEN,
                    'candidate_id': [candidate_id],
                    'cycle': [cycle],
                    'election_full': election_full,
                    'per_page': 100,
                    'page': 1
                }
                
                try:
                    response = requests.get(url, params=params, timeout=10)
                    response.raise_for_status()
                    data = response.json()
                    results = data.get('results', [])
                    
                    if results:
                        # Sum up all the totals from different size buckets
                        cycle_total = 0
                        for result in results:
                            total = result.get('total', 0) or 0
                            if total > 0:
                                cycle_total += total
                        
                        if cycle_total > 0:
                            total_amount += cycle_total
                            break  # Found data for this cycle, no need to try other election_full value
                            
                except requests.RequestException:
                    continue
        
        if total_amount > 0:
            return total_amount
    
    return None 


def main():
    """Main function to get campaign volume for a candidate."""
    candidate_name = "bloom"
    total = get_candidate_campaign_volume(candidate_name)
    
    if total is not None:
        print(f"Total campaign volume for {candidate_name}: ${total:,.2f}")
    else:
        print(f"No campaign volume data found for {candidate_name}")


if __name__ == "__main__":
    main()
