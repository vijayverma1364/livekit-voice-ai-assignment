import React, { useState } from 'react';
import { CallStatus } from '../hooks/useLiveKitCall';

export function StatusHeader({ callStatus, callId, roomName }) {
  const [copied, setCopied] = useState(false);

  const getStatusBadge = () => {
    switch (callStatus) {
      case CallStatus.CONNECTED:
        return <span className="status-pill connected"><span className="pulse-dot"></span> LIVE CALL</span>;
      case CallStatus.CONNECTING:
      case CallStatus.INITIALIZING:
        return <span className="status-pill connecting"><span className="pulse-dot connecting"></span> CONNECTING...</span>;
      case CallStatus.DISCONNECTING:
        return <span className="status-pill disconnecting">DISCONNECTING</span>;
      case CallStatus.ENDED:
        return <span className="status-pill ended">CALL ENDED</span>;
      case CallStatus.ERROR:
        return <span className="status-pill error">ERROR</span>;
      default:
        return <span className="status-pill idle">READY</span>;
    }
  };

  const handleCopyCallId = () => {
    if (!callId) return;
    navigator.clipboard.writeText(callId);
    setCopied(true);
    setTimeout(() => setCopied(false), 2000);
  };

  return (
    <div className="status-header-container">
      <div className="status-indicator-group">
        <span className="status-caption">Status</span>
        {getStatusBadge()}
      </div>

      {callId && (
        <div className="call-metadata-group">
          <div className="meta-item">
            <span className="meta-label">Call ID</span>
            <button
              type="button"
              className="copy-id-btn"
              onClick={handleCopyCallId}
              title="Click to copy Call ID"
            >
              <code>{callId.slice(0, 8)}...{callId.slice(-4)}</code>
              <span className="copy-icon">{copied ? '✓' : '📋'}</span>
            </button>
          </div>
          {roomName && (
            <div className="meta-item">
              <span className="meta-label">Room</span>
              <span className="room-badge">{roomName}</span>
            </div>
          )}
        </div>
      )}
    </div>
  );
}
