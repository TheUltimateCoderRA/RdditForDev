from datetime import datetime
import html
import json
import os
import re
import time
import xml.etree.ElementTree as ET
from google import genai
import requests as rq

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DEFAULT_HISTORY_FILE = os.path.join(BASE_DIR, "seen_leads.txt")


def load_leads(filename=DEFAULT_HISTORY_FILE):
  if not os.path.exists(filename):
    return set()
  with open(filename, "r") as f:
    return set(f.read().splitlines())


def save_lead(filename, post_id):
  with open(filename, "a") as f:
    f.write(f"{post_id}\n")


def _clean_and_parse_json(text):
  text = text.strip()
  if text.startswith("```json"):
    text = text[7:]
  elif text.startswith("```"):
    text = text[3:]
  if text.endswith("```"):
    text = text[:-3]
  return json.loads(text.strip())
def scrape_reddit(search_terms=None, seen_ids=None):
  if seen_ids is None:
    seen_ids = set()

  leads = []

  # Combine all 12 subreddits into ONE multi-subreddit RSS request
  multi_sub = (
      "forhire+freelance_forhire+ForHireFreelance+FreelanceProgramming+"
      "Programmers_forhire+jobbit+DeveloperJobs+DevsForHire+"
      "WebDeveloperJobs+developers_hire+techjobs+devjobs"
  )

  url = f"https://www.reddit.com/r/{multi_sub}/new.rss"
  headers = {
      "User-Agent": (
          "python:com.freelance.leadbot:v1.0.0 (by /u/dev_lead_finder_2026)"
      )
  }

  try:
    response = rq.get(url, headers=headers, timeout=10)

    if response.status_code == 200:
      root = ET.fromstring(response.content)
      ns = {"atom": "http://www.w3.org/2005/Atom"}

      for entry in root.findall("atom:entry", ns):
        id_elem = entry.find("atom:id", ns)
        title_elem = entry.find("atom:title", ns)
        link_elem = entry.find("atom:link", ns)
        content_elem = entry.find("atom:content", ns)

        post_id = id_elem.text if id_elem is not None else ""
        title = title_elem.text if title_elem is not None else ""
        permalink = (
            link_elem.attrib.get("href") if link_elem is not None else ""
        )
        content_html = content_elem.text if content_elem is not None else ""

        clean_body = re.sub(r"<[^>]+>", "", html.unescape(content_html))

        if not post_id or post_id in seen_ids:
          continue

        title_lower = title.lower()

        # Catch [Hiring] posts while skipping [For Hire] freelancers
        if "hiring" in title_lower and "for hire" not in title_lower:
          lead_object = {
              "title": title,
              "id": post_id,
              "permalink": permalink,
              "body": clean_body[:500],
          }
          leads.append(lead_object)
    else:
      now = datetime.now().strftime("%H:%M:%S")
      print(f"[{now}] Reddit RSS feed returned HTTP {response.status_code}")

  except Exception as e:
    now = datetime.now().strftime("%H:%M:%S")
    print(f"[{now}] Error reading multi-subreddit RSS feed: {e}")

  return leads


def get_score_prompt(user_profile, leads):
  return f"""
You are an AI assistant helping a freelancer identify relevant client leads.

User Profile:
{user_profile}

List of potential leads:
{leads}

Task Instructions:
1. Review every item in the provided leads list.
2. Filter out spam, self-promotions, and posts that are not genuine job/freelance opportunities.
3. For every valid lead, assign a match score from 1 to 100 based on how well it aligns with the user's profile.
4. Output ONLY a valid JSON array containing the qualified leads. Do not include any text outside the JSON.

Expected Output Format:
[
  {{
    "title": "Example Title",
    "id": "post_id_123",
    "permalink": "https://example.com/post",
    "body": "Post body content...",
    "score": 85
  }}
]
"""


def score_filter(user_profile, leads):
  if not leads:
    return []

  api_key = os.getenv("GEMINIkey") or os.getenv("GEMINI_API_KEY")
  client = genai.Client(api_key=api_key)
  response = client.models.generate_content(
      model="gemini-2.5-flash",
      contents=get_score_prompt(user_profile, leads),
  )

  return _clean_and_parse_json(response.text)


def get_pitch_prompt(user_profile, qualified_leads):
  return f"""
You are an expert sales copywriter and freelancer pitch specialist.

User Profile:
{user_profile}

High-Quality Leads:
{qualified_leads}

Task Instructions:
1. Write a concise, personalized, and compelling pitch (2-3 paragraphs max) for every lead.
2. Immediately reference a specific detail or pain point mentioned in their post.
3. Highlight 1-2 relevant skills from the User Profile.
4. End with a casual, low-friction Call To Action.
5. Do NOT use generic openings like "I hope this finds you well".
6. Output ONLY a valid JSON array containing the leads with an added "pitch" field.

Expected Output Format:
[
  {{
    "title": "Example Title",
    "id": "post_id_123",
    "permalink": "https://example.com/post",
    "body": "Post body content...",
    "score": 85,
    "pitch": "Hey there! Saw your post about..."
  }}
]
"""


def generate_pitches(user_profile, qualified_leads):
  if not qualified_leads:
    return []

  api_key = os.getenv("GEMINIkey") or os.getenv("GEMINI_API_KEY")
  client = genai.Client(api_key=api_key)
  response = client.models.generate_content(
      model="gemini-2.5-flash",
      contents=get_pitch_prompt(user_profile, qualified_leads),
  )

  return _clean_and_parse_json(response.text)


def send_lead_to_discord(webhook_url, lead):
  score = lead.get("score", 0)
  color = 0x2ECC71 if score >= 80 else 0xF1C40F

  pitch_text = lead.get("pitch", "No pitch generated.")
  if len(pitch_text) > 1020:
    pitch_text = pitch_text[:1020] + "..."

  embed = {
      "title": lead.get("title", "New Lead Found!"),
      "url": lead.get("permalink", ""),
      "color": color,
      "fields": [
          {"name": "🎯 Score", "value": f"**{score}/100**", "inline": True},
          {
              "name": "🆔 Post ID",
              "value": f"`{lead.get('id', 'N/A')}`",
              "inline": True,
          },
          {"name": "📝 Pitch", "value": pitch_text},
      ],
      "footer": {"text": "Reddit Lead Bot"},
  }

  response = rq.post(
      webhook_url, json={"username": "Lead Finder Bot", "embeds": [embed]}
  )
  return response.status_code in (200, 204)


def run_lead_pipeline(
    user_profile, search_terms, webhook_url, history_file=DEFAULT_HISTORY_FILE
):
  seen_ids = load_leads(history_file)

  raw_leads = scrape_reddit(search_terms, seen_ids)
  if not raw_leads:
    return []

  # Save raw lead IDs immediately so Gemini never re-evaluates the same post twice
  for lead in raw_leads:
    save_lead(history_file, lead["id"])

  qualified_leads = score_filter(user_profile, raw_leads)
  if not qualified_leads:
    return []

  pitched_leads = generate_pitches(user_profile, qualified_leads)

  sent_leads = []
  for lead in pitched_leads:
    success = send_lead_to_discord(webhook_url, lead)
    if success:
      sent_leads.append(lead)

  return sent_leads