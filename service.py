"""service file"""
import os

import praw

from donation_sticky import DonationSticky

if __name__ == "__main__":
    """main service function"""

    reddit = praw.Reddit(
        client_id=os.environ["client_id"],
        client_secret=os.environ["client_secret"],
        refresh_token=os.environ["refresh_token"],
        user_agent="linux:donation_sticky:v1.0 (by /u/jenbanim)"
    )
    bot = DonationSticky(
        reddit,
        os.environ["subreddit"],
        os.environ["amf_url"],
        os.environ["dt_title"],
        os.environ["dt_author"]
    )
    while True:
        bot.listen()
