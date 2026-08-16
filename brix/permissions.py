from __future__ import annotations

from brix.domain import Approval, BrowserTask, PermissionDecision
from brix.task_store import TaskStore


class PermissionRequired(RuntimeError):
    def __init__(self, approval: Approval) -> None:
        self.approval = approval
        super().__init__(f"Approval required: {approval.id}")


class PermissionDenied(RuntimeError):
    pass


ACTION_RISK = {
    "snapshot": 0,
    "navigate": 0,
    "back": 0,
    "forward": 0,
    "reload": 0,
    "tabs": 0,
    "switch_tab": 0,
    "scroll": 0,
    "screenshot": 0,
    "wait_for": 0,
    "get_text": 0,
    "storage": 0,
    "assert_element": 0,
    "assert_text": 0,
    "assert_url": 0,
    "detect_challenge": 0,
    "click": 1,
    "fill": 1,
    "type": 1,
    "press": 1,
    "hover": 1,
    "select": 1,
    "close_tab": 1,
    "upload": 2,
    "submit": 2,
    "send_message": 2,
    "account_change": 2,
    "purchase": 3,
    "delete": 3,
}


class PermissionPolicy:
    def __init__(self, store: TaskStore) -> None:
        self.store = store

    def enforce(self, task: BrowserTask, action: str) -> int:
        risk = ACTION_RISK.get(action, 3)
        if action == "navigate" and not task.permissions.allow_navigation:
            raise PermissionDenied("Navigation is disabled for this task")
        if action == "submit" and not task.permissions.allow_form_submission:
            raise PermissionDenied("Form submission is disabled for this task")
        if action == "send_message" and not task.permissions.allow_messages:
            raise PermissionDenied("Messages are disabled for this task")
        if action == "account_change" and not task.permissions.allow_account_changes:
            raise PermissionDenied("Account changes are disabled for this task")
        if action == "purchase" and not task.permissions.allow_purchase:
            raise PermissionDenied("Purchases are disabled for this task")
        decision = getattr(task.permissions, f"level_{risk}")
        if decision == PermissionDecision.DENY:
            raise PermissionDenied(f"Risk level {risk} actions are denied")
        if decision == PermissionDecision.ASK:
            if self.store.consume_approval(task.id, action):
                return risk
            approval = self.store.save_approval(
                Approval(task_id=task.id, action=action, risk_level=risk)
            )
            raise PermissionRequired(approval)
        return risk
