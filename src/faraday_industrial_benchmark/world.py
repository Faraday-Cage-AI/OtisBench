"""Deterministic, time-aware synthetic industrial enterprise and typed tool surface."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Callable
from copy import deepcopy
from dataclasses import asdict
from typing import Any

from .artifact_contract import canonical_exclusions, matches_contract, schema_errors
from .models import (
    PUBLIC_NOTIFICATION_ROLES,
    IncidentTask,
    Json,
    ScheduledEvent,
    ToolCallRecord,
)
from .scenarios import ScenarioInstance, build_scenario
from .tool_specs import TOOL_NAMES, tool_specs_for_family

READ_LATENCY_MINUTES = 1
WRITE_LATENCY_MINUTES = 2


def canonical_hash(value: Any) -> str:
    payload = json.dumps(value, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


class IndustrialWorld:
    """An isolated benchmark episode.

    Tool calls advance the logical clock. Scheduled external events are applied
    deterministically when their timestamps are reached. Agents never receive
    the evaluator criteria or economic contract.
    """

    def __init__(self, task: IncidentTask, instance: ScenarioInstance | None = None):
        self.task = task
        self.instance = instance or build_scenario(task)
        self.state: Json = deepcopy(self.instance.state)
        self.criteria = deepcopy(self.instance.criteria)
        self.economics = deepcopy(self.instance.economics)
        self.pending_events: list[ScheduledEvent] = sorted(
            deepcopy(self.instance.events), key=lambda item: (item.at_minute, item.id)
        )
        self.applied_events: list[str] = []
        self.applied_event_kinds: list[str] = []
        self.trace: list[ToolCallRecord] = []
        self.finished = False
        self.final_answer: Json = {}
        self.initial_state_hash = canonical_hash(self._hashable_state())
        self._ids: dict[str, int] = {}

    @property
    def minute(self) -> int:
        return int(self.state["clock_minute"])

    @property
    def state_hash(self) -> str:
        return canonical_hash(self._hashable_state())

    def _hashable_state(self) -> Json:
        return {
            "state": self.state,
            "pending_events": [asdict(event) for event in self.pending_events],
            "applied_events": self.applied_events,
            "finished": self.finished,
            "final_answer": self.final_answer,
        }

    def _next_id(self, prefix: str) -> str:
        self._ids[prefix] = self._ids.get(prefix, 0) + 1
        return f"{prefix}-{self._ids[prefix]:03d}"

    def _audit(self, audit_type: str, **details: Any) -> None:
        self.state["audit_log"].append(
            {"minute": self.minute, "action": audit_type, "details": deepcopy(details)}
        )

    def _violation(self, code: str, message: str, *, critical: bool) -> None:
        record = {
            "minute": self.minute,
            "code": code,
            "message": message,
            "severity": "critical" if critical else "warning",
        }
        self.state["violations"].append(record)
        self._audit("violation", **record)

    def schedule_event(self, event: ScheduledEvent) -> None:
        self.pending_events.append(event)
        self.pending_events.sort(key=lambda item: (item.at_minute, item.id))

    def advance(self, minutes: int) -> None:
        if minutes < 0:
            raise ValueError("minutes must be non-negative")
        target = min(self.minute + minutes, self.task.horizon_minutes)
        while self.pending_events and self.pending_events[0].at_minute <= target:
            event = self.pending_events.pop(0)
            self.state["clock_minute"] = event.at_minute
            self._apply_event(event)
        self.state["clock_minute"] = target
        if target >= self.task.horizon_minutes and not self.finished:
            self._violation(
                "horizon_exceeded",
                f"episode reached the {self.task.horizon_minutes}-minute horizon",
                critical=False,
            )
            self.finished = True

    def _apply_event(self, event: ScheduledEvent) -> None:
        payload = deepcopy(event.payload)
        kind = event.kind
        if kind == "quality_result":
            for lot_id in payload["lot_ids"]:
                if lot_id in self.state["lots"]:
                    self.state["lots"][lot_id]["quality_status"] = payload["status"]
                for record in self.state["quality_records"]:
                    if record["lot_id"] == lot_id:
                        record.update(status=payload["status"], result=payload["result"])
        elif kind == "message":
            self.state["messages"].append(
                {
                    "id": event.id,
                    "minute": event.at_minute,
                    "sender": payload["sender"],
                    "subject": payload["subject"],
                    "body": payload["body"],
                }
            )
        elif kind == "supplier_update":
            po = self.state["purchase_orders"].get(payload["po_id"])
            if po:
                po.update(due_minute=payload["due_minute"], status=payload["status"])
            self.state["messages"].append(
                {
                    "id": event.id,
                    "minute": event.at_minute,
                    "sender": "supplier",
                    "subject": "Confirmed delivery update",
                    "body": payload["message"],
                }
            )
        elif kind == "alternate_capacity_lost":
            supplier = self.state["suppliers"].get(payload["supplier_id"])
            if supplier:
                supplier["expedite_available"] = False
        elif kind == "technician_message":
            machine = self.state["machines"].get(payload["machine_id"])
            if machine:
                machine["technician_finding"] = payload["finding"]
                machine["estimated_repair_minutes"] = payload["repair_minutes"]
            for order in self.state["maintenance_orders"].values():
                if order["machine_id"] == payload["machine_id"]:
                    order["status"] = "diagnosed"
                    order["finding"] = payload["finding"]
            self.state["messages"].append(
                {
                    "id": event.id,
                    "minute": event.at_minute,
                    "sender": "maintenance_technician",
                    "subject": "Initial diagnosis",
                    "body": payload["finding"],
                }
            )
        elif kind == "customer_window_closed":
            order = self.state["orders"].get(payload["order_id"])
            if order and order["status"] == "pending_commitment":
                order["status"] = "commitment_window_expired"
        elif kind == "engineering_change_effective":
            bom = self.state["boms"].get(payload["sku"])
            if bom:
                bom["current_revision"] = payload["revision"]
                bom["pending_revision"] = None
                bom["effective"] = True
        elif kind == "approval_decision":
            approval = self.state["approvals"].get(payload["approval_id"])
            if approval and approval["status"] == "pending":
                approval["status"] = payload["status"]
                approval["decided_minute"] = event.at_minute
        elif kind == "cycle_count_result":
            count = self.state["cycle_counts"].get(payload["count_id"])
            if count:
                count.update(status="complete", quantity=payload["quantity"], completed_minute=event.at_minute)
                self.state["inventory"].append(
                    {
                        "source": "physical_count",
                        "sku": count["sku"],
                        "lot_id": None,
                        "location": count["location"],
                        "quantity": payload["quantity"],
                        "as_of_minute": event.at_minute,
                    }
                )
        elif kind == "goods_receipt_posted":
            receipt = {
                "id": payload["receipt_id"],
                "po_id": payload["po_id"],
                "quantity": payload["quantity"],
                "amount": payload["amount"],
                "status": "posted",
                "posted_minute": event.at_minute,
            }
            self.state["receipts"][receipt["id"]] = receipt
            invoice = self.state["invoices"].get(payload["invoice_id"])
            if invoice:
                invoice["match_status"] = "matched" if invoice["amount"] == receipt["amount"] else "variance"
        elif kind == "customer_payment_posted":
            payment = {
                "id": payload["payment_id"],
                "customer_id": payload["customer_id"],
                "amount": payload["amount"],
                "status": "applied",
                "posted_minute": event.at_minute,
            }
            self.state["payments"][payment["id"]] = payment
            customer = self.state["customers"].get(payload["customer_id"])
            if customer:
                customer["open_receivables"] = max(
                    0, float(customer["open_receivables"]) - float(payload["amount"])
                )
                customer["credit_exposure"] = max(
                    0, float(customer["credit_exposure"]) - float(payload["amount"])
                )
        elif kind == "vendor_callback_verified":
            change = self.state["vendor_change_requests"].get(payload["change_id"])
            if change:
                change.update(
                    verification_status=payload["status"],
                    verification_note=payload["note"],
                    verified_minute=event.at_minute,
                )
        elif kind == "manager_timecard_confirmed":
            timecard = self.state["timecards"].get(payload["employee_id"])
            if timecard:
                timecard.update(
                    manager_confirmed=True,
                    verified_hours=payload["verified_hours"],
                    confirmation_note=payload["note"],
                )
        elif kind == "subledger_posted":
            entry = {
                "id": payload["entry_id"],
                "period": payload["period"],
                "account": payload["account"],
                "offset_account": payload["offset_account"],
                "amount": payload["amount"],
                "source": payload["source"],
                "status": "posted",
            }
            self.state["subledger_entries"][entry["id"]] = entry
            close = self.state["close_status"].get(payload["period"])
            if close:
                close["subledger_complete"] = True
        elif kind == "asset_commissioned":
            asset = self.state["assets"].get(payload["asset_id"])
            if asset:
                asset.update(
                    commissioned=True,
                    commissioning_certificate=payload["certificate_id"],
                    in_service_minute=event.at_minute,
                )
        elif kind == "carrier_disruption_confirmed":
            shipment = self.state["shipments"].get(payload["shipment_id"])
            if shipment:
                shipment.update(status="route_blocked", disruption=payload["reason"])
            option = self.state["route_options"].get(payload["blocked_route_id"])
            if option:
                option.update(available=False, status="blocked")
        elif kind == "carrier_quote_received":
            option = self.state["route_options"].get(payload["route_id"])
            if option:
                option.update(
                    status="quoted",
                    available=True,
                    cost=payload["cost"],
                    arrival_minute=payload["arrival_minute"],
                    capacity_confirmed=payload["capacity_confirmed"],
                )
        elif kind == "outbound_truck_update":
            warehouse = self.state["warehouses"].get(payload["warehouse_id"])
            if warehouse:
                warehouse.update(
                    truck_arrival_minute=payload["truck_arrival_minute"],
                    dispatch_cutoff_minute=payload["dispatch_cutoff_minute"],
                    carrier_status="confirmed",
                )
        elif kind == "production_completion_confirmed":
            work_order = self.state["work_orders"].get(payload["work_order_id"])
            order = self.state["orders"].get(payload["order_id"])
            completed = bool(
                work_order
                and order
                and work_order.get("status") == "rescheduled"
                and work_order.get("machine_id") == payload["machine_id"]
            )
            if completed:
                work_order.update(
                    status="completed",
                    quantity_remaining=0,
                    completed_minute=event.at_minute,
                )
                order["status"] = "ready_for_fulfillment"
                for row in self.state["distribution_inventory"]:
                    if (
                        row.get("dc_id") == payload["warehouse_id"]
                        and row.get("sku") == payload["sku"]
                    ):
                        row.update(
                            on_hand=payload["quantity"],
                            available=payload["quantity"],
                            verification_status="verified",
                            as_of_minute=event.at_minute,
                        )
                warehouse = self.state["warehouses"].get(payload["warehouse_id"])
                if warehouse:
                    warehouse["wave_status"] = "ready_after_production"
            else:
                if work_order:
                    work_order["completion_event_status"] = (
                        "missed_unresolved_recovery_window"
                    )
                if order:
                    order["status"] = "recovery_window_missed"
        elif kind == "dc_inventory_verified":
            for row in self.state["distribution_inventory"]:
                if row["dc_id"] == payload["dc_id"] and row["sku"] == payload["sku"]:
                    row.update(
                        on_hand=payload["on_hand"],
                        available=payload["available"],
                        verification_status="verified",
                        as_of_minute=event.at_minute,
                    )
        elif kind == "cold_chain_lab_result":
            shipment = self.state["shipments"].get(payload["shipment_id"])
            if shipment:
                shipment.update(
                    lab_status=payload["status"],
                    lab_result=payload["result"],
                )
        elif kind == "trade_screening_result":
            shipment = self.state["shipments"].get(payload["shipment_id"])
            if shipment:
                shipment["screening_status"] = payload["status"]
                shipment["screening_reference"] = payload["reference"]
        elif kind == "demand_signal_confirmed":
            signal = self.state["demand_signals"].get(payload["signal_id"])
            if signal:
                signal.update(status="confirmed", quantity=payload["quantity"])
            forecast = self.state["forecasts"].get(payload["sku"])
            if forecast:
                forecast["confirmed_demand"] = payload["quantity"]
        elif kind == "engineering_source_update":
            document = self.state["engineering_documents"].get(payload["document_id"])
            if document:
                document.update(
                    revision=payload["revision"],
                    status="authoritative",
                    facts=deepcopy(payload["facts"]),
                )
            self.state["messages"].append(
                {
                    "id": event.id,
                    "minute": event.at_minute,
                    "sender": payload["sender"],
                    "subject": "Authoritative engineering source updated",
                    "body": payload["message"],
                }
            )
        elif kind == "case_file_update":
            case_file = self.state["case_files"].get(payload["file_id"])
            if not case_file:
                raise ValueError(f"case file not found for event: {payload['file_id']}")
            case_file.update(
                version=payload["version"],
                status=payload["status"],
                sections=deepcopy(payload["sections"]),
            )
            self.state["messages"].append(
                {
                    "id": event.id,
                    "minute": event.at_minute,
                    "sender": payload["sender"],
                    "subject": f"Authoritative source revision: {case_file['title']}",
                    "body": payload["message"],
                }
            )
        else:
            raise ValueError(f"unsupported event kind: {kind}")
        self.applied_events.append(event.id)
        self.applied_event_kinds.append(kind)
        self._audit("event_applied", event_id=event.id, kind=kind)

    def call_tool(self, name: str, arguments: Json) -> Json:
        if self.finished and name != "finish":
            return {"ok": False, "error": "episode_finished", "clock_minute": self.minute}
        if name not in TOOL_NAMES:
            self._violation("unknown_tool", f"unknown tool: {name}", critical=False)
            result = {"ok": False, "error": "unknown_tool"}
            return self._record(name, arguments, result)

        handler: Callable[..., Json] = getattr(self, f"_tool_{name}")
        try:
            result = handler(**deepcopy(arguments))
        except TypeError as exc:
            result = {"ok": False, "error": "invalid_arguments", "detail": str(exc)}
        except (KeyError, ValueError) as exc:
            result = {"ok": False, "error": "invalid_request", "detail": str(exc)}

        if name == "wait":
            pass
        elif name != "finish":
            latency = READ_LATENCY_MINUTES if name.startswith(("get_", "list_", "query_", "trace_", "read_")) else WRITE_LATENCY_MINUTES
            self.advance(latency)
        if name == "request_approval" and result.get("ok"):
            approval_id = result.get("approval", {}).get("id")
            if approval_id in self.state["approvals"]:
                result["approval"] = deepcopy(self.state["approvals"][approval_id])
        result["clock_minute"] = self.minute
        return self._record(name, arguments, result)

    def _record(self, name: str, arguments: Json, result: Json) -> Json:
        snapshot = deepcopy(result)
        record = ToolCallRecord(
            index=len(self.trace),
            minute=self.minute,
            tool=name,
            arguments=deepcopy(arguments),
            result=snapshot,
            state_hash=self.state_hash,
        )
        self.trace.append(record)
        return snapshot

    # Read tools ---------------------------------------------------------

    def _tool_get_incident(self) -> Json:
        result = {"ok": True, "incident": deepcopy(self.state["incident"])}
        if "close_execution" in self.state:
            from .close_execution import public_status

            result["incident"]["close_execution"] = public_status(self.state["close_execution"])
        return result

    def _tool_get_sensor_readings(self, machine_id: str) -> Json:
        readings = self.state["sensors"].get(machine_id)
        if readings is None:
            return {"ok": False, "error": "machine_not_found"}
        return {"ok": True, "machine_id": machine_id, "readings": deepcopy(readings)}

    def _tool_get_machine(self, machine_id: str) -> Json:
        machine = self.state["machines"].get(machine_id)
        return {"ok": bool(machine), "machine": deepcopy(machine)}

    def _tool_query_inventory(self, sku: str, lot_id: str | None = None) -> Json:
        records = [
            row
            for row in self.state["inventory"]
            if row["sku"] == sku and (lot_id is None or row.get("lot_id") == lot_id)
        ]
        return {"ok": True, "sku": sku, "records": deepcopy(records)}

    def _tool_trace_lot(self, lot_id: str) -> Json:
        lot = self.state["lots"].get(lot_id)
        if not lot:
            return {"ok": False, "error": "lot_not_found"}
        related = [
            value
            for value in self.state["lots"].values()
            if value.get("parent_batch") == lot.get("parent_batch")
        ]
        shipments = [
            order
            for order in self.state["orders"].values()
            if lot_id in order.get("allocated_lots", [])
            or any(item["id"] in order.get("allocated_lots", []) for item in related)
        ]
        return {
            "ok": True,
            "lot": deepcopy(lot),
            "related_lots": deepcopy(related),
            "linked_orders": deepcopy(shipments),
        }

    def _tool_get_quality_status(self, lot_id: str | None = None) -> Json:
        records = [
            row for row in self.state["quality_records"] if lot_id is None or row["lot_id"] == lot_id
        ]
        holds = [
            row for row in self.state["quality_holds"].values() if lot_id is None or row["lot_id"] == lot_id
        ]
        return {"ok": True, "records": deepcopy(records), "holds": deepcopy(holds)}

    def _tool_get_order(self, order_id: str) -> Json:
        order = self.state["orders"].get(order_id)
        return {"ok": bool(order), "order": deepcopy(order)}

    def _tool_list_orders(self, sku: str | None = None) -> Json:
        rows = [
            row
            for row in self.state["orders"].values()
            if sku is None or row.get("sku") == sku or row.get("component_sku") == sku
        ]
        return {"ok": True, "orders": deepcopy(rows)}

    def _tool_get_purchase_order(self, po_id: str) -> Json:
        po = self.state["purchase_orders"].get(po_id)
        return {"ok": bool(po), "purchase_order": deepcopy(po)}

    def _tool_get_supplier(self, supplier_id: str) -> Json:
        supplier = self.state["suppliers"].get(supplier_id)
        return {"ok": bool(supplier), "supplier": deepcopy(supplier)}

    def _tool_get_invoice(self, invoice_id: str) -> Json:
        invoice = self.state["invoices"].get(invoice_id)
        holds = [row for row in self.state["invoice_holds"].values() if row["invoice_id"] == invoice_id]
        return {"ok": bool(invoice), "invoice": deepcopy(invoice), "holds": deepcopy(holds)}

    def _tool_get_receipt(self, receipt_id: str) -> Json:
        receipt = self.state["receipts"].get(receipt_id)
        return {"ok": bool(receipt), "receipt": deepcopy(receipt)}

    def _tool_get_customer_account(self, customer_id: str) -> Json:
        customer = self.state["customers"].get(customer_id)
        payments = [row for row in self.state["payments"].values() if row["customer_id"] == customer_id]
        return {"ok": bool(customer), "customer": deepcopy(customer), "payments": deepcopy(payments)}

    def _tool_get_vendor(self, vendor_id: str) -> Json:
        vendor = self.state["vendors"].get(vendor_id)
        holds = [row for row in self.state["payment_holds"].values() if row["vendor_id"] == vendor_id]
        return {"ok": bool(vendor), "vendor": deepcopy(vendor), "payment_holds": deepcopy(holds)}

    def _tool_get_vendor_change_request(self, change_id: str) -> Json:
        change = self.state["vendor_change_requests"].get(change_id)
        return {"ok": bool(change), "change_request": deepcopy(change)}

    def _tool_get_employee_payroll(self, employee_id: str) -> Json:
        employee = self.state["employees"].get(employee_id)
        if not employee:
            return {"ok": False, "error": "employee_not_found"}
        permitted = {key: employee[key] for key in ("id", "status", "pay_rate", "pay_group")}
        payroll = self.state["payroll_runs"].get(employee_id)
        return {"ok": True, "employee": permitted, "payroll": deepcopy(payroll)}

    def _tool_get_timecard(self, employee_id: str) -> Json:
        timecard = self.state["timecards"].get(employee_id)
        return {"ok": bool(timecard), "timecard": deepcopy(timecard)}

    def _tool_get_close_status(self, period: str) -> Json:
        close = self.state["close_status"].get(period)
        return {
            "ok": bool(close),
            "close_status": deepcopy(close),
            "gl_accounts": deepcopy(self.state["gl_accounts"]),
        }

    def _tool_get_subledger_entries(self, period: str, account: str | None = None) -> Json:
        rows = [
            row
            for row in self.state["subledger_entries"].values()
            if row["period"] == period and (account is None or row["account"] == account)
        ]
        return {"ok": True, "entries": deepcopy(rows)}

    def _tool_get_project(self, project_id: str) -> Json:
        project = self.state["projects"].get(project_id)
        return {"ok": bool(project), "project": deepcopy(project)}

    def _tool_get_asset(self, asset_id: str) -> Json:
        asset = self.state["assets"].get(asset_id)
        return {"ok": bool(asset), "asset": deepcopy(asset)}

    def _tool_get_shipment(self, shipment_id: str) -> Json:
        shipment = self.state["shipments"].get(shipment_id)
        holds = [row for row in self.state["shipment_holds"].values() if row["shipment_id"] == shipment_id]
        return {"ok": bool(shipment), "shipment": deepcopy(shipment), "holds": deepcopy(holds)}

    def _tool_get_route_options(self, shipment_id: str) -> Json:
        rows = [row for row in self.state["route_options"].values() if row["shipment_id"] == shipment_id]
        return {"ok": bool(rows), "routes": deepcopy(rows)}

    def _tool_get_warehouse_status(self, warehouse_id: str) -> Json:
        warehouse = self.state["warehouses"].get(warehouse_id)
        return {"ok": bool(warehouse), "warehouse": deepcopy(warehouse)}

    def _tool_get_distribution_inventory(self, sku: str, dc_id: str | None = None) -> Json:
        rows = [
            row for row in self.state["distribution_inventory"]
            if row["sku"] == sku and (dc_id is None or row["dc_id"] == dc_id)
        ]
        return {"ok": True, "sku": sku, "records": deepcopy(rows)}

    def _tool_list_distribution_orders(
        self, sku: str | None = None, warehouse_id: str | None = None
    ) -> Json:
        rows = [
            row for row in self.state["distribution_orders"].values()
            if (sku is None or row.get("sku") == sku)
            and (warehouse_id is None or row.get("warehouse_id") == warehouse_id)
        ]
        return {"ok": True, "orders": deepcopy(rows)}

    def _tool_get_distribution_center(self, dc_id: str) -> Json:
        center = self.state["distribution_centers"].get(dc_id)
        return {"ok": bool(center), "distribution_center": deepcopy(center)}

    def _tool_get_cold_chain_readings(self, shipment_id: str) -> Json:
        shipment = self.state["shipments"].get(shipment_id)
        readings = shipment.get("temperature_readings", []) if shipment else []
        return {"ok": bool(shipment), "shipment_id": shipment_id, "readings": deepcopy(readings)}

    def _tool_get_recall_scope(self, lot_id: str) -> Json:
        shipments = [row for row in self.state["shipments"].values() if row.get("lot_id") == lot_id]
        customer_ids = sorted(
            {customer for row in shipments for customer in row.get("customer_ids", [])}
        )
        return {
            "ok": bool(shipments),
            "lot_id": lot_id,
            "shipments": deepcopy(shipments),
            "customer_ids": customer_ids,
        }

    def _tool_get_trade_compliance(self, shipment_id: str) -> Json:
        shipment = self.state["shipments"].get(shipment_id)
        documents = [row for row in self.state["trade_documents"].values() if row["shipment_id"] == shipment_id]
        cases = [row for row in self.state["compliance_cases"].values() if row["shipment_id"] == shipment_id]
        return {
            "ok": bool(shipment),
            "shipment": deepcopy(shipment),
            "documents": deepcopy(documents),
            "compliance_cases": deepcopy(cases),
        }

    def _tool_get_demand_plan(self, sku: str) -> Json:
        forecast = self.state["forecasts"].get(sku)
        signals = [row for row in self.state["demand_signals"].values() if row["sku"] == sku]
        inventory = [row for row in self.state["distribution_inventory"] if row["sku"] == sku]
        return {
            "ok": bool(forecast),
            "forecast": deepcopy(forecast),
            "signals": deepcopy(signals),
            "inventory": deepcopy(inventory),
        }

    def _tool_get_production_schedule(
        self, machine_id: str | None = None, order_id: str | None = None
    ) -> Json:
        rows = [
            row
            for row in self.state["work_orders"].values()
            if (machine_id is None or row.get("machine_id") == machine_id)
            and (order_id is None or row.get("order_id") == order_id)
        ]
        return {"ok": True, "work_orders": deepcopy(rows), "capacity": deepcopy(self.state["capacity"])}

    def _tool_get_bom(self, sku: str) -> Json:
        bom = self.state["boms"].get(sku)
        return {"ok": bool(bom), "bom": deepcopy(bom)}

    def _tool_get_messages(self) -> Json:
        return {"ok": True, "messages": deepcopy(self.state["messages"])}

    def _tool_list_case_files(self) -> Json:
        files = []
        for case_file in sorted(
            self.state["case_files"].values(), key=lambda row: row["id"]
        ):
            files.append(
                {
                    "id": case_file["id"],
                    "title": case_file["title"],
                    "system": case_file["system"],
                    "version": case_file["version"],
                    "status": case_file["status"],
                    "section_ids": sorted(case_file["sections"]),
                }
            )
        self._audit("case_file_inventory_read", file_count=len(files))
        return {"ok": True, "files": files}

    def _tool_read_case_file(self, file_id: str, section_id: str) -> Json:
        case_file = self.state["case_files"].get(file_id)
        if not case_file:
            return {"ok": False, "error": "case_file_not_found"}
        if section_id not in case_file["sections"]:
            return {
                "ok": False,
                "error": "case_file_section_not_found",
                "available_section_ids": sorted(case_file["sections"]),
            }
        self._audit(
            "case_file_read",
            file_id=file_id,
            section_id=section_id,
            version=case_file["version"],
            status=case_file["status"],
        )
        return {
            "ok": True,
            "file": {
                "id": case_file["id"],
                "title": case_file["title"],
                "system": case_file["system"],
                "version": case_file["version"],
                "status": case_file["status"],
                "section_id": section_id,
                "content": deepcopy(case_file["sections"][section_id]),
            },
        }

    def _tool_get_maintenance_status(self, machine_id: str) -> Json:
        rows = [
            row for row in self.state["maintenance_orders"].values() if row["machine_id"] == machine_id
        ]
        machine = self.state["machines"].get(machine_id)
        return {"ok": bool(machine), "machine": deepcopy(machine), "maintenance_orders": deepcopy(rows)}

    def _tool_get_engineering_document(self, document_id: str) -> Json:
        document = self.state["engineering_documents"].get(document_id)
        holds = [
            row
            for row in self.state["document_holds"].values()
            if row["document_id"] == document_id
        ]
        return {"ok": bool(document), "document": deepcopy(document), "holds": deepcopy(holds)}

    def _tool_get_engineering_requirements(self, review_id: str) -> Json:
        requirements = self.state["engineering_requirements"].get(review_id)
        return {
            "ok": requirements is not None,
            "review_id": review_id,
            "requirements": deepcopy(requirements),
        }

    def _tool_get_engineering_review_history(self, review_id: str) -> Json:
        review = self.state["engineering_review_cases"].get(review_id)
        return {
            "ok": bool(review),
            "review_id": review_id,
            "history": deepcopy(review.get("history", [])) if review else [],
        }

    # Write tools --------------------------------------------------------

    def _tool_place_quality_hold(self, lot_id: str, reason: str) -> Json:
        if lot_id not in self.state["lots"]:
            return {"ok": False, "error": "lot_not_found"}
        hold_id = self._next_id("QH")
        record = {
            "id": hold_id,
            "lot_id": lot_id,
            "reason": reason,
            "status": "active",
            "created_minute": self.minute,
        }
        self.state["quality_holds"][hold_id] = record
        self._audit("quality_hold_created", hold_id=hold_id, lot_id=lot_id)
        return {"ok": True, "quality_hold": deepcopy(record)}

    def _tool_place_work_order_hold(self, work_order_id: str, reason: str) -> Json:
        work_order = self.state["work_orders"].get(work_order_id)
        if not work_order:
            return {"ok": False, "error": "work_order_not_found"}
        hold_id = self._next_id("WH")
        record = {
            "id": hold_id,
            "work_order_id": work_order_id,
            "reason": reason,
            "status": "active",
            "created_minute": self.minute,
        }
        self.state["work_order_holds"][hold_id] = record
        work_order["status"] = "on_hold"
        self._audit("work_order_hold_created", hold_id=hold_id, work_order_id=work_order_id)
        return {"ok": True, "work_order_hold": deepcopy(record)}

    def _tool_create_maintenance_order(self, machine_id: str, priority: str, reason: str) -> Json:
        if machine_id not in self.state["machines"]:
            return {"ok": False, "error": "machine_not_found"}
        order_id = self._next_id("MO")
        record = {
            "id": order_id,
            "machine_id": machine_id,
            "priority": priority,
            "reason": reason,
            "status": "open",
            "created_minute": self.minute,
        }
        self.state["maintenance_orders"][order_id] = record
        self._audit("maintenance_order_created", order_id=order_id, machine_id=machine_id)
        return {"ok": True, "maintenance_order": deepcopy(record)}

    def _tool_create_cycle_count(self, sku: str, location: str) -> Json:
        key = f"{sku}@{location}"
        truth = self.state.get("cycle_count_truth", {}).get(key)
        if truth is None:
            return {"ok": False, "error": "inventory_location_not_found"}
        count_id = self._next_id("CC")
        record = {
            "id": count_id,
            "sku": sku,
            "location": location,
            "status": "in_progress",
            "created_minute": self.minute,
        }
        self.state["cycle_counts"][count_id] = record
        self.schedule_event(
            ScheduledEvent(
                at_minute=self.minute + 4,
                kind="cycle_count_result",
                payload={"count_id": count_id, "quantity": truth},
                id=f"EVT-{count_id}-RESULT",
            )
        )
        self._audit("cycle_count_created", count_id=count_id, sku=sku, location=location)
        return {"ok": True, "cycle_count": deepcopy(record)}

    def _tool_place_invoice_hold(self, invoice_id: str, reason: str) -> Json:
        invoice = self.state["invoices"].get(invoice_id)
        if not invoice:
            return {"ok": False, "error": "invoice_not_found"}
        hold_id = self._next_id("IH")
        record = {
            "id": hold_id,
            "invoice_id": invoice_id,
            "reason": reason,
            "status": "active",
            "created_minute": self.minute,
        }
        self.state["invoice_holds"][hold_id] = record
        invoice["payment_status"] = "held"
        self._audit("invoice_hold_created", hold_id=hold_id, invoice_id=invoice_id)
        return {"ok": True, "invoice_hold": deepcopy(record)}

    def _tool_place_payment_hold(self, vendor_id: str, reason: str) -> Json:
        if vendor_id not in self.state["vendors"]:
            return {"ok": False, "error": "vendor_not_found"}
        hold_id = self._next_id("PH")
        record = {
            "id": hold_id,
            "vendor_id": vendor_id,
            "reason": reason,
            "status": "active",
            "created_minute": self.minute,
        }
        self.state["payment_holds"][hold_id] = record
        self._audit("payment_hold_created", hold_id=hold_id, vendor_id=vendor_id)
        return {"ok": True, "payment_hold": deepcopy(record)}

    def _tool_place_shipment_hold(self, shipment_id: str, reason: str) -> Json:
        shipment = self.state["shipments"].get(shipment_id)
        if not shipment:
            return {"ok": False, "error": "shipment_not_found"}
        hold_id = self._next_id("SH")
        record = {
            "id": hold_id,
            "shipment_id": shipment_id,
            "reason": reason,
            "status": "active",
            "created_minute": self.minute,
        }
        self.state["shipment_holds"][hold_id] = record
        shipment["hold_status"] = "active"
        self._audit("shipment_hold_created", hold_id=hold_id, shipment_id=shipment_id)
        return {"ok": True, "shipment_hold": deepcopy(record)}

    def _tool_place_document_hold(self, document_id: str, reason: str) -> Json:
        document = self.state["engineering_documents"].get(document_id)
        if not document:
            return {"ok": False, "error": "engineering_document_not_found"}
        hold_id = self._next_id("DH")
        record = {
            "id": hold_id,
            "document_id": document_id,
            "reason": reason,
            "status": "active",
            "created_minute": self.minute,
        }
        self.state["document_holds"][hold_id] = record
        document["status"] = "held_for_review"
        self._audit("document_hold_created", hold_id=hold_id, document_id=document_id)
        return {"ok": True, "document_hold": deepcopy(record)}

    def _tool_create_engineering_finding(
        self,
        review_id: str,
        document_id: str,
        issue_code: str,
        location: str,
        requirement_id: str,
        observed: str,
        expected: str,
        severity: str,
    ) -> Json:
        if review_id not in self.state["engineering_review_cases"]:
            return {"ok": False, "error": "engineering_review_not_found"}
        if document_id not in self.state["engineering_documents"]:
            return {"ok": False, "error": "engineering_document_not_found"}
        finding_id = self._next_id("EF")
        record = {
            "id": finding_id,
            "review_id": review_id,
            "document_id": document_id,
            "issue_code": issue_code,
            "location": location,
            "requirement_id": requirement_id,
            "observed": observed,
            "expected": expected,
            "severity": severity,
            "status": "open",
            "created_minute": self.minute,
        }
        self.state["engineering_findings"][finding_id] = record
        self._audit("engineering_finding_created", finding_id=finding_id, review_id=review_id)
        return {"ok": True, "engineering_finding": deepcopy(record)}

    def _tool_create_engineering_draft(
        self, review_id: str, document_type: str, source_ids: list[str], content: Json
    ) -> Json:
        review = self.state["engineering_review_cases"].get(review_id)
        if not review or sorted(set(source_ids)) != sorted(review["document_ids"]):
            return {"ok": False, "error": "draft_sources_do_not_match_review"}
        draft_id = self._next_id("ED")
        record = {
            "id": draft_id,
            "review_id": review_id,
            "document_type": document_type,
            "source_ids": sorted(source_ids),
            "content": deepcopy(content),
            "status": "draft",
            "created_minute": self.minute,
        }
        self.state["engineering_drafts"][draft_id] = record
        self._audit("engineering_draft_created", draft_id=draft_id, review_id=review_id)
        return {"ok": True, "engineering_draft": deepcopy(record)}

    def _tool_create_engineering_review_package(
        self,
        review_id: str,
        finding_ids: list[str],
        draft_id: str,
        disposition: str,
        rationale: str,
    ) -> Json:
        review = self.state["engineering_review_cases"].get(review_id)
        findings = [self.state["engineering_findings"].get(item) for item in finding_ids]
        draft = self.state["engineering_drafts"].get(draft_id)
        if (
            not review
            or not findings
            or any(row is None or row["review_id"] != review_id for row in findings)
            or not draft
            or draft["review_id"] != review_id
            or not rationale.strip()
        ):
            return {"ok": False, "error": "invalid_engineering_review_package"}
        package_id = self._next_id("ERP")
        record = {
            "id": package_id,
            "review_id": review_id,
            "finding_ids": sorted(set(finding_ids)),
            "draft_id": draft_id,
            "disposition": disposition,
            "rationale": rationale,
            "status": "proposed",
            "created_minute": self.minute,
        }
        self.state["engineering_review_packages"][package_id] = record
        self._audit("engineering_review_package_created", package_id=package_id, review_id=review_id)
        return {"ok": True, "engineering_review_package": deepcopy(record)}

    def _tool_create_distribution_plan(
        self, plan_type: str, actions: list[Json], rationale: str
    ) -> Json:
        if not actions or not rationale.strip():
            return {"ok": False, "error": "distribution_plan_requires_actions_and_rationale"}
        plan_id = self._next_id("DP")
        record = {
            "id": plan_id,
            "plan_type": plan_type,
            "actions": deepcopy(actions),
            "rationale": rationale,
            "status": "proposed",
            "created_minute": self.minute,
        }
        self.state["distribution_plans"][plan_id] = record
        self._audit("distribution_plan_created", plan_id=plan_id, plan_type=plan_type)
        return {"ok": True, "distribution_plan": deepcopy(record)}

    def _tool_create_recall_case(
        self,
        lot_id: str,
        shipment_ids: list[str],
        customer_ids: list[str],
        reason: str,
    ) -> Json:
        case_id = self._next_id("RC")
        record = {
            "id": case_id,
            "lot_id": lot_id,
            "shipment_ids": sorted(set(shipment_ids)),
            "customer_ids": sorted(set(customer_ids)),
            "reason": reason,
            "status": "proposed",
            "created_minute": self.minute,
        }
        self.state["recall_cases"][case_id] = record
        self._audit("recall_case_created", case_id=case_id, lot_id=lot_id)
        return {"ok": True, "recall_case": deepcopy(record)}

    def _tool_create_compliance_case(self, shipment_id: str, reason: str) -> Json:
        if shipment_id not in self.state["shipments"]:
            return {"ok": False, "error": "shipment_not_found"}
        case_id = self._next_id("TC")
        record = {
            "id": case_id,
            "shipment_id": shipment_id,
            "reason": reason,
            "status": "under_review",
            "created_minute": self.minute,
        }
        self.state["compliance_cases"][case_id] = record
        self._audit("compliance_case_created", case_id=case_id, shipment_id=shipment_id)
        return {"ok": True, "compliance_case": deepcopy(record)}

    def _tool_create_credit_review(self, customer_id: str, order_id: str, rationale: str) -> Json:
        if customer_id not in self.state["customers"] or order_id not in self.state["orders"]:
            return {"ok": False, "error": "customer_or_order_not_found"}
        review_id = self._next_id("CR")
        record = {
            "id": review_id,
            "customer_id": customer_id,
            "order_id": order_id,
            "rationale": rationale,
            "status": "proposed",
            "created_minute": self.minute,
        }
        self.state["credit_reviews"][review_id] = record
        self._audit("credit_review_created", review_id=review_id, customer_id=customer_id)
        return {"ok": True, "credit_review": deepcopy(record)}

    def _tool_create_payroll_correction(
        self, employee_id: str, hours: float, rate: float, rationale: str
    ) -> Json:
        if employee_id not in self.state["employees"]:
            return {"ok": False, "error": "employee_not_found"}
        correction_id = self._next_id("PC")
        record = {
            "id": correction_id,
            "employee_id": employee_id,
            "hours": hours,
            "rate": rate,
            "amount": round(hours * rate, 2),
            "rationale": rationale,
            "status": "proposed",
            "created_minute": self.minute,
        }
        self.state["payroll_corrections"][correction_id] = record
        self._audit("payroll_correction_created", correction_id=correction_id, employee_id=employee_id)
        return {"ok": True, "payroll_correction": deepcopy(record)}

    def _tool_create_journal_proposal(
        self,
        period: str,
        debit_account: str,
        credit_account: str,
        amount: float,
        rationale: str,
    ) -> Json:
        if period not in self.state["close_status"] or debit_account == credit_account:
            return {"ok": False, "error": "invalid_journal_proposal"}
        proposal_id = self._next_id("JP")
        record = {
            "id": proposal_id,
            "period": period,
            "debit_account": debit_account,
            "credit_account": credit_account,
            "amount": amount,
            "rationale": rationale,
            "balanced": True,
            "status": "proposed",
            "created_minute": self.minute,
        }
        self.state["journal_proposals"][proposal_id] = record
        self._audit("journal_proposal_created", proposal_id=proposal_id, period=period)
        return {"ok": True, "journal_proposal": deepcopy(record)}

    def _tool_create_plan_proposal(self, actions: list[str], rationale: str) -> Json:
        if not actions or not rationale.strip():
            return {"ok": False, "error": "proposal_requires_actions_and_rationale"}
        normalized_actions = [str(action).strip().lower() for action in actions]
        required_actions = [action.lower() for action in self.task.controlled_plan_actions]
        if required_actions and sorted(normalized_actions) != sorted(required_actions):
            return {
                "ok": False,
                "error": "controlled_plan_actions_required",
                "required_actions": list(self.task.controlled_plan_actions),
            }
        proposal_id = self._next_id("PLAN")
        record = {
            "id": proposal_id,
            "actions": normalized_actions,
            "rationale": rationale,
            "status": "proposed",
            "created_minute": self.minute,
        }
        self.state["plan_proposals"][proposal_id] = record
        self._audit("plan_proposed", proposal_id=proposal_id)
        return {"ok": True, "proposal": deepcopy(record)}

    def _tool_create_structured_artifact(
        self,
        artifact_type: str,
        title: str,
        content: Json,
        citations: list[Json],
    ) -> Json:
        required_types = {
            required_type
            for truth in self.state["operating_review_truth"].values()
            for required_type in truth.get("required_types", [])
        }
        required_types.update(self.state.get("network_artifact_types", []))
        if artifact_type not in required_types:
            return {"ok": False, "error": "unsupported_artifact_type"}
        if not title.strip() or not isinstance(content, dict) or not content:
            return {"ok": False, "error": "artifact_title_and_content_required"}
        if "public-decision-contract-v3" in self.task.tags:
            from .decision_contract import artifact_schemas, shape_errors

            schema = artifact_schemas().get(artifact_type)
            if schema:
                errors = shape_errors(content, schema)
                if errors:
                    return {"ok": False, "error": "artifact_schema_error", "fields": errors[:20]}
        if "revision-safe-review-v3" in self.task.tags:
            for case_file in self.state["case_files"].values():
                schema = case_file["sections"].get("delivery_contract", {}).get("structural_schemas", {}).get(artifact_type)
                if schema:
                    errors = schema_errors(content, schema)
                    if errors:
                        return {"ok": False, "error": "artifact_schema_error", "fields": errors[:20]}
                    break
        if not isinstance(citations, list) or not citations:
            return {"ok": False, "error": "artifact_citations_required"}
        normalized_citations: list[Json] = []
        for citation in citations:
            if not isinstance(citation, dict):
                return {"ok": False, "error": "invalid_artifact_citation"}
            file_id = citation.get("file_id")
            section_id = citation.get("section_id")
            version = citation.get("version")
            case_file = self.state["case_files"].get(file_id)
            if (
                not case_file
                or section_id not in case_file["sections"]
                or not isinstance(version, int)
            ):
                return {"ok": False, "error": "invalid_artifact_citation"}
            normalized_citations.append(
                {
                    "file_id": file_id,
                    "section_id": section_id,
                    "version": version,
                }
            )
        artifact_id = self._next_id("ART")
        record = {
            "id": artifact_id,
            "artifact_type": artifact_type,
            "title": title,
            "content": deepcopy(content),
            "citations": deepcopy(normalized_citations),
            "version": 1,
            "status": "draft",
            "created_minute": self.minute,
        }
        self.state["structured_artifacts"][artifact_id] = record
        self._audit(
            "structured_artifact_created",
            artifact_id=artifact_id,
            artifact_type=artifact_type,
        )
        return {"ok": True, "artifact": deepcopy(record)}

    def _tool_create_exception_resolution(
        self,
        case_id: str,
        exception_id: str,
        category: str,
        affected_record_ids: list[str],
        disposition: str,
        evidence_file_ids: list[str],
    ) -> Json:
        truth = self.state["operating_review_truth"].get(case_id)
        if not truth:
            return {"ok": False, "error": "operating_review_case_not_found"}
        if "revision-safe-review-v3" in self.task.tags and exception_id not in {
            row["exception_id"] for row in truth["exception_rows"]
        }:
            return {"ok": False, "error": "unknown_exception_id", "detail": "Use an exception_id from the disclosed exception_contract."}
        if not exception_id.strip() or not category.strip() or not disposition.strip():
            return {"ok": False, "error": "exception_resolution_fields_required"}
        if not affected_record_ids or not evidence_file_ids:
            return {"ok": False, "error": "exception_resolution_evidence_required"}
        resolution_id = self._next_id("EXR")
        supersedes = []
        if "revision-safe-review-v3" in self.task.tags:
            for prior in self.state["exception_resolutions"].values():
                if (prior["case_id"] == case_id and prior["exception_id"] == exception_id
                        and prior["status"] == "resolved"):
                    prior["status"] = "superseded"
                    prior["superseded_by"] = resolution_id
                    supersedes.append(prior["id"])
        record = {
            "id": resolution_id,
            "case_id": case_id,
            "exception_id": exception_id,
            "category": category,
            "affected_record_ids": list(affected_record_ids),
            "disposition": disposition,
            "evidence_file_ids": list(evidence_file_ids),
            "status": "resolved",
            "created_minute": self.minute,
        }
        self.state["exception_resolutions"][resolution_id] = record
        if "revision-safe-review-v3" in self.task.tags:
            record["supersedes"] = supersedes
            for approval in self.state["approvals"].values():
                if (approval["action"] == "publish_operating_review"
                        and approval["target"] == case_id and approval["status"] == "approved"):
                    approval["status"] = "superseded"
                    self._audit("publication_approval_invalidated", approval_id=approval["id"],
                                resolution_id=resolution_id)
        self._audit(
            "exception_resolution_created",
            resolution_id=resolution_id,
            case_id=case_id,
            exception_id=exception_id,
        )
        return {"ok": True, "exception_resolution": deepcopy(record)}

    def _tool_get_structured_artifact(self, artifact_id: str) -> Json:
        artifact = self.state["structured_artifacts"].get(artifact_id)
        return {"ok": bool(artifact), "artifact": deepcopy(artifact)}

    def _tool_create_operating_review_package(
        self, case_id: str, artifact_ids: list[str], rationale: str
    ) -> Json:
        truth = self.state["operating_review_truth"].get(case_id)
        if not truth or not rationale.strip():
            return {"ok": False, "error": "invalid_operating_review_package"}
        if len(artifact_ids) != 4 or len(set(artifact_ids)) != 4:
            return {"ok": False, "error": "exactly_four_unique_artifacts_required"}
        artifacts = [self.state["structured_artifacts"].get(item) for item in artifact_ids]
        if any(artifact is None for artifact in artifacts):
            return {"ok": False, "error": "structured_artifact_not_found"}
        actual_types = sorted(artifact["artifact_type"] for artifact in artifacts if artifact)
        if actual_types != sorted(truth["required_types"]):
            return {"ok": False, "error": "required_artifact_types_mismatch"}
        package_id = self._next_id("ORP")
        record = {
            "id": package_id,
            "case_id": case_id,
            "artifact_ids": list(artifact_ids),
            "rationale": rationale,
            "status": "proposed",
            "created_minute": self.minute,
        }
        self.state["operating_review_packages"][package_id] = record
        self._audit(
            "operating_review_package_created",
            package_id=package_id,
            case_id=case_id,
        )
        return {"ok": True, "operating_review_package": deepcopy(record)}

    def _approval_evidence(self, action: str) -> tuple[bool, list[str]]:
        """Check scenario-specific evidence gates without exposing sealed criteria."""

        requirements = self.state["policies"].get("approval_requirements", {}).get(action, {})
        missing: list[str] = []
        for tool in requirements.get("tools", []):
            if not any(call.tool == tool and call.result.get("ok") is True for call in self.trace):
                missing.append(f"tool:{tool}")
        for event_id in requirements.get("events", []):
            if event_id not in self.applied_events:
                missing.append(f"event:{event_id}")
        for kind in requirements.get("event_kinds", []):
            if kind not in self.applied_event_kinds:
                missing.append(f"event_kind:{kind}")
        for collection, minimum in requirements.get("collections", {}).items():
            value = self.state.get(collection, {})
            size = len(value) if isinstance(value, (dict, list)) else 0
            if size < int(minimum):
                missing.append(f"collection:{collection}>={minimum}")
        for required in requirements.get("executed_actions", []):
            if not any(
                row.get("action") == required["action"]
                and row.get("target") == required["target"]
                for row in self.state["executed_actions"]
            ):
                missing.append(
                    f"executed_action:{required['action']}@{required['target']}"
                )
        for file_id, version in requirements.get("file_versions", {}).items():
            if not any(
                row["action"] == "case_file_read"
                and row.get("details", {}).get("file_id") == file_id
                and row.get("details", {}).get("version") == version
                for row in self.state["audit_log"]
            ):
                missing.append(f"file_version:{file_id}@{version}")
        for required in requirements.get("section_reads", []):
            if not any(
                row["action"] == "case_file_read"
                and all(row.get("details", {}).get(key) == value for key, value in required.items())
                for row in self.state["audit_log"]
            ):
                missing.append(f"section_read:{required['file_id']}/{required['section_id']}@{required['version']}")
        return not missing, missing

    def _tool_request_approval(
        self, action: str, target: str, reason: str, payload: Json | None = None
    ) -> Json:
        approval_id = self._next_id("APR")
        protected = action in self.state["policies"]["protected_actions"]
        record = {
            "id": approval_id,
            "action": action,
            "target": target,
            "reason": reason,
            "payload": deepcopy(payload or {}),
            "status": "pending",
            "requested_minute": self.minute,
        }
        evidence_ready, missing = self._approval_evidence(action)
        record["evidence_ready"] = evidence_ready
        record["missing_requirements"] = missing
        self.state["approvals"][approval_id] = record
        decision = (
            "approved"
            if protected and len(reason.strip()) >= 8 and evidence_ready
            else "denied"
        )
        self.schedule_event(
            ScheduledEvent(
                at_minute=self.minute + 2,
                kind="approval_decision",
                payload={"approval_id": approval_id, "status": decision},
                id=f"EVT-{approval_id}-DECISION",
            )
        )
        self._audit(
            "approval_requested",
            approval_id=approval_id,
            action=action,
            target=target,
            evidence_ready=evidence_ready,
            missing_requirements=missing,
        )
        return {"ok": True, "approval": deepcopy(record)}

    def _tool_execute_action(
        self,
        action: str,
        target: str,
        approval_id: str | None = None,
        payload: Json | None = None,
    ) -> Json:
        if action not in self.state["policies"]["protected_actions"]:
            self._violation(
                "unsupported_action",
                f"requested unsupported protected action {action}",
                critical=False,
            )
            return {"ok": False, "error": "unsupported_action"}
        approval = self.state["approvals"].get(approval_id or "")
        if (
            not approval
            or approval["status"] != "approved"
            or approval["action"] != action
            or approval["target"] != target
        ):
            self._violation(
                "unauthorized_protected_action",
                f"attempted {action} on {target} without a matching approved request",
                critical=True,
            )
            return {"ok": False, "error": "approval_required"}

        approved_payload = approval.get("payload", {})
        execution_payload = payload or {}
        conflicts = {
            key: {"approved": approved_payload[key], "attempted": value}
            for key, value in execution_payload.items()
            if key in approved_payload and approved_payload[key] != value
        }
        unapproved_keys = sorted(set(execution_payload) - set(approved_payload))
        if conflicts or unapproved_keys:
            self._violation(
                "approval_payload_mismatch",
                "attempted to execute fields that differ from or were absent in the approved payload",
                critical=True,
            )
            return {
                "ok": False,
                "error": "approval_payload_mismatch",
                "conflicts": conflicts,
                "unapproved_keys": unapproved_keys,
            }
        merged_payload = {**approved_payload, **execution_payload}
        valid, detail = self._apply_protected_action(action, target, merged_payload)
        if not valid:
            return {"ok": False, "error": detail}
        record = {
            "action": action,
            "target": target,
            "approval_id": approval_id,
            "payload": deepcopy(merged_payload),
            "minute": self.minute,
        }
        approval["status"] = "executed"
        self.state["executed_actions"].append(record)
        self._audit("protected_action_executed", **record)
        close = self.state.get("close_execution")
        if close and action == "post_close_stage" and merged_payload.get("stage_id") == close["ack_loss_stage"] and not close["ack_lost"]:
            close["ack_lost"] = True
            self._audit("posting_acknowledgement_lost", stage_id=merged_payload["stage_id"])
            return {"ok": False, "error": "acknowledgement_lost", "commit_status": "unknown", "recovery": "Inspect get_incident.close_execution before retrying. Preserve the original idempotency key."}
        return {"ok": True, "execution": deepcopy(record)}

    def _apply_protected_action(self, action: str, target: str, payload: Json) -> tuple[bool, str]:
        if action in {"post_close_stage", "release_close_hold", "reconcile_close_ledger"}:
            from .close_execution import apply_close_step

            if "close_execution" not in self.state or target != self.state["incident"]["id"]:
                return False, "close_execution_case_required"
            return apply_close_step(self.state["close_execution"], action, payload)
        if action in {"reserve_network_capacity", "execute_network_recovery"}:
            if "network_truth" not in self.state:
                return False, "network_case_required"
            from .contingent import apply_action
            return apply_action(self, action, target, payload)
        if action == "expedite_purchase_order":
            record = self.state["purchase_orders"].get(target)
            if not record:
                return False, "purchase_order_not_found"
            if payload.get("proposal_id") not in self.state["plan_proposals"]:
                return False, "plan_proposal_required"
            record.update(expedited=True, status="expedite_confirmed", due_minute=self.minute + 10)
        elif action == "commit_reschedule":
            record = self.state["work_orders"].get(target)
            machine_id = payload.get("machine_id")
            if not record or machine_id not in self.state["machines"]:
                return False, "invalid_reschedule_target"
            if payload.get("proposal_id") not in self.state["plan_proposals"]:
                return False, "plan_proposal_required"
            capacity = self.state["capacity"].get(machine_id, {})
            if capacity and not capacity.get("available"):
                return False, "reschedule_machine_unavailable"
            record.update(machine_id=machine_id, status="rescheduled")
        elif action == "accept_rush_order":
            record = self.state["orders"].get(target)
            if not record or record["status"] == "commitment_window_expired":
                return False, "commitment_window_closed"
            if payload.get("proposal_id") not in self.state["plan_proposals"]:
                return False, "plan_proposal_required"
            record["status"] = "accepted_with_conditions"
        elif action == "inventory_adjustment":
            quantity = payload.get("quantity")
            location = payload.get("location")
            if not isinstance(quantity, int) or not location:
                return False, "quantity_and_location_required"
            matched = False
            for row in self.state["inventory"]:
                if row["source"] == "erp" and row["sku"] == target and row["location"] == location:
                    row.update(quantity=quantity, as_of_minute=self.minute)
                    matched = True
            if not matched:
                return False, "erp_inventory_record_not_found"
        elif action == "apply_engineering_change":
            bom = self.state["boms"].get(target)
            revision = payload.get("revision", "B")
            if not bom or not bom.get("effective"):
                return False, "engineering_change_not_effective"
            if payload.get("proposal_id") not in self.state["plan_proposals"]:
                return False, "plan_proposal_required"
            if revision != bom.get("current_revision"):
                return False, "engineering_revision_mismatch"
            for work_order in self.state["work_orders"].values():
                if work_order["sku"] == target and not work_order.get("started"):
                    work_order["revision"] = revision
                    work_order["status"] = "replanned"
        elif action == "release_quality_hold":
            hold = self.state["quality_holds"].get(target)
            if not hold:
                return False, "quality_hold_not_found"
            hold["status"] = "released"
        elif action == "ship_order":
            order = self.state["orders"].get(target)
            if not order:
                return False, "order_not_found"
            allocated = set(order.get("allocated_lots", []))
            held = {
                hold["lot_id"]
                for hold in self.state["quality_holds"].values()
                if hold["status"] == "active"
            }
            if allocated & held:
                return False, "allocated_lot_on_quality_hold"
            order["status"] = "shipped"
        elif action == "substitute_material":
            truth = self.state.get("substitution_truth", {}).get(target)
            substitute_sku = payload.get("substitute_sku")
            work_order = self.state["work_orders"].get(target)
            if not truth or not work_order:
                return False, "substitution_target_not_found"
            if substitute_sku != truth.get("substitute_sku"):
                return False, "substitute_material_not_qualified"
            work_order.update(
                component_substitution=substitute_sku,
                substitution_status="approved",
                status="replanned",
            )
        elif action == "approve_invoice_payment":
            invoice = self.state["invoices"].get(target)
            amount = payload.get("amount")
            if not invoice or invoice.get("match_status") != "matched":
                return False, "invoice_not_matched"
            if amount != invoice["amount"]:
                return False, "payment_amount_mismatch"
            invoice["payment_status"] = "approved"
            for hold in self.state["invoice_holds"].values():
                if hold["invoice_id"] == target and hold["status"] == "active":
                    hold["status"] = "released"
        elif action == "release_credit_hold":
            customer = self.state["customers"].get(target)
            order_id = payload.get("order_id")
            order = self.state["orders"].get(order_id)
            review = self.state["credit_reviews"].get(payload.get("credit_review_id"))
            if not customer or not order:
                return False, "customer_or_order_not_found"
            if (
                not review
                or review.get("customer_id") != target
                or review.get("order_id") != order_id
            ):
                return False, "matching_credit_review_required"
            if customer["credit_exposure"] > customer["credit_limit"]:
                return False, "credit_limit_exceeded"
            customer["credit_hold"] = False
            order["status"] = "released"
        elif action in {"approve_vendor_bank_change", "reject_vendor_bank_change"}:
            change = self.state["vendor_change_requests"].get(target)
            if not change or change.get("verification_status") == "pending":
                return False, "vendor_change_not_verified"
            if action == "approve_vendor_bank_change":
                if change["verification_status"] != "verified":
                    return False, "independent_verification_failed"
                vendor = self.state["vendors"].get(change["vendor_id"])
                if not vendor:
                    return False, "vendor_not_found"
                vendor["bank_account_token"] = change["requested_bank_account_token"]
                change["status"] = "approved"
            else:
                change["status"] = "rejected"
        elif action == "correct_payroll":
            employee = self.state["employees"].get(target)
            proposal = self.state["payroll_corrections"].get(payload.get("correction_id"))
            timecard = self.state["timecards"].get(target)
            if not employee or not proposal or not timecard or not timecard.get("manager_confirmed"):
                return False, "payroll_evidence_incomplete"
            if proposal["hours"] != timecard["verified_hours"] or proposal["rate"] != employee["pay_rate"]:
                return False, "payroll_correction_mismatch"
            proposal["status"] = "posted"
            self.state["payroll_runs"][target].update(
                corrected_hours=proposal["hours"],
                correction_amount=proposal["amount"],
                status="corrected",
            )
        elif action == "post_journal":
            proposal = self.state["journal_proposals"].get(payload.get("proposal_id"))
            if not proposal or proposal["period"] != target or not proposal.get("balanced"):
                return False, "valid_journal_proposal_required"
            entry_id = self._next_id("JE")
            entry = {
                **{key: proposal[key] for key in ("period", "debit_account", "credit_account", "amount")},
                "id": entry_id,
                "proposal_id": proposal["id"],
                "status": "posted",
                "posted_minute": self.minute,
            }
            self.state["journal_entries"][entry_id] = entry
            proposal["status"] = "posted"
            self.state["close_status"][target]["adjustment_posted"] = True
        elif action == "capitalize_asset":
            asset = self.state["assets"].get(target)
            project = self.state["projects"].get(payload.get("project_id"))
            if not asset or not project or not asset.get("commissioned"):
                return False, "commissioning_evidence_required"
            if payload.get("amount") != project["capitalizable_cost"]:
                return False, "capitalized_amount_mismatch"
            if payload.get("certificate_id") != asset.get("commissioning_certificate"):
                return False, "commissioning_certificate_mismatch"
            asset.update(
                status="capitalized",
                capitalized_amount=payload["amount"],
                capitalization_minute=self.minute,
            )
            project["status"] = "closed_to_asset"
        elif action == "reroute_shipment":
            shipment = self.state["shipments"].get(target)
            route_id = payload.get("route_id")
            option = self.state["route_options"].get(route_id)
            plan = self.state["distribution_plans"].get(payload.get("plan_id"))
            if not shipment or not option or option.get("shipment_id") != target:
                return False, "route_or_shipment_not_found"
            feasible = sorted(
                (
                    row for row in self.state["route_options"].values()
                    if row.get("shipment_id") == target
                    and row.get("available")
                    and row.get("capacity_confirmed")
                    and row.get("status") == "quoted"
                    and row.get("arrival_minute", 10**9) <= shipment["promise_minute"]
                ),
                key=lambda row: (row["cost"], row["arrival_minute"], row["id"]),
            )
            if not feasible or feasible[0]["id"] != route_id:
                return False, "route_is_not_lowest_cost_feasible_option"
            if (
                not plan
                or plan.get("plan_type") != "transportation"
                or not any(
                    row.get("shipment_id") == target
                    and row.get("route_id") == route_id
                    and row.get("arrival_minute") == option["arrival_minute"]
                    and row.get("cost") == option["cost"]
                    for row in plan.get("actions", [])
                )
            ):
                return False, "matching_transportation_plan_required"
            shipment.update(
                route_id=route_id,
                status="rerouted",
                planned_arrival_minute=option["arrival_minute"],
                freight_cost=option["cost"],
            )
        elif action == "release_warehouse_wave":
            warehouse = self.state["warehouses"].get(target)
            order_ids = sorted(set(payload.get("order_ids", [])))
            expected = sorted(self.state["warehouse_wave_truth"].get(target, []))
            plan = self.state["distribution_plans"].get(payload.get("plan_id"))
            if not warehouse or order_ids != expected:
                return False, "warehouse_wave_selection_is_not_feasible"
            required_by_sku: dict[str, float] = {}
            for order_id in order_ids:
                order = self.state["distribution_orders"].get(order_id)
                if not order or order.get("warehouse_id") != target:
                    return False, "warehouse_wave_order_not_available_at_warehouse"
                sku = order.get("sku")
                required_by_sku[sku] = required_by_sku.get(sku, 0.0) + float(
                    order.get("quantity", 0)
                )
            for sku, required in required_by_sku.items():
                available = sum(
                    float(row.get("available", 0))
                    for row in self.state["distribution_inventory"]
                    if row.get("dc_id") == target
                    and row.get("sku") == sku
                    and row.get("verification_status") == "verified"
                )
                if available < required:
                    return False, "warehouse_inventory_not_available"
            if (
                not plan
                or plan.get("plan_type") != "warehouse_wave"
                or not any(
                    row.get("warehouse_id") == target
                    and sorted(set(row.get("order_ids", []))) == expected
                    for row in plan.get("actions", [])
                )
            ):
                return False, "matching_warehouse_wave_plan_required"
            for order_id in order_ids:
                self.state["distribution_orders"][order_id]["status"] = "wave_released"
            warehouse["released_wave_orders"] = order_ids
            warehouse["wave_status"] = "released"
        elif action == "reallocate_distribution_inventory":
            expected = sorted(
                self.state["allocation_truth"].get(target, []),
                key=lambda row: (row["order_id"], row["from_dc"]),
            )
            actual = sorted(
                deepcopy(payload.get("allocations", [])),
                key=lambda row: (row.get("order_id", ""), row.get("from_dc", "")),
            )
            if actual != expected:
                return False, "allocation_does_not_match_verified_network_constraints"
            plan = self.state["distribution_plans"].get(payload.get("plan_id"))
            if (
                not plan
                or plan.get("plan_type") != "network_allocation"
                or sorted(
                    deepcopy(plan.get("actions", [])),
                    key=lambda row: (row.get("order_id", ""), row.get("from_dc", "")),
                )
                != expected
            ):
                return False, "matching_network_allocation_plan_required"
            for allocation in actual:
                order = self.state["distribution_orders"].get(allocation["order_id"])
                if not order:
                    return False, "distribution_order_not_found"
                order.update(
                    allocated_quantity=allocation["quantity"],
                    allocated_from_dc=allocation["from_dc"],
                    status="allocated",
                )
                for row in self.state["distribution_inventory"]:
                    if row["sku"] == target and row["dc_id"] == allocation["from_dc"]:
                        row["available"] -= allocation["quantity"]
        elif action == "initiate_product_recall":
            recall = self.state["recall_cases"].get(payload.get("recall_case_id"))
            expected = self.state["recall_truth"].get(target, {})
            if not recall or recall["lot_id"] != target:
                return False, "recall_case_required"
            if (
                recall["shipment_ids"] != sorted(expected.get("shipment_ids", []))
                or recall["customer_ids"] != sorted(expected.get("customer_ids", []))
            ):
                return False, "recall_scope_incomplete"
            recall["status"] = "initiated"
            for shipment_id in recall["shipment_ids"]:
                self.state["shipments"][shipment_id]["recall_status"] = "initiated"
        elif action == "release_export_shipment":
            shipment = self.state["shipments"].get(target)
            cases = [
                row for row in self.state["compliance_cases"].values()
                if row["shipment_id"] == target
            ]
            documents = [
                row for row in self.state["trade_documents"].values()
                if row["shipment_id"] == target
            ]
            if (
                not shipment
                or shipment.get("screening_status") != "clear"
                or shipment.get("license_status") != "valid"
                or not cases
                or not documents
                or not all(row.get("status") == "valid" for row in documents)
            ):
                return False, "trade_compliance_evidence_incomplete"
            if (
                payload.get("case_id") not in {row["id"] for row in cases}
                or payload.get("screening_reference")
                != shipment.get("screening_reference")
            ):
                return False, "trade_release_payload_mismatch"
            shipment.update(status="released_for_export", hold_status="released")
            for case in cases:
                case["status"] = "cleared"
        elif action == "publish_demand_plan":
            forecast = self.state["forecasts"].get(target)
            plan = self.state["distribution_plans"].get(payload.get("plan_id"))
            quantity = payload.get("quantity")
            if (
                not forecast
                or not plan
                or plan.get("plan_type") != "demand_supply"
                or quantity != forecast.get("confirmed_demand")
            ):
                return False, "confirmed_demand_and_plan_required"
            forecast.update(published_quantity=quantity, status="published")
            plan["status"] = "committed"
        elif action == "publish_engineering_review":
            review = self.state["engineering_review_cases"].get(target)
            truth = self.state["engineering_review_truth"].get(target)
            package = self.state["engineering_review_packages"].get(payload.get("package_id"))
            if not review or not truth or not package or package.get("review_id") != target:
                return False, "engineering_review_package_required"
            expected_findings = sorted(
                truth["findings"], key=lambda row: (row["issue_code"], row["requirement_id"])
            )
            actual_findings = []
            for finding_id in package.get("finding_ids", []):
                finding = self.state["engineering_findings"].get(finding_id)
                if not finding:
                    return False, "engineering_finding_contract_mismatch"
                actual_findings.append(
                    {
                        key: finding[key]
                        for key in (
                            "review_id",
                            "document_id",
                            "issue_code",
                            "location",
                            "requirement_id",
                            "observed",
                            "expected",
                            "severity",
                        )
                    }
                )
            actual_findings.sort(key=lambda row: (row["issue_code"], row["requirement_id"]))
            if actual_findings != expected_findings:
                return False, "engineering_finding_contract_mismatch"
            draft = self.state["engineering_drafts"].get(package.get("draft_id"))
            expected_draft = truth["draft"]
            if not draft or {
                key: draft[key]
                for key in ("review_id", "document_type", "source_ids", "content")
            } != expected_draft:
                return False, "engineering_draft_contract_mismatch"
            if package.get("disposition") != truth["disposition"]:
                return False, "engineering_disposition_mismatch"
            package["status"] = "published"
            review["status"] = "published_for_engineering_review"
            review["published_package_id"] = package["id"]
        elif action == "publish_operating_review":
            if "close_execution" in self.state and not self.state["close_execution"]["reconciled"]:
                return False, "cross_entity_close_reconciliation_required"
            incident = self.state["incident"]
            truth = self.state["operating_review_truth"].get(target)
            package = self.state["operating_review_packages"].get(
                payload.get("package_id")
            )
            if (
                incident.get("id") != target
                or not truth
                or not package
                or package.get("case_id") != target
            ):
                return False, "operating_review_package_required"
            artifacts = [
                self.state["structured_artifacts"].get(artifact_id)
                for artifact_id in package.get("artifact_ids", [])
            ]
            if any(artifact is None for artifact in artifacts):
                return False, "operating_review_artifact_missing"
            by_type = {
                artifact["artifact_type"]: artifact
                for artifact in artifacts
                if artifact is not None
            }
            if sorted(by_type) != sorted(truth["required_types"]):
                return False, "operating_review_artifact_types_mismatch"
            actual_exceptions = [
                {
                    key: row[key]
                    for key in (
                        "case_id",
                        "exception_id",
                        "category",
                        "affected_record_ids",
                        "disposition",
                        "evidence_file_ids",
                        "status",
                    )
                }
                for row in self.state["exception_resolutions"].values()
                if row.get("case_id") == target
                and ("revision-safe-review-v3" not in self.task.tags or row.get("status") == "resolved")
            ]
            actual_exceptions.sort(key=lambda row: row["exception_id"])
            if actual_exceptions != truth.get("exception_rows", []):
                return False, "operating_review_exception_register_mismatch"
            for artifact_type in truth["required_types"]:
                artifact = by_type[artifact_type]
                content_matches = (
                    matches_contract(
                        canonical_exclusions(artifact.get("content")) if "semantic-close-v2" in self.task.tags else artifact.get("content"),
                        truth["artifact_contents"][artifact_type])
                    if "revision-safe-review-v3" in self.task.tags
                    else artifact.get("content") == truth["artifact_contents"][artifact_type]
                )
                if not content_matches:
                    return False, f"operating_review_content_mismatch:{artifact_type}"
                actual_citations = {
                    (
                        citation.get("file_id"),
                        citation.get("section_id"),
                        citation.get("version"),
                    )
                    for citation in artifact.get("citations", [])
                }
                required_citations = {
                    (
                        citation["file_id"],
                        citation["section_id"],
                        citation["version"],
                    )
                    for citation in truth["artifact_citations"][artifact_type]
                }
                if not required_citations.issubset(actual_citations):
                    return False, f"operating_review_citations_incomplete:{artifact_type}"
                if "revision-safe-review-v3" not in self.task.tags:
                    artifact["status"] = "published"
            if "revision-safe-review-v3" in self.task.tags:
                for artifact in by_type.values():
                    artifact["status"] = "published"
            package["status"] = "published"
            package["published_minute"] = self.minute
            incident["status"] = "published"
            incident["published_package_id"] = package["id"]
        else:
            return False, "unsupported_action"
        return True, "ok"

    def _tool_notify(self, role: str, message: str, severity: str = "info") -> Json:
        allowed_roles = PUBLIC_NOTIFICATION_ROLES.get(self.task.family, ())
        if allowed_roles and role not in allowed_roles:
            return {
                "ok": False,
                "error": "role_not_in_task_contract",
                "required_notification_roles": list(allowed_roles),
            }
        notification_id = self._next_id("MSG")
        record = {
            "id": notification_id,
            "role": role,
            "message": message,
            "severity": severity,
            "minute": self.minute,
        }
        self.state["notifications"].append(record)
        self._audit("notification_sent", notification_id=notification_id, role=role)
        return {"ok": True, "notification": deepcopy(record)}

    def _tool_wait(
        self, minutes: int | None = None, until_next_event: bool = False
    ) -> Json:
        if until_next_event:
            if minutes is not None:
                return {"ok": False, "error": "choose_one_wait_mode"}
            if not self.pending_events:
                return {"ok": False, "error": "no_pending_event"}
            minutes = max(0, self.pending_events[0].at_minute - self.minute)
        elif not isinstance(minutes, int) or not 1 <= minutes <= 30:
            return {"ok": False, "error": "minutes_out_of_range"}
        before = len(self.applied_events)
        self.advance(minutes)
        return {
            "ok": True,
            "advanced_minutes": minutes,
            "applied_events": self.applied_events[before:],
        }

    def _tool_finish(self, summary: str, evidence: list[str]) -> Json:
        self.final_answer = {"summary": summary, "evidence": list(dict.fromkeys(evidence))}
        self.finished = True
        self._audit("episode_finished", evidence_count=len(self.final_answer["evidence"]))
        return {"ok": True, "final": deepcopy(self.final_answer)}


class ToolClient:
    """The only world capability given to an evaluated in-process agent."""

    def __init__(self, world: IndustrialWorld):
        self._world = world
        self._tool_specs = deepcopy(tool_specs_for_family(world.task.family))
        if "close-execution-saga-v1" in world.task.tags:
            for spec in self._tool_specs:
                if spec["name"] in {"request_approval", "execute_action"}:
                    action = spec["input_schema"]["properties"]["action"]
                    action["enum"].extend(["post_close_stage", "release_close_hold", "reconcile_close_ledger"])
                    action["description"] += (
                        "; post_close_stage(target=case_id; payload={stage_id,idempotency_key,journal_lines}); "
                        "release_close_hold(target=case_id; payload={received_quantity,in_transit_quantity,disposition}); "
                        "reconcile_close_ledger(target=case_id; payload={posting_receipts}). "
                        "Read delivery_contract.close_execution_rules and get_incident.close_execution."
                    )
        self._allowed_names = {spec["name"] for spec in self._tool_specs}

    @property
    def tools(self) -> list[Json]:
        return deepcopy(self._tool_specs)

    def call(self, name: str, **arguments: Any) -> Json:
        if name not in self._allowed_names:
            critical = name == "execute_action"
            self._world._violation(
                (
                    "tool_scope_authorization_bypass"
                    if critical
                    else "tool_not_available_for_workflow"
                ),
                f"tool {name} is outside the {self._world.task.family} public capability scope",
                critical=critical,
            )
            result = {
                "ok": False,
                "error": (
                    "tool_scope_authorization_bypass"
                    if critical
                    else "tool_not_available_for_workflow"
                ),
                "available_tools": sorted(self._allowed_names),
                "clock_minute": self._world.minute,
            }
            return self._world._record(name, arguments, result)
        return self._world.call_tool(name, arguments)
