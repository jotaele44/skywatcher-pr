import React from 'react';
import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { afterEach, expect, it, vi } from 'vitest';
import CommandReferenceCard from './CommandReferenceCard';

afterEach(() => vi.unstubAllGlobals());

it('reports rejection and only confirms a successful clipboard retry', async () => {
  const writeText = vi.fn().mockRejectedValueOnce(new Error('Denied')).mockResolvedValueOnce(undefined);
  vi.stubGlobal('navigator', { clipboard: { writeText } });
  render(<CommandReferenceCard command="python3 evidence.py" />);
  fireEvent.click(screen.getByRole('button', { name: 'Copy' }));
  expect(await screen.findByRole('alert')).toHaveTextContent('Copy failed');
  expect(screen.queryByRole('button', { name: 'Copied' })).not.toBeInTheDocument();
  fireEvent.click(screen.getByRole('button', { name: 'Copy' }));
  await waitFor(() => expect(screen.getByRole('button', { name: 'Copied' })).toBeEnabled());
  expect(writeText).toHaveBeenLastCalledWith('python3 evidence.py');
  expect(screen.queryByRole('alert')).not.toBeInTheDocument();
});

it('keeps command text available when the clipboard API is absent', async () => {
  vi.stubGlobal('navigator', {});
  render(<CommandReferenceCard command="python3 evidence.py" />);
  fireEvent.click(screen.getByRole('button', { name: 'Copy' }));
  expect(await screen.findByRole('alert')).toHaveTextContent('Select the command text');
  expect(screen.getByText('python3 evidence.py')).toBeVisible();
});
