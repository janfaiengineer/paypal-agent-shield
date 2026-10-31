import React, { useEffect, useRef, useState, useCallback } from 'react';
import type {
  AdkGraphTelemetry,
  Policy,
  TaskBoardCard,
  TaskBoardColumnId,
} from '../types/shield';

declare global {
  interface Window {
    bryntum?: {
      taskboard?: {
        TaskBoard: new (config: Record<string, unknown>) => {
          destroy?: () => void;
          project?: {
            taskStore?: {
              data: unknown[];
            };
          };
        };
      };
    };
  }
}

interface BryntumTaskBoardViewProps {
  cards: TaskBoardCard[];
  telemetry: AdkGraphTelemetry | null;
  policy: Policy | null;
}

interface ResolveResponse {
  status: string;
  action?: string;
  card?: TaskBoardCard;
  new_max_budget_usd?: number;
  paypal_order_id?: string;
  adk_visited_nodes?: string[];
  reason?: string;
}

const COLUMNS: Array<{
  id: TaskBoardColumnId;
  text: string;
  color: string;
  accent: string;
  adkNode: string;
  subtitle: string;
}> = [
  {
    id: 'CHANNEL3_DISCOVERY',
    text: '🔍 Channel3 Ground-Truth',
    color: 'blue',
    accent: '#38bdf8',
    adkNode: 'adk_node_channel3_ground_truth',
    subtitle: 'Gate 3: Anti-Hallucination & SKU Sync',
  },
  {
    id: 'QUARANTINED',
    text: '⏸️ CFO HITL Quarantine',
    color: 'amber',
    accent: '#f59e0b',
    adkNode: 'adk_node_cfo_hitl_quarantine',
    subtitle: 'Gate 4: Exceso de Presupuesto (Drag → PayPal)',
  },
  {
    id: 'PAYPAL_SETTLED',
    text: '✅ PayPal Sandbox Settled',
    color: 'green',
    accent: '#10b981',
    adkNode: 'adk_node_paypal_settlement',
    subtitle: 'AP2 Ed25519 + Render WF + APIMatic SDK',
  },
  {
    id: 'BLOCKED_THREAT',
    text: '🚨 Zero-Trust Threat Sink',
    color: 'red',
    accent: '#ef4444',
    adkNode: 'adk_node_threat_sink',
    subtitle: 'MitM Tampering / Price Hallucination Blocked',
  },
];

const ADK_GRAPH_NODES = [
  {
    id: 'adk_node_crypto_gate',
    label: '1. Crypto Gate',
    sub: 'Gates 1 & 2 (Ed25519)',
    color: '#38bdf8',
  },
  {
    id: 'adk_node_channel3_ground_truth',
    label: '2. Channel3 Truth',
    sub: 'Gate 3 (Anti-Hallucination)',
    color: '#818cf8',
  },
  {
    id: 'adk_node_policy_budget_gate',
    label: '3. AG Grid Policy Gate',
    sub: 'Gates 4 & 5 (Router)',
    color: '#c084fc',
  },
  {
    id: 'adk_node_cfo_hitl_quarantine',
    label: '4A. CFO HITL Quarantine',
    sub: 'route_cfo_hitl_quarantine',
    color: '#f59e0b',
  },
  {
    id: 'adk_node_paypal_settlement',
    label: '4B. PayPal Settlement',
    sub: 'route_paypal_settlement',
    color: '#10b981',
  },
  {
    id: 'adk_node_threat_sink',
    label: '4C. Threat Sink',
    sub: 'route_threat_sink',
    color: '#ef4444',
  },
];

function escapeHtml(str: string): string {
  return String(str || '')
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;')
    .replace(/'/g, '&#039;');
}

export const BryntumTaskBoardView: React.FC<BryntumTaskBoardViewProps> = ({
  cards,
  telemetry,
  policy,
}) => {
  const boardContainerRef = useRef<HTMLDivElement>(null);
  const boardInstanceRef = useRef<{
    destroy?: () => void;
    project?: { taskStore?: { data: unknown[] } };
  } | null>(null);

  const [bryntumReady, setBryntumReady] = useState<boolean>(
    Boolean(window.bryntum?.taskboard?.TaskBoard)
  );
  const [resolvingId, setResolvingId] = useState<string | null>(null);
  const [bannerMsg, setBannerMsg] = useState<{
    type: 'success' | 'warning' | 'error';
    text: string;
  } | null>(null);
  const [draggedCardId, setDraggedCardId] = useState<string | null>(null);

  const quarantinedCards = cards.filter((c) => c.status === 'QUARANTINED');

  const resolveQuarantineCard = useCallback(
    async (cardId: string, targetColumn: 'PAYPAL_SETTLED' | 'BLOCKED_THREAT') => {
      setResolvingId(cardId);
      setBannerMsg({
        type: 'warning',
        text:
          targetColumn === 'PAYPAL_SETTLED'
            ? `⏳ Re-firmando póliza Ed25519 del CFO, expandiendo presupuesto en AG Grid y reanudando grafo Google ADK 2.0 para ${cardId}...`
            : `⏳ Rechazando mandato en cuarentena ${cardId} y enviando a Threat Sink...`,
      });
      try {
        const res = await fetch('/api/quarantine/resolve', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({
            card_id: cardId,
            target_column: targetColumn,
            cfo_note:
              targetColumn === 'PAYPAL_SETTLED'
                ? 'Approved via Bryntum TaskBoard Drag & Drop HITL'
                : 'Rejected by CFO via Bryntum TaskBoard',
          }),
        });
        const data = (await res.json()) as ResolveResponse;
        if (data.status === 'OK' && data.action === 'APPROVED_AND_SETTLED') {
          setBannerMsg({
            type: 'success',
            text: `✅ HITL Aprobado y Liquidado: Presupuesto AG Grid expandido a $${Number(
              data.new_max_budget_usd || 0
            ).toFixed(2)} USD | Orden PayPal Sandbox: ${
              data.paypal_order_id || 'COMPLETED'
            } | Nodos ADK 2.0: ${(data.adk_visited_nodes || []).join(' → ')}`,
          });
        } else if (data.status === 'OK' && data.action === 'REJECTED_BY_CFO') {
          setBannerMsg({
            type: 'error',
            text: `🚫 Mandato ${cardId} rechazado definitivamente por el CFO y movido a BLOCKED_THREAT.`,
          });
        } else {
          setBannerMsg({
            type: 'error',
            text: `⚠️ Operación bloqueada por Zero-Trust Shield: ${
              data.reason || 'Transición no permitida'
            }`,
          });
        }
      } catch (err) {
        const msg = err instanceof Error ? err.message : String(err);
        setBannerMsg({
          type: 'error',
          text: `❌ Error al resolver mandato HITL: ${msg}`,
        });
      } finally {
        setResolvingId(null);
      }
    },
    []
  );

  // Detect Bryntum UMD script load
  useEffect(() => {
    if (window.bryntum?.taskboard?.TaskBoard) {
      setBryntumReady(true);
      return;
    }
    const timer = window.setInterval(() => {
      if (window.bryntum?.taskboard?.TaskBoard) {
        setBryntumReady(true);
        window.clearInterval(timer);
      }
    }, 300);
    return () => window.clearInterval(timer);
  }, []);

  // Initialize Bryntum TaskBoard instance
  useEffect(() => {
    if (!bryntumReady || !boardContainerRef.current) return;
    const TaskBoardClass = window.bryntum?.taskboard?.TaskBoard;
    if (!TaskBoardClass) return;

    if (boardInstanceRef.current?.destroy) {
      boardInstanceRef.current.destroy();
      boardInstanceRef.current = null;
    }
    boardContainerRef.current.innerHTML = '';

    const formattedTasks = cards.map((c) => ({
      ...c,
      name: c.name,
      description: c.description,
      status: c.status,
      prio: c.prio,
    }));

    try {
      const board = new TaskBoardClass({
        appendTo: boardContainerRef.current,
         cls: 'ap2-bryntum-board',
        useDomTransition: true,
        stickyHeaders: true,
        showCountInHeader: true,
        columns: COLUMNS.map((col) => ({
          id: col.id,
          text: col.text,
          color: col.color,
          tooltip: col.subtitle,
        })),
        columnField: 'status',
        headerItems: {
          text: { field: 'name' },
        },
        bodyItems: {
          description: {
            type: 'template',
            template: ({ taskRecord }: { taskRecord: Record<string, unknown> }) => {
              const sku = escapeHtml(String(taskRecord.sku || 'N/A'));
              const amount = Number(taskRecord.amount_usd || 0).toFixed(2);
              const c3Price = Number(taskRecord.c3_price_usd || 0).toFixed(2);
              const node = escapeHtml(String(taskRecord.adk_node || ''));
              const gate = escapeHtml(String(taskRecord.gate_code || ''));
              const sig = escapeHtml(String(taskRecord.ed25519_sig || ''));
              const ppOrder = taskRecord.paypal_order_id
                ? escapeHtml(String(taskRecord.paypal_order_id))
                : '';
              const desc = escapeHtml(String(taskRecord.description || ''));
              const status = String(taskRecord.status || '');

              return `
                <div class="ap2-tb-card-body">
                  <div class="ap2-tb-desc">${desc}</div>
                  <div class="ap2-tb-metrics">
                    <span class="ap2-tb-pill amount">$${amount} USD</span>
                    <span class="ap2-tb-pill c3">C3: $${c3Price}</span>
                    <span class="ap2-tb-pill sku">SKU: ${sku}</span>
                  </div>
                  <div class="ap2-tb-meta">
                    <div><strong>ADK Node:</strong> <code>${node}</code></div>
                    <div><strong>Gate:</strong> <code>${gate}</code> | <strong>Ed25519:</strong> <code>${sig}</code></div>
                    ${
                      ppOrder
                        ? `<div class="ap2-tb-paypal"><strong>PayPal Order:</strong> <code>${ppOrder}</code></div>`
                        : ''
                    }
                    ${
                      status === 'QUARANTINED'
                        ? `<div class="ap2-tb-hitl-hint">👉 Arrastra a <strong>PayPal Sandbox Settled</strong> para aprobar excepción CFO (+Presupuesto AG Grid) y liquidar en vivo.</div>`
                        : ''
                    }
                  </div>
                </div>
              `;
            },
          },
        },
        footerItems: {
          tags: {
            type: 'template',
            template: ({ taskRecord }: { taskRecord: Record<string, unknown> }) => {
              const id = escapeHtml(String(taskRecord.id || ''));
              const time = escapeHtml(String(taskRecord.updated_at || ''));
              return `<div class="ap2-tb-footer"><span>🆔 ${id}</span><span>🕒 ${time}</span></div>`;
            },
          },
        },
        project: {
          tasks: formattedTasks,
        },
        listeners: {
          beforeTaskDrop: ({
            taskRecords,
            targetColumn,
          }: {
            taskRecords: Array<Record<string, unknown>>;
            targetColumn: { id: string };
          }) => {
            const first = taskRecords?.[0];
            if (!first || !targetColumn) return false;
            const currentStatus = String(first.status || '');
            const targetId = String(targetColumn.id || '');
            // Only allow dragging cards out of QUARANTINED to PAYPAL_SETTLED or BLOCKED_THREAT
            if (currentStatus !== 'QUARANTINED') {
              setBannerMsg({
                type: 'warning',
                text: `🔒 Inmutabilidad Zero-Trust: Solo los mandatos en 'CFO HITL Quarantine' pueden moverse manualmente. (${String(
                  first.id
                )} está en ${currentStatus}).`,
              });
              return false;
            }
            if (targetId !== 'PAYPAL_SETTLED' && targetId !== 'BLOCKED_THREAT') {
              setBannerMsg({
                type: 'warning',
                text: `⚠️ Arrastra el mandato en cuarentena hacia '✅ PayPal Sandbox Settled' para aprobar y liquidar, o hacia '🚨 Zero-Trust Threat Sink' para rechazar.`,
              });
              return false;
            }
            return true;
          },
          taskDrop: ({
            taskRecords,
            targetColumn,
          }: {
            taskRecords: Array<Record<string, unknown>>;
            targetColumn: { id: string };
          }) => {
            const first = taskRecords?.[0];
            if (!first || !targetColumn) return;
            const cardId = String(first.id || '');
            const targetId = String(targetColumn.id || '');
            if (targetId === 'PAYPAL_SETTLED' || targetId === 'BLOCKED_THREAT') {
              void resolveQuarantineCard(cardId, targetId);
            }
          },
        },
      });

      boardInstanceRef.current = board;
    } catch (err) {
      console.error('Error initializing Bryntum TaskBoard:', err);
    }

    return () => {
      if (boardInstanceRef.current?.destroy) {
        boardInstanceRef.current.destroy();
        boardInstanceRef.current = null;
      }
    };
  }, [bryntumReady, cards, resolveQuarantineCard]);

  const visitedSet = new Set(
    (telemetry?.visited_nodes || []).map((n) => n.replace(' (RESUMED)', ''))
  );
  const activeNode = (telemetry?.active_node || '').replace(' (RESUMED)', '');

  return (
    <div className="bryntum-adk-view">
      {/* 1. TELEMETRÍA EN VIVO DEL GRAFO GOOGLE ADK 2.0 WORKFLOW */}
      <div className="adk-graph-pipeline-card">
        <div className="adk-graph-header">
          <div style={{ display: 'flex', alignItems: 'center', gap: '10px', flexWrap: 'wrap' }}>
            <span className="adk-graph-title">
              🕸️ Google ADK 2.0 Graph Workflow:{' '}
              <code>{telemetry?.graph_name || 'ap2_zero_trust_checkout_graph'}</code>
            </span>
            <span className="tag" style={{ background: 'rgba(168, 85, 247, 0.18)', color: '#d8b4fe', borderColor: '#9333ea' }}>
              Ruta Activa: {telemetry?.last_route || 'route_cfo_hitl_quarantine'}
            </span>
            <span className="tag" style={{ background: 'rgba(56, 189, 248, 0.14)', color: '#38bdf8' }}>
              Mandato: {telemetry?.last_mandate_id || 'ap2_chk_hitl_demo'}
            </span>
          </div>
          <span style={{ fontSize: '11px', color: '#94a3b8' }}>
            Sincronizado 1-a-1 con Bryntum TaskBoard • {telemetry?.updated_at || 'LIVE'}
          </span>
        </div>

        <div className="adk-nodes-row">
          {ADK_GRAPH_NODES.map((node, index) => {
            const isVisited = visitedSet.has(node.id);
            const isActive = activeNode === node.id;
            return (
              <React.Fragment key={node.id}>
                <div
                  className={`adk-node-chip ${isVisited ? 'visited' : ''} ${
                    isActive ? 'active-node' : ''
                  }`}
                  style={{
                    borderColor: isActive
                      ? node.color
                      : isVisited
                      ? 'rgba(56, 189, 248, 0.5)'
                      : '#334155',
                    boxShadow: isActive ? `0 0 14px ${node.color}55` : undefined,
                  }}
                >
                  <div className="adk-node-top">
                    <span
                      className="adk-node-dot"
                      style={{
                        background: isActive
                          ? node.color
                          : isVisited
                          ? '#38bdf8'
                          : '#475569',
                      }}
                    />
                    <span className="adk-node-label">{node.label}</span>
                  </div>
                  <div className="adk-node-sub">{node.sub}</div>
                </div>
                {index < 2 && <span className="adk-node-arrow">→</span>}
                {index === 2 && <span className="adk-node-arrow">⇉</span>}
              </React.Fragment>
            );
          })}
        </div>
      </div>

      {/* 2. BANNER DE RETROALIMENTACIÓN HITL / EJECUCIÓN */}
      {bannerMsg && (
        <div className={`hitl-status-banner ${bannerMsg.type}`}>
          <span>{bannerMsg.text}</span>
          <button
            type="button"
            onClick={() => setBannerMsg(null)}
            style={{
              background: 'transparent',
              border: 'none',
              color: 'inherit',
              cursor: 'pointer',
              fontWeight: 700,
              fontSize: '13px',
            }}
          >
            ✕
          </button>
        </div>
      )}

      {/* 3. BARRA RÁPIDA DE CUARENTENA HITL (DRAG & DROP O 1-CLICK) */}
      <div className="hitl-action-strip">
        <div style={{ display: 'flex', alignItems: 'center', gap: '10px', flexWrap: 'wrap' }}>
          <span style={{ fontWeight: 700, fontSize: '12.5px', color: '#fbbf24' }}>
            ⏸️ Cola HITL del CFO ({quarantinedCards.length} en cuarentena):
          </span>
          {quarantinedCards.length === 0 ? (
            <span style={{ fontSize: '12px', color: '#94a3b8' }}>
              Sin mandatos pendientes. Ejecuta la prueba <strong>"🚨 3. Exceder Presupuesto"</strong> en el chat para pausar un mandato en el nodo <code>adk_node_cfo_hitl_quarantine</code>.
            </span>
          ) : (
            quarantinedCards.map((qCard) => (
              <div key={qCard.id} className="hitl-quick-card">
                <span>
                  <strong>{qCard.name}</strong> —{' '}
                  <span style={{ color: '#fbbf24', fontWeight: 700 }}>
                    ${qCard.amount_usd.toFixed(2)} USD
                  </span>{' '}
                  <span style={{ color: '#94a3b8', fontSize: '11px' }}>
                    (Saldo AG Grid: ${Number(policy?.remaining_usd || 0).toFixed(2)})
                  </span>
                </span>
                <button
                  type="button"
                  className="btn-hitl-approve"
                  disabled={resolvingId === qCard.id}
                  onClick={() => void resolveQuarantineCard(qCard.id, 'PAYPAL_SETTLED')}
                >
                  {resolvingId === qCard.id
                    ? '⏳ Liquidando en PayPal...'
                    : '⚡ Aprobar Excepción CFO (+Presupuesto AG Grid) & Liquidar en PayPal'}
                </button>
                <button
                  type="button"
                  className="btn-hitl-reject"
                  disabled={resolvingId === qCard.id}
                  onClick={() => void resolveQuarantineCard(qCard.id, 'BLOCKED_THREAT')}
                >
                  🚫 Rechazar
                </button>
              </div>
            ))
          )}
        </div>
        <div style={{ fontSize: '11.5px', color: '#cbd5e1', whiteSpace: 'nowrap' }}>
          💡 También puedes <strong>arrastrar y soltar (Drag & Drop)</strong> la tarjeta hacia{' '}
          <strong style={{ color: '#34d399' }}>PayPal Sandbox Settled</strong>
        </div>
      </div>

      {/* 4. BRYNTUM TASKBOARD OFICIAL (CON FALLBACK INTERACTIVO SI CDN ESTÁ CARGANDO) */}
      <div
        ref={boardContainerRef}
        className="bryntum-board-host"
        style={{ display: bryntumReady ? 'flex' : 'none' }}
      />

      {!bryntumReady && (
        <div className="fallback-kanban-grid">
          {COLUMNS.map((col) => {
            const colCards = cards.filter((c) => c.status === col.id);
            return (
              <div
                key={col.id}
                className="fallback-kanban-col"
                onDragOver={(e) => e.preventDefault()}
                onDrop={(e) => {
                  e.preventDefault();
                  if (
                    draggedCardId &&
                    (col.id === 'PAYPAL_SETTLED' || col.id === 'BLOCKED_THREAT')
                  ) {
                    void resolveQuarantineCard(draggedCardId, col.id);
                  }
                  setDraggedCardId(null);
                }}
              >
                <div
                  className="fallback-col-header"
                  style={{ borderTop: `3px solid ${col.accent}` }}
                >
                  <div style={{ fontWeight: 700, fontSize: '13px' }}>
                    {col.text} ({colCards.length})
                  </div>
                  <div style={{ fontSize: '11px', color: '#94a3b8', marginTop: '2px' }}>
                    {col.subtitle}
                  </div>
                </div>
                <div className="fallback-col-body">
                  {colCards.map((c) => (
                    <div
                      key={c.id}
                      className="fallback-card"
                      draggable={c.status === 'QUARANTINED'}
                      onDragStart={() => setDraggedCardId(c.id)}
                      style={{
                        borderLeft: `4px solid ${col.accent}`,
                        cursor: c.status === 'QUARANTINED' ? 'grab' : 'default',
                      }}
                    >
                      <div style={{ fontWeight: 700, fontSize: '13px', marginBottom: '4px' }}>
                        {c.name}
                      </div>
                      <div style={{ fontSize: '11.5px', color: '#cbd5e1', marginBottom: '8px' }}>
                        {c.description}
                      </div>
                      <div className="ap2-tb-metrics">
                        <span className="ap2-tb-pill amount">
                          ${c.amount_usd.toFixed(2)} USD
                        </span>
                        <span className="ap2-tb-pill c3">
                          C3: ${c.c3_price_usd.toFixed(2)}
                        </span>
                        <span className="ap2-tb-pill sku">SKU: {c.sku}</span>
                      </div>
                      <div className="ap2-tb-meta" style={{ marginTop: '6px' }}>
                        <div>
                          <strong>ADK Node:</strong> <code>{c.adk_node}</code>
                        </div>
                        <div>
                          <strong>Gate:</strong> <code>{c.gate_code}</code> |{' '}
                          <strong>Ed25519:</strong> <code>{c.ed25519_sig}</code>
                        </div>
                        {c.paypal_order_id && (
                          <div className="ap2-tb-paypal">
                            <strong>PayPal Order:</strong> <code>{c.paypal_order_id}</code>
                          </div>
                        )}
                      </div>
                    </div>
                  ))}
                </div>
              </div>
            );
          })}
        </div>
      )}
    </div>
  );
};
