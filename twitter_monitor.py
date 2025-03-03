import os
import sys
import tweepy
import time
import json
from twilio.rest import Client
from datetime import datetime

# Set up verbose logging
VERBOSE = os.environ.get('VERBOSE_LOGGING', 'false').lower() == 'true'

def log(message, always=False):
    """Log messages with timestamp, only if verbose logging is enabled or always=True"""
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    if VERBOSE or always:
        print(f"[{timestamp}] {message}")

def get_latest_tweets(api, user_id, since_id=None):
    """
    Get the latest tweets from a specific user using OAuth 1.0a (for private accounts)
    """
    log(f"Fetching tweets for user_id={user_id}, since_id={since_id}")
    
    try:
        # Get tweets from the user
        if since_id:
            log(f"Getting tweets since ID: {since_id}")
            tweets = api.user_timeline(
                user_id=user_id,
                count=10,
                since_id=since_id,
                tweet_mode='extended'
            )
        else:
            log("No since_id provided, getting most recent tweets")
            tweets = api.user_timeline(
                user_id=user_id,
                count=10,
                tweet_mode='extended'
            )
        
        log(f"Fetched {len(tweets)} tweets")
        log(f"Raw tweets data: {tweets}", always=True)
        
        # Log rate limit information
        rate_limit_status = api.rate_limit_status()
        if 'resources' in rate_limit_status and 'statuses' in rate_limit_status['resources'] and '/statuses/user_timeline' in rate_limit_status['resources']['statuses']:
            rate_info = rate_limit_status['resources']['statuses']['/statuses/user_timeline']
            log(f"Rate limit: {rate_info.get('remaining', 'N/A')}/{rate_info.get('limit', 'N/A')} - Reset at: {datetime.fromtimestamp(rate_info.get('reset', 0)).strftime('%Y-%m-%d %H:%M:%S')}")
        
        return tweets
    
    except tweepy.TooManyRequests as e:
        log(f"Rate limit exceeded: {str(e)}", always=True)
        log(f"Exception details: {repr(e)}", always=True)
        # Try to extract reset time from headers
        if hasattr(e, 'response') and e.response is not None:
            reset_time = e.response.headers.get('x-rate-limit-reset')
            if reset_time:
                reset_time_str = datetime.fromtimestamp(int(reset_time)).strftime('%Y-%m-%d %H:%M:%S')
                log(f"Rate limit will reset at: {reset_time_str}", always=True)
        return []
    except tweepy.TweepyException as e:
        log(f"Error fetching tweets: {str(e)}", always=True)
        log(f"Exception details: {repr(e)}", always=True)
        return []

def get_user_id(api, username):
    """
    Get the user ID from username using Twitter API v1.1 with OAuth 1.0a
    """
    log(f"Looking up user ID for username: {username}")
    
    try:
        user = api.get_user(screen_name=username)
        user_id = user.id
        log(f"Found user ID: {user_id} for username: {username}", always=True)
        log(f"User is protected: {user.protected}", always=True)
        return user_id
    except tweepy.TooManyRequests as e:
        log(f"Rate limit exceeded when looking up user: {str(e)}", always=True)
        log(f"Exception details: {repr(e)}", always=True)
        return None
    except tweepy.TweepyException as e:
        log(f"Error getting user ID: {str(e)}", always=True)
        log(f"Exception details: {repr(e)}", always=True)
        return None

def send_sms(account_sid, auth_token, from_number, to_number, message):
    """
    Send SMS using Twilio
    """
    log(f"Sending SMS to {to_number}")
    client = Client(account_sid, auth_token)
    
    try:
        message = client.messages.create(
            body=message,
            from_=from_number,
            to=to_number
        )
        log(f"SMS sent successfully, SID: {message.sid}")
        return message.sid
    except Exception as e:
        log(f"Error sending SMS: {str(e)}", always=True)
        raise

if __name__ == "__main__":
    # For local testing with .env file
    try:
        from dotenv import load_dotenv
        load_dotenv()
        log("Loaded environment variables from .env file")
    except ImportError:
        log("python-dotenv not installed, using system environment variables")
    
    log("Starting Twitter monitor script", always=True)
    
    # Get environment variables for OAuth 1.0a
    consumer_key = os.environ.get('TWITTER_CONSUMER_KEY')
    consumer_secret = os.environ.get('TWITTER_CONSUMER_SECRET')
    access_token = os.environ.get('TWITTER_ACCESS_TOKEN')
    access_token_secret = os.environ.get('TWITTER_ACCESS_TOKEN_SECRET')
    
    account_to_monitor = os.environ.get('TWITTER_ACCOUNT_TO_MONITOR')
    
    twilio_account_sid = os.environ.get('TWILIO_ACCOUNT_SID')
    twilio_auth_token = os.environ.get('TWILIO_AUTH_TOKEN')
    twilio_from_number = os.environ.get('TWILIO_FROM_NUMBER')
    twilio_to_number = os.environ.get('TWILIO_TO_NUMBER')
    
    last_tweet_id = os.environ.get('LAST_TWEET_ID', '')
    first_run = os.environ.get('FIRST_RUN', 'true').lower() == 'true'
    
    log(f"Configuration: monitoring @{account_to_monitor}", always=True)
    log(f"Last tweet ID: {last_tweet_id}", always=True)
    log(f"First run: {first_run}", always=True)
    
    # Validate required env vars
    if not all([consumer_key, consumer_secret, access_token, access_token_secret, 
                account_to_monitor, twilio_account_sid, twilio_auth_token, 
                twilio_from_number, twilio_to_number]):
        log("Missing required environment variables", always=True)
        sys.exit(1)
    
    # Set up OAuth 1.0a authentication
    auth = tweepy.OAuth1UserHandler(
        consumer_key, consumer_secret,
        access_token, access_token_secret
    )
    api = tweepy.API(auth)
    
    # Verify credentials
    try:
        me = api.verify_credentials()
        log(f"Authenticated as: @{me.screen_name}", always=True)
    except tweepy.TweepyException as e:
        log(f"Authentication failed: {str(e)}", always=True)
        sys.exit(1)
    
    # Get user ID from username
    user_id = get_user_id(api, account_to_monitor)
    if not user_id:
        log(f"Could not find user ID for {account_to_monitor}", always=True)
        sys.exit(1)
    
    log(f"Using user_id: {user_id} for further API calls", always=True)
    
    # Get latest tweets
    tweets = get_latest_tweets(api, user_id, last_tweet_id)
    
    if not tweets:
        log("No new tweets found or error occurred", always=True)
        sys.exit(0)
    
    # Process tweets
    if tweets:
        newest_id = str(tweets[0].id)
        log(f"Found {len(tweets)} new tweets. Newest ID: {newest_id}", always=True)
        
        # Set new last tweet ID for next run (modified for local testing)
        log(f"New last tweet ID: {newest_id} (save this to LAST_TWEET_ID for next run)", always=True)
        
        # First run handling - only save the ID, don't send notifications
        if first_run:
            log("First run - saved most recent tweet ID. Will notify for new tweets from now on.", always=True)
            log("Set FIRST_RUN=false for the next run to receive notifications", always=True)
            sys.exit(0)
        
        # Send SMS for each new tweet
        for tweet in reversed(tweets):  # Process oldest to newest
            tweet_text = tweet.full_text if hasattr(tweet, 'full_text') else tweet.text
            tweet_id = tweet.id
            tweet_time = tweet.created_at.strftime("%Y-%m-%d %H:%M:%S") if hasattr(tweet, 'created_at') and tweet.created_at else "Unknown"
            
            log(f"Processing tweet ID: {tweet_id} from {tweet_time}", always=True)
            log(f"Tweet text: {tweet_text[:50]}{'...' if len(tweet_text) > 50 else ''}")
                
            # Format URL to the tweet
            tweet_url = f"https://twitter.com/{account_to_monitor}/status/{tweet.id}"
            
            # Create message with link to tweet
            message = f"New tweet from @{account_to_monitor}: {tweet_text[:100]}{'...' if len(tweet_text) > 100 else ''}\n{tweet_url}"
            
            try:
                send_sms(
                    twilio_account_sid, 
                    twilio_auth_token,
                    twilio_from_number,
                    twilio_to_number,
                    message
                )
                log(f"Sent SMS notification for tweet ID: {tweet.id}", always=True)
            except Exception as e:
                log(f"Error sending SMS: {str(e)}", always=True)
    else:
        log("No new tweets found", always=True)
    
    log("Twitter monitor script completed", always=True)
