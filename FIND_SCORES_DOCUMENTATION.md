# find_scores.py - Comprehensive Documentation

## Overview

`find_scores.py` calculates **leverage scores** for election races to help prioritize donations based on potential impact. The system combines multiple data sources to rank races by their donation leverage.

## Core Formula

```
Leverage Score = Competitiveness × Saturation
```

---

## How It Works: Step-by-Step

### Step 1: Fetch Races from Civic Engine API

The system starts by fetching all upcoming elections from Civic Engine API:
- Filters by date: Default shows races in next 18 months (configurable)
- Filters out past elections (configurable)
- Extracts individual races from elections
- Calculates days until election for prioritization

### Step 2: For Each Race, Calculate Competitiveness

The system uses a **tiered approach** to determine competitiveness:

#### **TIER 1: Kalshi Prediction Markets (Primary Source)**

**How it works:**
1. Searches Kalshi API for markets matching the race
2. Validates market matches (state, office, district, year)
3. Selects best matching market from all results
4. Calculates competitiveness from market prices
5. **Weighted by match quality** - poor matches are downweighted

**For General Elections (2 candidates):**
- Uses binary market price (e.g., "Will Democrat win?")
- Formula: `1 - abs(price - 50) / 50`
- Example: 50% price = 1.0 (most competitive), 80% price = 0.4 (less competitive)

**For Primary Elections (3+ candidates):**
- Uses entropy-based calculation considering ALL candidates
- Formula: `0.6 × entropy_score + 0.4 × gap_score`
- Entropy: `-Σ(p_i × log(p_i))` where p_i is probability of candidate i
- Higher entropy = more evenly distributed = more competitive
- Also considers gap between top 2 candidates
- Adjusts for number of candidates (more candidates = more competitive due to vote splitting)

**What if Kalshi market is a poor match?**
- **Competitiveness:** System still uses it, but downweights it:
  - Weight = match_score if valid, or match_score × 0.5 if invalid
  - Poor matches contribute less to final competitiveness score
  - Warnings are displayed (e.g., "Year mismatch", "District mismatch")
  - Market validation status shows "POOR MATCH"
  - Data quality may be marked as "low" or "medium"
  
- **Saturation:** Poor matches are NOT used for saturation:
  - Only good matches (match_score ≥ 0.6 and is_valid = True) are used
  - Poor matches result in saturation = None → 1.0 (neutral, no penalty)
  - This prevents using wrong-race market activity for saturation calculation

**Data Quality Indicators:**
- High: Market volume > 100, good match
- Medium: Market volume 10-100, or poor match
- Low: Market volume < 10, or very poor match

#### **TIER 2: Historical Election Results (Always Collected)**

**When used:** Always attempted, combined with other sources

**How it works:**
1. Queries Civic Engine API for the position (e.g., "U.S. House - NC District 2")
2. Gets all past races for that position
3. Extracts winners from `Candidacy.result = "WON"`
4. Maps winners to parties using FEC API
5. Calculates competitiveness based on party consistency

**Competitiveness Calculation:**
- Same party wins all elections → Low competitiveness (0.3) - safe seat
- Parties alternate frequently → High competitiveness (0.8) - competitive
- Multiple parties → Very competitive (0.9)

**Weight:**
- Based on number of elections found: 0.3 for 1 election, up to 1.0 for 4+ elections
- More elections = higher weight = more confidence

**Data Quality:**
- High: 3+ election cycles found
- Medium: 2 election cycles found
- Low: 1 election cycle found

**Works for:** All race types that have positions in Civic Engine (House, Senate, State Senate, State House, Governor, etc.)

#### **TIER 3: NANDA Party Data (Always Collected)**

**When used:** Always attempted, combined with other sources

**How it works:**
1. Extracts state from race name
2. For county races: Attempts to use county-specific data (future improvement - currently aggregates)
3. For state/federal races: Aggregates county-level party affiliation data for the state
4. Calculates average party split (Dem/Rep ratio)
5. Competitiveness = how close to 50/50 split

**Weight:**
- Lower weight (0.2) since it's less accurate than Kalshi/historical
- State-level aggregation is less precise than district-specific data

**Limitations:**
- State-level aggregation for most races (not district-specific)
- County-specific matching not yet implemented (would require county name → FIPS mapping)
- Less accurate than Kalshi or historical data
- Data quality: Medium

**County Races:**
- Currently uses state-level aggregation (known limitation)
- Future improvement: Extract county name from race name and match to specific FIPS code
- Would provide more accurate competitiveness for county-level races

#### **COMBINING ALL SOURCES (Weighted Average)**

**New Approach:** All three sources (Kalshi, Historical, NANDA) are collected and combined with weighted averaging.

**How it works:**
1. Collect all available sources (some may be missing)
2. Each source has a weight:
   - Kalshi: match_score (0.0-1.0), downweighted if poor match
   - Historical: 0.3-1.0 based on number of elections
   - NANDA: 0.2 (fixed, lower weight)
3. Normalize weights so they sum to 1.0
4. Calculate weighted average: `Σ(comp_i × weight_i) / Σ(weight_i)`

**Benefits:**
- If one source is missing, others get more weight automatically
- Multiple sources provide more robust estimate
- Poor Kalshi matches contribute less but still provide some signal
- Historical data can supplement or validate Kalshi

**Example:**
- Kalshi (good match, weight 0.8) + Historical (3 elections, weight 0.7) + NANDA (weight 0.2)
- Total weight = 1.7, normalized to 1.0
- Final = (Kalshi × 0.47) + (Historical × 0.41) + (NANDA × 0.12)

**Default:** If no sources available at all, uses 0.5 (moderate competitiveness)

### Step 3: Calculate Saturation

Saturation measures how much fundraising has already occurred (inverse relationship).

#### **Federal Races (President, Senate, House)**

**Data Source:** FEC API (Federal Election Commission)

**How it works:**
1. Determines FEC cycle from election year
2. Queries FEC API for all candidates in the race
3. Sums total receipts (fundraising) for all candidates
4. Calculates saturation score: `1 / log(1 + total_receipts)`

**Formula:**
- $0 raised → saturation = 1.0 (highest, no saturation)
- $1M raised → saturation ≈ 0.14
- $10M raised → saturation ≈ 0.10
- $100M raised → saturation ≈ 0.09

**Data Quality:** High (actual campaign finance data)

**Error Handling:**
- Retry logic with exponential backoff (3 attempts)
- Handles rate limiting (429 errors)
- Distinguishes API errors from "no data" (returns conservative 0.5 for errors)

#### **State Races (Governor, State Senate, State House)**

**Data Source:** Kalshi market volume/spread as proxy

**IMPORTANT:** This proxy ONLY works when a Kalshi market exists for the race (even if it's a poor match).

**How it works:**
1. If Kalshi market found → uses market volume and bid-ask spread
2. Formula: `log(1 + spread) / log(1 + volume)`
3. Logic:
   - Low volume + high spread = less market attention = lower saturation = higher score
   - High volume + low spread = more market attention = higher saturation = lower score

**What if Kalshi market is a poor match?**
- System still uses it for saturation calculation
- Validation warnings are displayed
- Data quality may be marked as "medium" or "low"
- Warning: "Kalshi market volume/spread used as proxy - not actual fundraising data"

**What if NO Kalshi market exists OR match is poor?**
- Saturation cannot be calculated (set to None)
- Later set to 1.0 (neutral, no penalty) in leverage calculation
- Warning: "No saturation data available - Kalshi market not found" or "Poor Kalshi market match - saturation not calculated"
- **Rationale:** Using market activity from the wrong race doesn't make sense for saturation, so we use neutral value instead

**Data Quality:** Medium (proxy data, not actual finance data)

#### **Local Races (City Council, County, etc.)**

**Data Source:** None available

**How it works:**
- FEC doesn't cover local races
- Kalshi rarely has markets for local races
- NANDA doesn't cover local races
- **Result:** No saturation data available

**Handling:**
- Saturation set to None initially
- Later set to 1.0 (neutral, no penalty) in leverage calculation
- Warning: "No saturation data available for local race - no data sources cover local races"
- Leverage score = Competitiveness × 1.0 (only competitiveness matters)

**Data Quality:** None

### Step 4: Calculate Final Leverage Score

```
Leverage Score = Competitiveness × Saturation
```

**Special Cases:**
- If saturation is None (no data): Set to 1.0 (neutral, no penalty)
- Time-based boost: Races within 90 days get 10% boost, 180 days get 5% boost

---

## Election Type Handling

### Primary Elections

**Detection:**
- Kalshi markets with 3+ candidates indicate primary
- Civic Engine may classify as primary election type

**Competitiveness Calculation:**
- Uses entropy-based formula considering ALL candidates
- Accounts for vote splitting (more candidates = more competitive)
- Formula: `0.6 × entropy + 0.4 × gap_score`
- Entropy measures distribution of probabilities across all candidates

**Saturation:**
- Same as general elections (FEC for federal, Kalshi proxy for state)

### General Elections

**Detection:**
- Kalshi markets with 1-2 candidates (binary markets)
- Most common election type

**Competitiveness Calculation:**
- Uses binary market price
- Formula: `1 - abs(price - 50) / 50`
- 50% = most competitive, 0% or 100% = least competitive

**Saturation:**
- FEC data for federal races
- Kalshi proxy for state races (if market exists)

### Runoff Elections

**Current Handling:**
- Treated same as general elections
- No special handling (could be improved in future)

**Limitations:**
- May not distinguish between primary and runoff
- Uses same competitiveness calculation as general elections

### Recall Elections

**Current Handling:**
- Treated same as general elections
- No special handling (could be improved in future)

**Limitations:**
- May not distinguish recall from regular elections
- Uses same calculation methods

---

## Race Level Handling

### Federal Races

**Types:** President, U.S. Senate, U.S. House of Representatives

**Competitiveness:**
- Tier 1: Kalshi markets (if available)
- Tier 2: Historical election results (Civic Engine + FEC party mapping)
- Tier 3: NANDA state-level data (fallback)

**Saturation:**
- **Always uses FEC data** (actual campaign finance receipts)
- High data quality
- Retry logic for API failures

**Advantages:**
- Best data quality (actual finance data)
- Historical data available for most races
- Kalshi markets usually available

### State Races

**Types:** Governor, State Senate, State House, Attorney General, Secretary of State

**Competitiveness:**
- Tier 1: Kalshi markets (if available)
- Tier 2: Historical election results (Civic Engine + FEC party mapping)
- Tier 3: NANDA state-level data (fallback)

**Saturation:**
- **Kalshi proxy** (if Kalshi market exists)
- Uses market volume and spread as indicators
- **No saturation data** if no Kalshi market exists (set to neutral 1.0)

**Advantages:**
- Historical data often available
- Kalshi markets sometimes available

**Limitations:**
- No actual campaign finance data (uses proxy)
- Proxy only works when Kalshi market exists

### County Races

**Types:** County Supervisor, Sheriff, District Attorney, County Clerk, etc.

**Competitiveness:**
- Tier 1: Kalshi markets (rarely available)
- Tier 2: Historical election results (if position exists in Civic Engine)
- Tier 3: NANDA state-level data (fallback, less accurate)

**Saturation:**
- **No data available** (FEC doesn't cover, Kalshi rarely has markets)
- Set to neutral 1.0 (no penalty)
- Warning displayed

**Limitations:**
- Limited data sources
- May not have historical data in Civic Engine
- NANDA is state-level, not county-specific

### City Races

**Types:** Mayor, City Council, City Attorney, etc.

**Competitiveness:**
- Tier 1: Kalshi markets (very rarely available)
- Tier 2: Historical election results (if position exists in Civic Engine)
- Tier 3: NANDA state-level data (fallback, less accurate)

**Saturation:**
- **No data available** (FEC doesn't cover, Kalshi rarely has markets)
- Set to neutral 1.0 (no penalty)
- Warning displayed

**Limitations:**
- Very limited data sources
- May not have historical data in Civic Engine
- NANDA is state-level, not city-specific

### Regional/Township Races

**Types:** School Board, Water District, Special Districts, etc.

**Competitiveness:**
- Tier 1: Kalshi markets (almost never available)
- Tier 2: Historical election results (if position exists in Civic Engine)
- Tier 3: NANDA state-level data (fallback, less accurate)

**Saturation:**
- **No data available** (FEC doesn't cover, Kalshi almost never has markets)
- Set to neutral 1.0 (no penalty)
- Warning displayed

**Limitations:**
- Extremely limited data sources
- May not have historical data in Civic Engine
- NANDA is state-level, not district-specific

---

## Kalshi Market Validation

### How Validation Works

When a Kalshi market is found, the system validates it using `validate_kalshi_market_match()`:

**Validation Criteria:**
1. **State Match** (30% of score)
   - Checks if state abbreviation or full name appears in market title/ticker
   - Example: "TN" or "Tennessee" in market for Tennessee race

2. **Office Type Match** (30% of score)
   - For House: Looks for "HOUSE" in ticker or "house" in title
   - For Senate: Looks for "SENATE" in ticker or "senate" in title

3. **District Match** (20% of score, House only)
   - Checks if district number appears in market
   - Example: District 7 in "HOUSETN7S" or "TN 7"

4. **Year Match** (20% of score)
   - Checks if election year appears in market
   - Allows 2-year difference (e.g., 2024 market for 2026 race)

**Validation Result:**
- **Good Match:** All required criteria met (state + office, + district for House)
- **Poor Match:** Some criteria missing or mismatched
- **Match Score:** 0.0 to 1.0 (higher = better match)

### What Happens with Poor Match?

**Competitiveness:**
- System still uses the market price to calculate competitiveness
- Validation warnings are displayed
- Data quality may be reduced (high → medium → low)
- Score may be less reliable

**Saturation (State Races):**
- System still uses market volume/spread for saturation proxy
- Validation warnings are displayed
- Data quality marked as "medium" (proxy data)
- Warning: "Kalshi market volume/spread used as proxy - not actual fundraising data"

**Example Output:**
```
⚠️  Kalshi Market Validation: POOR MATCH (score: 0.30)
📋 Market Validation Details:
   - Year not found in market: looking for 2025
   - District mismatch: looking for district 7, market may be for different district
```

### What if No Match Found?

**Competitiveness:**
- Falls back to historical election results (Tier 2)
- If no historical data, uses NANDA (Tier 3)
- If no NANDA, uses default 0.5

**Saturation (State/Local Races):**
- Cannot calculate saturation (no data source)
- Set to None, then 1.0 (neutral) in leverage calculation
- Warning: "No saturation data available"

---

## Data Quality Indicators

### Competitiveness Data Quality

- **High:** Kalshi market with volume > 100, or 3+ historical elections
- **Medium:** Kalshi market with volume 10-100, or 2 historical elections, or NANDA data
- **Low:** Kalshi market with volume < 10, or 1 historical election, or default value
- **None:** No data available (shouldn't happen, defaults to 0.5)

### Saturation Data Quality

- **High:** FEC data (actual receipts) for federal races
- **Medium:** Kalshi proxy (market volume/spread) for state races
- **Low:** Kalshi proxy with low volume (< 10)
- **None:** No data available (local races, state races without Kalshi)

---

## Examples by Race Type

### Example 1: U.S. House Race (Federal)

**Race:** "U.S. House of Representatives - North Carolina 2nd Congressional District"

**Competitiveness:**
1. ✅ Kalshi market found: "NC-02 2024 General" (GOOD MATCH, score: 0.85)
2. Market price: 52% → Competitiveness = 0.96 (very competitive)
3. Data quality: High (volume > 100)

**Saturation:**
1. ✅ FEC data available (cycle 2024)
2. Total receipts: $8,500,000
3. Saturation = 1 / log(1 + 8,500,000) ≈ 0.10
4. Data quality: High (actual finance data)

**Leverage Score:** 0.96 × 0.10 = 0.096

---

### Example 2: State Senate Race (State)

**Race:** "Georgia State Senate - District 35"

**Competitiveness:**
1. ⚠️ Kalshi market found: "Georgia Republican Senate nominee" (POOR MATCH, score: 0.30)
2. Market price: 40% → Competitiveness = 0.80 (competitive)
3. Data quality: Medium (poor match, but market exists)

**Saturation:**
1. ⚠️ Kalshi proxy used (market volume: 50, spread: 8)
2. Saturation = log(1 + 8) / log(1 + 50) ≈ 0.42
3. Data quality: Medium (proxy data, not actual finance)
4. Warning: "Kalshi market volume/spread used as proxy - not actual fundraising data"

**Leverage Score:** 0.80 × 0.42 = 0.336

---

### Example 3: State Race Without Kalshi Market

**Race:** "Alabama State House - District 38"

**Competitiveness:**
1. ❌ No Kalshi market found
2. ✅ Historical data found: 3 elections (2020, 2022, 2024)
3. All won by same party (REP) → Competitiveness = 0.30 (safe seat)
4. Data quality: High (3+ elections)

**Saturation:**
1. ❌ No Kalshi market → No saturation data
2. Set to 1.0 (neutral, no penalty)
3. Warning: "No saturation data available - Kalshi market not found"
4. Data quality: None

**Leverage Score:** 0.30 × 1.0 = 0.30

---

### Example 4: City Council Race (Local)

**Race:** "San Francisco City Council - District 3"

**Competitiveness:**
1. ❌ No Kalshi market found
2. ❌ No historical data in Civic Engine (local positions may not be tracked)
3. ✅ NANDA data used (California state-level)
4. Competitiveness = 0.65 (based on state party split)
5. Data quality: Medium (state-level, not district-specific)

**Saturation:**
1. ❌ No FEC data (doesn't cover local races)
2. ❌ No Kalshi market
3. Set to 1.0 (neutral, no penalty)
4. Warning: "No saturation data available for local race - no data sources cover local races"
5. Data quality: None

**Leverage Score:** 0.65 × 1.0 = 0.65

---

## Key Limitations

### 1. Kalshi Proxy Limitations

- **Only works when market exists:** If no Kalshi market, no saturation data for state/local races
- **Not actual finance data:** Proxy based on market attention, not real fundraising
- **Poor matches still used:** System uses poor matches but flags them with warnings

### 2. Local Race Limitations

- **No saturation data:** FEC, Kalshi, and NANDA don't cover local races
- **Limited competitiveness data:** May only have state-level NANDA data
- **May not have historical data:** Civic Engine may not track all local positions

### 3. Primary Election Limitations

- **May not distinguish primary from general:** System uses same calculation
- **Runoff handling:** No special handling for runoff elections
- **Multi-candidate primaries:** Entropy calculation helps but may not capture all nuances

### 4. Data Quality Variations

- **Federal races:** Best data quality (FEC + Kalshi + Historical)
- **State races:** Medium data quality (Kalshi proxy, may not have markets)
- **Local races:** Lowest data quality (limited sources, state-level aggregation)

---

## Recommendations for Users

### High Confidence Races
- Federal races with Kalshi markets and FEC data
- State races with good Kalshi matches and historical data
- Look for "high" data quality indicators

### Medium Confidence Races
- State races with poor Kalshi matches
- Races with only historical data (no Kalshi)
- Check warnings for data quality issues

### Low Confidence Races
- Local races (city council, county)
- Races with only NANDA data
- Races with "low" or "none" data quality
- Consider these scores as rough estimates

### When to Use Scores
- **Best for:** Federal and state races with good data quality
- **Use with caution:** Local races, races with poor Kalshi matches
- **Always check:** Data quality indicators and warnings

---

## Future Improvements

### Potential Enhancements
1. **Better primary detection:** Distinguish primary from general elections
2. **Runoff handling:** Special handling for runoff elections
3. **Local race data:** Integrate local campaign finance databases if available
4. **Better Kalshi matching:** Improve validation to reject very poor matches
5. **Multi-cycle analysis:** Consider multiple election cycles for better competitiveness assessment

---

## Technical Details

### API Rate Limiting
- FEC API: Retry logic with exponential backoff (3 attempts, 1s/2s/4s delays)
- Handles 429 rate limit errors automatically
- Civic Engine API: Retry logic with exponential backoff (3 attempts)

### Error Handling
- Distinguishes API errors from "no data" cases
- API errors return conservative defaults (0.5) instead of treating as "no fundraising"
- Warnings displayed for all data quality issues

### Performance
- Processes races sequentially (could be parallelized in future)
- Caches NANDA data in memory
- Limits output to top 20 races by default

---

## Conclusion

`find_scores.py` provides a comprehensive system for ranking election races by donation leverage. It works best for federal and state races with good data quality, and gracefully handles races with limited or no data by using neutral values and clear warnings.

The system prioritizes transparency through data quality indicators and warnings, allowing users to make informed decisions about which races to prioritize for donations.

