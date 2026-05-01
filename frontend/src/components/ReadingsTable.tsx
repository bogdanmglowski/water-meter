import { formatTimestamp, formatVolume } from "../utils";
import type { Reading } from "../types";

interface ReadingsTableProps {
  readings: Reading[];
  currentPage: number;
  totalPages: number;
  totalReadings: number;
  pageSize: number;
  onPreviousPage: () => void;
  onNextPage: () => void;
}

export function ReadingsTable({
  readings,
  currentPage,
  totalPages,
  totalReadings,
  pageSize,
  onPreviousPage,
  onNextPage,
}: ReadingsTableProps) {
  const pageStart = totalReadings === 0 ? 0 : (currentPage - 1) * pageSize + 1;
  const pageEnd = totalReadings === 0 ? 0 : pageStart + readings.length - 1;

  return (
    <section className="card">
      <div className="section-head">
        <div>
          <h2>Raw Readings</h2>
          <p>Directly from PostgreSQL, shown as cumulative meter values.</p>
        </div>
        {totalReadings > 0 ? (
          <div className="table-pagination__summary">
            Showing {pageStart}-{pageEnd} of {totalReadings}
          </div>
        ) : null}
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

      {totalReadings > 0 ? (
        <div className="table-pagination">
          <button
            type="button"
            onClick={onPreviousPage}
            disabled={currentPage === 1}
          >
            Previous
          </button>
          <span className="table-pagination__status">
            Page {currentPage} of {totalPages}
          </span>
          <button
            type="button"
            onClick={onNextPage}
            disabled={currentPage === totalPages}
          >
            Next
          </button>
        </div>
      ) : null}
    </section>
  );
}
