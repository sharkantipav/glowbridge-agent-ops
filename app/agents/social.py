"""Social agent — daily content generator.

Per the brief, generates per day:
  - 2 X (Twitter) posts
  - 1 TikTok / Reels script
  - 1 Instagram caption
  - 1 Reddit research question

Auto-post rules (enforced in code):
  - X: only "educational" posts pass the gate (no claims, no fabrication).
       Even those are only posted if ENABLE_SOCIAL_AUTOPOST=true.
  - Reddit: NEVER auto-post. Always queued for Charles.
  - TikTok / Reels / Instagram: never auto-post (queued, owner decides).
"""
from __future__ import annotations

from app import db, llm, safety
from app.agents.base import run_context
from app.config import get_settings

GENERATE_SYSTEM = """\
You generate one day of educational social content for GlowBridge — an AI
receptionist for pest control companies (small / family-run / independent).

Audience: pest-control owners, technicians, and adjacent home-service operators.
Tone: practical, peer-to-peer, no corporate fluff, no emoji-spam, no hashtags.

Hard constraints — every piece you produce must obey:
- NEVER claim guaranteed bookings, revenue, or outcomes.
- NEVER fabricate customers, case studies, MRR, or specific dollar results.
- NEVER say "AI quotes prices".
- Don't use the word "guaranteed".
- Don't use phrases like "double your bookings", "never miss a call".
- Educational angle = surface a real problem (missed calls, voicemail, after-hours)
  and gesture at how thinking about it differently helps. Don't pitch a product
  in every post; 1 of 4 posts can be a soft mention.

Reply ONLY with JSON of this exact shape:
{
  "x_posts": [
    {"content": string},   // 2 items, each <= 270 chars
    {"content": string}
  ],
  "tiktok_reels": {
    "content": string,     // hook line
    "media_hint": string   // 30-second script outline
  },
  "instagram_caption": {
    "content": string      // <= 220 chars
  },
  "reddit_question": {
    "content": string      // posted to r/pestcontrol or r/smallbusiness;
                           // must be a genuine research question, not a pitch
  }
}
"""


def run() -> dict:
    s = get_settings()
    with run_context("social", {"autopost_enabled": s.enable_social_autopost}) as run:
        try:
            data = llm.json_call(
                system=GENERATE_SYSTEM,
                user="Generate today's content.",
                tier="smart",
                temperature=0.7,
                max_tokens=1200,
            )
        except Exception as e:
            run.error("generation_failed", error=str(e))
            run.output = {"generated": 0}
            return run.output

        generated = 0

        # X posts — both to draft, the eligible ones may auto-post.
        for x in data.get("x_posts") or []:
            content = (x.get("content") or "").strip()
            if not content:
                continue
            gate = safety.social_autopost_gate(platform="x", content=content)
            status = "draft"
            external_post_id = None
            if gate.passed and s.enable_social_autopost:
                try:
                    from app.integrations import buffer

                    channel_ids = buffer.x_channel_ids()
                    if not channel_ids:
                        raise RuntimeError("No active X/Twitter Buffer channel found")
                    posted = buffer.add_text_post_to_queue(channel_id=channel_ids[0], text=content)
                    status = "posted"
                    external_post_id = posted.get("id")
                    run.info("social_buffer_queued", platform="x", post_id=external_post_id)
                except Exception as e:  # noqa: BLE001
                    run.error("social_buffer_post_failed", platform="x", error=str(e))

            row = db.insert(
                "social_posts",
                {
                    "platform": "x",
                    "content": content,
                    "status": status,
                    "auto_eligible": gate.passed,
                    "external_post_id": external_post_id,
                    "posted_at": "now()" if external_post_id else None,
                },
            )
            generated += 1
            if not gate.passed:
                db.insert(
                    "approvals",
                    {
                        "kind": "social",
                        "target_id": row["id"],
                        "payload": {"platform": "x", "content": content},
                        "reason_for_review": ", ".join(gate.failures),
                    },
                )

        # TikTok/Reels — never auto.
        tk = data.get("tiktok_reels") or {}
        if tk.get("content"):
            row = db.insert(
                "social_posts",
                {
                    "platform": "tiktok",
                    "content": tk["content"],
                    "media_hint": tk.get("media_hint"),
                    "status": "draft",
                    "auto_eligible": False,
                },
            )
            db.insert(
                "approvals",
                {
                    "kind": "social",
                    "target_id": row["id"],
                    "payload": {"platform": "tiktok", "content": tk["content"], "media_hint": tk.get("media_hint")},
                    "reason_for_review": "tiktok_never_auto",
                },
            )
            generated += 1

        # Instagram — never auto.
        ig = data.get("instagram_caption") or {}
        if ig.get("content"):
            row = db.insert(
                "social_posts",
                {
                    "platform": "instagram",
                    "content": ig["content"],
                    "status": "draft",
                    "auto_eligible": False,
                },
            )
            db.insert(
                "approvals",
                {
                    "kind": "social",
                    "target_id": row["id"],
                    "payload": {"platform": "instagram", "content": ig["content"]},
                    "reason_for_review": "instagram_never_auto",
                },
            )
            generated += 1

        # Reddit — NEVER auto, per brief.
        rd = data.get("reddit_question") or {}
        if rd.get("content"):
            row = db.insert(
                "social_posts",
                {
                    "platform": "reddit",
                    "content": rd["content"],
                    "status": "draft",
                    "auto_eligible": False,
                },
            )
            db.insert(
                "approvals",
                {
                    "kind": "social",
                    "target_id": row["id"],
                    "payload": {"platform": "reddit", "content": rd["content"]},
                    "reason_for_review": "reddit_never_auto (per spec)",
                },
            )
            generated += 1

        # We do NOT actually call any social API for posting in v1 — even when
        # auto-eligible X posts pass the gate, we leave them as 'draft' until the
        # operator wires up the X API. Going further than this requires a posting
        # token that the user hasn't provided.
        run.output = {"generated": generated, "auto_eligible_x": sum(
            1 for x in data.get("x_posts") or [] if safety.social_autopost_gate(
                platform="x", content=(x.get("content") or "")).passed
        )}
        return run.output
