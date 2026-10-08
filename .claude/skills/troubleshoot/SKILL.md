---
name: troubleshoot
description: Use when Janitor fails to set up, build, test, start, or scan, or the UI shows an error - after a pull, a new build, or a config change. Runs make doctor, matches the error to known causes, and fixes the root cause without weakening any safety check.
---

# Troubleshoot Janitor

The person asking may not be a developer. Explain each finding in one plain sentence (what broke,
then what you will do), and show the command you ran.

## Step 1: Run the checker first

```bash
make doctor
```

It checks Python, Node, packages, git hooks, the config, AWS profiles, and ports, and prints a fix
for each FAIL. Fix the first FAIL, then run it again. If it says the machine is ready, go to step 2.

## Step 2: Find the stage that fails, and reproduce it in the smallest command

| Stage | Smallest command that shows the real error |
|-------|--------------------------------------------|
| Setup | `make setup` |
| UI build | `cd frontend && npm run build` (type errors print as `file:line`) |
| Backend tests | `.venv/bin/python -m pytest backend -q -x` (stops at the first failure) |
| UI tests | `cd frontend && npx vitest run` |
| Start | `make run` and read the terminal; the traceback's last line names the cause |
| Scan | The Overview page's scan health, or `curl -s http://127.0.0.1:8080/api/scans/latest` |
| UI error toast | The terminal running the backend has the traceback for any 500 |

## Step 3: Match the message

| Message (or part of it) | Cause | Fix |
|-------------------------|-------|-----|
| `uv: command not found` | uv isn't installed | Install uv (docs.astral.sh/uv), then `make setup` |
| `CERTIFICATE_VERIFY_FAILED`, `unable to get local issuer certificate` | A TLS-inspecting proxy | Python downloads: `make prices`/`make icons`/`make run-aws` already trust the macOS keychain. uv: `UV_NATIVE_TLS=1 make setup`. npm: `NODE_EXTRA_CA_CERTS=<your org CA bundle> npm install`. **Never turn verification off.** |
| `Vite requires Node.js version` | Node older than 22.12 | Install Node 22.12+, then `cd frontend && npm install` |
| `Cannot find module` / `Failed to resolve import` | Packages changed in a pull | `cd frontend && npm install` |
| `ModuleNotFoundError: No module named` | A backend dependency was added | `make setup` |
| `12-digit number that isn't a fake account ID` / `contains a term from .private-terms` | The leak check found a real-looking ID or private name | Replace it with a fake ID (`111111111111`-style). **Never** commit with `--no-verify`. |
| `has no 'successfully', 'please', or exclamation marks` | UI copy rule (`copy.test.ts`) | Reword: sentence case, what happened then what to do |
| `No config at ... and no example` | Both config files are missing | `git checkout config/janitor.example.yaml` |
| `is listed twice in janitor.yaml (line N)` / `appears twice in one section` | Duplicate entry | Merge the two entries at that line |
| `uses the old layout` | Pre-phase-3 config | Rewrite with `admin`, `member_role`, `accounts` (see `config/janitor.example.yaml`) |
| `must be 12 digits` / `isn't a valid IAM role name` / `isn't a valid regular expression` / `needs a value` / `is both listed and ignored` | A config value is wrong | Fix the value the message names in `config/janitor.yaml` |
| `admin profile ... isn't in your AWS config` / `needs role_arn and source_profile` / `member_role isn't set` / `assumes a role in another account` / `uses a different source login` | AWS profile setup (checked at `make run-aws` start) | Fix `~/.aws/config` as the message says; README "Run it against AWS" |
| `Address already in use` | Another server holds port 8080 or 5173 | `lsof -iTCP:8080 -sTCP:LISTEN`, then stop that process |
| `The UI isn't built. Run make build, or use make dev.` | `frontend/dist` is missing | `make build`, or use `make dev` and open :5173 |
| `AWS session expired. Refresh your MFA session` | MFA credentials expired | Refresh the MFA session as usual, then Scan now |
| `can't assume the admin role from profile` | The admin role's trust policy or the MFA session | Check the role's trust policy and MFA session |
| `can't assume <role> in <account>` | The role is missing in that account or doesn't trust the source login | Ask that account's owner; until then its shared AMIs stay Unknown |
| `isn't allowed to call <service:Operation>` | The role lacks that Describe permission | Ask for read access to that operation |
| `AWS throttled requests` | Rate limit | Wait a few minutes, scan again; or lower `scan.concurrency` |
| `Janitor stopped a call that isn't read-only` | **A code bug**: something called a non-read AWS operation | Find the call in `providers/aws.py` and remove it. **Never** widen `guard.py` or the session policy in `session.py`. |
| Many resources show **Unknown** | Some checks failed (a partial scan) | The scan health panel names each failed check; fix those |
| `The data changed since this plan was made` / `settings changed since this plan was made` | A scan or config edit happened after the plan | Plan the delete again (expected, not a bug) |

## Step 4: Not in the table

1. Read the full traceback; the last line is the error and the lines above show where it happened.
2. Find the file in `docs/GUIDE.md` ("Where do I change...").
3. Find the root cause before changing anything. Don't patch the symptom or retry until it passes.
4. Add a test that fails without the fix (`backend/tests/test_<module>.py`, or `*.test.ts(x)` beside the UI file).
5. If the message the user saw didn't say what to do, improve it too. Messages say what
   happened, then what to do.

## Rules while fixing

- **Never** weaken a safety check to make an error go away: the guard, the session policy, TLS
  verification, the leak check, or the pre-commit hook.
- **Never** copy values from `config/janitor.yaml` or `~/.aws/config` into tracked files, issues,
  or commit messages. The repo is public.
- `data/janitor.db` holds scans and the audit log. Old scan data upgrades itself (`SCHEMA_VERSION` in
  `store.py`). Moving the file aside is a last resort that loses the audit log: ask first.
- Finish with `make test` and show its result.
