import logging
import os
import sys
import time
from datetime import datetime
from urllib.parse import unquote

import requests

BARK_KEY = os.environ["BARK_KEY"]
PASSWORD = os.environ["ROUTER_PASSWORD"]
ROUTER_ADDR = os.environ["ROUTER_ADDR"]
TICK_INTERVAL = 2000  # 2s
OFFLINE_TICKS = 100  # 200s

session = requests.Session()
session.trust_env = False
logging.basicConfig(
    level=logging.INFO, format="[%(asctime)s] %(message)s", datefmt="%Y-%m-%d %H:%M:%S"
)

all_hosts: dict[str, dict] = {}
online_hosts: set[str] = set()
offline_ticks: dict[str, int] = {}


class Error(Exception):
    def __init__(self, code: int, *args) -> None:
        super().__init__(code, *args)
        self.code = code


def login(password: str) -> str:
    params = {"method": "do", "login": {"password": password}}
    resp = session.post(f"http://{ROUTER_ADDR}/", json=params, timeout=1)
    data = resp.json()
    if data["error_code"] != 0:
        raise Error(data["error_code"], "login error")
    return data["stok"]


def get_online_hosts(stok: str) -> dict[str, dict]:
    url = f"http://{ROUTER_ADDR}/stok={stok}/ds"
    params = {
        "hosts_info": {"table": "online_host"},
        "network": {"name": "iface_mac"},
        "method": "get",
    }
    resp = session.post(url, json=params, timeout=1)
    data = resp.json()
    if data["error_code"] != 0:
        raise Error(data["error_code"], "get online hosts error")

    hosts = data["hosts_info"]["online_host"]
    result = {}
    for host in hosts:
        h = list(host.values())[0]
        h["hostname"] = unquote(h["hostname"])
        result[h["mac"]] = h
    return result


def notify(current: list[str], be_online: list[str], be_offline: list[str]) -> None:
    title = []
    body = [datetime.now().strftime("%Y-%m-%d %H:%M:%S")]

    def render(hosts: list[str], action: str) -> None:
        if not hosts:
            return
        hosts.sort(key=lambda mac: all_hosts[mac]["ip"])
        title.append(f"{len(be_online)} 个设备{action}")
        body.append(f"{len(be_online)} 个设备{action}:")
        for i, mac in enumerate(be_online, start=1):
            host = all_hosts[mac]
            body.append(f"{i}. {host['mac']} *{host['ip']}* {host['hostname']}")

    render(be_online, "上线")
    render(be_offline, "下线")

    body.append("当前在线设备:")
    current.sort(key=lambda mac: all_hosts[mac]["ip"])
    for i, mac in enumerate(current, start=1):
        host = all_hosts[mac]
        body.append(f"{i}. {host['mac']} *{host['ip']}* {host['hostname']}")

    title = ", ".join(title)
    body = "\n".join(body)
    print(body)
    session.post(f"https://api.day.app/{BARK_KEY}/{title}/{body}?group=WiFi")


def run() -> None:
    stok = login(PASSWORD)

    last_run = 0
    auth_fails = 0
    while True:
        now = int(time.monotonic() * 1000)
        if now - last_run < TICK_INTERVAL:
            time.sleep(0.1)
            continue
        last_run = now
        try:
            current = get_online_hosts(stok)
            auth_fails = 0
        except Error as e:
            logging.error(f"get online hosts error: {e!r}")
            if e.code == -40401:
                auth_fails += 1
                if auth_fails >= 3:
                    raise
                stok = login(PASSWORD)
            continue
        except Exception as e:
            logging.error(f"get online hosts error: {e!r}")
            continue

        be_online = current.keys() - online_hosts
        be_offline = set()
        for mac in current.keys():
            offline_ticks[mac] = 0
        for mac in online_hosts - current.keys():
            offline_ticks[mac] = offline_ticks.get(mac, 0) + 1
            if offline_ticks[mac] >= OFFLINE_TICKS:
                be_offline.add(mac)
                offline_ticks[mac] = 0
                online_hosts.remove(mac)

        online_hosts.update(be_online)
        all_hosts.update(current)

        if be_online or be_offline:
            try:
                notify(list(current.keys()), list(be_online), list(be_offline))
            except Exception:
                logging.exception("notify failed")


def main() -> None:
    try:
        run()
    except Exception as e:
        print(f"Error: {e!r}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
