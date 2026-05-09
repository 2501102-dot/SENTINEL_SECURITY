"""
notifier.py - Free notification delivery

Channels:
1) Telegram Bot API (free, reliable)
2) Optional UltraMsg WhatsApp API (quick demo integration)
3) Optional CallMeBot WhatsApp API (fallback)
"""

import os
import time
import json
from datetime import datetime
from urllib.parse import quote_plus, urlencode
from urllib.request import urlopen, Request


class NotificationService:
    def __init__(self):
        cfg = self._load_config_file()

        self.alert_phone = self._cfg("ALERT_PHONE_NUMBER", "+923215981828", cfg)

        self.telegram_bot_token = self._cfg("TELEGRAM_BOT_TOKEN", "8611456949:AAHtcOmTXTFkccSxSELf-dbp5Nqxrx-vJLQ", cfg)
        self.telegram_chat_id = self._cfg("TELEGRAM_CHAT_ID", "8323912802", cfg)

        self.callmebot_phone = self._cfg("CALLMEBOT_PHONE", "", cfg)
        self.callmebot_apikey = self._cfg("CALLMEBOT_APIKEY", "", cfg)

        self.ultramsg_instance_id = self._cfg("ULTRAMSG_INSTANCE_ID", "", cfg)
        self.ultramsg_token = self._cfg("ULTRAMSG_TOKEN", "", cfg)
        self.ultramsg_to = self._normalize_ultramsg_to(self._cfg("ULTRAMSG_TO", self.alert_phone, cfg))
        self.ultramsg_priority = self._cfg("ULTRAMSG_PRIORITY", "10", cfg)

        self.enable_telegram = self._cfg("ENABLE_TELEGRAM_MESSAGE", "1", cfg) == "1"
        self.enable_whatsapp = self._cfg("ENABLE_WHATSAPP_MESSAGE", "1", cfg) == "1"
        self.cooldown_seconds = int(self._cfg("NOTIFY_COOLDOWN_SECONDS", "90", cfg))

        self.telegram_ready = bool(self.telegram_bot_token and self.telegram_chat_id)
        self.ultramsg_ready = bool(self.ultramsg_instance_id and self.ultramsg_token and self.ultramsg_to)
        self.callmebot_ready = bool(self.callmebot_phone and self.callmebot_apikey)
        self.whatsapp_ready = self.ultramsg_ready or self.callmebot_ready
        self.enabled = self.telegram_ready or self.whatsapp_ready

        self._last_notification_ts = 0.0

    def _load_config_file(self):
        cfg_path = os.path.join(os.path.dirname(__file__), "notification_config.json")
        if not os.path.exists(cfg_path):
            return {}
        try:
            with open(cfg_path, "r", encoding="utf-8") as f:
                raw = json.load(f)
            return {str(k).strip(): str(v).strip() for k, v in raw.items() if v is not None}
        except Exception as e:
            print(f"[NOTIFY] Failed to read notification_config.json: {e}")
            return {}

    def _cfg(self, key, default, cfg):
        value = os.getenv(key)
        if value is not None and str(value).strip() != "":
            return str(value).strip()
        if key in cfg and str(cfg[key]).strip() != "":
            return str(cfg[key]).strip()
        return str(default).strip()

    def _normalize_phone(self, value):
        # Keep leading '+' if present, remove spaces/dashes that may break provider parsing.
        s = str(value or "").strip().replace(" ", "").replace("-", "")
        return s

    def _normalize_ultramsg_to(self, value):
        """UltraMsg is most reliable with chat-id format like 923001234567@c.us."""
        s = str(value or "").strip()
        if "@" in s:
            return s

        digits = "".join(ch for ch in s if ch.isdigit())
        return f"{digits}@c.us" if digits else s

    def log_status(self):
        if self.telegram_ready:
            print("[NOTIFY] Telegram notifications enabled")
        if self.ultramsg_ready:
            print(f"[NOTIFY] UltraMsg WhatsApp notifications enabled for {self.ultramsg_to}")
        elif self.callmebot_ready:
            print("[NOTIFY] CallMeBot WhatsApp notifications enabled")
        if not self.enabled:
            print("[NOTIFY] No free notification channel configured")

    def _in_cooldown(self):
        now = time.time()
        if now - self._last_notification_ts < self.cooldown_seconds:
            return True
        self._last_notification_ts = now
        return False

    def _send_get(self, url):
        req = Request(url, headers={"User-Agent": "smartsec-notifier/1.0"})
        last_error = None
        for attempt in range(2):
            try:
                with urlopen(req, timeout=12) as resp:
                    return resp.read().decode("utf-8", errors="ignore")
            except Exception as e:
                last_error = e
                if attempt == 0:
                    time.sleep(1.0)
        raise last_error

    def _send_post_form(self, url, payload):
        body = urlencode(payload).encode("utf-8")
        req = Request(
            url,
            data=body,
            headers={
                "User-Agent": "smartsec-notifier/1.0",
                "Content-Type": "application/x-www-form-urlencoded",
            },
        )
        last_error = None
        for attempt in range(2):
            try:
                with urlopen(req, timeout=12) as resp:
                    return resp.read().decode("utf-8", errors="ignore")
            except Exception as e:
                last_error = e
                if attempt == 0:
                    time.sleep(1.0)
        raise last_error

    def _send_telegram(self, message):
        encoded = quote_plus(message)
        url = (
            f"https://api.telegram.org/bot{self.telegram_bot_token}/sendMessage"
            f"?chat_id={quote_plus(self.telegram_chat_id)}&text={encoded}"
        )
        self._send_get(url)

    def _send_callmebot_whatsapp(self, message):
        encoded = quote_plus(message)
        url = (
            "https://api.callmebot.com/whatsapp.php"
            f"?phone={quote_plus(self.callmebot_phone)}"
            f"&text={encoded}"
            f"&apikey={quote_plus(self.callmebot_apikey)}"
        )
        self._send_get(url)

    def _send_ultramsg_whatsapp(self, message):
        url = f"https://api.ultramsg.com/{self.ultramsg_instance_id}/messages/chat"
        payload = {
            "token": self.ultramsg_token,
            "to": self.ultramsg_to,
            "body": message,
            "priority": self.ultramsg_priority,
        }
        raw = self._send_post_form(url, payload)

        try:
            parsed = json.loads(raw) if raw else {}
        except Exception:
            parsed = {"raw": raw}

        sent = str(parsed.get("sent", "")).strip().lower() == "true"
        if not sent:
            msg = parsed.get("message") or parsed.get("error") or raw or "Unknown UltraMsg error"
            raise RuntimeError(f"UltraMsg send failed: {msg}")

    def notify_intrusion(self, camera_id, confidence, threat_level, details):
        if not self.enabled:
            return
        if self._in_cooldown():
            return

        ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        conf_pct = round(float(confidence) * 100)
        msg = (
            "SENTINEL ALERT\n"
            f"Camera: {camera_id}\n"
            "Detection: PERSON\n"
            f"Threat: {threat_level}\n"
            f"Confidence: {conf_pct}%\n"
            f"Time: {ts}\n"
            f"Details: {details}"
        )

        if self.enable_telegram and self.telegram_ready:
            try:
                self._send_telegram(msg)
                print("[NOTIFY] Telegram alert sent")
            except Exception as e:
                print(f"[NOTIFY] Telegram send failed: {e}")

        if self.enable_whatsapp and self.whatsapp_ready:
            try:
                if self.ultramsg_ready:
                    self._send_ultramsg_whatsapp(msg)
                    print(f"[NOTIFY] WhatsApp alert sent (UltraMsg) to {self.ultramsg_to}")
                else:
                    self._send_callmebot_whatsapp(msg)
                    print(f"[NOTIFY] WhatsApp alert sent (CallMeBot) to {self.callmebot_phone}")
            except Exception as e:
                print(f"[NOTIFY] WhatsApp send failed: {e}")

    def send_test_message(self):
        if not self.enabled:
            return {"ok": False, "reason": "No notification channel configured"}

        msg = (
            "SENTINEL TEST MESSAGE\n"
            "Your notification pipeline is active."
        )

        results = {"telegram": False, "whatsapp": False, "errors": []}
        if self.enable_telegram and self.telegram_ready:
            try:
                self._send_telegram(msg)
                results["telegram"] = True
            except Exception as e:
                results["errors"].append(f"telegram: {e}")

        if self.enable_whatsapp and self.whatsapp_ready:
            try:
                if self.ultramsg_ready:
                    self._send_ultramsg_whatsapp(msg)
                else:
                    self._send_callmebot_whatsapp(msg)
                results["whatsapp"] = True
            except Exception as e:
                results["errors"].append(f"whatsapp: {e}")

        ok = results["telegram"] or results["whatsapp"]
        return {"ok": ok, **results}
