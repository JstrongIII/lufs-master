# LUFS Master

Telegram Mini App for audio mastering to -8 LUFS loudness standard.

## Quick Deploy to Railway

1. Push this repo to GitHub
2. Go to [Railway](https://railway.app)
3. New Project → Deploy from GitHub → Select this repo
4. Railway auto-detects Python and deploys

## Manual Deploy

```bash
cd backend
pip install -r requirements.txt
python main.py
```

## Environment Variables

- `PORT` — Server port (default: 8000)
- `TARGET_LUFS` — Target LUFS (default: -8)

## Tech Stack

- **Backend:** FastAPI + FFmpeg loudnorm filter
- **Frontend:** Telegram Mini App (vanilla HTML/JS)
- **Hosting:** Railway / Render / Oracle Cloud