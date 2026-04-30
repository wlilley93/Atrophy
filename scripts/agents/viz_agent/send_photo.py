"""Shared helper - send a PNG image to Telegram via sendPhoto, with logging."""
import json
import logging
import os
import urllib.request
from datetime import datetime

LOG_DIR = os.path.expanduser('~/.atrophy/logs/viz_agent')
os.makedirs(LOG_DIR, exist_ok=True)

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [viz] %(message)s',
    handlers=[
        logging.FileHandler(os.path.join(LOG_DIR, 'viz_agent.log')),
        logging.StreamHandler(),
    ],
)
log = logging.getLogger('viz_agent')

MONTGOMERY_MANIFEST = os.path.expanduser(
    '~/.atrophy/agents/general_montgomery/data/agent.json'
)


def _resolve_telegram_creds(agent_json_path=MONTGOMERY_MANIFEST):
    """Resolve bot token and chat ID, preferring env vars over flat manifest fields."""
    with open(agent_json_path) as f:
        cfg = json.load(f)

    # Modern path: channels.telegram.bot_token_env / chat_id_env
    channels = cfg.get('channels', {}).get('telegram', {})
    token_env = channels.get('bot_token_env', '')
    chat_env = channels.get('chat_id_env', '')

    bot_token = os.environ.get(token_env, '') if token_env else ''
    chat_id = os.environ.get(chat_env, '') if chat_env else ''

    # Fallback: deprecated flat fields (log warning if used)
    if not bot_token:
        bot_token = cfg.get('telegram_bot_token', '')
        if bot_token:
            log.warning('Using deprecated telegram_bot_token field - migrate to channels.telegram.bot_token_env')
    if not chat_id:
        chat_id = cfg.get('telegram_chat_id', '')
        if chat_id:
            log.warning('Using deprecated telegram_chat_id field - migrate to channels.telegram.chat_id_env')

    if not bot_token or not chat_id:
        raise ValueError('No Telegram credentials found in manifest or env vars')

    return bot_token, chat_id


def send_photo(image_bytes, caption, agent_json_path=MONTGOMERY_MANIFEST):
    bot_token, chat_id = _resolve_telegram_creds(agent_json_path)

    log.info('Sending photo: %s (%d bytes)', caption, len(image_bytes))

    url = f"https://api.telegram.org/bot{bot_token}/sendPhoto"
    boundary = "----FormBoundary7MA4YWxkTrZu0gW"
    body = (
        f"--{boundary}\r\n"
        f'Content-Disposition: form-data; name="chat_id"\r\n\r\n'
        f"{chat_id}\r\n"
        f"--{boundary}\r\n"
        f'Content-Disposition: form-data; name="caption"\r\n\r\n'
        f"{caption}\r\n"
        f"--{boundary}\r\n"
        f'Content-Disposition: form-data; name="photo"; filename="chart.png"\r\n'
        f"Content-Type: image/png\r\n\r\n"
    ).encode('utf-8') + image_bytes + f"\r\n--{boundary}--\r\n".encode('utf-8')

    req = urllib.request.Request(url, data=body)
    req.add_header('Content-Type', f'multipart/form-data; boundary={boundary}')

    try:
        resp = urllib.request.urlopen(req)
        result = json.loads(resp.read())
        msg_id = result.get('result', {}).get('message_id', '?')
        log.info('Delivered: msg_id=%s ok=%s', msg_id, result.get('ok'))
        return result
    except Exception as exc:
        log.error('Send failed: %s', exc)
        raise
