"""Telegram bot for SlothFlix — runs as async task within FastAPI lifespan."""

import logging
import os
import secrets
from datetime import datetime, timedelta, timezone
from urllib.parse import quote

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import (
    ApplicationBuilder,
    CallbackQueryHandler,
    CommandHandler,
    ContextTypes,
)

from slothflix.config import settings
from slothflix.models.database import async_session
from slothflix.services.token import TokenService

logger = logging.getLogger(__name__)

ADMIN_ID = settings.telegram_admin_id
TOKEN_EXPIRY_DAYS = settings.token_expiry_days
APP_URL = settings.app_url.rstrip("/")
ROM_DIR = settings.rom_dir

_SYSTEM_DISPLAY = {
    "nes": "NES", "snes": "SNES", "gba": "GBA", "gbc": "GBC",
    "n64": "N64", "psx": "PSX", "ps1": "PS1", "genesis": "Genesis",
    "segamd": "Genesis", "atari2600": "Atari 2600", "nds": "DS",
    "ms": "Master System", "gg": "Game Gear", "vb": "Virtual Boy",
    "segacd": "Sega CD", "32x": "32X", "atari7800": "Atari 7800",
    "lynx": "Lynx", "ngp": "Neo Geo Pocket", "ws": "WonderSwan",
    "coleco": "ColecoVision", "pce": "PC Engine", "fds": "Famicom Disk",
    "saturn": "Saturn",
}


async def start_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "Welcome to SlothFlix!\n\n"
        "Use /request to get an access token.\n"
        "Use /status to check your current token."
    )


async def request_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    async with async_session() as session:
        existing = await TokenService.get_user_token(session, str(user.id))
    if existing:
        exp = existing.expires_at[:16]
        await update.message.reply_text(
            f"You already have an active token (expires {exp}).\nUse /status to check it."
        )
        return

    keyboard = InlineKeyboardMarkup([
        [
            InlineKeyboardButton(
                "Approve",
                callback_data=f"approve:{user.id}:{user.username or user.first_name}",
            ),
            InlineKeyboardButton(
                "Deny",
                callback_data=f"deny:{user.id}:{user.username or user.first_name}",
            ),
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
    async with async_session() as session:
        token = await TokenService.get_user_token(session, str(user.id))
    if token:
        exp = token.expires_at[:16]
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
        uid = context.args[0]
    except ValueError:
        await update.message.reply_text("Provide a numeric user ID.")
        return
    async with async_session() as session:
        await TokenService.revoke(session, user_id=uid)
    await update.message.reply_text(f"Revoked token for user {uid}.")


async def callback_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    data = query.data
    action, uid_str, username = data.split(":", 2)

    if query.from_user.id != ADMIN_ID:
        await query.answer("Only the admin can do that.", show_alert=True)
        return

    if action == "approve":
        token = secrets.token_hex(16)
        expires_at = TokenService.expiry_days(TOKEN_EXPIRY_DAYS)
        async with async_session() as session:
            await TokenService.create(session, uid_str, username, token, expires_at)
        await context.bot.send_message(
            chat_id=int(uid_str),
            text=(
                f"You're in! Click here to access SlothFlix:\n\n"
                f"{APP_URL}/?token={token}\n\n"
                f"Link expires in {TOKEN_EXPIRY_DAYS} days."
            ),
        )
        await query.edit_message_text(f"Approved @{username} (ID: {uid_str}). Token sent.")
    elif action == "deny":
        await context.bot.send_message(
            chat_id=int(uid_str), text="Your SlothFlix access request was denied."
        )
        await query.edit_message_text(f"Denied @{username} (ID: {uid_str}).")


# --- Game commands ---

def _scan_roms():
    """Scan ROM directory and return {system: [roms]}."""
    systems = {}
    if not os.path.isdir(ROM_DIR):
        return systems
    for sys_dir in sorted(os.listdir(ROM_DIR)):
        sys_path = os.path.join(ROM_DIR, sys_dir)
        if not os.path.isdir(sys_path):
            continue
        roms = []
        for f in sorted(os.listdir(sys_path)):
            if os.path.isfile(os.path.join(sys_path, f)):
                roms.append(f)
        if roms:
            systems[sys_dir] = roms
    return systems


async def games_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """List available game systems and ROM counts."""
    systems = _scan_roms()
    if not systems:
        await update.message.reply_text(
            f"No ROMs found.\n\nUpload ROMs at {APP_URL}/emu/"
        )
        return

    lines = ["Available Games:"]
    total = 0
    for sys_name, roms in systems.items():
        display = _SYSTEM_DISPLAY.get(sys_name, sys_name.upper())
        lines.append(f"  {display} - {len(roms)} ROMs")
        total += len(roms)
    lines.append(f"\nTotal: {total} games")
    lines.append(f"\nUpload more at {APP_URL}/emu/")

    await update.message.reply_text("\n".join(lines))


async def game_search_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Search for a specific ROM by name."""
    if not context.args:
        await update.message.reply_text("Usage: /game <search term>")
        return

    query = " ".join(context.args).lower()
    systems = _scan_roms()
    matches = []

    for sys_name, roms in systems.items():
        for rom in roms:
            if query in rom.lower():
                size = 0
                try:
                    size = os.path.getsize(os.path.join(ROM_DIR, sys_name, rom))
                except OSError:
                    pass
                display = _SYSTEM_DISPLAY.get(sys_name, sys_name.upper())
                size_str = (
                    f"{size / 1024:.0f} KB"
                    if size < 1024 * 1024
                    else f"{size / (1024 * 1024):.1f} MB"
                )
                matches.append((rom, sys_name, display, size_str))

    if not matches:
        await update.message.reply_text(f"No games found matching '{query}'")
        return

    lines = [f"Found {len(matches)} match(es):"]
    for rom, sys_name, display, size_str in matches[:10]:
        url = f"{APP_URL}/?game={sys_name}:{quote(rom)}"
        name = rom.replace(".", " ", 1).rsplit(".", 1)[0]
        lines.append(f"  {name} ({display}, {size_str})\n  Play: {url}")

    await update.message.reply_text("\n".join(lines))


async def netplay_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Generate netplay instructions for a game."""
    if not context.args:
        await update.message.reply_text("Usage: /netplay <game name>")
        return

    query = " ".join(context.args).lower()
    systems = _scan_roms()
    match = None

    for sys_name, roms in systems.items():
        for rom in roms:
            if query in rom.lower():
                match = (rom, sys_name)
                break
        if match:
            break

    if not match:
        await update.message.reply_text(f"No game found matching '{query}'")
        return

    rom, sys_name = match
    name = rom.rsplit(".", 1)[0]
    url = f"{APP_URL}/?game={sys_name}:{quote(rom)}"

    await update.message.reply_text(
        f'Netplay Room for "{name}"\n\n'
        f"1. Open: {url}\n"
        "2. Click the netplay button in the emulator\n"
        "3. Create a room and share the code here\n\n"
        "Share this message with friends!"
    )


async def run_bot():
    """Run the Telegram bot as an async task."""
    token = settings.telegram_bot_token
    if not token:
        logger.warning("TELEGRAM_BOT_TOKEN not set, bot disabled")
        return

    app = ApplicationBuilder().token(token).build()
    app.add_handler(CommandHandler("start", start_cmd))
    app.add_handler(CommandHandler("request", request_cmd))
    app.add_handler(CommandHandler("status", status_cmd))
    app.add_handler(CommandHandler("revoke", revoke_cmd))
    app.add_handler(CommandHandler("games", games_cmd))
    app.add_handler(CommandHandler("game", game_search_cmd))
    app.add_handler(CommandHandler("netplay", netplay_cmd))
    app.add_handler(CallbackQueryHandler(callback_handler))

    logger.info("Telegram bot starting polling...")
    await app.run_polling()
