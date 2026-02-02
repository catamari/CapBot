import logging
import os
import time
import threading
from datetime import datetime, timezone, timedelta
from requests import HTTPError

import discord
from discord import app_commands
from discord.ext import tasks

from db import init_db, get_db
from rsapi import *

LOG_NAME = "CapBot"
CLAN_NAME = "Unknown"
MAX_FAILURES = 5
MAX_USER_QUERIES = 20
UPDATE_LOOP_MINUTES = 1

def get_date_timestamp(date:str) -> float:
    """ Parses the date from a date string (RS Alog format) and returns it as a timestamp. """
    dt = datetime.strptime(date, "%d-%b-%Y %H:%M")
    dt = dt.replace(tzinfo=timezone.utc)
    return dt.timestamp()

def timestamp_to_date(timestamp) -> str:
    """ Converts a timestamp into a date string (RS Alog format). """
    dt = datetime.fromtimestamp(timestamp, tz=timezone.utc)
    return dt.strftime("%d-%b-%Y %H:%M")

def get_offset_from_now_timestamp(delta:timedelta) -> int:
    """ Returns a timestamp of the current time (UTC) minus the provided delta. """
    now = datetime.now(timezone.utc)
    start_date = now - delta
    return int(start_date.timestamp()) # Truncate as we only care about seconds

def get_user_activities(users:list[str], cancel_event:threading.Event, num_activities:int=20) -> dict[str, ActivityLog]:
    """
    Fetches the adventure's log for each user in the list.
    Handles Jamflex's extreme rate limiting.
    Returns a dict of rsn -> ActivityLog.
    """
    log = logging.getLogger("CapBot")
    log.debug(f"Fetching last {num_activities} activities for {len(users)} users.")

    request_delay = 10
    num_failures = 0
    index = 0
    activity_dict = {}
    while index < len(users):
        if cancel_event.is_set():
            return activity_dict
        
        rsn = users[index]
        try:
            time.sleep(1) # delay between each request to reduce 429 errors

            log.debug(f"Fetching alog for {rsn}")
            activities = fetch_user_activites(rsn, num_activities)
            activity_dict[rsn] = ActivityLog(private=False, activities=activities)

            index += 1
            request_delay = 10 # Reset as we had a success

        except PrivateProfileException:
            log.warning(f"Failed to fetch activities for {rsn}: runemetrics profile is private")
            activity_dict[rsn] = ActivityLog(private=True, activities=[])
            index += 1

        except HTTPError as http_error:
            if http_error.response.status_code == 429: # Too many requests
                log.warning(f"Received 'Too many requests' response. Waiting {request_delay} seconds")
                time.sleep(request_delay)
                request_delay *= 2 # double each time
                if request_delay > 100:
                    log.error("Max request delay exceeded. Skipping further requests")
                    break
                # Don't increment index so we retry
                continue
            raise http_error # unhandled; fallback to below block
        
        except Exception as ex:
            log.exception(f"Failed to fetch user activities for {rsn}: {ex}")
            num_failures += 1
            if num_failures > MAX_FAILURES:
                log.error(f"Exceeded max failures for fetching user activites. Stopping further queries.")
                return activity_dict
            index += 1 # skip this user
            continue
    
    return activity_dict

def update_task(cancel_event:threading.Event):
    """
    Background task to update the activity database for all the clan members.

    To avoid having a very large delay between someone capping and the bot detecting it, we have to do a fair amount of work due to the API limits.
    The API only allows roughly 15-20 requests/minute and is very aggressive with 'Too many request' errors which force you to wait an additional 10-30 seconds.
    To deal with this we only query 20 users each update and run the update more often.
    We also only query users who have recent (1 week) activity to bias more active players, but we force an update for a player if we haven't checked in over a day.
    If a users's alog is private we also only check once a day.
    """
    log = logging.getLogger(LOG_NAME)
    start_time = time.time()
    log.debug("Starting update_task...")

    # Fetch all clan members from rs api so we always have up to date list.
    try:
        log.info(f"Fetching clan members for {CLAN_NAME}")
        clan_members:list[ClanMember] = fetch_clan_members(CLAN_NAME)
    except Exception as ex:
        log.exception(f"Failed to fetch clan members for {CLAN_NAME}: {ex}")
        return

    with get_db() as dbcon:
        # Insert any new rsns into the activity table. We default the timestamps to 0 to ensure they'll be queried in the next step.
        rows = [(member.rsn,0,0) for member in clan_members]
        cur = dbcon.executemany("INSERT OR IGNORE INTO user_activity(rsn, last_activity_timestamp, last_query_timestamp) VALUES(?,?,?)", rows)
        log.debug(f"Added {cur.rowcount} new users into the user_activity table.")

        # Get all users that have been active in the last week, or we haven't checked recently. Prioritize stale queries to ensure active users don't hog the queue.
        recently_checked_timestamp = get_offset_from_now_timestamp(timedelta(minutes=5)) 
        recent_activity_timestamp = get_offset_from_now_timestamp(timedelta(days=7))
        stale_activity_timestamp = get_offset_from_now_timestamp(timedelta(days=1))
        cur = dbcon.execute(f"""
            SELECT rsn 
            FROM user_activity 
            WHERE 
                (private = 0 AND last_activity_timestamp < {recent_activity_timestamp} AND last_query_timestamp < {recently_checked_timestamp})
                OR last_query_timestamp < {stale_activity_timestamp} 
            ORDER BY last_query_timestamp ASC""")
        users_to_query = [row[0] for row in cur.fetchall()]

    if len(users_to_query) == 0:
        log.debug("No users to query.")
        return

    cap_events = []
    latest_activities = []
    private_profiles = set()

    # Only query a few at a time as it's very slow due to Jagex rate limits
    log.debug(f"{len(users_to_query)} total users to query.")
    users_to_query = users_to_query[:MAX_USER_QUERIES]

    # Query the user alogs. 
    user_activities:dict[str, ActivityLog] = get_user_activities(users_to_query, cancel_event)

    for rsn, activity_log in user_activities.items():
        if activity_log.private:
            private_profiles.add(rsn)
            continue

        # Find any cap events
        for activity in get_cap_events(activity_log.activities):
            timestamp = get_date_timestamp(activity.date)
            cap_events.append({"rsn": rsn, "cap_timestamp": timestamp})

        # Get latest activity date, which is always the first activity in the list
        if len(activity_log.activities) > 0:
            timestamp = get_date_timestamp(activity_log.activities[0].date)
            latest_activities.append({"rsn": rsn, "last_activity_timestamp": timestamp})

    with get_db() as dbcon:
        # Add new cap events
        insert_rows = [(event["rsn"], event["cap_timestamp"], "auto") for event in cap_events]
        log.debug(f"Attempting to insert rows: {insert_rows}")
        cur = dbcon.executemany("INSERT OR IGNORE INTO cap_events(rsn, cap_timestamp, source) VALUES(?,?,?)", insert_rows)
        log.debug(f"Inserted {cur.rowcount} new rows into cap_events. Rows = {insert_rows}")

        # Update user_activity table with last activities/query time.
        # Hard-coding private to false since it can't be true if we have activities.
        now = datetime.now(timezone.utc).timestamp()
        user_activity_rows = [(event["last_activity_timestamp"], now, event["rsn"]) for event in latest_activities]
        cur = dbcon.executemany("UPDATE user_activity SET last_activity_timestamp = ?, last_query_timestamp = ?, private = 0 WHERE rsn = ?", user_activity_rows)
        log.debug(f"Updated last_activity_timestamp for {cur.rowcount} rows in user_activity. Rows = {user_activity_rows}")

        # Update query time for users we queried but got no activity data from. This may be due to private alogs.
        no_activity_rows = [(now, (1 if rsn in private_profiles else 0), rsn) for rsn in users_to_query if rsn not in user_activities or len(user_activities[rsn].activities) == 0]
        cur = dbcon.executemany("UPDATE user_activity SET last_query_timestamp = ?, private = ? WHERE rsn = ?", no_activity_rows)
        log.debug(f"Updated last_query_timestamp for {cur.rowcount} in-active users in user_activity. Rows = {no_activity_rows}")

    log.debug(f"update_task completed after {time.time() - start_time} seconds.")

def init_log():
    log = logging.getLogger(LOG_NAME)
    log.setLevel(logging.DEBUG)
    formatter = logging.Formatter("%(asctime)s [%(threadName)-12.12s] [%(levelname)-5.5s]  %(message)s")

    console_handler = logging.StreamHandler()
    console_handler.setFormatter(formatter)
    log.addHandler(console_handler)

    file_handler = logging.FileHandler("capbot.log", "w")
    file_handler.setFormatter(formatter)
    log.addHandler(file_handler)

    log.info("CapBot log opened.")
    return log

init_log()
init_db()

class DiscordClient(discord.Client):
    def __init__(self, intents:discord.Intents):
        super().__init__(intents=intents)
        self.tree = app_commands.CommandTree(self)
        self.logger = logging.getLogger(LOG_NAME)
        self.guild_id = discord.Object(id=os.getenv("GUILD_ID"))
        self.task_thread = None
        self.task_cancel_event = threading.Event()

    async def setup_hook(self):
        # Copy our slash commands to the discord server we're running in.
        self.tree.copy_global_to(guild=self.guild_id)
        await self.tree.sync(guild=self.guild_id)

    async def on_ready(self):
        self.logger.debug(f'Logged on as {self.user}!')
        # Kick off the update task. We could do this earlier but this way we don't have to wait on it if login fails.
        self.update_database_task.start()

    async def close(self):
        # Kill the update thread before shutting down.
        self.logger.debug("Waiting for update_task thread to exit...")
        if self.task_thread and self.task_thread.is_alive():
            self.task_cancel_event.set()
            self.task_thread.join(timeout=30)
            if self.task_thread.is_alive():
                self.logger.error("Timed out waiting for update_task thread to join.")
        super().close()

    @tasks.loop(minutes=UPDATE_LOOP_MINUTES)
    async def update_database_task(self):
        """ Scheduled looping update to run the background update. """
        if self.task_thread and self.task_thread.is_alive():
            self.logger.error("update_task thread is still alive. Skipping update")
            return

        self.logger.debug("Starting update_task thread")
        self.task_thread = threading.Thread(target=update_task, args=(self.task_cancel_event,))
        self.task_thread.start()


intents = discord.Intents.default()
discord_client = DiscordClient(intents)

@discord_client.tree.command(name="caplist", description="Get the list of users that have capped in the last N days.")
async def caplist(interaction:discord.Interaction, days:int=7):
    now = datetime.now(timezone.utc)
    start_date = now - timedelta(days=days)
    timestamp = int(start_date.timestamp()) # Truncate as we only care about seconds
    with get_db() as db:
        con = db.execute(f"SELECT rsn,cap_timestamp FROM cap_events WHERE cap_timestamp >= {timestamp}")
        rows = [(row[0], row[1]) for row in con.fetchall()]
        rows.sort(key=lambda pair: pair[1], reverse=True) # sort by date

        # Find longest strings in each column so we can pad out the rest to match.
        longest_name = 0
        longest_date = 0
        for rsn, timestamp in rows:
            longest_name = max(longest_name, len(rsn))
            longest_date = max(longest_date, len(timestamp_to_date(timestamp)))

        # Compute table size
        column_headers = ["RSN", "Cap Date"]
        vertical_bars = len(column_headers) + 1
        padding = len(column_headers) * 2
        table_width = longest_name + longest_date + vertical_bars + padding

        message = f"### Users that have capped in the last {days} days:\n"
        message += "```\n" + ('-' * table_width) + "\n" # start code block + first horizontal bar

        # Add table rows
        for rsn, timestamp in rows:
            date = timestamp_to_date(timestamp)
            message += f"| {rsn:<{longest_name}} | {date:<{longest_date}} |\n"
        # Bottom vrtical bar + close code block
        message += ('-' * table_width) + "```"
    await interaction.response.send_message(message, ephemeral=True)

@discord_client.tree.command(name="list-private-alogs", description="List any users that have their alog set to private")
async def list_private_alogs(interaction:discord.Interaction):
    with get_db() as db:
        cur = db.execute("SELECT rsn FROM user_activity WHERE private=1")
        results = cur.fetchall()
        rsns = [f"- {row[0]}" for row in results]
        message = "### Users with private Alogs:\n" + "\n".join(rsns)
        if len(rsns) == 0:
            message += "None"
        await interaction.response.send_message(message, ephemeral=True)

def run_bot():
    token = os.getenv("BOT_TOKEN")
    discord_client.run(token=token)

if __name__ == "__main__":
    CLAN_NAME = os.getenv("CAPBOT_CLAN_NAME")
    run_bot()