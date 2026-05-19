"""Notification Service - Send alerts via Telegram and WhatsApp"""
import os
import json
import time
from datetime import datetime
from urllib.parse import quote_plus
from urllib.request import urlopen, Request
import urllib.parse

class NotificationService:
    def __init__(self):
        cfg = self._load_config()
        self.telegram_token = self._get_cfg("TELEGRAM_BOT_TOKEN", "", cfg)
        self.telegram_chat_id = self._get_cfg("TELEGRAM_CHAT_ID", "", cfg)
        self.telegram_enabled = bool(self._get_cfg("ENABLE_TELEGRAM_MESSAGE", "1", cfg) == "1")
        
        # UltraMsg WhatsApp config
        self.ultramsg_instance = self._get_cfg("ULTRAMSG_INSTANCE_ID", "", cfg)
        self.ultramsg_token = self._get_cfg("ULTRAMSG_TOKEN", "", cfg)
        self.ultramsg_to = self._get_cfg("ULTRAMSG_TO", "", cfg)
        self.whatsapp_enabled = bool(self._get_cfg("ENABLE_WHATSAPP_MESSAGE", "1", cfg) == "1")
        
        self.cooldown = int(self._get_cfg("NOTIFY_COOLDOWN_SECONDS", "15", cfg))
        self.enabled = bool((self.telegram_token and self.telegram_chat_id and self.telegram_enabled) or 
                           (self.ultramsg_instance and self.ultramsg_token and self.ultramsg_to and self.whatsapp_enabled))
        self._last_notify = 0.0
    
    def _load_config(self):
        """Load configuration from JSON file"""
        try:
            path = os.path.join(os.path.dirname(__file__), "notification_config.json")
            if os.path.exists(path):
                with open(path, "r") as f:
                    return json.load(f)
        except:
            pass
        return {}
    
    def _get_cfg(self, key, default, cfg):
        """Get config value from env or file"""
        val = os.getenv(key) or cfg.get(key) or default
        return str(val).strip() if val else default
    
    def _in_cooldown(self):
        """Check if still in cooldown period"""
        now = time.time()
        if now - self._last_notify < self.cooldown:
            return True
        self._last_notify = now
        return False
    
    def _send_telegram(self, message):
        """Send message via Telegram"""
        url = f"https://api.telegram.org/bot{self.telegram_token}/sendMessage"
        params = f"?chat_id={quote_plus(self.telegram_chat_id)}&text={quote_plus(message)}"
        try:
            req = Request(url + params, headers={"User-Agent": "smartsec/1.0"})
            with urlopen(req, timeout=10) as resp:
                resp.read()
        except Exception as e:
            print(f"[NOTIFY] Telegram error: {e}")
    
    def _send_whatsapp(self, message):
        """Send message via WhatsApp using UltraMsg API"""
        # Remove + from phone number if present
        phone = self.ultramsg_to.replace("+", "") if self.ultramsg_to else ""
        
        url = f"https://api.ultramsg.com/{self.ultramsg_instance}/messages/chat"
        
        # Prepare POST data
        data = urllib.parse.urlencode({
            'token': self.ultramsg_token,
            'to': phone,
            'body': message
        }).encode('utf-8')
        
        try:
            req = Request(url, data=data, headers={"User-Agent": "smartsec/1.0"})
            with urlopen(req, timeout=10) as resp:
                response = resp.read().decode('utf-8')
                print(f"[NOTIFY] WhatsApp response: {response}")
        except Exception as e:
            print(f"[NOTIFY] WhatsApp error: {e}")
    
    def notify_intrusion(self, camera_id, confidence, threat_level, details):
        """Send intrusion alert"""
        if not self.enabled or self._in_cooldown():
            return
        
        ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        conf = round(float(confidence) * 100)
        msg = f"🚨 SECURITY ALERT\n📷 Camera: {camera_id}\n⚠️ Threat: {threat_level}\n📊 Confidence: {conf}%\n🕐 Time: {ts}"
        
        # Send via Telegram if enabled
        if self.telegram_enabled and self.telegram_token and self.telegram_chat_id:
            self._send_telegram(msg)
            print(f"[NOTIFY] Telegram alert sent for {camera_id}")
        
        # Send via WhatsApp if enabled
        if self.whatsapp_enabled and self.ultramsg_instance and self.ultramsg_token and self.ultramsg_to:
            self._send_whatsapp(msg)
            print(f"[NOTIFY] WhatsApp alert sent for {camera_id}")
    
    def log_status(self):
        """Print notification status"""
        if self.telegram_enabled and self.telegram_token and self.telegram_chat_id:
            print("[NOTIFY] ✓ Telegram notifications enabled")
        else:
            print("[NOTIFY] ✗ Telegram disabled (configure TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID)")
        
        if self.whatsapp_enabled and self.ultramsg_instance and self.ultramsg_token and self.ultramsg_to:
            print(f"[NOTIFY] ✓ WhatsApp notifications enabled ({self.ultramsg_to})")
        else:
            print("[NOTIFY] ✗ WhatsApp disabled (configure ULTRAMSG_INSTANCE_ID, ULTRAMSG_TOKEN, ULTRAMSG_TO)")
