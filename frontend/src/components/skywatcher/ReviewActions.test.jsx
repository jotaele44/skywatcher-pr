import React from 'react';
import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { expect, it, vi } from 'vitest';
import ReviewActions from './ReviewActions';
it('exposes rejected writes, unlocks controls, and allows retry', async () => {
  const onChange = vi.fn().mockRejectedValueOnce(new Error('Write denied')).mockResolvedValueOnce({});
  render(<ReviewActions current="open" onChange={onChange} />);
  fireEvent.click(screen.getByRole('button', { name: 'Verify' }));
  expect(await screen.findByRole('alert')).toHaveTextContent('Write denied');
  expect(screen.getByRole('button', { name: 'Verify' })).not.toBeDisabled();
  fireEvent.click(screen.getByRole('button', { name: 'Verify' }));
  await waitFor(() => expect(onChange).toHaveBeenCalledTimes(2));
  await waitFor(() => expect(screen.queryByRole('alert')).toBeNull());
});
