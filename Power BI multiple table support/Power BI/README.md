# Natural Language Query Dashboard

A full-stack application that allows users to query databases using natural language and visualize the results with interactive charts.

## Features

- Natural language to SQL conversion using Google Gemini API
- Support for MySQL and PostgreSQL databases
- Interactive data visualization with Chart.js
- Real-time query execution and results display
- Responsive and modern UI

## Prerequisites

- Python 3.10 or higher
- Node.js (for development)
- MySQL or PostgreSQL database
- Google Gemini API key

## Project Structure

```
.
├── backend/
│   ├── main.py
│   ├── requirements.txt
│   ├── .env
│   ├── routers/
│   │   └── query.py
│   ├── services/
│   │   ├── database.py
│   │   └── gemini.py
│   └── models/
│       └── database.py
└── frontend/
    ├── index.html
    ├── styles.css
    └── script.js
```

## Setup Instructions

### Backend Setup

1. Navigate to the backend directory:
   ```bash
   cd backend
   ```

2. Create a virtual environment:
   ```bash
   python -m venv venv
   ```

3. Activate the virtual environment:
   - Windows:
     ```bash
     .\venv\Scripts\activate
     ```
   - Unix/MacOS:
     ```bash
     source venv/bin/activate
     ```

4. Install dependencies:
   ```bash
   pip install -r requirements.txt
   ```

5. Create a `.env` file in the backend directory and add your Gemini API key:
   ```
   GEMINI_API_KEY=your_api_key_here
   ```

6. Start the backend server:
   ```bash
   uvicorn main:app --reload
   ```

### Frontend Setup

1. Navigate to the frontend directory:
   ```bash
   cd frontend
   ```

2. Open `index.html` in your web browser or serve it using a local server.

## Usage

1. Open the application in your web browser
2. Configure your database connection:
   - Select database type (MySQL or PostgreSQL)
   - Enter host, port, username, password, and database name
   - Click "Save Configuration"

3. Enter your natural language query in the text area
   - Example: "Show total sales by month"
   - Example: "List top 10 customers by revenue"

4. Click "Execute Query" to see:
   - Generated SQL query
   - Query results in a table
   - Three suggested chart visualizations

## API Endpoints

- `POST /api/query`
  - Request body:
    ```json
    {
      "config": {
        "db_type": "mysql|postgresql",
        "host": "string",
        "port": number,
        "username": "string",
        "password": "string",
        "dbname": "string"
      },
      "query": "string"
    }
    ```
  - Response:
    ```json
    {
      "data": [...],
      "chart_suggestions": [
        {
          "chart_type": "string",
          "title": "string",
          "description": "string"
        }
      ],
      "sql_query": "string"
    }
    ```

## Security Notes

- Never commit your `.env` file or expose your API keys
- In production, implement proper authentication and authorization
- Use HTTPS for all API calls
- Implement rate limiting and input validation

## Contributing

1. Fork the repository
2. Create a feature branch
3. Commit your changes
4. Push to the branch
5. Create a Pull Request

## License

This project is licensed under the MIT License - see the LICENSE file for details. 