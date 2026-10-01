import React from 'react';
import { describe, it, expect, vi } from 'vitest';
import { render, screen, fireEvent } from '@testing-library/react';

import { StatusHeader } from '../components/StatusHeader';
import { ActiveCallsSelector } from '../components/ActiveCallsSelector';
import { AudioMonitor } from '../components/AudioMonitor';
import { WhisperConsole } from '../components/WhisperConsole';
import { LiveTranscriptView } from '../components/LiveTranscriptView';
import { ErrorBanner } from '../components/ErrorBanner';
import { SupervisorCallStatus } from '../hooks/useSupervisorCall';

describe('Supervisor Console Components', () => {
  describe('StatusHeader', () => {
    it('renders stealth eavesdrop badge and ready pill when IDLE', () => {
      render(
        <StatusHeader
          callStatus={SupervisorCallStatus.IDLE}
          callId={null}
          roomName={null}
          onDisconnect={vi.fn()}
        />
      );

      expect(screen.getByText(/Stealth Eavesdrop/i)).toBeDefined();
      expect(screen.getByText('READY')).toBeDefined();
    });

    it('renders LISTENING (STEALTH) and stop listening button when connected', () => {
      const handleDisconnect = vi.fn();
      render(
        <StatusHeader
          callStatus={SupervisorCallStatus.LISTENING}
          callId="12345678-abcd-1234-abcd-123456789abc"
          roomName="call-12345678"
          onDisconnect={handleDisconnect}
        />
      );

      expect(screen.getByText(/LISTENING \(STEALTH\)/i)).toBeDefined();
      expect(screen.getByText(/call-12345678/i)).toBeDefined();

      const stopBtn = screen.getByRole('button', { name: /Stop Listening/i });
      expect(stopBtn).toBeDefined();

      fireEvent.click(stopBtn);
      expect(handleDisconnect).toHaveBeenCalled();
    });
  });

  describe('ActiveCallsSelector', () => {
    const mockCalls = [
      { id: 'call-1', room_name: 'call-1', status: 'ACTIVE', created_at: '2026-09-30T10:00:00Z' },
      { id: 'call-2', room_name: 'call-2', status: 'CREATED', created_at: '2026-09-30T10:05:00Z' },
    ];

    it('renders call select dropdown and triggers connect with chosen call', () => {
      const handleConnect = vi.fn();
      render(
        <ActiveCallsSelector
          calls={mockCalls}
          selectedCallId="call-1"
          onSelectCallId={vi.fn()}
          onConnect={handleConnect}
          callStatus={SupervisorCallStatus.IDLE}
          loadingCalls={false}
          onRefreshCalls={vi.fn()}
        />
      );

      const joinBtn = screen.getByRole('button', { name: /Join & Listen Stealthily/i });
      expect(joinBtn).toBeDefined();

      fireEvent.click(joinBtn);
      expect(handleConnect).toHaveBeenCalledWith('call-1');
    });

    it('allows toggling to manual call ID input', () => {
      const handleSelect = vi.fn();
      render(
        <ActiveCallsSelector
          calls={mockCalls}
          selectedCallId="call-1"
          onSelectCallId={handleSelect}
          onConnect={vi.fn()}
          callStatus={SupervisorCallStatus.IDLE}
          loadingCalls={false}
          onRefreshCalls={vi.fn()}
        />
      );

      const select = screen.getByLabelText(/Select Ongoing Call/i);
      fireEvent.change(select, { target: { value: '__MANUAL__' } });

      expect(screen.getByPlaceholderText(/e\.g\. b0a769f3/i)).toBeDefined();
    });
  });

  describe('AudioMonitor', () => {
    it('renders customer and agent channels and indicates mic is blocked', () => {
      render(
        <AudioMonitor
          customerSpeaking={false}
          agentSpeaking={true}
          isListening={true}
        />
      );

      expect(screen.getByText(/Customer Stream/i)).toBeDefined();
      expect(screen.getByText(/Agent Stream/i)).toBeDefined();
      expect(screen.getByText(/Mic: Blocked \(Listen Only\)/i)).toBeDefined();
      expect(screen.getByText(/Zero audio leakage/i)).toBeDefined();
    });
  });

  describe('WhisperConsole', () => {
    it('dispatches whisper to agent when form is submitted', async () => {
      const handleSend = vi.fn().mockResolvedValue(true);
      render(
        <WhisperConsole
          onSendWhisper={handleSend}
          isListening={true}
          lastWhisperSent={null}
        />
      );

      const textarea = screen.getByPlaceholderText(/Type private coaching instruction/i);
      fireEvent.change(textarea, { target: { value: 'Offer a 10% discount.' } });

      const sendBtn = screen.getByRole('button', { name: /Whisper to Agent/i });
      fireEvent.click(sendBtn);

      expect(handleSend).toHaveBeenCalledWith('Offer a 10% discount.');
    });

    it('applies quick directive preset chip on click', () => {
      render(
        <WhisperConsole
          onSendWhisper={vi.fn()}
          isListening={true}
          lastWhisperSent={null}
        />
      );

      const chip = screen.getByRole('button', { name: /Offer a 10% discount\./i });
      fireEvent.click(chip);

      const textarea = screen.getByPlaceholderText(/Type private coaching instruction/i);
      expect(textarea.value).toBe('Offer a 10% discount.');
    });
  });

  describe('LiveTranscriptView', () => {
    it('distinguishes USER, AGENT, and SUPERVISOR WHISPER with private badge', () => {
      const mockTranscripts = [
        { id: '1', role: 'USER', text: 'Can I get a discount?', isPrivate: false, time: '+1.0s' },
        { id: '2', role: 'SUPERVISOR', text: 'Offer a 10% discount.', isPrivate: true, time: '+2.0s' },
        { id: '3', role: 'AGENT', text: 'I can offer you a 10% discount today.', isPrivate: false, time: '+3.5s' },
      ];

      render(<LiveTranscriptView transcripts={mockTranscripts} />);

      expect(screen.getByText('USER')).toBeDefined();
      expect(screen.getByText('AGENT')).toBeDefined();
      expect(screen.getByText('SUPERVISOR WHISPER')).toBeDefined();
      expect(screen.getByText(/Hidden from Customer/i)).toBeDefined();

      expect(screen.getByText(/Can I get a discount\?/i)).toBeDefined();
      expect(screen.getByText(/Offer a 10% discount\./i)).toBeDefined();
      expect(screen.getByText(/I can offer you a 10% discount today\./i)).toBeDefined();
    });
  });

  describe('ErrorBanner', () => {
    it('renders and dismisses error banner', () => {
      const handleDismiss = vi.fn();
      render(<ErrorBanner message="Test supervisor error" onDismiss={handleDismiss} />);

      expect(screen.getByRole('alert')).toBeDefined();
      expect(screen.getByText('Test supervisor error')).toBeDefined();

      fireEvent.click(screen.getByRole('button', { name: /Dismiss error/i }));
      expect(handleDismiss).toHaveBeenCalled();
    });
  });
});
