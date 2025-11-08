#!/usr/bin/env python3
"""
Civic Engine Stances & Issues Scraper
======================================

This script retrieves all issues and their associated unique stances from current elections
in the Civic Engine API. Stances are collected from candidacies in elections with dates
on or after today.

Usage:
    python civic_engine_scrape.py

Requirements:
    pip install requests

Author: AI Assistant
"""

import requests
import json
import os
import sys
import traceback
from typing import Dict, Any, Optional, List
from datetime import datetime, date, timedelta
from dataclasses import dataclass, field
from collections import defaultdict

# API endpoint
GRAPHQL_ENDPOINT = "https://bpi.civicengine.com/graphql"


def query_civicengine(
    query: str,
    variables: Optional[Dict[str, Any]] = None,
    token: Optional[str] = None
) -> Dict[str, Any]:
    """
    Query the Civic Engine GraphQL API.
    
    Args:
        query: The GraphQL query string
        variables: Optional dictionary of variables for the GraphQL query
        token: Optional API token. If not provided, uses CIVIC_ENGINE_API_KEY from environment
    
    Returns:
        Dictionary containing the API response
        
    Raises:
        requests.exceptions.RequestException: If the API request fails
        ValueError: If the token is not provided and not found in environment
    """
    # Use provided token or fall back to environment variable
    api_token = token if token is not None else os.getenv('CIVIC_ENGINE_API_KEY')
    
    # Validate token
    if not api_token:
        raise ValueError(
            "API token not provided. Please set CIVIC_ENGINE_API_KEY environment variable "
            "or pass the token parameter."
        )
    
    # Prepare headers
    headers = {
        'Content-Type': 'application/json',
        'Accept': 'application/json',
        'Authorization': f'Bearer {api_token}'
    }
    
    # Prepare payload
    payload = {"query": query}
    if variables:
        payload["variables"] = variables
    
    # Make the request
    response = requests.post(
        GRAPHQL_ENDPOINT,
        headers=headers,
        json=payload,
        timeout=30
    )
    
    # Raise an error for bad status codes
    response.raise_for_status()
    
    # Return the JSON response
    return response.json()


@dataclass
class Stance:
    """Data class for stance information"""
    id: str
    statement: Optional[str]
    issue_id: str
    issue_name: Optional[str]
    reference_url: Optional[str]
    locale: Optional[str]
    database_id: int


@dataclass
class Issue:
    """Data class for issue information"""
    id: str
    name: Optional[str]
    stances: List[Stance] = field(default_factory=list)


class CivicEngineStancesScraper:
    """
    Main scraper class for extracting issues and their unique stances from current elections
    """
    
    def __init__(self, api_key: Optional[str] = None):
        self.api_key = api_key or os.getenv('CIVIC_ENGINE_API_KEY')
        if not self.api_key:
            raise ValueError(
                "CIVIC_ENGINE_API_KEY environment variable is not set. "
                "Please set it before running the scraper."
            )
        
        self.issues: Dict[str, Issue] = {}  # issue_id -> Issue
        self.start_time = datetime.now()
    
    def get_elections_list(self, max_elections: int = 100) -> List[Dict]:
        """
        Get list of elections from the past year (just basic info, no nested data).
        This is the first phase - we'll fetch detailed data for each election separately.
        
        Args:
            max_elections: Maximum number of elections to fetch
        
        Returns:
            List of election dictionaries with just id, name, electionDay
        """
        print("🔍 Phase 1: Fetching list of elections from the past year...")
        
        # Get date from one year ago
        one_year_ago = (date.today() - timedelta(days=365)).isoformat()
        
        query = """
        query GetElectionsList($oneYearAgo: ISO8601Date!, $first: Int!) {
          elections(
            filterBy: { 
                electionDay: { gte: $oneYearAgo }
            }
            first: $first
          ) {
            nodes {
              id
              name
              electionDay
            }
            pageInfo {
              hasNextPage
              endCursor
            }
          }
        }
        """
        
        variables = {
            "oneYearAgo": one_year_ago,
            "first": max_elections
        }
        
        try:
            response = query_civicengine(query, variables=variables, token=self.api_key)
            
            if "errors" in response:
                raise RuntimeError(f"GraphQL errors: {response['errors']}")
            
            elections = response.get("data", {}).get("elections", {}).get("nodes", [])
            print(f"✓ Found {len(elections)} elections from the past year")
            return elections
            
        except Exception as e:
            print(f"❌ Error fetching elections list: {e}")
            print(traceback.format_exc())
            raise
    
    def get_races_for_election(self, election_id: str) -> List[Dict]:
        """
        Get races for a specific election, including candidacies and stances.
        Uses RaceFilter with electionId to filter races for this election.
        
        Args:
            election_id: The election ID to fetch races for
        
        Returns:
            List of race dictionaries with candidacies and stances
        """
        query = """
        query GetRacesForElection($electionId: ID!) {
          races(
            filterBy: { electionId: $electionId }
            first: 100
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
                stances {
                  id
                  databaseId
                  statement
                  referenceUrl
                  locale
                  issue {
                    id
                    name
                  }
                }
              }
            }
            pageInfo {
              hasNextPage
              endCursor
            }
          }
        }
        """
        
        variables = {
            "electionId": election_id
        }
        
        try:
            response = query_civicengine(query, variables=variables, token=self.api_key)
            
            if "errors" in response:
                print(f"   ⚠️  Errors for election {election_id}: {response['errors']}")
                return []
            
            races = response.get("data", {}).get("races", {}).get("nodes", [])
            return races
            
        except Exception as e:
            print(f"   ❌ Error fetching races for election {election_id}: {e}")
            print(traceback.format_exc())
            return []
    
    def process_stances(self, candidacies: List[Dict]) -> None:
        """
        Process candidacies and extract unique stances, grouped by issue.
        
        Args:
            candidacies: List of candidacy dictionaries with stances
        """
        print("📊 Processing stances and grouping by issue...")
        
        # Track unique stances by issue
        # Use stance ID as the key to ensure uniqueness
        stances_by_issue: Dict[str, Dict[str, Stance]] = defaultdict(dict)
        
        total_stances = 0
        
        for candidacy in candidacies:
            # stances is a direct list, not a connection
            stances = candidacy.get('stances', [])
            if not isinstance(stances, list):
                # If it's a dict (connection), try to get nodes
                stances = stances.get('nodes', []) if isinstance(stances, dict) else []
            
            for stance_data in stances:
                total_stances += 1
                
                issue = stance_data.get('issue', {})
                issue_id = issue.get('id')
                
                if not issue_id:
                    continue
                
                stance_id = stance_data.get('id')
                if not stance_id:
                    continue
                
                # Only add if we haven't seen this stance ID before
                if stance_id not in stances_by_issue[issue_id]:
                    stance = Stance(
                        id=stance_id,
                        statement=stance_data.get('statement'),
                        issue_id=issue_id,
                        issue_name=issue.get('name'),
                        reference_url=stance_data.get('referenceUrl'),
                        locale=stance_data.get('locale'),
                        database_id=stance_data.get('databaseId', 0)
                    )
                    
                    stances_by_issue[issue_id][stance_id] = stance
        
        # Convert to Issue objects
        for issue_id, stances_dict in stances_by_issue.items():
            # Get issue name from first stance (they should all have the same issue)
            issue_name = next(iter(stances_dict.values())).issue_name if stances_dict else None
            
            issue = Issue(
                id=issue_id,
                name=issue_name,
                stances=list(stances_dict.values())
            )
            
            self.issues[issue_id] = issue
        
        print(f"✓ Processed {total_stances} total stances")
        print(f"✓ Found {len(self.issues)} unique issues")
        print(f"✓ Found {sum(len(issue.stances) for issue in self.issues.values())} unique stances")
    
    def scrape_all_data(self) -> None:
        """
        Main method to scrape all stance and issue data from current elections.
        """
        print("🚀 Starting Civic Engine stances scraping...")
        print(f"⏰ Start time: {self.start_time}")
        
        try:
            # Step 1: Get list of elections from the past year
            elections_list = self.get_elections_list(max_elections=100)
            
            if not elections_list:
                print("⚠️  No elections found. Nothing to scrape.")
                return
            
            # Step 2: For each election, fetch races (which include candidacies and stances)
            print(f"\n🔍 Phase 2: Fetching races for {len(elections_list)} elections...")
            all_candidacies = []
            
            for i, election_info in enumerate(elections_list, 1):
                election_id = election_info.get('id')
                if not election_id:
                    continue
                
                if i % 10 == 0:
                    print(f"   Processing election {i}/{len(elections_list)}...")
                
                # Fetch races for this specific election
                races = self.get_races_for_election(election_id)
                
                if not races:
                    continue
                
                # Filter to only include STATE/FEDERAL level positions
                has_state_federal = False
                for race in races:
                    position = race.get("position", {})
                    level = position.get("level")
                    if level in ["STATE", "FEDERAL"]:
                        has_state_federal = True
                        break
                
                if not has_state_federal:
                    continue
                
                # Extract candidacies from races with STATE/FEDERAL positions
                for race in races:
                    position = race.get("position", {})
                    if position.get("level") not in ["STATE", "FEDERAL"]:
                        continue
                    
                    candidacies = race.get("candidacies", [])
                    if not isinstance(candidacies, list):
                        candidacies = candidacies.get("nodes", []) if isinstance(candidacies, dict) else []
                    all_candidacies.extend(candidacies)
            
            if not all_candidacies:
                print("⚠️  No candidacies found. Nothing to scrape.")
                return
            
            print(f"✓ Extracted {len(all_candidacies)} candidacies from {len(elections_list)} elections")
            
            # Step 3: Process stances and group by issue
            self.process_stances(all_candidacies)
            
            print(f"✅ Successfully scraped {len(self.issues)} issues")
            
        except Exception as e:
            print(f"❌ Error during scraping: {e}")
            print(traceback.format_exc())
            raise
    
    def save_to_json(self, filename: str = "civic_engine_issues_stances.json") -> None:
        """Save scraped data to JSON file."""
        # Ensure outputs directory exists
        os.makedirs("outputs", exist_ok=True)
        output_path = f"outputs/{filename}"
        
        # Sort issues by ID for consistent output
        sorted_issues = sorted(self.issues.values(), key=lambda x: int(x.id) if x.id.isdigit() else 0)
        
        data = {
            "metadata": {
                "scrape_time": self.start_time.isoformat(),
                "total_issues": len(self.issues),
                "total_unique_stances": sum(len(issue.stances) for issue in self.issues.values())
            },
            "issues": [
                {
                    "id": issue.id,
                    "name": issue.name,
                    "stance_count": len(issue.stances),
                    "stances": [
                        {
                            "id": stance.id,
                            "database_id": stance.database_id,
                            "statement": stance.statement,
                            "reference_url": stance.reference_url,
                            "locale": stance.locale
                        }
                        for stance in issue.stances
                    ]
                }
                for issue in sorted_issues
            ]
        }
        
        with open(output_path, 'w', encoding='utf-8') as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
        
        print(f"💾 Saved JSON data to {output_path}")
    
    def save_to_csv(self, filename: str = "civic_engine_issues_stances.csv") -> None:
        """Save summary data to CSV file."""
        try:
            import pandas as pd
        except ImportError:
            print("⚠️  pandas not available, skipping CSV export")
            return
        
        # Ensure outputs directory exists
        os.makedirs("outputs", exist_ok=True)
        output_path = f"outputs/{filename}"
        
        csv_data = []
        for issue in sorted(self.issues.values(), key=lambda x: int(x.id) if x.id.isdigit() else 0):
            for stance in issue.stances:
                csv_data.append({
                    "Issue ID": issue.id,
                    "Issue Name": issue.name or "",
                    "Stance ID": stance.id,
                    "Database ID": stance.database_id,
                    "Statement": (stance.statement or "")[:500],  # Truncate long statements
                    "Reference URL": stance.reference_url or "",
                    "Locale": stance.locale or ""
                })
        
        df = pd.DataFrame(csv_data)
        df.to_csv(output_path, index=False, encoding='utf-8')
        
        print(f"📊 Saved CSV data to {output_path}")
    
    def print_summary(self) -> None:
        """Print a summary of the scraped data."""
        print("\n" + "="*60)
        print("🎯 CIVIC ENGINE ISSUES & STANCES SCRAPING SUMMARY")
        print("="*60)
        
        print(f"📊 Total issues found: {len(self.issues)}")
        
        total_stances = sum(len(issue.stances) for issue in self.issues.values())
        print(f"📝 Total unique stances: {total_stances}")
        
        # Sort issues by stance count
        sorted_issues = sorted(
            self.issues.values(),
            key=lambda x: len(x.stances),
            reverse=True
        )
        
        print("\n🏆 TOP 10 ISSUES BY STANCE COUNT:")
        for i, issue in enumerate(sorted_issues[:10], 1):
            print(f"{i:2d}. {issue.name or 'Unknown'} (ID: {issue.id})")
            print(f"    🔸 Unique stances: {len(issue.stances)}")
            if issue.stances:
                sample_stance = issue.stances[0]
                sample_statement = (sample_stance.statement or "")[:80]
                print(f"    🔸 Sample stance: {sample_statement}...")
        
        elapsed_time = datetime.now() - self.start_time
        print(f"\n⏰ Total scraping time: {elapsed_time}")
        print("="*60)


def main():
    """Main function to run the scraper."""
    print("🚀 Civic Engine Issues & Stances Scraper")
    print("=" * 40)
    
    try:
        # Initialize scraper (will get API key from env var)
        scraper = CivicEngineStancesScraper()
        
        # Run the scraping process
        scraper.scrape_all_data()
        
        # Save results
        scraper.save_to_json()
        scraper.save_to_csv()
        
        # Print summary
        scraper.print_summary()
        
        print("\n✅ Scraping completed successfully!")
        print("📁 Check the outputs/ directory for the results")
        
    except ValueError as e:
        print(f"\n❌ Configuration error: {e}")
        print(traceback.format_exc())
        sys.exit(1)
    except KeyboardInterrupt:
        print("\n⚠️  Scraping interrupted by user")
    except Exception as e:
        print(f"\n❌ Scraping failed: {e}")
        print(traceback.format_exc())
        sys.exit(1)


if __name__ == "__main__":
    main()
