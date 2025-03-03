from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.chrome.service import Service
from webdriver_manager.chrome import ChromeDriverManager
from time import sleep
import os
import json
import requests
from twilio.rest import Client
from dotenv import load_dotenv
import logging
import argparse
from datetime import datetime
import time
import tempfile
import shutil

# Set up logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler("twitter_monitor.log"),
        logging.StreamHandler()
    ]
)

# Set up argument parser
parser = argparse.ArgumentParser(description='Monitor Twitter/X for new tweets from a private account')
parser.add_argument('--notification', choices=['twilio', 'discord', 'none'], default='none',
                    help='Notification method: twilio, discord, or none')
args = parser.parse_args()

# Load environment variables
load_dotenv()

# Get credentials from environment variables
twilio_account_sid = os.getenv('TWILIO_ACCOUNT_SID')
twilio_auth_token = os.getenv('TWILIO_AUTH_TOKEN')
twilio_number = os.getenv('TWILIO_NUMBER')
your_number = os.getenv('YOUR_NUMBER')
discord_webhook_url = os.getenv('DISCORD_WEBHOOK_URL')
account_to_monitor = os.getenv('TWITTER_ACCOUNT')

# Add this at the global level, before the main() function
latest_tweet_file = "latest_tweet.json"

# Function to send SMS via Twilio
def send_sms(message):
    try:
        client = Client(twilio_account_sid, twilio_auth_token)
        message = client.messages.create(
            body=message,
            from_=twilio_number,
            to=your_number
        )
        logging.info(f"SMS sent: {message.sid}")
        return True
    except Exception as e:
        logging.error(f"Failed to send SMS: {str(e)}")
        return False

# Function to send Discord webhook
def send_discord(message, tweet_content):
    try:
        # Clean up the tweet content to remove metadata
        cleaned_content = clean_tweet_text(tweet_content)
        
        data = {
            "content": message,
            "embeds": [{
                "title": f"New tweet from @{account_to_monitor}",
                "description": cleaned_content[:1500] + ("..." if len(cleaned_content) > 1500 else ""),
                "color": 3447003
            }]
        }
        response = requests.post(discord_webhook_url, json=data)
        if response.status_code == 204:
            logging.info("Discord notification sent")
            return True
        else:
            logging.error(f"Discord API returned {response.status_code}: {response.text}")
            return False
    except Exception as e:
        logging.error(f"Failed to send Discord notification: {str(e)}")
        return False

# Function to clean tweet text (remove metadata)
def clean_tweet_text(text):
    # Split by lines
    lines = text.split('\n')
    
    # Remove metadata lines (username, handle, date, etc.)
    clean_lines = []
    skip_lines = True
    
    for line in lines:
        # Skip lines until we find a line that doesn't contain metadata
        if skip_lines:
            # Skip lines with username, handle, date, verification badges
            if any(x in line for x in ['@', '·', 'Replying to', '✓']):
                continue
            else:
                skip_lines = False
        
        # Skip engagement metrics at the end (likes, retweets, etc.)
        if line.strip().isdigit() or (len(line.strip()) < 10 and line.strip().replace('K', '').replace('.', '').isdigit()):
            continue
            
        # Skip lines with URLs, hashtags, or other Twitter-specific elements
        if line.strip().startswith('http') or line.strip().startswith('#') or line.strip().startswith('@'):
            continue
        
        clean_lines.append(line)
    
    # Join the remaining lines and remove any extra whitespace
    cleaned_text = '\n'.join(clean_lines).strip()
    
    # Remove any remaining Twitter-specific elements like hashtags and mentions within the text
    words = cleaned_text.split()
    filtered_words = [word for word in words if not (word.startswith('#') or word.startswith('@'))]
    
    return ' '.join(filtered_words)

# Function to send notification based on selected method
def send_notification(message, tweet_content=""):
    if args.notification == 'twilio':
        if not twilio_account_sid or not twilio_auth_token or not twilio_number or not your_number:
            logging.error("Twilio credentials not properly configured in .env file")
            return False
        return send_sms(message)
    elif args.notification == 'discord':
        if not discord_webhook_url:
            logging.error("Discord webhook URL not configured in .env file")
            return False
        return send_discord(message, tweet_content)
    else:
        logging.info(f"Notification skipped (mode: {args.notification})")
        return True

def tweet_id_to_timestamp(tweet_id):
    """Convert a Twitter/X tweet ID to a timestamp"""
    try:
        tweet_id = int(tweet_id)
        shifted = tweet_id >> 22
        timestamp = shifted + 1288834974657
        time_created = datetime.fromtimestamp(timestamp/1000).strftime('%Y-%m-%d %H:%M:%S')
        return time_created
    except (ValueError, TypeError):
        return "Unknown (invalid ID format)"

def main(driver=None):
    global latest_known_tweet_id
    
    # Load the latest known tweet ID at the start of each cycle
    try:
        if os.path.exists(latest_tweet_file):
            with open(latest_tweet_file, 'r') as f:
                data = json.load(f)
                latest_known_tweet_id = data.get('latest_tweet_id')
                logging.info(f"Loaded latest known tweet ID: {latest_known_tweet_id}")
        else:
            latest_known_tweet_id = None
    except Exception as e:
        logging.error(f"Error loading latest tweet file: {str(e)}")
        latest_known_tweet_id = None

    # Only create a new browser instance if we don't have one
    if driver is None:
        # Chrome options
        chrome_options = Options()
        
        # Add headless mode options
        chrome_options.add_argument("--headless=new")  # new headless mode for recent Chrome versions
        chrome_options.add_argument("--window-size=1920,1080")  # Set a standard window size
        
        # Existing options
        chrome_options.add_argument("--disable-extensions")
        chrome_options.add_argument("--disable-gpu")
        chrome_options.add_argument("--no-sandbox")
        chrome_options.add_argument("--disable-dev-shm-usage")
        
        # Use your default Chrome profile
        default_chrome_profile = os.path.join(os.environ['USERPROFILE'], 'AppData', 'Local', 'Google', 'Chrome', 'User Data')
        chrome_options.add_argument(f"--user-data-dir={default_chrome_profile}")
        chrome_options.add_argument("--profile-directory=Default")
        
        logging.info("Starting Chrome browser in headless mode...")
        service = Service(ChromeDriverManager().install())
        driver = webdriver.Chrome(service=service, options=chrome_options)
    
    try:
        # Skip the login step since we're using an existing profile
        logging.info("Using existing Chrome profile with Twitter login")
        
        # Navigate to the account's "with_replies" page
        url = f"https://twitter.com/{account_to_monitor}/with_replies"
        logging.info(f"Navigating to {url}")
        driver.get(url)
        
        # Wait for the page to load
        sleep(15)
        
        # Save screenshot for debugging
        driver.save_screenshot("debug_screenshot.png")
        logging.info("Saved debug screenshot")
        
        # Try different selectors for tweets
        tweets = driver.find_elements(By.CSS_SELECTOR, '[data-testid="tweet"]')
        if not tweets:
            logging.info("Trying alternative selector...")
            tweets = driver.find_elements(By.CSS_SELECTOR, 'article[data-testid="tweet"]')
        if not tweets:
            logging.info("Trying another alternative selector...")
            tweets = driver.find_elements(By.XPATH, '//article[contains(@class, "css-")]')
        
        logging.info(f"Found {len(tweets)} tweet elements on the page")
        
        if not tweets:
            logging.warning("No tweets found. This could be due to page not loading correctly or selector issues.")
            logging.debug(f"Page source snippet: {driver.page_source[:1000]}...")
            return driver
            
        # Process tweets to filter for only those by the monitored account
        account_tweets = []
        
        for i, tweet in enumerate(tweets[:30]):  # Get first 30 tweets to filter
            try:
                # Get the full tweet text
                tweet_text = tweet.text
                tweet_html = tweet.get_attribute('innerHTML')
                tweet_lines = tweet_text.split('\n')
                
                # Check if this is a tweet by the monitored account
                is_from_account = False
                for line in tweet_lines[:3]:  # Check first 3 lines
                    if account_to_monitor in line:
                        is_from_account = True
                        break
                
                if is_from_account:
                    # Extract timestamp from the tweet
                    timestamp = None
                    for line in tweet_lines[:5]:
                        if '·' in line:
                            timestamp = line.split('·')[-1].strip()
                            break
                    
                    # Get tweet attributes
                    tweet_id = tweet.get_attribute('data-tweet-id') or "unknown"
                    
                    # Try to get the tweet URL if possible
                    tweet_url = None
                    extracted_tweet_id = None
                    
                    try:
                        # Look for timestamp links that contain the tweet ID
                        time_links = tweet.find_elements(By.CSS_SELECTOR, 'time')
                        for time_link in time_links:
                            parent_a = time_link.find_element(By.XPATH, './..')
                            href = parent_a.get_attribute('href')
                            if href and '/status/' in href:
                                tweet_url = href
                                # Extract the tweet ID from the URL
                                extracted_tweet_id = href.split('/status/')[1].split('?')[0].split('/')[0]
                                break
                        
                        # If we didn't find it with time links, try all links
                        if not tweet_url:
                            links = tweet.find_elements(By.TAG_NAME, 'a')
                            for link in links:
                                href = link.get_attribute('href')
                                if href and '/status/' in href:
                                    tweet_url = href
                                    # Extract the tweet ID from the URL
                                    extracted_tweet_id = href.split('/status/')[1].split('?')[0].split('/')[0]
                                    break
                    except Exception as e:
                        logging.debug(f"Error extracting tweet URL: {str(e)}")
                    
                    # Use the extracted ID if available, otherwise use the attribute
                    final_tweet_id = extracted_tweet_id or tweet_id
                    
                    # Convert tweet ID to exact timestamp
                    exact_timestamp = tweet_id_to_timestamp(final_tweet_id)
                    
                    # Add to our list
                    account_tweets.append({
                        "index": len(account_tweets) + 1,
                        "text": tweet_text,
                        "html": tweet_html[:500] + "..." if len(tweet_html) > 500 else tweet_html,
                        "display_timestamp": timestamp,
                        "tweet_id": final_tweet_id,
                        "exact_timestamp": exact_timestamp,
                        "url": tweet_url
                    })
                    
                    # Only collect up to 20 tweets by the monitored account
                    if len(account_tweets) >= 20:
                        break
            except Exception as e:
                logging.debug(f"Error processing tweet {i}: {str(e)}")
        
        # Sort tweets by exact timestamp (most recent first)
        # Convert string timestamps to datetime objects for proper sorting
        def get_exact_timestamp_value(tweet):
            timestamp_str = tweet.get("exact_timestamp", "Unknown")
            if timestamp_str == "Unknown" or "invalid" in timestamp_str:
                return datetime.min  # Return minimum date for unknown timestamps
            try:
                return datetime.strptime(timestamp_str, '%Y-%m-%d %H:%M:%S')
            except:
                return datetime.min
        
        # Sort tweets by exact timestamp (most recent first)
        account_tweets.sort(key=get_exact_timestamp_value, reverse=True)
        
        # Check if we have new tweets
        new_tweets = []
        if account_tweets:
            newest_tweet_id = account_tweets[0].get('tweet_id')
            logging.info(f"Current newest tweet ID: {newest_tweet_id}")
            logging.info(f"Previous latest known tweet ID: {latest_known_tweet_id}")
            
            try:
                newest_id_int = int(newest_tweet_id)
                latest_known_id_int = int(latest_known_tweet_id) if latest_known_tweet_id else None
                
                # Only save and notify if this is a newer tweet ID
                if latest_known_id_int is None or newest_id_int > latest_known_id_int:
                    # Save the newest tweet ID for future runs
                    with open(latest_tweet_file, 'w') as f:
                        json.dump({'latest_tweet_id': newest_tweet_id}, f)
                    logging.info(f"Saved newest tweet ID: {newest_tweet_id}")
                    
                    # If we have a previous tweet ID, collect all newer tweets
                    if latest_known_id_int:
                        for tweet in account_tweets:
                            current_tweet_id = int(tweet.get('tweet_id'))
                            if current_tweet_id <= latest_known_id_int:
                                break
                            new_tweets.append(tweet)
                    else:
                        # First run - only notify about the most recent tweet
                        new_tweets.append(account_tweets[0])
                    
                    # Send a single notification for all new tweets
                    if new_tweets:
                        logging.info(f"Found {len(new_tweets)} new tweets since last check")
                        
                        # Create a combined message with all new tweets
                        message_parts = [f"New tweets from @{account_to_monitor}:"]
                        for tweet in new_tweets:
                            cleaned_text = clean_tweet_text(tweet.get('text', ''))
                            timestamp = tweet.get('exact_timestamp')
                            message_parts.append(f"\n[{timestamp}]\n{cleaned_text}\n")
                        
                        combined_message = "\n".join(message_parts)
                        # Send a single notification with all new tweets
                        send_notification(combined_message)
                else:
                    logging.info(f"No new tweets (newest: {newest_id_int} <= latest known: {latest_known_id_int})")
            except ValueError as e:
                logging.error(f"Error comparing tweet IDs: {str(e)}")
        
        # Print detailed information about the top 3 tweets if available
        top_tweets_count = min(3, len(account_tweets))
        
        if top_tweets_count > 0:
            logging.info(f"==== TOP {top_tweets_count} MOST RECENT TWEETS ====")
            
            for idx, tweet in enumerate(account_tweets[:top_tweets_count]):
                logging.info(f"\n--- TWEET #{idx+1} DETAILS ---")
                logging.info(f"Tweet Index: {tweet['index']}")
                logging.info(f"Display Timestamp: {tweet.get('display_timestamp', 'unknown')}")
                logging.info(f"Tweet ID: {tweet.get('tweet_id', 'unknown')}")
                logging.info(f"Exact Timestamp: {tweet.get('exact_timestamp', 'unknown')}")
                logging.info(f"Tweet URL: {tweet.get('url', 'unknown')}")
                
                # Print the full raw text with line numbers for analysis
                logging.info("RAW TEXT (line by line):")
                for line_num, line in enumerate(tweet['text'].split('\n')):
                    logging.info(f"Line {line_num+1}: {line}")
                
                # Print cleaned text
                cleaned_text = clean_tweet_text(tweet['text'])
                logging.info("CLEANED TEXT:")
                logging.info(cleaned_text)
            
            logging.info("==== END OF TOP TWEETS DETAILS ====")
        else:
            logging.warning(f"No tweets found from {account_to_monitor}")
        
        return driver  # Return the driver instance
    except Exception as e:
        logging.error(f"Critical error: {str(e)}")
        driver.quit()  # Only quit if there's an error
        return None

if __name__ == "__main__":
    latest_known_tweet_id = None
    driver = None
    try:
        while True:
            logging.info("Starting monitoring cycle...")
            driver = main(driver)  # Pass and receive back the driver instance
            logging.info("Monitoring cycle completed. Waiting 60 seconds before next check...")
            time.sleep(60)
    except KeyboardInterrupt:
        logging.info("Monitoring stopped by user")
        if driver:
            driver.quit()
    except Exception as e:
        logging.error(f"Fatal error in main loop: {str(e)}")
        if driver:
            driver.quit()
