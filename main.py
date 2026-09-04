from datetime import datetime
import json
import os
import threading
import time
from dotenv import load_dotenv
from flask import Flask

load_dotenv()

from script import (
    DEFAULT_HISTORY_FILE,
    generate_pitches,
    load_leads,
    save_lead,
    score_filter,
    scrape_reddit,
    send_lead_to_discord,
)

# 1. Tiny Flask web server so Render hosts it for $0/month
app = Flask(__name__)


@app.route("/")
def health_check():
  return "Reddit Lead Finder Bot is Active and Running!", 200


def run_pipeline_with_logging(user_profile, search_terms, webhook_url):
  now = datetime.now().strftime("%H:%M:%S")
  print(f"[{now}] Checking Reddit RSS feeds for new leads...")

  seen_ids = load_leads(DEFAULT_HISTORY_FILE)
  raw_leads = scrape_reddit(search_terms, seen_ids)

  if not raw_leads:
    print(f"[{now}] No new hiring posts found right now.")
    return []

  for lead in raw_leads:
    save_lead(DEFAULT_HISTORY_FILE, lead["id"])

  print(f"[{now}] Sending {len(raw_leads)} leads to Gemini for scoring...")
  qualified_leads = score_filter(user_profile, raw_leads)

  if not qualified_leads:
    print(f"[{now}] All leads filtered out (low score/irrelevant).")
    return []

  pitched_leads = generate_pitches(user_profile, qualified_leads)

  for lead in pitched_leads:
    if webhook_url:
      success = send_lead_to_discord(webhook_url, lead)
      if success:
        print(f"[{now}] SUCCESS: Sent '{lead.get('title')[:30]}...' to Discord!")

  return pitched_leads


def bot_loop():
  user_profile = """
    Freelance Full-Stack Developer skilled in Python, JavaScript, React, Node.js, and API integrations.
    Looking for contract work, MVP builds, script automation, and web development projects.
    """
  search_terms = ["hiring", "developer", "programmer"]
  webhook_url = os.getenv("DISCORDhook") or os.getenv("DISCORD_WEBHOOK_URL", "")

  while True:
    try:
      run_pipeline_with_logging(user_profile, search_terms, webhook_url)
    except Exception as e:
      now = datetime.now().strftime("%H:%M:%S")
      print(f"[{now}] CRITICAL ERROR: {e}")

    time.sleep(300)


if __name__ == "__main__":
  # Start the lead finder bot in a background thread
  bot_thread = threading.Thread(target=bot_loop, daemon=True)
  bot_thread.start()

  # Start Flask web server for Render on port 10000
  port = int(os.environ.get("PORT", 10000))
  app.run(host="0.0.0.0", port=port)
