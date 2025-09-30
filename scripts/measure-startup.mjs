#!/usr/bin/env node
// Simple startup latency benchmarker for camo-fleet workers.
// Measures client-observed POST /sessions latency for several scenarios.

import { setTimeout as sleep } from 'node:timers/promises';

const HEADLESS_URL = process.env.HEADLESS_URL || 'http://localhost:8080';
const VNC_URL = process.env.VNC_URL || 'http://localhost:8081';
const RUNS = Number(process.env.RUNS || 5);
const START_URL = process.env.START_URL || 'https://example.org';
const TIMEOUT_MS = Number(process.env.TIMEOUT_MS || 30000);

async function waitHealthy(baseUrl, timeoutMs = 60000) {
  const deadline = Date.now() + timeoutMs;
  let lastErr = null;
  while (Date.now() < deadline) {
    try {
      const res = await fetch(`${baseUrl}/health`, { method: 'GET' });
      if (res.ok) {
        return true;
      }
      lastErr = new Error(`HTTP ${res.status}`);
    } catch (err) {
      lastErr = err;
    }
    await sleep(1000);
  }
  throw new Error(`Service ${baseUrl} not healthy: ${lastErr}`);
}

async function postJson(url, json, timeoutMs) {
  const ctrl = new AbortController();
  const t = setTimeout(() => ctrl.abort(), timeoutMs);
  try {
    const t0 = performance.now();
    const res = await fetch(url, {
      method: 'POST',
      headers: { 'content-type': 'application/json' },
      body: JSON.stringify(json),
      signal: ctrl.signal,
    });
    const t1 = performance.now();
    const body = await res.json().catch(() => ({}));
    return { ms: t1 - t0, status: res.status, body };
  } finally {
    clearTimeout(t);
  }
}

function summary(numbers) {
  if (!numbers.length) return null;
  const sorted = [...numbers].sort((a, b) => a - b);
  const sum = numbers.reduce((a, b) => a + b, 0);
  const mean = sum / numbers.length;
  const median = sorted[Math.floor(sorted.length / 2)];
  const p95 = sorted[Math.floor(sorted.length * 0.95) - 1] ?? sorted[sorted.length - 1];
  const min = sorted[0];
  const max = sorted[sorted.length - 1];
  return { count: numbers.length, min, median, mean, p95, max };
}

async function runScenario(name, baseUrl, payload, runs) {
  const latencies = [];
  const failures = [];
  for (let i = 0; i < runs; i++) {
    const { ms, status, body } = await postJson(`${baseUrl}/sessions`, payload, TIMEOUT_MS);
    if (status >= 400) {
      failures.push({ status, body });
    } else {
      latencies.push(ms);
      // Best effort cleanup to avoid leaking too many sessions
      if (body && body.id) {
        // fire-and-forget delete
        fetch(`${baseUrl}/sessions/${body.id}`, { method: 'DELETE' }).catch(() => void 0);
      }
    }
    // small delay between runs
    await sleep(500);
  }
  return { name, baseUrl, payload, stats: summary(latencies), failures };
}

async function main() {
  console.log('Waiting for workers to be healthy…');
  await Promise.all([waitHealthy(HEADLESS_URL), waitHealthy(VNC_URL)]);

  const scenarios = [
    { name: 'headless: bare', url: HEADLESS_URL, payload: { headless: true, vnc: false } },
    { name: 'headless: start_url', url: HEADLESS_URL, payload: { headless: true, vnc: false, start_url: START_URL } },
    { name: 'vnc: bare', url: VNC_URL, payload: { vnc: true } },
    { name: 'vnc: start_url', url: VNC_URL, payload: { vnc: true, start_url: START_URL } },
  ];

  const results = [];
  for (const sc of scenarios) {
    console.log(`Running: ${sc.name} × ${RUNS}`);
    const out = await runScenario(sc.name, sc.url, sc.payload, RUNS);
    results.push(out);
  }

  const formatted = results.map((r) => ({
    scenario: r.name,
    url: r.baseUrl,
    payload: r.payload,
    stats_ms: r.stats,
    failures: r.failures,
  }));

  console.log('\nResults (ms):');
  for (const r of formatted) {
    console.log(`- ${r.scenario}:`, r.stats_ms);
    if (r.failures.length) {
      console.log(`  failures: ${r.failures.length}`);
    }
  }

  console.log('\nJSON:');
  console.log(JSON.stringify({
    headless_url: HEADLESS_URL,
    vnc_url: VNC_URL,
    runs: RUNS,
    start_url: START_URL,
    results: formatted,
  }, null, 2));
}

main().catch((err) => {
  console.error('Benchmark failed:', err);
  process.exit(1);
});

