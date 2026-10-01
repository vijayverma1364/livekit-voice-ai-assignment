/**
 * API Service for Backend Control Plane Communication.
 * Handles agent discovery, call initialization, and call transcript fetching.
 * Zero server secrets or database credentials are exposed here.
 */

const API_BASE_URL = import.meta.env.VITE_API_URL || 'http://localhost:8000';

/**
 * Fetches the list of active Voice AI agents configured in PostgreSQL.
 * @returns {Promise<Array<{id: string, name: string, voice: string, model: string, system_prompt: string}>>}
 */
export async function fetchAgents() {
  const response = await fetch(`${API_BASE_URL}/agents`, {
    headers: { 'Accept': 'application/json' },
  });
  if (!response.ok) {
    const errorText = await response.text();
    throw new Error(`Failed to load agents (${response.status}): ${errorText || response.statusText}`);
  }
  return response.json();
}

/**
 * Initiates a new voice call session with the chosen agent.
 * Pre-creates the room on LiveKit and returns customer access credentials.
 * @param {string} agentId - UUID of the chosen Agent.
 * @param {string} [customerName] - Optional display name.
 * @param {string} [customerIdentity] - Optional unique participant ID.
 * @returns {Promise<{call_id: string, agent_id: string, room_name: string, status: string, livekit_url: string, livekit_token: string}>}
 */
export async function createCall(agentId, customerName = 'Customer', customerIdentity = '') {
  const payload = {
    agent_id: agentId,
    customer_name: customerName,
    customer_identity: customerIdentity || undefined,
  };

  const response = await fetch(`${API_BASE_URL}/calls`, {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
      'Accept': 'application/json',
    },
    body: JSON.stringify(payload),
  });

  if (!response.ok) {
    const errData = await response.json().catch(() => ({}));
    throw new Error(errData.detail || `Failed to initiate call (${response.status})`);
  }

  return response.json();
}

/**
 * Retrieves persisted call session details and transcripts.
 * Defaults to include_private=false to guarantee supervisor whispers are never retrieved.
 * @param {string} callId - UUID of the active or completed Call.
 * @returns {Promise<{id: string, status: string, transcripts: Array<{speaker: string, text: string, relative_time_ms: number}>}>}
 */
export async function fetchCallDetails(callId) {
  const response = await fetch(`${API_BASE_URL}/calls/${callId}?include_private=false`, {
    headers: { 'Accept': 'application/json' },
  });

  if (!response.ok) {
    throw new Error(`Failed to fetch call details (${response.status})`);
  }

  return response.json();
}
