"""Engagement per post: reaction counts by type (Like, Love, Care, Haha, Wow,
Sad, Angry), plus the post's real comment and share counts.

Comment and share counts come from the line under the post ("48 bình luận",
"5 lượt chia sẻ"), so they need no clicks.

Two sources:
- The reaction bar under a post. No clicks needed, but Facebook only shows
  icons for the top 3 types, plus the total.
- The reactions popup ("who reacted"), opened by clicking that bar. It has a
  tab per type with its count, so every type is covered. Costs one click.
"""
import re

TYPES = ["like", "love", "care", "haha", "wow", "sad", "angry"]

# Browser-side helpers, added into the scraper's page scripts
REACTIONS_JS = r"""
const REACTION_NAMES = [
  ["love", ["love", "yêu thích"]], ["like", ["like", "thích"]], ["care", ["care", "thương thương"]],
  ["haha", ["haha"]], ["wow", ["wow"]], ["sad", ["sad", "buồn"]], ["angry", ["angry", "phẫn nộ"]],
];
function reactionType(s) {
  s = (s || "").toLowerCase().trim();
  for (const [key, names] of REACTION_NAMES) if (names.some(n => s.startsWith(n))) return key;
  return null;
}
const COUNT_RE = /\d[\d.,]*(?:\s*(?:K|N|M|Tr)(?![\p{L}]))?/iu;
const NOT_REACTIONS = /(bình luận|comment|chia sẻ|share|lượt xem|view)/i;
const TOTAL_RE = /^\d[\d.,]*(?:\s*(?:K|N|M|Tr))?$/iu;

// Inside a post: "Thích: 120 người" style icon labels (top types) + the total line
function reactionsIn(p, idx, notInComment) {
  const found = {};
  let anchor = null;
  for (const el of p.querySelectorAll("[aria-label], img[alt]")) {
    if (!notInComment(el)) continue;
    const label = el.getAttribute("aria-label") || el.getAttribute("alt") || "";
    const m = label.match(/^([^:]+):\s*(.+)$/);
    const type = m && reactionType(m[1]);
    if (!type) continue;
    found[type] = m[2];
    anchor = anchor || el;
  }

  let totalText = "", button = null;
  if (anchor) {
    // The total is a bare count ("128", "1,2K") or "Bạn và 45 người khác".
    // Anything else with a number (e.g. the "5 giờ" time label) isn't it.
    const isTotal = t => (TOTAL_RE.test(t) || /(người khác|others?)$/i.test(t)) && !NOT_REACTIONS.test(t);
    let node = anchor;
    for (let k = 0; k < 5 && node && node !== p; k++) {
      node = node.parentElement;
      const line = (node.innerText || "").split("\n").map(t => t.trim()).find(isTotal);
      if (line) { totalText = line; break; }
    }
    button = anchor.closest("[role='button']") || (node && node.querySelector("[role='button']"));
  }
  if (button) button.setAttribute("data-fbs-react", idx);
  return { found, totalText, hasButton: !!button };
}

// The "48 bình luận · 5 lượt chia sẻ" line under a post. When the post's
// action buttons are there but a count isn't, Facebook is showing 0.
const COMMENTS_RE = /^(\d[\d.,]*(?:\s*(?:K|N|M|Tr))?)\s*(bình luận|comments?)$/iu;
const SHARES_RE = /^(\d[\d.,]*(?:\s*(?:K|N|M|Tr))?)\s*(lượt chia sẻ|chia sẻ|shares?)$/iu;
const ACTION_RE = /^(bình luận|comment|chia sẻ|share|thích|like)$/i;
function footerCounts(p, notInComment) {
  let comments = "", shares = "", footer = false;
  for (const el of p.querySelectorAll("span, [role='button'], a")) {
    if (!notInComment(el)) continue;
    const t = (el.innerText || "").trim();
    if (!t || t.length > 40) continue;
    let m;
    if (!comments && (m = t.match(COMMENTS_RE))) comments = m[1];
    else if (!shares && (m = t.match(SHARES_RE))) shares = m[1];
    else if (ACTION_RE.test(t)) footer = true;
  }
  return { comments, shares, footer };
}

// Inside the reactions popup: one tab per type ("Tất cả 120", "Thích 100", ...)
function reactionTabs(root) {
  const found = {};
  let totalText = "";
  for (const tab of root.querySelectorAll("[role='tab']")) {
    const parts = [tab.getAttribute("aria-label") || "", tab.innerText || "",
      ...Array.from(tab.querySelectorAll("[aria-label], img[alt]"))
        .map(e => e.getAttribute("aria-label") || e.getAttribute("alt") || "")];
    const all = parts.join(" ").replace(/\s+/g, " ").trim();
    const num = ((tab.innerText || "").match(COUNT_RE) || all.match(COUNT_RE) || [""])[0];
    if (/^(all|tất cả)/i.test(all)) { totalText = num; continue; }
    let type = null;
    for (const s of parts) if ((type = reactionType(s))) break;
    if (type && num) found[type] = num;
  }
  return { found, totalText };
}
"""

DIALOG_JS = "(root) => {" + REACTIONS_JS + "return reactionTabs(root); }"

_COUNT = re.compile(r"(\d[\d.,]*)\s*(k|n|m|tr|nghìn|triệu)?(?!\w)", re.I)
_MULT = {"k": 1_000, "n": 1_000, "nghìn": 1_000, "m": 1_000_000, "tr": 1_000_000, "triệu": 1_000_000}


def parse_count(text):
    """'1,2K' / '1.2K' / '2,5 N' / '1 Tr' / '1.234' / '45 người' -> int (None if no number)."""
    m = _COUNT.search(text or "")
    if not m:
        return None
    num, suffix = m.groups()
    if suffix:
        # With a K/N/M suffix the separator is a decimal point in both locales
        return round(float(num.replace(",", ".").rstrip(".")) * _MULT[suffix.lower()])
    return int(re.sub(r"[.,]", "", num))


def parse_total(text):
    """Reaction bar total: '128', '1,2K', 'Bạn và 45 người khác', 'An và Bình'."""
    text = (text or "").strip()
    if not text:
        return None
    others = re.search(r"(\d[\d.,]*\s*(?:k|n|m|tr)?)(?!\w)\s*(người khác|others?)", text, re.I)
    if others:
        # 'Bạn, An và 45 người khác' = 2 names + 45
        names = re.split(r",|\svà\s|\sand\s", text[:others.start()])
        return parse_count(others.group(1)) + len([n for n in names if n.strip()])
    count = parse_count(text)
    if count is not None:
        return count
    # Only names, e.g. 'An và Bình'
    return len([n for n in re.split(r",|\svà\s|\sand\s", text) if n.strip()])


COUNT_FIELDS = ["comment_count", "share_count"]


def footer_values(counts):
    """{"comments": "48", "shares": "", "footer": True} -> {"comment_count": 48, "share_count": 0}.

    Empty means unknown: the line under the post wasn't found.
    """
    counts = counts or {}
    out = {}
    for field, key in (("comment_count", "comments"), ("share_count", "shares")):
        value = parse_count(counts.get(key))
        out[field] = value if value is not None else (0 if counts.get("footer") else "")
    return out


def build_row(post_id, inline, popup, now, footer=None):
    """One reactions.csv row from the inline bar, the (optional) popup and the
    comment/share line. inline is None when reactions aren't being scraped."""
    if inline is None:
        return {"post_id": post_id, "total": "", **{t: "" for t in TYPES}, **footer_values(footer),
                "source": "off", "scraped_at": now, "updated_at": ""}
    source = "popup" if popup and popup["found"] else "bar" if inline["found"] or inline["totalText"] else "none"
    found = (popup or inline)["found"] if source == "popup" else inline["found"]
    counts = {t: parse_count(found.get(t)) or 0 for t in TYPES}

    total = None
    if source == "popup":
        total = parse_count(popup["totalText"])
    if total is None:
        total = parse_total(inline["totalText"])
    if total is None or total < sum(counts.values()):
        total = sum(counts.values())

    return {"post_id": post_id, "total": total, **counts, **footer_values(footer),
            "source": source, "scraped_at": now, "updated_at": ""}


def merge_row(old, new, now):
    """Refresh a saved post's row with a new reading, without losing detail.

    - A popup reading has every type, so it replaces the counts.
    - A bar reading only has the top 3 types: those and the total are
      updated; other types keep their earlier counts.
    - No reading (e.g. the bar didn't render) keeps the old row.
    Returns (row, changed).
    """
    if old is None:
        return {**new, "updated_at": now}, new["source"] != "none" or any(new[f] != "" for f in COUNT_FIELDS)

    row = dict(old)
    # Comment/share counts: take any new reading (they can go down, too)
    for f in COUNT_FIELDS:
        if new.get(f, "") != "":
            row[f] = new[f]
    if new["source"] in ("none", "off"):
        changed = any(str(row.get(f, "")) != str(old.get(f, "")) for f in COUNT_FIELDS)
        if changed:
            row["updated_at"] = now
        return row, changed

    if new["source"] == "popup":
        row.update({t: new[t] for t in TYPES}, source="popup")
    else:
        row.update({t: new[t] for t in TYPES if new[t]})
        row["source"] = old.get("source") if old.get("source") in ("popup", "bar") else "bar"
    # Recount, since earlier readings may have kept types the new one didn't show
    known = sum(int(row.get(t) or 0) for t in TYPES)
    row["total"] = max(int(new["total"] or 0), known)

    changed = any(str(row.get(k, "")) != str(old.get(k, "")) for k in ("total", *TYPES, *COUNT_FIELDS))
    row["updated_at"] = now
    return row, changed
