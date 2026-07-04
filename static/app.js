// ═════════════════════════════════════════════
// LexAide — Frontend Logic (Vanilla JS)
// ═════════════════════════════════════════════

const API = '/api';
const REQUEST_TIMEOUT_MS = 90000;  // OCR(이미지)·LLM 지연 대응 (45s → 90s)

// ─── 탭 전환 ─────────────────────────────────
document.querySelectorAll('.tab').forEach(btn => {
  btn.addEventListener('click', () => {
    const target = btn.dataset.tab;
    document.querySelectorAll('.tab').forEach(b => b.classList.toggle('active', b === btn));
    document.querySelectorAll('.tab-panel').forEach(p => {
      p.classList.toggle('active', p.dataset.panel === target);
    });
  });
});


// ─── 로딩 단계 (실제 Agent 진행과 연동) ──────
const LOADING_STEPS = [
  { id: 'lstep-1', text: 'Agent 1: 언어 감지 중...' },
  { id: 'lstep-2', text: 'Agent 2: 규칙 탐지 중...' },
  { id: 'lstep-3', text: 'Agent 3: 교차검증 중...'  },
  { id: 'lstep-4', text: 'Agent 4: 인용 검증 중...' },
];

// n번 단계를 active, 이전 단계를 done으로 표시
function setLoadingStep(n) {
  LOADING_STEPS.forEach((s, idx) => {
    const el = document.getElementById(s.id);
    if (!el) return;
    el.classList.remove('active', 'done');
    if (idx + 1 < n)  el.classList.add('done');
    if (idx + 1 === n) el.classList.add('active');
  });
  const mainText = document.getElementById('loading-main-text');
  if (mainText && LOADING_STEPS[n - 1]) mainText.textContent = LOADING_STEPS[n - 1].text;
}

function _resetLoadingSteps() {
  LOADING_STEPS.forEach(s => {
    const el = document.getElementById(s.id);
    if (el) { el.classList.remove('active', 'done'); }
  });
}


// ─── 로딩 표시 (타이머 제거 — 실제 API 호출 순서로 제어) ──
function showLoading(text = '심의 진행 중...') {
  _resetLoadingSteps();
  const ov = document.getElementById('loading');
  const mainText = document.getElementById('loading-main-text');
  if (mainText) mainText.textContent = text;
  ov.classList.add('show');
}
function hideLoading() {
  // 모든 단계 done 처리
  LOADING_STEPS.forEach(s => {
    const el = document.getElementById(s.id);
    if (el) { el.classList.remove('active'); el.classList.add('done'); }
  });
  document.getElementById('loading').classList.remove('show');
  setTimeout(_resetLoadingSteps, 300);
}


// ─── API 호출 ────────────────────────────────
async function apiPost(path, body, timeoutMs = REQUEST_TIMEOUT_MS) {
  const ctrl = new AbortController();
  const timer = setTimeout(() => ctrl.abort(), timeoutMs);
  try {
    const res = await fetch(API + path, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body),
      signal: ctrl.signal,
    });
    if (!res.ok) throw new Error(`API error: ${res.status}`);
    return await res.json();
  } catch (e) {
    if (e.name === 'AbortError') {
      throw new Error('LLM 응답이 지연되어 요청을 중단했습니다. 잠시 후 다시 실행하거나 LLM 비활성 모드로 테스트하세요.');
    }
    throw e;
  } finally {
    clearTimeout(timer);
  }
}


// ─── HTML 이스케이프 ─────────────────────────
function esc(s) {
  if (s == null) return '';
  return String(s)
    .replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;').replace(/'/g, '&#039;');
}

function clampText(text, n = 1600) {
  text = (text || '').trim();
  if (text.length <= n) return text;
  return text.slice(0, n) + '\n...';
}

function renderTextEvidence(title, text, note = '') {
  const body = clampText(text || '', 1800);
  return `
    <div class="evidence-card">
      <div class="evidence-head">
        <div>
          <div class="evidence-title">${esc(title)}</div>
          <div class="evidence-note">${esc(note || '심의 대상 원문')}</div>
        </div>
        <span class="evidence-chip">${body.length}자</span>
      </div>
      <pre class="evidence-text">${esc(body || '표시할 텍스트가 없습니다.')}</pre>
    </div>`;
}

function renderOcrQuality(q) {
  if (!q || !q.level) return '';
  const cls = q.level === 'LOW' ? 'low' : (q.level === 'MEDIUM' ? 'medium' : 'high');
  const metrics = [
    q.width && q.height ? `${q.width}×${q.height}` : '',
    q.avg_conf ? `평균 신뢰도 ${q.avg_conf}%` : '',
    q.word_count != null ? `인식 단어 ${q.word_count}개` : '',
  ].filter(Boolean).join(' · ');
  const issues = (q.issues || []).map(i => `<li>${esc(i)}</li>`).join('');
  return `
    <div class="ocr-quality ${cls}">
      <div class="ocr-q-head">
        <b>${q.level === 'LOW' ? 'OCR 신뢰도 낮음' : q.level === 'MEDIUM' ? 'OCR 수동 확인 권장' : 'OCR 품질 양호'}</b>
        <span>${esc(metrics)}</span>
      </div>
      <div class="ocr-q-msg">${esc(q.message || '')}</div>
      ${issues ? `<ul>${issues}</ul>` : ''}
    </div>`;
}

function renderAgentTimeline(r, mode = 'ko') {
  const hasViolation = (r.violations || []).length > 0;
  const hasWarning = (r.warnings || []).length > 0;
  const verified = r.verification && r.verification.total_count
    ? `${r.verification.verified_count}/${r.verification.total_count}`
    : '0/0';
  const grade = r.overall || 'PASS';
  const rows = [
    ['Agent 1', '언어·규제 분류', mode === 'id' ? 'OJK POJK' : '금소법', 'done'],
    ['Agent 2', '위반 탐지', `${(r.violations || []).length}건 위반 · ${(r.warnings || []).length}건 주의`, hasViolation ? 'risk' : (hasWarning ? 'warn' : 'done')],
    ['Agent 3', '정합성 검토', mode === 'cross' ? '번역 리스크 비교' : '단일 심의 생략', mode === 'cross' ? 'done' : 'muted'],
    ['Agent 4', '조문 검증', `${verified}건 확인`, r.verification ? 'done' : 'muted'],
  ];
  return `
    <div class="agent-timeline">
      <div class="agent-title">Agent 실행 흐름 <span>${esc(grade)}</span></div>
      ${rows.map(([a,b,c,s]) => `
        <div class="agent-step ${s}">
          <div class="agent-dot"></div>
          <div>
            <b>${esc(a)}</b>
            <strong>${esc(b)}</strong>
            <span>${esc(c)}</span>
          </div>
        </div>`).join('')}
    </div>`;
}

// ─── Human-in-the-loop 결정 바 + 모달 시스템 ───────────────
// 마지막 판정 결과 보관 (모달 컨텍스트용). mode: 'ko' | 'id' | 'cross'
const lastResults = {};
const MODE_LABEL = { ko: '한국어 · 금소법', id: '인니어 · OJK', cross: '한·인니 교차검증' };
const GRADE_LABEL = {
  VIOLATION: { kor: '위반 적발', cls: 'vio',  icon: '🔴' },
  WARNING:   { kor: '주의 필요', cls: 'warn', icon: '⚠️' },
  PASS:      { kor: '적합 판정', cls: 'pass', icon: '✅' },
};

// 교차검증 정합성 상태 → 등급 매핑
function crossGrade(cons) {
  switch ((cons || {}).consistency_status) {
    case 'BOTH_VIOLATION':
    case 'KO_ONLY_VIOLATION':
    case 'TRANSLATION_ERROR':
      return 'VIOLATION';
    case 'TRANSLATION_DISCREPANCY':
      return 'WARNING';
    default:
      return 'PASS';
  }
}

function renderHumanDecision(r, mode) {
  lastResults[mode] = r;
  const grade = (mode === 'cross') ? crossGrade(r) : (r.overall || 'PASS');
  const txt = grade === 'VIOLATION'
    ? 'AI가 위반 가능성을 탐지했습니다. 최종 승인·반려는 준법관리자가 판단합니다.'
    : grade === 'WARNING'
      ? '주의 항목이 있습니다. 표현 의도와 광고물 맥락을 확인한 뒤 결정하세요.'
      : '자동 탐지상 특이사항은 없지만, 최종 확인 권한은 준법관리자에게 있습니다.';
  return `
    <div class="human-box">
      <div class="human-msg">
        <b>Human-in-the-loop · 준법관리자 최종 판단</b>
        <span>${esc(txt)}</span>
      </div>
      <div class="human-actions">
        <button type="button" class="hitl-act act-approve" data-action="approve" data-mode="${esc(mode)}">승인</button>
        <button type="button" class="hitl-act act-revise"  data-action="revise"  data-mode="${esc(mode)}">수정 요청</button>
        <button type="button" class="hitl-act act-reject"  data-action="reject"  data-mode="${esc(mode)}">반려</button>
      </div>
    </div>`;
}
// ※ 심의 리포트 버튼은 결정(승인·수정요청·반려) 확정 후 배너에서만 노출 —
//    결재란 공란 출력으로 로그·서류가 어긋나는 것을 방지 (markDecision 참조)

// 모달 컨텍스트: 등급 / 점수 / 추천 사유 추출
function decisionContext(mode) {
  const r = lastResults[mode] || {};
  let grade, scoreText, suggestions = [];
  if (mode === 'cross') {
    grade = crossGrade(r);
    const kr = (r.ko_result || {}).risk_score || 0;
    const ir = (r.id_result || {}).risk_score || 0;
    scoreText = Math.max(kr, ir).toFixed(2);
    (r.translation_errors || []).forEach(t => suggestions.push(`'${t.ko_term}' 오번역 수정`));
    if (r.mismatch_summary) suggestions.push(r.mismatch_summary);
  } else {
    grade = r.overall || 'PASS';
    scoreText = (r.risk_score != null) ? Number(r.risk_score).toFixed(2) : '—';
    (r.violations || []).forEach(v => suggestions.push(splitReason(v.reason).title));
    (r.warnings || []).forEach(w => suggestions.push(splitReason(w.reason).title));
  }
  suggestions = [...new Set(suggestions.filter(Boolean))];
  return { grade, scoreText, suggestions };
}

// 액션별 모달 설정
const HITL_ACTIONS = {
  approve: {
    badge: '승인', cls: 'approve', title: '승인 처리',
    desc: '이 콘텐츠를 게시 가능 상태로 승인합니다.',
    needReason: false, confirmLabel: '승인 확정',
    successIcon: '✅', successMsg: '승인 완료',
  },
  revise: {
    badge: '수정 요청', cls: 'revise', title: '수정 요청',
    desc: '담당 부서에 수정이 필요한 사유를 전달합니다.',
    needReason: true, confirmLabel: '수정 요청 전송',
    reasonLabel: '수정 요청 사유', reasonPh: '어떤 표현을 어떻게 수정해야 하는지 적어주세요.',
    successIcon: '📝', successMsg: '수정 요청 전달됨',
  },
  reject: {
    badge: '반려', cls: 'reject', title: '반려 처리',
    desc: '이 콘텐츠를 반려하고 사유를 기록합니다.',
    needReason: true, confirmLabel: '반려 확정',
    reasonLabel: '반려 사유', reasonPh: '반려 사유를 입력하세요. (필수)',
    successIcon: '⛔', successMsg: '반려 처리됨',
  },
};

const _modal = {
  el:    () => document.getElementById('hitl-modal'),
  badge: () => document.getElementById('modal-badge'),
  title: () => document.getElementById('modal-title'),
  sub:   () => document.getElementById('modal-sub'),
  body:  () => document.getElementById('modal-body'),
  foot:  () => document.getElementById('modal-foot'),
};
let _modalState = { action: null, mode: null };

function openHitlModal(action, mode) {
  const cfg = HITL_ACTIONS[action];
  if (!cfg) return;
  const ctx = decisionContext(mode);
  const g = GRADE_LABEL[ctx.grade] || GRADE_LABEL.PASS;
  _modalState = { action, mode };

  const chips = (cfg.needReason && ctx.suggestions.length)
    ? `<div class="reason-chips">${ctx.suggestions.slice(0, 4)
        .map(s => `<button type="button" class="reason-chip">${esc(s)}</button>`).join('')}</div>`
    : '';
  const reasonField = cfg.needReason ? `
    <label class="modal-field-lbl">${esc(cfg.reasonLabel)}</label>
    ${chips}
    <textarea class="modal-textarea" id="modal-reason" placeholder="${esc(cfg.reasonPh)}"></textarea>` : '';

  _modal.badge().className = 'modal-badge ' + cfg.cls;
  _modal.badge().textContent = cfg.badge;
  _modal.title().textContent = cfg.title;
  _modal.sub().textContent = cfg.desc;
  _modal.body().innerHTML = `
    <div class="modal-summary">
      <div class="ms-grade ${g.cls}">${g.icon} ${g.kor}</div>
      <div class="ms-meta">Risk Score <b>${esc(ctx.scoreText)}</b><br>${esc(MODE_LABEL[mode] || '')}</div>
    </div>
    ${reasonField}`;
  _modal.foot().innerHTML = `
    <button type="button" class="modal-btn cancel" data-modal-close>취소</button>
    <button type="button" class="modal-btn ${cfg.cls}" data-modal-confirm>${esc(cfg.confirmLabel)}</button>`;
  _modal.el().classList.add('show');
}

function closeHitlModal() { _modal.el().classList.remove('show'); }

function confirmHitl() {
  const { action, mode } = _modalState;
  const cfg = HITL_ACTIONS[action];
  if (!cfg) return;
  let reason = '';
  if (cfg.needReason) {
    const ta = document.getElementById('modal-reason');
    reason = ta ? ta.value.trim() : '';
    if (!reason) { if (ta) { ta.classList.add('err'); ta.focus(); } return; }
  }
  const ts = new Date().toLocaleString('ko-KR', { hour12: false });
  const reasonHtml = reason
    ? `<div class="success-reason"><span>사유</span><p>${esc(reason)}</p></div>` : '';
  _modal.body().innerHTML = `
    <div class="modal-success">
      <div class="success-icon">${cfg.successIcon}</div>
      <div class="success-msg">${cfg.successMsg}</div>
      <div class="success-ts">기록 시각 ${esc(ts)} · 담당 준법관리자</div>
      ${reasonHtml}
    </div>`;
  _modal.foot().innerHTML = `<button type="button" class="modal-btn primary" data-modal-close>확인</button>`;
  markDecision(mode, action, reason, ts);
  // 심의 리포트에 결정 상태 반영용 (재심의하면 lastResults가 새로 덮여 자동 초기화)
  if (lastResults[mode]) lastResults[mode]._decision = { action, reason, ts };
  // 심의 이력·승인 로그 영속화 (저장 실패해도 UI는 진행)
  try {
    const ctx2 = decisionContext(mode);
    const snEl = document.getElementById(mode === 'cross' ? 'cross-ko' : mode + '-text');
    fetch('/api/decision', {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        mode, decision: action, reason,
        verdict: ctx2.grade,
        risk_score: parseFloat(ctx2.scoreText) || null,
        snippet: (snEl ? snEl.value.trim() : '').slice(0, 120),
      }),
    }).catch(() => {});
  } catch (e) {}
}

// 판정 패널 하단 액션바 → 결정 완료 상태로 갱신
function markDecision(mode, action, reason, ts) {
  const bar = document.getElementById(mode + '-hitl');
  if (!bar) return;
  const cfg = HITL_ACTIONS[action];
  bar.innerHTML = `
    <div class="human-box decided ${cfg.cls}">
      <div class="human-msg">
        <b>${cfg.successIcon} ${cfg.successMsg}</b>
        <span>${esc(ts)} · 준법관리자${reason ? ' · ' + esc(reason) : ''}</span>
      </div>
      <button type="button" class="hitl-act act-report" data-report-mode="${esc(mode)}"
        title="결정 사항(승인·수정요청·반려)이 결재란에 체크된 리포트를 출력합니다">📄 심의 리포트(PDF)</button>
      <button type="button" class="hitl-reset" data-mode="${esc(mode)}">되돌리기</button>
    </div>`;
}

// HITL / 모달 이벤트 위임
document.addEventListener('click', (e) => {
  const act = e.target.closest('.hitl-act');
  if (act && act.dataset.action) { openHitlModal(act.dataset.action, act.dataset.mode); return; }
  const reset = e.target.closest('.hitl-reset');
  if (reset) {
    const m = reset.dataset.mode;
    const bar = document.getElementById(m + '-hitl');
    if (lastResults[m]) delete lastResults[m]._decision;   // 리포트 결정 표기도 함께 해제
    if (bar && lastResults[m]) bar.innerHTML = renderHumanDecision(lastResults[m], m);
    return;
  }
  const chip = e.target.closest('.reason-chip');
  if (chip) {
    const ta = document.getElementById('modal-reason');
    if (ta) { ta.value = (ta.value ? ta.value.trim() + ' / ' : '') + chip.textContent; ta.classList.remove('err'); ta.focus(); }
    return;
  }
  if (e.target.closest('[data-modal-confirm]')) { confirmHitl(); return; }
  if (e.target.closest('[data-modal-close]') || e.target === _modal.el()) { closeHitlModal(); return; }
});
document.addEventListener('keydown', (e) => {
  const el = _modal.el();
  if (e.key === 'Escape' && el && el.classList.contains('show')) closeHitlModal();
});

// ─── 심의 이력·승인 로그 뷰 (심의 결정 전용 — 규칙 변경 이력은 규칙트리관리로 이동) ───
async function openHistory() {
  const m = document.getElementById('history-modal');
  const list = document.getElementById('history-list');
  if (!m || !list) return;
  list.innerHTML = '<div style="padding:24px;text-align:center;color:#9CA3AF">불러오는 중…</div>';
  m.classList.add('show');
  try {
    const res = await fetch('/api/history');
    list.innerHTML = renderHistory((await res.json()).items || []);
  } catch (e) {
    list.innerHTML = '<div style="padding:24px;text-align:center;color:#B91C1C">이력을 불러오지 못했습니다.</div>';
  }
}

// 규칙 변경 이력 — 누가·언제·무엇을(조정/신설/삭제/중지/재개/유형신설/법령신설)·이전값→이후값·왜
function renderRuleChanges(items) {
  if (!items.length) return '<div style="padding:24px;text-align:center;color:#9CA3AF">아직 규칙 변경 이력이 없습니다.</div>';
  const A = {
    raise: ['상향', '#B91C1C', '#FEF2F2'], lower: ['하향', '#B45309', '#FFFBEB'],
    add: ['규칙 신설', '#15803D', '#ECFDF5'], delete: ['삭제', '#B91C1C', '#FEF2F2'],
    disable: ['중지', '#6B7280', '#F3F4F6'], enable: ['재개', '#1D4ED8', '#EFF6FF'],
    add_block: ['유형 신설', '#0E7490', '#ECFEFF'], create_tree: ['법령 신설', '#7C3AED', '#F5F3FF'],
  };
  const cell = 'padding:8px 8px;vertical-align:top;';
  const clip = 'overflow:hidden;text-overflow:ellipsis;white-space:nowrap;';
  const rows = items.map(it => {
    const a = A[it.action] || [it.action || '-', '#6B7280', '#F3F4F6'];
    const delta = (it.before || it.after)
      ? `${esc(it.before || '—')} <span style="color:#9CA3AF">→</span> ${esc(it.after || '—')}` : '<span style="color:#9CA3AF">—</span>';
    return `<tr style="border-bottom:1px solid #F3F4F6">
      <td style="${cell}color:#6B7280;white-space:nowrap;font-size:.76rem">${esc((it.created_at || '').slice(5))}</td>
      <td style="${cell}"><span style="display:inline-block;background:${a[2]};color:${a[1]};padding:2px 8px;border-radius:6px;font-size:.72rem;font-weight:700;white-space:nowrap">${esc(a[0])}</span></td>
      <td style="${cell}${clip}color:#374151" title="${esc(it.tree_file || '')}">${esc(it.tree_file || '')}</td>
      <td style="${cell}${clip}color:#6B7280;font-size:.76rem" title="${esc(it.node_id || it.rule_id || '')}">${esc(it.node_id || it.rule_id || '')}</td>
      <td style="${cell}${clip}color:#374151" title="${esc((it.before || '') + ' → ' + (it.after || ''))}">${delta}</td>
      <td style="${cell}color:#6B7280;word-break:break-word">${esc(it.reason || '')}</td>
    </tr>`;
  }).join('');
  const th = 'padding:8px 8px;font-weight:700;';
  return `<table style="width:100%;border-collapse:collapse;font-size:.82rem;table-layout:fixed">
    <colgroup><col style="width:12%"><col style="width:10%"><col style="width:22%"><col style="width:16%"><col style="width:20%"><col style="width:20%"></colgroup>
    <thead><tr style="text-align:left;color:#6B7280;border-bottom:1px solid #E5E7EB">
      <th style="${th}">시각</th><th style="${th}">작업</th><th style="${th}">법령 트리</th><th style="${th}">규칙/노드</th><th style="${th}">이전 → 이후</th><th style="${th}">사유</th>
    </tr></thead><tbody>${rows}</tbody></table>`;
}
function renderHistory(items) {
  if (!items.length) return '<div style="padding:24px;text-align:center;color:#9CA3AF">아직 저장된 심의 이력이 없습니다.</div>';
  const D = { approve: ['승인', '#15803D', '#ECFDF5'], revise: ['수정요청', '#B45309', '#FFFBEB'], reject: ['반려', '#B91C1C', '#FEF2F2'] };
  const G = { VIOLATION: '위반', WARNING: '주의', PASS: '통과' };
  const rows = items.map(it => {
    const d = D[it.decision] || [it.decision || '-', '#6B7280', '#F3F4F6'];
    return `<tr style="border-bottom:1px solid #F3F4F6">
      <td style="padding:8px 6px;color:#6B7280;white-space:nowrap">${esc(it.created_at || '')}</td>
      <td style="padding:8px 6px">${esc((it.mode || '').toUpperCase())}</td>
      <td style="padding:8px 6px">${esc(G[it.verdict] || it.verdict || '')}</td>
      <td style="padding:8px 6px"><span style="background:${d[2]};color:${d[1]};padding:2px 9px;border-radius:6px;font-size:.74rem;font-weight:600">${esc(d[0])}</span></td>
      <td style="padding:8px 6px;color:#6B7280">${esc(it.reviewer || '')}</td>
      <td style="padding:8px 6px;color:#6B7280;max-width:220px">${esc(it.reason || '')}</td>
    </tr>`;
  }).join('');
  return `<table style="width:100%;border-collapse:collapse;font-size:.82rem">
    <thead><tr style="text-align:left;color:#6B7280;border-bottom:1px solid #E5E7EB">
      <th style="padding:8px 6px">시각</th><th style="padding:8px 6px">구분</th><th style="padding:8px 6px">판정</th><th style="padding:8px 6px">결정</th><th style="padding:8px 6px">담당</th><th style="padding:8px 6px">사유</th>
    </tr></thead><tbody>${rows}</tbody></table>`;
}
document.addEventListener('click', (e) => {
  if (e.target.closest('#history-btn')) { openHistory(); return; }
  if (e.target.closest('[data-history-close]') || e.target === document.getElementById('history-modal')) {
    document.getElementById('history-modal')?.classList.remove('show');
  }
});

function setPanelHtml(id, html, filledClass) {
  const el = document.getElementById(id);
  if (!el) return;
  el.className = filledClass;
  el.innerHTML = html;
}


// ─── 결과 렌더링: 판정 카드 ──────────────────
function renderVerdict(r, prefix = '') {
  const MAP = {
    VIOLATION: { vcls: 'v-vio',  gcls: 'vio',  icon: '🔴', kor: '위반 적발', bcls: 'bv' },
    WARNING:   { vcls: 'v-warn', gcls: 'warn', icon: '⚠️', kor: '주의 필요', bcls: 'bw' },
    PASS:      { vcls: 'v-pass', gcls: 'pass', icon: '✅', kor: '적합 판정', bcls: 'bp' },
  };
  const m = MAP[r.overall] || MAP.PASS;
  const p = prefix ? `[${esc(prefix)}]&nbsp;` : '';
  const bw = Math.min(Math.round(r.risk_score * 100), 100);
  let meta = `법령: <b>${esc((r.language || '').toUpperCase())}</b> &nbsp;|&nbsp; ${Math.round(r.elapsed_ms || 0)}ms`;
  if (r.applied_trees && r.applied_trees.length) {
    meta += ` &nbsp;|&nbsp; ${esc(r.applied_trees.join(', '))}`;
  }

  return `
    <div class="verdict ${m.vcls}">
      <div class="v-icon">${m.icon}</div>
      <div class="v-body">
        <div class="v-grade ${m.gcls}">${p}${m.kor}</div>
        <div class="v-meta">${meta}</div>
      </div>
      <div class="v-right">
        <div class="v-num">${(r.risk_score || 0).toFixed(2)}</div>
        <div class="v-bw"><div class="v-b ${m.bcls}" style="width:${bw}%"></div></div>
        <div class="v-lbl">Risk Score
          <span class="tip tipL" data-tip="위반 가능성 종합 점수 (0~1). Rule·LLM·임베딩 결과를 가중 결합한 값입니다. 점수가 낮아도 '주의' 항목이 탐지되면 안전을 위해 등급이 상향됩니다 (Recall 우선 설계).">?</span>
        </div>
      </div>
    </div>`;
}

// ─── 비전공자용 결과 요약 패널 ───────────────
function renderSummary(r) {
  const GRADE = {
    VIOLATION: { kor: '🔴 위반', desc: '규제 위반으로 판단되는 표현이 발견되었습니다. 수정이 필요합니다.' },
    WARNING:   { kor: '⚠️ 주의', desc: '위반은 아니지만, 오인 소지가 있어 점검이 권장되는 표현이 있습니다.' },
    PASS:      { kor: '✅ 통과', desc: '심의 기준을 모두 충족했습니다.' },
  };
  const g = GRADE[r.overall] || GRADE.PASS;
  const nv = (r.violations || []).length;
  const nw = (r.warnings || []).length;
  const score = (r.risk_score || 0).toFixed(2);
  return `
    <div class="summary-panel">
      <h4>📊 이 결과 이해하기 <span class="tip" data-tip="준법관리자·비전공자를 위한 요약입니다. 상세 데이터는 아래 'JSON 원문'에서 확인할 수 있습니다.">?</span></h4>
      <div class="summary-row"><span class="sr-key">종합 등급</span><span><b>${g.kor}</b> — ${esc(g.desc)}</span></div>
      <div class="summary-row"><span class="sr-key">Risk Score</span><span><b>${score}</b> / 1.00 — 위반 가능성 점수입니다. 0에 가까울수록 안전, 1에 가까울수록 위험합니다.</span></div>
      <div class="summary-row"><span class="sr-key">발견 항목</span><span>위반 <b>${nv}건</b>, 주의 <b>${nw}건</b></span></div>
      <div class="summary-row"><span class="sr-key">신뢰도란?</span><span>각 항목 옆의 <b>%</b>는 AI가 그 판단에 대해 가진 확신도입니다. (Rule = 패턴 명확도, LLM = 모델 판단 확신도)</span></div>
    </div>`;
}


// reason "{제목} (LLM 판단) | LLM: {상세}" → {title, detail}
function splitReason(reason) {
  reason = reason || '';
  let title = reason, detail = '';
  const i = reason.indexOf(' | LLM: ');
  if (i >= 0) { title = reason.slice(0, i); detail = reason.slice(i + 8); }
  title = title.replace(/\s*\(LLM 판단\)\s*/g, '').trim();
  return { title, detail };
}

// ─── 발견 항목 렌더링 (제목/상세 분리, 깔끔한 카드) ──
function renderFindings(r, mode = 'ko') {
  let html = '';
  const vios = r.violations || [];
  const warns = r.warnings || [];

  function card(item, cls, icon) {
    const { title, detail } = splitReason(item.reason);
    const pct = Math.round((item.confidence || 0) * 100);
    const tag = `<span class="bdg ${item.node_type === 'rule' ? 'br' : 'bl'}">${esc((item.node_type || '').toUpperCase())}</span>`;
    // matched_text: 항상 보이는 원문 하이라이트
    const matchPreview = item.matched_text
      ? `<div class="fc-match-preview">"${esc(item.matched_text)}"</div>` : '';
    const detailHtml = detail ? `<div class="fc-detail">${esc(detail)}</div>` : '';
    const action = item.action ? `<div class="hint">💡 ${esc(item.action)}</div>` : '';
    const hasBody = detail || item.citation || item.action;
    const result = cls === 'vio' ? 'VIOLATION' : 'WARNING';
    const editable = item.node_id && item.node_type !== 'embedding';
    const fb = editable ? `<div class="fc-fb-row">
          <button type="button" class="fc-fb" data-rule-adjust
            data-tree="${esc(item.tree_file || '')}" data-rule="${esc(item.rule_id || '')}"
            data-node="${esc(item.node_id)}" data-result="${result}"
            data-conf="${item.confidence || 0}" data-reason="${esc(title)}" data-mode="${esc(mode)}"
            title="이 판정을 적출한 심의 기준의 적용 등급·신뢰도를 조정합니다 (과대적출 교정)">⚖️ 심의 기준 조정</button>
        </div>` : '';
    return `
      <div class="fc ${cls}${hasBody ? ' collapsible' : ''}">
        <div class="fc-head">
          <span class="fc-t">${icon} ${esc(title)}</span>
          <span class="fc-tags">${tag}<span class="fc-conf">${pct}%</span>${hasBody ? '<span class="fc-chev">▸</span>' : ''}</span>
        </div>
        ${matchPreview}
        ${hasBody ? `<div class="fc-body">
          ${detailHtml}
          <div class="fc-cite">📖 ${esc(item.citation || '—')}</div>
          ${action}
        </div>` : ''}
        ${fb}
      </div>`;
  }

  if (vios.length) {
    html += '<div class="grp-lbl">위반 사항</div>';
    vios.forEach(v => { html += card(v, 'vio', '❌'); });
  }
  if (warns.length) {
    html += '<div class="grp-lbl">주의 사항</div>';
    warns.forEach(w => { html += card(w, 'warn', '⚠️'); });
  }
  if (!vios.length && !warns.length) {
    html += `
      <div class="ok-card">
        <span class="ok-i">✅</span>
        <div class="ok-t">위반·주의 없음</div>
        <div class="ok-s">모든 심의 기준 충족</div>
      </div>`;
  }
  html += `<div class="fc-add-row">
      <button type="button" class="fc-add" data-rule-add data-mode="${esc(mode)}" data-region="${r.language === 'id' ? 'ID' : 'KR'}"
        title="적출되지 않은 위험 표현을 새 심의 기준으로 신설합니다 (미적출 보강)">➕ 위험 표현 기준 신설</button>
      <span class="fc-add-hint">적합(통과) 판정 문구에서 표현을 선택한 뒤 눌러도 됩니다</span>
    </div>`;
  return html;
}


// ─── 부작위/현저성 위험 (Layout Risk Analyzer) ──
function renderLayoutWarnings(list) {
  if (!list || !list.length) return '';
  let html = '<div class="grp-lbl">🔍 시각적 현저성 검토 필요 (부작위 위험)</div>';
  list.forEach(w => {
    const src = w.source === 'pdf_text' ? 'PDF 텍스트레이어' : 'OCR 보조(낮은 신뢰도)';
    if (w.kind === 'min_size') {
      const pct = (w.ratio_pct != null) ? w.ratio_pct : Math.round((w.measured_pt / w.dominant_pt) * 100);
      const aOn = (t) => `<span style="font-size:.72rem;background:#FEF3E2;color:#92400E;border:1px solid #F3D08A;padding:3px 9px;border-radius:6px;display:inline-flex;align-items:center;gap:4px">⚠️ ${esc(t)}</span>`;
      const aOff = (t) => `<span style="font-size:.72rem;background:#F3F4F6;color:#9CA3AF;padding:3px 9px;border-radius:6px">${esc(t)}</span>`;
      html += `
      <div style="background:#fff;border:1px solid #F1D9A8;border-radius:12px;padding:14px 16px;margin:8px 0 12px">
        <div style="display:flex;align-items:center;gap:9px;margin-bottom:9px">
          <span style="font-size:.74rem;font-weight:600;background:#FFF7E6;color:#92400E;border:1px solid #F3D08A;padding:3px 9px;border-radius:6px">⚠️ 주의 · 부작위 현저성</span>
          <span style="font-size:.72rem;color:#9CA3AF">p.${w.page} · ${src}</span>
        </div>
        <div style="font-size:.95rem;font-weight:600;color:#1F2937;margin-bottom:13px">필수 고지가 혜택 대비 현저히 작게 표시됨</div>
        <div style="display:grid;grid-template-columns:minmax(0,1fr) minmax(0,1.3fr);gap:10px;margin-bottom:14px">
          <div style="background:#FAFAF9;border:1px solid #F0EFEA;border-radius:8px;padding:10px 12px">
            <div style="font-size:.7rem;color:#92400E;margin-bottom:6px">↗ 가장 강조된 문구</div>
            <div style="font-size:1.25rem;font-weight:600;color:#1F2937;line-height:1.15">${esc(w.benefit_text || '')}</div>
            <div style="font-size:.7rem;color:#9CA3AF;margin-top:5px">${w.benefit_pt}pt</div>
          </div>
          <div style="background:#FAFAF9;border:1px solid #F0EFEA;border-radius:8px;padding:10px 12px">
            <div style="font-size:.7rem;color:#9CA3AF;margin-bottom:6px">↘ 축소된 필수 고지</div>
            <div style="font-size:.72rem;color:#4B5563;line-height:1.45">${esc(w.disclosure_text)}</div>
            <div style="font-size:.72rem;color:#92400E;margin-top:6px">측정 ${w.measured_pt}pt · 본문(${w.dominant_pt}pt)의 ${pct}%</div>
          </div>
        </div>
        <div style="margin-bottom:13px">
          <div style="font-size:.72rem;color:#6B7280;margin-bottom:7px">현저성 판단 축 — 예금성 상품 광고 준수사항</div>
          <div style="display:flex;gap:7px;flex-wrap:wrap">
            ${aOn('크기 · 본문의 ' + pct + '%')}
            ${w.axis_position ? aOn('위치 · 하단 배치') : aOff('위치')}
            ${w.axis_bold ? aOn('굵기 · 혜택만 굵게') : aOff('굵기')}
            ${w.axis_color ? aOn('색상 · 저대비(흐림)') : aOff('색상')}
          </div>
        </div>
        <div style="border-left:3px solid #1D4ED8;padding:1px 0 1px 11px;margin-bottom:${w.intent ? '11px' : '0'}">
          <div style="font-size:.72rem;color:#1D4ED8;margin-bottom:3px">⚖️ 법적 근거</div>
          <div style="font-size:.8rem;color:#1F2937;line-height:1.55">${esc(w.citation || '')}</div>
        </div>
        ${w.intent ? `<div style="font-size:.74rem;color:#6B7280;line-height:1.55">ℹ️ ${esc(w.intent)}</div>` : ''}
      </div>`;
    } else {
      html += `
      <div class="fc warn">
        <div class="fc-t">⚠️ ${esc(w.position_reason || w.risk_type)}</div>
        <div class="fc-m">
          유리 강조: <code>${esc(w.favorable_text)}</code><br>
          불리/조건: <code>${esc(w.adverse_text)}</code><br>
          크기비 <b>${w.size_ratio}배</b>${w.area_ratio ? ` · 면적비 ${w.area_ratio}배` : ''} · p.${w.page} · ${src}
        </div>
        <div class="hint">💡 ${esc(w.recommendation)}</div>
      </div>`;
    }
  });
  html += `<div class="info-box" style="background:#FFFDF5;border-color:#FDE68A;color:#92400E;font-size:.78rem">${esc(list[0].message)} <b>최종 판단은 준법관리자(HITL)</b>가 수행합니다.</div>`;
  return html;
}

// ─── 유사 제재사례 (FAISS 임베딩) ────────────
function renderSanctions(r) {
  const list = r.similar_sanctions || [];
  if (!list.length) return '';
  let html = '<div class="grp-lbl">📚 유사 제재사례 (의미 기반 검색)</div>';
  list.forEach(s => {
    const pct = Math.round((s.score || 0) * 100);
    html += `
      <div class="fc sanction">
        <div class="fc-t">
          <span class="sanction-score">${pct}% 유사</span>
          ${esc(s.violation_type)} · ${esc(s.year || '')}
        </div>
        <div class="fc-m">
          "${esc(s.text)}"<br>
          <b>${esc(s.citation || s.law || '')}</b> — ${esc(s.sanction || '')}
        </div>
      </div>`;
  });
  return html;
}

// ─── AI 자기검증 (Agent 4) ───────────────────
function renderVerification(r) {
  const v = r.verification;
  if (!v || !v.checks || !v.checks.length) return '';
  let html = '<div class="grp-lbl">🛡 Agent 4 · 인용 검증</div>';
  html += `
    <div class="verify-summary">
      <div class="verify-title">Agent 4 조문 검증</div>
      <div class="verify-desc">${esc(v.summary || '')}</div>
    </div>`;
  v.checks.forEach(c => {
    let badge, statusText;
    if (c.source === 'api' && c.law_verified) {
      badge = '<span class="vchk ok">조문 확인</span>';
      statusText = '법제처 국가법령정보 API로 법령명과 조문번호를 확인했습니다.';
    } else if (c.source === 'local_ojk' && c.law_verified) {
      badge = '<span class="vchk ok">OJK 확인</span>';
      statusText = 'OJK 공식 PDF 기반 로컬 조문 DB로 POJK 조문번호를 확인했습니다.';
    } else if (c.source === 'format' && c.law_verified) {
      badge = '<span class="vchk fmt">형식 검증</span>';
      statusText = '공식 API 미연동 해외 법령으로, 조문 표기 형식만 확인했습니다.';
    } else {
      badge = '<span class="vchk bad">확인 필요</span>';
      statusText = 'API 조회 실패 또는 조문 확인 실패입니다. 수동 재검토가 필요합니다.';
    }

    const refs = c.article_refs || [];
    let refHtml = '';
    if (refs.length) {
      refHtml += '<div class="law-ref-list">';
      refs.forEach(ref => {
        const art = ref.article_no
          ? (c.source === 'local_ojk' ? `Pasal ${esc(ref.article_no)}` : `제${esc(ref.article_no)}조`)
          : '법령명';
        const ok = ref.law_verified && ref.article_verified !== false;
        const cls = ok ? 'ok' : 'bad';
        const label = ok ? '확인됨' : '재검토';
        const rlink = ref.link
          ? `<a class="law-open" href="${esc(ref.link)}" target="_blank" rel="noopener">원문 열기 ↗</a>`
          : '<span class="law-open disabled">링크 없음</span>';
        const summary = ref.summary_ko
          ? `<div class="law-ref-summary">${esc(ref.summary_ko)}</div>`
          : '';
        const use = ref.recommended_use
          ? `<div class="law-ref-use">적용: ${esc(ref.recommended_use)}</div>`
          : '';
        refHtml += `
          <div class="law-ref ${cls}">
            <div>
              <div class="law-ref-name">${esc(ref.official_name || ref.law_name || '')}</div>
              <div class="law-ref-meta">${art} · ${label}</div>
              ${summary}
              ${use}
            </div>
            ${rlink}
          </div>`;
      });
      refHtml += '</div>';
    }

    let flags = '';
    (c.llm_flags || []).forEach(f => { flags += `<div class="vflag hallucination">⚠️ ${esc(f)}</div>`; });
    html += `
      <div class="fc verify">
        <div class="verify-head">
          <div>
            <div class="verify-citation">${esc(c.citation)}</div>
            <div class="verify-status">${esc(statusText)}</div>
          </div>
          ${badge}
        </div>
        ${refHtml}
        ${flags}
      </div>`;
  });
  return html;
}

// ─── 언어 배지 ───────────────────────────────
function renderLangBadge(c) {
  const fb = c.fallback_used ? ' · 폴백' : '';
  return `<div class="lang-badge"><span class="ldot"></span>
    ${esc(c.label)} | ${esc(c.law_name)} | 신뢰도 ${Math.round((c.confidence || 0) * 100)}%${fb}</div>`;
}


// ─── 정합성 ──────────────────────────────────
function renderConsistency(cons) {
  let cls, ttl, tc, bc;
  switch (cons.consistency_status) {
    case 'TRANSLATION_ERROR':
      cls = 'c-err';  ttl = '⚠️ 번역 오류 탐지 (번역에서 위반 발생)'; tc = '#92400E'; bc = '#78350F'; break;
    case 'TRANSLATION_DISCREPANCY':
      cls = 'c-err';  ttl = '⚠️ 번역 등급 불일치 (재검토 권장)';      tc = '#92400E'; bc = '#78350F'; break;
    case 'BOTH_VIOLATION':
      cls = 'c-both'; ttl = '🔴 복합 위반 (양측)';      tc = '#991B1B'; bc = '#7F1D1D'; break;
    case 'KO_ONLY_VIOLATION':
      cls = 'c-both'; ttl = '🔴 원본 위반';             tc = '#991B1B'; bc = '#7F1D1D'; break;
    default:
      cls = 'c-ok';   ttl = '✅ 번역 정합성 통과';       tc = '#065F46'; bc = '#064E3B';
  }

  let html = `
    <div class="cons ${cls}">
      <div class="c-t" style="color:${tc}">${ttl}</div>
      <div class="c-b" style="color:${bc}">${esc(cons.mismatch_summary || '')}</div>
    </div>`;

  if (cons.translation_errors && cons.translation_errors.length) {
    html += '<div class="grp-lbl" style="margin-top:16px">📚 Termbase 불일치</div>';
    cons.translation_errors.forEach(t => {
      html += `
        <div class="fc vio">
          <div class="fc-t">'${esc(t.ko_term)}' 오번역</div>
          <div class="fc-m">발견: <code>${esc(t.found_wrong)}</code> → 권고: <code style="color:#059669;font-weight:700">${esc(t.expected_id)}</code></div>
          <div class="hint">${esc(t.suggestion)}</div>
        </div>`;
    });
  }
  return html;
}


// ─── JSON 디테일 박스 ────────────────────────
function renderJsonDetails(obj) {
  return `
    <details style="margin-top:14px">
      <summary>🗂 JSON 원문</summary>
      <div class="json-box">${esc(JSON.stringify(obj, null, 2))}</div>
    </details>`;
}


// ─── 발견 카드 접기/펼치기 (이벤트 위임) ───
document.addEventListener('click', (e) => {
  const head = e.target.closest('.fc.collapsible .fc-head');
  if (!head) return;
  head.parentElement.classList.toggle('open');
});

// 업로드된 파일 보관 (textareaId → File).
// 이미지: /api/detect_image (OCR + 심의)
// PDF:   /api/detect_pdf  (텍스트레이어 추출 + 심의)
const uploadedImages = {};  // 이미지 파일
const uploadedPdfs   = {};  // PDF 파일 (텍스트레이어 심의용)
// 부작위/현저성 위험 보관 (textareaId → layout_warnings[])
const layoutWarnings = {};
const uploadPreviewUrls = {};

const UPLOAD_TARGET_LABEL = {
  'ko-text': '한국어 광고물',
  'id-text': '인도네시아어 광고물',
  'cross-ko': '교차검증 원문',
  'cross-id': '교차검증 번역본',
};

function revokeUploadPreview(textareaId) {
  if (uploadPreviewUrls[textareaId]) {
    URL.revokeObjectURL(uploadPreviewUrls[textareaId]);
    delete uploadPreviewUrls[textareaId];
  }
}

function ensureUploadPreviewModal() {
  let modal = document.getElementById('upload-confirm-modal');
  if (modal) return modal;
  modal = document.createElement('div');
  modal.id = 'upload-confirm-modal';
  modal.className = 'upload-confirm-overlay';
  modal.innerHTML = `
    <div class="upload-confirm-card" role="dialog" aria-modal="true" aria-labelledby="upload-confirm-title">
      <div class="upload-confirm-head">
        <span class="upload-confirm-badge">시연용 광고물</span>
        <button type="button" class="upload-confirm-x" data-upload-preview-confirm aria-label="닫기">×</button>
        <h3 id="upload-confirm-title">이 광고물로 심의할까요?</h3>
        <p>본 광고물은 생성형 AI로 제작한 예시 광고이며, 실제 금융상품 광고가 아닙니다.</p>
      </div>
      <div class="upload-confirm-body">
        <div class="upload-confirm-preview" id="upload-confirm-preview"></div>
        <div class="upload-confirm-meta" id="upload-confirm-meta"></div>
      </div>
      <div class="upload-confirm-foot">
        <button type="button" class="modal-btn cancel" data-upload-preview-replace>다른 파일 선택</button>
        <button type="button" class="modal-btn primary" data-upload-preview-confirm>이 파일 사용</button>
      </div>
    </div>`;
  document.body.appendChild(modal);
  return modal;
}

function uploadFileKind(file) {
  const type = (file.type || '').toLowerCase();
  const name = (file.name || '').toLowerCase();
  if (type.startsWith('image/')) return '이미지';
  if (name.endsWith('.pdf')) return 'PDF';
  if (name.endsWith('.pptx')) return 'PPTX';
  if (name.endsWith('.docx')) return 'DOCX';
  if (name.endsWith('.hwp') || name.endsWith('.hwpx')) return 'HWP/HWPX';
  return '문서';
}

function showUploadPreviewModal({ file, textareaId, fileInputId, extracted }) {
  const modal = ensureUploadPreviewModal();
  const preview = document.getElementById('upload-confirm-preview');
  const meta = document.getElementById('upload-confirm-meta');
  const name = file.name || 'upload';
  const target = UPLOAD_TARGET_LABEL[textareaId] || '광고물';
  const kind = uploadFileKind(file);
  const chars = ((extracted && extracted.text) || '').trim().length;
  const lang = extracted && extracted.detected_lang ? extracted.detected_lang.toUpperCase() : '-';

  revokeUploadPreview(textareaId);
  const url = URL.createObjectURL(file);
  uploadPreviewUrls[textareaId] = url;

  if ((file.type || '').startsWith('image/')) {
    preview.innerHTML = `<img src="${url}" alt="${esc(name)} 미리보기">`;
  } else if (name.toLowerCase().endsWith('.pdf')) {
    preview.innerHTML = `<iframe title="${esc(name)} 미리보기" src="${url}#toolbar=0&navpanes=0&scrollbar=0&view=FitH"></iframe>`;
  } else {
    preview.innerHTML = `
      <div class="upload-confirm-file">
        <div class="upload-confirm-file-icon">PDF</div>
        <strong>${esc(name)}</strong>
        <span>미리보기는 PDF·이미지 파일에서 제공됩니다.</span>
      </div>`;
  }

  meta.innerHTML = `
    <div><span>구분</span><b>${esc(target)}</b></div>
    <div><span>파일명</span><b>${esc(name)}</b></div>
    <div><span>형식</span><b>${esc(kind)}</b></div>
    <div><span>추출 텍스트</span><b>${chars.toLocaleString('ko-KR')}자</b></div>
    <div><span>감지 언어</span><b>${esc(lang)}</b></div>`;
  modal.dataset.textareaId = textareaId;
  modal.dataset.fileInputId = fileInputId;
  modal.classList.add('show');
}

function closeUploadPreviewModal() {
  const modal = document.getElementById('upload-confirm-modal');
  if (!modal) return;
  const textareaId = modal.dataset.textareaId;
  if (textareaId) revokeUploadPreview(textareaId);
  modal.classList.remove('show');
}

document.addEventListener('click', (e) => {
  const modal = document.getElementById('upload-confirm-modal');
  const replace = e.target.closest('[data-upload-preview-replace]');
  if (replace && modal) {
    const fileInputId = modal.dataset.fileInputId;
    closeUploadPreviewModal();
    const input = fileInputId ? document.getElementById(fileInputId) : null;
    if (input) input.click();
    return;
  }
  if (e.target.closest('[data-upload-preview-confirm]') || (modal && e.target === modal)) {
    closeUploadPreviewModal();
  }
});

document.addEventListener('keydown', (e) => {
  const modal = document.getElementById('upload-confirm-modal');
  if (e.key === 'Escape' && modal && modal.classList.contains('show')) closeUploadPreviewModal();
});

// ─── 파일 업로드 → 텍스트 추출 → textarea 채우기 ───
function wireUpload(fileInputId, textareaId, statusId) {
  const fi = document.getElementById(fileInputId);
  if (!fi) return;
  fi.addEventListener('change', async () => {
    const f = fi.files[0];
    if (!f) return;
    const st = document.getElementById(statusId);
    st.className = 'upload-status';
    st.textContent = `'${f.name}' 처리 중...`;
    const fd = new FormData();
    fd.append('file', f);
    try {
      const ctrl = new AbortController();
      const timer = setTimeout(() => ctrl.abort(), REQUEST_TIMEOUT_MS);
      const res = await fetch('/api/extract', { method: 'POST', body: fd, signal: ctrl.signal });
      clearTimeout(timer);
      const j = await res.json();
      if (j.text && j.text.trim()) {
        document.getElementById(textareaId).value = j.text.trim();
        const isImg = (f.type || '').startsWith('image/');
        const isPdf = f.name.toLowerCase().endsWith('.pdf');
        if (isImg) { uploadedImages[textareaId] = f; delete uploadedPdfs[textareaId]; }
        else if (isPdf) { uploadedPdfs[textareaId] = f; delete uploadedImages[textareaId]; }
        else { delete uploadedImages[textareaId]; delete uploadedPdfs[textareaId]; }
        if (j.layout_warnings && j.layout_warnings.length) layoutWarnings[textareaId] = j.layout_warnings;
        else delete layoutWarnings[textareaId];
        // 이미지 파일인 경우 Input 아래 소형 미리보기 표시
        const previewMap = { 'ko-text': 'ko-img-preview', 'id-text': 'id-img-preview' };
        const previewId = previewMap[textareaId];
        if (previewId) {
          const previewEl = document.getElementById(previewId);
          if (previewEl) {
            if (isImg) {
              const url = URL.createObjectURL(f);
              previewEl.innerHTML = `<img src="${url}" alt="업로드 이미지"><div class="preview-label">📎 ${esc(f.name)}</div>`;
              previewEl.hidden = false;
            } else {
              previewEl.hidden = true;
              previewEl.innerHTML = '';
            }
          }
        }
        const ocr = j.ocr_used ? ' · OCR 인식' : '';
        const lang = j.detected_lang ? ` · ${j.detected_lang.toUpperCase()}` : '';
        st.className = 'upload-status ok';
        st.textContent = `✅ ${(j.source_type || '').toUpperCase()} 추출 완료 (${j.text.trim().length}자)${ocr}${lang}`;
        showUploadPreviewModal({
          file: f,
          textareaId,
          fileInputId,
          extracted: j,
        });
      } else {
        st.className = 'upload-status err';
        st.textContent = `⚠️ ${j.note || '텍스트를 추출하지 못했습니다'}`;
      }
    } catch (e) {
      st.className = 'upload-status err';
      st.textContent = '❌ 업로드 실패: ' + esc(e.message);
    }
    fi.value = '';
  });
  // 수동 편집 시 이미지 모드 해제 (텍스트 모드로 전환)
  const ta = document.getElementById(textareaId);
  if (ta) ta.addEventListener('input', () => {
    delete uploadedImages[textareaId];
    delete uploadedPdfs[textareaId];
    delete layoutWarnings[textareaId];
    revokeUploadPreview(textareaId);
  });
}

// 이미지 업로드 → OCR + 심의
async function apiDetectImage(file, language) {
  const fd = new FormData();
  fd.append('file', file);
  fd.append('language', language);
  fd.append('enable_llm', 'true');
  const ctrl = new AbortController();
  const timer = setTimeout(() => ctrl.abort(), REQUEST_TIMEOUT_MS);
  try {
    const res = await fetch('/api/detect_image', { method: 'POST', body: fd, signal: ctrl.signal });
    if (!res.ok) throw new Error(`API error: ${res.status}`);
    return await res.json();
  } catch (e) {
    if (e.name === 'AbortError') {
      throw new Error('이미지 OCR/LLM 분석이 지연되어 요청을 중단했습니다. 이미지 해상도를 낮추거나 다시 실행하세요.');
    }
    throw e;
  } finally {
    clearTimeout(timer);
  }
}

// 추출 텍스트 근거 렌더 (이미지 OCR 품질 배지 + 인식 텍스트)
function renderExtractEvidence(r) {
  if (!r.text) return '';
  const isOcr = !!r.ocr_quality;   // 이미지 OCR이면 품질 배지 표시
  const label = isOcr ? 'OCR 인식 결과' : '추출 텍스트';
  const sub = isOcr ? '이미지에서 추출한 심의 대상 문구' : '문서에서 추출한 심의 대상 문구';
  return (isOcr ? renderOcrQuality(r.ocr_quality) : '')
    + renderTextEvidence(label, r.text, sub);
}
wireUpload('ko-file', 'ko-text', 'ko-file-status');
wireUpload('id-file', 'id-text', 'id-file-status');
wireUpload('cross-ko-file', 'cross-ko', 'cross-ko-file-status');
wireUpload('cross-id-file', 'cross-id', 'cross-id-file-status');


// ─── 한국어 심의 ─────────────────────────────
document.getElementById('ko-run').addEventListener('click', async () => {
  const text = document.getElementById('ko-text').value.trim();
  if (!text) return;
  showLoading('한국어 심의 진행 중...');
  document.getElementById('ko-hitl').innerHTML = '';
  try {
    const imgFile = uploadedImages['ko-text'];
    const pdfFile = uploadedPdfs['ko-text'];
    let r, c;
    if (imgFile) {
      // 이미지: 업로드 때 비전으로 추출한 textarea 텍스트를 재사용 (재추출 안 함 → 결과 고정 + 중복 호출 제거)
      setLoadingStep(1);
      c = await apiPost('/classify', { text });
      setLoadingStep(2);
      r = await apiPost('/detect', { text, language: 'ko', enable_llm: true });
      setLoadingStep(4);
    } else if (pdfFile) {
      // PDF 텍스트레이어: 추출 + 심의
      setLoadingStep(1);
      c = await apiPost('/classify', { text });
      const detectedKoPdf = c.language || c.detected_lang || '';
      if (detectedKoPdf && detectedKoPdf !== 'ko') {
        setPanelHtml('ko-evidence', renderTextEvidence('PDF 원문', text, '언어 불일치로 심의 중단'), 'evidence-content');
        setPanelHtml('ko-result', `<div class="info-box" style="background:#FFFBEB;border-color:#F59E0B;color:#92400E;padding:14px">⚠️ <b>Agent 1: 언어 불일치 — 심의 중단</b><br>PDF 내용이 <b>${esc(detectedKoPdf.toUpperCase())}</b>로 감지되었습니다.</div>` + renderLangBadge(c), 'result-content');
        hideLoading(); return;
      }
      setLoadingStep(2);
      const fd2 = new FormData();
      fd2.append('file', pdfFile);
      fd2.append('language', 'ko');
      fd2.append('enable_llm', 'true');
      const pdfRes = await fetch('/api/detect_pdf', { method: 'POST', body: fd2 });
      r = await pdfRes.json();
      setLoadingStep(4);
    } else {
      setLoadingStep(1);
      c = await apiPost('/classify', { text });      // Agent 1: 실제 언어 감지·검증
      const detectedKo = c.language || c.detected_lang || '';
      const koMismatch = detectedKo && detectedKo !== 'ko';

      if (koMismatch) {
        // Agent 1 불일치 → 이후 심의 중단, 안내만 표시
        setPanelHtml('ko-evidence',
          renderTextEvidence('한국어 심의 원문', text, '언어 불일치로 심의 중단'),
          'evidence-content');
        setPanelHtml('ko-result',
          `<div class="info-box" style="background:#FFFBEB;border-color:#F59E0B;color:#92400E;margin-bottom:12px;padding:14px">
            ⚠️ <b>Agent 1: 언어 불일치 — 심의 중단</b><br>
            입력 텍스트가 <b>${esc(detectedKo.toUpperCase())}</b>로 감지되었습니다.
            한국어 탭에는 한국어(금소법) 텍스트를 입력하세요.<br><br>
            <span style="font-size:0.88em">→ 인도네시아어라면 <b>인니어 심의 탭</b>을, 한·인니 쌍이라면 <b>교차검증 탭</b>을 이용하세요.</span>
          </div>` +
          renderLangBadge(c),
          'result-content');
        hideLoading();
        return;
      }

      setLoadingStep(2);
      r = await apiPost('/detect', { text, language: 'ko', enable_llm: true }); // Agent 2+4
      setLoadingStep(4);
    }
    setPanelHtml('ko-evidence',
      renderExtractEvidence(r) || renderTextEvidence('한국어 심의 원문', text, '입력 텍스트 기준 검토'),
      'evidence-content');
    setPanelHtml('ko-result',
      renderLangBadge(c) +
      renderVerdict(r) +
      renderAgentTimeline(r, 'ko') +
      renderSummary(r) +
      renderFindings(r, 'ko') +
      renderLayoutWarnings(r.layout_warnings || layoutWarnings['ko-text']) +
      renderVerification(r) +
      renderSanctions(r) +
      renderJsonDetails(r),
      'result-content');
    const koHitl = document.getElementById('ko-hitl');
    if (koHitl) koHitl.innerHTML = renderHumanDecision(r, 'ko');
  } catch (e) {
    document.getElementById('ko-result').innerHTML =
      `<div class="info-box" style="background:#FFF5F5;border-color:#FFBBBB;color:#B91C1C">❌ ${esc(e.message)}</div>`;
  } finally {
    hideLoading();
  }
});


// ─── 인니어 심의 ─────────────────────────────
document.getElementById('id-run').addEventListener('click', async () => {
  const text = document.getElementById('id-text').value.trim();
  if (!text) return;
  showLoading('인니어 심의 진행 중...');
  document.getElementById('id-hitl').innerHTML = '';
  try {
    setLoadingStep(1);
    const c = await apiPost('/classify', { text });  // Agent 1: 실제 언어 감지·검증
    // Agent 1 검증: 탭 설정(id)과 실제 감지 언어 불일치 경고
    const detectedId = c.language || c.detected_lang || '';
    const idMismatch = detectedId && detectedId !== 'id';

    if (idMismatch) {
      // Agent 1 불일치 → 이후 심의 중단
      setPanelHtml('id-evidence',
        renderTextEvidence('인도네시아어 심의 원문', text, '언어 불일치로 심의 중단'),
        'evidence-content');
      setPanelHtml('id-result',
        `<div class="info-box" style="background:#FFFBEB;border-color:#F59E0B;color:#92400E;margin-bottom:12px;padding:14px">
          ⚠️ <b>Agent 1: 언어 불일치 — 심의 중단</b><br>
          입력 텍스트가 <b>${esc(detectedId.toUpperCase())}</b>로 감지되었습니다.
          인니어 탭에는 인도네시아어(OJK) 텍스트를 입력하세요.<br><br>
          <span style="font-size:0.88em">→ 한국어라면 <b>한국어 심의 탭</b>을, 한·인니 쌍이라면 <b>교차검증 탭</b>을 이용하세요.</span>
        </div>` +
        renderLangBadge(c),
        'result-content');
      hideLoading();
      return;
    }

    let html = renderLangBadge(c);
    if (!c.available_trees || !c.available_trees.length) {
      html += `<div class="info-box" style="background:#FFFDF5;border-color:#FDE68A;color:#92400E">⚠️ OJK 트리 미존재 — 3주차 이후 심의 가능합니다.</div>`;
    } else {
      setLoadingStep(2);
      const r = await apiPost('/detect', { text, language: 'id', enable_llm: true }); // Agent 2+4
      setLoadingStep(4);
      setPanelHtml('id-evidence',
        renderTextEvidence('인도네시아어 심의 원문', text, '입력 텍스트 기준 검토'),
        'evidence-content');
      html += renderVerdict(r) +
        renderAgentTimeline(r, 'id') +
        renderSummary(r) +
        renderFindings(r, 'id') +
        renderLayoutWarnings(r.layout_warnings || layoutWarnings['id-text']) +
        renderVerification(r) +
        renderJsonDetails(r);
      const idHitl = document.getElementById('id-hitl');
      if (idHitl) idHitl.innerHTML = renderHumanDecision(r, 'id');
    }
    setPanelHtml('id-result', html, 'result-content');
  } catch (e) {
    document.getElementById('id-result').innerHTML =
      `<div class="info-box" style="background:#FFF5F5;border-color:#FFBBBB;color:#B91C1C">❌ ${esc(e.message)}</div>`;
  } finally {
    hideLoading();
  }
});


// ─── 교차 심의 SSE 리더 ──────────────────────
async function apiStreamCross(koText, idText, onStep, timeoutMs = REQUEST_TIMEOUT_MS) {
  const ctrl = new AbortController();
  const timer = setTimeout(() => ctrl.abort(), timeoutMs);
  try {
    const res = await fetch(`${API}/cross/stream`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ ko_text: koText, id_text: idText, enable_llm: true }),
      signal: ctrl.signal,
    });
    if (!res.ok) throw new Error(`API error: ${res.status}`);
    const reader = res.body.getReader();
    const decoder = new TextDecoder();
    let buf = '';
    while (true) {
      const { done, value } = await reader.read();
      if (done) break;
      buf += decoder.decode(value, { stream: true });
      const lines = buf.split('\n');
      buf = lines.pop();
      for (const line of lines) {
        if (!line.startsWith('data: ')) continue;
        try {
          const ev = JSON.parse(line.slice(6));
          if (ev.error) throw new Error(ev.error);
          if (ev.done && ev.result) return ev.result;
          if (ev.step) onStep(ev.step);
        } catch (e) { if (e.message) throw e; }
      }
    }
    throw new Error('SSE 스트림이 결과 없이 종료됐습니다.');
  } catch (e) {
    if (e.name === 'AbortError') throw new Error('응답이 지연되어 요청을 중단했습니다. 잠시 후 다시 실행하세요.');
    throw e;
  } finally {
    clearTimeout(timer);
  }
}

// ─── 교차 심의 ───────────────────────────────
document.getElementById('cross-run').addEventListener('click', async () => {
  const ko = document.getElementById('cross-ko').value.trim();
  const id = document.getElementById('cross-id').value.trim();
  if (!ko || !id) return;
  showLoading('한·인니 교차 심의 중...');
  document.getElementById('cross-hitl').innerHTML = '';
  try {
    // 스왑 가드 — 원문/번역본이 뒤바뀌면 언어-트리 불일치로 '가짜 통과'가 나므로 심의 전 차단
    const [cKo, cId] = await Promise.all([
      apiPost('/classify', { text: ko }), apiPost('/classify', { text: id }),
    ]);
    const koLang = cKo.language || cKo.detected_lang || '';
    const idLang = cId.language || cId.detected_lang || '';
    if (koLang === 'id' || idLang === 'ko') {
      const swapped = koLang === 'id' && idLang === 'ko';
      document.getElementById('cross-result').innerHTML = `
        <div class="info-box" style="background:#FFFBEB;border-color:#F59E0B;color:#92400E;padding:16px">
          ⚠️ <b>Agent 1: 입력 언어 불일치 — 심의 중단</b><br>
          ${swapped
            ? '한국어 원본과 인도네시아어 번역본이 <b>서로 뒤바뀐 것</b>으로 감지되었습니다.<br>두 입력(파일)의 위치를 서로 바꾼 뒤 다시 실행하세요.'
            : `원본 칸은 <b>${esc((koLang || '?').toUpperCase())}</b>, 번역본 칸은 <b>${esc((idLang || '?').toUpperCase())}</b>로 감지되었습니다.<br>원본 칸에는 한국어, 번역본 칸에는 인도네시아어를 입력하세요.`}
          <br><br><span style="font-size:.85em">뒤바뀐 채 심의하면 각 관할 규정이 다른 언어에 적용되어 위반을 놓칩니다(가짜 통과 방지).</span>
        </div>`;
      hideLoading();
      return;
    }
    const cons = await apiStreamCross(ko, id, (step) => setLoadingStep(step));

    let leftCol = '<div class="sec-lbl">🇰🇷 한국어 결과</div>';
    if (cons.ko_result) {
      leftCol += renderVerdict(cons.ko_result, '금소법') + renderFindings(cons.ko_result, 'cross')
               + renderVerification(cons.ko_result);
    }

    let rightCol = '<div class="sec-lbl">🇮🇩 인니어 결과</div>';
    if (cons.id_skipped) {
      rightCol += `
        <div class="info-box" style="text-align:center;padding:24px">
          <div style="font-size:2rem;margin-bottom:8px">⏭️</div>
          <div style="font-weight:800;font-size:.9rem;margin-bottom:4px">인니어 심의 생략</div>
          <div style="font-size:.76rem">${esc(cons.id_skip_reason || '')}</div>
        </div>`;
    } else if (cons.id_result) {
      rightCol += renderVerdict(cons.id_result, 'OJK') + renderFindings(cons.id_result, 'cross')
                + renderVerification(cons.id_result);
    }

    setPanelHtml('cross-result', `
      <div class="sec-lbl">번역 정합성 결과</div>
      ${renderConsistency(cons)}
      <hr class="divider">
      <div class="cross-result-cols">
        <div>${leftCol}</div>
        <div>${rightCol}</div>
      </div>
      ${renderJsonDetails(cons)}`, 'result-content');
    const crossHitl = document.getElementById('cross-hitl');
    if (crossHitl) crossHitl.innerHTML = renderHumanDecision(cons, 'cross');
  } catch (e) {
    document.getElementById('cross-result').innerHTML =
      `<div class="info-box" style="background:#FFF5F5;border-color:#FFBBBB;color:#B91C1C">❌ ${esc(e.message)}</div>`;
  } finally {
    hideLoading();
  }
});


// ─── 메트릭 카운트업 애니메이션 ─────────────
document.addEventListener('DOMContentLoaded', () => {
  const DURATION = 1400; // ms

  document.querySelectorAll('.metric-val[data-target]').forEach(el => {
    const target = parseFloat(el.dataset.target);
    const suffix = el.dataset.suffix || '';
    const decimals = parseInt(el.dataset.decimal || '0', 10);
    const start = performance.now();

    function easeOutCubic(t) {
      return 1 - Math.pow(1 - t, 3);
    }

    function frame(now) {
      const elapsed = now - start;
      const progress = Math.min(elapsed / DURATION, 1);
      const eased = easeOutCubic(progress);
      const current = target * eased;
      el.textContent = current.toFixed(decimals) + suffix;
      if (progress < 1) {
        requestAnimationFrame(frame);
      } else {
        el.textContent = target.toFixed(decimals) + suffix;
      }
    }

    requestAnimationFrame(frame);
  });
});


// ════════════════════════════════════════════════════════════
// E. Rule Editor — 결과 카드에서 바로 교정하는 피드백 루프
//    과탐 같음 → POST /api/rule/adjust  ·  표현 위험등록 → POST /api/rule/add
//    저장 성공 시 같은 모드 재심의를 다시 실행해 '즉시 라이브 반영'을 보여준다.
// ════════════════════════════════════════════════════════════
const RE_HELD_CITATIONS = [
  '금융소비자보호법 제17조 (적합성 원칙)',
  '금융소비자보호법 제21조 (부당권유행위 금지)',
  '금융소비자보호법 제22조 및 동법 시행령 제18조',
  '금융소비자보호법 제22조 및 동법 시행령 제19조',
  'POJK No. 22 Tahun 2023 Pasal 29, Pasal 32, Pasal 53',
];
const RE_LEVELS = ['PASS', 'WARNING', 'VIOLATION'];
const RE_LEVEL_KO = { PASS: '통과', WARNING: '주의', VIOLATION: '위반' };

function reEnsureModal() {
  let m = document.getElementById('rule-modal');
  if (m) return m;
  m = document.createElement('div');
  m.id = 'rule-modal';
  m.className = 'rule-modal-overlay';
  m.innerHTML = `
    <div class="rule-modal-card" role="dialog" aria-modal="true">
      <div class="rule-modal-head"><span id="rule-modal-title"></span>
        <button type="button" class="rule-modal-x" data-rule-close>✕</button></div>
      <div class="rule-modal-body" id="rule-modal-body"></div>
      <div class="rule-modal-foot" id="rule-modal-foot"></div>
    </div>`;
  document.body.appendChild(m);
  return m;
}
function reClose() { document.getElementById('rule-modal')?.classList.remove('show'); }
let _mgrFile = '';
let _mgrAddCtx = null;
function reRun(mode) {
  if (mode === 'mgr') { reRefreshTrees().then(() => reRenderTree(_mgrFile)); return; }   // 편집 → 규칙 수 갱신 + 현재 트리 유지
  const id = mode === 'id' ? 'id-run' : (mode === 'cross' ? 'cross-run' : 'ko-run');
  document.getElementById(id)?.click();
}
function reToast(msg) {
  let t = document.getElementById('rule-toast');
  if (!t) { t = document.createElement('div'); t.id = 'rule-toast'; t.className = 'rule-toast'; document.body.appendChild(t); }
  t.textContent = msg; t.classList.add('show');
  setTimeout(() => t.classList.remove('show'), 2600);
}

// ── 과탐 교정(낮춤) / 미탐 보강(올림) ──
function reOpenAdjust(d) {
  const m = reEnsureModal();
  const cur = d.result || 'WARNING';
  const conf = Math.round((parseFloat(d.conf) || 0) * 100);
  document.getElementById('rule-modal-title').textContent = '⚖️ 심의 기준 조정 — 이 판정을 적출한 규칙';
  document.getElementById('rule-modal-body').innerHTML = `
    <div class="rl-meta">
      <div><span>트리</span> ${esc(d.tree || '-')}</div>
      <div><span>규칙</span> ${esc(d.rule || '-')} · <span>노드</span> ${esc(d.node || '-')}</div>
      ${d.reason ? `<div class="rl-q">"${esc(d.reason)}"</div>` : ''}
    </div>
    <label class="rl-lbl">판정 레벨 <span class="rl-req">(한 단계씩 조정 / 위반→통과는 재확인)</span></label>
    <div class="rl-levels" id="rl-levels">
      ${RE_LEVELS.map(L => `<button type="button" class="rl-lv lv-${L.toLowerCase()} ${L === cur ? 'cur' : ''}" data-lv="${L}">${RE_LEVEL_KO[L]}<small>${L}</small></button>`).join('')}
    </div>
    <label class="rl-lbl">신뢰도(confidence): <b id="rl-cf-v">${conf}%</b></label>
    <input type="range" id="rl-cf" class="rl-range" min="0" max="100" value="${conf}">
    <label class="rl-lbl">사유 <span class="rl-req">(이력에 기록됩니다)</span></label>
    <textarea id="rl-reason" class="rl-ta" placeholder="예) 면책문구가 함께 있어 과탐으로 보입니다"></textarea>
    <div id="rl-warn" class="rl-warn" style="display:none"></div>`;
  document.getElementById('rule-modal-foot').innerHTML = `
    <button type="button" class="modal-btn cancel" data-rule-close>취소</button>
    <button type="button" class="modal-btn primary" id="rl-save">저장 → 즉시 반영</button>`;
  Object.assign(m.dataset, { mode: d.mode || 'ko', tree: d.tree || '', rule: d.rule || '', node: d.node || '', cur, target: cur });
  m.classList.add('show');
  document.getElementById('rl-levels').onclick = (e) => {
    const b = e.target.closest('[data-lv]'); if (!b) return;
    m.dataset.target = b.dataset.lv;
    m.querySelectorAll('.rl-lv').forEach(x => x.classList.toggle('cur', x === b));
  };
  document.getElementById('rl-cf').oninput = (e) => { document.getElementById('rl-cf-v').textContent = e.target.value + '%'; };
  document.getElementById('rl-save').onclick = () => reSaveAdjust(false);
}

async function reSaveAdjust(confirmJump) {
  const m = document.getElementById('rule-modal');
  const reason = document.getElementById('rl-reason').value.trim();
  if (!reason) { document.getElementById('rl-reason').focus(); return; }
  const target = m.dataset.target, cur = m.dataset.cur;
  const body = {
    tree_file: m.dataset.tree, rule_id: m.dataset.rule, node_id: m.dataset.node,
    reason, confirm_jump: confirmJump,
    confidence: parseInt(document.getElementById('rl-cf').value, 10) / 100,
  };
  if (target !== cur) body.result = target;
  try {
    const res = await fetch('/api/rule/adjust', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) });
    if (res.status === 409) {
      const d = (await res.json()).detail || {};
      const w = document.getElementById('rl-warn');
      w.style.display = 'block';
      w.innerHTML = `⚠️ <b>2단계 점프</b> — 진짜 위반을 <b>${esc(RE_LEVEL_KO[d.to] || d.to || '')}</b>로 내립니다. 정말 변경할까요?
        <button type="button" class="modal-btn danger" id="rl-confirm">확인하고 변경</button>`;
      document.getElementById('rl-confirm').onclick = () => reSaveAdjust(true);
      return;
    }
    if (!res.ok) throw new Error('저장 실패 (' + res.status + ')');
    reClose(); reToast('규칙 저장 완료 — 재심의에 즉시 반영됩니다'); reRun(m.dataset.mode);
  } catch (e) { alert(e.message); }
}

// ── 표현 위험 등록(미탐 보강 · 새 규칙 추가) ──
function reKwToPattern(kw) {
  // 쉼표로 단어를 나누면 사이에 다른 말이 껴도 잡는다: '보험금, 무조건, 지급' → 보험금.{0,10}무조건.{0,10}지급
  const one = (s) => s.replace(/[.*+?^${}()|[\]\\]/g, '\\$&').replace(/\s+/g, '\\s*');
  const parts = kw.split(/[,，]/).map(p => p.trim()).filter(Boolean);
  return parts.length > 1 ? parts.map(one).join('.{0,10}') : one(kw.trim());
}
async function reOpenAdd(mode, presetKw, region) {
  const m = reEnsureModal();
  document.getElementById('rule-modal-title').textContent = '➕ 위험 표현 심의 기준 신설 (미적출 보강)';
  let trees = [];
  try { trees = (await (await fetch('/api/trees')).json()).trees || []; } catch (e) {}
  // 관할 분리 — 심의 언어(또는 트리관리 토글)의 관할 트리만 노출 (인니 신설에 한국 법령 안 뜸)
  const rg = region || (mode === 'id' ? 'ID' : (mode === 'mgr' ? _mgrRegion : 'KR'));
  trees = trees.filter(t => (t.region || 'KR') === rg);
  const defTree = (mode === 'mgr' && _mgrAddCtx && _mgrAddCtx.tree) ? _mgrAddCtx.tree
    : (rg === 'ID' ? 'OJK_POJK.yaml' : '금소법_22조_광고규제.yaml');
  const treeOpts = trees.map(t => `<option value="${esc(t.file)}" ${t.file === defTree ? 'selected' : ''}>${esc(t.file)} (${t.n_rules}규칙)</option>`).join('');
  const cites = RE_HELD_CITATIONS.filter(c => rg === 'ID' ? c.includes('POJK') : !c.includes('POJK'));
  const citeOpts = cites.map(c => `<option value="${esc(c)}">`).join('');
  document.getElementById('rule-modal-body').innerHTML = `
    <div class="rl-meta"><div><span>관할</span> ${esc(RE_REGION_KO[rg] || rg)}</div></div>
    ${reGuideHtml('add')}
    <label class="rl-lbl">① 위험 표현(키워드) <span class="rl-hint">— 잡고 싶은 표현. 예: '평생 보장'</span></label>
    <input id="ra-kw" class="rl-input" value="${esc(presetKw || '')}" placeholder="예) 평생 보장">
    <label class="rl-lbl">② 대상 법령 · 위반 유형</label>
    <div class="rl-row">
      <select id="ra-tree" class="rl-input">${treeOpts}</select>
      <select id="ra-rule" class="rl-input"><option>불러오는 중…</option></select>
    </div>
    <div class="rl-row">
      <div><label class="rl-lbl">③ 레벨 <span class="rl-hint">명백하면 위반, 애매하면 주의</span></label>
        <select id="ra-lv" class="rl-input"><option value="VIOLATION">위반</option><option value="WARNING" selected>주의</option></select></div>
      <div><label class="rl-lbl">④ 인용 조문 <span class="rl-req">(필수)</span></label>
        <div class="rl-cite-row">
          <input id="ra-cite" class="rl-input" list="ra-cite-list" placeholder="예) 보험업법 제97조 제1항 제1호">
          <button type="button" class="rl-cite-check" id="ra-cite-check">🔍 조문 확인</button>
        </div>
        <datalist id="ra-cite-list">${citeOpts}</datalist>
        <div id="ra-cite-result" class="rl-cite-result"></div></div>
    </div>
    <label class="rl-lbl">⑤ 사유 <span class="rl-req">(이력에 기록됩니다)</span></label>
    <textarea id="ra-reason" class="rl-ta" placeholder="예) 평생 보장은 원금·지급 보장으로 오인될 소지가 있습니다"></textarea>`;
  document.getElementById('rule-modal-foot').innerHTML = `
    <button type="button" class="modal-btn cancel" data-rule-close>취소</button>
    <button type="button" class="modal-btn primary" id="ra-save">추가 → 즉시 반영</button>`;
  m.dataset.mode = mode;
  m.classList.add('show');
  const loadRules = async () => {
    const f = document.getElementById('ra-tree').value;
    let rules = [], law = '', article = '';
    try {
      const td = await (await fetch('/api/tree?file=' + encodeURIComponent(f))).json();
      rules = td.rules || [];
      law = (td.meta || {}).law || '';
      article = (td.meta || {}).article || '';
    } catch (e) {}
    document.getElementById('ra-rule').innerHTML = rules.map(r => `<option value="${esc(r.rule_id)}">${esc(r.name || r.rule_id)}</option>`).join('') || '<option value="">(규칙 없음)</option>';
    // 인용 조문 후보 — 선택한 법령 트리에 실제로 붙어있는 조문에서 수집 (신설 법령도 자동 반영, 타 법령 조문 미노출)
    const treeCites = [];
    rules.forEach(r => (r.nodes || []).forEach(n => {
      const c = ((n.on_match || {}).citation || '').trim();
      if (c && !c.includes('전문가 추가') && !treeCites.includes(c)) treeCites.push(c);
    }));
    const lawCite = (law + (article ? ' ' + article : '')).trim();
    const dlOpts = treeCites.length ? treeCites : (lawCite ? [lawCite] : cites);
    document.getElementById('ra-cite-list').innerHTML = dlOpts.map(c => `<option value="${esc(c)}">`).join('');
    const cite = document.getElementById('ra-cite');
    if (f.includes('금소법') && f.includes('22')) cite.value = '금융소비자보호법 제22조 및 동법 시행령 제19조';
    else if (f.includes('금소법') && f.includes('21')) cite.value = '금융소비자보호법 제21조 (부당권유행위 금지)';
    else if (f.includes('금소법') && f.includes('17')) cite.value = '금융소비자보호법 제17조 (적합성 원칙)';
    else if (f.includes('OJK')) cite.value = 'POJK No. 22 Tahun 2023 Pasal 29, Pasal 32, Pasal 53';
    else cite.value = treeCites[0] || lawCite || '';
  };
  document.getElementById('ra-tree').onchange = loadRules;
  await loadRules();
  if (mode === 'mgr' && _mgrAddCtx && _mgrAddCtx.rule) document.getElementById('ra-rule').value = _mgrAddCtx.rule;
  _mgrAddCtx = null;
  document.getElementById('ra-save').onclick = reSaveAdd;
  document.getElementById('ra-cite-check').onclick = () => reCheckCitation('ra-cite', 'ra-cite-result');
}

// ── 법률 전문가용 인라인 가이드 (Q4) ──
function reGuideHtml(kind) {
  const items = kind === 'newlaw'
    ? ['법령명은 <b>현행 유효 조문</b>으로 (예: 보험업법 제97조). 삭제·이관된 조문 금지.',
       '생성 후 <b>[＋ 위반 유형]</b>으로 조문·유형별 그룹을, <b>[＋ 기준 추가]</b>로 규칙을 채웁니다.']
    : ['<b>1규칙 = 1금지행위 + 1조문.</b> 조문 근거 없는 규칙은 만들지 않습니다.',
       '<b>명백한 위반만 \'위반\'(자동)</b>, 해석 여지 있으면 <b>\'주의\'(사람 검토)</b> — 넓게 잡고 사람이 거릅니다.',
       '<b>[🔍 조문 확인]</b>으로 인용이 <b>실존·현행</b>인지 국가법령정보에서 즉시 확인하세요(삭제 조문 자동 감지).'];
  return `<details class="rl-guide"><summary>📘 법령 트리 작성 가이드 (전문가용)</summary>
    <ul>${items.map(t => `<li>${t}</li>`).join('')}</ul></details>`;
}

// ── 인용 조문 실측 확인 (Q2) — 국가법령정보 API로 진짜 조문을 보여줌 ──
let _reCiteLast = { citation: '', deleted: false, found: null };
async function reCheckCitation(inputId, resultId) {
  const cite = (document.getElementById(inputId).value || '').trim();
  const box = document.getElementById(resultId);
  if (!cite) { box.className = 'rl-cite-result'; box.innerHTML = ''; return null; }
  box.className = 'rl-cite-result loading'; box.textContent = '국가법령정보 조회 중…';
  let d, res;
  try { res = await fetch('/api/law/article?citation=' + encodeURIComponent(cite)); }
  catch (e) { box.className = 'rl-cite-result warn'; box.textContent = '조회 실패(네트워크)'; return null; }
  if (res.status === 404) {   // 엔드포인트 없음 = 서버 미재시작
    box.className = 'rl-cite-result warn';
    box.innerHTML = 'ⓘ 조문 확인 기능이 아직 서버에 로드되지 않았습니다 — <b>서버(run_server.bat)를 재시작</b>하세요.';
    return null;
  }
  try { d = await res.json(); }
  catch (e) { box.className = 'rl-cite-result warn'; box.textContent = '응답 파싱 실패'; return null; }
  _reCiteLast = { citation: cite, deleted: !!d.deleted, found: d.found };
  if (d.deleted) {
    box.className = 'rl-cite-result bad';
    box.innerHTML = `⛔ <b>삭제된 조문</b> — ${esc(d.content || d.message)}<br><span class="rl-cite-sub">현행 유효 조문으로 바꿔 입력하세요.</span>`;
  } else if (d.ok) {
    box.className = 'rl-cite-result good';
    box.innerHTML = `✅ <b>실존·현행</b> — ${esc(d.official_name || '')} ${esc(d.article_label || '')}${d.title ? ' (' + esc(d.title) + ')' : ''}`
      + (d.hang_ok === false ? `<br><span class="rl-cite-sub">⚠️ ${esc(d.message)}</span>` : '')
      + (d.link ? ` <a href="${esc(d.link)}" target="_blank" rel="noopener">원문</a>` : '');
  } else if (d.found === false && d.reachable) {
    box.className = 'rl-cite-result bad';
    box.innerHTML = `⛔ <b>존재하지 않는 조문</b> — ${esc(d.message)}`;
  } else {
    box.className = 'rl-cite-result warn';
    box.innerHTML = `ⓘ ${esc(d.message || '실측 확인 불가')}`;
  }
  return d;
}

async function reSaveAdd() {
  const m = document.getElementById('rule-modal');
  const kw = document.getElementById('ra-kw').value.trim();
  const reason = document.getElementById('ra-reason').value.trim();
  const rule = document.getElementById('ra-rule').value;
  if (!kw) { document.getElementById('ra-kw').focus(); return; }
  if (!reason) { document.getElementById('ra-reason').focus(); return; }
  if (!rule) { alert('규칙 블록을 선택하세요.'); return; }
  const cite = document.getElementById('ra-cite').value.trim();
  if (!cite) { alert('인용 조문(조문 근거)은 필수입니다. 근거 조문을 입력하거나 목록에서 선택하세요.'); document.getElementById('ra-cite').focus(); return; }
  // 삭제·이관 조문 저장 차단 — 국가법령정보 실측(제95조의4 같은 폐지 조문 방지)
  const chk = await reCheckCitation('ra-cite', 'ra-cite-result');
  if (chk && (chk.deleted || (chk.found === false && chk.reachable))) {
    alert('삭제되었거나 존재하지 않는 조문은 인용할 수 없습니다.\n' + (chk.message || '') + '\n현행 유효 조문으로 바꿔 입력하세요.');
    document.getElementById('ra-cite').focus(); return;
  }
  const body = {
    tree_file: document.getElementById('ra-tree').value,
    rule_id: rule,
    node_id: 'rule_expert_' + Date.now(),
    pattern: reKwToPattern(kw),
    result: document.getElementById('ra-lv').value,
    reason,
    citation: cite,
    action: '준법관리자 추가 규칙 — 해당 표현 재검토',
  };
  try {
    const res = await fetch('/api/rule/add', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) });
    if (!res.ok) { let t; try { t = (await res.json()).detail; } catch (_) { t = res.status; } throw new Error('추가 실패: ' + t); }
    reClose(); reToast(`규칙 추가 완료 — '${kw}' 재심의에 즉시 반영`); reRun(m.dataset.mode);
  } catch (e) { alert(e.message); }
}

// ── 위임 클릭 ──
document.addEventListener('click', (e) => {
  if (e.target.closest('[data-rule-close]') || e.target === document.getElementById('rule-modal')) { reClose(); return; }
  const adj = e.target.closest('[data-rule-adjust]');
  if (adj) { reOpenAdjust(Object.assign({}, adj.dataset)); return; }
  const add = e.target.closest('[data-rule-add]');
  if (add) {
    const sel = (window.getSelection && window.getSelection().toString().trim()) || '';
    reOpenAdd(add.dataset.mode || 'ko', sel, add.dataset.region || '');
  }
});


// ════════════════════════════════════════════════════════════
// 규칙 트리 관리(독립 편집기) — 심의 결과 없이도 좌표로 직접 수정/추가/삭제/끄기
//   원본 법령 룰: 수정(낮춤/올림)·끄기만 / 전문가 추가 룰: 수정·끄기·삭제
// ════════════════════════════════════════════════════════════
// 규칙트리관리 옆 상시 가이드 패널 — 준법 전문가가 시연 중 보면서 직접 작성 (📘 가이드로 접기/펼치기)
function reMgrGuideHtml() {
  return `<aside class="mgr-guide-panel" id="mgr-guide">
    <div class="mg-head">📘 법령 트리 작성 가이드<small>준법 전문가용 · 코드 불필요</small></div>
    <div class="mg-scroll">
      <div class="mg-sec"><div class="mg-t">① 트리는 3층 구조입니다</div>
        <ol>
          <li><b>법령(트리)</b> — 법·조항 하나 = 트리 하나. 예: <b>보험업법 제97조</b></li>
          <li><b>위반 유형(블록)</b> — 그 법이 금지하는 행위 묶음. 예: 허위 고지 / 부당 승환</li>
          <li><b>판정 규칙</b> — "이 표현이 나오면 → 이 등급"</li>
        </ol></div>
      <div class="mg-sec"><div class="mg-t">② 규칙이 판정하는 방식</div>
        <ul>
          <li><b>키워드 규칙</b> — 조문에 직결되는 <b>명백한 금지 표현</b>. 그 말이 나오면 자동 판정. (전문가 신규 추가는 이 방식)</li>
          <li><b>AI 문맥 판단</b> — 키워드로 못 잡는 애매한 표현을 문맥으로. 원본 트리에만 있고 항상 '주의'로 사람에게 넘김.</li>
        </ul></div>
      <div class="mg-sec"><div class="mg-t">③ 3가지 등급 — 언제 무엇을</div>
        <ul class="mg-lvlist">
          <li><span class="mg-lv v">위반</span> 조문에 정면으로 어긋나는 <b>명백한</b> 표현 → 자동 표시</li>
          <li><span class="mg-lv w">주의</span> 해석 여지 있음 → <b>준법관리자 검토</b>로 넘김</li>
          <li><span class="mg-lv p">통과</span> 문제 없음</li>
        </ul>
        <p class="mg-note">원칙: <b>확실하면 위반, 애매하면 주의.</b> 넓게 잡고 사람이 거릅니다(재현율 우선).</p></div>
      <div class="mg-sec"><div class="mg-t">④ 작성 4대 원칙</div>
        <ol>
          <li><b>1규칙 = 1금지행위 + 1조문.</b> 조문 근거 없는 규칙은 만들지 않는다.</li>
          <li>명백한 것만 '위반', 해석 여지 있으면 '주의'.</li>
          <li><b>현행 조문만.</b> 삭제·이관 조문 인용 금지 → <b>[🔍 조문 확인]</b>으로 검증.</li>
          <li><b>좁게 시작.</b> 패턴이 넓으면 정상 광고까지 걸린다(오탐).</li>
        </ol></div>
      <div class="mg-sec"><div class="mg-t">⑤ 화면에서 만드는 순서</div>
        <ol>
          <li><b>[＋ 새 법령]</b> → 법령명 → <b>[🔍 조문 확인]</b>(실존·현행) → 생성</li>
          <li><b>[＋ 위반 유형]</b> → 조문·유형별 그룹 추가</li>
          <li><b>[＋ 기준 추가]</b> → ①표현(키워드) ②등급 ③인용 조문(필수) ④사유</li>
          <li>저장 → 다음 심의부터 <b>즉시 적용</b> · 변경 이력 자동 기록</li>
        </ol></div>
      <div class="mg-sec"><div class="mg-t">⑥ 따라하기 — 보험업법 트리</div>
        <div class="mg-step"><div class="mg-step-h">1단계 · [＋ 새 법령] (법령·조항 추가)</div>
          <div class="mg-kv"><span>법령명</span><b>보험업법</b></div>
          <div class="mg-kv"><span>표시 이름</span><b>보험업법 제97조 (부당 모집행위 금지)</b></div>
          <div class="mg-kv"><span>첫 위반유형</span><b>부당 모집·허위 고지</b></div>
          <div class="mg-step-n">→ <b>[🔍 조문 확인]</b>으로 제97조 현행 확인 후 생성 (삭제 조문이면 저장 차단)</div></div>
        <div class="mg-step"><div class="mg-step-h">2단계 · [＋ 위반 유형] (같은 법에 유형 더)</div>
          <div class="mg-step-n">조문·금지행위 묶음별로 분리: <b>부당 승환계약</b> · <b>허위·과장 광고</b></div></div>
        <div class="mg-step"><div class="mg-step-h">3단계 · [＋ 기준 추가] (유형 안에 규칙)</div>
          <div class="mg-ex">
            <div class="row"><b>보험금 무조건 지급</b><span class="mg-lv v">위반</span></div>
            <div class="sub">인용 보험업법 제97조 제1항 제1호 · 사유 지급조건 오인 단정—허위 모집</div>
            <div class="row"><b>기존 보험 해지하고 갈아타면 유리</b><span class="mg-lv w">주의</span></div>
            <div class="sub">인용 보험업법 제97조 · 사유 부당 승환계약 유도 소지</div>
          </div></div></div>
      <div class="mg-sec"><div class="mg-t">⑦ 다른 예 — 금융소비자보호법 제17조(적합성 원칙)</div>
        <div class="mg-step">
          <div class="mg-kv"><span>법령·표시</span><b>금융소비자보호법 제17조 (적합성 원칙)</b></div>
          <div class="mg-kv"><span>위반유형</span><b>부적합 권유 (무차별·취약고객)</b></div>
          <div class="mg-ex">
            <div class="row"><b>누구나 초보자도 고위험 투자</b><span class="mg-lv w">주의</span></div>
            <div class="sub">인용 금소법 제17조 · 사유 적합성 확인 없는 무차별 권유</div>
            <div class="row"><b>은퇴자 노후자금으로 ELS 고수익</b><span class="mg-lv w">주의</span></div>
            <div class="sub">인용 금소법 제17조 · 사유 취약고객 부적합 권유</div>
          </div></div></div>
      <div class="mg-sec"><div class="mg-t">⑧ 원본 vs 준법담당 추가 규칙</div>
        <ul>
          <li><b>🔒 법령 기준(원본)</b> — 삭제·구조 수정 <b>불가</b>. 등급 조정·적용 중지만.</li>
          <li><b>준법담당 추가</b> — 조정·중지·<b>삭제</b> 모두 가능.</li>
          <li>모든 변경은 <b>사유·인용·이전값→이후값</b>이 감사 추적에 기록됩니다.</li>
        </ul></div>
    </div></aside>`;
}

function reEnsureMgr() {
  let m = document.getElementById('tree-mgr');
  if (m) return m;
  m = document.createElement('div');
  m.id = 'tree-mgr'; m.className = 'tree-mgr-overlay';
  m.innerHTML = `
    ${reMgrGuideHtml()}
    <div class="tree-mgr-card" role="dialog" aria-modal="true">
      <div class="tree-mgr-head">🗂️ 규칙 트리 관리
        <span class="tree-mgr-sub">법령 개정·정기 점검 시 심의 기준을 직접 정비 — 심의 없이 편집, 저장 즉시 다음 심의부터 적용</span>
        <button type="button" class="mgr-hist-btn" data-mgr-hist>📋 변경 이력</button>
        <button type="button" class="mgr-guide-btn" data-mgr-guide title="작성 가이드 접기/펼치기">📘 가이드</button>
        <button type="button" class="rule-modal-x" data-mgr-close>✕</button></div>
      <div class="tree-mgr-regions" id="mgr-regions"></div>
      <div class="mgr-watch" id="mgr-watch"></div>
      <div class="tree-mgr-tabs" id="mgr-tabs"></div>
      <div class="tree-mgr-subtabs" id="mgr-subtabs"></div>
      <div class="tree-mgr-body" id="mgr-body"></div>
      <div class="mgr-hist-panel" id="mgr-hist-panel">
        <div class="mgr-hist-head"><b>📋 규칙 변경 이력</b>
          <span class="mgr-hist-sub">누가·언제·무엇을·이전값→이후값·사유 (감사 추적)</span>
          <button type="button" class="mgr-hist-x" data-mgr-hist-close>✕ 닫기</button></div>
        <div class="mgr-hist-body" id="mgr-hist-body"></div>
      </div>
    </div>`;
  document.body.appendChild(m);
  return m;
}
let _mgrTrees = [];
let _mgrRegion = 'KR';
const RE_REGION_KO = { KR: '🇰🇷 한국 (국내 금융법령)', ID: '🇮🇩 인도네시아 (OJK)' };
async function reOpenManager() {
  const m = reEnsureMgr(); m.classList.add('show');
  document.getElementById('mgr-body').innerHTML = '<div class="mgr-loading">불러오는 중…</div>';
  try { _mgrTrees = (await (await fetch('/api/trees')).json()).trees || []; } catch (e) { _mgrTrees = []; }
  reRenderRegions();
  reLoadWatch(false);   // 규제 변경 모니터링 (12h 캐시, 열 때마다 자동 점검)
}

// 규칙 변경 이력 — 규칙트리관리 안에서 조회(심의 이력에서 이동). 현재 법령 그룹 우선 필터.
async function reOpenChangeHistory() {
  const panel = document.getElementById('mgr-hist-panel');
  const body = document.getElementById('mgr-hist-body');
  if (!panel || !body) return;
  panel.classList.add('show');
  body.innerHTML = '<div class="mgr-loading">불러오는 중…</div>';
  let items = [];
  try { items = ((await (await fetch('/api/rule_changes?limit=200')).json()).items) || []; }
  catch (e) { body.innerHTML = '<div class="mgr-loading">이력을 불러오지 못했습니다.</div>'; return; }
  // 현재 보고 있는 법령 그룹의 파일들만 우선 필터(전체 보기 토글 제공)
  const groupFiles = new Set(_mgrTrees
    .filter(t => (t.region || 'KR') === _mgrRegion && reLawGroup(t) === _mgrLawGroup)
    .map(t => t.file));
  const scoped = items.filter(it => groupFiles.has(it.tree_file));
  const render = (all) => {
    const rows = all ? items : (scoped.length ? scoped : items);
    body.innerHTML = `
      <div class="mgr-hist-filter">
        <button type="button" class="${!all ? 'on' : ''}" data-hist-scope="0">이 법령 (${scoped.length})</button>
        <button type="button" class="${all ? 'on' : ''}" data-hist-scope="1">전체 (${items.length})</button>
      </div>${renderRuleChanges(rows)}`;
    body.querySelectorAll('[data-hist-scope]').forEach(b => b.onclick = () => render(b.dataset.histScope === '1'));
  };
  render(scoped.length === 0);   // 이 법령 이력이 없으면 전체부터
}

// ── 규제 변경 모니터링 — 감시 법령(트리 근거)의 공포·시행일자 변경 감지 ──
async function reLoadWatch(refresh) {
  const el = document.getElementById('mgr-watch');
  if (!el) return;
  el.innerHTML = '<span class="mw-label">📡 규제 변경 감시</span><span class="mw-dim">점검 중…</span>';
  let d;
  try { d = await (await fetch('/api/law_watch' + (refresh ? '?refresh=true' : ''))).json(); }
  catch (e) { el.innerHTML = '<span class="mw-label">📡 규제 변경 감시</span><span class="mw-dim">점검 실패(네트워크)</span>'; return; }
  const t = (d.checked_at || '').replace('T', ' ').slice(5, 16);
  const chips = (d.items || []).map(it => {
    if (it.status === 'updated') {
      const c = it.current || {}, b = it.baseline || {};
      const dday = it.upcoming_days ? ` · 시행 D-${it.upcoming_days}` : '';
      return `<span class="mw-chip warn" title="공포 ${b['공포일자'] || '?'} → ${c['공포일자'] || '?'} · ${c['제개정구분'] || ''}">⚠️ ${esc(it.law)} — 개정 감지 (${esc(c['제개정구분'] || '변경')}${dday})
        <a href="${esc(it.link || '#')}" target="_blank" rel="noopener">원문</a>
        <button type="button" data-watch-ack="${esc(it.law)}">대응 완료(기준 갱신)</button></span>`;
    }
    if (it.status === 'unreachable') return `<span class="mw-chip dim">${esc(it.law)} · 조회 불가</span>`;
    return `<span class="mw-chip ok" title="공포 ${(it.current || {})['공포일자'] || ''} · 시행 ${(it.current || {})['시행일자'] || ''}">✓ ${esc(it.law)}</span>`;
  }).join('');
  el.innerHTML = `<span class="mw-label">📡 규제 변경 감시</span>${chips}
    <span class="mw-dim">최종 점검 ${esc(t)}</span>
    <button type="button" class="mw-refresh" data-watch-refresh>지금 점검</button>`;
}
document.addEventListener('click', async (e) => {
  if (e.target.closest('[data-watch-refresh]')) { reLoadWatch(true); return; }
  const ack = e.target.closest('[data-watch-ack]');
  if (ack) {
    try {
      await fetch('/api/law_watch/ack', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ law: ack.dataset.watchAck }) });
      reToast('기준 갱신 완료 — 트리 대응(조정·중지·신설)이 반영된 상태를 새 기준으로 저장');
      reLoadWatch(false);
    } catch (err) { alert('기준 갱신 실패'); }
  }
});
// 법령 그룹명 추출 — "금융소비자보호법 제22조 (광고 규제)" → "금융소비자보호법"
//   (조항 여러 개가 한 법령으로 묶임. 법령이 늘어도 상위 그룹은 소수로 유지)
function reLawGroup(t) {
  const law = t.law || t.name || t.file || '';
  const m = law.match(/^(.+?법(?:\s*시행령)?)/);   // '...법' 또는 '...법 시행령'까지
  if (m) return m[1].trim();
  if ((t.region || 'KR') === 'ID' || law.includes('POJK') || law.includes('OJK')) return 'OJK (인도네시아)';
  return law.split(/\s*제\s*\d/)[0].trim() || law;
}
let _mgrLawGroup = '';
// 관할(한국/인니) 분리 → 법령 그룹(1단) → 조항(2단) → 룰(본문)
function reRenderRegions() {
  const present = new Set(_mgrTrees.map(t => t.region || 'KR'));
  const regions = ['KR', 'ID'].filter(r => present.has(r));   // 한국 먼저, 인니 다음
  if (!regions.includes(_mgrRegion)) _mgrRegion = regions[0] || 'KR';
  document.getElementById('mgr-regions').innerHTML = regions.map(rg =>
    `<button type="button" class="mgr-region${rg === _mgrRegion ? ' on' : ''}" data-mgr-region="${rg}">${RE_REGION_KO[rg] || rg}</button>`).join('');
  const trees = _mgrTrees.filter(t => (t.region || 'KR') === _mgrRegion);
  // 1단: 법령 그룹 (등장 순서 유지)
  const groups = [];
  trees.forEach(t => { const g = reLawGroup(t); if (!groups.includes(g)) groups.push(g); });
  if (!groups.includes(_mgrLawGroup)) _mgrLawGroup = groups[0] || '';
  document.getElementById('mgr-tabs').innerHTML = groups.map(g => {
    const gts = trees.filter(t => reLawGroup(t) === g);
    const nNodes = gts.reduce((s, t) => s + (t.n_nodes || 0), 0);   // 실제 판정 규칙 수
    const nArt = gts.length;
    return `<button type="button" class="mgr-tab${g === _mgrLawGroup ? ' on' : ''}" data-mgr-group="${esc(g)}">${esc(g)}<small>${nArt}개 조항·규칙 ${nNodes}</small></button>`;
  }).join('') + `<button type="button" class="mgr-tab mgr-newlaw" data-mgr-newlaw="${_mgrRegion}">＋ 새 법령</button>`;
  if (groups.length) reRenderLawGroup(_mgrLawGroup);
  else {
    document.getElementById('mgr-subtabs').innerHTML = '';
    document.getElementById('mgr-body').innerHTML = '<div class="mgr-loading">해당 관할 트리가 없습니다.</div>';
  }
}
// 2단: 선택한 법령의 조항 칩
function reRenderLawGroup(group) {
  _mgrLawGroup = group;
  document.querySelectorAll('#mgr-tabs .mgr-tab').forEach(b => b.classList.toggle('on', b.dataset.mgrGroup === group));
  const trees = _mgrTrees.filter(t => (t.region || 'KR') === _mgrRegion && reLawGroup(t) === group);
  // 조항 라벨 — 법령명에서 그룹 접두 제거 → "제22조 (광고 규제)"
  const artLabel = (t) => {
    const law = t.law || t.name || t.file || '';
    const rest = law.replace(group, '').replace(/^[\s·—-]+/, '').trim();
    return rest || (t.name || t.file);
  };
  document.getElementById('mgr-subtabs').innerHTML = trees.map(t =>
    `<button type="button" class="mgr-subtab" data-mgr-tab="${esc(t.file)}">${esc(artLabel(t))}<small>${t.n_rules}유형·${t.n_nodes}규칙</small></button>`).join('');
  if (trees.length) reRenderTree(trees[0].file);
  else document.getElementById('mgr-body').innerHTML = '<div class="mgr-loading">이 법령에 조항 트리가 없습니다.</div>';
}
async function reRenderTree(file) {
  if (!file) return;
  _mgrFile = file;
  document.querySelectorAll('#mgr-subtabs .mgr-subtab').forEach(b => b.classList.toggle('on', b.dataset.mgrTab === file));
  const body = document.getElementById('mgr-body');
  body.innerHTML = '<div class="mgr-loading">불러오는 중…</div>';
  let v;
  try { v = await (await fetch('/api/tree?file=' + encodeURIComponent(file))).json(); }
  catch (e) { body.innerHTML = '<div class="mgr-loading">불러오지 못했습니다.</div>'; return; }
  body.innerHTML = (v.rules || []).map(r => `
    <div class="mgr-block">
      <div class="mgr-block-h"><b>${esc(r.name || r.rule_id)}</b><code>${esc(r.rule_id)}</code>
        <button type="button" class="mgr-add" data-mgr-add data-tree="${esc(file)}" data-rule="${esc(r.rule_id)}">+ 기준 추가</button></div>
      ${(r.nodes || []).filter(n => !n.internal).map(n => reNodeRow(file, r.rule_id, n)).join('')}
    </div>`).join('')
    + `<button type="button" class="mgr-add-block" data-mgr-addblock="${esc(file)}">＋ 위반 유형 추가 <small>(조문·유형별 규칙 그룹)</small></button>`;
}
// Q1 — 위반 유형(규칙 블록) 추가: 새 법령도 조문/유형별로 규칙을 묶을 수 있게
async function reAddBlock(file) {
  const name = prompt('추가할 위반 유형(규칙 블록)의 이름을 입력하세요.\n예) 허위·과장 광고 / 부당 비교 / 원금 보장 오인', '');
  if (name === null) return;
  if (!name.trim()) { alert('위반 유형 이름은 필수입니다.'); return; }
  try {
    const res = await fetch('/api/rule/block', { method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ tree_file: file, name: name.trim() }) });
    if (!res.ok) { let t; try { t = (await res.json()).detail; } catch (_) { t = res.status; } throw new Error(t); }
    reToast(`위반 유형 '${name.trim()}' 추가 — [＋ 기준 추가]로 규칙을 채우세요`);
    await reRefreshTrees();        // 규칙/노드 수 갱신(Q3)
    reRenderTree(file);
  } catch (e) { alert('위반 유형 추가 실패: ' + e.message); }
}
// Q3 — 트리 요약(규칙·노드 수) 다시 불러와 탭 라벨 갱신
async function reRefreshTrees() {
  try { _mgrTrees = (await (await fetch('/api/trees')).json()).trees || []; } catch (e) {}
  reRenderRegions();
}
// 정규식 패턴 → 사람이 읽는 키워드 칩 (준법담당자가 정규식을 몰라도 무슨 표현을 잡는지 보이게)
function rePatternToChips(pattern) {
  if (!pattern) return '<span class="mgr-pat-raw">—</span>';
  const toks = [];
  (pattern.match(/\(([^()]*\|[^()]*)\)/g) || []).forEach(g => {
    g.replace(/^\(|\)$/g, '').split('|').forEach(t => {
      const w = t.replace(/\\s\*/g, ' ').replace(/\\[a-z]/gi, '').replace(/[.*+?^${}\[\]]/g, '').trim();
      if (w && w.length <= 16) toks.push(w);
    });
  });
  const uniq = [...new Set(toks)].slice(0, 14);
  if (!uniq.length) {
    // 단일 키워드('평생\s*보장') 또는 쉼표 분리('보험금.{0,10}무조건.{0,10}지급') 패턴 → 단어별 칩으로 표시
    const segs = pattern.split(/\.\{0,\d+\}/).map(s =>
      s.replace(/\\s\*/g, ' ').replace(/\\[a-z]/gi, '').replace(/[.*+?^${}\[\]]/g, '').trim()
    ).filter(Boolean);
    if (segs.length && segs.every(w => w.length <= 24 && !/[()|\\]/.test(w))) {
      return segs.map(w => `<span class="mgr-kw">${esc(w)}</span>`).join('');
    }
    return `<span class="mgr-pat-raw" title="정규식">${esc(pattern)}</span>`;
  }
  return uniq.map(t => `<span class="mgr-kw">${esc(t)}</span>`).join('')
    + (toks.length > uniq.length ? '<span class="mgr-kw more">…</span>' : '');
}

function reNodeRow(file, ruleId, n) {
  const om = n.on_match || {};
  const lv = om.result || 'PASS';
  const expert = n.origin === 'expert';
  const off = n.enabled === false;
  const isLlm = n.type === 'llm';
  const badges = `<span class="mgr-bdg lv-${(lv || 'pass').toLowerCase()}">${RE_LEVEL_KO[lv] || lv}</span>`
    + (isLlm ? '<span class="mgr-bdg ty">AI 자동 판단</span>' : '')
    + (expert ? '<span class="mgr-bdg ex">준법담당 추가</span>' : '<span class="mgr-bdg og">🔒 법령 기준</span>')
    + (off ? '<span class="mgr-bdg off">적용 중지</span>' : '');
  const desc = isLlm
    ? `<div class="mgr-node-desc">${esc(n.check || 'AI 맥락 판단 (정규식 없음)')}</div>`
    : `<div class="mgr-node-pat" title="${esc(n.pattern || '')}">${rePatternToChips(n.pattern)}</div>`;
  const btns =
    `<button type="button" class="mgr-btn" data-mgr-edit data-tree="${esc(file)}" data-rule="${esc(ruleId)}" data-node="${esc(n.node_id)}" data-result="${esc(lv)}" data-conf="${om.confidence || 0}" data-reason="${esc((om.reason || '').slice(0, 70))}">조정</button>`
    + `<button type="button" class="mgr-btn" data-mgr-toggle data-tree="${esc(file)}" data-rule="${esc(ruleId)}" data-node="${esc(n.node_id)}" data-on="${off ? '1' : '0'}">${off ? '적용 재개' : '적용 중지'}</button>`
    + (expert ? `<button type="button" class="mgr-btn del" data-mgr-del data-tree="${esc(file)}" data-rule="${esc(ruleId)}" data-node="${esc(n.node_id)}">삭제</button>` : '');
  return `
    <div class="mgr-node${off ? ' off' : ''}">
      <div class="mgr-node-top">${badges}<code class="mgr-nid">${esc(n.node_id)}</code></div>
      ${desc}
      <div class="mgr-node-btns">${btns}</div>
    </div>`;
}
async function reDelete(d) {
  if (!confirm(`전문가 추가 룰을 삭제할까요?\n[${d.node}]\n(백업·이력은 남습니다)`)) return;
  const reason = prompt('삭제 사유(이력 기록):', '') || '';
  try {
    const res = await fetch('/api/rule/delete', { method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ tree_file: d.tree, rule_id: d.rule, node_id: d.node, reason }) });
    if (!res.ok) { let t; try { t = (await res.json()).detail; } catch (_) { t = res.status; } throw new Error(t); }
    reToast('규칙 삭제 완료'); await reRefreshTrees(); reRenderTree(d.tree);
  } catch (e) { alert('삭제 실패: ' + e.message); }
}
async function reToggle(d) {
  const enable = d.on === '1';   // 현재 꺼짐(on=1)이면 → 켜기
  const reason = prompt(enable ? '재활성 사유(이력 기록):' : '비활성화 사유(이력 기록):', '') || '';
  try {
    const res = await fetch('/api/rule/enable', { method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ tree_file: d.tree, rule_id: d.rule, node_id: d.node, enabled: enable, reason }) });
    if (!res.ok) throw new Error(res.status);
    reToast(enable ? '규칙 켜짐 — 다음 심의부터 반영' : '규칙 꺼짐 — 다음 심의부터 제외'); reRenderTree(d.tree);
  } catch (e) { alert('변경 실패: ' + e.message); }
}
// 새 법령 트리 생성 — 코드 없이 신규 관할/법령을 라이브로 추가 (조문 근거는 규칙 추가 단계에서 강제)
function reOpenCreateTree(region) {
  const m = reEnsureModal();
  document.getElementById('rule-modal-title').textContent = '🆕 새 법령 트리 생성 — 코드 없이 관할 확장';
  const isID = region === 'ID';
  document.getElementById('rule-modal-body').innerHTML = `
    <div class="rl-meta"><div><span>관할</span> ${esc(RE_REGION_KO[region] || region)} — 생성 즉시 이 관할 심의에 자동 편입됩니다</div></div>
    ${reGuideHtml('newlaw')}
    <label class="rl-lbl">법령명 <span class="rl-req">(예: 보험업법 제97조 (부당 모집행위 금지))</span></label>
    <div class="rl-cite-row">
      <input id="ct-law" class="rl-input" placeholder="예) 보험업법 제97조 (부당 모집행위 금지)">
      ${isID ? '' : '<button type="button" class="rl-cite-check" id="ct-law-check">🔍 조문 확인</button>'}
    </div>
    <div id="ct-law-result" class="rl-cite-result"></div>
    <label class="rl-lbl">표시 이름 <span class="rl-req">(선택)</span></label>
    <input id="ct-name" class="rl-input" placeholder="예) 보험업법 부당 모집행위">
    <label class="rl-lbl">첫 위반 유형(규칙 블록명) <span class="rl-req">(선택)</span></label>
    <input id="ct-block" class="rl-input" placeholder="예) 부당 모집행위 금지">
    <div class="rl-warn" style="display:block;background:#EAF1FF;border-color:#C7DBF7;color:#0043AB">
      ⓘ 생성 후 이 트리에 <b>[＋ 위반 유형]</b>으로 조문·유형 그룹을, <b>[＋ 기준 추가]</b>로 규칙을 채우면 다음 심의부터 즉시 적용됩니다.</div>`;
  document.getElementById('rule-modal-foot').innerHTML = `
    <button type="button" class="modal-btn cancel" data-rule-close>취소</button>
    <button type="button" class="modal-btn primary" id="ct-save">생성 → 관할 편입</button>`;
  m.dataset.region = region;
  m.classList.add('show');
  document.getElementById('ct-save').onclick = reSaveCreateTree;
  if (!isID) document.getElementById('ct-law-check').onclick = () => reCheckCitation('ct-law', 'ct-law-result');
}

async function reSaveCreateTree() {
  const m = document.getElementById('rule-modal');
  const law = document.getElementById('ct-law').value.trim();
  if (!law) { document.getElementById('ct-law').focus(); return; }
  const region = m.dataset.region;
  // 삭제·이관 조문으로 법령 생성 차단 (한국 법령만, 국가법령정보 실측)
  if (region !== 'ID') {
    const chk = await reCheckCitation('ct-law', 'ct-law-result');
    if (chk && (chk.deleted || (chk.found === false && chk.reachable))) {
      alert('삭제되었거나 존재하지 않는 조문으로는 법령 트리를 만들 수 없습니다.\n' + (chk.message || '') + '\n현행 유효 조문명으로 바꿔 입력하세요.');
      document.getElementById('ct-law').focus(); return;
    }
  }
  const name = document.getElementById('ct-name').value.trim();
  const block = document.getElementById('ct-block').value.trim();
  const jur = region === 'ID' ? ('인도네시아 (' + (name || law) + ')') : ('한국 (' + (name || law) + ')');
  const base = (name || law).replace(/[\\/:*?"<>|]/g, '').replace(/\s+/g, '_').slice(0, 40) || ('law_' + Date.now());
  const body = { file: base + '.yaml', law, name, jurisdiction: jur, first_block_name: block };
  try {
    const res = await fetch('/api/tree/create', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) });
    if (!res.ok) { let t; try { t = (await res.json()).detail; } catch (_) { t = res.status; } throw new Error(t); }
    const created = await res.json();
    reClose();
    reToast(`새 법령 '${name || law}' 생성 — ${RE_REGION_KO[region] || region} 심의에 편입`);
    _mgrTrees = (await (await fetch('/api/trees')).json()).trees || [];
    _mgrRegion = region;
    const newT = _mgrTrees.find(t => t.file === created.file);
    _mgrLawGroup = newT ? reLawGroup(newT) : '';   // 새로 만든 법령 그룹을 자동 선택
    reRenderRegions();
  } catch (e) { alert('생성 실패: ' + e.message); }
}

document.getElementById('tree-mgr-btn')?.addEventListener('click', reOpenManager);
document.addEventListener('click', (e) => {
  if (e.target.closest('[data-mgr-guide]')) { document.getElementById('tree-mgr')?.classList.toggle('guide-off'); return; }
  if (e.target.closest('[data-mgr-hist-close]')) { document.getElementById('mgr-hist-panel')?.classList.remove('show'); return; }
  if (e.target.closest('[data-mgr-hist]')) { reOpenChangeHistory(); return; }
  if (e.target.closest('[data-mgr-close]') || e.target === document.getElementById('tree-mgr')) {
    document.getElementById('tree-mgr')?.classList.remove('show');
    document.getElementById('mgr-hist-panel')?.classList.remove('show'); return;
  }
  const rg = e.target.closest('[data-mgr-region]'); if (rg) { _mgrRegion = rg.dataset.mgrRegion; _mgrLawGroup = ''; reRenderRegions(); return; }
  const nl = e.target.closest('[data-mgr-newlaw]'); if (nl) { reOpenCreateTree(nl.dataset.mgrNewlaw); return; }
  const grp = e.target.closest('[data-mgr-group]'); if (grp) { reRenderLawGroup(grp.dataset.mgrGroup); return; }
  const tab = e.target.closest('[data-mgr-tab]'); if (tab) { reRenderTree(tab.dataset.mgrTab); return; }
  const ab = e.target.closest('[data-mgr-addblock]'); if (ab) { reAddBlock(ab.dataset.mgrAddblock); return; }
  const ed = e.target.closest('[data-mgr-edit]'); if (ed) { reOpenAdjust(Object.assign({ mode: 'mgr' }, ed.dataset)); return; }
  const ad = e.target.closest('[data-mgr-add]'); if (ad) { _mgrAddCtx = { tree: ad.dataset.tree, rule: ad.dataset.rule }; reOpenAdd('mgr', ''); return; }
  const dl = e.target.closest('[data-mgr-del]'); if (dl) { reDelete(dl.dataset); return; }
  const tg = e.target.closest('[data-mgr-toggle]'); if (tg) { reToggle(tg.dataset); return; }
});


// ════════════════════════════════════════════════════════════
// 심의 리포트 자동 출력 — 대표 케이스 1장(A4) 인쇄/PDF.
//   AI 심의 결과(판정·근거조문·수정권고) + 준법관리자 결재 서식 = 규제 소명 자료.
// ════════════════════════════════════════════════════════════
function reOpenReport(mode) {
  const r = lastResults[mode];
  if (!r) { alert('먼저 심의를 실행하세요.'); return; }
  const G = { VIOLATION: ['위반', '#B91C1C'], WARNING: ['주의', '#B45309'], PASS: ['통과', '#0B6B38'] };
  const now = new Date();
  const ts = now.toLocaleString('ko-KR');
  const p2 = (n) => ('0' + n).slice(-2);
  const rid = `LA-${now.getFullYear()}${p2(now.getMonth() + 1)}${p2(now.getDate())}-${p2(now.getHours())}${p2(now.getMinutes())}${p2(now.getSeconds())}`;
  const rows = (items, kind) => (items || []).map(it => `
    <tr><td class="k">${kind}</td><td>${esc(it.reason || '')}</td>
    <td>${esc(it.citation || '—')}</td><td>${esc(it.action || '—')}</td></tr>`).join('');

  // 판정 1건(단일 심의 또는 교차검증의 한쪽 관할)을 리포트 섹션으로
  const section = (title, R, srcText) => {
    if (!R) return '';
    const g = R.overall || 'PASS';
    const gm = G[g] || [g, '#334155'];
    const risk = (R.risk_score != null) ? Number(R.risk_score).toFixed(2) : '—';
    const findings = (rows(R.violations, '위반') + rows(R.warnings, '주의'))
      || '<tr><td colspan="4" style="text-align:center;color:#6B7280;padding:14px">탐지된 위반·주의 항목 없음 (통과)</td></tr>';
    return `
    ${title ? `<div class="sec big">${title}</div>` : ''}
    <div class="v"><span class="b" style="background:${gm[1]}">${gm[0]}</span>
      <span>리스크 점수 <b>${risk}</b> / 1.00</span></div>
    <div class="sec">심의 대상 문구</div>
    <div class="q">${esc((srcText || '').trim().slice(0, 700)) || '(문구 없음)'}</div>
    <div class="sec">탐지 항목 · 근거 조문 · 수정 권고</div>
    <table><thead><tr><th style="width:48px">구분</th><th>판단 사유</th><th style="width:190px">근거 조문</th><th style="width:165px">수정 권고</th></tr></thead>
      <tbody>${findings}</tbody></table>`;
  };

  let lang, bodyHtml;
  if (mode === 'cross') {
    // 교차검증: 한국(금소법)·인니(OJK) 양쪽 판정 + 번역 정합성을 모두 수록
    lang = '한·인니 교차검증 · 금소법 + OJK POJK';
    const koText = (document.getElementById('cross-ko') || {}).value || '';
    const idText = (document.getElementById('cross-id') || {}).value || '';
    const drift = (r.translation_errors || []).map(t => `'${esc(t.ko_term || '')}' 오번역`).join(', ')
      || (r.mismatch_summary ? esc(r.mismatch_summary) : '');
    bodyHtml = `
    <div class="sec">번역 정합성 (규제 드리프트)</div>
    <div class="q">${drift || '원본·번역본 판정 일치 — 특이 드리프트 없음'}</div>
    ${section('🇰🇷 한국어 원본 — 금융소비자보호법', r.ko_result, koText)}
    ${r.id_skipped
      ? `<div class="sec big">🇮🇩 인니어 번역본 — OJK POJK</div><div class="q">인니어 심의 생략: ${esc(r.id_skip_reason || '')}</div>`
      : section('🇮🇩 인니어 번역본 — OJK POJK 22/2023', r.id_result, idText)}`;
  } else {
    lang = r.language === 'id' ? '인도네시아어 · OJK POJK' : '한국어 · 금융소비자보호법';
    const textEl = document.getElementById(mode + '-text') || document.getElementById('ko-text');
    bodyHtml = section('', r, textEl ? textEl.value : '');
  }

  const html = `<!DOCTYPE html><html lang="ko"><head><meta charset="utf-8"><title>LexAide 준법 심의 리포트 ${rid}</title>
  <style>
    *{box-sizing:border-box}
    body{font-family:'Malgun Gothic','맑은 고딕',sans-serif;color:#1a2b4a;margin:0;padding:30px 34px;font-size:12px}
    .h{display:flex;justify-content:space-between;align-items:flex-end;border-bottom:2.5px solid #001D6C;padding-bottom:10px}
    .t{font-size:20px;font-weight:800;color:#001D6C}.s{font-size:11px;color:#5C7A9E;margin-top:2px}
    .m{font-size:10.5px;color:#5C7A9E;text-align:right;line-height:1.7}
    .v{display:flex;align-items:center;gap:14px;margin:16px 0 4px}
    .b{font-size:15px;font-weight:900;padding:6px 16px;border-radius:8px;color:#fff}
    .sec{font-size:12.5px;font-weight:800;color:#001D6C;margin:16px 0 6px;border-left:4px solid #0043AB;padding-left:8px}
    .sec.big{font-size:14px;margin-top:22px;border-left-width:6px;padding-top:2px;padding-bottom:2px;background:#F6F9FF}
    .q{background:#F6F9FF;border:1px solid #E2EAF5;border-radius:8px;padding:10px 12px;font-size:11px;color:#334155;white-space:pre-wrap;line-height:1.6}
    table{width:100%;border-collapse:collapse;margin-top:4px}
    th,td{border:1px solid #D6E0EE;padding:7px 9px;text-align:left;vertical-align:top;font-size:11px;line-height:1.5}
    th{background:#EEF3FB;color:#0B1F44;font-weight:800}td.k{font-weight:800;white-space:nowrap}
    .d{margin-top:18px;border:1.5px solid #CBD9EC;border-radius:8px;padding:12px 14px}
    .d h4{margin:0 0 10px;font-size:12px;color:#001D6C}
    .ck{font-size:13px;margin-bottom:14px;letter-spacing:.5px}
    .sg{font-size:11px;color:#5C7A9E}.sg u{color:#1a2b4a;text-decoration:none;border-bottom:1px solid #9CB0CC;padding:0 40px}
    .f{margin-top:18px;font-size:9.5px;color:#94A3B8;border-top:1px solid #E2EAF5;padding-top:8px;line-height:1.6}
    .pb{margin:16px 0}.pb button{font-size:12px;font-weight:700;padding:8px 18px;border:none;border-radius:8px;background:#0043AB;color:#fff;cursor:pointer}
    @media print{.pb{display:none}body{padding:0}}
  </style></head><body>
    <div class="pb"><button onclick="window.print()">🖨 인쇄 / PDF로 저장</button></div>
    <div class="h"><div><div class="t">LexAide 준법 심의 리포트</div>
      <div class="s">다국어 금융광고 준법 심의 · Human-in-the-loop</div></div>
      <div class="m">리포트 번호 ${rid}<br>생성일시 ${ts}<br>관할·언어 ${lang}</div></div>
    ${bodyHtml}
    ${(() => {
      // 화면에서 이미 결정했으면 리포트에 그대로 반영(전자 기록 → 문서 증빙), 서명만 공란
      const dec = r._decision;
      const box = (label, key) => (dec && dec.action === key)
        ? `<b style="color:#0B1F44">☑ ${label}</b>` : `☐ ${label}`;
      const decMeta = dec ? `
      <div style="font-size:11px;color:#334155;margin-bottom:10px">결정 일시 ${esc(dec.ts)} · 담당 준법관리자${dec.reason ? `<br>사유: ${esc(dec.reason)}` : ''}</div>` : '';
      return `
    <div class="d"><h4>준법관리자 결정 (Human-in-the-loop)${dec ? ' — 시스템 기록 반영' : ''}</h4>
      <div class="ck">${box('승인', 'approve')}　　　${box('수정 요청', 'revise')}　　　${box('반려', 'reject')}</div>
      ${decMeta}
      <div class="sg">담당자 <u>&nbsp;</u>　　서명 <u>&nbsp;</u>　　일자 <u>&nbsp;</u></div></div>`;
    })()}
    <div class="f">본 리포트는 LexAide 심의 결과를 바탕으로 자동 생성된 규제 소명 자료입니다. AI는 위반 가능성을 적출·escalation 하며, 최종 판단·승인 권한은 준법관리자에게 있습니다. · 생성 ${ts}</div>
  </body></html>`;

  const w = window.open('', '_blank', 'width=920,height=1000');
  if (!w) { alert('팝업이 차단되었습니다. 팝업 허용 후 다시 시도하세요.'); return; }
  w.document.write(html); w.document.close();
}
document.addEventListener('click', (e) => {
  const rb = e.target.closest('[data-report-mode]');
  if (rb) reOpenReport(rb.dataset.reportMode);
});
