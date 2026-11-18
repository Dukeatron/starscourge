# 🚀 Buildathon: Make Wednesdays Great Again

**Masters' Union · For AI Developers · Winner gets Rs. 25,000**

> **Every team must build in a fork of this repository.** Projects not built in a fork of this repo won't be judged.

| | |
|---|---|
| **Date** | Wednesday, 18 November 2026 |
| **Hacking** | **3:00 PM – 7:00 PM IST** (code freeze at 7:00 PM sharp) |
| **Venue** | CDS Audi, 8th floor |
| **Prize** | Rs. 25,000 to the winning team |
| **Register your fork** | 👉 **[https://forms.gle/ZJUYKwTYjsMsVB2b9](https://forms.gle/ZJUYKwTYjsMsVB2b9)** (**deadline 3:30 PM IST**) |
| **Final submission** | Your fork as it stands at **7:00 PM IST**. There's nothing else to submit. |

> 🤖 **Using an AI coding agent?** Point it at [`AGENTS.md`](AGENTS.md). It has the full event brief, tracks, judging and rules in a form agents can read directly. Claude Code loads it automatically through `CLAUDE.md`, and Codex reads `AGENTS.md` natively.

---

## 🎯 Pick one build track

| # | Track | Brief |
|---|---|---|
| **01** | **Build for the Physical World** | Make a real-world task easier, faster or more reliable. Show it in a realistic scenario. |
| **02** | **Build for AI Agents** | Find something an agent struggles with. Build the tool that fixes it, then demo the agent using it. |
| **03** | **Build in Your Area of Expertise** | Pick a field you know firsthand. Ship a working product that improves how people handle it today. |

## ⚖️ How you'll be judged (each criterion is ⅓ of your score)

| Criterion | The question judges ask |
|---|---|
| **Working product** | Does it do what you say it does? Show the core workflow in your demo. |
| **Problem insight** | Who faces this problem, and why does it happen? |
| **Depth of execution** | How well did you solve the hardest part of the build? |

---

## Why fork this repo?

Everyone starts from the same commit (the **genesis commit**) at the same time. Organizers can then check that:
- all code was written **during** the Buildathon and not brought in from an earlier project,
- teams commit steadily instead of pasting in one huge AI-generated dump at the end,
- every repo stays public and visible while you build.

The organizers track every fork automatically: commits, timing and activity. Read [RULES.md](RULES.md) before you write any code.

---

## ✅ Setup (about 5 minutes, do it at 3:00 PM)

**In short:** fork → register your fork in the form **by 3:30 PM** → build → push before 7:00 PM.

### 1. Fork this repo
Click **Fork** (top right). On the fork screen:
- **Owner:** one team member's personal account. Only **one fork per team**.
- **Repository name:** `buildathon-<team-name>`, for example `buildathon-byte-bandits`
- Click **Create fork**.

> ⚠️ Don't download a ZIP or copy the files into a new repo. **It has to be a real GitHub fork**, or the tracker can't see you.

### 2. Keep it public
Forks of a public repo are public. **Don't make it private, archive it, or delete it** until judging is over.

### 3. Add your teammates
In your fork: **Settings → Collaborators → Add people**. Add each teammate's GitHub account so their commits count toward the team.

### 4. Enable Actions
Open the **Actions** tab of your fork and click **"I understand my workflows, go ahead and enable them"**. This runs the automatic check on every push.

### 5. Make your registration commit (your first commit)
Fill in [`team.json`](team.json). `track` must be one of `physical-world`, `ai-agents` or `area-of-expertise`. Then:

```bash
git clone https://github.com/<your-username>/buildathon-<team-name>.git
cd buildathon-<team-name>
# edit team.json
git add team.json
git commit -m "register: <team name>"
git push
```

The **Hackathon check** in the Actions tab should go green ✅. If it's red, open the run to see what's wrong in `team.json`.

### 6. Register your fork (deadline: 3:30 PM IST)
👉 **[https://forms.gle/ZJUYKwTYjsMsVB2b9](https://forms.gle/ZJUYKwTYjsMsVB2b9)**

It's a 4-question Google Form: team name, fork link, track, team members. It connects your repo to the organizers' live tracker.

- Fill it in **once per team**, right after forking, and **no later than 3:30 PM IST**. **Teams that don't register can't be tracked.**
- Paste your **fork's** URL (`https://github.com/<you>/buildathon-<team-name>`), not this starter repo's.
- Need to change something? Use the **"Edit your response"** link on the confirmation page. Don't fill it in twice.
- **Final submission is automatic.** Whatever is pushed to your fork at 7:00 PM IST is what gets judged.

---

## 🛠 While you build (3:00 – 7:00 PM)

- Put your code anywhere in the repo (`app/`, `src/`, `frontend/`, `backend/`…). There's no required layout.
- **Commit early, commit often**, at least every 30 minutes of real work, with messages that say what changed.
- **Push regularly.** Commits you never push don't exist to the tracker.
- AI coding tools (Claude Code, Codex, Cursor, Copilot…) are **allowed and encouraged**. Keep `AGENTS.md` and `CLAUDE.md` in the repo; they keep your agent within the rules.
- Before 7:00 PM, replace the "Your project" section below with your project's README.

## 🧊 Code freeze: 7:00 PM IST

At 7:00 PM the tracker takes a snapshot of every fork. **Commits pushed after code freeze are ignored.** Judges look at your last commit before 7:00 PM.

## ❌ Things that get you flagged

- Rewriting history (`git push --force`, rebasing away the genesis commit, squashing everything into one commit)
- Commits dated before 3:00 PM
- One or two giant commits containing most of the project
- A repo that isn't a fork of this one, or that's private or deleted

See [RULES.md](RULES.md) for the full list.

---

## Your project

### AgentShield

AgentShield is a guard proxy that sits between AI agents and the third-party APIs they call, catching runaway retry loops before they get the shared IP banned. It answers repeated calls from cache, blocks identical payloads that loop, and shows live what it saved.

- **Team:** _TODO: team name_
- **Track:** `ai-agents`
- **Problem:** Teams running AI agents against rate-limited APIs (for example a Shopify order-sync agent) watch them get stuck re-sending the same request. The agent has no memory of what it just sent and treats every error as "try again", so within seconds it trips the upstream rate limit and the provider bans the IP, taking every integration on that IP down with it.
- **What we built:** a FastAPI backend with a mock rate-limited upstream (4 calls per 10 s, then a 60 s IP ban), a `/proxy` route that runs every agent call through the AgentShield engine, live `/stats` and `/logs`, and two one-click demos that send the same agent traffic with and without the shield.
- **The hardest part:** _TODO: the proxy engine's loop detection (engine owner)._ On the backend: one in-memory source of truth with strict lock ordering, demos that run as cancellable tasks tagged with a generation number so a reset can never let a stale request slip in, and a metric invariant (`total = passed + cached + blocked + upstream_banned`) asserted after every test scenario.
- **Demo / screenshots:** see the demo commands below.

### Setup

Requires Python 3.10+.

```bash
python -m venv .venv
source .venv/bin/activate          # Windows: .venv\Scripts\activate
pip install -r requirements-dev.txt
```

### Run

```bash
uvicorn main:app --host 127.0.0.1 --port 8000
```

> **Single worker only.** All state (rate-limit window, ban, metrics, logs) lives in process memory. Running with `--workers 2` or more splits that state between processes and the numbers stop adding up.

### Test

```bash
pytest -q
```

Tests use a fake engine injected by `tests/conftest.py`. The two tests that need the real engine (protected demo counts) skip automatically when `proxy_engine.py` is missing or still the temporary stub.

### Routes

| Method | Path | What it does | Success | Errors |
| --- | --- | --- | --- | --- |
| GET | `/` | Serves `index.html` | 200 | 404 `{"error":"FRONTEND_NOT_FOUND"}` if the file is missing |
| POST | `/target-api` | Calls the mock upstream directly (no protection). Body optional: `{"agent_id": "...", "payload": {...}}` | 200 upstream body | 403 `IP_BANNED` |
| POST | `/proxy` | Sends a call through AgentShield. Body: `{"agent_id", "endpoint", "payload"}` | 200, or 429 `BLOCKED` with a `Retry-After` header | 403 passed through, 422 invalid body, 500 `INTERNAL_ERROR` |
| POST | `/demo/unprotected` | Starts the unprotected demo (7 direct calls, 0.2 s apart) | 202 `{"status":"started","demo":"unprotected"}` | 409 `{"error":"DEMO_ALREADY_RUNNING","demo":"..."}` |
| POST | `/demo/protected` | Starts the protected demo (the same 7 calls through the proxy) | 202 `{"status":"started","demo":"protected"}` | 409 as above |
| POST | `/demo/reset` | Cancels any running demo and clears all state | 200 `{"status":"reset"}` | none |
| GET | `/demo/status` | Whether a demo is running | 200 `{"running": bool, "demo": str or null}` | none |
| GET | `/stats` | `ip_status`, `ban_remaining_sec`, `total_calls`, `passed_calls`, `cached_calls`, `blocked_calls`, `bans_prevented`, `dollars_saved` | 200 | none |
| GET | `/logs` | Newest 50 log entries, newest first | 200 | none |

### Demo

```bash
curl -s -X POST localhost:8000/demo/unprotected   # 202
sleep 2 && curl -s localhost:8000/stats           # passed_calls 4, ip_status BANNED
curl -s -X POST localhost:8000/demo/protected     # 202, starts from a clean slate
sleep 2 && curl -s localhost:8000/stats           # passed 1, cached 1, blocked 5, HEALTHY
```
