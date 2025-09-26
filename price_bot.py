import os
import sqlite3
import threading
import time
from datetime import datetime

import telebot
from scrapers import fetch_price

TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN")
if not TOKEN:
    raise RuntimeError("TELEGRAM_BOT_TOKEN ortam değişkeni set edilmemiş.")

CHECK_INTERVAL = 30 * 60  # 30 dakika (saniye cinsinden)
DB_PATH = "products.db"

bot = telebot.TeleBot(TOKEN)


def get_db_connection():
    conn = sqlite3.connect(DB_PATH, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    return conn


def ensure_tables():
    conn = get_db_connection()
    cur = conn.cursor()
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS products (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            url TEXT NOT NULL,
            target_price REAL,
            last_price REAL,
            last_checked TIMESTAMP
        )
        """
    )
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS subscribers (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            chat_id INTEGER UNIQUE
        )
        """
    )
    conn.commit()
    conn.close()


ensure_tables()


def help_text():
    return (
        "🔔 *Fiyat Takip Botu Komutları*
"
        "/start – Botu kaydet ve yardım mesajı
"
        "/help – Yardım mesajı
"
        "/add AD | URL | HEDEF_FİYAT (opsiyonel)
"
        "/list – İzlenen ürünleri listele
"
        "/remove ID – Ürünü kaldır
"
        "/check – Fiyatları hemen kontrol et
"
        "💡 Yeni site eklersen scrapers.py dosyasındaki seçicileri güncelle."
    )


def add_subscriber(chat_id: int):
    conn = get_db_connection()
    cur = conn.cursor()
    cur.execute("INSERT OR IGNORE INTO subscribers (chat_id) VALUES (?)", (chat_id,))
    conn.commit()
    conn.close()


def get_subscribers():
    conn = get_db_connection()
    cur = conn.cursor()
    cur.execute("SELECT chat_id FROM subscribers")
    rows = cur.fetchall()
    conn.close()
    return [row["chat_id"] for row in rows]


def insert_product(name: str, url: str, target_price: float | None):
    conn = get_db_connection()
    cur = conn.cursor()
    cur.execute(
        "INSERT INTO products (name, url, target_price) VALUES (?, ?, ?)",
        (name, url, target_price),
    )
    conn.commit()
    conn.close()


def list_products():
    conn = get_db_connection()
    cur = conn.cursor()
    cur.execute("SELECT * FROM products ORDER BY id")
    rows = cur.fetchall()
    conn.close()
    return rows


def remove_product(product_id: int):
    conn = get_db_connection()
    cur = conn.cursor()
    cur.execute("DELETE FROM products WHERE id = ?", (product_id,))
    changes = cur.rowcount
    conn.commit()
    conn.close()
    return changes > 0


def update_product_price(product_id: int, price: float):
    conn = get_db_connection()
    cur = conn.cursor()
    cur.execute(
        """
        UPDATE products
        SET last_price = ?, last_checked = ?
        WHERE id = ?
        """,
        (price, datetime.utcnow(), product_id),
    )
    conn.commit()
    conn.close()


@bot.message_handler(commands=["start"])
def handle_start(message):
    add_subscriber(message.chat.id)
    bot.reply_to(message, help_text(), parse_mode="Markdown")


@bot.message_handler(commands=["help"])
def handle_help(message):
    bot.reply_to(message, help_text(), parse_mode="Markdown")


@bot.message_handler(commands=["add"])
def handle_add(message):
    add_subscriber(message.chat.id)
    try:
        payload = message.text.split(" ", 1)[1]
    except IndexError:
        bot.reply_to(message, "Format: /add AD | URL | HEDEF_FİYAT (opsiyonel)")
        return

    parts = [p.strip() for p in payload.split("|")]
    if len(parts) < 2:
        bot.reply_to(message, "En az isim ve URL gerekli.")
        return

    name = parts[0]
    url = parts[1]
    target_price = None

    if len(parts) >= 3 and parts[2]:
        try:
            target_price = float(parts[2].replace(",", "."))
        except ValueError:
            bot.reply_to(message, "Hedef fiyat sayı olmalı.")
            return

    try:
        insert_product(name, url, target_price)
    except Exception as exc:
        bot.reply_to(message, f"Ürün eklenirken hata: {exc}")
        return

    info = f"✅ *{name}* eklendi.
URL: {url}"
    if target_price:
        info += f"
🎯 Hedef fiyat: {target_price:.2f}"
    bot.reply_to(message, info, parse_mode="Markdown")


@bot.message_handler(commands=["list"])
def handle_list(message):
    rows = list_products()
    if not rows:
        bot.reply_to(message, "👀 Hiç ürün yok. `/add` ile ekleyebilirsin.")
        return

    lines = []
    for row in rows:
        target = f"{row['target_price']:.2f}" if row["target_price"] else "–"
        last = f"{row['last_price']:.2f}" if row["last_price"] else "–"
        checked = row["last_checked"] or "–"
        lines.append(
            f"*#{row['id']}* {row['name']}
"
            f"URL: {row['url']}
"
            f"🎯 Hedef: {target} | 💰 Son: {last} | ⏱ {checked}"
        )

    bot.reply_to(message, "
".join(lines), parse_mode="Markdown")


@bot.message_handler(commands=["remove"])
def handle_remove(message):
    try:
        product_id = int(message.text.split(" ", 1)[1])
    except (IndexError, ValueError):
        bot.reply_to(message, "Kullanım: /remove 3")
        return

    if remove_product(product_id):
        bot.reply_to(message, f"🗑 Ürün #{product_id} kaldırıldı.")
    else:
        bot.reply_to(message, f"Ürün #{product_id} bulunamadı.")


@bot.message_handler(commands=["check"])
def handle_check(message):
    add_subscriber(message.chat.id)
    bot.reply_to(message, "⏳ Kontrol ediliyor...")
    trigger_price_check(manual=True)


@bot.message_handler(func=lambda message: True)
def fallback(message):
    bot.reply_to(message, "Anlayamadım. Yardım için /help yazabilirsin.")


def trigger_price_check(manual: bool = False):
    rows = list_products()
    if not rows:
        if manual:
            subscribers = get_subscribers()
            for chat_id in subscribers:
                bot.send_message(
                    chat_id,
                    "İzlenen ürün yok. `/add` ile ekleyebilirsin."
                )
        return

    subscribers = get_subscribers()
    if not subscribers:
        return

    for row in rows:
        try:
            price = fetch_price(row["url"])
        except Exception as exc:
            for chat_id in subscribers:
                bot.send_message(
                    chat_id,
                    f"⚠️ {row['name']} fiyatı alınamadı: {exc}"
                )
            continue

        if price is None:
            continue

        send_alert = False
        reason_parts = []

        if row["last_price"] is None:
            send_alert = True
            reason_parts.append("İlk fiyat bilgisi kaydedildi.")
        elif price < row["last_price"]:
            send_alert = True
            reason_parts.append(f"Fiyat düştü! {row['last_price']:.2f} → {price:.2f}")
        if row["target_price"] and price <= row["target_price"]:
            send_alert = True
            reason_parts.append(f"Hedef fiyatın altına düştü! 🎯 {row['target_price']:.2f}")

        update_product_price(row["id"], price)

        if send_alert:
            message = (
                f"🚨 *{row['name']}*
"
                f"URL: {row['url']}
"
                f"💰 Güncel fiyat: {price:.2f}
"
                + "
".join(reason_parts)
            )
            for chat_id in subscribers:
                bot.send_message(chat_id, message, parse_mode="Markdown")


def price_watcher_loop():
    while True:
        try:
            trigger_price_check()
        except Exception as exc:
            print(f"[HATA] Fiyat kontrol döngüsü: {exc}")
        time.sleep(CHECK_INTERVAL)


watcher_thread = threading.Thread(target=price_watcher_loop, daemon=True)
watcher_thread.start()

print("Bot çalışıyor 🚀")
bot.infinity_polling(skip_pending=True)