# AI-Powered Job Scraper

An intelligent job search tool that uses [Exa](https://exa.ai) for web search and [Claude](https://anthropic.com) (Haiku) for smart filtering based on your criteria.

## Features

- **AI-Powered Filtering**: Claude analyzes each job listing against your criteria
- **Multi-Platform Search**: Searches LinkedIn, Indeed, Glassdoor, and company career pages
- **Smart Deduplication**: Removes duplicate listings across sources
- **Daily Updates**: Run daily to get fresh listings while preserving your notes
- **Excel Export**: Clean spreadsheet with apply links and tracking columns
- **Date Extraction**: Automatically extracts posting dates from job content
- **Status Detection**: Identifies active vs closed positions

## Setup

### 1. Install Dependencies

```bash
# Using uv (recommended)
uv sync

# Or using pip
pip install -e .
```

### 2. Configure API Keys

Copy the example environment file and add your API keys:

```bash
cp .env.example .env
```

Edit `.env` with your keys:
- **EXA_API_KEY**: Get from [exa.ai](https://exa.ai)
- **ANTHROPIC_API_KEY**: Get from [console.anthropic.com](https://console.anthropic.com)

### 3. Customize Your Search

Edit `job_scraper.py` to customize:

**CANDIDATE_CRITERIA** - Define what you're looking for:
```python
CANDIDATE_CRITERIA = """
- Role: Software Engineer
- Experience Level: Mid level (3-5 years)
- Location: Remote US or NYC
- Language: English only
- Industry: Tech startups
"""
```

**SEARCH_QUERIES** - Add your search terms:
```python
SEARCH_QUERIES = [
    'Software Engineer jobs NYC',
    'Remote Python developer USA',
    'site:linkedin.com/jobs Backend Engineer',
    # ... add more
]
```

**Configuration constants**:
```python
DAYS_BACK = 7          # Search last N days
RESULTS_PER_QUERY = 10 # Results per search
OUTPUT_FILE = "jobs.xlsx"
```

## Usage

```bash
# Using uv
uv run python job_scraper.py

# Or directly
python job_scraper.py
```

### Daily Workflow

1. Run the script daily to fetch new listings
2. Open `jobs.xlsx` to review matches
3. Use the tracking columns:
   - **My Status**: Your application status (Applied, Interviewed, etc.)
   - **Applied**: Checkbox for tracking
   - **Notes**: Your notes about the role

The script preserves your entries when updating with new jobs.

## Output Columns

| Column | Description |
|--------|-------------|
| Job Title | Position title |
| Platform | Source (LinkedIn, Indeed, etc.) |
| Location Type | Remote / Hybrid / Onsite |
| Experience Level | Entry / Mid / Senior |
| Posted | When the job was posted |
| Job Status | Active / Closed / Unknown |
| Apply Link | Direct link to apply |
| First Seen | When you first found this job |
| Last Seen | Last time job appeared in search |
| My Status | Your application status |
| Applied | Tracking checkbox |
| Notes | Your notes |

## Cost Estimation

The script uses Claude Haiku, the most cost-effective model:
- ~$0.25 per 1M input tokens
- ~$1.25 per 1M output tokens
- Typical run (100 jobs): < $0.01

Exa API has a free tier for getting started.

## How It Works

1. **Search**: Exa searches across job boards and career sites
2. **Deduplicate**: Removes duplicate URLs
3. **Filter**: Claude Haiku analyzes each job against your criteria
4. **Extract**: Claude extracts posted date, status, location type
5. **Merge**: Combines new results with existing data
6. **Export**: Saves to Excel with formatting

## License

MIT
