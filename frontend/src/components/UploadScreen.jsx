import React, { useRef, useState } from 'react';
import StepHeader from './StepHeader.jsx';
import * as Icon from './icons.jsx';

export default function UploadScreen({ category, onFile, busy, error }) {
  const inputRef = useRef(null);
  const [drag, setDrag] = useState(false);

  const columns = [
    ...category.input_fields.map((f) => f.label),
    ...(category.fixed_sites ? [] : ['Target Website']),
    ...(category.allowed_countries ? [] : ['Country']),
  ];

  const pick = (file) => {
    if (file && !busy) onFile(file);
  };

  return (
    <div className="page">
      <StepHeader
        step="1"
        title="Upload Product List"
        subtitle={`Upload your ${category.label.toLowerCase()} list and we'll find the best prices from supported websites.`}
        extra="Supported format: .xlsx   (Max file size: 10MB, up to 500 rows)"
      />

      {error && <div className="alert error">{error}</div>}

      <div className="card">
        <div
          className={`dropzone${drag ? ' drag' : ''}`}
          onClick={() => !busy && inputRef.current?.click()}
          onDragOver={(e) => { e.preventDefault(); setDrag(true); }}
          onDragLeave={() => setDrag(false)}
          onDrop={(e) => { e.preventDefault(); setDrag(false); pick(e.dataTransfer.files?.[0]); }}
        >
          <div className="dz-icon">
            <Icon.CloudUpload width={38} height={38} strokeWidth={1.6} />
          </div>
          <div className="dz-title">
            {busy ? 'Reading your file…' : 'Drag & drop your file here'}
          </div>
          <div className="dz-or">or</div>
          <button className="btn" disabled={busy} onClick={(e) => { e.stopPropagation(); inputRef.current?.click(); }}>
            <Icon.Upload width={15} height={15} />
            Browse Files
          </button>
          <div className="dz-hint">Supported format: .xlsx   |   Max file size: 10MB   |   Up to 500 rows</div>

          <input
            ref={inputRef}
            type="file"
            accept=".xlsx,.xlsm"
            hidden
            onChange={(e) => { pick(e.target.files?.[0]); e.target.value = ''; }}
          />
        </div>

        <div className="sample">
          <div className="sample-icon">
            <Icon.FileText width={16} height={16} />
          </div>
          <div style={{ flex: 1 }}>
            <h4>Sample File Format</h4>
            <p>Your file should contain the following columns:</p>
            <div className="chips">
              {columns.map((c) => <span className="chip" key={c}>{c}</span>)}
            </div>
            {category.fixed_sites && (
              <p className="muted" style={{ margin: '10px 0 0', fontSize: 11.5 }}>
                No website column needed — every product is searched across all {category.fixed_sites.length}{' '}
                supported retailer sites, and the lowest price (new preferred) is reported.
              </p>
            )}
          </div>
          <button
            className="btn link"
            onClick={() => window.open(`/api/categories/${category.key}/template`, '_blank')}
          >
            <Icon.Download width={14} height={14} />
            Download sample template
          </button>
        </div>
      </div>
    </div>
  );
}
