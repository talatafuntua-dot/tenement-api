from dotenv import load_dotenv
from pathlib import Path
import os

BASE_DIR = Path(__file__).resolve().parent.parent

load_dotenv(BASE_DIR / ".env")

DATABASE_URL = os.getenv("DATABASE_URL")

# -----------------------------
# PDF Generator Settings
# -----------------------------

OUTPUT_FOLDER = "output_pdfs"
TEMP_FOLDER = "temp"

CURRENCY_SYMBOL = "\u20A6"

CURRENCY_FIELDS = {
    "RATE_1",
    "RATE_2",
    "RATE_3",
    "TOTAL_1",
    "TOTAL_2",
    "TOTAL_3",
    "ARREARS_1",
    "ARREARS_2",
    "ARREARS_3",
    "PER_1",
    "PER_2",
    "PER_3",
    "ESTIMATED",
}

MERGED_PDF_NAME = "merged_output.pdf"

WORD_PDF_FORMAT = 17

SUPPORTED_EXCEL = (".xlsx",)

LOG_FILE = "error_log.txt"

KEEP_INDIVIDUAL_PDFS = False

OPEN_OUTPUT_FOLDER = True

COMPRESS_PDF = False

SHOW_WORD = False