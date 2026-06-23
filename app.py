from flask import Flask, request, jsonify
from flask_cors import CORS
import asyncio
import aiohttp
import os

app = Flask(__name__)
CORS(app)

CONCURRENT = 10
URL = "https://secure.runescape.com/m=hiscore_oldschool/index_lite.json?player={}"
HEADERS = {"User-Agent": "Mozilla/5.0"}


async def fetch_thieving(session, semaphore, name):
    async with semaphore:
        try:
            encoded = aiohttp.helpers.quote(name, safe="")
            async with session.get(URL.format(encoded), headers=HEADERS,
                                   timeout=aiohttp.ClientTimeout(total=10)) as r:
                if r.status == 404:
                    return {"name": name, "level": None, "error": "player not found"}
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
            return {"name": name, "level": None, "error": "timeout"}
        except Exception as e:
            return {"name": name, "level": None, "error": str(e)}


async def fetch_all(names):
    semaphore = asyncio.Semaphore(CONCURRENT)
    async with aiohttp.ClientSession() as session:
        tasks = [fetch_thieving(session, semaphore, n) for n in names]
        return await asyncio.gather(*tasks)


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
