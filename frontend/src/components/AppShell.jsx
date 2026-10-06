import React from 'react';
import * as Icon from './icons.jsx';

const NAV = [
  { key: 'home', label: 'Home', icon: Icon.Home },
  { key: 'upload', label: 'Upload & Extract', icon: Icon.Upload },
  { key: 'processing', label: 'Processing', icon: Icon.Spark, transient: true },
  { key: 'results', label: 'Result List', icon: Icon.ListIcon, transient: true },
  { key: 'history', label: 'History', icon: Icon.History },
  { key: 'settings', label: 'Settings', icon: Icon.Settings },
];

export default function AppShell({
  screen, onNavigate, canProcess, canResults, categories, category, onCategoryChange, children,
}) {
  const enabled = (key) => {
    if (key === 'processing') return canProcess;
    if (key === 'results') return canResults;
    return true;
  };

  // Processing and Result List only appear once a run reaches them, matching
  // the contextual navigation in the design.
  const items = NAV.filter((n) => !n.transient || enabled(n.key));

  return (
    <div className="shell">
      <div className="topbar">
        <div className="brand">
          <span className="brand-mark">
            <Icon.Tag width={14} height={14} strokeWidth={2.2} />
          </span>
          PriceExtractor
        </div>

        {categories.length > 0 && (
          <select
            className="category-select"
            value={category?.key || ''}
            onChange={(e) => onCategoryChange(e.target.value)}
          >
            {categories.map((c) => (
              <option key={c.key} value={c.key}>{c.label}</option>
            ))}
          </select>
        )}

        <div className="topbar-actions">
          <button className="icon-btn" title="Notifications" aria-label="Notifications">
            <Icon.Bell width={17} height={17} />
            <span className="dot" />
          </button>
          <div className="avatar" title="Signed in">M</div>
        </div>
      </div>

      <div className="body">
        <nav className="sidebar">
          {items.map(({ key, label, icon: Ico }) => (
            <button
              key={key}
              className={`nav-item${screen === key ? ' active' : ''}`}
              onClick={() => onNavigate(key)}
              disabled={!enabled(key)}
            >
              <Ico width={16} height={16} />
              {label}
            </button>
          ))}
        </nav>

        <main className="canvas">{children}</main>
      </div>
    </div>
  );
}
