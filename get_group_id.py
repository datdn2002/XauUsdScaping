import requests

BOT_TOKEN = "8429353540:AAGNIPh-Lje4KAl_Ko57OS8TBWfgzpgaJWM"

url = f"https://api.telegram.org/bot{BOT_TOKEN}/getUpdates"
response = requests.get(url)
data = response.json()

print("=== Danh sach cac chat da gui tin nhan den bot ===\n")

seen = set()
for update in data.get("result", []):
    if "message" in update:
        chat = update["message"]["chat"]
        chat_id = chat["id"]
        chat_type = chat["type"]
        name = chat.get("title") or chat.get("first_name", "Unknown")
        
        if chat_id not in seen:
            seen.add(chat_id)
            print(f"  Chat ID: {chat_id}")
            print(f"  Type: {chat_type}")
            print(f"  Name: {name}")
            print("-" * 30)

if not seen:
    print("Khong tim thay chat nao. Hay gui tin nhan vao nhom truoc!")

