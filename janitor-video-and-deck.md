# Janitor: Video Script and Deck Outline

Target: 5:00 video, 7-slide deck. Screen recording plus voiceover, with a small face-cam optional.

---

## Part 1: Video script (5:00)

**Setup before recording:** seeded dataset loaded, dry-run on, one in-use AMI and one prod-tagged volume ready for the "blocked" moment, terminal and UI at 125% zoom, notifications off.

### 0:00 to 0:30: Hook and problem
**On screen:** Slide 1, then a cost-report screenshot with idle snapshots and volumes highlighted.

**Say:**
"Every cloud account I've worked on in seven years has the same quiet problem: orphaned AMIs, unattached volumes, snapshots nobody remembers. Nobody deletes them because nobody is sure they're safe. So they keep costing money. I built Janitor to fix that, using Claude, without ever letting an AI delete anything it shouldn't."

### 0:30 to 1:30: Architecture and core idea
**On screen:** Slide 3 (architecture) and Slide 4 (safety model), animate left to right.

**Say:**
"Janitor runs entirely on my laptop with docker compose. A scanner collects resources, a graph builder works out what depends on what, and Claude reviews each resource and gives a verdict with a reason. But the key idea is this: Claude proposes, policy disposes. A deterministic rule engine sits after Claude, and it can block anything Claude suggests. In-use AMI, attached volume, prod tag, too recent: blocked, no matter what the model says. Then a human approves, and every action lands in an audit log."

### 1:30 to 4:00: Live demo (2.5 min)
**1:30 to 1:50. Start**
- Run `docker compose up`, show the login, pick a region, choose resource type "Snapshots".
- **Say:** "Here's a seeded account with thirty snapshots across two regions."

**1:50 to 2:20. Scan and filter**
- Click Scan. Show the stats panel update: count, total GB, estimated monthly cost.
- Apply a name filter and a date range.
- **Say:** "Stats are scoped to the resource type I picked, and I can filter by name, date, and region."

**2:20 to 3:00. Claude verdicts**
- Click Analyze. Verdict chips appear: delete, keep, review.
- Open one snapshot, then the Claude reasoning tab.
- **Say:** "Claude doesn't just say delete. It explains why: no source volume, older than 90 days, not backing any AMI. And when evidence is thin, it says review."

**3:00 to 3:30. The block moment (the money shot)**
- Select all, including an in-use AMI and the prod-tagged volume. Click Plan cleanup.
- Popup appears listing blocked items with the rule that blocked them.
- **Say:** "I selected everything on purpose. Look: these two are blocked by policy, not by the AI. The AMI is used by a running instance, and this volume is tagged prod. The model never gets the final say."

**3:30 to 4:00. Approve and execute**
- Review the plan, type the confirmation, approve. Show quarantine tags applied, then delete.
- Switch to the Audit tab.
- **Say:** "Dry-run by default. After approval, resources are quarantined first, then deleted. Every action is logged with who approved it, which Claude verdict led to it, and which policy snapshot applied."

### 4:00 to 5:00: Results and close
**On screen:** Slide 6 (results), then Slide 7 (what's next).

**Say:**
"On my labeled test set of thirty resources, Claude agreed with my judgment on [X]%, and not a single blocked resource slipped through policy. In this demo account, that's about [$Y] a month saved. Next: GCP support, scheduled scans, and Slack approvals, and checking resources against Terraform state to catch real orphans. The code and spec are in the repo. Thanks for watching."

**Fill in before recording:** [X]% agreement and [$Y] savings from your actual eval run.

### Recording tips
- Record the demo in one take per segment, stitch later.
- Keep cursor movements slow and deliberate.
- Record voiceover separately for cleaner audio.
- Add captions; many viewers watch muted.
- Keep a 20-second backup clip of the blocked-popup moment in case the live take fails.

---

## Part 2: Deck outline (7 slides)

### Slide 1: Title
- **Title:** Janitor: AI-Assisted Cloud Cleanup, with Guardrails
- **Subtitle:** Claude proposes. Policy and humans dispose.
- **Footer:** your name, role, date
- **Visual:** simple logo (a broom over a cloud) on a dark background.

### Slide 2: The problem
- **Headline:** Orphaned resources quietly burn money
- Three points:
  - AMIs, volumes and snapshots outlive the projects that created them
  - Nobody deletes them because the risk is unclear
  - Manual audits don't scale across regions and accounts
- **Visual:** cost chart or screenshot with idle resources highlighted. Add a real figure from your own experience if you can share one safely.

### Slide 3: The solution and architecture
- **Headline:** A local pipeline from scan to audited cleanup
- **Visual:** the architecture diagram: Scanner, Graph, Claude analyst, Policy engine, Executor, UI.
- One line under it: "Runs fully local with docker compose."

### Slide 4: Safety model
- **Headline:** The AI never has the final say
- Three layers:
  1. Claude: verdict, confidence, reason
  2. Policy engine: hard rules (in use, prod, age, retention)
  3. Human approval: dry-run, quarantine, audit log
- **Visual:** funnel or three-gate diagram.

### Slide 5: Demo screenshots
- **Headline:** From scan to approved cleanup
- 3 screenshots: filter table with verdict chips, blocked popup, audit log.
- Short caption under each.

### Slide 6: Results
- **Headline:** Measured, not just demoed
- Metrics: resources scanned, agreement with labeled set, blocked-by-policy count, projected monthly savings.
- Include the prompt-injection test result as one line.
- **Visual:** two or three big numbers.

### Slide 7: What's next
- **Headline:** Roadmap
- GCP and Azure providers
- Scheduled scans and weekly savings report
- Slack approvals
- Terraform state cross-check
- **Closing line:** repo link and contact.

### Speaker notes (one line each)
1. Introduce yourself and the one-sentence pitch.
2. Make the problem concrete with a real example.
3. Walk the diagram left to right, no more than 30 seconds.
4. Stress that safety is deterministic, not prompt-based.
5. Narrate what the audience is seeing, don't read the slide.
6. Be honest about limits: small test set, seeded data.
7. End with the repo and one clear ask.

### Design notes
- One idea per slide, large type, minimal text.
- Dark theme to match the dashboard.
- Reuse the same icon set as the UI so the deck and demo feel like one product.
