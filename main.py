import requests
import datetime
import re
import os
import json
import base64

from pprint import pprint
from enum import Enum, StrEnum, auto
from typing import Optional


BASE_API = "https://discord.com/api/v9"

WEB_USER_AGENT = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36"
CLIENT_USER_AGENT = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) discord/1.0.9175 Chrome/128.0.6613.186 Electron/32.2.7 Safari/537.36"

DEFAULT_BUILD_NUMBER = 507104

POLLING_INTERVAL = 60
HEARTBEAT_INTERVAL = 20
DO_NON_ORB_QUESTS = False
AUTO_ACCEPT_QUESTS = True


class LogLevel(StrEnum):
    INFO = "INFO"
    ERROR = "ERROR"
    WARNING = "WARNING"


def log(msg: str, level: LogLevel = LogLevel.INFO):
    print(f"[{datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] [{level.value}] {msg}")


def fetch_latest_build_number() -> Optional[int]:
    r = requests.get(
        "https://discord.com/app",
        headers={"User-Agent": WEB_USER_AGENT},
    )

    if r.status_code != 200:
        log(f"Failed to fetch Discord app page: {r.status_code}", LogLevel.ERROR)
        return None

    js_script_path = re.findall(r'src="/(assets/web[^"]+\.js)"', r.text)

    if not js_script_path:
        log("Failed to find web asset script in Discord app page", LogLevel.ERROR)
        return None
    
    js_script_path = js_script_path[0]

    r = requests.get(
        f"https://discord.com/{js_script_path}",
        headers={"User-Agent": WEB_USER_AGENT},
    )

    build_number = re.search(r'buildNumber["\s:]+["\s]*(\d{5,7})', r.text)

    if not build_number:
        log("Failed to find build number in web asset script", LogLevel.ERROR)
        return None
    
    log(f"Latest Discord build number: {build_number.group(1)}")
    return int(build_number.group(1))


def generate_super_properties(build_number: int) -> str:
    super_properties = {
        "os": "Windows",
        "browser": "Discord Client",
        "release_channel": "stable",
        "client_version": "1.0.9175",
        "os_version": "10.0.26100",
        "os_arch": "x64",
        "app_arch": "x64",
        "system_locale": "en-US",
        "browser_user_agent": CLIENT_USER_AGENT,
        "browser_version": re.search(r"Electron/(\d+\.\d+\.\d+)", CLIENT_USER_AGENT).group(1),
        "client_build_number": build_number,
        "native_build_number": 59498,
        "client_event_source": None,
    }

    log(f"Generated super properties: {json.dumps(super_properties, separators=(',', ':'))}", LogLevel.INFO)

    super_properties_str = json.dumps(super_properties, separators=(",", ":"))
    super_properties_encoded = super_properties_str.encode("utf-8")
    super_properties_b64 = base64.b64encode(super_properties_encoded).decode("utf-8")

    return super_properties_b64


def filter_expired_quests(quests: list) -> list:
    available_quests = []
    now = datetime.datetime.now(datetime.timezone.utc)

    for quest in quests:
        expires_at_str = quest["config"]["expires_at"]
        
        expires_at = datetime.datetime.fromisoformat(expires_at_str.replace("Z", "+00:00"))

        if expires_at > now:
            available_quests.append(quest)
    
    return available_quests


def filter_non_orb_quests(quests: list) -> list:
    orb_quests = []

    for quest in quests:
        for reward in quest["config"]["rewards_config"]["rewards"]:
            if reward["type"] == 4: # Orb reward type
                orb_quests.append(quest)
                break
    
    return orb_quests


def filter_completed_quests(quests: list) -> list:
    incomplete_quests = []

    for quest in quests:
        if quest["user_status"] is None \
        or quest["user_status"]["completed_at"] is None:
            incomplete_quests.append(quest)
    
    return incomplete_quests


class DiscordSession:
    def __init__(self, token: str, build_number: int) -> None:
        self.token = token
        self.build_number = build_number

        self.session = requests.Session()
        self.session.headers.update({
            "Authorization": token,
            "Content-Type": "application/json",
            "Accept": "*/*",
            "Accept-Language": "en-US,en;q=0.9",
            "User-Agent": CLIENT_USER_AGENT,
            "X-Super-Properties": generate_super_properties(build_number),
            "X-Discord-Locale": "en-US",
            "X-Discord-Timezone": "Asia/Ho_Chi_Minh",
            "Origin": "https://discord.com",
            "Referer": "https://discord.com/channels/@me",
        })

        if not self._validate_token():
            raise ValueError("Invalid token provided")

    def _validate_token(self) -> bool:
        r = self.session.get(f"{BASE_API}/users/@me")

        if r.status_code == 200:
            log(f"Token {self.token[:4]}...{self.token[-4:]} is valid")
            return True
        else:
            log(f"Token {self.token[:4]}...{self.token[-4:]} validation failed: {r.status_code} - {r.text}", LogLevel.ERROR)
            return False
        
    def fetch_all_quests(self) -> Optional[list]:
        r = self.session.get(f"{BASE_API}/quests/@me")

        if r.status_code != 200:
            log(f"Failed to fetch quests: {r.status_code} - {r.text}", LogLevel.ERROR)
            return None
        
        data = r.json()
        return data.get("quests", None)
    


def init_session(token: str, build_number: int):
    log(f"Initializing session for token: {token[:4]}...{token[-4:]}")
    
    try:
        session = DiscordSession(token, build_number)
    except ValueError as e:
        log(str(e), LogLevel.ERROR)
        log(f"Skipping token: {token[:4]}...{token[-4:]}", LogLevel.WARNING)
        return
    
    available_quests = session.fetch_all_quests()
    available_quests = filter_expired_quests(available_quests)
    available_quests = filter_completed_quests(available_quests)

    if not DO_NON_ORB_QUESTS:
        available_quests = filter_non_orb_quests(available_quests)

    log(f"Available quests for token {token[:4]}...{token[-4:]}: {len(available_quests)}", LogLevel.INFO)    
    


if __name__ == "__main__":
    latest_build_number = fetch_latest_build_number()

    if latest_build_number is None:
        log("Using default build number", LogLevel.WARNING)
        latest_build_number = DEFAULT_BUILD_NUMBER

    token_list = os.environ.get("TOKENS").split(",")

    for token in token_list:
        init_session(token.strip(), latest_build_number)