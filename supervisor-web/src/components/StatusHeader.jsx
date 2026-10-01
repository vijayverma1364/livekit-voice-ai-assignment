import React, { useState } from 'react';
import { SupervisorCallStatus } from '../hooks/useSupervisorCall';

export function StatusHeader({ callStatus, callId, roomName, onDisconnect }) {
  const [copied, setCopied] = useState(false);

  const getStatusBadge = () => {
    switch (callStatus) {
      case SupervisorCallStatus.LISTENING:
        return (
          <span className="status-pill listening">
            <span className="pulse-dot listening"></span> LISTENING (STEALTH)
          </span>
        );
      case SupervisorCallStatus.CONNECTING:
        return (
          <span className="status-pill connecting">
            <span className="pulse-dot connecting"></span> CONNECTING...
          </span>
        );
      case SupervisorCallStatus.DISCONNECTING:
        return <span className="status-pill disconnecting">DISCONNECTING</span>;
      case SupervisorCallStatus.ENDED:
        return <span className="status-pill ended">DISCONNECTED</span>;
      case SupervisorCallStatus.ERROR:
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

  const isConnected = callStatus === SupervisorCallStatus.LISTENING;

  return (
    <div className="status-header-container">
      <div className="status-indicator-group">
        <div className="status-caption-row">
          <span className="status-caption">Console Status</span>
          <span className="stealth-mode-badge" title="Supervisor is hidden from the room and cannot publish audio">
            🕵️ Stealth Eavesdrop
          </span>
        </div>
        {getStatusBadge()}
      </div>

      {callId && (
        <div className="call-metadata-group">
          <div className="meta-item">
            <span className="meta-label">Active Call ID</span>
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
          {isConnected && (
            <button
              type="button"
              id="btn-leave-call"
              className="btn-disconnect-secondary"
              onClick={onDisconnect}
            >
              Stop Listening
            </button>
          )}
        </div>
      )}
    </div>
  );
}
