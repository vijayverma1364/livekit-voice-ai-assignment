import React from 'react';

export function ErrorBanner({ message, onDismiss }) {
  if (!message) return null;

  return (
    <div className="error-banner-container" role="alert">
      <div className="error-banner-content">
        <span className="error-icon">⚠️</span>
        <div className="error-message-text">{message}</div>
      </div>
      {onDismiss && (
        <button
          type="button"
          className="error-dismiss-btn"
          onClick={onDismiss}
          aria-label="Dismiss error"
        >
          ✕
        </button>
      )}
    </div>
  );
}
