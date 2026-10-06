import React from 'react';
import StepHeader from './StepHeader.jsx';
import * as Icon from './icons.jsx';

const STATE_LABEL = {
  completed: 'Completed',
  in_progress: 'In progress…',
  pending: 'Pending',
};

function Donut({ percent, indeterminate }) {
  const size = 116;
  const stroke = 11;
  const r = (size - stroke) / 2;
  const c = 2 * Math.PI * r;
  // While nothing has completed yet, show a spinning partial arc instead of a
  // static empty ring, so it's clear the run has actually started.
  const offset = indeterminate ? c * 0.75 : c - (c * Math.min(Math.max(percent, 0), 100)) / 100;

  return (
    <div className="donut">
      <svg width={size} height={size} className={indeterminate ? 'donut-spin' : ''}>
        <circle cx={size / 2} cy={size / 2} r={r} fill="none" stroke="#e7edf9" strokeWidth={stroke} />
        <circle
          cx={size / 2}
          cy={size / 2}
          r={r}
          fill="none"
          stroke="var(--brand)"
          strokeWidth={stroke}
          strokeLinecap="round"
          strokeDasharray={c}
          strokeDashoffset={offset}
          style={indeterminate ? undefined : { transition: 'stroke-dashoffset .5s ease' }}
        />
      </svg>
      <div className="donut-label">{Math.round(percent)}%</div>
    </div>
  );
}

function StageIcon({ state }) {
  if (state === 'completed') {
    return (
      <span className="stage-dot" style={{ color: 'var(--ok)' }}>
        <Icon.CheckCircle width={17} height={17} />
      </span>
    );
  }
  if (state === 'in_progress') {
    return <span className="stage-dot"><span className="spinner" /></span>;
  }
  return (
    <span className="stage-dot pending">
      <Icon.Circle width={16} height={16} />
    </span>
  );
}

export default function ProcessingScreen({ job }) {
  const total = job?.total || 0;
  const done = job?.completed || 0;
  const percent = total ? (done / total) * 100 : 0;
  const stages = job?.stages || [];
  const indeterminate = job?.status !== 'done' && job?.status !== 'error' && done === 0;

  return (
    <div className="page">
      <StepHeader
        step="3"
        title="Processing"
        subtitle="We are visiting the websites, searching for the products and extracting the prices. This may take a few minutes."
      />

      {job?.error && <div className="alert error">{job.error}</div>}

      <div className="card">
        <div className="proc-top">
          <Donut percent={percent} indeterminate={indeterminate} />
          <div className="proc-copy">
            <h3>{job?.status === 'done' ? 'Processing complete' : 'Processing your file...'}</h3>
            <p>{done} of {total} products completed</p>
            <div className="bar"><div style={{ width: `${percent}%` }} /></div>
          </div>
        </div>

        <div className="stage-list">
          {stages.map((s) => (
            <div className={`stage ${s.state}`} key={s.key}>
              <StageIcon state={s.state} />
              <span className="stage-name">{s.label}</span>
              <span className="stage-state">
                {s.state === 'in_progress' && s.key !== 'reading' && s.total
                  ? `${s.done} of ${s.total}`
                  : STATE_LABEL[s.state]}
              </span>
            </div>
          ))}
        </div>

        {/* <div className="info-banner">
          <Icon.Info width={16} height={16} style={{ flex: 'none', marginTop: 1 }} />
          <span>
            This may take a few minutes. Coppel, Best Buy and Walmart are
            opened in a real
            browser, so those rows take longer than the rest.
          </span>
        </div> */}
      </div>
    </div>
  );
}
