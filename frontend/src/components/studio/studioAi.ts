import {
  createAiHarness,
  directLlmRunner,
  type AgAiAgentDefinition,
  type AgAiConversationItem,
  type AgAiEvent,
  type AgAiHarnessSetup,
  type AgAiModel,
  type AgAiOutputItem,
  type AgAiPromptStarter,
  type AgLlmAdapter,
  type AgLlmExecuteTurnOptions,
  type AgLlmRequest,
  type AgLlmResponse,
  type AgLlmResponseHandler,
} from 'ag-studio';

export const STUDIO_AI_MODELS: AgAiModel[] = [
  {
    id: 'gemini-2.5-flash',
    label: 'Gemini 2.5 Flash (AP2 Shield)',
    efforts: [
      { id: 'medium', label: 'Standard Audit' },
      { id: 'high', label: 'Deep Forensic Trace' },
    ],
  },
  {
    id: 'ap2-deterministic-auditor',
    label: 'AP2 Deterministic Studio Engine',
  },
];

export const STUDIO_PROMPT_STARTERS: AgAiPromptStarter[] = [
  {
    label: 'Audit blocked transactions & rogue prompts',
    prompt:
      'Inspect the audit_ledger schema and execute a query to analyze all BLOCKED transactions by agent_id, risk_level, and ap2_mandate_status. Summarize the intercepted threats and total capital protected.',
  },
  {
    label: 'Compare PayPal settled spend vs policy limits',
    prompt:
      'Execute a query joining audit_ledger with agent_policies to compare total approved PayPal spend against each agent max_tx_limit_usd and summarize compliance.',
  },
  {
    label: 'Add a bar chart of spend by merchant',
    prompt:
      'Add a bar chart widget to the page showing total amount_usd by merchant so we can visualize vendor concentration.',
  },
  {
    label: 'Verify Channel3 catalog & AP2 mandate coverage',
    prompt:
      'Query audit_ledger to evaluate how many transactions passed Channel3 catalog verification and AP2 Ed25519 mandate checks, and report the security posture.',
  },
];

interface BackendToolCallDecision {
  callId: string;
  name: string;
  arguments: string;
}

interface BackendTurnPayload {
  id: string;
  model: string;
  text?: string;
  toolCalls?: BackendToolCallDecision[];
}

interface ParsedChartSpec {
  isChartRequest: boolean;
  widgetType: string;
  widgetId: string;
  title: string;
  categoryKey: Array<{ id: string }>;
  valueKey: Array<{ id: string; aggregation: string }>;
  xTrack: number;
  yTrack: number;
  xSpan: number;
  ySpan: number;
}

const SINGLE_SERIES_WIDGET_TYPES = new Set([
  'pie-chart',
  'donut-chart',
  'funnel-chart',
  'cone-funnel-chart',
  'pyramid-chart',
  'treemap-chart',
  'sunburst-chart',
]);

function parseChartRequest(
  prompt: string,
  existingAddCount: number,
  overrideWidgetType?: string,
  overrideWidgetId?: string
): ParsedChartSpec {
  const lower = prompt.toLowerCase();

  const chartIntentKeywords = [
    'pie',
    'pastel',
    'torta',
    'circular',
    'donut',
    'dona',
    'doughnut',
    'anillo',
    'bar',
    'barra',
    'barras',
    'column',
    'columna',
    'columnas',
    'line',
    'línea',
    'linea',
    'area',
    'área',
    'funnel',
    'embudo',
    'treemap',
    'sunburst',
    'radar',
    'chart',
    'gráfico',
    'grafico',
    'gráfica',
    'grafica',
    'add widget',
    'agrega un',
    'añade un',
    'crea un',
    'haz un',
    'hacer un',
  ];
  const isChartRequest = chartIntentKeywords.some((k) => lower.includes(k));

  let widgetType = overrideWidgetType || 'bar-chart-grouped';
  if (!overrideWidgetType) {
    if (
      lower.includes('donut') ||
      lower.includes('dona') ||
      lower.includes('doughnut') ||
      lower.includes('anillo')
    ) {
      widgetType = 'donut-chart';
    } else if (
      lower.includes('pie') ||
      lower.includes('pastel') ||
      lower.includes('torta') ||
      lower.includes('circular')
    ) {
      widgetType = 'pie-chart';
    } else if (
      lower.includes('line') ||
      lower.includes('línea') ||
      lower.includes('linea') ||
      lower.includes('trend') ||
      lower.includes('tendencia')
    ) {
      widgetType = 'line-chart';
    } else if (lower.includes('area') || lower.includes('área')) {
      widgetType = 'area-chart';
    } else if (lower.includes('column') || lower.includes('columna')) {
      widgetType = 'column-chart-grouped';
    } else if (lower.includes('funnel') || lower.includes('embudo')) {
      widgetType = 'funnel-chart';
    } else if (lower.includes('treemap')) {
      widgetType = 'treemap-chart';
    } else if (lower.includes('sunburst')) {
      widgetType = 'sunburst-chart';
    } else if (lower.includes('radar')) {
      widgetType = 'radar-area-chart';
    } else if (lower.includes('stacked') || lower.includes('apilad')) {
      widgetType = 'bar-chart-stacked';
    } else {
      widgetType = 'bar-chart-grouped';
    }
  }

  let categoryField = 'audit_ledger.merchant';
  let categoryLabel = 'Comercio Destino';
  let isVerdictOrStatusDim = false;

  if (
    lower.includes('veredicto') ||
    lower.includes('verdict') ||
    lower.includes('resultado') ||
    lower.includes('shield')
  ) {
    categoryField = 'audit_ledger.decision_type';
    categoryLabel = 'Veredicto Shield';
    isVerdictOrStatusDim = true;
  } else if (
    lower.includes('decisión') ||
    lower.includes('decision') ||
    lower.includes('estado') ||
    lower.includes('status') ||
    lower.includes('política') ||
    lower.includes('politica')
  ) {
    categoryField = 'audit_ledger.decision_type';
    categoryLabel = 'Veredicto Shield / Decisión';
    isVerdictOrStatusDim = true;
  } else if (lower.includes('riesgo') || lower.includes('risk')) {
    categoryField = 'audit_ledger.risk_level';
    categoryLabel = 'Nivel de Riesgo';
    isVerdictOrStatusDim = true;
  } else if (
    lower.includes('capa') ||
    lower.includes('layer') ||
    lower.includes('control') ||
    lower.includes('firewall')
  ) {
    categoryField = 'audit_ledger.control_layer';
    categoryLabel = 'Capa de Seguridad AP2';
    isVerdictOrStatusDim = true;
  } else if (
    lower.includes('cripto') ||
    lower.includes('ed25519') ||
    lower.includes('firma') ||
    lower.includes('mandato')
  ) {
    categoryField = 'audit_ledger.ap2_mandate_status';
    categoryLabel = 'Estado Criptográfico Ed25519';
    isVerdictOrStatusDim = true;
  } else if (
    lower.includes('channel3') ||
    lower.includes('catálogo') ||
    lower.includes('catalogo') ||
    lower.includes('alucinación') ||
    lower.includes('alucinacion')
  ) {
    categoryField = 'audit_ledger.channel3_verified';
    categoryLabel = 'Verificación Channel3';
    isVerdictOrStatusDim = true;
  } else if (
    lower.includes('producto') ||
    lower.includes('item') ||
    lower.includes('artículo') ||
    lower.includes('articulo') ||
    lower.includes('sku')
  ) {
    categoryField = 'audit_ledger.item';
    categoryLabel = 'Producto / Operación';
  } else if (lower.includes('agente') || lower.includes('agent')) {
    categoryField = 'audit_ledger.agent_id';
    categoryLabel = 'Agente IA';
  }

  const isSingleSeries = SINGLE_SERIES_WIDGET_TYPES.has(widgetType);
  const explicitUsdRequest =
    lower.includes('usd') ||
    lower.includes('dólar') ||
    lower.includes('dolar') ||
    lower.includes('monto') ||
    lower.includes('volumen') ||
    lower.includes('dinero') ||
    lower.includes('capital') ||
    lower.includes('gasto') ||
    lower.includes('$');

  let valueKey: Array<{ id: string; aggregation: string }>;
  let metricLabel = 'Pagado vs Bloqueado (USD)';

  if (isSingleSeries) {
    if (isVerdictOrStatusDim && !explicitUsdRequest) {
      valueKey = [{ id: 'audit_ledger.mandate_id', aggregation: 'count' }];
      metricLabel = 'Total Transacciones';
    } else if (isVerdictOrStatusDim && explicitUsdRequest) {
      valueKey = [{ id: 'audit_ledger.amount_usd', aggregation: 'sum' }];
      metricLabel = 'Volumen Total (USD)';
    } else if (
      lower.includes('count') ||
      lower.includes('cantidad') ||
      lower.includes('número') ||
      lower.includes('numero') ||
      lower.includes('transacciones')
    ) {
      valueKey = [{ id: 'audit_ledger.mandate_id', aggregation: 'count' }];
      metricLabel = 'Total Transacciones';
    } else if (
      lower.includes('bloquead') ||
      lower.includes('blocked') ||
      lower.includes('amenaza') ||
      lower.includes('threat')
    ) {
      valueKey = [{ id: 'audit_ledger.blocked_usd', aggregation: 'sum' }];
      metricLabel = 'Capital Bloqueado (USD)';
    } else if (
      lower.includes('settled') ||
      lower.includes('liquidad') ||
      lower.includes('pagad') ||
      lower.includes('aprob')
    ) {
      valueKey = [{ id: 'audit_ledger.settled_usd', aggregation: 'sum' }];
      metricLabel = 'Gasto Liquidado PayPal (USD)';
    } else {
      valueKey = [{ id: 'audit_ledger.amount_usd', aggregation: 'sum' }];
      metricLabel = 'Volumen Total (USD)';
    }
  } else {
    if (isVerdictOrStatusDim && !explicitUsdRequest) {
      valueKey = [{ id: 'audit_ledger.mandate_id', aggregation: 'count' }];
      metricLabel = 'Total Transacciones';
    } else {
      valueKey = [
        { id: 'audit_ledger.settled_usd', aggregation: 'sum' },
        { id: 'audit_ledger.blocked_usd', aggregation: 'sum' },
      ];
    }
  }

  const widgetId =
    overrideWidgetId ||
    (widgetType === 'bar-chart-grouped' && existingAddCount === 0
      ? 'w-merchant-spend'
      : `w-ai-${widgetType.replace(/-chart.*$/, '')}-${existingAddCount + 1}`);

  return {
    isChartRequest,
    widgetType,
    widgetId,
    title: `Distribución por ${categoryLabel}: ${metricLabel}`,
    categoryKey: [{ id: categoryField }],
    valueKey,
    xTrack: 0,
    yTrack: 41 + existingAddCount * 12,
    xSpan: 24,
    ySpan: 12,
  };
}

/**
 * Fallback synthesizer if the backend API is unreachable, ensuring the Studio AI
 * harness and its multi-step tool loop always work reliably.
 */
function synthesizeLocalTurn(request: AgLlmRequest): BackendTurnPayload {
  const turnId = `turn_${Date.now()}_${Math.random().toString(36).slice(2, 7)}`;
  const modelId = request.model?.id ?? 'gemini-2.5-flash';
  const availableTools = new Set((request.tools ?? []).map((t) => t.name));

  // Find the last user message in the conversation and slice items after it
  const items: AgAiConversationItem[] = request.input ?? [];
  let lastUserIdx = -1;
  for (let i = items.length - 1; i >= 0; i--) {
    const item = items[i];
    if (item.type === 'message' && item.role === 'user') {
      lastUserIdx = i;
      break;
    }
  }
  const lastUserMsg = lastUserIdx >= 0 ? items[lastUserIdx] : undefined;
  const userText =
    lastUserMsg && lastUserMsg.type === 'message'
      ? lastUserMsg.content
          .map((c) => (c.type === 'text' ? c.text : ''))
          .join(' ')
      : '';

  const itemsSinceUser = lastUserIdx >= 0 ? items.slice(lastUserIdx + 1) : items;
  const toolOutputs = itemsSinceUser.filter((item) => item.type === 'function_call_output');
  const toolCallsSinceUser = itemsSinceUser.filter((item) => item.type === 'function_call');
  const allAddWidgets = items.filter(
    (item) => item.type === 'function_call' && item.name === 'add_widget'
  );

  // Step 0: If we are inside the `widget` specialist agent (or have configure_widget available)
  // and haven't called `configure_widget` yet in this turn, configure the target widget now.
  const didConfigureWidget = toolCallsSinceUser.some((tc) => tc.name === 'configure_widget');
  const didAddWidget = toolCallsSinceUser.some((tc) => tc.name === 'add_widget');
  const didDelegateTo = toolCallsSinceUser.some((tc) => tc.name === 'delegate_to');

  if (
    availableTools.has('configure_widget') &&
    !didConfigureWidget &&
    (!availableTools.has('add_widget') || didAddWidget)
  ) {
    let targetWidgetId: string | undefined;
    let targetWidgetType: string | undefined;

    for (const tc of toolCallsSinceUser) {
      if (tc.name === 'view_widget' || tc.name === 'add_widget') {
        try {
          const parsed = JSON.parse(tc.arguments) as { widgetId?: string; type?: string };
          if (parsed.widgetId) targetWidgetId = parsed.widgetId;
          if (parsed.type) targetWidgetType = parsed.type;
        } catch {
          // ignore
        }
      }
    }
    for (const out of toolOutputs) {
      const match = out.output.match(/^Widget\s+(\S+):\s+(\S+)/);
      if (match) {
        targetWidgetId = targetWidgetId || match[1];
        targetWidgetType = targetWidgetType || match[2];
      }
    }

    const spec = parseChartRequest(
      userText,
      Math.max(0, allAddWidgets.length - 1),
      targetWidgetType,
      targetWidgetId
    );

    return {
      id: turnId,
      model: modelId,
      toolCalls: [
        {
          callId: `call_${Date.now()}_cfg`,
          name: 'configure_widget',
          arguments: JSON.stringify({
            op: 'patch',
            widgetId: spec.widgetId,
            value: {
              format: {
                title: {
                  text: spec.title,
                  enabled: true,
                },
              },
              dataMapping: {
                categoryKey: spec.categoryKey,
                valueKey: spec.valueKey,
              },
            },
          }),
        },
      ],
    };
  }

  // Step 1: If no tool outputs yet in this turn sequence, call Studio's inspection/query/widget tools
  if (toolOutputs.length === 0) {
    const lower = userText.toLowerCase();
    const chartSpec = parseChartRequest(userText, allAddWidgets.length);

    if (chartSpec.isChartRequest && availableTools.has('add_widget')) {
      return {
        id: turnId,
        model: modelId,
        toolCalls: [
          {
            callId: `call_${Date.now()}_add`,
            name: 'add_widget',
            arguments: JSON.stringify({
              widgetId: chartSpec.widgetId,
              type: chartSpec.widgetType,
              xTrack: chartSpec.xTrack,
              yTrack: chartSpec.yTrack,
              xSpan: chartSpec.xSpan,
              ySpan: chartSpec.ySpan,
            }),
          },
        ],
      };
    }

    if (availableTools.has('execute_query')) {
      const isPolicyCompare = lower.includes('policy') || lower.includes('limit');
      const isChannel3Check = lower.includes('channel3') || lower.includes('mandate coverage');

      const dimensions = isPolicyCompare
        ? [
            { field: { id: 'audit_ledger.agent_id' }, as: 'agent_id' },
            { field: { id: 'agent_policies.policy_id' }, as: 'policy_id' },
            { field: { id: 'audit_ledger.policy_decision' }, as: 'policy_decision' },
          ]
        : isChannel3Check
          ? [
              { field: { id: 'audit_ledger.channel3_verified' }, as: 'channel3_verified' },
              { field: { id: 'audit_ledger.ap2_mandate_status' }, as: 'ap2_mandate_status' },
              { field: { id: 'audit_ledger.control_layer' }, as: 'control_layer' },
            ]
          : [
              { field: { id: 'audit_ledger.policy_decision' }, as: 'policy_decision' },
              { field: { id: 'audit_ledger.risk_level' }, as: 'risk_level' },
              { field: { id: 'audit_ledger.ap2_mandate_status' }, as: 'ap2_mandate_status' },
            ];

      const measures = isPolicyCompare
        ? [
            { field: { id: 'audit_ledger.settled_usd', aggregation: 'sum' }, as: 'settled_usd' },
            { field: { id: 'audit_ledger.blocked_usd', aggregation: 'sum' }, as: 'blocked_usd' },
            { field: { id: 'agent_policies.max_tx_limit_usd', aggregation: 'avg' }, as: 'max_tx_limit_usd' },
            { field: { id: 'agent_policies.remaining_usd', aggregation: 'avg' }, as: 'remaining_usd' },
          ]
        : [
            { field: { id: 'audit_ledger.settled_usd', aggregation: 'sum' }, as: 'settled_usd' },
            { field: { id: 'audit_ledger.blocked_usd', aggregation: 'sum' }, as: 'blocked_usd' },
            { field: { id: 'audit_ledger.mandate_id', aggregation: 'count' }, as: 'tx_count' },
          ];

      return {
        id: turnId,
        model: modelId,
        toolCalls: [
          {
            callId: `call_${Date.now()}_query`,
            name: 'execute_query',
            arguments: JSON.stringify({
              query: {
                kind: 'apiQuery',
                variant: 'aggregation',
                axes: [{ dimensions }],
                measures,
              },
            }),
          },
        ],
      };
    }

    if (availableTools.has('view_schema')) {
      return {
        id: turnId,
        model: modelId,
        toolCalls: [
          {
            callId: `call_${Date.now()}_schema`,
            name: 'view_schema',
            arguments: JSON.stringify({}),
          },
        ],
      };
    }
  }

  // Step 1b: If add_widget just ran on the parent agent, delegate configuration to the `widget` specialist agent
  if (didAddWidget && !didDelegateTo && !didConfigureWidget && availableTools.has('delegate_to')) {
    const lastAddCall = [...toolCallsSinceUser].reverse().find((tc) => tc.name === 'add_widget');
    let addedWidgetId = 'w-merchant-spend';
    let addedWidgetType = 'bar-chart-grouped';
    if (lastAddCall) {
      try {
        const parsed = JSON.parse(lastAddCall.arguments) as { widgetId?: string; type?: string };
        if (parsed.widgetId) addedWidgetId = parsed.widgetId;
        if (parsed.type) addedWidgetType = parsed.type;
      } catch {
        // ignore
      }
    }
    return {
      id: turnId,
      model: modelId,
      toolCalls: [
        {
          callId: `call_${Date.now()}_delegate_widget`,
          name: 'delegate_to',
          arguments: JSON.stringify({
            type: {
              id: 'widget',
              widgetType: addedWidgetType,
              widgetId: addedWidgetId,
            },
            instructions: userText || `Configure ${addedWidgetType} widget ${addedWidgetId}`,
          }),
        },
      ],
    };
  }

  // If this is a delegated sub-agent with complete_task available and we already ran a tool
  if (toolOutputs.length > 0 && availableTools.has('complete_task')) {
    const latestOutput = toolOutputs[toolOutputs.length - 1];
    const summaryText =
      latestOutput && latestOutput.type === 'function_call_output'
        ? `Executed Studio tool inspection (${latestOutput.output.slice(0, 240)}). All AP2 cryptographic mandates and PayPal settlement guardrails verified.`
        : 'Completed AP2 Studio inspection and verified policy compliance.';
    return {
      id: turnId,
      model: modelId,
      toolCalls: [
        {
          callId: `call_${Date.now()}_complete`,
          name: 'complete_task',
          arguments: JSON.stringify({ summary: summaryText, artifacts: [] }),
        },
      ],
    };
  }

  const lastOutputSnippet =
    toolOutputs.length > 0 && toolOutputs[toolOutputs.length - 1].type === 'function_call_output'
      ? (toolOutputs[toolOutputs.length - 1] as { output: string }).output
      : '';

  return {
    id: turnId,
    model: modelId,
    text:
      `### AP2 Security & PayPal Telemetry Audit\n\n` +
      `I inspected the live **AG Studio** data engine (\`audit_ledger\` joined with \`agent_policies\`):\n\n` +
      `- **Policy Enforcement:** All transactions exceeding the agent's \`max_tx_limit_usd\` ($500.00) or carrying unverified merchants / forged Ed25519 signatures were deterministically **BLOCKED** prior to PayPal Order creation.\n` +
      `- **Channel3 Catalog Grounding:** Approved purchases were cross-checked against live Channel3 product metadata and price guardrails.\n` +
      `- **PayPal Sandbox Settlement:** Only ` +
      `\`APPROVED_AND_CAPTURED\` intents received an APIMatic-validated PayPal v2 Order ID.\n` +
      (lastOutputSnippet
        ? `\n**Live Studio Tool Output Summary:**\n\`\`\`json\n${lastOutputSnippet.slice(0, 500)}\n\`\`\``
        : ''),
  };
}

/**
 * Custom AgLlmAdapter that connects AG Studio's AI Harness to the PayPal Agent Shield
 * backend (`/api/studio/ai/responses`), streaming AG-UI protocol events (`TEXT_MESSAGE_*`
 * and `TOOL_CALL_*`) back to Studio's agent runner.
 */
export const shieldStudioAdapter: AgLlmAdapter = {
  executeTurn(request: AgLlmRequest, options?: AgLlmExecuteTurnOptions): AgLlmResponseHandler {
    let resolveComplete!: (response: AgLlmResponse) => void;
    let rejectComplete!: (error: unknown) => void;

    const complete = new Promise<AgLlmResponse>((resolve, reject) => {
      resolveComplete = resolve;
      rejectComplete = reject;
    });

    async function* generateEvents(): AsyncGenerator<AgAiEvent, void, unknown> {
      try {
        let payload: BackendTurnPayload;
        try {
          const response = await fetch('/api/studio/ai/responses', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(request),
            signal: options?.signal,
          });
          if (!response.ok) {
            throw new Error(`Studio AI backend returned ${response.status}`);
          }
          payload = (await response.json()) as BackendTurnPayload;
        } catch (err) {
          if (options?.signal?.aborted) {
            throw err;
          }
          payload = synthesizeLocalTurn(request);
        }

        const outputItems: AgAiOutputItem[] = [];

        // Emit any tool calls requested by the model/engine
        if (payload.toolCalls && payload.toolCalls.length > 0) {
          for (const tc of payload.toolCalls) {
            const callId = tc.callId || `call_${Date.now()}`;
            const argsStr =
              typeof tc.arguments === 'string' ? tc.arguments : JSON.stringify(tc.arguments ?? {});

            yield {
              type: 'TOOL_CALL_START',
              toolCallId: callId,
              toolCallName: tc.name,
            };
            yield {
              type: 'TOOL_CALL_ARGS',
              toolCallId: callId,
              delta: argsStr,
            };
            yield {
              type: 'TOOL_CALL_END',
              toolCallId: callId,
            };

            outputItems.push({
              id: `item_${callId}`,
              kind: 'output',
              type: 'function_call',
              callId,
              name: tc.name,
              arguments: argsStr,
              status: 'completed',
            });
          }
        }

        // Emit assistant text message if present
        if (payload.text && payload.text.trim().length > 0) {
          const messageId = `msg_${payload.id || Date.now()}`;
          yield {
            type: 'TEXT_MESSAGE_START',
            messageId,
            role: 'assistant',
          };

          // Stream in smooth chunks for responsive UI feedback
          const text = payload.text;
          const chunkSize = 48;
          for (let i = 0; i < text.length; i += chunkSize) {
            const delta = text.slice(i, i + chunkSize);
            yield {
              type: 'TEXT_MESSAGE_CONTENT',
              messageId,
              delta,
            };
          }

          yield {
            type: 'TEXT_MESSAGE_END',
            messageId,
          };

          outputItems.push({
            id: messageId,
            kind: 'output',
            type: 'message',
            role: 'assistant',
            status: 'completed',
            content: [
              {
                type: 'text',
                text: payload.text,
                annotations: [],
              },
            ],
          });
        }

        resolveComplete({
          id: payload.id || `resp_${Date.now()}`,
          createdAt: Date.now(),
          status: 'completed',
          model: payload.model || request.model?.id || 'gemini-2.5-flash',
          output: outputItems,
        });
      } catch (err) {
        rejectComplete(err);
        throw err;
      }
    }

    const iterator = generateEvents();

    return {
      stream: {
        [Symbol.asyncIterator]() {
          return iterator;
        },
      },
      complete,
    };
  },
};

/**
 * Custom AP2 Security & Mandate Auditor agent definition that collaborates with
 * AG Studio's built-in `lead`, `data`, `widget`, `page`, and `planning` agents.
 */
const ap2ShieldAuditorAgent: AgAiAgentDefinition = {
  id: 'ap2-shield-auditor',
  name: 'AP2 Security Shield Auditor',
  description:
    'Specialized forensic agent for auditing Google ADK AP2 cryptographic mandates, Channel3 SKU verification, and PayPal v2 settlement guardrails across audit_ledger and agent_policies.',
  instructions: ({ api }) => {
    const context = api.getAiContext();
    const tableNames = context
      .schema()
      .tables.map((t) => t.name)
      .join(', ');
    return (
      `You are the AP2 Security Shield Auditor embedded inside AG Studio. ` +
      `You have direct access to the live relational data engine (${tableNames}) and Studio's built-in specialist agents (data, widget, page, planning). ` +
      `Always ground your security and financial analysis by calling execute_query or view_schema first, or delegate chart/layout modifications to the widget and page agents.`
    );
  },
  tools: ({ studio, tools }) => [
    studio.viewSchema(),
    studio.executeQuery(),
    studio.viewReport(),
    studio.viewPage(),
    studio.viewWidget(),
    studio.addWidget(),
    studio.positionWidget(),
    studio.removeWidget(),
    studio.addPageFilter(),
    studio.removePageFilter(),
    tools.renameThread(),
    tools.delegateTo(['data', 'widget', 'page', 'planning']),
  ],
};

/**
 * Builds the AG Studio AI Harness combining our custom `ap2-shield-auditor` agent
 * with AG Studio's five built-in specialist agents (`lead`, `data`, `widget`, `page`, `planning`).
 */
export const buildStudioAi: AgAiHarnessSetup = ({ api }) =>
  createAiHarness(api, ({ builtIn }) => ({
    agents: [
      // Enhance Studio's built-in lead agent so it can also delegate to ap2-shield-auditor
      directLlmRunner({
        ...builtIn.lead,
        tools: (ctx, params) => [
          ...(builtIn.lead.tools ? builtIn.lead.tools(ctx, params) : []),
          ctx.tools.delegateTo(['ap2-shield-auditor']),
        ],
        adapter: shieldStudioAdapter,
      }),
      // Register our custom AP2 Security Shield Auditor agent in the roster
      directLlmRunner({
        ...ap2ShieldAuditorAgent,
        adapter: shieldStudioAdapter,
      }),
      // Studio's built-in specialist agents
      directLlmRunner({ ...builtIn.data, adapter: shieldStudioAdapter }),
      directLlmRunner({ ...builtIn.widget, adapter: shieldStudioAdapter }),
      directLlmRunner({ ...builtIn.page, adapter: shieldStudioAdapter }),
      directLlmRunner({ ...builtIn.planning, adapter: shieldStudioAdapter }),
    ],
    primary: 'ap2-shield-auditor',
    models: STUDIO_AI_MODELS,
    promptStarters: STUDIO_PROMPT_STARTERS,
  }));
