import React from 'react';

export function AudioMonitor({ customerSpeaking, agentSpeaking, isListening }) {
  return (
    <div className="card-panel audio-monitor-card">
      <div className="panel-header-row">
        <h3 className="panel-title">Audio Stream Monitor</h3>
        <span className="mic-disabled-badge" title="Microphone publishing is blocked by backend security token">
          🔒 Mic: Blocked (Listen Only)
        </span>
      </div>

      <div className="audio-channels-grid">
        {/* Customer Audio Channel */}
        <div className={`audio-channel-box ${customerSpeaking ? 'active' : ''}`}>
          <div className="channel-header">
            <span className="channel-icon">👤</span>
            <span className="channel-name">Customer Stream</span>
          </div>
          <div className="channel-bars">
            <span className={`bar ${customerSpeaking ? 'pulse' : ''}`}></span>
            <span className={`bar ${customerSpeaking ? 'pulse' : ''}`}></span>
            <span className={`bar ${customerSpeaking ? 'pulse' : ''}`}></span>
            <span className={`bar ${customerSpeaking ? 'pulse' : ''}`}></span>
          </div>
          <span className="channel-status">
            {!isListening ? 'Inactive' : customerSpeaking ? 'Speaking...' : 'Listening'}
          </span>
        </div>

        {/* Agent Audio Channel */}
        <div className={`audio-channel-box ${agentSpeaking ? 'active' : ''}`}>
          <div className="channel-header">
            <span className="channel-icon">🤖</span>
            <span className="channel-name">Agent Stream</span>
          </div>
          <div className="channel-bars">
            <span className={`bar ${agentSpeaking ? 'pulse' : ''}`}></span>
            <span className={`bar ${agentSpeaking ? 'pulse' : ''}`}></span>
            <span className={`bar ${agentSpeaking ? 'pulse' : ''}`}></span>
            <span className={`bar ${agentSpeaking ? 'pulse' : ''}`}></span>
          </div>
          <span className="channel-status">
            {!isListening ? 'Inactive' : agentSpeaking ? 'Speaking...' : 'Listening'}
          </span>
        </div>
      </div>

      <div className="privacy-assurance-footer">
        <span className="shield-icon">🛡️</span>
        <span className="assurance-text">
          Zero audio leakage: Supervisor presence and audio cannot be detected by the customer.
        </span>
      </div>
    </div>
  );
}
