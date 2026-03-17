import os
from dotenv import load_dotenv

load_dotenv()

ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY", "")
TAVILY_API_KEY = os.getenv("TAVILY_API_KEY", "")
DATABASE_URL = os.getenv("DATABASE_URL", "sqlite:///./battery_intel.db")
UPLOAD_DIR = os.getenv("UPLOAD_DIR", "./uploads")

NAATBATT_URL = "https://www.nlr.gov/media/docs/libraries/transportation/naatbatt-database-29sep2025.xlsx"
NAATBATT_LOCAL_PATH = "data/naatbatt_latest.xlsx"

CLAUDE_MODEL = "claude-sonnet-4-6"

VALID_SHEETS = [
    "Raw Materials",
    "Battery Grade Materials",
    "Other Battery Components & Mat.",
    "Electrode & Cell Manufacturing",
    "Module-Pack Manufacturing",
    "Recycling-Repurposing",
    "Equipment",
    "R&D",
    "Services & Consulting",
    "Modeling & Software",
    "Distributors",
    "Professional Services (NB)",
]

# No country restriction — import all NAATBatt companies globally
VALID_COUNTRIES: set[str] = set()
