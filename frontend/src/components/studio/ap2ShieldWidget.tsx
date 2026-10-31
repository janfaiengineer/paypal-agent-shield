import React, { useEffect, useState } from 'react';
import type { AgWidgetData, AgWidgetDataFormat, AgWidgetField, AgWidgetParams, AgWidgetsConfig } from 'ag-studio';
import type { AgWidgetDefinition } from 'ag-studio-react';

export interface Ap2ShieldWidgetStyle {
  accentColor?: string;
}

export type Ap2ShieldWidgetFormat = AgWidgetDataFormat<Ap2ShieldWidgetStyle>;

export interface Ap2ShieldWidgetDataMapping {
  dimension?: AgWidgetField[];
  value?: AgWidgetField[];
}

export interface Ap2ShieldWidgetInDataMapping {
  dimension?: { id: string }[];
  value?: { id: string; aggregation?: string }[];
}

export interface Ap2ShieldWidgetInState extends AgWidgetData<Ap2ShieldWidgetInDataMapping, Ap2ShieldWidgetFormat> {
  type: 'ap2-shield-posture';
}

export interface Ap2ShieldWidgetState extends AgWidgetData<Ap2ShieldWidgetDataMapping, Ap2ShieldWidgetFormat> {
  type: 'ap2-shield-posture';
}

interface LayerTelemetry {
  layer: string;
  totalUsd: number;
  settledUsd: number;
  blockedUsd: number;
  count: number;
}

const SHIELD_SVG_ICON = `<svg xmlns="http://www.w3.org/2000/svg" width="32" height="32" viewBox="0 0 32 32" fill="none">
  <path d="M16 3L5 7.5V15.5C5 22.8 9.7 29.3 16 31C22.3 29.3 27 22.8 27 15.5V7.5L16 3Z" fill="#0070ba" fill-opacity="0.25" stroke="#0070ba" stroke-width="2"/>
  <path d="M12 16.5L14.8 19.3L20.5 13.5" stroke="#10b981" stroke-width="2.4" stroke-linecap="round" stroke-linejoin="round"/>
</svg>`;

const LAYER_META: Record<
  string,
  { badge: string; label: string; color: string; bg: string; border: string; desc: string }
> = {
  'Límite de Presupuesto CFO': {
    badge: 'L1',
    label: 'L1: Límite de Presupuesto CFO (Policy Engine)',
    color: '#f59e0b',
    bg: 'rgba(245, 158, 11, 0.12)',
    border: 'rgba(245, 158, 11, 0.35)',
    desc: 'Enforces CFO budget ceilings & Bryntum HITL quarantine',
  },
  'Firma Criptográfica Ed25519': {
    badge: 'L2',
    label: 'L2: Firma Criptográfica Ed25519 (Mandate Proof)',
    color: '#38bdf8',
    bg: 'rgba(56, 189, 248, 0.12)',
    border: 'rgba(56, 189, 248, 0.35)',
    desc: 'Verifies non-repudiable Ed25519 signatures & SHA-256 chain',
  },
  'Anti-Alucinación Channel3': {
    badge: 'L3',
    label: 'L3: Anti-Alucinación Channel3 (Ground Truth)',
    color: '#f43f5e',
    bg: 'rgba(244, 63, 94, 0.12)',
    border: 'rgba(244, 63, 94, 0.35)',
    desc: 'Cross-checks SKU price against Channel3 truth & blocks MitM',
  },
  'Liquidación PayPal Sandbox': {
    badge: 'L4',
    label: 'L4: Liquidación PayPal Sandbox (APIMatic SDK)',
    color: '#10b981',
    bg: 'rgba(16, 185, 129, 0.12)',
    border: 'rgba(16, 185, 129, 0.35)',
    desc: 'Executes verified orders on PayPal Sandbox via APIMatic SDK',
  },
  'Gobernanza CFO (Política)': {
    badge: 'GOV',
    label: 'GOV: Gobernanza CFO (Firma de Política AP2)',
    color: '#a855f7',
    bg: 'rgba(168, 85, 247, 0.12)',
    border: 'rgba(168, 85, 247, 0.35)',
    desc: 'Root CFO Ed25519 policy mandate registration',
  },
  'L1: Policy Engine': {
    badge: 'L1',
    label: 'L1: Policy Engine (Budget & Merchant Bounds)',
    color: '#f59e0b',
    bg: 'rgba(245, 158, 11, 0.12)',
    border: 'rgba(245, 158, 11, 0.35)',
    desc: 'Enforces CFO budget ceilings & merchant whitelisting',
  },
  'L2: Ed25519 Crypto': {
    badge: 'L2',
    label: 'L2: Ed25519 Cryptographic Mandate Proof',
    color: '#38bdf8',
    bg: 'rgba(56, 189, 248, 0.12)',
    border: 'rgba(56, 189, 248, 0.35)',
    desc: 'Verifies non-repudiable Ed25519 signatures & SHA-256 chain',
  },
  'L3: Prompt Sanitizer': {
    badge: 'L3',
    label: 'L3: Prompt Injection & Price Hallucination Guard',
    color: '#f43f5e',
    bg: 'rgba(244, 63, 94, 0.12)',
    border: 'rgba(244, 63, 94, 0.35)',
    desc: 'Cross-checks SKU price against Channel3 truth & blocks MitM',
  },
  'L4: PayPal Orders v2': {
    badge: 'L4',
    label: 'L4: PayPal Orders v2 Settlement (APIMatic SDK)',
    color: '#10b981',
    bg: 'rgba(16, 185, 129, 0.12)',
    border: 'rgba(16, 185, 129, 0.35)',
    desc: 'Executes verified orders on PayPal Sandbox via APIMatic SDK',
  },
};

export const Ap2ShieldPostureWidget: React.FC<AgWidgetParams<Ap2ShieldWidgetState>> = (params) => {
  const { widgetApi, dataMapping, format } = params;
  const [rows, setRows] = useState<LayerTelemetry[]>([]);
  const [activeLayerFilter, setActiveLayerFilter] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;

    async function loadShieldTelemetry() {
      const dimField = dataMapping?.dimension?.[0];
      const valFields = dataMapping?.value ?? [];
      const queryFields = [
        ...(dimField ? [dimField] : []),
        ...valFields,
      ];

      if (queryFields.length === 0) {
        widgetApi.setDisplayState('displayed');
        return;
      }

      try {
        const response = await widgetApi.getData(
          { fields: queryFields },
          { queryId: 'ap2-shield-posture-query' }
        );
        if (cancelled) return;

        const rawRows = (response?.results as { rows?: Record<string, unknown>[] } | undefined)?.rows ?? [];
        const parsed: LayerTelemetry[] = rawRows.map((r) => {
          const dimVal = dimField ? String(r[dimField.key] ?? 'L4: PayPal Orders v2') : 'L4: PayPal Orders v2';
          const v0 = valFields[0] ? Number(r[valFields[0].key] ?? 0) : 0;
          const v1 = valFields[1] ? Number(r[valFields[1].key] ?? 0) : 0;
          const v2 = valFields[2] ? Number(r[valFields[2].key] ?? 0) : 0;

          const isSettledLayer = dimVal.includes('L4') || dimVal.includes('PayPal');
          const settledUsd = valFields.length >= 2 ? v0 : isSettledLayer ? v0 : 0;
          const blockedUsd = valFields.length >= 2 ? v1 : isSettledLayer ? 0 : v0;
          const totalUsd = settledUsd + blockedUsd || v0;
          const count = valFields.length >= 3 ? v2 : 1;

          return {
            layer: dimVal,
            totalUsd,
            settledUsd,
            blockedUsd,
            count,
          };
        });

        setRows(parsed);
        widgetApi.setDisplayState('displayed');
      } catch {
        if (!cancelled) {
          widgetApi.setDisplayState('displayed');
        }
      }
    }

    void loadShieldTelemetry();
    return () => {
      cancelled = true;
    };
  }, [params, widgetApi, dataMapping]);

  const totalSettled = rows.reduce((acc, r) => acc + r.settledUsd, 0);
  const totalBlocked = rows.reduce((acc, r) => acc + r.blockedUsd, 0);
  const grandTotal = totalSettled + totalBlocked || 1;
  const protectionPct = Math.round((totalBlocked / grandTotal) * 100);
  const settlementPct = 100 - protectionPct;

  const handleLayerClick = (layerName: string) => {
    const dimField = dataMapping?.dimension?.[0];
    if (!dimField) return;

    if (activeLayerFilter === layerName) {
      setActiveLayerFilter(null);
      widgetApi.resetCrossFilter();
    } else {
      setActiveLayerFilter(layerName);
      widgetApi.toggleCrossFilter({
        type: 'value',
        group: 0,
        reset: true,
        field: dimField,
        value: layerName,
      });
    }
  };

  const titleText = format?.title?.text || '🛡️ AP2 Zero-Trust Defense Pipeline (Custom Studio Widget)';

  return (
    <div
      style={{
        height: '100%',
        width: '100%',
        boxSizing: 'border-box',
        padding: '12px 14px',
        background: 'linear-gradient(145deg, rgba(15, 23, 42, 0.96), rgba(9, 13, 22, 0.98))',
        color: '#f8fafc',
        display: 'flex',
        flexDirection: 'column',
        justifyContent: 'space-between',
        gap: '10px',
        fontFamily: 'Inter, system-ui, -apple-system, sans-serif',
        overflow: ' auto',
      }}
    >
      {/* Header */}
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', gap: '8px' }}>
        <div>
          <div style={{ display: 'flex', alignItems: 'center', gap: '6px' }}>
            <span
              style={{
                fontSize: '0.66rem',
                fontWeight: 700,
                padding: '2px 6px',
                borderRadius: '4px',
                background: 'rgba(0, 112, 186, 0.25)',
                color: '#38bdf8',
                border: '1px solid rgba(56, 189, 248, 0.35)',
                textTransform: 'uppercase',
                letterSpacing: '0.04em',
              }}
            >
              Custom AG Studio Widget
            </span>
            <span
              style={{
                fontSize: '0.66rem',
                fontWeight: 600,
                padding: '2px 6px',
                borderRadius: '4px',
                background: 'rgba(16, 185, 129, 0.16)',
                color: '#34d399',
                border: '1px solid rgba(16, 185, 129, 0.3)',
              }}
            >
              Ed25519 Verified
            </span>
          </div>
          <div style={{ fontSize: '0.86rem', fontWeight: 700, color: '#f1f5f9', marginTop: '4px' }}>
            {titleText}
          </div>
        </div>

        <div style={{ display: 'flex', gap: '12px', alignItems: 'center' }}>
          <div style={{ textAlign: 'right' }}>
            <div style={{ fontSize: '0.65rem', color: '#94a3b8', textTransform: 'uppercase' }}>
              PayPal Settled
            </div>
            <div style={{ fontSize: '0.95rem', fontWeight: 800, color: '#10b981' }}>
              ${totalSettled.toFixed(2)} ({settlementPct}%)
            </div>
          </div>
          <div style={{ textAlign: 'right' }}>
            <div style={{ fontSize: '0.65rem', color: '#94a3b8', textTransform: 'uppercase' }}>
              Shield Mitigated
            </div>
            <div style={{ fontSize: '0.95rem', fontWeight: 800, color: '#f43f5e' }}>
              ${totalBlocked.toFixed(2)} ({protectionPct}%)
            </div>
          </div>
          {activeLayerFilter && (
            <button
              type="button"
              onClick={() => {
                setActiveLayerFilter(null);
                widgetApi.resetCrossFilter();
              }}
              style={{
                fontSize: '0.68rem',
                padding: '3px 8px',
                borderRadius: '5px',
                border: '1px solid rgba(56, 189, 248, 0.45)',
                background: 'rgba(56, 189, 248, 0.15)',
                color: '#38bdf8',
                cursor: 'pointer',
              }}
            >
              Clear Filter ✕
            </button>
          )}
        </div>
      </div>

      {/* 4-Layer Interactive Pipeline */}
      <div
        style={{
          display: 'grid',
          gridTemplateColumns: 'repeat(4, minmax(140px, 1fr))',
          gap: '8px',
          flex: 1,
          alignItems: 'stretch',
        }}
      >
        {Object.entries(LAYER_META).map(([layerKey, meta]) => {
          const matched = rows.find((r) => r.layer === layerKey);
          const layerTotal = matched ? matched.totalUsd : 0;
          const pctOfAll = grandTotal > 0 ? Math.min(100, Math.round((layerTotal / grandTotal) * 100)) : 0;
          const isSelected = activeLayerFilter === layerKey;

          return (
            <div
              key={layerKey}
              onClick={() => handleLayerClick(layerKey)}
              title="Click to cross-filter all AG Studio widgets by this security layer"
              style={{
                background: isSelected ? meta.bg : 'rgba(30, 41, 59, 0.55)',
                border: `1px solid ${isSelected ? meta.color : meta.border}`,
                borderRadius: '8px',
                padding: '8px 10px',
                cursor: 'pointer',
                display: 'flex',
                flexDirection: 'column',
                justifyContent: 'space-between',
                transition: 'all 0.15s ease',
                boxShadow: isSelected ? `0 0 0 1px ${meta.color}` : 'none',
              }}
            >
              <div>
                <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
                  <span
                    style={{
                      fontSize: '0.68rem',
                      fontWeight: 800,
                      padding: '1px 6px',
                      borderRadius: '4px',
                      background: meta.bg,
                      color: meta.color,
                      border: `1px solid ${meta.border}`,
                    }}
                  >
                    {meta.badge}
                  </span>
                  <span style={{ fontSize: '0.82rem', fontWeight: 700, color: meta.color }}>
                    ${layerTotal.toFixed(2)}
                  </span>
                </div>
                <div
                  style={{
                    fontSize: '0.73rem',
                    fontWeight: 600,
                    color: '#e2e8f0',
                    marginTop: '5px',
                    lineHeight: 1.25,
                  }}
                >
                  {layerKey}
                </div>
                <div
                  style={{
                    fontSize: '0.64rem',
                    color: '#94a3b8',
                    marginTop: '2px',
                    lineHeight: 1.2,
                  }}
                >
                  {meta.desc}
                </div>
              </div>

              <div style={{ marginTop: '6px' }}>
                <div
                  style={{
                    height: '4px',
                    width: '100%',
                    background: 'rgba(15, 23, 42, 0.8)',
                    borderRadius: '999px',
                    overflow: 'hidden',
                  }}
                >
                  <div
                    style={{
                      height: '100%',
                      width: `${Math.max(pctOfAll, layerTotal > 0 ? 10 : 0)}%`,
                      background: meta.color,
                      borderRadius: '999px',
                    }}
                  />
                </div>
                <div
                  style={{
                    display: 'flex',
                    justifyContent: 'space-between',
                    fontSize: '0.62rem',
                    color: '#64748b',
                    marginTop: '3px',
                  }}
                >
                  <span>Share: {pctOfAll}%</span>
                  <span style={{ color: isSelected ? meta.color : '#94a3b8' }}>
                    {isSelected ? '● Cross-Filtering' : 'Click to Filter'}
                  </span>
                </div>
              </div>
            </div>
          );
        })}
      </div>
    </div>
  );
};

export const ap2ShieldPostureWidgetDef: AgWidgetDefinition<
  'ap2-shield-posture',
  Ap2ShieldWidgetInState,
  Ap2ShieldWidgetState
> = {
  id: 'ap2-shield-posture',
  label: 'AP2 Zero-Trust Posture',
  icon: SHIELD_SVG_ICON,
  dataMapping: {
    dimension: {
      type: 'field',
      supportedRoles: ['category'],
      required: true,
      sort: true,
      aiDescription: 'The security layer (audit_ledger.control_layer) or agent dimension to group AP2 telemetry by.',
      intent: 'category',
    },
    value: {
      type: 'fieldset',
      supportedRoles: ['numeric'],
      required: true,
      aiDescription: 'Monetary measures such as settled_usd, blocked_usd, or amount_usd.',
      intent: 'value',
    },
  },
  form: ({ createDefaults }) =>
    createDefaults({
      supportsCrossHighlight: false,
      dataMappingItems: [
        { key: 'dimension', label: 'Security Layer / Dimension' },
        { key: 'value', label: 'Settled & Blocked Metrics (USD)' },
      ],
    }),
  defaultState: {
    dataMapping: {
      dimension: [{ id: 'audit_ledger.control_layer' }],
      value: [
        { id: 'audit_ledger.settled_usd', aggregation: 'sum' },
        { id: 'audit_ledger.blocked_usd', aggregation: 'sum' },
      ],
    } as unknown as Ap2ShieldWidgetDataMapping,
    format: {
      title: {
        enabled: true,
        text: '🛡️ AP2 4-Layer Defense Pipeline (Interactive Custom Widget)',
      },
    },
  },
  comp: Ap2ShieldPostureWidget,
  defaultSize: { width: 600, height: 180 },
  minSize: { width: 320, height: 140 },
  ai: {
    label: 'AP2 Zero-Trust Shield Posture Scorecard',
    description:
      'Custom cybersecurity and financial governance widget visualizing the 4-layer AP2 defense pipeline (L1 Policy Engine, L2 Ed25519 Signature, L3 Prompt Sanitizer, L4 PayPal Orders v2) with interactive cross-filtering.',
    usage:
      'Use when the user wants to inspect AP2 cryptographic security posture, compare settled vs blocked volume across defense layers, or add an executive security scorecard.',
    configuration:
      'Map dimension to audit_ledger.control_layer and value to [sum(audit_ledger.settled_usd), sum(audit_ledger.blocked_usd)].',
  },
};

export function configureStudioWidgets(defaults: AgWidgetsConfig<any>): AgWidgetsConfig<any> {
  return {
    ...defaults,
    widgets: [...defaults.widgets, ap2ShieldPostureWidgetDef],
    menu: [
      {
        label: 'AP2 Security Shield (Custom)',
        widgetIds: ['ap2-shield-posture'],
      },
      ...defaults.menu,
    ],
  };
}
