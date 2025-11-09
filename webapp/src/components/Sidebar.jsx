import React, { useState, useEffect } from 'react'
import './Sidebar.css'

function Sidebar({ onDataChange }) {
  const [age, setAge] = useState('')
  const [gender, setGender] = useState('')
  const [city, setCity] = useState('')
  const [income, setIncome] = useState(0)
  const [policies, setPolicies] = useState([])
  const [newPolicyText, setNewPolicyText] = useState('')
  const [newPolicyImportance, setNewPolicyImportance] = useState(5)

  // Notify parent component when data changes
  useEffect(() => {
    if (onDataChange) {
      onDataChange({
        age,
        gender,
        city,
        income,
        policies
      })
    }
  }, [age, gender, city, income, policies, onDataChange])

  const handleIncomeChange = (e) => {
    setIncome(parseInt(e.target.value))
  }

  const formatIncome = (value) => {
    if (value === 0) return '$0'
    if (value < 1000) return `$${value}`
    if (value < 1000000) return `$${(value / 1000).toFixed(0)}K`
    return `$${(value / 1000000).toFixed(2)}M`
  }

  const handleAddPolicy = () => {
    if (newPolicyText.trim()) {
      const newPolicy = {
        id: Date.now(),
        text: newPolicyText.trim(),
        importance: newPolicyImportance
      }
      setPolicies([...policies, newPolicy])
      setNewPolicyText('')
      setNewPolicyImportance(5)
    }
  }

  const handleRemovePolicy = (id) => {
    setPolicies(policies.filter(p => p.id !== id))
  }

  const handlePolicyImportanceChange = (id, importance) => {
    setPolicies(policies.map(p => 
      p.id === id ? { ...p, importance } : p
    ))
  }

  return (
    <aside className="sidebar">
      <div className="sidebar-header">
        <h1>Policy Preference Matcher</h1>
      </div>

      <div className="sidebar-content">
        <section className="info-section">
          <h2>Basic Information</h2>
          
          <div className="form-group">
            <label htmlFor="age">Age</label>
            <input
              type="number"
              id="age"
              value={age}
              onChange={(e) => setAge(e.target.value)}
              placeholder="Enter your age"
              min="18"
            />
          </div>

          <div className="form-group">
            <label htmlFor="gender">Gender</label>
            <select
              id="gender"
              value={gender}
              onChange={(e) => setGender(e.target.value)}
            >
              <option value="">Select gender</option>
              <option value="male">Male</option>
              <option value="female">Female</option>
              <option value="non-binary">Non-binary</option>
              <option value="prefer-not-to-say">Prefer not to say</option>
            </select>
          </div>

          <div className="form-group">
            <label htmlFor="city">City of Residence</label>
            <input
              type="text"
              id="city"
              value={city}
              onChange={(e) => setCity(e.target.value)}
              placeholder="Enter your city"
            />
          </div>

          <div className="form-group">
            <label htmlFor="income">
              Annual Income: {formatIncome(income)}
            </label>
            <input
              type="range"
              id="income"
              min="0"
              max="1000000"
              step="1000"
              value={income}
              onChange={handleIncomeChange}
              className="slider"
            />
            <div className="slider-labels">
              <span>$0</span>
              <span>$1M+</span>
            </div>
          </div>
        </section>

        <section className="policies-section">
          <h2>Policy Preferences</h2>
          
          {policies.map((policy) => (
            <div key={policy.id} className="policy-item">
              <div className="policy-header">
                <p className="policy-text">{policy.text}</p>
                <button
                  type="button"
                  className="remove-policy-btn"
                  onClick={() => handleRemovePolicy(policy.id)}
                  aria-label="Remove policy"
                >
                  ×
                </button>
              </div>
              <div className="policy-importance">
                <label>Importance: {policy.importance}/10</label>
                <input
                  type="range"
                  min="0"
                  max="10"
                  value={policy.importance}
                  onChange={(e) => handlePolicyImportanceChange(policy.id, parseInt(e.target.value))}
                  className="slider"
                />
              </div>
            </div>
          ))}

          <div className="add-policy-form">
            <div className="form-group">
              <label htmlFor="new-policy">Add Policy Stance</label>
              <textarea
                id="new-policy"
                value={newPolicyText}
                onChange={(e) => setNewPolicyText(e.target.value)}
                placeholder="Describe your stance on a specific policy..."
                rows="3"
                className="policy-textarea"
              />
            </div>
            <div className="form-group">
              <label htmlFor="new-policy-importance">
                Importance: {newPolicyImportance}/10
              </label>
              <input
                type="range"
                id="new-policy-importance"
                min="0"
                max="10"
                value={newPolicyImportance}
                onChange={(e) => setNewPolicyImportance(parseInt(e.target.value))}
                className="slider"
              />
            </div>
            <button
              type="button"
              className="add-policy-btn"
              onClick={handleAddPolicy}
              disabled={!newPolicyText.trim()}
            >
              Add Policy
            </button>
          </div>
        </section>
      </div>
    </aside>
  )
}

export default Sidebar


