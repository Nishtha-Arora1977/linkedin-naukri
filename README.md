# JobApply Automation (LinkedIn + Naukri)

Automate Easy Apply on LinkedIn and quick-apply on Naukri with Selenium.

## Features

- **LinkedIn**: logs in (saved browser session), searches all keyword/location combos with the Easy Apply filter, opens each job, auto-fills standard screening questions from your `answers` config, attaches your resume, and submits. Jobs that ask unanswerable niche questions are skipped and reported.
- **Naukri**: logs in via saved session (first login manual), searches keyword/location combos, applies with your Naukri profile, handles confirm dialogs.
- **Company blacklist** (skip employers entirely)
- Answer "rules" mapping question keywords -> your canned answers
- Optional headless Chrome (`"headless": true`)
- Persistent Chrome profiles so you never re-login after the first time
- macOS `launchd` scheduling support

## Getting started

1. Install selenium: `pip install "selenium<4"` and download a matching [ChromeDriver](https://googlechromelabs.github.io/chrome-for-testing/).
2. Copy `config.example.json` to `config.json` and fill in:
   - LinkedIn email/password (stored locally only, never committed — `config.json` is gitignored)
   - Keywords and locations
   - Path to your chromedriver
3. Run: `python main.py` (LinkedIn) · `python main_naukri.py` (Naukri — log in manually in the first window; the session is saved afterwards)

## Scheduling (macOS, optional)

Sample plists in `launchd/` run LinkedIn at 9:00 AM and Naukri at 9:40 AM on weekdays. See `launchd/README` inside.

## Notes

- Your email/password/config are never pushed to git (`config.json` is gitignored).
- The bot skips jobs from blacklisted companies and jobs with questions it cannot answer.
