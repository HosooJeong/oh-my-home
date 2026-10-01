"""Explicit semantic-review stub for existing source/date tests, not a real verifier."""
import json
from app.response_validation import ResponseReview, ClaimDecision


def supported_review(prompt, response_type):
    if response_type is not ResponseReview:return None
    claims=json.loads(prompt.split('검토 JSON:\n')[1])
    return ResponseReview(decisions=[ClaimDecision(claim_id=c['claim_id'],verdict='supported',
        request_ids=[q['request_id'] for q in c['questions']],reason='supported') for c in claims])
