import React, { useEffect, useMemo, useRef, useState } from 'react';
import StepHeader from './StepHeader.jsx';
import DetailsModal from './DetailsModal.jsx';
import * as Icon from './icons.jsx';
import { safeHref } from '../api.js';

const PAGE_SIZE = 5;

const PALETTE = ['#2f6bf2', '#0aa5e9', '#17a673', '#e2001a', '#f2b705', '#6b4ed6', '#e10098'];

function siteBadge(domain) {
  const label = domain || 'site';
  let hash = 0;
  for (let i = 0; i < label.length; i += 1) hash = (hash * 31 + label.charCodeAt(i)) >>> 0;
  const color = PALETTE[hash % PALETTE.length];
  const short = label.replace(/\.(com|mx|gt|net|org).*$/, '').slice(0, 2).toUpperCase();
  return { label, short, color };
}

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

function HeaderFilter({ options, value, onChange }) {
  const [open, setOpen] = useState(false);
  const ref = useRef(null);

  useEffect(() => {
    const close = (e) => { if (ref.current && !ref.current.contains(e.target)) setOpen(false); };
    document.addEventListener('mousedown', close);
    return () => document.removeEventListener('mousedown', close);
  }, []);

  return (
    <span style={{ position: 'relative' }} ref={ref}>
      <button
        className={`filter-btn${value ? ' on' : ''}`}
        onClick={() => setOpen((o) => !o)}
        title="Filter"
      >
        <Icon.Filter width={12} height={12} />
      </button>
      {open && (
        <div
          style={{
            position: 'absolute', top: 20, left: 0, zIndex: 30,
            background: '#fff', border: '1px solid var(--border-strong)',
            borderRadius: 9, boxShadow: 'var(--shadow)', padding: 5,
            minWidth: 130, textTransform: 'none', letterSpacing: 0,
          }}
        >
          {[{ v: '', l: 'All' }, ...options].map((o) => (
            <button
              key={o.v}
              onClick={() => { onChange(o.v); setOpen(false); }}
              style={{
                display: 'block', width: '100%', textAlign: 'left',
                border: 0, borderRadius: 6, cursor: 'pointer',
                padding: '6px 9px', fontSize: 12,
                background: value === o.v ? 'var(--brand-soft)' : 'transparent',
                color: value === o.v ? 'var(--brand)' : 'var(--text)',
                fontWeight: value === o.v ? 600 : 500,
              }}
            >
              {o.l}
            </button>
          ))}
        </div>
      )}
    </span>
  );
}

// Maps our found/not_found/error status onto the original pill vocabulary.
const STATUS_PILL = { found: 'matched', not_found: 'not_found', error: 'error' };

function toRow(row, index) {
  const r = row.result;
  const f = r?.finding;
  const site = r?.resolved_domain || row.input_fields.target_website || '';
  return {
    index,
    raw: r,
    error: row.error,
    subject: r?.subject_label || Object.values(row.input_fields).filter(Boolean).join(' '),
    detail: Object.entries(row.input_fields)
      .filter(([k]) => k !== 'target_website')
      .map(([, v]) => v)
      .filter(Boolean)
      .join(' · '),
    site,
    status: STATUS_PILL[r?.status] || 'error',
    matched_title: f?.matched_title,
    product_url: f?.product_url,
    price: f?.price ?? null,
    least_price: r?.least_price ?? null,
    max_price: r?.max_price ?? null,
    citation_count: r?.citations?.length || 0,
    currency: f?.currency,
    confidence: f?.confidence,
    price_type: f?.price_type,
  };
}

export default function ResultsScreen({ category, job, onExport }) {
  const results = useMemo(() => job?.rows.map(toRow) || [], [job]);
  const [siteFilter, setSiteFilter] = useState('');
  const [statusFilter, setStatusFilter] = useState('');
  const [page, setPage] = useState(1);
  const [detailsRow, setDetailsRow] = useState(null);

  const filtered = useMemo(
    () => results.filter(
      (r) => (!siteFilter || r.site === siteFilter) && (!statusFilter || r.status === statusFilter)
    ),
    [results, siteFilter, statusFilter]
  );

  const pages = Math.max(1, Math.ceil(filtered.length / PAGE_SIZE));
  const current = Math.min(page, pages);
  const slice = filtered.slice((current - 1) * PAGE_SIZE, current * PAGE_SIZE);

  useEffect(() => { setPage(1); }, [siteFilter, statusFilter]);

  const siteOptions = [...new Set(results.map((r) => r.site))].map((s) => ({ v: s, l: s }));
  const statusOptions = [...new Set(results.map((r) => r.status))]
    .map((s) => ({ v: s, l: s.replace('_', ' ') }));

  const matched = results.filter((r) => r.status === 'matched').length;
  const notFound = results.length - matched;

  return (
    <div className="page wide">
      <StepHeader
        step="4"
        title="Result List"
        subtitle="Here are the extracted prices for your products. You can review, filter and export the results."
      />

      <div className="stat-grid">
        <div className="stat">
          <span className="stat-icon total"><Icon.Package width={16} height={16} /></span>
          <div><b>{job?.total || 0}</b><span>Total Products</span></div>
        </div>
        <div className="stat">
          <span className="stat-icon ok"><Icon.CheckCircle width={16} height={16} /></span>
          <div><b>{matched}</b><span>Matched</span></div>
        </div>
        <div className="stat">
          <span className="stat-icon bad"><Icon.XCircle width={16} height={16} /></span>
          <div><b>{notFound}</b><span>Not Found</span></div>
        </div>
        <div className="export-cell">
          <button className="btn" onClick={onExport} disabled={!results.length}>
            <Icon.Download width={15} height={15} />
            Export to Excel
          </button>
        </div>
      </div>

      <div className="card" style={{ padding: 16 }}>
        <div className="table-wrap">
          <table>
            <thead>
              <tr>
                <th>#</th>
                <th>{category.label === 'Firearms' ? 'Manufacturer / Model' : 'Product'}</th>
                <th>
                  Site
                  <HeaderFilter options={siteOptions} value={siteFilter} onChange={setSiteFilter} />
                </th>
                <th>
                  Status
                  <HeaderFilter options={statusOptions} value={statusFilter} onChange={setStatusFilter} />
                </th>
                <th>Matched Listing</th>
                <th>Price</th>
                <th>Confidence</th>
                <th>Condition</th>
                <th>Details</th>
              </tr>
            </thead>
            <tbody>
              {slice.map((r) => {
                const meta = siteBadge(r.site);
                const price = money(r.price, r.currency);
                return (
                  <tr key={r.index}>
                    <td className="muted">{r.index + 1}</td>
                    <td>
                      <div className="prod-cell">
                        <div className="thumb-ph">{(r.subject || '?').slice(0, 2).toUpperCase()}</div>
                        <div>
                          <div className="prod-name">{r.subject}</div>
                          <div className="prod-sub">{r.detail}</div>
                        </div>
                      </div>
                    </td>
                    <td>
                      <span className="site-cell">
                        <span className="site-logo" style={{ background: meta.color }}>{meta.short}</span>
                        {meta.label}
                      </span>
                    </td>
                    <td><span className={`pill ${r.status}`}>{r.status.replace('_', ' ')}</span></td>
                    <td>
                      {r.matched_title ? (
                        safeHref(r.product_url) ? (
                          <a className="listing-link" href={safeHref(r.product_url)} target="_blank" rel="noopener noreferrer">
                            {r.matched_title}
                          </a>
                        ) : (
                          <span>{r.matched_title}</span>
                        )
                      ) : (
                        <span className="muted">—</span>
                      )}
                    </td>
                    <td>
                      {price ? (
                        <span className="price">
                          {price}
                          {r.least_price != null && r.max_price != null && r.least_price !== r.max_price && (
                            <span className="price-sub">
                              Range: {money(r.least_price, r.currency)} – {money(r.max_price, r.currency)}
                              {r.citation_count ? ` (${r.citation_count} sites)` : ''}
                            </span>
                          )}
                        </span>
                      ) : (
                        <span className="muted">—</span>
                      )}
                    </td>
                    <td className="muted">{r.confidence != null ? `${Math.round(r.confidence * 100)}%` : '—'}</td>
                    <td>
                      {r.price_type ? (
                        <span className={`ai-cell${r.price_type === 'new' ? '' : ' bad'}`}>
                          {r.price_type === 'new'
                            ? <Icon.CheckCircle width={14} height={14} />
                            : <Icon.XCircle width={14} height={14} />}
                          {r.price_type}
                        </span>
                      ) : (
                        <span className="muted">—</span>
                      )}
                    </td>
                    <td>
                      <button className="btn-details" onClick={() => setDetailsRow(r)}>
                        <Icon.FileText width={13} height={13} />
                        Details
                      </button>
                    </td>
                  </tr>
                );
              })}
              {!slice.length && (
                <tr>
                  <td colSpan={9}>
                    <div className="empty">
                      <h3>Nothing to show</h3>
                      <p>No rows match the current filters.</p>
                    </div>
                  </td>
                </tr>
              )}
            </tbody>
          </table>
        </div>

        <div className="table-foot">
          {filtered.length
            ? `Showing ${(current - 1) * PAGE_SIZE + 1} - ${Math.min(current * PAGE_SIZE, filtered.length)} of ${filtered.length} results`
            : 'No results'}
          <div className="pager">
            <button onClick={() => setPage(current - 1)} disabled={current <= 1}>‹</button>
            {Array.from({ length: pages }, (_, i) => i + 1).map((p) => (
              <button
                key={p}
                className={p === current ? 'active' : ''}
                onClick={() => setPage(p)}
              >
                {p}
              </button>
            ))}
            <button onClick={() => setPage(current + 1)} disabled={current >= pages}>›</button>
          </div>
        </div>
      </div>
      <DetailsModal row={detailsRow} onClose={() => setDetailsRow(null)} />
    </div>
  );
}
