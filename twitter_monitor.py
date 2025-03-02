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

def get_latest_tweets(bearer_token, user_id, since_id=None):
    """
    Get the latest tweets from a specific user using OAuth 2.0 Bearer Token (Twitter API v2)
    """
    log(f"Fetching tweets for user_id={user_id}, since_id={since_id}")
    
    # Create client with Bearer Token (OAuth 2.0)
    client = tweepy.Client(bearer_token=bearer_token)
    
    try:
        # Define tweet fields to retrieve
        tweet_fields = ['created_at', 'text', 'id']
        
        # Get tweets from the user
        if since_id:
            log(f"Getting tweets since ID: {since_id}")
            response = client.get_users_tweets(
                id=user_id,
                max_results=10,
                tweet_fields=tweet_fields,
                since_id=since_id
            )
        else:
            log("No since_id provided, getting most recent tweets")
            response = client.get_users_tweets(
                id=user_id,
                max_results=10,
                tweet_fields=tweet_fields
            )
        
        tweets = response.data or []
        log(f"Fetched {len(tweets)} tweets")
        
        # Log rate limit information if available
        if hasattr(response, 'includes') and 'rate_limit' in response.includes:
            rate_info = response.includes['rate_limit']
            log(f"Rate limit: {rate_info.get('remaining', 'N/A')}/{rate_info.get('limit', 'N/A')} - Reset at: {rate_info.get('reset', 'N/A')}")
        
        return tweets
    
    except tweepy.TooManyRequests as e:
        log(f"Rate limit exceeded: {str(e)}", always=True)
        # Try to extract reset time from headers
        if hasattr(e, 'response') and e.response is not None:
            reset_time = e.response.headers.get('x-rate-limit-reset')
            if reset_time:
                reset_time_str = datetime.fromtimestamp(int(reset_time)).strftime('%Y-%m-%d %H:%M:%S')
                log(f"Rate limit will reset at: {reset_time_str}", always=True)
        return []
    except tweepy.TweepyException as e:
        log(f"Error fetching tweets: {str(e)}", always=True)
        return []

def get_user_id(bearer_token, username):
    """
    Get the user ID from username using Twitter API v2
    """
    log(f"Looking up user ID for username: {username}")
    client = tweepy.Client(bearer_token=bearer_token)
    
    try:
        response = client.get_user(username=username)
        if response.data:
            user_id = response.data.id
            log(f"Found user ID: {user_id} for username: {username}")
            return user_id
        else:
            log(f"User {username} not found", always=True)
            return None
    except tweepy.TooManyRequests as e:
        log(f"Rate limit exceeded when looking up user: {str(e)}", always=True)
        return None
    except tweepy.TweepyException as e:
        log(f"Error getting user ID: {str(e)}", always=True)
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
    log("Starting Twitter monitor script", always=True)
    
    # Get environment variables
    bearer_token = os.environ.get('TWITTER_BEARER_TOKEN')
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
    if not all([bearer_token, account_to_monitor, twilio_account_sid, 
               twilio_auth_token, twilio_from_number, twilio_to_number]):
        log("Missing required environment variables", always=True)
        sys.exit(1)
    
    # Get user ID from username
    user_id = get_user_id(bearer_token, account_to_monitor)
    if not user_id:
        log(f"Could not find user ID for {account_to_monitor}", always=True)
        sys.exit(1)
    
    # Get latest tweets
    tweets = get_latest_tweets(bearer_token, user_id, last_tweet_id)
    
    if not tweets:
        log("No new tweets found or error occurred", always=True)
        sys.exit(0)
    
    # Process tweets
    if tweets:
        newest_id = str(tweets[0].id)
        log(f"Found {len(tweets)} new tweets. Newest ID: {newest_id}", always=True)
        
        # Set new last tweet ID for next run
        print(f"::set-env name=NEW_LAST_TWEET_ID::{newest_id}")
        log(f"Setting NEW_LAST_TWEET_ID to {newest_id}", always=True)
        
        # First run handling - only save the ID, don't send notifications
        if first_run:
            log("First run - saved most recent tweet ID. Will notify for new tweets from now on.", always=True)
            print(f"::set-env name=FIRST_RUN::false")
            sys.exit(0)
        
        # Send SMS for each new tweet
        for tweet in reversed(tweets):  # Process oldest to newest
            tweet_text = tweet.text
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
