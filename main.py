from __future__ import annotations

from dotenv import load_dotenv
load_dotenv()

import uvicorn
from api import create_app

app = create_app()

if __name__ == "__main__":
    uvicorn.run(app, access_log=False, log_level="info")
