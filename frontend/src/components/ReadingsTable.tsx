import { formatTimestamp, formatVolume } from "../utils";
import type { Reading } from "../types";

interface ReadingsTableProps {
  readings: Reading[];
}

export function ReadingsTable({ readings }: ReadingsTableProps) {
  return (
    <section className="card">
      <div className="section-head">
        <div>
          <h2>Raw Readings</h2>
          <p>Directly from PostgreSQL, shown as cumulative meter values.</p>
        </div>
      </div>

      {readings.length === 0 ? (
        <div className="empty-state">
          <strong>No readings in this range.</strong>
          <p>Try widening the window or seed the database.</p>
        </div>
      ) : (
        <div className="table-wrap">
          <table className="reading-table">
            <thead>
              <tr>
                <th>Recorded</th>
                <th>Meter Value</th>
                <th>Source</th>
              </tr>
            </thead>
            <tbody>
              {readings.map((reading) => (
                <tr key={reading.recordedAt}>
                  <td>{formatTimestamp(reading.recordedAt)}</td>
                  <td>{formatVolume(reading.meterValueM3)}</td>
                  <td>{reading.source}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </section>
  );
}

