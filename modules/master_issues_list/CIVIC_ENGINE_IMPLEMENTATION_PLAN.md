# Civic Engine Issues & Stances Implementation Plan

## Goal
Retrieve all issues and their associated unique stances from current elections (electionDay >= today) in the Civic Engine GraphQL API.

## Schema Understanding

### Stance Type
Based on the API documentation:
- **id** (ID!): Unique identifier
- **databaseId** (Int!): Primary key from database
- **statement** (String): The candidate's exact statement about an issue
- **issue** (Issue!): Required - Issue category the statement is about
- **referenceUrl** (String): Source of the candidate's issue statement
- **locale** (String): Locale information

### Issue Type
- **id** (ID!): Unique identifier (e.g., "6" = Education, "5" = Economy)
- **name** (String): Issue name (e.g., "Education", "Economy")

### Relationships
- **Candidacy** → `stances` (plural) → **Stance**: A candidacy can have multiple stances
- **Stance** → `issue` (singular, required) → **Issue**: Each stance belongs to exactly one issue

## Implementation Approach

### Strategy
1. **Query Current Elections**: Get all elections where `electionDay >= today`
2. **Query Candidacies**: For each election, get all candidacies
3. **Extract Stances**: From each candidacy, extract all stances
4. **Group by Issue**: Group unique stances by their issue ID
5. **Output**: Generate a list of issues, each with its unique list of stances

### Key Decisions
- **Uniqueness**: Use stance `id` to ensure each stance appears only once per issue
- **Filtering**: Only include stances from current/future elections
- **Grouping**: Group stances by issue ID to create issue-centric output

## Implementation Steps

### 1. Authentication & Setup ✅
- [x] Use `CIVIC_ENGINE_API_KEY` environment variable
- [x] Use existing `query_civicengine` function from `get_civicengine.py`
- [x] Endpoint: `https://bpi.civicengine.com/graphql`
- [x] Auth: Bearer token via `Authorization` header

### 2. Query Current Elections ✅
- [x] Query elections with `filterBy: { electionDay: { gte: $today } }`
- [x] Extract election IDs for subsequent queries

### 3. Query Candidacies ✅
- [x] Query candidacies filtered by election IDs
- [x] Include stances in the query with all relevant fields:
  - id, databaseId, statement, referenceUrl, locale
  - issue (id, name)
- [x] Handle pagination if needed

### 4. Process & Group Stances ✅
- [x] Extract stances from each candidacy
- [x] Use stance `id` as unique key
- [x] Group stances by issue ID
- [x] Create Issue objects with associated Stance lists

### 5. Output Format ✅
- [x] JSON output with metadata:
  - Total issues
  - Total unique stances
  - Scrape timestamp
- [x] CSV output for easy viewing (optional, requires pandas)
- [x] Summary statistics printed to console

## Data Structure

### Output Format
```json
{
  "metadata": {
    "scrape_time": "2025-01-XX...",
    "total_issues": 20,
    "total_unique_stances": 5000
  },
  "issues": [
    {
      "id": "6",
      "name": "Education",
      "stance_count": 250,
      "stances": [
        {
          "id": "stance-id-1",
          "database_id": 123,
          "statement": "I support increased funding for public schools...",
          "reference_url": "https://...",
          "locale": "en-US"
        },
        ...
      ]
    },
    ...
  ]
}
```

## Query Structure

### Get Current Elections
```graphql
query GetCurrentElections($today: ISO8601Date!, $first: Int!) {
  elections(
    filterBy: { electionDay: { gte: $today } }
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
```

### Get Candidacies with Stances
```graphql
query GetCandidacies($electionIds: [ID!]!) {
  candidacies(
    filterBy: { election: { id: { in: $electionIds } } }
    first: 1000
  ) {
    nodes {
      id
      stances(first: 100) {
        nodes {
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
```

## Known Issue IDs
Based on documentation:
- 6: Education
- 5: Economy
- 12: Environment / Energy
- 62: Criminal Justice / Public Safety
- 24: Healthcare
- 18: Government Reform
- 46: Taxes / Budget
- 30: Infrastructure / Transportation
- 23: Guns
- 50: Wages / Job Benefits
- 81: Civil Rights
- 42: Legislation
- 25: Housing
- 29: Immigration
- 47: Defense / Veterans
- 45: Social Services
- 67: Abortion / Contraception
- 41: Drug Policy
- 15: Foreign Policy

## Error Handling
- Validate API key is set before starting
- Handle GraphQL errors gracefully
- Handle pagination if results exceed limits
- Skip invalid/missing data (stances without issues, etc.)

## Performance Considerations
- Process elections in batches to avoid overwhelming the API
- Use stance ID for deduplication (efficient)
- Consider pagination for large result sets
- Add progress indicators for long-running operations

## Testing
1. Test with small number of elections first
2. Verify stance uniqueness (no duplicates per issue)
3. Verify all stances have associated issues
4. Check output format matches expected structure
