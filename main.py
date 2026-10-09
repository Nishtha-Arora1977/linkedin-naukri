import time
import os
import subprocess
import urllib.parse
import json

from selenium import webdriver
from selenium.webdriver.common.keys import Keys
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.common.exceptions import NoSuchElementException, TimeoutException


class Unanswerable(Exception):
    pass


class EasyApplyLinkedin:

    def __init__(self, data):
        self.email = data['email']
        self.password = data['password']
        kw = data['keywords']
        loc = data.get('locations', [data.get('location', '')])
        self.keyword_lists = kw if isinstance(kw, list) else [kw]
        self.locations = loc if isinstance(loc, list) else [loc]
        self.ans = data.get('answers', {})
        self.rules = self.ans.get('rules', {})
        self.resume_path = self.ans.get('resume_path', '')
        options = webdriver.ChromeOptions()
        profile_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'chrome_profile')
        options.add_argument('--user-data-dir=' + profile_dir)
        self.driver = webdriver.Chrome(data['driver_path'], options=options)
        self.blacklist = [c.lower() for c in data.get('blacklist', ['work360', 'tantranzm'])]

    def cleanup_stale(self):
        # kill leftover chrome instances of this profile only
        profile_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'chrome_profile')
        subprocess.run(['pkill', '-9', '-f', 'user-data-dir=' + profile_dir],
                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

    def default_rule(self, label):
        """sensible defaults for common screening questions"""
        l = label.lower()
        if any(k in l for k in ('convict', 'criminal', 'arrest', 'felony')):
            return 'No'
        if any(k in l for k in ('interview', 'applied previously', 'applied before', 'previously applied')):
            return 'No'
        return None

    # ---------- session ----------

    def login_linkedin(self):
        self.driver.get("https://www.linkedin.com/feed/")
        time.sleep(4)
        if '/feed' in self.driver.current_url and '/checkpoint' not in self.driver.current_url:
            print('Already logged in, reusing saved session')
            return
        self.driver.get("https://www.linkedin.com/login")
        WebDriverWait(self.driver, 30).until(
            EC.presence_of_element_located((By.CSS_SELECTOR, 'input[type=email]')))

        def visible(by, value):
            for el in self.driver.find_elements(by, value):
                if el.is_displayed() and el.is_enabled():
                    return el
            raise NoSuchElementException(value)

        visible(By.CSS_SELECTOR, 'input[type=email]').send_keys(self.email)
        visible(By.CSS_SELECTOR, 'input[type=password]').send_keys(self.password)
        visible(By.CSS_SELECTOR, 'input[type=password]').send_keys(Keys.RETURN)
        WebDriverWait(self.driver, 45).until(
            lambda d: '/feed' in d.current_url or '/checkpoint' in d.current_url)
        if '/checkpoint' in self.driver.current_url:
            raise RuntimeError('LinkedIn verification needed, approve it in the browser window')
        time.sleep(3)

    # ---------- search ----------

    def job_search(self, keywords, location):
        q = ' OR '.join(keywords)
        keywords_q = urllib.parse.quote(q)
        location_q = urllib.parse.quote(location[:60])
        url = (f'https://www.linkedin.com/jobs/search/?f_AL=true'
               f'&keywords={keywords_q}&location={location_q}')
        self.driver.get(url)

        def results_loaded(d):
            return (d.find_elements(By.CSS_SELECTOR, 'li[class*="jobs-search-results__job-card"]')
                    or d.find_elements(By.CSS_SELECTOR, 'button.jobs-apply-button'))

        try:
            WebDriverWait(self.driver, 45).until(results_loaded)
        except TimeoutException:
            # retry once, LinkedIn jobs search is sometimes slow to render
            self.driver.get(url)
            WebDriverWait(self.driver, 45).until(results_loaded)
        time.sleep(3)

    # ---------- answer engine ----------

    def text_answer(self, label):
        l = label.lower()
        a = self.ans
        # explicit user rules take priority
        for k, v in self.rules.items():
            if k.lower() in l:
                return v
        dr = self.default_rule(label)
        if dr is not None:
            return dr
        if 'phone' in l or 'mobile' in l:
            return a.get('phone', '')
        if 'experience' in l or ('year' in l and 'work' in l):
            return a.get('experience_text', a.get('experience_years', ''))
        if r'\d+ years' in l or l.endswith('years'):
            return a.get('experience_years', '')
        if 'salary' in l or 'compensation' in l or 'pay' in l or 'expectation' in l or 'ctc' in l:
            return a.get('salary', '')
        if 'notice' in l or 'availab' in l or 'earliest' in l or 'start' in l or 'join' in l:
            return a.get('notice_period', '')
        if 'degree' in l or 'qualif' in l or 'education' in l or 'b.tech' in l or 'btech' in l:
            return a.get('degree', '')
        if 'university' in l or 'college' in l or 'school' in l or 'institute' in l:
            return a.get('university', '')
        if 'graduat' in l or 'completion' in l or 'passing' in l:
            return a.get('graduation_year', '')
        if 'company' in l or 'employer' in l or 'organi' in l:
            return a.get('current_company', '')
        if 'email' in l:
            return self.email
        if 'city' in l and 'location' in l or 'current location' in l:
            return a.get('city', '')
        if 'first name' in l:
            return a.get('first_name', '')
        if 'last name' in l:
            return a.get('last_name', '')
        if 'name' in l:
            return a.get('full_name', '')
        if 'cover letter' in l or 'message' in l or 'why' in l:
            return a.get('cover_letter', '')
        return None

    def radio_answer(self, label, options):
        """returns index of the option to pick"""
        l = label.lower()
        texts_low = [o.text.strip().lower() for o in options]

        def pick(pred):
            for i, t in enumerate(texts_low):
                if pred(t):
                    return i
            return None

        if 'experience' in l or 'years' in l:
            # 1.5 years -> look for the 1-2 years bucket
            idx = pick(lambda t: t in ('1 year', '1', '1-2 years', '1 to 2 years', '1 - 2 years'))
            if idx is None:
                idx = pick(lambda t: t.startswith('1'))
            if idx is not None:
                return idx
            return 0
        if 'notice' in l or 'availab' in l or 'earliest' in l or 'start' in l or 'join' in l:
            idx = pick(lambda t: 'immediate' in t or t == 'now')
            if idx is None:
                idx = pick(lambda t: '0' in t.split()[0])
            if idx is not None:
                return idx
            return 0
        if 'relocat' in l or 'willing' in l or 'authoriz' in l or 'legal' in l or 'eligible' in l or 'able' in l:
            idx = pick(lambda t: t.startswith('yes'))
            if idx is not None:
                return idx
        if 'sponsor' in l:
            # authorized without sponsorship
            idx = pick(lambda t: 'no sponsorship' in t or 'do not require' in t or ('yes' in t and 'sponsor' not in t))
            if idx is not None:
                return idx
        if 'salary' in l or 'expectation' in l or 'pay' in l or 'ctc' in l or 'compensation' in l:
            idx = pick(lambda t: '6' in t.replace(',', '').replace('lpa', '').replace('lakh', ''))
            if idx is not None:
                return idx
            return None
        if 'work type' in l or 'workplace' in l or 'remote' in l or 'hybrid' in l or 'on-site' in l or 'onsite' in l:
            # any: prefer remote in that order remote/hybrid/onsite
            for key in ('remote', 'hybrid', 'on-site', 'onsite', 'any'):
                idx = pick(lambda t, k=key: k in t)
                if idx is not None:
                    return idx
            return None
        idx = pick(lambda t: t.startswith('yes'))
        if idx is not None:
            return idx
        return None

    def fill_page(self, m):
        """best effort fill of all questions inside modal; raises Unanswerable if a required question cannot be answered"""
        elements = m.find_elements(By.CSS_SELECTOR, '.fb-dash-form-element')
        for el in elements:
            labels = el.find_elements(By.CSS_SELECTOR, 'label')
            label = labels[0].text.strip() if labels else ''
            # plain text / number / tel inputs
            filled = False
            for inp in el.find_elements(By.CSS_SELECTOR, 'input'):
                t = (inp.get_attribute('type') or '').lower()
                if not inp.is_displayed() or t in ('hidden', 'checkbox', 'radio', 'file'):
                    continue
                if (inp.get_attribute('value') or '').strip():
                    filled = True
                    continue
                ans = self.text_answer(label)
                if ans:
                    try:
                        inp.clear()
                        inp.send_keys(str(ans))
                        filled = True
                    except Exception:
                        pass
            # selects
            for sel in el.find_elements(By.CSS_SELECTOR, 'select'):
                if not (sel.get_attribute('value') or '').strip():
                    opts = sel.find_elements(By.CSS_SELECTOR, 'option')
                    idx = self.radio_answer(label, opts) if opts else None
                    if idx is not None and idx < len(opts):
                        sel.click()
                        opts[idx].click()
                        filled = True
                    else:
                        raise Unanswerable(f'select: {label}')
            # radio groups
            for field in el.find_elements(By.CSS_SELECTOR, 'fieldset'):
                legend = field.text.strip().lower()
                labs = field.find_elements(By.CSS_SELECTOR, 'label')
                idx = self.radio_answer(legend or label, labs)
                if idx is not None and idx < len(labs):
                    self.driver.execute_script('arguments[0].click();', labs[idx])
                    filled = True
                else:
                    raise Unanswerable(f'radio: {label} {legend}')
            # textareas (cover letter etc.)
            for ta in el.find_elements(By.CSS_SELECTOR, 'textarea'):
                if not (ta.get_attribute('value') or '').strip():
                    ans = self.text_answer(label)
                    if not ans:
                        raise Unanswerable(f'textarea: {label}')
                    ta.click()
                    ta.send_keys(ans)
                    filled = True
        return True

    # ---------- apply ----------

    def detect_insufficient(self, card_text):
        # blacklisted companies
        hit = [c for c in self.blacklist if c in card_text.lower()]
        return hit[0] if hit else None

    def get_page_offers(self):
        time.sleep(3)
        cards = self.driver.find_elements(By.CSS_SELECTOR, 'li[class*="jobs-search-results__job-card"]')
        applied = 0
        for card in cards:
            self.driver.execute_script('arguments[0].scrollIntoView({block: "center"});', card)
            time.sleep(1)
            try:
                self.dismiss_modals()  # close any leftover overlay first
                drift = self.detect_insufficient(card.text)
                if drift:
                    print(f'  skipping job at blacklisted company: {drift}')
                    continue
                # card content is lazy rendered: scroll and retry until the link appears
                link = None
                for _ in range(3):
                    try:
                        link = card.find_element(By.CSS_SELECTOR, 'a[href*="/jobs/view/"]')
                        break
                    except NoSuchElementException:
                        self.driver.execute_script('arguments[0].scrollIntoView({block: "center"});', card)
                        time.sleep(1.5)
                if not link:
                    print('  card did not render, skipping')
                    continue
                self.driver.execute_script('arguments[0].click();', link)
                time.sleep(2)

                btn = None
                for b in self.driver.find_elements(By.CSS_SELECTOR, 'button.jobs-apply-button'):
                    if b.is_displayed():
                        btn = b
                        break
                self.dismiss_modals()
                if not btn:
                    continue
                label = btn.get_attribute('aria-label') or btn.text
                if 'Applied' in label:
                    continue
                self.driver.execute_script('arguments[0].click();', btn)
                applied += self.easy_apply()
            except Exception as exc:
                import traceback
                tb = traceback.extract_tb(exc.__traceback__)
                where = tb[-1].name if tb else '?'
                print(f'  skipped a job: {type(exc).__name__} at {where}: {str(exc).split(chr(10))[0][:120]}')
                self.dismiss_modals()
        return applied

    def modal(self):
        for _ in range(3):
            try:
                el = self.driver.find_element(By.CSS_SELECTOR, 'div.jobs-easy-apply-modal')
                if el.is_displayed():
                    return el
            except NoSuchElementException:
                pass
            time.sleep(2)
        return None

    def required_empty(self, m):
        """list required-but-unanswered fields in the modal"""
        return self.driver.execute_script("""
const m = arguments[0];
let bad = [];
const fields = [...m.querySelectorAll('input,select,textarea')];
for (const f of fields) {
  const t = (f.getAttribute('type')||'').toLowerCase();
  if (t==='hidden'||t==='checkbox'||t==='radio'||t==='file') continue;
  if (!(f.offsetWidth||f.offsetHeight)) continue;
  const label = (f.closest('div[class*="form-element"]')?.querySelector('label')?.textContent) || '';
  const required = label.includes('*') || f.required || f.getAttribute('aria-required')==='true';
  if (!required) continue;
  let v;
  if (f.tagName==='SELECT') v = f.value;
  else if (f.tagName==='TEXTAREA') v = f.value || f.textContent;
  else v = f.value;
  if (!(v||'').trim()) bad.push(label.trim().slice(0,50) + ' [' + f.tagName + ' type=' + (t||'-') + ']');
}
const sets = [...m.querySelectorAll('fieldset')];
for (const s of sets) {
  const text = (s.querySelector('legend')?.textContent) || s.textContent || '';
  if (!text.includes('*') && !(s.textContent||'').includes('*')) continue;
  const anyChecked = [...s.querySelectorAll('input')].some(i=>i.checked);
  if (!anyChecked) bad.push('radio-group: ' + text.trim().slice(0,50));
}
return bad;
""", m)

    def attach_resume(self, m):
        for b in m.find_elements(By.CSS_SELECTOR, 'input[type=file]'):
            if self.resume_path and os.path.exists(self.resume_path):
                b.send_keys(self.resume_path)
                time.sleep(2)
                return True
            return self.resume_path and os.path.exists(self.resume_path)
        return True  # already attached/prefilled or not required

    def review_submit(self, m):
        try:
            submit = m.find_element(By.XPATH, './/footer//button[normalize-space()="Submit application"]')
            if submit.is_displayed():
                if not self.attach_resume(m):
                    print('  resume required but not found, skipping')
                    return False
                self.driver.execute_script('arguments[0].click();', submit)
                time.sleep(3)
                return True
        except NoSuchElementException:
            pass
        return False

    def easy_apply(self):
        m = self.modal()
        if not m:
            return 0
        time.sleep(1)

        def footer_button(label):
            try:
                b = m.find_element(
                    By.XPATH, f'.//footer//button[normalize-space()="{label}"]')
                return b if b.is_displayed() else None
            except NoSuchElementException:
                return None

        # step through pages: contact info -> resume -> questions -> review
        seen = []
        for _ in range(12):
            try:
                m = self.modal()
                if not m:
                    return 0
            except Exception:
                return 0
            try:
                self.fill_page(m)
            except Unanswerable as err:
                print(f'  cannot answer {err} -> skipping job')
                self.dismiss_modals()
                return 0
            except NoSuchElementException as err:
                print(f'  fill error -> skipping job')
                self.dismiss_modals()
                return 0
            btn = footer_button('Review') or footer_button('Next')
            if btn is None:
                ok = self.review_submit(m)
                self.dismiss_modals()
                return 1 if ok else 0
            page = m.text[:80]
            if page in seen:
                bad = self.required_empty(m)
                if bad:
                    print(f'  {len(bad)} required field(s) still unanswered: {bad} -> skipping job')
                    self.dismiss_modals()
                    return 0
                # modal refuses to advance and nothing required missing: stop
                self.dismiss_modals()
                return 0
            seen.append(page)
            self.driver.execute_script('arguments[0].click();', btn)
            time.sleep(2)
        return 0

    def dismiss_modals(self):
        for _ in range(5):
            overlay = self.driver.find_elements(
                By.CSS_SELECTOR, 'div.artdeco-modal-overlay--is-top-layer')
            if not overlay:
                return
            # close via esc / X button
            try:
                self.driver.switch_to.active_element.send_keys(Keys.ESCAPE)
            except Exception:
                pass
            time.sleep(1)
            for label in ('Discard', 'Dismiss'):
                for b in self.driver.find_elements(By.XPATH, f'//button[normalize-space()="{label}"]'):
                    if b.is_displayed():
                        try:
                            self.driver.execute_script('arguments[0].click();', b)
                            time.sleep(1)
                        except Exception:
                            pass
            try:
                x = self.driver.find_element(By.CSS_SELECTOR, 'button[data-test-modal-close-btn]')
                if x.is_displayed():
                    self.driver.execute_script('arguments[0].click();', x)
                    time.sleep(1)
            except NoSuchElementException:
                pass
            time.sleep(1)

    # ---------- pagination ----------

    def find_offers(self):
        applied = 0
        for loc in self.locations:
            print(f'=== searching: {"|".join(self.keyword_lists)} in {loc} ===', flush=True)
            self.job_search(self.keyword_lists, loc)
            applied += self.search_all_pages()
        print(f'Done. Jobs submitted this run: {applied}')

    def search_all_pages(self):
        applied = 0
        while True:
            applied += self.get_page_offers()
            time.sleep(2)
            nxt = None
            for b in self.driver.find_elements(
                    By.CSS_SELECTOR, 'button[aria-label="View next page"], button.jobs-search-pagination__button--next'):
                if b.is_displayed() and b.is_enabled():
                    nxt = b
                    break
            if nxt is None:
                break
            prev_url = self.driver.current_url
            self.driver.execute_script('arguments[0].click();', nxt)
            time.sleep(5)
            if self.driver.current_url == prev_url:
                break
        return applied

    # ---------- lifecycle ----------

    def close_session(self):
        self.driver.quit()

    def apply(self):
        try:
            self.cleanup_stale()
            time.sleep(2)
            self.driver.maximize_window()
            self.login_linkedin()
            self.find_offers()
        finally:
            self.close_session()


if __name__ == '__main__':
    with open('config.json') as config_file:
        data = json.load(config_file)
    bot = EasyApplyLinkedin(data)
    bot.apply()
