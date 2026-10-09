#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
publish_with_images.py — 工程人的智库 带图发布器（v2，走 VPS 中转）

原理（解决微信 IP 白名单）：
  本机公网 IP 不在公众号白名单，无法直连 api.weixin.qq.com。
  因此本脚本：
    1. 本地用 Pillow 把图片压缩到 2MB 内（JPEG）；
    2. 把 Markdown 中 `![alt](path)` 依次替换为占位符 @@IMG{n}@@；
    3. 以 multipart/form-data POST 到 VPS 的 /api/publish_ext_img
       （account / title / digest / content + 有序 images[]）；
    4. VPS（白名单 IP）负责把图片上传微信素材库、替换占位符、写入草稿箱。
  可选 --delete <media_id> 通过 VPS /api/delete_draft 清理旧草稿。

用法：
  python publish_with_images.py --md 文章.md --title "标题" --account default
  python publish_with_images.py --md 文章.md --title "标题" --delete <旧media_id>
"""
import argparse
import io
import json
import os
import re
import ssl
import sys
import urllib.request

VPS_HOST = "119.29.168.239:8899"
ENDPOINT = f"http://{VPS_HOST}/api/publish_ext_img"
DELETE_ENDPOINT = f"http://{VPS_HOST}/api/delete_draft"

# 账号键（与服务端 ACCOUNTS 对应）
ACCOUNTS = ["default", "helper", "everyday"]

CTX = ssl.create_default_context()
CTX.check_hostname = False
CTX.verify_mode = ssl.CERT_NONE


def compress_image(path, max_w=1080, quality=82):
    from PIL import Image
    img = Image.open(path).convert("RGB")
    w, h = img.size
    if w > max_w:
        ratio = max_w / w
        img = img.resize((max_w, int(h * ratio)), Image.LANCZOS)
    buf = io.BytesIO()
    q = quality
    img.save(buf, format="JPEG", quality=q, optimize=True)
    data = buf.getvalue()
    while len(data) > 1900 * 1024 and q > 40:
        q -= 8
        buf = io.BytesIO()
        img.save(buf, format="JPEG", quality=q, optimize=True)
        data = buf.getvalue()
    return data


def build_multipart(fields, images):
    """fields: dict[str,str]; images: list[(filename, bytes)]，均按序以 name='images' 发送。"""
    boundary = ("----WxImg" + os.urandom(8).hex()).encode("ascii")
    body = b""
    for k, v in fields.items():
        body += (b"--" + boundary + b"\r\n"
                 + b'Content-Disposition: form-data; name="' + k.encode() + b'"\r\n\r\n'
                 + v.encode("utf-8") + b"\r\n")
    for fn, data in images:
        body += (b"--" + boundary + b"\r\n"
                 + b'Content-Disposition: form-data; name="images"; filename="' + fn.encode() + b'"\r\n'
                 + b"Content-Type: image/jpeg\r\n\r\n"
                 + data + b"\r\n")
    body += b"--" + boundary + b"--\r\n"
    return body, ("multipart/form-data; boundary=" + boundary.decode())


def post_json(url, body, ctype):
    req = urllib.request.Request(url, data=body, headers={"Content-Type": ctype})
    with urllib.request.urlopen(req, context=CTX, timeout=120) as r:
        return json.loads(r.read().decode())
    return None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--md", required=True)
    ap.add_argument("--title", required=True)
    ap.add_argument("--account", default="default", choices=ACCOUNTS)
    ap.add_argument("--digest", default="")
    ap.add_argument("--delete", default="", help="发布后清理的旧草稿 media_id")
    args = ap.parse_args()

    md_path = os.path.abspath(args.md)
    base = os.path.dirname(md_path)
    with open(md_path, "r", encoding="utf-8") as f:
        md = f.read()

    # 收集图片引用（按出现顺序）
    refs = []  # (alt, local_abs)
    def repl(m):
        alt = m.group(1)
        ref = m.group(2).strip()
        local = ref if os.path.isabs(ref) else os.path.join(base, ref)
        idx = len(refs)
        refs.append((alt, local))
        return f"@@IMG{idx}@@"
    content = re.sub(r'!\[(.*?)\]\(([^)]+)\)', repl, md)

    if not refs:
        sys.exit("错误：Markdown 中未发现任何图片引用，请用带图版本；或改用 publish_to_draft.py 发无图版。")

    print(f"发现 {len(refs)} 张配图，本地压缩中...")
    images = []
    for i, (alt, local) in enumerate(refs):
        if not os.path.exists(local):
            sys.exit(f"错误：第 {i} 张图片缺失: {local}")
        data = compress_image(local)
        print(f"  ✓ [{i}] {os.path.basename(local)} -> {len(data)//1024}KB")
        images.append((f"img{i}.jpg", data))

    fields = {
        "account": args.account,
        "title": args.title,
        "digest": args.digest or args.title[:50],
        "content": content,
    }
    body, ctype = build_multipart(fields, images)
    print("上传到 VPS 中转并发布（VPS 在白名单内上传图片到微信）...")
    try:
        res = post_json(ENDPOINT, body, ctype)
    except Exception as e:
        sys.exit(f"发布请求失败: {e}")

    if not res or not res.get("ok"):
        sys.exit("发布失败: " + json.dumps(res, ensure_ascii=False))
    print(f"✅ 发布成功！media_id: {res.get('media_id')}  配图: {res.get('images')} 张")

    if args.delete:
        try:
            # 线上 /api/delete_draft 接收 JSON body（非 multipart）
            payload = json.dumps({"account": args.account, "media_id": args.delete}).encode("utf-8")
            req = urllib.request.Request(DELETE_ENDPOINT, data=payload,
                                         headers={"Content-Type": "application/json"})
            with urllib.request.urlopen(req, context=CTX, timeout=60) as r:
                dres = json.loads(r.read().decode())
            print(f"{'✅ 已清理旧草稿' if (dres and dres.get('ok')) else '⚠ 旧草稿清理失败'}: {args.delete}"
                  + ("" if (dres and dres.get('ok')) else f"  resp={json.dumps(dres, ensure_ascii=False)}"))
        except Exception as e:
            print(f"⚠ 清理旧草稿异常: {e}")

    print("\n--- 发布摘要 ---")
    print(f"账号: {args.account}（工程人的智库=default）")
    print(f"标题: {args.title}")
    print(f"media_id: {res.get('media_id')}")


if __name__ == "__main__":
    main()
