import React, { useState, useEffect } from 'react';
import { fetchAgents } from './services/api';
import { useLiveKitCall, CallStatus } from './hooks/useLiveKitCall';
import { AgentSelector } from './components/AgentSelector';
import { StatusHeader } from './components/StatusHeader';
import { CallControls } from './components/CallControls';
import { AudioWaveform } from './components/AudioWaveform';
import { TranscriptView } from './components/TranscriptView';
import { ErrorBanner } from './components/ErrorBanner';

export function App() {
  const [agents, setAgents] = useState([]);
  const [selectedAgentId, setSelectedAgentId] = useState('');
  const [loadingAgents, setLoadingAgents] = useState(true);
  const [agentLoadError, setAgentLoadError] = useState(null);

  const {
    callStatus,
    callId,
    roomName,
    micEnabled,
    isMuted,
    agentSpeaking,
    userSpeaking,
    transcripts,
    errorMessage,
    setErrorMessage,
    startCall,
    endCall,
    toggleMute,
    audioContainerRef,
  } = useLiveKitCall();

  // Load agents on initial page mount
  useEffect(() => {
    async function loadAgents() {
      try {
        setLoadingAgents(true);
        setAgentLoadError(null);
        const data = await fetchAgents();
        setAgents(data);
        if (data.length > 0) {
          // Default to Acme Support Agent if present, otherwise first available
          const acmeAgent = data.find((a) => a.name.includes('Acme'));
          setSelectedAgentId(acmeAgent ? acmeAgent.id : data[0].id);
        }
      } catch (err) {
        console.error('Failed to load agents:', err);
        setAgentLoadError('Could not load support agents from server. Ensure backend is running.');
      } finally {
        setLoadingAgents(false);
      }
    }

    loadAgents();
  }, []);

  const handleStartCall = () => {
    if (!selectedAgentId) {
      setErrorMessage('Please select an agent before starting a call.');
      return;
    }
    startCall(selectedAgentId, 'Customer User');
  };

  const isCallInProgress =
    callStatus === CallStatus.CONNECTED ||
    callStatus === CallStatus.CONNECTING ||
    callStatus === CallStatus.INITIALIZING;

  return (
    <div className="app-layout">
      {/* Audio element container for WebRTC playback */}
      <div
        ref={audioContainerRef}
        style={{
          position: 'absolute',
          width: 0,
          height: 0,
          overflow: 'hidden',
        }}
        aria-hidden="true"
      />

      {/* Main Header */}
      <header className="app-header">
        <div className="header-brand">
          <div className="brand-logo-icon">🎙️</div>
          <div className="brand-titles">
            <h1 className="brand-title">Acme Voice Support</h1>
            <p className="brand-subtitle">Real-time Conversational Voice AI Assistant</p>
          </div>
        </div>
        <StatusHeader
          callStatus={callStatus}
          callId={callId}
          roomName={roomName}
        />
      </header>

      {/* Error Notifications */}
      <div className="alerts-section">
        <ErrorBanner message={agentLoadError} onDismiss={() => setAgentLoadError(null)} />
        <ErrorBanner message={errorMessage} onDismiss={() => setErrorMessage(null)} />
      </div>

      {/* Primary Interaction Grid */}
      <main className="main-content-grid">
        {/* Left Column: Call Setup & Controls */}
        <section className="left-panel">
          <AgentSelector
            agents={agents}
            selectedAgentId={selectedAgentId}
            onSelect={setSelectedAgentId}
            disabled={isCallInProgress || loadingAgents}
          />

          {isCallInProgress && (
            <AudioWaveform
              agentSpeaking={agentSpeaking}
              userSpeaking={userSpeaking}
              micEnabled={micEnabled}
              isMuted={isMuted}
            />
          )}

          <CallControls
            callStatus={callStatus}
            onStartCall={handleStartCall}
            onEndCall={endCall}
            onToggleMute={toggleMute}
            isMuted={isMuted}
            micEnabled={micEnabled}
            disabled={loadingAgents || !selectedAgentId}
          />

          <div className="instructions-card">
            <h3 className="instructions-title">Customer Guide</h3>
            <ul className="instructions-list">
              <li>Click <strong>Start Voice Call</strong> to begin talking.</li>
              <li>Your microphone will automatically connect to LiveKit.</li>
              <li>The agent will announce that the call is recorded.</li>
              <li>Speak naturally; you can interrupt the agent at any time (barge-in).</li>
            </ul>
          </div>
        </section>

        {/* Right Column: Live Conversation Transcript */}
        <section className="right-panel">
          <TranscriptView transcripts={transcripts} isCallActive={isCallInProgress} />
        </section>
      </main>

      {/* Footer */}
      <footer className="app-footer">
        <div className="footer-content">
          <span>LiveKit SFU (WebRTC) • Self-Hosted Voice AI Pipeline</span>
          <span className="privacy-badge">🔒 Private & Secure</span>
        </div>
      </footer>
    </div>
  );
}

export default App;
