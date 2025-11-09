"""
Estimate monetary volume for election races using OpenAI classification.
"""

import os
import json
from typing import Dict, Any, Optional, Tuple
from openai import OpenAI

# Try to get OpenAI API key from environment or credentials
OPENAI_API_KEY = os.getenv('OPENAI_API_KEY')
if not OPENAI_API_KEY:
    try:
        import sys
        sys.path.append(os.path.join(os.path.dirname(__file__), '../..'))
        from credentials import RAYNA_OPENAI_API_KEY
        OPENAI_API_KEY = RAYNA_OPENAI_API_KEY
    except ImportError:
        pass

if not OPENAI_API_KEY:
    raise ValueError("OPENAI_API_KEY environment variable or RAYNA_OPENAI_API_KEY in credentials.py must be set")

client = OpenAI(api_key=OPENAI_API_KEY)


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


def classify_race_with_llm(race: Dict[str, Any]) -> str:
    """
    Use OpenAI to classify a race into one of the predefined categories.
    
    Args:
        race: Race record from Civic Engine with position information
        
    Returns:
        Classification string (e.g., "competitive_senate", "governor_large_state")
    """
    # Extract race information
    position = race.get("position", {})
    race_name = position.get("name", "")
    level = position.get("level", "")
    
    # Build prompt
    prompt = f"""Classify the following election race into one of these categories:

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

Race Information:
- Position Name: {race_name}
- Level: {level}

Respond with ONLY the category name (e.g., "competitive_senate" or "governor_large_state"), nothing else."""

    try:
        response = client.chat.completions.create(
            model="gpt-4o-mini",  # Using cheaper model for classification
            messages=[
                {"role": "system", "content": "You are an expert at classifying election races. Respond with only the category name."},
                {"role": "user", "content": prompt}
            ],
            temperature=0.1,  # Low temperature for consistent classification
            max_tokens=50
        )
        
        classification = response.choices[0].message.content.strip().lower()
        
        # Validate classification
        if classification in CLASSIFICATION_CATEGORIES:
            return classification
        
        # Try to handle variations (e.g., "competitive senate" -> "competitive_senate")
        classification_normalized = classification.replace(" ", "_")
        if classification_normalized in CLASSIFICATION_CATEGORIES:
            return classification_normalized
        
        # Fallback: try to match partial
        for cat in CLASSIFICATION_CATEGORIES.keys():
            if cat.replace("_", " ") in classification or classification.replace("_", " ") in cat:
                return cat
        
        # Default fallback
        print(f"Warning: Could not match classification '{classification}', using default")
        return "safe_house"  # Conservative default
        
    except Exception as e:
        print(f"Error calling OpenAI API: {e}")
        # Fallback to rule-based classification
        return classify_race_rule_based(race)


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


def estimate_race_monetary_volume(race: Dict[str, Any]) -> Dict[str, Any]:
    """
    Estimate the monetary volume for a race by classifying it and returning an estimate.
    
    Args:
        race: Race record from Civic Engine with position information
            Expected structure:
            {
                "id": "...",
                "position": {
                    "id": "...",
                    "name": "U.S. Senate - North Carolina",
                    "level": "FEDERAL"
                },
                ...
            }
    
    Returns:
        Dictionary with:
        - classification: The category classification
        - min_estimate: Minimum estimated volume per candidate (in dollars)
        - max_estimate: Maximum estimated volume per candidate (in dollars)
        - mid_estimate: Midpoint estimate (average of min and max)
        - method: "llm" or "rule_based"
    """
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
    
    return {
        "classification": classification,
        "min_estimate": min_estimate,
        "max_estimate": max_estimate,
        "mid_estimate": mid_estimate,
        "method": method
    }


if __name__ == "__main__":
    # Test examples for different race types
    
    test_races = [
        # Federal Elections
        {
            "id": "test-federal-1",
            "position": {
                "id": "pos-pres",
                "name": "President of the United States",
                "level": "FEDERAL"
            }
        },
        {
            "id": "test-federal-2",
            "position": {
                "id": "pos-senate-1",
                "name": "U.S. Senate - North Carolina",
                "level": "FEDERAL"
            }
        },
        {
            "id": "test-federal-3",
            "position": {
                "id": "pos-house-1",
                "name": "U.S. House of Representatives - Florida 6th Congressional District",
                "level": "FEDERAL"
            }
        },
        {
            "id": "test-federal-4",
            "position": {
                "id": "pos-house-2",
                "name": "U.S. House of Representatives - California 2nd Congressional District",
                "level": "FEDERAL"
            }
        },
        
        # State Elections
        {
            "id": "test-state-1",
            "position": {
                "id": "pos-gov-1",
                "name": "Governor - California",
                "level": "STATE"
            }
        },
        {
            "id": "test-state-2",
            "position": {
                "id": "pos-gov-2",
                "name": "Governor - Wyoming",
                "level": "STATE"
            }
        },
        {
            "id": "test-state-3",
            "position": {
                "id": "pos-state-senate-1",
                "name": "State Senate - Minnesota District 60",
                "level": "STATE"
            }
        },
        {
            "id": "test-state-4",
            "position": {
                "id": "pos-state-house-1",
                "name": "State House of Representatives - Virginia 32nd District",
                "level": "STATE"
            }
        },
        
        # Local/City Elections
        {
            "id": "test-local-1",
            "position": {
                "id": "pos-mayor-1",
                "name": "Mayor - New York City",
                "level": "CITY"
            }
        },
        {
            "id": "test-local-2",
            "position": {
                "id": "pos-mayor-2",
                "name": "Mayor - Los Angeles",
                "level": "CITY"
            }
        },
        {
            "id": "test-local-3",
            "position": {
                "id": "pos-mayor-3",
                "name": "Mayor - Minneapolis",
                "level": "CITY"
            }
        },
        {
            "id": "test-local-4",
            "position": {
                "id": "pos-mayor-4",
                "name": "Mayor - Des Moines",
                "level": "CITY"
            }
        },
        {
            "id": "test-local-5",
            "position": {
                "id": "pos-council-1",
                "name": "City Council - New York City District 1",
                "level": "CITY"
            }
        },
        {
            "id": "test-local-6",
            "position": {
                "id": "pos-council-2",
                "name": "City Council - Minneapolis Ward 3",
                "level": "CITY"
            }
        },
        {
            "id": "test-local-7",
            "position": {
                "id": "pos-school-1",
                "name": "School Board - Minneapolis Public Schools",
                "level": "LOCAL"
            }
        },
        {
            "id": "test-local-8",
            "position": {
                "id": "pos-county-1",
                "name": "County Commissioner - Hennepin County District 3",
                "level": "LOCAL"
            }
        },
    ]
    
    print("=" * 80)
    print("TESTING RACE MONETARY VOLUME ESTIMATION")
    print("=" * 80)
    print()
    
    for i, test_race in enumerate(test_races, 1):
        print(f"Test {i}: {test_race['position']['name']} ({test_race['position']['level']})")
        print("-" * 80)
        
        result = estimate_race_monetary_volume(test_race)
        print(f"  Classification: {result['classification']}")
        print(f"  Estimated volume per candidate: ${result['min_estimate']:,.0f} - ${result['max_estimate']:,.0f}")
        print(f"  Midpoint estimate: ${result['mid_estimate']:,.0f}")
        print(f"  Method: {result['method']}")
        print()

