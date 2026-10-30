import React, { useMemo, useCallback } from 'react';
import { AgGridReact } from 'ag-grid-react';
import {
  AllCommunityModule,
  ModuleRegistry,
  themeQuartz,
  colorSchemeDark,
  type ColDef,
  type CellValueChangedEvent,
  type RowClassParams,
  type ICellRendererParams,
} from 'ag-grid-community';
import type { Policy, AuditEntry } from '../types/shield';

ModuleRegistry.registerModules([AllCommunityModule]);

const darkGridTheme = themeQuartz.withPart(colorSchemeDark).withParams({
  backgroundColor: '#0f172a',
  headerBackgroundColor: '#1e293b',
  oddRowBackgroundColor: '#0b1120',
  foregroundColor: '#f1f5f9',
  borderColor: '#334155',
});

interface PolicyDashboardProps {
  policy: Policy | null;
  auditLog: AuditEntry[];
}

const StatusCellRenderer: React.FC<ICellRendererParams<AuditEntry>> = (params) => {
  const val = params.value || '';
  if (val === 'BLOCKED_BY_SHIELD') {
    return <span className="status-pill blocked">🛑 {val}</span>;
  }
  if (val === 'PAYPAL_COMPLETED') {
    return <span className="status-pill approved">✅ {val}</span>;
  }
  if (val === 'POLICY_SIGNED') {
    return <span className="status-pill policy">🔐 {val}</span>;
  }
  return <span>{val}</span>;
};

export const PolicyDashboard: React.FC<PolicyDashboardProps> = ({ policy, auditLog }) => {
  const policyRows = useMemo(() => (policy ? [policy] : []), [policy]);

  const policyColumnDefs = useMemo<ColDef<Policy>[]>(() => {
    const cols: ColDef<Policy>[] = [
      { field: 'agent_id', headerName: 'Agent ID', width: 150 },
      { field: 'policy_id', headerName: 'Policy ID', width: 130 },
      {
        field: 'max_budget_usd',
        headerName: '✏️ Max Budget (USD)',
        editable: true,
        width: 175,
        valueParser: (params) => Number(params.newValue),
        valueFormatter: (params) => `$${Number(params.value ?? 0).toFixed(2)}`,
        cellStyle: {
          backgroundColor: 'rgba(56, 189, 248, 0.16)',
          fontWeight: 'bold',
          color: '#38bdf8',
        },
      },
      {
        field: 'remaining_usd',
        headerName: 'Remaining (USD)',
        width: 160,
        valueFormatter: (params) => `$${Number(params.value ?? 0).toFixed(2)}`,
        cellStyle: { fontWeight: 'bold', color: '#34d399' },
      },
      { field: 'cfo_signature', headerName: 'CFO Ed25519 Signature', flex: 1 },
      { field: 'ap2_policy_hash', headerName: 'AP2 Policy Hash (SHA-256)', flex: 1 },
    ];
    return cols;
  }, []);

  const auditColumnDefs = useMemo<ColDef<AuditEntry>[]>(
    () => [
      { field: 'timestamp', headerName: 'Hora', width: 95 },
      { field: 'mandate_id', headerName: 'AP2 Mandate', width: 145 },
      { field: 'item', headerName: 'Producto / Evento', width: 220 },
      {
        field: 'amount',
        headerName: 'Monto',
        width: 110,
        valueFormatter: (p) => `$${Number(p.value ?? 0).toFixed(2)}`,
      },
      {
        field: 'status',
        headerName: 'Veredicto Shield',
        width: 185,
        cellRenderer: StatusCellRenderer,
      },
      {
        field: 'details',
        headerName: 'Evidencia Criptográfica Ed25519 & PayPal Order ID',
        flex: 1,
      },
    ],
    []
  );

  const handlePolicyCellValueChanged = useCallback(
    async (event: CellValueChangedEvent<Policy>) => {
      if (event.colDef.field === 'max_budget_usd' && event.data) {
        await fetch('/api/policy', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({
            agent_id: event.data.agent_id,
            max_budget_usd: Number(event.newValue),
            allowed_category: event.data.allowed_category,
          }),
        });
      }
    },
    []
  );

  const getAuditRowClass = useCallback((params: RowClassParams<AuditEntry>) => {
    if (!params.data) return '';
    if (params.data.status === 'BLOCKED_BY_SHIELD') return 'row-blocked';
    if (params.data.status === 'PAYPAL_COMPLETED') return 'row-approved';
    if (params.data.status === 'POLICY_SIGNED') return 'row-policy';
    return '';
  }, []);

  return (
    <div className="dashboard-panel">
      <div className="kpi-bar">
        <div className="kpi-card">
          <div className="kpi-label">Presupuesto Autorizado (CFO)</div>
          <div className="kpi-value" id="kpi-max">
            ${policy ? Number(policy.max_budget_usd).toFixed(2) : '200.00'}
          </div>
        </div>
        <div className="kpi-card">
          <div className="kpi-label">Saldo Disponible (AG Grid)</div>
          <div className="kpi-value" id="kpi-remaining" style={{ color: '#34d399' }}>
            ${policy ? Number(policy.remaining_usd).toFixed(2) : '200.00'}
          </div>
        </div>
        <div className="kpi-card">
          <div className="kpi-label">Identidades Ed25519 & Hash AP2</div>
          <div
            className="kpi-value"
            id="kpi-hash"
            style={{
              fontSize: '12px',
              fontFamily: 'monospace',
              color: '#cbd5e1',
              marginTop: '8px',
            }}
          >
            {policy
              ? `CFO PubKey: ${policy.cfo_pubkey}... | AP2: ${policy.ap2_policy_hash.slice(0, 18)}...`
              : '—'}
          </div>
        </div>
      </div>

      <div>
        <div className="section-header">
          <span>1. Políticas Presupuestarias del CFO (AG Grid Editable)</span>
          <span className="hint">
            💡 Haz doble clic en &quot;✏️ Max Budget&quot; y presiona Enter para firmar un nuevo
            Mandato AP2
          </span>
        </div>
        <div
          id="policyGrid"
          className="grid-wrapper ag-theme-quartz-dark"
          style={{ height: '110px', width: '100%' }}
        >
          <AgGridReact<Policy>
            theme={darkGridTheme}
            rowData={policyRows}
            columnDefs={policyColumnDefs}
            onCellValueChanged={handlePolicyCellValueChanged}
          />
        </div>
      </div>

      <div style={{ flex: 1, display: 'flex', flexDirection: 'column' }}>
        <div className="section-header">
          <span>
            2. Firewall en Vivo: Auditoría Criptográfica AP2 &amp; Liquidación PayPal (APIMatic)
          </span>
          <a
            href="https://developer.paypal.com/dashboard/api-calls/sandbox"
            target="_blank"
            rel="noopener noreferrer"
            style={{
              fontSize: '12px',
              color: '#38bdf8',
              textDecoration: 'none',
              background: 'rgba(56,189,248,0.1)',
              border: '1px solid rgba(56,189,248,0.3)',
              padding: '3px 10px',
              borderRadius: '6px',
              fontWeight: 600,
            }}
          >
            📡 Ver API Calls en PayPal Sandbox ↗
          </a>
        </div>
        <div
          id="auditGrid"
          className="grid-wrapper ag-theme-quartz-dark"
          style={{ flex: 1, minHeight: '300px', width: '100%' }}
        >
          <AgGridReact<AuditEntry>
            theme={darkGridTheme}
            rowData={auditLog}
            columnDefs={auditColumnDefs}
            getRowClass={getAuditRowClass}
          />
        </div>
      </div>
    </div>
  );
};
