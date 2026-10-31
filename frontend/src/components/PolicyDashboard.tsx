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
import { AgStudio, AgStudioProvider } from 'ag-studio-react';
import {
  AgStudioAiModule,
  studioTheme,
  type AgDataSourcesDefinition,
  type AgReportState,
  type AgStudioMode,
} from 'ag-studio';
import { BryntumTaskBoardView } from './BryntumTaskBoardView';
import { configureStudioWidgets } from './studio/ap2ShieldWidget';
import { buildStudioAi } from './studio/studioAi';
import type {
  Policy,
  AuditEntry,
  TaskBoardCard,
  AdkGraphTelemetry,
} from '../types/shield';

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

const initialStudioState = {
  selectedPageId: 'cfo-ap2-analytics',
  pages: [
    {
      id: 'cfo-ap2-analytics',
      widgets: {
        'shield-posture-widget': {
          type: 'ap2-shield-posture',
          format: {
            title: {
              text: '🛡️ AP2 4-Layer Defense Pipeline (Interactive Custom Widget)',
              enabled: true,
            },
          },
          dataMapping: {
            dimension: [{ id: 'audit_ledger.control_layer' }],
            value: [
              { id: 'audit_ledger.settled_usd', aggregation: 'sum' },
              { id: 'audit_ledger.blocked_usd', aggregation: 'sum' },
            ],
          },
        },
        'kpi-settled-usd': {
          type: 'value',
          format: {
            title: { text: 'Total Liquidado en PayPal (USD)', enabled: true },
            style: { color: '#34d399' },
          },
          dataMapping: {
            value: [{ id: 'audit_ledger.settled_usd', aggregation: 'sum' }],
          },
        },
        'kpi-blocked-usd': {
          type: 'value',
          format: {
            title: { text: 'Capital Protegido / Bloqueado (USD)', enabled: true },
            style: { color: '#f87171' },
          },
          dataMapping: {
            value: [{ id: 'audit_ledger.blocked_usd', aggregation: 'sum' }],
          },
        },
        'kpi-mandates-count': {
          type: 'value',
          format: {
            title: { text: 'Eventos Auditados en Sesión', enabled: true },
            style: { color: '#38bdf8' },
          },
          dataMapping: {
            value: [{ id: 'audit_ledger.mandate_id', aggregation: 'count' }],
          },
        },
        'chart-decision-volume': {
          type: 'bar-chart-grouped',
          format: {
            title: { text: 'Flujo Financiero: Pagado vs Bloqueado (USD)', enabled: true },
          },
          dataMapping: {
            categoryKey: [{ id: 'audit_ledger.decision_type' }],
            valueKey: [{ id: 'audit_ledger.tx_amount_usd', aggregation: 'sum' }],
          },
        },
        'chart-layer-donut': {
          type: 'donut-chart',
          format: {
            title: { text: 'Eventos por Capa de Seguridad AP2', enabled: true },
          },
          dataMapping: {
            categoryKey: [{ id: 'audit_ledger.control_layer' }],
            valueKey: [{ id: 'audit_ledger.mandate_id', aggregation: 'count' }],
          },
        },
        'studio-audit-grid': {
          type: 'grid',
          format: {
            title: {
              text: 'Desglose Relacional: Transacciones AP2 ⋈ Políticas CFO (AG Studio)',
              enabled: true,
            },
          },
          dataMapping: {
            cols: [
              { id: 'audit_ledger.timestamp' },
              { id: 'audit_ledger.mandate_id' },
              { id: 'audit_ledger.agent_id' },
              { id: 'audit_ledger.item' },
              { id: 'audit_ledger.decision_type' },
              { id: 'audit_ledger.control_layer' },
              { id: 'audit_ledger.settled_usd', aggregation: 'sum' },
              { id: 'audit_ledger.blocked_usd', aggregation: 'sum' },
              { id: 'agent_policies.max_tx_limit_usd', aggregation: 'avg' },
            ],
          },
        },
      },
      widgetLayout: {
        'shield-posture-widget': { xTrack: 0, yTrack: 0, xSpan: 24, ySpan: 8 },
        'kpi-settled-usd': { xTrack: 0, yTrack: 8, xSpan: 8, ySpan: 6 },
        'kpi-blocked-usd': { xTrack: 8, yTrack: 8, xSpan: 8, ySpan: 6 },
        'kpi-mandates-count': { xTrack: 16, yTrack: 8, xSpan: 8, ySpan: 6 },
        'chart-decision-volume': { xTrack: 0, yTrack: 14, xSpan: 12, ySpan: 13 },
        'chart-layer-donut': { xTrack: 12, yTrack: 14, xSpan: 12, ySpan: 13 },
        'studio-audit-grid': { xTrack: 0, yTrack: 27, xSpan: 24, ySpan: 14 },
      },
    },
  ],
} as unknown as AgReportState;

function classifyControlLayer(entry: AuditEntry): string {
  const details = (entry.details || '').toUpperCase();
  if (entry.status === 'PAYPAL_COMPLETED') {
    return 'Liquidación PayPal Sandbox';
  }
  if (details.includes('BUDGET_EXCEEDED')) {
    return 'Límite de Presupuesto CFO';
  }
  if (details.includes('GROUND_TRUTH_MISMATCH') || details.includes('HALLUCINATION_BLOCKED')) {
    return 'Anti-Alucinación Channel3';
  }
  if (details.includes('ED25519') || details.includes('CRYPTO_ERROR')) {
    return 'Firma Criptográfica Ed25519';
  }
  if (details.includes('AP2_HASH_MISMATCH')) {
    return 'Integridad Hash AP2';
  }
  return 'Gobernanza CFO (Política)';
}

function classifyDecisionType(status: AuditEntry['status']): string {
  if (status === 'PAYPAL_COMPLETED') return 'Pago Liquidado (PayPal)';
  if (status === 'QUARANTINED_HITL') return 'Cuarentena HITL (Bryntum TaskBoard)';
  if (status === 'BLOCKED_BY_SHIELD') return 'Capital Protegido (Bloqueado)';
  return 'Gobernanza / Firma de Política';
}

interface PolicyDashboardProps {
  policy: Policy | null;
  auditLog: AuditEntry[];
  taskboardCards: TaskBoardCard[];
  adkGraphTelemetry: AdkGraphTelemetry | null;
}

const StatusCellRenderer: React.FC<ICellRendererParams<AuditEntry>> = (params) => {
  const val = params.value || '';
  if (val === 'BLOCKED_BY_SHIELD') {
    return <span className="status-pill blocked">🛑 {val}</span>;
  }
  if (val === 'QUARANTINED_HITL') {
    return <span className="status-pill quarantined">⏸️ {val}</span>;
  }
  if (val === 'PAYPAL_COMPLETED') {
    return <span className="status-pill approved">✅ {val}</span>;
  }
  if (val === 'POLICY_SIGNED') {
    return <span className="status-pill policy">🔐 {val}</span>;
  }
  return <span>{val}</span>;
};

export const PolicyDashboard: React.FC<PolicyDashboardProps> = ({
  policy,
  auditLog,
  taskboardCards,
  adkGraphTelemetry,
}) => {
  const [activeView, setActiveView] = useState<
    'control-plane' | 'bryntum-hitl' | 'ag-studio'
  >('control-plane');
  const [studioMode, setStudioMode] = useState<AgStudioMode>('edit');
  const [quickFilter, setQuickFilter] = useState<string>('');
  const auditGridRef = useRef<AgGridReact<AuditEntry>>(null);

  const quarantinedCount = useMemo(
    () => taskboardCards.filter((c) => c.status === 'QUARANTINED').length,
    [taskboardCards]
  );

  const policyRows = useMemo(() => (policy ? [policy] : []), [policy]);

  // Métricas financieras reales calculadas directamente sobre las transacciones de la sesión
  const metrics = useMemo(() => {
    const maxBudget = Number(policy?.max_budget_usd ?? 200);
    const remaining = Number(policy?.remaining_usd ?? 200);
    const usedPct = maxBudget > 0 ? Math.min(100, Math.max(0, ((maxBudget - remaining) / maxBudget) * 100)) : 0;

    let settledUsd = 0;
    let settledCount = 0;
    let blockedUsd = 0;
    let blockedCount = 0;

    for (const entry of auditLog) {
      const amt = Number(entry.amount ?? 0);
      if (entry.status === 'PAYPAL_COMPLETED') {
        settledUsd += amt;
        settledCount += 1;
      } else if (
        entry.status === 'BLOCKED_BY_SHIELD' ||
        entry.status === 'QUARANTINED_HITL'
      ) {
        blockedUsd += amt;
        blockedCount += 1;
      }
    }

    return {
      maxBudget,
      remaining,
      usedPct,
      settledUsd,
      settledCount,
      blockedUsd,
      blockedCount,
    };
  }, [policy, auditLog]);

  const policyColumnDefs = useMemo<ColDef<Policy>[]>(() => {
    const cols: ColDef<Policy>[] = [
      { field: 'agent_id', headerName: 'Agente IA', width: 145 },
      {
        field: 'max_budget_usd',
        headerName: '✏️ Presupuesto Máx (USD)',
        editable: true,
        width: 195,
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
        headerName: 'Saldo Disponible (USD)',
        width: 175,
        valueFormatter: (params) => `$${Number(params.value ?? 0).toFixed(2)}`,
        cellStyle: { fontWeight: 'bold', color: '#34d399' },
      },
      { field: 'allowed_category', headerName: 'Categoría Autorizada', width: 165 },
      { field: 'cfo_signature', headerName: 'Firma Ed25519 del CFO', flex: 1 },
      { field: 'ap2_policy_hash', headerName: 'Hash Mandato AP2 (SHA-256)', flex: 1 },
    ];
    return cols;
  }, []);

  const auditColumnDefs = useMemo<ColDef<AuditEntry>[]>(
    () => [
      { field: 'timestamp', headerName: 'Hora', width: 95 },
      { field: 'mandate_id', headerName: 'Mandato AP2', width: 145 },
      { field: 'item', headerName: 'Producto / Operación', width: 220 },
      {
        field: 'amount',
        headerName: 'Monto (USD)',
        width: 120,
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
    if (params.data.status === 'QUARANTINED_HITL') return 'row-quarantined';
    if (params.data.status === 'PAYPAL_COMPLETED') return 'row-approved';
    if (params.data.status === 'POLICY_SIGNED') return 'row-policy';
    return '';
  }, []);

  // Modelo relacional multi-tabla para AG Studio 3 (`audit_ledger` ⋈ `agent_policies` + expresiones calculadas)
  const studioData = useMemo<AgDataSourcesDefinition>(() => {
    const activeAgentId = policy?.agent_id ?? 'procurement-01';
    const cardMerchantById = new Map<string, string>();
    for (const card of taskboardCards) {
      if (card.id && card.merchant) {
        cardMerchantById.set(card.id, card.merchant);
      }
    }

    const liveRows = auditLog.map((entry) => {
      const amount = Number(entry.amount ?? 0);
      const isSettled = entry.status === 'PAYPAL_COMPLETED';
      const isBlocked = entry.status === 'BLOCKED_BY_SHIELD';
      const isQuarantined = entry.status === 'QUARANTINED_HITL';
      const detailsUpper = (entry.details || '').toUpperCase();
      const itemUpper = (entry.item || '').toUpperCase();

      const policyDecision = isSettled
        ? 'APPROVED_AND_CAPTURED'
        : isBlocked
          ? 'BLOCKED'
          : isQuarantined
            ? 'QUARANTINED_HITL'
            : 'POLICY_SIGNED';

      const riskLevel = isBlocked
        ? 'CRITICAL'
        : isQuarantined
          ? 'HIGH'
          : 'LOW';

      const ap2MandateStatus =
        detailsUpper.includes('ED25519') && isBlocked
          ? 'CRYPTO_REJECTED'
          : detailsUpper.includes('BUDGET_EXCEEDED')
            ? 'BUDGET_EXCEEDED'
            : 'ED25519_VERIFIED';

      const channel3Verified =
        detailsUpper.includes('GROUND_TRUTH_MISMATCH') ||
        detailsUpper.includes('HALLUCINATION_BLOCKED')
          ? 'BLOCKED_MISMATCH'
          : 'VERIFIED';

      const resolvedMerchant =
        entry.merchant ||
        cardMerchantById.get(entry.mandate_id) ||
        (isBlocked || detailsUpper.includes('DARKWEB') || detailsUpper.includes('SPOOF')
          ? 'hacker@darkweb.io'
          : isQuarantined || itemUpper.includes('LAPTOP') || itemUpper.includes('MONITOR')
            ? 'monitors-direct@sandbox.paypal.com'
            : itemUpper.includes('CHAIR') || itemUpper.includes('POLICY')
              ? 'office-supply@sandbox.paypal.com'
              : 'apple-b2b@paypal.com');

      return {
        timestamp: entry.timestamp,
        mandate_id: entry.mandate_id,
        agent_id: activeAgentId,
        merchant: resolvedMerchant,
        item: entry.item,
        decision_type: classifyDecisionType(entry.status),
        policy_decision: policyDecision,
        control_layer: classifyControlLayer(entry),
        risk_level: riskLevel,
        ap2_mandate_status: ap2MandateStatus,
        channel3_verified: channel3Verified,
        amount_usd: amount,
        tx_amount_usd: isSettled || isBlocked || isQuarantined ? amount : 0,
        settled_usd: isSettled ? amount : 0,
        blocked_usd: isBlocked || isQuarantined ? amount : 0,
        details: entry.details,
      };
    });

    const policyTableRows = [
      {
        agent_id: activeAgentId,
        policy_id: policy?.policy_id ?? 'pol_default',
        max_tx_limit_usd: Number(policy?.max_budget_usd ?? 200),
        remaining_usd: Number(policy?.remaining_usd ?? 200),
        allowed_category: policy?.allowed_category ?? 'Hardware',
        ap2_policy_hash: policy?.ap2_policy_hash ?? '',
      },
    ];

    return {
      description:
        'Modelo relacional de auditoría financiera y criptográfica en tiempo real: une el ledger de mandatos AP2 (`audit_ledger`) con las políticas presupuestarias del CFO (`agent_policies`).',
      sources: [
        {
          id: 'audit_ledger',
          name: 'Auditoría AP2 & PayPal Sandbox',
          description:
            'Transacciones reales evaluadas por el Firewall Criptográfico AP2, verificadas contra Channel3 y liquidadas en PayPal Sandbox.',
          data: liveRows,
          fields: [
            { id: 'timestamp', name: 'Hora', format: 'textFormat' },
            { id: 'mandate_id', name: 'Mandato AP2', format: 'textFormat' },
            { id: 'agent_id', name: 'Agente IA', format: 'textFormat' },
            { id: 'merchant', name: 'Comercio Destino', format: 'textFormat' },
            { id: 'item', name: 'Producto / Operación', format: 'textFormat' },
            { id: 'decision_type', name: 'Veredicto Shield', format: 'textFormat' },
            { id: 'policy_decision', name: 'Estado Político AP2', format: 'textFormat' },
            { id: 'control_layer', name: 'Capa de Seguridad AP2', format: 'textFormat' },
            { id: 'risk_level', name: 'Nivel de Riesgo', format: 'textFormat' },
            { id: 'ap2_mandate_status', name: 'Estado Criptográfico Ed25519', format: 'textFormat' },
            { id: 'channel3_verified', name: 'Verificación Channel3', format: 'textFormat' },
            { id: 'amount_usd', name: 'Monto Bruto (USD)', format: 'currencyFormat' },
            { id: 'tx_amount_usd', name: 'Monto Evaluado (USD)', format: 'currencyFormat' },
            { id: 'settled_usd', name: 'Pagado en PayPal (USD)', format: 'currencyFormat' },
            { id: 'blocked_usd', name: 'Capital Protegido (USD)', format: 'currencyFormat' },
            { id: 'details', name: 'Evidencia Criptográfica', format: 'textFormat' },
          ],
        },
        {
          id: 'agent_policies',
          name: 'Políticas de Gobernanza CFO',
          description:
            'Límites presupuestarios firmados con Ed25519 por el CFO para cada agente autónomo de compras.',
          data: policyTableRows,
          fields: [
            { id: 'agent_id', name: 'Agente IA', format: 'textFormat' },
            { id: 'policy_id', name: 'ID Política CFO', format: 'textFormat' },
            { id: 'max_tx_limit_usd', name: 'Límite Presupuestario CFO (USD)', format: 'currencyFormat' },
            { id: 'remaining_usd', name: 'Saldo Disponible (USD)', format: 'currencyFormat' },
            { id: 'allowed_category', name: 'Categoría Autorizada', format: 'textFormat' },
            { id: 'ap2_policy_hash', name: 'Hash Mandato AP2', format: 'textFormat' },
          ],
        },
      ],
      relationships: [
        {
          id: 'ledger_to_agent_policy',
          source: { tableId: 'audit_ledger', fieldId: 'agent_id' },
          target: { tableId: 'agent_policies', fieldId: 'agent_id' },
          type: 'many-to-one',
        },
      ],
      expressions: [
        {
          id: 'shieldProtectionRate',
          name: 'Tasa de Capital Protegido (%)',
          description: 'Proporción del volumen financiero interceptado por AP2 Shield sobre el volumen total evaluado.',
          isMeasure: true,
          format: 'percentageFormat',
          expression: 'SUM([audit_ledger.blocked_usd]) / SUM([audit_ledger.tx_amount_usd])',
        },
        {
          id: 'paypalSettlementRate',
          name: 'Tasa de Liquidación PayPal (%)',
          description: 'Proporción del volumen financiero liquidado en PayPal Sandbox sobre el volumen total evaluado.',
          isMeasure: true,
          format: 'percentageFormat',
          expression: 'SUM([audit_ledger.settled_usd]) / SUM([audit_ledger.tx_amount_usd])',
        },
      ],
    };
  }, [auditLog, policy, taskboardCards]);

  return (
    <div className="dashboard-panel">
      <div className="kpi-bar">
        <div className="kpi-card">
          <div className="kpi-label">Presupuesto Autorizado (CFO)</div>
          <div className="kpi-value" id="kpi-max">
            ${metrics.maxBudget.toFixed(2)}
          </div>
          <div className="kpi-sub">
            Política activa: {policy?.policy_id ?? 'pol_default'}
          </div>
        </div>

        <div className="kpi-card">
          <div className="kpi-label">Saldo Disponible (AG Grid)</div>
          <div className="kpi-value" id="kpi-remaining" style={{ color: '#34d399' }}>
            ${metrics.remaining.toFixed(2)}
          </div>
          <div className="kpi-sub">
            {metrics.usedPct.toFixed(1)}% del presupuesto utilizado
          </div>
        </div>

        <div className="kpi-card">
          <div className="kpi-label">Liquidado en PayPal Sandbox</div>
          <div className="kpi-value" style={{ color: '#38bdf8' }}>
            ${metrics.settledUsd.toFixed(2)}
          </div>
          <div className="kpi-sub">
            {metrics.settledCount} {metrics.settledCount === 1 ? 'orden completada' : 'órdenes completadas'}
          </div>
        </div>

        <div className="kpi-card">
          <div className="kpi-label">Capital Protegido (Bloqueado)</div>
          <div className="kpi-value" style={{ color: '#f87171' }}>
            ${metrics.blockedUsd.toFixed(2)}
          </div>
          <div className="kpi-sub">
            {metrics.blockedCount} {metrics.blockedCount === 1 ? 'intento detenido' : 'intentos detenidos'} por Shield
          </div>
        </div>
      </div>

      {/* Selector de vista: Control Plane (AG Grid) vs Bryntum HITL TaskBoard & ADK 2.0 Graph vs CFO Analytics Studio (AG Studio 3) */}
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
            className={`studio-tab-btn bryntum-highlight ${
              activeView === 'bryntum-hitl' ? 'active' : ''
            }`}
            onClick={() => setActiveView('bryntum-hitl')}
          >
            📋 Bryntum HITL TaskBoard &amp; ADK 2.0 Graph
            {quarantinedCount > 0 && (
              <span className="quarantine-count-badge">{quarantinedCount} HITL</span>
            )}
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
              placeholder="🔍 Filtrar mandato, producto, estado..."
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
        ) : activeView === 'bryntum-hitl' ? (
          <div className="audit-toolbar">
            <span style={{ fontSize: '11.5px', color: '#a78bfa', fontWeight: 600 }}>
              🕸️ Nodo ADK Activo: <code>{adkGraphTelemetry?.active_node || 'adk_node_cfo_hitl_quarantine'}</code>
            </span>
          </div>
        ) : (
          <div className="audit-toolbar">
            <span style={{ fontSize: '11.5px', color: '#cbd5e1' }}>
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
          <div className="adk-mini-banner">
            <div style={{ display: 'flex', alignItems: 'center', gap: '10px', flexWrap: 'wrap' }}>
              <span style={{ fontWeight: 700, color: '#c084fc', fontSize: '12px' }}>
                🕸️ Google ADK 2.0 Graph Workflow:
              </span>
              <code style={{ fontSize: '11.5px', color: '#38bdf8' }}>
                {(adkGraphTelemetry?.visited_nodes || [
                  'adk_node_crypto_gate',
                  'adk_node_channel3_ground_truth',
                  'adk_node_policy_budget_gate',
                  'adk_node_cfo_hitl_quarantine',
                ]).join(' → ')}
              </code>
            </div>
            <button
              type="button"
              className="btn-open-taskboard"
              onClick={() => setActiveView('bryntum-hitl')}
            >
              📋 Abrir Bryntum HITL TaskBoard ({quarantinedCount} en cuarentena) →
            </button>
          </div>

          <div>
            <div className="section-header">
              <span>1. Políticas Presupuestarias del CFO (AG Grid Editable)</span>
              <span className="hint">
                💡 Haz doble clic en &quot;✏️ Presupuesto Máx (USD)&quot; y presiona Enter para
                firmar un nuevo Mandato AP2
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
      ) : activeView === 'bryntum-hitl' ? (
        <BryntumTaskBoardView
          cards={taskboardCards}
          telemetry={adkGraphTelemetry}
          policy={policy}
        />
      ) : (
        <div style={{ flex: 1, display: 'flex', flexDirection: 'column', minHeight: 0 }}>
          <div className="section-header">
            <span>
              📊 AG Studio 3 — Custom Widget (`ap2-shield-posture`), Studio AI Agent (`ap2-shield-auditor`) &amp; Motor Relacional
            </span>
            <span className="hint">
              ✨ Haz clic en el ícono de IA (panel derecho) para hablar con el agente o en los botones del Custom Widget para cross-filtering
            </span>
          </div>
          <div className="studio-container-wrapper" data-ag-theme-mode="dark">
            <AgStudioProvider modules={[AgStudioAiModule]}>
              <AgStudio
                theme={darkStudioTheme}
                data={studioData}
                initialState={initialStudioState}
                widgets={configureStudioWidgets}
                ai={buildStudioAi}
                mode={studioMode}
                enableFilterEditingInViewMode={true}
                style={{ width: '100%', height: '100%', flex: 1 }}
              />
            </AgStudioProvider>
          </div>
        </div>
      )}
    </div>
  );
};
