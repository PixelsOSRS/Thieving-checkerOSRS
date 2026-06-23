from flask import Flask, request, jsonify
from flask_cors import CORS
import asyncio
import aiohttp
import os

app = Flask(__name__)
CORS(app)

BATCH_SIZE = 5
DELAY = 2.0
RETRIES = 3
URL = "https://secure.runescape.com/m=hiscore_oldschool/index_lite.json?player={}"

AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.0 Safari/605.1.15",
    "Mozilla/5.0 (X11; Linux x86_64; rv:125.0) Gecko/20100101 Firefox/125.0",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:124.0) Gecko/20100101 Firefox/124.0",
    "Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.0 Mobile/15E148 Safari/604.1",
]

import random

async def fetch_thieving(session, semaphore, name, attempt=0):
    async with semaphore:
        headers = {
            "User-Agent": random.choice(AGENTS),
            "Accept": "application/json, text/plain, */*",
            "Accept-Language": "en-US,en;q=0.9",
            "Referer": "https://secure.runescape.com/",
        }
        try:
            encoded = aiohttp.helpers.quote(name, safe="")
            async with session.get(URL.format(encoded), headers=headers,
                                   timeout=aiohttp.ClientTimeout(total=15)) as r:
                if r.status == 404:
                    return {"name": name, "level": None, "error": "player not found"}
                if r.status == 503 or r.status == 429:
                    if attempt < RETRIES:
                        await asyncio.sleep(3 * (attempt + 1))
                        return await fetch_thieving(session, semaphore, name, attempt + 1)
                    return {"name": name, "level": None, "error": f"rate limited (HTTP {r.status})"}
                if r.status != 200:
                    return {"name": name, "level": None, "error": f"HTTP {r.status}"}
                data = await r.json(content_type=None)
                for skill in data.get("skills", []):
                    if skill.get("name", "").lower() == "thieving":
                        lvl = skill.get("level", -1)
                        if lvl < 1:
                            return {"name": name, "level": None, "error": "not on hiscores"}
                        return {"name": name, "level": lvl, "error": None}
                return {"name": name, "level": None, "error": "no data"}
        except asyncio.TimeoutError:
            if attempt < RETRIES:
                await asyncio.sleep(2)
                return await fetch_thieving(session, semaphore, name, attempt + 1)
            return {"name": name, "level": None, "error": "timeout"}
        except Exception as e:
            return {"name": name, "level": None, "error": str(e)}


async def fetch_all(names):
    semaphore = asyncio.Semaphore(BATCH_SIZE)
    results = []
    async with aiohttp.ClientSession() as session:
        for i in range(0, len(names), BATCH_SIZE):
            batch = names[i:i + BATCH_SIZE]
            tasks = [fetch_thieving(session, semaphore, n) for n in batch]
            batch_results = await asyncio.gather(*tasks)
            results.extend(batch_results)
            if i + BATCH_SIZE < len(names):
                await asyncio.sleep(DELAY)
    return results


@app.route("/check", methods=["POST"])
def check():
    data = request.get_json()
    names = data.get("names", [])
    if not names or len(names) > 500:
        return jsonify({"error": "Provide between 1 and 500 names."}), 400
    names = list(dict.fromkeys([n.strip() for n in names if n.strip()]))
    results = asyncio.run(fetch_all(names))
    return jsonify(results)


@app.route("/")
def index():
    return "OSRS Thieving Checker API is running."


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)
