'use strict';

// ── State ──────────────────────────────────────────────────────────────────
let state = 'IDLE'; // IDLE | SEARCHED | SELECTED | GENERATED
let selectedLaw = null;
let generatedData = null;
let generatedBlob = null;

// Batch state
const batchSelected = new Map(); // law_id → LawSearchResult

// ── Elements ───────────────────────────────────────────────────────────────
const searchInput       = document.getElementById('search-input');
const searchBtn         = document.getElementById('search-btn');
const errorBanner       = document.getElementById('error-banner');
const sectionResults    = document.getElementById('section-results');
const resultsBody       = document.getElementById('results-body');
const checkAll          = document.getElementById('check-all');
const batchBar          = document.getElementById('batch-bar');
const batchCountLabel   = document.getElementById('batch-count-label');
const batchGenerateBtn  = document.getElementById('batch-generate-btn');
const sectionBatch      = document.getElementById('section-batch');
const batchProgressLabel= document.getElementById('batch-progress-label');
const batchProgressFrac = document.getElementById('batch-progress-fraction');
const progressBarFill   = document.getElementById('progress-bar-fill');
const batchProgressList = document.getElementById('batch-progress-list');
const sectionGenerate   = document.getElementById('section-generate');
const selectedLawName   = document.getElementById('selected-law-name');
const selectedLawNum    = document.getElementById('selected-law-num');
const generateBtn       = document.getElementById('generate-btn');
const generateStatus    = document.getElementById('generate-status');
const sectionDownload   = document.getElementById('section-download');
const statChars         = document.getElementById('stat-chars');
const statArticles      = document.getElementById('stat-articles');
const statFormat        = document.getElementById('stat-format');
const previewArea       = document.getElementById('preview-area');
const previewText       = document.getElementById('preview-text');
const downloadBtn       = document.getElementById('download-btn');
const resetBtn          = document.getElementById('reset-btn');

// Tsutatsu elements
const tsutatsuGrid     = document.getElementById('tsutatsu-grid');
const tsutatsuProgress = document.getElementById('tsutatsu-progress');
const tsutatsuLabel    = document.getElementById('tsutatsu-label');
const tsutatsuFrac     = document.getElementById('tsutatsu-frac');
const tsutatsuBarFill  = document.getElementById('tsutatsu-bar-fill');
const tsutatsuError    = document.getElementById('tsutatsu-error');

// TaxAnswer elements
const taxanswerGrid     = document.getElementById('taxanswer-grid');
const taxanswerProgress = document.getElementById('taxanswer-progress');
const taxanswerLabel    = document.getElementById('taxanswer-label');
const taxanswerFrac     = document.getElementById('taxanswer-frac');
const taxanswerBarFill  = document.getElementById('taxanswer-bar-fill');
const taxanswerError    = document.getElementById('taxanswer-error');

// ── Init ───────────────────────────────────────────────────────────────────
loadQuickSelect();
loadTsutatsuList();
loadTaxAnswerList();
searchBtn.addEventListener('click', () => doSearch(searchInput.value.trim()));
searchInput.addEventListener('keydown', (e) => { if (e.key === 'Enter') doSearch(searchInput.value.trim()); });
generateBtn.addEventListener('click', doGenerate);
downloadBtn.addEventListener('click', doDownload);
resetBtn.addEventListener('click', doReset);
batchGenerateBtn.addEventListener('click', doBatchGenerate);
checkAll.addEventListener('change', () => {
  document.querySelectorAll('.row-check').forEach(cb => {
    cb.checked = checkAll.checked;
    updateBatchFromCheckbox(cb);
  });
  refreshBatchBar();
});

// ── Quick select ───────────────────────────────────────────────────────────
async function loadQuickSelect() {
  try {
    const resp = await fetch('/api/quickselect');
    const laws = await resp.json();
    const container = document.getElementById('quick-select-buttons');
    laws.forEach(law => {
      const btn = document.createElement('button');
      btn.className = 'quick-btn';
      btn.textContent = law.law_title;
      btn.addEventListener('click', () => {
        document.querySelectorAll('.quick-btn').forEach(b => b.classList.remove('active'));
        btn.classList.add('active');
        searchInput.value = law.search_query;
        doSearch(law.search_query);
      });
      container.appendChild(btn);
    });
  } catch (_) {}
}

// ── 基本通達 ────────────────────────────────────────────────────────────────
async function loadTsutatsuList() {
  try {
    const resp = await fetch('/api/tsutatsu');
    const list = await resp.json();
    list.forEach(item => {
      const btn = document.createElement('button');
      btn.className = 'tsutatsu-btn';
      btn.dataset.key = item.key;
      btn.innerHTML = `<span class="tsutatsu-btn-title">${esc(item.title)}</span>`;
      btn.addEventListener('click', () => doFetchTsutatsu(item.key, item.title, btn));
      tsutatsuGrid.appendChild(btn);
    });
  } catch (_) {}
}

async function doFetchTsutatsu(key, title, clickedBtn) {
  // Hide previous error
  tsutatsuError.classList.add('hidden');

  // Disable all buttons
  document.querySelectorAll('.tsutatsu-btn').forEach(b => {
    b.disabled = true;
    b.classList.remove('active');
  });
  clickedBtn.classList.add('active');

  // Show progress
  tsutatsuProgress.classList.remove('hidden');
  tsutatsuLabel.textContent = `${title} を取得中…`;
  tsutatsuFrac.textContent = '';
  tsutatsuBarFill.style.width = '0%';
  tsutatsuProgress.scrollIntoView({ behavior: 'smooth', block: 'nearest' });

  return new Promise((resolve) => {
    const es = new EventSource(`/api/tsutatsu/${key}/stream`);
    let done = false;

    es.onmessage = async (e) => {
      let data;
      try { data = JSON.parse(e.data); } catch { return; }

      if (data.type === 'start') {
        tsutatsuFrac.textContent = `0 / ${data.total}`;
      } else if (data.type === 'progress') {
        const pct = data.total > 0 ? Math.min((data.done / data.total) * 90, 90) : 0;
        tsutatsuBarFill.style.width = `${pct}%`;
        tsutatsuFrac.textContent = `${data.done} / ${data.total}`;
        tsutatsuLabel.textContent = `${title} — ${data.section} を取得中`;

      } else if (data.type === 'done') {
        es.close();
        done = true;
        tsutatsuBarFill.style.width = '95%';
        tsutatsuLabel.textContent = '.mdをダウンロード中…';
        tsutatsuFrac.textContent = data.chars ? `${data.chars.toLocaleString()} 文字` : '';

        try {
          const dlResp = await fetch(`/api/tsutatsu/${key}/result/${data.job_id}`);
          if (!dlResp.ok) throw new Error(`ダウンロードエラー: HTTP ${dlResp.status}`);
          const blob = await dlResp.blob();
          const url = URL.createObjectURL(blob);
          triggerDownload(url, _extractFilenameRfc6266(dlResp) || `${title}.zip`);
          setTimeout(() => URL.revokeObjectURL(url), 15000);
        } catch (err) {
          tsutatsuError.textContent = `エラー: ${err.message}`;
          tsutatsuError.classList.remove('hidden');
        }

        tsutatsuBarFill.style.width = '100%';
        tsutatsuLabel.textContent = `完了: ${title}`;
        _resetTsutatsuButtons();
        resolve();

      } else if (data.type === 'error') {
        es.close();
        done = true;
        tsutatsuError.textContent = `エラー: ${data.message}`;
        tsutatsuError.classList.remove('hidden');
        tsutatsuProgress.classList.add('hidden');
        _resetTsutatsuButtons();
        resolve();
      }
    };

    es.onerror = () => {
      if (done) return;
      es.close();
      tsutatsuError.textContent = 'エラー: 通達の取得中に接続が切断されました';
      tsutatsuError.classList.remove('hidden');
      tsutatsuProgress.classList.add('hidden');
      _resetTsutatsuButtons();
      resolve();
    };
  });
}

function _resetTsutatsuButtons() {
  document.querySelectorAll('#tsutatsu-grid .tsutatsu-btn').forEach(b => {
    b.disabled = false;
    b.classList.remove('active');
  });
}

// ── タックスアンサー ──────────────────────────────────────────────────────────
async function loadTaxAnswerList() {
  try {
    const resp = await fetch('/api/taxanswer');
    const list = await resp.json();
    list.forEach(item => {
      const btn = document.createElement('button');
      btn.className = 'tsutatsu-btn';
      btn.dataset.key = item.key;
      btn.innerHTML = `<span class="tsutatsu-btn-title">${esc(item.title)}</span>`
                    + `<span style="font-size:.75rem;color:inherit;opacity:.75;margin-top:2px">${item.article_count}件</span>`;
      btn.addEventListener('click', () => doFetchTaxAnswer(item.key, item.title, btn));
      taxanswerGrid.appendChild(btn);
    });
  } catch (_) {}
}

async function doFetchTaxAnswer(key, title, clickedBtn) {
  taxanswerError.classList.add('hidden');

  document.querySelectorAll('#taxanswer-grid .tsutatsu-btn').forEach(b => {
    b.disabled = true;
    b.classList.remove('active');
  });
  clickedBtn.classList.add('active');

  taxanswerProgress.classList.remove('hidden');
  taxanswerLabel.textContent = `${title} を取得中…`;
  taxanswerFrac.textContent = '';
  taxanswerBarFill.style.width = '0%';
  taxanswerProgress.scrollIntoView({ behavior: 'smooth', block: 'nearest' });

  return new Promise((resolve) => {
    const es = new EventSource(`/api/taxanswer/${key}/stream`);
    let done = false;

    es.onmessage = async (e) => {
      let data;
      try { data = JSON.parse(e.data); } catch { return; }

      if (data.type === 'start') {
        taxanswerFrac.textContent = `0 / ${data.total}`;
      } else if (data.type === 'progress') {
        const pct = data.total > 0 ? Math.min((data.done / data.total) * 90, 90) : 0;
        taxanswerBarFill.style.width = `${pct}%`;
        taxanswerFrac.textContent = `${data.done} / ${data.total}`;
        taxanswerLabel.textContent = `${title} — No.${data.article} を取得中`;

      } else if (data.type === 'done') {
        es.close();
        done = true;
        taxanswerBarFill.style.width = '95%';
        taxanswerLabel.textContent = '.mdをダウンロード中…';
        taxanswerFrac.textContent = data.chars ? `${data.chars.toLocaleString()} 文字 / ${data.article_count}件` : '';

        try {
          const dlResp = await fetch(`/api/taxanswer/${key}/result/${data.job_id}`);
          if (!dlResp.ok) throw new Error(`ダウンロードエラー: HTTP ${dlResp.status}`);
          const blob = await dlResp.blob();
          const url = URL.createObjectURL(blob);
          triggerDownload(url, _extractFilenameRfc6266(dlResp) || `タックスアンサー_${title}.md`);
          setTimeout(() => URL.revokeObjectURL(url), 15000);
        } catch (err) {
          taxanswerError.textContent = `エラー: ${err.message}`;
          taxanswerError.classList.remove('hidden');
        }

        taxanswerBarFill.style.width = '100%';
        taxanswerLabel.textContent = `完了: ${title}`;
        _resetTaxAnswerButtons();
        resolve();

      } else if (data.type === 'error') {
        es.close();
        done = true;
        taxanswerError.textContent = `エラー: ${data.message}`;
        taxanswerError.classList.remove('hidden');
        taxanswerProgress.classList.add('hidden');
        _resetTaxAnswerButtons();
        resolve();
      }
    };

    es.onerror = () => {
      if (done) return;
      es.close();
      taxanswerError.textContent = 'エラー: タックスアンサーの取得中に接続が切断されました';
      taxanswerError.classList.remove('hidden');
      taxanswerProgress.classList.add('hidden');
      _resetTaxAnswerButtons();
      resolve();
    };
  });
}

function _resetTaxAnswerButtons() {
  document.querySelectorAll('#taxanswer-grid .tsutatsu-btn').forEach(b => {
    b.disabled = false;
    b.classList.remove('active');
  });
}

// RFC 6266 / RFC 5987 filename extraction
function _extractFilenameRfc6266(resp) {
  const cd = resp.headers.get('Content-Disposition') || '';
  // Try filename*=UTF-8''encoded first
  const m6266 = cd.match(/filename\*=UTF-8''([^\s;]+)/i);
  if (m6266) return decodeURIComponent(m6266[1]);
  // Fallback to filename="..."
  const mPlain = cd.match(/filename="?([^";]+)"?/i);
  return mPlain ? mPlain[1] : null;
}

// ── Search ─────────────────────────────────────────────────────────────────
async function doSearch(query) {
  if (!query) return;
  hideError();
  searchBtn.disabled = true;
  searchBtn.textContent = '検索中…';
  batchSelected.clear();
  refreshBatchBar();

  try {
    const resp = await fetch(`/api/search?q=${encodeURIComponent(query)}`);
    if (!resp.ok) {
      const err = await resp.json().catch(() => ({}));
      throw new Error(err.detail || `HTTPエラー ${resp.status}`);
    }
    const results = await resp.json();
    renderResults(results);
    setState('SEARCHED');
  } catch (e) {
    showError(e.message);
  } finally {
    searchBtn.disabled = false;
    searchBtn.textContent = '検索';
  }
}

function renderResults(results) {
  resultsBody.innerHTML = '';
  checkAll.checked = false;

  results.forEach(law => {
    const tr = document.createElement('tr');
    tr.innerHTML = `
      <td class="col-check">
        <input type="checkbox" class="row-check"
          data-id="${esc(law.law_id)}"
          data-title="${esc(law.law_title)}"
          data-num="${esc(law.law_num)}"
          data-type="${esc(law.law_type)}">
      </td>
      <td><strong>${esc(law.law_title)}</strong></td>
      <td style="font-size:.82rem;color:#475569">${esc(law.law_num)}</td>
      <td><span style="font-size:.8rem">${esc(law.law_type)}</span></td>
      <td><button class="select-row-btn"
            data-id="${esc(law.law_id)}"
            data-title="${esc(law.law_title)}"
            data-num="${esc(law.law_num)}">選択</button></td>
    `;
    resultsBody.appendChild(tr);
  });

  // Single-select buttons
  resultsBody.querySelectorAll('.select-row-btn').forEach(btn => {
    btn.addEventListener('click', () => selectLaw({
      law_id: btn.dataset.id,
      law_title: btn.dataset.title,
      law_num: btn.dataset.num,
    }));
  });

  // Batch checkboxes
  resultsBody.querySelectorAll('.row-check').forEach(cb => {
    cb.addEventListener('change', () => {
      updateBatchFromCheckbox(cb);
      refreshBatchBar();
      const all = resultsBody.querySelectorAll('.row-check');
      checkAll.checked = [...all].every(c => c.checked);
    });
  });
}

function updateBatchFromCheckbox(cb) {
  if (cb.checked) {
    batchSelected.set(cb.dataset.id, {
      law_id: cb.dataset.id,
      law_title: cb.dataset.title,
      law_num: cb.dataset.num,
      law_type: cb.dataset.type,
    });
  } else {
    batchSelected.delete(cb.dataset.id);
  }
}

function refreshBatchBar() {
  const count = batchSelected.size;
  if (count >= 1) {
    batchCountLabel.textContent = `${count}件選択中`;
    batchBar.classList.remove('hidden');
  } else {
    batchBar.classList.add('hidden');
  }
}

// ── Single-law flow ────────────────────────────────────────────────────────
function selectLaw(law) {
  selectedLaw = law;
  selectedLawName.textContent = law.law_title;
  selectedLawNum.textContent = law.law_num;
  generateBtn.disabled = false;
  generateStatus.classList.add('hidden');
  generatedData = null;
  generatedBlob = null;
  sectionDownload.classList.add('hidden');
  sectionBatch.classList.add('hidden');
  setState('SELECTED');
}

async function doGenerate() {
  if (!selectedLaw) return;
  hideError();
  generateBtn.disabled = true;
  generateStatus.classList.remove('hidden');
  sectionDownload.classList.add('hidden');

  try {
    const resp = await fetch(`/api/law/${encodeURIComponent(selectedLaw.law_id)}/markdown`);
    if (!resp.ok) {
      const err = await resp.json().catch(() => ({}));
      throw new Error(err.detail || `HTTPエラー ${resp.status}`);
    }
    const contentType = resp.headers.get('Content-Type') || '';
    if (contentType.includes('application/zip')) {
      generatedBlob = await resp.blob();
      generatedData = {
        filename: _extractFilenameRfc6266(resp) || `${selectedLaw.law_title}.zip`,
        is_split: true,
        char_count: generatedBlob.size,
        article_count: null,
      };
    } else {
      generatedData = await resp.json();
      generatedBlob = null;
    }
    renderDownload();
    setState('GENERATED');
  } catch (e) {
    showError(e.message);
  } finally {
    generateBtn.disabled = false;
    generateStatus.classList.add('hidden');
  }
}

function renderDownload() {
  const d = generatedData;
  if (d.is_split) {
    statChars.textContent = `${(d.char_count / 1024).toFixed(0)} KB`;
    statArticles.textContent = '—';
    statFormat.textContent = 'ZIP（章分割）';
    previewArea.classList.add('hidden');
    downloadBtn.textContent = 'ZIPをダウンロード';
  } else {
    statChars.textContent = d.char_count.toLocaleString() + ' 文字';
    statArticles.textContent = d.article_count.toLocaleString() + ' 条';
    statFormat.textContent = 'Markdown (.md)';
    previewText.value = d.content.slice(0, 500);
    previewArea.classList.remove('hidden');
    downloadBtn.textContent = '.mdファイルをダウンロード';
  }
}

function doDownload() {
  if (!generatedData) return;
  if (generatedData.is_split && generatedBlob) {
    const url = URL.createObjectURL(generatedBlob);
    triggerDownload(url, generatedData.filename);
    URL.revokeObjectURL(url);
  } else if (generatedData.content) {
    const blob = new Blob([generatedData.content], { type: 'text/markdown;charset=utf-8' });
    const url = URL.createObjectURL(blob);
    triggerDownload(url, generatedData.filename);
    URL.revokeObjectURL(url);
  }
}

// ── Batch flow ─────────────────────────────────────────────────────────────
async function doBatchGenerate() {
  const laws = [...batchSelected.values()];
  if (laws.length === 0) return;

  hideError();
  batchGenerateBtn.disabled = true;
  sectionBatch.classList.remove('hidden');
  sectionDownload.classList.add('hidden');
  sectionBatch.scrollIntoView({ behavior: 'smooth' });

  // Init progress UI
  batchProgressList.innerHTML = '';
  const listItems = laws.map(law => {
    const li = document.createElement('li');
    li.id = `batch-li-${law.law_id}`;
    li.innerHTML = `<span class="batch-status-icon">○</span>${esc(law.law_title)}`;
    batchProgressList.appendChild(li);
    return li;
  });

  const collectedFiles = [];
  let successCount = 0;

  for (let i = 0; i < laws.length; i++) {
    const law = laws[i];
    const li = listItems[i];

    li.className = 'processing';
    li.querySelector('.batch-status-icon').textContent = '▶';
    batchProgressLabel.textContent = `取得中: ${law.law_title}`;
    batchProgressFrac.textContent = `${i + 1} / ${laws.length}`;
    progressBarFill.style.width = `${(i / laws.length) * 100}%`;

    try {
      const resp = await fetch(`/api/law/${encodeURIComponent(law.law_id)}/markdown`);
      if (!resp.ok) {
        const err = await resp.json().catch(() => ({}));
        throw new Error(err.detail || `HTTP ${resp.status}`);
      }

      const contentType = resp.headers.get('Content-Type') || '';
      if (contentType.includes('application/zip')) {
        const blob = await resp.blob();
        const innerZip = await JSZip.loadAsync(blob);
        for (const [fname, file] of Object.entries(innerZip.files)) {
          if (!file.dir) {
            const content = await file.async('string');
            collectedFiles.push({ filename: fname, content });
          }
        }
      } else {
        const data = await resp.json();
        collectedFiles.push({ filename: data.filename, content: data.content });
      }

      li.className = 'done';
      li.querySelector('.batch-status-icon').textContent = '✓';
      successCount++;
    } catch (e) {
      li.className = 'error';
      li.querySelector('.batch-status-icon').textContent = '✗';
      li.append(` — ${e.message}`);
    }
  }

  if (successCount === 0) {
    batchProgressLabel.textContent = 'エラー: すべての法令の取得に失敗しました';
    batchProgressFrac.textContent = '';
    batchGenerateBtn.disabled = false;
    return;
  }

  batchProgressLabel.textContent = 'ZIPを作成中…';
  batchProgressFrac.textContent = '';
  progressBarFill.style.width = '95%';

  try {
    const bundleResp = await fetch('/api/bundle', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(collectedFiles),
    });
    if (!bundleResp.ok) throw new Error(`ZIP作成エラー: HTTP ${bundleResp.status}`);
    const zipBlob = await bundleResp.blob();
    const url = URL.createObjectURL(zipBlob);
    triggerDownload(url, _extractFilenameRfc6266(bundleResp) || '税法_NotebookLM用.zip');
    setTimeout(() => URL.revokeObjectURL(url), 10000);
  } catch (e) {
    showError(e.message);
  }

  progressBarFill.style.width = '100%';
  batchProgressLabel.textContent = `完了 (${successCount} / ${laws.length} 件成功)`;
  batchGenerateBtn.disabled = false;
}

// ── Reset ──────────────────────────────────────────────────────────────────
function doReset() {
  selectedLaw = null;
  generatedData = null;
  generatedBlob = null;
  batchSelected.clear();
  checkAll.checked = false;
  searchInput.value = '';
  document.querySelectorAll('.quick-btn').forEach(b => b.classList.remove('active'));
  refreshBatchBar();
  sectionBatch.classList.add('hidden');
  setState('IDLE');
  hideError();
}

// ── State machine ──────────────────────────────────────────────────────────
function setState(newState) {
  state = newState;
  sectionResults.classList.toggle('hidden', state === 'IDLE');
  sectionGenerate.classList.toggle('hidden', state === 'IDLE' || state === 'SEARCHED');
  sectionDownload.classList.toggle('hidden', state !== 'GENERATED');
}

// ── Utilities ──────────────────────────────────────────────────────────────
function showError(msg) {
  errorBanner.textContent = `エラー: ${msg}`;
  errorBanner.classList.remove('hidden');
}
function hideError() {
  errorBanner.classList.add('hidden');
}
function triggerDownload(url, filename) {
  const a = Object.assign(document.createElement('a'), { href: url, download: filename });
  document.body.appendChild(a);
  a.click();
  document.body.removeChild(a);
}
function _extractFilename(resp) {
  return _extractFilenameRfc6266(resp);
}
function esc(str) {
  return String(str)
    .replace(/&/g, '&amp;').replace(/</g, '&lt;')
    .replace(/>/g, '&gt;').replace(/"/g, '&quot;');
}
