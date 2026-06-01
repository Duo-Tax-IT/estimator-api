import os

# Settings requires an OpenAI key to instantiate; tests never call OpenAI for
# real, so a dummy value is enough to import the app and build requests. Set
# before app modules import config.
os.environ.setdefault("OPENAI_API_KEY", "test-key")
os.environ.setdefault(
    "RPDATA_API_URL", "https://calc.duo.tax/property/{rp_id}"
)
os.environ.setdefault("MEGAMIND_API_URL", "https://api.megamind.duo.tax")
os.environ.setdefault("MEGAMIND_API_KEY", "test-key")
