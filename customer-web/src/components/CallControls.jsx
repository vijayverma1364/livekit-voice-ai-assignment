import React from 'react';
import { CallStatus } from '../hooks/useLiveKitCall';

export function CallControls({
  callStatus,
  onStartCall,
  onEndCall,
  onToggleMute,
  isMuted,
  micEnabled,
  disabled,
}) {
  const isCallActive =
    callStatus === CallStatus.CONNECTED ||
    callStatus === CallStatus.CONNECTING ||
    callStatus === CallStatus.INITIALIZING;

  return (
    <div className="call-controls-container">
      {!isCallActive ? (
        <button
          type="button"
          id="btn-start-call"
          className="btn-call-action start-call"
          onClick={onStartCall}
          disabled={disabled}
        >
          <span className="btn-icon">📞</span>
          <span className="btn-text">Start Voice Call</span>
        </button>
      ) : (
        <div className="active-controls-group">
          {callStatus === CallStatus.CONNECTED && (
            <button
              type="button"
              id="btn-toggle-mic"
              className={`btn-control-secondary mic-btn ${isMuted ? 'muted' : 'active'}`}
              onClick={onToggleMute}
              title={isMuted ? 'Unmute microphone' : 'Mute microphone'}
            >
              <span className="btn-icon">{isMuted ? '🔇' : '🎙️'}</span>
              <span className="btn-text">{isMuted ? 'Unmute Mic' : 'Mute Mic'}</span>
            </button>
          )}

          <button
            type="button"
            id="btn-end-call"
            className="btn-call-action end-call"
            onClick={onEndCall}
            disabled={callStatus === CallStatus.DISCONNECTING}
          >
            <span className="btn-icon">⏹</span>
            <span className="btn-text">
              {callStatus === CallStatus.DISCONNECTING ? 'Disconnecting...' : 'End Call'}
            </span>
          </button>
        </div>
      )}

      {/* Microphone status indicator */}
      <div className="mic-status-indicator">
        <span className={`mic-dot ${isCallActive && micEnabled && !isMuted ? 'active' : 'inactive'}`}></span>
        <span className="mic-label">
          {!isCallActive
            ? 'Mic: Standby'
            : isMuted
            ? 'Mic: Muted'
            : micEnabled
            ? 'Mic: Live & Transmitting'
            : 'Mic: Initializing...'}
        </span>
      </div>
    </div>
  );
}
