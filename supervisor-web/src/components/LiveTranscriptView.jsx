import React, { useEffect, useRef } from 'react';

export function LiveTranscriptView({ transcripts, isCallActive = true }) {
  const scrollAreaRef = useRef(null);
  const isNearBottomRef = useRef(true);
  const prevTranscriptsLengthRef = useRef(0);
  const prevLastTextRef = useRef('');

  // Track user scroll position: if user scrolls upward, keep their position
  const handleScroll = () => {
    const el = scrollAreaRef.current;
    if (!el) return;
    const distanceFromBottom = el.scrollHeight - el.scrollTop - el.clientHeight;
    isNearBottomRef.current = distanceFromBottom <= 60;
  };

  useEffect(() => {
    const el = scrollAreaRef.current;
    if (!el) return;

    if (!isCallActive) return;

    const currentLen = transcripts.length;
    const currentLastText = currentLen > 0 ? transcripts[currentLen - 1].text : '';

    const isNewTurn = currentLen !== prevTranscriptsLengthRef.current;
    const isNewContent = currentLastText !== prevLastTextRef.current;

    prevTranscriptsLengthRef.current = currentLen;
    prevLastTextRef.current = currentLastText;

    if ((isNewTurn || isNewContent) && isNearBottomRef.current) {
      requestAnimationFrame(() => {
        if (scrollAreaRef.current && isNearBottomRef.current) {
          scrollAreaRef.current.scrollTop = scrollAreaRef.current.scrollHeight;
        }
      });
    }
  }, [transcripts, isCallActive]);

  return (
    <div className="card-panel transcript-view-panel">
      <div className="panel-header-row">
        <h2 className="panel-title">Real-Time Supervisor Transcript Feed</h2>
        <span className="transcript-count-badge">
          {transcripts.length} {transcripts.length === 1 ? 'Turn' : 'Turns'}
        </span>
      </div>

      <div
        ref={scrollAreaRef}
        onScroll={handleScroll}
        className="transcript-scroll-area"
        tabIndex={0}
        aria-label="Supervisor Conversation Transcript"
      >
        {transcripts.length === 0 ? (
          <div className="transcript-empty-state">
            <span className="empty-icon">🎧</span>
            <p className="empty-text">No conversation turns recorded yet.</p>
            <span className="empty-subtext">
              Connect to an ongoing call to stream bidirectional conversation and private coaching history.
            </span>
          </div>
        ) : (
          <div className="transcript-list">
            {transcripts.map((entry, index) => {
              const isUser = entry.role === 'USER';
              const isSupervisor = entry.role === 'SUPERVISOR' || entry.isPrivate;
              const _isAgent = entry.role === 'AGENT';

              let rowClass = 'agent-turn';
              let badgeLabel = 'AGENT';
              let badgeClass = 'tag-agent';

              if (isSupervisor) {
                rowClass = 'supervisor-turn';
                badgeLabel = 'SUPERVISOR WHISPER';
                badgeClass = 'tag-supervisor';
              } else if (isUser) {
                rowClass = 'user-turn';
                badgeLabel = 'USER';
                badgeClass = 'tag-user';
              }

              return (
                <div
                  key={entry.id || index}
                  className={`transcript-message-row ${rowClass}`}
                >
                  <div className="message-bubble">
                    <div className="message-meta-header">
                      <span className={`speaker-tag ${badgeClass}`}>
                        {badgeLabel}
                      </span>
                      {isSupervisor && (
                        <span className="private-confidential-tag">
                          🔒 Hidden from Customer
                        </span>
                      )}
                      {entry.time && <span className="timestamp-text">{entry.time}</span>}
                    </div>
                    <div className="message-content-text">{entry.text}</div>
                  </div>
                </div>
              );
            })}
          </div>
        )}
      </div>
    </div>
  );
}
