import React, { useEffect, useState } from 'react';
import * as Icon from './icons.jsx';
import { apiFetch } from '../api.js';

const PALETTE = ['#2f6bf2', '#0aa5e9', '#17a673', '#e2001a', '#f2b705', '#6b4ed6', '#e10098'];

function siteBadge(domain) {
  let hash = 0;
  for (let i = 0; i < domain.length; i += 1) hash = (hash * 31 + domain.charCodeAt(i)) >>> 0;
  return { color: PALETTE[hash % PALETTE.length], short: domain.replace(/\..*$/, '').slice(0, 2).toUpperCase() };
}

export function HomeScreen({ health, category, onStart }) {
  const fields = category?.input_fields.map((f) => f.label).join(', ') || '';
  return (
    <div className="page">
      <div className="step-head">
        <div className="step-badge"><Icon.Home width={15} height={15} /></div>
        <div>
          <h2>Welcome to PriceExtractor</h2>
          <p>
            Upload a product list and the engine pulls the matching price from each
            retailer, then reports its reasoning for every match.
          </p>
        </div>
      </div>

      <div className="card">
        <h4 style={{ margin: '0 0 4px', fontSize: 14 }}>Start a new extraction</h4>
        <p className="muted" style={{ margin: '0 0 14px', fontSize: 12.5 }}>
          Bring an .xlsx with {fields || 'the required columns'} and a target website.
        </p>
        <button className="btn" onClick={onStart}>
          <Icon.Upload width={15} height={15} />
          Upload Product List
        </button>
      </div>

      <div className="card">
        <h4 style={{ margin: '0 0 12px', fontSize: 14 }}>Supported websites — {category?.label}</h4>
        <div style={{ display: 'grid', gap: 10 }}>
          {(category?.known_sites || []).map((s) => {
            const meta = siteBadge(s);
            return (
              <div key={s} style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
                <span className="site-logo" style={{ background: meta.color, width: 26, height: 26, fontSize: 10 }}>
                  {meta.short}
                </span>
                <div style={{ fontWeight: 600, fontSize: 13 }}>{s}</div>
              </div>
            );
          })}
        </div>
      </div>

      <div className="card">
        <h4 style={{ margin: '0 0 8px', fontSize: 14 }}>AI validation</h4>
        <p className="muted" style={{ margin: 0, fontSize: 12.5 }}>
          Azure OpenAI is{' '}
          <strong style={{ color: health?.ai_validation ? 'var(--ok)' : 'var(--warn)' }}>
            {health?.ai_validation ? 'connected' : 'not configured'}
          </strong>
          {health?.ai_validation
            ? ' — every price is grounded in a live web search with its own reasoning.'
            : ' — set AZURE_OPENAI_ENDPOINT/API_KEY in .env or the app settings.'}
        </p>
      </div>
    </div>
  );
}

export function HistoryScreen({ onOpen }) {
  const [jobs, setJobs] = useState([]);
  const [loading, setLoading] = useState(true);

  const load = () => {
    setLoading(true);
    apiFetch('/api/batch/jobs')
      .then((r) => {
        if (!r.ok) throw new Error();
        return r.json();
      })
      .then((d) => setJobs(d.jobs || []))
      .catch(() => setJobs([]))
      .finally(() => setLoading(false));
  };

  useEffect(load, []);

  return (
    <div className="page">
      <div className="step-head">
        <div className="step-badge"><Icon.History width={15} height={15} /></div>
        <div>
          <h2>History</h2>
          <p>Your previous extraction runs in this browser.</p>
        </div>
      </div>

      <div className="card" style={{ padding: 16 }}>
        <div className="actions" style={{ marginTop: 0, marginBottom: 14 }}>
          <div className="spacer" />
          <button className="btn ghost" onClick={load}>
            <Icon.Refresh width={14} height={14} />
            Refresh
          </button>
        </div>

        {loading ? (
          <div className="empty"><p>Loading…</p></div>
        ) : jobs.length === 0 ? (
          <div className="empty">
            <Icon.History width={30} height={30} />
            <h3>No runs yet</h3>
            <p>Upload a product list to see it here.</p>
          </div>
        ) : (
          <div className="table-wrap">
            <table>
              <thead>
                <tr>
                  <th>Category</th>
                  <th>Status</th>
                  <th>Rows</th>
                  <th>Matched</th>
                  <th>Started</th>
                  <th />
                </tr>
              </thead>
              <tbody>
                {jobs.map((j) => (
                  <tr key={j.id}>
                    <td style={{ fontWeight: 600, textTransform: 'capitalize' }}>{j.category}</td>
                    <td>
                      <span className={`pill ${j.status === 'done' ? 'matched' : 'ambiguous'}`}>
                        {j.status}
                      </span>
                    </td>
                    <td>{j.total}</td>
                    <td>{j.matched}</td>
                    <td className="muted">{new Date(j.created_at * 1000).toLocaleString()}</td>
                    <td style={{ textAlign: 'right' }}>
                      <button className="btn link" onClick={() => onOpen(j.id, j.category)}>View</button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>
    </div>
  );
}

export function SettingsScreen({ health, categories }) {
  return (
    <div className="page">
      <div className="step-head">
        <div className="step-badge"><Icon.Settings width={15} height={15} /></div>
        <div>
          <h2>Settings</h2>
          <p>Runtime configuration, loaded from the backend environment.</p>
        </div>
      </div>

      <div className="card">
        <h4 style={{ margin: '0 0 12px', fontSize: 14 }}>Service status</h4>
        <div className="table-wrap">
          <table>
            <tbody>
              <tr>
                <td style={{ width: 220, fontWeight: 600 }}>Backend</td>
                <td>{health ? 'Connected' : 'Unreachable'}</td>
              </tr>
              <tr>
                <td style={{ fontWeight: 600 }}>AI validation ({health?.model || 'unknown model'})</td>
                <td>{health?.ai_validation ? 'Enabled' : 'Disabled'}</td>
              </tr>
              {categories.map((c) => (
                <tr key={c.key}>
                  <td style={{ fontWeight: 600 }}>{c.label} sites</td>
                  <td>{(c.known_sites || []).join(', ') || '—'}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
        <p className="muted" style={{ fontSize: 12.5, marginBottom: 0, marginTop: 14 }}>
          Change the Azure deployment in <code>.env</code> (or the app settings), then restart the API.
        </p>
      </div>
    </div>
  );
}
