"""HiveSwarm gateway — run with `python -m gateway`."""
import uvicorn
from gateway.app import create_app

if __name__ == "__main__":
    app = create_app()
    uvicorn.run(app, host="127.0.0.1", port=8000, log_level="info")
