"""A local stand-in for a Facebook group feed, built from the same markers the
scraper looks for (role=feed, aria-posinset, story_message, comment labels...).
Posts appear 6 at a time as the page is scrolled, like the real feed."""
from pathlib import Path


def comment(post_id, n, reply=False):
    inner = ("<div role='article' aria-label='Phản hồi dưới tên SV r'><a role='link'><span>SV r</span></a>"
             "<div dir='auto'>REPLY-MUST-NOT-BE-SAVED</div></div>") if reply else ""
    return (f"<div role='article' aria-label='Bình luận dưới tên SV {n}'><a role='link'><span>SV {n}</span></a>"
            f"<div dir='auto'>Bình luận {n} của bài {post_id}</div><span>5 bình luận</span>{inner}</div>")


def post(i, base_id, group):
    pid = base_id + i
    likes = 10 + i
    return (
        f"<div><div aria-posinset='{i}' role='article' style='height:520px'>"
        f"<h3><a><strong>Tác giả {i % 3}</strong></a></h3>"
        f"<a href='https://www.facebook.com/groups/{group}/posts/{pid}/'>{i + 1} giờ</a>"
        f"<div data-ad-rendering-role='story_message'><div dir='auto'><span id='t{pid}'>Bài {pid} đoạn đầu…</span> "
        f"<div role='button' onclick=\"document.getElementById('t{pid}').textContent='Bài {pid} đầy đủ';"
        f"this.outerHTML='<div role=button>Ẩn bớt</div>'\">Xem thêm</div></div></div>"
        f"<div role='button'><span aria-label='Thích: {likes} người'></span><span>{likes}</span></div>"
        f"<div><span>{12 + i} bình luận</span><span>{i} lượt chia sẻ</span></div>"
        f"<div role='button'>Thích</div><div role='button'>Bình luận</div><div role='button'>Chia sẻ</div>"
        f"<div>{comment(pid, 1, reply=True)}{comment(pid, 2)}"
        f"<div role='button' onclick='moreComments(this, {pid})'>Xem thêm bình luận</div></div>"
        f"</div></div>"
    )


def write_feed(folder, name, count=30, base_id=5000, group="testgroup"):
    """Write <folder>/<name>.html and return its file:// URL."""
    posts = "".join(post(i, base_id, group) for i in range(count))
    html = f"""<!doctype html><html><head><meta charset="utf-8"></head><body>
<div role='feed' id='f'></div><template id='all'>{posts}</template>
<template id='more'>{"".join(comment("PID", n) for n in (3, 4, 5))}</template>
<script>
function moreComments(button, pid) {{
  button.insertAdjacentHTML('beforebegin', document.getElementById('more').innerHTML.replaceAll('PID', pid));
  button.remove();
}}
const all = [...document.getElementById('all').content.children]; let n = 0;
function more() {{ for (let k = 0; k < 6 && n < all.length; k++, n++) document.getElementById('f').appendChild(all[n].cloneNode(true)); }}
more();
window.addEventListener('scroll', () => {{ if (innerHeight + scrollY > document.body.scrollHeight - 800) more(); }});
</script></body></html>"""
    path = Path(folder) / f"{name}.html"
    path.write_text(html, encoding="utf-8")
    return path.resolve().as_uri()
