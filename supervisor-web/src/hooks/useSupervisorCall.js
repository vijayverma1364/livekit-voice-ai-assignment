import { useState, useRef, useEffect, useCallback } from 'react';
import { Room, RoomEvent, Track } from 'livekit-client';
import { fetchSupervisorToken, fetchSupervisorCallDetails } from '../services/api';

export const SupervisorCallStatus = {
  IDLE: 'IDLE',
  CONNECTING: 'CONNECTING',
  LISTENING: 'LISTENING',
  DISCONNECTING: 'DISCONNECTING',
  ENDED: 'ENDED',
  ERROR: 'ERROR',
};

/**
 * Custom React hook for managing supervisor stealth listening and private whisper dispatch.
 */
export function useSupervisorCall() {
  const [callStatus, setCallStatus] = useState(SupervisorCallStatus.IDLE);
  const [callId, setCallId] = useState(null);
  const [roomName, setRoomName] = useState(null);
  const [customerSpeaking, setCustomerSpeaking] = useState(false);
  const [agentSpeaking, setAgentSpeaking] = useState(false);
  const [transcripts, setTranscripts] = useState([]);
  const [errorMessage, setErrorMessage] = useState(null);
  const [lastWhisperSent, setLastWhisperSent] = useState(null);

  const roomRef = useRef(null);
  const audioContainerRef = useRef(null);
  const pollTimerRef = useRef(null);

  // Sync transcripts with backend (include_private=true to show supervisor whispers)
  const syncTranscripts = useCallback(async (activeCallId) => {
    if (!activeCallId) return;
    try {
      const details = await fetchSupervisorCallDetails(activeCallId);
      const rawList = details?.transcripts || details?.transcript || [];
      if (Array.isArray(rawList) && rawList.length > 0) {
        const mapped = rawList.map((t) => {
          let role = 'USER';
          if (t.speaker === 'agent') role = 'AGENT';
          else if (t.speaker === 'supervisor') role = 'SUPERVISOR';

          return {
            id: t.id || `${t.relative_time_ms}-${t.speaker}`,
            role,
            speaker: t.speaker,
            text: t.text,
            isPrivate: t.is_private,
            time: `+${(t.relative_time_ms / 1000).toFixed(1)}s`,
          };
        });
        // Deduplicate consecutive identical utterances
        const deduplicated = [];
        for (const item of mapped) {
          const prevItem = deduplicated[deduplicated.length - 1];
          if (prevItem && prevItem.role === item.role && prevItem.text.trim() === item.text.trim()) {
            continue;
          }
          deduplicated.push(item);
        }
        setTranscripts(deduplicated);
      }
    } catch (err) {
      console.warn('Supervisor transcript sync error:', err.message);
    }
  }, []);

  // Connect to active call as stealth supervisor
  const connectToCall = useCallback(async (targetCallId, supervisorName = 'Supervisor') => {
    if (!targetCallId) {
      setErrorMessage('Please select or enter an active Call ID.');
      return;
    }

    setErrorMessage(null);
    setCallStatus(SupervisorCallStatus.CONNECTING);
    setTranscripts([]);
    setCallId(targetCallId);

    try {
      // Fetch restricted supervisor token
      const tokenData = await fetchSupervisorToken(targetCallId, supervisorName);
      setRoomName(tokenData.room_name);

      // Initialize room connection
      const room = new Room({
        adaptiveStream: true,
        dynacast: true,
      });
      roomRef.current = room;

      // Handle remote audio tracks (customer and agent audio)
      room.on(RoomEvent.TrackSubscribed, (track, _publication, _participant) => {
        if (track.kind === Track.Kind.Audio) {
          const audioElement = track.attach();
          audioElement.id = `supervisor-audio-${track.sid}`;
          audioElement.autoplay = true;

          if (audioContainerRef.current) {
            audioContainerRef.current.appendChild(audioElement);
          } else {
            document.body.appendChild(audioElement);
          }
          const playPromise = audioElement.play();
          if (playPromise !== undefined) {
            playPromise.catch((err) => {
              console.warn('[Supervisor] Audio autoplay blocked:', err);
            });
          }
          console.log('[Supervisor] Subscribed to audio track:', track.sid);
        }
      });

      room.on(RoomEvent.TrackUnsubscribed, (track) => {
        track.detach().forEach((el) => el.remove());
        console.log('[Supervisor] Detached audio track:', track.sid);
      });

      // Active speaker monitoring for audio levels
      room.on(RoomEvent.ActiveSpeakersChanged, (speakers) => {
        let isAgent = false;
        let isCustomer = false;

        speakers.forEach((speaker) => {
          // Identify agent vs customer by identity
          const identity = (speaker.identity || '').toLowerCase();
          if (identity.includes('agent') || identity.includes('assistant')) {
            isAgent = true;
          } else {
            isCustomer = true;
          }
        });

        setAgentSpeaking(isAgent);
        setCustomerSpeaking(isCustomer);
      });

      // Room disconnect event
      room.on(RoomEvent.Disconnected, (reason) => {
        console.log('[Supervisor] Room disconnected:', reason);
        setCallStatus(SupervisorCallStatus.ENDED);
        setCustomerSpeaking(false);
        setAgentSpeaking(false);
      });

      // Connect to LiveKit room with supervisor token
      const wsUrl = tokenData.livekit_url || import.meta.env.VITE_LIVEKIT_URL || 'ws://localhost:7880';
      console.log('[Supervisor] Connecting stealth to:', wsUrl, 'Room:', tokenData.room_name);
      await room.connect(wsUrl, tokenData.livekit_token);
      console.log('[Supervisor] Stealth connected successfully!');

      setCallStatus(SupervisorCallStatus.LISTENING);

      // Start periodic transcript polling
      pollTimerRef.current = setInterval(() => {
        syncTranscripts(targetCallId);
      }, 1500);

      // Initial sync
      syncTranscripts(targetCallId);

    } catch (err) {
      console.error('[Supervisor] Connection error:', err);
      setErrorMessage(err.message || 'Failed to connect to call as supervisor.');
      setCallStatus(SupervisorCallStatus.ERROR);
      if (roomRef.current) {
        try {
          await roomRef.current.disconnect();
        } catch {
          // ignore cleanup disconnect error
        }
      }
    }
  }, [syncTranscripts]);

  // Send private coaching whisper via LiveKit WebRTC Data Channel
  const sendWhisper = useCallback(async (whisperText) => {
    const text = (whisperText || '').trim();
    if (!text) {
      throw new Error('Whisper text cannot be empty.');
    }

    if (!roomRef.current || callStatus !== SupervisorCallStatus.LISTENING) {
      throw new Error('Not connected to an active call.');
    }

    try {
      const payload = JSON.stringify({
        type: 'whisper',
        text: text,
      });
      const encoder = new TextEncoder();
      const data = encoder.encode(payload);

      // Publish over LiveKit Data Channel with topic 'whisper'
      await roomRef.current.localParticipant.publishData(data, {
        topic: 'whisper',
        reliable: true,
      });

      const timestamp = new Date().toLocaleTimeString([], { hour: '2-digit', minute: '2-digit', second: '2-digit' });
      setLastWhisperSent({
        text,
        timestamp,
      });

      // Optimistically append to local transcript view
      setTranscripts((prev) => [
        ...prev,
        {
          id: `whisper-${Date.now()}`,
          role: 'SUPERVISOR',
          speaker: 'supervisor',
          text,
          isPrivate: true,
          time: timestamp,
        },
      ]);

      console.log('[Supervisor] Dispatched private whisper:', text);
      return true;
    } catch (err) {
      console.error('[Supervisor] Failed to publish whisper data:', err);
      throw new Error(`Failed to deliver whisper: ${err.message}`);
    }
  }, [callStatus]);

  // Disconnect from call
  const disconnect = useCallback(async () => {
    if (pollTimerRef.current) {
      clearInterval(pollTimerRef.current);
      pollTimerRef.current = null;
    }

    setCallStatus(SupervisorCallStatus.DISCONNECTING);

    if (roomRef.current) {
      try {
        await roomRef.current.disconnect();
      } catch (err) {
        console.warn('[Supervisor] Disconnect warning:', err);
      }
      roomRef.current = null;
    }

    if (audioContainerRef.current) {
      audioContainerRef.current.innerHTML = '';
    }

    setCustomerSpeaking(false);
    setAgentSpeaking(false);
    setCallStatus(SupervisorCallStatus.ENDED);

    // Final sync
    if (callId) {
      setTimeout(() => syncTranscripts(callId), 600);
    }
  }, [callId, syncTranscripts]);

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
  };
}
