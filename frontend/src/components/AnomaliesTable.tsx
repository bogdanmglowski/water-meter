import type { AnomalyItem } from "../types";
import { formatTimestamp, formatVolume } from "../utils";

interface AnomaliesTableProps {
  anomalies: AnomalyItem[];
}

export function AnomaliesTable({ anomalies }: AnomaliesTableProps) {
  return (
    <section className="card">
      <div className="section-head">
        <div>
          <h2>Skipped Anomalies</h2>
          <p>Readings skipped during ingestion because the jump exceeded the configured threshold.</p>
        </div>
      </div>

      {anomalies.length === 0 ? (
        <div className="empty-state">
          <strong>No anomalies in this range.</strong>
          <p>Large positive jumps will appear here instead of being inserted into readings.</p>
        </div>
      ) : (
        <div className="table-wrap">
          <table className="reading-table reading-table--anomalies">
            <thead>
              <tr>
                <th>Recorded</th>
                <th>Value</th>
                <th>Previous</th>
                <th>Delta</th>
                <th>Threshold</th>
                <th>Source</th>
              </tr>
            </thead>
            <tbody>
              {anomalies.map((anomaly) => (
                <tr key={anomaly.id}>
                  <td>{formatTimestamp(anomaly.recordedAt)}</td>
                  <td>{formatVolume(anomaly.meterValueM3)}</td>
                  <td>
                    {formatVolume(anomaly.previousMeterValueM3)} at {formatTimestamp(anomaly.previousRecordedAt)}
                  </td>
                  <td>{formatVolume(anomaly.deltaM3)}</td>
                  <td>{formatVolume(anomaly.thresholdM3)}</td>
                  <td>{anomaly.source}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </section>
  );
}
