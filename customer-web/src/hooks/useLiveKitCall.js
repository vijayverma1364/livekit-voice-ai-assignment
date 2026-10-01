import { useState, useRef, useEffect, useCallback } from 'react';
import { Room, RoomEvent, Track } from 'livekit-client';
import { createCall, fetchCallDetails } from '../services/api';

export const CallStatus = {
  IDLE: 'IDLE',
  INITIALIZING: 'INITIALIZING',
  CONNECTING: 'CONNECTING',
  CONNECTED: 'CONNECTED',
  DISCONNECTING: 'DISCONNECTING',
  ENDED: 'ENDED',
  ERROR: 'ERROR',
};

/**
 * Custom React hook managing LiveKit WebRTC audio connection,
 * microphone publishing, agent audio playback, and live transcripts.
 */
export function useLiveKitCall() {
  const [callStatus, setCallStatus] = useState(CallStatus.IDLE);
  const [callId, setCallId] = useState(null);
  const [roomName, setRoomName] = useState(null);
  const [micEnabled, setMicEnabled] = useState(false);
  const [isMuted, setIsMuted] = useState(false);
  const [agentSpeaking, setAgentSpeaking] = useState(false);
  const [userSpeaking, setUserSpeaking] = useState(false);
  const [transcripts, setTranscripts] = useState([]);
  const [errorMessage, setErrorMessage] = useState(null);

  const roomRef = useRef(null);
  const audioContainerRef = useRef(null);
  const pollTimerRef = useRef(null);

  // Helper to append or stream-update a transcript entry cleanly in-place
  const appendTranscript = useCallback((speakerRole, text, segmentId = null, isFinal = false, timestamp = null) => {
    if (!text || !text.trim()) return;

    // Normalize role to USER or AGENT
    const role = speakerRole.toLowerCase() === 'agent' || speakerRole.toLowerCase() === 'assistant'
      ? 'AGENT'
      : 'USER';
    const cleanText = text.trim();

    setTranscripts((prev) => {
      // Never allow a duplicate initial greeting
      const isGreeting = role === 'AGENT' && cleanText.toLowerCase().includes('thank you for calling acme support');
      if (isGreeting && prev.some((p) => p.role === 'AGENT' && p.text.toLowerCase().includes('thank you for calling acme support'))) {
        return prev;
      }

      if (prev.length === 0) {
        return [
          {
            id: segmentId || `live-${Date.now()}`,
            segmentId,
            role,
            text: cleanText,
            time: timestamp || new Date().toLocaleTimeString([], { hour: '2-digit', minute: '2-digit', second: '2-digit' }),
            isFinal: Boolean(isFinal),
          },
        ];
      }

      const lastIdx = prev.length - 1;
      const last = prev[lastIdx];

      // If exact duplicate of last entry, ignore
      if (last.role === role && last.text.toLowerCase() === cleanText.toLowerCase()) {
        return prev;
      }

      // Merge sequential chunks for the active speaker turn
      if (last.role === role) {
        let mergedText = last.text;

        if (cleanText.toLowerCase().startsWith(last.text.toLowerCase())) {
          mergedText = cleanText;
        } else if (last.text.toLowerCase().startsWith(cleanText.toLowerCase())) {
          mergedText = last.text;
        } else if (last.text.toLowerCase().includes(cleanText.toLowerCase())) {
          mergedText = last.text;
        } else if (cleanText.toLowerCase().includes(last.text.toLowerCase())) {
          mergedText = cleanText;
        } else if (segmentId && last.segmentId && segmentId === last.segmentId) {
          mergedText = cleanText;
        } else {
          // Additional sentence or segment in the same continuous turn
          mergedText = `${last.text} ${cleanText}`;
        }

        const updated = [...prev];
        updated[lastIdx] = {
          ...last,
          text: mergedText,
          isFinal: Boolean(isFinal || last.isFinal),
          segmentId: segmentId || last.segmentId,
        };
        return updated;
      }

      // Brand new speaker turn (USER <-> AGENT transition)
      return [
        ...prev,
        {
          id: segmentId || `live-${Date.now()}-${Math.random().toString(36).substr(2, 6)}`,
          segmentId,
          role,
          text: cleanText,
          time: timestamp || new Date().toLocaleTimeString([], { hour: '2-digit', minute: '2-digit', second: '2-digit' }),
          isFinal: Boolean(isFinal),
        },
      ];
    });
  }, []);

  // Sync transcripts from PostgreSQL backend periodically
  const syncTranscriptsFromBackend = useCallback(async (activeCallId) => {
    if (!activeCallId) return;
    try {
      const details = await fetchCallDetails(activeCallId);
      const rawList = details?.transcripts || details?.transcript || [];
      if (Array.isArray(rawList) && rawList.length > 0) {
        // Map backend transcripts to client format (guaranteeing only USER or AGENT)
        const mapped = rawList
          .filter((t) => !t.is_private && (t.speaker === 'customer' || t.speaker === 'user' || t.speaker === 'agent'))
          .map((t) => ({
            id: t.id || `${t.relative_time_ms}-${t.speaker}`,
            role: (t.speaker === 'customer' || t.speaker === 'user') ? 'USER' : 'AGENT',
            text: t.text,
            time: `+${(t.relative_time_ms / 1000).toFixed(1)}s`,
          }));

        // Deduplicate consecutive identical utterances
        const deduplicated = [];
        for (const item of mapped) {
          const prevItem = deduplicated[deduplicated.length - 1];
          if (prevItem && prevItem.role === item.role && prevItem.text.trim() === item.text.trim()) {
            continue;
          }
          deduplicated.push(item);
        }

        setTranscripts((prev) => {
          if (deduplicated.length >= prev.length) {
            return deduplicated;
          }
          const mappedTexts = new Set(deduplicated.map((m) => m.text.trim()));
          const extra = prev.filter((p) => !mappedTexts.has(p.text.trim()));
          return [...deduplicated, ...extra];
        });
      }
    } catch (err) {
      console.warn('Transcript poll error:', err.message);
    }
  }, []);

  // Start Voice Call
  const startCall = useCallback(async (agentId, customerName = 'Customer') => {
    // Clear any previous poll timer to avoid race conditions
    if (pollTimerRef.current) {
      clearInterval(pollTimerRef.current);
      pollTimerRef.current = null;
    }

    setErrorMessage(null);
    setCallStatus(CallStatus.INITIALIZING);
    setTranscripts([]);

    let createdCallId = null;

    try {
      // Request call session and credentials from backend
      const callData = await createCall(agentId, customerName);
      createdCallId = callData.call_id;
      setCallId(callData.call_id);
      setRoomName(callData.room_name);
      setCallStatus(CallStatus.CONNECTING);

      // Set up room with AEC and noise suppression
      const room = new Room({
        adaptiveStream: true,
        dynacast: true,
        audioCaptureDefaults: {
          echoCancellation: true,
          noiseSuppression: true,
          autoGainControl: true,
        },
      });
      roomRef.current = room;

      // Handle Remote Audio Tracks (Agent Voice Playback)
      room.on(RoomEvent.TrackSubscribed, (track, _publication, _participant) => {
        if (track.kind === Track.Kind.Audio) {
          const audioElement = track.attach();
          audioElement.id = `audio-track-${track.sid}`;
          audioElement.autoplay = true;

          // Attach to container for playback
          if (audioContainerRef.current) {
            audioContainerRef.current.appendChild(audioElement);
          } else {
            document.body.appendChild(audioElement);
          }

          // Explicitly invoke play() to guarantee browser playback
          const playPromise = audioElement.play();
          if (playPromise !== undefined) {
            playPromise.catch((err) => {
              console.warn('[LiveKit] Browser audio autoplay blocked, user interaction required:', err);
            });
          }
          console.log('[LiveKit] Subscribed and attached agent audio track:', track.sid);
        }
      });

      room.on(RoomEvent.TrackUnsubscribed, (track) => {
        track.detach().forEach((el) => el.remove());
        console.log('[LiveKit] Detached audio track:', track.sid);
      });

      // Active Speaker Detection for Visual Feedback
      room.on(RoomEvent.ActiveSpeakersChanged, (speakers) => {
        let isAgentSpeaking = false;
        let isUserSpeaking = false;

        speakers.forEach((speaker) => {
          if (speaker === room.localParticipant) {
            isUserSpeaking = true;
          } else {
            isAgentSpeaking = true;
          }
        });

        setUserSpeaking(isUserSpeaking);
        setAgentSpeaking(isAgentSpeaking);

        // Ensure agent audio elements are playing when agent speaks
        if (isAgentSpeaking && audioContainerRef.current) {
          const audios = audioContainerRef.current.querySelectorAll('audio');
          audios.forEach((el) => {
            if (el.paused) {
              el.play().catch(() => {});
            }
          });
        }
      });

      // Listen for LiveKit native transcription stream
      room.on(RoomEvent.TranscriptionReceived, (segments, participant) => {
        if (!segments || !Array.isArray(segments)) return;
        const isUser = participant === room.localParticipant;
        for (const seg of segments) {
          if (seg.text && seg.text.trim()) {
            appendTranscript(isUser ? 'USER' : 'AGENT', seg.text.trim(), seg.id, seg.final);
          }
        }
      });

      // Listen for LiveKit Data Channel transcription messages
      room.on(RoomEvent.DataReceived, (payload, participant, kind, topic) => {
        try {
          const textDecoder = new TextDecoder();
          const str = textDecoder.decode(payload);
          const data = JSON.parse(str);

          // Only accept transcription topic messages
          if (topic === 'lk.transcription' || data.text) {
            const speakerRole = (participant === room.localParticipant || data.speaker === 'user')
              ? 'USER'
              : 'AGENT';
            appendTranscript(speakerRole, data.text || str, data.id, data.final);
          }
        } catch {
          // If not JSON, ignore raw binary or other topics
        }
      });

      // Handle Disconnection
      room.on(RoomEvent.Disconnected, (reason) => {
        console.log('[LiveKit] Room disconnected:', reason);
        setCallStatus(CallStatus.ENDED);
        setMicEnabled(false);
        setUserSpeaking(false);
        setAgentSpeaking(false);
      });

      // Connect to LiveKit room
      const wsUrl = callData.livekit_url || import.meta.env.VITE_LIVEKIT_URL || 'ws://localhost:7880';
      console.log('[LiveKit] Connecting to:', wsUrl, 'Room:', callData.room_name);
      await room.connect(wsUrl, callData.livekit_token);
      console.log('[LiveKit] Connected successfully!');

      // Enable local microphone
      try {
        await room.localParticipant.setMicrophoneEnabled(true, {
          echoCancellation: true,
          noiseSuppression: true,
          autoGainControl: true,
        });
        setMicEnabled(true);
        setIsMuted(false);
        console.log('[LiveKit] Microphone published with AEC.');
      } catch (micErr) {
        console.error('[LiveKit] Microphone access error:', micErr);
        throw new Error('Microphone permission denied or device not found. Please allow microphone access in your browser.');
      }

      setCallStatus(CallStatus.CONNECTED);

      // Start polling transcript updates from backend
      syncTranscriptsFromBackend(createdCallId);
      pollTimerRef.current = setInterval(() => {
        syncTranscriptsFromBackend(createdCallId);
      }, 1000);

    } catch (err) {
      console.error('[useLiveKitCall] Call setup failed:', err);
      setErrorMessage(err.message || 'Failed to establish call connection.');
      setCallStatus(CallStatus.ERROR);
      if (roomRef.current) {
        try {
          await roomRef.current.disconnect();
        } catch {
          // ignore disconnect error during failure cleanup
        }
      }
    }
  }, [appendTranscript, syncTranscriptsFromBackend]);

  // End active call
  const endCall = useCallback(async () => {
    if (pollTimerRef.current) {
      clearInterval(pollTimerRef.current);
      pollTimerRef.current = null;
    }

    setCallStatus(CallStatus.DISCONNECTING);

    if (roomRef.current) {
      try {
        await roomRef.current.disconnect();
      } catch (err) {
        console.warn('Error during disconnect:', err);
      }
      roomRef.current = null;
    }

    // Clean up detached audio elements
    if (audioContainerRef.current) {
      audioContainerRef.current.innerHTML = '';
    }

    setMicEnabled(false);
    setUserSpeaking(false);
    setAgentSpeaking(false);
    setCallStatus(CallStatus.ENDED);

    // Final transcript sync after ending call
    if (callId) {
      setTimeout(() => syncTranscriptsFromBackend(callId), 800);
    }
  }, [callId, syncTranscriptsFromBackend]);

  // Toggle Microphone Mute
  const toggleMute = useCallback(async () => {
    if (!roomRef.current || callStatus !== CallStatus.CONNECTED) return;
    try {
      const nextMuted = !isMuted;
      await roomRef.current.localParticipant.setMicrophoneEnabled(!nextMuted);
      setIsMuted(nextMuted);
      setMicEnabled(!nextMuted);
    } catch (err) {
      console.error('Failed to toggle microphone mute:', err);
    }
  }, [isMuted, callStatus]);

  // Cleanup on unmount
  useEffect(() => {
    return () => {
      if (pollTimerRef.current) {
        clearInterval(pollTimerRef.current);
      }
      if (roomRef.current) {
        roomRef.current.disconnect();
      }
    };
  }, []);

  return {
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
  };
}
