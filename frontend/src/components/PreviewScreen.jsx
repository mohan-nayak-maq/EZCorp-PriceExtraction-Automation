import React from 'react';
import StepHeader from './StepHeader.jsx';
import * as Icon from './icons.jsx';

function formatSize(bytes) {
  if (!bytes && bytes !== 0) return '';
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${Math.round(bytes / 1024)} KB`;
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
}

export default function PreviewScreen({ preview, onBack, onContinue, starting }) {
  const { columns = [], rows = [], total_rows: total = 0, warnings = [] } = preview;

  return (
    <div className="page">
      <StepHeader
        step="2"
        title="Upload Product List"
        subtitle="File uploaded successfully. Please review the details below and click Continue to start processing."
      />

      <div className="card">
        <div className="file-row">
          <span className="file-ok">
            <Icon.CheckCircle width={21} height={21} />
          </span>
          <div style={{ flex: 1 }}>
            <div className="file-name">{preview.filename}</div>
          </div>
          <div className="file-meta">
            <span>{formatSize(preview.size_bytes)}</span>
            <span className="sep" />
            <span>{total} rows</span>
          </div>
          <button className="btn ghost" onClick={onBack} disabled={starting}>
            <Icon.Upload width={14} height={14} />
            Change File
          </button>
        </div>

        {warnings.length > 0 && (
          <div className="alert warn" style={{ marginTop: 16, marginBottom: 0 }}>
            {warnings.slice(0, 4).map((w, i) => <div key={i}>{w}</div>)}
            {warnings.length > 4 && <div>+{warnings.length - 4} more…</div>}
          </div>
        )}

        <div className="section-title">
          File Preview (First {rows.length} rows)
        </div>

        <div className="table-wrap">
          <table>
            <thead>
              <tr>{columns.map((c, i) => <th key={i}>{c}</th>)}</tr>
            </thead>
            <tbody>
              {rows.map((r, i) => (
                <tr key={i}>
                  {columns.map((_, j) => <td key={j}>{r[j] || <span className="muted">—</span>}</td>)}
                </tr>
              ))}
            </tbody>
          </table>
        </div>

        <div className="table-foot">
          Showing {rows.length} of {total} rows
          {preview.usable_rows !== total && (
            <span>· {preview.usable_rows} ready to process</span>
          )}
        </div>
      </div>

      <div className="actions">
        <button className="btn ghost" onClick={onBack} disabled={starting}>
          <Icon.ArrowLeft width={14} height={14} />
          Back
        </button>
        <div className="spacer" />
        <button className="btn" onClick={onContinue} disabled={starting}>
          {starting ? 'Starting…' : 'Continue'}
          <Icon.ArrowRight width={14} height={14} />
        </button>
      </div>
    </div>
  );
}
