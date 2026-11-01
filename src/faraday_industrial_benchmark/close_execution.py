"""Stateful cross-entity close with partial commits and recoverable exceptions."""

from copy import deepcopy


def build_close_execution(contract, bridge):
    stages = []
    expected = {}
    transfers = {r["transfer_id"]: r for r in contract["transfers"] if r["status"] == "active"}
    for row in bridge["transfers"]:
        tid = row["transfer_id"]
        transfer = transfers[tid]
        previous = []
        for role, entity in (
            ("sender", transfer["sender"]),
            ("receiver", transfer["receiver"]),
            ("elimination", "CONSOL"),
        ):
            stage_id = f"{tid}:{role}"
            stages.append(
                {
                    "stage_id": stage_id,
                    "transfer_id": tid,
                    "role": role,
                    "entity": entity,
                    "prerequisites": list(previous),
                }
            )
            expected[stage_id] = [
                deepcopy(line)
                for line in bridge["journal_lines"]
                if line["transfer_id"] == tid and line["entity"] == entity
            ]
            previous.append(stage_id)
    held = next(r for r in bridge["transfers"] if r["in_transit_quantity"] > 0)
    hold_stage = f"{held['transfer_id']}:receiver"
    return {
        "stages": stages,
        "expected": expected,
        "postings": {},
        "keys": {},
        "hold_stage": hold_stage,
        "hold_released": False,
        "hold_answer": {
            "received_quantity": held["received_quantity"],
            "in_transit_quantity": held["in_transit_quantity"],
            "disposition": "retain_unreceived_in_transit",
        },
        "ack_loss_stage": f"{held['transfer_id']}:sender",
        "ack_lost": False,
        "reconciled": False,
    }


def public_status(state):
    posted = state["postings"]
    hold_visible = state["hold_stage"].replace(":receiver", ":sender") in posted
    return {
        "stages": deepcopy(state["stages"]),
        "postings": deepcopy(posted),
        "reconciled": state["reconciled"],
        "receiver_exception": {
            "stage_id": state["hold_stage"],
            "status": "released" if state["hold_released"] else "blocked",
            "reason": "Receiver requested full receipt, but authoritative receipt evidence may be partial. Reconcile physical versus logical receipt events; preserve unreceived inventory in transit.",
        }
        if hold_visible
        else None,
    }


def apply_close_step(state, action, payload):
    """Atomic business validation. Acknowledgement loss is handled after commit."""
    if action == "release_close_hold":
        sender = state["hold_stage"].replace(":receiver", ":sender")
        if sender not in state["postings"]:
            return False, "sender_posting_required_before_receiver_investigation"
        if payload != state["hold_answer"]:
            return False, "receiver_receipt_reconciliation_incorrect"
        state["hold_released"] = True
        return True, "ok"
    if action == "reconcile_close_ledger":
        if len(state["postings"]) != len(state["stages"]):
            return False, "cross_entity_postings_incomplete"
        receipts = sorted(r["receipt_id"] for r in state["postings"].values())
        if payload != {"posting_receipts": receipts}:
            return False, "posting_receipt_reconciliation_required"
        state["reconciled"] = True
        return True, "ok"
    stage_id = payload.get("stage_id")
    stage = next((r for r in state["stages"] if r["stage_id"] == stage_id), None)
    key = payload.get("idempotency_key")
    if not stage or not isinstance(key, str) or not key.strip():
        return False, "stage_and_idempotency_key_required"
    if set(payload) != {"stage_id", "idempotency_key", "journal_lines"}:
        return False, "posting_payload_fields_invalid"
    if key in state["keys"]:
        return (
            (True, "ok") if state["keys"][key] == payload else (False, "idempotency_key_conflict")
        )
    if stage_id in state["postings"]:
        return False, "stage_already_posted_use_original_key"
    if any(prereq not in state["postings"] for prereq in stage["prerequisites"]):
        return False, "posting_prerequisites_incomplete"
    if stage_id == state["hold_stage"] and not state["hold_released"]:
        return False, "receiver_receipt_exception_requires_resolution"
    if payload["journal_lines"] != state["expected"][stage_id]:
        return False, "journal_business_values_incorrect"
    state["postings"][stage_id] = {
        "receipt_id": f"POST-{len(state['postings']) + 1:03d}",
        "idempotency_key": key,
        "journal_lines": deepcopy(payload["journal_lines"]),
    }
    state["keys"][key] = deepcopy(payload)
    return True, "ok"


PUBLIC_RULES = (
    "Execute the cross-entity close before publishing. get_incident.close_execution is the live posting ledger. "
    "Each stage requires request_approval then execute_action, targeting the case ID. "
    "Action post_close_stage payload: stage_id, unique idempotency_key, journal_lines derived from the intercompany bridge "
    "for that transfer/entity, preserving line order. Sender precedes receiver; both precede elimination. "
    "A receiver exception can appear after sender posting: release_close_hold requires received_quantity, "
    "in_transit_quantity and disposition=retain_unreceived_in_transit, derived from receipt evidence, not the receiver request. "
    "A posting acknowledgement may be lost AFTER commit. Never infer rollback from a failed response. Inspect get_incident; "
    "if retrying request fresh approval with the EXACT same payload/idempotency key. A changed key cannot repost a stage. "
    "After all stages, reconcile_close_ledger requires posting_receipts: sorted receipt IDs from the live ledger. "
    "Only then request approval to publish the four reconciled artifacts. All actions use existing approval and execution tools."
)


def run_reference_close(tools, case_id, bridge):
    """Use only public stage metadata, the computed bridge and live receipts."""

    def execute(action, payload):
        approval = tools.call(
            "request_approval",
            action=action,
            target=case_id,
            reason="Execute the evidence-reconciled cross-entity close step.",
            payload=payload,
        )
        assert approval["ok"]
        return tools.call(
            "execute_action", action=action, target=case_id, approval_id=approval["approval"]["id"]
        )

    status = tools.call("get_incident")["incident"]["close_execution"]
    for stage in status["stages"]:
        status = tools.call("get_incident")["incident"]["close_execution"]
        exception = status["receiver_exception"]
        if (
            exception
            and exception["stage_id"] == stage["stage_id"]
            and exception["status"] == "blocked"
        ):
            row = next(r for r in bridge["transfers"] if r["transfer_id"] == stage["transfer_id"])
            assert execute(
                "release_close_hold",
                {
                    "received_quantity": row["received_quantity"],
                    "in_transit_quantity": row["in_transit_quantity"],
                    "disposition": "retain_unreceived_in_transit",
                },
            )["ok"]
        payload = {
            "stage_id": stage["stage_id"],
            "idempotency_key": f"close:{stage['stage_id']}",
            "journal_lines": [
                r
                for r in bridge["journal_lines"]
                if r["transfer_id"] == stage["transfer_id"] and r["entity"] == stage["entity"]
            ],
        }
        result = execute("post_close_stage", payload)
        if not result["ok"]:
            assert result["error"] == "acknowledgement_lost"
            live = tools.call("get_incident")["incident"]["close_execution"]
            assert (
                live["postings"][stage["stage_id"]]["idempotency_key"] == payload["idempotency_key"]
            )
    live = tools.call("get_incident")["incident"]["close_execution"]
    assert execute(
        "reconcile_close_ledger",
        {"posting_receipts": sorted(r["receipt_id"] for r in live["postings"].values())},
    )["ok"]
