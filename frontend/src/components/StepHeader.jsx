import React from 'react';

export default function StepHeader({ step, title, subtitle, extra }) {
  return (
    <div className="step-head">
      <div className="step-badge">{step}</div>
      <div>
        <h2>{title}</h2>
        {subtitle && <p>{subtitle}</p>}
        {extra && <p>{extra}</p>}
      </div>
    </div>
  );
}
