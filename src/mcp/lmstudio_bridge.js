#!/usr/bin/env node
/**
 * LM Studio Bridge — MCP Server
 *
 * Bridges Claude to local LM Studio (Qwen3.5 35B) running on Mac Mini.
 * Zero npm dependencies — pure Node.js stdlib only.
 *
 * Place at: ~/.claude/mcp/lmstudio_bridge.js
 *
 * Tools:
 *   lmstudio_chat           — free-form prompt to Qwen3.5
 *   lmstudio_analyze        — structured analysis (CIS data, market data, etc.)
 *   lmstudio_macro_brief    — generate CometCloud macro brief from live data
 *
 * Config (env vars):
 *   LMSTUDIO_BASE   default: http://localhost:1234
 *   LMSTUDIO_MODEL  default: auto-detect from LM Studio /v1/models
 *   LM_TEMPERATURE  default: 0.7
 */

'use strict';

const http     = require('http');
const readline = require('readline');

// ── Config ─────────────────────────────────────────────────────────────────

const BASE        = (process.env.LMSTUDIO_BASE  || 'http://localhost:1234').replace(/\/$/, '');
const MODEL_HINT  = process.env.LMSTUDIO_MODEL  || '';   // leave blank to auto-detect
const DEFAULT_TEMP = parseFloat(process.env.LM_TEMPERATURE || '0.7');

// ── HTTP helper ─────────────────────────────────────────────────────────────

function httpPost(url, body, timeoutMs = 120000) {
  return new Promise((resolve, reject) => {
    const parsed   = new URL(url);
    const bodyBuf  = Buffer.from(JSON.stringify(body));
    const options  = {
      hostname : parsed.hostname,
      port     : parsed.port || 80,
      path     : parsed.pathname,
      method   : 'POST',
      headers  : {
        'Content-Type'   : 'application/json',
        'Content-Length' : bodyBuf.length,
      },
    };
    const req = http.request(options, (res) => {
      const chunks = [];
      res.on('data', c => chunks.push(c));
      res.on('end',  () => {
        try { resolve(JSON.parse(Buffer.concat(chunks).toString())); }
        catch (e) { reject(new Error(`JSON parse failed: ${e.message}`)); }
      });
    });
    req.setTimeout(timeoutMs, () => { req.destroy(); reject(new Error('LM Studio request timed out (120s)')); });
    req.on('error', reject);
    req.write(bodyBuf);
    req.end();
  });
}

function httpGet(url) {
  return new Promise((resolve, reject) => {
    const parsed  = new URL(url);
    const options = { hostname: parsed.hostname, port: parsed.port || 80, path: parsed.pathname };
    http.get(options, (res) => {
      const chunks = [];
      res.on('data', c => chunks.push(c));
      res.on('end',  () => {
        try { resolve(JSON.parse(Buffer.concat(chunks).toString())); }
        catch (e) { reject(new Error(`JSON parse failed: ${e.message}`)); }
      });
    }).on('error', reject);
  });
}

// ── Model detection ─────────────────────────────────────────────────────────

let _model = MODEL_HINT;

async function getModel() {
  if (_model) return _model;
  try {
    const data = await httpGet(`${BASE}/v1/models`);
    const models = data?.data || [];
    if (models.length === 0) throw new Error('No models loaded in LM Studio');
    // Use whatever model is currently loaded — no hardcoded preference
    _model = models[0].id;
    return _model;
  } catch (e) {
    throw new Error(`Cannot reach LM Studio at ${BASE}: ${e.message}`);
  }
}

// ── LM Studio call ──────────────────────────────────────────────────────────

async function chat(messages, temperature = DEFAULT_TEMP, maxTokens = 2048) {
  const model = await getModel();
  const result = await httpPost(`${BASE}/v1/chat/completions`, {
    model,
    messages,
    temperature,
    max_tokens      : maxTokens,
    stream          : false,
    // Disable Qwen3.x thinking/reasoning mode — we want direct structured output,
    // not chain-of-thought. Works with LM Studio >= 0.3.6 and Qwen3 series.
    thinking        : { type: 'disabled' },
    enable_thinking : false,
  });
  const msg     = result?.choices?.[0]?.message;
  // Fallback: some LM Studio versions put the answer in reasoning_content
  // when thinking is partially active; use it as a last resort.
  const content = msg?.content || msg?.reasoning_content || '';
  if (!content) throw new Error(`Empty response from LM Studio. Raw: ${JSON.stringify(result).slice(0, 200)}`);
  return content;
}

// ── Tool definitions ─────────────────────────────────────────────────────────

const TOOLS = [
  {
    name        : 'lmstudio_chat',
    description : (
      'Send a free-form prompt to the local Qwen3.5 35B model running in LM Studio on the Mac Mini. ' +
      'No API cost. Best for long-form analysis, reasoning tasks, or anything that benefits from a ' +
      'large local context window. Responds in the same language as the prompt.'
    ),
    inputSchema : {
      type       : 'object',
      properties : {
        prompt      : { type: 'string', description: 'The prompt or question to send to Qwen3.5.' },
        system      : { type: 'string', description: 'Optional system prompt to set model behaviour.' },
        temperature : { type: 'number', description: 'Sampling temperature 0.0–1.0 (default 0.7). Lower = more deterministic.' },
        max_tokens  : { type: 'number', description: 'Max tokens in response (default 2048, max 8192).' },
      },
      required : ['prompt'],
    },
  },
  {
    name        : 'lmstudio_analyze',
    description : (
      'Ask Qwen3.5 35B to analyze structured data — CIS scores, market data, protocol TVL, portfolio ' +
      'allocations, or any JSON/text payload. Provide the raw data and a specific analysis task. ' +
      'Capped at 1200 tokens to avoid timeout. For single-asset CIS reports use cometcloud_get_cis_report instead.'
    ),
    inputSchema : {
      type       : 'object',
      properties : {
        data        : { type: 'string', description: 'Data to analyze — JSON string, CSV, or plain text.' },
        task        : { type: 'string', description: 'Specific analysis task, e.g. "Identify top 3 risk factors", "Compare pillar scores across L1s".' },
        context     : { type: 'string', description: 'Optional background context (e.g. "CIS v4.1 scoring. Grades: A+>=85...").' },
        temperature : { type: 'number', description: 'Temperature (default 0.3 for analytical tasks).' },
      },
      required : ['data', 'task'],
    },
  },
  {
    name        : 'lmstudio_cis_narrative',
    description : (
      'Add a short institutional analyst commentary (2–3 paragraphs) on top of a pre-built ' +
      'CIS scorecard. Takes the markdown output of cometcloud_get_cis_report and returns analyst ' +
      'narrative — regime context, pillar interpretation, key risks. ' +
      'Fast: capped at 600 tokens to avoid timeout. Compliance-safe: no BUY/SELL/HOLD/LONG.'
    ),
    inputSchema : {
      type       : 'object',
      properties : {
        scorecard : { type: 'string', description: 'Markdown output from cometcloud_get_cis_report.' },
        focus     : { type: 'string', description: 'Optional focus: "near-term risks", "sector comparison", "regime sensitivity".' },
      },
      required : ['scorecard'],
    },
  },
  {
    name        : 'lmstudio_macro_brief',
    description : (
      'Generate a CometCloud Macro Brief using Qwen3.5 35B. Accepts raw macro data ' +
      '(Fear & Greed, BTC dominance, market cap, regime, sector flows) and produces a ' +
      'structured institutional-quality macro narrative. Same pipeline as the dashboard MacroBrief widget.'
    ),
    inputSchema : {
      type       : 'object',
      properties : {
        macro_data : {
          type        : 'object',
          description : 'Macro snapshot object. Include: fear_greed_index, fear_greed_label, btc_dominance, btc_price, total_market_cap_usd, defi_tvl_usd, macro_regime, top_movers.',
        },
        style : {
          type        : 'string',
          enum        : ['concise', 'detailed'],
          description : 'Output style — concise (3 paragraphs) or detailed (full report). Default: concise.',
        },
      },
      required : ['macro_data'],
    },
  },
];

// ── Shared compliance rules (EN + ZH) ────────────────────────────────────────
// Applied to every tool. Both languages needed: model may respond in Chinese.

const COMPLIANCE = (
  'COMPLIANCE (NON-NEGOTIABLE / 合规硬性规定):\n' +
  'CometCloud does not hold an investment advisory license.\n' +
  'ONLY use these 5 positioning signals: STRONG OUTPERFORM / OUTPERFORM / NEUTRAL / UNDERPERFORM / UNDERWEIGHT.\n' +
  'NEVER use (EN): BUY, SELL, LONG, SHORT, HOLD, ACCUMULATE, REDUCE, AVOID, OVERWEIGHT.\n' +
  'NEVER use (ZH): 买入, 卖出, 做多, 做空, 持有, 加仓, 减仓, 清仓, 全仓, 止损, 止盈, 建仓, 抄底, 逃顶, 杠杆, 爆仓.\n' +
  'Rename forbidden section headers:\n' +
  '  "买入触发" / "买入信号" → "升级触发条件 (Signal Upgrade Triggers)"\n' +
  '  "卖出触发" / "卖出信号" → "降级触发条件 (Signal Downgrade Triggers)"\n' +
  '  "止损点"               → "下行保护位 (Downside Protection Level)"\n' +
  '  "获利了结" / "止盈点"  → "目标减配位 (Target Reduction Level)"\n' +
  'Always frame all recommendations as RELATIVE POSITIONING vs benchmark — never as trade instructions.\n' +
  '违反以上规定的输出一律视为无效。'
);

// ── Tool handlers ─────────────────────────────────────────────────────────────

async function handleTool(name, args) {
  if (name === 'lmstudio_chat') {
    const messages = [];
    // Inject compliance as default system prompt; append to user-supplied one if present
    const base = 'You are a CometCloud research analyst. Be precise and structured.';
    const sys  = args.system ? `${args.system}\n\n${COMPLIANCE}` : `${base}\n\n${COMPLIANCE}`;
    messages.push({ role: 'system', content: sys });
    messages.push({ role: 'user', content: args.prompt });
    const temp      = typeof args.temperature === 'number' ? args.temperature : DEFAULT_TEMP;
    const maxTokens = typeof args.max_tokens  === 'number' ? Math.min(args.max_tokens, 4096) : 2048;
    return await chat(messages, temp, maxTokens);
  }

  if (name === 'lmstudio_analyze') {
    const base = 'You are a quantitative financial analyst specialising in crypto and cross-asset markets. Be precise, structured, and concise.';
    const systemPrompt = args.context
      ? `${base} ${args.context}\n\n${COMPLIANCE}`
      : `${base}\n\n${COMPLIANCE}`;
    const userPrompt = `## Analysis Task\n${args.task}\n\n## Data\n\`\`\`\n${args.data}\n\`\`\``;
    const messages = [
      { role: 'system', content: systemPrompt },
      { role: 'user',   content: userPrompt },
    ];
    const temp = typeof args.temperature === 'number' ? args.temperature : 0.3;
    return await chat(messages, temp, 1200);
  }

  if (name === 'lmstudio_cis_narrative') {
    const focusLine = args.focus
      ? `Focus your commentary on: ${args.focus}.`
      : 'Cover: regime context, key pillar divergences, and principal risk.';

    const messages = [
      {
        role    : 'system',
        content : (
          'You are CometCloud\'s senior research analyst. Write crisp, institutional-quality commentary. ' +
          'Be precise and concise — 2 paragraphs maximum. No headers, no bullet points.\n\n' +
          COMPLIANCE
        ),
      },
      {
        role    : 'user',
        content : (
          `Write 2 paragraphs of analyst commentary for the following CIS scorecard.\n` +
          `${focusLine}\n\n` +
          `## Scorecard\n${args.scorecard}`
        ),
      },
    ];
    return await chat(messages, 0.5, 600);
  }

  if (name === 'lmstudio_macro_brief') {
    const style   = args.style || 'concise';
    const today   = new Date().toISOString().split('T')[0];   // YYYY-MM-DD — ground the model's date
    const data    = typeof args.macro_data === 'object'
      ? JSON.stringify(args.macro_data, null, 2)
      : String(args.macro_data);

    const lengthGuide = style === 'concise'
      ? 'Write 3 concise paragraphs: (1) regime & sentiment, (2) capital flows & sector rotation, (3) key risks and opportunities.'
      : 'Write a detailed macro brief with sections: Macro Regime, Sentiment & Positioning, Capital Flows, Sector Rotation, Key Risks, Outlook.';

    const maxTok = style === 'detailed' ? 3500 : 1800;   // detailed needs more room

    const messages = [
      {
        role    : 'system',
        content : (
          'You are CometCloud\'s macro analyst. Write institutional-quality macro briefs for crypto and cross-asset markets. ' +
          'Use precise financial language. ' +
          'COMPLIANCE (NON-NEGOTIABLE): ONLY use these signals: STRONG OUTPERFORM / OUTPERFORM / NEUTRAL / UNDERPERFORM / UNDERWEIGHT. ' +
          'NEVER use: BUY, SELL, LONG, SHORT, ACCUMULATE, REDUCE, AVOID, HOLD, OVERWEIGHT as positioning language. ' +
          'Never use directional trade language ("go long", "long BTC", "short ETH"). ' +
          'Frame everything as relative positioning. ' +
          'End every brief with: "*This brief is for informational purposes only and does not constitute investment advice.*"' +
          'Format in clean markdown.'
        ),
      },
      {
        role    : 'user',
        content : (
          `Today's date: ${today}\n\n` +
          `Generate a CometCloud Macro Brief from the following data.\n\n` +
          `${lengthGuide}\n\n` +
          `## Market Data\n\`\`\`json\n${data}\n\`\`\``
        ),
      },
    ];
    return await chat(messages, 0.6, maxTok);
  }

  throw new Error(`Unknown tool: ${name}`);
}

// ── MCP stdio protocol ────────────────────────────────────────────────────────

const rl = readline.createInterface({ input: process.stdin, terminal: false });

function send(obj) {
  process.stdout.write(JSON.stringify(obj) + '\n');
}

rl.on('line', async (line) => {
  const raw = line.trim();
  if (!raw) return;

  let msg;
  try { msg = JSON.parse(raw); }
  catch { return; }   // ignore unparseable lines

  const { id, method, params } = msg;

  // Notifications — no response
  if (method === 'notifications/initialized' || method === 'notifications/cancelled') return;

  try {
    if (method === 'initialize') {
      send({
        jsonrpc : '2.0', id,
        result  : {
          protocolVersion : '2024-11-05',
          capabilities    : { tools: {} },
          serverInfo      : { name: 'lmstudio_mcp', version: '1.0.0' },
        },
      });

    } else if (method === 'tools/list') {
      send({ jsonrpc: '2.0', id, result: { tools: TOOLS } });

    } else if (method === 'tools/call') {
      const { name, arguments: args } = params;
      const text = await handleTool(name, args || {});
      send({ jsonrpc: '2.0', id, result: { content: [{ type: 'text', text }] } });

    } else if (method === 'ping') {
      send({ jsonrpc: '2.0', id, result: {} });

    } else {
      send({ jsonrpc: '2.0', id, error: { code: -32601, message: `Method not found: ${method}` } });
    }

  } catch (e) {
    send({ jsonrpc: '2.0', id, error: { code: -32603, message: e.message } });
  }
});

rl.on('close', () => process.exit(0));
