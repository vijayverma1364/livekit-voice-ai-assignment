import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { fetchCalls, fetchSupervisorToken, fetchSupervisorCallDetails } from '../services/api';

describe('Supervisor Web API Service', () => {
  const originalFetch = global.fetch;

  beforeEach(() => {
    vi.restoreAllMocks();
  });

  afterEach(() => {
    global.fetch = originalFetch;
  });

  describe('fetchCalls', () => {
    it('fetches call list from GET /calls successfully', async () => {
      const mockCalls = [
        { id: 'c1', room_name: 'call-c1', status: 'ACTIVE', created_at: '2026-09-30T10:00:00Z' },
      ];

      global.fetch = vi.fn().mockResolvedValue({
        ok: true,
        json: async () => mockCalls,
      });

      const result = await fetchCalls(10);
      expect(result).toEqual(mockCalls);
      expect(global.fetch).toHaveBeenCalledWith(
        expect.stringMatching(/\/calls\?limit=10$/),
        expect.objectContaining({
          headers: { 'Accept': 'application/json' },
        })
      );
    });

    it('throws error when GET /calls returns non-ok', async () => {
      global.fetch = vi.fn().mockResolvedValue({
        ok: false,
        status: 500,
        statusText: 'Server Error',
        text: async () => 'DB failed',
      });

      await expect(fetchCalls()).rejects.toThrow('Failed to load calls (500)');
    });
  });

  describe('fetchSupervisorToken', () => {
    it('requests supervisor token via POST /calls/{id}/supervisor-token', async () => {
      const mockTokenResponse = {
        call_id: 'call-123',
        room_name: 'call-call-123',
        supervisor_identity: 'supervisor-test',
        livekit_url: 'ws://localhost:7880',
        livekit_token: 'supervisor.jwt.token',
      };

      global.fetch = vi.fn().mockResolvedValue({
        ok: true,
        json: async () => mockTokenResponse,
      });

      const result = await fetchSupervisorToken('call-123', 'Lead Supervisor');
      expect(result).toEqual(mockTokenResponse);
      expect(global.fetch).toHaveBeenCalledWith(
        expect.stringMatching(/\/calls\/call-123\/supervisor-token$/),
        expect.objectContaining({
          method: 'POST',
          headers: {
            'Content-Type': 'application/json',
            'Accept': 'application/json',
          },
          body: JSON.stringify({
            supervisor_name: 'Lead Supervisor',
            supervisor_identity: undefined,
          }),
        })
      );
    });
  });

  describe('fetchSupervisorCallDetails', () => {
    it('explicitly queries include_private=true for supervisor inspection', async () => {
      const mockDetails = {
        id: 'call-123',
        status: 'ACTIVE',
        transcripts: [
          { speaker: 'customer', text: 'Discount?', is_private: false },
          { speaker: 'supervisor', text: 'Offer 10% discount', is_private: true },
        ],
      };

      global.fetch = vi.fn().mockResolvedValue({
        ok: true,
        json: async () => mockDetails,
      });

      const result = await fetchSupervisorCallDetails('call-123');
      expect(result).toEqual(mockDetails);
      expect(global.fetch).toHaveBeenCalledWith(
        expect.stringMatching(/\/calls\/call-123\?include_private=true$/),
        expect.objectContaining({
          headers: { 'Accept': 'application/json' },
        })
      );
    });
  });
});
