import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { renderHook, act } from '@testing-library/react';
import { useSupervisorCall, SupervisorCallStatus } from '../hooks/useSupervisorCall';
import * as api from '../services/api';

// Mock livekit-client Room
vi.mock('livekit-client', () => {
  class MockLocalParticipant {
    publishData = vi.fn(async (_data, _options) => {
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
      Disconnected: 'disconnected',
    },
    Track: {
      Kind: {
        Audio: 'audio',
      },
    },
  };
});

describe('useSupervisorCall Hook', () => {
  beforeEach(() => {
    vi.restoreAllMocks();
  });

  afterEach(() => {
    vi.clearAllTimers();
  });

  it('initializes in IDLE state with empty transcripts', () => {
    const { result } = renderHook(() => useSupervisorCall());

    expect(result.current.callStatus).toBe(SupervisorCallStatus.IDLE);
    expect(result.current.callId).toBeNull();
    expect(result.current.roomName).toBeNull();
    expect(result.current.transcripts).toEqual([]);
    expect(result.current.errorMessage).toBeNull();
  });

  it('connects to active call in stealth mode and transitions to LISTENING', async () => {
    vi.spyOn(api, 'fetchSupervisorToken').mockResolvedValue({
      call_id: 'call-uuid-1',
      room_name: 'call-room-1',
      supervisor_identity: 'supervisor-1',
      livekit_url: 'ws://localhost:7880',
      livekit_token: 'fake-supervisor-jwt',
    });

    vi.spyOn(api, 'fetchSupervisorCallDetails').mockResolvedValue({
      id: 'call-uuid-1',
      status: 'ACTIVE',
      transcripts: [],
    });

    const { result } = renderHook(() => useSupervisorCall());

    await act(async () => {
      await result.current.connectToCall('call-uuid-1', 'Lead Supervisor');
    });

    expect(result.current.callStatus).toBe(SupervisorCallStatus.LISTENING);
    expect(result.current.callId).toBe('call-uuid-1');
    expect(result.current.roomName).toBe('call-room-1');
  });

  it('dispatches whisper to agent via data channel on topic whisper', async () => {
    vi.spyOn(api, 'fetchSupervisorToken').mockResolvedValue({
      call_id: 'call-uuid-1',
      room_name: 'call-room-1',
      livekit_url: 'ws://localhost:7880',
      livekit_token: 'fake-supervisor-jwt',
    });

    vi.spyOn(api, 'fetchSupervisorCallDetails').mockResolvedValue({
      id: 'call-uuid-1',
      status: 'ACTIVE',
      transcripts: [],
    });

    const { result } = renderHook(() => useSupervisorCall());

    await act(async () => {
      await result.current.connectToCall('call-uuid-1');
    });

    await act(async () => {
      await result.current.sendWhisper('Offer a 10% discount.');
    });

    expect(result.current.lastWhisperSent).toBeDefined();
    expect(result.current.lastWhisperSent.text).toBe('Offer a 10% discount.');

    // Check optimistic transcript addition
    const hasWhisper = result.current.transcripts.some(
      (t) => t.role === 'SUPERVISOR' && t.text === 'Offer a 10% discount.'
    );
    expect(hasWhisper).toBe(true);
  });

  it('disconnects and resets listening state', async () => {
    vi.spyOn(api, 'fetchSupervisorToken').mockResolvedValue({
      call_id: 'call-uuid-1',
      room_name: 'call-room-1',
      livekit_url: 'ws://localhost:7880',
      livekit_token: 'fake-supervisor-jwt',
    });

    const { result } = renderHook(() => useSupervisorCall());

    await act(async () => {
      await result.current.connectToCall('call-uuid-1');
    });

    await act(async () => {
      await result.current.disconnect();
    });

    expect(result.current.callStatus).toBe(SupervisorCallStatus.ENDED);
  });
});
