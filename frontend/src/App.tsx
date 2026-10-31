import React, { useEffect, useState, useCallback } from 'react';
import './App.css';
import { Topbar } from './components/Topbar';
import { ChatPanel } from './components/ChatPanel';
import { PolicyDashboard } from './components/PolicyDashboard';
import { ConfigModal } from './components/ConfigModal';
import type {
  Policy,
  AuditEntry,
  ShieldState,
  ConfigStatus,
  CredentialsPayload,
  TaskBoardCard,
  AdkGraphTelemetry,
} from './types/shield';

export const App: React.FC = () => {
  const [policy, setPolicy] = useState<Policy | null>(null);
  const [auditLog, setAuditLog] = useState<AuditEntry[]>([]);
  const [taskboardCards, setTaskboardCards] = useState<TaskBoardCard[]>([]);
  const [adkGraphTelemetry, setAdkGraphTelemetry] = useState<AdkGraphTelemetry | null>(null);
  const [credsStatus, setCredsStatus] = useState<ConfigStatus | null>(null);
  const [isConfigOpen, setIsConfigOpen] = useState(false);

  const refreshCredsStatus = useCallback(async () => {
    try {
      const res = await fetch('/api/config/status');
      if (res.ok) {
        const st: ConfigStatus = await res.json();
        setCredsStatus(st);
      }
    } catch (err) {
      console.error('Error fetching credentials status:', err);
    }
  }, []);

  const handleSaveCredentials = useCallback(
    async (payload: CredentialsPayload) => {
      await fetch('/api/config', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(payload),
      });
      await refreshCredsStatus();
    },
    [refreshCredsStatus]
  );

  useEffect(() => {
    void refreshCredsStatus();

    const loadInitialState = async () => {
      try {
        const res = await fetch('/api/state');
        if (res.ok) {
          const data: ShieldState = await res.json();
          setPolicy(data.policy);
          setAuditLog(data.audit_log);
          if (data.taskboard_cards) setTaskboardCards(data.taskboard_cards);
          if (data.adk_graph_telemetry) setAdkGraphTelemetry(data.adk_graph_telemetry);
        }
      } catch (err) {
        console.error('Error loading initial state:', err);
      }
    };

    void loadInitialState();

    const evtSource = new EventSource('/api/stream');
    evtSource.onmessage = (event) => {
      try {
        const data: ShieldState = JSON.parse(event.data);
        setPolicy(data.policy);
        setAuditLog(data.audit_log);
        if (data.taskboard_cards) setTaskboardCards(data.taskboard_cards);
        if (data.adk_graph_telemetry) setAdkGraphTelemetry(data.adk_graph_telemetry);
      } catch (err) {
        console.error('Error parsing SSE state:', err);
      }
    };

    return () => {
      evtSource.close();
    };
  }, [refreshCredsStatus]);

  return (
    <>
      <Topbar credsStatus={credsStatus} onOpenConfig={() => setIsConfigOpen(true)} />
      <div className="workspace">
        <ChatPanel agentModel={credsStatus?.gemini_model || 'gemini-3.5-flash'} />
        <PolicyDashboard
          policy={policy}
          auditLog={auditLog}
          taskboardCards={taskboardCards}
          adkGraphTelemetry={adkGraphTelemetry}
        />
      </div>
      <ConfigModal
        isOpen={isConfigOpen}
        onClose={() => setIsConfigOpen(false)}
        onSave={handleSaveCredentials}
      />
    </>
  );
};

export default App;
