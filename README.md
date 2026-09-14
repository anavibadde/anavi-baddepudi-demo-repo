# Refund review (demo)

A queue for reviewing customer refund requests: an analyst submits one, a reviewer
approves or rejects it, and both see the decision history.

**Nothing is executed.** Approving a request records a decision; no payment provider
is called and no money moves.

## Run it

Two terminals.

```bash
# backend — http://127.0.0.1:8000
cd backend
python3 -m venv .venv && .venv/bin/pip install -r requirements.txt
.venv/bin/python -m app.seed          # drops and reseeds the demo database
.venv/bin/uvicorn app.main:app --reload
```

```bash
# frontend — http://localhost:5173 (proxies /api to the backend)
cd frontend
npm install
npm run dev
```

Pick who you are with the "Viewing as" selector in the header. There is no login:
the browser asserts a user id and the API trusts it, which is the first thing that
would have to go in a real deployment.

## How it works

- **Roles.** Analysts submit. Managers decide on their direct reports' requests.
  Admins see and decide everything.
- **Visibility.** You see your own requests plus your direct reports'. Anything
  outside your line returns 404 rather than 403, so request ids cannot be probed.
- **No self-approval.** The submitter can never decide their own request, whatever
  their role; it goes to their manager.
- **One decision, ever.** The status update is conditional on the request still
  being pending, so if two reviewers click at once the second gets a 409 instead of
  overwriting the first.
- **Risk flags**, computed once at submit time and stored on the request:
  | Flag | Trigger |
  | --- | --- |
  | High value | over $1,000 |
  | Repeat refunds | 2+ approved refunds for the customer in 90 days |
  | Rapid succession | 2+ requests for the customer in 24 hours |
  | Fraud dispute | the stated reason |

  Any flag means the reviewer must tick a confirmation before approving. **High
  value plus any other flag escalates to admin-only approval.** Rejecting never
  needs confirmation.
- **History** is an append-only event log; the status column is a rollup of it.

## Layout

```
backend/app/models.py   tables
backend/app/risk.py     flag heuristics and the escalation rule
backend/app/rules.py    visibility and decision authorization
backend/app/main.py     HTTP layer
backend/app/seed.py     fake org chart and ~54 requests
frontend/src/           queue, detail panel, submit form
```

## Tests and lint

```bash
cd backend  && .venv/bin/python -m pytest && .venv/bin/ruff check app tests
cd frontend && npm run lint && npm run build
```
