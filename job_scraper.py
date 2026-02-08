# Job Scraper - AI-Powered Job Search with Claude Filtering
# Uses Exa for web search and Claude Haiku for intelligent filtering
# Supports daily runs with deduplication and data persistence

import asyncio
import json
import os
import shutil
from datetime import datetime, timedelta
from pathlib import Path

import anthropic
from dotenv import load_dotenv
from exa_py import Exa
import pandas as pd

# Load environment variables
load_dotenv()

# =============================================================================
# CONFIGURATION - Modify these settings as needed
# =============================================================================

# Output file (fixed name for daily updates)
OUTPUT_FILE = "jobs.xlsx"

# How many days back to search for jobs (default: 7 = last week)
DAYS_BACK = 7

# Number of results per search query
RESULTS_PER_QUERY = 10

# Claude model for filtering (haiku is cheapest)
CLAUDE_MODEL = "claude-3-haiku-20240307"

# Batch size for Claude API calls (to reduce costs)
CLAUDE_BATCH_SIZE = 10

# =============================================================================
# CANDIDATE CRITERIA - Customize this for your job search
# =============================================================================

CANDIDATE_CRITERIA = """
- Role: Product Manager (including Associate PM, Junior PM, APM)
- Experience Level: Entry level or Mid level (0-5 years experience)
- Location: Germany OR Remote positions that allow working from Germany/EU
- Language: English-speaking roles ONLY. Must NOT require German language skills.
- Industry: Open to all, but preference for Tech, SaaS, AI/ML, FinTech
- Company Size: Any
"""

# =============================================================================
# SEARCH QUERIES - Customize these for your target roles and locations
# =============================================================================

SEARCH_QUERIES = [
    # Location-based searches
    'Product Manager jobs Germany',
    'Junior Product Manager Germany',
    'Associate Product Manager Berlin',
    'Product Manager Munich startup',
    'Entry level Product Manager Germany',

    # Remote searches
    'Remote Product Manager Europe',
    'Product Manager remote EU',
    'Junior Product Manager remote EMEA',

    # Industry-specific
    'Product Manager AI startup Germany',
    'Product Manager FinTech Berlin',
    'SaaS Product Manager Germany',
    'Tech Product Manager remote Europe',

    # Job board specific (customize domains for your region)
    'site:linkedin.com/jobs Product Manager Germany',
    'site:indeed.de Product Manager',
    'site:glassdoor.com Product Manager Germany',
    'site:stepstone.de Product Manager',
    'site:arbeitnow.com Product Manager',
    'site:relocate.me Product Manager Germany',
]


async def search_jobs(exa: Exa, query: str) -> list[dict]:
    """Search for jobs using Exa API."""
    try:
        print(f"  Searching: {query[:55]}...")

        start_date = datetime.now() - timedelta(days=DAYS_BACK)
        start_date_str = start_date.strftime("%Y-%m-%d")

        results = await asyncio.to_thread(
            exa.search_and_contents,
            query,
            text=True,
            type="auto",
            livecrawl="fallback",
            num_results=RESULTS_PER_QUERY,
            start_published_date=start_date_str,
        )

        jobs = []
        for result in results.results:
            snippet = result.text[:1000] if result.text else ""
            title = result.title or "N/A"

            jobs.append({
                "title": title,
                "url": result.url,
                "snippet": snippet,
                "source_query": query,
                "first_seen": datetime.now(),
                "last_seen": datetime.now(),
            })

        print(f"    Found {len(jobs)} results")
        return jobs

    except Exception as e:
        print(f"    Error: {e}")
        return []


def deduplicate_jobs(jobs: list[dict]) -> list[dict]:
    """Remove duplicate jobs by URL."""
    seen_urls = set()
    unique = []

    skip_patterns = [
        "/about", "/contact", "/privacy", "/terms",
        "/blog/", "/news/", "/press/", "wikipedia.org"
    ]

    for job in jobs:
        url = job["url"]
        if url in seen_urls:
            continue
        if any(pattern in url.lower() for pattern in skip_patterns):
            continue
        seen_urls.add(url)
        unique.append(job)

    return unique


async def filter_jobs_with_claude(client: anthropic.Anthropic, jobs: list[dict]) -> list[dict]:
    """
    Use Claude Haiku to filter jobs based on candidate criteria.
    Processes jobs in batches for efficiency.
    """
    if not jobs:
        return []

    filtered_jobs = []
    total_batches = (len(jobs) + CLAUDE_BATCH_SIZE - 1) // CLAUDE_BATCH_SIZE

    print(f"\nFiltering {len(jobs)} jobs with Claude ({total_batches} batches)...")

    for batch_idx in range(0, len(jobs), CLAUDE_BATCH_SIZE):
        batch = jobs[batch_idx:batch_idx + CLAUDE_BATCH_SIZE]
        batch_num = batch_idx // CLAUDE_BATCH_SIZE + 1
        print(f"  Processing batch {batch_num}/{total_batches}...")

        # Prepare jobs for Claude
        jobs_text = ""
        for i, job in enumerate(batch):
            jobs_text += f"""
---JOB {i}---
Title: {job['title']}
URL: {job['url']}
Content: {job['snippet'][:800]}
"""

        prompt = f"""Analyze these job listings and determine which ones match the candidate criteria.

CANDIDATE CRITERIA:
{CANDIDATE_CRITERIA}

JOBS TO ANALYZE:
{jobs_text}

For each job, respond with a JSON array. Each element should have:
- "index": the job number (0, 1, 2, etc.)
- "matches": true if the job matches ALL criteria, false otherwise
- "rejection_reason": if matches is false, briefly explain why (e.g., "requires German", "senior role", "not PM role")
- "posted_date": extract the posting date if mentioned (e.g., "2 days ago", "Jan 15", "2024-02-01"), or "unknown"
- "job_status": "active" if accepting applications, "closed" if filled/expired, "unknown" otherwise
- "location_type": "remote", "hybrid", "onsite", or "unknown"
- "experience_level": "entry", "mid", "senior", or "unknown"

Respond ONLY with a valid JSON array, no other text.
"""

        try:
            response = await asyncio.to_thread(
                client.messages.create,
                model=CLAUDE_MODEL,
                max_tokens=2000,
                messages=[{"role": "user", "content": prompt}]
            )

            # Parse Claude's response
            response_text = response.content[0].text.strip()

            # Handle markdown code blocks
            if response_text.startswith("```"):
                response_text = response_text.split("```")[1]
                if response_text.startswith("json"):
                    response_text = response_text[4:]

            results = json.loads(response_text)

            for result in results:
                idx = result.get("index", -1)
                if 0 <= idx < len(batch) and result.get("matches", False):
                    job = batch[idx].copy()
                    job["posted_date_display"] = result.get("posted_date", "Unknown")
                    job["content_status"] = result.get("job_status", "unknown").capitalize()
                    job["location_type"] = result.get("location_type", "unknown").capitalize()
                    job["experience_level"] = result.get("experience_level", "unknown").capitalize()
                    filtered_jobs.append(job)

        except json.JSONDecodeError as e:
            print(f"    Warning: Could not parse Claude response for batch {batch_num}")
            # Fall back to including all jobs from this batch
            for job in batch:
                job["posted_date_display"] = "Unknown"
                job["content_status"] = "Unknown"
                job["location_type"] = "Unknown"
                job["experience_level"] = "Unknown"
                filtered_jobs.append(job)
        except Exception as e:
            print(f"    Error in batch {batch_num}: {e}")

        # Small delay between batches
        await asyncio.sleep(0.3)

    return filtered_jobs


def categorize_job(job: dict) -> dict:
    """Add platform metadata to job."""
    url = job["url"].lower()

    if "linkedin.com" in url:
        platform = "LinkedIn"
    elif "indeed" in url:
        platform = "Indeed"
    elif "glassdoor" in url:
        platform = "Glassdoor"
    elif "xing.com" in url:
        platform = "XING"
    elif "stepstone" in url:
        platform = "StepStone"
    elif "arbeitnow" in url:
        platform = "Arbeitnow"
    elif "relocate.me" in url:
        platform = "Relocate.me"
    elif "germantechjobs" in url:
        platform = "German Tech Jobs"
    else:
        platform = "Company Career Site"

    job["platform"] = platform
    return job


def load_existing_data(filename: str) -> pd.DataFrame | None:
    """Load existing Excel file if it exists."""
    if Path(filename).exists():
        try:
            df = pd.read_excel(filename, sheet_name='Job Listings')
            print(f"  Loaded {len(df)} existing jobs from {filename}")
            return df
        except Exception as e:
            print(f"  Warning: Could not load existing file: {e}")
            return None
    return None


def merge_jobs(new_jobs: list[dict], existing_df: pd.DataFrame | None) -> list[dict]:
    """Merge new jobs with existing data, preserving user entries."""
    if existing_df is None or existing_df.empty:
        return new_jobs

    existing_lookup = {}
    for _, row in existing_df.iterrows():
        url = row.get("Apply Link", "")
        if url:
            existing_lookup[url] = {
                "applied": row.get("Applied", ""),
                "notes": row.get("Notes", ""),
                "first_seen": row.get("First Seen", ""),
                "my_status": row.get("My Status", ""),
            }

    merged = []
    new_urls = set()

    for job in new_jobs:
        url = job["url"]
        new_urls.add(url)

        if url in existing_lookup:
            existing = existing_lookup[url]
            job["user_applied"] = existing.get("applied", "")
            job["user_notes"] = existing.get("notes", "")
            job["user_my_status"] = existing.get("my_status", "")
            if existing.get("first_seen"):
                try:
                    job["first_seen"] = pd.to_datetime(existing["first_seen"])
                except:
                    pass
        else:
            job["user_applied"] = ""
            job["user_notes"] = ""
            job["user_my_status"] = ""

        merged.append(job)

    # Keep old jobs not found in new search
    for _, row in existing_df.iterrows():
        url = row.get("Apply Link", "")
        if url and url not in new_urls:
            merged.append({
                "title": row.get("Job Title", ""),
                "url": url,
                "snippet": row.get("Description Preview", ""),
                "platform": row.get("Platform", ""),
                "location_type": row.get("Location Type", ""),
                "experience_level": row.get("Experience Level", ""),
                "posted_date_display": row.get("Posted", ""),
                "content_status": "Not Found in Search",
                "first_seen": row.get("First Seen", ""),
                "last_seen": row.get("Last Seen", ""),
                "user_applied": row.get("Applied", ""),
                "user_notes": row.get("Notes", ""),
                "user_my_status": row.get("My Status", ""),
            })

    return merged


def export_to_excel(jobs: list[dict], filename: str) -> str:
    """Export jobs to Excel file with formatting."""
    now = datetime.now()

    data = []
    for i, job in enumerate(jobs, 1):
        content_status = job.get("content_status", "Unknown")

        if content_status.lower() == "closed":
            job_status = "Closed"
        elif content_status == "Not Found in Search":
            job_status = "Maybe Closed"
        elif content_status.lower() == "active":
            job_status = "Active"
        else:
            job_status = "Unknown"

        first_seen = job.get("first_seen", now)
        if isinstance(first_seen, str):
            first_seen_str = first_seen
        else:
            first_seen_str = first_seen.strftime("%Y-%m-%d") if first_seen else now.strftime("%Y-%m-%d")

        last_seen = job.get("last_seen", now)
        if isinstance(last_seen, str):
            last_seen_str = last_seen
        else:
            last_seen_str = last_seen.strftime("%Y-%m-%d") if last_seen else now.strftime("%Y-%m-%d")

        data.append({
            "#": i,
            "Job Title": job.get("title", ""),
            "Platform": job.get("platform", ""),
            "Location Type": job.get("location_type", "Unknown"),
            "Experience Level": job.get("experience_level", "Unknown"),
            "Posted": job.get("posted_date_display", "Unknown"),
            "Job Status": job_status,
            "Apply Link": job.get("url", ""),
            "Description Preview": (job.get("snippet", "")[:300] + "...") if len(job.get("snippet", "")) > 300 else job.get("snippet", ""),
            "First Seen": first_seen_str,
            "Last Seen": last_seen_str,
            "My Status": job.get("user_my_status", ""),
            "Applied": job.get("user_applied", ""),
            "Notes": job.get("user_notes", ""),
        })

    df = pd.DataFrame(data)

    # Sort: Active first, then by first seen (newest first)
    status_order = {"Active": 0, "Unknown": 1, "Maybe Closed": 2, "Closed": 3}
    df["_status_order"] = df["Job Status"].map(status_order).fillna(1)
    df["_first_seen_sort"] = pd.to_datetime(df["First Seen"], errors='coerce')
    df = df.sort_values(
        by=["_status_order", "_first_seen_sort"],
        ascending=[True, False]
    ).drop(columns=["_status_order", "_first_seen_sort"])

    df["#"] = range(1, len(df) + 1)

    with pd.ExcelWriter(filename, engine='openpyxl') as writer:
        df.to_excel(writer, index=False, sheet_name='Job Listings')

        worksheet = writer.sheets['Job Listings']
        column_widths = {
            'A': 5, 'B': 45, 'C': 15, 'D': 15, 'E': 15,
            'F': 12, 'G': 12, 'H': 55, 'I': 70,
            'J': 12, 'K': 12, 'L': 15, 'M': 10, 'N': 30,
        }
        for col, width in column_widths.items():
            worksheet.column_dimensions[col].width = width

    return filename


async def main():
    """Main function to run the job scraper."""
    print("=" * 60)
    print("AI-POWERED JOB SCRAPER")
    print(f"Run date: {datetime.now().strftime('%Y-%m-%d %H:%M')}")
    print("=" * 60)

    # Check for API keys
    exa_api_key = os.environ.get("EXA_API_KEY")
    anthropic_api_key = os.environ.get("ANTHROPIC_API_KEY") or os.environ.get("CLAUDE_API_KEY")

    if not exa_api_key:
        print("\nERROR: EXA_API_KEY not found. Add it to .env file.")
        return

    if not anthropic_api_key:
        print("\nERROR: ANTHROPIC_API_KEY or CLAUDE_API_KEY not found. Add it to .env file.")
        return

    # Load existing data
    print("\nLoading existing data...")
    existing_df = load_existing_data(OUTPUT_FILE)

    # Initialize clients
    exa = Exa(api_key=exa_api_key)
    claude = anthropic.Anthropic(api_key=anthropic_api_key)

    print(f"\nSearching jobs (last {DAYS_BACK} days)...")
    print("-" * 60)

    # Run all searches
    all_jobs = []
    for query in SEARCH_QUERIES:
        jobs = await search_jobs(exa, query)
        all_jobs.extend(jobs)
        await asyncio.sleep(0.3)

    print("-" * 60)
    print(f"\nTotal raw results: {len(all_jobs)}")

    # Deduplicate
    print("Removing duplicates...")
    unique_jobs = deduplicate_jobs(all_jobs)
    print(f"Unique jobs: {len(unique_jobs)}")

    # Filter with Claude
    filtered_jobs = await filter_jobs_with_claude(claude, unique_jobs)
    print(f"\nJobs matching criteria: {len(filtered_jobs)}")

    # Categorize
    categorized_jobs = [categorize_job(job) for job in filtered_jobs]

    # Merge with existing
    print("\nMerging with existing data...")
    merged_jobs = merge_jobs(categorized_jobs, existing_df)

    new_count = len(filtered_jobs)
    if existing_df is not None:
        existing_urls = set(existing_df.get("Apply Link", []))
        new_count = len([j for j in filtered_jobs if j["url"] not in existing_urls])

    if new_count > 0:
        print(f"  Found {new_count} new jobs!")

    # Backup existing file before overwriting
    if Path(OUTPUT_FILE).exists():
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        backup_path = OUTPUT_FILE.replace(".xlsx", f"_backup_{timestamp}.xlsx")
        shutil.copy2(OUTPUT_FILE, backup_path)
        print(f"\nBackup saved: {backup_path}")

    # Export
    print(f"\nExporting to: {OUTPUT_FILE}")
    export_to_excel(merged_jobs, OUTPUT_FILE)

    # Summary
    print("\n" + "=" * 60)
    print("SUMMARY")
    print("=" * 60)
    print(f"Total jobs in database: {len(merged_jobs)}")
    print(f"New jobs this run: {new_count}")

    # Status breakdown
    print("\nBy Job Status:")
    status_counts = {}
    for job in merged_jobs:
        status = job.get("content_status", "Unknown")
        if status == "Not Found in Search":
            status = "Maybe Closed"
        status_counts[status] = status_counts.get(status, 0) + 1
    for status, count in sorted(status_counts.items()):
        print(f"  {status}: {count}")

    # Platform breakdown
    print("\nBy Platform:")
    platforms = {}
    for job in merged_jobs:
        p = job.get("platform", "Unknown")
        platforms[p] = platforms.get(p, 0) + 1
    for platform, count in sorted(platforms.items(), key=lambda x: -x[1]):
        print(f"  {platform}: {count}")

    print("\n" + "=" * 60)
    print("Done! Run daily to get fresh job listings.")
    print("=" * 60)


if __name__ == "__main__":
    asyncio.run(main())
