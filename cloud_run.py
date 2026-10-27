"""
One automation pass, run every 20 minutes by GitHub Actions (.github/workflows/automate.yml):

  1. post the next due product from the post queue (and queue its pin)
  2. pin the next due pin
  3. run the daily price update when it is due

State (queues, published.json, price_state.json) comes from the `state` branch via
state_sync.py, so the laptop can be off. Run locally with CLOUD_SYNC=true to test.
"""
import sys

import auto_update as au
import pinterest as pn
import post_queue as pq
import publish as pw
import state_sync as sync


def main() -> int:
    if not pw.CLOUD_SYNC:
        print("CLOUD_SYNC is not on; nothing to do.")
        return 1
    token = pw.ROOT / "token.json"
    if not (pw.APP_KEY and pw.APP_SECRET and token.exists() and token.stat().st_size):
        print("Secrets are not set up yet (see SETUP-GUIDE.md, Cloud). Skipping.")
        return 0
    sync.pull()
    svc = pw.blogger_service()
    failed = False

    try:
        before = {x["product"]["product_id"]: x["status"] for x in pq.load()}
        pq.run_due(svc, pq.pin_after_post)
        after = [x for x in pq.load() if before.get(x["product"]["product_id"]) == "queued" and x["status"] != "queued"]
        for x in after:
            print(f"post: {x['status']} {x.get('url') or x.get('error', '')} | {x.get('title') or x['product'].get('product_title', '')[:60]}")
        if not after:
            q = pq.load()
            print(f"post: nothing due ({sum(1 for x in q if x['status'] == 'queued')} queued, "
                  f"{pq.posted_last_day(q)}/{pq.DAILY_LIMIT} in 24 h)")
    except Exception as e:
        print("post queue error:", e)
        failed = True

    if pn.connected():
        try:
            pn.run_due()
        except Exception as e:
            print("pin queue error:", e)

    if au.due():
        try:
            print("price update:", au.run(svc))
        except Exception as e:
            print("price update error:", e)
            failed = True
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
