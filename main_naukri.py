import time
import os
import urllib.parse
import json

from selenium import webdriver
from selenium.webdriver.common.keys import Keys
from selenium.webdriver.common.by import By
from selenium.common.exceptions import NoSuchElementException, TimeoutException


import subprocess


class NaukriApply:

    def __init__(self, data):
        kw = data['keywords']
        self.keywords = kw if isinstance(kw, list) else [kw]
        locs = data.get('locations', [])
        self.locations = locs if isinstance(locs, list) else [locs]
        # map our friendly locations to naukri slugs
        self.slug_map = {
            'india (remote)': ['remote'],
            'gurugram': ['gurgaon', 'delhi-ncr'],
            'delhi': ['delhi-ncr'],
            'noida': ['noida', 'delhi-ncr'],
            'bengaluru': ['bangalore'],
            'hyderabad': ['hyderabad'],
            'pune': ['pune'],
            'dubai': ['dubai'],
        }
        options = webdriver.ChromeOptions()
        profile_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'naukri_profile')
        options.add_argument('--user-data-dir=' + profile_dir)
        if data.get('headless'):
            options.add_argument('--headless=new')
            options.add_argument('--window-size=1920,1080')
        self.driver = webdriver.Chrome(data['driver_path'], options=options)
        self.blacklist = [c.lower() for c in data.get('blacklist', ['work360', 'tantranzm'])]

    def close_extra_tabs(self):
        try:
            handles = self.driver.window_handles
            for h in handles[1:]:
                self.driver.switch_to.window(h)
                self.driver.close()
            self.driver.switch_to.window(handles[0])
        except Exception:
            pass

    def cleanup_stale(self):
        # kill leftover chrome instances of this profile only
        subprocess.run(['pkill', '-9', '-f',
                        'user-data-dir=' + os.path.join(os.path.dirname(os.path.abspath(__file__)), 'naukri_profile')],
                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

    # ---------- session ----------

    def logged_in(self):
        try:
            els = self.driver.find_elements(By.CSS_SELECTOR, 'div[class*="loggedInUser"], a[title="My Naukri"]')
            return any(e.is_displayed() for e in els)
        except Exception:
            return False

    def login_naukri(self):
        self.driver.get('https://www.naukri.com/')
        for _ in range(6):
            time.sleep(4)
            if self.logged_in():
                print('Already logged in, reusing saved session')
                return True
        print('Not logged in yet -> login manually in the browser, waiting up to 15 minutes...')
        deadline = time.time() + 900
        while time.time() < deadline:
            time.sleep(5)
            if self.logged_in():
                print('Logged in! Session saved for future runs.')
                return True
        print('Give up this run - will retry at the next scheduled run. Log in next time within 15 min.')
        return False

    # ---------- apply ----------

    def search_url(self, keyword, loc_slugs):
        kw_slug = keyword.strip().lower().replace(' ', '-')
        loc_part = '-in-' + '-and-'.join(loc_slugs) if loc_slugs else ''
        return f'https://www.naukri.com/{kw_slug}{loc_part}-jobs?k={urllib.parse.quote(kw_slug)}'

    def one_search(self, keyword, loc_slugs):
        self.driver.get(self.search_url(keyword, loc_slugs))
        time.sleep(8)
        applied = 0
        cards = self.driver.find_elements(By.CSS_SELECTOR,
            'div[class*="jobTuple"], div[class*="cust-job-tuple"], div[class*="job-card"], div[class*="srp-jobtuple"]')
        print(f'  {len(cards)} cards for: {keyword} / {",".join(loc_slugs)}')
        for card in cards:
            try:
                self.driver.execute_script('arguments[0].scrollIntoView({block:"center"});', card)
                time.sleep(0.8)
                text = card.text.lower()
                if any(c in text for c in self.blacklist):
                    continue
                self.driver.execute_script('arguments[0].click();', card)
                time.sleep(2)
                btn = None
                for b in self.driver.find_elements(By.CSS_SELECTOR, 'button'):
                    t = (b.get_attribute('aria-label') or b.text or '').strip().lower()
                    if t == 'apply' and b.is_displayed():
                        btn = b
                        break
                if not btn:
                    continue
                self.driver.execute_script('arguments[0].click();', btn)
                time.sleep(3)
                # possible confirm dialog
                for b in self.driver.find_elements(By.CSS_SELECTOR, 'button'):
                    t = (b.get_attribute('aria-label') or b.text or '').strip().lower()
                    if t in ('apply', 'yes, sure', 'continue') and b.is_displayed():
                        self.driver.execute_script('arguments[0].click();', b)
                        break
                time.sleep(2)
                applied += 1
                title = card.text.split('\n')[0][:60]
                print(f'  applied: {title}')
            except Exception as exc:
                print(f'  skipped: {type(exc).__name__}')
        return applied

    def run(self):
        try:
            self.cleanup_stale()
            time.sleep(2)
            self.driver.maximize_window()
            if not self.login_naukri():
                return
            total = 0
            for kw in self.keywords:
                for loc in self.locations:
                    slugs = self.slug_map.get(loc.lower(), [loc.lower().replace(' ', '-')])
                    try:
                        total += self.one_search(kw, slugs)
                        self.close_extra_tabs()
                        time.sleep(3)
                    except Exception as exc:
                        print(f'search failed {kw}/{slugs}: {type(exc).__name__}')
            print(f'Done. Naukri submitted this run: {total}')
        finally:
            self.driver.quit()


if __name__ == '__main__':
    with open('config.json') as config_file:
        data = json.load(config_file)
    NaukriApply(data).run()
