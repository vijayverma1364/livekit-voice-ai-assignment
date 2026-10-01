import React, { useState } from 'react';
import { SupervisorCallStatus } from '../hooks/useSupervisorCall';

export function ActiveCallsSelector({
  calls,
  selectedCallId,
  onSelectCallId,
  onConnect,
  callStatus,
  loadingCalls,
  onRefreshCalls,
}) {
  const [manualInput, setManualInput] = useState('');
  const [useManual, setUseManual] = useState(false);

  const isConnected =
    callStatus === SupervisorCallStatus.LISTENING ||
    callStatus === SupervisorCallStatus.CONNECTING;

  const handleManualSubmit = (e) => {
    e.preventDefault();
    if (!manualInput.trim()) return;
    onSelectCallId(manualInput.trim());
    onConnect(manualInput.trim());
  };

  const handleSelectChange = (e) => {
    const val = e.target.value;
    if (val === '__MANUAL__') {
      setUseManual(true);
    } else {
      setUseManual(false);
      onSelectCallId(val);
    }
  };

  return (
    <div className="card-panel call-selector-card">
      <div className="panel-header-row">
        <h2 className="panel-title">Active Calls Monitor</h2>
        <button
          type="button"
          className="btn-refresh"
          onClick={onRefreshCalls}
          disabled={loadingCalls || isConnected}
          title="Refresh call list"
        >
          🔄 {loadingCalls ? 'Refreshing...' : 'Refresh'}
        </button>
      </div>

      {!useManual ? (
        <div className="selector-group">
          <label htmlFor="call-select" className="input-label">
            Select Ongoing Call
          </label>
          <select
            id="call-select"
            className="styled-select"
            value={selectedCallId || ''}
            onChange={handleSelectChange}
            disabled={isConnected || loadingCalls}
          >
            {calls.length === 0 ? (
              <option value="">No recent calls found</option>
            ) : (
              calls.map((c) => (
                <option key={c.id} value={c.id}>
                  [{c.status}] {c.room_name || c.id.slice(0, 8)} •{' '}
                  {new Date(c.created_at).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })}
                </option>
              ))
            )}
            <option value="__MANUAL__">+ Enter Call ID Manually...</option>
          </select>
        </div>
      ) : (
        <form onSubmit={handleManualSubmit} className="manual-call-form">
          <div className="manual-header">
            <label htmlFor="manual-call-id" className="input-label">
              Enter Call ID (UUID)
            </label>
            <button
              type="button"
              className="text-link-btn"
              onClick={() => setUseManual(false)}
            >
              ← Back to call list
            </button>
          </div>
          <input
            id="manual-call-id"
            type="text"
            className="styled-text-input"
            placeholder="e.g. b0a769f3-6b43-4d7a-9c2d-9318984d382a"
            value={manualInput}
            onChange={(e) => setManualInput(e.target.value)}
            disabled={isConnected}
          />
        </form>
      )}

      <div className="selector-actions">
        {!isConnected ? (
          <button
            type="button"
            id="btn-listen-call"
            className="btn-primary-action listen-action"
            onClick={() => onConnect(useManual ? manualInput : selectedCallId)}
            disabled={loadingCalls || (!selectedCallId && !manualInput)}
          >
            <span className="btn-icon">🎧</span>
            <span>Join & Listen Stealthily</span>
          </button>
        ) : (
          <div className="listening-indicator-banner">
            <span className="pulse-dot listening"></span>
            <span>Stealth Audio Stream Active</span>
          </div>
        )}
      </div>
    </div>
  );
}
