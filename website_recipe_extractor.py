import time
import random
import logging
from typing import Optional, Dict, List, Any, Callable, TypedDict, Union
from urllib.parse import urlparse

import requests
from recipe_scrapers import scrape_html

# --- Types ---

class RecipeData(TypedDict):
    title: str
    author: str
    yields: str
    description: str
    ingredients: List[str]
    instructions: str
    total_time: int
    host: str
    image_url: str

class ScrapeResponse(TypedDict):
    status: str
    data: Optional[RecipeData]
    message: Optional[str]

# --- Configuration & Logging ---

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S"
)
logger = logging.getLogger(__name__)

USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/121.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:122.0) Gecko/20100101 Firefox/122.0"
]

# --- Helpers ---

def is_valid_url(url: str) -> bool:
    """Basic validation to ensure the URL is well-formed."""
    try:
        result = urlparse(url)
        return all([result.scheme, result.netloc])
    except ValueError:
        return False

def get_browser_headers() -> Dict[str, str]:
    """Generates a fresh set of headers for a request."""
    return {
        "User-Agent": random.choice(USER_AGENTS),
        "Accept-Language": "en-US,en;q=0.9",
        "Referer": "https://www.google.com/"
    }

def get_retry_delay(cycle: int) -> float:
    """Calculates delay."""
    wait_time = 4 + random.uniform(0, 4)
    return wait_time 

class ScraperHelper:
    """Wrapper to safely extract fields from the scraper object."""
    def __init__(self, scraper: Any):
        self.scraper = scraper

    def safe_get(self, func_name: str, default: Any, *args, **kwargs) -> Any:
        try:
            # Get the attribute (method) from the scraper
            method = getattr(self.scraper, func_name)
            # Call it with any provided arguments
            return method(*args, **kwargs)
        except Exception:
            logger.debug(f"Failed to extract {func_name}, using default.", exc_info=True)
            return default

# --- Core Logic ---

def fetch_recipe_scraper(url: str, max_retries: int = 2, timeout: int = 10) -> Optional[Any]:
    """
    Fetches and returns a recipe scraper object.
    """
    if not is_valid_url(url):
        logger.error(f"Invalid URL provided: {url}")
        return None

    logger.info(f"Starting scrape job for: {url}")
    session = requests.Session()

    for cycle in range(max_retries):
        logger.info(f"--- Cycle {cycle + 1} of {max_retries} ---")
        
        try:
            # Headers are generated once per retry cycle to rotate User-Agents
            response = session.get(
                url, 
                headers=get_browser_headers(), 
                timeout=timeout
            )
            response.raise_for_status()

            scraper = scrape_html(html=response.text, org_url=url, wild_mode=True)
            logger.info("SUCCESS: Page fetched and parsed successfully.")
            return scraper

        except requests.exceptions.RequestException:
            logger.exception("Network-related error occurred during request")
        except Exception:
            logger.exception("An unexpected error occurred while parsing the HTML")

        if cycle < max_retries - 1:
            delay = get_retry_delay(cycle)
            logger.info(f"Retrying after {delay:.2f} seconds...")
            time.sleep(delay)
            
    logger.error(f"Max retries reached ({max_retries}). Failed to scrape URL.")
    return None

def extract_recipe_to_dict(scraper: Any) -> RecipeData:
    """
    Normalizes scraper output into a standard RecipeData schema.
    """
    helper = ScraperHelper(scraper)
    
    return {
        "title":       helper.safe_get("title", ""),
        "author":      helper.safe_get("author", ""),
        "yields":      helper.safe_get("yields", ""),
        "description": helper.safe_get("description", ""),
        "ingredients": helper.safe_get("ingredients", []),
        "instructions": helper.safe_get("instructions", ""),
        "total_time":  helper.safe_get("total_time", -1),
        "host":        helper.safe_get("host", ""),
        "image_url":   helper.safe_get("image", ""),
    }

def get_recipe(url: str, timeout: int = 10) -> ScrapeResponse:
    """
    Public API for the scraper. Returns a standardized dictionary response.
    """
    scraper = fetch_recipe_scraper(url, timeout=timeout)

    if scraper is None:
        return {
            "status": "error", 
            "data": None, 
            "message": "Could not retrieve or parse recipe"
        }

    return {
        "status": "success",
        "data": extract_recipe_to_dict(scraper),
        "message": None
    }