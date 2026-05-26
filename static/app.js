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

// ── Init ───────────────────────────────────────────────────────────────────
loadQuickSelect();
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
      // Sync check-all state
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
        filename: _extractFilename(resp) || `${selectedLaw.law_title}.zip`,
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

  const zip = new JSZip();
  let successCount = 0;

  for (let i = 0; i < laws.length; i++) {
    const law = laws[i];
    const li = listItems[i];

    // Update progress
    li.className = 'processing';
    li.querySelector('.batch-status-icon').textContent = '▶';
    batchProgressLabel.textContent = `処理中: ${law.law_title}`;
    batchProgressFrac.textContent = `${i + 1} / ${laws.length}`;
    progressBarFill.style.width = `${((i) / laws.length) * 100}%`;

    try {
      const resp = await fetch(`/api/law/${encodeURIComponent(law.law_id)}/markdown`);
      if (!resp.ok) {
        const err = await resp.json().catch(() => ({}));
        throw new Error(err.detail || `HTTP ${resp.status}`);
      }

      const contentType = resp.headers.get('Content-Type') || '';
      if (contentType.includes('application/zip')) {
        // Large law returned as ZIP — extract and re-add to our ZIP
        const blob = await resp.blob();
        const innerZip = await JSZip.loadAsync(blob);
        for (const [fname, file] of Object.entries(innerZip.files)) {
          const content = await file.async('string');
          zip.file(fname, content);
        }
      } else {
        const data = await resp.json();
        zip.file(data.filename, data.content);
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

  progressBarFill.style.width = '100%';
  batchProgressLabel.textContent = `完了 (${successCount} / ${laws.length} 件成功)`;
  batchProgressFrac.textContent = '';
  batchGenerateBtn.disabled = false;

  if (successCount === 0) return;

  // Bundle and download
  const today = new Date().toISOString().slice(0, 10).replace(/-/g, '');
  const zipBlob = await zip.generateAsync({ type: 'blob', compression: 'DEFLATE' });
  const url = URL.createObjectURL(zipBlob);
  triggerDownload(url, `税法_NotebookLM用_${today}.zip`);
  URL.revokeObjectURL(url);
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
  const cd = resp.headers.get('Content-Disposition') || '';
  const m = cd.match(/filename="?([^"]+)"?/);
  return m ? m[1] : null;
}
function esc(str) {
  return String(str)
    .replace(/&/g, '&amp;').replace(/</g, '&lt;')
    .replace(/>/g, '&gt;').replace(/"/g, '&quot;');
}
