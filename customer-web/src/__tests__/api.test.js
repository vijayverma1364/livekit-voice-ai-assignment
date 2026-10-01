import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { fetchAgents, createCall, fetchCallDetails } from '../services/api';

describe('Customer Web API Service', () => {
  const originalFetch = global.fetch;

  beforeEach(() => {
    vi.restoreAllMocks();
  });

  afterEach(() => {
    global.fetch = originalFetch;
  });

  describe('fetchAgents', () => {
    it('fetches agents list successfully', async () => {
      const mockAgents = [
        { id: '1', name: 'Acme Support Agent', voice: 'alloy', model: 'gpt-4o-mini' },
      ];

      global.fetch = vi.fn().mockResolvedValue({
        ok: true,
        json: async () => mockAgents,
      });

      const result = await fetchAgents();
      expect(result).toEqual(mockAgents);
      expect(global.fetch).toHaveBeenCalledWith(
        expect.stringMatching(/\/agents$/),
        expect.objectContaining({
          headers: { 'Accept': 'application/json' },
        })
      );
    });

    it('throws error when response is not ok', async () => {
      global.fetch = vi.fn().mockResolvedValue({
        ok: false,
        status: 500,
        statusText: 'Internal Server Error',
        text: async () => 'Database offline',
      });

      await expect(fetchAgents()).rejects.toThrow('Failed to load agents (500)');
    });
  });

  describe('createCall', () => {
    it('sends POST /calls with agent_id and customer_name and returns credentials', async () => {
      const mockResponse = {
        call_id: 'call-uuid-1234',
        agent_id: 'agent-uuid-5678',
        room_name: 'call-call-uuid-1234',
        status: 'CREATED',
        livekit_url: 'ws://localhost:7880',
        livekit_token: 'valid.jwt.token',
      };

      global.fetch = vi.fn().mockResolvedValue({
        ok: true,
        json: async () => mockResponse,
      });

      const result = await createCall('agent-uuid-5678', 'Alice Doe');
      expect(result).toEqual(mockResponse);
      expect(global.fetch).toHaveBeenCalledWith(
        expect.stringMatching(/\/calls$/),
        expect.objectContaining({
          method: 'POST',
          headers: {
            'Content-Type': 'application/json',
            'Accept': 'application/json',
          },
          body: JSON.stringify({
            agent_id: 'agent-uuid-5678',
            customer_name: 'Alice Doe',
            customer_identity: undefined,
          }),
        })
      );
    });

    it('throws error when POST /calls returns 400/404/500', async () => {
      global.fetch = vi.fn().mockResolvedValue({
        ok: false,
        status: 404,
        json: async () => ({ detail: 'Agent not found' }),
      });

      await expect(createCall('bad-id')).rejects.toThrow('Agent not found');
    });
  });

  describe('fetchCallDetails', () => {
    it('always requests include_private=false to guarantee supervisor confidentiality', async () => {
      const mockDetails = {
        id: 'call-123',
        status: 'ACTIVE',
        transcripts: [
          { speaker: 'agent', text: 'Hello!', relative_time_ms: 500, is_private: false },
          { speaker: 'customer', text: 'Hi', relative_time_ms: 1200, is_private: false },
        ],
      };

      global.fetch = vi.fn().mockResolvedValue({
        ok: true,
        json: async () => mockDetails,
      });

      const result = await fetchCallDetails('call-123');
      expect(result).toEqual(mockDetails);
      expect(global.fetch).toHaveBeenCalledWith(
        expect.stringMatching(/\/calls\/call-123\?include_private=false$/),
        expect.objectContaining({
          headers: { 'Accept': 'application/json' },
        })
      );
    });
  });
});
