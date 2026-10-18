"""The slowapp SDK: `python3 -m slowapp_sdk validate|fixture|catalog`. Ships inside slowapp-python
at /opt/slowapp/slowapp_sdk, so an app's CI uses the SDK of the exact base it builds FROM."""
from pathlib import Path

try:
    __version__ = (Path(__file__).resolve().parent / "VERSION").read_text().strip()   # written by the image build
except OSError:
    __version__ = "dev"
