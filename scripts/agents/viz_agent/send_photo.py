"""Shared helper - send a PNG image to Telegram via sendPhoto."""
import json
import urllib.request
import os

AGENT_JSON = os.path.expanduser('~/.atrophy/agents/general_montgomery/data/agent.json')


def send_photo(image_bytes, caption, agent_json_path=AGENT_JSON):
    with open(agent_json_path) as f:
        cfg = json.load(f)
    bot_token = cfg['telegram_bot_token']
    chat_id = cfg['telegram_chat_id']

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
    resp = urllib.request.urlopen(req)
    return json.loads(resp.read())
