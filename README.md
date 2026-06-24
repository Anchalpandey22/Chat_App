# 💬 ChatApp — WhatsApp Lite
### Real-Time Chat Application with Groups, Auth & SQLite Database

---
 
## Tech Stack

| Layer     | Technology                          |
|-----------|-------------------------------------|
| Frontend  | HTML + CSS + Vanilla JavaScript     |
| Backend   | Python Flask                        |
| Database  | SQLite (built into Python — no install needed) |
| Real-Time | Server-Sent Events (SSE)           |
| Auth      | Session-based login + SHA256 hashed passwords | 

---

## Features 

- ✅ User Registration & Login (passwords hashed)
- ✅ Real-time 1-to-1 messaging (no page refresh needed)
- ✅ Group chats — create groups, add members, chat
- ✅ Online/offline status indicator
- ✅ Unread message badge
- ✅ Message history stored in SQLite
- ✅ Profile page with editable status
- ✅ WhatsApp-style dark theme UI
- ✅ Date separators in chat

---

## How to Run

### Step 1 — Install Python
You need Python 3.8+. Check: `python --version`

### Step 2 — Navigate to this folder
```bash
cd path/to/chatapp
```

### Step 3 — Install Flask (only one package needed)
```bash
pip install flask
```

### Step 4 — Run the app
```bash
python app.py
```

### Step 5 — Open in browser
```
http://127.0.0.1:5000
```

---

## How to Test Real-Time Chat

To test messaging between two users:
1. Open `http://127.0.0.1:5000` in **Browser Window 1** → Register as "Anchal"
2. Open `http://127.0.0.1:5000` in **Browser Window 2** (or Incognito) → Register as "Friend"
3. In Window 1, click "Friend" in the sidebar → type a message → send
4. Watch it appear instantly in Window 2 without any refresh!

---

## Database

SQLite database file `chatapp.db` is created automatically on first run.
Tables:
- `users` — all registered users
- `messages` — all 1-to-1 messages
- `groups` — group chat rooms
- `group_members` — who is in which group
- `group_messages` — group chat messages

To reset everything: just delete `chatapp.db` and restart.

---

## Project Structure

```
chatapp/
├── app.py              ← Flask backend (all routes + DB + SSE)
├── requirements.txt    ← Only needs Flask
├── chatapp.db          ← SQLite database (auto-created)
├── templates/
│   ├── login.html      ← Login page
│   ├── register.html   ← Register page
│   └── chat.html       ← Main chat interface (WhatsApp-style)
└── static/             ← (for future assets)
```
