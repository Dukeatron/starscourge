"""Keep tests hermetic: never load a local .env file into the test process."""

import os

os.environ["AI_ENGINE_DOTENV"] = "0"
