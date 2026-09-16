#!/usr/bin/env python3
# Fortnite Leaks -> Discord Webhook Bot
# Monitors trusted Fortnite leakers on X (Twitter) and forwards to Discord webhook
# Works without Twitter API keys by scraping X.com + using api.fxtwitter.com for full data
# Author: Muse Spark for FortniteLeaks project

import requests
import re
import html
import json
import time
import os
import sys
from datetime import datetime, timezone

# Ensure utf-8 stdout on Windows
try:
    sys.stdout.reconfigure(encoding='utf-8')
except:
    pass

# File logging for background/hidden mode
LOG_FILE = os.path.join(os.path.dirname(__file__), "bot.log")
def log(msg):
    try:
        ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        with open(LOG_FILE, "a", encoding="utf-8") as f:
            f.write(f"[{ts}] {msg}\n")
    except: pass
    # also print to console if available
    try: print(msg)
    except: pass

# ---------------- CONFIG ----------------
WEBHOOK_URL = "https://discord.com/api/webhooks/1549911239545856042/p0LVrTmILdeUYV2SMoZMgJ4PBaYnKQH-Fp2xA_2SEo4F4rMtxp5agA_civVBbsVEDUDJ"

# Trusted leakers - add/remove here. Bot will monitor all of them.
TRUSTED_LEAKERS = {
    "HYPEX":            {"color": 0x1D9BF0, "label": "HYPEX", "icon": "https://pbs.twimg.com/profile_images/1680830035639369730/0BG8cBZa_200x200.jpg"},
    "ShiinaBR":         {"color": 0xFFD600, "label": "ShiinaBR", "icon": "https://pbs.twimg.com/profile_images/1696443731220504577/9zLMnCKL_200x200.jpg"},
    "FN_Assist":        {"color": 0x00BA7C, "label": "FNAssist", "icon": ""},
    "Egyptian_Leaker":  {"color": 0x7856FF, "label": "Egyptian Leaker", "icon": ""},
    "Loolo_WRLD":       {"color": 0x1D9BF0, "label": "Loolo_WRLD", "icon": ""},
    "FNBRintel":        {"color": 0xE0245E, "label": "FNBRintel", "icon": ""},
    "SamLeakss":        {"color": 0xFF7A00, "label": "SamLeakss", "icon": ""},
    "RealShiina":       {"color": 0xFFD600, "label": "Shiina (Alt)", "icon": ""},
    "BeastFNLeaks":     {"color": 0xE0245E, "label": "BeastFNLeaks", "icon": ""},  # may 404 - will skip
    "iFireMonkey":      {"color": 0xFF7A00, "label": "iFireMonkey", "icon": ""},   # may 404
}

# Poll every N seconds (Discord rate limit + X scraping friendly)
POLL_INTERVAL = 90  # 90 seconds between full cycles
PER_USER_DELAY = 3  # seconds between users to avoid hammering X

# Files
STATE_FILE = os.path.join(os.path.dirname(__file__), "leaks_seen.json")
CONFIG_FILE = os.path.join(os.path.dirname(__file__), "leaks_bot_config.json")

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
    "Accept-Language": "en-US,en;q=0.9",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
}

# ---------------- STATE ----------------
def load_seen():
    if os.path.exists(STATE_FILE):
        try:
            with open(STATE_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
                return set(data.get("seen_ids", []))
        except:
            return set()
    return set()

def save_seen(seen):
    try:
        with open(STATE_FILE, "w", encoding="utf-8") as f:
            json.dump({"seen_ids": sorted(list(seen))[-5000:], "updated": datetime.now(timezone.utc).isoformat()}, f, indent=2)
    except Exception as e:
        print(f"[WARN] save_seen failed: {e}")

def load_config():
    # Allow overriding WEBHOOK_URL via config file or env var
    cfg_webhook = WEBHOOK_URL
    if os.path.exists(CONFIG_FILE):
        try:
            with open(CONFIG_FILE, "r", encoding="utf-8") as f:
                cfg = json.load(f)
                cfg_webhook = cfg.get("webhook_url", cfg_webhook)
                global TRUSTED_LEAKERS, POLL_INTERVAL
                if "poll_interval" in cfg:
                    POLL_INTERVAL = cfg["poll_interval"]
                if "leakers" in cfg:
                    # allow custom leaker list
                    pass
        except Exception as e:
            print(f"[WARN] load_config failed: {e}")
    env_wh = os.environ.get("DISCORD_WEBHOOK_URL")
    if env_wh:
        cfg_webhook = env_wh
    return cfg_webhook

# ---------------- FETCH ----------------
def scrape_ids(username):
    """Scrape https://x.com/{username} for recent tweet IDs. Returns list[str] newest first."""
    url = f"https://x.com/{username}"
    try:
        r = requests.get(url, headers=HEADERS, timeout=15)
        if r.status_code == 404:
            print(f"  [404] @{username} not found (handle may have changed)")
            return []
        if r.status_code != 200:
            print(f"  [HTTP {r.status_code}] @{username} -> {r.text[:200]}")
            return []
        data = r.text
        # Extract data-href="/username/status/ID" - most reliable for rendered tweets
        ids = re.findall(rf'data-href="/{re.escape(username)}/status/(\d+)"', data, flags=re.IGNORECASE)
        if not ids:
            # fallback: any /status/ id
            ids = re.findall(r'/[^/]+/status/(\d+)', data)
        # dedupe preserve order
        seen = set()
        uniq = []
        for i in ids:
            if i not in seen:
                seen.add(i)
                uniq.append(i)
        # Typically first 4-5 after relay are real tweets; take up to 5
        return uniq[:5]
    except Exception as e:
        print(f"  [ERR] scrape_ids @{username}: {e}")
        return []

def fetch_tweet_details(username, tweet_id):
    """Use api.fxtwitter.com to get full tweet JSON. Username in URL is dummy - API returns correct author."""
    # fxtwitter allows any username prefix, we use the scraped username
    url = f"https://api.fxtwitter.com/{username}/status/{tweet_id}"
    try:
        r = requests.get(url, headers={"User-Agent": HEADERS["User-Agent"]}, timeout=12)
        if r.status_code != 200:
            print(f"    [fx {r.status_code}] {tweet_id} -> {r.text[:200]}")
            return None
        j = r.json()
        if j.get("code") != 200 or not j.get("tweet"):
            print(f"    [fx no tweet] {tweet_id}: {j}")
            return None
        return j["tweet"]
    except Exception as e:
        print(f"    [ERR] fxtwitter {tweet_id}: {e}")
        return None

def fetch_all_for_user(username):
    ids = scrape_ids(username)
    print(f"  @{username}: found {len(ids)} ids: {ids[:3]}")
    tweets = []
    for tid in ids:
        t = fetch_tweet_details(username, tid)
        if t:
            tweets.append(t)
        time.sleep(0.6)  # be nice to fxtwitter
    return tweets

# ---------------- DISCORD ----------------
def send_to_discord(webhook_url, tweet):
    """Send tweet dict from fxtwitter to Discord webhook as embed."""
    author = tweet.get("author", {})
    screen_name = author.get("screen_name", "unknown")
    display_name = author.get("name", screen_name)
    avatar_url = author.get("avatar_url", "")
    tweet_url = tweet.get("url", f"https://x.com/{screen_name}/status/{tweet.get('id')}")
    text = tweet.get("text", "")
    created_ts = tweet.get("created_timestamp")  # unix
    # Use leaker config for color if available
    cfg = TRUSTED_LEAKERS.get(screen_name) or TRUSTED_LEAKERS.get(tweet.get("author", {}).get("screen_name", "")) or {"color": 0x1D9BF0}
    # Fallback lookup case-insensitive
    if screen_name not in TRUSTED_LEAKERS:
        for k,v in TRUSTED_LEAKERS.items():
            if k.lower() == screen_name.lower():
                cfg = v
                break

    color = cfg.get("color", 0x1D9BF0)
    # Discord embed description max 4096, truncate gracefully
    desc = text
    if len(desc) > 4000:
        desc = desc[:3997] + "..."

    # Build embed
    embed = {
        "color": color,
        "author": {
            "name": f"{display_name} (@{screen_name}) {'✓' if author.get('verification',{}).get('verified') else ''}".strip(),
            "url": f"https://x.com/{screen_name}",
            "icon_url": avatar_url
        },
        "description": desc + f"\n\n[View on X]({tweet_url})",
        "url": tweet_url,
        "footer": {
            "text": f"Fortnite Leak • {screen_name} • ❤️ {tweet.get('likes',0)}  ♻️ {tweet.get('retweets',0)}  💬 {tweet.get('replies',0)}  👁️ {tweet.get('views','?')}"
        },
        "timestamp": datetime.fromtimestamp(created_ts, tz=timezone.utc).isoformat() if created_ts else datetime.now(timezone.utc).isoformat()
    }

    # Media image
    media = tweet.get("media", {})
    photos = media.get("photos", [])
    if photos:
        # use first photo as embed image (Discord only shows one per embed)
        embed["image"] = {"url": photos[0].get("url")}
    elif media.get("all"):
        # fallback: check if first is photo
        first = media["all"][0]
        if first.get("type") == "photo":
            embed["image"] = {"url": first.get("url")}

    payload = {
        "username": f"Fortnite Leaks • {display_name}",
        "avatar_url": avatar_url,
        "embeds": [embed]
    }

    # For multiple images, add extra embeds or send followup? Discord webhook can have up to 10 embeds, but we keep simple
    # If >1 photo, add them as additional embeds (without author duplicate)
    extra_embeds = []
    if len(photos) > 1:
        for p in photos[1:4]:  # max 3 extra
            extra_embeds.append({
                "url": tweet_url,
                "color": color,
                "image": {"url": p.get("url")}
            })
        payload["embeds"].extend(extra_embeds)

    # Send with retry on rate limit
    for attempt in range(3):
        try:
            r = requests.post(webhook_url, json=payload, timeout=10)
            if r.status_code in (200, 204):
                print(f"    [SENT] {tweet_url} -> Discord OK")
                return True
            elif r.status_code == 429:
                retry_after = r.json().get("retry_after", 2000) / 1000.0
                print(f"    [RATE LIMITED] retry after {retry_after}s")
                time.sleep(retry_after + 1)
                continue
            else:
                print(f"    [DISCORD {r.status_code}] {r.text[:500]}")
                # Log payload for debug
                return False
        except Exception as e:
            print(f"    [ERR] discord send: {e}")
            time.sleep(2)
    return False

def send_test_embed(webhook_url):
    """Send a test message to verify webhook works."""
    payload = {
        "username": "Fortnite Leaks Bot",
        "avatar_url": "https://pbs.twimg.com/profile_images/1680830035639369730/0BG8cBZa_200x200.jpg",
        "content": "✅ **Fortnite Leaks Bot connected!**\nMonitoring trusted leakers and will forward new posts here automatically.",
        "embeds": [
            {
                "title": "Bot Active — Monitoring Trusted Leakers",
                "description": "**Tracked accounts:**\n" + "\n".join([f"• `@{u}`" for u in TRUSTED_LEAKERS.keys() if TRUSTED_LEAKERS[u]]) + "\n\nNew leaks from HYPEX, ShiinaBR, etc. will appear here instantly!",
                "color": 0xFFD600,
                "footer": {"text": "FortniteLeaks Bot • Polling every 90s • Made for you"},
                "timestamp": datetime.now(timezone.utc).isoformat()
            }
        ]
    }
    r = requests.post(webhook_url, json=payload, timeout=10)
    print(f"[TEST] webhook POST -> {r.status_code} {r.text[:500]}")
    return r.status_code in (200, 204)

# ---------------- MAIN ----------------
def run_once(webhook_url, seen, dry_run=False):
    new_count = 0
    for username in list(TRUSTED_LEAKERS.keys()):
        print(f"\n[Checking @{username}]")
        try:
            tweets = fetch_all_for_user(username)
        except Exception as e:
            print(f"  [ERR] fetch_all_for_user {username}: {e}")
            continue
        for tweet in reversed(tweets):  # oldest first so Discord shows chronological
            tid = str(tweet.get("id"))
            if tid in seen:
                continue
            print(f"  [NEW] {tweet.get('url')} - {tweet.get('text')[:80]}...")
            if dry_run:
                print(f"    (dry_run - would send to Discord)")
            else:
                ok = send_to_discord(webhook_url, tweet)
                if ok:
                    seen.add(tid)
                    save_seen(seen)
                    new_count += 1
                    time.sleep(1.2)  # avoid Discord rate limit
                else:
                    print(f"    [FAILED] not marking as seen")
            if dry_run:
                seen.add(tid)  # still mark to avoid re-processing in same run
                new_count += 1
        time.sleep(PER_USER_DELAY)
    return new_count

def main():
    import argparse
    parser = argparse.ArgumentParser(description="Fortnite Leaks -> Discord Webhook Bot")
    parser.add_argument("--test", action="store_true", help="Send test embed to webhook and exit")
    parser.add_argument("--once", action="store_true", help="Run one poll cycle and exit (send new tweets)")
    parser.add_argument("--dry-run", action="store_true", help="With --once, don't actually send to Discord, just show what would be sent")
    parser.add_argument("--loop", action="store_true", help="Run continuously (default if no args)")
    parser.add_argument("--interval", type=int, default=None, help="Override poll interval seconds")
    parser.add_argument("--webhook", type=str, default=None, help="Override webhook URL")
    args = parser.parse_args()

    webhook = args.webhook or load_config()
    if args.interval:
        global POLL_INTERVAL
        POLL_INTERVAL = args.interval

    if not webhook or "discord.com/api/webhooks" not in webhook:
        print("[ERROR] Invalid webhook URL. Set in discord_leaks_bot.py or via --webhook or env DISCORD_WEBHOOK_URL")
        sys.exit(1)

    print(f"=== Fortnite Leaks -> Discord Bot ===")
    print(f"Webhook: {webhook[:60]}...")
    print(f"Leakers: {', '.join(TRUSTED_LEAKERS.keys())}")
    print(f"State file: {STATE_FILE}")
    print(f"Poll interval: {POLL_INTERVAL}s")

    seen = load_seen()
    print(f"Loaded {len(seen)} seen tweet IDs")

    if args.test:
        ok = send_test_embed(webhook)
        sys.exit(0 if ok else 1)

    if args.once:
        n = run_once(webhook, seen, dry_run=args.dry_run)
        print(f"\n[DONE] {n} new tweets processed (once)")
        if not args.dry_run:
            save_seen(seen)
        return

    # Loop mode (default)
    print("\n[LOOP] Starting continuous polling. Press Ctrl+C to stop.")
    # On first run, we don't want to spam old tweets. If seen is empty, do a dry-run to populate seen without sending.
    if len(seen) == 0:
        print("[FIRST RUN] No history found - doing initial sync (marking existing tweets as seen, not sending). Use --once to force send.")
        run_once(webhook, seen, dry_run=True)
        save_seen(seen)
        print(f"Initial sync done: {len(seen)} tweets marked as seen. Next cycle will only send NEW tweets.")
        # Optionally send test embed
        send_test_embed(webhook)

    try:
        while True:
            try:
                n = run_once(webhook, seen, dry_run=False)
                print(f"\n[CYCLE DONE] {n} new tweets sent. Sleeping {POLL_INTERVAL}s...")
            except Exception as e:
                print(f"[CYCLE ERROR] {e}")
                import traceback
                traceback.print_exc()
            time.sleep(POLL_INTERVAL)
    except KeyboardInterrupt:
        print("\n[STOP] Bot stopped by user. Saving state...")
        save_seen(seen)

if __name__ == "__main__":
    main()
