# Flask Server

Flask backend server for the Policy Preference Matcher application.

## Setup

1. Install dependencies:
```bash
pip install -r ../requirements.txt
```

2. Run the server:
```bash
python app.py
```

The server will start on `http://localhost:5000`

## API Endpoints

### POST /run_search

Runs a search to find matching races and candidates based on user preferences.

**Request Body:**
```json
{
  "donationAmount": 1000,
  "userData": {
    "age": 30,
    "gender": "male",
    "city": "San Francisco",
    "income": 75000,
    "policies": [
      {
        "id": 1234567890,
        "text": "I support universal healthcare",
        "importance": 9
      }
    ]
  },
  "resultLimit": 10
}
```

**Response:**
```json
{
  "success": true,
  "results": [
    {
      "name": "2024 Presidential Race",
      "type": "Federal",
      "date": "November 5, 2024",
      "location": "United States",
      "candidates": [
        {
          "name": "John Smith",
          "party": "Democratic Party",
          "alignment": 92,
          "funding": 125000000,
          "viewpoints": [...],
          "winProbabilityIncrease": 0.1
        }
      ]
    }
  ]
}
```

### GET /health

Health check endpoint.

**Response:**
```json
{
  "status": "healthy"
}
```

## Development

The server runs in debug mode by default. To run in production, set `debug=False` in `app.py`.

