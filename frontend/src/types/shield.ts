export interface Policy {
  policy_id: string;
  agent_id: string;
  max_budget_usd: number;
  remaining_usd: number;
  allowed_category: string;
  cfo_signature: string;
  cfo_pubkey: string;
  agent_pubkey: string;
  ap2_policy_hash: string;
}

export type VerdictStatus =
  | 'BLOCKED_BY_SHIELD'
  | 'PAYPAL_COMPLETED'
  | 'POLICY_SIGNED'
  | 'QUARANTINED_HITL'
  | string;

export interface AuditEntry {
  timestamp: string;
  mandate_id: string;
  item: string;
  amount: number;
  status: VerdictStatus;
  details: string;
}

export type TaskBoardColumnId =
  | 'CHANNEL3_DISCOVERY'
  | 'QUARANTINED'
  | 'PAYPAL_SETTLED'
  | 'BLOCKED_THREAT';

export interface TaskBoardCard {
  id: string;
  name: string;
  status: TaskBoardColumnId;
  prio: 'high' | 'medium' | 'low';
  sku: string;
  amount_usd: number;
  c3_price_usd: number;
  merchant: string;
  adk_node: string;
  gate_code: string;
  ed25519_sig: string;
  paypal_order_id?: string | null;
  description: string;
  updated_at: string;
  can_approve_hitl: boolean;
}

export interface AdkGraphTelemetry {
  graph_name: string;
  active_node: string;
  last_route: string;
  visited_nodes: string[];
  last_mandate_id: string;
  updated_at: string;
}

export interface ShieldState {
  policy: Policy;
  audit_log: AuditEntry[];
  taskboard_cards?: TaskBoardCard[];
  adk_graph_telemetry?: AdkGraphTelemetry;
}

export interface ConfigStatus {
  gemini_ready: boolean;
  gemini_model: string;
  paypal_live_ready: boolean;
  channel3_ready: boolean;
  render_workflow_ready: boolean;
  render_workflow_slug?: string;
}

export interface CredentialsPayload {
  google_api_key: string;
  paypal_client_id: string;
  paypal_client_secret: string;
  channel3_api_key: string;
  render_api_key: string;
}

export interface ChatMessage {
  id: string;
  role: 'user' | 'agent';
  text: string;
  tools?: string[];
  isLoading?: boolean;
}
