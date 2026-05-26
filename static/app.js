'use strict';

// State
let state = 'IDLE'; // IDLE | SEARCHED | SELECTED | GENERATED
let selectedLaw = null;
let generatedData = null; // { filename, content, char_count, article_count, is_split } or Blob (zip)
let generatedBlob = null;

// Elements
const searchInput = document.getElementById('search-input');
const searchBtn = document.getElementById('search-btn');
const errorBanner = document.getElementById('error-banner');
const sectionResults = document.getElementById('section-results');
const resultsBody = document.getElementById('results-body');
const sectionGenerate = document.getElementById('section-generate');
const selectedLawName = document.getElementById('selected-law-name');
const selectedLawNum = document.getElementById('selected-law-num');
const generateBtn = document.getElementById('generate-btn');
const generateStatus = document.getElementById('generate-status');
const sectionDownload = document.getElementById('section-download');
const statChars = document.getElementById('stat-chars');
const statArticles = document.getElementById('stat-articles');
const statFormat = document.getElementById('stat-format');
const previewArea = document.getElementById('preview-area');
const previewText = document.getElementById('preview-text');
const downloadBtn = document.getElementById('download-btn');
const resetBtn = document.getElementById('reset-btn');

// Init
loadQuickSelect();
searchBtn.addEventListener('click', () => doSearch(searchInput.value.trim()));
searchInput.addEventListener('keydown', (e) => {
  if (e.key === 'Enter') doSearch(searchInput.value.trim());
});
generateBtn.addEventListener('click', doGenerate);
downloadBtn.addEventListener('click', doDownload);
resetBtn.addEventListener('click', doReset);

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
  } catch (e) {
    // Quick select is non-critical; silently fail
  }
}

async function doSearch(query) {
  if (!query) return;
  hideError();
  searchBtn.disabled = true;
  searchBtn.textContent = '検索中…';

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
  results.forEach(law => {
    const tr = document.createElement('tr');
    tr.innerHTML = `
      <td><strong>${esc(law.law_title)}</strong></td>
      <td style="font-size:.82rem;color:#475569">${esc(law.law_num)}</td>
      <td><span style="font-size:.8rem">${esc(law.law_type)}</span></td>
      <td><button class="select-row-btn" data-id="${esc(law.law_id)}" data-title="${esc(law.law_title)}" data-num="${esc(law.law_num)}">選択</button></td>
    `;
    resultsBody.appendChild(tr);
  });

  resultsBody.querySelectorAll('.select-row-btn').forEach(btn => {
    btn.addEventListener('click', () => {
      selectLaw({
        law_id: btn.dataset.id,
        law_title: btn.dataset.title,
        law_num: btn.dataset.num,
      });
    });
  });
}

function selectLaw(law) {
  selectedLaw = law;
  selectedLawName.textContent = law.law_title;
  selectedLawNum.textContent = law.law_num;
  generateBtn.disabled = false;
  generateStatus.classList.add('hidden');
  generatedData = null;
  generatedBlob = null;
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
      // Large law returned as ZIP
      generatedBlob = await resp.blob();
      generatedData = {
        filename: _extractFilename(resp) || `${selectedLaw.law_title}.zip`,
        is_split: true,
        char_count: generatedBlob.size,
        article_count: null,
      };
    } else {
      const data = await resp.json();
      generatedData = data;
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
    // ZIP blob from server
    const url = URL.createObjectURL(generatedBlob);
    triggerDownload(url, generatedData.filename);
    URL.revokeObjectURL(url);
  } else if (generatedData.content) {
    // Markdown: build blob client-side
    const blob = new Blob([generatedData.content], { type: 'text/markdown;charset=utf-8' });
    const url = URL.createObjectURL(blob);
    triggerDownload(url, generatedData.filename);
    URL.revokeObjectURL(url);
  }
}

function triggerDownload(url, filename) {
  const a = document.createElement('a');
  a.href = url;
  a.download = filename;
  document.body.appendChild(a);
  a.click();
  document.body.removeChild(a);
}

function doReset() {
  selectedLaw = null;
  generatedData = null;
  generatedBlob = null;
  searchInput.value = '';
  document.querySelectorAll('.quick-btn').forEach(b => b.classList.remove('active'));
  setState('IDLE');
  hideError();
}

function setState(newState) {
  state = newState;
  sectionResults.classList.toggle('hidden', state === 'IDLE');
  sectionGenerate.classList.toggle('hidden', state === 'IDLE' || state === 'SEARCHED');
  sectionDownload.classList.toggle('hidden', state !== 'GENERATED');
}

function showError(msg) {
  errorBanner.textContent = `エラー: ${msg}`;
  errorBanner.classList.remove('hidden');
}
function hideError() {
  errorBanner.classList.add('hidden');
}

function _extractFilename(resp) {
  const cd = resp.headers.get('Content-Disposition') || '';
  const m = cd.match(/filename="?([^"]+)"?/);
  return m ? m[1] : null;
}

function esc(str) {
  return String(str)
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;');
}
