"""Telegram bot for SlothFlix token management."""

import os
import secrets
from datetime import datetime, timedelta

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import (
    ApplicationBuilder,
    CallbackQueryHandler,
    CommandHandler,
    ContextTypes,
)

import cache

BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")
ADMIN_ID = int(os.getenv("TELEGRAM_ADMIN_ID", "5597932516"))
TOKEN_EXPIRY_DAYS = int(os.getenv("TOKEN_EXPIRY_DAYS", "7"))
APP_URL = os.getenv("APP_URL", "http://localhost:8180").rstrip("/")


async def start_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "Welcome to SlothFlix!\n\n"
        "Use /request to get an access token.\n"
        "Use /status to check your current token."
    )


async def request_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    existing = cache.get_user_token(user.id)
    if existing:
        exp = existing["expires_at"][:16]
        await update.message.reply_text(f"You already have an active token (expires {exp}).\nUse /status to check it.")
        return

    keyboard = InlineKeyboardMarkup([
        [
            InlineKeyboardButton("Approve", callback_data=f"approve:{user.id}:{user.username or user.first_name}"),
            InlineKeyboardButton("Deny", callback_data=f"deny:{user.id}:{user.username or user.first_name}"),
        ]
    ])
    await context.bot.send_message(
        chat_id=ADMIN_ID,
        text=f"Access request from @{user.username or user.first_name} (ID: {user.id})",
        reply_markup=keyboard,
    )
    await update.message.reply_text("Request sent! The admin will review it shortly.")


async def status_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    token_row = cache.get_user_token(user.id)
    if token_row:
        exp = token_row["expires_at"][:16]
        await update.message.reply_text(f"Your token is active. Expires: {exp}")
    else:
        await update.message.reply_text("You have no active token. Use /request to get one.")


async def revoke_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID:
        await update.message.reply_text("Admin only.")
        return
    if not context.args:
        await update.message.reply_text("Usage: /revoke <telegram_user_id>")
        return
    try:
        uid = int(context.args[0])
    except ValueError:
        await update.message.reply_text("Provide a numeric user ID.")
        return
    cache.revoke_token(user_id=uid)
    await update.message.reply_text(f"Revoked token for user {uid}.")


async def callback_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    data = query.data
    action, uid_str, username = data.split(":", 2)
    uid = int(uid_str)

    if query.from_user.id != ADMIN_ID:
        await query.answer("Only the admin can do that.", show_alert=True)
        return

    if action == "approve":
        token = secrets.token_hex(16)
        expires_at = (datetime.utcnow() + timedelta(days=TOKEN_EXPIRY_DAYS)).isoformat()
        cache.save_token(token, uid, username, expires_at)
        await context.bot.send_message(
            chat_id=uid,
            text=f"You're in! Click here to access SlothFlix:\n\n{APP_URL}/?token={token}\n\nLink expires in {TOKEN_EXPIRY_DAYS} days.",
        )
        await query.edit_message_text(f"Approved @{username} (ID: {uid}). Token sent.")
    elif action == "deny":
        await context.bot.send_message(chat_id=uid, text="Your SlothFlix access request was denied.")
        await query.edit_message_text(f"Denied @{username} (ID: {uid}).")


def main():
    if not BOT_TOKEN:
        print("TELEGRAM_BOT_TOKEN not set, bot disabled.")
        return
    app = ApplicationBuilder().token(BOT_TOKEN).build()
    app.add_handler(CommandHandler("start", start_cmd))
    app.add_handler(CommandHandler("request", request_cmd))
    app.add_handler(CommandHandler("status", status_cmd))
    app.add_handler(CommandHandler("revoke", revoke_cmd))
    app.add_handler(CallbackQueryHandler(callback_handler))
    print("Telegram bot started.")
    app.run_polling()


if __name__ == "__main__":
    main()
