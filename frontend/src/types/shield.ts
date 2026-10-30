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
  | string;

export interface AuditEntry {
  timestamp: string;
  mandate_id: string;
  item: string;
  amount: number;
  status: VerdictStatus;
  details: string;
}

export interface ShieldState {
  policy: Policy;
  audit_log: AuditEntry[];
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
