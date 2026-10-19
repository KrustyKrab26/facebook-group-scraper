# Facebook Group Scraper — an educational project

[![tests](https://github.com/KrustyKrab26/facebook-group-scraper/actions/workflows/tests.yml/badge.svg)](https://github.com/KrustyKrab26/facebook-group-scraper/actions/workflows/tests.yml)

A small, careful scraper for **Facebook groups you are a member of**, built for
a university multimedia / data course. It collects posts, a few comments per
post, reaction counts by type and Facebook's comment/share totals with
[Playwright](https://playwright.dev/python/), saves everything to CSV with
author names hashed, and comes with a local dashboard for running it and
exploring the data.

> **Educational use only.** Automated collection from Facebook is restricted by
> [Meta's Terms](https://www.facebook.com/terms.php) and by privacy law. Read
> [Responsible use and the law](#responsible-use-and-the-law) before running it,
> keep runs small, and never publish the raw data.
>
> **Respect the people in the group.** Every post and comment was written by a
> real person who didn't sign up to be in your dataset. Author names are
> **hashed by default — keep it that way**, and read
> [Respect others' privacy](#respect-others-privacy).
>
> **Chỉ dùng cho mục đích học tập.** Xem phần
> [Sử dụng có trách nhiệm](#sử-dụng-có-trách-nhiệm-tiếng-việt) bằng tiếng Việt.

Works on **Windows, macOS and Linux** (Python 3.10+), and in **Docker**. The
test suite runs on all three systems on every push.

---

## Contents

- [Respect others' privacy](#respect-others-privacy)
- [Features](#features)
- [What it deliberately doesn't do](#what-it-deliberately-doesnt-do)
- [Responsible use and the law](#responsible-use-and-the-law)
- [Sử dụng có trách nhiệm (tiếng Việt)](#sử-dụng-có-trách-nhiệm-tiếng-việt)
- [Quick start](#quick-start)
- [The dashboard](#the-dashboard)
- [Logging in](#logging-in)
- [Output files](#output-files)
- [Settings](#settings)
- [How it works](#how-it-works)
- [Reproducibility and tests](#reproducibility-and-tests)
- [Docker](#docker)
- [Project layout](#project-layout)
- [Troubleshooting](#troubleshooting)
- [Credits and license](#credits-and-license)

---

## Respect others' privacy

The people whose posts you collect are classmates, friends and strangers who
wrote for their group, not for a dataset. Treat what you collect as their
personal data, because it is.

**Author names are hashed — keep it that way.**

- With **Hash author names** on (the default), every author name is turned
  into a code like `user_3f9a1c07b2e4` *before anything is written to disk*.
  Real names are never saved, not in the CSVs, not in the logs.
- The code is the first 12 hex digits of SHA-256(`HASH_SALT` + name). The same
  person always gets the same code, so you can still count posts per author,
  find the most active members, or link a post to its comments — without
  knowing who anyone is.
- **`HASH_SALT` is what makes the codes safe.** Without it, nobody can turn a
  code back into a name by trying names from the member list; with it, anyone
  can. `python start.py` / `install.py` generates a random salt in `.env` on
  the first run. Keep it secret, never commit or share it, and don't change it
  later (the same person would then get a different code).
- Turning hashing off saves real names. Don't, unless you have the people's
  consent; the scraper logs a warning every run if it's off or if the salt is
  still a placeholder.

**And beyond hashing:**

- **Don't try to re-identify anyone.** Don't work out who a code belongs to,
  match posts to profiles, or combine the data with other sources.
- **Text can identify people too.** A quoted post can be searched on Facebook
  even without a name. Report counts and charts; paraphrase; quote only with
  permission.
- **Collect only what you need.** Turn off comments or reactions if your
  analysis doesn't use them. Photos are never downloaded.
- **Keep it on your computer, and delete it when you're done** (`data/groups/…`).
- **Never publish the raw data** — CSVs, codes, cookies — not even "anonymised".
- **If someone asks you to remove their posts, remove them.**

Hashing is *pseudonymisation*, not full anonymisation: the data stays personal
data, with all the care that implies.

## Features

**Collecting**
- Posts from one or more groups: text (long posts expanded), Facebook's time
  label, hashed author.
- Up to 1-5 comments per post (replies are skipped).
- Reaction counts by type (Like, Love, Care, Haha, Wow, Sad, Angry) from the
  bar under the post, or from the "who reacted" popup for every type.
- Facebook's own **comment count** and **share count** for each post.
- Vietnamese and English Facebook interfaces ("1,2K", "Bạn và 45 người khác",
  "2 giờ", "Hôm qua lúc 14:30"...).
- Optional refresh of saved posts' reactions and comments as the scraper
  scrolls past them again.

**Careful by default**
- Small runs with random pauses, a **low-risk mode** preset, a daily-pace guide.
- Stops at the first login/checkpoint/"temporarily blocked" page and warns you
  (banner, desktop notification); never retries on its own.
- Doesn't load Facebook's images, videos or fonts: about **85% less RAM** in
  testing, and less traffic.
- **Batches**: scrape N posts, rest with the page kept open, continue from the
  same place, up to a total you choose.
- Skims quickly past posts it already has, and never clicks "Xem thêm" on them.

**Privacy and security**
- **Author names hashed with a secret salt before saving** (on by default; a
  random salt is generated on install). Real names never reach the disk.
- Your Facebook session (and optional password) stored in one file encrypted
  with a passphrase you choose (scrypt + Fernet). No OS keychain needed.
- Dashboard only reachable from your own computer; other websites can't drive it.
- Data, logins and settings are all git-ignored.

**Dashboard** (http://localhost:8765)
- Overview, Posts (search and sort), Analytics (charts), Settings, Log, Account
  (log in again by browser window or by pasting cookies), light/dark theme.

**Runs anywhere**
- One command to install and start on Windows, macOS and Linux; Docker image;
  pinned dependency versions; tests on all three systems in CI.

## What it deliberately doesn't do

Facebook detects automation mostly by **volume and pace**, so this project
reduces risk by doing less. It does **not** try to hide that it is automated:

| Not done | Why |
|---|---|
| Stealth plugins / hiding Playwright's automation flags | Deliberately defeating Meta's bot detection is a much clearer Terms violation than slow, small-scale collection, and accounts caught doing it tend to be disabled for good |
| Faking the browser fingerprint | Same as above; it also makes runs harder to reproduce and to describe in a methods section |
| Rotating proxies, VPNs or IP addresses | Disguises who is collecting; sudden location changes also look like an account takeover and trigger *more* checks |
| Several accounts taking turns | Extra or fake accounts break Facebook's rules on their own |
| Solving CAPTCHAs automatically | That is circumvention. You complete any check yourself in a normal browser window |
| Retrying automatically after a checkpoint | The fastest way to get an account locked. The scraper stops and tells you |
| Replaying Facebook's internal (GraphQL) requests or opening every post separately | Many times more requests, and no longer "reading the page like a user" |
| Scraping private profiles, messages, or anything outside the groups you list | Out of scope, and a privacy problem for people who never agreed to be studied |
| Saving real names, downloading photos | Not needed for the analysis; collect as little personal data as possible |

## Responsible use and the law

This is not legal advice; the rules that apply depend on where you are.

- **Meta's Terms.** Facebook's Terms of Service do not allow collecting data by
  automated means without Meta's permission. Using this tool on Facebook may
  breach them, and Meta can restrict or disable the account used. Use an
  account you can afford to have challenged, and stop when Facebook asks you to.
- **Privacy law.** Posts and comments in a group are personal data of the
  people who wrote them. Depending on where you and they are, data-protection
  law applies (for example the GDPR in the EU, or Vietnam's personal data
  protection rules). In practice: have a clear purpose, collect only what that
  purpose needs, keep authors pseudonymous (hashing is on by default), store
  the data securely, and delete it when the course is over.
- **Private groups.** Members posted for the group, not for research; it's
  good practice to ask the admins before collecting.
- **Never publish the raw data** (posts, comments, hashes, cookies). Share
  aggregate results — counts, charts, anonymised quotes with permission —
  instead.

### If you need a large dataset

Don't make the scraper faster or harder to detect. Use a channel that allows it:

1. **Meta Content Library and API** — Meta's official access for researchers
   (application required, usually through a university). See
   [Meta's researcher tools](https://transparency.meta.com/researchtools/).
2. **Ask the group admins** for an export or written permission, and agree on
   what you'll collect and how it will be used.
3. **Use your own data**: Facebook's *Download Your Information* exports what
   you posted yourself.
4. **Use an existing, ethically collected public dataset**, or a site that
   allows scraping (e.g. `books.toscrape.com`) if the goal is learning the
   technique rather than this particular data.
5. Work with a **smaller, sampled** dataset: a few hundred posts collected
   slowly is usually enough for a learning project.

## Sử dụng có trách nhiệm (tiếng Việt)

Đây không phải tư vấn pháp lý; quy định cụ thể tuỳ nơi bạn sống và học.

- **Điều khoản của Meta** không cho phép thu thập dữ liệu Facebook bằng công
  cụ tự động khi chưa được Meta cho phép. Dùng công cụ này có thể vi phạm điều
  khoản đó và tài khoản có thể bị hạn chế hoặc khoá. Dừng ngay khi Facebook
  yêu cầu xác minh.
- **Dữ liệu cá nhân.** Bài viết và bình luận là dữ liệu cá nhân của người viết.
  Luật bảo vệ dữ liệu cá nhân (của Việt Nam, GDPR ở châu Âu...) có thể áp dụng:
  chỉ thu thập đúng phần cần cho mục đích học tập, giữ ẩn danh tác giả (đã bật
  sẵn), lưu trữ an toàn và xoá khi xong môn học.
- **Nhóm riêng tư:** nên xin phép quản trị viên trước khi thu thập.
- **Không công bố dữ liệu thô** (bài viết, bình luận, mã băm, cookie). Chỉ chia
  sẻ kết quả tổng hợp: số liệu, biểu đồ.

**Tôn trọng quyền riêng tư của người khác.** Mỗi bài viết, bình luận là của một
người thật, họ viết cho nhóm chứ không phải cho bộ dữ liệu của bạn.

- **Luôn giữ băm (hash) tên tác giả** — bật sẵn mặc định. Tên được đổi thành mã
  dạng `user_3f9a1c07b2e4` *trước khi lưu*, nên tên thật không bao giờ được ghi
  ra file. Cùng một người luôn có cùng một mã, nên vẫn đếm được số bài mỗi người.
- **Giữ bí mật `HASH_SALT`** (tạo ngẫu nhiên khi cài đặt): có salt là có thể dò
  ngược mã ra tên từ danh sách thành viên. Không commit, không chia sẻ, không
  đổi giữa chừng.
- **Không tìm cách nhận diện lại** ai đứng sau một mã, không đối chiếu với trang
  cá nhân hay nguồn dữ liệu khác.
- **Trích dẫn cẩn thận:** nội dung bài vẫn có thể tìm ra người viết. Ưu tiên số
  liệu tổng hợp, diễn đạt lại, chỉ trích nguyên văn khi được đồng ý.
- **Thu thập vừa đủ, xoá khi xong**, và **xoá bài của ai đó nếu họ yêu cầu**.
- **Cần dữ liệu lớn?** Đừng tăng tốc hay che giấu scraper. Hãy dùng kênh chính
  thức: **Meta Content Library** (dành cho nhà nghiên cứu, cần đăng ký qua
  trường), xin **quản trị viên nhóm** xuất dữ liệu hoặc cho phép bằng văn bản,
  dùng dữ liệu của chính bạn (*Tải xuống thông tin của bạn*), hoặc dùng bộ dữ
  liệu công khai đã được thu thập hợp lệ.

**Tính năng chính:** cào bài viết, 1-5 bình luận mỗi bài, số reaction theo từng
loại, số bình luận và lượt chia sẻ thật; nhiều nhóm, mỗi nhóm một thư mục; cào
theo đợt có nghỉ; chế độ an toàn (low-risk), cảnh báo checkpoint; ẩn danh tác
giả; đăng nhập lưu mã hoá; dashboard có biểu đồ phân tích; chạy trên Windows,
macOS, Linux và Docker.

---

## Quick start

Requirements: **Python 3.10 or newer** and an internet connection. Google
Chrome or Microsoft Edge is recommended (used for logging in; Playwright's own
Chromium is installed automatically for scraping).

```bash
git clone https://github.com/KrustyKrab26/facebook-group-scraper.git
cd facebook-group-scraper
python start.py          # Windows: py start.py, or double-click start.bat
```

On macOS/Linux you can also run `sh start.sh`.

The first run creates a virtual environment in `.venv`, installs the pinned
packages and Chromium, and creates `.env` from `.env.example` with a **random
`HASH_SALT`** (the secret behind the author-name codes: keep it private, back
it up, don't change it). Then the dashboard opens at <http://localhost:8765>:

1. **Account** tab: choose a vault passphrase and log in (see below).
2. **Settings** tab: add your group URL(s); keep the defaults otherwise.
3. **Start scrape**, and watch the Overview and Log tabs.

On Linux, if Chromium won't start, install its system libraries once:
`sudo .venv/bin/python -m playwright install-deps chromium`.

Recommended pace: 30-50 posts per run, 2-3 runs a day, about 100-150 posts a
day in total, daytime only. Turn on **Low-risk mode** if Facebook starts
showing checks, and stop for the day when it does.

## The dashboard

| Tab | What's there |
|---|---|
| **Overview** | Status and progress of the current run (posts, scrolls, page memory), totals, latest log lines and posts |
| **Posts** | Every saved post with reactions, comment/share counts and saved comments; search (also in comments); sort by newest, reactions, comments or shares |
| **Analytics** | Reaction mix, posts per day, when people post (weekday × hour), most-reacted posts, reactions/comments per post, top phrases |
| **Settings** | All options; unsaved changes are saved when you click **Start scrape** |
| **Log** | The full run log with a filter and a "problems only" switch |
| **Account** | Log in again: browser window or pasted cookies; vault passphrase |

The group menu under the title picks which group the dashboard shows and which
one **Start scrape** scrapes. The sun/moon button switches the colour theme;
it is unrelated to **low-risk mode** (green shield badge when on). While a
scrape runs, **Stop** finishes the current scroll, saves and closes the browser.

Post dates in Analytics are worked out from Facebook's time labels and the
moment each post was scraped, so they are approximate.

## Logging in

Facebook sessions expire. When a run ends on a login page, the dashboard says
"Facebook asked you to log in again" and links to the **Account** tab:

1. **Browser window.** Opens a normal Chrome/Edge window with a temporary
   profile on Facebook's login page. Type your login there (or let the
   dashboard type a saved email/password for you) and finish any 2FA or
   security check yourself. The dashboard notices when you're logged in, saves
   the session, closes the window and deletes the temporary profile.
2. **Paste cookies.** If Meta's check page stays blank in that window: log in
   to Facebook in a browser where it works, open DevTools (F12) → Application /
   Storage → Cookies → `https://www.facebook.com`, and copy the values of
   `c_user` and `xs` (optionally `datr`, `fr`, `sb`), or paste a whole export
   (cookie-extension JSON, `cookies.txt`, or `c_user=…; xs=…`). Close that tab
   afterwards **without logging out**.

The session goes straight into `data/vault.enc`, encrypted with your
passphrase (scrypt + Fernet). Nothing you type is logged or echoed back, and
the passphrase can't be recovered: if you forget it, delete `data/vault.enc`
and log in again. Terminal alternative: `python start.py --login`.

## Output files

Everything is written to `data/` (git-ignored):

| File | Contents |
|---|---|
| `groups/<group>/posts.csv` | post_id, author (hashed), time_text, text, scraped_at |
| `groups/<group>/comments.csv` | post_id, comment_index (1-5), author (hashed), text, scraped_at |
| `groups/<group>/reactions.csv` | post_id, total, like, love, care, haha, wow, sad, angry, comment_count, share_count, source, scraped_at, updated_at |
| `settings.json` | settings saved from the dashboard |
| `status.json`, `logs.txt` | live progress and the run log |
| `vault.enc` | your encrypted login |

`<group>` is the part of the URL after `/groups/`. Join a group's files on
`post_id`. CSVs are UTF-8 with BOM, so Excel shows Vietnamese correctly.

In `reactions.csv`, `source` says how complete the reaction counts are:
`popup` (every type counted), `bar` (Facebook only shows the top 3 types; the
total is still right), `none` (no reactions) or `off` (not collected).
`comment_count` / `share_count` are Facebook's own totals; `0` means Facebook
showed no number, empty means unknown.

## Settings

Set them in the dashboard (saved to `data/settings.json`). Values not set
there come from `.env`, then the defaults below. Options that don't apply are
greyed out.

| Setting | Default | Meaning |
|---|---|---|
| **Groups** | one example group | Group URLs, one per line (max 20) |
| Go through every group | off | Scrape all listed groups in one run |
| Pause between groups | 3 min | ±20% |
| Newest posts first | on | Chronological feed order |
| **Low-risk mode** | off | At most 30 posts per run/batch, 5-12 s pauses, no extra clicks |
| Checkpoint warning | on | Banner, notification, confirmation before starting again |
| Max new posts per run | 100 | 1-500 (not used in batch mode) |
| Auto-adjust scrolls | on | Plans enough scrolls to pass saved posts (max 300) |
| Max scrolls per run | 40 | Only when auto-adjust is off |
| Stop after N empty scrolls | 4 | When the feed stops loading |
| Pause between scrolls | 3-7 s | Random |
| a. Skim past saved posts | on | 1-2 s pauses while everything on screen is already saved |
| b. No "Xem thêm" on saved posts | on | Only expand posts about to be saved |
| c. Batches | off | Posts per batch 30, total 150, rest 120 min |
| Scrape comments / per post | on / 3 | 1-5 |
| Click "View more comments" | on | One click per post when needed |
| Scrape reactions | on | Reaction counts by type |
| Open the reactions popup | on | One click per post for every type |
| Update saved posts | off | Refresh counts and add new comments while scrolling past |
| Also use popups for saved posts | off | Up to 2 extra clicks per saved post |
| Don't load images, videos, fonts | on | Big RAM and data saver |
| Reopen the page above (MB) | 1200 | 0 = never |
| Browser / hide window | auto / off | Chromium, then Chrome, then Edge |
| **Hash author names** | on | **Keep it on.** Names become salted SHA-256 codes before saving; see [Respect others' privacy](#respect-others-privacy) |

Only in `.env`: `HASH_SALT`, `DATA_DIR`, `DASHBOARD_HOST`, `DASHBOARD_PORT`,
`SCRAPER_PASSPHRASE` (servers/Docker only).

## How it works

- **Reading the feed.** The group feed is scrolled with the mouse wheel; after
  every scroll the posts on screen are read from the page (story text, comment
  articles, reaction labels, the "48 bình luận · 5 lượt chia sẻ" line) and
  saved immediately, so stopping never loses data. Facebook removes old posts
  from the page as you scroll, which is why reading happens every scroll.
- **Saved posts.** Each run starts at the newest post; posts already in the
  CSV are skipped (optionally refreshed). Batches avoid starting over.
- **Memory.** Images, videos and fonts are blocked by URL, videos are paused,
  garbage is collected every 10 scrolls, and the tab is reopened if its memory
  passes the limit. On a test feed with large photos: 1,625 MB → 238 MB peak.
- **Speed past saved posts.** On a test feed with 60 saved posts, getting 10
  new ones went from 68 s and 72 "Xem thêm" clicks to 27 s and 10 clicks.
- **Stopping.** Login, checkpoint and 2FA pages, and "temporarily blocked" /
  "automated behaviour" notices, end the run with a warning.

## Reproducibility and tests

- Dependency versions are pinned in `requirements.txt` (Playwright 1.64.0,
  python-dotenv 1.2.4, cryptography 50.0.2); `install.py` installs exactly
  those plus the matching Chromium.
- No machine-specific paths: everything is relative to the project folder or
  `DATA_DIR`; the scraper runs the same on Windows, macOS, Linux and Docker.
- The tests never contact Facebook. They use fake feed pages
  (`tests/mock_feed.py`) with the same structure the scraper reads, a
  throwaway data folder, and a headless Chromium:

```bash
python -m unittest discover -s tests -t . -v
```

They cover number/date/cookie parsing, settings validation, the encrypted
vault, and full scrapes (posts, comments, reactions, counts, second runs,
batches, several groups). GitHub Actions runs them on Ubuntu, macOS and
Windows with Python 3.10 and 3.12, and builds the Docker image.

Facebook changes its page structure from time to time; if the scraper stops
finding posts, update the selectors in `scraper.py` (`EXTRACT_JS`,
`HELPERS_JS`) and `reactions.py` (`REACTIONS_JS`), and the fake feed with them.

## Docker

Logging in needs a visible browser, so log in once on your own computer
(`python start.py`) to create `data/vault.enc`. Then:

```bash
docker build -t fb-group-scraper .
docker run -it --rm -p 127.0.0.1:8765:8765 -v "$PWD/data:/app/data" --env-file .env fb-group-scraper
```

Enter the passphrase when asked and open <http://localhost:8765>. In
PowerShell use `-v "${PWD}/data:/app/data"`.

## Project layout

| File | Role |
|---|---|
| `start.py` / `start.bat` / `start.sh` | One-command install and start |
| `install.py` | Creates `.venv`, installs packages and Chromium, creates `.env` |
| `dashboard.py`, `dashboard.html` | Local web dashboard and its API |
| `scraper.py` | Feed reading, batches, memory handling (`main.py` runs one scrape) |
| `reactions.py` | Reaction / comment / share counts |
| `analytics.py` | Data for the Posts and Analytics tabs |
| `config.py` | Settings, defaults and validation |
| `secret_store.py` | Encrypted vault |
| `login.py`, `import_session.py`, `set_credentials.py` | Logging in from the terminal |
| `utils.py` | CSV files, logging, browser start-up |
| `tests/` | Test suite and fake feed pages |
| `Dockerfile`, `.github/workflows/tests.yml` | Container and CI |

## Troubleshooting

| Problem | Fix |
|---|---|
| `Executable doesn't exist ... chrome` | Run `python install.py` again |
| Chromium won't start on Linux | `sudo .venv/bin/python -m playwright install-deps chromium` |
| `spawn UNKNOWN` (Windows) | Your PC blocks Playwright's Chromium; it falls back to Chrome or Edge automatically |
| Blank page with only the Meta logo when logging in | Account tab → **Paste cookies** |
| Redirected to login / checkpoint / 2FA | Account tab → log in again; stop for the day if it repeats |
| "Wrong passphrase" | Retype it, or delete `data/vault.enc` and log in again |
| "No feed found" | The account must be a member of the group |
| 0 posts, empty text, no comments | Facebook changed its layout: see [Reproducibility and tests](#reproducibility-and-tests) |
| "Blocked by Facebook" | Wait a day, lower the limits, turn on low-risk mode |
| "Port 8765 is busy" | The dashboard is already open, or set `DASHBOARD_PORT` in `.env` |
| High RAM | Keep "Don't load images…" on; lower "Reopen the page above" |

## Credits and license

Started from [Lencho123/playwright-Facebook-scraper](https://github.com/Lencho123/playwright-Facebook-scraper)
(a minimal Playwright login + scroll example) and rewritten for this course
project. Released under the [MIT License](LICENSE). The license covers the
code only; it gives no rights to any data you collect, and doesn't change
your obligations under Meta's Terms or privacy law.
