#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
publish_to_draft.py - 工程人智库 一键发布到微信草稿箱（VPS 中转真路径）

机制：本机 → VPS 中转(119.29.168.239:8899/api/publish_ext) → 公众号草稿箱
账号键映射：default=工程人的智库 / helper=工程人的助手 / everyday=工程人的每一天

说明：
- 中转服务器会自动把 Markdown 转成公众号样式 HTML，并生成蓝色标题封面（thumb）。
- 中转服务器 md2html() 不渲染图片，故本脚本默认剥离 ![...](...) 图片行，
  保证草稿箱渲染不出错；正文配图请在微信编辑器内手动补。
- 仅推送到「草稿箱」，不自动群发。

用法：
  python publish_to_draft.py --md 文章.md --title "标题"
  python publish_to_draft.py --md 文章.md --title "标题" --account default
"""
import sys
import os
import json
import argparse
import urllib.request
import urllib.error

VPS_HOST = "119.29.168.239"
VPS_PORT = 8899  # 实测可用端口（8898 返回 404，不可用）
ENDPOINT = "/api/publish_ext"
DEFAULT_AUTHOR = "工程数字化老兵"

# 账号键 → 公众号名（与 VPS wx_server ACCOUNTS 对齐）
ACCOUNT_NAMES = {
    "default": "工程人的智库",
    "helper": "工程人的助手",
    "everyday": "工程人的每一天",
}


def read_md(path):
    with open(path, "r", encoding="utf-8") as f:
        return f.read()


def strip_images(md):
    """剥离图片 markdown 行（服务器 md2html 不渲染图片，避免产生乱码 <p>）。"""
    out = []
    for line in md.split("\n"):
        s = line.strip()
        if s.startswith("![") and "](" in s:
            continue
        # 也去掉紧跟图片的封面说明行（形如 "> *封面图：...*"）
        if s.startswith(">") and ("封面" in s or "cover" in s.lower()):
            continue
        out.append(line)
    return "\n".join(out).strip()


def push_to_vps(account_key, title, content):
    url = f"http://{VPS_HOST}:{VPS_PORT}{ENDPOINT}"
    payload = {
        "account": account_key,
        "title": title,
        "content": content,
        "thumb_media_id": "",
    }
    data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    req = urllib.request.Request(
        url, data=data, headers={"Content-Type": "application/json; charset=utf-8"}
    )
    try:
        with urllib.request.urlopen(req, timeout=60) as r:
            return json.loads(r.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        return {"ok": False, "error": f"HTTP {e.code}: {e.read().decode('utf-8','ignore')[:300]}"}
    except Exception as e:  # noqa: BLE001
        return {"ok": False, "error": f"{type(e).__name__}: {e}"}


def main():
    parser = argparse.ArgumentParser(description="工程人智库 · 微信草稿箱推送（VPS 中转）")
    parser.add_argument("--md", required=True, help="Markdown 文章路径")
    parser.add_argument("--title", required=True, help="文章标题")
    parser.add_argument("--account", default="default",
                        choices=["default", "helper", "everyday"],
                        help="default=工程人的智库 / helper=工程人的助手 / everyday=工程人的每一天")
    parser.add_argument("--keep-images", action="store_true",
                        help="保留图片 markdown 行（仅当 VPS 已支持图片渲染时使用）")
    args = parser.parse_args()

    if not os.path.exists(args.md):
        print(f"  [FAIL] 文件不存在: {args.md}")
        sys.exit(1)

    print("=" * 50)
    print(f"  推送至：{ACCOUNT_NAMES[args.account]}  (account={args.account})")
    print(f"  中转：  http://{VPS_HOST}:{VPS_PORT}{ENDPOINT}")
    print("=" * 50)

    md_content = read_md(args.md)
    content = md_content if args.keep_images else strip_images(md_content)
    print(f"  [1/3] 读取 Markdown: {args.md}  ({len(content)} 字符，"
          f"{'保留' if args.keep_images else '已剥离'}图片)")

    print(f"  [2/3] 通过 VPS 推送到草稿箱 ...")
    result = push_to_vps(args.account, args.title, content)
    print(f"  Response: {result}")

    if result.get("media_id") or result.get("ok"):
        print("\n  [OK] 已推送草稿箱！")
        print(f"       media_id : {result.get('media_id', '(见后台)')}")
        print(f"       account  : {result.get('account', ACCOUNT_NAMES[args.account])}")
        print("       请在微信公众平台「草稿箱」查看，确认无误后手动群发。")
    else:
        print(f"\n  [FAIL] {result.get('error', result)}")
        sys.exit(1)


if __name__ == "__main__":
    main()
