"""メール本文の組み立てと Gmail SMTP 送信

送信部は products/fanza-aff/src/services/email_notifier.py から移植。
"""

import html
import os
import smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

from src.models import Item


def _sources_line(item: Item) -> str:
    """出典行（統合された他ソースと反響を並べる）"""
    parts = [item.source] + item.also_seen
    line = " / ".join(dict.fromkeys(parts))
    eng = item.engagement()
    return f"{line}（{eng}）" if eng else line


def build_subject(date_str: str, picked: int, total: int) -> str:
    return f"[cc-radar] {date_str} 重要{picked}件/全{total}件"


def build_plain(
    date_str: str, items: list[Item], total: int, warnings: list[str], histogram: str = ""
) -> str:
    lines = [
        f"Claude Code まわりの新着 {date_str}",
        f"候補 {total} 件を評価し、重要度 {items[0].score:.1f}〜{items[-1].score:.1f} の {len(items)} 件を選びました。"
        if items
        else f"候補 {total} 件を評価しました。",
        "上から重要度順です。",
        "",
    ]
    for i, it in enumerate(items, start=1):
        lines.append(f"【{i}】({it.score:.1f}) {it.title_ja}")
        if it.whats_new:
            lines.append(f"  何が変わったか: {it.whats_new}")
        if it.why_matters:
            lines.append(f"  なぜ重要か:     {it.why_matters}")
        lines.append(f"  出典: {_sources_line(it)}")
        if it.title_ja != it.title:
            lines.append(f"  原題: {it.title}")
        lines.append(f"  {it.url}")
        if it.discuss_url and it.discuss_url != it.url:
            lines.append(f"  議論: {it.discuss_url}")
        lines.append("")

    if warnings:
        lines.append("--- 注意 ---")
        lines.extend(f"- {w}" for w in warnings)
    if histogram:
        # 掲載が多すぎ・少なすぎのときに閾値をどちらへ動かすか決めるための材料
        lines.append("")
        lines.append(f"スコア分布: {histogram}")
    return "\n".join(lines)


def build_html(
    date_str: str, items: list[Item], total: int, warnings: list[str], histogram: str = ""
) -> str:
    def esc(s: str) -> str:
        return html.escape(s or "")

    blocks = [
        "<html><body style=\"font-family:-apple-system,'Hiragino Sans',sans-serif;"
        'line-height:1.7;color:#222;max-width:720px">',
        f"<h2 style='margin-bottom:4px'>Claude Code まわりの新着 {esc(date_str)}</h2>",
        f"<p style='color:#666;margin-top:0'>候補 {total} 件を評価し、重要度順に {len(items)} 件を掲載。</p>",
    ]
    for i, it in enumerate(items, start=1):
        blocks.append("<div style='margin:24px 0;padding-left:12px;border-left:3px solid #d0d0d0'>")
        blocks.append(
            f"<div style='font-weight:600;font-size:16px'>"
            f"<span style='color:#b45309'>[{it.score:.1f}]</span> "
            f"<a href='{esc(it.url)}' style='color:#1a56db;text-decoration:none'>{i}. {esc(it.title_ja)}</a>"
            f"</div>"
        )
        if it.whats_new:
            blocks.append(f"<div><b>何が変わったか:</b> {esc(it.whats_new)}</div>")
        if it.why_matters:
            blocks.append(f"<div><b>なぜ重要か:</b> {esc(it.why_matters)}</div>")
        meta = [f"出典: {esc(_sources_line(it))}"]
        if it.title_ja != it.title:
            meta.append(f"原題: {esc(it.title)}")
        if it.discuss_url and it.discuss_url != it.url:
            meta.append(f"<a href='{esc(it.discuss_url)}' style='color:#666'>議論を見る</a>")
        blocks.append(
            f"<div style='color:#666;font-size:13px;margin-top:4px'>{' ｜ '.join(meta)}</div>"
        )
        blocks.append("</div>")

    if warnings:
        items_html = "".join(f"<li>{esc(w)}</li>" for w in warnings)
        blocks.append(
            f"<div style='margin-top:32px;padding:12px;background:#fff7ed;font-size:13px'>"
            f"<b>注意</b><ul>{items_html}</ul></div>"
        )
    if histogram:
        blocks.append(
            f"<div style='margin-top:24px;color:#888;font-size:12px'>"
            f"スコア分布: {esc(histogram)}</div>"
        )
    blocks.append("</body></html>")
    return "\n".join(blocks)


def send(subject: str, plain: str, html_body: str) -> bool:
    """Gmail SMTP で送信する。未設定ならスキップして False"""
    gmail_user = os.getenv("GMAIL_USER", "")
    gmail_password = os.getenv("GMAIL_APP_PASSWORD", "")
    target_email = os.getenv("TARGET_EMAIL", "") or gmail_user

    if not gmail_user or not gmail_password:
        print("[mail] GMAIL_USER / GMAIL_APP_PASSWORD 未設定 → スキップ")
        return False

    msg = MIMEMultipart("alternative")
    msg["From"] = gmail_user
    msg["To"] = target_email
    msg["Subject"] = subject
    msg.attach(MIMEText(plain, "plain", "utf-8"))
    msg.attach(MIMEText(html_body, "html", "utf-8"))

    with smtplib.SMTP("smtp.gmail.com", 587) as server:
        server.starttls()
        server.login(gmail_user, gmail_password)
        server.sendmail(gmail_user, target_email, msg.as_string())

    print(f"[mail] 送信完了 → {target_email}")
    return True
