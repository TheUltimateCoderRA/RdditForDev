from datetime import datetime
import os
import time
from dotenv import load_dotenv

# Load environment variables from .env file
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


def run_pipeline_with_logging(user_profile, search_terms, webhook_url):
  now = datetime.now().strftime("%H:%M:%S")
  print(f"[{now}] Checking Reddit RSS feeds for new leads...")

  seen_ids = load_leads(DEFAULT_HISTORY_FILE)
  print(f"[{now}] Loaded {len(seen_ids)} previously processed lead IDs.")

  raw_leads = scrape_reddit(search_terms, seen_ids)
  print(f"[{now}] Found {len(raw_leads)} new un-seen raw leads on Reddit.")
  if not raw_leads:
    print(f"[{now}] No new hiring posts found right now.")
    return []

  # Save raw leads immediately so Gemini never re-evaluates the same post
  for lead in raw_leads:
    save_lead(DEFAULT_HISTORY_FILE, lead["id"])

  print(f"[{now}] Sending leads to Gemini for scoring...")
  qualified_leads = score_filter(user_profile, raw_leads)
  print(f"[{now}] Gemini qualified {len(qualified_leads)} relevant lead(s).")
  if not qualified_leads:
    print(
        f"[{now}] All found leads were filtered out (low score/irrelevant)."
    )
    return []

  print(f"[{now}] Generating pitches with Gemini...")
  pitched_leads = generate_pitches(user_profile, qualified_leads)

  sent_leads = []
  for lead in pitched_leads:
    if webhook_url:
      success = send_lead_to_discord(webhook_url, lead)
      if success:
        sent_leads.append(lead)
        print(
            f"[{now}] SUCCESS: Sent lead '{lead.get('title')[:40]}...' to"
            " Discord!"
        )
      else:
        print(f"[{now}] ERROR: Discord Webhook rejected lead {lead.get('id')}.")
    else:
      print(f"[{now}] WARNING: No Webhook URL configured! Skipping Discord.")

  return sent_leads


if __name__ == "__main__":
  # Custom Profile tailored to your specific tech stack
  user_profile = """
  Freelance Full-Stack Developer, Web Scraping & Automation Specialist.
  Frontend Skills: HTML5, CSS3, JavaScript (ES6+), React.
  Backend & Data Skills: Python, REST APIs, Databases (SQL & NoSQL), Data Science & Analytics (pandas).
  Specialized Services: Custom Web Application Development, Web Scraping & Data Extraction, Bot & Process Automation, API Integrations, Data Analysis Pipelines.
  Looking for: Full-stack web projects, Web scraping scripts, Automation tools, Python backend builds, and Data science tasks.
  """

  search_terms = ["hiring", "developer", "programmer", "python", "react"]
  webhook_url = os.getenv("DISCORDhook") or os.getenv("DISCORD_WEBHOOK_URL", "")

  print("==================================================")
  print("         REDDIT LEAD FINDER BOT STARTED           ")
  print("==================================================")
  print(f"Webhook Found: {bool(webhook_url)}")
  print(
      "Stack Target:  React, Python, Web Scraping, Automation, Data Science"
  )
  print("--------------------------------------------------\n")

  while True:
    try:
      run_pipeline_with_logging(user_profile, search_terms, webhook_url)
    except Exception as e:
      now = datetime.now().strftime("%H:%M:%S")
      print(f"[{now}] CRITICAL ERROR: {e}")

    now = datetime.now().strftime("%H:%M:%S")
    print(f"[{now}] Cycle complete. Sleeping for 5 minutes...\n")
    time.sleep(300)