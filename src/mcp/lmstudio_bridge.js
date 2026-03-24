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
    // Prefer any model with qwen in the name
    const qwen = models.find(m => m.id.toLowerCase().includes('qwen'));
    _model = (qwen || models[0]).id;
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
    max_tokens : maxTokens,
    stream     : false,
  });
  const content = result?.choices?.[0]?.message?.content;
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
      'The model runs locally with full context; ideal for multi-asset analysis or detailed breakdowns.'
    ),
    inputSchema : {
      type       : 'object',
      properties : {
        data        : { type: 'string', description: 'Data to analyze — JSON string, CSV, or plain text. Can be CIS universe, portfolio, market snapshot, etc.' },
        task        : { type: 'string', description: 'Specific analysis task, e.g. "Identify the top 3 risk factors", "Summarize regime signals", "Compare pillar scores across L1s".' },
        context     : { type: 'string', description: 'Optional background context (e.g. "This is CIS v4.1 scoring data. Grades are absolute: A+>=85...").' },
        temperature : { type: 'number', description: 'Temperature (default 0.3 for analytical tasks).' },
      },
      required : ['data', 'task'],
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

// ── Tool handlers ─────────────────────────────────────────────────────────────

async function handleTool(name, args) {
  if (name === 'lmstudio_chat') {
    const messages = [];
    if (args.system) messages.push({ role: 'system', content: args.system });
    messages.push({ role: 'user', content: args.prompt });
    const temp      = typeof args.temperature === 'number' ? args.temperature : DEFAULT_TEMP;
    const maxTokens = typeof args.max_tokens  === 'number' ? Math.min(args.max_tokens, 8192) : 2048;
    return await chat(messages, temp, maxTokens);
  }

  if (name === 'lmstudio_analyze') {
    const systemPrompt = args.context
      ? `You are a quantitative financial analyst. ${args.context}`
      : 'You are a quantitative financial analyst specialising in crypto and cross-asset markets. Be precise, structured, and concise. Use bullet points where appropriate.';
    const userPrompt = `## Analysis Task\n${args.task}\n\n## Data\n\`\`\`\n${args.data}\n\`\`\``;
    const messages = [
      { role: 'system', content: systemPrompt },
      { role: 'user',   content: userPrompt },
    ];
    const temp = typeof args.temperature === 'number' ? args.temperature : 0.3;
    return await chat(messages, temp, 3000);
  }

  if (name === 'lmstudio_macro_brief') {
    const style = args.style || 'concise';
    const data  = typeof args.macro_data === 'object'
      ? JSON.stringify(args.macro_data, null, 2)
      : String(args.macro_data);

    const lengthGuide = style === 'concise'
      ? 'Write 3 concise paragraphs: (1) regime & sentiment, (2) capital flows & sector rotation, (3) key risks and opportunities.'
      : 'Write a detailed macro brief with sections: Macro Regime, Sentiment & Positioning, Capital Flows, Sector Rotation, Key Risks, Outlook.';

    const messages = [
      {
        role    : 'system',
        content : (
          'You are CometCloud\'s macro analyst. Write institutional-quality macro briefs for crypto and cross-asset markets. ' +
          'Use precise financial language. Never use buy/sell — use OUTPERFORM/NEUTRAL/UNDERPERFORM. ' +
          'Format in clean markdown.'
        ),
      },
      {
        role    : 'user',
        content : `Generate a CometCloud Macro Brief from the following data.\n\n${lengthGuide}\n\n## Market Data\n\`\`\`json\n${data}\n\`\`\``,
      },
    ];
    return await chat(messages, 0.6, 2500);
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
