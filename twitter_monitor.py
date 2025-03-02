import os
import sys
import tweepy
from twilio.rest import Client

def get_latest_tweets(bearer_token, user_id, since_id=None):
    """
    Get the latest tweets from a specific user using OAuth 2.0 Bearer Token (Twitter API v2)
    """
    # Create client with Bearer Token (OAuth 2.0)
    client = tweepy.Client(bearer_token=bearer_token)
    
    try:
        # Define tweet fields to retrieve
        tweet_fields = ['created_at', 'text', 'id']
        
        # Get tweets from the user
        if since_id:
            response = client.get_users_tweets(
                id=user_id,
                max_results=10,
                tweet_fields=tweet_fields,
                since_id=since_id
            )
        else:
            response = client.get_users_tweets(
                id=user_id,
                max_results=10,
                tweet_fields=tweet_fields
            )
        
        return response.data or []
    
    except tweepy.TweepyException as e:
        print(f"Error fetching tweets: {str(e)}")
        return []

def get_user_id(bearer_token, username):
    """
    Get the user ID from username using Twitter API v2
    """
    client = tweepy.Client(bearer_token=bearer_token)
    
    try:
        response = client.get_user(username=username)
        if response.data:
            return response.data.id
        else:
            print(f"User {username} not found")
            return None
    except tweepy.TweepyException as e:
        print(f"Error getting user ID: {str(e)}")
        return None

def send_sms(account_sid, auth_token, from_number, to_number, message):
    """
    Send SMS using Twilio
    """
    client = Client(account_sid, auth_token)
    
    message = client.messages.create(
        body=message,
        from_=from_number,
        to=to_number
    )
    
    return message.sid

if __name__ == "__main__":
    # Get environment variables
    bearer_token = os.environ.get('TWITTER_BEARER_TOKEN')
    account_to_monitor = os.environ.get('TWITTER_ACCOUNT_TO_MONITOR')
    
    twilio_account_sid = os.environ.get('TWILIO_ACCOUNT_SID')
    twilio_auth_token = os.environ.get('TWILIO_AUTH_TOKEN')
    twilio_from_number = os.environ.get('TWILIO_FROM_NUMBER')
    twilio_to_number = os.environ.get('TWILIO_TO_NUMBER')
    
    last_tweet_id = os.environ.get('LAST_TWEET_ID', '')
    first_run = os.environ.get('FIRST_RUN', 'true').lower() == 'true'
    
    # Validate required env vars
    if not all([bearer_token, account_to_monitor, twilio_account_sid, 
               twilio_auth_token, twilio_from_number, twilio_to_number]):
        print("Missing required environment variables")
        sys.exit(1)
    
    # Get user ID from username
    user_id = get_user_id(bearer_token, account_to_monitor)
    if not user_id:
        print(f"Could not find user ID for {account_to_monitor}")
        sys.exit(1)
    
    # Get latest tweets
    tweets = get_latest_tweets(bearer_token, user_id, last_tweet_id)
    
    if not tweets:
        print("No new tweets found or error occurred")
        sys.exit(0)
    
    # Process tweets
    if tweets:
        newest_id = str(tweets[0].id)
        
        # Set new last tweet ID for next run
        print(f"::set-env name=NEW_LAST_TWEET_ID::{newest_id}")
        
        # First run handling - only save the ID, don't send notifications
        if first_run:
            print("First run - saved most recent tweet ID. Will notify for new tweets from now on.")
            print(f"::set-env name=FIRST_RUN::false")
            sys.exit(0)
        
        # Send SMS for each new tweet
        for tweet in reversed(tweets):  # Process oldest to newest
            tweet_text = tweet.text
                
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
                print(f"Sent SMS notification for tweet ID: {tweet.id}")
            except Exception as e:
                print(f"Error sending SMS: {str(e)}")
    else:
        print("No new tweets found")
