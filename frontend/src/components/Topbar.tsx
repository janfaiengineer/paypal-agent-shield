import React from 'react';
import type { ConfigStatus } from '../types/shield';

interface TopbarProps {
  credsStatus: ConfigStatus | null;
  onOpenConfig: () => void;
}

export const Topbar: React.FC<TopbarProps> = ({ credsStatus, onOpenConfig }) => {
  const isAllLive =
    credsStatus?.paypal_live_ready &&
    credsStatus?.gemini_ready &&
    credsStatus?.channel3_ready;

  const statusText = credsStatus
    ? `🔑 PayPal: ${credsStatus.paypal_live_ready ? 'LIVE' : 'SIMULATED'} | ADK: ${
        credsStatus.gemini_ready ? 'READY' : 'NO KEY'
      } | Channel3: ${credsStatus.channel3_ready ? 'LIVE' : 'FALLBACK'} | Render WF: ${
        credsStatus.render_workflow_ready ? 'LIVE' : 'LOCAL'
      }`
    : '🔑 Modo: Verificando...';

  return (
    <div className="topbar">
      <div className="brand">
        <span>🛡️ PayPal Agent Shield</span>
        <span className="tag">Google ADK 2.0 Graph</span>
        <span className="tag">AP2 Ed25519</span>
        <span className="tag">PayPal APIMatic SDK</span>
        <span className="tag">Render Workflows</span>
        <span
          className="tag"
          style={{
            background: 'rgba(168, 85, 247, 0.18)',
            color: '#d8b4fe',
            borderColor: 'rgba(168, 85, 247, 0.5)',
          }}
        >
          Bryntum TaskBoard HITL
        </span>
        <span
          className="tag"
          style={{
            background: 'rgba(245, 158, 11, 0.16)',
            color: '#fbbf24',
            borderColor: 'rgba(245, 158, 11, 0.45)',
          }}
        >
          AG Studio 3 + AG Grid
        </span>
      </div>
      <div style={{ display: 'flex', alignItems: 'center', gap: '10px' }}>
        <span
          id="creds-status"
          className="tag"
          style={{
            cursor: 'pointer',
            color: credsStatus ? (isAllLive ? '#34d399' : '#fbbf24') : undefined,
            borderColor: credsStatus ? (isAllLive ? '#059669' : '#d97706') : undefined,
          }}
          onClick={onOpenConfig}
        >
          {statusText}
        </span>
        <button
          onClick={onOpenConfig}
          style={{
            background: '#1e293b',
            color: '#f8fafc',
            border: '1px solid #334155',
            padding: '6px 12px',
            borderRadius: '6px',
            fontSize: '12px',
            cursor: 'pointer',
            fontWeight: 600,
          }}
        >
          ⚙️ API Keys (BYOK)
        </button>
        <span className="badge-live">● SSE REAL-TIME</span>
      </div>
    </div>
  );
};
