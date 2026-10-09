#!/usr/bin/env python3
"""
topic_suggestor.py - 工程人智库选题推荐脚本

功能：
1. 列出所有内置选题（按分类）
2. 按分类筛选选题
3. 根据关键词推荐选题
4. 随机推荐选题

用法：
  python topic_suggestor.py                     # 随机推荐3个选题
  python topic_suggestor.py --category 技术实战   # 筛选指定分类选题
  python topic_suggestor.py --keyword AI         # 关键词搜索
  python topic_suggestor.py --list              # 列出所有选题
  python topic_suggestor.py --random 5          # 随机推荐5个选题
"""

import os
import sys
import json
import argparse
import random
from pathlib import Path

# ── 内置选题库 ──────────────────────────────────────────
TOPICS = {
    "技术实战": [
        {
            "title": "DeepSeek辅助工程管理的5个实战技巧",
            "core": "AI工具在进度、成本、质量、安全、资料五个维度的实战应用",
            "audience": "项目经理、施工员、资料员",
            "words": 2000
        },
        {
            "title": "工程人如何用AI搭建自己的知识库",
            "core": "从0到1搭建个人/团队知识库，用AI实现文档自动分类与检索",
            "audience": "工程技术人员、资料管理员",
            "words": 1800
        },
        {
            "title": "施工现场安全隐患AI识别指南",
            "core": "用AI视觉识别替代人工巡检，提升安全隐患发现效率",
            "audience": "安全员、现场管理人员",
            "words": 1600
        },
        {
            "title": "用AI 10分钟写出施工方案框架",
            "core": "AI辅助施工方案快速生成，结构完整、符合规范",
            "audience": "技术负责人、施工员",
            "words": 1500
        },
        {
            "title": "工程变更签证：如何用AI快速核算成本",
            "core": "AI读取变更图纸/指令，自动计算工程量与成本影响",
            "audience": "造价员、项目经理",
            "words": 1800
        },
    ],
    "思维升级": [
        {
            "title": "从1352篇文章中蒸馏认知框架：工程人的思维升级方法",
            "core": "用AI蒸馏优秀博主思维模型，建立自己的认知操作系统",
            "audience": "工程管理人员、终身学习者",
            "words": 2500
        },
        {
            "title": "工程人为什么要建立自己的思维模型",
            "core": "从经验主义到模型思维，提升工程决策质量",
            "audience": "工程管理人员",
            "words": 1800
        },
        {
            "title": "用Iceberg框架重新理解工程管理",
            "core": "表象层→数据层→利益层→权力层→认知层，五层分析框架",
            "audience": "项目经理、工程总监",
            "words": 2200
        },
        {
            "title": "工程师的批判性思维：如何不被表象迷惑",
            "core": "培养批判性思维，避免工程决策中的认知偏差",
            "audience": "所有工程从业人员",
            "words": 1600
        },
    ],
    "行业洞察": [
        {
            "title": "2026年工程建设行业趋势预测",
            "core": "AI+工程、绿色建造、数字化交付三大趋势深度解析",
            "audience": "工程管理人员、企业决策者",
            "words": 2200
        },
        {
            "title": "AI将如何改变工程管理模式",
            "core": "从BIM到AI，工程管理范式的三次跃迁",
            "audience": "工程管理人员、技术人员",
            "words": 2000
        },
        {
            "title": "从"基建大国"到"基建强国"：工程师的新使命",
            "core": "质量强国战略下，工程人的角色转型与能力提升",
            "audience": "工程技术人员、管理人员",
            "words": 1800
        },
        {
            "title": "绿色建造：工程人必须了解的政策与技术",
            "core": "双碳目标下的绿色建造政策解读与关键技术",
            "audience": "工程管理人员、技术人员",
            "words": 2000
        },
    ],
    "职场成长": [
        {
            "title": "工程人如何用AI提升职场竞争力",
            "core": "AI时代，工程人需要掌握的新技能与思维方式",
            "audience": "所有工程从业人员",
            "words": 1800
        },
        {
            "title": "从技术岗到管理岗：工程人的进阶路径",
            "core": "技术→管理转型的关键能力与常见陷阱",
            "audience": "技术人员、新任管理者",
            "words": 2000
        },
        {
            "title": "工程人必知的10个职场隐性规则",
            "core": "工程行业职场生存法则，少走5年弯路",
            "audience": "年轻工程师、职场新人",
            "words": 1600
        },
        {
            "title": "如何把工程项目经验转化为个人知识资产",
            "core": "项目经验→知识资产→个人IP，三步实现职场跃迁",
            "audience": "所有工程从业人员",
            "words": 1800
        },
    ]
}


# ── 输出格式化 ──────────────────────────────────────────
def print_topic(topic: dict, index: int = None):
    """格式化打印单个选题"""
    prefix = f"{index}. " if index else ""
    print(f"\n{prefix}【{topic['title']}】")
    print(f"    核心：{topic['core']}")
    print(f"    受众：{topic['audience']}")
    print(f"    字数：{topic['words']}字")


def print_topics(topics: list, category: str = None):
    """格式化打印选题列表"""
    if category:
        print(f"\n{'='*50}")
        print(f"📂 分类：{category}")
        print(f"{'='*50}")
    for i, t in enumerate(topics, 1):
        print_topic(t, i)


def print_all_topics():
    """打印所有选题"""
    for category, topics in TOPICS.items():
        print_topics(topics, category)


# ── 筛选与搜索 ──────────────────────────────────────────
def filter_by_category(category: str) -> list:
    """按分类筛选"""
    for cat, topics in TOPICS.items():
        if category in cat:
            return [(cat, topics)]
    return [(cat, topics) for cat, topics in TOPICS.items()]


def search_by_keyword(keyword: str) -> list:
    """按关键词搜索选题"""
    results = []
    for category, topics in TOPICS.items():
        for t in topics:
            if (keyword.lower() in t['title'].lower() or
                keyword.lower() in t['core'].lower()):
                results.append((category, t))
    return results


def random_pick(n: int = 3) -> list:
    """随机推荐n个选题"""
    all_topics = []
    for category, topics in TOPICS.items():
        for t in topics:
            all_topics.append((category, t))
    return random.sample(all_topics, min(n, len(all_topics)))


# ── 输出为 Markdown ──────────────────────────────────────
def output_markdown(topics_with_category: list, output_path: str = None):
    """输出为 Markdown 格式（用于草稿选题卡片）"""
    lines = []
    lines.append("# 推荐选题\n")
    for item in topics_with_category:
        if isinstance(item, tuple):
            category, t = item
        else:
            t = item
            category = "未分类"
        lines.append(f"## {t['title']}\n")
        lines.append(f"- **分类**：{category}")
        lines.append(f"- **核心论点**：{t['core']}")
        lines.append(f"- **目标读者**：{t['audience']}")
        lines.append(f"- **预计字数**：{t['words']}字\n")

    content = "\n".join(lines)

    if output_path:
        Path(output_path).write_text(content, encoding="utf-8")
        print(f"✅ 选题卡片已保存：{output_path}")
    else:
        print(content)


# ── 主函数 ──────────────────────────────────────────────
def main():
    parser = argparse.ArgumentParser(description="工程人智库·选题推荐")
    parser.add_argument("--category", type=str, help="按分类筛选（模糊匹配）")
    parser.add_argument("--keyword", type=str, help="关键词搜索")
    parser.add_argument("--list", action="store_true", help="列出所有选题")
    parser.add_argument("--random", type=int, default=3, help="随机推荐n个选题")
    parser.add_argument("--output", type=str, help="输出选题卡片到指定路径")
    args = parser.parse_args()

    # 如果没有参数，随机推荐
    if not any([args.category, args.keyword, args.list]):
        results = random_pick(args.random)
        print(f"\n🎲 随机推荐 {len(results)} 个选题：\n")
        for i, (cat, t) in enumerate(results, 1):
            print(f"{i}. [{cat}] {t['title']}")
            print(f"   核心：{t['core']}\n")
        return

    # 列出所有
    if args.list:
        print_all_topics()
        return

    # 按分类筛选
    if args.category:
        results = filter_by_category(args.category)
        for cat, topics in results:
            print_topics(topics, cat)
        return

    # 关键词搜索
    if args.keyword:
        results = search_by_keyword(args.keyword)
        if not results:
            print(f"❌ 没有找到包含「{args.keyword}」的选题。")
            return
        print(f"\n🔍 找到 {len(results)} 个相关选题：\n")
        for i, (cat, t) in enumerate(results, 1):
            print(f"{i}. [{cat}] {t['title']}")
        return


if __name__ == "__main__":
    main()
