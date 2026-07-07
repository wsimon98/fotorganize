"""Local AI models (GPU). Imported only by the worker process, never by the web app.

Heavy deps (torch, transformers, insightface) are imported lazily inside functions so
the FastAPI server and CLI stay importable without them installed.
"""
