import React from 'react';
import { describe, it, expect, vi } from 'vitest';
import { render, screen, fireEvent } from '@testing-library/react';

import { AgentSelector } from '../components/AgentSelector';
import { StatusHeader } from '../components/StatusHeader';
import { CallControls } from '../components/CallControls';
import { TranscriptView } from '../components/TranscriptView';
import { ErrorBanner } from '../components/ErrorBanner';
import { CallStatus } from '../hooks/useLiveKitCall';

describe('Customer Web UI Components', () => {
  describe('AgentSelector', () => {
    const mockAgents = [
      { id: 'agent-1', name: 'Acme Support Agent', model: 'gpt-4o-mini', voice: 'alloy' },
      { id: 'agent-2', name: 'Billing Agent', model: 'gpt-4o', voice: 'nova' },
    ];

    it('renders loading state when agents list is empty', () => {
      render(<AgentSelector agents={[]} selectedAgentId="" onSelect={vi.fn()} disabled={false} />);
      expect(screen.getByText(/Loading available agents.../i)).toBeDefined();
    });

    it('renders agent options and handles selection change', () => {
      const handleSelect = vi.fn();
      render(
        <AgentSelector
          agents={mockAgents}
          selectedAgentId="agent-1"
          onSelect={handleSelect}
          disabled={false}
        />
      );

      const select = screen.getByLabelText(/Select Voice AI Agent/i);
      expect(select).toBeDefined();
      expect(screen.getByText(/2 Available/i)).toBeDefined();

      fireEvent.change(select, { target: { value: 'agent-2' } });
      expect(handleSelect).toHaveBeenCalledWith('agent-2');
    });

    it('disables select input when disabled prop is true', () => {
      render(
        <AgentSelector
          agents={mockAgents}
          selectedAgentId="agent-1"
          onSelect={vi.fn()}
          disabled={true}
        />
      );
      const select = screen.getByLabelText(/Select Voice AI Agent/i);
      expect(select.disabled).toBe(true);
    });
  });

  describe('StatusHeader', () => {
    it('displays READY badge when IDLE', () => {
      render(<StatusHeader callStatus={CallStatus.IDLE} callId={null} roomName={null} />);
      expect(screen.getByText('READY')).toBeDefined();
    });

    it('displays LIVE CALL and call ID when CONNECTED', () => {
      render(
        <StatusHeader
          callStatus={CallStatus.CONNECTED}
          callId="12345678-abcd-ef01-2345-6789abcdef01"
          roomName="call-12345678"
        />
      );
      expect(screen.getByText(/LIVE CALL/i)).toBeDefined();
      expect(screen.getByText(/call-12345678/i)).toBeDefined();
      expect(screen.getByTitle(/Click to copy Call ID/i)).toBeDefined();
    });

    it('displays CONNECTING when initializing', () => {
      render(<StatusHeader callStatus={CallStatus.CONNECTING} callId="123" roomName="call-123" />);
      expect(screen.getByText(/CONNECTING/i)).toBeDefined();
    });

    it('displays CALL ENDED when call finishes', () => {
      render(<StatusHeader callStatus={CallStatus.ENDED} callId="123" roomName="call-123" />);
      expect(screen.getByText(/CALL ENDED/i)).toBeDefined();
    });

    it('displays ERROR when call errors', () => {
      render(<StatusHeader callStatus={CallStatus.ERROR} callId="123" roomName="call-123" />);
      expect(screen.getByText(/ERROR/i)).toBeDefined();
    });
  });

  describe('CallControls', () => {
    it('renders Start Voice Call button in IDLE state', () => {
      const handleStart = vi.fn();
      render(
        <CallControls
          callStatus={CallStatus.IDLE}
          onStartCall={handleStart}
          onEndCall={vi.fn()}
          onToggleMute={vi.fn()}
          isMuted={false}
          micEnabled={false}
          disabled={false}
        />
      );

      const startBtn = screen.getByRole('button', { name: /Start Voice Call/i });
      expect(startBtn).toBeDefined();
      expect(screen.getByText(/Mic: Standby/i)).toBeDefined();

      fireEvent.click(startBtn);
      expect(handleStart).toHaveBeenCalled();
    });

    it('renders End Call and Mute buttons when CONNECTED', () => {
      const handleEnd = vi.fn();
      const handleMute = vi.fn();
      render(
        <CallControls
          callStatus={CallStatus.CONNECTED}
          onStartCall={vi.fn()}
          onEndCall={handleEnd}
          onToggleMute={handleMute}
          isMuted={false}
          micEnabled={true}
          disabled={false}
        />
      );

      const endBtn = screen.getByRole('button', { name: /End Call/i });
      const muteBtn = screen.getByRole('button', { name: /Mute Mic/i });
      expect(endBtn).toBeDefined();
      expect(muteBtn).toBeDefined();
      expect(screen.getByText(/Mic: Live & Transmitting/i)).toBeDefined();

      fireEvent.click(muteBtn);
      expect(handleMute).toHaveBeenCalled();

      fireEvent.click(endBtn);
      expect(handleEnd).toHaveBeenCalled();
    });

    it('displays Unmute Mic and Muted indicator when isMuted is true', () => {
      render(
        <CallControls
          callStatus={CallStatus.CONNECTED}
          onStartCall={vi.fn()}
          onEndCall={vi.fn()}
          onToggleMute={vi.fn()}
          isMuted={true}
          micEnabled={false}
          disabled={false}
        />
      );

      expect(screen.getByRole('button', { name: /Unmute Mic/i })).toBeDefined();
      expect(screen.getByText(/Mic: Muted/i)).toBeDefined();
    });
  });

  describe('TranscriptView', () => {
    it('renders empty state when no transcripts exist', () => {
      render(<TranscriptView transcripts={[]} />);
      expect(screen.getByText(/No conversation turns yet/i)).toBeDefined();
      expect(screen.getByText(/0 Turns/i)).toBeDefined();
    });

    it('strictly renders USER or AGENT speaker tags for every visible turn', () => {
      const mockTranscripts = [
        { id: '1', role: 'USER', text: 'Hello, I need assistance with my order.', time: '10:00:01' },
        { id: '2', role: 'AGENT', text: 'Thank you for calling Acme Support. Please note that this call is recorded.', time: '10:00:03' },
        { id: '3', role: 'USER', text: 'Can I get a refund?', time: '10:00:10' },
        { id: '4', role: 'AGENT', text: 'I cannot issue refunds directly. Please email support@acme.com.', time: '10:00:13' },
      ];

      render(<TranscriptView transcripts={mockTranscripts} />);

      expect(screen.getByText(/4 Turns/i)).toBeDefined();

      // Check that all USER tags appear
      const userTags = screen.getAllByText('USER');
      expect(userTags.length).toBe(2);

      // Check that all AGENT tags appear
      const agentTags = screen.getAllByText('AGENT');
      expect(agentTags.length).toBe(2);

      // Verify turn texts
      expect(screen.getByText(/Hello, I need assistance with my order./i)).toBeDefined();
      expect(screen.getByText(/Thank you for calling Acme Support/i)).toBeDefined();
      expect(screen.getByText(/Can I get a refund\?/i)).toBeDefined();
      expect(screen.getByText(/support@acme.com/i)).toBeDefined();

      // Verify that supervisor tags never appear
      expect(screen.queryByText(/SUPERVISOR/i)).toBeNull();
      expect(screen.queryByText(/WHISPER/i)).toBeNull();
    });
  });

  describe('ErrorBanner', () => {
    it('returns null when message is empty', () => {
      const { container } = render(<ErrorBanner message={null} onDismiss={vi.fn()} />);
      expect(container.firstChild).toBeNull();
    });

    it('renders error message and dismisses on click', () => {
      const handleDismiss = vi.fn();
      render(<ErrorBanner message="Test connection error" onDismiss={handleDismiss} />);

      expect(screen.getByRole('alert')).toBeDefined();
      expect(screen.getByText(/Test connection error/i)).toBeDefined();

      const dismissBtn = screen.getByRole('button', { name: /Dismiss error/i });
      fireEvent.click(dismissBtn);
      expect(handleDismiss).toHaveBeenCalled();
    });
  });
});
