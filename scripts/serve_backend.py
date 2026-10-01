"""Run the optional full Flask app locally with Waitress, never the debugger."""
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app import app
from waitress import serve


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "5000"))
    print(f"Starting local Waitress server on port {port}. Press Ctrl+C to stop.")
    serve(app, host="127.0.0.1", port=port)
