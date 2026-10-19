from scraper import scrape_posts
from utils import log_message

if __name__ == "__main__":
    log_message("=== Scraper Started ===")
    scrape_posts()
    log_message("=== Scraper Ended ===")
