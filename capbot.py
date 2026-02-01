import json
import requests
import logging
import sqlite3
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from requests import HTTPError
from typing import Tuple
from urllib.parse import quote

from discord import app_commands
from discord.ext import tasks

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

CLAN_NAME = "Vought"
MAX_FAILURES = 5

def get_date_timestamp(date:str):
    dt = datetime.strptime(date, "%d-%b-%Y %H:%M")
    dt = dt.replace(tzinfo=timezone.utc)
    return dt.timestamp()

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
    log = logging.getLogger("CapBot")

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

def get_clan_cap_events(clan_name:str, max_events:int=-1):
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

def init_log():
    log = logging.getLogger("CapBot")
    log.setLevel(logging.DEBUG)
    formatter = logging.Formatter("%(asctime)s [%(threadName)-12.12s] [%(levelname)-5.5s]  %(message)s")

    console_handler = logging.StreamHandler()
    console_handler.setFormatter(formatter)
    log.addHandler(console_handler)

    file_handler = logging.FileHandler("capbot.log", "w")
    file_handler.setFormatter(formatter)
    log.addHandler(file_handler)
    return log

def init_db():
    con = sqlite3.connect("capdata.db")
    cur = con.cursor()
    cur.execute("""
        CREATE TABLE IF NOT EXISTS cap_events(
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            rsn TEXT NOT NULL,
            cap_timestamp INTEGER NOT NULL,
            source TEXT,
            manual_user TEXT,
            
            UNIQUE(rsn, cap_timestamp)
        )
    """)
    return con

def main():
    log = init_log()
    dbcon = init_db()

    # We may not be able to ignore events < last timestamp as it depends on when their alog was updated
    #last_timestamp = dbcon.execute("SELECT cap_timestamp FROM cap_events ORDER BY cap_timestamp DESC LIMIT 1").fetchone()

    cap_events = get_clan_cap_events(CLAN_NAME, max_events=10)
    insert_rows = [(event[0], event[1], "auto") for event in cap_events]
    log.debug(f"Attempting to insert rows: {insert_rows}")
    with dbcon:
        cur = dbcon.executemany("INSERT OR IGNORE INTO cap_events(rsn, cap_timestamp, source) VALUES(?,?,?)", insert_rows)
        log.debug(f"Inserted {cur.rowcount} new rows.")

    dbcon.close()

if __name__ == "__main__":
    main()