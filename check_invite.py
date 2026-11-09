
#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
Elysian Horizon Discord 邀请码监控
同时支持：
1. Server酱微信通知
2. Pushover iPhone 推送
"""

import json
import os
import sys
from datetime import datetime, timezone

import requests


# =========================
# 配置
# =========================

INVITE_CODE = os.environ.get("INVITE_CODE", "elysianhorizon")

SERVERCHAN_SENDKEY = os.environ.get("SERVERCHAN_SENDKEY", "")

PUSHOVER_USER_KEY = os.environ.get("PUSHOVER_USER_KEY", "")
PUSHOVER_API_TOKEN = os.environ.get("PUSHOVER_API_TOKEN", "")

STATE_FILE = os.environ.get("STATE_FILE", "state.json")

REMIND_AFTER_MINUTES = int(
    os.environ.get("REMIND_AFTER_MINUTES", "30")
)

HEARTBEAT_INTERVAL_HOURS = float(
    os.environ.get("HEARTBEAT_INTERVAL_HOURS", "24")
)

# Pushover 紧急通知：每 60 秒重发，最多持续 1 小时
PUSHOVER_RETRY_SECONDS = 60
PUSHOVER_EXPIRE_SECONDS = 3600

INVITE_URL = f"https://discord.gg/{INVITE_CODE}"

DISCORD_API_URL = (
    f"https://discord.com/api/v10/invites/"
    f"{INVITE_CODE}?with_counts=true"
)

REQUEST_HEADERS = {
    "User-Agent": (
        "ElysianWatcher/1.0 "
        "(+https://github.com/cyanusay/elysian-watcher)"
    )
}


# =========================
# 状态读写
# =========================

def load_state():
    if not os.path.exists(STATE_FILE):
        return {
            "status": "paused",
            "open_since": None,
            "notified_open": False,
            "last_remind_at": None,
            "last_heartbeat": None,
        }

    with open(STATE_FILE, "r", encoding="utf-8") as f:
        return json.load(f)


def save_state(state):
    with open(STATE_FILE, "w", encoding="utf-8") as f:
        json.dump(state, f, ensure_ascii=False, indent=2)

    print(f"[状态] 已保存到 {STATE_FILE}: {state}")


# =========================
# Discord 状态检测
# =========================

def check_invite_status():
    try:
        resp = requests.get(
            DISCORD_API_URL,
            headers=REQUEST_HEADERS,
            timeout=15
        )
    except requests.RequestException as e:
        print(f"[警告] 请求 Discord API 失败: {e}")
        return "paused"

    print(f"[查询] HTTP 状态码: {resp.status_code}")

    if resp.status_code == 200:
        try:
            data = resp.json()
        except ValueError:
            print("[警告] 响应不是合法 JSON。")
            return "paused"

        if data.get("code") != INVITE_CODE and "guild" not in data:
            print("[查询] 返回内容异常，按暂停处理。")
            return "paused"

        features = data.get("guild", {}).get("features", [])

        if "INVITES_DISABLED" in features:
            print("[查询] 检测到 INVITES_DISABLED -> 暂停")
            return "paused"

        print("[查询] 邀请有效且未暂停 -> 开放")
        return "open"

    print(f"[查询] 邀请不可用，HTTP {resp.status_code} -> 暂停")
    return "paused"


# =========================
# 微信通知：Server酱
# =========================

def send_notification(title, content=""):
    if not SERVERCHAN_SENDKEY:
        print("[微信] 未配置 SERVERCHAN_SENDKEY，跳过微信通知。")
        return False

    url = f"https://sctapi.ftqq.com/{SERVERCHAN_SENDKEY}.send"

    try:
        resp = requests.post(
            url,
            data={"title": title, "desp": content},
            timeout=15
        )
        result = resp.json()

    except requests.RequestException as e:
        print(f"[微信] 请求失败: {e}")
        return False

    except ValueError:
        print("[微信] 接口返回非 JSON。")
        return False

    if result.get("code") == 0:
        print(f"[微信] 发送成功: {title}")
        return True

    print(f"[微信] 发送失败: {result}")
    return False


# =========================
# iPhone 通知：Pushover
# =========================

def send_pushover(title, message, priority=1):
    """
    priority=1：高优先级，绕过 Pushover quiet hours。
    priority=2：紧急优先级，重复提醒直到用户确认。
    """

    if not PUSHOVER_USER_KEY or not PUSHOVER_API_TOKEN:
        print("[iPhone] 未配置 Pushover Secrets，跳过推送。")
        return False

    payload = {
        "token": PUSHOVER_API_TOKEN,
        "user": PUSHOVER_USER_KEY,
        "title": title,
        "message": message,
        "priority": priority,
    }

    if priority == 2:
        payload["retry"] = PUSHOVER_RETRY_SECONDS
        payload["expire"] = PUSHOVER_EXPIRE_SECONDS

    try:
        resp = requests.post(
            "https://api.pushover.net/1/messages.json",
            data=payload,
            timeout=20
        )

        try:
            result = resp.json()
        except ValueError:
            print(f"[iPhone] 返回非 JSON，HTTP {resp.status_code}")
            return False

    except requests.RequestException as e:
        print(f"[iPhone] 推送请求失败: {e}")
        return False

    if resp.ok and result.get("status") == 1:
        if priority == 2:
            print("[iPhone] 紧急推送成功，等待用户确认。")
        else:
            print("[iPhone] 高优先级推送成功。")
        return True

    print(f"[iPhone] 推送失败: {result}")
    return False


# =========================
# 双通道通知
# =========================

def send_open_alert():
    title = "🚨 Elysian Horizon 开放了！"

    message = (
        "旅程 Discord 邀请现在已经开放！\n\n"
        "赶紧点击链接加入：\n"
        f"{INVITE_URL}"
    )

    print("[通知] 发送首次开放提醒。")

    # 微信主通知
    send_notification(
        title,
        (
            "Discord 邀请码现在已经开放！赶紧加入！\n\n"
            f"链接：{INVITE_URL}"
        )
    )

    # 微信单独链接通知，保留原来的行为
    send_notification(INVITE_URL)

    # iPhone 紧急通知
    send_pushover(
        title,
        message,
        priority=2
    )


def send_reminder_alert():
    title = "⚠️ Elysian Horizon 仍然开放中"

    message = (
        "旅程的 Discord 邀请仍然开放！\n\n"
        f"点击加入：{INVITE_URL}\n\n"
        f"每 {REMIND_AFTER_MINUTES} 分钟提醒一次。"
    )

    print("[通知] 发送持续开放提醒。")

    send_notification(
        title,
        (
            f"Discord 邀请仍然开放！\n\n"
            f"链接：{INVITE_URL}\n\n"
            f"每 {REMIND_AFTER_MINUTES} 分钟提醒一次。"
        )
    )

    send_pushover(
        title,
        message,
        priority=1
    )


# =========================
# 主流程
# =========================

def main():
    now = datetime.now(timezone.utc)

    state = load_state()
    print(f"[状态] 读取到旧状态: {state}")

    current_status = check_invite_status()

    if current_status == "open":

        if state["status"] != "open":
            # 暂停 -> 开放
            print("[判断] 状态变化：暂停 -> 开放")

            send_open_alert()

            state["status"] = "open"
            state["open_since"] = now.isoformat()
            state["notified_open"] = True
            state["last_remind_at"] = now.isoformat()

        else:
            # 已经开放，检查提醒间隔
            last_remind_at = (
                state.get("last_remind_at")
                or state.get("open_since")
            )

            if last_remind_at:
                last_remind = datetime.fromisoformat(last_remind_at)

                elapsed_minutes = (
                    now - last_remind
                ).total_seconds() / 60.0

                print(
                    f"[判断] 距离上次提醒约 "
                    f"{elapsed_minutes:.1f} 分钟。"
                )

                if elapsed_minutes >= REMIND_AFTER_MINUTES:
                    send_reminder_alert()
                    state["last_remind_at"] = now.isoformat()

            else:
                print("[判断] 仍然开放，但没有提醒时间记录。")

    else:
        # 暂停状态
        if state["status"] != "paused":
            print("[判断] 状态变化：开放 -> 暂停")

        else:
            print("[判断] 仍然暂停，无需通知。")

        state["status"] = "paused"
        state["open_since"] = None
        state["notified_open"] = False
        state["last_remind_at"] = None

    # 24 小时心跳：只发微信，不打扰 iPhone
    if HEARTBEAT_INTERVAL_HOURS > 0:

        last_heartbeat = state.get("last_heartbeat")

        if last_heartbeat:
            hb_elapsed_hours = (
                now - datetime.fromisoformat(last_heartbeat)
            ).total_seconds() / 3600.0
        else:
            hb_elapsed_hours = HEARTBEAT_INTERVAL_HOURS

        if hb_elapsed_hours >= HEARTBEAT_INTERVAL_HOURS:

            status_cn = (
                "开放中 ✅"
                if state["status"] == "open"
                else "暂停中 ⏸️"
            )

            print("[心跳] 发送微信监控心跳。")

            send_notification(
                "✅ Elysian 监控正常运行中",
                (
                    f"脚本运行正常。当前邀请状态：**{status_cn}**\n\n"
                    f"每 {HEARTBEAT_INTERVAL_HOURS:.0f} 小时发送一次。"
                )
            )

            state["last_heartbeat"] = now.isoformat()

    save_state(state)


if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        print(f"[致命错误] 脚本运行出错: {e}")
        sys.exit(1)
