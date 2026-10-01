import React, { useState } from 'react';

export function WhisperConsole({ onSendWhisper, isListening, lastWhisperSent }) {
  const [whisperText, setWhisperText] = useState('');
  const [sending, setSending] = useState(false);
  const [statusFeedback, setStatusFeedback] = useState(null);

  const presets = [
    'Offer a 10% discount.',
    'Direct customer to support@acme.com for policy review.',
    'Do NOT promise refunds or financial credits.',
    'Ask for order number and email address.',
    'Politely apologize for the inconvenience and offer immediate escalation.',
  ];

  const handleSubmit = async (e) => {
    e?.preventDefault();
    const text = whisperText.trim();
    if (!text || sending) return;

    try {
      setSending(true);
      setStatusFeedback(null);
      await onSendWhisper(text);
      setStatusFeedback({
        type: 'success',
        message: `Whisper dispatched: "${text}"`,
      });
      setWhisperText('');
    } catch (err) {
      setStatusFeedback({
        type: 'error',
        message: err.message || 'Failed to dispatch whisper.',
      });
    } finally {
      setSending(false);
    }
  };

  const handleApplyPreset = (preset) => {
    setWhisperText(preset);
  };

  return (
    <div className="card-panel whisper-console-card">
      <div className="panel-header-row">
        <h3 className="panel-title">Private Coaching Whisper</h3>
        <span className="channel-tag">WebRTC Data Channel</span>
      </div>

      <p className="whisper-hint">
        Directives sent here are injected privately into the agent's dynamic context. The agent will execute
        the instruction in its next response without revealing supervisor presence.
      </p>

      {/* Preset Suggestions */}
      <div className="preset-chips-container">
        <span className="chips-label">Quick Directives:</span>
        <div className="chips-list">
          {presets.map((preset, index) => (
            <button
              key={index}
              type="button"
              className="preset-chip"
              onClick={() => handleApplyPreset(preset)}
              disabled={!isListening || sending}
            >
              {preset}
            </button>
          ))}
        </div>
      </div>

      <form onSubmit={handleSubmit} className="whisper-form">
        <div className="textarea-container">
          <textarea
            id="whisper-input"
            className="styled-textarea"
            rows={3}
            placeholder={
              isListening
                ? 'Type private coaching instruction (e.g. "Offer a 10% discount.")...'
                : 'Connect to an active call to enable private whispering...'
            }
            value={whisperText}
            onChange={(e) => setWhisperText(e.target.value)}
            disabled={!isListening || sending}
          />
        </div>

        <div className="whisper-form-actions">
          <button
            type="submit"
            id="btn-send-whisper"
            className="btn-primary-action whisper-action"
            disabled={!isListening || !whisperText.trim() || sending}
          >
            <span className="btn-icon">💬</span>
            <span>{sending ? 'Dispatching...' : 'Whisper to Agent'}</span>
          </button>
        </div>
      </form>

      {/* Status Feedback */}
      {statusFeedback && (
        <div className={`feedback-alert ${statusFeedback.type}`}>
          <span className="feedback-icon">{statusFeedback.type === 'success' ? '✓' : '⚠️'}</span>
          <span className="feedback-text">{statusFeedback.message}</span>
        </div>
      )}

      {lastWhisperSent && (
        <div className="last-whisper-badge">
          <span className="last-whisper-label">Last Dispatched:</span>
          <span className="last-whisper-text">"{lastWhisperSent.text}"</span>
          <span className="last-whisper-time">({lastWhisperSent.timestamp})</span>
        </div>
      )}
    </div>
  );
}
