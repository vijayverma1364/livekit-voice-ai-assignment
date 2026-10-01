import React from 'react';

export function AgentSelector({ agents, selectedAgentId, onSelect, disabled }) {
  if (!agents || agents.length === 0) {
    return (
      <div className="agent-selector-card loading">
        <label className="selector-label">Support Agent</label>
        <div className="skeleton-select">Loading available agents...</div>
      </div>
    );
  }

  return (
    <div className="agent-selector-card">
      <div className="selector-header">
        <label htmlFor="agent-select" className="selector-label">
          Select Voice AI Agent
        </label>
        <span className="agent-count-badge">{agents.length} Available</span>
      </div>
      <select
        id="agent-select"
        className="agent-select-input"
        value={selectedAgentId}
        onChange={(e) => onSelect(e.target.value)}
        disabled={disabled}
      >
        {agents.map((agent) => (
          <option key={agent.id} value={agent.id}>
            {agent.name} ({agent.model} • voice: {agent.voice})
          </option>
        ))}
      </select>
    </div>
  );
}
