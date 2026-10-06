import React, { useCallback, useEffect, useRef, useState } from 'react';
import AppShell from './components/AppShell.jsx';
import UploadScreen from './components/UploadScreen.jsx';
import PreviewScreen from './components/PreviewScreen.jsx';
import ProcessingScreen from './components/ProcessingScreen.jsx';
import ResultsScreen from './components/ResultsScreen.jsx';
import { HomeScreen, HistoryScreen, SettingsScreen } from './components/StaticScreens.jsx';
import { apiDownload, apiFetch } from './api.js';

const POLL_MS = 2000;

function previewFields(category) {
  return [
    ...category.input_fields.map((f) => f.name),
    ...(category.fixed_sites ? [] : ['target_website']),
    ...(category.allowed_countries ? [] : ['country']),
  ];
}

function previewColumns(category) {
  return [
    ...category.input_fields.map((f) => f.label),
    ...(category.fixed_sites ? [] : ['Target Website']),
    ...(category.allowed_countries ? [] : ['Country']),
  ];
}

function toPreview(file, category, data) {
  const fields = previewFields(category);
  return {
    filename: file.name,
    size_bytes: file.size,
    columns: previewColumns(category),
    rows: data.preview_rows.map((r) => fields.map((f) => r[f] || '')),
    total_rows: data.row_count,
    usable_rows: data.row_count,
    warnings: [...(data.errors || []), ...(data.row_errors || [])],
  };
}

function buildStages(data) {
  // "in_progress" (spinner) as soon as the job is running - don't wait for
  // the first row to finish before showing activity.
  const state = data.status === 'done' || data.status === 'error'
    ? 'completed'
    : data.status === 'running' ? 'in_progress' : 'pending';
  return [{ key: 'search', label: 'Searching the web', state, done: data.processed, total: data.total }];
}

function toJob(data) {
  return {
    id: data.id,
    category: data.category,
    total: data.total,
    completed: data.processed,
    status: data.status,
    error: data.error,
    rows: data.rows,
    stages: buildStages(data),
  };
}

export default function App() {
  const [categories, setCategories] = useState([]);
  const [category, setCategory] = useState(null);
  const [screen, setScreen] = useState('upload');
  const [health, setHealth] = useState(null);
  const [file, setFile] = useState(null);
  const [preview, setPreview] = useState(null);
  const [job, setJob] = useState(null);
  const [error, setError] = useState(null);
  const [busy, setBusy] = useState(false);
  const [starting, setStarting] = useState(false);
  const pollRef = useRef(null);

  useEffect(() => {
    fetch('/api/health').then((r) => r.json()).then(setHealth).catch(() => setHealth(null));
    fetch('/api/categories').then((r) => r.json()).then((list) => {
      setCategories(list);
      if (list.length) setCategory(list[0]);
    }).catch(() => setCategories([]));
    return () => clearInterval(pollRef.current);
  }, []);

  const poll = useCallback((id) => {
    clearInterval(pollRef.current);
    const tick = async () => {
      try {
        const res = await apiFetch(`/api/batch/jobs/${id}`);
        if (!res.ok) throw new Error('Lost track of that job.');
        const data = await res.json();
        setJob(toJob(data));
        if (data.status === 'done' || data.status === 'error') {
          clearInterval(pollRef.current);
          setScreen('results');
        }
      } catch (e) {
        clearInterval(pollRef.current);
        setError(e.message);
      }
    };
    tick();
    pollRef.current = setInterval(tick, POLL_MS);
  }, []);

  const handleFile = async (picked) => {
    setError(null);
    setBusy(true);
    const form = new FormData();
    form.append('file', picked);
    try {
      const res = await apiFetch(`/api/batch/preview?category=${category.key}`, { method: 'POST', body: form });
      const data = await res.json();
      if (!res.ok) throw new Error(data.detail || 'Could not read that file.');
      setFile(picked);
      setPreview(toPreview(picked, category, data));
      setScreen('preview');
    } catch (e) {
      setError(e.message);
    } finally {
      setBusy(false);
    }
  };

  const startExtraction = async () => {
    if (!file) return;
    setStarting(true);
    setError(null);
    const form = new FormData();
    form.append('file', file);
    try {
      const res = await apiFetch(`/api/batch/jobs?category=${category.key}`, { method: 'POST', body: form });
      const data = await res.json();
      if (!res.ok) throw new Error(data.detail || 'Could not start the extraction.');
      setJob({
        id: data.job_id,
        category: category.key,
        total: data.total,
        completed: 0,
        status: 'running',
        rows: [],
        stages: buildStages({ status: 'running', processed: 0, total: data.total }),
      });
      setScreen('processing');
      poll(data.job_id);
    } catch (e) {
      setError(e.message);
    } finally {
      setStarting(false);
    }
  };

  const openJob = (id, jobCategory) => {
    clearInterval(pollRef.current);
    const cat = categories.find((c) => c.key === jobCategory);
    if (cat) setCategory(cat);
    apiFetch(`/api/batch/jobs/${id}`)
      .then((r) => {
        if (!r.ok) throw new Error();
        return r.json();
      })
      .then((data) => {
        setJob(toJob(data));
        if (data.status === 'done' || data.status === 'error') setScreen('results');
        else { setScreen('processing'); poll(id); }
      })
      .catch(() => setError('Could not open that run.'));
  };

  const reset = () => {
    setFile(null);
    setPreview(null);
    setError(null);
    setScreen('upload');
  };

  const exportExcel = () => {
    if (!job) return;
    apiDownload(`/api/batch/jobs/${job.id}/export`, `${job.category}_results_${job.id.slice(0, 8)}.xlsx`)
      .catch((e) => setError(e.message));
  };

  const navigate = (key) => {
    if (key === 'upload') reset();
    else setScreen(key);
  };

  const changeCategory = (key) => {
    const cat = categories.find((c) => c.key === key);
    if (cat) setCategory(cat);
    reset();
  };

  if (!category) {
    return <div className="shell"><div className="canvas page">Loading…</div></div>;
  }

  const render = () => {
    switch (screen) {
      case 'home':
        return <HomeScreen health={health} category={category} onStart={reset} />;
      case 'preview':
        return (
          <PreviewScreen
            preview={preview}
            onBack={reset}
            onContinue={startExtraction}
            starting={starting}
          />
        );
      case 'processing':
        return <ProcessingScreen job={job} />;
      case 'results':
        return <ResultsScreen category={category} job={job} onExport={exportExcel} />;
      case 'history':
        return <HistoryScreen onOpen={openJob} />;
      case 'settings':
        return <SettingsScreen health={health} categories={categories} />;
      default:
        return <UploadScreen category={category} onFile={handleFile} busy={busy} error={error} />;
    }
  };

  return (
    <AppShell
      screen={screen}
      onNavigate={navigate}
      canProcess={!!job}
      canResults={!!job && job.completed > 0}
      categories={categories}
      category={category}
      onCategoryChange={changeCategory}
    >
      {error && screen !== 'upload' && <div className="alert error">{error}</div>}
      {render()}
    </AppShell>
  );
}
