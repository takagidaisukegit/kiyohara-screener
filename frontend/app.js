'use strict';

const API_BASE = '';  // 同一オリジン（FastAPIが静的ファイルも配信）

let currentData = [];
let sortCol = 'net_cash_ratio';
let sortAsc = false;

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

  try {
    const res = await fetch(`${API_BASE}/api/screen`);

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

  const ncrClass = s.net_cash_ratio >= 1.5 ? 'ncr-high' : s.net_cash_ratio >= 1.0 ? 'ncr-mid' : 'ncr-low';
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
      <td class="td-ncr"><span class="${ncrClass}">${s.net_cash_ratio.toFixed(2)}</span></td>
      <td class="td-nc">${ncStr}</td>
      <td class="td-pbr"><span class="${pbrClass}">${s.pbr.toFixed(2)}x</span></td>
      <td class="td-per"><span class="${perClass}">${s.per.toFixed(1)}x</span></td>
      <td class="td-cap">${capStr}</td>
      <td class="td-div"><span class="${divClass}">${divStr}</span></td>
      <td class="td-links">${linkHtml}</td>
    </tr>`;
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
