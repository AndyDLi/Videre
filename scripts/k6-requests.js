// One request per constant-arrival-rate iteration; targets must already exist and AI must be cached.

import http from 'k6/http';
import { check } from 'k6';
import exec from 'k6/execution';
import { Counter, Trend } from 'k6/metrics';

function required(name) {
  const value = __ENV[name];
  if (!value || !value.trim()) throw new Error(name + ' is required');
  return value.trim();
}
function integer(name, minimum, maximum, fallback) {
  const raw = __ENV[name] === undefined ? String(fallback) : __ENV[name];
  if (!/^\d+$/.test(raw) || Number(raw) < minimum || Number(raw) > maximum) {
    throw new Error(name + ' must be an integer from ' + minimum + ' to ' + maximum);
  }
  return Number(raw);
}
function optionalLatency(name) {
  if (__ENV[name] === undefined) return null;
  const value = Number(__ENV[name]);
  if (!__ENV[name].trim() || !Number.isFinite(value) || value <= 0) {
    throw new Error(name + ' must be a finite positive number');
  }
  return value;
}

const baseURL = required('API_BASE_URL').replace(/\/$/, '');
if (!/^https?:\/\/[^/?#\s]+(?:\/[^?#\s]*)?$/.test(baseURL)) {
  throw new Error('API_BASE_URL must be an explicit HTTP(S) URL without query or fragment');
}
const config = {
  api_base_url: baseURL,
  environment: required('ENVIRONMENT'),
  offered_rps: integer('RPS', 1, 500),
  duration_seconds: integer('DURATION_SECONDS', 10, 600, 300),
  max_vus: integer('MAX_VUS', 1, 500, 100),
  node_id: required('NODE_ID'),
  ai_entity_type: required('AI_ENTITY_TYPE'),
  ai_entity_id: required('AI_ENTITY_ID'),
  p95_ms: optionalLatency('P95_MS'),
  p99_ms: optionalLatency('P99_MS'),
  workload_revision: __ENV.WORKLOAD_REVISION || 'unknown',
  backend_revision: __ENV.BACKEND_REVISION || 'unknown',
  workload: 'fixed-rps-equal-five-route-cached-ai',
  http_timeout_seconds: 10,
  graceful_stop_seconds: 11,
};
if (!['node', 'gpu', 'job'].includes(config.ai_entity_type) || config.ai_entity_id.length > 128) {
  throw new Error('AI_ENTITY_TYPE must be node, gpu, or job; AI_ENTITY_ID must have at most 128 characters');
}
const summaryPath = required('SUMMARY_PATH');
config.preallocated_vus = Math.min(config.max_vus, Math.max(10, Math.ceil(config.offered_rps * 2)));
const expected = config.offered_rps * config.duration_seconds;
// Arrival executors can include or omit one request at the time-window boundary.
const countBounds = ['count>=' + (expected - 1), 'count<=' + (expected + 1)];
const started = new Counter('started_iterations');
const completed = new Counter('completed_iterations');
const successful = new Counter('successful_requests');
const routeNames = ['capacity', 'nodes', 'jobs', 'node_detail', 'ai_cached'];
const durations = {};
const successes = {};
const thresholds = {
  checks: ['rate==1'],
  http_req_failed: ['rate==0'],
  dropped_iterations: ['count==0'],
  started_iterations: countBounds,
  completed_iterations: countBounds,
  iterations: countBounds,
  http_reqs: countBounds,
  successful_requests: countBounds,
};
for (const route of routeNames) {
  durations[route] = new Trend(route + '_duration_ms', true);
  successes[route] = new Counter(route + '_successful_requests');
  // Always-true thresholds retain route summaries during exploratory runs.
  thresholds[route + '_duration_ms'] = ['p(95)>=0'];
  thresholds[route + '_successful_requests'] = ['count>=0'];
  if (config.p95_ms !== null) thresholds[route + '_duration_ms'].push('p(95)<=' + config.p95_ms);
  if (config.p99_ms !== null) thresholds[route + '_duration_ms'].push('p(99)<=' + config.p99_ms);
}
export const options = {
  scenarios: {
    requests: {
      executor: 'constant-arrival-rate',
      rate: config.offered_rps,
      timeUnit: '1s',
      duration: config.duration_seconds + 's',
      preAllocatedVUs: config.preallocated_vus,
      maxVUs: config.max_vus,
      gracefulStop: config.graceful_stop_seconds + 's',
    },
  },
  thresholds,
  summaryTrendStats: ['med', 'p(95)', 'p(99)', 'max'],
  // A redirect must fail rather than adding another request to an iteration.
  maxRedirects: 0,
};

const nonempty = value => typeof value === 'string' && value.trim().length > 0;
const count = value => Number.isInteger(value) && value >= 0;
const date = value => nonempty(value) && Number.isFinite(Date.parse(value));
const nullableDate = value => value === null || date(value);
const nullableString = value => value === null || typeof value === 'string';
function node(body) {
  return body && nonempty(body.id) && nonempty(body.cluster_id) &&
    ['cpu_cores', 'memory_gb', 'gpu_count'].every(field => count(body[field])) &&
    nonempty(body.health_state) && date(body.updated_at);
}
function gpu(body) {
  return body && nonempty(body.id) && nonempty(body.node_id) && nonempty(body.health_state) &&
    ['utilization_percentage', 'temperature_celsius'].every(field => Number.isFinite(body[field])) &&
    ['memory_used_mb', 'memory_total_mb', 'ecc_correctable_count', 'ecc_uncorrectable_count',
      'xid_error_count'].every(field => count(body[field])) && date(body.last_updated_at);
}
function job(body) {
  return body && nonempty(body.id) && nonempty(body.cluster_id) && nonempty(body.lifecycle_state) &&
    ['requested_cpu_cores', 'requested_memory_gb', 'requested_gpu_count'].every(field => count(body[field])) &&
    Number.isInteger(body.priority) && nullableString(body.pod_name) && nullableString(body.failure_reason) &&
    date(body.created_at) && nullableDate(body.started_at) && nullableDate(body.completed_at);
}
function page(body, limit, validate) {
  return body && Array.isArray(body.items) && count(body.total) && body.limit === limit &&
    body.offset === 0 && body.items.length <= limit && body.total >= body.items.length &&
    body.items.every(validate);
}
function capacity(body) {
  return Array.isArray(body) && body.length > 0 && body.every(item =>
    item && nonempty(item.cluster_id) &&
    ['total_gpus', 'unavailable_gpus', 'degraded_gpus', 'idle_gpus', 'active_gpus',
      'idle_reserved_gpus', 'drained_node_count', 'unschedulable_node_count', 'queued_job_count',
      'queueing_delay_event_count', 'fragmentation_event_count'].every(field => count(item[field])) &&
    // Compatibility aliases represent the same categories and are never added to their totals.
    item.idle_reserved_gpus === item.idle_gpus &&
    item.fragmentation_event_count === item.queueing_delay_event_count &&
    item.total_gpus === item.unavailable_gpus + item.degraded_gpus + item.idle_gpus + item.active_gpus);
}
function validBody(route, body) {
  if (route === 'capacity') return capacity(body);
  if (route === 'nodes') return page(body, 50, node);
  if (route === 'jobs') return page(body, 10, job);
  if (route === 'node_detail') {
    return node(body) && body.id === config.node_id && Array.isArray(body.gpus) &&
      body.gpus.every(item => gpu(item) && item.node_id === body.id) && body.gpus.length === body.gpu_count;
  }
  return body && body.entity_type === config.ai_entity_type && body.entity_id === config.ai_entity_id &&
    body.from_cache === true && count(body.cache_age_seconds) && nonempty(body.summary) &&
    Array.isArray(body.next_steps) && body.next_steps.length > 0 && body.next_steps.every(nonempty);
}

export default function () {
  const route = routeNames[exec.scenario.iterationInTest % routeNames.length];
  started.add(1);
  const params = { timeout: '10s', tags: { route, name: route } };
  let response;
  if (route === 'ai_cached') {
    params.headers = { 'Content-Type': 'application/json' };
    response = http.post(baseURL + '/ai/analyze', JSON.stringify({
      entity_type: config.ai_entity_type, entity_id: config.ai_entity_id,
    }), params);
  } else {
    const path = {
      capacity: '/capacity', nodes: '/nodes?limit=50&offset=0',
      jobs: '/jobs?limit=10&offset=0', node_detail: '/nodes/' + encodeURIComponent(config.node_id),
    }[route];
    response = http.get(baseURL + path, params);
  }
  durations[route].add(response.timings.duration);
  let body = null;
  try { body = response.json(); } catch (_) { /* Invalid JSON is a failed body check. */ }
  const valid = check(response, {
    'status is 200': value => value.status === 200,
    'response matches route contract': () => validBody(route, body),
  }, { route });
  completed.add(1);
  if (!valid) {
    exec.test.abort('Invalid ' + route + ' response (status ' + response.status +
      '); AI must stay cached. Stop and inspect fixture/backend before retrying.');
    return;
  }
  successful.add(1);
  successes[route].add(1);
}

export function handleSummary(data) {
  const metric = (name, value) => data.metrics[name] ? data.metrics[name].values[value] || 0 : 0;
  const counts = {
    expected_iterations: expected,
    started_iterations: metric('started_iterations', 'count'),
    completed_iterations: metric('completed_iterations', 'count'),
    iterations: metric('iterations', 'count'),
    http_requests: metric('http_reqs', 'count'),
    successful_requests: metric('successful_requests', 'count'),
    dropped_iterations: metric('dropped_iterations', 'count'),
  };
  const failedThresholds = [];
  for (const name of Object.keys(data.metrics)) {
    const checks = data.metrics[name].thresholds || {};
    for (const expression of Object.keys(checks)) {
      if (!checks[expression].ok) failedThresholds.push(name + ': ' + expression);
    }
  }
  const passed = failedThresholds.length === 0 && counts.dropped_iterations === 0 &&
    metric('checks', 'rate') === 1 && metric('http_req_failed', 'rate') === 0 &&
    Math.abs(counts.started_iterations - expected) <= 1 &&
    ['completed_iterations', 'iterations', 'http_requests', 'successful_requests']
      .every(name => counts[name] === counts.started_iterations);
  const routes = {};
  for (const route of routeNames) {
    const routeCount = metric(route + '_successful_requests', 'count');
    routes[route] = {
      duration_ms: data.metrics[route + '_duration_ms'] ? data.metrics[route + '_duration_ms'].values : {},
      successful_requests: routeCount,
      successful_rps: routeCount / config.duration_seconds,
    };
  }
  const summary = {
    passed, config, counts, routes,
    successful_rps: counts.successful_requests / config.duration_seconds,
    check_failure_rate: 1 - metric('checks', 'rate'),
    http_failure_rate: metric('http_req_failed', 'rate'),
    failed_thresholds: failedThresholds,
    load_generator_limited: counts.dropped_iterations > 0,
    metrics: data.metrics,
  };
  return {
    [summaryPath]: JSON.stringify(summary, null, 2),
    stdout: (passed ? 'PASSED' : 'FAILED') + ': offered ' + config.offered_rps +
      ' RPS; successful ' + summary.successful_rps + ' RPS; ' + counts.completed_iterations +
      '/' + expected + ' completed; dropped ' + counts.dropped_iterations +
      (summary.load_generator_limited ? ' (load generator could not sustain offered rate)' : '') + '\n',
  };
}
