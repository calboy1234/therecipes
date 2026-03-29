import time
import requests
import json
import random
from recipe_scrapers import scrape_me, scrape_html
from requests.exceptions import HTTPError, ConnectionError, Timeout


def fetch_recipe_scraper(url, max_retries=4, quiet=False):
    """
    Attempts to fetch the recipe and return the scraper object.
    Includes standard and stealth methods.
    Added a 'quiet' toggle to suppress prints during website automation.
    """
    def log(message):
        if not quiet:
            print(message)

    log(f"\n{'='*60}\nScraping: {url}\n{'='*60}")
    
    for cycle in range(max_retries):
        log(f"\n--- Cycle {cycle + 1} of {max_retries} ---")
        
        # --- METHOD 1: Standard ---
        try:
            log("Attempt 1: Standard access...")
            scraper = scrape_me(url)
            log("[SUCCESS] Standard access worked!")
            return scraper
            
        except (HTTPError, ConnectionError, Timeout) as e:
            if isinstance(e, HTTPError) and e.response is not None and e.response.status_code == 403:
                log("[WARNING] Blocked (403 Forbidden). Switching to Stealth Mode...")
            else:
                log(f"[WARNING] Method 1 failed: {e}. Trying Stealth Mode...")
        except Exception as e:
            log(f"[WARNING] Unexpected error: {e}. Trying Stealth Mode...")

        # --- METHOD 2: Stealth ---
        try:
            log("Attempt 2: Fetching with custom browser headers...")
            headers = {
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/121.0.0.0 Safari/537.36",
                "Accept-Language": "en-US,en;q=0.9",
                "Referer": "https://www.google.com/"
            }
            
            response = requests.get(url, headers=headers, timeout=15)
            response.raise_for_status()
            
            scraper = scrape_html(html=response.text, org_url=url)
            log("[SUCCESS] Stealth Mode worked!")
            return scraper

        except Exception as e:
            log(f"[ERROR] Stealth Mode failed: {e}")

        # Retry Logic 
        if cycle < max_retries - 1:
            log("[INFO] Both methods failed. Waiting before next cycle...")
            time.sleep(10+random.random()*10)
        else:
            log(f"[ERROR] Max retries reached ({max_retries}). Failed to scrape URL.")
            return None


def safe_extract(extraction_method, default=None):
    """
    Helper function to safely extract data.
    If a website is missing a field (like an image or author), 
    this prevents the script from crashing and returns a default value.
    """
    try:
        return extraction_method()
    except Exception:
        return default


def extract_recipe_to_dict(scraper):
    """
    Takes a scraper object and formats all its data into a clean Python dictionary.
    """
    if not scraper:
        return {"error": "Failed to scrape recipe."}

    recipe_data = {
        "title": safe_extract(scraper.title, "Unknown Title"),
        "author": safe_extract(scraper.author, "Unknown Author"),
        "yields": safe_extract(scraper.yields, "Unknown Yield"),
        "description": safe_extract(scraper.description, "No description available."),
        "ingredients": safe_extract(scraper.ingredients, []),
        "instructions": safe_extract(scraper.instructions, []),
        "total_time": safe_extract(scraper.total_time, -1),
        "host": safe_extract(scraper.host, "")
    }
    
    return recipe_data


def get_recipe_json(url, quiet=True):
    """
    The main entry point for your web automation!
    Pass it a URL, and it returns a perfectly formatted JSON string.
    """
    scraper = fetch_recipe_scraper(url, quiet=quiet)
    
    if scraper is None:
        # Return a JSON error message if scraping failed entirely
        return json.dumps({"status": "error", "message": "Could not retrieve recipe"}, indent=4)
        
    recipe_dict = extract_recipe_to_dict(scraper)
    
    # Convert the Python dictionary to a formatted JSON string
    return json.dumps({"status": "success", "data": recipe_dict}, indent=4)