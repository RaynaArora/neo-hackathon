import React, { useState } from 'react'
import Sidebar from './components/Sidebar'
import SearchResults from './components/SearchResults'
import './App.css'

// Generate relevant policy viewpoints based on user's policies
const generateRelevantViewpoints = (userPolicies, candidateName) => {
  if (!userPolicies || userPolicies.length === 0) {
    return [
      'Supports comprehensive healthcare reform',
      'Advocates for climate action and renewable energy',
      'Focuses on economic growth and job creation'
    ]
  }

  // Sort user policies by importance (highest first)
  const sortedPolicies = [...userPolicies].sort((a, b) => b.importance - a.importance)
  
  // Generate viewpoints that relate to top 3 user policies
  const viewpoints = sortedPolicies.slice(0, 3).map((policy, index) => {
    // Create a viewpoint that relates to the user's policy
    const policyKeywords = policy.text.toLowerCase()
    
    // Generate candidate-specific viewpoints based on policy text
    if (policyKeywords.includes('health') || policyKeywords.includes('healthcare') || policyKeywords.includes('medical')) {
      return `Strong advocate for ${policy.text.toLowerCase()} with comprehensive healthcare reform proposals`
    } else if (policyKeywords.includes('climate') || policyKeywords.includes('environment') || policyKeywords.includes('green')) {
      return `Committed to ${policy.text.toLowerCase()} through aggressive environmental policies`
    } else if (policyKeywords.includes('education') || policyKeywords.includes('school')) {
      return `Prioritizes ${policy.text.toLowerCase()} with innovative education funding plans`
    } else if (policyKeywords.includes('economy') || policyKeywords.includes('economic') || policyKeywords.includes('jobs')) {
      return `Focuses on ${policy.text.toLowerCase()} to drive economic growth and job creation`
    } else if (policyKeywords.includes('immigration')) {
      return `Supports ${policy.text.toLowerCase()} with comprehensive immigration reform`
    } else if (policyKeywords.includes('gun') || policyKeywords.includes('firearm')) {
      return `Advocates for ${policy.text.toLowerCase()} through responsible gun safety measures`
    } else {
      return `Champions ${policy.text.toLowerCase()} as a key policy priority`
    }
  })

  // Fill remaining slots if user has fewer than 3 policies
  const defaultViewpoints = [
    'Supports comprehensive healthcare reform',
    'Advocates for climate action and renewable energy',
    'Focuses on economic growth and job creation'
  ]
  
  while (viewpoints.length < 3) {
    viewpoints.push(defaultViewpoints[viewpoints.length])
  }

  return viewpoints.slice(0, 3)
}

// Format funding amount
const formatFunding = (amount) => {
  if (amount < 1000) return `$${amount.toLocaleString()}`
  if (amount < 1000000) return `$${(amount / 1000).toFixed(1)}K`
  if (amount < 1000000000) return `$${(amount / 1000000).toFixed(2)}M`
  return `$${(amount / 1000000000).toFixed(2)}B`
}

// Calculate win probability increase based on donation amount and candidate's current funding
const calculateWinProbabilityIncrease = (donationAmount, candidateFunding, raceType) => {
  const donation = parseFloat(donationAmount) || 0
  if (donation <= 0) return 0

  // Base impact multiplier varies by race type (local races are more sensitive to donations)
  const baseMultiplier = raceType === 'Local' ? 0.15 : raceType === 'State' ? 0.08 : 0.05
  
  // Impact is inversely proportional to current funding (smaller campaigns benefit more)
  // Use logarithmic scaling to make it more realistic
  const fundingFactor = Math.log10(Math.max(candidateFunding, 1000)) / 10
  const impactMultiplier = baseMultiplier / (1 + fundingFactor)
  
  // Calculate percentage increase (capped at reasonable maximums)
  const percentageIncrease = Math.min(
    (donation / Math.max(candidateFunding, donation)) * impactMultiplier * 100,
    raceType === 'Local' ? 12 : raceType === 'State' ? 8 : 5
  )
  
  return Math.round(percentageIncrease * 10) / 10 // Round to 1 decimal place
}

// Dummy data generator (kept for fallback, but API should be used)
const generateDummyResults = (donationAmount, userData) => {
  const races = [
    {
      name: '2024 Presidential Race',
      type: 'Federal',
      date: 'November 5, 2024',
      location: 'United States',
      candidates: [
        { 
          name: 'John Smith', 
          party: 'Democratic Party', 
          alignment: 92,
          funding: 125000000,
          viewpoints: []
        },
        { 
          name: 'Jane Doe', 
          party: 'Republican Party', 
          alignment: 45,
          funding: 98000000,
          viewpoints: []
        },
        { 
          name: 'Alex Johnson', 
          party: 'Independent', 
          alignment: 78,
          funding: 45000000,
          viewpoints: []
        }
      ]
    },
    {
      name: '2024 Senate Race - California',
      type: 'State',
      date: 'November 5, 2024',
      location: 'California',
      candidates: [
        { 
          name: 'Sarah Williams', 
          party: 'Democratic Party', 
          alignment: 88,
          funding: 28000000,
          viewpoints: []
        },
        { 
          name: 'Michael Brown', 
          party: 'Republican Party', 
          alignment: 52,
          funding: 19500000,
          viewpoints: []
        },
        { 
          name: 'Emily Chen', 
          party: 'Green Party', 
          alignment: 85,
          funding: 8500000,
          viewpoints: []
        }
      ]
    },
    {
      name: '2024 House of Representatives - District 12',
      type: 'Federal',
      date: 'November 5, 2024',
      location: 'San Francisco, CA',
      candidates: [
        { 
          name: 'David Lee', 
          party: 'Democratic Party', 
          alignment: 95,
          funding: 5200000,
          viewpoints: []
        },
        { 
          name: 'Robert Taylor', 
          party: 'Republican Party', 
          alignment: 38,
          funding: 3100000,
          viewpoints: []
        }
      ]
    },
    {
      name: '2024 Mayoral Race',
      type: 'Local',
      date: 'November 5, 2024',
      location: 'San Francisco, CA',
      candidates: [
        { 
          name: 'Maria Garcia', 
          party: 'Democratic Party', 
          alignment: 90,
          funding: 1800000,
          viewpoints: []
        },
        { 
          name: 'James Wilson', 
          party: 'Independent', 
          alignment: 72,
          funding: 950000,
          viewpoints: []
        },
        { 
          name: 'Patricia Martinez', 
          party: 'Republican Party', 
          alignment: 48,
          funding: 1200000,
          viewpoints: []
        }
      ]
    }
  ]

  // Add relevant viewpoints and win probability increase to each candidate
  races.forEach(race => {
    race.candidates.forEach(candidate => {
      candidate.viewpoints = generateRelevantViewpoints(
        userData?.policies || [], 
        candidate.name
      )
      candidate.winProbabilityIncrease = calculateWinProbabilityIncrease(
        donationAmount,
        candidate.funding,
        race.type
      )
    })
  })

  // Sort candidates within each race by alignment (highest first)
  races.forEach(race => {
    race.candidates.sort((a, b) => b.alignment - a.alignment)
  })

  // Sort races by highest candidate alignment
  races.sort((a, b) => {
    const maxA = Math.max(...a.candidates.map(c => c.alignment))
    const maxB = Math.max(...b.candidates.map(c => c.alignment))
    return maxB - maxA
  })

  return races
}

function App() {
  const [donationAmount, setDonationAmount] = useState('')
  const [searchResults, setSearchResults] = useState(null)
  const [userData, setUserData] = useState(null)
  const [isSearching, setIsSearching] = useState(false)

  const handleSearch = async (e) => {
    e.preventDefault()
    
    if (!donationAmount || parseFloat(donationAmount) <= 0) {
      alert('Please enter a valid donation amount')
      return
    }

    setIsSearching(true)
    
    try {
      const response = await fetch('http://localhost:5000/run_search', {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
        },
        body: JSON.stringify({
          donationAmount: parseFloat(donationAmount),
          userData: userData || {},
          resultLimit: 10
        })
      })

      if (!response.ok) {
        const errorData = await response.json()
        throw new Error(errorData.error || 'Search failed')
      }

      const data = await response.json()
      if (data.success && data.results) {
        setSearchResults(data.results)
      } else {
        throw new Error('Invalid response from server')
      }
    } catch (error) {
      console.error('Search error:', error)
      alert(`Search failed: ${error.message}`)
      setSearchResults(null)
    } finally {
      setIsSearching(false)
    }
  }

  const handleDataChange = (data) => {
    setUserData(data)
  }

  return (
    <div className="app">
      <Sidebar onDataChange={handleDataChange} />
      <main className="main-content">
        <div className="search-container">
          <form onSubmit={handleSearch} className="search-form">
            <input
              type="number"
              className="search-input"
              placeholder="Enter donation amount ($)"
              value={donationAmount}
              onChange={(e) => setDonationAmount(e.target.value)}
              min="0"
              step="1"
            />
            <button 
              type="submit" 
              className="search-button"
              disabled={isSearching}
            >
              {isSearching ? 'Searching...' : 'Search'}
            </button>
          </form>
        </div>
        
        {isSearching ? (
          <div className="loading-container">
            <div className="loading-spinner"></div>
            <p className="loading-text">Searching for matching races...</p>
          </div>
        ) : searchResults ? (
          <SearchResults results={searchResults} userPolicies={userData?.policies || []} />
        ) : (
          <div className="content-placeholder">
            <h2>Search Results</h2>
            <p>Enter your information and search to see matching races and candidates.</p>
          </div>
        )}
      </main>
    </div>
  )
}

export default App


