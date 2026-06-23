from flask import Flask, request, jsonify
from flask_cors import CORS
import asyncio
import aiohttp
import os

app = Flask(__name__)
CORS(app)

BATCH_SIZE = 10
DELAY = 0.5
RETRIES = 2

WOM_URL = "https://api.wiseoldman.net/v2/players/{}"


async def fetch_thieving(session, semaphore, name, attempt=0):
    async with semaphore:
        headers = {
            "User-Agent": "osrs-thieving-checker/1.0",
            "Accept": "application/json",
        }
        try:
            encoded = aiohttp.helpers.quote(name.lower().replace(" ", "_"), safe="")
            async with session.get(WOM_URL.format(encoded), headers=headers,
                                   timeout=aiohttp.ClientTimeout(total=15)) as r:
                if r.status == 404:
                    return {"name": name, "level": None, "error": "not found on WOM"}
                if r.status == 429:
                    if attempt < RETRIES:
                        await asyncio.sleep(5)
                        return await fetch_thieving(session, semaphore, name, attempt + 1)
                    return {"name": name, "level": None, "error": "rate limited"}
                if r.status != 200:
                    return {"name": name, "level": None, "error": f"HTTP {r.status}"}

                data = await r.json(content_type=None)
                lvl = (data
                       .get("latestSnapshot", {})
                       .get("data", {})
                       .get("skills", {})
                       .get("thieving", {})
                       .get("level"))

                if lvl is None:
                    return {"name": name, "level": None, "error": "no thieving data"}
                if lvl < 1:
                    return {"name": name, "level": None, "error": "not on hiscores"}
                return {"name": name, "level": lvl, "error": None}

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
