import hashlib
import itertools
import math
import os
import random
import re
import time
from datetime import datetime, timedelta

from playwright.sync_api import sync_playwright

from config import (
    AUTO_SCROLL_CAP, AUTO_SCROLL_LIMIT, BATCH_MODE, BATCH_POSTS, BATCH_REST_MIN, BATCH_TOTAL, BLOCK_MEDIA, COLLECT_REACTIONS, EXPAND_COMMENTS, EXPAND_REACTIONS,
    FAST_FORWARD, GROUP_PAUSE_MIN, GROUPS, SKIP_SEE_MORE_SAVED, STOP_FILE, HEADLESS, LOW_RISK_MODE, MAX_COMMENTS_PER_POST, MAX_DELAY, MAX_IDLE_SCROLLS,
    MAX_POSTS, MIN_DELAY, RECYCLE_MB, SCRAPE_ALL_GROUPS, SCROLL_LIMIT, SELECTED_GROUP, SORT_CHRONOLOGICAL,
    UPDATE_SAVED, UPDATE_SAVED_CLICKS, GroupFiles, group_slug,
)
import reactions
from secret_store import VaultError, load_session
from utils import (
    anonymize, clean_saved_files, describe_migration, launch_browser, load_existing_ids, load_saved_engagement, log_message,
    migrate_legacy_data, record_checkpoint, save_comments_to_csv, save_posts_to_csv, save_reactions_to_csv,
    update_comment_texts, update_reactions_csv, write_status,
)

SEE_MORE = re.compile(r"^\s*(See more|Xem thêm)\s*$")

# Shared browser-side helpers. A comment is a role=article inside the post,
# labelled "Comment by ..." / "Bình luận ..."; replies ("Reply by ...") are skipped.
HELPERS_JS = r"""
// Facebook's "Xem thêm"/"Ẩn bớt" (See more/less) buttons sit inside the text;
// keep their labels out of what we save. Same rules as utils.clean_text.
function cleanText(t) {
  return (t || "").split("\n")
    .filter(l => !/^\s*(xem thêm|ẩn bớt|see more|see less)\s*$/i.test(l))
    .join("\n")
    .replace(/\s*(ẩn bớt|see less)\s*$/i, "")
    .replace(/(…|\.\.\.)\s*(xem thêm|see more)\s*$/i, "…")
    .trim();
}
const isCommentLabel = a => /^(comment|bình luận)/i.test(a.getAttribute("aria-label") || "");
const isReplyLabel = a => /^(reply|phản hồi|trả lời)/i.test(a.getAttribute("aria-label") || "");
// True if el belongs to post p itself, not to one of its comments
function notInComment(el, p) {
  const art = el.closest("div[role='article']");
  return !art || art === p || art.contains(p) || !(isCommentLabel(art) || isReplyLabel(art));
}

function commentsIn(root, max) {
  const all = Array.from(root.querySelectorAll("div[role='article']"))
    .filter(a => a !== root && !a.hasAttribute("aria-posinset"));
  let top = all.filter(isCommentLabel);
  if (!top.length) {
    // No labels: take articles that aren't nested inside another comment
    top = all.filter(a => !isReplyLabel(a))
      .filter(a => !all.includes(a.parentElement.closest("div[role='article']")));
  }
  return top.slice(0, max).map(c => {
    const authorEl = c.querySelector("a[role='link'] span, a span");
    const author = authorEl ? authorEl.innerText.trim() : "";
    const lines = Array.from(c.querySelectorAll("div[dir='auto'], span[dir='auto']"))
      .filter(d => !d.querySelector("[dir='auto']"))
      .filter(d => d.closest("div[role='article']") === c)  // not text from replies
      .map(d => d.innerText.trim())
      .filter(t => t && t !== author);
    return { author, text: cleanText([...new Set(lines)].join("\n")) };
  }).filter(c => c.text);
}
"""

MORE_COMMENTS = (
    r"/^(view (more|all|previous|\d+ more) comments?|view all \d+ comments|"
    r"xem thêm bình luận|xem (tất cả )?\d+ bình luận|xem \d+ bình luận khác|xem bình luận trước)/i"
)

# Runs in the browser: returns the posts currently rendered in the group feed,
# each with up to `max` comments already visible under it.
# Facebook virtualizes the feed (old posts get removed from the DOM as you
# scroll), so this is called after every scroll, not once at the end.
EXTRACT_JS = r"""
({ max, withReactions }) => {
""" + HELPERS_JS + reactions.REACTIONS_JS + r"""
  const feed = document.querySelector("div[role='feed']");
  if (!feed) return [];

  // Tags from the previous call would point at the wrong posts now
  document.querySelectorAll("[data-fbs-idx]").forEach(e => e.removeAttribute("data-fbs-idx"));
  document.querySelectorAll("[data-fbs-more]").forEach(e => e.removeAttribute("data-fbs-more"));
  document.querySelectorAll("[data-fbs-react]").forEach(e => e.removeAttribute("data-fbs-react"));

  // Top-level posts carry aria-posinset; comments are role=article without it
  let posts = Array.from(feed.querySelectorAll("div[aria-posinset]"));
  if (!posts.length) {
    posts = Array.from(feed.querySelectorAll("div[role='article']"))
      .filter(a => !a.parentElement.closest("div[role='article']"));
  }

  return posts.map((p, idx) => {
    p.setAttribute("data-fbs-idx", idx);

    const link = p.querySelector("a[href*='/posts/'], a[href*='/permalink/']");
    const match = link && link.href.match(/\/(?:posts|permalink)\/(\d+)/);

    const authorEl = p.querySelector("h2 a, h3 a, h2 strong, h3 strong");

    const msg = p.querySelector(
      "[data-ad-rendering-role='story_message'], [data-ad-preview='message'], [data-ad-comet-preview='message']"
    );
    let text = msg ? msg.innerText : "";
    if (!text) {
      // Fallback: the longest leaf text block in the post, ignoring comments
      const blocks = Array.from(p.querySelectorAll("div[dir='auto']"))
        .filter(d => !d.querySelector("div[dir='auto']"))
        .filter(d => notInComment(d, p))
        .map(d => d.innerText.trim());
      text = blocks.sort((a, b) => b.length - a.length)[0] || "";
    }

    const moreBtn = Array.from(p.querySelectorAll("div[role='button'], span[role='button']"))
      .find(b => """ + MORE_COMMENTS + r""".test(b.innerText.trim()));
    if (moreBtn) moreBtn.setAttribute("data-fbs-more", idx);

    return {
      idx,
      post_id: match ? match[1] : null,
      author: authorEl ? authorEl.innerText.trim() : "",
      time_text: link ? (link.getAttribute("aria-label") || link.innerText).trim() : "",
      text: cleanText(text),
      comments: max > 0 ? commentsIn(p, max) : [],
      has_more_comments: !!moreBtn,
      reactions: withReactions ? reactionsIn(p, idx, el => notInComment(el, p)) : null,
      counts: footerCounts(p, el => notInComment(el, p)),
    };
  });
}
"""

# Same comment logic, run on one element (an expanded post or a post dialog)
COMMENTS_JS = "(root, max) => {" + HELPERS_JS + "return commentsIn(root, max); }"


def human_pause(low=MIN_DELAY, high=MAX_DELAY):
    time.sleep(random.uniform(low, high))


def expand_see_more(page, root="div[role='feed']"):
    """Click "Xem thêm" on long posts and comments so the full text is saved."""
    buttons = page.locator(f"{root} [role='button']").filter(has_text=SEE_MORE)
    # Each click removes that button, so the list shifts: always take the first.
    # A button that won't click is skipped by remembering how many are left.
    stuck = 0
    for _ in range(buttons.count()):
        if buttons.count() <= stuck:
            break
        try:
            buttons.nth(stuck).click(timeout=2000)
            time.sleep(random.uniform(0.3, 0.8))
        except Exception:
            stuck += 1


def close_dialog(page, dialogs_before):
    dialogs = page.locator("div[role='dialog']")
    page.keyboard.press("Escape")
    time.sleep(random.uniform(0.8, 1.5))
    if dialogs.count() > dialogs_before:
        close = dialogs.last.locator("[aria-label='Close'], [aria-label='Đóng']").first
        try:
            close.click(timeout=2000)
            time.sleep(random.uniform(0.8, 1.5))
        except Exception:
            pass
    return dialogs.count() <= dialogs_before


def load_more_comments(page, idx):
    """Click a post's "View more comments" once and read up to the limit.

    Facebook either expands the comments in place or opens the post in a
    dialog; both are handled. Returns None if nothing could be read.
    """
    dialogs = page.locator("div[role='dialog']")
    before = dialogs.count()
    try:
        page.locator(f"[data-fbs-more='{idx}']").first.click(timeout=3000)
    except Exception:
        return None
    human_pause(1.5, 3.5)

    if dialogs.count() > before:
        try:
            expand_see_more(page, "div[role='dialog']")
            comments = dialogs.last.evaluate(COMMENTS_JS, MAX_COMMENTS_PER_POST)
        finally:
            if not close_dialog(page, before):
                log_message("Couldn't close a post dialog")
        return comments

    try:
        expand_see_more(page, f"[data-fbs-idx='{idx}']")
        return page.locator(f"[data-fbs-idx='{idx}']").first.evaluate(COMMENTS_JS, MAX_COMMENTS_PER_POST)
    except Exception:
        return None


def load_reaction_popup(page, idx):
    """Open a post's "who reacted" popup and read the count on each type's tab."""
    dialogs = page.locator("div[role='dialog']")
    before = dialogs.count()
    try:
        page.locator(f"[data-fbs-react='{idx}']").first.click(timeout=3000)
        page.wait_for_function(f"document.querySelectorAll(\"div[role='dialog']\").length > {before}", timeout=6000)
    except Exception:
        return None
    try:
        dialogs.last.locator("[role='tab']").first.wait_for(timeout=5000)
        return dialogs.last.evaluate(reactions.DIALOG_JS)
    except Exception:
        return None
    finally:
        human_pause(1, 2.5)
        if not close_dialog(page, before):
            log_message("Couldn't close a reactions popup")


def refresh_saved_post(page, post, key, saved_reacts, saved_comments):
    """Re-read a post saved in an earlier run. Returns (reaction row or None, new comment rows).

    Without UPDATE_SAVED_CLICKS only what's already on screen is used (the
    reaction bar and the 1-2 comments under the post), so no extra clicks.
    """
    now = datetime.now().isoformat(timespec="seconds")

    new_comment_rows, completed = [], {}
    existing = saved_comments.get(key, [])
    if MAX_COMMENTS_PER_POST:
        comments = post["comments"]
        if (UPDATE_SAVED_CLICKS and EXPAND_COMMENTS and post["has_more_comments"]
                and len(existing) < MAX_COMMENTS_PER_POST):
            comments = load_more_comments(page, post["idx"]) or comments
        for c in comments:
            author = anonymize(c["author"])
            for old in existing:
                cut = old["text"].rstrip("…").rstrip()
                if (old["author"] == author and old["text"].endswith("…") and not c["text"].endswith("…")
                        and len(c["text"]) > len(cut) and c["text"].startswith(cut)):
                    old["text"] = c["text"]
                    completed[(key, str(old["comment_index"]))] = c["text"]
        known = {(c["author"], c["text"]) for c in existing}
        n = len(existing)
        for c in comments:
            if n >= MAX_COMMENTS_PER_POST:
                break
            author = anonymize(c["author"])
            if (author, c["text"]) in known:
                continue
            n += 1
            known.add((author, c["text"]))
            new_comment_rows.append({"post_id": key, "comment_index": n, "author": author,
                                     "text": c["text"], "scraped_at": now})
        saved_comments[key] = existing + new_comment_rows

    reaction_row = None
    popup = None
    if COLLECT_REACTIONS and UPDATE_SAVED_CLICKS and EXPAND_REACTIONS and post["reactions"]["hasButton"]:
        popup = load_reaction_popup(page, post["idx"])
    row, changed = reactions.merge_row(
        saved_reacts.get(key), reactions.build_row(key, post["reactions"], popup, now, post["counts"]), now)
    if changed:
        saved_reacts[key] = reaction_row = row
    return reaction_row, new_comment_rows, completed


POSTS_PER_SCROLL_GUESS = 6


def estimate_scrolls(already_saved, scrolls_done, posts_seen, want=MAX_POSTS):
    """Auto mode: scrolls needed to pass the saved posts and collect `want` new ones.

    Starts from a guess of ~6 posts per scroll, then uses the rate this run is
    actually getting. Recomputed after every scroll; never above AUTO_SCROLL_CAP.
    """
    rate = POSTS_PER_SCROLL_GUESS
    if scrolls_done >= 3 and posts_seen:
        rate = max(1.0, posts_seen / scrolls_done)
    remaining = max(0, already_saved + want - posts_seen)
    return max(scrolls_done + 1, min(AUTO_SCROLL_CAP, scrolls_done + math.ceil(remaining / rate) + 5))


def nudge_feed(page):
    try:
        page.locator("div[role='feed'] [aria-posinset], div[role='feed'] > div").last.scroll_into_view_if_needed(timeout=3000)
    except Exception:
        pass
    page.mouse.wheel(0, random.randint(600, 1200))


BLOCK_TEXT = re.compile(
    r"(temporarily blocked|tạm thời bị chặn|automated behavior|hành vi tự động|"
    r"confirm (it's|that it's) you|xác nhận (đó là bạn|bạn là con người)|you can't use this feature|"
    r"bạn không thể sử dụng tính năng này)", re.I)


def blocked(page):
    """Login/checkpoint/2FA page, or a "you're temporarily blocked" style notice."""
    if any(part in page.url for part in ("/checkpoint", "/login", "/two_step_verification")):
        return True
    try:
        notices = page.locator("div[role='dialog'], div[role='alert']").all_inner_texts()
    except Exception:
        return False
    return any(BLOCK_TEXT.search(t) for t in notices)


# Facebook's own images, videos and fonts. Blocking them by URL (not with
# page.route) keeps the browser cache working for its scripts.
MEDIA_URL_PATTERNS = [
    "*scontent*.fbcdn.net/*", "*video*.fbcdn.net/*",
    "*.jpg*", "*.jpeg*", "*.png*", "*.gif*", "*.webp*", "*.mp4*", "*.webm*",
    "*.woff*", "*.ttf*", "*.otf*",
]

# Runs in the page after each scroll: stop videos that are already there
PAUSE_MEDIA_JS = """() => {
  for (const v of document.querySelectorAll("video")) {
    try { v.pause(); v.preload = "none"; v.removeAttribute("src"); v.load(); } catch (e) {}
  }
}"""


class FeedPage:
    """One browser tab on a group's feed, with memory measuring and blocking set up."""

    def __init__(self, context, url):
        self.context, self.url = context, url
        self.page = context.new_page()
        self.cdp = context.new_cdp_session(self.page)
        self.cdp.send("Performance.enable")
        if BLOCK_MEDIA:
            self.cdp.send("Network.enable")
            self.cdp.send("Network.setBlockedURLs", {"urls": MEDIA_URL_PATTERNS})

    def open(self):
        """Load the feed. Returns None, or (state, message) if it can't be used."""
        log_message(f"Opening {self.url}")
        self.page.goto(self.url)
        human_pause(5, 8)
        if blocked(self.page):
            return "blocked", "Redirected to login/checkpoint. Log in again in the dashboard's Account tab."
        try:
            self.page.wait_for_selector("div[role='feed']", timeout=20000)
        except Exception:
            return "error", "No feed found. Are you a member of the group, and is the session still valid?"
        return None

    def memory_mb(self):
        """JavaScript memory of this tab, the part that grows while scrolling."""
        try:
            metrics = {m["name"]: m["value"] for m in self.cdp.send("Performance.getMetrics")["metrics"]}
            return round(metrics.get("JSHeapUsedSize", 0) / 2**20)
        except Exception:
            return 0

    def tidy(self, collect_garbage=False):
        try:
            self.page.evaluate(PAUSE_MEDIA_JS)
            if collect_garbage:
                self.cdp.send("HeapProfiler.collectGarbage")
        except Exception:
            pass

    def close(self):
        try:
            self.page.close()
        except Exception:
            pass


def stop_requested():
    return os.path.exists(STOP_FILE)


def wait(seconds, status, message, state="running"):
    """Sleep in short steps so the Stop button works. Returns False if stopped."""
    until = datetime.now() + timedelta(seconds=seconds)
    status.update(state=state, message=message, next_batch_at=until.isoformat(timespec="seconds")
                  if state == "resting" else "")
    write_status(status)
    beat = time.time()
    while datetime.now() < until:
        if stop_requested():
            return False
        if time.time() - beat > 60:  # heartbeat, so the dashboard knows we're alive
            write_status(status)
            beat = time.time()
        time.sleep(min(5, max(0.1, (until - datetime.now()).total_seconds())))
    status["next_batch_at"] = ""
    return True


def post_key(post):
    return post["post_id"] or "h_" + hashlib.sha256(post["text"].encode("utf-8")).hexdigest()[:16]


class GroupRun:
    """One group's scraping, which can stop after a batch and later continue
    from the same place in the feed (its tab stays open in between)."""

    def __init__(self, context, url, status):
        self.context, self.status = context, status
        self.files = files = GroupFiles(url)
        for name, n in clean_saved_files(files).items():
            log_message(f"Removed 'Xem thêm'/'Ẩn bớt' button text from {n} rows of {name} (backup: {name}.bak)")
        self.seen = load_existing_ids(files)
        self.saved_before = set(self.seen)
        log_message(f"{len(self.seen)} posts already saved for {files.slug}, they will be skipped")
        self.url = files.url.rstrip("/")
        if SORT_CHRONOLOGICAL and self.url.startswith("http"):
            self.url += "/?sorting_setting=CHRONOLOGICAL"
        self.saved_reacts, self.saved_comments = load_saved_engagement(files) if UPDATE_SAVED else ({}, {})
        self.refreshed = set()
        # Every post the feed has shown, saved before or not. Scrolling past
        # already-saved posts is still progress: older, unsaved posts are
        # further down, so only a feed that stops loading counts as idle.
        self.encountered = set()
        # Same, but since the tab was last (re)opened: after reopening, the
        # feed starts from the top again and those posts count as progress.
        self.since_open = set()
        self.idle = 0
        self.recycles, self.last_recycle = 0, 0
        self.scrolls = 0
        self.new = self.comments = self.skipped = self.updated = 0
        self.feed = None
        self.ended = None  # (state, message) once this group can't continue

    def open(self):
        self.feed = FeedPage(self.context, self.url)
        problem = self.feed.open()
        if problem:
            self.close()
        return problem

    def close(self):
        if self.feed:
            self.feed.close()
            self.feed = None

    def summary(self, reason):
        return (f"{reason}. Saved {self.new} new posts and {self.comments} comments "
                f"(scrolled past {self.skipped} already saved"
                + (f", updated {self.updated} of them" if UPDATE_SAVED else "") + ").")

    def run_batch(self, want):
        """Scroll until `want` new posts are saved. Returns (state, reason, new posts).

        state "more" means the group can continue later; "done", "blocked",
        "error" and "stopped" mean it can't.
        """
        if self.feed is None:
            problem = self.open()
            if problem:
                return problem[0], problem[1], 0
        status = self.status
        page = self.feed.page
        if blocked(page):
            return "blocked", "Checkpoint appeared while resting", 0

        # Saved posts still ahead of us in the feed (the ones not passed yet)
        ahead = max(0, len(self.saved_before) - self.skipped)
        auto = AUTO_SCROLL_LIMIT
        limit = estimate_scrolls(ahead, 0, 0, want) if auto else SCROLL_LIMIT
        mode = " (auto)" if auto else ""
        if auto:
            log_message(f"Planning about {limit} scrolls for {want} new posts")
        status.update(state="running", scroll_limit=self.scrolls + limit, next_batch_at="")
        write_status(status)

        got = 0
        b_scrolls = b_seen = 0
        while True:
            if stop_requested():
                return "stopped", "Stopped from the dashboard", got
            if b_scrolls >= limit:
                return ("more" if BATCH_MODE else "done"), f"Reached the scroll limit ({limit}{mode})", got
            page = self.feed.page

            posts = self.read_posts(page, want - got)
            batch, comment_rows, reaction_rows = [], [], []
            reaction_updates, comment_fixes = {}, {}
            fresh = fresh_saved = skipped = updated = 0
            for post in posts:
                if len(batch) >= want - got:
                    break
                if not post["text"] and not post["post_id"]:
                    continue
                key = post_key(post)
                if key not in self.since_open:
                    self.since_open.add(key)
                    fresh += 1
                    fresh_saved += key in self.seen
                if key not in self.encountered:
                    self.encountered.add(key)
                    b_seen += 1
                    if key in self.seen:
                        skipped += 1
                if key in self.seen:
                    if UPDATE_SAVED and key in self.saved_before and key not in self.refreshed:
                        self.refreshed.add(key)
                        row, new_comments, completed = refresh_saved_post(
                            page, post, key, self.saved_reacts, self.saved_comments)
                        if row:
                            reaction_updates[key] = row
                        comment_rows += new_comments
                        comment_fixes.update(completed)
                        updated += bool(row or new_comments or completed)
                    continue
                self.seen.add(key)

                comments = post["comments"]
                if (EXPAND_COMMENTS and post["has_more_comments"]
                        and len(comments) < MAX_COMMENTS_PER_POST):
                    comments = load_more_comments(page, post["idx"]) or comments

                now = datetime.now().isoformat(timespec="seconds")
                popup = None
                if COLLECT_REACTIONS and EXPAND_REACTIONS and post["reactions"]["hasButton"]:
                    popup = load_reaction_popup(page, post["idx"])
                reaction_rows.append(reactions.build_row(key, post["reactions"], popup, now, post["counts"]))
                for n, c in enumerate(comments[:MAX_COMMENTS_PER_POST], 1):
                    comment_rows.append({
                        "post_id": key, "comment_index": n,
                        "author": anonymize(c["author"]), "text": c["text"], "scraped_at": now,
                    })
                batch.append({
                    "post_id": key, "author": anonymize(post["author"]),
                    "time_text": post["time_text"], "text": post["text"], "scraped_at": now,
                })

            # Save every scroll so nothing is lost if the run stops early
            files = self.files
            save_posts_to_csv(files, batch)
            save_comments_to_csv(files, comment_rows)
            save_reactions_to_csv(files, reaction_rows)
            update_reactions_csv(files, reaction_updates)
            update_comment_texts(files, comment_fixes)
            got += len(batch)
            self.new += len(batch)
            self.comments += len(comment_rows)
            self.skipped += skipped
            self.updated += updated
            self.scrolls += 1
            b_scrolls += 1

            # a. Everything new on screen was already saved: hurry on
            fast = FAST_FORWARD and fresh > 0 and fresh_saved == fresh and not batch

            self.feed.tidy(collect_garbage=self.scrolls % 10 == 0)
            memory = self.feed.memory_mb()
            status["session_new"] = status.get("session_new", 0) + len(batch)
            status.update(scroll=self.scrolls, run_new=self.new, run_comments=self.comments,
                          run_skipped=self.skipped, run_updated=self.updated, memory_mb=memory)
            status["per_scroll"].append(len(batch))
            write_status(status)
            log_message(f"Scroll {self.scrolls}{' (fast)' if fast else ''}: +{len(batch)} posts, "
                        f"+{len(comment_rows)} comments, {skipped} already saved"
                        + (f", {updated} of them updated" if UPDATE_SAVED else "")
                        + f" (batch {got}/{want}, page memory {memory} MB)")

            if got >= want:
                return "more", f"Got {got} new posts", got

            self.idle = self.idle + 1 if not fresh else 0
            if self.idle >= MAX_IDLE_SCROLLS:
                return "done", "The feed stopped loading more posts", got

            if blocked(page):
                return "blocked", "Checkpoint appeared mid-run, stopped", got

            if auto:
                limit = estimate_scrolls(ahead, b_scrolls, b_seen, want)
                status["scroll_limit"] = self.scrolls - b_scrolls + limit

            # At most every 15 scrolls and 5 times per group, so a limit set
            # below what a fresh page needs can't make it reopen forever
            if (RECYCLE_MB and memory > RECYCLE_MB and self.scrolls - self.last_recycle >= 15
                    and self.recycles < 5):
                # A long feed holds on to memory; a fresh tab starts small. It
                # loads from the top again, so give the scroll budget back.
                self.recycles += 1
                self.last_recycle = self.scrolls
                log_message(f"Page memory {memory} MB > {RECYCLE_MB} MB: reopening the group (#{self.recycles})")
                self.close()
                problem = self.open()
                if problem:
                    return problem[0], problem[1], got
                self.since_open = set()
                limit = min(AUTO_SCROLL_CAP, limit + b_scrolls) if auto else limit + b_scrolls
                self.idle = 0
                continue

            if self.idle:
                # Nothing loaded last time: bring the last post into view so the
                # feed's loader triggers, and give it longer to fetch
                nudge_feed(page)
                human_pause(MIN_DELAY + 2, MAX_DELAY + 4)
            elif fast:
                page.mouse.wheel(0, random.randint(2800, 4000))
                time.sleep(random.uniform(1, 2))
            else:
                page.mouse.wheel(0, random.randint(1500, 2500))
                human_pause()

    def read_posts(self, page, still_needed):
        """Expand "Xem thêm" where it's needed, then read the posts on screen."""
        args = {"max": MAX_COMMENTS_PER_POST, "withReactions": COLLECT_REACTIONS}
        if not SKIP_SEE_MORE_SAVED:
            expand_see_more(page)
            return page.evaluate(EXTRACT_JS, args)
        # b. Only expand posts we'll actually save (or refresh). Clicking
        # scrolls a post into view, which can load more posts, so look again
        # for new ones a couple of times.
        posts = page.evaluate(EXTRACT_JS, args)
        tried, new_tried = set(), 0
        for _ in range(3):
            wanted = []
            for p in posts:
                key = post_key(p)
                if not (p["text"] or p["post_id"]) or key in tried or not self.needs_full_text(key):
                    continue
                if key not in self.seen:  # a post we'd save: only as many as this batch still needs
                    if new_tried >= still_needed:
                        continue
                    new_tried += 1
                wanted.append(p)
            if not wanted:
                break
            for p in wanted:
                tried.add(post_key(p))
                expand_see_more(page, f"[data-fbs-idx='{p['idx']}']")
            posts = page.evaluate(EXTRACT_JS, args)
        return posts

    def needs_full_text(self, key):
        if key not in self.seen:
            return True
        return UPDATE_SAVED and key in self.saved_before and key not in self.refreshed


def scrape_posts():
    groups = GROUPS if SCRAPE_ALL_GROUPS else [SELECTED_GROUP]
    if os.path.exists(STOP_FILE):
        os.remove(STOP_FILE)  # left over from an earlier Stop
    status = {
        "state": "starting", "message": "", "target": groups[0], "group": group_slug(groups[0]),
        "group_index": 1, "groups_total": len(groups),
        "started_at": datetime.now().isoformat(timespec="seconds"),
        "scroll": 0, "scroll_limit": SCROLL_LIMIT,
        "run_new": 0, "run_comments": 0, "max_posts": BATCH_POSTS if BATCH_MODE else MAX_POSTS,
        "per_scroll": [], "memory_mb": 0, "session_new": 0,
        "batch_mode": BATCH_MODE, "batch_index": 0, "batch_total": BATCH_TOTAL if BATCH_MODE else 0,
        "next_batch_at": "",
    }

    def finish(state, message):
        log_message(message)
        status.update(state=state, message=message, next_batch_at="")
        write_status(status)
        if state == "blocked":
            record_checkpoint(message)
        if os.path.exists(STOP_FILE):
            os.remove(STOP_FILE)

    write_status(status)
    try:
        _scrape(groups, status, finish)
    except Exception as e:
        finish("error", f"Crashed: {e}")
        raise


def _scrape(groups, status, finish):
    for line in describe_migration(migrate_legacy_data()):
        log_message(line)

    try:
        session = load_session()
    except VaultError as e:
        return finish("error", str(e))
    if session is None:
        return finish("error", "No saved login yet. Log in in the dashboard's Account tab.")

    if LOW_RISK_MODE:
        log_message(f"Low-risk mode: up to {BATCH_POSTS if BATCH_MODE else MAX_POSTS} posts, "
                    f"{MIN_DELAY:g}-{MAX_DELAY:g}s pauses, no comment or reaction popups")
    if BLOCK_MEDIA:
        log_message("Not loading images, videos and fonts (saves memory)")
    if BATCH_MODE:
        log_message(f"Batch mode: {BATCH_POSTS} new posts per batch, {BATCH_TOTAL} in total, "
                    f"{BATCH_REST_MIN:g} min rest between batches")

    with sync_playwright() as p:
        browser = launch_browser(p, HEADLESS)
        # Small fixed window: less to draw and keep in memory
        context = browser.new_context(storage_state=session, locale="vi-VN",
                                      viewport={"width": 1100, "height": 850}, device_scale_factor=1,
                                      reduced_motion="reduce", service_workers="block")
        runs = []
        try:
            state, message = (run_batches if BATCH_MODE else run_once)(context, groups, status, runs)
        finally:
            for run in runs:
                run.close()
            browser.close()
    finish(state, message)


def describe_runs(runs, groups, reason):
    if len(groups) == 1 and runs:
        return runs[0].summary(reason)
    parts = "; ".join(f"{r.files.slug}: {r.new} new posts" for r in runs)
    return f"{reason}. {len(runs)}/{len(groups)} groups: {parts}."


def run_once(context, groups, status, runs):
    """One pass over the groups, up to MAX_POSTS each, closing each tab when done."""
    results = []
    for n, url in enumerate(groups, 1):
        run = GroupRun(context, url, status)
        runs.append(run)
        status.update(target=url, group=run.files.slug, group_index=n, scroll=0, per_scroll=[])
        if len(groups) > 1:
            log_message(f"=== Group {n}/{len(groups)}: {run.files.slug} ===")
        state, reason, _ = run.run_batch(MAX_POSTS)
        run.close()
        state = "done" if state == "more" else state
        results.append((run.files.slug, state, run.summary(reason)))
        if state in ("blocked", "stopped"):
            break  # the account is being challenged, or you asked to stop
        if n < len(groups):
            pause = GROUP_PAUSE_MIN * 60 * random.uniform(0.8, 1.2)
            log_message(f"Pausing {pause / 60:.1f} min before the next group")
            if not wait(pause, status, f"Pausing before group {n + 1}/{len(groups)}"):
                results.append(("", "stopped", "Stopped from the dashboard"))
                break
    if len(results) == 1:
        return results[0][1], results[0][2]
    final = next((s for _, s, _ in results if s in ("blocked", "stopped")), "done")
    return final, f"{len(results)}/{len(groups)} groups. " + "; ".join(f"{g}: {m}" for g, m in
                                                                     ((g, m) for g, _, m in results) if g)


def run_batches(context, groups, status, runs):
    """c. Batches: every group gets BATCH_POSTS new posts per batch; between
    batches the tabs stay open, so the next batch continues where this one
    stopped instead of scrolling down from the top again."""
    active = [GroupRun(context, url, status) for url in groups]
    runs.extend(active)
    total = 0
    for batch_no in itertools.count(1):
        status["batch_index"] = batch_no
        log_message(f"=== Batch {batch_no} ({total}/{BATCH_TOTAL} new posts so far) ===")
        this_round = list(active)
        for n, run in enumerate(this_round, 1):
            want = min(BATCH_POSTS, BATCH_TOTAL - total)
            if want <= 0:
                break
            status.update(target=run.files.url, group=run.files.slug, group_index=groups.index(run.files.url) + 1,
                          per_scroll=[])
            if len(groups) > 1:
                log_message(f"--- {run.files.slug} ---")
            state, reason, got = run.run_batch(want)
            total += got
            if state in ("blocked", "stopped"):
                return state, describe_runs(runs, groups, reason)
            if state != "more":  # this group's feed is finished (or broke)
                log_message(f"{run.files.slug}: {run.summary(reason)}")
                run.ended = (state, reason)
                run.close()
                active.remove(run)
            if n < len(this_round) and total < BATCH_TOTAL:
                pause = GROUP_PAUSE_MIN * 60 * random.uniform(0.8, 1.2)
                if not wait(pause, status, "Pausing before the next group"):
                    return "stopped", describe_runs(runs, groups, "Stopped from the dashboard")
        if total >= BATCH_TOTAL:
            return "done", describe_runs(runs, groups, f"Reached {BATCH_TOTAL} new posts in total")
        if not active:
            return "done", describe_runs(runs, groups, "Every group's feed ran out")
        rest = BATCH_REST_MIN * 60 * random.uniform(0.9, 1.1)
        until = (datetime.now() + timedelta(seconds=rest)).strftime("%H:%M")
        message = f"Batch {batch_no} done ({total}/{BATCH_TOTAL} new posts). Resting until {until}, page kept open."
        log_message(message)
        if not wait(rest, status, message, state="resting"):
            return "stopped", describe_runs(runs, groups, "Stopped from the dashboard while resting")
