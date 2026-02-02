import requests
from dataclasses import dataclass
from urllib.parse import quote

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

@dataclass
class ActivityLog:
    private:bool
    activities:list[Activity]

class PrivateProfileException(Exception):
    pass

class RuneMetricsApiError(Exception):
    pass

def fetch_user_activites(rsn:str, num_activities:int=20) -> list[Activity]:
    encoded_rsn = quote(rsn)
    url = f"https://apps.runescape.com/runemetrics/profile/profile?user={encoded_rsn}&activities={num_activities}"
    response = requests.get(url)
    response.raise_for_status()
    jdata = response.json()
    if "error" in jdata:
        error_message = jdata['error']
        if error_message == "PROFILE_PRIVATE":
            raise PrivateProfileException(f"Error fetching alog for {rsn}: User's ALog is private.")
        else:
            raise RuneMetricsApiError(f"Error fetching alog for {rsn}: {jdata['error']}")
    
    activities = jdata.get("activities")
    if activities is None:
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