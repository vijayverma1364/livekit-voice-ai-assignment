import React, { useState, useEffect } from 'react';
import { fetchCalls } from './services/api';
import { useSupervisorCall, SupervisorCallStatus } from './hooks/useSupervisorCall';
import { StatusHeader } from './components/StatusHeader';
import { ActiveCallsSelector } from './components/ActiveCallsSelector';
import { AudioMonitor } from './components/AudioMonitor';
import { WhisperConsole } from './components/WhisperConsole';
import { LiveTranscriptView } from './components/LiveTranscriptView';
import { ErrorBanner } from './components/ErrorBanner';

export function App() {
  const [calls, setCalls] = useState([]);
  const [selectedCallId, setSelectedCallId] = useState('');
  const [loadingCalls, setLoadingCalls] = useState(true);
  const [callListError, setCallListError] = useState(null);

  const {
    callStatus,
    callId,
    roomName,
    customerSpeaking,
    agentSpeaking,
    transcripts,
    errorMessage,
    setErrorMessage,
    lastWhisperSent,
    connectToCall,
    disconnect,
    sendWhisper,
    audioContainerRef,
  } = useSupervisorCall();

  // Load active and recent calls from backend
  const loadCalls = async (silent = false) => {
    try {
      if (!silent) setLoadingCalls(true);
      setCallListError(null);
      const data = await fetchCalls(50);
      setCalls(data);

      if (data.length > 0) {
        const active = data.find((c) => c.status === 'ACTIVE');
        if (active) {
          setSelectedCallId((prev) => {
            const currentActive = data.some((c) => c.id === prev && c.status === 'ACTIVE');
            return currentActive ? prev : active.id;
          });
        } else if (!selectedCallId) {
          setSelectedCallId(data[0].id);
        }
      }
    } catch (err) {
      if (!silent) {
        console.error('Failed to load calls:', err);
        setCallListError('Could not load calls from backend. Ensure FastAPI server is running on port 8000.');
      }
    } finally {
      if (!silent) setLoadingCalls(false);
    }
  };

  useEffect(() => {
    loadCalls(false);
    const interval = setInterval(() => {
      if (callStatus === SupervisorCallStatus.IDLE) {
        loadCalls(true);
      }
    }, 2000);
    return () => clearInterval(interval);
  }, [callStatus]);

  const handleConnect = (targetId) => {
    const idToUse = targetId || selectedCallId;
    if (!idToUse) {
      setErrorMessage('Please select or specify a valid Call ID.');
      return;
    }
    connectToCall(idToUse, 'Supervisor Lead');
  };

  const isListening = callStatus === SupervisorCallStatus.LISTENING;

  return (
    <div className="supervisor-app-layout">
      {/* Audio element container for incoming WebRTC streams (positioned off-screen) */}
      <div
        ref={audioContainerRef}
        style={{
          position: 'fixed',
          left: '-9999px',
          top: '-9999px',
          width: '1px',
          height: '1px',
          opacity: 0,
          pointerEvents: 'none',
        }}
        aria-hidden="true"
      />

      {/* Header */}
      <header className="supervisor-header">
        <div className="brand-group">
          <div className="brand-badge-icon">🛡️</div>
          <div className="brand-text-block">
            <div className="brand-title-row">
              <h1 className="brand-title">Supervisor Stealth Console</h1>
              <span className="livekit-version-pill">LiveKit SFU WebRTC</span>
            </div>
            <p className="brand-subtitle">
              Live Bidirectional Eavesdrop & Real-Time Private Data Channel Coaching
            </p>
          </div>
        </div>

        <StatusHeader
          callStatus={callStatus}
          callId={callId}
          roomName={roomName}
          onDisconnect={disconnect}
        />
      </header>

      {/* Alerts */}
      <div className="alerts-container">
        <ErrorBanner message={callListError} onDismiss={() => setCallListError(null)} />
        <ErrorBanner message={errorMessage} onDismiss={() => setErrorMessage(null)} />
      </div>

      {/* Main Grid */}
      <main className="supervisor-main-grid">
        {/* Left Column: Call Discovery, Audio Monitor & Whisper Tool */}
        <section className="left-column">
          <ActiveCallsSelector
            calls={calls}
            selectedCallId={selectedCallId}
            onSelectCallId={setSelectedCallId}
            onConnect={handleConnect}
            callStatus={callStatus}
            loadingCalls={loadingCalls}
            onRefreshCalls={loadCalls}
          />

          <AudioMonitor
            customerSpeaking={customerSpeaking}
            agentSpeaking={agentSpeaking}
            isListening={isListening}
          />

          <WhisperConsole
            onSendWhisper={sendWhisper}
            isListening={isListening}
            lastWhisperSent={lastWhisperSent}
          />
        </section>

        {/* Right Column: Real-Time Full Transcript Feed */}
        <section className="right-column">
          <LiveTranscriptView transcripts={transcripts} isCallActive={isListening} />
        </section>
      </main>

      {/* Footer */}
      <footer className="supervisor-footer">
        <div className="footer-status-row">
          <span>
            Port 3001 • Stealth Privileges: <code>can_publish=false, can_subscribe=true, hidden=true</code>
          </span>
          <span className="stealth-indicator-tag">🔒 Private Coaching Channel</span>
        </div>
      </footer>
    </div>
  );
}
