# Transport Agentic Assistant

An agentic assistant for analysing Cityflo bus-trip performance. It processes the GPS trip export, normalises device timestamps to India time, calculates delay and on-time status, and answers operational questions in plain English.

## Setup

Create and activate a Python environment, then install dependencies:

```bash
pip install -r requirements.txt
```

Create a `.env` file with your API key:

```text
OPENAI_API_KEY=your_key_here
```

## Run

Run the default question:

```bash
python app.py
```

Or ask a question directly:

```bash
python app.py Which routes were late on 2026-08-03?
```

The answer is printed in the terminal. Processing also writes `trips_processed.csv` (processed trip data) and `summary_data.csv` (route metrics) for debugging and review.

## How It Works

1. `ops_logic.py` reads `trips.csv` and uses `schedule_v2.csv` file for updated value, handles Excel serial datetimes, normalizes actual arrival timestamps to Indian time (IST +5:30), and calculates runtime, delay, and on-time status. It also creates a flag highlighting whether a row is valid or not.
2. `server.py` exposes MCP tools: `route_performance` for route summaries and `trip_level_information` for filtered trip records.
3. `app.py` starts the MCP server and gives its tools to the OpenAI agent. The agent selects the appropriate tool, uses its returned data, and provides a an answer.

## Key Rules

- On time means arrival within 4 minutes of scheduled arrival.
- Scheduled departure is already local India time; actual arrivals are adjusted from their supplied device offset to `+05:30`.
- REC-114 revised runtimes apply only to confirmed `4xx` vehicle series. Ambiguous abbreviated codes are flagged rather than guessed.
- Invalid timestamps and arrivals before departure are excluded from route metrics.
- Tool and terminal output mask phone-number patterns and do not expose complaint text.
- The code also handles PII masking
- There was a logs file as well, however I personally did not find it useful, as it was last week's data

## Project Files

- `app.py` - command-line agent entry point.
- `server.py` - MCP tool server.
- `ops_logic.py` - CSV processing and route metrics.
- `trips.csv` - GPS trip export.
- `schedule_v2.csv` - revised schedule data.
- `trips_processed.csv` and `summary_data.csv`

