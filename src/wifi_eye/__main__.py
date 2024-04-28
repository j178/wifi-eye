import os
import sys
import time
from datetime import datetime

import requests

BARK_KEY = os.environ["BARK_KEY"]
PASSWORD = os.environ["PASSWORD"]
TICK_INTERVAL = 2000  # 2s
OFFLINE_TICKS = 100  # 200s

session = requests.Session()
session.trust_env = False

all_hosts: dict[str, dict] = {}
online_hosts: set[str] = set()
offline_ticks: dict[str, int] = {}


def login(password: str) -> str:
    params = {"method": "do", "login": {"password": password}}
    resp = session.post("http://192.168.0.1/", json=params, timeout=1)
    data = resp.json()
    if data["error_code"] != 0:
        raise Exception(f"login error: {data['error_code']}")
    return data["stok"]


def get_online_hosts(stok: str) -> dict[str, dict]:
    url = f"http://192.168.0.1/stok={stok}/ds"
    params = {
        "hosts_info": {"table": "online_host"},
        "network": {"name": "iface_mac"},
        "method": "get",
    }
    resp = session.post(url, json=params, timeout=1)
    data = resp.json()
    if data["error_code"] != 0:
        raise Exception(f"get online hosts error: {data['error_code']}")

    hosts = data["hosts_info"]["online_host"]
    result = {}
    for host in hosts:
        h = list(host.values())[0]
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
    for i, host in enumerate(current, start=1):
        host = all_hosts[host]
        body.append(f"{i}. {host['mac']} *{host['ip']}* {host['hostname']}")

    title = ", ".join(title)
    body = "\n".join(body)
    session.post(f"https://api.day.app/{BARK_KEY}/{title}/{body}?group=WiFi")
    print(body)


def main():
    stok = login(PASSWORD)

    last_run = int(time.time() * 1000)
    while True:
        now = int(time.time() * 1000)
        if now < last_run or now - last_run < TICK_INTERVAL:
            time.sleep(0.1)
            continue
        last_run = now
        try:
            current = get_online_hosts(stok)
        except Exception as e:
            print(f"get online hosts error: {e!r}")
            continue

        be_online = current.keys() - online_hosts
        be_offline = set()
        for host in current.keys():
            offline_ticks.pop(host, None)
        for host in online_hosts - current.keys():
            offline_ticks[host] = offline_ticks.get(host, 0) + 1
            if offline_ticks[host] >= OFFLINE_TICKS:
                be_offline.add(host)
                offline_ticks[host] = 0
                online_hosts.remove(host)

        online_hosts.update(be_online)
        all_hosts.update(current)

        if be_online or be_offline:
            notify(list(current.keys()), list(be_online), list(be_offline))


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        sys.exit(1)
