import json
import logging
import os
import requests
import sqlite3
import time
import threading
from dataclasses import dataclass
from datetime import datetime, timezone, timedelta
from requests import HTTPError
from typing import Tuple
from urllib.parse import quote

import discord
from discord import app_commands
from discord.ext import tasks

from db import init_db, get_db

"""
Main scheduled job:
- Run on some interval (eg. 15 mins)
- Fetch list of all clan members (cache)
- Fetch https://apps.runescape.com/runemetrics/profile/profile?user=Philly+PD&activities=20 per user
- Look for json['activities'][n]['text'] == "Capped at my Clan Citadel."
- Create a list of all users that capped and include the event date
- Query db to get a list of all users who already capped this week
- Filter out any new users if they've already capped
- Insert newly capped users into sqlite db with (rsn,date,automatic)

Name changes?
- If someone caps then changes their name their old name would appear in the list still. Admin has to map that to new name.

Build tick:
- time isn't consistent. Depends when first person enters, and shifts at least a few minutes each week

Commands:
- /caplist <days=7>
    - list the users who capped in the last n days and the date the capped

Stretch
- /set-user-capped <rsn> <cap-date (default=now)>
    - INSERT (rsn,date,manual,admin who ran command)
- /set-user-not-capped
"""

LOG_NAME = "CapBot"
CLAN_NAME = "Vought"
MAX_FAILURES = 5

def get_date_timestamp(date:str) -> float:
    dt = datetime.strptime(date, "%d-%b-%Y %H:%M")
    dt = dt.replace(tzinfo=timezone.utc)
    return dt.timestamp()

def timestamp_to_date(timestamp) -> str:
    dt = datetime.fromtimestamp(timestamp, tz=timezone.utc)
    return dt.strftime("%d-%b-%Y %H:%M")

@dataclass
class ClanMember:
    rsn:str
    rank:str
    total_xp:int
    kills:int

def fetch_clan_members(clan_name:str) -> list[ClanMember]:
    url = f"https://secure.runescape.com/m=clan-hiscores/members_lite.ws?clanName={clan_name}"
    response = requests.get(url)
    response.raise_for_status()
    content = response.text

    clan_members:list[ClanMember] = []
    rows = content.split("\n")
    for row in rows[1:]:
        entry = row.split(",")
        if len(entry) < 4:
            continue

        clan_members.append(ClanMember(
            rsn=entry[0].replace("\xa0", " ").strip(),
            rank=entry[1].strip(),
            total_xp=int(entry[2]),
            kills=int(entry[3])
        ))
    return clan_members

@dataclass
class Activity:
    date:str
    details:str
    text:str

def fetch_user_activites(rsn:str, num_activities:int=20) -> list[Activity]:
    log = logging.getLogger(LOG_NAME)

    encoded_rsn = quote(rsn)
    url = f"https://apps.runescape.com/runemetrics/profile/profile?user={encoded_rsn}&activities={num_activities}"
    response = requests.get(url)
    response.raise_for_status()
    jdata = response.json()
    if "error" in jdata:
        error_message = jdata['error']
        if error_message == "PROFILE_PRIVATE":
            log.warning(f"Error fetching alog for {rsn}: User's ALog is private.")
        else:
            log.error(f"Error fetching alog for {rsn}: {jdata['error']}")
        return []
    
    activities = jdata.get("activities")
    if activities is None:
        log.warning(f"No activies found for user {rsn}. Response: {response.text}")
        return []
    
    activity_list:list[Activity] = []
    for activity in activities:
        activity_list.append(Activity(
            date=activity["date"],
            details=activity["details"],
            text=activity["text"]
        ))
    return activity_list

def get_cap_events(activities:list[Activity]) -> list[Activity]:
    cap_events = []
    for activity in activities:
        if activity.text == "Capped at my Clan Citadel.":
            cap_events.append(activity)
    return cap_events

def get_clan_cap_events(clan_name:str, cancel_event:threading.Event, max_events:int=-1):
    log = logging.getLogger("CapBot")
    try:
        log.info(f"Fetching clan members for {clan_name}")
        clan_members:list[ClanMember] = fetch_clan_members(clan_name)
    except Exception as ex:
        log.exception(f"Failed to fetch clan members for {clan_name}: {ex}")
        return {}

    #start_time = time.time()
    request_delay = 10
    num_success = 0
    num_failures = 0
    index = 0
    user_cap_events:list[Tuple[str, int]] = [] # [(rsn,timestamp)]
    while index < len(clan_members):
        if cancel_event.is_set():
            return user_cap_events
        
        member = clan_members[index]
        #elapsed_time = time.time() - start_time
        total_requests = num_failures + num_success
        try:
            # if total_requests > 0 and total_requests % 15 == 0:
            #     # Rate limiting seems to kick in every 15 requests, so wait long
            #     time.sleep(15)
            # else:
            time.sleep(3) # stay within 20 requests/minute

            log.debug(f"Fetching alog for {member.rsn}")
            activities = fetch_user_activites(member.rsn)
            activities = get_cap_events(activities)
            for activity in activities:
                timestamp = get_date_timestamp(activity.date)
                user_cap_events.append((member.rsn, timestamp))

            num_success += 1
            if max_events > 0 and num_success >= max_events:
                break
            index += 1
            request_delay = 10 # Reset as we had a success

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
            log.exception(f"Failed to fetch user activities for {member.rsn}: {ex}")
            num_failures += 1
            if num_failures > MAX_FAILURES:
                log.error(f"Exceeded max failures for fetching user activites. Stopping further queries.")
                return user_cap_events
            index += 1 # skip this user
            continue
    
    return user_cap_events

def fetch_cap_event_task(cancel_event:threading.Event):
    log = logging.getLogger(LOG_NAME)
    start_time = time.time()
    log.debug("Starting fetch_cap_event_task...")

    cap_events = get_clan_cap_events(CLAN_NAME, cancel_event)

    insert_rows = [(event[0], event[1], "auto") for event in cap_events]
    log.debug(f"Attempting to insert rows: {insert_rows}")
    with get_db() as dbcon:
        cur = dbcon.executemany("INSERT OR IGNORE INTO cap_events(rsn, cap_timestamp, source) VALUES(?,?,?)", insert_rows)
        log.debug(f"Inserted {cur.rowcount} new rows.")

    log.debug(f"fetch_cap_event_task completed after {time.time() - start_time} seconds.")

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
        self.tree.copy_global_to(guild=self.guild_id)
        await self.tree.sync(guild=self.guild_id)

    async def on_ready(self):
        self.logger.info("ready")
        print(f'Logged on as {self.user}!')
        self.update_database_task.start()

    async def close(self):
        self.logger.debug("Waiting for fetch_cap_event_task thread to exit...")
        if self.task_thread and self.task_thread.is_alive():
            self.task_cancel_event.set()
            self.task_thread.join(timeout=30)
            if self.task_thread.is_alive():
                self.logger.error("Timed out waiting for fetch_cap_event_task thread to join.")
        super().close()

    @tasks.loop(minutes=15)
    async def update_database_task(self):
        if self.task_thread and self.task_thread.is_alive():
            self.logger.error("fetch_cap_event_task thread is still alive. Skipping update")
            return

        self.logger.debug("Starting fetch_cap_event_task thread")
        self.task_thread = threading.Thread(target=fetch_cap_event_task, args=(self.task_cancel_event,))
        self.task_thread.start()

    @update_database_task.before_loop
    async def before_update_database_task(self):
        self.logger.debug("Waiting until ready to start update_database_task")
        await self.wait_until_ready()
        self.logger.debug("Ready")

intents = discord.Intents.default()
discord_client = DiscordClient(intents)

@discord_client.tree.command(name="test", description="Test command")
async def test_command(interaction:discord.Interaction):
    await interaction.response.send_message("Hello")

@discord_client.tree.command(name="caplist", description="Get the list of users that have capped in the last N days.")
async def caplist(interaction:discord.Interaction, days:int=7):
    now = datetime.now(timezone.utc)
    start_date = now - timedelta(days=days)
    timestamp = int(start_date.timestamp()) # Truncate as we only care about seconds
    with get_db() as db:
        con = db.execute(f"SELECT rsn,cap_timestamp FROM cap_events WHERE cap_timestamp >= {timestamp}")
        results = con.fetchall()
        rows = [(row[0], row[1]) for row in results]
        rows.sort(key=lambda pair: pair[1], reverse=True) # sort by date

        # Find longest username
        longest_name = 0
        longest_date = 0
        for rsn, timestamp in rows:
            longest_name = max(longest_name, len(rsn))
            longest_date = max(longest_date, len(timestamp_to_date(timestamp)))

        column_headers = ["RSN", "Cap Date"]
        vertical_bars = len(column_headers) + 1
        padding = len(column_headers) * 2
        table_width = longest_name + longest_date + vertical_bars + padding

        message = f"### Users that have capped in the last {days} days:\n"
        message += "```\n" + ('-' * table_width) + "\n"

        for rsn, timestamp in results:
            date = timestamp_to_date(timestamp)
            message += f"| {rsn:<{longest_name}} | {date:<{longest_date}} |\n"
        message += ('-' * table_width) + "```"
    await interaction.response.send_message(message, ephemeral=True)

def run_bot():
    token = os.getenv("BOT_TOKEN")
    discord_client.run(token=token)

if __name__ == "__main__":
    run_bot()