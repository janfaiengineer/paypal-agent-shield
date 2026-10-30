import React, { useMemo, useCallback, useState, useRef } from 'react';
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
import { AgStudio } from 'ag-studio-react';
import {
  studioTheme,
  type AgDataSourcesDefinition,
  type AgReportState,
  type AgStudioMode,
} from 'ag-studio';
import type { Policy, AuditEntry } from '../types/shield';

ModuleRegistry.registerModules([AllCommunityModule]);

const darkGridTheme = themeQuartz.withPart(colorSchemeDark).withParams({
  backgroundColor: '#0f172a',
  headerBackgroundColor: '#1e293b',
  oddRowBackgroundColor: '#0b1120',
  foregroundColor: '#f1f5f9',
  borderColor: '#334155',
});

const darkStudioTheme = studioTheme
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  .withPart(colorSchemeDark as any)
  .withParams({
    browserColorScheme: 'dark',
    gridBrowserColorScheme: 'dark',
    accentColor: '#38bdf8',
    gridAccentColor: '#38bdf8',
    backgroundColor: '#0f172a',
    foregroundColor: '#ffffff',
    textColor: '#f8fafc',
    subtleTextColor: '#cbd5e1',
    iconColor: '#f1f5f9',
    gridIconColor: '#f1f5f9',
    borderColor: '#334155',
    studioWrapperBackgroundColor: '#090d16',
    studioCanvasBackgroundColor: '#0b1120',
    studioPanelContainerBackgroundColor: '#0f172a',
    studioPanelGroupBackgroundColor: '#1e293b',
    studioPanelGroupTitleBarTextColor: '#ffffff',
    studioFormLabelColor: '#e2e8f0',
    studioWidgetBackgroundColor: '#131c31',
    studioWidgetTitleTextColor: '#ffffff',
    studioWidgetSubtitleTextColor: '#cbd5e1',
    studioWidgetCaptionTextColor: '#cbd5e1',
    studioWidgetToolbarBackgroundColor: '#1e293b',
    studioWidgetToolbarButtonColor: '#f8fafc',
    gridHeaderBackgroundColor: '#1e293b',
    gridHeaderTextColor: '#38bdf8',
    gridDataBackgroundColor: '#0f172a',
    gridOddRowBackgroundColor: '#131c31',
    gridCellTextColor: '#f8fafc',
    menuBackgroundColor: '#1e293b',
    menuTextColor: '#f8fafc',
    tooltipBackgroundColor: '#1e293b',
    tooltipTextColor: '#f8fafc',
    chartTextColor: '#f8fafc',
    chartSubtleTextColor: '#cbd5e1',
    chartAxisLineColor: '#64748b',
    chartGridLineColor: '#1e293b',
  });

const initialStudioState: AgReportState = {
  selectedPageId: 'cfo-ap2-analytics',
  pages: [
    {
      id: 'cfo-ap2-analytics',
      widgets: {
        'kpi-total-volume': {
          type: 'value',
          format: {
            title: { text: 'Volumen Total Evaluado (USD)', enabled: true },
            style: { color: '#38bdf8' },
          },
          dataMapping: {
            value: [{ id: 'amount_usd', aggregation: 'sum' }],
          },
        },
        'kpi-mandates-count': {
          type: 'value',
          format: {
            title: { text: 'Mandatos AP2 Auditados', enabled: true },
            style: { color: '#34d399' },
          },
          dataMapping: {
            value: [{ id: 'mandate_id', aggregation: 'count' }],
          },
        },
        'kpi-avg-risk': {
          type: 'value',
          format: {
            title: { text: 'Risk Score Promedio (Shield)', enabled: true },
            style: { color: '#fbbf24' },
          },
          dataMapping: {
            value: [{ id: 'risk_score', aggregation: 'avg' }],
          },
        },
        'chart-verdict-volume': {
          type: 'bar-chart-grouped',
          format: {
            title: { text: 'Volumen USD por Veredicto del Firewall AP2', enabled: true },
          },
          dataMapping: {
            categoryKey: [{ id: 'status' }],
            valueKey: [{ id: 'amount_usd', aggregation: 'sum' }],
          },
        },
        'chart-category-donut': {
          type: 'donut-chart',
          format: {
            title: { text: 'Exposición por Vector / Categoría', enabled: true },
          },
          dataMapping: {
            categoryKey: [{ id: 'category' }],
            valueKey: [{ id: 'amount_usd', aggregation: 'sum' }],
          },
        },
        'studio-audit-grid': {
          type: 'grid',
          format: {
            title: { text: 'Tabla Analítica AP2 & PayPal Sandbox (AG Studio)', enabled: true },
          },
          dataMapping: {
            cols: [
              { id: 'timestamp' },
              { id: 'mandate_id' },
              { id: 'item' },
              { id: 'category' },
              { id: 'status' },
              { id: 'amount_usd', aggregation: 'sum' },
              { id: 'risk_score', aggregation: 'avg' },
            ],
          },
        },
      },
      widgetLayout: {
        'kpi-total-volume': { xTrack: 0, yTrack: 0, xSpan: 8, ySpan: 6 },
        'kpi-mandates-count': { xTrack: 8, yTrack: 0, xSpan: 8, ySpan: 6 },
        'kpi-avg-risk': { xTrack: 16, yTrack: 0, xSpan: 8, ySpan: 6 },
        'chart-verdict-volume': { xTrack: 0, yTrack: 6, xSpan: 12, ySpan: 13 },
        'chart-category-donut': { xTrack: 12, yTrack: 6, xSpan: 12, ySpan: 13 },
        'studio-audit-grid': { xTrack: 0, yTrack: 19, xSpan: 24, ySpan: 14 },
      },
    },
  ],
};

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
  const [activeView, setActiveView] = useState<'control-plane' | 'ag-studio'>('control-plane');
  const [studioMode, setStudioMode] = useState<AgStudioMode>('edit');
  const [quickFilter, setQuickFilter] = useState<string>('');
  const auditGridRef = useRef<AgGridReact<AuditEntry>>(null);

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

  const handleExportAuditCsv = useCallback(() => {
    auditGridRef.current?.api?.exportDataAsCsv({
      fileName: `paypal-agent-shield-ap2-audit-${new Date().toISOString().slice(0, 10)}.csv`,
    });
  }, []);

  const getAuditRowClass = useCallback((params: RowClassParams<AuditEntry>) => {
    if (!params.data) return '';
    if (params.data.status === 'BLOCKED_BY_SHIELD') return 'row-blocked';
    if (params.data.status === 'PAYPAL_COMPLETED') return 'row-approved';
    if (params.data.status === 'POLICY_SIGNED') return 'row-policy';
    return '';
  }, []);

  // Dataset enriquecido en tiempo real para AG Studio 3
  const studioData = useMemo<AgDataSourcesDefinition>(() => {
    const liveRows = auditLog.map((entry, idx) => {
      const isBlocked = entry.status === 'BLOCKED_BY_SHIELD';
      const isApproved = entry.status === 'PAYPAL_COMPLETED';
      const isPromptInjection =
        entry.details.toLowerCase().includes('injection') ||
        entry.details.toLowerCase().includes('riesgo') ||
        Number(entry.amount) > (policy?.max_budget_usd ?? 200);

      let category = 'Gob. Criptográfica AP2';
      if (isApproved) category = 'Hardware & Periféricos (Autorizado)';
      else if (isBlocked && isPromptInjection) category = 'Ataque Prompt Injection / Exceso';
      else if (isBlocked) category = 'Violación de Presupuesto CFO';

      const riskScore = isBlocked ? (isPromptInjection ? 96 : 82) : isApproved ? 12 : 5;

      return {
        row_id: `LIVE-${idx + 1}`,
        timestamp: entry.timestamp,
        mandate_id: entry.mandate_id,
        item: entry.item,
        amount_usd: Number(entry.amount ?? 0),
        status: entry.status,
        category,
        risk_score: riskScore,
        agent_id: policy?.agent_id ?? 'agent-buyer-01',
        max_budget_usd: Number(policy?.max_budget_usd ?? 200),
        remaining_usd: Number(policy?.remaining_usd ?? 200),
        details: entry.details,
      };
    });

    // Si solo existe el evento de arranque, agregamos telemetría semilla de referencia para que los gráficos de AG Studio luzcan completos desde el primer segundo
    const referenceRows =
      liveRows.length <= 1
        ? [
            {
              row_id: 'SEED-1',
              timestamp: '09:14:22',
              mandate_id: 'AP2-8F91A02C',
              item: 'Keychron K2 Mechanical Keyboard',
              amount_usd: 89.99,
              status: 'PAYPAL_COMPLETED',
              category: 'Hardware & Periféricos (Autorizado)',
              risk_score: 11,
              agent_id: 'agent-buyer-01',
              max_budget_usd: Number(policy?.max_budget_usd ?? 200),
              remaining_usd: Number(policy?.remaining_usd ?? 200),
              details: 'PayPal Order COMPLETED | Ed25519 Verified',
            },
            {
              row_id: 'SEED-2',
              timestamp: '09:16:05',
              mandate_id: 'AP2-3C77D19E',
              item: 'Logitech MX Master 3S Mouse',
              amount_usd: 99.0,
              status: 'PAYPAL_COMPLETED',
              category: 'Hardware & Periféricos (Autorizado)',
              risk_score: 14,
              agent_id: 'agent-buyer-01',
              max_budget_usd: Number(policy?.max_budget_usd ?? 200),
              remaining_usd: Number(policy?.remaining_usd ?? 200),
              details: 'PayPal Order COMPLETED | Ed25519 Verified',
            },
            {
              row_id: 'SEED-3',
              timestamp: '09:18:40',
              mandate_id: 'AP2-9A04F61B',
              item: 'NVIDIA RTX 4090 GPU (Rogue Prompt)',
              amount_usd: 450.0,
              status: 'BLOCKED_BY_SHIELD',
              category: 'Ataque Prompt Injection / Exceso',
              risk_score: 98,
              agent_id: 'agent-buyer-01',
              max_budget_usd: Number(policy?.max_budget_usd ?? 200),
              remaining_usd: Number(policy?.remaining_usd ?? 200),
              details: 'Blocked by AP2 Firewall: Exceeds CFO Max Budget & Prompt Injection',
            },
            {
              row_id: 'SEED-4',
              timestamp: '09:21:10',
              mandate_id: 'AP2-5D12E88A',
              item: 'Apple MacBook Pro M3 Max (Unauthorized)',
              amount_usd: 2500.0,
              status: 'BLOCKED_BY_SHIELD',
              category: 'Violación de Presupuesto CFO',
              risk_score: 94,
              agent_id: 'agent-buyer-01',
              max_budget_usd: Number(policy?.max_budget_usd ?? 200),
              remaining_usd: Number(policy?.remaining_usd ?? 200),
              details: 'Blocked by AP2 Firewall: Zero PayPal API Calls Executed',
            },
          ]
        : [];

    return {
      description:
        'Telemetría en tiempo real del Firewall Criptográfico AP2 (Ed25519), políticas del CFO y órdenes liquidadas en PayPal Sandbox.',
      sources: [
        {
          id: 'ap2_shield_telemetry',
          name: 'Auditoría AP2 & PayPal Sandbox',
          description:
            'Eventos de compra de agentes IA, veredictos del firewall AP2, montos en USD y puntajes de riesgo.',
          data: [...liveRows, ...referenceRows],
          fields: [
            { id: 'timestamp', name: 'Hora', format: 'textFormat' },
            { id: 'mandate_id', name: 'Mandato AP2', format: 'textFormat' },
            { id: 'item', name: 'Producto / Evento', format: 'textFormat' },
            { id: 'category', name: 'Categoría / Vector', format: 'textFormat' },
            { id: 'status', name: 'Veredicto Shield', format: 'textFormat' },
            { id: 'agent_id', name: 'Agent ID', format: 'textFormat' },
            { id: 'amount_usd', name: 'Monto (USD)', format: 'currencyFormat' },
            { id: 'risk_score', name: 'Score de Riesgo', format: 'integerFormat' },
            { id: 'max_budget_usd', name: 'Presupuesto CFO (USD)', format: 'currencyFormat' },
            { id: 'remaining_usd', name: 'Saldo Disponible (USD)', format: 'currencyFormat' },
            { id: 'details', name: 'Evidencia Criptográfica', format: 'textFormat' },
          ],
        },
      ],
    };
  }, [auditLog, policy]);

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
          <div className="kpi-label">Identidades Ed25519 &amp; Hash AP2</div>
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

      {/* Selector de vista: Control Plane (AG Grid) vs CFO Analytics Studio (AG Studio 3) */}
      <div className="studio-switcher-bar">
        <div className="studio-tabs">
          <button
            type="button"
            className={`studio-tab-btn ${activeView === 'control-plane' ? 'active' : ''}`}
            onClick={() => setActiveView('control-plane')}
          >
            🛡️ Control Plane (AG Grid En Vivo)
          </button>
          <button
            type="button"
            className={`studio-tab-btn studio-highlight ${
              activeView === 'ag-studio' ? 'active' : ''
            }`}
            onClick={() => setActiveView('ag-studio')}
          >
            📊 CFO Analytics Studio (AG Studio 3 BI)
          </button>
        </div>

        {activeView === 'control-plane' ? (
          <div className="audit-toolbar">
            <input
              type="text"
              className="audit-search-input"
              placeholder="🔍 Filtrar mandato, item, estado..."
              value={quickFilter}
              onChange={(e) => setQuickFilter(e.target.value)}
            />
            <button
              type="button"
              className="btn-export-csv"
              onClick={handleExportAuditCsv}
              title="Exportar auditoría criptográfica AP2 en formato CSV"
            >
              📥 Exportar CSV AP2
            </button>
          </div>
        ) : (
          <div className="audit-toolbar">
            <span style={{ fontSize: '11.5px', color: '#94a3b8' }}>
              Modo de AG Studio 3:
            </span>
            <button
              type="button"
              className={`studio-tab-btn ${studioMode === 'edit' ? 'active' : ''}`}
              style={{ padding: '4px 10px', fontSize: '11.5px' }}
              onClick={() => setStudioMode('edit')}
            >
              🛠️ Diseñador BI (Edit)
            </button>
            <button
              type="button"
              className={`studio-tab-btn ${studioMode === 'view' ? 'active' : ''}`}
              style={{ padding: '4px 10px', fontSize: '11.5px' }}
              onClick={() => setStudioMode('view')}
            >
              👁️ Reporte Ejecutivo (View)
            </button>
          </div>
        )}
      </div>

      {activeView === 'control-plane' ? (
        <>
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
              style={{ flex: 1, minHeight: '280px', width: '100%' }}
            >
              <AgGridReact<AuditEntry>
                ref={auditGridRef}
                theme={darkGridTheme}
                rowData={auditLog}
                columnDefs={auditColumnDefs}
                getRowClass={getAuditRowClass}
                quickFilterText={quickFilter}
              />
            </div>
          </div>
        </>
      ) : (
        <div style={{ flex: 1, display: 'flex', flexDirection: 'column', minHeight: 0 }}>
          <div className="section-header">
            <span>
              📊 AG Studio 3 — Centro de Inteligencia Financiera &amp; Riesgo Criptográfico AP2
            </span>
            <span className="hint">
              ✨ Arrastra campos, crea Pivot Grids, gráficos de barras/dona y cruza filtros en vivo
            </span>
          </div>
          <div className="studio-container-wrapper" data-ag-theme-mode="dark">
            <AgStudio
              theme={darkStudioTheme}
              data={studioData}
              initialState={initialStudioState}
              mode={studioMode}
              enableFilterEditingInViewMode={true}
              style={{ width: '100%', height: '100%', flex: 1 }}
            />
          </div>
        </div>
      )}
    </div>
  );
};
