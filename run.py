"""SlothFlix Docker entry point."""

import os
from web import create_app

app = create_app()
app.run(host="0.0.0.0", port=int(os.getenv("FLASK_PORT", "8180")), threaded=True)
