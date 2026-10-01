import React, { useEffect, useRef } from 'react';

export function TranscriptView({ transcripts, isCallActive = true }) {
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

    // Never auto-scroll if the call is ended or inactive
    if (!isCallActive) return;

    const currentLen = transcripts.length;
    const currentLastText = currentLen > 0 ? transcripts[currentLen - 1].text : '';

    const isNewTurn = currentLen !== prevTranscriptsLengthRef.current;
    const isNewContent = currentLastText !== prevLastTextRef.current;

    prevTranscriptsLengthRef.current = currentLen;
    prevLastTextRef.current = currentLastText;

    // Auto-scroll ONLY when new content arrives AND user is already near bottom
    if ((isNewTurn || isNewContent) && isNearBottomRef.current) {
      requestAnimationFrame(() => {
        if (scrollAreaRef.current && isNearBottomRef.current) {
          scrollAreaRef.current.scrollTop = scrollAreaRef.current.scrollHeight;
        }
      });
    }
  }, [transcripts, isCallActive]);

  return (
    <div className="transcript-card">
      <div className="transcript-header">
        <h2 className="transcript-title">Live Conversation Transcript</h2>
        <span className="transcript-badge">
          {transcripts.length} {transcripts.length === 1 ? 'Turn' : 'Turns'}
        </span>
      </div>

      <div
        ref={scrollAreaRef}
        onScroll={handleScroll}
        className="transcript-scroll-area"
        tabIndex={0}
        aria-label="Conversation Transcript"
      >
        {transcripts.length === 0 ? (
          <div className="transcript-empty-state">
            <span className="empty-icon">💬</span>
            <p className="empty-text">No conversation turns yet.</p>
            <span className="empty-subtext">
              Select an agent and start a call to speak with the Voice AI assistant.
            </span>
          </div>
        ) : (
          <div className="transcript-list">
            {transcripts.map((entry, index) => {
              const isUser = entry.role === 'USER';
              return (
                <div
                  key={entry.id || index}
                  className={`transcript-message-row ${isUser ? 'user-turn' : 'agent-turn'}`}
                >
                  <div className="message-bubble">
                    <div className="message-meta-header">
                      {/* Explicitly displays User or Agent on every visible line */}
                      <span className={`speaker-tag ${isUser ? 'tag-user' : 'tag-agent'}`}>
                        {isUser ? 'USER' : 'AGENT'}
                      </span>
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
