"""Render public previews without reading private Flask configuration or data."""
from pathlib import Path

from build_pages import build


if __name__ == "__main__":
    build(Path(__file__).resolve().parent / "demo_render")
