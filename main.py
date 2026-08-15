"""Launch the API server. Run from this directory: `uv run python main.py`.

Equivalent to `uv run uvicorn app.api.server:api_app --port 8000`.
"""

import uvicorn


def main():
    uvicorn.run("app.api.server:api_app", host="127.0.0.1", port=8000, reload=False)

if __name__ == "__main__":
    main()
