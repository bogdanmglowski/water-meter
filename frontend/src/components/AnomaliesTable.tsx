import type { AnomalyItem } from "../types";
import { formatTimestamp, formatVolume } from "../utils";

interface AnomaliesTableProps {
  anomalies: AnomalyItem[];
  showArchived: boolean;
  pendingArchiveAnomalyId: number | null;
  pendingRawReadingAnomalyId: number | null;
  onArchiveAnomaly: (anomaly: AnomalyItem) => void;
  onUnarchiveAnomaly: (anomaly: AnomalyItem) => void;
  onAddToRawReadings: (anomaly: AnomalyItem) => void;
}

export function AnomaliesTable({
  anomalies,
  showArchived,
  pendingArchiveAnomalyId,
  pendingRawReadingAnomalyId,
  onArchiveAnomaly,
  onUnarchiveAnomaly,
  onAddToRawReadings,
}: AnomaliesTableProps) {
  return (
    <section className="card">
      <div className="section-head">
        <div>
          <h2>Skipped Anomalies</h2>
          <p>Readings skipped during ingestion because the delta was negative or exceeded the configured threshold.</p>
        </div>
      </div>

      {anomalies.length === 0 ? (
        <div className="empty-state">
          <strong>No anomalies match the current filter.</strong>
          <p>
            {showArchived
              ? "This range has no active or archived anomalies to review."
              : "Skipped readings will appear here until you archive them manually."}
          </p>
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
                <th>Evidence</th>
                <th>Actions</th>
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
                  <td>
                    <div className="anomaly-evidence">
                      {anomaly.imageUrl ? (
                        <a
                          href={anomaly.imageUrl}
                          target="_blank"
                          rel="noreferrer"
                          className="anomaly-link"
                        >
                          Open image
                        </a>
                      ) : (
                        <span className="anomaly-muted">No image</span>
                      )}
                      <span
                        className={`anomaly-status ${anomaly.archived ? "anomaly-status--archived" : "anomaly-status--active"}`}
                      >
                        {anomaly.archived ? "Archived" : "Active"}
                      </span>
                    </div>
                  </td>
                  <td className="reading-table__actions">
                    <div className="anomaly-actions">
                      <button
                        type="button"
                        className="reading-archive-button reading-archive-button--raw"
                        onClick={() => onAddToRawReadings(anomaly)}
                        disabled={anomaly.storedAsRaw || pendingRawReadingAnomalyId === anomaly.id}
                      >
                        {pendingRawReadingAnomalyId === anomaly.id
                          ? "Saving..."
                          : anomaly.storedAsRaw
                            ? "In raw"
                            : "Add to raw"}
                      </button>
                      {anomaly.archived ? (
                        <button
                          type="button"
                          className="reading-archive-button"
                          onClick={() => onUnarchiveAnomaly(anomaly)}
                          disabled={pendingArchiveAnomalyId === anomaly.id}
                        >
                          {pendingArchiveAnomalyId === anomaly.id ? "Restoring..." : "Unarchive"}
                        </button>
                      ) : (
                        <button
                          type="button"
                          className="reading-archive-button"
                          onClick={() => onArchiveAnomaly(anomaly)}
                          disabled={pendingArchiveAnomalyId === anomaly.id}
                        >
                          {pendingArchiveAnomalyId === anomaly.id ? "Archiving..." : "Archive"}
                        </button>
                      )}
                    </div>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </section>
  );
}
