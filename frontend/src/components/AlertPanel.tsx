import { formatTimestamp, formatVolume } from "../utils";
import type { AlertItem } from "../types";

interface AlertPanelProps {
  alerts: AlertItem[];
}

export function AlertPanel({ alerts }: AlertPanelProps) {
  return (
    <section className="card">
      <div className="section-head">
        <div>
          <h2>Visual Alerts</h2>
          <p>Spikes, leak suspicion, and data-quality anomalies.</p>
        </div>
        <span className="count-pill">{alerts.length}</span>
      </div>

      {alerts.length === 0 ? (
        <div className="empty-state">
          <strong>No active alerts in this range.</strong>
          <p>The recent pattern looks normal from the rules implemented in v1.</p>
        </div>
      ) : (
        <div className="alert-list">
          {alerts.map((alert) => (
            <article key={alert.id} className={`alert alert--${alert.severity}`}>
              <div className="alert__meta">
                <span className={`severity severity--${alert.severity}`}>
                  {alert.severity}
                </span>
                <span className="alert__kind">{alert.kind.replace(/_/g, " ")}</span>
              </div>
              <strong>{alert.message}</strong>
              <div className="alert__stats">
                <span>Actual: {formatVolume(alert.actualValueM3)}</span>
                {alert.baselineValueM3 !== null ? (
                  <span>Baseline: {formatVolume(alert.baselineValueM3)}</span>
                ) : null}
                {alert.ratio !== null ? <span>Ratio: {alert.ratio.toFixed(1)}x</span> : null}
              </div>
              <span className="alert__time">
                {formatTimestamp(alert.startsAt)} to {formatTimestamp(alert.endsAt)}
              </span>
            </article>
          ))}
        </div>
      )}
    </section>
  );
}
