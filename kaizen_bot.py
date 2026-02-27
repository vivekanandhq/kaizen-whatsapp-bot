from playwright.sync_api import sync_playwright
import time
import re
import requests
from groq import Groq
from datetime import datetime
import json
import os

# ============================================
# API KEYS
# ============================================
class APIConfig:
    GROQ_KEY = "   "  # <-- APNI KEY 
    NEWS_KEY = "   "

client = Groq(api_key=APIConfig.GROQ_KEY)

# ============================================
# PERSISTENT MEMORY
# ============================================
class PersistentMemory:
    def __init__(self, filename="kaizen_memory.json"):
        self.filename = filename
        self.user_contexts = {}
        self.load()
    
    def load(self):
        if os.path.exists(self.filename):
            try:
                with open(self.filename, 'r') as f:
                    self.user_contexts = json.load(f)
                print(f"📂 Loaded memory for {len(self.user_contexts)} users")
            except:
                self.user_contexts = {}
    
    def save(self):
        try:
            with open(self.filename, 'w') as f:
                json.dump(self.user_contexts, f, indent=2)
        except:
            pass
    
    def get_context(self, user_id):
        if user_id not in self.user_contexts:
            self.user_contexts[user_id] = {
                "messages": [
                    {"role": "system", "content": "You are Kaizen, a helpful WhatsApp assistant. Remember everything the user tells you."}
                ],
                "last_active": datetime.now().isoformat()
            }
            self.save()
        return self.user_contexts[user_id]["messages"]
    
    def add_message(self, user_id, role, content):
        context = self.get_context(user_id)
        context.append({"role": role, "content": content})
        if len(context) > 21:
            self.user_contexts[user_id]["messages"] = [context[0]] + context[-20:]
        self.user_contexts[user_id]["last_active"] = datetime.now().isoformat()
        self.save()
    
    def clear_memory(self, user_id):
        if user_id in self.user_contexts:
            del self.user_contexts[user_id]
            self.save()
            return True
        return False

memory = PersistentMemory()

# ============================================
# NEWS FUNCTION
# ============================================
def get_news(category: str = "general") -> str:
    try:
        categories = {"tech": "technology", "sports": "sports", "business": "business"}
        cat = categories.get(category.lower(), "general")
        
        url = f"https://newsapi.org/v2/top-headlines?country=in&category={cat}&apiKey={APIConfig.NEWS_KEY}"
        response = requests.get(url, timeout=5)
        
        if response.status_code == 200:
            articles = response.json().get('articles', [])[:3]
            if articles:
                return "\n".join([f"📰 {a['title']} ({a['source']['name']})" for a in articles])
        return "No news found"
    except:
        return "❌ News error"

# ============================================
# CURRENCY FUNCTION
# ============================================
def convert_currency(amount: float, from_curr: str, to_curr: str) -> str:
    try:
        url = f"https://api.frankfurter.app/latest?from={from_curr.upper()}&to={to_curr.upper()}"
        response = requests.get(url, timeout=5)
        
        if response.status_code == 200:
            data = response.json()
            rate = data['rates'][to_curr.upper()]
            converted = amount * rate
            return f"💰 {amount} {from_curr.upper()} = {converted:.2f} {to_curr.upper()}"
        return "❌ Conversion failed"
    except:
        return "❌ Currency error"

# ============================================
# TIME FUNCTION
# ============================================
def get_time_info() -> str:
    now = datetime.now()
    return f"🕐 {now.strftime('%I:%M %p')}\n📅 {now.strftime('%A, %B %d, %Y')}"

# ============================================
# WAKE WORD DETECTION
# ============================================
def is_called(message):
    if not message:
        return False
    message_lower = message.lower().strip()
    return message_lower.startswith("kaizen!") or " kaizen!" in message_lower

def extract_query(message):
    query = re.sub(r'^kaizen!\s*', '', message, flags=re.IGNORECASE)
    query = re.sub(r'\bkaizen!\s*', '', query, flags=re.IGNORECASE)
    return query.strip()

def validate_query(query):
    if not query:
        return False, "Please ask something after kaizen!"
    if len(query) < 3:
        return False, "Question too short."
    return True, query

# ============================================
# QUERY ROUTER
# ============================================
def process_query(user_id: str, query: str) -> str:
    query_lower = query.lower()
    
    # NEWS
    if any(word in query_lower for word in ['news', 'headlines']):
        for cat in ['tech', 'sports', 'business']:
            if cat in query_lower:
                return get_news(cat)
        return get_news()
    
    # CURRENCY
    elif 'convert' in query_lower:
        match = re.search(r'convert\s+(\d+(?:\.\d+)?)\s*([a-z]{3})\s+to\s+([a-z]{3})', query_lower, re.IGNORECASE)
        if match:
            amount = float(match.group(1))
            from_curr = match.group(2)
            to_curr = match.group(3)
            return convert_currency(amount, from_curr, to_curr)
        return "Use: convert 100 USD to INR"
    
    # TIME
    elif any(word in query_lower for word in ['time', 'date', 'day', 'clock']):
        return get_time_info()
    
    # CLEAR MEMORY
    elif 'clear my memory' in query_lower or 'forget everything' in query_lower:
        if memory.clear_memory(user_id):
            return "🧹 Memory cleared!"
        return "No memory to clear."
    
    # DEFAULT: GROQ
    else:
        try:
            memory.add_message(user_id, "user", query)
            messages = memory.get_context(user_id)
            
            response = client.chat.completions.create(
                messages=messages,
                model="llama-3.3-70b-versatile",
                temperature=0.7,
                max_tokens=200
            )
            
            reply = response.choices[0].message.content
            memory.add_message(user_id, "assistant", reply)
            return reply
        except Exception as e:
            return f"❌ Error: {str(e)}"

# ============================================
# WHATSAPP BOT WITH SELF MSGS ALLOWED
# ============================================
class KaizenBot:
    def __init__(self):
        print("\n" + "═"*50)
        print("     KAIZEN! - SELF MSGS ALLOWED 😭")
        print("═"*50)
        
        self.playwright = sync_playwright().start()
        self.context = None
        self.page = None
        self.processed_ids = set()
    
    def start(self):
        print("\n📱 Starting WhatsApp...")
        
        self.context = self.playwright.chromium.launch_persistent_context(
            user_data_dir="./whatsapp_session",
            headless=False,
            args=["--disable-notifications"]
        )
        self.page = self.context.new_page()
        self.page.goto("https://web.whatsapp.com")
        
        print("   🚀 Waiting for WhatsApp...")
        start = time.time()
        qr_shown = False
        
        while True:
            elapsed = time.time() - start
            
            if self.page.locator('#pane-side').count() > 0:
                print(f"\r   ✅ Ready in {elapsed:.1f}s!")
                time.sleep(2)
                return True
            
            if not qr_shown and self.page.locator('canvas').count() > 0:
                print(f"\r   📱 QR Code - Please scan!")
                qr_shown = True
            
            if elapsed > 120:
                print("\n   ⚠️ Timeout!")
                return False
            
            time.sleep(0.1)
    
    def get_all_chats(self):
        try:
            self.page.wait_for_selector('#pane-side', timeout=5000)
            chats = self.page.locator('div[role="listitem"]').all()
            if not chats:
                chats = self.page.locator('div[role="row"]').all()
            return chats[:5] if chats else []
        except:
            return []
    
    def get_chat_name(self, chat):
        try:
            name_elem = chat.locator('span[title]').first
            if name_elem.count():
                return name_elem.get_attribute('title') or "Unknown"
        except:
            pass
        return "Unknown"
    
    def click_chat(self, chat):
        try:
            chat.click()
            time.sleep(1.5)
            return True
        except:
            return False
    
    def get_last_message(self):
        """Get last message - SELF MSGS ALLOWED!"""
        try:
            time.sleep(0.5)
            messages = self.page.locator('div.message-in, div.message-out').all()
            if not messages:
                return None, None
            
            last = messages[-1]
            class_attr = last.get_attribute('class') or ''
            is_out = 'message-out' in class_attr
            
            text_elem = last.locator('span.selectable-text, span[dir="ltr"]').last
            if text_elem.count():
                text = text_elem.text_content().strip()
                msg_id = last.get_attribute('data-id') or str(time.time())
                return text, msg_id
            return None, None
        except:
            return None, None
    
    def send_message(self, text):
        try:
            box = self.page.locator('footer div[contenteditable="true"]').first
            if box.count():
                box.click()
                box.fill(text)
                time.sleep(0.3)
                box.press("Enter")
                time.sleep(0.5)
                return True
        except:
            pass
        return False
    
    def run(self):
        if not self.start():
            return
        
        print("\n" + "═"*50)
        print("🤖 KAIZEN ONLINE - SELF MSGS ALLOWED")
        print("📌 Try: 'kaizen! hello' (from any chat, even your own)")
        print("═"*50)
        
        try:
            scan_count = 0
            
            while True:
                scan_count += 1
                print(f"\n🔍 SCAN #{scan_count}")
                
                chats = self.get_all_chats()
                if not chats:
                    print("   No chats")
                    time.sleep(5)
                    continue
                
                for i, chat in enumerate(chats):
                    chat_name = self.get_chat_name(chat)
                    
                    if not self.click_chat(chat):
                        continue
                    
                    msg, msg_id = self.get_last_message()
                    
                    if not msg:
                        self.page.keyboard.press("Escape")
                        continue
                    
                    if msg_id in self.processed_ids:
                        self.page.keyboard.press("Escape")
                        continue
                    
                    print(f"\n📂 [{i+1}] {chat_name}")
                    print(f"   💬 {msg[:50]}...")
                    
                    if is_called(msg):
                        print(f"   🎯 WAKE WORD DETECTED!")
                        
                        query = extract_query(msg)
                        is_valid, response_or_error = validate_query(query)
                        
                        if is_valid:
                            response = process_query(chat_name, query)
                        else:
                            response = response_or_error
                        
                        if self.send_message(response):
                            print(f"   ✅ Replied")
                            self.processed_ids.add(msg_id)
                        else:
                            print(f"   ❌ Send failed")
                    
                    self.page.keyboard.press("Escape")
                    time.sleep(0.5)
                
                print(f"\n⏳ Next scan in 5s...")
                time.sleep(5)
                
        except KeyboardInterrupt:
            print("\n\n🛑 Stopped")
            memory.save()
        finally:
            if self.context:
                self.context.close()
            if self.playwright:
                self.playwright.stop()

# ============================================
# RUN
# ============================================
if __name__ == "__main__":
    bot = KaizenBot()
    bot.run()
