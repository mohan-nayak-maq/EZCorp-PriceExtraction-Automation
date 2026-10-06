import React from 'react';
import * as Icon from './icons.jsx';
import { safeHref } from '../api.js';

function money(value, currency) {
  if (value === null || value === undefined) return null;
  try {
    return new Intl.NumberFormat('en-US', {
      style: 'currency',
      currency: currency || 'USD',
      maximumFractionDigits: 2,
    }).format(value);
  } catch {
    return `${currency || ''} ${value}`;
  }
}

function Section({ title, children }) {
  return (
    <div className="details-section">
      <h4>{title}</h4>
      {children}
    </div>
  );
}

// Everything here is data the model already produced in its single search call
// (confidence, reasoning, citations, candidates) - this is a presentation
// layer only, it does not run any extra AI call and does not touch the
// search/retry logic in engine.py.
export default function DetailsModal({ row, onClose }) {
  if (!row) return null;
  const r = row.raw;
  const f = r?.finding;
  const confidencePct = f?.confidence != null ? Math.round(f.confidence * 100) : null;
  const trace = r?.trace || {};
  const siteCitations = r?.citations || [];

  return (
    <div className="modal-overlay" onClick={onClose}>
      <div className="modal-panel" onClick={(e) => e.stopPropagation()}>
        <div className="modal-head">
          <div>
            <div className="modal-title">{row.subject}</div>
            <div className="modal-sub">{row.detail}{row.site ? ` · ${row.site}` : ''}</div>
          </div>
          <button className="modal-close" onClick={onClose} title="Close">
            <Icon.Close width={16} height={16} />
          </button>
        </div>

        <div className="modal-body">
          <div className="details-grid">
            <div className="details-stat">
              <span>Current retail price</span>
              <b>{money(f?.price, f?.currency) || '—'}</b>
            </div>
            <div className="details-stat">
              <span>Condition</span>
              <b>{f?.price_type || '—'}</b>
            </div>
            <div className="details-stat">
              <span>Confidence (AI-generated)</span>
              <b className={confidencePct != null && confidencePct < 50 ? 'low' : ''}>
                {confidencePct != null ? `${confidencePct}%` : '—'}
              </b>
            </div>
            <div className="details-stat">
              <span>Availability</span>
              <b>{f?.availability || '—'}</b>
            </div>
          </div>

          <Section title="Matched listing / source link">
            {f?.matched_title ? (
              <div>
                <div className="details-listing-title">{f.matched_title}</div>
                {safeHref(f?.product_url) && (
                  <a className="details-source-link" href={safeHref(f.product_url)} target="_blank" rel="noopener noreferrer">
                    <Icon.ExternalLink width={13} height={13} />
                    {f.product_url}
                  </a>
                )}
              </div>
            ) : (
              <p className="muted">No listing was matched.</p>
            )}
          </Section>

          <Section title="Why this price was selected">
            <p className="details-reasoning">{f?.reasoning || 'No reasoning summary was returned.'}</p>
            {!!f?.reasoning_steps?.length && (
              <ol className="details-steps">
                {f.reasoning_steps.map((step, i) => <li key={i}>{step}</li>)}
              </ol>
            )}
          </Section>

          {!!f?.considered_candidates?.length && (
            <Section title="Other listings considered">
              <ul className="details-candidates">
                {f.considered_candidates.map((c, i) => (
                  <li key={i}>
                    <div className="cand-line">
                      <span className="cand-title">{c.title || 'Untitled listing'}</span>
                      <span className="cand-price">{money(c.price, c.currency) || c.price_text || '—'}</span>
                    </div>
                    <div className="cand-reason">{c.reason}</div>
                  </li>
                ))}
              </ul>
            </Section>
          )}

          {!!siteCitations.length && (
            <Section title="Prices found across sites (this row's search)">
              <ul className="details-candidates">
                {siteCitations.map((c, i) => (
                  <li key={i}>
                    <div className="cand-line">
                      <span className="cand-title">{c.domain}</span>
                      <span className="cand-price">{money(c.price, c.currency)}</span>
                    </div>
                    {safeHref(c.url) && (
                      <a className="details-source-link" href={safeHref(c.url)} target="_blank" rel="noopener noreferrer">
                        <Icon.ExternalLink width={12} height={12} />
                        {c.url}
                      </a>
                    )}
                  </li>
                ))}
              </ul>
            </Section>
          )}

          {!!trace.citations?.length && (
            <Section title="Citations returned by web search">
              <ul className="details-citations">
                {trace.citations.map((c, i) => (
                  <li key={i}>
                    {safeHref(c.url)
                      ? <a href={safeHref(c.url)} target="_blank" rel="noopener noreferrer">{c.title || c.url}</a>
                      : <span>{c.title || c.url}</span>}
                  </li>
                ))}
              </ul>
            </Section>
          )}

          {!!f?.caveats?.length && (
            <Section title="Caveats">
              <ul className="details-plain-list">
                {f.caveats.map((c, i) => <li key={i}>{c}</li>)}
              </ul>
            </Section>
          )}

          {!!r?.warnings?.length && (
            <Section title="Verification warnings">
              <ul className="details-plain-list warn">
                {r.warnings.map((w, i) => <li key={i}>{w}</li>)}
              </ul>
            </Section>
          )}

          {(r?.error || row.error) && (
            <Section title="Error">
              <p className="details-reasoning error">{r?.error || row.error}</p>
            </Section>
          )}

          <div className="details-meta">
            {r?.model && <span>Model: {r.model}</span>}
            {r?.elapsed_seconds != null && <span>Elapsed: {r.elapsed_seconds}s</span>}
            {!!trace.queries?.length && <span>Searches run: {trace.queries.length}</span>}
          </div>
        </div>
      </div>
    </div>
  );
}
