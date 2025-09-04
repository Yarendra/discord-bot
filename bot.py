import os
import asyncio
from fastapi import FastAPI, Request
import json
import discord
from discord.ext import commands
from dotenv import load_dotenv
import re

load_dotenv()

TOKEN = os.getenv("DISCORD_BOT_TOKEN")
GUILD_ID = int(os.getenv("DISCORD_GUILD_ID"))
PORT = int(os.getenv("PORT", 8080))

intents = discord.Intents.default()
intents.guilds = True
intents.messages = True
intents.message_content = True

bot = commands.Bot(command_prefix="!", intents=intents)
app = FastAPI()

@bot.event
async def on_ready():
    print(f"✅ Bot logged in as {bot.user}")

def build_summary(repo: str, pr: str, raw_log: str, backend_status: bool) -> str:
    ansi_escape = re.compile(r'\x1B(?:[@-Z\\-_]|\[[0-?]*[ -/]*[@-~])')
    clean_log = ansi_escape.sub('', raw_log or "")
    skip_re = re.compile(r"^(Backend:.*|Logs)$")
    filtered_lines = [
        line.rstrip()
        for line in clean_log.splitlines()
        if line.strip() and not skip_re.match(line.strip())
    ]
    clean_log = "\n".join(filtered_lines)
    
    failed = any("FAIL" in l or "FAILED" in l or "error" in l.lower() for l in filtered_lines)

    backend_icon = "✅" if backend_status and not failed else "❌"

    summary = [
        f"📊 Detailed Summary for **{repo}**",
        f"Backend: {backend_icon}",
        "──────────────────────────────────────────────────────────────"
    ]
    if clean_log:
        summary.append(clean_log)
    summary.append(f"\nPR: #{pr if pr else 'N/A'}")

    return "\n".join(summary)


@app.post("/github")
async def github_webhook(request: Request):
    try:
        data = await request.json()
    except json.JSONDecodeError:
        raw = await request.body()
        print("⚠️ Invalid JSON received, falling back to raw body")
        try:
            data = json.loads(raw.decode("utf-8"))
        except Exception:
            print(f"❌ Still invalid JSON: {raw[:200]}...")
            return {"error": "Invalid JSON payload"}

    print(f"📩 GitHub payload: {data}")

    repo = (
        data.get("repository", {}).get("full_name")
        or data.get("repo")
    )
    repo_name = repo.split("/")[1] if repo and "/" in repo else repo or "unknown-repo"

    run_id = data.get("run_id")
    pr_num = data.get("pr")
    backend = data.get("backend")
    frontend = data.get("frontend")
    backend_log = data.get("backend_log")
    # frontend_log = data.get("frontend_log")

    guild = bot.get_guild(GUILD_ID)
    if not guild:
        print("❌ Guild not found")
        return {"error": "Guild not found"}

    category = discord.utils.get(guild.categories, name=repo_name)
    if not category:
        print(f"❌ Category {repo_name} not found. Skipping.")
        return {"error": f"Category {repo_name} not found"}

    channel = discord.utils.get(category.text_channels, name="pr-report")
    if not channel:
        print(f"❌ Channel pr-report not found in {repo_name}. Skipping.")
        return {"error": "Channel pr-report not found"}

    logs_url = f"https://github.com/{repo}/actions/runs/{run_id}"

    statuses = [s for s in [backend, frontend] if s]
    status_icon = "✅" if statuses and all(s == "success" for s in statuses) else "❌"

    job_lines = []
    if backend:
        job_lines.append(f"Backend: {'✅' if backend == 'success' else '❌'}")
    if frontend:
        job_lines.append(f"Frontend: {'✅' if frontend == 'success' else '❌'}")
    if not job_lines:
        job_lines.append("No jobs reported")

    pr_text = f"\nPR: #{pr_num}" if pr_num else ""

    await channel.send(
        f"{status_icon} PR check finished for **{repo_name}**{pr_text}"
        + f"\n[Logs]({logs_url})"
    )
    summary_message = build_summary(
        repo_name,
        pr_num,
        backend_log or "",
        backend_status=(backend == "success" if backend else False),
    )
    await channel.send(summary_message)

    return {"ok": True}

async def main():
    import uvicorn
    loop = asyncio.get_running_loop()
    loop.create_task(bot.start(TOKEN))
    config = uvicorn.Config(app, host="0.0.0.0", port=PORT)
    server = uvicorn.Server(config)
    await server.serve()

if __name__ == "__main__":
    asyncio.run(main())
