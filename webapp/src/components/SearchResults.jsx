import React from 'react'
import './SearchResults.css'

// Format funding amount
const formatFunding = (amount) => {
  if (amount < 1000) return `$${amount.toLocaleString()}`
  if (amount < 1000000) return `$${(amount / 1000).toFixed(1)}K`
  if (amount < 1000000000) return `$${(amount / 1000000).toFixed(2)}M`
  return `$${(amount / 1000000000).toFixed(2)}B`
}

function SearchResults({ results, userPolicies }) {
  if (!results || results.length === 0) {
    return (
      <div className="no-results">
        <p>No results found. Try adjusting your search criteria.</p>
      </div>
    )
  }

  return (
    <div className="search-results">
      {results.map((election, index) => (
        <div key={index} className="election-card">
          <div className="election-header">
            <h3 className="election-title">{election.name}</h3>
            <span className="election-type">{election.type}</span>
          </div>
          <p className="election-date">{election.date}</p>
          <p className="election-location">{election.location}</p>
          
          <div className="candidates-list">
            <h4 className="candidates-heading">Candidates</h4>
            {election.candidates.map((candidate, candIndex) => (
              <div key={candIndex} className="candidate-card">
                <div className="candidate-header">
                  <div className="candidate-info">
                    <h5 className="candidate-name">{candidate.name}</h5>
                    <span className="candidate-party">{candidate.party}</span>
                  </div>
                  <div className="alignment-score">
                    <span className="alignment-value">{candidate.alignment}%</span>
                    <span className="alignment-label">Match</span>
                  </div>
                </div>
                <div className="alignment-bar-container">
                  <div 
                    className="alignment-bar"
                    style={{ width: `${candidate.alignment}%` }}
                  />
                </div>
                
                <div className="candidate-details">
                  <div className="info-row">
                    <div className="funding-info">
                      <span className="funding-label">Total Funding:</span>
                      <span className="funding-amount">
                        {candidate.funding ? formatFunding(candidate.funding) : 'N/A'}
                      </span>
                    </div>
                    
                    {candidate.winProbabilityIncrease !== undefined && candidate.winProbabilityIncrease > 0 && (
                      <div className="win-probability-info">
                        <span className="win-probability-label">Estimated Win Probability Increase (from donation):</span>
                        <span className="win-probability-value">
                          +{candidate.winProbabilityIncrease}%
                        </span>
                      </div>
                    )}
                  </div>
                  
                  {candidate.viewpoints && candidate.viewpoints.length > 0 && (
                    <div className="viewpoints-section">
                      <h6 className="viewpoints-heading">Key Policy Viewpoints</h6>
                      <ul className="viewpoints-list">
                        {candidate.viewpoints.map((viewpoint, vIndex) => (
                          <li key={vIndex} className="viewpoint-item">
                            {viewpoint}
                          </li>
                        ))}
                      </ul>
                    </div>
                  )}
                </div>
              </div>
            ))}
          </div>
        </div>
      ))}
    </div>
  )
}

export default SearchResults

