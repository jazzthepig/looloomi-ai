#!/usr/bin/env node
/**
 * LM Studio bridge — MCP server (stdio, zero npm dependencies).
 *
 * v2 (2026-10-14). The v1 bridge looked like it worked and did not:
 *   - it picked `/v1/models[0]` — with two models loaded, which one answered was an accident;
 *   - it "turned thinking off" with `thinking:{type:disabled}` / `enable_thinking:false`, which LM Studio
 *     ignores — three calls that day spent their whole token budget thinking and returned no answer;
 *   - it put the compliance block into every system prompt, so a factual question became a compliance puzzle;
 *   - its tool descriptions named a model that was not loaded (and a different one in each installed copy).
 *
 * v2 rules:
 *   - **Never guess the model.** `model` argument → LMSTUDIO_MODEL → the only loaded LLM. Two loaded and no
 *     choice ⇒ error that lists them. Asking for a model that is not loaded ⇒ error (no silent JIT load).
 *   - **Reasoning is explicit and verified.** Every tool takes `reasoning` (default off; any level the chosen
 *     model advertises — see lmstudio_models). The documented switch is `reasoning` on `/api/v1/chat`. After every call the bridge reads
 *     the reasoning tokens back; `off` that still reasoned is reported (chat) or refused (judge).
 *   - **Structured judgments** (`lmstudio_judge`): fixed question types (probability / choice / score — the
 *     same shapes as Jev's System One: noul / choice / score), JSON schema enforced by LM Studio's
 *     `response_format` where the model honours reasoning=off there, otherwise `/api/v1/chat` with
 *     reasoning=off and the schema in the prompt. Either way the answer is validated here; anything out of
 *     range, missing or extra is an error, never a default.
 *   - **Compliance where text can reach users:** always on for the narrative and macro-brief tools; default on
 *     for chat / analyze, `compliance:false` for internal research; never on the judge (it returns numbers).
 *
 * Install: point the MCP config at this file in the repo (not a copy — copies drift):
 *   .mcp.json (repo) already does; for Claude Desktop / Cowork:  ln -sf <repo>/src/mcp/lmstudio_bridge.js ~/.claude/mcp/lmstudio_bridge.js
 *
 * Config (env):
 *   LMSTUDIO_BASE              default http://127.0.0.1:1234 (IPv4 — "localhost" can resolve to ::1, which LM Studio does not serve)
 *   LMSTUDIO_MODEL             default model key when a call does not name one (e.g. qwen/qwen3.8-27b)
 *   LM_API_TOKEN               bearer token, only if LM Studio's server authentication is on
 *   LM_TEMPERATURE             default temperature for chat (0.7)
 *   LMSTUDIO_TIMEOUT_MS        default 180000; LMSTUDIO_JUDGE_TIMEOUT_MS default 90000
 *
 * Tests: tests/test_lmstudio_bridge.py (runs this file against a mock LM Studio).
 */

'use strict';

const http = require('http');
const https = require('https');
const crypto = require('crypto');
const readline = require('readline');

const VERSION = '2.0.0';

// ── Config ─────────────────────────────────────────────────────────────────────

function posInt(v, dflt) {
  const n = parseInt(v, 10);
  return Number.isFinite(n) && n > 0 ? n : dflt;
}
function finiteOr(v, dflt) {
  return Number.isFinite(v) ? v : dflt;
}

const BASE = (process.env.LMSTUDIO_BASE || 'http://127.0.0.1:1234').replace(/\/+$/, '');
const DEFAULT_MODEL = (process.env.LMSTUDIO_MODEL || '').trim();
const API_TOKEN = (process.env.LM_API_TOKEN || '').trim();
const DEFAULT_TEMP = finiteOr(parseFloat(process.env.LM_TEMPERATURE), 0.7);
const TIMEOUT_MS = posInt(process.env.LMSTUDIO_TIMEOUT_MS, 180000);
const JUDGE_TIMEOUT_MS = posInt(process.env.LMSTUDIO_JUDGE_TIMEOUT_MS, 90000);
const MODELS_TTL_MS = 30000;
// Superset of what LM Studio models advertise (capabilities.reasoning.allowed_options); each call is checked
// against the chosen model's own list — 10-14: qwen3.8-27b offers off/low/medium/xhigh/on, no "high".
const REASONING_LEVELS = ['off', 'minimal', 'low', 'medium', 'high', 'xhigh', 'on'];

// ── HTTP ───────────────────────────────────────────────────────────────────────

class HttpError extends Error {
  constructor(status, text, path) {
    super(`LM Studio ${path} → HTTP ${status}: ${String(text).slice(0, 300)}`);
    this.status = status;
  }
}

function request(method, path, body, timeoutMs = TIMEOUT_MS) {
  return new Promise((resolve, reject) => {
    const url = new URL(BASE + path);
    const lib = url.protocol === 'https:' ? https : http;
    const payload = body === undefined ? null : Buffer.from(JSON.stringify(body));
    const headers = { Accept: 'application/json' };
    if (payload) {
      headers['Content-Type'] = 'application/json';
      headers['Content-Length'] = payload.length;
    }
    if (API_TOKEN) headers.Authorization = `Bearer ${API_TOKEN}`;
    const req = lib.request(
      {
        hostname: url.hostname,
        port: url.port || (url.protocol === 'https:' ? 443 : 80),
        path: url.pathname + url.search,
        method,
        headers,
      },
      (res) => {
        const chunks = [];
        res.on('data', (c) => chunks.push(c));
        res.on('end', () => {
          const text = Buffer.concat(chunks).toString('utf8');
          if (res.statusCode < 200 || res.statusCode >= 300) {
            reject(new HttpError(res.statusCode, text, path));
            return;
          }
          try {
            resolve(JSON.parse(text));
          } catch (e) {
            reject(new Error(`LM Studio ${path} returned non-JSON: ${text.slice(0, 200)}`));
          }
        });
      },
    );
    req.setTimeout(timeoutMs, () => {
      req.destroy(new Error(`LM Studio ${path} timed out after ${Math.round(timeoutMs / 1000)}s`));
    });
    req.on('error', (e) => reject(e.code === 'ECONNREFUSED'
      ? new Error(`Cannot reach LM Studio at ${BASE} (connection refused) — is the server running?`)
      : e));
    if (payload) req.write(payload);
    req.end();
  });
}

// ── Models: list what is loaded, never guess ──────────────────────────────────

let _models = null; // { at, list, source }

async function loadedModels(force = false) {
  if (!force && _models && Date.now() - _models.at < MODELS_TTL_MS) return _models;
  let list;
  let source;
  try {
    const data = await request('GET', '/api/v1/models', undefined, 15000);
    list = (data.models || [])
      .filter((m) => m.type === 'llm' && Array.isArray(m.loaded_instances) && m.loaded_instances.length > 0)
      .map((m) => ({
        key: m.key,
        ids: [m.key, ...m.loaded_instances.map((i) => i.id)].filter(Boolean),
        context_length: m.loaded_instances[0]?.config?.context_length ?? null,
        max_context_length: m.max_context_length ?? null,
        reasoning: m.capabilities?.reasoning || null,
        params: m.params_string || null,
        quantization: m.quantization?.name || null,
        format: m.format || null,
        display_name: m.display_name || m.key,
      }));
    source = 'api/v1/models';
  } catch (e) {
    if (!(e instanceof HttpError)) throw e;
    // Older LM Studio without the REST v1 list: /v1/models cannot tell loaded from downloaded,
    // so nothing is "the only one" — callers must name the model.
    const data = await request('GET', '/v1/models', undefined, 15000);
    list = (data.data || []).map((m) => ({
      key: m.id, ids: [m.id], context_length: null, max_context_length: null, reasoning: null,
      params: null, quantization: null, format: null, display_name: m.id, loaded_unknown: true,
    }));
    source = 'v1/models (loaded state unknown)';
  }
  _models = { at: Date.now(), list, source };
  return _models;
}

function names(list) {
  return list.length ? list.map((m) => m.key).join(', ') : '(none)';
}

async function resolveModel(requested) {
  const want = String(requested || DEFAULT_MODEL || '').trim();
  const { list, source } = await loadedModels();
  if (want) {
    const hit = list.find((m) => m.ids.includes(want));
    if (hit) return hit;
    const fresh = await loadedModels(true);
    const hit2 = fresh.list.find((m) => m.ids.includes(want));
    if (hit2) return hit2;
    throw new Error(`Model "${want}" is not loaded in LM Studio (loaded: ${names(fresh.list)}). ` +
      'Load it in LM Studio or name a loaded one — the bridge does not load models on its own.');
  }
  const certain = list.filter((m) => !m.loaded_unknown);
  if (certain.length === 1) return certain[0];
  if (list.length === 0) throw new Error(`No LLM is loaded in LM Studio at ${BASE}.`);
  throw new Error(`${list.length} models are available (${names(list)}; from ${source}) — pass "model" ` +
    'or set LMSTUDIO_MODEL. The bridge does not guess which one answers.');
}

function checkReasoning(model, level) {
  if (!REASONING_LEVELS.includes(level)) {
    throw new Error(`reasoning must be one of ${REASONING_LEVELS.join(' / ')} (got "${level}")`);
  }
  const allowed = model.reasoning?.allowed_options;
  if (Array.isArray(allowed)) {
    if (!allowed.includes(level)) {
      throw new Error(`${model.key} does not allow reasoning="${level}" (allowed: ${allowed.join(', ')}).`);
    }
  } else if (level !== 'off' && !model.loaded_unknown) {
    throw new Error(`${model.key} exposes no reasoning setting; only reasoning="off" is meaningful for it.`);
  }
}

// ── Two call paths, both measured ─────────────────────────────────────────────

function leaked(r) {
  return Number(r.reasoningTokens) > 0 || (typeof r.reasoningText === 'string' && r.reasoningText.trim() !== '');
}

/** REST v1 `/api/v1/chat` — the documented `reasoning` switch. No JSON schema on this endpoint. */
async function restChat({ model, system, user, temperature, maxTokens, reasoning, timeoutMs }) {
  const body = {
    model: model.key,
    input: user,
    temperature,
    max_output_tokens: maxTokens,
    stream: false,
    store: false,
  };
  if (system) body.system_prompt = system;
  if (model.reasoning) body.reasoning = reasoning; // the endpoint errors if the model has no such setting
  const t0 = Date.now();
  const res = await request('POST', '/api/v1/chat', body, timeoutMs);
  const out = Array.isArray(res.output) ? res.output : [];
  const text = out.filter((o) => o.type === 'message').map((o) => o.content || '').join('');
  const reasoningText = out.filter((o) => o.type === 'reasoning').map((o) => o.content || '').join('');
  const st = res.stats || {};
  return {
    path: 'api/v1/chat',
    text,
    reasoningText,
    reasoningTokens: Number.isFinite(st.reasoning_output_tokens) ? st.reasoning_output_tokens : (reasoningText ? NaN : 0),
    inputTokens: st.input_tokens ?? null,
    outputTokens: st.total_output_tokens ?? null,
    tokensPerSecond: st.tokens_per_second ?? null,
    latencyMs: Date.now() - t0,
  };
}

/** OpenAI-compatible `/v1/chat/completions` — the documented JSON-schema enforcement. */
async function completions({ model, messages, temperature, maxTokens, seed, schema, reasoning, timeoutMs }) {
  const body = { model: model.key, messages, temperature, max_tokens: maxTokens, stream: false };
  if (Number.isInteger(seed)) body.seed = seed;
  if (schema) body.response_format = { type: 'json_schema', json_schema: { name: 'judgment', strict: true, schema } };
  // Not documented for LM Studio's OpenAI endpoint; harmless if ignored — the result is measured below.
  if (model.reasoning) body.reasoning_effort = reasoning === 'off' ? 'none' : reasoning;
  const t0 = Date.now();
  const res = await request('POST', '/v1/chat/completions', body, timeoutMs);
  const msg = res.choices?.[0]?.message || {};
  const u = res.usage || {};
  const reasoningText = msg.reasoning_content || msg.reasoning || '';
  const rt = u.completion_tokens_details?.reasoning_tokens;
  return {
    path: 'v1/chat/completions',
    text: msg.content || '',
    reasoningText,
    reasoningTokens: Number.isFinite(rt) ? rt : (reasoningText ? NaN : 0),
    inputTokens: u.prompt_tokens ?? null,
    outputTokens: u.completion_tokens ?? null,
    tokensPerSecond: null,
    latencyMs: Date.now() - t0,
    finishReason: res.choices?.[0]?.finish_reason || null,
  };
}

function metaLine(model, reasoning, r) {
  const rt = Number.isFinite(r.reasoningTokens) ? r.reasoningTokens : 'unknown';
  return `— model=${model.key} · reasoning=${reasoning} · reasoning_tokens=${rt}` +
    `${leaked(r) && reasoning === 'off' ? ' (⚠ reasoned despite off)' : ''}` +
    ` · tokens in/out=${r.inputTokens ?? '?'}/${r.outputTokens ?? '?'} · ${r.latencyMs} ms · via ${r.path}`;
}

// ── Compliance (user-facing text only) ────────────────────────────────────────

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
  'Always frame views as RELATIVE POSITIONING vs benchmark — never as trade instructions.\n' +
  '违反以上规定的输出一律视为无效。'
);

const DISCLAIMER = '*This brief is for informational purposes only and does not constitute investment advice.*';

// ── Judge: fixed question types, validated answers ────────────────────────────

const QTYPES = { probability: 'probability', noul: 'probability', choice: 'choice', score: 'score' };

function normalizeQuestions(questions) {
  if (!questions || typeof questions !== 'object' || Array.isArray(questions)) {
    throw new Error('questions must be an object keyed by question id');
  }
  const ids = Object.keys(questions);
  if (ids.length === 0 || ids.length > 20) throw new Error('questions: 1–20 questions per call');
  const out = {};
  for (const id of ids) {
    if (!/^[A-Za-z][A-Za-z0-9_]{0,39}$/.test(id)) throw new Error(`question id "${id}": letters, digits, _; start with a letter`);
    const q = questions[id] || {};
    const type = QTYPES[q.type];
    if (!type) throw new Error(`question ${id}: type must be probability (alias noul) / choice / score`);
    if (typeof q.instructions !== 'string' || !q.instructions.trim()) throw new Error(`question ${id}: instructions required`);
    const nq = { type, instructions: q.instructions.trim() };
    if (type === 'choice') {
      const opts = Array.isArray(q.options) ? q.options : (q.criteria && typeof q.criteria === 'object' ? Object.keys(q.criteria) : null);
      if (!opts || opts.length < 2 || opts.some((o) => typeof o !== 'string' || !o)) {
        throw new Error(`question ${id}: choice needs options (≥ 2 non-empty strings)`);
      }
      nq.options = opts;
      if (q.criteria && typeof q.criteria === 'object' && !Array.isArray(q.criteria)) nq.criteria = q.criteria;
    }
    if (type === 'score') {
      const r = Array.isArray(q.range) ? q.range : [0, 10];
      if (r.length !== 2 || !r.every(Number.isFinite) || !(r[0] < r[1])) throw new Error(`question ${id}: range must be [min, max]`);
      nq.range = r;
    }
    out[id] = nq;
  }
  return out;
}

function answerSchema(qs, withReason) {
  const properties = {};
  for (const [id, q] of Object.entries(qs)) {
    if (q.type === 'probability') properties[id] = { type: 'number', minimum: 0, maximum: 1 };
    else if (q.type === 'choice') properties[id] = { type: 'string', enum: q.options };
    else properties[id] = { type: 'number', minimum: q.range[0], maximum: q.range[1] };
  }
  const required = Object.keys(qs);
  if (withReason) {
    properties.reason = { type: 'string', maxLength: 240 };
    required.push('reason');
  }
  return { type: 'object', properties, required, additionalProperties: false };
}

function parseJsonObject(text) {
  let t = String(text || '').trim();
  const fence = t.match(/```(?:json)?\s*([\s\S]*?)```/i);
  if (fence) t = fence[1].trim();
  const a = t.indexOf('{');
  const b = t.lastIndexOf('}');
  if (a < 0 || b <= a) throw new Error(`no JSON object in the answer: ${String(text).slice(0, 160)}`);
  return JSON.parse(t.slice(a, b + 1));
}

function validateAnswers(qs, obj, withReason) {
  const errs = [];
  if (!obj || typeof obj !== 'object' || Array.isArray(obj)) return ['answer is not a JSON object'];
  for (const [id, q] of Object.entries(qs)) {
    const v = obj[id];
    if (v === undefined || v === null) { errs.push(`${id}: missing`); continue; }
    if (q.type === 'probability' && !(typeof v === 'number' && v >= 0 && v <= 1)) errs.push(`${id}: ${JSON.stringify(v)} is not a probability in [0, 1]`);
    if (q.type === 'choice' && !q.options.includes(v)) errs.push(`${id}: ${JSON.stringify(v)} is not one of ${q.options.join(' / ')}`);
    if (q.type === 'score' && !(typeof v === 'number' && v >= q.range[0] && v <= q.range[1])) errs.push(`${id}: ${JSON.stringify(v)} outside [${q.range.join(', ')}]`);
  }
  const allowed = new Set([...Object.keys(qs), ...(withReason ? ['reason'] : [])]);
  for (const k of Object.keys(obj)) if (!allowed.has(k)) errs.push(`unexpected key "${k}"`);
  if (withReason && typeof obj.reason !== 'string') errs.push('reason: missing');
  return errs;
}

function judgePrompts(state, qs, withReason, schemaInPrompt, schema) {
  const lines = Object.entries(qs).map(([id, q]) => {
    if (q.type === 'probability') return `- ${id} (probability 0–1 that this is true): ${q.instructions}`;
    if (q.type === 'choice') {
      const crit = q.criteria ? ' — ' + q.options.map((o) => `${o}: ${q.criteria[o] || ''}`).join('; ') : '';
      return `- ${id} (choose exactly one of: ${q.options.join(' | ')}): ${q.instructions}${crit}`;
    }
    return `- ${id} (score from ${q.range[0]} to ${q.range[1]}): ${q.instructions}`;
  });
  let system = 'You are a decision function. Read the STATE and answer every question. ' +
    'Answer only from the STATE; do not use outside knowledge of dates, prices or events. ' +
    'Return one JSON object whose keys are the question ids' + (withReason ? ', plus "reason" (one short sentence)' : '') +
    '. No text outside the JSON.';
  if (schemaInPrompt) system += `\nJSON schema:\n${JSON.stringify(schema)}`;
  const user = `STATE:\n${state}\n\nQUESTIONS:\n${lines.join('\n')}`;
  return { system, user };
}

const structuredPath = new Map(); // model.key → 'completions' | 'rest' (learned per bridge process)

async function judge(args) {
  const model = await resolveModel(args.model);
  const reasoning = args.reasoning || 'off';
  checkReasoning(model, reasoning);
  if (typeof args.state !== 'string' || !args.state.trim()) throw new Error('state is required (the situation to judge, as text)');
  const qs = normalizeQuestions(args.questions);
  const withReason = args.with_reason === true;
  const schema = answerSchema(qs, withReason);
  const temperature = Number.isFinite(args.temperature) ? args.temperature : 0;
  const seed = Number.isInteger(args.seed) ? args.seed : 7;
  const maxTokens = Math.min(posInt(args.max_tokens, 64 + 48 * Object.keys(qs).length + (withReason ? 96 : 0)), 2048);
  const timeoutMs = JUDGE_TIMEOUT_MS;

  const tried = [];
  let r = null;
  let path = structuredPath.get(model.key) || 'completions';
  if (path === 'completions') {
    const p = judgePrompts(args.state, qs, withReason, false, schema);
    try {
      r = await completions({
        model, messages: [{ role: 'system', content: p.system }, { role: 'user', content: p.user }],
        temperature, maxTokens, seed, schema, reasoning, timeoutMs,
      });
      if (reasoning === 'off' && leaked(r)) {
        tried.push(`v1/chat/completions reasoned despite off (reasoning_tokens=${r.reasoningTokens})`);
        structuredPath.set(model.key, 'rest');
        r = null;
      } else {
        structuredPath.set(model.key, 'completions');
      }
    } catch (e) {
      if (!(e instanceof HttpError) || e.status >= 500) throw e;
      tried.push(`v1/chat/completions rejected the request (${e.message.slice(0, 120)})`);
      structuredPath.set(model.key, 'rest');
      r = null;
    }
    if (!r) path = 'rest';
  }
  let promptForHash;
  if (path === 'rest') {
    const p = judgePrompts(args.state, qs, withReason, true, schema);
    r = await restChat({ model, system: p.system, user: p.user, temperature, maxTokens, reasoning, timeoutMs });
    promptForHash = p;
    if (reasoning === 'off' && leaked(r)) {
      throw new Error(`${model.key} reasoned although reasoning="off" on both paths ` +
        `(${[...tried, `api/v1/chat reasoning_tokens=${r.reasoningTokens}`].join('; ')}). ` +
        'Turn reasoning off for this model in LM Studio or choose another model.');
    }
  } else {
    promptForHash = judgePrompts(args.state, qs, withReason, false, schema);
  }

  let obj;
  try { obj = parseJsonObject(r.text); } catch (e) { throw new Error(`${model.key} via ${r.path}: ${e.message}`); }
  const errs = validateAnswers(qs, obj, withReason);
  if (errs.length) throw new Error(`${model.key} via ${r.path}: answer failed validation — ${errs.join('; ')}`);

  const promptSha = crypto.createHash('sha256')
    .update(JSON.stringify({ model: model.key, quantization: model.quantization, ...promptForHash, schema, temperature, seed, reasoning }))
    .digest('hex');
  return JSON.stringify({
    answers: obj,
    meta: {
      model: model.key,
      quantization: model.quantization,
      reasoning,
      reasoning_tokens: Number.isFinite(r.reasoningTokens) ? r.reasoningTokens : null,
      path: r.path,
      fallbacks: tried,
      input_tokens: r.inputTokens,
      output_tokens: r.outputTokens,
      latency_ms: r.latencyMs,
      temperature,
      seed: r.path === 'v1/chat/completions' ? seed : null,
      prompt_sha256: promptSha,
    },
  }, null, 2);
}

// ── Free-text tools ───────────────────────────────────────────────────────────

async function freeText({ modelArg, reasoningArg, system, user, temperature, maxTokens }) {
  const model = await resolveModel(modelArg);
  const reasoning = reasoningArg || 'off';
  checkReasoning(model, reasoning);
  const r = await restChat({ model, system, user, temperature, maxTokens, reasoning, timeoutMs: TIMEOUT_MS });
  if (!r.text.trim()) {
    throw new Error(`${model.key} returned no answer text (${metaLine(model, reasoning, r)}). ` +
      (leaked(r) ? 'It spent the budget reasoning — raise max_tokens or use reasoning="off".' : ''));
  }
  return { model, reasoning, r };
}

function clampTokens(v, dflt, max) {
  return Math.min(posInt(v, dflt), max);
}

async function handleTool(name, args) {
  if (name === 'lmstudio_models') {
    const { list, source } = await loadedModels(true);
    let dflt;
    try { dflt = (await resolveModel(undefined)).key; } catch (e) { dflt = `none — ${e.message}`; }
    return JSON.stringify({
      base: BASE, source, default_model: dflt, env_LMSTUDIO_MODEL: DEFAULT_MODEL || null,
      loaded: list.map((m) => ({
        key: m.key, display_name: m.display_name, params: m.params, quantization: m.quantization, format: m.format,
        context_length: m.context_length, max_context_length: m.max_context_length,
        reasoning_options: m.reasoning?.allowed_options || null, reasoning_default: m.reasoning?.default || null,
      })),
    }, null, 2);
  }

  if (name === 'lmstudio_judge') return judge(args);

  if (name === 'lmstudio_chat') {
    if (typeof args.prompt !== 'string' || !args.prompt.trim()) throw new Error('prompt is required');
    const base = 'You are a CometCloud research analyst. Be precise and structured.';
    const parts = [args.system || base];
    if (args.compliance !== false) parts.push(COMPLIANCE);
    const { model, reasoning, r } = await freeText({
      modelArg: args.model, reasoningArg: args.reasoning, system: parts.join('\n\n'), user: args.prompt,
      temperature: Number.isFinite(args.temperature) ? args.temperature : DEFAULT_TEMP,
      maxTokens: clampTokens(args.max_tokens, 2048, 8192),
    });
    return `${r.text.trim()}\n\n${metaLine(model, reasoning, r)}`;
  }

  if (name === 'lmstudio_analyze') {
    if (typeof args.data !== 'string' || typeof args.task !== 'string') throw new Error('data and task are required strings');
    const base = 'You are a quantitative financial analyst specialising in crypto and cross-asset markets. Be precise, structured, and concise.';
    const parts = [args.context ? `${base} ${args.context}` : base];
    if (args.compliance !== false) parts.push(COMPLIANCE);
    const { model, reasoning, r } = await freeText({
      modelArg: args.model, reasoningArg: args.reasoning, system: parts.join('\n\n'),
      user: `## Analysis Task\n${args.task}\n\n## Data\n\`\`\`\n${args.data}\n\`\`\``,
      temperature: Number.isFinite(args.temperature) ? args.temperature : 0.3,
      maxTokens: clampTokens(args.max_tokens, 1200, 4096),
    });
    return `${r.text.trim()}\n\n${metaLine(model, reasoning, r)}`;
  }

  if (name === 'lmstudio_cis_narrative') {
    if (typeof args.scorecard !== 'string' || !args.scorecard.trim()) throw new Error('scorecard is required');
    const focusLine = args.focus ? `Focus your commentary on: ${args.focus}.` : 'Cover: regime context, key pillar divergences, and principal risk.';
    const { r } = await freeText({
      modelArg: args.model, reasoningArg: args.reasoning,
      system: 'You are CometCloud\'s senior research analyst. Write crisp, institutional-quality commentary. ' +
        'Be precise and concise — 2 paragraphs maximum. No headers, no bullet points.\n\n' + COMPLIANCE,
      user: `Write 2 paragraphs of analyst commentary for the following CIS scorecard.\n${focusLine}\n\n## Scorecard\n${args.scorecard}`,
      temperature: 0.5, maxTokens: 600,
    });
    return r.text.trim();
  }

  if (name === 'lmstudio_macro_brief') {
    if (args.macro_data === undefined) throw new Error('macro_data is required');
    const style = args.style === 'detailed' ? 'detailed' : 'concise';
    const today = new Date().toISOString().split('T')[0]; // UTC date grounds the model
    const data = typeof args.macro_data === 'object' ? JSON.stringify(args.macro_data, null, 2) : String(args.macro_data);
    const lengthGuide = style === 'concise'
      ? 'Write 3 concise paragraphs: (1) regime & sentiment, (2) capital flows & sector rotation, (3) key risks and opportunities.'
      : 'Write a detailed macro brief with sections: Macro Regime, Sentiment & Positioning, Capital Flows, Sector Rotation, Key Risks, Outlook.';
    const { r } = await freeText({
      modelArg: args.model, reasoningArg: args.reasoning,
      system: 'You are CometCloud\'s macro analyst. Write institutional-quality macro briefs for crypto and cross-asset markets. ' +
        'Use precise financial language. Format in clean markdown. Use only the data provided; say so when a field is missing.\n\n' +
        COMPLIANCE + `\nEnd every brief with: "${DISCLAIMER}"`,
      user: `Today's date (UTC): ${today}\n\nGenerate a CometCloud Macro Brief from the following data.\n\n${lengthGuide}\n\n## Market Data\n\`\`\`json\n${data}\n\`\`\``,
      temperature: 0.6, maxTokens: style === 'detailed' ? 3500 : 1800,
    });
    const text = r.text.trim();
    return text.includes(DISCLAIMER) ? text : `${text}\n\n${DISCLAIMER}`;
  }

  throw new Error(`Unknown tool: ${name}`);
}

// ── Tool definitions (no model names here — the model is whatever you choose) ─

const MODEL_ARG = { type: 'string', description: 'LM Studio model key (see lmstudio_models). Default: LMSTUDIO_MODEL, else the only loaded LLM.' };
const REASONING_ARG = { type: 'string', enum: REASONING_LEVELS, description: 'Reasoning setting (default "off"); must be one the model advertises (lmstudio_models). The result reports the reasoning tokens actually spent.' };

const TOOLS = [
  {
    name: 'lmstudio_models',
    description: 'List the LLMs loaded in the local LM Studio server (key, size, quantization, context length, reasoning options) and which one is the default. Call this first when unsure which model to name.',
    inputSchema: { type: 'object', properties: {} },
  },
  {
    name: 'lmstudio_judge',
    description: 'Ask a local model to answer fixed, typed questions about a situation and return validated JSON. ' +
      'Question types: probability (alias noul) → number in [0,1]; choice → one of options; score → number in range. ' +
      'Reasoning is off by default and verified (an answer produced with reasoning when "off" was asked is an error). ' +
      'Out-of-range, missing or extra keys are errors, never defaults. Returns {answers, meta} with model, path, reasoning_tokens, prompt_sha256 (use it as a cache key).',
    inputSchema: {
      type: 'object',
      properties: {
        state: { type: 'string', description: 'The situation to judge, as text. For historical replays give returns / z-scores / states only — no names, dates or price levels.' },
        questions: {
          type: 'object',
          description: 'Keyed by id (letters/digits/_). Each: {type: "probability"|"choice"|"score", instructions, options? (choice), criteria? (choice: {option: meaning}), range? (score, default [0,10])}.',
        },
        model: MODEL_ARG,
        reasoning: REASONING_ARG,
        with_reason: { type: 'boolean', description: 'Also return a one-sentence "reason" (default false).' },
        temperature: { type: 'number', description: 'Default 0.' },
        seed: { type: 'integer', description: 'Default 7 (honoured on the JSON-schema path).' },
        max_tokens: { type: 'integer', description: 'Default scales with the number of questions; max 2048.' },
      },
      required: ['state', 'questions'],
    },
  },
  {
    name: 'lmstudio_chat',
    description: 'Free-form prompt to a local model in LM Studio. No API cost. Reasoning off by default; the reply ends with a line reporting model, reasoning tokens and latency. ' +
      'Adds the compliance block to the system prompt unless compliance=false (internal research only — never for text that reaches users).',
    inputSchema: {
      type: 'object',
      properties: {
        prompt: { type: 'string' },
        system: { type: 'string', description: 'Optional system prompt.' },
        model: MODEL_ARG,
        reasoning: REASONING_ARG,
        compliance: { type: 'boolean', description: 'Default true.' },
        temperature: { type: 'number', description: 'Default LM_TEMPERATURE (0.7).' },
        max_tokens: { type: 'integer', description: 'Default 2048, max 8192.' },
      },
      required: ['prompt'],
    },
  },
  {
    name: 'lmstudio_analyze',
    description: 'Ask a local model to analyze a payload (JSON / CSV / text) for a specific task. Reasoning off by default; compliance block on unless compliance=false. ' +
      'For single-asset CIS reports use cometcloud_get_cis_report instead.',
    inputSchema: {
      type: 'object',
      properties: {
        data: { type: 'string' },
        task: { type: 'string' },
        context: { type: 'string', description: 'Optional background context.' },
        model: MODEL_ARG,
        reasoning: REASONING_ARG,
        compliance: { type: 'boolean', description: 'Default true.' },
        temperature: { type: 'number', description: 'Default 0.3.' },
        max_tokens: { type: 'integer', description: 'Default 1200, max 4096.' },
      },
      required: ['data', 'task'],
    },
  },
  {
    name: 'lmstudio_cis_narrative',
    description: 'Two paragraphs of analyst commentary on a CIS scorecard (markdown from cometcloud_get_cis_report). Compliance block always on.',
    inputSchema: {
      type: 'object',
      properties: {
        scorecard: { type: 'string' },
        focus: { type: 'string', description: 'Optional focus, e.g. "near-term risks".' },
        model: MODEL_ARG,
        reasoning: REASONING_ARG,
      },
      required: ['scorecard'],
    },
  },
  {
    name: 'lmstudio_macro_brief',
    description: 'A CometCloud macro brief from a macro snapshot (fear & greed, BTC dominance, market cap, regime, flows). Compliance block always on; ends with the informational-purposes disclaimer.',
    inputSchema: {
      type: 'object',
      properties: {
        macro_data: { type: 'object', description: 'Macro snapshot.' },
        style: { type: 'string', enum: ['concise', 'detailed'], description: 'Default concise.' },
        model: MODEL_ARG,
        reasoning: REASONING_ARG,
      },
      required: ['macro_data'],
    },
  },
];

// ── MCP stdio protocol ────────────────────────────────────────────────────────

const SUPPORTED_PROTOCOLS = ['2025-06-18', '2025-03-26', '2024-11-05'];

function send(obj) {
  process.stdout.write(JSON.stringify(obj) + '\n');
}

async function onMessage(msg) {
  const { id, method, params } = msg;
  if (typeof method === 'string' && method.startsWith('notifications/')) return;
  try {
    if (method === 'initialize') {
      const asked = params?.protocolVersion;
      send({
        jsonrpc: '2.0', id,
        result: {
          protocolVersion: SUPPORTED_PROTOCOLS.includes(asked) ? asked : '2024-11-05',
          capabilities: { tools: {} },
          serverInfo: { name: 'lmstudio_mcp', version: VERSION },
        },
      });
    } else if (method === 'tools/list') {
      send({ jsonrpc: '2.0', id, result: { tools: TOOLS } });
    } else if (method === 'tools/call') {
      const { name, arguments: args } = params || {};
      try {
        const text = await handleTool(name, args || {});
        send({ jsonrpc: '2.0', id, result: { content: [{ type: 'text', text }] } });
      } catch (e) {
        // Tool failures are results with isError (MCP convention), so the caller sees the reason.
        send({ jsonrpc: '2.0', id, result: { content: [{ type: 'text', text: `Error: ${e.message}` }], isError: true } });
      }
    } else if (method === 'ping') {
      send({ jsonrpc: '2.0', id, result: {} });
    } else if (id !== undefined) {
      send({ jsonrpc: '2.0', id, error: { code: -32601, message: `Method not found: ${method}` } });
    }
  } catch (e) {
    if (id !== undefined) send({ jsonrpc: '2.0', id, error: { code: -32603, message: e.message } });
  }
}

if (require.main === module) {
  const pending = new Set();
  const rl = readline.createInterface({ input: process.stdin, terminal: false });
  rl.on('line', (line) => {
    const raw = line.trim();
    if (!raw) return;
    let msg;
    try { msg = JSON.parse(raw); } catch { return; }
    const p = onMessage(msg).finally(() => pending.delete(p));
    pending.add(p);
  });
  // v1 exited on stdin close even with calls in flight — the answer to the last request was lost.
  rl.on('close', () => { Promise.allSettled([...pending]).then(() => process.exit(0)); });
}

module.exports = { normalizeQuestions, answerSchema, validateAnswers, parseJsonObject, REASONING_LEVELS, VERSION };
