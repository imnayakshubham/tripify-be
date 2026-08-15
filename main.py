"""Launch the API server. Run from this directory: `uv run python main.py`.

Equivalent to `uv run uvicorn app.api.server:api_app --host 0.0.0.0 --port 8000`.
"""

import os

import uvicorn


def main():
    uvicorn.run(
        "app.api.server:api_app",
        host=os.getenv("HOST", "0.0.0.0"),
        port=int(os.getenv("PORT", "8000")),
        reload=False,
    )


if __name__ == "__main__":
    main()
