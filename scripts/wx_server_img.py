#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
wx_server_img.py — 工程人的智库 微信公众号发布中转站（带图增强版）

在 wx_server.py 基础上新增：
  - POST /api/publish_ext_img : 多图发布接口
        接收 multipart/form-data:
          account   : default / helper / everyday
          title     : 文章标题
          digest    : 摘要（可选）
          content   : Markdown 正文，图片处用占位符 @@IMG{n}@@ （n 从 0 开始，按图片顺序）
          images    : 一个或多个图片文件（顺序与 @@IMG{n}@@ 对应）
        服务端在白名单 IP 上把图片上传到微信素材库拿到 URL，
        替换占位符后用 md2html 渲染，最后 draft/add 写入对应账号草稿箱。
  - POST /api/delete_draft : 清理草稿
          { "account": "default", "media_id": "..." }

部署：把本文件覆盖到 VPS 上的 wx_server.py 并重启服务即可。
其余接口（/、/api/upload、/api/publish、/api/publish_ext、/api/publish_all、/api/batch_upload）保持原样。
"""
import json, time, os, sys, io, re, traceback, uuid
from http.server import HTTPServer, BaseHTTPRequestHandler
from urllib.parse import parse_qs, unquote
import urllib.request, ssl, socket

# ==================== 配置 ====================
SERVER_HOST = "0.0.0.0"
SERVER_PORT = 8899
ADMIN_PASSWORD = "gcren2026"
ARTICLE_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "articles")
DATA_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "publish_log.json")

ctx = ssl.create_default_context()

# ==================== 多账号配置 ====================
ACCOUNTS = {
    "default": {
        "appid": "wxad5dd45a26c1ae29",
        "secret": "d8013d810cafdf0163e2892638b76140",
        "name": "工程人的智库",
    },
    "helper": {
        "appid": "wx3a759e8e27b5be1f",
        "secret": "d8013d810cafdf0163e2892638b76140",
        "name": "工程人的助手",
    },
    "everyday": {
        "appid": "wxa778fff8a7410da0",
        "secret": "65leCYalEBEoafZJ6KvfrEJQW9VZrIVgQspXTD9qcwA",
        "name": "工程人的每一天",
    },
}

_token_cache = {}
os.makedirs(ARTICLE_DIR, exist_ok=True)


# ==================== 微信API ====================
def get_token(key="default"):
    global _token_cache
    now = time.time()
    if key in _token_cache:
        tok, exp = _token_cache[key]
        if now < exp - 300:
            return tok
    cfg = ACCOUNTS[key]
    url = (f"https://api.weixin.qq.com/cgi-bin/token"
           f"?grant_type=client_credential&appid={cfg['appid']}&secret={cfg['secret']}")
    with urllib.request.urlopen(url, context=ctx, timeout=15) as r:
        d = json.loads(r.read().decode())
    if "access_token" not in d:
        raise Exception("Token获取失败: " + json.dumps(d, ensure_ascii=False))
    _token_cache[key] = (d["access_token"], now + d.get("expires_in", 7200))
    return d["access_token"]


def make_cover(title):
    from PIL import Image, ImageDraw, ImageFont
    w, h = 900, 500
    img = Image.new("RGB", (w, h), "#2B6CB0")
    font = small = None
    font_paths = []
    if sys.platform == "win32":
        windir = os.environ.get("WINDIR", "C:\\Windows")
        font_paths = [
            os.path.join(windir, "Fonts", "msyh.ttc"),
            os.path.join(windir, "Fonts", "msyhbd.ttc"),
            os.path.join(windir, "Fonts", "simhei.ttf"),
            os.path.join(windir, "Fonts", "simsun.ttc"),
        ]
    else:
        font_paths = [
            "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
            "/usr/share/fonts/truetype/wqy/wqy-zenhei.ttc",
            "/usr/share/fonts/wqy-zenhei/wqy-zenhei.ttc",
        ]
    for fp in font_paths:
        try:
            font = ImageFont.truetype(fp, 44)
            small = ImageFont.truetype(fp, 22)
            break
        except:
            continue
    if not font:
        font = small = ImageFont.load_default()
    draw = ImageDraw.Draw(img)
    overlay = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    od = ImageDraw.Draw(overlay)
    od.rectangle([(0, 0), (w, 10)], fill=(72, 187, 120, 255))
    od.rectangle([(0, h - 10), (w, h)], fill=(72, 187, 120, 255))
    img = Image.alpha_composite(img.convert("RGBA"), overlay).convert("RGB")
    draw = ImageDraw.Draw(img)
    text = title[:20]
    line2 = ""
    if len(text) > 12:
        mid = len(text) // 2
        line1 = text[:mid]
        line2 = text[mid:]
    else:
        line1 = text
    if line2:
        b1 = draw.textbbox((0, 0), line1, font=font)
        b2 = draw.textbbox((0, 0), line2, font=font)
        tw1, th1 = b1[2] - b1[0], b1[3] - b1[1]
        tw2, th2 = b2[2] - b2[0], b2[3] - b2[1]
        yy = (h - th1 - th2 - 10) // 2
        draw.text(((w - tw1) // 2, yy), line1, fill="white", font=font)
        draw.text(((w - tw2) // 2, yy + th1 + 10), line2, fill="white", font=font)
    else:
        bb = draw.textbbox((0, 0), line1, font=font)
        tw, th = bb[2] - bb[0], bb[3] - bb[1]
        draw.text(((w - tw) // 2, (h - th) // 2 - 20), line1, fill="white", font=font)
    buf = io.BytesIO()
    img.save(buf, format="JPEG", quality=92)
    buf.seek(0)
    return buf.getvalue()


def upload_thumb(token, img_data):
    boundary = "----WxB" + str(int(time.time() * 1000))
    body = ("--" + boundary + "\r\n" +
            'Content-Disposition: form-data; name="media"; filename="cover.jpg"\r\n' +
            "Content-Type: image/jpeg\r\n\r\n").encode() + img_data + ("\r\n--" + boundary + "--\r\n").encode()
    url = "https://api.weixin.qq.com/cgi-bin/media/upload?access_token=" + token + "&type=thumb"
    req = urllib.request.Request(url, data=body, headers={"Content-Type": "multipart/form-data; boundary=" + boundary})
    with urllib.request.urlopen(req, context=ctx, timeout=60) as r:
        d = json.loads(r.read().decode())
    if "thumb_media_id" in d:
        return d["thumb_media_id"]
    raise Exception("封面上传失败: " + json.dumps(d, ensure_ascii=False))


def upload_image_material(token, img_data, filename="img.jpg"):
    """上传图片素材（正文用），返回 (url, media_id)"""
    boundary = "----WxB" + str(int(time.time() * 1000))
    body = ("--" + boundary + "\r\n" +
            'Content-Disposition: form-data; name="media"; filename="' + filename + '"\r\n' +
            "Content-Type: image/jpeg\r\n\r\n").encode() + img_data + ("\r\n--" + boundary + "--\r\n").encode()
    url = "https://api.weixin.qq.com/cgi-bin/material/add_material?access_token=" + token + "&type=image"
    req = urllib.request.Request(url, data=body, headers={"Content-Type": "multipart/form-data; boundary=" + boundary})
    with urllib.request.urlopen(req, context=ctx, timeout=60) as r:
        d = json.loads(r.read().decode())
    if "url" in d:
        return d["url"], d.get("media_id")
    raise Exception("图片素材上传失败: " + json.dumps(d, ensure_ascii=False))


def md2html(md):
    lines = md.split("\n")
    parts = []
    in_code = False
    code_buf = []
    in_table = False
    tbody = []
    fm = 0
    for line in lines:
        # 透传已替换为 <img ...> 的图片行
        if line.strip().startswith("<img"):
            parts.append(line.strip())
            continue
        if fm < 2 and line.strip() == "---":
            fm += 1
            continue
        if fm == 1:
            continue
        if line.startswith("title:") or line.startswith("cover:"):
            continue
        if line.startswith("# ") and not line.startswith("## "):
            continue
        if line.strip().startswith("```"):
            if in_code:
                in_code = False
                parts.append('<pre style="background:#f6f8fa;padding:16px;border-radius:8px;overflow-x:auto;font-size:14px;line-height:1.6;border:1px solid #e2e8f0;"><code>' + "".join(code_buf) + '</code></pre>')
                code_buf = []
            else:
                in_code = True
            continue
        if in_code:
            code_buf.append(line.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;"))
            continue
        if "|" in line and line.strip().startswith("|"):
            if "---" in line:
                continue
            cells = [c.strip() for c in line.strip().split("|")[1:-1]]
            tag = "th" if not in_table else "td"
            st = "border:1px solid #e2e8f0;padding:8px 12px;font-size:14px;"
            if tag == "th":
                st += "background:#f7fafc;font-weight:bold;text-align:center;color:#2D3748;"
            else:
                st += "color:#4A5568;"
            tbody.append("<tr>" + "".join('<' + tag + ' style="' + st + '">' + c + '</' + tag + '>' for c in cells) + "</tr>")
            in_table = True
            continue
        if in_table:
            parts.append('<table style="border-collapse:collapse;width:100%;margin:20px 0;">' + "".join(tbody) + '</table>')
            in_table = False
            tbody = []
        if not line.strip():
            continue
        t = line.strip()
        t = re.sub(r"\*\*(.*?)\*\*", r'<strong style="color:#1A202C;">\1</strong>', t)
        t = re.sub(r"`(.*?)`", r'<code style="background:#EDF2F7;padding:2px 6px;border-radius:3px;font-size:13px;color:#E53E3E;">\1</code>', t)
        if t.startswith("## "):
            parts.append('<h2 style="font-size:20px;font-weight:bold;color:#1A202C;margin:32px 0 16px;padding-bottom:8px;border-bottom:2px solid #48BB78;">' + t[3:] + '</h2>')
        elif t.startswith("### "):
            parts.append('<h3 style="font-size:17px;font-weight:bold;color:#2D3748;margin:24px 0 12px;padding-left:12px;border-left:3px solid #48BB78;">' + t[4:] + '</h3>')
        elif t.startswith(">"):
            qt = t.lstrip(">").strip()
            qt = re.sub(r"\*\*(.*?)\*\*", r"<strong>\1</strong>", qt)
            parts.append('<blockquote style="margin:16px 0;padding:12px 16px;background:#F0FFF4;border-left:4px solid #48BB78;color:#2D3748;font-size:15px;line-height:1.8;border-radius:0 8px 8px 0;">' + qt + '</blockquote>')
        elif re.match(r"^[-*]\s", t):
            c = re.sub(r"^[-*]\s", "", t)
            parts.append('<p style="margin:4px 0;padding-left:20px;font-size:15px;line-height:1.8;color:#4A5568;"><span style="color:#48BB78;margin-right:8px;">●</span>' + c + '</p>')
        elif re.match(r"^\d+\.\s", t):
            c = re.sub(r"^\d+\.\s", "", t)
            parts.append('<p style="margin:4px 0;padding-left:20px;font-size:15px;line-height:1.8;color:#4A5568;">' + c + '</p>')
        elif t.strip() == "---":
            parts.append('<hr style="border:none;height:1px;background:linear-gradient(to right,transparent,#48BB78,transparent);margin:28px 0;">')
        else:
            t2 = re.sub(r"\*(.*?)\*", r"<em>\1</em>", t)
            parts.append('<p style="margin:8px 0;font-size:15px;line-height:2;color:#4A5568;text-align:justify;">' + t2 + '</p>')
    if in_table:
        parts.append('<table style="border-collapse:collapse;width:100%;margin:20px 0;">' + "".join(tbody) + '</table>')
    return '<div style="font-family:-apple-system,BlinkMacSystemFont,\'Helvetica Neue\',\'PingFang SC\',\'Hiragino Sans GB\',\'Microsoft YaHei\',sans-serif;padding:20px 16px;color:#4A5568;">' + "\n".join(parts) + "</div>"


def add_draft_ext(token, title, author, digest, content, thumb_id):
    payload = {
        "articles": [{
            "title": title,
            "author": author,
            "digest": digest,
            "content": content,
            "content_source_url": "",
            "thumb_media_id": thumb_id,
            "need_open_comment": 1,
            "only_fans_can_comment": 0
        }]
    }
    body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    url = "https://api.weixin.qq.com/cgi-bin/draft/add?access_token=" + token
    req = urllib.request.Request(url, data=body, headers={"Content-Type": "application/json; charset=utf-8"})
    with urllib.request.urlopen(req, context=ctx, timeout=30) as r:
        d = json.loads(r.read().decode())
    if "media_id" in d:
        return d["media_id"]
    raise Exception("发布草稿失败: " + json.dumps(d, ensure_ascii=False))


# ==================== 多图发布核心 ====================
def publish_ext_img(account_key, title, digest, content, images):
    """images: list of (filename, bytes)。按列表顺序对应占位符 @@IMG{n}@@。"""
    if account_key not in ACCOUNTS:
        raise Exception("未知账号: " + account_key)
    token = get_token(account_key)
    urls = []
    for i, (fn, data) in enumerate(images):
        url, _ = upload_image_material(token, data, filename=fn)
        urls.append(url)
        content = content.replace("@@IMG%d@@" % i,
                                  '<img src="%s" style="max-width:100%%;border-radius:8px;box-shadow:0 2px 10px rgba(0,0,0,0.12);">' % url)
    html = md2html(content)
    # 封面：优先用第一张图；失败则用自动生成的纯色封面
    thumb_id = None
    try:
        if images:
            thumb_id = upload_thumb(token, images[0][1])
    except Exception:
        thumb_id = None
    if not thumb_id:
        thumb_id = upload_thumb(token, make_cover(title))
    author = ACCOUNTS[account_key]["name"]
    media_id = add_draft_ext(token, title, author, digest or title[:50], html, thumb_id)
    return {"title": title, "media_id": media_id, "account": author, "images": len(images)}


def delete_draft(account_key, media_id):
    token = get_token(account_key)
    body = json.dumps({"media_id": media_id}, ensure_ascii=False).encode("utf-8")
    url = "https://api.weixin.qq.com/cgi-bin/draft/delete?access_token=" + token
    req = urllib.request.Request(url, data=body, headers={"Content-Type": "application/json; charset=utf-8"})
    with urllib.request.urlopen(req, context=ctx, timeout=30) as r:
        d = json.loads(r.read().decode())
    return d.get("errcode", -1) == 0


# ==================== HTTP Handler ====================
class RequestHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        if self.path == "/" or self.path == "/index.html":
            self._html(page_index())
        elif self.path == "/api/status":
            self._json({"status": "ok", "time": time.strftime("%Y-%m-%d %H:%M:%S"), "img_support": True})
        elif self.path.startswith("/api/article/"):
            fid = unquote(self.path[13:])
            fp = os.path.join(ARTICLE_DIR, fid)
            if os.path.exists(fp):
                with open(fp, "r", encoding="utf-8") as f:
                    self._json({"title": fid.replace(".md", ""), "content": f.read()})
            else:
                self._json({"error": "not found"})
        elif self.path == "/api/articles":
            self._json({"articles": list_articles(), "log": load_publish_log()})
        else:
            self._html("404 Not Found", 404)

    def _parse_multipart(self, body, ctype):
        """解析 multipart/form-data，返回 (fields:dict, files:list of (name,filename,bytes))"""
        boundary = "--" + ctype.split("boundary=")[-1].strip()
        parts = body.split(boundary.encode())
        fields = {}
        files = []
        for part in parts:
            if b"\r\n\r\n" not in part:
                continue
            head, _, payload = part.partition(b"\r\n\r\n")
            head = head.decode("utf-8", "ignore")
            if "filename=" in head:
                fn_match = re.search(r'filename="([^"]+)"', head)
                name_match = re.search(r'name="([^"]+)"', head)
                fname = fn_match.group(1) if fn_match else "file.bin"
                pname = name_match.group(1) if name_match else "file"
                data = payload.rstrip(b"\r\n")
                files.append((pname, fname, data))
            else:
                name_match = re.search(r'name="([^"]+)"', head)
                if name_match:
                    pname = name_match.group(1)
                    val = payload.rstrip(b"\r\n").decode("utf-8", "ignore")
                    fields[pname] = val
        return fields, files

    def do_POST(self):
        length = int(self.headers.get("Content-Length", 0))
        body = self.rfile.read(length) if length else b""
        ctype = self.headers.get("Content-Type", "")

        if self.path == "/api/upload":
            try:
                d = self._parse_body(body)
                title = d.get("title", "untitled")
                content = d.get("content", "")
                fn = str(int(time.time())) + "_" + title[:30].replace("/", "-").replace("\\", "-").replace(" ", "_") + ".md"
                fp = os.path.join(ARTICLE_DIR, fn)
                with open(fp, "w", encoding="utf-8") as f:
                    f.write("---\ntitle: " + title + "\n---\n\n" + content)
                self._json({"ok": True, "file": fn})
            except Exception as e:
                self._json({"ok": False, "error": str(e)})

        elif self.path == "/api/publish":
            try:
                d = self._parse_body(body)
                result = publish_article(d["file"])
                self._json({"ok": True, "media_id": result["media_id"], "title": result["title"]})
            except Exception as e:
                self._json({"ok": False, "error": str(e)})

        elif self.path == "/api/publish_ext":
            try:
                d = self._parse_body(body)
                account_key = d.get("account", "default")
                title = d.get("title", "")
                content = d.get("content", "")
                result = publish_article_ext(account_key, title, content)
                self._json({"ok": True, "media_id": result["media_id"], "title": result["title"], "account": result["account"]})
            except Exception as e:
                self._json({"ok": False, "error": str(e)})

        elif self.path == "/api/publish_ext_img":
            # 多图发布：multipart/form-data
            try:
                if "multipart/form-data" not in ctype:
                    raise Exception("需要 multipart/form-data")
                fields, files = self._parse_multipart(body, ctype)
                account_key = fields.get("account", "default")
                title = fields.get("title", "")
                digest = fields.get("digest", "")
                content = fields.get("content", "")
                images = [(fn, data) for (pname, fn, data) in files if pname == "images"]
                result = publish_ext_img(account_key, title, digest, content, images)
                self._json({"ok": True, "media_id": result["media_id"], "title": result["title"],
                            "account": result["account"], "images": result["images"]})
            except Exception as e:
                self._json({"ok": False, "error": str(e)})

        elif self.path == "/api/delete_draft":
            try:
                d = self._parse_body(body)
                ok = delete_draft(d.get("account", "default"), d.get("media_id", ""))
                self._json({"ok": ok})
            except Exception as e:
                self._json({"ok": False, "error": str(e)})

        elif self.path == "/api/publish_all":
            try:
                articles = list_articles()
                log = load_publish_log()
                ok = fail = 0
                for a in articles:
                    if a["id"] not in log:
                        try:
                            publish_article(a["id"])
                            ok += 1
                            time.sleep(2)
                        except Exception:
                            fail += 1
                self._json({"ok": True, "success": ok, "fail": fail})
            except Exception as e:
                self._json({"ok": False, "error": str(e)})

        elif self.path == "/api/batch_upload":
            try:
                if "multipart/form-data" in ctype:
                    boundary = ctype.split("boundary=")[-1].strip()
                    parts = body.split(boundary.encode())
                    count = 0
                    for part in parts:
                        if b"filename=" in part and b".md" in part:
                            fn_match = re.search(rb'filename="([^"]+)"', part)
                            if fn_match:
                                fn = fn_match.group(1).decode("utf-8")
                                content_match = re.search(rb'\r\n\r\n(.+?)\r\n--', part, re.DOTALL)
                                if content_match:
                                    content = content_match.group(1).decode("utf-8")
                                    fp = os.path.join(ARTICLE_DIR, fn)
                                    with open(fp, "w", encoding="utf-8") as f:
                                        f.write(content)
                                    count += 1
                    self._json({"ok": True, "count": count})
                else:
                    self._json({"ok": False, "error": "invalid content type"})
            except Exception as e:
                self._json({"ok": False, "error": str(e)})

        else:
            self._json({"error": "unknown endpoint"})

    def _parse_body(self, body):
        if not body or not body.strip():
            raise ValueError("请求体为空")
        return json.loads(body.decode("utf-8"))

    def do_OPTIONS(self):
        self.send_response(200)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET,POST,OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.end_headers()

    def _json(self, data, code=200):
        body = json.dumps(data, ensure_ascii=False).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _html(self, html, code=200):
        body = html.encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, fmt, *args):
        print("[%s] %s" % (time.strftime("%H:%M:%S"), self.path))


# ==================== 文章管理（保持原样） ====================
def load_publish_log():
    if os.path.exists(DATA_FILE):
        with open(DATA_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    return {}

def save_publish_log(log):
    with open(DATA_FILE, "w", encoding="utf-8") as f:
        json.dump(log, f, ensure_ascii=False, indent=2)

def list_articles():
    articles = []
    if os.path.isdir(ARTICLE_DIR):
        for fn in sorted(os.listdir(ARTICLE_DIR)):
            if fn.endswith(".md"):
                fp = os.path.join(ARTICLE_DIR, fn)
                title = fn.replace(".md", "").replace("_", " ")
                with open(fp, "r", encoding="utf-8") as f:
                    for line in f:
                        if line.startswith("title:"):
                            title = line.split(":", 1)[1].strip()
                            break
                        if line.strip() == "---":
                            continue
                articles.append({"id": fn, "title": title})
    return articles

def publish_article(filename, account_key="default"):
    fp = os.path.join(ARTICLE_DIR, filename)
    if not os.path.exists(fp):
        raise Exception("文件不存在: " + filename)
    with open(fp, "r", encoding="utf-8") as f:
        md = f.read()
    title = filename.replace(".md", "")
    for line in md.split("\n"):
        if line.startswith("title:"):
            title = line.split(":", 1)[1].strip()
            break
    lines = md.split("\n")
    cleaned = []
    fm_count = 0
    for line in lines:
        if line.strip() == "---" and fm_count < 2:
            fm_count += 1
            continue
        if fm_count == 1:
            continue
        cleaned.append(line)
    md_clean = "\n".join(cleaned).strip()
    token = get_token(account_key)
    img = make_cover(title)
    thumb = upload_thumb(token, img)
    html = md2html(md_clean)
    media_id = add_draft_ext(token, title, ACCOUNTS[account_key]["name"], title[:50], html, thumb)
    if account_key == "default":
        log = load_publish_log()
        log[filename] = {"title": title, "media_id": media_id, "time": time.strftime("%Y-%m-%d %H:%M:%S"), "status": "ok"}
        save_publish_log(log)
    return {"title": title, "media_id": media_id}

def publish_article_ext(account_key, title, content):
    if account_key not in ACCOUNTS:
        raise Exception("未知账号: " + account_key)
    token = get_token(account_key)
    img = make_cover(title)
    thumb = upload_thumb(token, img)
    html = md2html(content)
    author = ACCOUNTS[account_key]["name"]
    media_id = add_draft_ext(token, title, author, title[:50], html, thumb)
    return {"title": title, "media_id": media_id, "account": author}

def page_index():
    articles = list_articles()
    log = load_publish_log()
    art_html = ""
    for a in articles:
        status = ""
        if a["id"] in log:
            rec = log[a["id"]]
            status = '<span style="color:#48BB78;">✓ 已发布 ' + rec.get("time", "") + '</span>'
        else:
            status = '<span style="color:#A0AEC0;">未发布</span>'
        art_html += '''
        <div style="display:flex;align-items:center;justify-content:space-between;padding:16px 20px;background:white;border-radius:12px;margin-bottom:8px;border:1px solid #E2E8F0;">
            <div>
                <div style="font-size:16px;font-weight:600;color:#1A202C;">''' + a["title"] + '''</div>
                <div style="font-size:13px;color:#A0AEC0;margin-top:4px;">''' + a["id"] + '''</div>
            </div>
            <div style="display:flex;align-items:center;gap:12px;">
                ''' + status + '''
                <button onclick="publishArticle(\'''' + a["id"] + '''\')" style="padding:8px 20px;background:#48BB78;color:white;border:none;border-radius:8px;font-size:14px;cursor:pointer;">发布到草稿箱</button>
            </div>
        </div>'''
    return '''<!DOCTYPE html>
<html lang="zh-CN"><head><meta charset="UTF-8"><meta name="viewport" content="width=device-width,initial-scale=1.0">
<title>工程人的智库 - 文章管理</title></head><body>
<h1>🏗️ 工程人的智库 · 带图增强版</h1>
<p>支持 /api/publish_ext_img（多图发布）与 /api/delete_draft。</p>
<div>''' + art_html + '''</div></body></html>'''


if __name__ == "__main__":
    os.makedirs(ARTICLE_DIR, exist_ok=True)
    print("=" * 50)
    print("  工程人的智库 - 微信公众号中转服务（带图增强版）")
    print("  外网访问: http://119.29.168.239:%d" % SERVER_PORT)
    print("  新增: /api/publish_ext_img (多图) | /api/delete_draft")
    print("=" * 50)
    srv = HTTPServer((SERVER_HOST, SERVER_PORT), RequestHandler)
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        print("\n服务已停止")
