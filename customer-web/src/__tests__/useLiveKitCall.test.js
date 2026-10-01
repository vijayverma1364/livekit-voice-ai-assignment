import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { renderHook, act } from '@testing-library/react';
import { useLiveKitCall, CallStatus } from '../hooks/useLiveKitCall';
import * as api from '../services/api';

// Mock livekit-client Room
vi.mock('livekit-client', () => {
  class MockLocalParticipant {
    constructor() {
      this.isMicrophoneEnabled = false;
    }
    setMicrophoneEnabled = vi.fn(async (enabled) => {
      this.isMicrophoneEnabled = enabled;
      return true;
    });
  }

  class MockRoom {
    constructor() {
      this.localParticipant = new MockLocalParticipant();
      this.listeners = {};
    }
    on = vi.fn((event, cb) => {
      this.listeners[event] = cb;
    });
    connect = vi.fn(async () => true);
    disconnect = vi.fn(async () => true);
    emit = (event, ...args) => {
      if (this.listeners[event]) {
        this.listeners[event](...args);
      }
    };
  }

  return {
    Room: MockRoom,
    RoomEvent: {
      TrackSubscribed: 'trackSubscribed',
      TrackUnsubscribed: 'trackUnsubscribed',
      ActiveSpeakersChanged: 'activeSpeakersChanged',
      DataReceived: 'dataReceived',
      Disconnected: 'disconnected',
    },
    Track: {
      Kind: {
        Audio: 'audio',
      },
    },
  };
});

describe('useLiveKitCall Hook', () => {
  beforeEach(() => {
    vi.restoreAllMocks();
  });

  afterEach(() => {
    vi.clearAllTimers();
  });

  it('starts in IDLE state with mic disabled and empty transcripts', () => {
    const { result } = renderHook(() => useLiveKitCall());

    expect(result.current.callStatus).toBe(CallStatus.IDLE);
    expect(result.current.callId).toBeNull();
    expect(result.current.roomName).toBeNull();
    expect(result.current.micEnabled).toBe(false);
    expect(result.current.isMuted).toBe(false);
    expect(result.current.transcripts).toEqual([]);
    expect(result.current.errorMessage).toBeNull();
  });

  it('handles startCall, token connection, and microphone publishing', async () => {
    vi.spyOn(api, 'createCall').mockResolvedValue({
      call_id: 'test-call-123',
      agent_id: 'test-agent-456',
      room_name: 'call-test-call-123',
      status: 'CREATED',
      livekit_url: 'ws://localhost:7880',
      livekit_token: 'fake-jwt-token',
    });

    vi.spyOn(api, 'fetchCallDetails').mockResolvedValue({
      id: 'test-call-123',
      status: 'ACTIVE',
      transcripts: [
        { id: 't1', speaker: 'agent', text: 'Welcome to Acme Support', relative_time_ms: 200, is_private: false },
      ],
    });

    const { result } = renderHook(() => useLiveKitCall());

    await act(async () => {
      await result.current.startCall('test-agent-456', 'Customer Jane');
    });

    expect(result.current.callStatus).toBe(CallStatus.CONNECTED);
    expect(result.current.callId).toBe('test-call-123');
    expect(result.current.roomName).toBe('call-test-call-123');
    expect(result.current.micEnabled).toBe(true);
    expect(result.current.isMuted).toBe(false);
  });

  it('toggles microphone mute state during active call', async () => {
    vi.spyOn(api, 'createCall').mockResolvedValue({
      call_id: 'test-call-123',
      agent_id: 'test-agent-456',
      room_name: 'call-test-call-123',
      livekit_url: 'ws://localhost:7880',
      livekit_token: 'fake-jwt-token',
    });

    const { result } = renderHook(() => useLiveKitCall());

    await act(async () => {
      await result.current.startCall('test-agent-456');
    });

    expect(result.current.isMuted).toBe(false);

    // Mute
    await act(async () => {
      await result.current.toggleMute();
    });
    expect(result.current.isMuted).toBe(true);
    expect(result.current.micEnabled).toBe(false);

    // Unmute
    await act(async () => {
      await result.current.toggleMute();
    });
    expect(result.current.isMuted).toBe(false);
    expect(result.current.micEnabled).toBe(true);
  });

  it('handles endCall properly, disconnecting room and resetting mic', async () => {
    vi.spyOn(api, 'createCall').mockResolvedValue({
      call_id: 'test-call-123',
      agent_id: 'test-agent-456',
      room_name: 'call-test-call-123',
      livekit_url: 'ws://localhost:7880',
      livekit_token: 'fake-jwt-token',
    });

    vi.spyOn(api, 'fetchCallDetails').mockResolvedValue({
      id: 'test-call-123',
      status: 'ENDED',
      transcripts: [],
    });

    const { result } = renderHook(() => useLiveKitCall());

    await act(async () => {
      await result.current.startCall('test-agent-456');
    });

    await act(async () => {
      await result.current.endCall();
    });

    expect(result.current.callStatus).toBe(CallStatus.ENDED);
    expect(result.current.micEnabled).toBe(false);
  });

  it('transitions to ERROR state when createCall rejects', async () => {
    vi.spyOn(api, 'createCall').mockRejectedValue(new Error('Agent configuration invalid'));

    const { result } = renderHook(() => useLiveKitCall());

    await act(async () => {
      await result.current.startCall('bad-agent');
    });

    expect(result.current.callStatus).toBe(CallStatus.ERROR);
    expect(result.current.errorMessage).toBe('Agent configuration invalid');
    expect(result.current.micEnabled).toBe(false);
  });
});
