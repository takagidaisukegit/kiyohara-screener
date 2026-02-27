'use strict';

const API_BASE = '';  // 同一オリジン（FastAPIが静的ファイルも配信）

let currentData = [];
let sortCol = 'net_cash_ratio';
let sortAsc = false;
let defaultCriteria = {};

// ===== 起動時: デフォルト基準を取得してフォームに反映 =====
async function loadCriteria() {
  try {
    const res = await fetch(`${API_BASE}/api/criteria`);
    if (res.ok) {
      defaultCriteria = await res.json();
      applyCriteriaToForm(defaultCriteria);
      updateBadges(defaultCriteria);
    }
  } catch (e) {
    // サーバー未起動時は無視
  }
}

function applyCriteriaToForm(c) {
  document.getElementById('cfgNcr').value    = c.net_cash_ratio_min ?? 0.5;
  document.getElementById('cfgCapMin').value = c.market_cap_min_oku ?? 50;
  document.getElementById('cfgCapMax').value = c.market_cap_max_oku ?? 1000;
  document.getElementById('cfgPbr').value    = c.pbr_max ?? 1.0;
  document.getElementById('cfgPer').value    = c.per_max ?? 20;
  document.getElementById('cfgTopN').value   = c.top_n ?? 20;
}

function collectCriteria() {
  return {
    net_cash_ratio_min: parseFloat(document.getElementById('cfgNcr').value),
    market_cap_min_oku: parseFloat(document.getElementById('cfgCapMin').value),
    market_cap_max_oku: parseFloat(document.getElementById('cfgCapMax').value),
    pbr_max:            parseFloat(document.getElementById('cfgPbr').value),
    per_max:            parseFloat(document.getElementById('cfgPer').value),
    top_n:              parseInt(document.getElementById('cfgTopN').value),
  };
}

function resetCriteria() {
  applyCriteriaToForm(defaultCriteria);
  updateBadges(defaultCriteria);
}

function toggleSettings() {
  const panel = document.getElementById('settingsPanel');
  const btn   = document.getElementById('btnSettings');
  const open  = panel.style.display === 'none' || panel.style.display === '';
  if (open && panel.style.display === 'none') {
    panel.style.display = '';
    btn.textContent = '✕ 閉じる';
  } else {
    panel.style.display = 'none';
    btn.textContent = '⚙ 基準を変更';
  }
}

function updateBadges(c) {
  const el = (id) => document.getElementById(id);
  if (!c) return;
  el('badgeNcr').textContent  = `ネットキャッシュ比率 ≥ ${c.net_cash_ratio_min}`;
  el('badgeCap').textContent  = `時価総額 ${c.market_cap_min_oku}〜${c.market_cap_max_oku}億円`;
  el('badgePbr').textContent  = `PBR ≤ ${c.pbr_max}倍`;
  el('badgePer').textContent  = `PER ≤ ${c.per_max}倍`;
  el('badgeTopN').textContent = `上位${c.top_n}社表示`;
}

// ===== メイン: スクリーニング実行 =====
async function runScreening() {
  const btn = document.getElementById('btnScreen');
  btn.disabled = true;
  btn.innerHTML = '<span class="btn-icon">⏳</span>実行中...';

  hideElement('emptyState');
  hideElement('tableWrap');
  hideElement('errorBox');
  hideElement('statsRow');
  showElement('loader');

  const c = collectCriteria();
  updateBadges(c);

  const params = new URLSearchParams({
    net_cash_ratio_min: c.net_cash_ratio_min,
    market_cap_min_oku: c.market_cap_min_oku,
    market_cap_max_oku: c.market_cap_max_oku,
    pbr_max:            c.pbr_max,
    per_max:            c.per_max,
    top_n:              c.top_n,
  });

  try {
    const res = await fetch(`${API_BASE}/api/screen?${params}`);

    if (res.status === 429) {
      showError('スクリーニングが既に実行中です。しばらくお待ちください。');
      return;
    }
    if (!res.ok) {
      const err = await res.json().catch(() => ({ detail: res.statusText }));
      showError(`エラー (${res.status}): ${err.detail || res.statusText}`);
      return;
    }

    const data = await res.json();
    currentData = data.stocks || [];
    sortCol = 'net_cash_ratio';
    sortAsc = false;

    renderStats(data);
    renderTable(currentData);
    loadCatalysts(currentData);  // スクリーニング結果が出た後、非同期でカタリスト分析

    document.getElementById('lastUpdated').textContent = `最終更新: ${data.updated_at}`;

  } catch (e) {
    showError(`通信エラー: ${e.message}\n\nバックエンドが起動しているか確認してください。`);
  } finally {
    hideElement('loader');
    btn.disabled = false;
    btn.innerHTML = '<span class="btn-icon">▶</span>スクリーニング実行';
  }
}

// ===== 統計カード =====
function renderStats(data) {
  document.getElementById('statScreened').textContent = data.total_screened?.toLocaleString() ?? '—';
  document.getElementById('statPassed').textContent   = data.total_passed?.toLocaleString() ?? '—';
  document.getElementById('statShown').textContent    = data.stocks?.length ?? '—';
  const rate = data.total_screened > 0
    ? ((data.total_passed / data.total_screened) * 100).toFixed(1) + '%'
    : '—';
  document.getElementById('statPassRate').textContent = rate;
  showElement('statsRow');
}

// ===== テーブル描画 =====
function renderTable(stocks) {
  const tbody = document.getElementById('stockTableBody');
  document.getElementById('resultCount').textContent = stocks.length;

  if (stocks.length === 0) {
    tbody.innerHTML = '<tr><td colspan="12" style="text-align:center;padding:40px;color:var(--text-sub)">基準を満たす銘柄が見つかりませんでした</td></tr>';
    showElement('tableWrap');
    hideElement('emptyState');
    return;
  }

  tbody.innerHTML = stocks.map((s, i) => buildRow(s, i)).join('');

  // ソートアイコン更新
  document.querySelectorAll('.stock-table th').forEach(th => {
    const col = th.dataset.col;
    if (!col) return;
    const icon = th.querySelector('.sort-icon');
    if (!icon) return;
    if (col === sortCol) {
      th.classList.add('sort-active');
      icon.textContent = sortAsc ? '▲' : '▼';
    } else {
      th.classList.remove('sort-active');
      icon.textContent = '⇅';
    }
  });

  showElement('tableWrap');
  hideElement('emptyState');
}

function buildRow(s, index) {
  const rank = index + 1;
  const medal = rank === 1 ? '🥇' : rank === 2 ? '🥈' : rank === 3 ? '🥉' : rank;
  const rankHtml = rank <= 3 ? `<span class="rank-medal">${medal}</span>` : rank;

  const ncr = s.net_cash_ratio;
  const ncrClass = ncr === null ? '' : ncr >= 1.5 ? 'ncr-high' : ncr >= 1.0 ? 'ncr-mid' : 'ncr-low';
  const ncrText  = ncr === null ? '<span style="color:var(--text-dim)">N/A</span>' : `<span class="${ncrClass}">${ncr.toFixed(2)}</span>`;
  const pbrClass = s.pbr <= 0.4 ? 'pbr-vlow' : s.pbr <= 0.7 ? 'pbr-low' : 'pbr-mid';
  const perClass = s.per <= 10 ? 'per-low' : 'per-mid';
  const divClass = s.dividend_yield >= 4 ? 'div-high' : s.dividend_yield >= 2.5 ? 'div-mid' : '';

  const links = s.chart_links || {};
  const linkHtml = `
    <div class="chart-links">
      ${links.minkabu ? `<a class="chart-link link-minkabu" href="${links.minkabu}" target="_blank" rel="noopener">みんかぶ</a>` : ''}
      ${links.kabutan ? `<a class="chart-link link-kabutan" href="${links.kabutan}" target="_blank" rel="noopener">株探</a>` : ''}
      ${links.yahoo   ? `<a class="chart-link link-yahoo"   href="${links.yahoo}"   target="_blank" rel="noopener">Yahoo</a>` : ''}
      ${links.buffett ? `<a class="chart-link link-buffett" href="${links.buffett}" target="_blank" rel="noopener">B-Code</a>` : ''}
      ${links.irbank  ? `<a class="chart-link link-irbank"  href="${links.irbank}"  target="_blank" rel="noopener">IRBank</a>` : ''}
    </div>`;

  const price = s.price ? `¥${Number(s.price).toLocaleString()}` : '—';
  const capStr = s.market_cap_oku ? `${s.market_cap_oku.toLocaleString()}億` : '—';
  const divStr = s.dividend_yield > 0 ? `${s.dividend_yield}%` : '—';
  const ncStr  = s.net_cash_oku != null ? `${s.net_cash_oku.toLocaleString()}億` : '—';

  return `
    <tr>
      <td class="td-rank">${rankHtml}</td>
      <td class="td-code">
        <a href="${links.minkabu || '#'}" target="_blank" rel="noopener">${s.code}</a>
      </td>
      <td class="td-name">
        <span class="stock-name">${escHtml(s.name)}</span>
      </td>
      <td class="td-sector"><span class="sector-tag">${escHtml(s.sector)}</span></td>
      <td class="td-price">${price}</td>
      <td class="td-ncr">${ncrText}</td>
      <td class="td-nc">${ncStr}</td>
      <td class="td-pbr"><span class="${pbrClass}">${s.pbr.toFixed(2)}x</span></td>
      <td class="td-per"><span class="${perClass}">${s.per.toFixed(1)}x</span></td>
      <td class="td-cap">${capStr}</td>
      <td class="td-div"><span class="${divClass}">${divStr}</span></td>
      <td class="td-catalyst" id="catalyst-${s.code}">
        <span class="catalyst-loading">分析中...</span>
      </td>
      <td class="td-links">${linkHtml}</td>
    </tr>`;
}

// ===== カタリスト非同期ロード =====

/**
 * スクリーニング結果の全銘柄に対してカタリスト分析を並列リクエストし、
 * 各セルを受信し次第更新する。
 */
function loadCatalysts(stocks) {
  stocks.forEach(s => {
    fetchOneCatalyst(s.code);
  });
}

async function fetchOneCatalyst(code) {
  const cell = document.getElementById(`catalyst-${code}`);
  if (!cell) return;
  try {
    const res = await fetch(`${API_BASE}/api/catalyst/${encodeURIComponent(code)}`);
    if (!res.ok) {
      cell.innerHTML = '<span class="catalyst-none">—</span>';
      return;
    }
    const data = await res.json();
    const text = data.catalyst || '—';
    if (text === '明確なカタリストなし' || text === '—') {
      cell.innerHTML = `<span class="catalyst-none">${escHtml(text)}</span>`;
    } else {
      cell.innerHTML = `<span class="catalyst-text">${escHtml(text)}</span>`;
    }
  } catch (e) {
    cell.innerHTML = '<span class="catalyst-none">—</span>';
  }
}

// ===== ソート =====
function sortTable(col) {
  if (sortCol === col) {
    sortAsc = !sortAsc;
  } else {
    sortCol = col;
    sortAsc = col === 'pbr' || col === 'per';  // PBR/PERは昇順デフォルト
  }

  const sorted = [...currentData].sort((a, b) => {
    const av = a[col] ?? 0;
    const bv = b[col] ?? 0;
    return sortAsc ? av - bv : bv - av;
  });

  renderTable(sorted);
}

// ===== ユーティリティ =====
function showElement(id) { const el = document.getElementById(id); if (el) el.style.display = ''; }
function hideElement(id)  { const el = document.getElementById(id); if (el) el.style.display = 'none'; }

function showError(msg) {
  hideElement('loader');
  const box = document.getElementById('errorBox');
  box.textContent = msg;
  showElement('errorBox');
  showElement('emptyState');
}

function escHtml(str) {
  if (!str) return '';
  return String(str)
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;');
}

// ===== 初期化 =====
loadCriteria();
