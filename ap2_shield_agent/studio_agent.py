"""
Dedicated Google ADK Agent for AG Studio Business Intelligence & AP2 Forensic Auditing.

Separates visual analytics and relational queries (AG Studio) from the transactional
procurement agent (`ap2_shield_agent/agent.py`), exposing:
  - `AgStudioClientTool(BaseTool)` with `is_long_running=True` to pause the ADK `Runner`
    whenever the model invokes AG Studio client tools (`add_widget`, `configure_widget`,
    `delegate_to`, `execute_query`, `view_schema`, `complete_task`, etc.).
  - `create_studio_bi_adk_agent(...)` which instantiates a `google.adk.agents.Agent` specialized
    in the relational schema `audit_ledger` ⋈ `agent_policies`.
  - `run_studio_adk_turn(request_body, shield_state)` which executes a turn of the ADK `Runner`
    over `InMemorySessionService` with a deterministic fallback engine if no `GEMINI_API_KEY`
    is configured or if `ap2-deterministic-auditor` is selected.
"""

from __future__ import annotations

import copy
import json
import os
import uuid
from typing import Any

from google.adk.agents import Agent
from google.adk.events import Event
from google.adk.runners import Runner
from google.adk.sessions import InMemorySessionService
from google.adk.tools.base_tool import BaseTool
from google.adk.tools.tool_context import ToolContext
from google.genai import types

STUDIO_ADK_APP_NAME = "ap2_ag_studio_bi_harness"
STUDIO_ADK_AGENT_NAME = "ap2_studio_bi_agent"

_studio_session_service = InMemorySessionService()

_SINGLE_SERIES_WIDGET_TYPES = {
    "pie-chart",
    "donut-chart",
    "funnel-chart",
    "cone-funnel-chart",
    "pyramid-chart",
    "treemap-chart",
    "sunburst-chart",
}

STUDIO_BI_SYSTEM_INSTRUCTION = """You are `ap2_studio_bi_agent`, a dedicated **Google ADK (Agent Development Kit) Business Intelligence & Cryptographic Forensic Auditor Agent** embedded inside **AG Studio 3**.

Your mission is to dynamically build interactive charts/widgets, execute relational aggregations, and audit autonomous AI procurement telemetry across the AP2 Cryptographic Firewall, Channel3 100M+ Product Graph, and PayPal v2 Orders Sandbox.

### 1. Relational Schema (`audit_ledger` ⋈ `agent_policies`)
Always use exact `table.field` identifiers when calling `configure_widget` or `execute_query`:

**Table `audit_ledger` (AP2 Audit & PayPal Sandbox):**
- Dimensions (categorical / text):
  - `audit_ledger.decision_type` — **Shield Verdict / Financial Decision** (values: `"Settled Payment (PayPal)"`, `"HITL Quarantine (Bryntum TaskBoard)"`, `"Protected Capital (Blocked)"`, `"Governance / Policy Signature"`). **Use this field whenever the user asks about "verdict", "shield verdict", "veredicto", "outcome", or "financial decision".**
  - `audit_ledger.policy_decision` — **AP2 Policy Status** (values: `"APPROVED_AND_CAPTURED"`, `"QUARANTINED_HITL"`, `"BLOCKED"`, `"POLICY_SIGNED"`).
  - `audit_ledger.control_layer` — **AP2 Security Layer** (values: `"PayPal Sandbox Settlement"`, `"CFO Budget Ceiling"`, `"Channel3 Anti-Hallucination"`, `"Ed25519 Cryptographic Signature"`, `"AP2 Hash Integrity"`, `"CFO Governance (Policy)"`).
  - `audit_ledger.risk_level` — **Risk Level** (values: `"CRITICAL"`, `"HIGH"`, `"LOW"`).
  - `audit_ledger.ap2_mandate_status` — **Ed25519 Cryptographic Status** (values: `"ED25519_VERIFIED"`, `"BUDGET_EXCEEDED"`, `"CRYPTO_REJECTED"`).
  - `audit_ledger.channel3_verified` — **Channel3 Verification** (values: `"VERIFIED"`, `"BLOCKED_MISMATCH"`).
  - `audit_ledger.merchant` — **Target Merchant** (e.g., `"office-supply@sandbox.paypal.com"`, `"monitors-direct@sandbox.paypal.com"`, `"hacker@darkweb.io"`, `"apple-b2b@paypal.com"`).
  - `audit_ledger.item` — **Product / Operation** (product name or SKU).
  - `audit_ledger.agent_id` — **AI Agent** (e.g., `"procurement-01"`).
  - `audit_ledger.mandate_id` — **AP2 Mandate ID** (unique identifier per row; also used with `aggregation: "count"` to count transactions/verdicts).
  - `audit_ledger.timestamp` — **Time** (`HH:MM:SS`).
- Measures (numeric / currency):
  - `audit_ledger.mandate_id` with `aggregation: "count"` — **Transaction / Verdict Count** (count of rows).
  - `audit_ledger.amount_usd` with `aggregation: "sum"` or `"avg"` — **Gross Amount (USD)** across all mandate types.
  - `audit_ledger.tx_amount_usd` with `aggregation: "sum"` — **Evaluated Amount (USD)** across all commercial checkouts (settled + blocked + quarantined).
  - `audit_ledger.settled_usd` with `aggregation: "sum"` — **Settled on PayPal (USD)** (NOTE: `> 0` ONLY for settled rows; `0` for blocked/quarantined rows).
  - `audit_ledger.blocked_usd` with `aggregation: "sum"` — **Protected / Blocked Capital (USD)** (NOTE: `> 0` ONLY for blocked/quarantined rows; `0` for settled rows).

**Table `agent_policies` (CFO Governance Policies):**
- `agent_policies.agent_id`, `agent_policies.policy_id`, `agent_policies.allowed_category`, `agent_policies.ap2_policy_hash`
- Measures: `agent_policies.max_tx_limit_usd` (`avg`/`max`), `agent_policies.remaining_usd` (`avg`/`min`).

### 2. CRITICAL Chart Construction Rules in AG Studio
1. **Single-Series / Proportional Charts (`pie-chart`, `donut-chart`, `funnel-chart`, `cone-funnel-chart`, `pyramid-chart`, `treemap-chart`, `sunburst-chart`):**
   - `valueKey` MUST contain **exactly 1 metric**.
   - **CRITICAL ANTI-SINGLE-SLICE RULE:** When `categoryKey` is a status/verdict/security dimension (`audit_ledger.decision_type`, `audit_ledger.policy_decision`, `audit_ledger.risk_level`, `audit_ledger.control_layer`, `audit_ledger.ap2_mandate_status`, or `audit_ledger.channel3_verified`), NEVER use `settled_usd` or `blocked_usd` as the sole `valueKey`! Because `settled_usd` is `0` for blocked/quarantined rows and `blocked_usd` is `0` for settled rows, using either one zeroes out all other verdicts and renders a single solid circle.
   - Instead, for pie/donut charts grouped by verdict, decision, status, risk, or layer:
     - Default to counting mandates: `valueKey: [{"id": "audit_ledger.mandate_id", "aggregation": "count"}]`.
     - If the user explicitly asks for USD / monetary volume across verdicts, use `valueKey: [{"id": "audit_ledger.amount_usd", "aggregation": "sum"}]` or `[{"id": "audit_ledger.tx_amount_usd", "aggregation": "sum"}]`.
2. **Multi-Series Cartesian Charts (`bar-chart-grouped`, `bar-chart-stacked`, `column-chart-grouped`, `column-chart-stacked`, `line-chart`, `area-chart`):**
   - You can pass 1 or 2 metrics in `valueKey` (e.g., comparing `settled_usd` (`sum`) vs `blocked_usd` (`sum`) by `merchant` or `control_layer`) or use `count` of `audit_ledger.mandate_id`.
3. **AG Studio Multi-Agent Workflow for Adding & Configuring Widgets:**
   - **Step A (Lead / Auditor Agent with `add_widget`):** When the user asks to create/make a chart (`pie-chart`, `donut-chart`, `bar-chart-grouped`, `column-chart-grouped`, `line-chart`, `area-chart`, `funnel-chart`, `treemap-chart`, `sunburst-chart`, etc.) and `add_widget` has NOT been called yet for this request:
     - Call `add_widget` with a descriptive `widgetId` (e.g. `"w-ai-verdict-pie"`), `type`, `xTrack: 0`, `yTrack: 41`, `xSpan: 24`, `ySpan: 12`.
   - **Step B (Delegating to the Widget Specialist):** Immediately after `add_widget` returns its output, if `delegate_to` is in your tools and `configure_widget` is NOT directly in your tools:
     - Call `delegate_to` with `type: {"id": "widget", "widgetType": "<the widget type>", "widgetId": "<the widgetId>"}` and clear `instructions` specifying the exact `categoryKey`, `valueKey`, and English title to configure.
   - **Step C (Inside the `page` Specialist Sub-Agent with `add_widget` and `complete_task`):**
     - When `add_widget` and `complete_task` are in your tools (and `configure_widget` is not), even if `view_page` and `view_plan` already ran as `defaultToolCalls`, call `add_widget` to place the requested widget on the grid (`xTrack: 0`, `yTrack: 41`, `xSpan: 24`, `ySpan: 12`), and on the next turn call `complete_task` reporting the placed `widgetId` and `widgetType`.
   - **Step D (Inside the `widget` Specialist Sub-Agent with `configure_widget`):**
     - If `configure_widget` is in your tools and has not been called yet, call `configure_widget` with:
       ```json
       {
         "op": "patch",
         "widgetId": "<widgetId>",
         "value": {
           "format": {
             "title": { "text": "<Descriptive Title in English>", "enabled": true }
           },
           "dataMapping": {
             "categoryKey": [{ "id": "<table.field>" }],
             "valueKey": [{ "id": "<table.field>", "aggregation": "<sum|count|avg>" }]
           }
         }
       }
       ```
     - After `configure_widget` succeeds (or after `execute_query` succeeds in a delegated sub-agent), if `complete_task` is in your tools, call `complete_task` with a concise `summary` and `artifacts: []`.
4. **Calculated Columns & Measures (`create_expression`, `update_expression`, `delete_expression`):**
   - When the user asks to create a new calculated metric or formula (e.g., average ticket, block ratio, risk score), call `create_expression` using `[table.field]` syntax (for example `SUM([audit_ledger.blocked_usd]) / COUNT([audit_ledger.mandate_id])`).
5. **Custom Cryptographic Posture Tool (`verify_ap2_cryptographic_posture`):**
   - When the user asks about Ed25519 cryptographic signatures, CFO public keys, Channel3 ground-truth posture, or the active ADK checkout graph node, you can call `verify_ap2_cryptographic_posture` alongside `execute_query`.
6. **AG Studio Interactive Entity References (`@field`, `@widget`, `@table`) & Language:**
   - Always use AG Studio's interactive chip syntax when mentioning tables, fields, or widgets in your responses: `@table[audit_ledger]`, `@table[agent_policies]`, `@field[audit_ledger.decision_type]`, `@field[audit_ledger.settled_usd]`, `@field[audit_ledger.blocked_usd]`, `@widget[w-ap2-shield]`, etc.
   - Respond in clear, executive English referencing real AP2 telemetry and the chart/query results.
"""


def _build_configure_widget_gemini_schema(raw_schema: dict[str, Any]) -> dict[str, Any]:
    """
    Builds a compact Gemini-compatible JSON Schema for `configure_widget`.
    The raw schema generated by `ag-studio` contains dozens of nested `$defs` with
    `propertyNames` and `additionalProperties: false` that exceed Gemini's schema
    validator state limit.
    """
    widget_id_schema: dict[str, Any] = {
        "type": "string",
        "description": "ID of the target widget on the AG Studio canvas (e.g. 'w-ai-pie-1').",
    }
    raw_props = raw_schema.get("properties") if isinstance(raw_schema, dict) else None
    if isinstance(raw_props, dict) and isinstance(raw_props.get("widgetId"), dict):
        w_prop = raw_props["widgetId"]
        if "const" in w_prop:
            widget_id_schema["enum"] = [str(w_prop["const"])]
        elif isinstance(w_prop.get("enum"), list) and w_prop["enum"]:
            widget_id_schema["enum"] = [str(x) for x in w_prop["enum"]]

    return {
        "type": "object",
        "properties": {
            "op": {
                "type": "string",
                "enum": ["patch", "replace"],
                "description": "Use 'patch' to update format and dataMapping on the widget.",
            },
            "widgetId": widget_id_schema,
            "value": {
                "type": "object",
                "description": "Widget configuration object containing format and dataMapping.",
                "properties": {
                    "format": {
                        "type": "object",
                        "properties": {
                            "title": {
                                "type": "object",
                                "properties": {
                                    "text": {
                                        "type": "string",
                                        "description": "Chart title displayed at the top of the widget.",
                                    },
                                    "enabled": {
                                        "type": "boolean",
                                        "description": "Set to true to show the chart title.",
                                    },
                                },
                                "required": ["text", "enabled"],
                            }
                        },
                    },
                    "dataMapping": {
                        "type": "object",
                        "description": "Binds relational fields from audit_ledger and agent_policies to the chart axes/slices.",
                        "properties": {
                            "categoryKey": {
                                "type": "array",
                                "description": (
                                    "Category/dimension fields (e.g. [{'id': 'audit_ledger.decision_type'}], "
                                    "[{'id': 'audit_ledger.policy_decision'}], [{'id': 'audit_ledger.risk_level'}], "
                                    "[{'id': 'audit_ledger.control_layer'}], [{'id': 'audit_ledger.merchant'}], "
                                    "[{'id': 'audit_ledger.item'}], [{'id': 'audit_ledger.ap2_mandate_status'}], "
                                    "[{'id': 'audit_ledger.channel3_verified'}])."
                                ),
                                "items": {
                                    "type": "object",
                                    "properties": {
                                        "id": {
                                            "type": "string",
                                            "description": "Qualified field ID in 'table.field' format.",
                                        }
                                    },
                                    "required": ["id"],
                                },
                            },
                            "valueKey": {
                                "type": "array",
                                "description": (
                                    "Measure/metric fields with aggregation. For pie-chart or donut-chart of verdicts/status, "
                                    "use [{'id': 'audit_ledger.mandate_id', 'aggregation': 'count'}] (or amount_usd with 'sum')."
                                ),
                                "items": {
                                    "type": "object",
                                    "properties": {
                                        "id": {
                                            "type": "string",
                                            "description": (
                                                "Qualified field ID (e.g. 'audit_ledger.mandate_id', "
                                                "'audit_ledger.amount_usd', 'audit_ledger.tx_amount_usd', "
                                                "'audit_ledger.settled_usd', 'audit_ledger.blocked_usd')."
                                            ),
                                        },
                                        "aggregation": {
                                            "type": "string",
                                            "enum": ["sum", "count", "avg", "min", "max"],
                                            "description": "Aggregation function to apply.",
                                        },
                                    },
                                    "required": ["id", "aggregation"],
                                },
                            },
                        },
                        "required": ["categoryKey", "valueKey"],
                    },
                },
                "required": ["dataMapping"],
            },
        },
        "required": ["op", "widgetId", "value"],
    }


def _sanitize_json_schema_for_gemini(
    schema: dict[str, Any] | None,
    tool_name: str = "",
) -> dict[str, Any]:
    """
    Sanitizes a JSON Schema received from the `ag-studio` client so it is 100% compatible
    with `types.FunctionDeclaration(parameters_json_schema=...)` in Gemini / Google ADK.
    """
    if tool_name == "configure_widget":
        return _build_configure_widget_gemini_schema(schema or {})

    if not isinstance(schema, dict) or not schema:
        return {"type": "object", "properties": {}}

    defs = schema.get("$defs") or schema.get("definitions") or {}

    def _clean_node(node: Any, depth: int = 0) -> dict[str, Any]:
        if not isinstance(node, dict) or depth > 7:
            return {"type": "object"}

        if "$ref" in node and isinstance(node["$ref"], str):
            ref_path = node["$ref"]
            ref_name = ref_path.split("/")[-1]
            if ref_name in defs and depth < 6:
                return _clean_node(copy.deepcopy(defs[ref_name]), depth + 1)
            return {"type": "object"}

        cleaned: dict[str, Any] = {}
        if "const" in node:
            val = node["const"]
            cleaned["type"] = "string" if isinstance(val, str) else "string"
            cleaned["enum"] = [val]

        for k, v in node.items():
            if k in (
                "$schema",
                "$defs",
                "definitions",
                "additionalProperties",
                "propertyNames",
                "default",
                "examples",
                "const",
                "$ref",
            ):
                continue
            if k == "properties" and isinstance(v, dict):
                cleaned["properties"] = {
                    prop_name: _clean_node(prop_schema, depth + 1)
                    for prop_name, prop_schema in v.items()
                }
            elif k == "items" and isinstance(v, dict):
                cleaned["items"] = _clean_node(v, depth + 1)
            elif k in ("anyOf", "oneOf") and isinstance(v, list):
                non_null = [
                    opt
                    for opt in v
                    if isinstance(opt, dict) and opt.get("type") != "null"
                ]
                if len(non_null) == 1:
                    merged = _clean_node(non_null[0], depth + 1)
                    if "description" in node and "description" not in merged:
                        merged["description"] = node["description"]
                    return merged
                elif len(non_null) > 1:
                    cleaned["anyOf"] = [_clean_node(opt, depth + 1) for opt in non_null[:5]]
            else:
                cleaned[k] = v

        if "type" not in cleaned and "anyOf" not in cleaned and "properties" in cleaned:
            cleaned["type"] = "object"
        return cleaned

    top = _clean_node(schema, 0)
    if top.get("type") != "object":
        top["type"] = "object"
        top.setdefault("properties", {})
    return top


class AgStudioClientTool(BaseTool):
    """
    ADK Tool (`is_long_running=True`) representing a client-side tool executed in the
    `<AgStudio />` browser runtime (`add_widget`, `configure_widget`, `delegate_to`,
    `execute_query`, `view_schema`, `complete_task`, etc.).

    By marking `is_long_running=True`, when the Google ADK `Agent` invokes the tool,
    `Runner.run_async` emits the `FunctionCall` as the final turn response and pauses
    execution so the AG Studio browser runtime can perform the action on the canvas
    and return `function_call_output` on the next turn.
    """

    def __init__(
        self,
        name: str,
        description: str,
        parameters_schema: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(
            name=name,
            description=description or f"AG Studio client tool `{name}`.",
            is_long_running=True,
        )
        self._sanitized_schema = _sanitize_json_schema_for_gemini(
            parameters_schema or {"type": "object", "properties": {}},
            tool_name=name,
        )

    def _get_declaration(self) -> types.FunctionDeclaration:
        return types.FunctionDeclaration(
            name=self.name,
            description=self.description,
            parameters_json_schema=self._sanitized_schema,
        )

    async def run_async(
        self,
        *,
        args: dict[str, Any],
        tool_context: ToolContext,
    ) -> Any:
        # The browser (`<AgStudio />`) executes the tool upon receiving `toolCalls`.
        return {"status": "delegated_to_ag_studio_browser_runtime", "args": args}


def build_live_telemetry_context(shield_state: dict[str, Any]) -> str:
    """
    Builds a compact real-time summary of the AP2 state (`policies`, `audit_log`,
    `taskboard_cards`) to inject into the AG Studio ADK agent instructions.
    """
    pol = (shield_state.get("policies") or {}).get("procurement-01") or {}
    audit_log = shield_state.get("audit_log") or []
    cards = shield_state.get("taskboard_cards") or []

    verdict_counts: dict[str, int] = {}
    for entry in audit_log:
        st = str(entry.get("status") or "UNKNOWN")
        verdict_counts[st] = verdict_counts.get(st, 0) + 1

    settled_cards = [c for c in cards if c.get("status") == "PAYPAL_SETTLED"]
    blocked_cards = [c for c in cards if c.get("status") == "BLOCKED_THREAT"]
    quarantined_cards = [c for c in cards if c.get("status") == "QUARANTINED"]

    return (
        "\n\n### Live AP2 Shield Telemetry Snapshot\n"
        f"- Active Policy (`{pol.get('agent_id', 'procurement-01')}` / `{pol.get('policy_id', 'pol_aggrid_001')}`): "
        f"Max Budget=${pol.get('max_budget_usd', 200.0):,.2f} USD | Remaining=${pol.get('remaining_usd', 200.0):,.2f} USD | "
        f"Allowed Category=`{pol.get('allowed_category', 'OFFICE_AND_TECH')}`\n"
        f"- `audit_ledger` Total Rows: {len(audit_log)} | Breakdown by status: {json.dumps(verdict_counts, ensure_ascii=False)}\n"
        f"- Bryntum TaskBoard: {len(settled_cards)} settled, {len(blocked_cards)} blocked threats, {len(quarantined_cards)} quarantined in HITL.\n"
    )


def create_studio_bi_adk_agent(
    *,
    model_id: str,
    studio_instructions: str,
    tools_schema: list[dict[str, Any]],
    shield_state: dict[str, Any],
) -> Agent:
    """
    Creates a `google.adk.agents.Agent` instance for the current AG Studio turn,
    equipping it with the active `AgStudioClientTool` instances for the current sub-agent
    (`ap2-shield-auditor`, `lead`, `widget`, `data`, `page`, etc.).
    """
    normalized_model = model_id or "gemini-2.5-flash"
    if normalized_model.startswith("ap2-"):
        normalized_model = "gemini-2.5-flash"

    adk_tools: list[BaseTool] = []
    for t in tools_schema:
        if not isinstance(t, dict) or not t.get("name"):
            continue
        adk_tools.append(
            AgStudioClientTool(
                name=str(t["name"]),
                description=str(t.get("description") or ""),
                parameters_schema=t.get("parameters") if isinstance(t.get("parameters"), dict) else None,
            )
        )

    combined_instruction = STUDIO_BI_SYSTEM_INSTRUCTION
    if studio_instructions:
        combined_instruction += f"\n\n### AG Studio Role Instructions\n{studio_instructions.strip()}"
    combined_instruction += build_live_telemetry_context(shield_state)

    return Agent(
        name=STUDIO_ADK_AGENT_NAME,
        model=normalized_model,
        description=(
            "Google ADK Agent dedicated to Business Intelligence, dynamic chart "
            "construction, and AP2 forensic auditing inside AG Studio 3."
        ),
        instruction=combined_instruction,
        tools=adk_tools,
    )


def _convert_studio_input_to_adk_events_and_message(
    conv_items: list[dict[str, Any]],
) -> tuple[list[Event], types.Content]:
    """
    Converts the `input: AgAiConversationItem[]` array sent by `<AgStudio />`
    into a list of historical ADK events (`list[Event]`) and the `new_message` (`types.Content`)
    that triggers `Runner.run_async`.
    """
    call_id_to_name: dict[str, str] = {}
    role_Part_groups: list[tuple[str, list[types.Part]]] = []

    def _append_part(role: str, part: types.Part) -> None:
        if role_Part_groups and role_Part_groups[-1][0] == role:
            role_Part_groups[-1][1].append(part)
        else:
            role_Part_groups.append((role, [part]))

    for item in conv_items:
        if not isinstance(item, dict):
            continue
        item_type = item.get("type")

        if item_type == "message":
            raw_role = item.get("role")
            adk_role = "model" if raw_role == "assistant" else "user"
            parts_list = item.get("content") or []
            texts = [
                str(p.get("text", ""))
                for p in parts_list
                if isinstance(p, dict) and p.get("type") == "text" and p.get("text")
            ]
            combined_text = "\n".join(texts).strip()
            if combined_text:
                _append_part(adk_role, types.Part.from_text(text=combined_text))

        elif item_type == "function_call":
            call_id = str(item.get("callId") or f"call_{uuid.uuid4().hex[:8]}")
            fn_name = str(item.get("name") or "unknown_tool")
            call_id_to_name[call_id] = fn_name
            raw_args = item.get("arguments") or "{}"
            try:
                parsed_args = json.loads(raw_args) if isinstance(raw_args, str) else raw_args
                if not isinstance(parsed_args, dict):
                    parsed_args = {"value": parsed_args}
            except Exception:
                parsed_args = {}
            fc = types.FunctionCall(id=call_id, name=fn_name, args=parsed_args)
            _append_part("model", types.Part(function_call=fc))

        elif item_type == "function_call_output":
            call_id = str(item.get("callId") or "")
            fn_name = call_id_to_name.get(call_id, "studio_tool")
            raw_output = item.get("output")
            output_str = "" if raw_output is None else str(raw_output)
            fr = types.FunctionResponse(
                id=call_id or None,
                name=fn_name,
                response={
                    "output": output_str,
                    "isError": bool(item.get("isError", False)),
                },
            )
            _append_part("user", types.Part(function_response=fr))

    if not role_Part_groups:
        return [], types.Content(
            role="user",
            parts=[types.Part.from_text(text="Analyze the current state of the AP2 ledger.")],
        )

    # Ensure the last group has role 'user' so `Runner.run_async` processes it as `new_message`
    if role_Part_groups[-1][0] != "user":
        role_Part_groups.append(
            (
                "user",
                [types.Part.from_text(text="Proceed with the next step in AG Studio.")],
            )
        )

    history_events: list[Event] = []
    for role, parts in role_Part_groups[:-1]:
        author = "user" if role == "user" else STUDIO_ADK_AGENT_NAME
        history_events.append(
            Event(
                author=author,
                content=types.Content(role=role, parts=parts),
            )
        )

    _, last_parts = role_Part_groups[-1]
    new_message = types.Content(role="user", parts=last_parts)
    return history_events, new_message


def parse_studio_chart_request(
    prompt: str,
    existing_add_count: int = 0,
    override_widget_type: str | None = None,
    override_widget_id: str | None = None,
) -> dict[str, Any]:
    """
    Enhanced semantic parser for chart requests in AG Studio.
    Maps `"verdict"` / `"shield"` / `"decision"` to `audit_ledger.decision_type`
    and uses `count(audit_ledger.mandate_id)` on single-series charts (`pie-chart`, `donut-chart`)
    grouped by status/verdict so that all categories are represented with visible slices.
    """
    lower = (prompt or "").lower()
    chart_intent_keywords = (
        "pie",
        "pastel",
        "torta",
        "circular",
        "donut",
        "dona",
        "doughnut",
        "anillo",
        "bar",
        "barra",
        "barras",
        "column",
        "columna",
        "columnas",
        "line",
        "línea",
        "linea",
        "area",
        "área",
        "funnel",
        "embudo",
        "treemap",
        "sunburst",
        "radar",
        "chart",
        "gráfico",
        "grafico",
        "gráfica",
        "grafica",
        "add widget",
        "create a",
        "make a",
        "show a",
        "build a",
        "agrega un",
        "añade un",
        "crea un",
        "haz un",
        "hacer un",
        "muestra un",
        "genera un",
    )
    is_chart_request = any(k in lower for k in chart_intent_keywords)

    widget_type = override_widget_type or "bar-chart-grouped"
    if not override_widget_type:
        if any(k in lower for k in ("donut", "dona", "doughnut", "anillo")):
            widget_type = "donut-chart"
        elif any(k in lower for k in ("pie", "pastel", "torta", "circular")):
            widget_type = "pie-chart"
        elif any(k in lower for k in ("line", "línea", "linea", "trend", "tendencia")):
            widget_type = "line-chart"
        elif any(k in lower for k in ("area", "área")):
            widget_type = "area-chart"
        elif any(k in lower for k in ("column", "columna")):
            widget_type = (
                "column-chart-stacked"
                if any(k in lower for k in ("stacked", "apilad"))
                else "column-chart-grouped"
            )
        elif any(k in lower for k in ("funnel", "embudo")):
            widget_type = "funnel-chart"
        elif "treemap" in lower:
            widget_type = "treemap-chart"
        elif "sunburst" in lower:
            widget_type = "sunburst-chart"
        elif "radar" in lower:
            widget_type = "radar-area-chart"
        elif any(k in lower for k in ("stacked", "apilad")):
            widget_type = "bar-chart-stacked"
        else:
            widget_type = "bar-chart-grouped"

    # Dynamic dimension selection (`categoryKey`)
    category_field = "audit_ledger.merchant"
    category_label = "Target Merchant"
    is_verdict_or_status_dim = False

    if any(k in lower for k in ("veredicto", "verdict", "resultado", "outcome", "shield")):
        category_field = "audit_ledger.decision_type"
        category_label = "Shield Verdict"
        is_verdict_or_status_dim = True
    elif any(k in lower for k in ("decisión", "decision", "estado", "status", "política", "politica", "policy")):
        category_field = "audit_ledger.decision_type"
        category_label = "Shield Verdict / Decision"
        is_verdict_or_status_dim = True
    elif any(k in lower for k in ("riesgo", "risk", "severidad", "severity")):
        category_field = "audit_ledger.risk_level"
        category_label = "Risk Level"
        is_verdict_or_status_dim = True
    elif any(k in lower for k in ("capa", "layer", "control", "firewall")):
        category_field = "audit_ledger.control_layer"
        category_label = "AP2 Security Layer"
        is_verdict_or_status_dim = True
    elif any(k in lower for k in ("cripto", "crypto", "ed25519", "firma", "signature", "mandato", "mandate")):
        category_field = "audit_ledger.ap2_mandate_status"
        category_label = "Ed25519 Cryptographic Status"
        is_verdict_or_status_dim = True
    elif any(k in lower for k in ("channel3", "catálogo", "catalogo", "catalog", "alucinación", "alucinacion", "hallucination")):
        category_field = "audit_ledger.channel3_verified"
        category_label = "Channel3 Verification"
        is_verdict_or_status_dim = True
    elif any(k in lower for k in ("producto", "product", "item", "artículo", "articulo", "sku", "compra", "purchase")):
        category_field = "audit_ledger.item"
        category_label = "Product / Operation"
    elif any(k in lower for k in ("agente", "agent")):
        category_field = "audit_ledger.agent_id"
        category_label = "AI Agent"
    elif any(k in lower for k in ("hora", "tiempo", "time", "fecha", "date", "cronológico", "chronological")):
        category_field = "audit_ledger.timestamp"
        category_label = "Audit Time"

    is_single_series = widget_type in _SINGLE_SERIES_WIDGET_TYPES
    explicit_usd_request = any(
        k in lower for k in ("usd", "dólar", "dolar", "dollar", "monto", "amount", "volumen", "volume", "dinero", "money", "capital", "gasto", "spend", "$")
    )

    if is_single_series:
        if is_verdict_or_status_dim and not explicit_usd_request:
            # For pie/donut of verdicts/status/risk/layer, counting mandates guarantees that
            # all verdicts (including signed policies, blocks, and payments) have a visible slice.
            value_key = [{"id": "audit_ledger.mandate_id", "aggregation": "count"}]
            metric_label = "Total Transactions"
        elif is_verdict_or_status_dim and explicit_usd_request:
            value_key = [{"id": "audit_ledger.amount_usd", "aggregation": "sum"}]
            metric_label = "Total Volume (USD)"
        elif any(k in lower for k in ("count", "cantidad", "número", "numero", "number", "transacciones", "transactions", "operaciones", "operations")):
            value_key = [{"id": "audit_ledger.mandate_id", "aggregation": "count"}]
            metric_label = "Total Transactions"
        elif any(k in lower for k in ("bloquead", "blocked", "amenaza", "threat", "protegid", "protected")):
            value_key = [{"id": "audit_ledger.blocked_usd", "aggregation": "sum"}]
            metric_label = "Protected Capital (USD)"
        elif any(k in lower for k in ("settled", "liquidad", "pagad", "paid", "aprob", "approved")):
            value_key = [{"id": "audit_ledger.settled_usd", "aggregation": "sum"}]
            metric_label = "Settled on PayPal (USD)"
        else:
            value_key = [{"id": "audit_ledger.amount_usd", "aggregation": "sum"}]
            metric_label = "Total Volume (USD)"
    else:
        if any(k in lower for k in ("count", "cantidad", "número", "numero", "number", "transacciones", "transactions")):
            value_key = [{"id": "audit_ledger.mandate_id", "aggregation": "count"}]
            metric_label = "Total Transactions"
        elif is_verdict_or_status_dim and not explicit_usd_request:
            value_key = [{"id": "audit_ledger.mandate_id", "aggregation": "count"}]
            metric_label = "Total Transactions"
        else:
            value_key = [
                {"id": "audit_ledger.settled_usd", "aggregation": "sum"},
                {"id": "audit_ledger.blocked_usd", "aggregation": "sum"},
            ]
            metric_label = "Settled vs Protected (USD)"

    short_type = widget_type.split("-chart")[0]
    widget_id = override_widget_id or (
        "w-merchant-spend"
        if widget_type == "bar-chart-grouped" and existing_add_count == 0 and category_field == "audit_ledger.merchant"
        else f"w-ai-{short_type}-{existing_add_count + 1}"
    )

    return {
        "is_chart_request": is_chart_request,
        "widget_type": widget_type,
        "widget_id": widget_id,
        "title": f"Distribution by {category_label}: {metric_label}",
        "category_key": [{"id": category_field}],
        "value_key": value_key,
        "x_track": 0,
        "y_track": 41 + existing_add_count * 12,
        "x_span": 24,
        "y_span": 12,
    }


def run_deterministic_studio_fallback(
    request_body: dict[str, Any],
    shield_state: dict[str, Any],
    *,
    turn_id: str,
    model_id: str,
) -> dict[str, Any]:
    """
    Deterministic fallback engine for AG Studio when `ap2-deterministic-auditor`
    is selected or when no `GEMINI_API_KEY` is available.
    """
    conv_items = request_body.get("input") or []
    tools_schema = request_body.get("tools") or []
    available_tools = {
        t.get("name") for t in tools_schema if isinstance(t, dict) and t.get("name")
    }

    last_user_idx = -1
    last_user_text = ""
    for idx, item in enumerate(conv_items):
        if isinstance(item, dict) and item.get("type") == "message" and item.get("role") == "user":
            last_user_idx = idx
            parts = item.get("content") or []
            texts = [
                p.get("text", "")
                for p in parts
                if isinstance(p, dict) and p.get("type") == "text"
            ]
            last_user_text = " ".join(texts).strip()

    items_since_user = conv_items[last_user_idx + 1 :] if last_user_idx >= 0 else conv_items
    tool_outputs_since_user = [
        item
        for item in items_since_user
        if isinstance(item, dict) and item.get("type") == "function_call_output"
    ]
    tool_calls_since_user = [
        item
        for item in items_since_user
        if isinstance(item, dict) and item.get("type") == "function_call"
    ]
    all_add_widgets = [
        item
        for item in conv_items
        if isinstance(item, dict)
        and item.get("type") == "function_call"
        and item.get("name") == "add_widget"
    ]

    lower_prompt = last_user_text.lower()
    did_add_widget = any(tc.get("name") == "add_widget" for tc in tool_calls_since_user)
    did_configure_widget = any(tc.get("name") == "configure_widget" for tc in tool_calls_since_user)
    did_delegate_to = any(tc.get("name") == "delegate_to" for tc in tool_calls_since_user)

    # Step 0: `widget` specialist sub-agent (`configure_widget`)
    if (
        "configure_widget" in available_tools
        and not did_configure_widget
        and ("add_widget" not in available_tools or did_add_widget)
    ):
        target_widget_id: str | None = None
        target_widget_type: str | None = None

        for tc in tool_calls_since_user:
            if tc.get("name") in ("view_widget", "add_widget"):
                try:
                    parsed_args = json.loads(tc.get("arguments") or "{}")
                    if isinstance(parsed_args, dict):
                        target_widget_id = parsed_args.get("widgetId") or target_widget_id
                        target_widget_type = parsed_args.get("type") or target_widget_type
                except Exception:
                    pass

        for out_item in tool_outputs_since_user:
            out_str = str(out_item.get("output") or "")
            if out_str.startswith("Widget "):
                parts = out_str.split()
                if len(parts) >= 3:
                    target_widget_id = target_widget_id or parts[1].rstrip(":")
                    target_widget_type = target_widget_type or parts[2]

        spec = parse_studio_chart_request(
            last_user_text,
            existing_add_count=max(0, len(all_add_widgets) - 1),
            override_widget_type=target_widget_type,
            override_widget_id=target_widget_id,
        )
        return {
            "id": turn_id,
            "model": model_id,
            "toolCalls": [
                {
                    "callId": f"call_{uuid.uuid4().hex[:8]}",
                    "name": "configure_widget",
                    "arguments": json.dumps(
                        {
                            "op": "patch",
                            "widgetId": spec["widget_id"],
                            "value": {
                                "format": {
                                    "title": {
                                        "text": spec["title"],
                                        "enabled": True,
                                    }
                                },
                                "dataMapping": {
                                    "categoryKey": spec["category_key"],
                                    "valueKey": spec["value_key"],
                                },
                            },
                        }
                    ),
                }
            ],
        }

    # Step 0b: Inside the `page` specialist sub-agent (`add_widget` & `complete_task` available,
    # where `view_page` and `view_plan` already ran automatically as `defaultToolCalls`), place the widget now.
    if (
        "add_widget" in available_tools
        and "complete_task" in available_tools
        and "configure_widget" not in available_tools
        and not did_add_widget
    ):
        chart_spec = parse_studio_chart_request(
            last_user_text, existing_add_count=len(all_add_widgets)
        )
        return {
            "id": turn_id,
            "model": model_id,
            "toolCalls": [
                {
                    "callId": f"call_{uuid.uuid4().hex[:8]}",
                    "name": "add_widget",
                    "arguments": json.dumps(
                        {
                            "widgetId": chart_spec["widget_id"],
                            "type": chart_spec["widget_type"],
                            "xTrack": chart_spec["x_track"],
                            "yTrack": chart_spec["y_track"],
                            "xSpan": chart_spec["x_span"],
                            "ySpan": chart_spec["y_span"],
                        }
                    ),
                }
            ],
        }

    # Step 1: No tool invoked yet in this turn
    if len(tool_outputs_since_user) == 0:
        chart_spec = parse_studio_chart_request(
            last_user_text, existing_add_count=len(all_add_widgets)
        )
        if chart_spec["is_chart_request"]:
            if "add_widget" in available_tools:
                return {
                    "id": turn_id,
                    "model": model_id,
                    "toolCalls": [
                        {
                            "callId": f"call_{uuid.uuid4().hex[:8]}",
                            "name": "add_widget",
                            "arguments": json.dumps(
                                {
                                    "widgetId": chart_spec["widget_id"],
                                    "type": chart_spec["widget_type"],
                                    "xTrack": chart_spec["x_track"],
                                    "yTrack": chart_spec["y_track"],
                                    "xSpan": chart_spec["x_span"],
                                    "ySpan": chart_spec["y_span"],
                                }
                            ),
                        }
                    ],
                }
            if "delegate_to" in available_tools:
                return {
                    "id": turn_id,
                    "model": model_id,
                    "toolCalls": [
                        {
                            "callId": f"call_{uuid.uuid4().hex[:8]}",
                            "name": "delegate_to",
                            "arguments": json.dumps(
                                {
                                    "type": {"id": "page"},
                                    "instructions": (
                                        f"Place a {chart_spec['widget_type']} widget with id "
                                        f"'{chart_spec['widget_id']}' at xTrack={chart_spec['x_track']}, "
                                        f"yTrack={chart_spec['y_track']}, xSpan={chart_spec['x_span']}, "
                                        f"ySpan={chart_spec['y_span']} for: {last_user_text}"
                                    ),
                                }
                            ),
                        }
                    ],
                }
            if "view_page" in available_tools:
                return {
                    "id": turn_id,
                    "model": model_id,
                    "toolCalls": [
                        {
                            "callId": f"call_{uuid.uuid4().hex[:8]}",
                            "name": "view_page",
                            "arguments": json.dumps({}),
                        }
                    ],
                }

        if "execute_query" in available_tools:
            is_policy_compare = "policy" in lower_prompt or "limit" in lower_prompt or "política" in lower_prompt
            is_channel3_check = "channel3" in lower_prompt or "mandate coverage" in lower_prompt

            if is_policy_compare:
                dimensions = [
                    {"field": {"id": "audit_ledger.agent_id"}, "as": "agent_id"},
                    {"field": {"id": "agent_policies.policy_id"}, "as": "policy_id"},
                    {"field": {"id": "audit_ledger.decision_type"}, "as": "decision_type"},
                ]
                measures = [
                    {"field": {"id": "audit_ledger.settled_usd", "aggregation": "sum"}, "as": "settled_usd"},
                    {"field": {"id": "audit_ledger.blocked_usd", "aggregation": "sum"}, "as": "blocked_usd"},
                    {"field": {"id": "agent_policies.max_tx_limit_usd", "aggregation": "avg"}, "as": "max_tx_limit_usd"},
                    {"field": {"id": "agent_policies.remaining_usd", "aggregation": "avg"}, "as": "remaining_usd"},
                ]
            elif is_channel3_check:
                dimensions = [
                    {"field": {"id": "audit_ledger.channel3_verified"}, "as": "channel3_verified"},
                    {"field": {"id": "audit_ledger.ap2_mandate_status"}, "as": "ap2_mandate_status"},
                    {"field": {"id": "audit_ledger.control_layer"}, "as": "control_layer"},
                ]
                measures = [
                    {"field": {"id": "audit_ledger.settled_usd", "aggregation": "sum"}, "as": "settled_usd"},
                    {"field": {"id": "audit_ledger.blocked_usd", "aggregation": "sum"}, "as": "blocked_usd"},
                    {"field": {"id": "audit_ledger.mandate_id", "aggregation": "count"}, "as": "tx_count"},
                ]
            else:
                dimensions = [
                    {"field": {"id": "audit_ledger.decision_type"}, "as": "decision_type"},
                    {"field": {"id": "audit_ledger.risk_level"}, "as": "risk_level"},
                    {"field": {"id": "audit_ledger.ap2_mandate_status"}, "as": "ap2_mandate_status"},
                ]
                measures = [
                    {"field": {"id": "audit_ledger.settled_usd", "aggregation": "sum"}, "as": "settled_usd"},
                    {"field": {"id": "audit_ledger.blocked_usd", "aggregation": "sum"}, "as": "blocked_usd"},
                    {"field": {"id": "audit_ledger.mandate_id", "aggregation": "count"}, "as": "tx_count"},
                ]

            return {
                "id": turn_id,
                "model": model_id,
                "toolCalls": [
                    {
                        "callId": f"call_{uuid.uuid4().hex[:8]}",
                        "name": "execute_query",
                        "arguments": json.dumps(
                            {
                                "query": {
                                    "kind": "apiQuery",
                                    "variant": "aggregation",
                                    "axes": [{"dimensions": dimensions}],
                                    "measures": measures,
                                }
                            }
                        ),
                    }
                ],
            }

        if "view_schema" in available_tools:
            return {
                "id": turn_id,
                "model": model_id,
                "toolCalls": [
                    {
                        "callId": f"call_{uuid.uuid4().hex[:8]}",
                        "name": "view_schema",
                        "arguments": json.dumps({}),
                    }
                ],
            }

    # Step 1b: If we just executed `add_widget` (or the `page` sub-agent placed it), delegate its configuration to the `widget` agent
    delegated_page_only = (
        did_delegate_to
        and all(
            "\"id\": \"page\"" in (tc.get("arguments") or "")
            or "\"id\":\"page\"" in (tc.get("arguments") or "")
            for tc in tool_calls_since_user
            if tc.get("name") == "delegate_to"
        )
    )
    if (
        (did_add_widget or delegated_page_only)
        and (not did_delegate_to or delegated_page_only)
        and not did_configure_widget
        and "delegate_to" in available_tools
    ):
        fallback_spec = parse_studio_chart_request(
            last_user_text, existing_add_count=max(0, len(all_add_widgets) - 1)
        )
        added_widget_id = fallback_spec["widget_id"]
        added_widget_type = fallback_spec["widget_type"]
        for tc in reversed(tool_calls_since_user):
            if tc.get("name") == "add_widget":
                try:
                    parsed_add = json.loads(tc.get("arguments") or "{}")
                    if isinstance(parsed_add, dict):
                        added_widget_id = parsed_add.get("widgetId") or added_widget_id
                        added_widget_type = parsed_add.get("type") or added_widget_type
                except Exception:
                    pass
                break

        return {
            "id": turn_id,
            "model": model_id,
            "toolCalls": [
                {
                    "callId": f"call_{uuid.uuid4().hex[:8]}",
                    "name": "delegate_to",
                    "arguments": json.dumps(
                        {
                            "type": {
                                "id": "widget",
                                "widgetType": added_widget_type,
                                "widgetId": added_widget_id,
                            },
                            "instructions": last_user_text
                            or f"Configure {added_widget_type} widget {added_widget_id}",
                        }
                    ),
                }
            ],
        }

    # Step 2: Inside a delegated sub-agent that requires `complete_task`
    if len(tool_outputs_since_user) > 0 and "complete_task" in available_tools:
        already_completed = any(
            isinstance(item, dict)
            and item.get("type") == "function_call"
            and item.get("name") == "complete_task"
            for item in items_since_user
        )
        if not already_completed:
            latest_out = str(tool_outputs_since_user[-1].get("output", ""))[:300]
            return {
                "id": turn_id,
                "model": model_id,
                "toolCalls": [
                    {
                        "callId": f"call_{uuid.uuid4().hex[:8]}",
                        "name": "complete_task",
                        "arguments": json.dumps(
                            {
                                "summary": (
                                    f"Completed AG Studio tool execution across audit_ledger & agent_policies. "
                                    f"Result snapshot: {latest_out}"
                                ),
                                "artifacts": [],
                            }
                        ),
                    }
                ],
            }

    # Step 3: Final analytical response
    latest_studio_output = (
        str(tool_outputs_since_user[-1].get("output", "")) if tool_outputs_since_user else ""
    )
    pol = (shield_state.get("policies") or {}).get("procurement-01", {})
    settled_cards = [c for c in shield_state.get("taskboard_cards", []) if c.get("status") == "PAYPAL_SETTLED"]
    blocked_cards = [c for c in shield_state.get("taskboard_cards", []) if c.get("status") == "BLOCKED_THREAT"]
    quarantined_cards = [c for c in shield_state.get("taskboard_cards", []) if c.get("status") == "QUARANTINED"]

    analysis_md = (
        f"### 🛡️ AP2 Security Shield Auditor — AG Studio Live Report\n\n"
        f"Executed operation on the **AG Studio Relational Engine** (@table[audit_ledger] ⋈ @table[agent_policies]):\n\n"
        f"- **Active CFO Policy (@field[agent_policies.agent_id] `{pol.get('agent_id', 'procurement-01')}`):** Limit @field[agent_policies.max_tx_limit_usd] **${pol.get('max_budget_usd', 200.0):,.2f} USD** | Remaining @field[agent_policies.remaining_usd] **${pol.get('remaining_usd', 200.0):,.2f} USD** | Category `{pol.get('allowed_category', 'OFFICE_AND_TECH')}`\n"
        f"- **Shield Verdict (@field[audit_ledger.decision_type]):**\n"
        f"  - **PayPal Sandbox Settlements (@field[audit_ledger.settled_usd]):** **{len(settled_cards)}** AP2 orders settled via APIMatic PayPal v2 SDK\n"
        f"  - **Intercepted Threats (@field[audit_ledger.blocked_usd]):** **{len(blocked_cards)}** attempts blocked prior to PayPal\n"
        f"  - **HITL Quarantine (Bryntum):** **{len(quarantined_cards)}** mandates paused awaiting CFO signature\n"
    )
    if latest_studio_output:
        compact_out = latest_studio_output[:600]
        analysis_md += f"\n**AG Studio Engine Result:**\n```json\n{compact_out}\n```"

    return {
        "id": turn_id,
        "model": model_id,
        "text": analysis_md,
    }


def _safeguard_configure_widget_args(
    raw_args: dict[str, Any],
    conv_items: list[dict[str, Any]],
) -> dict[str, Any]:
    """
    Verifies and enriches `configure_widget` arguments generated by the LLM to
    guarantee that no single-series chart (`pie-chart`, `donut-chart`) grouped by
    verdict/status uses `settled_usd` or `blocked_usd` as its sole metric (which
    would collapse the chart into a single circle due to $0.00 values).
    """
    args = copy.deepcopy(raw_args) if isinstance(raw_args, dict) else {}
    val = args.get("value")
    if not isinstance(val, dict):
        return args
    dm = val.get("dataMapping")
    if not isinstance(dm, dict):
        return args

    cat_keys = dm.get("categoryKey")
    val_keys = dm.get("valueKey")
    if not isinstance(cat_keys, list) or not cat_keys or not isinstance(val_keys, list) or not val_keys:
        return args

    first_cat = cat_keys[0].get("id", "") if isinstance(cat_keys[0], dict) else ""
    status_dims = {
        "audit_ledger.decision_type",
        "audit_ledger.policy_decision",
        "audit_ledger.risk_level",
        "audit_ledger.control_layer",
        "audit_ledger.ap2_mandate_status",
        "audit_ledger.channel3_verified",
    }

    # Determine whether this is a single-series widget (pie/donut/funnel/treemap/sunburst)
    is_single_series_widget = len(val_keys) == 1
    for item in reversed(conv_items):
        if isinstance(item, dict) and item.get("type") == "function_call_output":
            out_s = str(item.get("output") or "")
            if any(wt in out_s for wt in _SINGLE_SERIES_WIDGET_TYPES):
                is_single_series_widget = True
                break

    if is_single_series_widget and first_cat in status_dims:
        if len(val_keys) > 1:
            val_keys = [val_keys[0]]
            dm["valueKey"] = val_keys
        first_val_id = val_keys[0].get("id", "") if isinstance(val_keys[0], dict) else ""
        if first_val_id in ("audit_ledger.settled_usd", "audit_ledger.blocked_usd"):
            val_keys[0] = {"id": "audit_ledger.mandate_id", "aggregation": "count"}

    return args


async def run_studio_adk_turn(
    request_body: dict[str, Any],
    shield_state: dict[str, Any],
) -> dict[str, Any]:
    """
    Executes a full turn of the Google ADK agent (`ap2_studio_bi_agent`) for AG Studio.
    If the user explicitly selected `ap2-deterministic-auditor` or no Gemini API Key
    is configured in the environment, cleanly delegates to the enhanced deterministic engine.
    """
    conv_items = request_body.get("input") or []
    tools_schema = request_body.get("tools") or []
    studio_instructions = str(request_body.get("instructions") or "")
    model_info = request_body.get("model") or {}
    requested_model_id = (
        (model_info.get("id") if isinstance(model_info, dict) else None)
        or "gemini-2.5-flash"
    )
    turn_id = f"studio_adk_{uuid.uuid4().hex[:8]}"

    api_key = (
        os.environ.get("GEMINI_API_KEY")
        or os.environ.get("GOOGLE_API_KEY")
        or ""
    ).strip()

    if requested_model_id == "ap2-deterministic-auditor" or not api_key:
        return run_deterministic_studio_fallback(
            request_body,
            shield_state,
            turn_id=turn_id,
            model_id=requested_model_id,
        )

    try:
        agent = create_studio_bi_adk_agent(
            model_id=requested_model_id,
            studio_instructions=studio_instructions,
            tools_schema=tools_schema,
            shield_state=shield_state,
        )
        history_events, new_message = _convert_studio_input_to_adk_events_and_message(conv_items)

        session_id = f"studio_sess_{uuid.uuid4().hex[:10]}"
        user_id = "ag_studio_cfo"
        session = await _studio_session_service.create_session(
            app_name=STUDIO_ADK_APP_NAME,
            user_id=user_id,
            session_id=session_id,
        )
        if history_events:
            session.events.extend(history_events)

        runner = Runner(
            agent=agent,
            app_name=STUDIO_ADK_APP_NAME,
            session_service=_studio_session_service,
        )

        emitted_tool_calls: list[dict[str, str]] = []
        emitted_texts: list[str] = []

        async for ev in runner.run_async(
            user_id=user_id,
            session_id=session_id,
            new_message=new_message,
        ):
            fcs = ev.get_function_calls() if hasattr(ev, "get_function_calls") else []
            if fcs:
                for fc in fcs:
                    fc_args = dict(fc.args) if fc.args else {}
                    if fc.name == "configure_widget":
                        fc_args = _safeguard_configure_widget_args(fc_args, conv_items)
                    emitted_tool_calls.append(
                        {
                            "callId": str(fc.id or f"call_{uuid.uuid4().hex[:8]}"),
                            "name": str(fc.name),
                            "arguments": json.dumps(fc_args, ensure_ascii=False),
                        }
                    )

            if ev.content and ev.content.parts:
                for part in ev.content.parts:
                    if getattr(part, "text", None) and not getattr(part, "thought", False):
                        emitted_texts.append(part.text)

        if emitted_tool_calls:
            resp: dict[str, Any] = {
                "id": turn_id,
                "model": requested_model_id,
                "toolCalls": emitted_tool_calls,
            }
            combined_text = "\n".join(t.strip() for t in emitted_texts if t.strip()).strip()
            if combined_text:
                resp["text"] = combined_text
            return resp

        final_text = "\n".join(t.strip() for t in emitted_texts if t.strip()).strip()
        if final_text:
            return {
                "id": turn_id,
                "model": requested_model_id,
                "text": final_text,
            }
    except Exception as exc:
        print(f"[STUDIO-ADK-AGENT] Warning: ADK turn fallback triggered ({exc})")

    return run_deterministic_studio_fallback(
        request_body,
        shield_state,
        turn_id=turn_id,
        model_id=requested_model_id,
    )
