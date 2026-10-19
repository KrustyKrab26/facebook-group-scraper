"""Reads the CSVs and computes what the dashboard's Posts and Analytics tabs show."""
import csv
import os
import re
from collections import Counter, defaultdict
from datetime import datetime, timedelta

from config import GroupFiles
from reactions import TYPES as REACTION_TYPES

# Common Vietnamese/English filler syllables, skipped when counting phrases
STOPWORDS = set("""
và của có cho mình là các những được không thì này đó với ở một em anh chị ạ ơi nha nhé
ai gì mọi người cái để trong đã sẽ khi cũng như bạn ko k hay hoặc nào thế vậy rồi nữa
lại ra vào từ về theo nên mà nếu đang bị còn đi làm tại do rất lắm thôi luôn đây kia
ad admin mn mng mọi ib inbox cmt the a an of to and or is are in on for you i it this
""".split())


def read_csv(path):
    if not os.path.isfile(path):
        return []
    with open(path, newline="", encoding="utf-8-sig") as f:
        return list(csv.DictReader(f))


def _int_or_none(value):
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def real_comments(p):
    """Facebook's comment count if known, else how many we saved."""
    return p["comment_count"] if p["comment_count"] is not None else len(p["comments"])


def load(files):
    """Posts joined with their comments and reaction counts, newest scrape first."""
    posts = read_csv(files.posts)
    comments = defaultdict(list)
    for c in read_csv(files.comments):
        comments[c.get("post_id")].append(c)
    reactions = {r.get("post_id"): r for r in read_csv(files.reactions)}

    joined = []
    for p in posts:
        pid = p.get("post_id")
        r = reactions.get(pid)
        counts = {t: int((r or {}).get(t) or 0) for t in REACTION_TYPES}
        posted_at, has_time = parse_post_time(p.get("time_text", ""), p.get("scraped_at", ""))
        joined.append({
            **p,
            "comments": sorted(comments.get(pid, []), key=lambda c: int(c.get("comment_index") or 0)),
            "reactions": counts,
            "reaction_total": int((r or {}).get("total") or 0),
            "reaction_source": (r or {}).get("source", ""),
            # Facebook's real totals; None = not read (older data, or the line wasn't there)
            "comment_count": _int_or_none((r or {}).get("comment_count")),
            "share_count": _int_or_none((r or {}).get("share_count")),
            "reaction_updated_at": (r or {}).get("updated_at", ""),
            "posted_at": posted_at.isoformat(timespec="minutes") if posted_at else "",
            "posted_has_time": has_time,
        })
    joined.reverse()
    return joined


# --- Post time ---------------------------------------------------------------
# Facebook shows relative times ("2 giờ", "3d", "Hôm qua lúc 14:30") or dates
# ("12 tháng 10", "October 12 at 2:30 PM"). Turned into a datetime using the
# moment the post was scraped. Best effort: unknown formats give None.

_REL = [
    (re.compile(r"^(\d+)\s*(phút|p|m|min|mins|minutes?)\b", re.I), "minutes"),
    (re.compile(r"^(\d+)\s*(giờ|g|h|hr|hrs|hours?)\b", re.I), "hours"),
    (re.compile(r"^(\d+)\s*(ngày|d|days?)\b", re.I), "days"),
    (re.compile(r"^(\d+)\s*(tuần|w|weeks?)\b", re.I), "weeks"),
]
_MONTHS = {m: i for i, m in enumerate(
    ["january", "february", "march", "april", "may", "june", "july", "august",
     "september", "october", "november", "december"], 1)}
_CLOCK = re.compile(r"(?:lúc|at)\s*(\d{1,2}):(\d{2})\s*(am|pm|sa|ch)?", re.I)


def _clock(text):
    m = _CLOCK.search(text)
    if not m:
        return None
    hour, minute, ampm = int(m.group(1)), int(m.group(2)), (m.group(3) or "").lower()
    if ampm in ("pm", "ch") and hour < 12:
        hour += 12
    if ampm in ("am", "sa") and hour == 12:
        hour = 0
    return hour, minute


def parse_post_time(text, scraped_at):
    """Return (datetime or None, whether the time of day is known)."""
    try:
        base = datetime.fromisoformat(scraped_at)
    except (TypeError, ValueError):
        return None, False
    text = (text or "").strip()
    low = text.lower()
    if not text:
        return None, False
    if low.startswith(("vừa xong", "just now")):
        return base, True
    for pattern, unit in _REL:
        m = pattern.match(low)
        if m:
            when = base - timedelta(**{unit: int(m.group(1))})
            return when, unit in ("minutes", "hours")
    clock = _clock(low)
    if low.startswith(("hôm qua", "yesterday")):
        day = base - timedelta(days=1)
        if clock:
            return day.replace(hour=clock[0], minute=clock[1], second=0, microsecond=0), True
        return day, False

    year = base.year
    m = re.search(r"(\d{1,2})\s*tháng\s*(\d{1,2})(?:,?\s*(\d{4}))?", low)
    if m:
        day, month = int(m.group(1)), int(m.group(2))
        year = int(m.group(3)) if m.group(3) else year
    else:
        m = re.search(r"(" + "|".join(_MONTHS) + r")\s+(\d{1,2})(?:,?\s*(\d{4}))?", low)
        if m:
            month, day = _MONTHS[m.group(1)], int(m.group(2))
            year = int(m.group(3)) if m.group(3) else year
        else:
            m = re.search(r"(\d{1,2})/(\d{1,2})/(\d{4})", low)
            if not m:
                return None, False
            day, month, year = int(m.group(1)), int(m.group(2)), int(m.group(3))
    try:
        when = datetime(year, month, day, *(clock or (0, 0)))
    except ValueError:
        return None, False
    if when > base + timedelta(days=1):  # "12 tháng 12" seen in January means last year
        when = when.replace(year=when.year - 1)
    return when, bool(clock)


# --- Posts tab ---------------------------------------------------------------

SORTS = {
    "newest": lambda p: p.get("scraped_at", ""),
    "reactions": lambda p: p["reaction_total"],
    "comments": real_comments,
    "shares": lambda p: p["share_count"] or 0,
}


def list_posts(files, query="", sort="newest", offset=0, limit=20):
    posts = load(files)
    if query:
        q = query.lower()
        posts = [p for p in posts if q in p.get("text", "").lower()
                 or any(q in c.get("text", "").lower() for c in p["comments"])]
    if sort in SORTS and sort != "newest":
        posts.sort(key=SORTS[sort], reverse=True)
    return {"total": len(posts), "posts": posts[offset:offset + limit]}


# --- Analytics tab -----------------------------------------------------------

def top_phrases(posts, n=12):
    # Vietnamese words are mostly two syllables, so count syllable pairs
    counts = Counter()
    for post in posts:
        text = re.sub(r"https?://\S+", " ", post.get("text", "").lower())
        syllables = re.findall(r"[^\W\d_]+", text)
        pairs = {
            f"{a} {b}" for a, b in zip(syllables, syllables[1:])
            if a not in STOPWORDS and b not in STOPWORDS
        }
        counts.update(pairs)  # once per post, so one spammy post can't dominate
    return counts.most_common(n)


COMMENT_BUCKETS = [("0", 0, 0), ("1-5", 1, 5), ("6-20", 6, 20), ("21-50", 21, 50), ("51+", 51, None)]
REACTION_BUCKETS = [("0", 0, 0), ("1-5", 1, 5), ("6-20", 6, 20), ("21-50", 21, 50),
                    ("51-100", 51, 100), ("101-500", 101, 500), ("500+", 501, None)]


def group_summary(files):
    """Row counts for the group picker, without parsing everything."""
    reactions = read_csv(files.reactions)
    return {
        "slug": files.slug, "url": files.url,
        "posts": len(read_csv(files.posts)),
        "comments": len(read_csv(files.comments)),
        "reactions": sum(int(r.get("total") or 0) for r in reactions),
    }


def analytics(files):
    posts = load(files)
    n = len(posts)
    total_reactions = sum(p["reaction_total"] for p in posts)
    total_comments = sum(len(p["comments"]) for p in posts)

    by_type = {t: sum(p["reactions"][t] for p in posts) for t in REACTION_TYPES}

    buckets = []
    for label, lo, hi in REACTION_BUCKETS:
        buckets.append([label, sum(1 for p in posts
                                   if p["reaction_total"] >= lo and (hi is None or p["reaction_total"] <= hi))])

    counted = [p for p in posts if p["comment_count"] is not None]
    shared = [p for p in posts if p["share_count"] is not None]
    total_real_comments = sum(p["comment_count"] for p in counted)
    total_shares = sum(p["share_count"] for p in shared)
    comment_buckets = [[label, sum(1 for p in counted if p["comment_count"] >= lo
                                   and (hi is None or p["comment_count"] <= hi))]
                       for label, lo, hi in COMMENT_BUCKETS]

    per_day = Counter(p["posted_at"][:10] for p in posts if p["posted_at"])
    days = sorted(per_day)
    if days:
        start, end = datetime.fromisoformat(days[0]), datetime.fromisoformat(days[-1])
        start = max(start, end - timedelta(days=59))  # last 60 days at most
        series = []
        d = start
        while d <= end:
            key = d.date().isoformat()
            series.append([key, per_day.get(key, 0)])
            d += timedelta(days=1)
    else:
        series = []

    # Weekday x hour, only for posts whose time of day is known
    heat = [[0] * 24 for _ in range(7)]
    timed = 0
    for p in posts:
        if p["posted_at"] and p["posted_has_time"]:
            when = datetime.fromisoformat(p["posted_at"])
            heat[when.weekday()][when.hour] += 1
            timed += 1

    top = sorted(posts, key=lambda p: p["reaction_total"], reverse=True)[:10]
    return {
        "posts": n,
        "comments": total_comments,
        "reactions": total_reactions,
        "avg_reactions": round(total_reactions / n, 1) if n else 0,
        "with_comments_pct": round(100 * sum(1 for p in posts if real_comments(p)) / n) if n else 0,
        "real_comments": total_real_comments,
        "avg_comments": round(total_real_comments / len(counted), 1) if counted else 0,
        "shares": total_shares,
        "counted_posts": len(counted),
        "dated_posts": sum(1 for p in posts if p["posted_at"]),
        "reactions_by_type": by_type,
        "reaction_sources": dict(Counter(p["reaction_source"] or "none" for p in posts)),
        "reaction_buckets": buckets,
        "comment_distribution": comment_buckets,
        "posts_per_day": series,
        "heatmap": heat,
        "heatmap_posts": timed,
        "top_posts": [{"text": p.get("text", "")[:140], "time_text": p.get("time_text", ""),
                       "total": p["reaction_total"], "reactions": p["reactions"],
                       "comments": real_comments(p), "shares": p["share_count"] or 0}
                      for p in top if p["reaction_total"]],
        "top_phrases": top_phrases(posts),
        "unique_authors": len({p.get("author") for p in posts if p.get("author")}),
    }
