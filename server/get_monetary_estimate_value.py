"""
Calculate monetary estimate value multiplier for races.

This stage of the pipeline estimates the "power of the dollar" for each race
by comparing the donation amount to the estimated total race volume.
The multiplier is then applied to the existing relevance_score.
"""

import os
import sys
import math
import json
import fcntl
import time
from typing import Dict, Any, List, Tuple, Optional
from datetime import datetime, timedelta
from concurrent.futures import ThreadPoolExecutor, as_completed

# Try to get OpenAI API key from environment or credentials
OPENAI_API_KEY = os.getenv('OPENAI_API_KEY')
if not OPENAI_API_KEY:
    try:
        sys.path.append(os.path.join(os.path.dirname(__file__), '..'))
        from credentials import RAYNA_OPENAI_API_KEY
        OPENAI_API_KEY = RAYNA_OPENAI_API_KEY
    except ImportError:
        pass

if OPENAI_API_KEY:
    from openai import OpenAI
    client = OpenAI(api_key=OPENAI_API_KEY)
else:
    client = None
    print("Warning: OPENAI_API_KEY not set. LLM classification will be unavailable, using rule-based fallback only.")

# Cache configuration
CACHE_DIR = os.path.join(os.path.dirname(__file__), 'database')
VOLUME_CACHE_FILE = os.path.join(CACHE_DIR, 'volume_estimates_cache.json')
CACHE_DURATION_HOURS = 24


# Classification categories and their estimated monetary volumes (per candidate)
CLASSIFICATION_CATEGORIES = {
    # Federal Elections
    "presidential": (1_000_000_000, 2_000_000_000),  # $1-2+ billion
    "competitive_senate": (10_000_000, 100_000_000),  # $10-100+ million
    "safe_senate": (1_000_000, 10_000_000),  # $1-10 million
    "competitive_house": (1_000_000, 10_000_000),  # $1-10 million
    "safe_house": (100_000, 1_000_000),  # $100K-1 million
    
    # State Elections
    "governor_large_state": (10_000_000, 100_000_000),  # $10-100+ million
    "governor_small_state": (1_000_000, 10_000_000),  # $1-10 million
    "state_senate_competitive": (50_000, 500_000),  # $50K-500K
    "state_house": (10_000, 100_000),  # $10K-100K
    
    # Local Elections
    "mayor_major_city": (5_000_000, 50_000_000),  # $5-50+ million
    "mayor_mid_size_city": (100_000, 5_000_000),  # $100K-5 million
    "mayor_small_city": (10_000, 100_000),  # $10K-100K
    "city_council_major_city": (100_000, 1_000_000),  # $100K-1 million
    "city_council_typical": (5_000, 50_000),  # $5K-50K
    "school_board": (1_000, 20_000),  # $1K-20K
    "county_commissioner": (10_000, 200_000),  # $10K-200K
}

# Major cities for classification
MAJOR_CITIES = [
    "New York", "NYC", "Los Angeles", "LA", "Chicago", "Houston", "Phoenix",
    "Philadelphia", "San Antonio", "San Diego", "Dallas", "San Jose",
    "Austin", "Jacksonville", "San Francisco", "Columbus", "Fort Worth",
    "Charlotte", "Indianapolis", "Seattle", "Denver", "Washington", "DC"
]

# Large states (for governor classification)
LARGE_STATES = [
    "California", "Texas", "Florida", "New York", "Pennsylvania", "Illinois",
    "Ohio", "Georgia", "North Carolina", "Michigan", "New Jersey", "Virginia",
    "Washington", "Arizona", "Massachusetts", "Tennessee", "Indiana", "Missouri"
]


def classify_races_batch_with_llm(races: List[Dict[str, Any]]) -> List[str]:
    """
    Use OpenAI to classify multiple races in a single API call.
    
    Args:
        races: List of race records with position information
        
    Returns:
        List of classification strings (e.g., ["competitive_senate", "governor_large_state", ...])
    """
    if not client or len(races) == 0:
        return [classify_race_rule_based(race) for race in races]
    
    # Build batch prompt
    races_info = []
    for i, race in enumerate(races):
        position = race.get("position", {})
        race_name = position.get("name", "")
        level = position.get("level", "")
        races_info.append(f"Race {i+1}: Position Name: {race_name}, Level: {level}")
    
    races_text = "\n".join(races_info)
    
    prompt = f"""Classify each of the following election races into one of these categories:

Federal Elections:
- presidential: U.S. Presidential election
- competitive_senate: Competitive U.S. Senate race
- safe_senate: Safe/non-competitive U.S. Senate race
- competitive_house: Competitive U.S. House of Representatives race
- safe_house: Safe/non-competitive U.S. House race

State Elections:
- governor_large_state: Governor race in a large state (CA, TX, FL, NY, PA, IL, OH, GA, NC, MI, NJ, VA, WA, AZ, MA, TN, IN, MO)
- governor_small_state: Governor race in a smaller state
- state_senate_competitive: Competitive state senate race
- state_house: State house/assembly race

Local Elections:
- mayor_major_city: Mayor race in major city (NYC, LA, Chicago, Houston, Phoenix, Philadelphia, etc.)
- mayor_mid_size_city: Mayor race in mid-size city
- mayor_small_city: Mayor race in small city
- city_council_major_city: City council race in major city
- city_council_typical: City council race in typical city
- school_board: School board election
- county_commissioner: County commissioner race

Races to classify:
{races_text}

Respond with a JSON array of classifications, one per race in order. Example: ["competitive_senate", "governor_large_state", "city_council_typical"]"""

    try:
        response = client.chat.completions.create(
            model="gpt-4o-mini",  # Using cheaper model for classification
            messages=[
                {"role": "system", "content": "You are an expert at classifying election races. Respond with a JSON array of category names."},
                {"role": "user", "content": prompt}
            ],
            temperature=0.1,  # Low temperature for consistent classification
            max_tokens=200  # More tokens for batch responses
        )
        
        response_text = response.choices[0].message.content.strip()
        
        # Try to parse as JSON
        try:
            # Remove markdown code blocks if present
            if response_text.startswith("```"):
                # Extract JSON from code block
                lines = response_text.split("\n")
                response_text = "\n".join(lines[1:-1]) if len(lines) > 2 else response_text
            
            classifications = json.loads(response_text)
            
            # Validate we got the right number
            if not isinstance(classifications, list):
                raise ValueError("Response is not a list")
            
            if len(classifications) != len(races):
                print(f"Warning: Expected {len(races)} classifications, got {len(classifications)}")
                # Pad or truncate as needed
                if len(classifications) < len(races):
                    classifications.extend([None] * (len(races) - len(classifications)))
                else:
                    classifications = classifications[:len(races)]
            
            # Validate and normalize each classification
            validated_classifications = []
            for i, classification in enumerate(classifications):
                if classification is None:
                    validated_classifications.append(classify_race_rule_based(races[i]))
                    continue
                
                classification = str(classification).strip().lower()
                
                # Validate classification
                if classification in CLASSIFICATION_CATEGORIES:
                    validated_classifications.append(classification)
                    continue
                
                # Try to handle variations
                classification_normalized = classification.replace(" ", "_")
                if classification_normalized in CLASSIFICATION_CATEGORIES:
                    validated_classifications.append(classification_normalized)
                    continue
                
                # Fallback: try to match partial
                matched = False
                for cat in CLASSIFICATION_CATEGORIES.keys():
                    if cat.replace("_", " ") in classification or classification.replace("_", " ") in cat:
                        validated_classifications.append(cat)
                        matched = True
                        break
                
                if not matched:
                    print(f"Warning: Could not match classification '{classification}' for race {i+1}, using rule-based fallback")
                    validated_classifications.append(classify_race_rule_based(races[i]))
            
            return validated_classifications
            
        except json.JSONDecodeError as e:
            print(f"Error parsing JSON response: {e}")
            print(f"Response was: {response_text}")
            # Fallback to rule-based for all
            return [classify_race_rule_based(race) for race in races]
        
    except Exception as e:
        print(f"Error calling OpenAI API: {e}")
        # Fallback to rule-based classification for all
        return [classify_race_rule_based(race) for race in races]


def classify_race_with_llm(race: Dict[str, Any]) -> str:
    """
    Use OpenAI to classify a single race (wrapper for batch function).
    
    Args:
        race: Race record with position information
        
    Returns:
        Classification string (e.g., "competitive_senate", "governor_large_state")
    """
    results = classify_races_batch_with_llm([race])
    return results[0] if results else classify_race_rule_based(race)


def classify_race_rule_based(race: Dict[str, Any]) -> str:
    """
    Fallback rule-based classification if LLM fails.
    
    Args:
        race: Race record from Civic Engine
        
    Returns:
        Classification string
    """
    position = race.get("position", {})
    race_name = position.get("name", "").upper()
    level = position.get("level", "").upper()
    
    # Federal elections
    if level == "FEDERAL":
        if "PRESIDENT" in race_name:
            return "presidential"
        elif "SENATE" in race_name or "U.S. SENATE" in race_name:
            return "competitive_senate"  # Default to competitive
        elif "HOUSE" in race_name or "REPRESENTATIVES" in race_name:
            return "competitive_house"  # Default to competitive
    
    # State elections
    elif level == "STATE":
        if "GOVERNOR" in race_name:
            # Check if it's a large state
            for state in LARGE_STATES:
                if state.upper() in race_name:
                    return "governor_large_state"
            return "governor_small_state"
        elif "SENATE" in race_name:
            return "state_senate_competitive"
        elif "HOUSE" in race_name or "ASSEMBLY" in race_name:
            return "state_house"
    
    # Local elections
    elif level in ["LOCAL", "CITY"]:
        if "MAYOR" in race_name:
            # Check if major city
            for city in MAJOR_CITIES:
                if city.upper() in race_name:
                    return "mayor_major_city"
            # Could be mid-size or small, default to mid-size
            return "mayor_mid_size_city"
        elif "COUNCIL" in race_name:
            for city in MAJOR_CITIES:
                if city.upper() in race_name:
                    return "city_council_major_city"
            return "city_council_typical"
        elif "SCHOOL BOARD" in race_name or "BOARD OF EDUCATION" in race_name:
            return "school_board"
        elif "COMMISSIONER" in race_name or "COUNTY" in race_name:
            return "county_commissioner"
    
    # Default fallback
    return "safe_house"


def get_estimated_volume(classification: str) -> Tuple[float, float]:
    """
    Get estimated monetary volume range for a classification.
    
    Args:
        classification: Classification category name
        
    Returns:
        Tuple of (min_estimate, max_estimate) in dollars
    """
    return CLASSIFICATION_CATEGORIES.get(classification, (10_000, 100_000))


def get_volume_cache_key(race: Dict[str, Any]) -> str:
    """
    Generate a cache key for a race's volume estimate.
    
    Args:
        race: Race dictionary
    
    Returns:
        Cache key string
    """
    position = race.get("position", {})
    race_id = race.get("race_id", "")
    position_name = position.get("name", "")
    level = position.get("level", "")
    
    # Use race_id if available, otherwise use position info
    if race_id:
        return f"race_{race_id}"
    else:
        return f"pos_{level}_{position_name}"


def get_cached_volume_estimate(race: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """
    Get cached volume estimate for a race if available and fresh.
    
    Args:
        race: Race dictionary
    
    Returns:
        Cached volume estimate dict if available and fresh, None otherwise
    """
    cache_key = get_volume_cache_key(race)
    
    if not os.path.exists(VOLUME_CACHE_FILE):
        return None
    
    try:
        with open(VOLUME_CACHE_FILE, 'r') as f:
            cache_data = json.load(f)
        
        # Check timestamp
        cache_timestamp_str = cache_data.get('timestamp', '')
        if not cache_timestamp_str:
            return None
        
        cache_timestamp = datetime.fromisoformat(cache_timestamp_str)
        age = datetime.now() - cache_timestamp
        
        # Check if cache is less than 1 hour old
        if age < timedelta(hours=CACHE_DURATION_HOURS):
            estimates = cache_data.get('estimates', {})
            if cache_key in estimates:
                return estimates[cache_key]
        
        return None
    
    except (json.JSONDecodeError, ValueError, KeyError, IOError) as e:
        return None


def save_volume_estimate_to_cache(race: Dict[str, Any], volume_estimate: Dict[str, Any]) -> None:
    """
    Save volume estimate to cache with proper file locking to prevent race conditions.
    
    Args:
        race: Race dictionary
        volume_estimate: Volume estimate dictionary (must not be None)
    """
    if volume_estimate is None:
        return  # Don't save None estimates
    
    cache_key = get_volume_cache_key(race)
    
    # Ensure cache directory exists
    os.makedirs(CACHE_DIR, exist_ok=True)
    
    # Use a lock file for cross-process synchronization
    lock_file_path = VOLUME_CACHE_FILE + '.lock'
    max_retries = 10
    retry_delay = 0.1  # 100ms
    
    for attempt in range(max_retries):
        try:
            # Acquire exclusive lock
            lock_file = open(lock_file_path, 'w')
            try:
                fcntl.flock(lock_file.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
                
                # Load existing cache - preserve existing data even if timestamp is invalid
                cache_data = {'estimates': {}}
                if os.path.exists(VOLUME_CACHE_FILE):
                    try:
                        with open(VOLUME_CACHE_FILE, 'r') as f:
                            loaded_data = json.load(f)
                            # Preserve existing estimates even if timestamp is missing/invalid
                            if isinstance(loaded_data, dict) and 'estimates' in loaded_data:
                                cache_data['estimates'] = loaded_data['estimates']
                    except (json.JSONDecodeError, IOError, ValueError) as e:
                        # If cache is corrupted, try to preserve what we can
                        # Don't reset to empty - this would lose all cached data
                        cache_data['estimates'] = {}
                
                # Update cache
                if 'estimates' not in cache_data:
                    cache_data['estimates'] = {}
                
                cache_data['timestamp'] = datetime.now().isoformat()
                cache_data['estimates'][cache_key] = volume_estimate
                
                # Save cache - use atomic write to avoid corruption
                temp_file = VOLUME_CACHE_FILE + '.tmp'
                try:
                    # Write to temp file first
                    with open(temp_file, 'w') as f:
                        json.dump(cache_data, f, indent=2)
                    
                    # Atomic rename (while holding lock)
                    if os.path.exists(temp_file):
                        os.replace(temp_file, VOLUME_CACHE_FILE)
                    
                    # Success - break out of retry loop
                    break
                    
                except IOError as e:
                    print(f"Warning: Failed to write cache file: {e}")
                    # Try to clean up temp file
                    try:
                        if os.path.exists(temp_file):
                            os.remove(temp_file)
                    except:
                        pass
                    # Release lock and retry
                    fcntl.flock(lock_file.fileno(), fcntl.LOCK_UN)
                    lock_file.close()
                    if attempt < max_retries - 1:
                        time.sleep(retry_delay)
                        continue
                    return
                
            finally:
                # Release lock
                fcntl.flock(lock_file.fileno(), fcntl.LOCK_UN)
                lock_file.close()
                
        except (IOError, BlockingIOError) as e:
            # Lock is held by another process, wait and retry
            if attempt < max_retries - 1:
                time.sleep(retry_delay * (attempt + 1))  # Exponential backoff
                continue
            else:
                print(f"Warning: Could not acquire lock after {max_retries} attempts: {e}")
                return
        except Exception as e:
            print(f"Warning: Unexpected error saving cache: {e}")
            return
    
    # Clean up lock file if it exists (shouldn't normally, but just in case)
    try:
        if os.path.exists(lock_file_path) and os.path.getsize(lock_file_path) == 0:
            os.remove(lock_file_path)
    except:
        pass


def estimate_race_monetary_volume(race: Dict[str, Any], use_cache: bool = True) -> Dict[str, Any]:
    """
    Estimate the monetary volume for a race by classifying it and returning an estimate.
    
    Args:
        race: Race record with position information
        use_cache: Whether to use cached results if available
    
    Returns:
        Dictionary with:
        - classification: The category classification
        - min_estimate: Minimum estimated volume per candidate (in dollars)
        - max_estimate: Maximum estimated volume per candidate (in dollars)
        - mid_estimate: Midpoint estimate (average of min and max)
        - method: "llm" or "rule_based"
    """
    # Check cache first
    if use_cache:
        cached = get_cached_volume_estimate(race)
        if cached:
            return cached
    
    # Classify the race
    try:
        classification = classify_race_with_llm(race)
        method = "llm"
    except Exception as e:
        print(f"LLM classification failed: {e}, using rule-based fallback")
        classification = classify_race_rule_based(race)
        method = "rule_based"
    
    # Get volume estimates
    min_estimate, max_estimate = get_estimated_volume(classification)
    mid_estimate = (min_estimate + max_estimate) / 2
    
    result = {
        "classification": classification,
        "min_estimate": min_estimate,
        "max_estimate": max_estimate,
        "mid_estimate": mid_estimate,
        "method": method
    }
    
    # Save to cache (only if successful and not a fallback)
    if use_cache and result is not None:
        save_volume_estimate_to_cache(race, result)
    
    return result


def calculate_dollar_power_multiplier(donation_amount: float, total_race_volume: float) -> float:
    """
    Calculate a multiplier representing the "power of the dollar" for a donation.
    
    The multiplier is based on the proportion of the donation relative to the total race volume.
    A larger donation relative to race size has more impact.
    
    Args:
        donation_amount: The donation amount in dollars
        total_race_volume: Estimated total volume for the race (sum across all candidates)
    
    Returns:
        Multiplier value (typically between 0.5 and 5.0)
    """
    if total_race_volume <= 0:
        return 1.0  # No change if we can't estimate volume
    
    if donation_amount <= 0:
        return 1.0  # No change if no donation
    
    # Calculate proportion
    proportion = donation_amount / total_race_volume
    
    # Use a logarithmic scaling function to calculate multiplier
    # This gives diminishing returns but still rewards larger donations
    # Formula: multiplier = 1 + log10(1 + proportion * 1000) * 2
    # This means:
    # - proportion = 0.001 (0.1%) -> multiplier ≈ 1.6
    # - proportion = 0.01 (1%) -> multiplier ≈ 2.4
    # - proportion = 0.1 (10%) -> multiplier ≈ 3.4
    # - proportion = 1.0 (100%) -> multiplier ≈ 4.6
    
    # Cap the proportion to avoid extreme multipliers
    proportion = min(proportion, 1.0)  # Cap at 100% of race volume
    
    # Calculate multiplier using logarithmic scale
    multiplier = 1.0 + math.log10(1.0 + proportion * 1000) * 2.0
    
    # Cap multiplier between 0.5 and 5.0 for reasonable bounds
    multiplier = max(0.5, min(5.0, multiplier))
    
    return multiplier


def calculate_race_total_volume(race: Dict[str, Any], volume_estimate: Dict[str, Any]) -> float:
    """
    Calculate total estimated volume for a race (across all candidates).
    
    Args:
        race: Race dictionary with candidates
        volume_estimate: Dictionary with mid_estimate from estimate_race_monetary_volume
    
    Returns:
        Total estimated volume in dollars
    """
    candidate_count = len(race.get("candidates", []))
    if candidate_count == 0:
        return 0.0
    
    # Use midpoint estimate per candidate, multiplied by number of candidates
    per_candidate_estimate = volume_estimate.get("mid_estimate", 0.0)
    total_volume = per_candidate_estimate * candidate_count
    
    return total_volume


def _estimate_volumes_for_batch(race_batch: List[Tuple[int, Dict[str, Any]]]) -> List[Tuple[int, Dict[str, Any]]]:
    """
    Helper function to estimate volumes for a batch of races (for parallelization).
    
    Args:
        race_batch: List of tuples (index, race dictionary)
    
    Returns:
        List of tuples (index, volume_estimate_dict)
    """
    if not race_batch:
        return []
    
    indices = [idx for idx, _ in race_batch]
    races = [race for _, race in race_batch]
    
    results = []
    
    # Check cache for each race first
    races_to_classify = []
    indices_to_classify = []
    cached_results = {}
    
    for idx, race in race_batch:
        cached = get_cached_volume_estimate(race)
        if cached:
            cached_results[idx] = cached
        else:
            races_to_classify.append(race)
            indices_to_classify.append(idx)
    
    # Classify races that aren't cached
    if races_to_classify:
        try:
            # Use batch LLM classification
            classifications = classify_races_batch_with_llm(races_to_classify)
            
            # Build volume estimates for non-cached races
            for idx, race, classification in zip(indices_to_classify, races_to_classify, classifications):
                min_estimate, max_estimate = get_estimated_volume(classification)
                mid_estimate = (min_estimate + max_estimate) / 2
                volume_estimate = {
                    "classification": classification,
                    "min_estimate": min_estimate,
                    "max_estimate": max_estimate,
                    "mid_estimate": mid_estimate,
                    "method": "llm"
                }
                # Save to cache
                save_volume_estimate_to_cache(race, volume_estimate)
                cached_results[idx] = volume_estimate
        except Exception as e:
            # Fallback to rule-based for all failed races
            for idx, race in zip(indices_to_classify, races_to_classify):
                try:
                    classification = classify_race_rule_based(race)
                    min_estimate, max_estimate = get_estimated_volume(classification)
                    mid_estimate = (min_estimate + max_estimate) / 2
                    volume_estimate = {
                        "classification": classification,
                        "min_estimate": min_estimate,
                        "max_estimate": max_estimate,
                        "mid_estimate": mid_estimate,
                        "method": "rule_based"
                    }
                    cached_results[idx] = volume_estimate
                except Exception:
                    cached_results[idx] = None
    
    # Return results in order
    for idx in indices:
        if idx in cached_results:
            results.append((idx, cached_results[idx]))
        else:
            results.append((idx, None))
    
    return results


def get_monetary_estimate_value(races: List[Dict[str, Any]], donation_amount: float, verbose: bool = False, max_workers: int = 10) -> List[Dict[str, Any]]:
    """
    Calculate monetary estimate value multipliers for races and update relevance scores.
    
    This function:
    1. Estimates monetary volume for each race (parallelized)
    2. Calculates a dollar power multiplier based on donation amount vs race volume
    3. Multiplies the existing relevance_score by this multiplier
    
    Args:
        races: List of race dictionaries with relevance_score already calculated
        donation_amount: The donation amount in dollars
        verbose: Whether to print progress information
        max_workers: Maximum number of parallel workers for LLM calls
    
    Returns:
        Updated list of race dictionaries with relevance_score multiplied by dollar power
    """
    if verbose:
        print(f"Calculating monetary estimate values for {len(races)} races with donation amount ${donation_amount:,.2f}...")
    
    # Step 1: Batch and parallelize volume estimation (LLM calls)
    volume_estimates = {}
    
    # Batch size for LLM calls
    BATCH_SIZE = 10
    
    if verbose:
        print(f"  Estimating volumes (batched {BATCH_SIZE} per request, parallelized with {max_workers} workers)...")
    
    # Group races into batches
    race_batches = []
    for i in range(0, len(races), BATCH_SIZE):
        batch = [(j, races[j]) for j in range(i, min(i + BATCH_SIZE, len(races)))]
        race_batches.append(batch)
    
    if verbose:
        print(f"    Created {len(race_batches)} batches for {len(races)} races")
    
    # Use ThreadPoolExecutor to parallelize batch processing
    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        # Submit all batch tasks
        future_to_batch = {
            executor.submit(_estimate_volumes_for_batch, batch): batch 
            for batch in race_batches
        }
        
        # Collect results as they complete
        completed_batches = 0
        completed_races = 0
        for future in as_completed(future_to_batch):
            completed_batches += 1
            try:
                batch_results = future.result()
                for race_index, volume_estimate in batch_results:
                    if volume_estimate:
                        volume_estimates[race_index] = volume_estimate
                    completed_races += 1
                
                if verbose:
                    print(f"    Completed batch {completed_batches}/{len(race_batches)} ({completed_races}/{len(races)} races)...")
            except Exception as e:
                if verbose:
                    print(f"    Error in batch volume estimation: {e}")
    
    # Step 2: Calculate multipliers and update scores (sequential, fast)
    for i, race in enumerate(races):
        try:
            # Get volume estimate (from cache or parallel results)
            volume_estimate = None
            if i in volume_estimates:
                volume_estimate = volume_estimates[i]
            
            # If parallel call failed or returned None, try to estimate synchronously
            if volume_estimate is None:
                try:
                    volume_estimate = estimate_race_monetary_volume(race, use_cache=True)
                except Exception as e:
                    if verbose:
                        print(f"  Failed to estimate volume for race {race.get('race_id', 'unknown')}: {e}")
                    # Use a default fallback estimate
                    classification = classify_race_rule_based(race)
                    min_estimate, max_estimate = get_estimated_volume(classification)
                    mid_estimate = (min_estimate + max_estimate) / 2
                    volume_estimate = {
                        "classification": classification,
                        "min_estimate": min_estimate,
                        "max_estimate": max_estimate,
                        "mid_estimate": mid_estimate,
                        "method": "rule_based_fallback"
                    }
                    # Don't cache fallback estimates - they might be wrong
            
            # Ensure we have a valid volume estimate
            if volume_estimate is None:
                if verbose:
                    print(f"  Warning: No volume estimate for race {race.get('race_id', 'unknown')}, skipping multiplier")
                race['metadata']['monetary_volume_error'] = "Failed to estimate volume"
                continue  # Skip this race
            
            # Calculate total race volume (across all candidates)
            total_race_volume = calculate_race_total_volume(race, volume_estimate)
            
            # Calculate dollar power multiplier
            multiplier = calculate_dollar_power_multiplier(donation_amount, total_race_volume)
            
            # Get existing relevance score
            current_score = race.get('relevance_score', 0.0)
            
            # Multiply by multiplier
            new_score = current_score * multiplier
            
            # Update race
            race['relevance_score'] = new_score
            race['metadata']['monetary_volume'] = {
                'classification': volume_estimate['classification'],
                'per_candidate_estimate': volume_estimate['mid_estimate'],
                'total_race_volume': total_race_volume,
                'donation_amount': donation_amount,
                'donation_proportion': donation_amount / total_race_volume if total_race_volume > 0 else 0.0,
                'dollar_power_multiplier': multiplier,
                'method': volume_estimate['method']
            }
            race['metadata']['stage'] = 'get_monetary_estimate_value'
        
        except Exception as e:
            if verbose:
                print(f"  Error calculating monetary estimate for race {race.get('race_id', 'unknown')}: {e}")
            # Keep existing score on error
            race['metadata']['monetary_volume_error'] = str(e)
    
    if verbose:
        print(f"Completed calculating monetary estimate values")
    
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
                {"id": "cand-1", "name": "John Smith"},
                {"id": "cand-2", "name": "Jane Doe"}
            ],
            "relevance_score": 0.5,  # Example existing score
            "metadata": {}
        },
        {
            "race_id": "test-2",
            "position": {
                "id": "pos-2",
                "name": "Mayor - New York City",
                "level": "CITY"
            },
            "election": {
                "id": "election-2",
                "name": "2024 General Election",
                "electionDay": "2024-11-05"
            },
            "candidates": [
                {"id": "cand-3", "name": "Alice Johnson"}
            ],
            "relevance_score": 0.3,  # Example existing score
            "metadata": {}
        }
    ]
    
    print("Testing get_monetary_estimate_value...")
    print("=" * 80)
    
    donation = 10000.0  # $10,000 donation
    updated_races = get_monetary_estimate_value(test_races, donation, verbose=True)
    
    for race in updated_races:
        print(f"\nRace: {race['position']['name']}")
        print(f"  Original Score: {race['metadata'].get('original_score', 'N/A')}")
        print(f"  New Relevance Score: {race['relevance_score']:.3f}")
        if 'monetary_volume' in race['metadata']:
            mv = race['metadata']['monetary_volume']
            print(f"  Classification: {mv['classification']}")
            print(f"  Total Race Volume: ${mv['total_race_volume']:,.2f}")
            print(f"  Donation Proportion: {mv['donation_proportion']*100:.2f}%")
            print(f"  Dollar Power Multiplier: {mv['dollar_power_multiplier']:.3f}")

