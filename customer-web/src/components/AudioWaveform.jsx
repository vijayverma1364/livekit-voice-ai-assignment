import React from 'react';

export function AudioWaveform({ agentSpeaking, userSpeaking, micEnabled, isMuted }) {
  let activeSpeakerText = 'Listening...';
  let indicatorClass = 'idle';

  if (agentSpeaking) {
    activeSpeakerText = 'Agent is speaking';
    indicatorClass = 'agent-speaking';
  } else if (userSpeaking && !isMuted) {
    activeSpeakerText = 'You are speaking';
    indicatorClass = 'user-speaking';
  } else if (isMuted) {
    activeSpeakerText = 'Microphone muted';
    indicatorClass = 'muted';
  } else if (!micEnabled) {
    activeSpeakerText = 'Microphone connecting...';
    indicatorClass = 'idle';
  }

  return (
    <div className={`audio-waveform-card ${indicatorClass}`}>
      <div className="wave-bars-container">
        <span className="wave-bar bar-1"></span>
        <span className="wave-bar bar-2"></span>
        <span className="wave-bar bar-3"></span>
        <span className="wave-bar bar-4"></span>
        <span className="wave-bar bar-5"></span>
      </div>
      <div className="speaker-label">{activeSpeakerText}</div>
    </div>
  );
}
