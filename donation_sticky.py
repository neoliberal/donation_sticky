"""Posts & stickies AMF donation messages in the DT"""
import json
import signal
import sys
import time

from bs4 import BeautifulSoup
from prawcore.exceptions import PrawcoreException
import requests
from slack_python_logging import slack_logger


class DonationSticky(object):
    """Main bot class"""
    __slots__ = ["reddit", "subreddit", "amf_url", "logger", "tracked"]

    def __init__(self, reddit, subreddit, amf_url):
        """initialize DonationSticky"""
        self.reddit = reddit
        self.subreddit = self.reddit.subreddit(subreddit)
        self.amf_url = amf_url
        self.logger = slack_logger.initialize("donation_sticky")
        self.tracked = self.load()

        signal.signal(signal.SIGTERM, self.exit) # for systemd
        self.logger.info("Successfully initialized")

    def exit(self, signum, frame):
        """Save prior to exiting"""
        _ = frame # unused
        self.save()
        self.logger.info("Exited gracefully with signal %s", signum)
        sys.exit(0)

    def load(self):
        """Loads json list of already stickied donations
        
        Useful when restarting the service.
        """
        try:
            with open("tracked_donations.json") as f:
                tracked = json.load(f)
                self.logger.debug("Loaded tracked donations")
                return tracked
        except FileNotFoundError:
            self.logger.debug("No tracked donations, starting fresh")
            return list()

    def save(self):
        """Save json list of already stickied donations"""
        self.logger.debug("Saving tracked donations")
        with open("tracked_donations.json", "w") as f:
            json.dump(self.tracked, f)
            self.logger.debug("Saved pickle file")
                    
    def listen(self):
        """Listen for new donations at AMF url"""
        page_raw = requests.get(self.amf_url)
        page = BeautifulSoup(page_raw.text, "lxml")
        table_id = "ctl00_MainContent_UcFundraiserSponsors1_grdDonors"
        table = page.find(id=table_id)
        if table is None:
            # Not sure why, but this happened once
            time.sleep(60)
            return
        item_class = "TableItemText"

        # The "Gift Aid" column doesn't always appear, so we need to id
        # columns by their text labels
        column_labels = [
            col.get_text().lower()
            for col in table.find("tr", class_ = "TableHeaderStyle") 
            if hasattr(col, "get_text")
        ]
        name_idx = column_labels.index("sponsor")
        location_idx = column_labels.index("location")
        amount_idx = column_labels.index("us$")
        msg_idx = column_labels.index("message")

        donations = []
        for row in table.find_all("tr", class_ = item_class):
            cells = [cell for cell in row.find_all("td")]
            # stripped_strings is the only way to get line breaks that make
            # sense, but it returns lists of one-line strings, and we want one
            # string with many lines, hence this sweet nested comprehension
            items = ["\n".join([l for l in c.stripped_strings]) for c in cells]
            if not any(items):
                # Empty row (ie. there are <20 total donations)
                continue
            name = items[name_idx]
            location = items[location_idx]
            amount = float(items[amount_idx][3:].replace(',', ''))
            message = items[msg_idx]
            donations.insert(0, [name, location, amount, message])

        # Remove posts that are no longer displayed (ie. old or edited)
        for tracked_donation in self.tracked:
            if tracked_donation not in donations:
                self.tracked.remove(tracked_donation)
                self.save()

        for donation in donations:
            name = donation[0]
            amount = donation[2]
            if donation not in self.tracked and amount > 24:
                self.logger.debug("New donation by %s", name)
                self.tracked.append(donation)
                try:
                    self.post_comment(donation)
                except PrawcoreException as e:
                    self.logger.error("Failed to post comment, error: %s", e)
                self.save()

        time.sleep(60)

    def post_comment(self, donation):
        """Stickies the donation message in the DT"""
        submission = self.get_discussion_thread()
        name, location, amount, message = donation
        quote_string = "\n".join(
            [f">{line}" for line in message.split("\n")]
        )
        msg = (
            f"{name} from {location} donated ${amount:.2f} to the charity "+
            f"drive and said:\n\n{quote_string}\n\nTo claim this spot, "+
            f"donate at least $25 to the AMF at {self.amf_url}"
        )
        submission.reply(msg).mod.distinguish(sticky=True)
        self.logger.debug("Stickied donation message from %s", name)

    def get_discussion_thread(self):
        self.logger.debug("Finding discussion thread")
        for submission in self.subreddit.search("Discussion Thread", sort="new"):
            if submission.author == self.reddit.user.me():
                self.logger.debug("Found discussion thread")
                return submission
        self.logger.critial("Could not find discussion thread")