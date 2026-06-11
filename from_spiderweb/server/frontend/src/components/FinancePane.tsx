import React from 'react';
import { useAppStore } from '../state/store';

interface Contract {
  id: string;
  vendor: string;
  amount: number;
  agency: string;
}

// Temporary mock data for the finance module. Replace this with
// data loaded from the backend or database when available.
const mockContracts: Contract[] = [
  { id: 'C1', vendor: 'ACME Corp', amount: 100000, agency: 'PR Agency X' },
  { id: 'C2', vendor: 'Globex Inc', amount: 250000, agency: 'PR Agency Y' },
];

/**
 * FinancePane displays a simple table of contracts and updates the
 * global selection state when a row is clicked. In a future
 * implementation this component should use a table library like
 * TanStack Table and load data from the backend API.
 */
export const FinancePane: React.FC = () => {
  const setSelection = useAppStore((s) => s.setSelection);

  return (
    <div>
      <h2>Finance Intelligence</h2>
      <table>
        <thead>
          <tr>
            <th>ID</th>
            <th>Vendor</th>
            <th>Amount</th>
            <th>Agency</th>
          </tr>
        </thead>
        <tbody>
          {mockContracts.map((c) => (
            <tr key={c.id} onClick={() => setSelection(c)} style={{ cursor: 'pointer' }}>
              <td>{c.id}</td>
              <td>{c.vendor}</td>
              <td>${c.amount.toLocaleString()}</td>
              <td>{c.agency}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
};