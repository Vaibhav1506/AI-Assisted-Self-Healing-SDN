'use strict';

const $ = (id) => document.getElementById(id);
const SCENARIOS = {
  normal: ['Normal operation', 'Observe healthy traffic without injecting a fault.'],
  link_down: ['Link failure', 'Disconnect the last link of the primary branch.'],
  loss: ['Packet loss', 'Inject 20% loss on the primary branch.'],
  congestion: ['Congestion', 'Offer background traffic at 120% of the selected link capacity.'],
  delay: ['Increased delay', 'Apply 60 ms of delay on the impaired primary link.'],
  both_down: ['Both paths down', 'Disconnect both branches. No healthy alternative exists.'],
};
const METHODS = {
  rf_without_loss_guard: ['Random Forest + loss guard', 'Classifier with a 15% measured-loss safeguard.', 'RF + loss guard'],
  rf_without_loss: ['Random Forest only', 'The fitted classifier, without the explicit loss safeguard.', 'Random Forest only'],
  threshold: ['Fixed thresholds', 'Rules for loss, latency, utilization and missing RTT.', 'Fixed thresholds'],
};
const state = {runs: [], run: null, time: 0, playing: false, speed: 1, chart: 'loss',
  session: null, runner: {busy: false}, page: 'experiment', pollBusy: false, selectionVersion: 0};
const escapeHtml = (value) => String(value ?? '').replace(/[&<>"']/g, (c) => ({'&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;'}[c]));
const fmt = (value, digits = 2) => value === null || value === undefined || !Number.isFinite(Number(value)) ? '—' : Number(value).toFixed(digits);
const methodName = (id) => METHODS[id]?.[0] ?? id ?? 'Unknown method';
const scenarioName = (id) => SCENARIOS[id]?.[0] ?? id ?? 'Unknown scenario';
const topologyName = (id) => id === 'diamond' ? '4 switches' : '6 switches';
const clock = (n) => Number(n || 0).toFixed(1).padStart(4, '0');

// A dashboard reset hides earlier records without modifying experiment evidence.
// The cutoff is saved in index.html so it applies after refresh and in every browser.
const historyResetAt = Date.parse(document.querySelector('meta[name="dashboard-reset-at"]')?.content ?? '');
function visibleRuns(runs) {
  return Number.isFinite(historyResetAt) ? runs.filter((run) => Date.parse(run.started) > historyResetAt) : runs;
}

async function api(path, data) {
  const options = data === undefined ? {} : {method: 'POST', headers: {'Content-Type': 'application/json',
    'X-Dashboard-Token': state.session?.token ?? ''}, body: JSON.stringify(data)};
  const response = await fetch(path, options);
  const result = await response.json();
  if (!response.ok) throw new Error(result.error || 'Could not complete the request.');
  return result;
}

let toastTimer;
function toast(message, error = false) {
  $('toast').textContent = message;
  $('toast').className = `toast${error ? ' error' : ''}`;
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => $('toast').classList.add('hidden'), error ? 9500 : 4500);
}

function config() {
  return {topology: document.querySelector('input[name="topology"]:checked').value,
    scenario: $('scenario').value, method: $('method').value, load: Number($('load').value), capacity: Number($('capacity').value),
    ...returnPolicy()};
}

function returnPolicy(prefix = '') {
  return {failback: $(`${prefix}failback`).value === 'true',
    failback_delay: Number($(`${prefix}failback-delay`).value),
    failback_confirmations: Number($(`${prefix}failback-confirmations`).value)};
}

function updateFailbackInputs() {
  for (const prefix of ['', 'compare-']) {
    const disabled = state.runner.busy || $(`${prefix}failback`).value !== 'true';
    for (const field of ['failback-delay', 'failback-confirmations']) $(`${prefix}${field}`).disabled = disabled;
  }
}

function sameConfig(run, conf) {
  return run.config.topology === conf.topology && run.config.scenario === conf.scenario &&
    run.config.method === conf.method && Number(run.config.load_mbps) === conf.load &&
    Number(run.config.capacity_mbps ?? 10) === conf.capacity &&
    (run.config.failback ?? false) === conf.failback && (!conf.failback ||
      (Number(run.config.failback_delay ?? 5) === conf.failback_delay &&
       Number(run.config.failback_confirmations ?? 3) === conf.failback_confirmations));
}

function setConfig(conf) {
  const topology = document.querySelector(`input[name="topology"][value="${conf.topology === 'diamond' ? 'diamond' : 'long_diamond'}"]`);
  topology.checked = true;
  $('scenario').value = conf.scenario;
  $('method').value = conf.method;
  $('load').value = conf.load_mbps ?? conf.load ?? 4;
  $('capacity').value = conf.capacity_mbps ?? conf.capacity ?? 10;
  $('failback').value = String(conf.failback ?? false);
  $('failback-delay').value = conf.failback_delay ?? 5;
  $('failback-confirmations').value = conf.failback_confirmations ?? 3;
  updateHelp();
}

function updateHelp() {
  $('scenario-help').textContent = $('scenario').value === 'congestion'
    ? `Offer ${fmt(1.2 * Number($('capacity').value), 1)} Mbps of background traffic to a ${$('capacity').value} Mbps branch.`
    : SCENARIOS[$('scenario').value]?.[1] ?? '';
  $('method-help').textContent = METHODS[$('method').value]?.[1] ?? '';
  updateFailbackInputs();
}

async function configurationChanged() {
  updateHelp();
  const version = ++state.selectionVersion;
  const matching = state.runs.find((r) => sameConfig(r, config()) && r.purpose !== 'smoke');
  pause(); state.run = null; state.time = 0;
  renderExperiment();
  if (matching) {
    await selectRun(matching.id, {version});
  }
}

async function selectRun(id, options = {}) {
  const version = options.version ?? ++state.selectionVersion;
  try {
    const run = await api(`/api/runs/${encodeURIComponent(id)}`);
    if (version !== state.selectionVersion) return;
    pause(); state.run = run;
    setConfig(run.config);
    state.time = runDuration(run);
    renderExperiment();
    if (options.navigate) showPage('experiment');
  } catch (error) { if (version === state.selectionVersion) toast(error.message, true); }
}

function runDuration(run = state.run) {
  if (!run) return 36;
  const latest = Math.max(0, ...run.events.map((e) => Number(e.elapsed_s) || 0), ...run.samples.map((s) => Number(s.elapsed_s) || 0));
  if (isLive(run) || run.status !== 'complete') return latest;
  return Math.max(Number(run.config.duration || 36), latest);
}

function isLive(run = state.run) {
  return !!run && state.runner.busy && state.runner.run_id === run.id;
}

function frame() {
  const run = state.run;
  const conf = run?.config ?? {...config(), duration: 36, load_mbps: config().load, capacity_mbps: config().capacity};
  const events = (run?.events ?? []).filter((e) => e.elapsed_s <= state.time + .001);
  const samples = (run?.samples ?? []).filter((s) => s.elapsed_s <= state.time + .001);
  let active = 'primary', fault = false;
  for (const event of events) {
    if (event.event === 'route_change') active = event.destination;
    if (event.event === 'fault_on') fault = true;
    if (event.event === 'fault_off') fault = false;
  }
  const primary = samples.filter((s) => s.path === 'primary').at(-1);
  const backup = samples.filter((s) => s.path === 'backup').at(-1);
  const faultOn = events.find((e) => e.event === 'fault_on');
  const faultOff = events.find((e) => e.event === 'fault_off');
  const switched = events.find((e) => e.event === 'route_change' && e.reason !== 'primary_restored' && faultOn &&
    e.elapsed_s >= faultOn.elapsed_s && e.elapsed_s < (faultOff?.elapsed_s ?? Infinity));
  const failback = events.find((e) => e.event === 'route_change' && e.reason === 'primary_restored');
  const failbackAfterClear = events.find((e) => e.event === 'route_change' && e.reason === 'primary_restored' &&
    faultOff && e.elapsed_s >= faultOff.elapsed_s);
  const recoveryAt = run?.summary?.recovery_observed ? Number(run.summary.fault_on_s) + Number(run.summary.verified_recovery_s) : null;
  return {run, conf, events, samples, active, fault, primary, backup, faultOn, faultOff, switched, failback, failbackAfterClear,
    recovered: recoveryAt !== null && recoveryAt <= state.time + .001, recoveryAt,
    finished: !!run && !isLive() && state.time >= runDuration() - .01};
}

function renderExperiment() {
  const f = frame();
  const live = isLive();
  const run = state.run;
  $('network-title').textContent = f.conf.topology === 'diamond' ? 'Four-switch topology' : 'Six-switch topology';
  $('source-badge').className = `status-pill${live ? ' live' : run ? ' recorded' : ''}`;
  $('source-badge').textContent = live ? 'Live' : run ? 'Recorded run' : 'Not started';
  $('active-route-label').textContent = `${f.active === 'primary' ? 'Primary' : 'Backup'} route${!run ? ' · initial' : ' active'}`;
  const reasons = {healthy: 'Active path assessed healthy', no_healthy_alternative: 'No healthy alternative',
    link_down: 'Link failure detected', degradation: 'Degradation detected', awaiting_confirmation: 'Confirming degradation',
    awaiting_primary_stability: 'Confirming stable primary recovery', primary_restored: 'Primary restored',
    hold_down: 'Switch hold-down active'};
  const decision = f.primary?.decision;
  $('controller-label').textContent = decision ? reasons[decision] ?? decision.replaceAll('_', ' ') : 'Awaiting measurements';
  $('network-status').textContent = f.fault ? f.conf.scenario === 'both_down' ? 'Both branches disconnected' : `${scenarioName(f.conf.scenario)} active` :
    run ? f.finished ? 'Experiment complete' : 'No fault active' : 'Topology preview';
  $('elapsed').textContent = clock(state.time);
  $('duration').textContent = clock(Math.max(run?.config.duration || 36, runDuration()));
  $('replay-range').max = runDuration();
  $('replay-range').value = state.time;
  $('replay-range').disabled = !run || live || !runDuration();
  $('play-button').disabled = !run || live || !runDuration();
  $('play-button').textContent = state.playing ? 'Ⅱ' : '▶';
  $('play-button').setAttribute('aria-label', state.playing ? 'Pause recorded experiment' : 'Replay recorded experiment');
  renderNetworkTelemetry(f);
  renderNetwork(f);
  renderMetrics(f);
  renderChart(f);
  renderTimeline(f);
  renderOutcome(f);
  $('timeline-caption').textContent = live ? 'Live events' : run ? 'Recorded events' : 'No events';
  $('run-status').textContent = !run ? 'No run selected' : live ? 'In progress' : f.finished ? run.status : 'Playback';
  $('selected-run-label').textContent = run ? `${live ? 'Live' : 'Recorded run'} / ${run.id} · ${Number(run.config.duration)}s · ${Number(run.config.load_mbps)} Mbps` : 'No run selected.';
}

function renderNetworkTelemetry(f) {
  const capacity = Number(f.conf.capacity_mbps ?? 10);
  const cell = (label, value) => `<div><dt>${escapeHtml(label)}</dt><dd>${escapeHtml(value)}</dd></div>`;
  const paths = ['primary', 'backup'].map((path) => {
    const sample = f[path];
    const rate = sample?.utilization == null ? null : Number(sample.utilization) * capacity;
    const status = !sample ? 'Awaiting probes' : sample.link_up ? 'Links up' : 'Link down';
    const role = f.active === path ? 'Selected route' : 'Standby route';
    return `<article class="path-readout${f.active === path ? ' selected' : ''}"><h3>${path === 'primary' ? 'Primary' : 'Backup'} <span>${role} · ${status}</span></h3><dl>${
      cell('Path RTT', `${fmt(sample?.rtt_ms)} ms`) +
      cell('Probe loss', `${fmt(sample?.loss_pct, 1)} %`) +
      cell('Utilization', `${fmt(sample?.utilization == null ? null : sample.utilization * 100, 1)} %`) +
      cell('Branch traffic ≈', `${fmt(rate)} Mbps`)
    }</dl><p>${sample ? `Measured at ${clock(sample.elapsed_s)} s` : 'No measured values yet'}</p></article>`;
  }).join('');
  const sample = f.primary ?? f.backup;
  const decision = sample?.decision?.replaceAll('_', ' ') ?? 'Awaiting measurements';
  $('network-telemetry').innerHTML = paths + `<div class="application-readout"><strong>Application · h1 → h2</strong><span>Offered UDP: ${escapeHtml(fmt(f.conf.load_mbps ?? f.conf.load, 1))} Mbps</span><span>Probe RTT: ${escapeHtml(fmt(sample?.app_rtt_ms))} ms</span><span>Probe loss: ${escapeHtml(fmt(sample?.app_loss_pct, 1))} %</span><span>Controller: ${escapeHtml(decision)}</span></div><p class="telemetry-note">RTT is measured end to end, not at each switch. Branch traffic is estimated from the last inter-switch link’s byte counters (busier direction), including probes and background traffic. Capacity: ${escapeHtml(capacity)} Mbps. Moving dots illustrate the selected route; they are not individual measured packets. Receiver throughput is available after completion.</p>`;
}

let networkSignature = '';
function renderNetwork(f) {
  const six = f.conf.topology !== 'diamond';
  const moving = isLive(f.run) || state.playing;
  const signature = JSON.stringify([f.run?.id, six, f.active, f.fault, f.conf.scenario, f.conf.fault_path, moving, f.primary?.elapsed_s, f.backup?.elapsed_s]);
  if (signature === networkSignature) return;
  networkSignature = signature;
  const nodes = {h1:[65,145], S1:[215,145], S2:[six ? 360 : 450,82], S3:[685,145],
    S4:[six ? 360 : 450,228], h2:[835,145]};
  if (six) Object.assign(nodes, {S5:[540,82], S6:[540,228]});
  const paths = {primary: six ? ['S1','S2','S5','S3'] : ['S1','S2','S3'],
    backup: six ? ['S1','S4','S6','S3'] : ['S1','S4','S3']};
  const edges = [];
  for (const [a,b] of [['h1','S1'],['S3','h2']]) edges.push({a,b,active:true});
  for (const [path, route] of Object.entries(paths)) {
    for (let i=0;i<route.length-1;i++) edges.push({a:route[i],b:route[i+1],path,
      active: f.active === path, fault: f.fault && i === route.length-2 && (path === (f.conf.fault_path || 'primary') || f.conf.scenario === 'both_down')});
  }
  const activeBranchImpaired = edges.some((edge) => edge.path && edge.active && edge.fault);
  let svg = `<title>${six ? 'Six' : 'Four'} switches connecting sender h1 to receiver h2. ${f.active} route selected. ${f.fault ? 'Injected fault active.' : 'No injected fault active.'}</title>`;
  svg += '<text x="450" y="21" class="route-label">PRIMARY BRANCH</text><text x="450" y="307" class="route-label">BACKUP BRANCH</text>';
  for (const path of ['primary', 'backup']) {
    const sample = f[path];
    svg += `<text x="450" y="${path === 'primary' ? 40 : 327}" class="route-telemetry">RTT ${escapeHtml(fmt(sample?.rtt_ms))} ms · loss ${escapeHtml(fmt(sample?.loss_pct, 1))}% · use ${escapeHtml(fmt(sample?.utilization == null ? null : sample.utilization * 100, 1))}%</text>`;
  }
  for (const edge of edges) {
    const [x1,y1] = nodes[edge.a], [x2,y2] = nodes[edge.b];
    svg += `<path class="net-edge${edge.active ? ' active' : ''}${edge.fault ? ' fault' : ''}" d="M${x1},${y1} L${x2},${y2}"/>`;
    if (edge.fault) {
      const x=(x1+x2)/2,y=(y1+y2)/2;
      svg += `<circle cx="${x}" cy="${y}" r="10" fill="#fff"/><path class="fault-cross" d="M${x-3},${y-3}l6,6m0,-6l-6,6"/><text class="fault-label" x="${x+10}" y="${y + (edge.path === 'primary' ? -18 : 25)}">${f.conf.scenario === 'both_down' || f.conf.scenario === 'link_down' ? 'LINK DOWN' : 'IMPAIRED'}</text>`;
    }
    // Match the impairment shown in the diagram, including loss, delay and congestion.
    const receiverBlocked = edge.b === 'h2' && activeBranchImpaired;
    if (edge.active && f.run && moving && !(f.fault && f.conf.scenario === 'both_down') && !edge.fault && !receiverBlocked) {
      svg += `<circle class="packet" r="3.5"><animateMotion dur="1.5s" repeatCount="indefinite" path="M${x1},${y1} L${x2},${y2}"/></circle>`;
    }
  }
  for (const [name,[x,y]] of Object.entries(nodes)) {
    const host = name.startsWith('h');
    svg += `<rect class="node-box${host || paths[f.active].includes(name) ? ' active' : ''}" x="${x-28}" y="${y-24}" width="56" height="48" rx="3"><title>${host ? name === 'h1' ? 'UDP sender' : 'UDP receiver' : name === 'S1' ? 'Ingress switch: selects the application branch' : name === 'S3' ? 'Egress switch: branches merge toward h2' : 'Branch forwarding switch'}. Per-switch RTT is not measured.</title></rect>`;
    svg += host ? `<path class="node-symbol" d="M${x-12},${y-10}h24v16h-24z M${x-6},${y+12}h12 M${x},${y+6}v6"/>` :
      `<path class="node-symbol" d="M${x-13},${y-5}h25m-5,-5 5,5-5,5 M${x+13},${y+6}h-25m5,-5-5,5 5,5"/>`;
    svg += `<text class="node-name" x="${x}" y="${y+43}">${name}</text>`;
    if (host) svg += `<text class="node-role" x="${x}" y="${y+61}">${name === 'h1' ? 'SENDER / .1' : 'RECEIVER / .2'}</text>`;
  }
  $('network-svg').innerHTML = svg;
}

function metric(id, value, unit) { $(id).innerHTML = `${escapeHtml(value)}<small>${unit}</small>`; }
function renderMetrics(f) {
  const summary = f.run?.summary;
  metric('metric-recovery', f.recovered ? fmt(summary.verified_recovery_s) : '—', 's');
  metric('metric-switch', f.switched ? fmt(f.switched.elapsed_s - f.faultOn.elapsed_s) : '—', 's');
  metric('metric-throughput', f.finished && summary ? fmt(summary.receiver_mbps, 3) : '—', 'Mbps');
  metric('metric-loss', f.finished && summary ? fmt(summary.udp_loss_pct, 3) : '—', '%');
  metric('metric-failback', f.failbackAfterClear ? fmt(f.failbackAfterClear.elapsed_s - f.faultOff.elapsed_s) : '—', 's');
  $('failback-caption').textContent = !f.conf.failback ? 'Automatic return disabled' :
    f.failbackAfterClear ? 'From actual fault clearance' :
    f.failback ? 'Primary selected before fault clearance' :
    f.finished ? f.active === 'primary' ? 'Primary remained selected' : 'Automatic return not observed' :
    f.primary?.decision === 'awaiting_primary_stability' ? 'Checking primary stability' : 'From fault clearance';
  $('recovery-caption').textContent = f.recovered ? 'Two healthy probe windows verified' :
    f.conf.scenario === 'normal' ? 'No fault · recovery not required' :
    f.finished ? 'Recovery not observed during fault' : 'Waiting for recovery evidence';
}

function renderChart(f) {
  const settings = {loss: ['loss_pct','LOSS / %',100], rtt: ['rtt_ms','RTT / ms',40], util: ['utilization','UTILIZATION / %',100]}[state.chart];
  const [key,unit,floor] = settings;
  $('chart-unit').textContent = unit;
  const w=Math.max(280,$('chart').clientWidth || 850);
  const h=Math.max(180,$('chart').clientHeight || 205);
  const left=42,right=18,top=14,bottom=32;
  const duration=Math.max(Number(f.conf.duration || 36),runDuration(),1);
  const val=(s) => s[key] === null || s[key] === undefined ? null : Number(s[key])*(state.chart === 'util' ? 100 : 1);
  const values=f.samples.map(val).filter((v) => v !== null && Number.isFinite(v));
  const max=Math.max(floor,Math.ceil(Math.max(0,...values)/20)*20);
  const x=(t) => left + Math.min(t/duration,1)*(w-left-right);
  const y=(v) => top+(1-Math.min(v/max,1))*(h-top-bottom);
  let svg=`<svg viewBox="0 0 ${w} ${h}" role="img" aria-label="${unit} for primary and backup paths over time">`;
  const faultOn=f.events.find((e) => e.event === 'fault_on');
  const faultOff=f.events.find((e) => e.event === 'fault_off');
  if (faultOn) svg+=`<rect x="${x(faultOn.elapsed_s)}" y="${top}" width="${Math.max(0,x(faultOff?.elapsed_s ?? state.time)-x(faultOn.elapsed_s))}" height="${h-top-bottom}" fill="var(--fault-shade)"/>`;
  for (let i=0;i<=4;i++) {
    const v=max*i/4;
    svg+=`<path class="grid-line" d="M${left},${y(v)}H${w-right}"/><text x="${left-10}" y="${y(v)+3}" text-anchor="end">${Math.round(v)}</text>`;
  }
  const tickStep = duration > 20 ? 6 : 2;
  for (let t=0;t<=duration+.1;t+=tickStep) svg+=`<text x="${x(t)}" y="${h-7}" text-anchor="middle">${t}s</text>`;
  for (const path of ['primary','backup']) {
    let d='',drawing=false;
    for (const sample of f.samples.filter((s) => s.path === path)) {
      const v=val(sample);
      if (v === null || !Number.isFinite(v)) { drawing=false; continue; }
      d+=`${drawing ? 'L' : 'M'}${x(sample.elapsed_s).toFixed(2)},${y(v).toFixed(2)} `;
      drawing=true;
    }
    svg+=`<path class="line ${path}-line" d="${d}"/>`;
    const last=f.samples.filter((s) => s.path === path && val(s) !== null).at(-1);
    if(last) svg+=`<circle cx="${x(last.elapsed_s)}" cy="${y(val(last))}" r="3" fill="${path==='primary' ? 'var(--accent)' : 'var(--standby)'}"><title>${path}: ${fmt(val(last))} at ${fmt(last.elapsed_s)}s</title></circle>`;
  }
  if (f.run && !f.finished) svg+=`<path stroke="#a1aa95" stroke-dasharray="3 3" d="M${x(state.time)},${top}V${h-bottom}"/>`;
  if (!f.samples.length) svg+=`<text x="${w/2}" y="${h/2}" text-anchor="middle">${f.run ? 'Measurements will appear as playback advances' : 'Measured telemetry will appear here'}</text>`;
  svg+='</svg>';
  $('chart').innerHTML=svg;
  $('chart-note').textContent = state.chart === 'rtt' ? 'Missing RTT indicates no probe response; gaps are left in the line. Values are round-trip times.' :
    state.chart === 'util' ? 'Estimated from switch transmit-byte counters; includes background traffic. Background hosts are omitted from the diagram.' :
    'Path probe loss is separate from the whole-run receiver-side application loss.';
}

function renderTimeline(f) {
  const entries=f.events.map((e) => ({...e}));
  if(f.recovered) entries.push({event:'recovery',elapsed_s:f.recoveryAt});
  entries.sort((a,b) => a.elapsed_s-b.elapsed_s);
  const labels={started:['Traffic started','Primary selected'],fault_on:['Fault injected',scenarioName(f.conf.scenario)],
    route_change:['Route changed','Backup selected'],recovery:['Recovery verified','Two healthy windows'],fault_off:['Fault cleared','Injected fault removed'],completed:['Run complete','Traffic measured']};
  const items=entries.filter((e) => labels[e.event]);
  $('timeline').innerHTML=items.length ? items.map((e) => `<div class="timeline-item ${e.event}"><span class="event-dot"></span><time>${fmt(e.elapsed_s)}s</time><strong>${e.reason === 'primary_restored' ? 'Primary restored' : labels[e.event][0]}</strong><small>${escapeHtml(e.event === 'route_change' ? `${e.source} → ${e.destination}` : labels[e.event][1])}</small></div>`).join('') :
    '<p class="empty-copy">No events recorded.</p>';
}

function outcome(run) {
  if (!run) return ['neutral','○','No experiment selected','Run an experiment to collect measurements.'];
  if (run.status === 'failed') return ['warn','!','Experiment did not complete',run.error || 'Inspect the saved metadata for the failure details.'];
  if (run.config.scenario === 'normal') return ['neutral','✓','Healthy operation',`${run.summary?.route_changes ?? 0} route changes recorded. No fault was injected, so recovery was not required.`];
  if (run.summary?.recovery_observed) return ['','✓','Recovery verified',`Traffic was rerouted and two healthy application probe windows were observed while the injected fault persisted.`];
  if (run.config.scenario === 'both_down') return ['neutral','↔','No healthy alternative','Both branches were disconnected during the fault. Any connectivity after fault clearance is distinct from rerouting recovery.'];
  return ['warn','!','Recovery not observed',`${run.summary?.route_changes ?? 0} route changes recorded. The post-switch recovery criterion was not met while the fault persisted.`];
}

function renderOutcome(f) {
  let data;
  if (!f.run) data=outcome(null);
  else if (!f.finished) data=f.recovered ? ['','✓','Recovery verified','Two healthy application probe windows observed after rerouting. Whole-run traffic statistics are available at completion.'] :
    ['neutral','…',isLive() ? 'Experiment in progress' : 'Recorded playback','The timeline and diagram follow the experiment. Final traffic statistics appear at completion.'];
  else data=outcome(f.run);
  const [kind, ,title,description]=data;
  $('outcome-content').className=`outcome-content ${kind}`;
  $('outcome-content').innerHTML=`<div><h3>${escapeHtml(title)}</h3><p>${escapeHtml(description)}</p></div>`;
  const labels={'summary.json':'Summary','samples.csv':'Probe samples','events.jsonl':'Event log','metadata.json':'Configuration'};
  $('evidence-links').innerHTML=f.run ? (f.run.evidence || []).filter((name) => labels[name]).map((name) =>
    `<a href="/api/runs/${encodeURIComponent(f.run.id)}/files/${name}" download>${labels[name]}</a>`).join('') : '<span class="muted">Evidence files are saved with each experiment.</span>';
}

function pause() {state.playing=false;}
let lastPaint=0,lastTick=0;
function animate(now) {
  if(state.playing && state.run) {
    if(lastTick) state.time=Math.min(runDuration(),state.time+(now-lastTick)/1000*state.speed);
    if(state.time>=runDuration()) pause();
    if(now-lastPaint>90 || !state.playing) {renderExperiment();lastPaint=now;}
  }
  lastTick=now;
  requestAnimationFrame(animate);
}

function showPage(page) {
  state.page=page;
  if (page!=='experiment') pause();
  document.querySelectorAll('.page').forEach((element) => element.classList.toggle('hidden', element.id!==`page-${page}`));
  document.querySelectorAll('.nav-tab').forEach((button) => {button.classList.toggle('active',button.dataset.page===page);
    if(button.dataset.page===page) button.setAttribute('aria-current','page');else button.removeAttribute('aria-current');});
  const copy={experiment:['Experiment','Select a topology, fault scenario and detection method.'],
    history:['Run history','Saved measurements and event logs.'],
    compare:['Method comparison','Compare completed runs with the same network settings.']}[page];
  $('page-title').textContent=copy[0];
  $('page-description').textContent=copy[1];
  if(page==='history') renderHistory();
  if(page==='compare') renderComparison();
}

function shortOutcome(run) {
  if(run.status==='failed') return ['warn','Failed'];
  if(run.status!=='complete') return ['neutral','Incomplete'];
  if(run.config.scenario==='normal') return ['neutral','No fault'];
  if(run.summary?.recovery_observed) return ['',`${fmt(run.summary.verified_recovery_s)}s verified`];
  if(run.config.scenario==='both_down') return ['neutral','No alternative'];
  return ['warn','Not observed'];
}

function renderHistory() {
  const runs=state.runs.filter((run) => ($('history-scenario').value==='all' || run.config.scenario===$('history-scenario').value) &&
    ($('history-topology').value==='all' || run.config.topology===$('history-topology').value));
  $('history-count').textContent=state.runs.length;
  $('history-empty').classList.toggle('hidden',!!runs.length);
  $('history-empty').textContent=state.runs.length ? 'No experiments match these filters.' : 'No experiments yet. Start an experiment in the laboratory to record your first run.';
  $('history-body').innerHTML=runs.map((run) => {
    const date = new Date(run.started);
    const stamp=Number.isNaN(date.getTime()) ? run.id : date.toLocaleString(undefined,{month:'short',day:'numeric',hour:'2-digit',minute:'2-digit'});
    const [kind,label]=shortOutcome(run);
    const policy = run.config.failback ? `Auto return · ${fmt(run.config.failback_delay ?? 5, 1)}s / ${Number(run.config.failback_confirmations ?? 3)} healthy observations` : 'Automatic return disabled';
    return `<tr><td>${escapeHtml(stamp)}<small>${escapeHtml(run.id)}${run.purpose==='smoke' ? ' · smoke' : ''}</small></td><td>${escapeHtml(scenarioName(run.config.scenario))}<small>${fmt(run.config.load_mbps,1)} Mbps load / ${fmt(run.config.capacity_mbps ?? 10,1)} Mbps capacity · ${Number(run.config.duration)}s</small><small>${escapeHtml(policy)}</small></td><td>${escapeHtml(METHODS[run.config.method]?.[2] ?? methodName(run.config.method))}</td><td>${topologyName(run.config.topology)}</td><td><span class="result-tag ${kind}">${label}</span></td><td>${fmt(run.summary?.receiver_mbps,3)} Mbps</td><td><button class="row-action" data-view-run="${escapeHtml(run.id)}">Open</button></td></tr>`;
  }).join('');
}

function comparisonRuns() {
  const scenario=$('compare-scenario').value,topology=$('compare-topology').value,load=Number($('compare-load').value),capacity=Number($('compare-capacity').value);
  return Object.keys(METHODS).map((method) => state.runs.find((run) => run.status==='complete' && run.summary &&
    run.purpose==='evaluation' && Number(run.config.duration)===36 &&
    sameConfig(run,{scenario,topology,method,load,capacity,...returnPolicy('compare-')})) ?? null);
}

function renderComparison() {
  const runs=comparisonRuns();
  $('comparison-cards').innerHTML=Object.keys(METHODS).map((method,index) => {
    const run=runs[index];
    const [kind,label]=run ? shortOutcome(run) : ['neutral','No matching run'];
    return `<article class="panel comparison-card"><h3>${escapeHtml(methodName(method))}</h3><strong>${fmt(run?.summary?.verified_recovery_s)}<small>s</small></strong><p>Verified recovery time</p><span class="result-tag ${kind}">${label}</span>${run ? `<button class="row-action" data-view-run="${escapeHtml(run.id)}">Open run</button>` : '<button class="row-action" disabled>No recording</button>'}</article>`;
  }).join('');
  $('comparison-head').innerHTML=`<tr><th>Measurement</th>${Object.values(METHODS).map((m) => `<th>${m[2]}</th>`).join('')}</tr>`;
  const rows=[['Route changes',(r)=>r ? r.summary.route_changes : '—'],
    ['Failure-driven switches',(r)=>r ? r.summary.failover_changes ?? r.summary.route_changes : '—'],
    ['Automatic failbacks',(r)=>r ? r.summary.automatic_failbacks ?? 0 : '—'],
    ['Fault → route change',(r)=>`${fmt(r?.summary?.detection_and_actuation_s)} s`],
    ['Verified recovery',(r)=>`${fmt(r?.summary?.verified_recovery_s)} s`],
    ['Fault clear → primary',(r)=>`${fmt(r?.summary?.fault_clear_to_failback_s)} s`],
    ['Receiver throughput',(r)=>`${fmt(r?.summary?.receiver_mbps,3)} Mbps`],
    ['Application loss',(r)=>`${fmt(r?.summary?.udp_loss_pct,3)} %`],
    ['Probe RTT average',(r)=>`${fmt(r?.summary?.mean_probe_rtt_ms)} ms`],
    ['Run ID',(r)=>r?.id ?? 'No matching run']];
  $('comparison-body').innerHTML=rows.map(([label,value]) => `<tr><td>${label}</td>${runs.map((run)=>`<td>${escapeHtml(value(run))}</td>`).join('')}</tr>`).join('');
}

function renderRunner() {
  const busy=state.runner.busy;
  const live=state.session?.live_enabled;
  $('access-note').classList.toggle('hidden',!!live);
  $('live-note').classList.toggle('hidden',!live);
  $('stop-button').classList.toggle('hidden',!busy);
  $('run-button').disabled=busy;
  $('compare-run').disabled=busy;
  $('config-form').querySelectorAll('input,select').forEach((element)=>element.disabled=busy);
  for (const id of ['compare-scenario','compare-topology','compare-load','compare-capacity','compare-failback']) $(id).disabled=busy;
  updateFailbackInputs();
  const phases={starting:'Building virtual network',running:'Experiment running',stopping:'Stopping and cleaning up'};
  if(busy) $('run-button').textContent=phases[state.runner.phase] ?? 'Experiment running';
  else $('run-button').textContent='Run experiment';
  $('connection-text').textContent=busy ? 'Experiment running' : live ? 'Local runner ready' : 'Saved results';
  document.querySelector('.connection .dot').classList.remove('error');
  $('compare-progress').classList.toggle('hidden',!busy);
  if(busy) $('compare-progress').textContent=`${methodName(state.runner.config?.method)} · ${phases[state.runner.phase] ?? state.runner.phase}${state.runner.queue.length ? ` · ${state.runner.queue.length} queued` : ''}`;
}

async function refreshRuns() {
  state.runs=visibleRuns(await api('/api/runs'));
  renderHistory();renderComparison();
}

async function launch(compare=false) {
  if(!state.session?.live_enabled) { $('live-dialog').showModal();return; }
  const conf=compare ? {scenario:$('compare-scenario').value,topology:$('compare-topology').value,
    method:'rf_without_loss_guard',load:Number($('compare-load').value),capacity:Number($('compare-capacity').value),
    ...returnPolicy('compare-')} : config();
  if(!Number.isFinite(conf.load) || conf.load<=0 || conf.load>100) {toast('Choose a traffic load greater than 0 and at most 100 Mbps.',true);return;}
  if(!Number.isFinite(conf.capacity) || conf.capacity<=0 || conf.capacity>100) {toast('Choose a link capacity greater than 0 and at most 100 Mbps.',true);return;}
  if(!Number.isFinite(conf.failback_delay) || conf.failback_delay<0) {toast('Choose a finite, non-negative stability wait.',true);return;}
  if(!Number.isInteger(conf.failback_confirmations) || conf.failback_confirmations<1) {toast('Choose at least one healthy observation, as a whole number.',true);return;}
  try {
    pause();
    state.runner=await api(compare ? '/api/compare' : '/api/run',conf);
    state.run=null;state.time=0;
    if(!compare) renderExperiment();
    renderRunner();
    toast(compare ? 'Three experiments queued. Each method will run sequentially.' : 'Starting the experiment. Network setup may take a few seconds.');
  } catch(error) {toast(error.message,true);}
}

let pollNumber=0;
async function poll() {
  if(state.pollBusy) return;
  state.pollBusy=true;
  try {
    const previous=state.runner;
    state.runner=await api('/api/state');
    renderRunner();
    if(state.runner.busy && state.runner.run_id) {
      const run=await api(`/api/runs/${state.runner.run_id}`);
      // During a live experiment, always follow the runner rather than a recording.
      pause();state.run=run;setConfig(run.config);state.time=runDuration(run);renderExperiment();
    }
    if(state.runner.busy && state.runner.completed_ids.length !== (previous.completed_ids?.length ?? 0)) await refreshRuns();
    if(previous.busy && !state.runner.busy) {
      await refreshRuns();
      if(state.runner.run_id) await selectRun(state.runner.run_id);
      if(state.runner.error) toast(state.runner.error,true);
      else if(state.runner.phase==='stopped') toast('Experiment stopped. The runner has finished cleanup.');
      else toast('Experiment complete. Results are ready.');
    } else if(++pollNumber%5===0 && !state.runner.busy) await refreshRuns();
  } catch(error) {
    $('connection-text').textContent='Server disconnected';
    document.querySelector('.connection .dot').classList.add('error');
    $('run-button').disabled=true;$('compare-run').disabled=true;
  } finally {state.pollBusy=false;}
}

async function init() {
  for(const [id,[name]] of Object.entries(SCENARIOS)) {
    for(const target of ['history-scenario','compare-scenario']) {
      const option=document.createElement('option');option.value=id;option.textContent=name;$(target).append(option);
    }
  }
  $('compare-scenario').value='loss';
  document.querySelectorAll('[data-page]').forEach((button)=>button.addEventListener('click',()=>showPage(button.dataset.page)));
  $('view-history').addEventListener('click',()=>showPage('history'));
  $('config-form').addEventListener('submit',(event)=>{event.preventDefault();launch();});
  $('config-form').querySelectorAll('input,select').forEach((element)=>element.addEventListener('change',configurationChanged));
  $('play-button').addEventListener('click',()=>{
    if(!state.run || isLive())return;
    if(state.playing)pause();else {if(state.time>=runDuration()-.01)state.time=0;state.playing=true;}
    renderExperiment();
  });
  $('replay-range').addEventListener('input',()=>{pause();state.time=Number($('replay-range').value);renderExperiment();});
  $('speed-button').addEventListener('click',()=>{state.speed=state.speed===1 ? 2 : state.speed===2 ? 4 : 1;$('speed-button').textContent=`${state.speed}×`;});
  document.querySelectorAll('[data-chart]').forEach((button)=>button.addEventListener('click',()=>{
    state.chart=button.dataset.chart;document.querySelectorAll('[data-chart]').forEach((b)=>b.classList.toggle('active',b===button));renderChart(frame());
  }));
  for(const target of ['history-scenario','history-topology']) $(target).addEventListener('change',renderHistory);
  for(const target of ['compare-scenario','compare-topology','compare-load','compare-capacity','compare-failback','compare-failback-delay','compare-failback-confirmations']) $(target).addEventListener('change',()=>{updateFailbackInputs();renderComparison();});
  $('refresh-history').addEventListener('click',async()=>{try{await refreshRuns();toast('Run history refreshed.');}catch(error){toast(error.message,true);}});
  document.addEventListener('click',(event)=>{const button=event.target.closest('[data-view-run]');if(button)selectRun(button.dataset.viewRun,{navigate:true});});
  $('compare-run').addEventListener('click',()=>launch(true));
  $('stop-button').addEventListener('click',async()=>{try{state.runner=await api('/api/stop',{});renderRunner();toast('Stop requested. Waiting for network cleanup.');}catch(error){toast(error.message,true);}});
  $('live-help-button').addEventListener('click',()=>$('live-dialog').showModal());
  $('close-dialog').addEventListener('click',()=>$('live-dialog').close());
  $('live-dialog').addEventListener('click',(event)=>{if(event.target===$('live-dialog')){const rect=$('live-dialog').getBoundingClientRect();if(event.clientX<rect.left||event.clientX>rect.right||event.clientY<rect.top||event.clientY>rect.bottom)$('live-dialog').close();}});
  $('copy-command').addEventListener('click',async()=>{try{await navigator.clipboard.writeText('sudo python3 dashboard/server.py');toast('Launch command copied.');}catch{toast('Run: sudo python3 dashboard/server.py');}});
  renderExperiment();renderComparison();
  const chartResize = new ResizeObserver(() => {
    if(state.page==='experiment') renderChart(frame());
  });
  chartResize.observe($('chart'));
  try {
    const [session,runs,runner]=await Promise.all([api('/api/session'),api('/api/runs'),api('/api/state')]);
    Object.assign(state,{session,runs:visibleRuns(runs),runner});renderRunner();renderHistory();renderComparison();
    const initial=state.runs.find((run)=>sameConfig(run,config())&&run.status==='complete'&&run.purpose!=='smoke');
    if(initial)await selectRun(initial.id);
    if(runner.busy)await poll();
  } catch(error) {toast(`Unable to connect to the local runner. ${error.message}`,true);$('connection-text').textContent='Server disconnected';}
  requestAnimationFrame(animate);
  setInterval(poll,1200);
}
init();
